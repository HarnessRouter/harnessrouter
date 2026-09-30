import json
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as gw

HEADERS = {"x-harness-internal": "test-internal-key", "x-harness-org": "pilab-tests",
           "x-harness-member": "tester@example.com"}


def test_config_api_round_trip_and_ordinary_pi_separation():
    with TestClient(gw.app) as api:
        cfg = {"actionFusion": False, "observationPack": True, "evidencePreservingReducer": False,
               "onlineContextCompact": True, "cacheWriteReadRatio": 0}
        body = {"name": "SoL experiment", "base": "pi-lab", "pi_lab": cfg}
        r = api.post("/v1/harnesses", headers=HEADERS, json=body)
        assert r.status_code == 200, r.text
        h = r.json()
        assert h["base"] == "pi-lab" and h["piLab"] == cfg
        r = api.get("/v1/harnesses/" + h["id"], headers=HEADERS)
        assert r.json()["piLab"] == cfg
        cfg["actionFusion"] = True
        r = api.put("/v1/harnesses/" + h["id"], headers=HEADERS, json={**body, "pi_lab": cfg})
        assert r.status_code == 200, r.text
        assert r.json()["piLab"]["actionFusion"] is True
        r = api.post("/v1/harnesses", headers=HEADERS, json={**body, "base": "pi"})
        assert r.status_code == 200, r.text
        assert r.json()["piLab"] is None


def test_distinct_backend_has_pi_connectivity_without_aliasing():
    assert gw._harness_props(gw.HarnessBody(name="x", base="pi-lab"))["base"] == "pi-lab"
    for (provider, backend), route in gw._INTEGRATION_WIRING.items():
        if backend == "pi":
            assert gw._INTEGRATION_WIRING[(provider, "pi-lab")] == route
    assert gw._MODEL_CATALOG["pi-lab"]["models"] == gw._MODEL_CATALOG["pi"]["models"]


@pytest.mark.parametrize("value", [{"actionFusion": "true"}, {"other": 1}, {"cacheWriteReadRatio": -1},
                                   {"cacheWriteReadRatio": float("inf")}, {"reducerModel": " "}])
def test_invalid_config_rejected_before_storage(value):
    with pytest.raises(gw.HTTPException):
        gw._harness_props(gw.HarnessBody(name="x", base="pi-lab", pi_lab=value))


def test_camel_case_input_and_defaults():
    body = gw.HarnessBody(name="x", base="pi-lab", piLab={"actionFusion": False})
    cfg = json.loads(gw._harness_props(body)["pi_lab"])
    assert cfg["actionFusion"] is False and cfg["observationPack"] is True
