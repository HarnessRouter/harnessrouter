"""The Harness Memories sub-protocol over HTTP: every route is the caller's principals, one access
check in memory_plane, and one call to the memory's provider. Nothing here knows a provider."""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

import memory_plane as mp

router = APIRouter()
_principal = None          # app.py's resolver, bound by install()
_uhp_error = None


_file_bytes = None          # app.py's reader of an uploaded file's bytes, bound by install()
_on_grant = None            # app.py's hook after a grant is written, bound by install()


def install(app, principal, uhp_error, graph, file_meta=None, file_bytes=None, on_grant=None) -> None:
    """Bind the gateway's principal resolver, error envelope, graph backing and file store, and
    mount the routes. `on_grant(org, principal)` runs after a grant is written: the gateway uses
    it to give an agent that was just let into its first memory the tools to use it."""
    global _principal, _uhp_error, _file_bytes, _on_grant
    _principal, _uhp_error, mp.GRAPH, mp.FILES, _file_bytes, _on_grant = principal, uhp_error, graph, file_meta, file_bytes, on_grant
    if os.environ.get("HR_MEMORY_FIXTURE") == "1" and "fixture" not in mp.PROVIDERS:
        import memory_fixture
        mp.PROVIDERS["fixture"] = memory_fixture.FixtureProvider()
    app.include_router(router)


def principals_of(p: dict) -> list[str]:
    """Who a caller is to the access model: the person, and the group that is the workspace it acts in."""
    out = []
    if p.get("member"):
        out.append(f"member:{p['member']}")
    if p.get("workspace"):
        out.append(f"group:{p['workspace']}")
    return out


async def _who(request: Request) -> tuple[str, str, str, list[str]]:
    p = await _principal(request)
    org = p.get("org", "")
    if not org:
        raise _uhp_error(401, "invalid_credential", "Missing or invalid API key.")
    # The workspace a memory belongs to is named the way a plug's is (the console's header, else the
    # instance's default workspace), so a memory finds the provider its own workspace connected.
    ws = str(request.headers.get("x-harness-workspace") or p.get("workspace") or "default")
    return org, str(p.get("member") or ""), ws, principals_of(p)


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


async def _once(request: Request, org: str, member: str, mid: str, what: str, write):
    """A write that makes something, made once per Idempotency-Key: a retry with the key of a write
    that was answered gets that answer again and makes nothing. The key is the caller's (an agent's
    CLI retries a tool call; a client retries after a timeout), scoped to the caller, the memory and
    the operation. Kept with the graph, so any replica answers the retry. `write()` returns
    (status, body)."""
    key = (request.headers.get("Idempotency-Key") or "").strip()
    if not key:
        return await write()
    vid = "hmw_" + hashlib.sha256(f"{org}|{member}|{mid}|{what}|{key}".encode()).hexdigest()[:40]
    seen = await mp.GRAPH.get(vid, label="MemoryWrite")
    if seen and seen.get("answer"):
        return int(seen.get("status") or 200), json.loads(seen["answer"])
    status, body = await write()
    await mp.GRAPH.upsert("MemoryWrite", vid, {"org": org, "memory_id": mid, "status": str(status),
                                             "answer": json.dumps(body, separators=(",", ":")), "at": str(int(time.time()))})
    return status, body


def _answer_of(status: int, body: dict):
    return body if status == 200 else JSONResponse(body, status_code=status)


async def _records_out(org, mid, records, pr) -> list[dict]:
    seen: dict = {}
    return [await mp.present(org, mid, r, pr, seen) for r in records]


