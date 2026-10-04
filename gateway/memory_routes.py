"""The Harness Memories sub-protocol over HTTP: every route is the caller's principals, one access
check in memory_plane, and one call to the memory's provider. Nothing here knows a provider."""
from __future__ import annotations

import os
import time
import uuid

from fastapi import APIRouter, Request

import memory_plane as mp

router = APIRouter()
_principal = None          # app.py's resolver, bound by install()
_uhp_error = None


def install(app, principal, uhp_error, graph) -> None:
    """Bind the gateway's principal resolver, error envelope and graph backing, and mount the routes."""
    global _principal, _uhp_error
    _principal, _uhp_error, mp.GRAPH = principal, uhp_error, graph
    if os.environ.get("HR_MEMORY_FIXTURE") == "1" and "fixture" not in mp.PROVIDERS:
        import memory_fixture
        mp.PROVIDERS["fixture"] = memory_fixture.FixtureProvider()
    app.include_router(router)


def principals_of(p: dict) -> list[str]:
    """Who a caller is to the access model: the person, and the workspace it acts in."""
    out = []
    if p.get("member"):
        out.append(f"member:{p['member']}")
    if p.get("workspace"):
        out.append(f"workspace:{p['workspace']}")
    return out


async def _who(request: Request) -> tuple[str, str, str, list[str]]:
    p = await _principal(request)
    org = p.get("org", "")
    if not org:
        raise _uhp_error(401, "invalid_credential", "Missing or invalid API key.")
    return org, str(p.get("member") or ""), str(p.get("workspace") or ""), principals_of(p)


async def _json(request: Request) -> dict:
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise _uhp_error(422, "memory_invalid", "The request body is a JSON object.")
    return body


def _err(e: mp.MemoryError):
    return _uhp_error(e.status, e.code, e.message, e.param)


def guarded(fn):
    """A MemoryError raised anywhere below a route leaves as the protocol's error envelope."""
    import functools

    @functools.wraps(fn)
    async def wrapper(*a, **kw):
        try:
            return await fn(*a, **kw)
        except mp.MemoryError as e:
            raise _err(e)
    return wrapper


async def _records_out(org, mid, records, pr) -> list[dict]:
    seen: dict = {}
    return [await mp.present(org, mid, r, pr, seen) for r in records]


async def _answer(org, m, pr, res: dict) -> dict:
    """A recall-shaped answer: the provider's results presented to this reader, and where the
    reader can go from here."""
    seen: dict = {}
    results = [{"record": await mp.present(org, m["id"], x["record"], pr, seen),
                "score": x.get("score"), "why": x.get("why") or []} for x in res.get("results") or []]
    return {"object": "memory.recall", "results": results, **await mp.neighbours(org, m, pr),
            "degraded": res.get("degraded") or [], "abstain": bool(res.get("abstain"))}


# ── discovery (declared before /{mid} so the words are not read as ids) ──────────────────────────
@router.get("/v1/memories/providers")
@guarded
async def providers(request: Request) -> dict:
    await _who(request)
    return {"object": "list", "data": [p.capabilities() for _, p in sorted(mp.PROVIDERS.items())]}


@router.get("/v1/memories/types")
@guarded
async def types(request: Request) -> dict:
    await _who(request)
    core = [{"type": t, "core": True} for t in mp.CORE_TYPES]
    ext = [dict(t, provider=pid) for pid, p in sorted(mp.PROVIDERS.items()) for t in await p.types()]
    return {"object": "list", "data": core + ext}


# ── the tree ──────────────────────────────────────────────────────────────────────────────────
@router.post("/v1/memories")
@guarded
async def create_memory(request: Request) -> dict:
    org, member, ws, pr = await _who(request)
    b = await _json(request)
    m = await mp.create(org, member, ws, pr, name=b.get("name"), description=b.get("description"),
                        parent_id=b.get("parent_id"), restricted=bool(b.get("restricted")),
                        provider=b.get("provider"))
    return await mp.out(org, m, pr)


@router.get("/v1/memories")
@guarded
async def list_memories(request: Request, parent: str = "", ancestor: str = "") -> dict:
    org, _, _, pr = await _who(request)
    if ancestor:
        m, _ = await mp.need(org, ancestor, pr, "read")
        data = []
        for k in await mp._subtree(org, m["id"]):
            kp = await mp.effective(org, k, pr)
            if kp:
                data.append(await mp.out(org, k, pr, kp))
        return {"object": "list", "data": data}
    return {"object": "list", "data": await (mp.children(org, parent, pr) if parent else mp.roots(org, pr))}


@router.get("/v1/memories/{mid}")
@guarded
async def get_memory(mid: str, request: Request) -> dict:
    org, _, _, pr = await _who(request)
    m, privs = await mp.need(org, mid, pr, "read")
    return await mp.out(org, m, pr, privs)


