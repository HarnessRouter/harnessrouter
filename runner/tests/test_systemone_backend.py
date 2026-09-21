"""The systemone backend: the System One Harness as a runner turn.

What these pin, each measured before it was written down:

  the relay route's base is the provider's API ROOT for OpenRouter, because its decisions endpoint
      lives at /api/alpha/decisions and a POST to /api/v1/alpha/decisions is a 404 (2026-09-19)
  the driver's events are claude's stream-json: init, one tool_use + tool_result per executed
      action, a thinking block for a step that executed nothing, a text, a result with usage
  a loop that stops because no action cleared its confidence bar ends `incomplete` with the
      reason, which the runner reports as its own status rather than a failure or a step cap
  a resumed turn continues the order desk from where the last turn left it, from the workspace
  disabling an action withholds it from the question the model answers
"""
import json
import pathlib
import sys
import tempfile

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server  # noqa: E402
import systemone_driver as drv  # noqa: E402

s1 = pytest.importorskip("systemone_harness", reason="the System One Harness is installed on the runner's venv, not here")
from systemone_harness import RecordedProvider  # noqa: E402


# ── the relay route ──
def test_openrouter_route_is_rooted_at_the_api_not_its_v1():
    base, tok = server._systemone_relay_route("openrouter", "https://openrouter.ai/api/v1", "sk-or-real")
    assert base.startswith("http://127.0.0.1:") and base.endswith("/v1") and tok.startswith("hr-relay-")
    upstream, key, _flags = server._HERMES_RELAY["routes"][tok]
    assert upstream == "https://openrouter.ai/api" and key == "sk-or-real"


def test_typesafe_route_keeps_its_version_segment():
    base, tok = server._systemone_relay_route("typesafe", "https://api.typesafe.ai", "ts-real")
    upstream, _key, _flags = server._HERMES_RELAY["routes"][tok]
    assert upstream == "https://api.typesafe.ai/v1"


def test_the_builder_hands_the_driver_a_placeholder_never_the_key():
    env: dict = {}
    cmd = server._build_systemone("openrouter", server.Auth(api_key="sk-or-real", base_url="https://openrouter.ai/api/v1"),
                                  "typesafe/jev-1.13", "ship it", "/tmp/ws", env,
                                  mcp_servers=[{"name": "desk", "url": "https://x/mcp"}, {"name": "bad"}],
                                  tools_disabled=["ship"], max_turns=7, timeout_seconds=30, agent_doc="be quick")
    assert cmd[0] == server.SYSTEMONE_PYTHON and cmd[1].endswith("systemone_driver.py")
    job = json.loads(cmd[2])
    assert job["api_key"].startswith("hr-relay-") and "sk-or-real" not in cmd[2]
    assert job["base_url"].endswith("/v1") and job["provider"] == "openrouter"
    assert env["SYSTEMONE_API_KEY"] == job["api_key"]          # the taps find the route by it
    assert job["mcp_servers"] == [{"name": "desk", "url": "https://x/mcp"}]   # an entry with no target is dropped
    assert job["tools_disabled"] == ["ship"] and job["max_turns"] == 7 and job["timeout_seconds"] == 30
    assert job["agent_doc"] == "be quick" and job["model"] == "typesafe/jev-1.13"


def test_an_unknown_provider_and_a_missing_base_url_are_refused():
    with pytest.raises(Exception, match="unknown systemone provider"):
        server._build_systemone("bedrock", server.Auth(api_key="k", base_url="https://x"), "m", "p", "/tmp", {})
    with pytest.raises(Exception, match="base_url"):
        server._build_systemone("openrouter", server.Auth(api_key="k"), "m", "p", "/tmp", {})


# ── the driver's events, on a scripted model ──
def _choice(questions, name, pick, p=0.95):
    probs = {k: 0.0 for k in questions[name]["criteria"]}
    probs[pick] = p
    return {"type": "choice", "choice": pick, "probabilities": probs, "confidence": p}


