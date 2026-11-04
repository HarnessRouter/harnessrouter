"""A small HTTP server over graphiti-core, for HarnessRouter's Graphiti memory provider.

Graphiti is a library. Its own REST server takes no entity types, so a schema could never reach
extraction through it, and the schema is the reason to choose Graphiti. This serves what a provider
needs and nothing else: an episode with the types it should extract, stated nodes and facts, search,
reads and deletes. A group is one memory.

The graph is kept in LadybugDB (MIT), a graph database that runs inside this server, one file per memory. So a
memory is kept apart by the store itself, and erasing a memory removes its file.

Set GRAPHITI_API_KEY to require a bearer. It listens on all interfaces, so keep it on a private network."""
from __future__ import annotations

import asyncio
import os
import re
import sys
import time
import types
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

import ladybug
from fastapi import Depends, FastAPI, Header, HTTPException

DATA = os.environ.get("GRAPHITI_DATA", "/data")
# An open memory costs about 60 MB and a closed one costs nothing, and opening one again takes a moment. So only the
# most recently used stay open, however many are kept.
OPEN_MAX = int(os.environ.get("GRAPHITI_OPEN_MAX", "8"))
# What one open memory may use. It reserves address space for its largest size whether it fills it or not, and the
# store's default of 8 TB runs a process out of address space at about a dozen open. What doesn't fit in the buffer
# is read from its file.
BUFFER_BYTES = int(os.environ.get("GRAPHITI_BUFFER_MB", "128")) << 20
MAX_DB_BYTES = 1 << 40


def _open_store(path: str) -> ladybug.Database:
    return ladybug.Database(path, buffer_pool_size=BUFFER_BYTES, max_db_size=MAX_DB_BYTES, max_num_threads=2)


# Graphiti's embedded driver is written against Kuzu, and LadybugDB is Kuzu's maintained fork with the same interface.
# It imports `kuzu` by name, so that name is given to LadybugDB here, before the driver loads.
sys.modules["kuzu"] = types.SimpleNamespace(Database=_open_store, AsyncConnection=ladybug.AsyncConnection, Connection=ladybug.Connection)

from graphiti_core import Graphiti  # noqa: E402
from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient  # noqa: E402
from graphiti_core.driver.driver import GraphProvider  # noqa: E402
from graphiti_core.driver.kuzu_driver import KuzuDriver  # noqa: E402
from graphiti_core.edges import EntityEdge  # noqa: E402
from graphiti_core.embedder import OpenAIEmbedder  # noqa: E402
from graphiti_core.errors import GroupsEdgesNotFoundError, GroupsNodesNotFoundError  # noqa: E402
from graphiti_core.graph_queries import get_fulltext_indices  # noqa: E402
from graphiti_core.llm_client import LLMConfig, OpenAIClient  # noqa: E402
from graphiti_core.nodes import EntityNode, EpisodeType, EpisodicNode  # noqa: E402
from graphiti_core.search.search_config_recipes import COMBINED_HYBRID_SEARCH_RRF  # noqa: E402
from graphiti_core.search.search_filters import SearchFilters  # noqa: E402
from pydantic import BaseModel, Field, create_model  # noqa: E402

_graphs: dict[str, Graphiti] = {}
_locks: dict[str, asyncio.Lock] = {}
_holding: ContextVar[list | None] = ContextVar("holding", default=None)
_TYPES = {"text": str, "choice": str, "date": str, "number": float, "yesno": bool}
_GROUP = re.compile(r"[A-Za-z0-9_-]{1,128}")


def _lock(group: str) -> asyncio.Lock:
    return _locks.setdefault(group, asyncio.Lock())


async def _close(group: str) -> None:
    """Leaves what was written in the file itself, and not in a log to replay at the next start. Taken out of the
    open ones first, and under its lock, so a request that wants it again waits and then opens it again."""
    g = _graphs.pop(group, None)
    if g is None:
        return
    async with _lock(group):
        try:
            await g.driver.execute_query("CHECKPOINT")
        except Exception as e:  # noqa: BLE001
            print(f"[graphiti] {group} not checkpointed: {type(e).__name__}", flush=True)
        g.driver.client.close()
        g.driver.db.close()


async def _make_room() -> None:
    """Closes what was used longest ago, never one a request is using. With every one in use, more stay open for now."""
    while len(_graphs) > OPEN_MAX:
        idle = [(g._hr_used, group) for group, g in _graphs.items() if not g._hr_busy]
        if not idle:
            return
        await _close(min(idle)[1])


