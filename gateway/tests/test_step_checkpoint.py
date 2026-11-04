"""A turn's workspace is checkpointed after its tool steps, not only when it ends (#505).

A hosted sandbox keeps the workspace and its marker in /tmp. When it died mid-turn, every step
since the last end-of-turn checkpoint went with it: the follow-up turn restored the previous turn's
workspace. #530 kept the work where the workspace sits on a volume (self-hosted); this is the
hosted half. A checkpoint now follows a completed tool step, in the background, one at a time per
session, at most one per interval, and the end-of-turn checkpoint is always the last write.
"""
import asyncio
import json
import os
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as A  # noqa: E402


def _step(tuid: str = "t1") -> dict:
    """A finished tool step, as every normaliser emits it."""
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": tuid, "content": "ok"}]}}


def _call(tuid: str = "t1") -> dict:
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": tuid, "name": "Bash", "input": {"command": "ls"}}]}}


@pytest.fixture
def relay(monkeypatch):
    """The checkpoint path with the sandbox and the stores replaced: records each relay call."""
    calls: list[dict] = []
    upserts: list[dict] = []
    state = {"delay": 0.0, "ok": True, "bytes": 1000}

    async def _relay(sid, commit=True):
        calls.append({"sid": sid, "commit": commit, "at": asyncio.get_running_loop().time()})
        if state["delay"]:
            await asyncio.sleep(state["delay"])
        calls[-1]["done"] = asyncio.get_running_loop().time()
        return state["ok"], state["bytes"], "sha", "abc123"

    async def _upsert(_sid, props):
        upserts.append(props)

    async def _vget(_sid):
        return {"checkpoint_bytes": str(state["bytes"])}

    monkeypatch.setattr(A, "_checkpoint_relay", _relay)
    monkeypatch.setattr(A, "_vertex_upsert", _upsert)
    monkeypatch.setattr(A, "_vertex_get", _vget)
    monkeypatch.setattr(A, "_STEP_CKPT", "1")
    monkeypatch.setattr(A, "STEP_CKPT_EVERY_S", 0.2)
    monkeypatch.setattr(A, "_step_ckpt", {})
    return {"calls": calls, "upserts": upserts, "state": state}


async def _idle() -> None:
    """Let the background worker run what it has without waiting out an interval."""
    for _ in range(5):
        await asyncio.sleep(0)


def test_a_tool_result_is_a_finished_step_and_a_call_alone_is_not():
    assert A._tool_step_done([_call(), _step()])
    assert not A._tool_step_done([_call()])
    # the trace-injected prompt stores content as a plain string (_blocks_from_canonical)
    assert not A._tool_step_done([{"type": "user", "message": {"content": "do the thing"}}])
    assert not A._tool_step_done([])


def test_self_hosted_is_off_by_default_and_hosted_is_on(monkeypatch):
    """Self-hosted, the workspace on /data already outlives a restart (#530)."""
    monkeypatch.setattr(A, "_STEP_CKPT", "")
    monkeypatch.setattr(A.BACKING, "mode", "local")
    assert not A._step_ckpt_enabled()
    monkeypatch.setattr(A.BACKING, "mode", "vg")
    assert A._step_ckpt_enabled()
    monkeypatch.setattr(A, "_STEP_CKPT", "0")
    assert not A._step_ckpt_enabled()
    monkeypatch.setattr(A.BACKING, "mode", "local")
    monkeypatch.setattr(A, "_STEP_CKPT", "1")
    assert A._step_ckpt_enabled()


async def test_a_step_is_checkpointed_without_a_commit_and_the_session_says_when(relay):
    rec = {}
    A._step_checkpoint_maybe("s", rec, [_call(), _step()])
    await _idle()
    assert [c["commit"] for c in relay["calls"]] == [False]
    assert float(relay["upserts"][-1]["ws_mid_turn_at"]) > 0
    assert rec["step_checkpoints"] == 1


async def test_events_with_no_finished_step_start_nothing(relay):
    A._step_checkpoint_maybe("s", {}, [_call()])
    await _idle()
    assert relay["calls"] == [] and A._step_ckpt == {}


