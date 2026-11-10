"""Hindsight (vectorize-io/hindsight, MIT) as a memory provider.

Hindsight keeps a memory in a bank and works on what it is given: a retained document is split into
facts and entities, linked into a graph, and consolidated into observations in the background. Every
shape here was read off a server running on 2026-11-04.

  one memory = one bank. `container`.
  a record someone states = a document we name (`hrec_...`), retained with the strategy `hr_stated`,
      whose extraction mode is `chunks`: the words are kept as written and cost no model call. A
      retain answers no ids, so the id has to be ours. Hindsight also holds it as one fact, which is
      what a search finds; that fact is reported as the document it came from. Hindsight also reads a
      copy (`hrx_...`, the same id after the prefix), retained in the background with its own extraction,
      so a stated record gets the facts, entities and links Hindsight is built to make (11-06): those come
      from the stated record, and the copy is never listed. Revising reads it again; forgetting takes its
      facts out of search; erasing deletes it with the record.
  observe  = a document with no strategy, retained asynchronously: the bank extracts facts and entities
      from it, and it stays as the `episode`. `keeps_episodes`, and the answer is a job.
  a derived record = a fact (Hindsight's id), or an entity (`ent_<id>`). A fact says which entities it
      involves and which document it came from, as references, so the graph read has real edges. An
      observation, which Hindsight consolidates from other facts in the background, has neither: it names
      its `source_memory_ids`, and each is its `derived_from`, a stated record's fact as that record (measured
      11-06: 172 of a bank's 211 facts were observations, and with no references they drew as loose dots).
  revise   = the same document retained with update_mode `replace`. Hindsight keeps no earlier words of
      a document, so the versions are kept in its metadata: `emulated`, and said in the capability
      document. A derived fact is edited in place by Hindsight, which keeps that fact's own history.
  forget   = the facts' state set invalid, which takes them out of search. The document stays.
  erase    = DELETE the document, with its facts. A single derived fact has no delete of its own, since
      Hindsight would have to delete what it came from, so it is invalidated and reported `unreachable`.
  schema   = the bank's `entity_labels`: a vocabulary its extraction tags each derived fact with. Measured:
      `type:Company` arrives as an entity on the fact and, with `tag`, as a tag recall can scope to. So it
      classifies facts and not entities, which is `labels` rather than `guides`: no properties, no relations,
      and the label nodes are shown as a fact's `attributes.labels`, never as entities. A stated record is
      kept word for word without the extraction, so only what an episode derives gets labels.
"""
from __future__ import annotations

import datetime as _dt
import json
import time
import uuid

import httpx

import memory_plane as mp

TIMEOUT_S = 90
PREFIX = "hrec_"
COPY = "hrx_"      # the copy Hindsight reads of a stated record: the same id after the prefix
ENTITY = "ent_"
LABEL = "type:"     # how Hindsight names a label of the group we keep: never an entity of the graph
# The wording matters more than any other setting. Measured three times each on one text: this one labelled
# what each fact mentions and left an unrelated fact bare; "What this fact is about." labelled nothing at all.
LABEL_ASK = "Every kind of thing this fact mentions. Choose all that apply, or none if nothing fits."
STATED = "hr_stated"
TURN = "hr_turn"    # the strategy a finished turn is retained with: the bank's own extraction, told what not to keep
MAX_KEPT_VERSIONS = 50
UNIT_PAGE, UNIT_PAGES = 500, 20    # how a bank's facts are read to name what an observation came from: up to 10,000
ACTIVE = "valid"
# Tests set an httpx transport here so every call is exercised without a server.
transport: httpx.BaseTransport | None = None
# Every other call opens its connections through the gateway's checked network (app.py sets this), so an address
# that passed the check when it was saved and later resolves somewhere internal (a DNS rebind) is refused at connect.
checked_transport = None


def _transport():
    return transport if transport is not None else (checked_transport() if checked_transport else None)



def _stamp(record: dict) -> dict:
    """The item's timestamp: when what it says happened (the record's or episode's valid_from). Hindsight dates what it
    derives from it by this; without it, by when it was written."""
    t = (record.get("time") or {}).get("valid_from")
    return {"timestamp": str(t)} if t else {}

class HindsightUnavailable(mp.MemoryError):
    def __init__(self, why: str):
        super().__init__(502, "memory_unavailable", f"Hindsight did not answer: {why}"[:300])


async def check(api_key: str, base_url: str = "") -> str:
    """'' when a Hindsight server answers at this address, else why not, in a sentence."""
    if not base_url:
        return "Hindsight needs the address of your server."
    try:
        async with httpx.AsyncClient(timeout=20, transport=_transport()) as c:
            r = await c.get(base_url.rstrip("/") + "/v1/default/banks", headers={"Authorization": f"Bearer {api_key}"} if api_key else {})
    except httpx.HTTPError as e:
        return f"Hindsight could not be reached at that address: {type(e).__name__}."
    return "" if r.status_code == 200 else f"Hindsight refused the connection (HTTP {r.status_code})."


