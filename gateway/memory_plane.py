"""Memories: the tree, the access and the provider seam behind the Harness Memories sub-protocol.

A memory is a node in a tree. It holds records and may have child memories; a grant gives a
principal privileges on a node and the node's descendants inherit it, up to a restricted node, which
stops what flows from above. That much is this module's, and it is the same whichever provider keeps
the records. What a record IS, how it is derived, ranked or consolidated, belongs to the provider
(a memory service the workspace connected) behind the small interface below.

This process keeps no memory of its own: `PROVIDERS` holds the adapters, and a deployment has
memories once one of them is connected. Tests register a fixture provider.

Three rules shape everything here:
  - A question (recall) is asked of a memory and everything below it the caller may read, and each
    answer names the memory it is in: that is how a caller finds where to start. Everything else
    (list, get, the queries) acts on ONE memory, and nothing ever looks above: the caller walks.
  - Access is decided here, on every call, from grants. A provider never sees a principal and cannot
    be asked to widen a read.
  - What is not readable does not exist: a memory, a parent, a reference target the caller may not
    read are answered exactly as one that was never there.
"""
from __future__ import annotations

import json
import re
import time
import uuid

PRIVILEGES = ("read", "write", "create", "delete")
CORE_TYPES = ("episode", "fact", "note", "procedure", "link", "entity")
# The graph is not a second structure: a record is a node and a reference is an edge. An entity
# (a person, a company, a thing records are about) is a record like any other, and a relationship
# with something to say (who, since when, on whose word) is a `fact` that references its `subject`
# and its `object`. These are the reference names with a defined meaning; any other is carried.
REFERENCE_RELS = ("derived_from", "part_of", "about", "subject", "object")
GRAPH_SCAN = 2000         # records read to answer one graph; past it the answer says it was cut
GRAPH_NODES = 500
_MID = re.compile(r"hmem_[0-9a-f]{32}")
_NAME_MAX, _DESC_MAX = 120, 2000

# The store the records of the TREE live in (memories and grants): the gateway's graph backing,
# bound by app.py at import. Providers keep the records of the memories themselves.
GRAPH = None
PROVIDERS: dict[str, "Provider"] = {}
# How a provider that needs the workspace's own credential gets it: app.py binds a resolver over
# the plug registry, `await CREDENTIALS(org, workspace, provider_id) -> {field: value} | None`.
CREDENTIALS = None
# How a file part's reference is checked and completed: app.py binds a resolver over the server's
# file store, `await FILES(org, file_id) -> {"name", "media_type", "bytes"} | None` (None for a
# file that does not exist or is not this caller's).
FILES = None
_ROLES = ("user", "assistant", "system", "tool")


