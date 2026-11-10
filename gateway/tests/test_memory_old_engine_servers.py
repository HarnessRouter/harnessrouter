"""Observe against the engine servers a self-hoster already runs: the images deploy/memories/up.sh built or pulled for
0.40.0 to 0.40.3, which the test instance runs too. Each finished turn now carries guidance for the engine's extraction
(memory_plane.EXTRACTION_GUIDE): Graphiti's custom_extraction_instructions through our own Graphiti server, the Mem0
server's `prompt`, a Hindsight retain strategy with its retain_mission, ReMe's memory_hint. What each server makes of
that is read here from its own request model at the pinned version (copied below as the pinned code declares it; each
was also run, in its image, against these same bodies):

  - Graphiti, our server before this release: EpisodeIn has no such field and a pydantic model ignores what it doesn't
    declare, so the turn is taken and the guidance is not applied until the server is rebuilt (up.sh builds it);
  - Mem0 server at 753496cf: MemoryCreate.prompt is declared, and Memory.add uses it as the extraction's instructions;
  - Hindsight at sha256:19d0c08f: retain_mission is a field a retain strategy may set, a string, and an item names its
    strategy;
  - ReMe at sha256:5fc0ff36: auto_memory declares memory_hint.

None refuses a turn, so nothing is sent conditionally.
"""
from __future__ import annotations

import ast
import asyncio
import json
import os
import sys
from typing import Any, Dict, List, Optional

import httpx
import jsonschema
from pydantic import BaseModel, ConfigDict, Field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import memory_graphiti  # noqa: E402
import memory_hindsight  # noqa: E402
import memory_mem0  # noqa: E402
import memory_plane as mp  # noqa: E402
import memory_reme  # noqa: E402

run = asyncio.run
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TURN = [{"content": [{"type": "text", "role": "user", "text": "Reply with exactly M1"}, {"type": "text", "role": "assistant", "text": "M1"}],
         "attributes": {"session_id": "sess_1", "model": "m", "kind": "turn"}}]
AGENT = {"kind": "member", "id": "hrn_1", "type": "agent"}


def _sent(monkeypatch, module, answer) -> list[tuple[str, str, dict]]:
    calls: list = []

    def handle(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content) if req.content else None
        calls.append((req.method, req.url.path, body))
        return httpx.Response(200, json=answer(req.method, req.url.path, body))
    monkeypatch.setattr(module, "transport", httpx.MockTransport(handle))
    return calls


# ── Graphiti: our server, deploy/memories/graphiti/server.py, as 0.40.0 to 0.40.3 built it ───────────────────────────
class OldEpisodeIn(BaseModel):          # verbatim but for the name; no model_config, so pydantic's extra="ignore"
    group_id: str
    content: str
    name: str = ""
    source_description: str = ""
    reference_time: str | None = None
    entity_types: list[dict] = []
    edge_types: list[dict] = []
    edge_type_map: list[dict] = []
    background: bool = False


def _current_episode_in():
    src = open(os.path.join(ROOT, "deploy", "memories", "graphiti", "server.py")).read()
    node = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == "EpisodeIn")
    ns: dict = {"BaseModel": BaseModel}
    exec(compile(ast.Module([node], []), "server.py", "exec"), ns)
    return ns["EpisodeIn"]


def test_an_old_graphiti_server_takes_the_turn_and_a_rebuilt_one_applies_the_guidance(monkeypatch):
    calls = _sent(monkeypatch, memory_graphiti, lambda m, p, b: {
        "episode": {"uuid": "e1", "name": "episode-1", "content": "x", "created_at": "2026-11-09T00:00:00Z"}, "nodes": [], "edges": []})
    run(memory_graphiti.Graphiti("http://graphiti.test").observe("hmem_1", TURN, AGENT))
    body = next(b for m, p, b in calls if p == "/episodes")
    old = OldEpisodeIn.model_validate(body)                          # no 422: the turn is taken
    assert "custom_extraction_instructions" not in old.model_dump()  # and the guidance is not applied
    assert _current_episode_in().model_validate(body).custom_extraction_instructions == mp.EXTRACTION_GUIDE


# ── Mem0's server at 753496cf (server/main.py), the commit deploy/memories builds ───────────────────────────────────
class Message(BaseModel):
    role: str = Field(..., description="Role of the message (user or assistant).")
    content: str = Field(..., description="Message content.")


