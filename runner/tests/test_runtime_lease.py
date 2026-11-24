"""Cross-process runtime ownership lease contract."""
import multiprocessing
import pathlib
import sys
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from runtime_lease import (LeaseConflict, LeaseLost, RuntimeLeaseRegistry,
                           RuntimeLeaseToken)


def test_acquire_is_idempotent_for_same_owner_and_fences_takeover(tmp_path):
    registry = RuntimeLeaseRegistry(str(tmp_path / "leases.sqlite3"))
    first = registry.acquire("session/thread", "gateway-a", ttl=10, now=100.0)
    again = registry.acquire("session/thread", "gateway-a", ttl=10, now=101.0)
    assert again == first

    with pytest.raises(LeaseConflict):
        registry.acquire("session/thread", "gateway-b", ttl=10, now=102.0)

    takeover = registry.acquire("session/thread", "gateway-b", ttl=10, now=111.0)
    assert takeover.fence == first.fence + 1
    assert takeover.owner == "gateway-b"

    with pytest.raises(LeaseLost):
        registry.renew(RuntimeLeaseToken("session/thread", "gateway-a", first.fence),
                       ttl=10, now=112.0)
    with pytest.raises(LeaseLost):
        registry.release(RuntimeLeaseToken("session/thread", "gateway-a", first.fence), now=112.0)


def test_renew_release_and_reopen_preserve_fence(tmp_path):
    path = str(tmp_path / "leases.sqlite3")
    registry = RuntimeLeaseRegistry(path)
    lease = registry.acquire("runtime-1", "runner-1", ttl=5, now=10.0)
    renewed = registry.renew(RuntimeLeaseToken("runtime-1", "runner-1", lease.fence),
                             ttl=20, now=11.0)
    assert renewed.expires_at == 31.0
    registry.close()

    reopened = RuntimeLeaseRegistry(path)
    assert reopened.inspect("runtime-1") == renewed
    reopened.release(RuntimeLeaseToken("runtime-1", "runner-1", lease.fence), now=12.0)
    released = reopened.inspect("runtime-1")
    assert released is not None
    assert released.owner is None
    assert released.fence == lease.fence


def test_expired_lease_cannot_be_used_by_old_owner(tmp_path):
    registry = RuntimeLeaseRegistry(str(tmp_path / "leases.sqlite3"))
    lease = registry.acquire("runtime-1", "owner-a", ttl=2, now=10.0)
    with pytest.raises(LeaseLost):
        registry.assert_owner(RuntimeLeaseToken("runtime-1", "owner-a", lease.fence), now=12.0)


def _contender(path, owner, start, result):
    registry = RuntimeLeaseRegistry(path)
    try:
        lease = registry.acquire("shared-runtime", owner, ttl=30, now=start)
        result.put((owner, "acquired", lease.fence))
    except LeaseConflict:
        result.put((owner, "conflict", None))


def test_two_processes_have_one_active_owner(tmp_path):
    path = str(tmp_path / "leases.sqlite3")
    ctx = multiprocessing.get_context("spawn")
    result = ctx.Queue()
    processes = [ctx.Process(target=_contender, args=(path, owner, 100.0, result))
                 for owner in ("owner-a", "owner-b")]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0
    rows = [result.get(timeout=2) for _ in processes]
    assert sorted(row[1] for row in rows) == ["acquired", "conflict"]