class MemoryError(Exception):
    """A refusal the protocol names; app.py turns it into the error envelope."""

    def __init__(self, status: int, code: str, message: str, param: str | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.param = status, code, message, param


def _not_found() -> MemoryError:
    return MemoryError(404, "memory_not_found", "No memory with that id.", "memory_id")


def _now_ms() -> str:
    return str(int(time.time() * 1000))


# ── the provider seam ─────────────────────────────────────────────────────────────────────────
class Provider:
    """What a memory provider answers for the memories bound to it. `mid` is the memory's id: the
    provider keeps each memory apart from every other, by a container of its own or by a condition
    it applies itself, and says which in `capabilities()["isolation"]`.

    An adapter implements what its service can do and leaves the rest: an operation left as it is
    here answers `memory_unsupported`, and the capability document must say the same."""

    id = ""

    def capabilities(self) -> dict:
        return {"id": self.id}

    async def bind(self, org: str, workspace: str) -> "Provider":
        """The provider as one workspace reaches it. A provider that needs the workspace's own
        account returns an instance holding that credential, or refuses when none is connected."""
        return self

    async def job(self, mid: str, job_id: str) -> dict | None:
        return None

    def _no(self, what: str):
        raise MemoryError(422, "memory_unsupported", f"This memory's provider does not {what}.")

    async def create(self, mid: str, memory: dict) -> None:
        return None

    async def drop(self, mid: str) -> None:
        return None

    async def count(self, mid: str) -> int:
        return 0

    async def observe(self, mid: str, episodes: list[dict], writer: dict) -> dict:
        """-> {"records": [...], "job": None | {"id", "status"}}: what was written now, and the
        work still running when the provider derives after it answers."""
        self._no("take episodes")

    async def remember(self, mid: str, record: dict, writer: dict) -> dict:
        self._no("take a stated record")

    async def recall(self, mid: str, req: dict) -> dict:
        self._no("answer recall")

    async def recall_many(self, mids: list[str], req: dict) -> dict:
        """One question asked of several memories this provider keeps: results in one ranking, each
        carrying `memory_id`. The default asks each memory in turn; a provider that can search
        several in one request overrides it."""
        results, degraded, abstains = [], [], []
        for mid in mids:
            res = await self.recall(mid, req)
            results += [{**x, "memory_id": mid} for x in res.get("results") or []]
            degraded += [d for d in res.get("degraded") or [] if d not in degraded]
            abstains.append(bool(res.get("abstain")))
        results.sort(key=lambda x: -(x.get("score") or 0))
        return {"results": results[: int(req.get("limit") or 8)], "degraded": degraded,
                "abstain": bool(abstains) and all(abstains)}

    async def get(self, mid: str, rid: str, as_of: str | None = None) -> dict | None:
        self._no("read one record")

    async def list(self, mid: str, req: dict) -> dict:
        self._no("list records")

    async def revise(self, mid: str, rid: str, patch: dict, writer: dict) -> dict:
        self._no("revise a record")

    async def forget(self, mid: str, rid: str, writer: dict) -> dict:
        self._no("forget a record")

    async def erase(self, mid: str, rids: list[str]) -> dict:
        self._no("erase")

    async def history(self, mid: str, rid: str) -> list[dict]:
        self._no("keep history")

    async def prime(self, mid: str) -> dict:
        return {"text": "", "tokens": 0}

    async def queries(self, mid: str) -> list[dict]:
        return []

    async def define_query(self, mid: str, q: dict) -> dict:
        self._no("keep named queries")

    async def run_query(self, mid: str, name: str, params: dict) -> dict:
        self._no("keep named queries")

    async def free_query(self, mid: str, language: str, statement: str, params: dict, write: bool) -> dict:
        self._no("run a query written by the caller")

    async def types(self) -> list[dict]:
        return []

    async def operate(self, mid: str, rid: str, name: str, body: dict, writer: dict) -> dict:
        self._no("offer operations on a record")

    async def operation_requires(self, mid: str, rid: str, name: str) -> str:
        self._no("offer operations on a record")

    async def consolidate(self, mid: str, budget: dict | None, trigger: str) -> dict:
        self._no("consolidate through the protocol")

    async def consolidations(self, mid: str) -> list[dict]:
        return []

    async def consolidation(self, mid: str, run: str) -> dict | None:
        return None

    async def consolidation_changes(self, mid: str, run: str) -> list[dict]:
        self._no("report what a consolidation changed")

    async def revert_consolidation(self, mid: str, run: str, writer: dict) -> dict:
        self._no("revert a consolidation")


async def provider_of(memory: dict) -> Provider:
    """The provider behind a memory, bound to the memory's own workspace."""
    p = PROVIDERS.get(str(memory.get("provider") or ""))
    if p is None:
        raise MemoryError(503, "memory_unavailable", "This memory's provider is not connected.")
    return await p.bind(str(memory.get("org") or ""), str(memory.get("workspace") or "") or "default")


def field_of(record: dict, field: str):
    cur = record
    for part in str(field).split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
    return cur


def matches(record: dict, flt) -> bool:
    """One record against a protocol filter: {"field", "op", "value"}, {"and": [...]}, {"or": [...]}.
    A provider that cannot express a filter itself applies it here and says so in `degraded`."""
    if not flt:
        return True
    if "and" in flt:
        return all(matches(record, f) for f in flt["and"])
    if "or" in flt:
        return any(matches(record, f) for f in flt["or"])
    v, op, want = field_of(record, flt.get("field")), flt.get("op", "eq"), flt.get("value")
    if op == "eq":
        return v == want
    if op == "in":
        return v in (want or [])
    if op in ("gte", "lte", "gt", "lt"):
        return v is not None and {"gte": v >= want, "lte": v <= want, "gt": v > want, "lt": v < want}[op]
    if op == "contains":
        return str(want).lower() in str(v or "").lower()
    raise MemoryError(422, "memory_invalid", f"Unknown filter operator `{op}`.", "filters")


# ── the tree ──────────────────────────────────────────────────────────────────────────────────
def _anc(memory: dict) -> list[str]:
    """Ancestor ids, root first: stamped at create and on a move, so placement costs no query."""
    return [x for x in str(memory.get("anc") or "").split(",") if x]


async def _load(org: str, mid: str) -> dict | None:
    if not mid or not _MID.fullmatch(mid):
        return None
    v = await GRAPH.get(mid, label="Memory")
    if not v or str(v.get("org") or "") != org or str(v.get("deleted") or "0") == "1":
        return None
    return v


async def _chain(org: str, memory: dict) -> list[dict]:
    """The memory and the ancestors whose grants reach it, nearest first: the walk leaves a node only
    when that node is not restricted, so a restricted node is included and then ends the chain."""
    out, cur = [memory], memory
    for aid in reversed(_anc(memory)):
        if str(cur.get("restricted") or "0") == "1":
            break
        cur = await _load(org, aid)
        if cur is None:
            break
        out.append(cur)
    return out


async def effective(org: str, memory: dict, principals: list[str]) -> list[str]:
    """The privileges these principals hold on the memory: every grant on it and on the ancestors
    the cutoff-aware chain reaches. The creator of a node holds all four on it, an implicit grant
    that flows down like any other."""
    chain = await _chain(org, memory)
    ids = {str(m["id"]) for m in chain}
    privs: set[str] = set()
    for m in chain:
        if f"member:{m.get('created_by') or ''}" in principals and m.get("created_by"):
            return list(PRIVILEGES)
    for g in await GRAPH.find("MemoryGrant", {"org": org}):
        if str(g.get("memory_id") or "") in ids and str(g.get("principal") or "") in principals \
                and str(g.get("deleted") or "0") != "1":
            privs.update(p for p in json.loads(g.get("privileges") or "[]") if p in PRIVILEGES)
    return [p for p in PRIVILEGES if p in privs]


async def need(org: str, mid: str, principals: list[str], privilege: str) -> tuple[dict, list[str]]:
    """The memory, if these principals hold `privilege` on it. Holding nothing on it is `not found`;
    seeing it and lacking this privilege is `forbidden`."""
    m = await _load(org, mid)
    if m is None:
        raise _not_found()
    privs = await effective(org, m, principals)
    if not privs:
        raise _not_found()
    if privilege not in privs:
        raise MemoryError(403, "memory_forbidden", f"This needs `{privilege}` on the memory.")
    return m, privs


async def out(org: str, memory: dict, principals: list[str], privs: list[str] | None = None) -> dict:
    """The memory object as this caller sees it: ancestors only as far up as it may see."""
    privs = privs if privs is not None else await effective(org, memory, principals)
    anc, seen = [], []
    for aid in _anc(memory):
        a = await _load(org, aid)
        seen.append(aid if a and await effective(org, a, principals) else None)
    # contiguous from the parent upward: an ancestor past one the caller cannot see is not shown
    for aid in reversed(seen):
        if aid is None:
            break
        anc.insert(0, aid)
    parent = str(memory.get("parent_id") or "")
    kids = [k for k in await GRAPH.find("Memory", {"org": org, "parent_id": memory["id"]})
            if str(k.get("deleted") or "0") != "1"]
    try:
        n = await (await provider_of(memory)).count(str(memory["id"]))
    except MemoryError:
        n = None                       # the provider is not reachable: unknown, not zero
    return {"id": memory["id"], "object": "memory", "name": memory.get("name") or "",
            "description": memory.get("description") or "",
            "parent_id": parent if parent and parent in anc else None, "ancestors": anc,
            "restricted": str(memory.get("restricted") or "0") == "1",
            "provider": memory.get("provider") or "", "privileges": privs,
            "records": {"count": n}, "children": {"count": len(kids)},
            "createdAt": int(memory.get("created_at") or 0), "updatedAt": int(memory.get("updated_at") or 0)}


def _brief(o: dict) -> dict:
    return {k: o[k] for k in ("id", "name", "description", "records", "children", "privileges")}


async def neighbours(org: str, memory: dict, principals: list[str]) -> dict:
    """Where the caller can go from here: the parent and the direct children it may read."""
    res: dict = {"children": []}
    pid = str(memory.get("parent_id") or "")
    if pid:
        p = await _load(org, pid)
        if p:
            pp = await effective(org, p, principals)
            if "read" in pp:
                res["parent"] = _brief(await out(org, p, principals, pp))
    for k in sorted(await GRAPH.find("Memory", {"org": org, "parent_id": memory["id"]}),
                    key=lambda x: (str(x.get("name") or "").casefold(), str(x["id"]))):
        if str(k.get("deleted") or "0") == "1":
            continue
        kp = await effective(org, k, principals)
        if "read" in kp:
            res["children"].append(_brief(await out(org, k, principals, kp)))
    return res


def _clean(name, description) -> tuple[str, str]:
    name = str(name or "").strip()
    if not name or len(name) > _NAME_MAX:
        raise MemoryError(422, "memory_invalid", "Give the memory a name of at most 120 characters.", "name")
    return name, str(description or "").strip()[:_DESC_MAX]


async def create(org: str, member: str, workspace: str, principals: list[str], *, name, description="",
                 parent_id=None, restricted=False, provider="") -> dict:
    name, description = _clean(name, description)
    prov = str(provider or "").strip()
    anc: list[str] = []
    if parent_id:
        parent, _ = await need(org, str(parent_id), principals, "create")
        anc = _anc(parent) + [str(parent["id"])]
        prov = prov or str(parent.get("provider") or "")
    if prov not in PROVIDERS:
        raise MemoryError(422, "memory_invalid",
                          "Name a connected memory provider." if prov else
                          "No memory provider is connected: connect one, then create the memory.", "provider")
    bound = await PROVIDERS[prov].bind(org, workspace or "default")     # refuses when the workspace has not connected it
    mid, now = "hmem_" + uuid.uuid4().hex, _now_ms()
    props = {"org": org, "workspace": workspace, "name": name, "description": description,
             "parent_id": str(parent_id or ""), "anc": ",".join(anc), "restricted": "1" if restricted else "0",
             "provider": prov, "created_by": member, "created_at": now, "updated_at": now, "deleted": "0"}
    await bound.create(mid, {"id": mid, **props})
    await GRAPH.upsert("Memory", mid, props, raise_on_fail=True)
    return {"id": mid, **props}


async def _subtree(org: str, mid: str) -> list[dict]:
    """The memory's descendants, parents before children: one level per pass."""
    found, frontier = [], [mid]
    while frontier:
        nxt = []
        for pid in frontier:
            for k in await GRAPH.find("Memory", {"org": org, "parent_id": pid}):
                if str(k.get("deleted") or "0") != "1":
                    found.append(k)
                    nxt.append(str(k["id"]))
        frontier = nxt
    return found


async def update(org: str, mid: str, principals: list[str], patch: dict) -> dict:
    m, privs = await need(org, mid, principals, "write")
    props: dict = {}
    if "name" in patch or "description" in patch:
        props["name"], props["description"] = _clean(patch.get("name", m.get("name")),
                                                     patch.get("description", m.get("description")))
    if "restricted" in patch and bool(patch["restricted"]) != (str(m.get("restricted") or "0") == "1"):
        if "delete" not in privs:      # who inherits is access; changing it is changing access
            raise MemoryError(403, "memory_forbidden", "Changing `restricted` needs `delete` on the memory.")
        props["restricted"] = "1" if patch["restricted"] else "0"
    if "parent_id" in patch and str(patch["parent_id"] or "") != str(m.get("parent_id") or ""):
        if "delete" not in privs:
            raise MemoryError(403, "memory_forbidden", "Moving a memory needs `delete` on it.")
        new_parent, anc = str(patch["parent_id"] or ""), []
        if new_parent:
            p, _ = await need(org, new_parent, principals, "create")
            anc = _anc(p) + [str(p["id"])]
            if mid in anc or new_parent == mid:
                raise MemoryError(422, "memory_invalid", "A memory cannot be moved under itself.", "parent_id")
        props["parent_id"], props["anc"] = new_parent, ",".join(anc)
        for k in await _subtree(org, mid):      # every descendant's placement follows
            tail = _anc(k)[_anc(k).index(mid):]
            await GRAPH.upsert("Memory", str(k["id"]), {"anc": ",".join(anc + tail)}, raise_on_fail=True)
    if props:
        props["updated_at"] = _now_ms()
        await GRAPH.upsert("Memory", mid, props, raise_on_fail=True)
    return {**m, **props}


async def delete(org: str, mid: str, principals: list[str]) -> list[str]:
    m, _ = await need(org, mid, principals, "delete")
    gone = []
    for x in [m] + await _subtree(org, mid):
        try:
            await (await provider_of(x)).drop(str(x["id"]))
        except MemoryError:
            pass                       # a provider that is gone cannot hold what is being deleted
        await GRAPH.upsert("Memory", str(x["id"]), {"deleted": "1", "updated_at": _now_ms()}, raise_on_fail=True)
        gone.append(str(x["id"]))
    return gone


# How many memories one recall may search. A subtree can hold a node per customer; past this the
# answer says it was cut, and the caller narrows by starting lower in the tree.
RECALL_MAX_MEMORIES = 200


async def reach_below(org: str, memory: dict, principals: list[str], depth: int | None = None) -> tuple[list[dict], bool]:
    """The memory and every descendant these principals may read, nearest first, and whether the
    list was cut. A descendant is judged on its own: one under a restricted node the caller cannot
    read is still reached when the caller holds a grant on it, and the node between is never named."""
    found, frontier, level, cut = [memory], [str(memory["id"])], 0, False
    while frontier and (depth is None or level < depth):
        nxt = []
        for pid in frontier:
            for k in await GRAPH.find("Memory", {"org": org, "parent_id": pid}):
                if str(k.get("deleted") or "0") == "1":
                    continue
                nxt.append(str(k["id"]))
                if "read" in await effective(org, k, principals):
                    if len(found) >= RECALL_MAX_MEMORIES:
                        cut = True
                    else:
                        found.append(k)
        frontier, level = nxt, level + 1
    return found, cut


async def recall(org: str, memories: list[dict], req: dict) -> dict:
    """One question over a set of memories the caller may read: grouped by the provider that keeps
    each, asked once per provider, merged into one ranking. Each result names the memory it is in."""
    groups: dict[tuple, tuple[Provider, list[str]]] = {}
    for m in memories:
        key = (str(m.get("provider") or ""), str(m.get("workspace") or "") or "default")
        if key not in groups:
            groups[key] = (await provider_of(m), [])
        groups[key][1].append(str(m["id"]))
    results, degraded, abstains = [], [], []
    asked = [s for s in ("query", "text", "filters") if req.get(s)]
    for prov, mids in groups.values():
        signals = (prov.capabilities().get("recall") or {}).get("signals") or []
        res = await prov.recall_many(mids, req)
        results += res.get("results") or []
        for d in (res.get("degraded") or []) + [f"{s}:not_supported" for s in asked if s not in signals]:
            if d not in degraded:
                degraded.append(d)
        abstains.append(bool(res.get("abstain")))
    results.sort(key=lambda x: -(x.get("score") or 0))
    return {"results": results[: int(req.get("limit") or 8)], "degraded": degraded,
            "abstain": bool(abstains) and all(abstains)}


async def graph(org: str, memory: dict, principals: list[str], *, around: str = "", hops: int = 1,
                types: list[str] | None = None, limit: int = 200) -> dict:
    """The records of a memory as a graph: nodes are records, edges are their references. With
    `around`, the neighbourhood of one record, `hops` references away in either direction; without
    it, the records of this memory and what they point at. Records are looked for in the memory and
    below it, as a search does; a reference may lead into any memory, and its target is a node only
    when the caller may read it. Nothing here is a provider's own structure: the same answer comes
    from any provider that keeps records and references."""
    reach, cut = await reach_below(org, memory, principals)
    names = {str(m["id"]): str(m.get("name") or "") for m in reach}
    recs: dict[tuple[str, str], dict] = {}
    degraded: list[str] = [f"subtree:capped_at_{RECALL_MAX_MEMORIES}_memories"] if cut else []
    for m in reach:
        prov, cursor, mid = await provider_of(m), "", str(m["id"])
        while len(recs) < GRAPH_SCAN:
            page = await prov.list(mid, {"types": None, "as_of": None, "include": "active", "limit": 200, "cursor": cursor})
            for r in page.get("records") or []:
                recs[(mid, str(r["id"]))] = r
            cursor = page.get("next") or ""
            if not cursor:
                break
        if len(recs) >= GRAPH_SCAN:
            degraded.append(f"records:capped_at_{GRAPH_SCAN}")
            break
    own = str(memory["id"])
    edges = [((mid, rid), (str(x.get("memory_id") or mid), str(x.get("record_id") or "")), str(x.get("rel") or "related"))
             for (mid, rid), r in recs.items() for x in r.get("references") or [] if x.get("record_id")]
    if around:
        start = [k for k in recs if k[1] == around and k[0] == own] or [k for k in recs if k[1] == around]
        if not start:
            raise MemoryError(404, "memory_record_not_found", "No such record in this memory.", "around")
        frontier = {start[0]}
    else:
        frontier = {k for k in recs if k[0] == own}
    keep, readable = set(frontier), dict.fromkeys(names, True)

    async def may_read(mid: str) -> bool:
        if mid not in readable:
            t = await _load(org, mid)
            readable[mid] = bool(t) and "read" in await effective(org, t, principals)
            if readable[mid]:
                names[mid] = str(t.get("name") or "")
        return readable[mid]

    for _ in range(max(0, min(int(hops), 3))):
        nxt = set()
        for a, b, _rel in edges:
            for here, there in ((a, b), (b, a)):
                if here in frontier and there not in keep:
                    nxt.add(there)
        got = set()
        for k in nxt:
            if k not in recs and await may_read(k[0]):       # a target outside what was scanned
                t = await _load(org, k[0])
                r = await (await provider_of(t)).get(k[0], k[1])
                if r:
                    recs[k] = r
                    edges += [(k, (str(x.get("memory_id") or k[0]), str(x.get("record_id") or "")), str(x.get("rel") or "related"))
                              for x in r.get("references") or [] if x.get("record_id")]
            if k in recs:
                got.add(k)
        keep |= got
        frontier = got
    if types:
        keep = {k for k in keep if recs[k].get("type") in types}
    ordered = sorted(keep, key=lambda k: (k != (own, around), k[0] != own, str((recs[k].get("time") or {}).get("written_at") or ""), k[1]))
    limit = max(1, min(int(limit or 200), GRAPH_NODES))
    truncated = len(ordered) > limit
    shown = set(ordered[:limit])
    seen: dict = {}
    nodes = [{"record": await present(org, k[0], recs[k], principals, seen), "memory": {"id": k[0], "name": names.get(k[0], "")}}
             for k in ordered[:limit]]
    out_edges = []
    for a, b, rel in edges:
        if a not in shown:
            continue
        if b in shown:
            out_edges.append({"from": {"memory_id": a[0], "record_id": a[1]}, "to": {"memory_id": b[0], "record_id": b[1]}, "rel": rel, "available": True})
        elif not await may_read(b[0]):                       # the caller may not read where it leads: said, and nothing more
            out_edges.append({"from": {"memory_id": a[0], "record_id": a[1]}, "to": {"memory_id": b[0], "record_id": b[1]}, "available": False})
    return {"nodes": nodes, "edges": out_edges, "truncated": truncated, "degraded": degraded}


async def roots(org: str, principals: list[str]) -> list[dict]:
    """Where a caller enters the tree: every memory it holds a privilege on whose parent it cannot
    see. A caller granted one branch enters at that branch, not at a root it has no part in."""
    res = []
    for m in await GRAPH.find("Memory", {"org": org}):
        if str(m.get("deleted") or "0") == "1":
            continue
        privs = await effective(org, m, principals)
        if not privs:
            continue
        pid = str(m.get("parent_id") or "")
        if pid:
            p = await _load(org, pid)
            if p and await effective(org, p, principals):
                continue
        res.append(await out(org, m, principals, privs))
    return sorted(res, key=lambda x: (x["name"].casefold(), x["id"]))


async def children(org: str, mid: str, principals: list[str]) -> list[dict]:
    m, _ = await need(org, mid, principals, "read")
    res = []
    for k in await GRAPH.find("Memory", {"org": org, "parent_id": m["id"]}):
        if str(k.get("deleted") or "0") == "1":
            continue
        kp = await effective(org, k, principals)
        if kp:
            res.append(await out(org, k, principals, kp))
    return sorted(res, key=lambda x: (x["name"].casefold(), x["id"]))


# ── grants ────────────────────────────────────────────────────────────────────────────────────
# One vocabulary for who acts on a memory, in a grant (`<kind>:<id>`) and on a record's writer
# (`{kind, id}`). A member is anyone who acts: a person or an agent, equal before the access model;
# which of the two is a property of the member (`type`), never a kind. A group is a set of members.
# The provider is the engine itself, which writes and holds no grant. Anything else is `x.`.
ACTOR_KINDS = ("member", "group", "provider")
_PRINCIPAL = re.compile(r"(member|group|x\.[a-z0-9_.-]+):[A-Za-z0-9_.@:+\-]{1,160}")


async def grants(org: str, mid: str, principals: list[str]) -> list[dict]:
    """Who holds what on this memory, and on which node each grant sits (its own or an ancestor's)."""
    m, _ = await need(org, mid, principals, "delete")
    ids = [str(x["id"]) for x in await _chain(org, m)]
    res = []
    for g in await GRAPH.find("MemoryGrant", {"org": org}):
        if str(g.get("memory_id") or "") in ids and str(g.get("deleted") or "0") != "1":
            res.append({"id": g["id"], "object": "memory.grant", "memory_id": g["memory_id"],
                        "principal": g["principal"], "privileges": json.loads(g.get("privileges") or "[]"),
                        "inherited": g["memory_id"] != mid})
    return res


async def grant(org: str, mid: str, principals: list[str], principal: str, privileges: list,
                by: str) -> dict:
    await need(org, mid, principals, "delete")
    principal = str(principal or "").strip()
    privs = [p for p in PRIVILEGES if p in (privileges or [])]
    if not _PRINCIPAL.fullmatch(principal):
        raise MemoryError(422, "memory_invalid", "A principal is `<kind>:<id>`: a member (a person or an agent) or a group.", "principal")
    if not privs:
        raise MemoryError(422, "memory_invalid", "Name at least one of read, write, create, delete.", "privileges")
    for g in await GRAPH.find("MemoryGrant", {"org": org, "memory_id": mid, "principal": principal}):
        if str(g.get("deleted") or "0") != "1":        # one grant per principal per node: it is replaced
            await GRAPH.upsert("MemoryGrant", str(g["id"]), {"privileges": json.dumps(privs)}, raise_on_fail=True)
            return {"id": g["id"], "object": "memory.grant", "memory_id": mid, "principal": principal,
                    "privileges": privs, "inherited": False}
    gid = "hgrt_" + uuid.uuid4().hex
    await GRAPH.upsert("MemoryGrant", gid, {"org": org, "memory_id": mid, "principal": principal,
                                            "privileges": json.dumps(privs), "granted_by": by,
                                            "created_at": _now_ms(), "deleted": "0"}, raise_on_fail=True)
    return {"id": gid, "object": "memory.grant", "memory_id": mid, "principal": principal,
            "privileges": privs, "inherited": False}


async def granted(org: str, principal: str) -> list[tuple[dict, list[str]]]:
    """Every memory this principal holds a grant ON (not merely below one), with what it may do
    there, highest in the tree first. It is where a member was let in: the same answer for a person
    and for an agent, and the only source of what an agent's harness shows as its memories."""
    res = []
    for g in await GRAPH.find("MemoryGrant", {"org": org, "principal": principal}):
        if str(g.get("deleted") or "0") == "1":
            continue
        m = await _load(org, str(g.get("memory_id") or ""))
        if m:
            res.append((len(await _chain(org, m)), str(m.get("name") or "").casefold(), m, await effective(org, m, [principal])))
    return [(m, privs) for _, _, m, privs in sorted(res, key=lambda x: (x[0], x[1], str(x[2]["id"]))) if privs]


async def revoke(org: str, mid: str, principals: list[str], gid: str) -> None:
    await need(org, mid, principals, "delete")
    g = await GRAPH.get(gid, label="MemoryGrant")
    if not g or str(g.get("org") or "") != org or str(g.get("memory_id") or "") != mid:
        raise MemoryError(404, "memory_not_found", "No such grant on this memory.", "grant_id")
    await GRAPH.upsert("MemoryGrant", gid, {"deleted": "1"}, raise_on_fail=True)


# ── records ───────────────────────────────────────────────────────────────────────────────────
async def present(org: str, mid: str, record: dict, principals: list[str], _seen: dict | None = None) -> dict:
    """A record as this reader gets it: marked untrusted, and each reference resolved with the
    READER's privileges. A target in a memory the reader may not read is named and nothing more."""
    r = {**record, "object": "memory.record", "memory_id": mid, "trust": "untrusted"}
    c = record.get("content")
    r["content"] = c if isinstance(c, list) else ([{"type": "text", "text": c}] if isinstance(c, str) and c else [])
    refs, seen = [], _seen if _seen is not None else {}
    for ref in record.get("references") or []:
        tm = str(ref.get("memory_id") or mid)
        if tm not in seen:
            t = await _load(org, tm)
            seen[tm] = bool(t) and "read" in await effective(org, t, principals)
        refs.append({**{k: ref.get(k) for k in ("rel", "record_id")}, "memory_id": tm, "available": seen[tm]}
                    if seen[tm] else {"memory_id": tm, "record_id": ref.get("record_id"), "available": False})
    r["references"] = refs
    return r


def writer_of(member: str, agent: bool = False) -> dict:
    """Stamped here from the authenticated caller; a client's own `written_by` is never read. A
    person and an agent are both members; `type` says which, for a reader who wants to know."""
    return {"kind": "member", "id": member, "type": "agent" if agent else "human"}


def parts_of(content, *, empty_ok: bool = False) -> list[dict]:
    """A record's content as the protocol carries it: an ordered list of parts. Two kinds are
    defined, `text` and `file`; what a file IS (an image, a recording, a video, a PDF) is its media
    type, so a new modality needs no new kind. A string is shorthand for one text part. A part of a
    kind this server does not define is kept as it is when its type is `x.`-prefixed."""
    if isinstance(content, str):
        content = [{"type": "text", "text": content}] if content.strip() else []
    if not isinstance(content, list):
        raise MemoryError(422, "memory_invalid", "Content is text, or a list of parts.", "content")
    parts = []
    for p in content:
        if not isinstance(p, dict):
            raise MemoryError(422, "memory_invalid", "Each part of the content is an object with a type.", "content")
        typ = str(p.get("type") or "")
        if typ == "text":
            if not isinstance(p.get("text"), str) or not p["text"].strip():
                raise MemoryError(422, "memory_invalid", "A text part carries text.", "content")
            out = {"type": "text", "text": p["text"]}
        elif typ == "file":
            f = p.get("file")
            if not isinstance(f, dict) or not str(f.get("id") or "").strip():
                raise MemoryError(422, "memory_invalid", "A file part names a file by its id.", "content")
            out = {"type": "file", "file": {k: f[k] for k in ("id", "name", "media_type", "bytes", "version") if f.get(k) is not None}}
            if isinstance(p.get("text"), str) and p["text"].strip():
                out["text"] = p["text"]
                out["text_source"] = p.get("text_source") if p.get("text_source") in ("stated", "derived") else "stated"
        elif typ.startswith("x."):
            out = dict(p)
        else:
            raise MemoryError(422, "memory_invalid", "A part is `text` or `file`; any other kind is `x.`-prefixed.", "content")
        if p.get("role") is not None:
            if p["role"] not in _ROLES:
                raise MemoryError(422, "memory_invalid", "A part's role is user, assistant, system or tool.", "content")
            out["role"] = p["role"]
        parts.append(out)
    if not parts and not empty_ok:
        raise MemoryError(422, "memory_invalid", "A record carries content: text, or a list of parts.", "content")
    return parts


def text_of(parts) -> str:
    """Every word a record says: its text parts and the text that stands for its files."""
    if isinstance(parts, str):
        return parts
    return "\n".join(str(p.get("text")) for p in parts or [] if isinstance(p, dict) and p.get("text"))


async def settle_files(org: str, parts: list[dict], provider: "Provider") -> list[dict]:
    """Each file part checked against the server's file store and completed from it (the name,
    media type and size are the store's, never the caller's), then against what the memory's
    provider keeps: a media type it does not keep is refused, never dropped."""
    import fnmatch
    kept = ((provider.capabilities().get("content") or {}).get("media")) or ["text/*"]
    for p in parts:
        if p.get("type") != "file":
            continue
        meta = await FILES(org, str(p["file"]["id"])) if FILES else None
        if not meta:
            raise MemoryError(422, "memory_invalid", "A file part names a file this caller uploaded.", "content")
        p["file"] = {"id": str(p["file"]["id"]), "name": meta.get("name") or "", "media_type": meta.get("media_type") or "application/octet-stream",
                     "bytes": int(meta.get("bytes") or 0)}
        if not any(fnmatch.fnmatch(p["file"]["media_type"], pat) for pat in kept):
            raise MemoryError(422, "memory_unsupported",
                              f"This memory's provider does not keep {p['file']['media_type']} content.", "content")
    return parts


def _record_in(body: dict) -> dict:
    typ = str(body.get("type") or "fact")
    if not re.fullmatch(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*", typ):
        raise MemoryError(422, "memory_invalid", "A record type is lower-case words joined by dots.", "type")
    content = parts_of(body.get("content"), empty_ok=(typ == "link" or typ not in CORE_TYPES))
    refs = []
    for ref in body.get("references") or []:
        if not isinstance(ref, dict) or not ref.get("record_id"):
            raise MemoryError(422, "memory_invalid", "A reference names a record_id (and a memory_id when it is elsewhere).", "references")
        refs.append({"rel": str(ref.get("rel") or "related"), "memory_id": str(ref.get("memory_id") or ""),
                     "record_id": str(ref["record_id"])})
    t = body.get("time") or {}
    return {"type": typ, "content": content, "attributes": dict(body.get("attributes") or {}),
            "references": refs, "time": {k: t.get(k) for k in ("valid_from", "valid_to") if t.get(k)}}
