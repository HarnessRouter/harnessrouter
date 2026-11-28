"""The realtime base's own module: the job a turn is given, the route it may use, the session probe.

What these pin:

  the driver is handed the relay's placeholder and the relay's address for the mint, and the
      provider's own address for the socket, which carries no credential; the key is in nothing
      it is given
  the socket's address is the connection's base with the socket's scheme, /realtime and the
      model, and a base that is not a web address is refused before a process starts
  the turn's route forwards the client-secret mint and nothing else
  a session is present when its items file is, and an id that is not one is never a path

This file imports the module alone, with no runner beside it. The wiring into the runner (the
registry entry, the route as the relay holds it, the refusal in the relay's handler) is in
test_realtime_route.py.
"""
import json
import pathlib
import sys
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
pytest.importorskip("fastapi")
from fastapi import HTTPException  # noqa: E402

import realtime_backend as rb  # noqa: E402

KEY = "azure-real-key-0123456789"
BASE = "https://res.openai.azure.com/openai/v1"


def auth(api_key=KEY, base_url=BASE):
    return types.SimpleNamespace(api_key=api_key, base_url=base_url)


def build(env=None, **kw):
    calls = {}

    def relay(base_url, api_key):
        calls["relay"] = (base_url, api_key)
        return "http://127.0.0.1:40123/v1", "hr-relay-abc"

    def driver_cmd(python, driver, job, env_):
        calls["job"] = job
        env_["HR_DRIVER_JOB"] = json.dumps(job)
        return [python, driver]

    env = {} if env is None else env
    args = {"provider": "azure-foundry", "auth": auth(), "model": "gpt-realtime-2-1", "prompt": "hi", "cwd": "/ws"}
    args.update(kw)
    cmd = rb.build(args.pop("provider"), args.pop("auth"), args.pop("model"), args.pop("prompt"), args.pop("cwd"),
                   env, relay=relay, driver_cmd=driver_cmd, **args)
    return cmd, calls, env


# ── the job ──
def test_the_driver_gets_the_placeholder_the_mint_through_the_relay_and_the_socket_direct():
    cmd, calls, env = build(mcp_servers=[{"name": "desk", "url": "https://x/mcp"}, {"name": "bad"},
                                         {"name": "local", "command": "node"}, "nonsense"],
                            tools_disabled=["refund", ""], max_turns=3, timeout_seconds=40, agent_doc="Be brief.",
                            resume_session_id="rt_1", partial=True)
    assert cmd == [rb.PYTHON, rb.DRIVER] and cmd[1].endswith("realtime_driver.py")
    assert calls["relay"] == (BASE, KEY)                       # the route is made on the connection as stored
    job = calls["job"]
    assert job["api_key"] == "hr-relay-abc" and env["HR_REALTIME_KEY"] == "hr-relay-abc"
    assert job["mint_url"] == "http://127.0.0.1:40123/v1/realtime/client_secrets"
    assert job["ws_url"] == "wss://res.openai.azure.com/openai/v1/realtime?model=gpt-realtime-2-1"
    assert KEY not in json.dumps(cmd) + json.dumps(env) + json.dumps(job)
    assert job["mcp_servers"] == [{"name": "desk", "url": "https://x/mcp"}, {"name": "local", "command": "node"}]
    assert job["tools_disabled"] == ["refund"] and job["max_turns"] == 3 and job["timeout_seconds"] == 40
    assert job["agent_doc"] == "Be brief." and job["resume_session_id"] == "rt_1" and job["partial"] is True
    assert job["model"] == "gpt-realtime-2-1" and job["provider"] == "azure-foundry" and job["cwd"] == "/ws"


def test_a_turn_with_nothing_optional_says_so_in_plain_values():
    _cmd, calls, _env = build()
    job = calls["job"]
    assert job["resume_session_id"] == "" and job["mcp_servers"] == [] and job["tools_disabled"] == []
    assert job["agent_doc"] == "" and job["partial"] is False and job["max_turns"] is None
    assert job["skills"] == []


def test_the_job_names_the_turns_skills_and_carries_none_of_their_files():
    written = [{"name": "refunds", "desc": "How to refund.", "entry": ".harness/skills/refunds/SKILL.md",
                "files": [{"path": "SKILL.md", "content": "x" * 5000}]}, "nonsense", {"name": "plain"}]
    _cmd, calls, _env = build(skills=written)
    assert calls["job"]["skills"] == [
        {"name": "refunds", "desc": "How to refund.", "entry": ".harness/skills/refunds/SKILL.md"},
        {"name": "plain", "desc": "", "entry": ""}]


