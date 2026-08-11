"""Guard: codex resume must strip account-bound encrypted reasoning from the rollout.

Regression this pins: a Responses `reasoning` item carries `encrypted_content` (the `gAAA…`
chain-of-thought blob) that only the upstream account that minted it can decrypt. Codex replays the
whole rollout as the next turn's input, so a follow-up served by a DIFFERENT account 400s with
`invalid_encrypted_content` — and the orphaned item stays in the rollout, wedging every later resume.
`_strip_codex_encrypted_reasoning` removes reasoning items before resume; messages, tool calls, and
tool outputs must survive untouched so history is preserved.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as rn  # noqa: E402


def _rollout(tmp_path) -> Path:
    """A minimal rollout mirroring the real codex jsonl shape (see a live rollout-*.jsonl)."""
    lines = [
        {"type": "session_meta", "payload": {"id": "s1"}},
        {"type": "response_item", "payload": {"type": "message", "role": "user",
                                              "content": [{"type": "input_text", "text": "hi"}]}},
        {"type": "response_item", "payload": {"type": "reasoning", "id": "rs_1", "summary": [],
                                              "encrypted_content": "gAAAAAoneXXX"}},
        {"type": "response_item", "payload": {"type": "function_call", "call_id": "c1",
                                              "name": "shell", "arguments": "{}"}},
        {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "c1",
                                              "output": "ok"}},
        {"type": "event_msg", "payload": {"type": "agent_message", "message": "done"}},
        {"type": "response_item", "payload": {"type": "reasoning", "id": "rs_2", "summary": [],
                                              "encrypted_content": "gAAAAAtwoYYY"}},
        # a failed-turn telemetry record whose ERROR STRING mentions encrypted content — must be kept
        {"type": "event_msg", "payload": {"type": "task_complete",
                                          "error": {"message": "The encrypted content gAAA...= could not be verified"}}},
    ]
    p = tmp_path / "rollout.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    return p


def test_strip_removes_reasoning_items_only(tmp_path):
    p = _rollout(tmp_path)
    n = rn._strip_codex_encrypted_reasoning([str(p)])
    assert n == 2  # both reasoning items removed

    kept = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    types = [(o.get("type"), (o.get("payload") or {}).get("type")) for o in kept]
    assert ("response_item", "reasoning") not in types
    # everything else survives, in order
    assert types == [
        ("session_meta", None),
        ("response_item", "message"),
        ("response_item", "function_call"),
        ("response_item", "function_call_output"),
        ("event_msg", "agent_message"),
        ("event_msg", "task_complete"),
    ]
    # the only remaining "encrypted_content" substring is inside the kept error-message telemetry
    remaining = [o for o in kept if "encrypted_content" in json.dumps(o)]
    assert remaining == []  # error msg text uses "encrypted content" (space), not the JSON key


def test_strip_is_noop_without_reasoning(tmp_path):
    p = tmp_path / "r.jsonl"
    p.write_text(json.dumps({"type": "response_item",
                             "payload": {"type": "message", "role": "user", "content": []}}) + "\n")
    before = p.read_text()
    assert rn._strip_codex_encrypted_reasoning([str(p)]) == 0
    assert p.read_text() == before  # untouched when there is nothing to strip


def test_strip_tolerates_missing_and_malformed(tmp_path):
    good = tmp_path / "good.jsonl"
    good.write_text(json.dumps({"type": "response_item",
                                "payload": {"type": "reasoning", "id": "r", "encrypted_content": "gAAAz"}}) + "\n"
                    + "not json but mentions reasoning and encrypted_content\n")
    missing = tmp_path / "nope.jsonl"
    n = rn._strip_codex_encrypted_reasoning([str(good), str(missing)])
    assert n == 1
    # the malformed line is preserved verbatim (never dropped on a parse failure)
    assert "not json but mentions" in good.read_text()
