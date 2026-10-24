"""Where a harness came from (`source`), as whatever made it said: the console's Start saves a demo
from its recorded run with `source: "demo:<n>@<ms>"`, and the setup's task list shows that run as
its first task for as long as the setup exists. So the value is stored on create, read back with
the harness (GET, the list, the create's own answer), and never changed by an update: a PUT that
leaves it out, or carries another value, keeps the stored one. A harness made without one has no
`source` key at all, and a value longer than the cap is refused rather than cut."""
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app  # noqa: E402

H = {"x-harness-internal": "test-internal-key", "x-harness-org": "org.source", "x-harness-member": "tester@example.com"}
MARK = "demo:0@1792378362430"


@pytest.fixture(scope="module")
def client():
    with TestClient(app.app) as c:
        yield c


def _model(base):
    return app._MODEL_CATALOG[app._backend_of_harness({"base": base})]["models"][0]


def _make(client, **extra):
    r = client.post("/v1/harnesses", json={"name": "Product images", "base": "pi", "default_model": _model("pi"),
                                           "system_prompt": "Make product images.", **extra}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def _listed(client, hid):
    hs = client.get("/v1/harnesses", headers=H).json()["harnesses"]
    return next(h for h in hs if h["id"] == hid)


def test_stored_on_create_and_read_back_everywhere(client):
    made = _make(client, source=MARK)
    assert made["source"] == MARK                                   # the create's own answer
    assert client.get(f"/v1/harnesses/{made['id']}", headers=H).json()["source"] == MARK
    assert _listed(client, made["id"])["source"] == MARK


def test_an_update_never_changes_it(client):
    made = _make(client, source=MARK)
    hid = made["id"]
    # the harness read and sent back, with another value in it: saved, the source kept
    got = client.get(f"/v1/harnesses/{hid}", headers=H).json()
    got.update(systemPrompt="v2", source="demo:9@1")
    r = client.put(f"/v1/harnesses/{hid}", json=got, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["systemPrompt"] == "v2" and r.json()["source"] == MARK
    # a body that leaves it out: kept too
    r = client.put(f"/v1/harnesses/{hid}", json={"name": "Product images", "base": "pi", "system_prompt": "v3"}, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["source"] == MARK
    assert client.get(f"/v1/harnesses/{hid}", headers=H).json()["source"] == MARK
    assert _listed(client, hid)["source"] == MARK


def test_absent_stays_absent(client):
    made = _make(client)
    hid = made["id"]
    assert "source" not in made
    assert "source" not in client.get(f"/v1/harnesses/{hid}", headers=H).json()
    assert "source" not in _listed(client, hid)
    # an update cannot add one either: it is the maker's to say, once
    r = client.put(f"/v1/harnesses/{hid}", json={"name": "Product images", "base": "pi", "source": MARK}, headers=H)
    assert r.status_code == 200, r.text
    assert "source" not in r.json()
    assert "source" not in client.get(f"/v1/harnesses/{hid}", headers=H).json()
    # blank is no source
    assert "source" not in _make(client, source="   ")


def test_the_organization_route_keeps_it_the_same_way(client):
    org = H["x-harness-org"]
    r = client.post(f"/v1/orgs/{org}/harnesses", json={"name": "Contract review", "base": "pi", "source": "demo:1@1792378167358"}, headers=H)
    assert r.status_code == 200, r.text
    hid = r.json()["id"]
    assert r.json()["source"] == "demo:1@1792378167358"
    r = client.put(f"/v1/orgs/{org}/harnesses/{hid}", json={"name": "Contract review", "base": "pi", "source": "other"}, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["source"] == "demo:1@1792378167358"
    assert client.get(f"/v1/orgs/{org}/harnesses/{hid}", headers=H).json()["source"] == "demo:1@1792378167358"


def test_a_value_over_the_cap_is_refused_not_cut(client):
    before = len(client.get("/v1/harnesses", headers=H).json()["harnesses"])
    r = client.post("/v1/harnesses", json={"name": "x", "base": "pi", "source": "d" * (app.HARNESS_SOURCE_MAX + 1)}, headers=H)
    assert r.status_code == 422
    assert len(client.get("/v1/harnesses", headers=H).json()["harnesses"]) == before
    assert _make(client, source="d" * app.HARNESS_SOURCE_MAX)["source"] == "d" * app.HARNESS_SOURCE_MAX