@router.put("/v1/memories/{mid}")
@guarded
async def put_memory(mid: str, request: Request) -> dict:
    org, _, _, pr = await _who(request)
    m = await mp.update(org, mid, pr, await _json(request))
    return await mp.out(org, m, pr)


@router.delete("/v1/memories/{mid}")
@guarded
async def delete_memory(mid: str, request: Request) -> dict:
    org, _, _, pr = await _who(request)
    return {"id": mid, "object": "memory", "deleted": True, "memories": await mp.delete(org, mid, pr)}


# ── grants ────────────────────────────────────────────────────────────────────────────────────
@router.get("/v1/memories/{mid}/grants")
@guarded
async def list_grants(mid: str, request: Request) -> dict:
    org, _, _, pr = await _who(request)
    return {"object": "list", "data": await mp.grants(org, mid, pr)}


@router.post("/v1/memories/{mid}/grants")
@guarded
async def add_grant(mid: str, request: Request) -> dict:
    org, member, _, pr = await _who(request)
    b = await _json(request)
    return await mp.grant(org, mid, pr, b.get("principal"), b.get("privileges") or [], member)


@router.delete("/v1/memories/{mid}/grants/{gid}")
@guarded
async def drop_grant(mid: str, gid: str, request: Request) -> dict:
    org, _, _, pr = await _who(request)
    await mp.revoke(org, mid, pr, gid)
    return {"id": gid, "object": "memory.grant", "deleted": True}


# ── writes ────────────────────────────────────────────────────────────────────────────────────
@router.post("/v1/memories/{mid}/observe")
@guarded
async def observe(mid: str, request: Request) -> dict:
    org, member, _, pr = await _who(request)
    m, _ = await mp.need(org, mid, pr, "write")
    eps = (await _json(request)).get("episodes")
    if not isinstance(eps, list) or not eps or not all(isinstance(e, dict) and e.get("content") for e in eps):
        raise _uhp_error(422, "memory_invalid", "`episodes` is a non-empty list, each with content.", "episodes")
    made = await mp.provider_of(m).observe(mid, eps, mp.writer_of(member))
    return {"object": "list", "data": await _records_out(org, mid, made, pr)}


@router.post("/v1/memories/{mid}/records")
@guarded
async def remember(mid: str, request: Request) -> dict:
    org, member, _, pr = await _who(request)
    m, _ = await mp.need(org, mid, pr, "write")
    rec = await mp.provider_of(m).remember(mid, mp._record_in(await _json(request)), mp.writer_of(member))
    return await mp.present(org, mid, rec, pr)


@router.patch("/v1/memories/{mid}/records/{rid}")
@guarded
async def revise(mid: str, rid: str, request: Request) -> dict:
    org, member, _, pr = await _who(request)
    m, _ = await mp.need(org, mid, pr, "write")
    b = await _json(request)
    patch = {k: b[k] for k in ("content", "attributes", "references", "time") if k in b}
    if not patch:
        raise _uhp_error(422, "memory_invalid", "A revision changes content, attributes, references or time.")
    return await mp.present(org, mid, await mp.provider_of(m).revise(mid, rid, patch, mp.writer_of(member)), pr)


@router.delete("/v1/memories/{mid}/records/{rid}")
@guarded
async def forget(mid: str, rid: str, request: Request) -> dict:
    org, member, _, pr = await _who(request)
    m, _ = await mp.need(org, mid, pr, "write")
    return await mp.present(org, mid, await mp.provider_of(m).forget(mid, rid, mp.writer_of(member)), pr)


@router.post("/v1/memories/{mid}/erase")
@guarded
async def erase(mid: str, request: Request) -> dict:
    org, _, _, pr = await _who(request)
    m, _ = await mp.need(org, mid, pr, "delete")
    ids = (await _json(request)).get("record_ids")
    if not isinstance(ids, list) or not ids:
        raise _uhp_error(422, "memory_invalid", "`record_ids` names what to erase.", "record_ids")
    res = await mp.provider_of(m).erase(mid, [str(i) for i in ids])
    return {"object": "memory.erasure", "erased": res.get("erased") or [], "unreachable": res.get("unreachable") or []}


