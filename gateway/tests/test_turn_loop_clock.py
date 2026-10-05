"""A turn's loop turns when the runner has something, so its periodic duties count the clock.

The loop used to sleep RESP_POLL_S and run a duty "every N polls" (the lease and the heartbeat every
20, the durable cancel check every 10). With a held request it turns several times a second while
text streams and once per hold while a tool runs, so N polls is no longer N intervals of time.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402


def test_a_duty_runs_once_per_n_intervals_however_often_the_loop_turns(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(gw.time, "time", lambda: now[0])
    monkeypatch.setattr(gw, "RESP_POLL_S", 1.2)
    every = gw._Every(now[0])
    runs = 0
    for _ in range(600):            # ten turns of the loop a second, for a minute
        now[0] += 0.1
        runs += every("renew", 20)  # 20 intervals of 1.2 s = 24 s
    assert runs == 2
    assert not every("cancel", 50)  # 60 s after the start, by the clock
    now[0] += 0.2
    assert every("cancel", 50) and not every("cancel", 50)


def test_a_slow_loop_runs_a_duty_late_by_at_most_one_turn(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(gw.time, "time", lambda: now[0])
    monkeypatch.setattr(gw, "RESP_POLL_S", 1.2)
    every = gw._Every(0.0)
    at = []
    for _ in range(24):             # one turn of the loop every 5 s (a held request with nothing new)
        now[0] += 5.0
        if every("renew", 20):      # due every 24 s
            at.append(now[0])
    assert at == [25.0, 50.0, 75.0, 100.0]


def test_only_the_named_duties_run_at_once(monkeypatch):
    now = [500.0]
    monkeypatch.setattr(gw.time, "time", lambda: now[0])
    every = gw._Every(now[0], at_once=("touch",))
    assert every("touch", 20) and not every("touch", 20)
    assert not every("renew", 20)


def test_the_loop_asks_from_what_it_has_fed_holds_by_default_and_paces_itself_without_a_hold():
    src = open(os.path.join(os.path.dirname(__file__), "..", "app.py")).read()
    i = src.index("held = RESP_HOLD_S > 0")
    loop = src[i:src.index("_last_err = str(rec", i)]
    assert gw.RESP_HOLD_S > 0                                     # the default holds
    assert '"since": fed_upto' in loop and '{"wait": RESP_HOLD_S} if RESP_HOLD_S > 0 else {}' in loop
    assert "if not held:\n                await asyncio.sleep(RESP_POLL_S)" in loop      # an older runner
    assert "held = bool(s.get(\"held\"))" in loop
    # a failed request is not a held one: the next is paced, so a dead runner is not asked in a spin
    assert loop.index("poll_fails += 1") < loop.index("held = False") < loop.index("if poll_fails >= 5")
    # the trace is written once per interval and at the end, and what a cut loop left is written after it
    assert "if pending and (s.get(\"done\") or time.time() - last_flush >= RESP_POLL_S):" in loop
    assert "if pending:   # the loop was left between two writes" in loop