@asynccontextmanager
async def _lifespan(_app):
    yield
    for group in list(_graphs):
        await _close(group)


app = FastAPI(title="Graphiti for HarnessRouter", docs_url=None, redoc_url=None, lifespan=_lifespan)


@app.middleware("http")
async def _let_go(request, call_next):
    """What this request opened stays open until it has answered."""
    held: list[Graphiti] = []
    _holding.set(held)
    try:
        return await call_next(request)
    finally:
        for g in held:
            g._hr_busy -= 1
        await _make_room()


def path_of(group: str) -> str:
    """A group names a file here, so a name that could lead anywhere else is refused."""
    if not _GROUP.fullmatch(group):
        raise HTTPException(400, "a group is letters, digits, dashes and underscores")
    return os.path.join(DATA, f"{group}.lbug")


def exists(group: str) -> bool:
    return group in _graphs or os.path.exists(path_of(group))


class Store(KuzuDriver):
    """The driver leaves out a parameter whose value is None, and this store refuses a query that names a parameter it
    wasn't given. None is how a fact says it hasn't ended, so it has to get there."""

    async def execute_query(self, cypher_query_: str, **kwargs: Any):
        kwargs.pop("database_", None)
        kwargs.pop("routing_", None)
        res = await self.client.execute(cypher_query_, parameters=kwargs)
        if not res:
            return [], None, None
        return ([list(r.rows_as_dict()) for r in res] if isinstance(res, list) else list(res.rows_as_dict())), None, None


def graph_of(group: str) -> Graphiti:
    """One database per group: a memory is kept apart by the store itself."""
    driver = Store(db=path_of(group))
    driver._database = group    # Graphiti compares a group with this, and this driver doesn't set it
    llm, reranker, embedder = _clients()
    return Graphiti(graph_driver=driver, llm_client=llm, cross_encoder=reranker, embedder=embedder)


@lru_cache(maxsize=1)
def _clients():
    """One set for the whole server: memories open and close, and the model's connections have no reason to."""
    cfg = LLMConfig(api_key=os.environ.get("OPENAI_API_KEY"), base_url=os.environ.get("OPENAI_BASE_URL") or None,
                    model=os.environ.get("MODEL_NAME", "gpt-4o-mini"), small_model=os.environ.get("SMALL_MODEL_NAME") or os.environ.get("MODEL_NAME", "gpt-4o-mini"))
    return OpenAIClient(cfg, reasoning=None, verbosity=None), OpenAIRerankerClient(cfg), OpenAIEmbedder()


async def ready(group: str) -> Graphiti:
    g = _graphs.get(group)
    if g is None:
        # One at a time per memory: requests that arrive together would each make its indexes.
        async with _lock(group):
            g = _graphs.get(group)
            if g is None:
                g = await _open_graph(group)
                g._hr_busy = 0
                _graphs[group] = g
    g._hr_used = time.monotonic()
    held = _holding.get()
    if held is not None:
        g._hr_busy += 1
        held.append(g)
    return g


async def _open_graph(group: str) -> Graphiti:
    # A log still holding something means the server didn't stop cleanly. The store replays it, but what it replays
    # doesn't reach the search by words, so that index is made again.
    wal = f"{path_of(group)}.wal"
    replayed = os.path.exists(wal) and os.path.getsize(wal) > 0
    g = await asyncio.to_thread(graph_of, group)
    # Search by words is an extension the store loads per open database, and its indexes are made once, here:
    # the driver leaves both to its caller. A forgotten episode's words and time need columns of their own.
    await g.driver.execute_query("LOAD EXTENSION FTS")
    rows = (await g.driver.execute_query("CALL SHOW_INDEXES() RETURN *"))[0]
    full_text = [r for r in rows if r.get("index_type") == "FTS"]
    if replayed:
        for r in full_text:
            await g.driver.execute_query(f"CALL DROP_FTS_INDEX('{r['table_name']}', '{r['index_name']}')")
            await g.driver.execute_query(r["index_definition"])
        print(f"[graphiti] {group} didn't stop cleanly: its search by words was made again", flush=True)
    have = {str(r.get("index_name")) for r in full_text}
    for q in get_fulltext_indices(GraphProvider.KUZU):
        if not any(f"'{name}'" in q for name in have):
            await g.driver.execute_query(q)
    await g.driver.execute_query("ALTER TABLE Episodic ADD IF NOT EXISTS hr_words STRING")
    await g.driver.execute_query("ALTER TABLE Episodic ADD IF NOT EXISTS hr_forgotten STRING")
    return g