# ── reads ─────────────────────────────────────────────────────────────────────────────────────
@router.post("/v1/memories/{mid}/recall")
@guarded
async def recall(mid: str, request: Request) -> dict:
    org, _, _, pr = await _who(request)
    m, _ = await mp.need(org, mid, pr, "read")
    b = await _json(request)
    if not (b.get("query") or b.get("text") or b.get("filters")):
        raise _uhp_error(422, "memory_invalid", "Give a query, text or filters.")
    req = {k: b.get(k) for k in ("query", "text", "filters", "types", "as_of", "include", "depth")}
    req["limit"] = max(1, min(int(b.get("limit") or 8), 100))
    prov = mp.provider_of(m)
    signals = (prov.capabilities().get("recall") or {}).get("signals") or []
    asked = [s for s in ("query", "text", "filters") if req.get(s)]
    res = await prov.recall(mid, req)
    # what was asked for and the provider does not do is said, whatever the adapter remembered to say
    res["degraded"] = list(dict.fromkeys((res.get("degraded") or []) +
                                         [f"{s}:not_supported" for s in asked if s not in signals]))
    return await _answer(org, m, pr, res)


@router.get("/v1/memories/{mid}/records")
@guarded
async def list_records(mid: str, request: Request, type: str = "", as_of: str = "", include: str = "active",
                       limit: int = 50, cursor: str = "") -> dict:
    org, _, _, pr = await _who(request)
    m, _ = await mp.need(org, mid, pr, "read")
    res = await mp.provider_of(m).list(mid, {"types": [type] if type else None, "as_of": as_of or None,
                                             "include": include, "limit": max(1, min(limit, 200)), "cursor": cursor})
    return {"object": "list", "data": await _records_out(org, mid, res.get("records") or [], pr),
            "next": res.get("next"), **await mp.neighbours(org, m, pr)}


@router.get("/v1/memories/{mid}/records/{rid}")
@guarded
async def get_record(mid: str, rid: str, request: Request, as_of: str = "") -> dict:
    org, _, _, pr = await _who(request)
    m, _ = await mp.need(org, mid, pr, "read")
    rec = await mp.provider_of(m).get(mid, rid, as_of or None)
    if not rec:
        raise _uhp_error(404, "memory_record_not_found", "No such record in this memory.", "record_id")
    return await mp.present(org, mid, rec, pr)


@router.get("/v1/memories/{mid}/records/{rid}/history")
@guarded
async def history(mid: str, rid: str, request: Request) -> dict:
    org, _, _, pr = await _who(request)
    m, _ = await mp.need(org, mid, pr, "read")
    return {"object": "list", "data": await _records_out(org, mid, await mp.provider_of(m).history(mid, rid), pr)}


# ── queries ───────────────────────────────────────────────────────────────────────────────────
@router.get("/v1/memories/{mid}/queries")
@guarded
async def list_queries(mid: str, request: Request) -> dict:
    org, _, _, pr = await _who(request)
    m, _ = await mp.need(org, mid, pr, "read")
    return {"object": "list", "data": await mp.provider_of(m).queries(mid)}


@router.put("/v1/memories/{mid}/queries/{name}")
@guarded
async def define_query(mid: str, name: str, request: Request) -> dict:
    org, member, _, pr = await _who(request)
    m, _ = await mp.need(org, mid, pr, "write")
    b = await _json(request)
    if not name.replace("_", "").isalnum() or not b.get("body") or b.get("requires", "read") not in ("read", "write"):
        raise _uhp_error(422, "memory_invalid", "A named query has a name of letters, digits and underscores, a body, and requires read or write.")
    q = {"name": name, "description": str(b.get("description") or ""), "params": b.get("params") or {"type": "object"},
         "requires": b.get("requires", "read"), "language": str(b.get("language") or ""), "body": str(b["body"]),
         "defined_by": mp.writer_of(member)}
    return await mp.provider_of(m).define_query(mid, q)


@router.post("/v1/memories/{mid}/queries/{name}")
@guarded
async def run_query(mid: str, name: str, request: Request) -> dict:
    org, _, _, pr = await _who(request)
    m, privs = await mp.need(org, mid, pr, "read")
    prov = mp.provider_of(m)
    q = next((x for x in await prov.queries(mid) if x["name"] == name), None)
    if not q:
        raise _uhp_error(404, "memory_not_found", "No such query on this memory.", "name")
    if q.get("requires", "read") not in privs:
        raise _uhp_error(403, "memory_forbidden", f"This query needs `{q['requires']}` on the memory.")
    return await _answer(org, m, pr, await prov.run_query(mid, name, (await _json(request)).get("params") or {}))


@router.post("/v1/memories/{mid}/query")
@guarded
async def free_query(mid: str, request: Request) -> dict:
    org, _, _, pr = await _who(request)
    m, privs = await mp.need(org, mid, pr, "read")
    b = await _json(request)
    prov = mp.provider_of(m)
    free = (prov.capabilities().get("queries") or {}).get("free") or {}
    if not free:
        raise _uhp_error(422, "memory_unsupported", "This memory's provider does not run a query written by the caller.")
    write = bool(b.get("write"))
    if write and "write" not in privs:
        raise _uhp_error(403, "memory_forbidden", "A query that writes needs `write` on the memory.")
    if not b.get("statement"):
        raise _uhp_error(422, "memory_invalid", "Give the statement to run.", "statement")
    res = await prov.free_query(mid, str(b.get("language") or ""), str(b["statement"]), b.get("params") or {}, write)
    if "results" not in res:           # the provider's own rows, as they are
        return {"object": "memory.query", "rows": res.get("rows") or [], "degraded": res.get("degraded") or []}
    return await _answer(org, m, pr, res)