class MemoryCreate(BaseModel):
    messages: List[Message] = Field(..., description="List of messages to store.")
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    run_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    expiration_date: Optional[str] = Field(None, description="Expiration date in YYYY-MM-DD format.")
    infer: Optional[bool] = Field(None, description="Whether to extract facts from messages. Defaults to True.")
    memory_type: Optional[str] = Field(None, description="Type of memory to store (e.g. 'core').")
    prompt: Optional[str] = Field(None, description="Custom prompt to use for fact extraction.")


def test_the_pinned_mem0_server_takes_the_guidance_as_its_extraction_prompt(monkeypatch):
    calls = _sent(monkeypatch, memory_mem0, lambda m, p, b: {"results": []})
    run(memory_mem0.Mem0Server("k", "http://mem0.test").observe("hmem_1", TURN, AGENT))
    body = next(b for m, p, b in calls if m == "POST" and p == "/memories")
    got = MemoryCreate.model_validate(body)
    assert got.prompt == mp.EXTRACTION_GUIDE and got.infer is True and set(body) <= set(MemoryCreate.model_fields)


# ── Hindsight at sha256:19d0c08f (hindsight_api/api/http.py, config_resolver.py) ────────────────────────────────────
class RetainRequest(BaseModel):         # the fields it declares; extra is pydantic's default (ignore)
    model_config = ConfigDict(populate_by_name=True)
    items: list[dict]
    async_: Any = Field(None, alias="async")
    document_tags: Any = None
    operation_id: Any = None


MEMORY_ITEM_FIELDS = {"content", "timestamp", "context", "metadata", "document_id", "entities", "resolve_entities", "tags",
                      "observation_scopes", "strategy", "update_mode"}
# _configurable_field_types() for what a strategy here sets: a strategy's overrides are checked against these types
# when the bank's config is updated, and apply_strategy keeps the configurable ones
STRATEGY_FIELD_TYPES = {"retain_mission": str, "retain_extraction_mode": str}


def test_the_pinned_hindsight_takes_a_strategy_with_a_retain_mission_and_items_that_name_it(monkeypatch):
    calls = _sent(monkeypatch, memory_hindsight, lambda m, p, b: {"operation_id": "op1", "items": [], "bank_id": "x"})
    run(memory_hindsight.Hindsight("http://hindsight.test").observe("hmem_1", TURN, AGENT))
    config = next(b for m, p, b in calls if p.endswith("/config"))
    assert set(config) == {"updates"}
    for name, overrides in config["updates"]["retain_strategies"].items():
        for k, v in overrides.items():
            assert isinstance(v, STRATEGY_FIELD_TYPES[k]), (name, k)
    assert config["updates"]["retain_strategies"][memory_hindsight.TURN]["retain_mission"] == mp.EXTRACTION_GUIDE
    retain = RetainRequest.model_validate(next(b for m, p, b in calls if p.endswith("/memories") and m == "POST"))
    assert all(set(i) <= MEMORY_ITEM_FIELDS and i["strategy"] == memory_hindsight.TURN for i in retain.items)


# ── ReMe at sha256:5fc0ff36 (reme/config/default.yaml, auto_memory's parameters) ────────────────────────────────────
AUTO_MEMORY = {"type": "object", "required": ["messages"], "properties": {
    "request_id": {"type": "string"}, "messages": {"type": "array", "items": {"type": "object"}},
    "session_id": {"type": "string", "default": ""}, "memory_hint": {"type": "string"},
    "include_images": {"type": "boolean", "default": False}, "date": {"type": "string", "default": ""}}}


def test_the_pinned_reme_declares_the_hint_its_note_is_written_with(monkeypatch):
    calls = _sent(monkeypatch, memory_reme, lambda m, p, b: {"success": not p.endswith("auto_memory"), "metadata": {}})
    run(memory_reme.ReMe("http://reme.test", "", True).observe("hmem_1", TURN, AGENT))
    body = next(b for m, p, b in calls if p.endswith("auto_memory"))
    jsonschema.validate(body, AUTO_MEMORY)
    assert set(body) <= set(AUTO_MEMORY["properties"]) and body["memory_hint"] == mp.EXTRACTION_GUIDE
