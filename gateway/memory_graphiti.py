"""Graphiti (getzep/graphiti, Apache-2.0), the engine behind Zep, as a memory provider: a temporal graph.

Graphiti reads an episode and extracts entities and facts between them, each fact with when it became
true and when it stopped. It is a library and its own REST server takes no entity types, so this talks to
the small server in deploy/memories/graphiti, which is the same library. Everything here was measured
against that server on 2026-11-04.

  one memory = one graph (FalkorDB database). `container`.
  observe  = an episode, with this memory's schema as the types to extract. It answers when done, with
      what it found. `derivation: write_time`, and the episode stays, so `keeps_episodes`.
  a derived record = a fact (`edge_<uuid>`, type `fact`), an entity (`node_<uuid>`, type `entity`, labelled
      with its schema type) or an episode (`ep_<uuid>`). A fact references the two entities it joins and
      the episodes it came from, so these references are the graph.
  remember = a stated node, words kept as written, no model call. It is found by search like any entity.
      An entity it references gets a real edge in the graph, named by the reference's `rel`.
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
import uuid

import httpx

import memory_plane as mp

TIMEOUT_S = 180
NODE, EDGE, EPISODE = "node_", "edge_", "ep_"
# Tests set an httpx transport here so every call is exercised without a server.
transport: httpx.BaseTransport | None = None


class GraphitiUnavailable(mp.MemoryError):
    def __init__(self, why: str):
        super().__init__(502, "memory_unavailable", f"Graphiti did not answer: {why}"[:300])


async def check(api_key: str, base_url: str = "") -> str:
    """'' when the Graphiti server answers at this address, else why not, in a sentence."""
    if not base_url:
        return "Graphiti needs the address of your server."
    try:
        async with httpx.AsyncClient(timeout=20, transport=transport) as c:
            r = await c.get(base_url.rstrip("/") + "/check", headers={"Authorization": f"Bearer {api_key}"} if api_key else {})
    except httpx.HTTPError as e:
        return f"Graphiti could not be reached at that address: {type(e).__name__}."
    return "" if r.status_code == 200 else f"Graphiti refused the connection (HTTP {r.status_code})."


def _now() -> str:
    d = _dt.datetime.now(_dt.timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


class Graphiti(mp.Provider):
    id = "graphiti"

    def __init__(self, base_url: str = "", api_key: str = "", org: str = ""):
        self.base, self.key, self.org = base_url.rstrip("/"), api_key, org

    def capabilities(self) -> dict:
        return {"id": self.id, "isolation": "container", "derivation": "write_time",
                "observe": {"keeps_episodes": True, "answers": "records"},
                "recall": {"signals": ["query", "text", "filters"], "abstain": False,
                           "filters": {"native": [], "applied_after_ranking": "every filter"}},
                "history": {"content": "versions", "structure": "versions", "emulated": True}, "as_of": "none",
                "revise": "native", "forget": "native", "erase": {"unreachable": "reported"},
                "prime": True, "consolidate": False, "holds": True, "queries": {"named": False, "free": None},
                "types": False, "graph": {"entities": "derived"},
                "schema": {"mode": "guides", "properties": True, "relations": True},
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
            async with httpx.AsyncClient(timeout=TIMEOUT_S, transport=transport) as c:
                r = await c.request(method, self.base + mp.vendor_path(path), json=body, params=params, headers=headers)
        except httpx.HTTPError as e:
            raise GraphitiUnavailable(type(e).__name__)
        if r.status_code in ok or r.status_code == 404:
            return r
        if r.status_code in (401, 403):
            raise mp.MemoryError(503, "memory_unavailable", "Graphiti refused this workspace's key: reconnect it.")
        raise GraphitiUnavailable(f"HTTP {r.status_code}")

    # ── one shape in, one shape out ───────────────────────────────────────────────────────────
    def _node_out(self, mid: str, n: dict) -> dict:
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
        body = str(n.get("summary") or "")
        return {"id": NODE + str(n["uuid"]), "type": rtype, "title": str(a.get("hr_title") if stated else n.get("name") or "") or "",
                "content": [{"type": "text", "text": body}] if body else [], "attributes": attrs, "references": js("hr_refs", "[]"), "version": version,
                "status": status, "supersedes": version - 1 if version > 1 else None,
                "time": {"valid_from": a.get("hr_valid_from"), "valid_to": a.get("hr_valid_to"), "written_at": a.get("hr_written_at") or n.get("created_at"),
                         "invalidated_at": a.get("hr_written_at") if status != "active" else None},
                "written_by": js("hr_writer", json.dumps({"kind": "provider", "id": self.id}))}

    def _edge_out(self, mid: str, e: dict) -> dict:
        closed = e.get("invalid_at") or e.get("expired_at")
        refs = [{"rel": "about", "memory_id": mid, "record_id": NODE + str(e[k])} for k in ("source", "target") if e.get(k)]
        refs += [{"rel": "derived_from", "memory_id": mid, "record_id": EPISODE + str(x)} for x in e.get("episodes") or []]
        a = e.get("attributes") or {}
        return {"id": EDGE + str(e["uuid"]), "type": "fact", "title": "", "content": [{"type": "text", "text": str(e.get("fact") or "")}],
                "attributes": {"predicate": e.get("name"), **{k: v for k, v in a.items() if not str(k).startswith("hr_")}}, "references": refs, "version": 1,
                "status": "forgotten" if a.get("hr_forgotten") else "superseded" if closed else "active", "supersedes": None,
                "time": {"valid_from": e.get("valid_at"), "valid_to": e.get("invalid_at"), "written_at": e.get("created_at"), "invalidated_at": e.get("expired_at")},
                "written_by": {"kind": "provider", "id": self.id}}

    def _episode_out(self, mid: str, x: dict) -> dict:
        return {"id": EPISODE + str(x["uuid"]), "type": "episode", "title": str(x.get("name") or ""),
                "content": [{"type": "text", "text": str(x.get("content") or "")}], "attributes": {}, "references": [], "version": 1, "status": "active", "supersedes": None,
                "time": {"valid_from": x.get("valid_at"), "valid_to": None, "written_at": x.get("created_at"), "invalidated_at": None},
                "written_by": {"kind": "provider", "id": self.id}}

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
            total += len(r.json()) if r.status_code == 200 else 0
        return total

    # ── writes ────────────────────────────────────────────────────────────────────────────────
    async def _edges_for(self, mid: str, source: str, refs: list) -> None:
        """A reference between two of this memory's entities is a real edge in the graph, named by its rel."""
        for x in refs or []:
            rid = str(x.get("record_id") or "")
            if str(x.get("memory_id") or mid) == mid and rid.startswith(NODE) and source.startswith(NODE):
                await self._call("POST", "/edges", body={"group_id": mid, "source": source[len(NODE):], "target": rid[len(NODE):],
                                                         "name": str(x.get("rel") or "RELATES_TO"), "fact": str(x.get("fact") or x.get("rel") or "related")})

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
        label = str(attrs.get("entity_type") or "")
        r = await self._call("POST", "/nodes", body={"group_id": mid, "name": title or said[:120] or uuid.uuid4().hex, "summary": said, "labels": [label] if label.isidentifier() else [], "attributes": a})
        if r.status_code != 200:
            raise GraphitiUnavailable("the record was not stored")
        out = self._node_out(mid, r.json())
        await self._edges_for(mid, out["id"], record.get("references") or [])
        return out

    async def observe(self, mid, episodes, writer):
        schema = await self._schema(mid)
        rels = schema.get("relations") or []
        names = {str(t.get("id") or t.get("name")): str(t.get("name")) for t in schema.get("types") or []}
        emap: dict[tuple[str, str], list[str]] = {}
        for rel in rels:
            pair = (names.get(str(rel.get("from")), str(rel.get("from"))), names.get(str(rel.get("to")), str(rel.get("to"))))
            emap.setdefault(pair, []).append(str(rel.get("name")))
        records = []
        for e in episodes:
            text = "\n".join(f"{p.get('role')}: {p['text']}" if p.get("role") else str(p["text"]) for p in e.get("content") or [] if p.get("text"))
            r = await self._call("POST", "/episodes", body={
                "group_id": mid, "content": text, "source_description": f"{writer.get('kind')}:{writer.get('id')}",
                "entity_types": schema.get("types") or [], "edge_types": [{"name": x.get("name"), "description": x.get("description"), "properties": x.get("properties") or []} for x in rels],
                "edge_type_map": [{"from": a, "to": b, "names": n} for (a, b), n in emap.items()]})
            if r.status_code != 200:
                raise GraphitiUnavailable("the episode was not taken")
            d = r.json()
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
        r = await self._call("PUT", f"/groups/{mid}/nodes/{rid[len(NODE):]}", body={"name": title or said[:120], "summary": said, "attributes": a})
        if r.status_code != 200:
            raise GraphitiUnavailable("the revision was not stored")
        return {**self._node_out(mid, r.json()), "supersedes": cur["version"]}

    async def forget(self, mid, rid, writer):
        cur = await self.get(mid, rid)
        if not cur or cur["status"] != "active":
            raise mp.MemoryError(404, "memory_record_not_found", "No such record in this memory.", "record_id")
        if rid.startswith(EDGE):
            r = await self._call("POST", f"/groups/{mid}/edges/{rid[len(EDGE):]}/close", body={"forgotten": True})
            return self._edge_out(mid, r.json())
        if not rid.startswith(NODE):
            raise mp.MemoryError(422, "memory_unsupported", "An episode is what happened: erase it instead.")
        r0 = await self._call("GET", f"/groups/{mid}/nodes/{rid[len(NODE):]}")
        n = r0.json()
        a = {**(n.get("attributes") or {}), "hr_status": "forgotten", "hr_written_at": _now(), "hr_forgotten_by": f"{writer.get('kind')}:{writer.get('id')}"}
        r = await self._call("PUT", f"/groups/{mid}/nodes/{rid[len(NODE):]}", body={"name": n.get("name"), "summary": n.get("summary"), "attributes": a})
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
                r = await self._call("DELETE", f"/groups/{mid}/nodes/{rid[len(NODE):]}")
            else:
                r = await self._call("DELETE", f"/groups/{mid}/episodes/{rid[len(EPISODE):]}")
            if r.status_code == 200:
                erased.append(rid)
        return {"erased": erased, "unreachable": unreachable}

    # ── reads ─────────────────────────────────────────────────────────────────────────────────
    async def get(self, mid, rid, as_of=None):
        for prefix, kind, out in ((NODE, "nodes", self._node_out), (EDGE, "edges", self._edge_out)):
            if rid.startswith(prefix):
                r = await self._call("GET", f"/groups/{mid}/{kind}/{rid[len(prefix):]}")
                return out(mid, r.json()) if r.status_code == 200 else None
        if rid.startswith(EPISODE):
            r = await self._call("GET", f"/groups/{mid}/episodes", params={"limit": 1000})
            hit = next((x for x in (r.json() if r.status_code == 200 else []) if str(x.get("uuid")) == rid[len(EPISODE):]), None)
            return self._episode_out(mid, hit) if hit else None
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
        rows.sort(key=lambda x: str(x["time"]["written_at"] or ""), reverse=True)
        kept, used, cut = [], 0, False
        for x in rows:
            cost = mp.tokens_of(mp.record_words(x))
            if kept and used + cost > budget:
                cut = True
                continue
            kept.append(x)
            used += cost
        return {"records": kept, "tokens": used, "truncated": cut}

    async def _everything(self, mid: str, types: list[str]) -> list[dict]:
        rows: list[dict] = []
        wants = lambda *ts: not types or any(t in types for t in ts)       # noqa: E731
        r = await self._call("GET", f"/groups/{mid}/nodes", params={"limit": 1000})
        rows += [x for x in (self._node_out(mid, n) for n in (r.json() if r.status_code == 200 else [])) if not types or x["type"] in types]
        if wants("fact"):
            r = await self._call("GET", f"/groups/{mid}/edges", params={"limit": 1000})
            rows += [self._edge_out(mid, e) for e in (r.json() if r.status_code == 200 else [])]
        if wants("episode"):
            r = await self._call("GET", f"/groups/{mid}/episodes", params={"limit": 1000})
            rows += [self._episode_out(mid, x) for x in (r.json() if r.status_code == 200 else [])]
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
        rows = [self._edge_out(mid, e) for e in d.get("edges") or []] + [self._node_out(mid, n) for n in d.get("nodes") or []] + [self._episode_out(mid, x) for x in d.get("episodes") or []]
        why = [w for w, on in (("query", query), ("text", text), ("filters", later)) if on]
        kept = [x for x in rows if keep(x)]
        return {"results": [{"record": x, "memory_id": mid, "score": round(1 - i / max(len(kept), 1), 4), "why": why} for i, x in enumerate(kept)][:limit], "degraded": degraded, "abstain": False}