def _sentence(text) -> tuple[str, dict]:
    """Hindsight writes a fact as "<what> | When: … | Where: … | Involving: … | <why>", and only the first part
    is the sentence, which is how its own consolidation reads it too. The rest comes back as attributes, except
    who is involved: those are the fact's references already."""
    what, *rest = str(text or "").split(" | ")
    more: dict = {}
    for part in rest:
        key, sep, val = part.partition(": ")
        if sep and key in ("When", "Where"):
            more[key.lower()] = val
        elif not (sep and key == "Involving") and part.strip():
            more["why"] = part.strip()
    return what, more


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{_dt.datetime.now(_dt.timezone.utc).microsecond // 1000:03d}Z"


def _split(text: str, titled: bool) -> tuple[str, str]:
    if not titled:
        return "", text
    head, _, rest = text.partition("\n")
    return head.strip(), rest.strip()


class Hindsight(mp.Provider):
    id = "hindsight"

    def __init__(self, base_url: str = "", api_key: str = ""):
        self.base, self.key = base_url.rstrip("/"), api_key
        self._ready: set[str] = set()
        self._entities: dict[str, tuple[float, dict[str, str]]] = {}
        self._units: dict[str, tuple[float, dict[str, str]]] = {}

# What Hindsight itself makes and how it links it: the part of a memory's schema nobody sets. The console draws it locked
# beside what a person can set; record types and reference rels as this adapter answers them.
    BUILTIN = {
        "types": [
            {"name": "episode", "description": "A conversation Hindsight was given, kept whole."},
            {"name": "fact", "description": "Something Hindsight learned: about the world, from an experience, or an observation it drew from other facts."},
            {"name": "entity", "description": "Someone or something its facts mention."},
        ],
        "relations": [
            {"name": "about", "from": "fact", "to": "entity", "description": "Who or what a fact mentions."},
            {"name": "derived_from", "from": "fact", "to": "episode", "description": "The conversation it was read from."},
            {"name": "derived_from", "from": "fact", "to": "fact", "description": "The facts an observation was drawn from."},
        ],
    }

    def capabilities(self) -> dict:
        return {"id": self.id, "isolation": "container", "derivation": "background",
                "observe": {"keeps_episodes": True, "answers": "job"},
                "recall": {"signals": ["query", "text", "filters"], "abstain": False,
                           "filters": {"native": ["type", "attributes.labels"], "applied_after_ranking": "every other filter"}},
                "history": {"content": "versions", "structure": "none", "emulated": True}, "as_of": "one record",
                "revise": "native", "forget": "native", "erase": {"unreachable": "reported"},
                "prime": True, "consolidate": "trigger", "holds": True, "queries": {"named": False, "free": None},
                "types": False, "graph": {"entities": "derived"},
                "schema": {"mode": "labels", "builtin": self.BUILTIN},
                "content": {"media": ["text/*"], "describes": []}}

    async def bind(self, org, workspace):
        fields = await mp.CREDENTIALS(org, workspace, self.id) if mp.CREDENTIALS else None
        base = str((fields or {}).get("base_url") or "").strip().rstrip("/")
        if not base:
            raise mp.MemoryError(503, "memory_unavailable", "Hindsight is not connected for this workspace: connect it with your server's address.")
        return Hindsight(base, str((fields or {}).get("api_key") or ""))

    # ── the wire ──────────────────────────────────────────────────────────────────────────────
    async def _call(self, method: str, path: str, *, body=None, params=None, ok=(200,)) -> httpx.Response:
        headers = {"Accept": "application/json"}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_S, transport=_transport()) as c:
                r = await c.request(method, self.base + mp.vendor_path(path), json=body, params=params, headers=headers)
        except httpx.HTTPError as e:
            raise HindsightUnavailable(type(e).__name__)
        if r.status_code in ok or r.status_code == 404:
            return r
        if r.status_code in (401, 403):
            raise mp.MemoryError(503, "memory_unavailable", "Hindsight refused this workspace's key: reconnect it.")
        raise HindsightUnavailable(f"HTTP {r.status_code}")

    @staticmethod
    def _bank(mid: str) -> str:
        return f"/v1/default/banks/{mid}"

    async def _ensure(self, mid: str, mission: str = "") -> None:
        if mid in self._ready:
            return
        r = await self._call("PUT", self._bank(mid), body={"name": mid, **({"mission": mission} if mission else {})})
        if r.status_code != 200:
            raise HindsightUnavailable("the bank was not created")
        # retain_mission is Hindsight's own guidance for what its extraction keeps ("injected into any extraction mode"),
        # here for what a finished turn is read with (TURN). A strategy's fields it doesn't know are ignored, so a
        # server without it reads the turn as before.
        r = await self._call("PATCH", self._bank(mid) + "/config",
                             body={"updates": {"retain_strategies": {STATED: {"retain_extraction_mode": "chunks"},
                                                                     TURN: {"retain_mission": mp.EXTRACTION_GUIDE}}}})
        if r.status_code != 200:
            raise HindsightUnavailable("the bank was not set up")
        self._ready.add(mid)

    # ── one shape in, one shape out ───────────────────────────────────────────────────────────
    @staticmethod
    def _meta(record: dict, writer: dict, version: int = 1, kept: list | None = None) -> dict:
        """The protocol's fields, kept in a document's metadata, whose values are strings."""
        m = {"hr_stated": "1", "hr_type": str(record.get("type") or "fact"), "hr_version": str(version),
             "hr_writer": json.dumps({k: v for k, v in writer.items() if v}, separators=(",", ":"))}
        if record.get("title"):
            m["hr_title"] = "1"
        if record.get("attributes"):
            m["hr_attributes"] = json.dumps(record["attributes"], separators=(",", ":"))
        if record.get("references"):
            m["hr_refs"] = json.dumps(record["references"], separators=(",", ":"))
        t = record.get("time") or {}
        for k in ("valid_from", "valid_to"):
            if t.get(k):
                m["hr_" + k] = str(t[k])
        if kept:
            m["hr_versions"] = json.dumps(kept[-MAX_KEPT_VERSIONS:], separators=(",", ":"))
        return m

    @staticmethod
    def _stated(rid: str, text: str, meta: dict, written: str | None, active: bool) -> dict:
        title, body = _split(text, bool(meta.get("hr_title")))
        def js(k, d):
            try:
                return json.loads(meta.get(k) or d)
            except ValueError:
                return json.loads(d)
        version = int(meta.get("hr_version") or 1)
        return {"id": rid, "type": meta.get("hr_type") or "fact", "title": title,
                "content": [{"type": "text", "text": body}] if body else [],
                "attributes": js("hr_attributes", "{}"), "references": js("hr_refs", "[]"), "version": version,
                "status": "active" if active else "forgotten", "supersedes": version - 1 if version > 1 else None,
                "time": {"valid_from": meta.get("hr_valid_from"), "valid_to": meta.get("hr_valid_to"),
                         "written_at": written, "invalidated_at": None if active else written},
                "written_by": js("hr_writer", '{"kind":"provider","id":"hindsight"}')}

    def _doc_out(self, mid: str, doc: dict) -> dict:
        meta = doc.get("document_metadata") or {}
        tags = doc.get("tags") or []
        if meta.get("hr_stated"):
            return self._stated(str(doc["id"]), str(doc.get("original_text") or ""), meta, doc.get("updated_at"), "forgotten" not in tags)
        parts = []
        try:
            parts = json.loads(meta.get("hr_parts") or "[]")
        except ValueError:
            pass
        closed = "forgotten" in tags
        return {"id": str(doc["id"]), "type": "episode", "title": "", "content": parts or [{"type": "text", "text": str(doc.get("original_text") or "")}],
                "attributes": json.loads(meta.get("hr_attributes") or "{}"), "references": [], "version": 1, "status": "forgotten" if closed else "active", "supersedes": None,
                "time": {"valid_from": None, "valid_to": None, "written_at": doc.get("created_at"), "invalidated_at": doc.get("updated_at") if closed else None},
                "written_by": json.loads(meta.get("hr_writer") or '{"kind":"provider","id":"hindsight"}')}

    def _fact_out(self, mid: str, unit: dict, entities: dict[str, str], units: dict[str, str] | None = None) -> dict:
        meta = unit.get("metadata") or {}
        active = str(unit.get("state") or ACTIVE) == ACTIVE
        if meta.get("hr_stated") and str(unit.get("document_id") or "").startswith(PREFIX):
            return self._stated(str(unit["document_id"]), str(unit.get("text") or ""), meta, unit.get("mentioned_at"), active)
        names = unit.get("entities") or []
        if isinstance(names, str):
            names = [x.strip() for x in names.split(",") if x.strip()]
        refs = [{"rel": "about", "memory_id": mid, "record_id": ENTITY + entities[n]} for n in names if n in entities]
        if unit.get("document_id"):
            refs.append({"rel": "derived_from", "memory_id": mid, "record_id": self._record_of(str(unit["document_id"]))})
        # an observation: the facts it was consolidated from, each as the record a reader sees it as
        for src in unit.get("source_memory_ids") or []:
            ref = {"rel": "derived_from", "memory_id": mid, "record_id": (units or {}).get(str(src), str(src))}
            if ref not in refs:
                refs.append(ref)
        kind = unit.get("fact_type") or unit.get("type")
        labels = sorted(str(n)[len(LABEL):] for n in names if self._is_label(n))
        said, more = _sentence(unit.get("text"))
        if unit.get("occurred_start"):
            more.pop("when", None)             # the time says it, as a date
        return {"id": str(unit["id"]), "type": "fact", "title": "", "content": [{"type": "text", "text": said}],
                # `world` is its word for a plain fact. Only what sets one apart is worth a reader's attention.
                "attributes": {**({"kind": kind} if kind and kind != "world" else {}), **more, **({"labels": labels} if labels else {})},
                "references": refs, "version": 1,
                "status": "active" if active else "forgotten", "supersedes": None,
                # the end of one event is when it happened, not when the fact stopped being true
                "time": {"valid_from": unit.get("occurred_start"),
                         "valid_to": unit.get("occurred_end") if unit.get("occurred_end") != unit.get("occurred_start") else None,
                         "written_at": unit.get("mentioned_at") or unit.get("date"), "invalidated_at": unit.get("invalidated_at")},
                "written_by": {"kind": "provider", "id": self.id}}

    @staticmethod
    def _is_label(name) -> bool:
        return str(name or "").startswith(LABEL)

    def _entity_out(self, e: dict) -> dict:
        return {"id": ENTITY + str(e["id"]), "type": "entity", "title": str(e.get("canonical_name") or ""), "content": [],
                "attributes": {"mentions": e.get("mention_count") or 0, **(e.get("metadata") or {})}, "references": [], "version": 1,
                "status": "active", "supersedes": None,
                "time": {"valid_from": None, "valid_to": None, "written_at": e.get("last_seen") or e.get("first_seen"), "invalidated_at": None},
                "written_by": {"kind": "provider", "id": self.id}}

    async def _entity_ids(self, mid: str) -> dict[str, str]:
        hit = self._entities.get(mid)
        if hit and time.time() - hit[0] < 30:
            return hit[1]
        r = await self._call("GET", self._bank(mid) + "/entities", params={"limit": 500})
        names = {str(e.get("canonical_name")): str(e["id"]) for e in ((r.json() or {}).get("items") or []) if not self._is_label(e.get("canonical_name"))} if r.status_code == 200 else {}
        self._entities[mid] = (time.time(), names)
        return names

    @staticmethod
    def _copy_of(rid: str) -> str:
        return COPY + rid[len(PREFIX):]

    @staticmethod
    def _record_of(doc_id: str) -> str:
        """A copy Hindsight read of a stated record is that record."""
        return PREFIX + doc_id[len(COPY):] if doc_id.startswith(COPY) else doc_id

    async def _read_copy(self, mid: str, rid: str, record: dict, replace: bool = False) -> None:
        """Hindsight reads what was stated as it reads anything it is given, in the background. A copy not taken
        costs what Hindsight would have learned from it, never the record."""
        said = mp.said(record)
        if not said.strip():
            return
        item = {"content": said, "document_id": self._copy_of(rid), "tags": ["t:read"], "metadata": {"hr_read": rid}, **_stamp(record),
                **({"update_mode": "replace"} if replace else {})}
        try:
            await self._call("POST", self._bank(mid) + "/memories", body={"async": True, "items": [item]})
        except mp.MemoryError:
            pass

    async def _unit_ids(self, mid: str, need=()) -> dict[str, str]:
        """Each fact of the bank as the record it is read as: a stated record's own fact is that record (its document),
        any other fact is itself. Read again when a fact asked about isn't in it yet, since an observation can be
        made from a record stated after the last read."""
        hit = self._units.get(mid)
        if hit and time.time() - hit[0] < 30 and all(str(x) in hit[1] for x in need):
            return hit[1]
        if hit and time.time() - hit[0] < 2:
            return hit[1]
        out: dict[str, str] = {}
        at = 0
        for _ in range(UNIT_PAGES):
            r = await self._call("GET", self._bank(mid) + "/memories/list", params={"limit": UNIT_PAGE, "offset": at})
            if r.status_code != 200:
                break
            doc = r.json() or {}
            items = doc.get("items") or []
            for u in items:
                d = str(u.get("document_id") or "")
                out[str(u["id"])] = d if (u.get("metadata") or {}).get("hr_stated") and d.startswith(PREFIX) else str(u["id"])
            at += len(items)
            if not items or at >= int(doc.get("total") or 0):
                break
        self._units[mid] = (time.time(), out)
        return out

    async def _sources(self, mid: str, units: list[dict]) -> dict[str, str]:
        need = {str(x) for u in units for x in (u.get("source_memory_ids") or [])}
        return await self._unit_ids(mid, need) if need else {}

    async def _doc(self, mid: str, rid: str) -> dict | None:
        r = await self._call("GET", self._bank(mid) + f"/documents/{rid}")
        return r.json() if r.status_code == 200 else None

    async def _units_of(self, mid: str, rid: str) -> list[dict]:
        r = await self._call("GET", self._bank(mid) + "/memories/list", params={"document_id": rid, "limit": 200})
        return ((r.json() or {}).get("items") or []) if r.status_code == 200 else []

    # ── lifecycle ─────────────────────────────────────────────────────────────────────────────
    async def create(self, mid, memory):
        await self._ensure(mid, str(memory.get("description") or ""))

    async def drop(self, mid):
        await self._call("DELETE", self._bank(mid))
        self._ready.discard(mid)
        self._entities.pop(mid, None)
        self._units.pop(mid, None)

    async def count(self, mid):
        """What the tree holds, from the lists themselves. Its /stats route stayed at zero for minutes while
        facts were there to read, and a memory that reads as empty opens on the wrong tab."""
        facts = await self._call("GET", self._bank(mid) + "/memories/list", params={"limit": 1, "state": ACTIVE})
        if facts.status_code == 404:
            return 0
        if facts.status_code != 200:
            return None
        eps = await self._call("GET", self._bank(mid) + "/documents", params={"tags": "t:episode", "limit": 1})
        return int((facts.json() or {}).get("total") or 0) + len(await self._entity_ids(mid)) + \
            (int((eps.json() or {}).get("total") or 0) if eps.status_code == 200 else 0)

    # ── writes ────────────────────────────────────────────────────────────────────────────────
    async def remember(self, mid, record, writer):
        await self._ensure(mid)
        rid = PREFIX + uuid.uuid4().hex
        meta = self._meta(record, writer)
        tags = [f"t:{record.get('type') or 'fact'}"] + (["standing"] if (record.get("attributes") or {}).get("standing") else [])
        r = await self._call("POST", self._bank(mid) + "/memories", body={"async": False, "items": [
            {"content": mp.said(record), "document_id": rid, "metadata": meta, "tags": tags, "strategy": STATED,
             **_stamp(record)}]})
        if r.status_code != 200:
            raise HindsightUnavailable("the record was not stored")
        await self._read_copy(mid, rid, record)
        return self._stated(rid, mp.said(record), meta, _now(), True)

    async def observe(self, mid, episodes, writer):
        await self._ensure(mid)
        items, ids = [], []
        for e in episodes:
            rid = PREFIX + uuid.uuid4().hex
            ids.append(rid)
            text = "\n".join(f"{p.get('name') or p.get('role')}: {p['text']}" if p.get("name") or p.get("role") else str(p["text"])
                             for p in e.get("content") or [] if p.get("text"))
            items.append({"content": text, "document_id": rid, "tags": ["t:episode"], "strategy": TURN, **_stamp(e), "metadata": {
                "hr_type": "episode", "hr_writer": json.dumps({"kind": "provider", "id": self.id, "on_behalf_of": f"{writer.get('kind')}:{writer.get('id')}"}, separators=(",", ":")),
                "hr_parts": json.dumps(e.get("content") or [], separators=(",", ":")),
                **({"hr_attributes": json.dumps(e["attributes"], separators=(",", ":"))} if e.get("attributes") else {})}})
        r = await self._call("POST", self._bank(mid) + "/memories", body={"async": True, "items": items})
        doc = r.json() if r.status_code == 200 else None
        if not doc:
            raise HindsightUnavailable("the episode was not taken")
        ops = doc.get("operation_ids") or ([doc["operation_id"]] if doc.get("operation_id") else [])
        return {"records": [], "job": {"id": "|".join([*ids, "ops", *ops]), "status": "pending"}}

    async def job(self, mid, job_id):
        ids, _, ops = job_id.partition("|ops|")
        pending, failed = False, ""
        for op in [x for x in ops.split("|") if x]:
            r = await self._call("GET", self._bank(mid) + f"/operations/{op}")
            if r.status_code != 200:
                return None
            st = str((r.json() or {}).get("status") or "")
            if st in ("pending", "processing", "running", "queued"):
                pending = True
            elif st == "failed":
                failed = "Hindsight could not process the episode."
        if pending or failed:
            return {"id": job_id, "status": "failed" if failed else "pending", "error": failed, "records": []}
        names = await self._entity_ids(mid)
        units = [u for rid in ids.split("|") for u in await self._units_of(mid, rid)]
        srcs = await self._sources(mid, units)
        records = [self._fact_out(mid, u, names, srcs) for u in units]
        return {"id": job_id, "status": "completed", "error": "", "records": records}

    async def revise(self, mid, rid, patch, writer):
        if rid.startswith(PREFIX):
            doc = await self._doc(mid, rid)
            if not doc or not (doc.get("document_metadata") or {}).get("hr_stated") or "forgotten" in (doc.get("tags") or []):
                raise mp.MemoryError(404, "memory_record_not_found", "No such record in this memory.", "record_id")
            cur = self._doc_out(mid, doc)
            merged = {"type": cur["type"], "title": patch.get("title", cur["title"]), "content": patch.get("content", cur["content"]),
                      "attributes": {**cur["attributes"], **(patch.get("attributes") or {})}, "references": patch.get("references", cur["references"]),
                      "time": {**{k: cur["time"][k] for k in ("valid_from", "valid_to")}, **(patch.get("time") or {})}}
            old = doc.get("document_metadata") or {}
            try:
                kept = json.loads(old.get("hr_versions") or "[]")
            except ValueError:
                kept = []
            kept.append({"v": cur["version"], "title": cur["title"], "content": cur["content"], "attributes": cur["attributes"], "at": doc.get("updated_at"),
                         "by": cur["written_by"], "world": {k: cur["time"][k] for k in ("valid_from", "valid_to")}})
            version = cur["version"] + 1
            meta = self._meta(merged, writer, version, kept)
            tags = [f"t:{merged['type']}"] + (["standing"] if merged["attributes"].get("standing") else [])
            r = await self._call("POST", self._bank(mid) + "/memories", body={"async": False, "items": [
                {"content": mp.said(merged), "document_id": rid, "metadata": meta, "tags": tags, "strategy": STATED, "update_mode": "replace",
                 **_stamp(merged)}]})
            if r.status_code != 200:
                raise HindsightUnavailable("the revision was not stored")
            if mp.said(merged) != mp.said(cur):
                await self._read_copy(mid, rid, merged, replace=True)
            return self._stated(rid, mp.said(merged), meta, _now(), True)
        if rid.startswith(ENTITY):
            raise mp.MemoryError(422, "memory_unsupported", "Hindsight derives its entities: revise what they came from.")
        text = mp.text_of(patch["content"]) if patch.get("content") else None
        r = await self._call("PATCH", self._bank(mid) + f"/memories/{rid}", body={"text": text} if text else {})
        if r.status_code != 200:
            raise mp.MemoryError(404, "memory_record_not_found", "No such record in this memory.", "record_id")
        out = self._fact_out(mid, {**r.json(), "fact_type": r.json().get("type")}, await self._entity_ids(mid), await self._sources(mid, [r.json()]))
        return {**out, "version": 2, "supersedes": 1}

    async def forget(self, mid, rid, writer):
        reason = f"forgotten by {writer.get('kind')}:{writer.get('id')}"
        if rid.startswith(PREFIX):
            doc = await self._doc(mid, rid)
            if not doc or "forgotten" in (doc.get("tags") or []):
                raise mp.MemoryError(404, "memory_record_not_found", "No such record in this memory.", "record_id")
            for u in [*await self._units_of(mid, rid), *await self._units_of(mid, self._copy_of(rid))]:
                await self._call("PATCH", self._bank(mid) + f"/memories/{u['id']}", body={"state": "invalidated", "reason": reason})
            tags = [t for t in (doc.get("tags") or []) if t != "standing"] + ["forgotten"]
            await self._call("PATCH", self._bank(mid) + f"/documents/{rid}", body={"tags": tags})
            return self._doc_out(mid, {**doc, "tags": tags, "updated_at": _now()})
        if rid.startswith(ENTITY):
            raise mp.MemoryError(422, "memory_unsupported", "Hindsight derives its entities: forget what they came from.")
        r = await self._call("PATCH", self._bank(mid) + f"/memories/{rid}", body={"state": "invalidated", "reason": reason})
        if r.status_code != 200:
            raise mp.MemoryError(404, "memory_record_not_found", "No such record in this memory.", "record_id")
        return self._fact_out(mid, {**r.json(), "state": "invalidated", "fact_type": r.json().get("type")}, {}, await self._sources(mid, [r.json()]))

    async def close_episode(self, mid, rid, writer):
        """Only the conversation: its `forget` above invalidates every fact it taught, and these stay."""
        doc = await self._doc(mid, rid)
        if doc and "forgotten" not in (doc.get("tags") or []):
            await self._call("PATCH", self._bank(mid) + f"/documents/{rid}", body={"tags": [*(doc.get("tags") or []), "forgotten"]})

    async def erase(self, mid, rids):
        erased, unreachable = [], []
        for rid in rids:
            if rid.startswith(PREFIX):
                await self._call("DELETE", self._bank(mid) + f"/documents/{self._copy_of(rid)}", ok=(200, 404))
                r = await self._call("DELETE", self._bank(mid) + f"/documents/{rid}")
                if r.status_code == 200:
                    erased.append(rid)
            elif rid.startswith(ENTITY):
                unreachable.append(rid)
            else:
                r = await self._call("PATCH", self._bank(mid) + f"/memories/{rid}", body={"state": "invalidated", "reason": "erased"})
                if r.status_code == 200:
                    erased.append(rid)
                    unreachable.append(rid)     # it stays stored: only what it came from can be deleted
        return {"erased": erased, "unreachable": unreachable}

    # ── reads ─────────────────────────────────────────────────────────────────────────────────
    async def get(self, mid, rid, as_of=None):
        if rid.startswith(ENTITY):
            r = await self._call("GET", self._bank(mid) + f"/entities/{rid[len(ENTITY):]}")
            return self._entity_out(r.json()) if r.status_code == 200 and not self._is_label(r.json().get("canonical_name")) else None
        if rid.startswith(PREFIX):
            doc = await self._doc(mid, rid)
            if not doc:
                return None
            if as_of:
                past = [v for v in await self.history(mid, rid) if str(v["time"]["written_at"] or "") <= as_of]
                return {**past[-1], "status": "active"} if past else None
            return self._doc_out(mid, doc)
        r = await self._call("GET", self._bank(mid) + f"/memories/{rid}")
        if r.status_code != 200:
            return None
        u = r.json()
        return self._fact_out(mid, {**u, "fact_type": u.get("type")}, await self._entity_ids(mid), await self._sources(mid, [u]))

    async def history(self, mid, rid):
        head = await self.get(mid, rid)
        if not head:
            raise mp.MemoryError(404, "memory_record_not_found", "No such record in this memory.", "record_id")
        if not rid.startswith(PREFIX):
            return [head]
        doc = await self._doc(mid, rid)
        try:
            kept = json.loads(((doc or {}).get("document_metadata") or {}).get("hr_versions") or "[]")
        except ValueError:
            kept = []
        out = []
        for i, k in enumerate(kept):
            until = kept[i + 1]["at"] if i + 1 < len(kept) else head["time"]["written_at"]
            out.append({**head, "title": k.get("title") or "", "content": k.get("content") or [], "attributes": k.get("attributes") or head["attributes"], "version": k.get("v") or i + 1,
                        "status": "superseded", "supersedes": (k.get("v") or i + 1) - 1 or None, "written_by": k.get("by") or head["written_by"],
                        "time": {**head["time"], **(k.get("world") or {}), "written_at": k.get("at"), "invalidated_at": until}})
        return [*out, head]

    async def prime(self, mid, budget):
        r = await self._call("GET", self._bank(mid) + "/documents", params={"tags": "standing", "limit": 50})
        rows = []
        for d in ((r.json() or {}).get("items") or []) if r.status_code == 200 else []:
            full = await self._doc(mid, str(d["id"]))
            if full and "forgotten" not in (full.get("tags") or []):
                rows.append(self._doc_out(mid, full))
        return mp.within_budget(rows, budget)

    async def list(self, mid, req):
        if req.get("as_of"):
            raise mp.MemoryError(422, "memory_unsupported", "This memory's provider does not list a memory as of a past time.")
        types = [t for t in (req.get("types") or []) if t]
        size, at = int(req.get("limit") or 50), int(req.get("cursor") or 0)
        if types == ["entity"]:
            r = await self._call("GET", self._bank(mid) + "/entities", params={"limit": size, "offset": at})
            doc = r.json() if r.status_code == 200 else {}
            rows = [self._entity_out(e) for e in doc.get("items") or [] if not self._is_label(e.get("canonical_name"))]
            return {"records": rows, "next": str(at + size) if at + size < int(doc.get("total") or 0) else None}
        if types == ["episode"]:
            r = await self._call("GET", self._bank(mid) + "/documents", params={"tags": "t:episode", "limit": size, "offset": at})
            doc = r.json() if r.status_code == 200 else {}
            rows = [self._doc_out(mid, await self._doc(mid, str(d["id"])) or d) for d in doc.get("items") or []]
            if req.get("include") != "all":
                rows = [x for x in rows if x["status"] == "active"]
            return {"records": rows, "next": str(at + size) if at + size < int(doc.get("total") or 0) else None}
        if not types:
            return await self._list_all(mid, req, at, size)
        return await self._list_facts(mid, req, at, size, types)

    async def _list_facts(self, mid, req, at, size, types):
        params = {"limit": size, "offset": at}
        if req.get("include") != "all":
            params["state"] = ACTIVE
        r = await self._call("GET", self._bank(mid) + "/memories/list", params=params)
        doc = r.json() if r.status_code == 200 else {}
        names = await self._entity_ids(mid)
        srcs = await self._sources(mid, doc.get("items") or [])
        seen, rows = set(), []
        for u in doc.get("items") or []:
            x = self._fact_out(mid, u, names, srcs)
            if x["id"] in seen or (types and x["type"] not in types):
                continue
            seen.add(x["id"])
            rows.append(x)
        total = int(doc.get("total") or 0)
        return {"records": rows, "next": str(at + size) if at + size < total else None}

    async def _list_all(self, mid, req, at, size):
        """Every kind in one list, which Hindsight keeps in three places: conversations, then entities, then
        facts, with the cursor a position across them. Facts alone would hide what a person or an agent has
        to be able to see to forget it."""
        rows: list[dict] = []
        start = 0
        for kind in (["episode"], ["entity"], ["fact"]):
            total = await self._kind_total(mid, kind[0])
            end = start + total
            if at + size > start and at < end and len(rows) < size:
                offset, room = max(at - start, 0), size - len(rows)
                page = (await self._list_facts(mid, req, offset, room, None) if kind == ["fact"] else
                        await self.list(mid, {**req, "types": kind, "limit": room, "cursor": str(offset)}))
                rows += page["records"]
            start = end
        return {"records": rows, "next": str(at + size) if at + size < start else None}

    async def _kind_total(self, mid, kind) -> int:
        if kind == "entity":
            r = await self._call("GET", self._bank(mid) + "/entities", params={"limit": 1})
        elif kind == "episode":
            r = await self._call("GET", self._bank(mid) + "/documents", params={"tags": "t:episode", "limit": 1})
        else:
            r = await self._call("GET", self._bank(mid) + "/memories/list", params={"limit": 1, "state": ACTIVE})
        return int((r.json() or {}).get("total") or 0) if r.status_code == 200 else 0

    async def recall(self, mid, req):
        degraded: list[str] = []
        if req.get("as_of"):
            degraded.append("as_of:not_supported")
        query, text = str(req.get("query") or "").strip(), str(req.get("text") or "").strip()
        limit = int(req.get("limit") or 8)
        flt = req.get("filters") or None
        label = str(flt["value"]) if isinstance(flt, dict) and flt.get("field") == "attributes.labels" and flt.get("op") == "contains" else ""
        later = [flt] if flt and not label else []
        if later:
            degraded.append("filters:applied_after_ranking")
        if not query and not text:
            listed = await self.list(mid, {"types": req.get("types"), "limit": max(limit, 50), "include": req.get("include")})
            rows = [x for x in listed["records"] if all(mp.matches(x, f) for f in later) and (not label or mp.matches(x, flt))]
            return {"results": [{"record": x, "memory_id": mid, "score": 1.0, "why": ["filters"]} for x in rows[:limit]], "degraded": degraded, "abstain": False}
        body: dict = {"query": f"{query} {text}".strip(), "budget": "mid", "max_tokens": 4096}
        types = [t for t in (req.get("types") or []) if t]
        if "episode" in types:
            degraded.append("types:episodes_are_not_searched")    # recall reads the facts, not what they came from
        if label:
            body.update(tags=[LABEL + label], tags_match="any_strict")
        elif types:
            # a fact an episode derives carries the episode's tag, so a search for facts reads both
            body.update(tags=[f"t:{t}" for t in types] + (["t:episode"] if "fact" in types else []), tags_match="any_strict")
        r = await self._call("POST", self._bank(mid) + "/memories/recall", body=body)
        if r.status_code != 200:
            if r.status_code == 404:
                return {"results": [], "degraded": degraded, "abstain": False}
            raise HindsightUnavailable("the search did not answer")
        names = await self._entity_ids(mid)
        found = (r.json() or {}).get("results") or []
        srcs = await self._sources(mid, found)
        seen, results = set(), []
        for u in found:
            x = self._fact_out(mid, {**u, "fact_type": u.get("type"), "state": ACTIVE}, names, srcs)
            if x["id"] in seen or (types and x["type"] not in types) or not all(mp.matches(x, f) for f in later):
                continue
            seen.add(x["id"])
            s = u.get("scores") or {}
            why = [w for w, on in (("query", query and float(s.get("semantic") or 0) > 0), ("text", float(s.get("keyword") or 0) > 0),
                                   ("filters", bool(later))) if on] or ["query"]
            results.append({"record": x, "memory_id": mid, "score": s.get("final"), "why": why})
        return {"results": results[:limit], "degraded": degraded, "abstain": False}

    # ── its labels: a vocabulary the extraction tags each derived fact with ───────────────────
    async def apply_schema(self, mid, schema):
        await self._ensure(mid)
        values = [{"value": str(t.get("name") or ""), "description": str(t.get("description") or "")}
                  for t in schema.get("types") or [] if t.get("name")]
        labels = {"attributes": [{"key": LABEL[:-1], "description": LABEL_ASK, "type": "multi-values", "optional": True, "tag": True, "values": values}]} if values else None
        r = await self._call("PATCH", self._bank(mid) + "/config", body={"updates": {"entity_labels": labels}})
        if r.status_code != 200:
            raise HindsightUnavailable("the labels were not stored")

    # ── consolidation: Hindsight's own, started and read back ─────────────────────────────────
    def _run(self, mid: str, op: dict, trigger: str = "manual") -> dict:
        st = str(op.get("status") or "running")
        return {"id": str(op.get("id") or op.get("operation_id") or ""), "object": "memory.consolidation", "memory_id": mid,
                "status": "completed" if st == "completed" else "failed" if st == "failed" else "running", "trigger": trigger,
                "started_at": op.get("created_at"), "finished_at": op.get("completed_at"), "changes": {"created": 0, "superseded": 0, "forgotten": 0},
                "usage": {"input_tokens": 0, "output_tokens": 0}}

    async def consolidate(self, mid, budget, trigger):
        r = await self._call("POST", self._bank(mid) + "/consolidate", body={})
        if r.status_code != 200:
            raise HindsightUnavailable("consolidation did not start")
        return self._run(mid, {**(r.json() or {}), "status": "running"}, trigger)

    async def consolidations(self, mid):
        r = await self._call("GET", self._bank(mid) + "/operations", params={"type": "consolidation", "limit": 20})
        items = (r.json() or {}).get("operations") or (r.json() or {}).get("items") or [] if r.status_code == 200 else []
        return [self._run(mid, o) for o in items]

    async def consolidation(self, mid, run):
        r = await self._call("GET", self._bank(mid) + f"/operations/{run}")
        return self._run(mid, {**r.json(), "id": run}) if r.status_code == 200 else None

    async def consolidation_changes(self, mid, run):
        return []
