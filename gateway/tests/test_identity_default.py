"""A gateway trusts self-asserted identity headers only when its operator chose that (GHSA-qrr8-m92f-7vfp).

A console that is not in self-hosted mode attaches the internal key to every request carrying an
Authorization header. With the identity mode unset the gateway used to run "observe", which keeps
the X-Harness-Org / X-Harness-Member headers beside a bearer that does not verify, so a junk bearer
could assert any organization. Unset now means enforce; the self-hosted entrypoint sets "off".
"""
import os
import pathlib
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402

KEY = os.environ["HARNESS_INTERNAL_KEY"]
GATEWAY = pathlib.Path(__file__).resolve().parents[1]


def _mode_with(value) -> str:
    env = {k: v for k, v in os.environ.items() if k != "HR_IDENTITY_MODE"}
    if value is not None:
        env["HR_IDENTITY_MODE"] = value
    out = subprocess.run([sys.executable, "-c", "import app; print('MODE=' + app.HR_IDENTITY_MODE)"],
                         cwd=GATEWAY, env=env, capture_output=True, text=True, timeout=180)
    line = [x for x in out.stdout.splitlines() if x.startswith("MODE=")]
    assert line, out.stderr[-600:]
    return line[-1][5:]


def test_unset_or_unknown_means_enforce_and_the_two_named_modes_are_kept():
    assert _mode_with(None) == "enforce"
    assert _mode_with("") == "enforce"
    assert _mode_with("Enforce ") == "enforce"
    assert _mode_with("strict") == "enforce"          # a typo fails closed, not open
    assert _mode_with(" OFF") == "off"
    assert _mode_with("observe") == "observe"


def test_self_hosted_entrypoint_still_sets_off():
    entry = (GATEWAY.parent / "docker" / "entrypoint.sh").read_text()
    assert 'export HR_IDENTITY_MODE="${HR_IDENTITY_MODE:-off}"' in entry


@pytest.fixture
def client():
    with TestClient(gw.app) as c:
        yield c


def test_under_enforce_a_junk_bearer_cannot_assert_an_organization(client, monkeypatch):
    monkeypatch.setattr(gw, "HR_IDENTITY_MODE", "enforce")
    asserted = {"x-harness-internal": KEY, "x-harness-org": "org.someone-else", "x-harness-member": "them@example.com"}
    for junk in ("Bearer junk", "Bearer a.b.c", "Bearer sk-hr-not-a-real-key"):
        r = client.get("/v1/orgs/org.someone-else/harnesses", headers={**asserted, "authorization": junk})
        assert r.status_code == 401, (junk, r.status_code, r.text[:200])
    # a service holding the key and sending no Authorization keeps header identity, as before
    assert client.get("/v1/orgs/org.someone-else/harnesses", headers=asserted).status_code == 200


def test_observe_remains_an_explicit_choice_with_its_documented_behaviour(client, monkeypatch):
    monkeypatch.setattr(gw, "HR_IDENTITY_MODE", "observe")
    h = {"x-harness-internal": KEY, "x-harness-org": "org.a", "x-harness-member": "a@example.com", "authorization": "Bearer junk"}
    assert client.get("/v1/orgs/org.a/harnesses", headers=h).status_code == 200