def auth(authorization: str = Header(default="")) -> None:
    key = os.environ.get("GRAPHITI_API_KEY", "")
    if key and authorization != f"Bearer {key}":
        raise HTTPException(401, "invalid key")


def models_of(types: list[dict], key: str = "properties") -> dict[str, type[BaseModel]]:
    """A schema's types as the Pydantic models Graphiti extracts into."""
    out: dict[str, type[BaseModel]] = {}
    for t in types or []:
        name = str(t.get("name") or "")
        if not name:
            continue
        fields: dict[str, Any] = {}
        for p in t.get(key) or []:
            fname = str(p.get("name") or "")
            if not fname.isidentifier() or fname in RESERVED:
                continue
            fields[fname] = (_TYPES.get(str(p.get("type") or "text"), str) | None, Field(default=None, description=str(p.get("description") or fname)))
        m = create_model(name, **fields)
        m.__doc__ = str(t.get("description") or name)
        out[name] = m
    return out


RESERVED = {"uuid", "name", "group_id", "labels", "created_at", "summary", "attributes", "name_embedding", "fact", "fact_embedding",
            "source_node_uuid", "target_node_uuid", "episodes", "expired_at", "valid_at", "invalid_at"}


def iso(t: datetime | None) -> str | None:
    """The store keeps times in UTC and gives them back without saying so."""
    if t is None:
        return None
    return (t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t).isoformat()


def utc(text: str) -> datetime:
    """The store drops an offset instead of applying it, so a time goes in as UTC."""
    t = datetime.fromisoformat(text)
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)


def node_out(n: EntityNode) -> dict:
    return {"uuid": n.uuid, "name": n.name, "summary": n.summary, "labels": n.labels, "attributes": n.attributes,
            "created_at": iso(n.created_at)}


def edge_out(e: EntityEdge) -> dict:
    return {"uuid": e.uuid, "name": e.name, "fact": e.fact, "source": e.source_node_uuid, "target": e.target_node_uuid,
            "episodes": e.episodes, "attributes": e.attributes, "created_at": iso(e.created_at),
            "valid_at": iso(e.valid_at), "invalid_at": iso(e.invalid_at), "expired_at": iso(e.expired_at)}


def episode_out(e: EpisodicNode) -> dict:
    return {"uuid": e.uuid, "name": e.name, "content": e.content, "source_description": e.source_description,
            "created_at": iso(e.created_at), "valid_at": iso(e.valid_at)}


class EpisodeIn(BaseModel):
    group_id: str
    content: str
    name: str = ""
    source_description: str = ""
    reference_time: str | None = None
    entity_types: list[dict] = []
    edge_types: list[dict] = []
    edge_type_map: list[dict] = []


@app.post("/episodes", dependencies=[Depends(auth)])
async def add_episode(b: EpisodeIn) -> dict:
    g = await ready(b.group_id)
    when = utc(b.reference_time) if b.reference_time else datetime.now(timezone.utc)
    emap = {(m["from"], m["to"]): m["names"] for m in b.edge_type_map if m.get("from") and m.get("to") and m.get("names")} or None
    res = await g.add_episode(name=b.name or f"episode-{uuid.uuid4().hex[:8]}", episode_body=b.content, source=EpisodeType.message,
                              source_description=b.source_description or "conversation", reference_time=when, group_id=b.group_id,
                              entity_types=models_of(b.entity_types) or None, edge_types=models_of(b.edge_types) or None, edge_type_map=emap)
    return {"episode": episode_out(res.episode), "nodes": [node_out(n) for n in res.nodes], "edges": [edge_out(e) for e in res.edges]}


class NodeIn(BaseModel):
    group_id: str
    name: str
    summary: str = ""
    labels: list[str] = []
    attributes: dict = {}


@app.post("/nodes", dependencies=[Depends(auth)])
async def add_node(b: NodeIn) -> dict:
    g = await ready(b.group_id)
    n = EntityNode(uuid=str(uuid.uuid4()), name=b.name, group_id=b.group_id, labels=["Entity", *b.labels], summary=b.summary, attributes=b.attributes)
    await n.generate_name_embedding(g.embedder)
    await n.save(g.driver)
    return node_out(n)