# ── type operations ───────────────────────────────────────────────────────────────────────────
@router.post("/v1/memories/{mid}/records/{rid}/operations/{name}")
@guarded
async def operate(mid: str, rid: str, name: str, request: Request) -> dict:
    org, member, _, pr = await _who(request)
    m, privs = await mp.need(org, mid, pr, "read")
    prov = mp.provider_of(m)
    needs = await prov.operation_requires(mid, rid, name)
    if needs not in privs:
        raise _uhp_error(403, "memory_forbidden", f"This operation needs `{needs}` on the memory.")
    return {"object": "memory.operation", "name": name,
            "result": await prov.operate(mid, rid, name, await _json(request), mp.writer_of(member))}


# ── snapshots: a name for an instant ──────────────────────────────────────────────────────────
@router.post("/v1/memories/{mid}/snapshots")
@guarded
async def snapshot(mid: str, request: Request) -> dict:
    org, member, _, pr = await _who(request)
    await mp.need(org, mid, pr, "write")
    b = await _json(request)
    name = str(b.get("name") or "").strip()
    if not name:
        raise _uhp_error(422, "memory_invalid", "Give the snapshot a name.", "name")
    sid = "hsnp_" + uuid.uuid4().hex
    at = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int((time.time() % 1) * 1000):03d}Z"
    props = {"org": org, "memory_id": mid, "name": name, "message": str(b.get("message") or ""), "at": at, "by": member}
    await mp.GRAPH.upsert("MemorySnapshot", sid, props, raise_on_fail=True)
    return {"id": sid, "object": "memory.snapshot", **{k: props[k] for k in ("memory_id", "name", "message", "at")}}


@router.get("/v1/memories/{mid}/snapshots")
@guarded
async def snapshots(mid: str, request: Request) -> dict:
    org, _, _, pr = await _who(request)
    await mp.need(org, mid, pr, "read")
    rows = await mp.GRAPH.find("MemorySnapshot", {"org": org, "memory_id": mid})
    return {"object": "list", "data": sorted(
        [{"id": r["id"], "object": "memory.snapshot", "memory_id": mid, "name": r.get("name"),
          "message": r.get("message") or "", "at": r.get("at")} for r in rows], key=lambda x: x["at"], reverse=True)}


# ── consolidation runs ────────────────────────────────────────────────────────────────────────
@router.post("/v1/memories/{mid}/consolidations")
@guarded
async def consolidate(mid: str, request: Request) -> dict:
    org, _, _, pr = await _who(request)
    m, _ = await mp.need(org, mid, pr, "write")
    try:
        b = await request.json()
    except ValueError:
        b = {}
    return await mp.provider_of(m).consolidate(mid, (b or {}).get("budget"), "request")


@router.get("/v1/memories/{mid}/consolidations")
@guarded
async def consolidations(mid: str, request: Request) -> dict:
    org, _, _, pr = await _who(request)
    m, _ = await mp.need(org, mid, pr, "read")
    return {"object": "list", "data": await mp.provider_of(m).consolidations(mid)}


@router.get("/v1/memories/{mid}/consolidations/{run}")
@guarded
async def consolidation(mid: str, run: str, request: Request) -> dict:
    org, _, _, pr = await _who(request)
    m, _ = await mp.need(org, mid, pr, "read")
    r = await mp.provider_of(m).consolidation(mid, run)
    if not r:
        raise _uhp_error(404, "memory_not_found", "No such consolidation run.", "run")
    return r


@router.get("/v1/memories/{mid}/consolidations/{run}/changes")
@guarded
async def consolidation_changes(mid: str, run: str, request: Request) -> dict:
    org, _, _, pr = await _who(request)
    m, _ = await mp.need(org, mid, pr, "read")
    seen: dict = {}
    return {"object": "list", "data": [{"change": c["change"], "record": await mp.present(org, mid, c["record"], pr, seen)}
                                       for c in await mp.provider_of(m).consolidation_changes(mid, run)]}


@router.post("/v1/memories/{mid}/consolidations/{run}/revert")
@guarded
async def revert(mid: str, run: str, request: Request) -> dict:
    org, member, _, pr = await _who(request)
    m, _ = await mp.need(org, mid, pr, "delete")
    return await mp.provider_of(m).revert_consolidation(mid, run, mp.writer_of(member))
