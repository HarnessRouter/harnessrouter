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


def test_a_bodyless_post_publishes_the_share(api):
    """Sessions §5 documents `POST .../share` with no body — publishing is the request's whole
    meaning — and this endpoint 422'd that dialect, which is how the entire conformance R-series
    skipped against the reference server."""
    sid = "hsessshare" + os.urandom(4).hex()
    _session(sid)
    r = api.post(f"/v1/sessions/{sid}/share")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["enabled"] is True and d["token"]
    assert d["id"] == d["token"], "the token is the share's identity, under one name"
    assert d["url"] == f"/share/{d['token']}", "the object must say where its view is served"
    assert api.get(f"/v1/sessions/{sid}/share").json()["url"] == d["url"], (
        "GET must report the same link POST published")


def test_the_published_url_opens_with_no_credential(api):
    sid = "hsessshare" + os.urandom(4).hex()
    _session(sid)
    url = api.post(f"/v1/sessions/{sid}/share").json()["url"]
    r = api.get(url)     # no auth beyond the link itself: the token is the credential
    assert r.status_code == 200, r.text
    assert r.json()["object"] == "session.shared"
    assert r.json()["session_id"] == sid


def test_delete_on_the_share_endpoint_revokes(api):
    """§5 requires revocability and names no path. DELETE on the share endpoint is the reading a
    client tries first, and it answered 405 while revocation hid inside POST {"enabled": false}."""
    sid = "hsessshare" + os.urandom(4).hex()
    _session(sid)
    url = api.post(f"/v1/sessions/{sid}/share").json()["url"]
    assert api.get(url).status_code == 200
    r = api.delete(f"/v1/sessions/{sid}/share")
    assert r.status_code == 200 and r.json()["enabled"] is False
    assert api.get(url).status_code == 404, "a revoked link must stop resolving"


def test_deleting_the_session_takes_its_share_with_it(api, monkeypatch):
    """The R-07 defect, verified live before this fix: DELETE /v1/traces answered 200 and the
    share link went on serving the full conversation, because the resolver matches on
    {share_token, shared: "1"} and the tombstone never touched `shared` — while the turns behind
    the view are rebuilt from response records, which deletion does not remove. Sessions §6:
    deletion MUST make the session unreadable, and the published link is the reader its owner is
    least likely to remember."""
    sid = "hsessshare" + os.urandom(4).hex()
    _session(sid)

    async def owned(request, s):
        return ORG, {"id": s, "tenant": ORG}
    monkeypatch.setattr(gw, "_owned_session", owned)

    url = api.post(f"/v1/sessions/{sid}/share").json()["url"]
    assert api.get(url).status_code == 200
    assert api.delete(f"/v1/traces/{sid}").status_code == 200
    assert api.get(url).status_code == 404, "a deleted session's share link must die with it"
    assert api.get(url + "/turns").status_code == 404, (
        "the turns behind the view are rebuilt from response records deletion does not remove — "
        "the resolver is the only gate, so it must refuse")
