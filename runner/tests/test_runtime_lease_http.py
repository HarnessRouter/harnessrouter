"""Runner internal Runtime lease HTTP contract (Unix Runner image)."""
import os
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

if os.name != "posix":
    pytest.skip("Runner HTTP tests require the Unix Runner image", allow_module_level=True)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


def test_runtime_lease_http_preserves_fence_and_rejects_stale_owner(monkeypatch, tmp_path):
    monkeypatch.setenv("HR_RUNTIME_LEASE_DB", str(tmp_path / "runtime-leases.sqlite3"))
    monkeypatch.setattr(server, "_INTERNAL_KEY", "runner-key")
    monkeypatch.setattr(server, "_runtime_lease_registry", None)
    monkeypatch.setattr(server, "_runtime_lease_registry_path", None)
    monkeypatch.setattr(server, "_SESSION_UIDS", False)
    client = TestClient(server.app)

    acquired = client.post("/internal/runtime-leases/acquire", headers={"x-harness-internal": "runner-key"}, json={
        "runtime_id": "session/thread", "owner": "runner-a", "ttl_seconds": 30,
    })
    assert acquired.status_code == 200
    lease = acquired.json()
    assert lease["owner"] == "runner-a"
    assert lease["fence"] == 1

    conflict = client.post("/internal/runtime-leases/acquire", headers={"x-harness-internal": "runner-key"}, json={
        "runtime_id": "session/thread", "owner": "runner-b", "ttl_seconds": 30,
    })
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "runtime_lease_conflict"

    renewed = client.post("/internal/runtime-leases/renew", headers={"x-harness-internal": "runner-key"}, json={
        "runtime_id": "session/thread", "owner": "runner-a", "fence": lease["fence"],
        "ttl_seconds": 30,
    })
    assert renewed.status_code == 200
    assert renewed.json()["fence"] == lease["fence"]

    stale = client.post("/internal/runtime-leases/release", headers={"x-harness-internal": "runner-key"}, json={
        "runtime_id": "session/thread", "owner": "runner-b", "fence": lease["fence"],
    })
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "runtime_lease_lost"

    released = client.post("/internal/runtime-leases/release", headers={"x-harness-internal": "runner-key"}, json={
        "runtime_id": "session/thread", "owner": "runner-a", "fence": lease["fence"],
    })
    assert released.status_code == 200
    assert released.json()["owner"] is None


def test_runtime_lease_http_never_uses_unkeyed_internal_surface(monkeypatch, tmp_path):
    monkeypatch.setenv("HR_RUNTIME_LEASE_DB", str(tmp_path / "runtime-leases.sqlite3"))
    monkeypatch.setattr(server, "_INTERNAL_KEY", "runner-key")
    monkeypatch.setattr(server, "_runtime_lease_registry", None)
    monkeypatch.setattr(server, "_runtime_lease_registry_path", None)
    client = TestClient(server.app)
    response = client.post("/internal/runtime-leases/acquire", json={
        "runtime_id": "runtime", "owner": "owner", "ttl_seconds": 30,
    })
    assert response.status_code == 401
