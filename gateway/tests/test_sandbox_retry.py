"""The runner call's retry ladder waits for a runner that is not there yet, never for a verdict.

A cold sandbox answers with an empty body, a 429 or a 5xx while it spins up, and the ladder waits
through that. A 4xx that is not 429 is the runner's verdict on the request (an unknown provider for
the backend, a bad key, a body too large): waiting cannot change it, and retrying it 28 times hid
the reason behind five minutes of silence and a message that said "unavailable" (#201, reported by
master5d; fixed by hiro-nikaitou in #258). The message names the attempts actually made and
carries the runner's own sentence."""
import asyncio
import os
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402


class _Resp:
    def __init__(self, status: int, body: bytes = b'{"ok": true}'):
        self.status_code, self.content = status, body

    def json(self):
        import json
        return json.loads(self.content)


def _drive(monkeypatch, answers, attempts=28):
    """Run _sandbox_json against a fake runner that answers `answers` in order (the last repeats);
    returns (result or the raised error, calls made, sleeps taken)."""
    calls, sleeps = [], []

    async def _sandbox(path, sid, method, body=None, params=None):
        a = answers[min(len(calls), len(answers) - 1)]
        calls.append(path)
        if isinstance(a, Exception):
            raise a
        return a

    async def _sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(gw, "_sandbox", _sandbox)
    monkeypatch.setattr(gw.asyncio, "sleep", _sleep)
    try:
        out = asyncio.run(gw._sandbox_json("/turn", "hsess1", body={}, attempts=attempts))
    except RuntimeError as e:
        out = e
    return out, calls, sleeps


def test_a_runner_verdict_is_answered_at_once_with_its_sentence(monkeypatch):
    out, calls, sleeps = _drive(monkeypatch, [_Resp(400, b'{"detail":"unknown codex provider \'custom\' (one of [\'azure\',\'openai\',\'tokenrouter\'])"}')])
    assert isinstance(out, RuntimeError) and len(calls) == 1 and sleeps == []
    assert "failed after 1 of 28 tries" in str(out) and "unknown codex provider 'custom'" in str(out)


@pytest.mark.parametrize("status", [401, 403, 404, 413, 422])
def test_every_other_4xx_is_a_verdict_too(monkeypatch, status):
    out, calls, sleeps = _drive(monkeypatch, [_Resp(status, b'{"detail":"no"}')], attempts=5)
    assert isinstance(out, RuntimeError) and len(calls) == 1 and sleeps == []
    assert f"HTTP {status}:" in str(out)


def test_a_cold_start_is_waited_for(monkeypatch):
    """Empty bodies, 429 and 5xx are what a sandbox answers while it spins up; the ladder waits
    through them and returns the first real answer, sleeping between tries."""
    for cold in ([_Resp(200, b""), _Resp(503), _Resp(429)], [ConnectionError("refused")]):
        out, calls, sleeps = _drive(monkeypatch, cold + [_Resp(200)], attempts=6)
        assert out == {"ok": True}, out
        assert len(calls) == len(cold) + 1 and len(sleeps) == len(cold)


def test_a_runner_that_never_comes_up_is_reported_with_the_tries_made(monkeypatch):
    out, calls, sleeps = _drive(monkeypatch, [_Resp(503, b"")], attempts=4)
    assert isinstance(out, RuntimeError) and len(calls) == 4 and len(sleeps) == 3
    assert "failed after 4 of 4 tries" in str(out) and "HTTP 503" in str(out)
