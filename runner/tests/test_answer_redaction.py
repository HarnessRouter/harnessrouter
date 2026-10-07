"""A turn's answer leaves the runner without the turn's secret values, and with its own account intact.

Two private reports (GHSA-rmh9-whjx-gfrc, GHSA-7pwj-vv9r-rh2m). Redaction ran on the serialized
record: JSON escapes a quote, a backslash, a newline and every non-ASCII character there, so a secret
holding one was not found and went out whole. And it replaced every occurrence anywhere, while a
value from a $headers reference is chosen by the caller: a caller could blank the turn's status and
every event's type. Now the walk is over values, touches only what the agent wrote, and is capped
in depth so an answer can always be serialized.
"""
import asyncio
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server  # noqa: E402

PEM = "-----BEGIN KEY-----\nMIIBVQIBADANBgkqhkiG\n-----END KEY-----"
AWKWARD = ["sk-plain-ABC123", 'sk-"quoted"-XYZ', "sk-back\\slash", PEM, "sk-паролата-42"]


def _read(monkeypatch, rec: dict) -> dict:
    base = {"status": "completed", "done": True, "backend": "claude", "model": "claude-sonnet-5.5", "started": 0.0,
            "session_id": "sess-1", "events": []}
    monkeypatch.setitem(server._turns, "turn_r", {**base, **rec})
    return asyncio.run(server.get_turn("turn_r"))


def _event(text: str, tool_input) -> list[dict]:
    return [{"type": "assistant", "session_id": "sess-1", "message": {"role": "assistant", "model": "claude-sonnet-5.5",
             "content": [{"type": "text", "text": text},
                         {"type": "tool_use", "id": "tu_1", "name": "Bash", "input": tool_input}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "tu_1", "content": [{"type": "text", "text": text}]}]}},
            {"type": "result", "subtype": "success", "result": text, "usage": {"input_tokens": 10, "output_tokens": 5}}]


@pytest.mark.parametrize("secret", AWKWARD)
def test_no_secret_leaves_in_any_form(monkeypatch, secret):
    secrets = server._turn_secrets({"TOKEN": secret}, ["TOKEN"])
    as_json = json.dumps({"key": secret})          # the agent ran `cat config.json`: the secret, escaped
    text = f"env says {secret}; the file says {as_json}"
    out = _read(monkeypatch, {"result": text, "error": text, "reason": text, "handoff": {"note": text},
                              "events": _event(text, {"command": f"echo {secret}", "type": secret}), "secrets": secrets})
    wire = json.dumps(out, ensure_ascii=False) + json.dumps(out)
    for form in (secret, json.dumps(secret)[1:-1], json.dumps(secret, ensure_ascii=False)[1:-1]):
        assert form not in wire, form
    assert out["result"].startswith("env says [redacted]; the file says")
    assert out["events"][0]["message"]["content"][1]["input"] == {"command": "echo [redacted]", "type": "[redacted]"}


def test_a_caller_chosen_value_cannot_rewrite_the_turns_own_account(monkeypatch):
    """A $headers value is the caller's choice: it is redacted from what the agent wrote, and the
    turn's status, event types, roles, model, session, tool names and usage stay what they were."""
    picked = ["assistant", "completed", "input_tokens", "tool_result", "claude-sonnet-5.5", "success", "sess-1", "Bash"]
    secrets = server._turn_secrets({f"V{i}": v for i, v in enumerate(picked)}, [f"V{i}" for i in range(len(picked))])
    out = _read(monkeypatch, {"result": "the assistant completed", "events": _event("the assistant completed", {"c": "x"}),
                              "secrets": secrets})
    assert out["status"] == "completed" and out["model"] == "claude-sonnet-5.5" and out["session_id"] == "sess-1"
    ev = out["events"]
    assert [e["type"] for e in ev] == ["assistant", "user", "result"] and ev[2]["subtype"] == "success"
    assert ev[0]["message"]["role"] == "assistant" and ev[0]["message"]["model"] == "claude-sonnet-5.5"
    assert ev[0]["session_id"] == "sess-1" and ev[0]["message"]["content"][1]["name"] == "Bash"
    assert ev[1]["message"]["content"][0]["type"] == "tool_result" and ev[1]["message"]["content"][0]["tool_use_id"] == "tu_1"
    assert ev[2]["usage"] == {"input_tokens": 10, "output_tokens": 5}
    assert out["result"] == "the [redacted] [redacted]"                 # what the agent wrote is still redacted
    assert ev[0]["message"]["content"][0]["text"] == "the [redacted] [redacted]"


def test_a_deeply_nested_answer_is_still_readable(monkeypatch):
    deep: dict = {"leaf": "tok_0123456789abcdef"}
    for _ in range(20000):
        deep = {"d": deep}
    out = _read(monkeypatch, {"events": _event("ok", deep), "secrets": ["tok_0123456789abcdef"]})
    wire = json.dumps(out)                                              # serializable: the gateway can read the turn
    assert "[nested too deeply to show]" in wire and "tok_0123456789abcdef" not in wire
    assert out["status"] == "completed" and out["events"][0]["message"]["content"][0]["text"] == "ok"


def test_reading_a_turn_leaves_its_record_as_it_was(monkeypatch):
    rec = {"result": "x tok_0123456789abcdef", "events": _event("y tok_0123456789abcdef", {"c": 1}),
           "secrets": ["tok_0123456789abcdef"]}
    _read(monkeypatch, rec)
    stored = server._turns["turn_r"]
    assert stored["result"] == "x tok_0123456789abcdef"
    assert stored["events"][0]["message"]["content"][0]["text"] == "y tok_0123456789abcdef"


def test_a_turn_without_secrets_is_answered_as_written(monkeypatch):
    out = _read(monkeypatch, {"result": 'a "quoted" line\nand ünïcode', "events": _event("plain", {"n": [1, 2.5, None, True]})})
    assert out["result"] == 'a "quoted" line\nand ünïcode'
    assert out["events"][0]["message"]["content"][1]["input"] == {"n": [1, 2.5, None, True]}
