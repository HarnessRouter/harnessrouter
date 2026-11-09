"""ReMe (agentscope-ai/ReMe, Apache-2.0) as a memory provider: memory as files.

ReMe keeps memory as ordinary Markdown with frontmatter and wikilinks, indexed for search. Every shape
here was read off a server running on 2026-11-04.

  one memory = one folder, digest/<memory id>/. ReMe indexes only `daily` and `digest`, about six seconds
      after a write, and its search has no folder scope: every hit is checked against the folder here, so
      a search of one memory can't return another's. `enforced_filter`, and the file server is shared.
  a record = one file, <record id>.md, in a subfolder when its attributes name one (`attributes.folder`),
      which is what the console's tree shows. Frontmatter carries the protocol's fields, and a record's
      references are also written as wikilinks, so ReMe's own graph and search expansion see them.
  remember = POST /save, verbatim. Search finds it once indexed; until then the last writes are matched
      here, so an agent can read back what it just wrote.
  observe  = the turn as an episode file, then POST /auto_memory: ReMe's agent writes a note about it into
      the shared `daily` folder, which is moved at once into this memory's folder. `derivation: agent`.
  recall   = POST /search. Words (BM25) by default; with embeddings configured on the server it's hybrid.
      The server's health says which and the capability document follows it, and a `query` is reported
      `degraded` whenever a search's own counts show it ran on words.
  revise   = the file rewritten. ReMe keeps no versions, so the earlier ones are kept beside it under
      .history/, which nothing indexes: `emulated`, and said in the capability document.
  forget   = frontmatter `hr_status: forgotten`, checked on every read. erase = the file, its history and
      its source conversation, so nothing is unreachable.
  schema   = none. The folders, the frontmatter and the links are the structure, and nothing in ReMe reads
      a type.
  consolidate = none. ReMe's own auto_dream merges the shared daily folder across the whole workspace, which
      would mix memories that are kept apart here, so it isn't offered.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import time
import uuid

import httpx

import memory_plane as mp

TIMEOUT_S = 120
ROOT = "digest"
HISTORY = ".history"
LINKS = "<!-- hr:links -->"
RECENT_S = 20
SEARCH_WIDTH = 100
# Tests set an httpx transport here so every call is exercised without a server.
transport: httpx.BaseTransport | None = None
# Every other call opens its connections through the gateway's checked network (app.py sets this), so an address
# that passed the check when it was saved and later resolves somewhere internal (a DNS rebind) is refused at connect.
checked_transport = None


def _transport():
    return transport if transport is not None else (checked_transport() if checked_transport else None)
_SAFE = re.compile(r"[^A-Za-z0-9 _.-]+")
_MEANING: dict[str, tuple[float, bool]] = {}


class ReMeUnavailable(mp.MemoryError):
    def __init__(self, why: str):
        super().__init__(502, "memory_unavailable", f"ReMe did not answer: {why}"[:300])


async def check(api_key: str, base_url: str = "") -> str:
    """'' when a ReMe server answers at this address, else why not, in a sentence."""
    if not base_url:
        return "ReMe needs the address of your server."
    try:
        async with httpx.AsyncClient(timeout=20, transport=_transport()) as c:
            r = await c.post(base_url.rstrip("/") + "/version", json={}, headers={"Authorization": f"Bearer {api_key}"} if api_key else {})
    except httpx.HTTPError as e:
        return f"ReMe could not be reached at that address: {type(e).__name__}."
    return "" if r.status_code == 200 else f"ReMe refused the connection (HTTP {r.status_code})."


def _now() -> str:
    d = _dt.datetime.now(_dt.timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def _folder(attrs: dict) -> str:
    """A record's folder from its attributes: plain names only, so it stays inside the memory."""
    parts = [_SAFE.sub("", p).strip(" .") for p in str((attrs or {}).get("folder") or "").split("/")]
    return "/".join(p for p in parts if p)


