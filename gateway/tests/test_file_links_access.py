"""Who can open a task's file, at each address the product hands out (#594).

A reply's link to its own file opened "file not found" unless the task was shared, because the
console pointed it at the PUBLIC address (/w/...), which answers only for a shared task. The fix
reads the file through the signed-in addresses instead; this file pins down what each address
answers, so that moving a link from one to another can never widen who reads what:

  /w/{harness}/{sid}/workspace/{path}            public: the task must be shared, no caller at all
  /share/{token}/f/{path}                        public: the token is the credential, while shared
  /a/{sid}/{path}                                signed in: the task's organization, live tasks only
  /v1/containers/{sid}/files/{file_id}/content   signed in: the same (the API's annotations point here)

Four readers, each against each address: the owner signed in (the console: internal key and the
member's organization; or the organization's own API key), another organization, someone holding
the share link, and a request with no credential. The principal is resolved for real here, not
stubbed; only the file bytes are."""
import asyncio
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402

OWN, OTHER = "org-own", "org-other"
OWNER = {"x-harness-internal": "test-internal-key", "x-harness-org": OWN, "x-harness-member": "ana@example.com"}
STRANGER = {"x-harness-internal": "test-internal-key", "x-harness-org": OTHER, "x-harness-member": "eve@example.com"}
NOBODY: dict = {}
FILE = "hello-world.pptx"
BYTES = b"PK\x03\x04 a deck"


def _sid() -> str:
    return "hsesslinks" + os.urandom(6).hex()


@pytest.fixture()
def api(monkeypatch):
    """The real principal, the SQLite backing, and a workspace that holds one file."""
    async def file_bytes(container_id, file_id):
        path = gw._wf_path(file_id) if file_id.startswith("wf_") else None
        if path == FILE:
            return BYTES, "application/vnd.openxmlformats-officedocument.presentationml.presentation", FILE
        return None
    monkeypatch.setattr(gw, "_container_file_bytes", file_bytes)
    gw._SHARE_TOKEN_CACHE.clear()
    return TestClient(gw.app)


def _task(**extra) -> str:
    sid = _sid()
    asyncio.run(gw._vertex_upsert(sid, {"tenant": OWN, "status": "done", "member_id": "ana@example.com",
                                        "harness_id": "chrn_links", **extra}))
    return sid


def _addresses(sid: str, token: str = "") -> dict:
    out = {"public": f"/w/chrn_links/{sid}/workspace/{FILE}",
           "by-path": f"/a/{sid}/{FILE}",
           "content": f"/v1/containers/{sid}/files/{gw._wf_id(FILE)}/content"}
    if token:
        out["share"] = f"/share/{token}/f/{FILE}"
    return out


def _key(api, org: str) -> str:
    """An organization's own API key, minted the way the console mints one."""
    hdr = {**OWNER, "x-harness-org": org}
    r = api.post(f"/v1/orgs/{org}/keys", json={"name": "links"}, headers=hdr)
    assert r.status_code == 200, r.text
    return r.json()["key"]


def _status(api, url: str, headers: dict) -> int:
    return api.get(url, headers=headers).status_code


def test_an_unshared_task_opens_only_for_its_own_organization_signed_in(api):
    sid = _task()
    at = _addresses(sid)
    # the owner, signed in: both signed-in addresses serve the file, the public one does not
    r = api.get(at["by-path"], headers=OWNER)
    assert r.status_code == 200 and r.content == BYTES
    r = api.get(at["content"], headers=OWNER)
    assert r.status_code == 200 and r.content == BYTES
    assert FILE in r.headers["content-disposition"], "a download keeps the file's own name"
    assert _status(api, at["public"], OWNER) == 404, "the public address never reads a sign-in"
    # another organization: not found, never forbidden (a probe learns nothing)
    assert _status(api, at["by-path"], STRANGER) == 404
    assert _status(api, at["content"], STRANGER) == 404
    assert _status(api, at["public"], STRANGER) == 404
    # no credential at all: refused at the signed-in addresses, not found at the public one
    assert _status(api, at["by-path"], NOBODY) == 401
    assert _status(api, at["content"], NOBODY) == 401
    assert _status(api, at["public"], NOBODY) == 404


def test_the_api_annotations_link_opens_with_the_organizations_own_key_only(api):
    """The download_url a response's annotation carries is the content address; an API caller opens it
    with its own key, and another organization's key finds nothing there."""
    sid = _task()
    url = _addresses(sid)["content"]
    assert gw._file_url(sid, gw._wf_id(FILE)).endswith(url)
    own, other = _key(api, OWN), _key(api, OTHER)
    r = api.get(url, headers={"authorization": f"Bearer {own}"})
    assert r.status_code == 200 and r.content == BYTES
    assert _status(api, url, {"authorization": f"Bearer {other}"}) == 404
    assert _status(api, url, {"authorization": "Bearer sk-hr-" + "0" * 64}) == 401


