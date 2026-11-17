import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# The runner enforces Unix ownership boundaries and imports ``pwd`` at module load.
# Keep the test suite collectable on Windows; the actual readiness tests run in the
# Linux runner image where that boundary exists.  Use an OS check before importing
# ``server`` because session-router has a module with the same import name.
if os.name != "posix":
    pytest.skip("runner readiness tests require the Unix runner image", allow_module_level=True)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


@pytest.mark.parametrize("phase,ready", [("starting", False), ("installing", False), ("failed", False), ("ready", True)])
def test_state_controls_readiness_and_turn_admission(monkeypatch, tmp_path, phase, ready):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"phase": phase, "ready": ready, "accepting": ready}))
    monkeypatch.setenv("HR_RUNNER_STATE", str(path))
    monkeypatch.setattr(server, "_SESSION_UIDS", False)
    client = TestClient(server.app)
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == (200 if ready else 503)
    assert client.get("/readyz").json()["phase"] == phase
    if not ready:
        response = client.post("/turn?identifier=readiness", json={"prompt": "hello"})
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "runner_not_ready"


def test_corrupt_or_missing_managed_state_is_not_ready(monkeypatch, tmp_path):
    path = tmp_path / "state.json"
    monkeypatch.setenv("HR_RUNNER_STATE", str(path))
    assert not server._runner_state()["ready"]
    path.write_text("{")
    assert not server._runner_state()["ready"]


def test_direct_runner_without_installer_keeps_existing_behavior(monkeypatch):
    monkeypatch.delenv("HR_RUNNER_STATE", raising=False)
    assert server._runner_state()["ready"]