class ReMe(mp.Provider):
    id = "reme"
    # A finished task is kept as a note of its own (episodes/<id>.md), one a person reads and edits: it is what ReMe kept,
    # so a turn counts it (app.py's _derived_records). Other engines' episodes are the input, and what they drew counts.
    episode_is_kept = True

    def __init__(self, base_url: str = "", api_key: str = "", by_meaning: bool = False):
        self.base, self.key, self.by_meaning = base_url.rstrip("/"), api_key, by_meaning
        self._recent: dict[str, list[tuple[float, str]]] = {}

# What ReMe itself makes and how it links it: the part of a memory's schema nobody sets. The console draws it locked
# beside what a person can set; record types and reference rels as this adapter answers them.
    BUILTIN = {
        "types": [
            {"name": "episode", "description": "A conversation ReMe was given, kept as a file."},
            {"name": "note", "description": "What ReMe's own agent wrote down about a conversation."},
        ],
        "relations": [
            {"name": "derived_from", "from": "note", "to": "episode", "description": "The conversation the note is about."},
        ],
    }

    def capabilities(self) -> dict:
        return {"id": self.id, "isolation": "enforced_filter", "derivation": "agent", "layout": "files",
                "observe": {"keeps_episodes": True, "answers": "records"},
                "recall": {"signals": ["query", "text", "filters"] if self.by_meaning else ["text", "filters"], "abstain": False,
                           "filters": {"native": [], "applied_after_ranking": "every filter"}},
                "history": {"content": "versions", "structure": "none", "emulated": True}, "as_of": "one record",
                "revise": "native", "forget": "emulated", "erase": {"unreachable": "none"},
                "prime": True, "consolidate": False, "holds": True, "queries": {"named": False, "free": None},
                "types": False, "graph": {"entities": "stated"}, "schema": {"mode": "none", "builtin": self.BUILTIN},
                "content": {"media": ["text/*"], "describes": []}}

    async def bind(self, org, workspace):
        fields = await mp.CREDENTIALS(org, workspace, self.id) if mp.CREDENTIALS else None
        base = str((fields or {}).get("base_url") or "").strip().rstrip("/")
        if not base:
            raise mp.MemoryError(503, "memory_unavailable", "ReMe is not connected for this workspace: connect it with your server's address.")
        bound = ReMe(base, str((fields or {}).get("api_key") or ""))
        bound.by_meaning = await bound._searches_by_meaning()
        return bound

    async def _searches_by_meaning(self) -> bool:
        """ReMe's embeddings are off unless its config turns them on, so this server's answer decides what
        is declared. Read at most once a minute: `bind` runs on every call."""
        hit = _MEANING.get(self.base)
        if hit and time.time() - hit[0] < 60:
            return hit[1]
        try:
            d = await self._call("health_check", timeout=10)
        except mp.MemoryError:
            return hit[1] if hit else False
        on = bool((((d.get("metadata") or {}).get("health") or {}).get("components") or {}).get("embedding_store"))
        _MEANING[self.base] = (time.time(), on)
        return on

    # ── the wire: every route is a POST that answers {answer, success, metadata} ──────────────
    async def _call(self, route: str, body: dict | None = None, timeout: float = TIMEOUT_S) -> dict:
        headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
        try:
            async with httpx.AsyncClient(timeout=timeout, transport=_transport()) as c:
                r = await c.post(self.base + "/" + route, json=body or {}, headers=headers)
        except httpx.HTTPError as e:
            raise ReMeUnavailable(type(e).__name__)
        if r.status_code in (401, 403):
            raise mp.MemoryError(503, "memory_unavailable", "ReMe refused this workspace's key: reconnect it.")
        if r.status_code != 200:
            raise ReMeUnavailable(f"HTTP {r.status_code}")
        return r.json() or {}

    @staticmethod
    def _dir(mid: str) -> str:
        return f"{ROOT}/{mid}"

    async def _files(self, mid: str) -> list[str]:
        d = await self._call("list", {"path": self._dir(mid), "recursive": True, "extensions": ["md"], "limit": 2000})
        return [p for p in ((d.get("metadata") or {}).get("items") or []) if f"/{HISTORY}/" not in p]

    async def _path_of(self, mid: str, rid: str) -> str | None:
        if not re.fullmatch(r"hrec_[0-9a-f]{32}", rid or ""):
            return None
        for p in await self._files(mid):
            if p.rsplit("/", 1)[-1] == f"{rid}.md":
                return p
        return None

    # ── one shape in, one shape out ───────────────────────────────────────────────────────────
    @staticmethod
    def _front(rid: str, record: dict, writer: dict, version: int, status: str = "active") -> dict:
        title = str(record.get("title") or "")
        said = mp.text_of(record.get("content") or [])
        t = record.get("time") or {}
        f = {"name": (title or said[:80] or rid), "description": said[:200].replace("\n", " ") or title or rid, "hr_id": rid,
             "hr_type": record.get("type") or "note", "hr_version": version, "hr_status": status, "hr_written_at": _now(),
             "hr_writer": {k: v for k, v in (writer or {}).items() if v}}
        if title:
            f["hr_title"] = title
        if record.get("attributes"):
            f["hr_attributes"] = record["attributes"]
        if record.get("references"):
            f["hr_refs"] = record["references"]
        for k in ("valid_from", "valid_to"):
            if t.get(k):
                f["hr_" + k] = t[k]
        return f

    @staticmethod
    def _text(front: dict, body: str, refs_at: dict[str, str] | None = None) -> str:
        head = "\n".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in front.items())
        links = [p for p in (refs_at or {}).values()]
        tail = "\n\n" + LINKS + "\n" + "\n".join(f"- [[{p}]]" for p in links) + "\n" if links else "\n"
        return f"---\n{head}\n---\n\n{body}{tail}"

    @staticmethod
    def _body(raw: str) -> str:
        text = raw or ""
        if text.startswith("---"):
            end = text.find("\n---", 3)
            if end >= 0:
                text = text[end + 4:]
        return text.split(LINKS, 1)[0].strip()

    async def _read(self, path: str) -> dict | None:
        st = await self._call("stat", {"path": path})
        meta = st.get("metadata") or {}
        if not meta.get("exists"):
            return None
        raw = await self._call("load", {"path": path})
        return self._out(path, meta.get("frontmatter") or {}, self._body(str(raw.get("answer") or "")), meta.get("mtime"))

    @staticmethod
    def _out(path: str, f: dict, body: str, mtime=None) -> dict:
        rid = path.rsplit("/", 1)[-1][:-3]
        attrs = f.get("hr_attributes") if isinstance(f.get("hr_attributes"), dict) else {}
        if "hr_id" not in f:                # a note ReMe's agent wrote, before it was claimed
            attrs = {**attrs, **({"memory_tags": f["memory_tags"]} if f.get("memory_tags") else {})}
        status = str(f.get("hr_status") or "active")
        version = int(f.get("hr_version") or 1)
        written = f.get("hr_written_at") or (str(mtime) + "Z" if mtime else None)
        writer = f.get("hr_writer") if isinstance(f.get("hr_writer"), dict) else {"kind": "provider", "id": "reme"}
        return {"id": rid, "type": str(f.get("hr_type") or "note"), "title": str(f.get("hr_title") or (f.get("name") if "hr_id" not in f else "") or ""),
                "content": [{"type": "text", "text": body}] if body else [], "attributes": attrs,
                "references": f.get("hr_refs") if isinstance(f.get("hr_refs"), list) else [], "version": version, "status": status,
                "supersedes": version - 1 if version > 1 else None,
                "time": {"valid_from": f.get("hr_valid_from"), "valid_to": f.get("hr_valid_to"), "written_at": written,
                         "invalidated_at": written if status != "active" else None},
                "written_by": writer}

    async def _refs_at(self, mid: str, refs: list) -> dict[str, str]:
        out: dict[str, str] = {}
        for x in refs or []:
            if str(x.get("memory_id") or mid) == mid and x.get("record_id"):
                p = await self._path_of(mid, str(x["record_id"]))
                if p:
                    out[str(x["record_id"])] = p
        return out

    def _touched(self, mid: str, path: str) -> None:
        now = time.time()
        self._recent[mid] = [x for x in self._recent.get(mid, []) if now - x[0] < RECENT_S and x[1] != path] + [(now, path)]

    async def _save(self, mid: str, path: str, front: dict, body: str, refs: list | None) -> None:
        d = await self._call("save", {"path": path, "content": self._text(front, body, await self._refs_at(mid, refs or []))})
        if not d.get("success"):
            raise ReMeUnavailable("the file was not saved")
        self._touched(mid, path)

    # ── lifecycle ─────────────────────────────────────────────────────────────────────────────
    async def create(self, mid, memory):
        await self._call("save", {"path": f"{self._dir(mid)}/{HISTORY}/created.txt", "content": str(memory.get("name") or mid)})

    async def drop(self, mid):
        await self._call("delete", {"path": self._dir(mid)})
        self._recent.pop(mid, None)

    async def count(self, mid):
        return len(await self._files(mid))

    # ── writes ────────────────────────────────────────────────────────────────────────────────
    async def remember(self, mid, record, writer):
        rid = "hrec_" + uuid.uuid4().hex
        folder = _folder(record.get("attributes") or {})
        path = "/".join(x for x in (self._dir(mid), folder, f"{rid}.md") if x)
        body = mp.text_of(record.get("content") or [])
        front = self._front(rid, record, writer, 1)
        await self._save(mid, path, front, body, record.get("references"))
        return self._out(path, front, body)

    async def observe(self, mid, episodes, writer):
        records = []
        for e in episodes:
            rid = "hrec_" + uuid.uuid4().hex
            parts = [p for p in e.get("content") or [] if p.get("text")]
            body = "\n\n".join(f"{p.get('role')}: {p['text']}" if p.get("role") else str(p["text"]) for p in parts)
            on_behalf = {"kind": "provider", "id": self.id, "on_behalf_of": f"{writer.get('kind')}:{writer.get('id')}"}
            front = self._front(rid, {"type": "episode", "attributes": e.get("attributes") or {}, "content": [{"type": "text", "text": body}]}, on_behalf, 1)
            path = f"{self._dir(mid)}/episodes/{rid}.md"
            await self._save(mid, path, front, body, None)
            records.append(self._out(path, front, body))
            note = await self._note_from(mid, rid, parts, on_behalf)
            if note:
                records.append(note)
        return {"records": records, "job": None}

    async def _note_from(self, mid: str, rid: str, parts: list[dict], writer: dict) -> dict | None:
        """ReMe's agent writes a note about the turn into the shared `daily` folder. It is moved into this
        memory's folder before anything else can read it there. A failure here costs the note, not the episode."""
        msgs = [{"name": str(p.get("role") or "user"), "role": p.get("role") if p.get("role") in ("user", "assistant", "system") else "user", "content": p["text"]} for p in parts]
        try:
            d = await self._call("auto_memory", {"messages": msgs, "session_id": f"{mid}_{rid}"})
        except mp.MemoryError:
            return None
        made = str((d.get("metadata") or {}).get("path") or "")
        if not d.get("success") or not made:
            return None
        note_id = "hrec_" + uuid.uuid4().hex
        dst = f"{self._dir(mid)}/notes/{note_id}.md"
        moved = await self._call("move", {"src_path": made, "dst_path": dst, "retarget": False})
        if not moved.get("success"):
            await self._call("delete", {"path": made})
            return None
        await self._call("frontmatter_update", {"path": dst, "metadata": {
            "hr_id": note_id, "hr_type": "note", "hr_version": 1, "hr_status": "active", "hr_written_at": _now(), "hr_writer": writer,
            "hr_refs": [{"rel": "derived_from", "memory_id": mid, "record_id": rid}]}})
        self._touched(mid, dst)
        return await self._read(dst)

    async def _keep_version(self, mid: str, rid: str, cur: dict) -> None:
        kept = await self._kept(mid, rid)
        kept.append(cur)
        await self._call("save", {"path": f"{self._dir(mid)}/{HISTORY}/{rid}.json", "content": json.dumps(kept)})

    async def _kept(self, mid: str, rid: str) -> list[dict]:
        d = await self._call("load", {"path": f"{self._dir(mid)}/{HISTORY}/{rid}.json"})
        try:
            kept = json.loads(str(d.get("answer") or "[]")) if d.get("success") else []
        except ValueError:
            kept = []
        return kept if isinstance(kept, list) else []

    async def revise(self, mid, rid, patch, writer):
        path = await self._path_of(mid, rid)
        cur = await self._read(path) if path else None
        if not cur or cur["status"] != "active":
            raise mp.MemoryError(404, "memory_record_not_found", "No such record in this memory.", "record_id")
        await self._keep_version(mid, rid, cur)
        merged = {"type": cur["type"], "title": patch.get("title", cur["title"]), "content": patch.get("content", cur["content"]),
                  "attributes": {**cur["attributes"], **(patch.get("attributes") or {})}, "references": patch.get("references", cur["references"]),
                  "time": {**{k: cur["time"][k] for k in ("valid_from", "valid_to")}, **(patch.get("time") or {})}}
        version = cur["version"] + 1
        front = self._front(rid, merged, writer, version)
        body = mp.text_of(merged["content"])
        folder = _folder(merged["attributes"])
        new_path = "/".join(x for x in (self._dir(mid), folder, f"{rid}.md") if x)
        if new_path != path:
            await self._call("move", {"src_path": path, "dst_path": new_path})
        await self._save(mid, new_path, front, body, merged["references"])
        return {**self._out(new_path, front, body), "supersedes": cur["version"]}

    async def forget(self, mid, rid, writer):
        path = await self._path_of(mid, rid)
        cur = await self._read(path) if path else None
        if not cur or cur["status"] != "active":
            raise mp.MemoryError(404, "memory_record_not_found", "No such record in this memory.", "record_id")
        await self._call("frontmatter_update", {"path": path, "metadata": {
            "hr_status": "forgotten", "hr_forgotten_by": f"{writer.get('kind')}:{writer.get('id')}", "hr_written_at": _now()}})
        return await self._read(path)

    async def erase(self, mid, rids):
        erased = []
        for rid in rids:
            path = await self._path_of(mid, rid)
            if not path:
                continue
            d = await self._call("delete", {"path": path})
            if d.get("success"):
                erased.append(rid)
                await self._call("delete", {"path": f"{self._dir(mid)}/{HISTORY}/{rid}.json"})
                await self._call("delete", {"path": f"session/dialog/{mid}_{rid}.jsonl"})
        return {"erased": erased, "unreachable": []}

    # ── reads ─────────────────────────────────────────────────────────────────────────────────
    async def get(self, mid, rid, as_of=None):
        path = await self._path_of(mid, rid)
        if not path:
            return None
        if as_of:
            past = [v for v in await self.history(mid, rid) if str(v["time"]["written_at"] or "") <= as_of]
            return {**past[-1], "status": "active"} if past else None
        return await self._read(path)

    async def history(self, mid, rid):
        head = await self.get(mid, rid)
        if not head:
            raise mp.MemoryError(404, "memory_record_not_found", "No such record in this memory.", "record_id")
        kept = await self._kept(mid, rid)
        out = []
        for i, v in enumerate(kept):
            until = kept[i + 1]["time"]["written_at"] if i + 1 < len(kept) else head["time"]["written_at"]
            out.append({**v, "status": "superseded", "time": {**v["time"], "invalidated_at": until}})
        return [*out, head]

    async def _rows(self, mid: str, include_all: bool = False) -> list[dict]:
        rows = []
        for p in await self._files(mid):
            x = await self._read(p)
            if x and (include_all or x["status"] == "active"):
                rows.append(x)
        rows.sort(key=lambda x: str(x["time"]["written_at"] or ""), reverse=True)
        return rows

    async def prime(self, mid, budget):
        rows = [x for x in await self._rows(mid) if x["attributes"].get("standing") is True]
        return mp.within_budget(rows, budget)

    async def list(self, mid, req):
        if req.get("as_of"):
            raise mp.MemoryError(422, "memory_unsupported", "This memory's provider does not list a memory as of a past time.")
        types = [t for t in (req.get("types") or []) if t]
        rows = [x for x in await self._rows(mid, req.get("include") == "all") if not types or x["type"] in types]
        at, size = int(req.get("cursor") or 0), int(req.get("limit") or 50)
        return {"records": rows[at:at + size], "next": str(at + size) if at + size < len(rows) else None}

    async def recall(self, mid, req):
        degraded: list[str] = []
        if req.get("as_of"):
            degraded.append("as_of:not_supported")
        query, text = str(req.get("query") or "").strip(), str(req.get("text") or "").strip()
        limit = int(req.get("limit") or 8)
        types = [t for t in (req.get("types") or []) if t]
        later = [req["filters"]] if req.get("filters") else []
        if later:
            degraded.append("filters:applied_after_ranking")

        def keep(x: dict) -> bool:
            return x["status"] == "active" and (not types or x["type"] in types) and all(mp.matches(x, f) for f in later)
        if not query and not text:
            rows = [x for x in await self._rows(mid) if keep(x)]
            return {"results": [{"record": x, "memory_id": mid, "score": 1.0, "why": ["filters"]} for x in rows[:limit]], "degraded": degraded, "abstain": False}
        asked = f"{query} {text}".strip()
        d = await self._call("search", {"query": asked, "limit": max(limit * 5, SEARCH_WIDTH)})
        meta = d.get("metadata") or {}
        # its `hybrid` count is false when only vectors matched, so that isn't what says words. A server with
        # embeddings that found words and no vectors had them fail for this search.
        n = meta.get("counts") or {}
        if query and not n.get("vector") and (n.get("keyword") or not self.by_meaning):
            degraded.append("query:searched_as_words")
        prefix = self._dir(mid) + "/"
        results, seen = [], set()
        for hit in meta.get("results") or []:
            p = str(hit.get("path") or "")
            if not p.startswith(prefix) or f"/{HISTORY}/" in p or p in seen:
                continue                     # another memory's file: the server's search has no folder scope
            seen.add(p)
            x = await self._read(p)
            if x and keep(x):
                scores = hit.get("scores") or {}
                results.append({"record": x, "memory_id": mid, "score": scores.get("score"),
                                "why": [w for w, on in (("text", scores.get("keyword")), ("query", scores.get("vector")), ("filters", later)) if on] or ["text"]})
        # what was just written and isn't indexed yet: matched here by its words
        words = [w for w in re.findall(r"\w+", asked.lower()) if len(w) > 2]
        now = time.time()
        for at, p in self._recent.get(mid, []):
            if now - at >= RECENT_S or p in seen:
                continue
            x = await self._read(p)
            if x and keep(x) and words:
                said = mp.record_words(x).lower()
                hits = sum(1 for w in words if w in said)
                if hits:
                    seen.add(p)
                    results.append({"record": x, "memory_id": mid, "score": hits / len(words), "why": ["text"]})
        results.sort(key=lambda r: -(r.get("score") or 0))
        return {"results": results[:limit], "degraded": degraded, "abstain": False}