class EdgeIn(BaseModel):
    group_id: str
    source: str
    target: str
    name: str
    fact: str
    attributes: dict = {}
    valid_at: str | None = None


@app.post("/edges", dependencies=[Depends(auth)])
async def add_edge(b: EdgeIn) -> dict:
    g = await ready(b.group_id)
    e = EntityEdge(uuid=str(uuid.uuid4()), group_id=b.group_id, source_node_uuid=b.source, target_node_uuid=b.target, name=b.name, fact=b.fact,
                   episodes=[], created_at=datetime.now(timezone.utc), valid_at=utc(b.valid_at) if b.valid_at else None, attributes=b.attributes)
    await e.generate_embedding(g.embedder)
    await e.save(g.driver)
    return edge_out(e)


class SearchIn(BaseModel):
    group_id: str
    query: str
    limit: int = 10


@app.post("/search", dependencies=[Depends(auth)])
async def search(b: SearchIn) -> dict:
    if not exists(b.group_id):
        return {"edges": [], "nodes": [], "episodes": []}
    g = await ready(b.group_id)
    cfg = COMBINED_HYBRID_SEARCH_RRF.model_copy(deep=True)
    cfg.limit = b.limit
    res = await g.search_(b.query, config=cfg, group_ids=[b.group_id], search_filter=SearchFilters())
    return {"edges": [edge_out(e) for e in res.edges], "nodes": [node_out(n) for n in res.nodes], "episodes": [episode_out(x) for x in res.episodes]}


async def mentioned_in(g, group: str) -> dict[str, list[str]]:
    rows, _, _ = await g.driver.execute_query(
        "MATCH (e:Episodic)-[:MENTIONS]->(n:Entity) WHERE e.group_id = $gid RETURN n.uuid AS uuid, collect(e.uuid) AS episodes", gid=group)
    return {r["uuid"]: r["episodes"] for r in rows}


@app.get("/groups/{group}/nodes", dependencies=[Depends(auth)])
async def nodes(group: str, limit: int = 100) -> list[dict]:
    if not exists(group):
        return []
    g = await ready(group)
    try:
        found = await EntityNode.get_by_group_ids(g.driver, [group], limit=limit)
    except GroupsNodesNotFoundError:
        return []
    mentioned = await mentioned_in(g, group)
    return [{**node_out(n), "episodes": mentioned.get(n.uuid, [])} for n in found]


@app.get("/groups/{group}/edges", dependencies=[Depends(auth)])
async def edges(group: str, limit: int = 100) -> list[dict]:
    if not exists(group):
        return []
    g = await ready(group)
    try:
        return [edge_out(e) for e in await EntityEdge.get_by_group_ids(g.driver, [group], limit=limit)]
    except GroupsEdgesNotFoundError:
        return []


@app.get("/groups/{group}/episodes", dependencies=[Depends(auth)])
async def episodes(group: str, limit: int = 100) -> list[dict]:
    if not exists(group):
        return []
    g = await ready(group)
    closed, _, _ = await g.driver.execute_query(
        "MATCH (e:Episodic) WHERE e.group_id = $gid AND e.hr_forgotten IS NOT NULL RETURN e.uuid AS uuid, e.hr_words AS words, e.hr_forgotten AS at", gid=group)
    by = {r["uuid"]: r for r in closed}
    out = []
    for e in await EpisodicNode.get_by_group_ids(g.driver, [group], limit=limit):
        x = episode_out(e)
        if e.uuid in by:
            x.update(content=by[e.uuid]["words"] or "", forgotten_at=by[e.uuid]["at"])
        out.append(x)
    return out


class EpisodeForget(BaseModel):
    at: str


@app.post("/groups/{group}/episodes/{uid}/forget", dependencies=[Depends(auth)])
async def forget_episode(group: str, uid: str, b: EpisodeForget) -> dict:
    """Graphiti reads recent episodes back as context for the next extraction, so a forgotten one's words
    leave `content` and are kept beside it as its trace. Otherwise the next episode could learn them again."""
    g = await ready(group)
    done, _, _ = await g.driver.execute_query(
        "MATCH (e:Episodic {uuid: $uid}) WHERE e.group_id = $gid AND e.hr_forgotten IS NULL "
        "SET e.hr_words = e.content, e.content = '', e.hr_forgotten = $at RETURN e.uuid AS uuid", uid=uid, gid=group, at=b.at)
    if not done:
        raise HTTPException(404, "no such episode")
    return {"uuid": uid, "forgotten_at": b.at}


