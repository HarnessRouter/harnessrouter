"""A base's own memory is off when the platform's memory is attached.

With both, an agent kept things in two places, and one of them was the base's private store: on sslip (11-09) a
Hermes agent with platform memory also ran Hermes's built-in memory tool, once failing silently ("Unknown action
'None'") and once saving into Hermes's own store, which the console never shows. So when a turn's MCP servers carry
the gateway's memories server, each base whose own memory the runner can switch off has it off: Hermes in its
config (its `memory` and `session_search` toolsets, and the store behind them), cheetahclaws and Roder through the
switch that withholds a tool from the model. A turn without platform memory keeps the base as it was."""
import json
import pathlib
import sys
import tomllib

import pytest
import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server  # noqa: E402

GATEWAY_MEMORIES = {"name": "memories", "url": "https://hr.example.com/v1/mcp/memories", "transport": "http",
                    "auth": "hosted-cred"}
CHEETAH_MEMORY = {"MemoryDelete", "MemoryList", "MemorySave", "MemorySearch", "MemoryVerify"}


def test_the_platform_memory_is_known_by_its_address_whatever_its_name():
    assert server._has_platform_memory([GATEWAY_MEMORIES])
    assert server._has_platform_memory([{**GATEWAY_MEMORIES, "name": "memories_2", "url": "http://10.0.0.5:8080/v1/mcp/memories/"}])
    # a person's own server called memories is theirs, and another of the gateway's servers is not memory
    assert not server._has_platform_memory([{"name": "memories", "url": "https://mem.example.org/mcp"}])
    assert not server._has_platform_memory([{"name": "plugs", "url": "https://hr.example.com/v1/mcp/plugs"}])
    assert not server._has_platform_memory([{"name": "local", "command": "python3"}, None])
    assert not server._has_platform_memory(None)


# ── Hermes: its own memory toolsets and the store behind them ─────────────────────────────────
def _hermes_cfg(tmp_path, **kw) -> dict:
    env = {"HOME": str(tmp_path)}
    server._hermes_prepare_env("bedrock", server.Auth(), str(tmp_path), env, model="m", **kw)
    return yaml.safe_load((tmp_path / ".hermes" / "config.yaml").read_text())


def test_hermes_with_platform_memory_offers_none_of_its_own(tmp_path):
    cfg = _hermes_cfg(tmp_path, own_memory_off=True)
    assert cfg["agent"]["disabled_toolsets"] == ["memory", "session_search"]
    assert cfg["memory"] == {"memory_enabled": False, "user_profile_enabled": False}
    assert cfg["agent"]["verify_on_stop"] is False, "the rest of the file is as it was"


def test_hermes_without_platform_memory_keeps_its_own(tmp_path):
    cfg = _hermes_cfg(tmp_path)
    assert "disabled_toolsets" not in cfg["agent"] and "memory" not in cfg


# ── what reaches each builder from a turn ─────────────────────────────────────────────────────
@pytest.fixture
def started(tmp_path, monkeypatch):
    """Start a turn of a base with these MCP servers; nothing runs, and what each builder was given is kept."""
    monkeypatch.setattr(server, "_SESSION_UIDS", False)
    got: dict = {}

    def nothing(*a, **k):
        return None
    monkeypatch.setattr(server, "_run_hermes_bg", nothing)
    monkeypatch.setattr(server, "_run_turn_bg", nothing)
    real_hermes = server._hermes_prepare_env

    def hermes(*a, **k):
        got["own_memory_off"] = k.get("own_memory_off")
        return real_hermes(*a, **k)
    monkeypatch.setattr(server, "_hermes_prepare_env", hermes)

    def cheetah(*a, **k):
        got["tools_disabled"] = list(k.get("tools_disabled") or [])
        return ["true"]
    monkeypatch.setattr(server, "_build_cheetahclaws", cheetah)

    def roder(*a, **k):
        got["tools_disabled"] = list(k.get("tools_disabled") or [])
        return ["true"]
    monkeypatch.setattr(server.roder_backend, "build", roder)

    def start(backend: str, servers: list[dict], tools_disabled=None, provider="openai-api"):
        got.clear()
        ws = tmp_path / f"ws-{backend}-{len(servers)}"
        req = server.TurnReq(backend=backend, provider=provider, model="m", prompt="hi", cwd=str(ws),
                             auth=server.Auth(api_key="k", base_url="https://api.example/v1"),
                             mcp_servers=servers, tools_disabled=tools_disabled)
        server._start_turn(req, f"sess-{backend}-{len(servers)}")
        return got, ws
    return start


def test_a_hermes_turn_with_platform_memory_switches_its_own_off(started):
    got, ws = started("hermes", [GATEWAY_MEMORIES])
    assert got["own_memory_off"] is True
    cfg = yaml.safe_load((ws / ".harness" / "home" / ".hermes" / "config.yaml").read_text())
    assert cfg["agent"]["disabled_toolsets"] == ["memory", "session_search"] and cfg["memory"]["memory_enabled"] is False
    got, ws = started("hermes", [])
    assert got["own_memory_off"] is False
    assert "disabled_toolsets" not in yaml.safe_load((ws / ".harness" / "home" / ".hermes" / "config.yaml").read_text())["agent"]


def test_a_cheetahclaws_turn_with_platform_memory_withholds_its_memory_tools(started):
    got, _ = started("cheetahclaws", [GATEWAY_MEMORIES], tools_disabled=["Bash"])
    assert got["tools_disabled"][0] == "Bash" and CHEETAH_MEMORY <= set(got["tools_disabled"])
    assert CHEETAH_MEMORY <= set(server.CHEETAHCLAWS_TOOLS), "each is a tool the CLI was measured offering"
    got, _ = started("cheetahclaws", [], tools_disabled=["Bash"])
    assert got["tools_disabled"] == ["Bash"]


def test_a_roder_turn_with_platform_memory_withholds_its_memory_and_knowledge_stores(started, tmp_path):
    got, _ = started("roder", [GATEWAY_MEMORIES], provider="openai")
    assert {"memory_save", "knowledge_save"} <= set(got["tools_disabled"])
    # what those switch ids do to Roder's own allowlist: every tool of both families is gone, nothing else is
    allowed = set(server.roder_backend.allowlist(got["tools_disabled"]))
    assert not allowed & set(server.roder_backend.TOOLS["memory_save"] + server.roder_backend.TOOLS["knowledge_save"])
    assert {"read_file", "exec_command"} <= allowed
    got, _ = started("roder", [], provider="openai")
    assert not {"memory_save", "knowledge_save"} & set(got["tools_disabled"])


def test_a_base_whose_memory_is_already_off_or_absent_is_left_as_it_was():
    for backend in ("claude", "codex", "jcode", "grok", "agentzero", "zeroclaw", "nanobot"):
        assert server._own_memory_off(backend, ["X"]) == ["X"]
    assert server._own_memory_off("roder", ["memory_save"]) == ["memory_save", "knowledge_save"], "never twice"
    assert json.dumps(server._OWN_MEMORY_TOOLS)          # names only, nothing else rides on it
