"""mem0 (Platform API) as a memory provider.

Every shape here was read off the live API on 2026-10-04, with a workspace's own key, and the
adapter claims only what that showed:

  one memory = one mem0 `user_id` (the memory's id). mem0 has no container to put a memory in, so
      the isolation is this adapter's: every search and listing carries the id as a filter, and a
      record fetched by id is refused unless mem0 says it belongs to this memory. `enforced_filter`.
  remember = POST /v3/memories/add/ with infer=false: stored as stated, answered at once with its id.
  observe  = the same call with infer=true: mem0 extracts facts in the background and answers with
      an event id. It does NOT keep the episode as a record: what remains is the facts it derived
      (each carries the metadata sent), so `observe` answers a job, and the job's records are facts.
  recall   = POST /v3/memories/search/: semantic, BM25 and entity matching fused by mem0 into one
      score, with the parts in `score_breakdown`. Words cannot be asked for on their own, so `text`
      alone is searched as the query and kept only where BM25 matched. Metadata filters are
      equality only (`in` is refused: "Unsupported metadata operator"); anything else is applied
      here, after ranking, and said in `degraded`. mem0 never says "I do not know": no abstention.
  revise   = PUT /v1/memories/{id}/ with `text`: changed in place, and mem0 keeps the change in the
      record's history (old and new). Versions are read from that history.
  forget   = PUT with an `expiration_date` in the past: hidden from search and listing, still
      stored, still in history. That is mem0's own soft removal.
  erase    = DELETE. The memory is gone from search, listing and get, and its HISTORY IS STILL
      SERVED by id, original input included, even after the whole user is deleted (measured). So
      every erased id is reported `unreachable`: the content can still be read from mem0.
  content = text only. A record's text parts are stored as one memory; a file part is refused by the
      gateway before it reaches here, because mem0 is declared to keep `text/*` and nothing else.
  no `as_of` on recall or list (a single record's past is read from its history), no named or free
      queries, no extension types, no files, no consolidation the caller can start or read.

What this adapter adds to a mem0 memory is in its metadata under `hr_`: the record type, the writer
the gateway stamped, references, validity, the version count.
"""
from __future__ import annotations

import datetime as _dt
import json
import time

import httpx

import memory_plane as mp

API = "https://api.mem0.ai"
TIMEOUT_S = 45
# Tests set an httpx transport here so every call is exercised without an account.
transport: httpx.BaseTransport | None = None
_RESERVED = "hr_"


def _utc(ts) -> str | None:
    """mem0 answers timestamps in more than one zone and precision; one form leaves here."""
    if not ts:
        return None
    try:
        d = _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return str(ts)
    if d.tzinfo is None:
        d = d.replace(tzinfo=_dt.timezone.utc)
    return d.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def _today() -> _dt.date:
    return _dt.datetime.now(_dt.timezone.utc).date()


class Mem0Unavailable(mp.MemoryError):
    def __init__(self, why: str):
        super().__init__(502, "memory_unavailable", f"mem0 did not answer: {why}"[:300])


