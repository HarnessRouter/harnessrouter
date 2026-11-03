"""Two organizations, each with a workspace called "default", keep two plug rows (GHSA-gf7m-w8pf-6f68).
The row's id used to be plug.<workspace>.<type>, so the second to connect overwrote the first's row, and the first then read "missing"."""
import asyncio

from test_plugs_local import client, _req  # noqa: F401
import app as gw


def _as(org):
    return {"x-harness-org": org, "x-harness-member": "owner", "x-harness-workspace": "default"}


def _put(client, org, domain):  # noqa: F811
    return _req(client, "PUT", "/v1/plugs/browser", {"enabled": True, "config": {"allow_domains": [domain]}}, headers=_as(org))


def _read(client, org):  # noqa: F811
    r = _req(client, "GET", "/v1/plugs", headers=_as(org))
    assert r.status_code == 200, r.text
    return next(p for p in r.json()["plugs"] if p["type"] == "browser")


def _rows(org):
    rows = asyncio.run(gw.BACKING.graph.find(gw._PLUG_LABEL, {"workspace": "default", "type": "browser"}))
    return [r for r in rows if str(r.get("org") or "") == org]


def test_the_second_organization_to_connect_does_not_overwrite_the_first(client):  # noqa: F811
    assert _put(client, "org-rows-a", "a.example").status_code == 200
    assert _put(client, "org-rows-b", "b.example").status_code == 200
    assert _read(client, "org-rows-a")["config"]["allow_domains"] == ["a.example"]
    assert _read(client, "org-rows-b")["config"]["allow_domains"] == ["b.example"]
    assert _req(client, "DELETE", "/v1/plugs/browser", headers=_as("org-rows-b")).status_code == 200
    assert _read(client, "org-rows-a")["config"]["allow_domains"] == ["a.example"], "the other's delete took this row"
    assert _read(client, "org-rows-b")["status"] == "missing"


def test_a_row_from_before_keeps_its_id_and_is_not_doubled(client):  # noqa: F811
    org = "org-rows-old"
    asyncio.run(gw._vg_upsert(gw._PLUG_LABEL, "plug.default.browser",
                              {"org": org, "workspace": "default", "type": "browser", "status": "connected", "source": "local",
                               "config": '{"allow_domains":["old.example"],"deny_domains":[],"proxy":false}', "key_refs": "[]",
                               "attention": "", "version": "1", "updated_at": "1"}))
    assert _read(client, org)["config"]["allow_domains"] == ["old.example"]
    assert _put(client, org, "new.example").status_code == 200
    assert [r["id"] for r in _rows(org)] == ["plug.default.browser"]
    assert _read(client, org)["config"]["allow_domains"] == ["new.example"]
    assert _req(client, "DELETE", "/v1/plugs/browser", headers=_as(org)).status_code == 200
    assert _rows(org) == []


def test_the_id_names_the_organization():
    assert gw._plug_vid("a", "default", "browser") != gw._plug_vid("b", "default", "browser")
    assert gw._plug_vid("a", "default", "browser", {"id": "plug.default.browser"}) == "plug.default.browser"


def test_a_live_read_does_not_serve_the_runners_own_state(client, monkeypatch):  # noqa: F811
    """The listing hides `.harness/` and a write there is refused; a live read by path served it."""
    reads = []

    async def read(sid, path):
        reads.append(path)
        return b"visible"

    async def owned(request, sid):
        return {}

    monkeypatch.setattr(gw.BACKING.workspace, "read", read)
    monkeypatch.setattr(gw, "_owned_session", owned)
    for path in (".harness/agent-subdir", "./.harness/x", "a/../.harness/x", ".harness", "//.harness/x"):
        assert gw._ws_machinery(path), path
    r = _req(client, "GET", "/v1/sessions/hsessx/files/.harness/agent-subdir")
    assert r.status_code == 404 and reads == []
    r = _req(client, "GET", "/v1/sessions/hsessx/files/report.md")
    assert r.status_code == 200 and r.content == b"visible" and reads == ["report.md"]
    assert not gw._ws_machinery("my.harness/x") and not gw._ws_machinery("dir/.harness/x")
