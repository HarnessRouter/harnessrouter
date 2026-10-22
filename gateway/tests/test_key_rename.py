"""A key can be renamed (PATCH /v1/orgs/{org}/keys/{kid}), and only its own organization's.

The console's Rename sends this; the route was the hosted service's alone, so on a self-hosted box
every rename answered 405. Driven through the real routes on the local store.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
os.environ.setdefault("HR_DATA_DIR", tempfile.mkdtemp(prefix="hr-keyrename-"))
import app as gw  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _as(org: str, member: str = "owner@local") -> dict:
    return {"x-harness-internal": gw.INTERNAL_KEY, "x-harness-org": org, "x-harness-member": member}


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(gw, "INTERNAL_KEY", gw.INTERNAL_KEY or "test-internal-key")
    with TestClient(gw.app) as c:
        yield c


def _mint(client, org: str, name: str) -> str:
    r = client.post(f"/v1/orgs/{org}/keys", headers=_as(org), json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _names(client, org: str) -> dict:
    r = client.get(f"/v1/orgs/{org}/keys", headers=_as(org))
    assert r.status_code == 200, r.text
    return {k["id"]: k["name"] for k in r.json()["keys"]}


def test_a_key_is_renamed_and_the_list_says_so(client):
    kid = _mint(client, "org-rn", "first name")
    r = client.patch(f"/v1/orgs/org-rn/keys/{kid}", headers=_as("org-rn"), json={"name": "  ci deploy  "})
    assert r.status_code == 200, r.text
    assert r.json() == {"id": kid, "name": "ci deploy"}
    assert _names(client, "org-rn")[kid] == "ci deploy"


def test_an_empty_name_is_refused_and_the_old_one_kept(client):
    kid = _mint(client, "org-rn2", "keep me")
    r = client.patch(f"/v1/orgs/org-rn2/keys/{kid}", headers=_as("org-rn2"), json={"name": "   "})
    assert r.status_code == 422
    assert _names(client, "org-rn2")[kid] == "keep me"


def test_another_organizations_key_is_not_there(client):
    kid = _mint(client, "org-a1", "theirs")
    r = client.patch(f"/v1/orgs/org-b1/keys/{kid}", headers=_as("org-b1"), json={"name": "mine now"})
    assert r.status_code == 404
    r = client.patch(f"/v1/orgs/org-a1/keys/{kid}", headers=_as("org-b1"), json={"name": "mine now"})
    assert r.status_code == 403
    assert _names(client, "org-a1")[kid] == "theirs"


def test_an_id_that_is_not_a_key_is_not_renamed(client):
    r = client.patch("/v1/orgs/org-rn3/keys/sess_not_a_key", headers=_as("org-rn3"), json={"name": "x"})
    assert r.status_code == 404
