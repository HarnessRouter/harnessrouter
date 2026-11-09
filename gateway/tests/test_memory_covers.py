"""A memory's cover: the picture its card shows, made once by the console and kept with the instance's other files,
so a list of memories loads pictures and never works one out. PUT takes the bytes of a PNG or WebP of at most 512 KB
from someone who may write the memory; GET gives them to anyone who may read it, with a cache that never asks again
(the console names the version in the address). The memory says when its cover was made and which drawing it shows,
and the cover goes when the memory does."""
from __future__ import annotations

import os
import struct
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app  # noqa: E402
import memory_fixture  # noqa: E402
import memory_plane  # noqa: E402

ORG, OTHER = "coverorg", "coverorg-other"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x01" * 200
WEBP = b"RIFF" + struct.pack("<I", 4 + 200) + b"WEBP" + b"VP8 " + b"\x02" * 196
JPEG = b"\xff\xd8\xff\xe0" + b"\x03" * 200


class Who:
    def __init__(self, c, member, org=ORG):
        self.c, self.h = c, {"x-harness-internal": "test-internal-key", "x-harness-org": org, "x-harness-member": member}

    def __getattr__(self, m):
        def call(path, **kw):
            kw["headers"] = {**self.h, **(kw.get("headers") or {})}
            return getattr(self.c, m)(path, **kw)
        return call


@pytest.fixture(scope="module")
def people():
    memory_plane.PROVIDERS["fixture"] = memory_fixture.FixtureProvider()
    with TestClient(app.app) as c:
        yield Who(c, "ada@example.com"), Who(c, "ben@example.com"), Who(c, "carl@example.com", OTHER)


def _made(ada, name="Accounts", **b) -> str:
    r = ada.post("/v1/memories", json={"provider": "fixture", "name": name, **b})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _put(who, mid, data, kind="image/png", sig=None):
    h = {"content-type": kind} if kind else {}
    if sig is not None:
        h["x-cover-sig"] = sig
    return who.put(f"/v1/memories/{mid}/cover", content=data, headers=h)


def _code(r):
    return r.json()["error"]["code"]


def _said(r):
    return r.json()["error"]["message"]


def test_only_someone_who_may_write_sets_it_and_another_organization_never_finds_it(people):
    ada, ben, carl = people
    mid = _made(ada)
    ada.post(f"/v1/memories/{mid}/grants", json={"principal": "member:ben@example.com", "privileges": ["read"]})
    r = _put(ben, mid, PNG)
    assert r.status_code == 403 and _code(r) == "memory_forbidden"
    r = _put(carl, mid, PNG)
    assert r.status_code == 404 and _code(r) == "memory_not_found"
    assert _put(ada, mid, PNG, sig="a1b2c3").status_code == 200
    # read is enough to see it, and nothing outside the organization learns it is there
    assert ben.get(f"/v1/memories/{mid}/cover").content == PNG
    r = carl.get(f"/v1/memories/{mid}/cover")
    assert r.status_code == 404 and _code(r) == "memory_not_found"


def test_only_a_png_or_webp_picture_of_at_most_512_kb_is_taken_and_a_refusal_says_why(people):
    ada, _, _ = people
    mid = _made(ada, "Refusals")
    for data, kind, words in [
        (JPEG, "image/jpeg", "PNG or WebP"),
        (PNG, "", "PNG or WebP"),
        (PNG, "application/octet-stream", "PNG or WebP"),
        (WEBP, "image/png", "isn't a PNG"),
        (PNG, "image/webp", "isn't a WebP"),
        (b"", "image/png", "picture"),
        (PNG + b"\x00" * (512 * 1024), "image/png", "512 KB"),
    ]:
        r = _put(ada, mid, data, kind)
        assert r.status_code == 422 and _code(r) == "memory_invalid", (kind, r.text)
        assert words in _said(r), (kind, _said(r))
    for sig in ["has spaces", "x" * 65, "semi;colon"]:
        r = _put(ada, mid, PNG, sig=sig)
        assert r.status_code == 422 and _code(r) == "memory_invalid", sig
    # nothing refused was kept
    assert ada.get(f"/v1/memories/{mid}/cover").status_code == 404
    assert ada.get(f"/v1/memories/{mid}").json()["cover_at"] is None


def test_the_picture_comes_back_as_it_went_with_its_type_and_a_cache_that_never_asks_again(people):
    ada, _, _ = people
    mid = _made(ada, "Round trip")
    r = ada.get(f"/v1/memories/{mid}/cover")
    assert r.status_code == 404 and _code(r) == "memory_not_found"
    r = _put(ada, mid, PNG, sig="s1")
    assert r.status_code == 200, r.text
    put = r.json()
    assert put["object"] == "memory.cover" and put["memory_id"] == mid and put["cover_sig"] == "s1"
    assert isinstance(put["cover_at"], int) and put["cover_at"] > 0
    r = ada.get(f"/v1/memories/{mid}/cover", params={"v": put["cover_at"]})
    assert r.status_code == 200 and r.content == PNG
    assert r.headers["content-type"] == "image/png"
    assert r.headers["cache-control"] == "private, max-age=31536000, immutable"
    assert r.headers["x-content-type-options"] == "nosniff"
    m = ada.get(f"/v1/memories/{mid}").json()
    assert (m["cover_at"], m["cover_sig"]) == (put["cover_at"], "s1")
    # a new picture replaces it; WebP is taken as well, and a picture sent with no drawing named has none
    again = _put(ada, mid, WEBP, kind="image/webp; charset=binary").json()
    assert again["cover_at"] >= put["cover_at"] and again["cover_sig"] is None
    r = ada.get(f"/v1/memories/{mid}/cover", params={"v": again["cover_at"]})
    assert r.content == WEBP and r.headers["content-type"] == "image/webp"


def test_the_list_says_when_each_cover_was_made_and_which_drawing_it_shows(people):
    ada, _, _ = people
    a, b = _made(ada, "Listed with a cover"), _made(ada, "Listed without")
    put = _put(ada, a, PNG, sig="k9").json()
    for counts in ("false", "true"):
        rows = {x["id"]: x for x in ada.get("/v1/memories", params={"counts": counts}).json()["data"]}
        assert (rows[a]["cover_at"], rows[a]["cover_sig"]) == (put["cover_at"], "k9")
        assert (rows[b]["cover_at"], rows[b]["cover_sig"]) == (None, None)


def test_the_cover_goes_with_the_memory_and_with_every_memory_below_it(people):
    ada, _, _ = people
    top = _made(ada, "Going")
    kid = _made(ada, "Going too", parent_id=top)
    assert _put(ada, top, PNG).status_code == 200 and _put(ada, kid, WEBP, kind="image/webp").status_code == 200
    assert memory_plane.cover_key(ORG, top) != memory_plane.cover_key(ORG, kid)

    async def kept(mid):
        return await memory_plane.COVERS.get(memory_plane.cover_key(ORG, mid))
    import asyncio
    assert asyncio.run(kept(top)) == PNG and asyncio.run(kept(kid)) == WEBP
    assert sorted(ada.delete(f"/v1/memories/{top}").json()["memories"]) == sorted([top, kid])
    assert asyncio.run(kept(top)) is None and asyncio.run(kept(kid)) is None
    assert ada.get(f"/v1/memories/{top}/cover").status_code == 404
