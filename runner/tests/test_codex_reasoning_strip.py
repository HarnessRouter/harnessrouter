"""Guard: a codex rollout must be safe to replay — against BOTH failure modes.

This file used to pin the wrong specification. It asserted that reasoning items are DELETED and
that "messages, tool calls, and tool outputs must survive untouched" — which is exactly the state
the provider rejects. Against a store-backed Responses endpoint (codex sends `store: true` to
Azure), a replayed item `id` is a reference into server-side state, so an assistant message left
behind by a deleted reasoning item dangles:

    Item 'msg_…' of type 'message' was provided without its required 'reasoning' item: 'rs_…'

Deterministic, not flaky: every follow-up replays at least one such item, so turn 1 succeeds and
every later turn fails. The old fixture could never have caught it — its only `message` was
`role:"user"` with no `id`, and its `function_call` had no `id` either, so there was no `msg_*`
anywhere for a reference to dangle from.

The fixtures here are therefore CAPTURED BYTES from real sessions on a live box, not payloads
transcribed by eye:
  - codex_rollout_healthy.jsonl  — reasoning items intact, provider-minted ids present
  - codex_rollout_damaged.jsonl  — the actual rollout of hsess6a10d262c0da45ffb0ce1bb86fa39d35,
    whose follow-up 400'd; reasoning already destroyed by the old delete-based strip
Encrypted blobs and long content are redacted in place; the structure is untouched.

The invariant under test, which outlives any particular shape: after sanitising, no
provider-minted id may be left in the file without a reasoning item to anchor it.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as rn  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
MINTED = ("msg_", "rs_", "fc_", "fcr_", "ctc_")


def _load(name: str, tmp_path: Path) -> Path:
    dst = tmp_path / name
    dst.write_text((FIXTURES / name).read_text())
    return dst


def _items(path: Path) -> list[dict]:
    out = []
    for line in path.read_text().splitlines():
        if '"response_item"' not in line:
            continue
        try:
            o = json.loads(line)
        except ValueError:
            continue
        if o.get("type") == "response_item" and isinstance(o.get("payload"), dict):
            out.append(o["payload"])
    return out


def _minted_ids(path: Path) -> list[str]:
    return [str(p.get("id")) for p in _items(path) if str(p.get("id") or "").startswith(MINTED)]


def test_reasoning_survives_with_its_id_only_the_blob_is_dropped(tmp_path):
    """The account-bound blob is what must go; the item and its id are what the server checks."""
    f = _load("codex_rollout_healthy.jsonl", tmp_path)
    before_lines = len(f.read_text().splitlines())
    before_reasoning = [p for p in _items(f) if p.get("type") == "reasoning"]
    before_msg_ids = [i for i in _minted_ids(f) if i.startswith("msg_")]
    assert before_reasoning, "fixture must contain reasoning items"
    assert before_msg_ids, "fixture must contain provider-minted message ids"

    counts = rn._sanitize_codex_rollout([str(f)])

    after_reasoning = [p for p in _items(f) if p.get("type") == "reasoning"]
    assert len(after_reasoning) == len(before_reasoning), "reasoning items must NOT be deleted"
    assert all("encrypted_content" not in p for p in after_reasoning), "blob must be gone"
    assert all(p.get("id") for p in after_reasoning), "reasoning items keep their id"
    assert counts["reasoning"] == len(before_reasoning)
    # Nothing else moved: same line count, same message ids, and the repair branch stayed shut.
    assert len(f.read_text().splitlines()) == before_lines
    assert [i for i in _minted_ids(f) if i.startswith("msg_")] == before_msg_ids
    assert counts["damaged"] == 0 and counts["deref"] == 0


def test_damaged_rollout_is_repaired_by_dropping_every_minted_id(tmp_path):
    """The real wedged session. With reasoning already destroyed, the ids must go — all of them.

    A half-measure (de-id only messages, say) does not fix anything: it relocates the same 400 to
    whichever item type still carries an id.
    """
    f = _load("codex_rollout_damaged.jsonl", tmp_path)
    before_lines = len(f.read_text().splitlines())
    assert not [p for p in _items(f) if p.get("type") == "reasoning"], "fixture is the damaged one"
    assert _minted_ids(f), "fixture must carry provider-minted ids"
    before_calls = [p.get("call_id") for p in _items(f) if p.get("call_id")]
    before_roles = [p.get("role") for p in _items(f) if p.get("role")]

    counts = rn._sanitize_codex_rollout([str(f)])

    assert _minted_ids(f) == [], "no provider-minted id may survive in a damaged rollout"
    assert counts["damaged"] == 1 and counts["deref"] > 0
    # The transcript itself is preserved — this repairs the replay, it does not erase history.
    assert [p.get("call_id") for p in _items(f) if p.get("call_id")] == before_calls
    assert [p.get("role") for p in _items(f) if p.get("role")] == before_roles
    assert len(f.read_text().splitlines()) == before_lines


def test_no_minted_id_is_ever_left_without_a_reasoning_anchor(tmp_path):
    """The invariant, stated once. This is the assertion that would have caught the original bug,
    and it will catch the next variant of it whatever shape codex sends."""
    for name in ("codex_rollout_healthy.jsonl", "codex_rollout_damaged.jsonl"):
        d = tmp_path / name.replace(".jsonl", "")
        d.mkdir(parents=True, exist_ok=True)
        f = _load(name, d)
        rn._sanitize_codex_rollout([str(f)])
        has_reasoning = any(p.get("type") == "reasoning" for p in _items(f))
        if not has_reasoning:
            assert _minted_ids(f) == [], f"{name}: dangling references would 400 on replay"


def test_sanitise_is_idempotent(tmp_path):
    """Run twice, byte-identical after the first pass — a resume may sanitise the same file again."""
    for name in ("codex_rollout_healthy.jsonl", "codex_rollout_damaged.jsonl"):
        d = tmp_path / name.replace(".jsonl", "")
        d.mkdir(parents=True, exist_ok=True)
        f = d / name
        f.write_text((FIXTURES / name).read_text())
        rn._sanitize_codex_rollout([str(f)])
        once = f.read_text()
        rn._sanitize_codex_rollout([str(f)])
        assert f.read_text() == once, f"{name}: second pass changed the file"


def test_reasoning_without_encrypted_content_is_still_kept(tmp_path):
    """A provider that returns reasoning WITHOUT a blob must not trip anything.

    The old predicate keyed on the literal substring `"encrypted_content"`, so such an item was
    invisible to it. Nothing may depend on that substring any more.
    """
    f = tmp_path / "r.jsonl"
    f.write_text("\n".join(json.dumps(o) for o in [
        {"type": "response_item", "payload": {"type": "reasoning", "id": "rs_1", "summary": []}},
        {"type": "response_item", "payload": {"type": "message", "id": "msg_1", "role": "assistant",
                                              "content": [{"type": "output_text", "text": "hi"}]}},
    ]) + "\n")
    counts = rn._sanitize_codex_rollout([str(f)])
    items = _items(f)
    assert any(p.get("type") == "reasoning" and p.get("id") == "rs_1" for p in items)
    # Reasoning is present, so the ids resolve and the repair branch must stay shut.
    assert counts["damaged"] == 0
    assert any(p.get("id") == "msg_1" for p in items)


def test_tolerates_missing_and_malformed(tmp_path):
    """Unchanged from the original suite: a missing file is skipped, bad lines survive verbatim."""
    good = tmp_path / "ok.jsonl"
    good.write_text('{"type": "response_item", "payload": {"type": "reasoning", "id": "rs_1",'
                    ' "encrypted_content": "gAAA"}}\nnot json at all\n')
    rn._sanitize_codex_rollout([str(tmp_path / "nope.jsonl"), str(good)])
    text = good.read_text()
    assert "not json at all" in text
    assert "encrypted_content" not in text
    assert '"rs_1"' in text
