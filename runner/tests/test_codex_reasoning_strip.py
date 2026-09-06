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


def test_content_only_replay_drops_every_blob_and_every_minted_id(tmp_path):
    """A resume under another account replays content: no encrypted blob (it is bound to the
    account that minted it) and no provider-minted id (it is a lookup into that account's state).
    Items are never deleted, so tool pairing and the transcript survive."""
    f = _load("codex_rollout_healthy.jsonl", tmp_path)
    before_lines = len(f.read_text().splitlines())
    before_items = _items(f)
    before_reasoning = [p for p in before_items if p.get("type") == "reasoning"]
    assert before_reasoning and _minted_ids(f), "fixture must carry reasoning items and minted ids"

    counts = rn._sanitize_codex_rollout([str(f)], content_only=True)

    after_items = _items(f)
    assert len(after_items) == len(before_items) and len(f.read_text().splitlines()) == before_lines
    assert all("encrypted_content" not in p for p in after_items if p.get("type") == "reasoning")
    assert _minted_ids(f) == []
    assert counts["reasoning"] == len(before_reasoning) and counts["deref"] > 0 and counts["damaged"] == 1
    # what the transcript and the tool pairing need is still there
    for pb, pa in zip(before_items, after_items):
        for k in ("type", "call_id", "phase", "role", "content", "name", "arguments", "output"):
            assert pb.get(k) == pa.get(k), k


def test_same_account_replay_is_untouched(tmp_path):
    """The account that minted the history can resolve its ids and decrypt its blobs: a follow-up
    or a model switch on the same key keeps the whole history, byte for byte."""
    f = _load("codex_rollout_healthy.jsonl", tmp_path)
    before = f.read_text()
    counts = rn._sanitize_codex_rollout([str(f)], content_only=False)
    assert f.read_text() == before
    assert counts == {"reasoning": 0, "deref": 0, "damaged": 0}


def test_damaged_rollout_is_repaired_by_dropping_every_minted_id(tmp_path):
    """A rollout an older build already stripped of its reasoning items has message ids that
    reference nothing; content-only replay removes them the same way."""
    f = _load("codex_rollout_damaged.jsonl", tmp_path)
    assert _minted_ids(f), "fixture must carry orphaned minted ids"
    counts = rn._sanitize_codex_rollout([str(f)], content_only=True)
    assert _minted_ids(f) == [] and counts["damaged"] == 1 and counts["deref"] > 0


def test_sanitise_is_idempotent(tmp_path):
    f = _load("codex_rollout_healthy.jsonl", tmp_path)
    rn._sanitize_codex_rollout([str(f)], content_only=True)
    once = f.read_text()
    counts = rn._sanitize_codex_rollout([str(f)], content_only=True)
    assert f.read_text() == once and counts["reasoning"] == 0 and counts["deref"] == 0


