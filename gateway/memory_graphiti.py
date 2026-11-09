"""Graphiti (getzep/graphiti, Apache-2.0), the engine behind Zep, as a memory provider: a temporal graph.

Graphiti reads an episode and extracts entities and facts between them, each fact with when it became
true and when it stopped. It is a library and its own REST server takes no entity types, so this talks to
the small server in deploy/memories/graphiti, which is the same library. Everything here was measured
against that server on 2026-11-04.

  one memory = one database file in the server's store (LadybugDB). `container`.
  observe  = an episode, with this memory's schema as the types to extract. It answers when done, with
      what it found. `derivation: write_time`, and the episode stays, so `keeps_episodes`.
  a derived record = a fact (`edge_<uuid>`, type `fact`), an entity (`node_<uuid>`, type `entity`, labelled
      with its schema type) or an episode (`ep_<uuid>`). A fact references the two entities it joins and
      the episodes it came from, so these references are the graph.
  remember = a stated node, words kept as written, found by search like any entity. An entity it references
      gets a real edge in the graph, named by the reference's `rel`. Graphiti also reads a copy, an episode named
      `hr_read:<node>` taken in the background (11-06, so each system is used as it is built to be): the entities
      and facts it finds come from the stated record, never from the copy, which is not shown. Graphiti's merging
      can rewrite a node's summary, so a stated node keeps its words in `hr_text`. Revising re-reads; forgetting
      or erasing it takes the copy, and what came only from it, away.
  holds    = Graphiti's own: a new fact that contradicts an old one closes it (`invalid_at`), and the old
      one stays readable. A closed fact is `superseded`, and `time.valid_to` says when.
  forget   = a fact closed now; a stated node marked. erase = deleted. An erased fact's words can still be in
      the episode it came from, so a fact from an episode is reported `unreachable`.
  schema   = what extraction reads. This is the provider where a schema changes what is kept: `guides`, with
      properties and relations.
"""
from __future__ import annotations

import datetime as _dt
import json
import time
import uuid

import httpx

import memory_plane as mp

TIMEOUT_S = 180
NODE, EDGE, EPISODE = "node_", "edge_", "ep_"
SESSION = " session:"   # how an episode's source names the task it came from (observe), after who sent it
READ = "hr_read:"    # the name of the episode Graphiti reads a stated record as, followed by the node's uuid
LINK = "hr_link"     # on an edge made for a record's reference, not for a fact
# Tests set an httpx transport here so every call is exercised without a server.
transport: httpx.BaseTransport | None = None
# Every other call opens its connections through the gateway's checked network (app.py sets this), so an address
# that passed the check when it was saved and later resolves somewhere internal (a DNS rebind) is refused at connect.
checked_transport = None


def _transport():
    return transport if transport is not None else (checked_transport() if checked_transport else None)


class GraphitiUnavailable(mp.MemoryError):
    def __init__(self, why: str):
        super().__init__(502, "memory_unavailable", f"Graphiti did not answer: {why}"[:300])


async def check(api_key: str, base_url: str = "") -> str:
    """'' when the Graphiti server answers at this address, else why not, in a sentence."""
    if not base_url:
        return "Graphiti needs the address of your server."
    try:
        async with httpx.AsyncClient(timeout=20, transport=_transport()) as c:
            r = await c.get(base_url.rstrip("/") + "/check", headers={"Authorization": f"Bearer {api_key}"} if api_key else {})
    except httpx.HTTPError as e:
        return f"Graphiti could not be reached at that address: {type(e).__name__}."
    return "" if r.status_code == 200 else f"Graphiti refused the connection (HTTP {r.status_code})."


def _is_link(e: dict) -> bool:
    return bool((e.get("attributes") or {}).get(LINK))


