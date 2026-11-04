"""A small HTTP server over graphiti-core, for HarnessRouter's Graphiti memory provider.

Graphiti is a library. Its own REST server takes no entity types, so a schema could never reach
extraction through it, and the schema is the reason to choose Graphiti. This serves what a provider
needs and nothing else: an episode with the types it should extract, stated nodes and facts, search,
reads and deletes. A group is one memory.

Set GRAPHITI_API_KEY to require a bearer. It listens on all interfaces, so keep it on a private network."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from graphiti_core import Graphiti
from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
from graphiti_core.driver.falkordb_driver import FalkorDriver
from graphiti_core.edges import EntityEdge
from graphiti_core.errors import GroupsEdgesNotFoundError, GroupsNodesNotFoundError
from graphiti_core.llm_client import LLMConfig, OpenAIClient
from graphiti_core.nodes import EntityNode, EpisodeType, EpisodicNode
from graphiti_core.search.search_config_recipes import COMBINED_HYBRID_SEARCH_RRF
from graphiti_core.search.search_filters import SearchFilters
from pydantic import BaseModel, Field, create_model

app = FastAPI(title="Graphiti for HarnessRouter", docs_url=None, redoc_url=None)
_graphs: dict[str, Graphiti] = {}
_TYPES = {"text": str, "choice": str, "date": str, "number": float, "yesno": bool}


def graph_of(group: str) -> Graphiti:
    """One FalkorDB graph per group: a memory is kept apart by the database itself."""
    if group not in _graphs:
        driver = FalkorDriver(host=os.environ.get("FALKORDB_HOST", "falkordb"), port=int(os.environ.get("FALKORDB_PORT", "6379")),
                              password=os.environ.get("FALKORDB_PASSWORD") or None, database=group)
        cfg = LLMConfig(api_key=os.environ.get("OPENAI_API_KEY"), base_url=os.environ.get("OPENAI_BASE_URL") or None,
                        model=os.environ.get("MODEL_NAME", "gpt-4o-mini"), small_model=os.environ.get("SMALL_MODEL_NAME") or os.environ.get("MODEL_NAME", "gpt-4o-mini"))
        _graphs[group] = Graphiti(graph_driver=driver, llm_client=OpenAIClient(cfg, reasoning=None, verbosity=None), cross_encoder=OpenAIRerankerClient(cfg))
    return _graphs[group]


async def ready(group: str) -> Graphiti:
    g = graph_of(group)
    if not getattr(g, "_hr_ready", False):
        await g.build_indices_and_constraints()
        g._hr_ready = True
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


def node_out(n: EntityNode) -> dict:
    return {"uuid": n.uuid, "name": n.name, "summary": n.summary, "labels": n.labels, "attributes": n.attributes,
            "created_at": n.created_at.isoformat() if n.created_at else None}


def edge_out(e: EntityEdge) -> dict:
    return {"uuid": e.uuid, "name": e.name, "fact": e.fact, "source": e.source_node_uuid, "target": e.target_node_uuid,
            "episodes": e.episodes, "attributes": e.attributes, "created_at": e.created_at.isoformat() if e.created_at else None,
            "valid_at": e.valid_at.isoformat() if e.valid_at else None, "invalid_at": e.invalid_at.isoformat() if e.invalid_at else None,
            "expired_at": e.expired_at.isoformat() if e.expired_at else None}


def episode_out(e: EpisodicNode) -> dict:
    return {"uuid": e.uuid, "name": e.name, "content": e.content, "source_description": e.source_description,
            "created_at": e.created_at.isoformat() if e.created_at else None, "valid_at": e.valid_at.isoformat() if e.valid_at else None}


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
    when = datetime.fromisoformat(b.reference_time) if b.reference_time else datetime.now(timezone.utc)
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
                   episodes=[], created_at=datetime.now(timezone.utc), valid_at=datetime.fromisoformat(b.valid_at) if b.valid_at else None, attributes=b.attributes)
    await e.generate_embedding(g.embedder)
    await e.save(g.driver)
    return edge_out(e)


class SearchIn(BaseModel):
    group_id: str
    query: str
    limit: int = 10


@app.post("/search", dependencies=[Depends(auth)])
async def search(b: SearchIn) -> dict:
    g = await ready(b.group_id)
    cfg = COMBINED_HYBRID_SEARCH_RRF.model_copy(deep=True)
    cfg.limit = b.limit
    res = await g.search_(b.query, config=cfg, group_ids=[b.group_id], search_filter=SearchFilters())
    return {"edges": [edge_out(e) for e in res.edges], "nodes": [node_out(n) for n in res.nodes], "episodes": [episode_out(x) for x in res.episodes]}


async def mentioned_in(g, group: str) -> dict[str, list[str]]:
    rows, _, _ = await g.driver.execute_query(
        "MATCH (e:Episodic)-[:MENTIONS]->(n:Entity) WHERE e.group_id = $group RETURN n.uuid AS uuid, collect(e.uuid) AS episodes", group=group)
    return {r["uuid"]: r["episodes"] for r in rows}


@app.get("/groups/{group}/nodes", dependencies=[Depends(auth)])
async def nodes(group: str, limit: int = 100) -> list[dict]:
    g = await ready(group)
    try:
        found = await EntityNode.get_by_group_ids(g.driver, [group], limit=limit)
    except GroupsNodesNotFoundError:
        return []
    mentioned = await mentioned_in(g, group)
    return [{**node_out(n), "episodes": mentioned.get(n.uuid, [])} for n in found]


@app.get("/groups/{group}/edges", dependencies=[Depends(auth)])
async def edges(group: str, limit: int = 100) -> list[dict]:
    g = await ready(group)
    try:
        return [edge_out(e) for e in await EntityEdge.get_by_group_ids(g.driver, [group], limit=limit)]
    except GroupsEdgesNotFoundError:
        return []


@app.get("/groups/{group}/episodes", dependencies=[Depends(auth)])
async def episodes(group: str, limit: int = 100) -> list[dict]:
    g = await ready(group)
    closed, _, _ = await g.driver.execute_query(
        "MATCH (e:Episodic) WHERE e.group_id = $group AND e.hr_forgotten IS NOT NULL RETURN e.uuid AS uuid, e.hr_words AS words, e.hr_forgotten AS at", group=group)
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
        "MATCH (e:Episodic {uuid: $uid}) WHERE e.group_id = $group AND e.hr_forgotten IS NULL "
        "SET e.hr_words = e.content, e.content = '', e.hr_forgotten = $at RETURN e.uuid AS uuid", uid=uid, group=group, at=b.at)
    if not done:
        raise HTTPException(404, "no such episode")
    return {"uuid": uid, "forgotten_at": b.at}


@app.get("/groups/{group}/nodes/{uid}", dependencies=[Depends(auth)])
async def node(group: str, uid: str) -> dict:
    g = await ready(group)
    try:
        return {**node_out(await EntityNode.get_by_uuid(g.driver, uid)), "episodes": (await mentioned_in(g, group)).get(uid, [])}
    except Exception:  # noqa: BLE001 -- graphiti raises its own error for a miss
        raise HTTPException(404, "no such node") from None


@app.get("/groups/{group}/edges/{uid}", dependencies=[Depends(auth)])
async def edge(group: str, uid: str) -> dict:
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
    when = datetime.fromisoformat(b.at) if b.at else datetime.now(timezone.utc)
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
    g = await ready(group)
    await g.driver.execute_query("MATCH (n) DETACH DELETE n")
    _graphs.pop(group, None)
    return {"deleted": group}


@app.get("/check", dependencies=[Depends(auth)])
async def check() -> dict:
    """A connection is tried here before it is kept, so a wrong key is refused then and not at the first write."""
    return {"ok": True}


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}
