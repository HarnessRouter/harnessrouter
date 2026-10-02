"""Public active documents are origin-isolated; revocation is checked beyond local caches."""
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402


@pytest.fixture
def shared(monkeypatch):
    state = {"id": "session1", "tenant": "org1", "share_token": "shrtest", "shared": "1", "status": "done"}

    async def get(sid):
        return dict(state) if sid == state["id"] else None

    async def find(label, props):
        # Deliberately emulate an eventually consistent index: the point read must be
        # authoritative even when the lookup still returns a revoked session.
        return [{"id": state["id"]}]

    async def upsert(sid, props):
        state.update(props)

    async def principal(request):
        return {"org": "org1"}

    async def file_bytes(sid, fid):
        path = gw._wf_path(fid)
        media = {"page.html": "text/html", "image.svg": "image/svg+xml",
                 "page.xhtml": "application/xhtml+xml", "style.css": "text/css",
                 "code.js": "text/javascript", "photo.png": "image/png"}.get(path, "application/octet-stream")
        return b"<script>window.canary = 1</script>\x00\xff", media, path

    async def trace_base(sid):
        return None

    async def turns(sid):
        return {"turns": []}

    async def files(sid):
        return {"page.html": b"example"}

    monkeypatch.setattr(gw, "VG_GATEWAY_URL", "http://unused.test")
    monkeypatch.setattr(gw, "_vertex_get", get)
    monkeypatch.setattr(gw, "_vertex_upsert", upsert)
    monkeypatch.setattr(gw.BACKING.graph, "find", find)
    monkeypatch.setattr(gw, "_principal", principal)
    monkeypatch.setattr(gw, "_container_file_bytes", file_bytes)
    monkeypatch.setattr(gw, "_trace_base", trace_base)
    monkeypatch.setattr(gw, "_session_turns_data", turns)
    monkeypatch.setattr(gw, "_ws_files", files)
    monkeypatch.setattr(gw, "_SHARE_TOKEN_CACHE", {})
    return state


def client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=gw.app), base_url="https://gateway.test")


@pytest.mark.parametrize("file", ["page.html", "image.svg", "page.xhtml", "style.css", "code.js", "photo.png", "unknown.bin"])
@pytest.mark.parametrize("prefix", ["/share/shrtest/f/", "/w/h/session1/workspace/"])
async def test_public_file_document_policy_and_bytes(shared, prefix, file):
    async with client() as http:
        response = await http.get(prefix + file)
    assert response.status_code == 200
    assert response.content == b"<script>window.canary = 1</script>\x00\xff"
    csp = response.headers["content-security-policy"]
    assert "sandbox allow-scripts" in csp
    assert "allow-same-origin" not in csp
    assert "form-action 'none'" in csp
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


@pytest.mark.parametrize("path", ["/share/shrtest", "/share/shrtest/meta", "/share/shrtest/turns", "/share/shrtest/files"])
async def test_share_metadata_and_revoked_errors_are_not_cached(shared, path):
    async with client() as http:
        response = await http.get(path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "private, no-store"
        shared["shared"] = "0"
        response = await http.get(path)
    assert response.status_code == 404
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("method", ["DELETE", "POST"])
async def test_revoke_denies_a_sibling_with_a_warm_token_lookup(shared, method):
    async with client() as http:
        assert (await http.get("/share/shrtest/f/page.html")).status_code == 200
        sibling_cache = dict(gw._SHARE_TOKEN_CACHE)
        response = await http.request(method, "/v1/sessions/session1/share",
                                      **({"json": {"enabled": False}} if method == "POST" else {}))
        assert response.status_code == 200
        # Local invalidation cannot touch another replica. Restore its warmed lookup.
        gw._SHARE_TOKEN_CACHE.update(sibling_cache)
        for path in ["/share/shrtest/f/page.html", "/w/h/session1/workspace/page.html"]:
            response = await http.get(path)
            assert response.status_code == 404
            assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("update", [{"status": "deleted"}, {"share_token": "rotated"}])
async def test_cached_lookup_cannot_outlive_deletion_or_token_rotation(shared, update):
    async with client() as http:
        assert (await http.get("/share/shrtest/f/page.html")).status_code == 200
        shared.update(update)
        assert (await http.get("/share/shrtest/f/page.html")).status_code == 404


async def test_authenticated_artifact_behavior_is_not_changed(shared):
    async with client() as http:
        response = await http.get("/a/session1/page.html")
    assert response.status_code == 200
    assert "sandbox" not in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "private, max-age=60"