def test_a_shared_task_opens_for_the_link_and_still_not_for_another_organization_signed_in(api):
    sid = _task()
    token = api.post(f"/v1/sessions/{sid}/share", headers=OWNER).json()["token"]
    at = _addresses(sid, token)
    # the link holder, with no account: the two public addresses serve the file
    assert _status(api, at["share"], NOBODY) == 200
    assert _status(api, at["public"], NOBODY) == 200
    # and the signed-in addresses still refuse them: a share link is not a sign-in
    assert _status(api, at["by-path"], NOBODY) == 401
    assert _status(api, at["content"], NOBODY) == 401
    # another organization reads it as anyone with the link does, and no further
    assert _status(api, at["share"], STRANGER) == 200
    assert _status(api, at["by-path"], STRANGER) == 404
    assert _status(api, at["content"], STRANGER) == 404
    # the owner reads it everywhere
    assert all(_status(api, u, OWNER) == 200 for k, u in at.items() if k != "public") and _status(api, at["public"], NOBODY) == 200
    # sharing switched off: the public addresses close at once; the owner's signed-in reads do not
    assert api.delete(f"/v1/sessions/{sid}/share", headers=OWNER).status_code == 200
    assert _status(api, at["share"], NOBODY) == 404
    assert _status(api, at["public"], NOBODY) == 404
    assert _status(api, at["by-path"], OWNER) == 200
    assert _status(api, at["content"], OWNER) == 200


def test_an_unknown_share_token_is_not_found(api):
    assert _status(api, f"/share/shr{'0' * 32}/f/{FILE}", NOBODY) == 404


def test_a_deleted_task_opens_nowhere_even_for_its_owner(api):
    """The by-path read checked the organization and stopped, so a deleted task's files went on
    opening there while the content address, which asks _owned_session, refused them."""
    sid = _task(status="deleted", shared="1", share_token="shr" + os.urandom(16).hex())
    at = _addresses(sid)
    assert _status(api, at["content"], OWNER) == 404
    assert _status(api, at["by-path"], OWNER) == 404
    assert _status(api, at["public"], NOBODY) == 404


# ── a path that is not plain names opens nothing (the security review of #594) ─────────────────────────
# The console now refuses these before it asks (its relays build a URL, and fetch() resolves '..').
# The gateway's own two by-path routes must not lean on that: the session id is only ever a key looked
# up in the graph (a missing one is a 404 before any storage is read), and the path must pass
# _ws_visible, which refuses an empty, '.', '..', dot-led or backslashed segment, before any read; a
# read then matches a whole member name, never a joined filesystem path. Pinned here, both through
# HTTP (encoded the ways a client could send them) and on the decoded values a route receives.
BAD_PATHS = ["..", "../x", "a/../../x", "./x", "a//b", "a\\b", "..\\x", "", "/", ".git/config", "x/.."]
BAD_SIDS = ["..", ".", "a\\b", "x..", ""]


@pytest.fixture()
def reads(monkeypatch):
    seen = []

    async def file_bytes(container_id, file_id):
        seen.append((container_id, file_id))
        return BYTES, "text/plain", FILE
    monkeypatch.setattr(gw, "_container_file_bytes", file_bytes)
    gw._SHARE_TOKEN_CACHE.clear()
    return seen


class _Req:
    def __init__(self, headers):
        self.headers, self.method = headers, "GET"
        self.url = type("U", (), {"path": "/a/x"})()


def _code(coro) -> int:
    try:
        asyncio.run(coro)
    except Exception as e:  # noqa: BLE001
        return getattr(e, "status_code", 500)
    return 200


def test_a_path_that_is_not_plain_names_opens_nothing_at_either_by_path_route(reads):
    sid = _task(shared="1", share_token="shr" + os.urandom(16).hex())
    for p in BAD_PATHS:
        assert _code(gw.artifact_by_path(sid, p, _Req(OWNER))) == 404, p
        assert _code(gw.workspace_by_path("chrn_links", sid, p)) == 404, p
    assert reads == [], "a refused path must not reach a storage read"
    # the plain path beside them still opens, both ways
    assert _code(gw.artifact_by_path(sid, FILE, _Req(OWNER))) == 200
    assert _code(gw.workspace_by_path("chrn_links", sid, FILE)) == 200


def test_a_session_id_that_is_not_a_plain_name_is_not_found_before_any_read(reads):
    for s in BAD_SIDS:
        assert _code(gw.artifact_by_path(s, FILE, _Req(OWNER))) == 404, s
        assert _code(gw.workspace_by_path("chrn_links", s, FILE)) == 404, s
    assert reads == []


def test_encoded_steps_up_over_http_open_nothing(api, reads):
    sid = _task(shared="1", share_token="shr" + os.urandom(16).hex())
    for tail in ["%2e%2e/%2e%2e/v1/sessions", "..%2f..%2fv1%2fsessions", "a%5cb", "%2e%2e%5cx", ".%2e/x", "x%2f..%2f..%2fy"]:
        for url in (f"/a/{sid}/{tail}", f"/w/chrn_links/{sid}/workspace/{tail}"):
            r = api.get(url, headers=OWNER)   # the client sends the path as written: nothing resolves '..'
            assert r.status_code == 404, (url, r.status_code)
    assert reads == []