def _fill(questions, answers):
    for k, q in questions.items():
        if k in answers:
            continue
        if q["type"] == "choice":
            answers[k] = _choice(questions, k, next(iter(q["criteria"])), 0.5)
        elif q["type"] == "noul":
            answers[k] = {"type": "noul", "noul": 0.5}
        else:
            answers[k] = {"type": "score", "score": 0, "probabilities": {}, "confidence": 0.5}
    return answers


def _perfect(state, questions):
    obs = state["observation"]
    a = {"goal_reached": {"type": "noul", "noul": 0.02}}
    if obs.get("unpicked"):
        a["next_action"] = _choice(questions, "next_action", "pick_item")
        a["pick_item__item"] = _choice(questions, "pick_item__item", obs["unpicked"][0])
    elif not obs.get("packed"):
        a["next_action"] = _choice(questions, "next_action", "pack")
    elif not obs.get("carrier"):
        a["next_action"] = _choice(questions, "next_action", "choose_carrier")
        a["choose_carrier__carrier"] = _choice(questions, "choose_carrier__carrier", "post")
    else:
        a["next_action"] = _choice(questions, "next_action", "ship")
    return _fill(questions, a)


def _job(cwd, **over):
    return {"cwd": cwd, "model": "typesafe/jev-1.13", "prompt": "Ship order A-104 with the cheapest carrier.",
            "provider": "openrouter", "base_url": "http://127.0.0.1:1/v1", "api_key": "hr-relay-x",
            "mcp_servers": [], "tools_disabled": [], "max_turns": 20, "timeout_seconds": None, "agent_doc": "", **over}


def test_a_turn_is_init_then_a_call_and_result_per_action_then_the_sentence_and_a_result():
    with tempfile.TemporaryDirectory() as cwd:
        events = []
        result = drv.run_turn(_job(cwd), provider=RecordedProvider(_perfect), emit=events.append)
        assert events[0]["type"] == "system" and events[0]["subtype"] == "init" and events[0]["session_id"].startswith("s1_")
        thinking = [e for e in events if e["type"] == "assistant" and e["message"]["content"][0]["type"] == "thinking"]
        assert "built-in order desk" in thinking[0]["message"]["content"][0]["thinking"]
        calls = [e["message"]["content"][0] for e in events if e["type"] == "assistant" and e["message"]["content"][0]["type"] == "tool_use"]
        outs = [e["message"]["content"][0] for e in events if e["type"] == "user"]
        assert [c["name"] for c in calls] == ["pick_item", "pick_item", "pick_item", "pack", "choose_carrier", "ship"]
        assert calls[0]["input"] == {"item": "blue mug"} and [c["id"] for c in calls] == [o["tool_use_id"] for o in outs]
        assert outs[-1]["content"] == "Shipped by post." and outs[-1]["is_error"] is False
        text = [e for e in events if e["type"] == "assistant" and e["message"]["content"][0]["type"] == "text"]
        assert text[-1]["message"]["content"][0]["text"] == "The environment reached a terminal state after 6 actions."
        assert events[-1] is result and result["subtype"] == "success" and result["is_error"] is False
        assert result["reason"] == "environment_terminal" and result["usage"]["input_tokens"] > 0
        assert result["handoff"] is None                 # a completed run hands nothing off (#227)
        assert result["model"] == "recorded/jev" and result["session_id"] == events[0]["session_id"]
        assert server._status_from_result(result, 0) == "done"
        # the manifest is a file in the workspace, where the artifact cards read from
        assert json.loads((pathlib.Path(cwd) / "manifest.json").read_text())["carrier"] == "post"
        # and the session's state is under the workspace, for the next turn
        sid = result["session_id"]
        assert (pathlib.Path(cwd) / ".harness" / "systemone" / sid / "environment.json").exists()