async def check(api_key: str) -> str:
    """'' when mem0 accepts the key, else why not, in a sentence for the person connecting it."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S, transport=transport) as c:
            r = await c.get(API + "/v1/ping/", headers={"Authorization": f"Token {api_key}"})
    except httpx.HTTPError as e:
        return f"mem0 could not be reached: {type(e).__name__}."
    return "" if r.status_code == 200 else f"mem0 refused the key (HTTP {r.status_code})."


def _split(text: str, titled: bool) -> tuple[str, str]:
    """(title, body) of a mem0 memory: its first line is the title when the record was given one."""
    if not titled:
        return "", text
    head, _, rest = text.partition("\n")
    return head.strip(), rest.strip()


class Mem0(mp.Provider):
    id = "mem0"

    def __init__(self, api_key: str = ""):
        self.key = api_key
        self._counts: dict[str, tuple[float, int]] = {}

    def capabilities(self) -> dict:
        return {"id": self.id, "isolation": "enforced_filter", "derivation": "write_time",
                "observe": {"keeps_episodes": False, "answers": "job"},
                # mem0 links entities inside itself to rank, and no longer serves them: an entity is
                # here only when someone states one
                "graph": {"entities": "stated"},
                "recall": {"signals": ["query", "text", "filters"], "abstain": False,
                           "filters": {"native": ["eq on type and attributes.*", "gte/lte/gt/lt on time.written_at"],
                                       "applied_after_ranking": "every other filter"}},
                "history": {"content": "versions", "structure": "none"}, "as_of": "one record",
                "revise": "native", "forget": "native", "erase": {"unreachable": "reported"},
                "prime": False, "consolidate": False, "queries": {"named": False, "free": None},
                "types": False, "content": {"media": ["text/*"], "describes": []}}

    async def bind(self, org: str, workspace: str) -> "Mem0":
        fields = await mp.CREDENTIALS(org, workspace, self.id) if mp.CREDENTIALS else None
        key = str((fields or {}).get("api_key") or "")
        if not key:
            raise mp.MemoryError(503, "memory_unavailable",
                                 "mem0 is not connected for this workspace: connect it with its API key.")
        return Mem0(key) if key != self.key else self

    # ── the wire ──────────────────────────────────────────────────────────────────────────────
    async def _call(self, method: str, path: str, *, body=None, params=None, ok=(200,)) -> httpx.Response:
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_S, transport=transport) as c:
                r = await c.request(method, API + path, json=body, params=params,
                                    headers={"Authorization": f"Token {self.key}", "Accept": "application/json"})
        except httpx.HTTPError as e:
            raise Mem0Unavailable(type(e).__name__)
        if r.status_code in ok or r.status_code == 404:
            return r
        if r.status_code in (401, 403):
            raise mp.MemoryError(503, "memory_unavailable", "mem0 refused this workspace's key: reconnect it.")
        raise Mem0Unavailable(f"HTTP {r.status_code} {r.text[:160]}")

    # ── one shape in, one shape out ───────────────────────────────────────────────────────────
    @staticmethod
    def _meta(record: dict, writer: dict, version: int = 1) -> dict:
        """The protocol's fields a mem0 memory has no place for, kept in its metadata."""
        m = {k: v for k, v in (record.get("attributes") or {}).items() if not str(k).startswith(_RESERVED)}
        m[_RESERVED + "type"] = record.get("type") or "fact"
        if record.get("title"):
            m[_RESERVED + "title"] = "1"        # the memory's first line is the record's title
        m[_RESERVED + "version"] = version
        m[_RESERVED + "writer_kind"], m[_RESERVED + "writer_id"] = writer.get("kind") or "", writer.get("id") or ""
        if writer.get("type"):
            m[_RESERVED + "writer_type"] = writer["type"]
        if record.get("references"):
            m[_RESERVED + "refs"] = json.dumps(record["references"], separators=(",", ":"))
        for k in ("valid_from", "valid_to"):
            if (record.get("time") or {}).get(k):
                m[_RESERVED + k] = record["time"][k]
        return m

    @staticmethod
    def _out(item: dict) -> dict:
        meta = dict(item.get("metadata") or {})
        exp = item.get("expiration_date")
        gone = bool(exp) and str(exp)[:10] < _today().isoformat()
        try:
            refs = json.loads(meta.get(_RESERVED + "refs") or "[]")
        except ValueError:
            refs = []
        writer = {"kind": meta.get(_RESERVED + "writer_kind") or "provider", "id": meta.get(_RESERVED + "writer_id") or "mem0"}
        if meta.get(_RESERVED + "writer_type"):
            writer["type"] = meta[_RESERVED + "writer_type"]
        if meta.get(_RESERVED + "observed_by"):
            writer = {"kind": "provider", "id": "mem0", "on_behalf_of": meta[_RESERVED + "observed_by"]}
        title, body = _split(item.get("memory") or "", bool(meta.get(_RESERVED + "title")))
        return {"id": str(item["id"]), "type": meta.get(_RESERVED + "type") or "fact", "title": title,
                "content": [{"type": "text", "text": body}] if body else [],
                "attributes": {k: v for k, v in meta.items() if not str(k).startswith(_RESERVED)},
                "references": refs if isinstance(refs, list) else [],
                "version": int(meta.get(_RESERVED + "version") or 1), "status": "forgotten" if gone else "active",
                "supersedes": None,
                "time": {"valid_from": meta.get(_RESERVED + "valid_from"), "valid_to": meta.get(_RESERVED + "valid_to"),
                         "written_at": _utc(item.get("updated_at") or item.get("created_at")),
                         "invalidated_at": _utc(str(exp) + "T23:59:59+00:00") if gone else None},
                "written_by": writer}

    async def _owned(self, mid: str, rid: str) -> dict | None:
        """The mem0 memory with this id, if it is this memory's. The id is mem0's and global: one
        learned in another memory must find nothing here."""
        r = await self._call("GET", f"/v1/memories/{rid}/")
        if r.status_code != 200:
            return None
        item = r.json()
        return item if str(item.get("user_id") or "") == mid else None

    # ── lifecycle ─────────────────────────────────────────────────────────────────────────────
    async def drop(self, mid: str) -> None:
        await self._call("DELETE", "/v1/memories/", params={"user_id": mid})
        self._counts.pop(mid, None)

    async def count(self, mid: str):
        hit = self._counts.get(mid)
        if hit and time.time() - hit[0] < 30:
            return hit[1]
        r = await self._call("POST", "/v3/memories/", body={"filters": {"user_id": mid}}, params={"page": 1, "page_size": 1})
        n = int((r.json() or {}).get("count") or 0) if r.status_code == 200 else None
        if n is not None:
            self._counts[mid] = (time.time(), n)
        return n

    # ── writes ────────────────────────────────────────────────────────────────────────────────
    async def remember(self, mid, record, writer):
        text = mp.said(record)              # mem0 has one text per memory: the title is its first line
        r = await self._call("POST", "/v3/memories/add/", body={
            "user_id": mid, "infer": False, "messages": [{"role": "user", "content": text}],
            "metadata": self._meta(record, writer)})
        made = (r.json() or {}).get("results") or []
        if r.status_code != 200 or not made:
            raise Mem0Unavailable("the memory was not stored")
        self._counts.pop(mid, None)
        return self._out((await self._owned(mid, str(made[0]["id"]))) or
                         {"id": made[0]["id"], "memory": text, "metadata": self._meta(record, writer)})

    async def observe(self, mid, episodes, writer):
        """One add per episode, inferred. mem0 answers before it has extracted anything, so this
        answers a job; with several episodes the job id names every event."""
        events = []
        for e in episodes:
            # each text part is one message, under the role it carries (mem0 takes user, assistant, system)
            msgs = [{"role": p.get("role") if p.get("role") in ("user", "assistant", "system") else "user", "content": p["text"]}
                    for p in e.get("content") or [] if p.get("text")]
            meta = self._meta({"type": "fact", "attributes": e.get("attributes") or {}}, {"kind": "provider", "id": "mem0"})
            meta[_RESERVED + "observed_by"] = f"{writer.get('kind')}:{writer.get('id')}"
            r = await self._call("POST", "/v3/memories/add/", body={"user_id": mid, "messages": msgs, "metadata": meta})
            ev = (r.json() or {}).get("event_id") if r.status_code == 200 else None
            if not ev:
                raise Mem0Unavailable("the episode was not taken")
            events.append(str(ev))
        self._counts.pop(mid, None)
        return {"records": [], "job": {"id": ".".join(events), "status": "pending"}}

    async def job(self, mid, job_id):
        records, pending, failed = [], False, ""
        for ev in job_id.split("."):
            r = await self._call("GET", f"/v1/event/{ev}/")
            doc = r.json() if r.status_code == 200 else None
            if not doc or str((doc.get("payload") or {}).get("user_id") or "") != mid:
                return None                 # an event of another memory, or none: the same answer
            st = str(doc.get("status") or "").upper()
            if st in ("PENDING", "RUNNING", "IN_PROGRESS", "QUEUED"):
                pending = True
            elif st == "FAILED":
                failed = "mem0 could not process the episode."
            else:
                for x in doc.get("results") or []:
                    item = await self._owned(mid, str(x.get("id") or ""))
                    if item:
                        records.append(self._out(item))
        return {"id": job_id, "status": "failed" if failed else "pending" if pending else "completed",
                "error": failed, "records": records}

    async def revise(self, mid, rid, patch, writer):
        item = await self._owned(mid, rid)
        if not item or self._out(item)["status"] != "active":
            raise mp.MemoryError(404, "memory_record_not_found", "No such record in this memory.", "record_id")
        cur = self._out(item)
        merged = {"type": cur["type"], "title": patch.get("title", cur["title"]), "content": patch.get("content", cur["content"]),
                  "attributes": {**cur["attributes"], **(patch.get("attributes") or {})},
                  "references": patch.get("references", cur["references"]),
                  "time": {**{k: cur["time"][k] for k in ("valid_from", "valid_to")}, **(patch.get("time") or {})}}
        body: dict = {"metadata": self._meta(merged, writer, cur["version"] + 1)}
        if "content" in patch or "title" in patch:
            body["text"] = mp.said(merged)
        r = await self._call("PUT", f"/v1/memories/{rid}/", body=body)
        if r.status_code != 200:
            raise Mem0Unavailable("the revision was not stored")
        out = self._out(r.json())
        out["supersedes"] = cur["version"]
        return out

    async def forget(self, mid, rid, writer):
        item = await self._owned(mid, rid)
        if not item or self._out(item)["status"] != "active":
            raise mp.MemoryError(404, "memory_record_not_found", "No such record in this memory.", "record_id")
        meta = {**(item.get("metadata") or {}), _RESERVED + "forgotten_by": f"{writer.get('kind')}:{writer.get('id')}"}
        r = await self._call("PUT", f"/v1/memories/{rid}/", body={
            "expiration_date": (_today() - _dt.timedelta(days=1)).isoformat(), "metadata": meta})
        if r.status_code != 200:
            raise Mem0Unavailable("the record was not closed")
        self._counts.pop(mid, None)
        return self._out(r.json())

    async def erase(self, mid, rids):
        erased = []
        for rid in rids:
            if await self._owned(mid, rid):
                r = await self._call("DELETE", f"/v1/memories/{rid}/")
                if r.status_code == 200:
                    erased.append(rid)
        self._counts.pop(mid, None)
        # mem0 keeps a deleted memory's history, with its content and the input it came from, and
        # serves it by id (measured): what was erased here can still be read there.
        return {"erased": erased, "unreachable": list(erased)}

    # ── reads ─────────────────────────────────────────────────────────────────────────────────
    async def get(self, mid, rid, as_of=None):
        item = await self._owned(mid, rid)
        if not item:
            return None
        if not as_of:
            return self._out(item)
        past = [v for v in await self.history(mid, rid) if v["time"]["written_at"] <= as_of]
        return {**past[-1], "status": "active"} if past else None

    async def history(self, mid, rid):
        item = await self._owned(mid, rid)
        if not item:
            raise mp.MemoryError(404, "memory_record_not_found", "No such record in this memory.", "record_id")
        r = await self._call("GET", f"/v1/memories/{rid}/history/")
        events = sorted(r.json() if r.status_code == 200 else [], key=lambda e: str(e.get("updated_at") or ""))
        head, versions = self._out(item), []
        for e in events:
            if e.get("event") != "ADD" and e.get("old_memory") == e.get("new_memory"):
                continue                    # a change of metadata or expiry, not of what the record says
            vt, vb = _split(e.get("new_memory") or "", bool(head["title"]))
            # mem0 keeps what each version said, not its fields: the reason belongs to the head alone
            versions.append({**head, "attributes": {k: v for k, v in head["attributes"].items() if k != "revision_reason"},
                             "title": vt, "content": [{"type": "text", "text": vb}] if vb else [], "version": len(versions) + 1,
                             "status": "superseded", "supersedes": len(versions) or None,
                             "time": {**head["time"], "written_at": _utc(e.get("updated_at")), "invalidated_at": None}})
        if not versions:
            return [head]
        for a, b in zip(versions, versions[1:]):
            a["time"]["invalidated_at"] = b["time"]["written_at"]
        versions[-1].update(status=head["status"], attributes=head["attributes"])
        versions[-1]["time"]["invalidated_at"] = head["time"]["invalidated_at"]
        return versions

    def _filters(self, mid, req: dict, degraded: list[str]) -> tuple[dict, list]:
        """(what mem0 is asked, what is left to apply here). The memory's id (or the ids, for a
        question asked of several memories) is always the first clause: nothing a caller sends can
        remove it."""
        scope = {"user_id": mid} if isinstance(mid, str) else \
            ({"user_id": mid[0]} if len(mid) == 1 else {"OR": [{"user_id": x} for x in mid]})
        clauses, later = [scope], []
        types = [t for t in (req.get("types") or []) if t]
        if len(types) == 1:
            clauses.append({"metadata": {_RESERVED + "type": types[0]}})
        elif types:
            clauses.append({"OR": [{"metadata": {_RESERVED + "type": t}} for t in types]})

        def walk(f):
            if not f:
                return
            if "and" in f:
                for x in f["and"]:
                    walk(x)
                return
            field, op, val = str(f.get("field") or ""), f.get("op", "eq"), f.get("value")
            if "or" not in f and op == "eq" and field.startswith("attributes.") and "." not in field[11:]:
                clauses.append({"metadata": {field[11:]: val}})
            elif "or" not in f and op == "eq" and field == "type":
                clauses.append({"metadata": {_RESERVED + "type": val}})
            elif "or" not in f and field == "time.written_at" and op in ("gte", "lte", "gt", "lt"):
                clauses.append({"created_at": {op: val}})
            else:
                later.append(f)
        walk(req.get("filters"))
        if later:
            degraded.append("filters:applied_after_ranking")
        return ({"AND": clauses} if len(clauses) > 1 else clauses[0]), later

    async def list(self, mid, req):
        degraded: list[str] = []
        if req.get("as_of"):
            raise mp.MemoryError(422, "memory_unsupported", "This memory's provider does not list a memory as of a past instant.")
        flt, later = self._filters(mid, req, degraded)
        page = int(req.get("cursor") or 1)
        r = await self._call("POST", "/v3/memories/", params={"page": page, "page_size": int(req.get("limit") or 50)},
                             body={"filters": flt, "show_expired": req.get("include") == "all"})
        doc = r.json() if r.status_code == 200 else {}
        rows = [x for x in (self._out(i) for i in doc.get("results") or []) if all(mp.matches(x, f) for f in later)]
        return {"records": rows, "next": str(page + 1) if doc.get("next") else None}

    async def recall(self, mid, req):
        res = await self.recall_many([mid], req)
        return res

    async def recall_many(self, mids, req):
        """mem0 searches several scopes in one request (an OR of user_ids, measured), so a subtree
        is one call, and each hit says which memory it is in."""
        mid = list(mids)
        degraded: list[str] = []
        if req.get("as_of"):
            degraded.append("as_of:not_supported")
        query, text = str(req.get("query") or "").strip(), str(req.get("text") or "").strip()
        flt, later = self._filters(mid, req, degraded)
        limit = int(req.get("limit") or 8)
        if not query and not text:           # fields alone: mem0 has no ranking to do, so this is a listing
            r = await self._call("POST", "/v3/memories/", params={"page": 1, "page_size": limit}, body={"filters": flt})
            rows = [(i, self._out(i)) for i in ((r.json() or {}).get("results") or [] if r.status_code == 200 else [])]
            return {"results": [{"record": x, "memory_id": str(i.get("user_id") or ""), "score": 1.0, "why": ["filters"]}
                                for i, x in rows if all(mp.matches(x, f) for f in later)],
                    "degraded": degraded, "abstain": False}
        if query and text:
            degraded.append("text:searched_with_the_query")       # one fused search, not two signals
        r = await self._call("POST", "/v3/memories/search/", body={
            "query": f"{query} {text}".strip(), "filters": flt, "top_k": min(limit * (3 if later or (text and not query) else 1), 100)})
        results = []
        for item in (r.json() or {}).get("results") or [] if r.status_code == 200 else []:
            parts = item.get("score_breakdown") or {}
            if text and not query and not float(parts.get("bm25") or 0) > 0:
                continue                    # words were asked for: a hit by meaning alone is not one
            rec = self._out(item)
            if not all(mp.matches(rec, f) for f in later):
                continue
            why = [w for w, on in (("query", query and float(parts.get("semantic") or 0) > 0),
                                   ("text", float(parts.get("bm25") or 0) > 0),
                                   ("filters", bool(req.get("filters")))) if on]
            if str(item.get("user_id") or "") not in mid:
                continue                    # not one of the memories asked: never returned, whatever mem0 said
            results.append({"record": rec, "memory_id": str(item["user_id"]), "score": item.get("score"), "why": why})
        return {"results": results[:limit], "degraded": degraded, "abstain": False}