async def _answer(org, m, pr, res: dict, places: dict | None = None) -> dict:
    """A recall-shaped answer: the results presented to this reader, each with the memory it is
    in (the place to walk from), and where the reader can go from the memory that was asked."""
    seen: dict = {}
    places = places or {str(m["id"]): m}
    results = []
    for x in res.get("results") or []:
        mid = str(x.get("memory_id") or m["id"])
        results.append({"record": await mp.present(org, mid, x["record"], pr, seen),
                        "memory": {"id": mid, "name": (places.get(mid) or {}).get("name") or ""},
                        "score": x.get("score"), "why": x.get("why") or []})
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
async def list_memories(request: Request, parent: str = "", ancestor: str = "", granted: bool = False) -> dict:
    org, _, _, pr = await _who(request)
    if granted:
        return {"object": "list", "data": await mp.given(org, pr)}
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
    g = await mp.grant(org, mid, pr, b.get("principal"), b.get("privileges") or [], member)
    if _on_grant:
        await _on_grant(org, g["principal"])
    return g


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
    if not isinstance(eps, list) or not eps or not all(isinstance(e, dict) for e in eps):
        raise _uhp_error(422, "memory_invalid", "`episodes` is a non-empty list, each with content.", "episodes")
    prov = await mp.provider_of(m)
    eps = [{"content": await mp.settle_files(org, mp.parts_of(e.get("content")), prov),
            "attributes": dict(e.get("attributes") or {})} for e in eps]

    async def write():
        made = await prov.observe(mid, eps, mp.writer_of(member))
        body = {"object": "list", "data": await _records_out(org, mid, made.get("records") or [], pr)}
        if made.get("job"):
            # the provider derives after it answers: what it wrote is read from the job once it settles
            return 202, {**body, "job": {"object": "memory.job", **made["job"]}}
        return 200, body
    return _answer_of(*await _once(request, org, member, mid, "observe", write))


@router.get("/v1/memories/{mid}/jobs/{job_id}")
@guarded
async def job(mid: str, job_id: str, request: Request) -> dict:
    org, _, _, pr = await _who(request)
    m, _ = await mp.need(org, mid, pr, "read")
    j = await (await mp.provider_of(m)).job(mid, job_id)
    if not j:
        raise _uhp_error(404, "memory_not_found", "No such job on this memory.", "job_id")
    return {"object": "memory.job", "id": j["id"], "status": j["status"], "error": j.get("error") or "",
            "data": await _records_out(org, mid, j.get("records") or [], pr)}


@router.post("/v1/memories/{mid}/records")
@guarded
async def remember(mid: str, request: Request) -> dict:
    org, member, _, pr = await _who(request)
    m, _ = await mp.need(org, mid, pr, "write")
    prov, rec_in = await mp.provider_of(m), mp._record_in(await _json(request))
    await mp.settle_files(org, rec_in["content"], prov)

    async def write():
        return 200, await mp.present(org, mid, await prov.remember(mid, rec_in, mp.writer_of(member)), pr)
    return _answer_of(*await _once(request, org, member, mid, "remember", write))


@router.patch("/v1/memories/{mid}/records/{rid}")
@guarded
async def revise(mid: str, rid: str, request: Request) -> dict:
    org, member, _, pr = await _who(request)
    m, _ = await mp.need(org, mid, pr, "write")
    b = await _json(request)
    patch = {k: b[k] for k in ("title", "content", "attributes", "references", "time") if k in b}
    if not patch:
        raise _uhp_error(422, "memory_invalid", "A revision changes the title, content, attributes, references or time.")
    if "title" in patch:
        patch["title"] = mp.title_of(patch["title"])
    prov = await mp.provider_of(m)
    if "content" in patch:
        patch["content"] = await mp.settle_files(org, mp.parts_of(patch["content"]), prov)
    if "references" in patch:
        # A reviser sets the references it can see. One that leads into a memory it may not read was
        # shown to it as unavailable, without where it leads: it can neither restate nor remove it,
        # so it stays as it was.
        cur = await prov.get(mid, rid)
        kept = []
        for ref in (cur or {}).get("references") or []:
            tm = str(ref.get("memory_id") or mid)
            t = await mp._load(org, tm)
            if not t or "read" not in await mp.effective(org, t, pr):
                kept.append(ref)
        stated = mp._record_in({"type": (cur or {}).get("type") or "fact", "title": "x",
                                "references": [r for r in patch["references"] if isinstance(r, dict) and r.get("available") is not False]})["references"]
        patch["references"] = stated + kept
    return await mp.present(org, mid, await prov.revise(mid, rid, patch, mp.writer_of(member)), pr)