async def test_the_end_of_turn_checkpoint_commits_and_clears_the_stamp(relay):
    await A._checkpoint("s", {})
    assert [c["commit"] for c in relay["calls"]] == [True]
    assert relay["upserts"][-1]["ws_mid_turn_at"] == ""


async def test_a_step_inside_the_interval_is_saved_when_it_ends_not_dropped(relay):
    """The last step before a long one (a build, a sleep) must be in a checkpoint: a plain
    rate limit would drop it, and the sandbox can die during the long step."""
    rec = {}
    A._step_checkpoint_maybe("s", rec, [_step("a")])
    await _idle()
    A._step_checkpoint_maybe("s", rec, [_step("b")])    # inside the interval
    A._step_checkpoint_maybe("s", rec, [_step("c")])    # still inside it: the same pending save
    await _idle()
    assert len(relay["calls"]) == 1
    await asyncio.sleep(0.3)
    assert len(relay["calls"]) == 2
    assert relay["calls"][1]["at"] - relay["calls"][0]["at"] >= 0.19


async def test_the_end_of_turn_checkpoint_waits_for_one_being_written(relay):
    """Last writer wins on the blob, so the end-of-turn checkpoint must start after the mid-turn
    one has finished, never race it."""
    relay["state"]["delay"] = 0.1
    rec = {}
    A._step_checkpoint_maybe("s", rec, [_step()])
    await _idle()
    assert A._step_ckpt["s"]["busy"]
    await A._checkpoint("s", rec)
    mid, end = relay["calls"]
    assert (mid["commit"], end["commit"]) == (False, True)
    assert end["at"] >= mid["done"]
    assert relay["upserts"][-1]["ws_mid_turn_at"] == ""
    assert "s" not in A._step_ckpt


async def test_a_save_waiting_out_its_interval_is_dropped_at_the_end_of_the_turn(relay):
    rec = {}
    A._step_checkpoint_maybe("s", rec, [_step("a")])
    await _idle()
    A._step_checkpoint_maybe("s", rec, [_step("b")])    # waits for the interval
    t0 = asyncio.get_running_loop().time()
    await A._checkpoint("s", rec)
    assert asyncio.get_running_loop().time() - t0 < 0.15   # did not wait the interval out
    assert [c["commit"] for c in relay["calls"]] == [False, True]
    await asyncio.sleep(0.3)
    assert len(relay["calls"]) == 2                          # and nothing ran after it


async def test_a_workspace_past_the_size_limit_is_only_checkpointed_at_the_end(relay, monkeypatch):
    monkeypatch.setattr(A, "STEP_CKPT_MAX_BYTES", 500)       # the last checkpoint was 1000
    rec = {}
    A._step_checkpoint_maybe("s", rec, [_step("a")])
    await _idle()
    A._step_checkpoint_maybe("s", rec, [_step("b")])
    await asyncio.sleep(0.3)
    assert relay["calls"] == []
    await A._checkpoint("s", rec)
    assert [c["commit"] for c in relay["calls"]] == [True]


async def test_a_failed_mid_turn_checkpoint_is_not_the_turns_outcome(relay):
    """checkpoint_error is never cleared by a later success, so a mid-turn failure written on the
    turn's record would still be there after its end-of-turn checkpoint succeeded."""
    relay["state"]["ok"] = False
    rec = {"tenant": "org"}
    A._step_checkpoint_maybe("s", rec, [_step()])
    await _idle()
    assert relay["calls"] and "checkpoint_error" not in rec and "step_checkpoints" not in rec
    relay["state"]["ok"] = True
    await A._checkpoint("s", rec)
    assert rec.get("checkpointed") is True and "checkpoint_error" not in rec


async def test_a_turn_whose_restore_failed_never_checkpoints_mid_turn(relay):
    """The same work-loss guard as the end-of-turn checkpoint: this workspace is not the
    checkpoint, and writing it would overwrite the good one."""
    A._step_checkpoint_maybe("s", {"hydrate_failed_with_checkpoint": True}, [_step()])
    await _idle()
    assert relay["calls"] == []


