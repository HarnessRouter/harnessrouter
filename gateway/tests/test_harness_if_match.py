"""An update built from a read does not overwrite a change made in between (Harnesses §5.2).

PUT /v1/harnesses/{hid} replaces the whole configuration. A caller that builds its body from a read,
such as an app applying the copy of the harness it keeps in its repo, silently overwrote whatever
changed between its read and its write: an edit made in the console, another step's plugin. A read
now answers the harness's version as an ETag, and an update may send it back as If-Match: one that no
longer matches is refused 412 `precondition_failed` and nothing is written. An update without
If-Match replaces as it always has. The same holds on the organization's own routes.
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as gw  # noqa: E402  (environment: conftest.py)

ORG = "org.ifmatch"
ME = {"x-harness-internal": "test-internal-key", "x-harness-org": ORG, "x-harness-member": "ada@example.com"}
OTHER = {**ME, "x-harness-org": "org.ifmatch.other"}
CHANGED = "This harness changed since you read it. Read it again and retry."


@pytest.fixture(scope="module")
def client():
    with TestClient(gw.app) as c:
        yield c


def _made(client, path="", tagged=True):
    """A new harness, read back: (its body as read, the ETag the read answered, the item route). `tagged`
    False for the tests that hold what was true before ETags, so they also pass on a server without them."""
    r = client.post("/v1/harnesses", headers=ME, json={"name": "story", "base": "hermes", "system_prompt": "v1"})
    assert r.status_code == 200, r.text
    url = (f"/v1/orgs/{ORG}/harnesses/" if path == "org" else "/v1/harnesses/") + r.json()["id"]
    got = client.get(url, headers=ME)
    assert got.status_code == 200, got.text
    tag = got.headers.get("etag")
    if tagged:
        assert tag and tag.startswith('"') and tag.endswith('"'), got.headers   # strong, quoted
    return got.json(), tag or '"0"', url


def _stored(hid):
    return asyncio.run(gw._vertex_get(hid))


@pytest.mark.parametrize("path", ["public", "org"])
def test_an_update_sending_the_etag_it_read_saves_and_answers_the_new_one(client, path):
    h, tag, url = _made(client, path)
    r = client.put(url, headers={**ME, "If-Match": tag}, json={**h, "systemPrompt": "v2"})
    assert r.status_code == 200, r.text
    assert r.json()["systemPrompt"] == "v2"
    new = r.headers.get("etag")
    assert new and new != tag
    assert client.get(url, headers=ME).headers["etag"] == new


@pytest.mark.parametrize("path", ["public", "org"])
def test_an_update_after_a_change_since_its_read_is_refused_and_writes_nothing(client, path):
    h, tag, url = _made(client, path)
    # someone else changes it in between: a person's edit, saved without a precondition
    assert client.put(url, headers=ME, json={**h, "systemPrompt": "their edit"}).status_code == 200
    r = client.put(url, headers={**ME, "If-Match": tag}, json={**h, "systemPrompt": "v2", "name": "renamed"})
    assert r.status_code == 412, r.text
    assert r.json()["error"] == {"type": "invalid_request_error", "code": "precondition_failed",
                                 "message": CHANGED, "param": "If-Match", "detail": None}
    kept = _stored(h["id"])
    assert kept["system_prompt"] == "their edit" and kept["name"] == "story"


@pytest.mark.parametrize("path", ["public", "org"])
def test_an_update_without_if_match_replaces_as_before(client, path):
    h, _, url = _made(client, path, tagged=False)
    assert client.put(url, headers=ME, json={**h, "systemPrompt": "their edit"}).status_code == 200
    r = client.put(url, headers=ME, json={**h, "systemPrompt": "v2"})
    assert r.status_code == 200, r.text
    assert r.json()["systemPrompt"] == "v2" and _stored(h["id"])["system_prompt"] == "v2"


def test_any_tag_a_list_and_a_weakened_tag_match(client):
    h, tag, url = _made(client)
    r = client.put(url, headers={**ME, "If-Match": "*"}, json={**h, "systemPrompt": "v2"})
    assert r.status_code == 200, r.text
    tag = r.headers["etag"]
    r = client.put(url, headers={**ME, "If-Match": f'"stale", {tag}'}, json={**h, "systemPrompt": "v3"})
    assert r.status_code == 200, r.text
    tag = r.headers["etag"]
    # a proxy that compresses an answer may pass the ETag on weakened; the caller holds only that form
    r = client.put(url, headers={**ME, "If-Match": "W/" + tag}, json={**h, "systemPrompt": "v4"})
    assert r.status_code == 200, r.text
    assert client.put(url, headers={**ME, "If-Match": '"0"'}, json={**h, "systemPrompt": "v5"}).status_code == 412


def test_a_change_from_any_route_moves_the_version_and_a_write_an_update_leaves_alone_does_not(client):
    h, tag, url = _made(client)
    hid = h["id"]
    # what an update never writes: a read of the configuration is not stale about it
    asyncio.run(gw._vg_upsert("Harness", hid, {"kit": "sheets", "live_at": "1", "updated_at": "2"}))
    assert client.get(url, headers=ME).headers["etag"] == tag
    # what an update replaces, written by another route (a plugin publish, a kit's launch)
    asyncio.run(gw._vg_upsert("Harness", hid, {"plugins": '[{"name": "another step"}]'}))
    assert client.get(url, headers=ME).headers["etag"] != tag
    r = client.put(url, headers={**ME, "If-Match": tag}, json={**h, "systemPrompt": "v2"})
    assert r.status_code == 412 and _stored(hid)["system_prompt"] == "v1"


def test_the_precondition_is_judged_before_the_body(client):
    """A stale read is the thing to fix first: the caller's body was built from it."""
    h, tag, url = _made(client)
    assert client.put(url, headers=ME, json={**h, "systemPrompt": "their edit"}).status_code == 200
    r = client.put(url, headers={**ME, "If-Match": tag}, json={**h, "base": "codex"})
    assert r.status_code == 412, r.text


@pytest.mark.parametrize("path", ["public", "org"])
def test_another_organizations_harness_is_still_not_found(client, path):
    h, tag, url = _made(client, path, tagged=False)
    other = url.replace(f"/orgs/{ORG}/", "/orgs/org.ifmatch.other/")
    assert client.get(other, headers=OTHER).status_code == 404
    r = client.put(other, headers={**OTHER, "If-Match": tag}, json={**h, "systemPrompt": "x"})
    assert r.status_code == 404, r.text
    assert _stored(h["id"])["system_prompt"] == "v1"


def test_the_version_covers_every_field_an_update_writes():
    body = gw.HarnessBody(name="n", base="hermes", base_label="l", default_model="", system_prompt="s",
                          mcp_servers=[], skills=[], plugins=[], disabled_tools=[], additional_headers=["X-A"],
                          env={}, calibrates="", environment="", max_step=3, timeout_seconds=9,
                          reasoning_effort="")
    assert set(gw._harness_props(body)) == set(gw._HARNESS_VERSIONED)


def test_a_412_is_the_callers_to_fix_never_a_server_error():
    """The error type says whether retrying unchanged can work (Errors §2): a stale read cannot."""
    e = gw.uhp_error(412, "precondition_failed", CHANGED, "If-Match")
    assert e.status_code == 412 and e.detail["type"] == "invalid_request_error"