def _now() -> str:
    d = _dt.datetime.now(_dt.timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


class Graphiti(mp.Provider):
    id = "graphiti"

    def __init__(self, base_url: str = "", api_key: str = "", org: str = ""):
        self.base, self.key, self.org = base_url.rstrip("/"), api_key, org
        self._copies_at: dict[str, tuple[float, dict[str, str], set[str]]] = {}
        self._eps_at: dict[str, tuple[float, list[dict]]] = {}

# What Graphiti itself makes and how it links it: the part of a memory's schema nobody sets. The console draws it locked
# beside what a person can set; record types and reference rels as this adapter answers them.
    BUILTIN = {
        "types": [
            {"name": "episode", "description": "A conversation or task Graphiti read, kept as it was given."},
            {"name": "entity", "description": "A person, place or thing Graphiti found. The types you add here are kinds of entity."},
            {"name": "fact", "description": "A statement that joins two entities, with when it was true. The relations you add here are kinds of fact."},
        ],
        "relations": [
            {"name": "about", "from": "fact", "to": "entity", "description": "The two entities a fact joins."},
            {"name": "derived_from", "from": "fact", "to": "episode", "description": "Where Graphiti read it."},
            {"name": "derived_from", "from": "entity", "to": "episode", "description": "Where Graphiti read it."},
        ],
    }

    def capabilities(self) -> dict:
        return {"id": self.id, "isolation": "container", "derivation": "write_time",
                "observe": {"keeps_episodes": True, "answers": "records"},
                "recall": {"signals": ["query", "text", "filters"], "abstain": False,
                           "filters": {"native": [], "applied_after_ranking": "every filter"}},
                "history": {"content": "versions", "structure": "versions", "emulated": True}, "as_of": "none",
                "revise": "native", "forget": "native", "erase": {"unreachable": "reported"},
                "prime": True, "consolidate": False, "holds": True, "queries": {"named": False, "free": None},
                "types": False, "graph": {"entities": "derived"},
                "schema": {"mode": "guides", "properties": True, "relations": True, "builtin": self.BUILTIN},
                "content": {"media": ["text/*"], "describes": []}}

    async def bind(self, org, workspace):
        fields = await mp.CREDENTIALS(org, workspace, self.id) if mp.CREDENTIALS else None
        base = str((fields or {}).get("base_url") or "").strip().rstrip("/")
        if not base:
            raise mp.MemoryError(503, "memory_unavailable", "Graphiti is not connected for this workspace: connect it with your server's address.")
        return Graphiti(base, str((fields or {}).get("api_key") or ""), org)

    async def _call(self, method: str, path: str, *, body=None, params=None, ok=(200,)) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_S, transport=_transport()) as c:
                r = await c.request(method, self.base + mp.vendor_path(path), json=body, params=params, headers=headers)
        except httpx.HTTPError as e:
            raise GraphitiUnavailable(type(e).__name__)
        if r.status_code in ok or r.status_code == 404:
            return r
        if r.status_code in (401, 403):
            raise mp.MemoryError(503, "memory_unavailable", "Graphiti refused this workspace's key: reconnect it.")
        raise GraphitiUnavailable(f"HTTP {r.status_code}")

    # ── one shape in, one shape out ───────────────────────────────────────────────────────────
    def _node_out(self, mid: str, n: dict, copies: dict[str, str] | None = None) -> dict:
        a = n.get("attributes") or {}
        stated = bool(a.get("hr_stated"))
        def js(k, d):
            try:
                return json.loads(a.get(k) or d)
            except (TypeError, ValueError):
                return json.loads(d)
        label = next((x for x in n.get("labels") or [] if x != "Entity"), "")
        status = str(a.get("hr_status") or "active")
        version = int(a.get("hr_version") or 1)
        plain = {k: v for k, v in a.items() if not str(k).startswith("hr_")}
        attrs = js("hr_attributes", "{}") if stated else {**plain, **({"entity_type": label} if label else {})}
        rtype = str(a.get("hr_type") or "entity")
        body = str((a.get("hr_text") if stated and a.get("hr_text") is not None else n.get("summary")) or "")
        refs = js("hr_refs", "[]") + self._from(mid, n.get("episodes") or [], copies, NODE + str(n["uuid"]))
        # A stated record kept without a title has no `hr_title`, so its title is empty. str() of the missing value
        # read "None", and the console showed that word as the record's heading (sslip, 11-09).
        title = a.get("hr_title") if stated else n.get("name")
        title = "" if title is None or (stated and str(title) == "None") else str(title)
        return {"id": NODE + str(n["uuid"]), "type": rtype, "title": title,
                "content": [{"type": "text", "text": body}] if body else [], "attributes": attrs, "references": refs, "version": version,
                "status": status, "supersedes": version - 1 if version > 1 else None,
                "time": {"valid_from": a.get("hr_valid_from"), "valid_to": a.get("hr_valid_to"), "written_at": a.get("hr_written_at") or n.get("created_at"),
                         "invalidated_at": a.get("hr_written_at") if status != "active" else None},
                "written_by": js("hr_writer", json.dumps({"kind": "provider", "id": self.id}))}

    @staticmethod
    def _from(mid: str, episodes: list, copies: dict[str, str] | None, me: str = "") -> list[dict]:
        """What a record came from: its episodes, a stated record's copy read as that record, each once. A stated
        node Graphiti matched in its own copy didn't come from itself."""
        out: list[dict] = []
        for x in episodes:
            ref = {"rel": "derived_from", "memory_id": mid, "record_id": (copies or {}).get(str(x)) or EPISODE + str(x)}
            if ref["record_id"] != me and ref not in out:
                out.append(ref)
        return out

    def _facts_out(self, mid: str, edges: list[dict], copies: dict[str, str] | None = None) -> list[dict]:
        """The edges that are facts. An edge made for a record's reference (_edges_for) is how the
        graph walks to it: the reference is already on the record, and nobody stated it as a fact."""
        return [self._edge_out(mid, e, copies) for e in edges if not _is_link(e)]

    def _edge_out(self, mid: str, e: dict, copies: dict[str, str] | None = None) -> dict:
        closed = e.get("invalid_at") or e.get("expired_at")
        refs = [{"rel": "about", "memory_id": mid, "record_id": NODE + str(e[k])} for k in ("source", "target") if e.get(k)]
        refs += self._from(mid, e.get("episodes") or [], copies)
        a = e.get("attributes") or {}
        return {"id": EDGE + str(e["uuid"]), "type": "fact", "title": "", "content": [{"type": "text", "text": str(e.get("fact") or "")}],
                "attributes": {"predicate": e.get("name"), **{k: v for k, v in a.items() if not str(k).startswith("hr_")}}, "references": refs, "version": 1,
                "status": "forgotten" if a.get("hr_forgotten") else "superseded" if closed else "active", "supersedes": None,
                "time": {"valid_from": e.get("valid_at"), "valid_to": e.get("invalid_at"), "written_at": e.get("created_at"), "invalidated_at": e.get("expired_at")},
                "written_by": {"kind": "provider", "id": self.id}}

    def _episode_out(self, mid: str, x: dict) -> dict:
        closed = x.get("forgotten_at")
        # the task it came from, as observe named it in its source; a fact or an entity names its episodes, so this is
        # how a later turn of the same task knows them for its own (memory_tools.same_session)
        src = str(x.get("source_description") or "")
        session = src.split(SESSION, 1)[1].strip() if SESSION in src else ""
        return {"id": EPISODE + str(x["uuid"]), "type": "episode", "title": str(x.get("name") or ""),
                "content": [{"type": "text", "text": str(x.get("content") or "")}],
                "attributes": {"session_id": session} if session else {}, "references": [], "version": 1,
                "status": "forgotten" if closed else "active", "supersedes": None,
                "time": {"valid_from": x.get("valid_at"), "valid_to": None, "written_at": x.get("created_at"), "invalidated_at": closed},
                "written_by": {"kind": "provider", "id": self.id}}

    async def _episodes(self, mid: str) -> list[dict]:
        r = await self._call("GET", f"/groups/{mid}/episodes", params={"limit": 1000})
        return r.json() if r.status_code == 200 else []

    async def _copies(self, mid: str, need=(), episodes: list[dict] | None = None) -> dict[str, str]:
        """Each copy Graphiti read of a stated record, as that record: episode uuid -> `node_<uuid>`. Read again when
        an episode asked about isn't in it yet, since a copy is read a few seconds after its record is written."""
        hit = self._copies_at.get(mid)
        if episodes is None and hit and time.time() - hit[0] < 30 and all(str(x) in hit[1] or str(x) in hit[2] for x in need):
            return hit[1]
        eps = episodes if episodes is not None else await self._episodes(mid)
        out = {str(x["uuid"]): NODE + str(x["name"])[len(READ):] for x in eps if str(x.get("name") or "").startswith(READ)}
        self._copies_at[mid] = (time.time(), out, {str(x["uuid"]) for x in eps})
        return out

    @staticmethod
    def _is_copy(x: dict) -> bool:
        return str(x.get("name") or "").startswith(READ)

    async def _extraction(self, mid: str) -> dict:
        """This memory's schema as what Graphiti extracts into."""
        schema = await self._schema(mid)
        rels = schema.get("relations") or []
        names = {str(t.get("id") or t.get("name")): str(t.get("name")) for t in schema.get("types") or []}
        emap: dict[tuple[str, str], list[str]] = {}
        for rel in rels:
            pair = (names.get(str(rel.get("from")), str(rel.get("from"))), names.get(str(rel.get("to")), str(rel.get("to"))))
            emap.setdefault(pair, []).append(str(rel.get("name")))
        return {"entity_types": schema.get("types") or [], "edge_types": [{"name": x.get("name"), "description": x.get("description"), "properties": x.get("properties") or []} for x in rels],
                "edge_type_map": [{"from": a, "to": b, "names": n} for (a, b), n in emap.items()]}

    async def _read_copy(self, mid: str, node: str, title: str, said: str, when: str | None, writer: dict) -> None:
        """Graphiti reads what was stated, as it reads anything it is given, in the background. A copy not taken
        costs what Graphiti would have found in it, never the record."""
        text = f"{title}\n\n{said}".strip() if title and title not in said else said
        if not text.strip():
            return
        try:
            await self._call("POST", "/episodes", body={"group_id": mid, "content": text, "name": READ + node, "background": True,
                                                        "source_description": f"{writer.get('kind')}:{writer.get('id')}",
                                                        **({"reference_time": str(when)} if when else {}), **await self._extraction(mid)})
        except mp.MemoryError:
            pass
        self._copies_at.pop(mid, None)

    async def _drop_copies(self, mid: str, node: str) -> None:
        for ep, rid in (await self._copies(mid, episodes=await self._episodes(mid))).items():
            if rid == NODE + node:
                await self._call("DELETE", f"/groups/{mid}/episodes/{ep}")
        self._copies_at.pop(mid, None)

    async def _schema(self, mid: str) -> dict:
        m = await mp._load(self.org, mid) if self.org else None
        try:
            return json.loads((m or {}).get("schema") or "{}")
        except (TypeError, ValueError):
            return {}

    # ── lifecycle ─────────────────────────────────────────────────────────────────────────────
    async def drop(self, mid):
        await self._call("DELETE", f"/groups/{mid}")

    async def count(self, mid):
        total = 0
        for kind in ("nodes", "edges"):
            r = await self._call("GET", f"/groups/{mid}/{kind}", params={"limit": 1000})
            total += sum(1 for x in r.json() if not _is_link(x)) if r.status_code == 200 else 0
        return total

    # ── writes ────────────────────────────────────────────────────────────────────────────────
    async def _edges_for(self, mid: str, source: str, refs: list) -> None:
        """A reference between two of this memory's entities is a real edge in the graph, named by its rel."""
        for x in refs or []:
            rid = str(x.get("record_id") or "")
            if str(x.get("memory_id") or mid) == mid and rid.startswith(NODE) and source.startswith(NODE):
                await self._call("POST", "/edges", body={"group_id": mid, "source": source[len(NODE):], "target": rid[len(NODE):],
                                                         "name": str(x.get("rel") or "RELATES_TO"), "fact": str(x.get("rel") or "related"), "attributes": {LINK: "1"}})

    async def remember(self, mid, record, writer):
        said = mp.text_of(record.get("content") or [])
        title = str(record.get("title") or "")
        attrs = record.get("attributes") or {}
        a = {"hr_stated": "1", "hr_type": record.get("type") or "fact", "hr_version": 1, "hr_written_at": _now(),
             "hr_writer": json.dumps({k: v for k, v in writer.items() if v}, separators=(",", ":")),
             "hr_attributes": json.dumps(attrs, separators=(",", ":")), "hr_refs": json.dumps(record.get("references") or [], separators=(",", ":"))}
        if title:
            a["hr_title"] = title
        for k in ("valid_from", "valid_to"):
            if (record.get("time") or {}).get(k):
                a["hr_" + k] = record["time"][k]
        a["hr_text"] = said
        label = str(attrs.get("entity_type") or "")
        r = await self._call("POST", "/nodes", body={"group_id": mid, "name": title or said[:120] or uuid.uuid4().hex, "summary": said, "labels": [label] if label.isidentifier() else [], "attributes": a})
        if r.status_code != 200:
            raise GraphitiUnavailable("the record was not stored")
        out = self._node_out(mid, r.json())
        await self._edges_for(mid, out["id"], record.get("references") or [])
        await self._read_copy(mid, str(r.json()["uuid"]), title, said, (record.get("time") or {}).get("valid_from"), writer)
        return out

    async def observe(self, mid, episodes, writer):
        extraction = await self._extraction(mid)
        records = []
        for e in episodes:
            text = "\n".join(f"{p.get('role')}: {p['text']}" if p.get("role") else str(p["text"]) for p in e.get("content") or [] if p.get("text"))
            session = str((e.get("attributes") or {}).get("session_id") or "")
            r = await self._call("POST", "/episodes", body={
                "group_id": mid, "content": text,
                "source_description": f"{writer.get('kind')}:{writer.get('id')}" + (SESSION + session if session else ""),
                **({"reference_time": str((e.get("time") or {})["valid_from"])} if (e.get("time") or {}).get("valid_from") else {}),
                # Graphiti's own guidance for its extraction, placed in its entity and fact prompts (add_episode's
                # custom_extraction_instructions; deploy/memories/graphiti passes it on)
                "custom_extraction_instructions": mp.EXTRACTION_GUIDE,
                **extraction})
            if r.status_code != 200:
                raise GraphitiUnavailable("the episode was not taken")
            d = r.json()
            self._eps_at.pop(mid, None)
            records.append(self._episode_out(mid, d["episode"]))
            records += [self._node_out(mid, n) for n in d.get("nodes") or []]
            records += [self._edge_out(mid, x) for x in d.get("edges") or []]
        return {"records": records, "job": None}

    async def revise(self, mid, rid, patch, writer):
        cur = await self.get(mid, rid)
        if not cur or cur["status"] != "active":
            raise mp.MemoryError(404, "memory_record_not_found", "No such record in this memory.", "record_id")
        said = mp.text_of(patch["content"]) if patch.get("content") is not None else mp.text_of(cur["content"])
        if rid.startswith(EDGE):
            r = await self._call("PUT", f"/groups/{mid}/edges/{rid[len(EDGE):]}", body={"fact": said})
            if r.status_code != 200:
                raise GraphitiUnavailable("the revision was not stored")
            return {**self._edge_out(mid, r.json()), "version": cur["version"] + 1, "supersedes": cur["version"]}
        if not rid.startswith(NODE):
            raise mp.MemoryError(422, "memory_unsupported", "An episode is what happened: it isn't revised.")
        r0 = await self._call("GET", f"/groups/{mid}/nodes/{rid[len(NODE):]}")
        a = dict((r0.json() or {}).get("attributes") or {})
        try:
            kept = json.loads(a.get("hr_versions") or "[]")
        except ValueError:
            kept = []
        kept.append({"v": cur["version"], "title": cur["title"], "content": cur["content"], "attributes": cur["attributes"], "at": cur["time"]["written_at"], "by": cur["written_by"],
                     "world": {k: cur["time"][k] for k in ("valid_from", "valid_to")}})
        for k, v in (patch.get("time") or {}).items():
            if k in ("valid_from", "valid_to"):
                a["hr_" + k] = v
        title = patch.get("title", cur["title"])
        attrs = {**cur["attributes"], **(patch.get("attributes") or {})}
        refs = patch.get("references", cur["references"])
        a.update({"hr_stated": "1", "hr_type": cur["type"], "hr_version": cur["version"] + 1, "hr_written_at": _now(), "hr_versions": json.dumps(kept, separators=(",", ":")),
                  "hr_writer": json.dumps({k: v for k, v in writer.items() if v}, separators=(",", ":")), "hr_attributes": json.dumps(attrs, separators=(",", ":")),
                  "hr_refs": json.dumps(refs, separators=(",", ":"))})
        if title:
            a["hr_title"] = title
        a["hr_text"] = said
        r = await self._call("PUT", f"/groups/{mid}/nodes/{rid[len(NODE):]}", body={"name": title or said[:120], "summary": said, "attributes": a})
        if r.status_code != 200:
            raise GraphitiUnavailable("the revision was not stored")
        if said != mp.text_of(cur["content"]) or title != cur["title"]:
            await self._drop_copies(mid, rid[len(NODE):])
            await self._read_copy(mid, rid[len(NODE):], title, said, a.get("hr_valid_from"), writer)
        return {**self._node_out(mid, r.json()), "supersedes": cur["version"]}

    async def forget(self, mid, rid, writer):
        cur = await self.get(mid, rid)
        if not cur or cur["status"] != "active":
            raise mp.MemoryError(404, "memory_record_not_found", "No such record in this memory.", "record_id")
        if rid.startswith(EDGE):
            r = await self._call("POST", f"/groups/{mid}/edges/{rid[len(EDGE):]}/close", body={"forgotten": True})
            return self._edge_out(mid, r.json())
        if rid.startswith(EPISODE):
            at = _now()
            r = await self._call("POST", f"/groups/{mid}/episodes/{rid[len(EPISODE):]}/forget", body={"at": at})
            self._eps_at.pop(mid, None)
            if r.status_code != 200:
                raise GraphitiUnavailable("the episode was not closed")
            return {**cur, "status": "forgotten", "time": {**cur["time"], "invalidated_at": at}}
        r0 = await self._call("GET", f"/groups/{mid}/nodes/{rid[len(NODE):]}")
        n = r0.json()
        a = {**(n.get("attributes") or {}), "hr_status": "forgotten", "hr_written_at": _now(), "hr_forgotten_by": f"{writer.get('kind')}:{writer.get('id')}"}
        r = await self._call("PUT", f"/groups/{mid}/nodes/{rid[len(NODE):]}", body={"name": n.get("name"), "summary": n.get("summary"), "attributes": a})
        # what Graphiti learned only from it leaves with it, so a search can't bring it back
        await self._drop_copies(mid, rid[len(NODE):])
        return self._node_out(mid, r.json())

    async def erase(self, mid, rids):
        erased, unreachable = [], []
        for rid in rids:
            cur = await self.get(mid, rid)
            if not cur:
                continue
            if rid.startswith(EDGE):
                r = await self._call("DELETE", f"/groups/{mid}/edges/{rid[len(EDGE):]}")
                if any(x["rel"] == "derived_from" for x in cur["references"]):
                    unreachable.append(rid)      # its words can still be in the episode it came from
            elif rid.startswith(NODE):
                await self._drop_copies(mid, rid[len(NODE):])
                r = await self._call("DELETE", f"/groups/{mid}/nodes/{rid[len(NODE):]}")
            else:
                r = await self._call("DELETE", f"/groups/{mid}/episodes/{rid[len(EPISODE):]}")
                self._eps_at.pop(mid, None)
            if r.status_code == 200:
                erased.append(rid)
        return {"erased": erased, "unreachable": unreachable}

    # ── reads ─────────────────────────────────────────────────────────────────────────────────
    async def get(self, mid, rid, as_of=None):
        for prefix, kind, out in ((NODE, "nodes", self._node_out), (EDGE, "edges", self._edge_out)):
            if rid.startswith(prefix):
                r = await self._call("GET", f"/groups/{mid}/{kind}/{rid[len(prefix):]}")
                if r.status_code != 200:
                    return None
                return out(mid, r.json(), await self._copies(mid, r.json().get("episodes") or []))
        if rid.startswith(EPISODE):
            # one listing for the episodes asked about together (a turn's start asks for each fact's episodes at once,
            # memory_tools.same_session), and read again after a few seconds, since a new one may have come
            hit = self._eps_at.get(mid)
            if not hit or time.time() - hit[0] > 5 or not any(str(x.get("uuid")) == rid[len(EPISODE):] for x in hit[1]):
                r = await self._call("GET", f"/groups/{mid}/episodes", params={"limit": 1000})
                hit = (time.time(), r.json() if r.status_code == 200 else [])
                self._eps_at[mid] = hit
            found = next((x for x in hit[1] if str(x.get("uuid")) == rid[len(EPISODE):]), None)
            return self._episode_out(mid, found) if found else None
        return None

    async def history(self, mid, rid):
        head = await self.get(mid, rid)
        if not head:
            raise mp.MemoryError(404, "memory_record_not_found", "No such record in this memory.", "record_id")
        if not rid.startswith(NODE):
            return [head]
        r = await self._call("GET", f"/groups/{mid}/nodes/{rid[len(NODE):]}")
        try:
            kept = json.loads(((r.json() or {}).get("attributes") or {}).get("hr_versions") or "[]")
        except ValueError:
            kept = []
        out = []
        for i, k in enumerate(kept):
            until = kept[i + 1]["at"] if i + 1 < len(kept) else head["time"]["written_at"]
            out.append({**head, "title": k.get("title") or "", "content": k.get("content") or [], "attributes": k.get("attributes") or head["attributes"], "version": k.get("v") or i + 1, "status": "superseded",
                        "supersedes": (k.get("v") or i + 1) - 1 or None, "written_by": k.get("by") or head["written_by"], "time": {**head["time"], **(k.get("world") or {}), "written_at": k.get("at"), "invalidated_at": until}})
        return [*out, head]

    async def prime(self, mid, budget):
        r = await self._call("GET", f"/groups/{mid}/nodes", params={"limit": 1000})
        rows = [x for x in (self._node_out(mid, n) for n in (r.json() if r.status_code == 200 else [])) if x["status"] == "active" and x["attributes"].get("standing") is True]
        return mp.within_budget(rows, budget)

    async def _everything(self, mid: str, types: list[str]) -> list[dict]:
        rows: list[dict] = []
        wants = lambda *ts: not types or any(t in types for t in ts)       # noqa: E731
        eps = await self._episodes(mid)
        copies = await self._copies(mid, episodes=eps)
        r = await self._call("GET", f"/groups/{mid}/nodes", params={"limit": 1000})
        rows += [x for x in (self._node_out(mid, n, copies) for n in (r.json() if r.status_code == 200 else [])) if not types or x["type"] in types]
        if wants("fact"):
            r = await self._call("GET", f"/groups/{mid}/edges", params={"limit": 1000})
            rows += self._facts_out(mid, r.json() if r.status_code == 200 else [], copies)
        if wants("episode"):
            # a copy Graphiti read of a stated record is that record, already listed
            rows += [self._episode_out(mid, x) for x in eps if not self._is_copy(x)]
        rows.sort(key=lambda x: str(x["time"]["written_at"] or ""), reverse=True)
        return rows

    async def list(self, mid, req):
        if req.get("as_of"):
            raise mp.MemoryError(422, "memory_unsupported", "This memory's provider does not list a memory as of a past time.")
        types = [t for t in (req.get("types") or []) if t]
        rows = await self._everything(mid, types)
        if req.get("include") != "all":
            rows = [x for x in rows if x["status"] == "active"]
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
            rows = [x for x in await self._everything(mid, types) if keep(x)]
            return {"results": [{"record": x, "memory_id": mid, "score": 1.0, "why": ["filters"]} for x in rows[:limit]], "degraded": degraded, "abstain": False}
        r = await self._call("POST", "/search", body={"group_id": mid, "query": f"{query} {text}".strip(), "limit": max(limit * 2, 10)})
        d = r.json() if r.status_code == 200 else {}
        seen = [x for e in (d.get("edges") or []) + (d.get("nodes") or []) for x in e.get("episodes") or []]
        copies = await self._copies(mid, seen)
        rows = self._facts_out(mid, d.get("edges") or [], copies) + [self._node_out(mid, n, copies) for n in d.get("nodes") or []] + \
            [self._episode_out(mid, x) for x in d.get("episodes") or [] if not self._is_copy(x)]
        why = [w for w, on in (("query", query), ("text", text), ("filters", later)) if on]
        kept = [x for x in rows if keep(x)]
        return {"results": [{"record": x, "memory_id": mid, "score": round(1 - i / max(len(kept), 1), 4), "why": why} for i, x in enumerate(kept)][:limit], "degraded": degraded, "abstain": False}
