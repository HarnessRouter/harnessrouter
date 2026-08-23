"""Share links on a self-hosted box: no hosted graph URL, the SQLite backing, and a link that has
to resolve for someone who has no account. The resolver used to bail out the moment
VG_GATEWAY_URL was empty, so every self-hosted share answered "share not found" while the console
happily minted the links."""
import asyncio
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402

ORG = "local"


@pytest.fixture()
def api(monkeypatch):
    monkeypatch.setattr(gw, "VG_GATEWAY_URL", "")          # self-hosted: there is no hosted graph

    async def principal(request):
        return {"org": ORG, "member": "me@local"}
    monkeypatch.setattr(gw, "_principal", principal)
    gw._SHARE_TOKEN_CACHE.clear()
    gw._SHARE_STATE_CACHE.clear()
    return TestClient(gw.app)


def _session(sid: str, **extra) -> None:
    asyncio.run(gw._vertex_upsert(sid, {"tenant": ORG, "status": "done", "member_id": "me@local", **extra}))


def test_a_share_link_resolves_without_a_hosted_graph(api):
    sid = "hsessshare" + os.urandom(4).hex()
    _session(sid)
    r = api.post(f"/v1/sessions/{sid}/share", json={"enabled": True})
    assert r.status_code == 200 and r.json()["enabled"] is True
    token = r.json()["token"]
    assert token.startswith("shr")
    assert asyncio.run(gw._share_sid(token)) == sid
    # The public route, as the recipient hits it: no principal, no cookie, just the link.
    assert api.get(f"/share/{token}/meta").status_code == 200


def test_switching_sharing_off_revokes_the_link(api):
    sid = "hsessshare" + os.urandom(4).hex()
    _session(sid)
    token = api.post(f"/v1/sessions/{sid}/share", json={"enabled": True}).json()["token"]
    assert api.get(f"/share/{token}/meta").status_code == 200
    assert api.post(f"/v1/sessions/{sid}/share", json={"enabled": False}).status_code == 200
    assert asyncio.run(gw._share_sid(token)) is None
    assert api.get(f"/share/{token}/meta").status_code == 404


def test_an_unknown_token_is_not_found(api):
    assert asyncio.run(gw._share_sid("shr" + "0" * 32)) is None
    assert api.get("/share/shr" + "0" * 32 + "/meta").status_code == 404