@router.delete("/v1/memories/{mid}/records/{rid}")
@guarded
async def forget(mid: str, rid: str, request: Request) -> dict:
    org, member, _, pr = await _who(request)
    m, _ = await mp.need(org, mid, pr, "write")
    return await mp.present(org, mid, await (await mp.provider_of(m)).forget(mid, rid, mp.writer_of(member)), pr)


@router.post("/v1/memories/{mid}/erase")
@guarded
async def erase(mid: str, request: Request) -> dict:
    org, _, _, pr = await _who(request)
    m, _ = await mp.need(org, mid, pr, "delete")
    ids = (await _json(request)).get("record_ids")
    if not isinstance(ids, list) or not ids:
        raise _uhp_error(422, "memory_invalid", "`record_ids` names what to erase.", "record_ids")
    res = await (await mp.provider_of(m)).erase(mid, [str(i) for i in ids])
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
    req = {k: b.get(k) for k in ("query", "text", "filters", "types", "as_of", "include")}
    req["limit"] = max(1, min(int(b.get("limit") or 8), 100))
    depth = b.get("depth")
    if depth is not None and (not isinstance(depth, int) or isinstance(depth, bool) or depth < 0):
        raise _uhp_error(422, "memory_invalid", "`depth` is a whole number of levels below this memory; 0 is this memory alone.", "depth")
    # A question is asked of the whole subtree the caller may read: that is how a caller finds where
    # to start. What it reads back names the memory each answer is in.
    reach, cut = await mp.reach_below(org, m, pr, depth)
    res = await mp.recall(org, reach, req)
    if cut:
        res["degraded"].append(f"subtree:capped_at_{mp.RECALL_MAX_MEMORIES}_memories")
    return await _answer(org, m, pr, res, {str(x["id"]): x for x in reach})


@router.post("/v1/memories/{mid}/graph")
@guarded
async def graph(mid: str, request: Request) -> dict:
    """The records of a memory as one graph: nodes are records (entities among them, where the
    provider keeps any), edges are their references."""
    org, _, _, pr = await _who(request)
    m, _ = await mp.need(org, mid, pr, "read")
    b = await _json(request)
    hops = b.get("hops", 1)
    if not isinstance(hops, int) or isinstance(hops, bool) or not 0 <= hops <= 3:
        raise _uhp_error(422, "memory_invalid", "`hops` is 0 to 3: how many references away from the start.", "hops")
    types = b.get("types")
    if types is not None and (not isinstance(types, list) or not all(isinstance(t, str) for t in types)):
        raise _uhp_error(422, "memory_invalid", "`types` is a list of record types.", "types")
    return {"object": "memory.graph", **await mp.graph(org, m, pr, around=str(b.get("around") or ""), hops=hops,
                                                       types=types or None, limit=b.get("limit") or 200)}


@router.get("/v1/memories/{mid}/records")
@guarded
async def list_records(mid: str, request: Request, type: str = "", as_of: str = "", include: str = "active",
                       limit: int = 50, cursor: str = "") -> dict:
    org, _, _, pr = await _who(request)
    m, _ = await mp.need(org, mid, pr, "read")
    res = await (await mp.provider_of(m)).list(mid, {"types": [type] if type else None, "as_of": as_of or None,
                                             "include": include, "limit": max(1, min(limit, 200)), "cursor": cursor})
    return {"object": "list", "data": await _records_out(org, mid, res.get("records") or [], pr),
            "next": res.get("next"), **await mp.neighbours(org, m, pr)}


