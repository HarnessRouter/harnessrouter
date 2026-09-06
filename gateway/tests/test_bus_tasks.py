"""The Redis bus tasks are held and restarted: asyncio keeps only a weak reference to a task, so
the unreferenced create_task() of the pump and the listener was collected mid-await ("Task was
destroyed but it is pending!") and every replica silently lost its subscriber (2026-09-06)."""
import asyncio
import gc
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402


@pytest.mark.asyncio
async def test_held_task_survives_gc():
    async def fn():
        await asyncio.sleep(3600)
    t = gw._spawn_forever("t-gc", fn)
    gc.collect()
    await asyncio.sleep(0.05)
    assert gw._BG_TASKS["t-gc"] is t and not t.done()
    t.cancel()
    await asyncio.sleep(0.01)
    assert "t-gc" not in gw._BG_TASKS            # a cancelled task (shutdown) is not restarted


@pytest.mark.asyncio
async def test_task_that_ends_is_restarted_and_flags_the_subscriber(capsys):
    starts = []
    gw._redis_ok["sub"] = True

    async def fn():
        starts.append(1)
        if len(starts) == 1:
            raise RuntimeError("boom")
        await asyncio.sleep(3600)
    t = gw._spawn_forever("redis-listen", fn)
    await asyncio.sleep(0.05)
    assert t.done() and gw._redis_ok["sub"] is False
    assert "task redis-listen ended: RuntimeError('boom'); restarting" in capsys.readouterr().out
    await asyncio.sleep(1.2)
    t2 = gw._BG_TASKS["redis-listen"]
    assert t2 is not t and not t2.done() and len(starts) == 2
    t2.cancel()
    await asyncio.sleep(0.01)