async def test_a_new_turn_does_not_inherit_the_last_ones_worker(relay):
    old = {}
    A._step_checkpoint_maybe("s", old, [_step("a")])
    await _idle()
    A._step_checkpoint_maybe("s", old, [_step("b")])      # pending, and the turn never settles it
    new = {}
    A._step_checkpoint_maybe("s", new, [_step("c")])      # the next turn's first step: at once
    await _idle()
    assert len(relay["calls"]) == 2 and A._step_ckpt["s"]["rec"] is new
    await asyncio.sleep(0.3)
    assert len(relay["calls"]) == 2                         # the old pending save was stopped


# ── the app-write repair after a mid-turn checkpoint ─────────────────────────────────────────────
def _captures(monkeypatch, entries):
    """entries: [(cfile_id, filename, written_at, source)] (as in test_session_file_fallback)."""
    async def _list(_prefix, **_k):
        return {"items": [{"file_id": f"containers/s/{cid}.meta"} for cid, *_ in entries]}

    async def _get(fid, **_k):
        cid = fid.rsplit("/", 1)[-1][: -len(".meta")]
        for c, name, ts, src in entries:
            if c == cid:
                m = {"filename": name, "written_at": ts}
                if src:
                    m["source"] = src
                return json.dumps(m).encode()
        return None

    async def _bytes(_sid, cid):
        return (b"app copy", "application/json", "sheet.json")

    written: dict = {}

    class _Ws:
        async def write(self, _sid, name, data):
            written[name] = data
            return True

    monkeypatch.setattr(A, "_blob_list", _list)
    monkeypatch.setattr(A, "_blob_get", _get)
    monkeypatch.setattr(A, "_container_file_bytes", _bytes)
    monkeypatch.setattr(A.BACKING, "workspace", _Ws(), raising=False)
    return written


async def test_an_app_copy_older_than_a_mid_turn_checkpoint_stays_out(monkeypatch):
    """The sequence #505's step 3 opened: the app wrote sheet.json between turns (200), the agent
    edited it in a step, a mid-turn checkpoint took the edit (300), and the sandbox died. The dead
    turn never collected, so the app's capture is still the newest one for the name. Put back, it
    would replace the agent's edit with the app's older copy."""
    written = _captures(monkeypatch, [("cfile_app", "sheet.json", 200.0, "app")])
    assert await A._reapply_app_writes("s", 300.0) == 0
    assert written == {}


async def test_an_app_copy_newer_than_the_mid_turn_checkpoint_is_put_back(monkeypatch):
    written = _captures(monkeypatch, [("cfile_app", "sheet.json", 400.0, "app")])
    assert await A._reapply_app_writes("s", 300.0) == 1
    assert written == {"sheet.json": b"app copy"}


async def test_after_an_end_of_turn_checkpoint_the_rule_is_unchanged(monkeypatch):
    written = _captures(monkeypatch, [("cfile_app", "sheet.json", 200.0, "app")])
    assert await A._reapply_app_writes("s") == 1
    assert written == {"sheet.json": b"app copy"}


async def test_hydrate_hands_the_mid_turn_stamp_to_the_repair(monkeypatch):
    seen = []

    async def _vget(_sid):
        return {"ws_sha": "sha", "ws_mid_turn_at": "300.0"}

    class _R:
        status_code = 200
        headers = {"content-type": "application/json"}

        def json(self):
            return {"ok": True, "skipped": False, "restored": True}

    async def _sandbox(*_a, **_k):
        return _R()

    async def _relay(*_a, **_k):
        return _R()

    async def _reapply(sid, mid_turn_at=0.0):
        seen.append(mid_turn_at)
        return 0

    monkeypatch.setattr(A, "_vertex_get", _vget)
    monkeypatch.setattr(A, "_sandbox", _sandbox)
    monkeypatch.setattr(A, "_hydrate_relay", _relay)
    monkeypatch.setattr(A, "_reapply_app_writes", _reapply)
    rec: dict = {}
    await A._hydrate("s", rec)
    assert rec["hydrated"] and seen == [300.0]