def test_a_resumed_turn_continues_the_desk_from_where_it_stopped():
    with tempfile.TemporaryDirectory() as cwd:
        first = []
        r1 = drv.run_turn(_job(cwd, max_turns=2), provider=RecordedProvider(_perfect), emit=first.append)
        assert r1["subtype"] == "error_max_turns" and server._status_from_result(r1, 0) == "max_turns"
        sid = r1["session_id"]
        second = []
        seen_history = []
        prov = RecordedProvider(lambda s, q: seen_history.append(s.get("history")) or _perfect(s, q))
        r2 = drv.run_turn(_job(cwd, prompt="Carry on.", resume_session_id=sid), provider=prov, emit=second.append)
        assert second[0]["session_id"] == sid and r2["subtype"] == "success"
        names = [e["message"]["content"][0]["name"] for e in second
                 if e["type"] == "assistant" and e["message"]["content"][0]["type"] == "tool_use"]
        assert names == ["pick_item", "pack", "choose_carrier", "ship"]      # the two picks of turn one are not redone
        assert seen_history[0] and seen_history[0][0].startswith("pick_item(item='blue mug')")


def test_a_refusal_streak_is_incomplete_with_its_reason_not_a_failure():
    shaky = lambda s, q: _fill(q, {"next_action": _choice(q, "next_action", "ship", 0.6)})
    with tempfile.TemporaryDirectory() as cwd:
        events = []
        # picked, packed and carrier chosen already: only ship remains, and the model is 60% sure
        from systemone_harness.envs import OrderWorkflow
        desk = OrderWorkflow("ship_cheapest")
        for item in ("blue mug", "tea towel", "kettle"):
            desk.execute("pick_item", {"item": item})
        desk.execute("pack", {})
        desk.execute("choose_carrier", {"carrier": "post"})
        sid = "s1_resume01"
        d = pathlib.Path(cwd) / ".harness" / "systemone" / sid
        d.mkdir(parents=True)
        (d / "environment.json").write_text(json.dumps(desk.snapshot()))
        result = drv.run_turn(_job(cwd, resume_session_id=sid), provider=RecordedProvider(shaky), emit=events.append)
        assert result["subtype"] == "incomplete" and result["is_error"] is False
        assert result["reason"] == "no_confident_action"
        # the handoff rides the result event beside the reason: the branch a router can send on
        # without reading the trace (#227). A harness that predates the field hands None.
        assert "handoff" in result
        if result["handoff"] is not None:
            assert isinstance(result["handoff"], dict)
            assert result["handoff"].get("reason") == "no_confident_action"
            assert {"state", "questions", "answers", "weakest", "threshold", "risk", "step"} <= set(result["handoff"])
        assert server._status_from_result(result, 0) == "incomplete"
        thinking = [e["message"]["content"][0]["thinking"] for e in events
                    if e["type"] == "assistant" and e["message"]["content"][0]["type"] == "thinking"]
        assert any("Refused ship" in t and "0.60" in t for t in thinking)
        assert not any(e["type"] == "user" for e in events)          # nothing executed


def test_a_disabled_action_is_never_offered():
    seen = []
    prov = RecordedProvider(lambda s, q: seen.append(list(q["next_action"]["criteria"])) or _perfect(s, q))
    with tempfile.TemporaryDirectory() as cwd:
        drv.run_turn(_job(cwd, tools_disabled=["ship"], max_turns=6), provider=prov, emit=lambda e: None)
    assert all("ship" not in offered for offered in seen) and seen


def test_an_mcp_entry_carries_its_auth_as_a_header_and_a_targetless_one_is_dropped():
    e = drv._server_entry({"name": "x", "url": "https://h/mcp", "auth": "tok", "headers": {"A": "b"}, "transport": "sse"})
    assert e == {"url": "https://h/mcp", "headers": {"A": "b", "Authorization": "Bearer tok"}, "transport": "sse"}
    assert drv._server_entry({"name": "plugin", "command": "./run.sh", "args": [1]})["args"] == ["1"]
    assert drv._server_entry({"name": "nothing"}) is None