@router.get("/v1/memories/{mid}/records/{rid}")
@guarded
async def get_record(mid: str, rid: str, request: Request, as_of: str = "") -> dict:
    org, _, _, pr = await _who(request)
    m, _ = await mp.need(org, mid, pr, "read")
    rec = await (await mp.provider_of(m)).get(mid, rid, as_of or None)
    if not rec:
        raise _uhp_error(404, "memory_record_not_found", "No such record in this memory.", "record_id")
    return await mp.present(org, mid, rec, pr)


@router.get("/v1/memories/{mid}/records/{rid}/content/{index}")
@guarded
async def record_file(mid: str, rid: str, index: int, request: Request, as_of: str = ""):
    """The bytes of one file part of a record. The record carries the reference; this is where
    the bytes are read, by whoever may read the record."""
    org, _, _, pr = await _who(request)
    m, _ = await mp.need(org, mid, pr, "read")
    rec = await (await mp.provider_of(m)).get(mid, rid, as_of or None)
    parts = (await mp.present(org, mid, rec, pr))["content"] if rec else []
    if not rec or index < 0 or index >= len(parts) or parts[index].get("type") != "file":
        raise _uhp_error(404, "memory_record_not_found", "No such file part in this record.", "index")
    f = parts[index]["file"]
    data = await _file_bytes(org, str(f["id"])) if _file_bytes else None
    if data is None:
        raise _uhp_error(404, "memory_record_not_found", "The file this part names is no longer kept.", "index")
    return Response(content=data, media_type=f.get("media_type") or "application/octet-stream",
                    headers={"content-disposition": f'attachment; filename="{str(f.get("name") or "file").replace(chr(34), "")}"',
                             "x-content-type-options": "nosniff"})


@router.get("/v1/memories/{mid}/records/{rid}/history")
@guarded
async def history(mid: str, rid: str, request: Request) -> dict:
    org, _, _, pr = await _who(request)
    m, _ = await mp.need(org, mid, pr, "read")
    return {"object": "list", "data": await _records_out(org, mid, await (await mp.provider_of(m)).history(mid, rid), pr)}


# ── queries ───────────────────────────────────────────────────────────────────────────────────
@router.get("/v1/memories/{mid}/queries")
@guarded
async def list_queries(mid: str, request: Request) -> dict:
    org, _, _, pr = await _who(request)
    m, _ = await mp.need(org, mid, pr, "read")
    return {"object": "list", "data": await (await mp.provider_of(m)).queries(mid)}


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
    return await (await mp.provider_of(m)).define_query(mid, q)


@router.post("/v1/memories/{mid}/queries/{name}")
@guarded
async def run_query(mid: str, name: str, request: Request) -> dict:
    org, _, _, pr = await _who(request)
    m, privs = await mp.need(org, mid, pr, "read")
    prov = await mp.provider_of(m)
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
    prov = await mp.provider_of(m)
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
    prov = await mp.provider_of(m)
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
    return await (await mp.provider_of(m)).consolidate(mid, (b or {}).get("budget"), "request")


@router.get("/v1/memories/{mid}/consolidations")
@guarded
async def consolidations(mid: str, request: Request) -> dict:
    org, _, _, pr = await _who(request)
    m, _ = await mp.need(org, mid, pr, "read")
    return {"object": "list", "data": await (await mp.provider_of(m)).consolidations(mid)}


@router.get("/v1/memories/{mid}/consolidations/{run}")
@guarded
async def consolidation(mid: str, run: str, request: Request) -> dict:
    org, _, _, pr = await _who(request)
    m, _ = await mp.need(org, mid, pr, "read")
    r = await (await mp.provider_of(m)).consolidation(mid, run)
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
                                       for c in await (await mp.provider_of(m)).consolidation_changes(mid, run)]}


@router.post("/v1/memories/{mid}/consolidations/{run}/revert")
@guarded
async def revert(mid: str, run: str, request: Request) -> dict:
    org, member, _, pr = await _who(request)
    m, _ = await mp.need(org, mid, pr, "delete")
    return await (await mp.provider_of(m)).revert_consolidation(mid, run, mp.writer_of(member))