@app.get("/groups/{group}/nodes/{uid}", dependencies=[Depends(auth)])
async def node(group: str, uid: str) -> dict:
    if not exists(group):
        raise HTTPException(404, "no such node")
    g = await ready(group)
    try:
        return {**node_out(await EntityNode.get_by_uuid(g.driver, uid)), "episodes": (await mentioned_in(g, group)).get(uid, [])}
    except Exception:  # noqa: BLE001 -- graphiti raises its own error for a miss
        raise HTTPException(404, "no such node") from None


@app.get("/groups/{group}/edges/{uid}", dependencies=[Depends(auth)])
async def edge(group: str, uid: str) -> dict:
    if not exists(group):
        raise HTTPException(404, "no such edge")
    g = await ready(group)
    try:
        return edge_out(await EntityEdge.get_by_uuid(g.driver, uid))
    except Exception:  # noqa: BLE001
        raise HTTPException(404, "no such edge") from None


class Close(BaseModel):
    at: str | None = None
    forgotten: bool = False


class NodePut(BaseModel):
    name: str | None = None
    summary: str = ""
    attributes: dict = {}


@app.put("/groups/{group}/nodes/{uid}", dependencies=[Depends(auth)])
async def put_node(group: str, uid: str, b: NodePut) -> dict:
    g = await ready(group)
    n = await EntityNode.get_by_uuid(g.driver, uid)
    n.summary, n.attributes = b.summary, b.attributes
    if b.name:
        n.name = b.name
        await n.generate_name_embedding(g.embedder)
    await n.save(g.driver)
    return node_out(n)


class EdgePut(BaseModel):
    fact: str


@app.put("/groups/{group}/edges/{uid}", dependencies=[Depends(auth)])
async def put_edge(group: str, uid: str, b: EdgePut) -> dict:
    g = await ready(group)
    e = await EntityEdge.get_by_uuid(g.driver, uid)
    e.fact = b.fact
    await e.generate_embedding(g.embedder)
    await e.save(g.driver)
    return edge_out(e)


@app.post("/groups/{group}/edges/{uid}/close", dependencies=[Depends(auth)])
async def close_edge(group: str, uid: str, b: Close) -> dict:
    g = await ready(group)
    e = await EntityEdge.get_by_uuid(g.driver, uid)
    when = utc(b.at) if b.at else datetime.now(timezone.utc)
    e.invalid_at, e.expired_at = when, datetime.now(timezone.utc)
    if b.forgotten:
        e.attributes = {**(e.attributes or {}), "hr_forgotten": "1"}
    await e.save(g.driver)
    return edge_out(e)


@app.delete("/groups/{group}/edges/{uid}", dependencies=[Depends(auth)])
async def del_edge(group: str, uid: str) -> dict:
    g = await ready(group)
    await (await EntityEdge.get_by_uuid(g.driver, uid)).delete(g.driver)
    return {"deleted": uid}


@app.delete("/groups/{group}/nodes/{uid}", dependencies=[Depends(auth)])
async def del_node(group: str, uid: str) -> dict:
    g = await ready(group)
    await (await EntityNode.get_by_uuid(g.driver, uid)).delete(g.driver)
    return {"deleted": uid}


@app.delete("/groups/{group}/episodes/{uid}", dependencies=[Depends(auth)])
async def del_episode(group: str, uid: str) -> dict:
    g = await ready(group)
    await g.remove_episode(uid)
    return {"deleted": uid}


@app.delete("/groups/{group}", dependencies=[Depends(auth)])
async def del_group(group: str) -> dict:
    """The memory's file goes, with its log and whatever else the store keeps beside it."""
    path = path_of(group)
    await _close(group)
    for name in os.listdir(DATA):
        if name == f"{group}.lbug" or name.startswith(f"{group}.lbug."):
            os.remove(os.path.join(DATA, name))
    return {"deleted": group, "path_gone": not os.path.exists(path)}


@app.get("/check", dependencies=[Depends(auth)])
async def check() -> dict:
    """A connection is tried here before it is kept, so a wrong key is refused then and not at the first write."""
    return {"ok": True}


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}
