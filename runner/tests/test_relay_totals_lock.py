"""A route's totals are folded by the relay's request threads and read by the turn, on different
threads by construction (#449). These pin the ordering by holding a fold at its worst moment and
acting from a second thread, rather than by asking whether a lock object exists:

- a reader sees the whole fold or the one before it, never a mixture of two answers' figures;
- two folds racing on one route both land, so no call's tokens are lost.
"""
import pathlib
import sys
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server as rs  # noqa: E402

GRACE = 0.5      # how long a second thread is given to act early; a fixed tree only waits longer


class _Gated(dict):
    """A call's usage that stops after handing over its first figure, until released: the fold has
    written one key of the route's total and not the next."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.inside = threading.Event()
        self.release = threading.Event()

    def items(self):
        for n, kv in enumerate(super().items()):
            if n == 1:
                self.inside.set()
                assert self.release.wait(10)
            yield kv


class _SlowInt:
    """A figure that is read only once released: the fold has read the route's current total and
    has not written its sum yet, the read-modify-write window where another fold can land."""

    def __init__(self, n):
        self.n = n
        self.inside = threading.Event()
        self.release = threading.Event()

    def _wait(self):
        self.inside.set()
        assert self.release.wait(10)

    def __int__(self):
        self._wait()
        return self.n

    def __radd__(self, other):
        self._wait()
        return other + self.n


def _route(flags: dict) -> dict:
    tok = "hr-relay-test-totals-%d" % id(flags)
    rs._HERMES_RELAY["routes"][tok] = ("http://upstream.invalid", "k", flags)
    return {"OPENAI_API_KEY": tok}


def _run(fn, *args):
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("v", fn(*args)), daemon=True)
    t.start()
    return t, out


def _read_during(fold, flags: dict, gate) -> dict:
    """Start `fold`, wait until it is held midway, read the route's usage from another thread, then
    let the fold finish. Returns what the reader saw."""
    env = _route(flags)
    folder, _ = _run(fold)
    assert gate.inside.wait(10)
    reader, seen = _run(rs._relay_usage, env)
    reader.join(GRACE)
    gate.release.set()
    folder.join(10)
    reader.join(10)
    assert not folder.is_alive() and not reader.is_alive()
    return seen["v"]


def test_a_reader_sees_a_whole_usage_add_or_the_one_before_it():
    before = {"input_tokens": 10, "output_tokens": 4}
    flags = {"usage": dict(before)}
    call = _Gated(input_tokens=5, output_tokens=3)
    seen = _read_during(lambda: rs._usage_add(flags, call), flags, call)
    after = {"input_tokens": 15, "output_tokens": 7}
    assert seen in (before, after), f"the reader saw part of a fold: {seen}"
    assert flags["usage"] == after


def test_a_reader_sees_a_whole_stream_fold_or_the_one_before_it():
    before = {"input_tokens": 10, "output_tokens": 4}
    flags = {"usage": dict(before)}
    call = _Gated(input_tokens=5, output_tokens=3)
    seen = _read_during(lambda: rs._stream_fold(flags, call, None, {}), flags, call)
    after = {"input_tokens": 15, "output_tokens": 7}
    assert seen in (before, after), f"the reader saw part of a fold: {seen}"
    assert flags["usage"] == after


def _race(first, second):
    """Hold `first` inside its read-modify-write, run `second` from another thread, then release."""
    gate = first[1]
    a, _ = _run(*first[0])
    assert gate.inside.wait(10)
    b, _ = _run(*second)
    b.join(GRACE)
    gate.release.set()
    a.join(10)
    b.join(10)
    assert not a.is_alive() and not b.is_alive()


def test_two_usage_folds_racing_on_one_route_both_land():
    flags = {"usage": {"output_tokens": 100}}
    slow = _SlowInt(3)
    _race(((rs._usage_add, flags, {"output_tokens": slow}), slow),
          (rs._usage_add, flags, {"output_tokens": 4}))
    assert flags["usage"]["output_tokens"] == 107, "one call's tokens were lost"


def test_two_thinking_folds_racing_on_one_route_both_land():
    flags = {"reasoning_tokens": 100}
    slow = _SlowInt(3)
    _race(((rs._thinking_add, flags, slow), slow), (rs._thinking_add, flags, 4))
    assert flags["reasoning_tokens"] == 107, "one call's thinking tokens were lost"


def test_many_calls_on_one_route_sum_exactly():
    flags: dict = {}
    n_threads, n_calls = 8, 200

    def calls():
        for _ in range(n_calls):
            rs._usage_add(flags, {"input_tokens": 1, "output_tokens": 2})
            rs._thinking_add(flags, 1)

    threads = [threading.Thread(target=calls) for _ in range(n_threads)]
    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        sys.setswitchinterval(old)
    total = n_threads * n_calls
    assert flags["usage"] == {"input_tokens": total, "output_tokens": 2 * total}
    assert flags["reasoning_tokens"] == total