def test_tolerates_missing_and_malformed(tmp_path):
    missing = tmp_path / "nope.jsonl"
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"type":"response_item","payload":{"type":"reasoning","id":"rs_1","encrypted_content":"x"}}\nnot json {"response_item"\n')
    counts = rn._sanitize_codex_rollout([str(missing), str(bad)], content_only=True)
    lines = bad.read_text().splitlines()
    assert len(lines) == 2 and lines[1] == 'not json {"response_item"'
    items = _items(bad)
    assert items and "encrypted_content" not in items[0] and "id" not in items[0]
    assert counts["reasoning"] == 1 and counts["deref"] == 1


def test_the_account_marker_decides_content_only(tmp_path):
    """First turn on a key: no marker, so a resume (if any) is content-only. Same key next turn:
    untouched. A different key: content-only again. The marker never names the key."""
    import server as rs
    for auth, expect in ((rs.Auth(api_key="k1"), "1"), (rs.Auth(api_key="k1"), "0"), (rs.Auth(api_key="k2"), "1"), (rs.Auth(api_key="k2"), "0")):
        env = {"HOME": str(tmp_path)}
        cfg_dir = rs._codex_prepare_env("openai", auth, "gpt-5.5", str(tmp_path), env)
        assert env["HR_CODEX_ACCOUNT_CHANGED"] == expect
        assert "k1" not in (cfg_dir / "hr-account").read_text() and "k2" not in (cfg_dir / "hr-account").read_text()


def test_a_resumed_session_keeps_every_provider_id_it_ran_under(tmp_path, monkeypatch):
    """Codex looks the rollout's recorded provider id up in the config on resume. A session started
    on the platform's TokenRouter (hr-tokenrouter), or before the ids were namespaced (azure), and
    continued on the org's own OpenAI key must still load: the config declares those ids too, at
    this turn's endpoint."""
    from server import Auth, _codex_prepare_env
    home = tmp_path / "home"; sess = home / ".codex" / "sessions" / "2026" / "07"; sess.mkdir(parents=True)
    (sess / "rollout-1.jsonl").write_text('{"type": "session_meta", "payload": {"id": "s1", "model_provider": "hr-tokenrouter"}}\n'
                                          '{"type": "turn_context", "payload": {"model": "gpt-5.5", "model_provider": "azure"}}\n')
    env = {"HOME": str(home)}
    _codex_prepare_env("openai", Auth(api_key="sk-x", base_url="https://broker.example/v1/llm"), "gpt-5.4-mini", str(tmp_path), env, resume=True)
    cfg = (home / ".codex" / "config.toml").read_text()
    assert 'model_provider = "hr-openai"' in cfg and "[model_providers.hr-openai]" in cfg
    assert "[model_providers.hr-tokenrouter]" in cfg and "[model_providers.azure]" in cfg
    assert cfg.count('base_url = "https://broker.example/v1/llm"') == 3, "every alias points at this turn's endpoint"
    fresh = {"HOME": str(tmp_path / "fresh")}
    _codex_prepare_env("openai", Auth(api_key="sk-x", base_url="https://broker.example/v1/llm"), "gpt-5.4-mini", str(tmp_path), fresh, resume=False)
    assert "[model_providers.hr-tokenrouter]" not in (tmp_path / "fresh" / ".codex" / "config.toml").read_text(), "a fresh session declares only its own"


def test_a_failure_names_the_providers_refusal_over_the_clis_retries():
    from server import _PROVIDER_REFUSAL
    lines = ["Reading prompt from stdin...", "ERROR: 401 Unauthorized: Incorrect API key provided", "Reconnecting... 1/5", "Reconnecting... 2/5"]
    assert next((ln for ln in lines if _PROVIDER_REFUSAL.search(ln)), "") == "ERROR: 401 Unauthorized: Incorrect API key provided"
    assert not _PROVIDER_REFUSAL.search("Reconnecting... 1/5")


def test_app_server_resumes_the_rollout_that_is_here(tmp_path):
    """The wanted thread when its rollout is here; else the newest rollout's own id; None with no rollout."""
    from server import _codex_resume_thread_id
    home = tmp_path / ".codex"; sess = home / "sessions" / "2026" / "09"; sess.mkdir(parents=True)
    assert _codex_resume_thread_id(home, "t-wanted") is None
    (sess / "rollout-a.jsonl").write_text('{"type": "session_meta", "payload": {"id": "t-old"}}\n')
    import os, time
    os.utime(sess / "rollout-a.jsonl", (time.time() - 100, time.time() - 100))
    (sess / "rollout-b.jsonl").write_text('{"type": "session_meta", "payload": {"id": "t-new"}}\n')
    assert _codex_resume_thread_id(home, "t-old") == "t-old", "the wanted rollout is here"
    assert _codex_resume_thread_id(home, "t-missing") == "t-new", "not here: the newest rollout is this conversation"


def test_codex_config_declares_the_catalog_window_and_no_feature_overrides(tmp_path, monkeypatch):
    """The runner declares the window Codex's own catalog has for gpt-5.x and leaves Codex's
    feature flags alone: compaction was measured to work on every provider once the broker stopped
    stripping `reasoning`, with the remote-compaction flag on or off (Codex compacts locally when a
    provider has no compaction endpoint)."""
    import server as rs
    env = {"HOME": str(tmp_path)}
    cfg_dir = rs._codex_prepare_env("openai", rs.Auth(api_key="k"), "gpt-5.5", str(tmp_path), env)
    cfg = (cfg_dir / "config.toml").read_text()
    assert "model_context_window = 272000" in cfg and "[features]" not in cfg
    import tomllib
    parsed = tomllib.loads(cfg)
    assert parsed["model_providers"]["hr-openai"]["wire_api"] == "responses"