@pytest.mark.parametrize("kw, word", [
    ({"provider": "openrouter"}, "unknown realtime provider"),
    ({"auth": auth(api_key="")}, "base_url and an API key"),
    ({"auth": auth(base_url="")}, "base_url and an API key"),
    ({"auth": auth(base_url="res.openai.azure.com/openai/v1")}, "web address"),
    ({"auth": auth(base_url="ftp://res.openai.azure.com/openai/v1")}, "web address"),
])
def test_a_connection_that_cannot_serve_it_is_refused_before_a_route_exists(kw, word):
    with pytest.raises(HTTPException) as e:
        build(**kw)
    assert e.value.status_code == 400 and word in str(e.value.detail)
    assert KEY not in str(e.value.detail)


def test_no_route_is_registered_for_a_refused_turn():
    made = []
    with pytest.raises(HTTPException):
        rb.build("azure-foundry", auth(base_url="not a url"), "m", "hi", "/ws", {},
                 relay=lambda *a: made.append(a) or ("x", "y"), driver_cmd=lambda *a: [])
    assert made == []


# ── the socket's address ──
@pytest.mark.parametrize("base, model, want", [
    (BASE, "gpt-realtime-2-1", "wss://res.openai.azure.com/openai/v1/realtime?model=gpt-realtime-2-1"),
    (BASE + "/", "gpt-realtime-2-1", "wss://res.openai.azure.com/openai/v1/realtime?model=gpt-realtime-2-1"),
    ("https://api.openai.com/v1", "gpt-realtime", "wss://api.openai.com/v1/realtime?model=gpt-realtime"),
    ("http://127.0.0.1:8080/v1", "m", "ws://127.0.0.1:8080/v1/realtime?model=m"),
    # a model id is a value, never part of the address
    (BASE, "a b&c=d#e", "wss://res.openai.azure.com/openai/v1/realtime?model=a+b%26c%3Dd%23e"),
    ("", "m", ""), ("res.openai.azure.com", "m", ""), ("file:///etc/passwd", "m", ""), ("https://", "m", ""),
])
def test_the_socket_is_on_the_connections_own_base(base, model, want):
    assert rb.socket_url(base, model) == want


# ── the route ──
def test_the_route_forwards_the_mint_and_nothing_else():
    flags = {"passthrough": True, "only": rb.ROUTE_ONLY}
    assert rb.route_allows(flags, "POST", "/realtime/client_secrets")
    assert rb.route_allows(flags, "post", "/realtime/client_secrets?api-version=x")       # the path, without its query
    for method, tail in [("GET", "/realtime/client_secrets"), ("DELETE", "/realtime/client_secrets"),
                         ("POST", "/chat/completions"), ("POST", "/responses"), ("GET", "/models"),
                         ("POST", "/realtime/client_secrets/../chat/completions"), ("POST", "/files"),
                         ("POST", "/realtime/calls"), ("POST", "/realtime/client_secretsx"), ("POST", "/")]:
        assert not rb.route_allows(flags, method, tail), (method, tail)


def test_a_route_with_no_limit_forwards_as_it_always_did():
    for flags in ({}, {"passthrough": True}, {"only": None}, {"only": ()}):
        assert rb.route_allows(flags, "DELETE", "/anything/at/all")


# ── the session ──
def test_a_session_is_present_when_its_items_file_is(tmp_path):
    d = tmp_path / ".harness" / "realtime" / "rt_abc"
    d.mkdir(parents=True)
    assert not rb.session_present(str(tmp_path), [], "rt_abc")          # the folder alone is not a conversation
    (d / "items.json").write_text("not json", encoding="utf-8")
    assert not rb.session_present(str(tmp_path), [], "rt_abc")
    (d / "items.json").write_text('{"a": 1}', encoding="utf-8")
    assert not rb.session_present(str(tmp_path), [], "rt_abc")          # not a list of items
    (d / "items.json").write_text("[]", encoding="utf-8")
    assert rb.session_present(str(tmp_path), [], "rt_abc")
    assert not rb.session_present(str(tmp_path), [], "rt_other")


@pytest.mark.parametrize("sid", ["", None, "../rt_abc", "rt_abc/../../x", "a" * 81, "rt abc", "rt_abc\x00"])
def test_an_id_that_is_not_one_is_never_a_path(tmp_path, sid):
    d = tmp_path / ".harness" / "realtime" / "rt_abc"
    d.mkdir(parents=True)
    (d / "items.json").write_text("[]", encoding="utf-8")
    assert not rb.session_present(str(tmp_path), [], sid)
