"""A memory's cover: the picture its card shows, made once by the console and kept with the instance's other files,
so a list of memories loads pictures and never works one out.

PUT takes a PNG or WebP (never SVG) of at most 512 KB and 4096 x 4096 pixels from someone who may write the memory.
The size is held while the body streams, before anything is decoded; the first bytes must say the type sent; then the
picture is decoded by the PNG and WebP decoders alone and made again, so no trailing payload, text chunk, EXIF or
colour profile survives, and only what was made again is kept. GET gives it to anyone who may read the memory (the
same check as recall), with the type kept at PUT and headers that never let it run as anything else. The key is the
organization and the memory alone. The cover goes when the memory does, at a delete and at the day-30 sweep."""
from __future__ import annotations

import asyncio
import hashlib
import io
import os
import struct
import sys
import zlib

import pytest
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app  # noqa: E402
import memory_fixture  # noqa: E402
import memory_plane  # noqa: E402

ORG, OTHER = "coverorg", "coverorg-other"
run = asyncio.run


def _pic(fmt: str, size=(12, 8), mode="RGBA", **save) -> bytes:
    im = Image.new(mode, size, (40, 90, 200, 255) if mode == "RGBA" else 1)
    if mode == "RGBA":
        im.putpixel((1, 1), (250, 10, 10, 128))
    out = io.BytesIO()
    im.save(out, format=fmt, **save)
    return out.getvalue()


PNG, WEBP = _pic("PNG"), _pic("WEBP", lossless=True)
GIF, BMP = _pic("GIF", mode="RGB"), _pic("BMP", mode="RGB")
JPEG = _pic("JPEG", mode="RGB")
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><rect width="9" height="9"/></svg>'


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


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


def _put(who, mid, data, kind="image/png", sig=None, **headers):
    h = {"content-type": kind} if kind else {}
    if sig is not None:
        h["x-cover-sig"] = sig
    return who.put(f"/v1/memories/{mid}/cover", content=data, headers={**h, **headers})


def _code(r):
    return r.json()["error"]["code"]


def _said(r):
    return r.json()["error"]["message"]


def _kept(mid):
    return run(memory_plane.COVERS.get(memory_plane.cover_key(ORG, mid)))


def _refused(r, words):
    assert r.status_code == 422 and _code(r) == "memory_invalid", r.text
    assert words in _said(r), _said(r)


# ── 1. formats ────────────────────────────────────────────────────────────────────────────────
def test_only_a_png_or_webp_is_taken_never_svg_and_a_refusal_says_why(people):
    ada, _, _ = people
    mid = _made(ada, "Formats")
    for data, kind, words in [
        (SVG, "image/svg+xml", "PNG or WebP"),
        (SVG, "image/png", "isn't a PNG"),
        (JPEG, "image/jpeg", "PNG or WebP"),
        (PNG, "", "PNG or WebP"),
        (PNG, "application/octet-stream", "PNG or WebP"),
        (WEBP, "image/png", "isn't a PNG"),
        (PNG, "image/webp", "isn't a WebP"),
        (b"", "image/png", "picture"),
    ]:
        _refused(_put(ada, mid, data, kind), words)
    for sig in ["has spaces", "x" * 65, "semi;colon"]:
        _refused(_put(ada, mid, PNG, sig=sig), "X-Cover-Sig")
    # nothing refused was kept
    assert ada.get(f"/v1/memories/{mid}/cover").status_code == 404
    assert ada.get(f"/v1/memories/{mid}").json()["cover_at"] is None and _kept(mid) is None


def test_a_png_header_over_another_body_or_another_format_renamed_is_refused(people):
    ada, _, _ = people
    mid = _made(ada, "Disguised")
    sig = b"\x89PNG\r\n\x1a\n"
    for body in (GIF, BMP):
        _refused(_put(ada, mid, sig + body), "couldn't be read as a PNG")
    for renamed in (GIF, BMP):
        _refused(_put(ada, mid, renamed, "image/png"), "isn't a PNG")
    webp_head = b"RIFF" + struct.pack("<I", 4 + len(GIF)) + b"WEBP"
    _refused(_put(ada, mid, webp_head + GIF, "image/webp"), "couldn't be read as a WebP")
    assert _kept(mid) is None


def test_what_is_kept_is_the_picture_made_again_with_nothing_else(people):
    ada, _, _ = people
    mid = _made(ada, "Made again")
    # a real PNG carrying a text chunk, EXIF, a colour profile, and a payload after its end
    im = Image.open(io.BytesIO(PNG))
    from PIL import PngImagePlugin
    info = PngImagePlugin.PngInfo()
    info.add_text("Comment", "<script>alert(1)</script>")
    exif = Image.Exif()
    exif[0x010E] = "description with a secret"
    out = io.BytesIO()
    im.save(out, format="PNG", pnginfo=info, exif=exif.tobytes(), icc_profile=b"\x00" * 128)
    dirty = out.getvalue() + b"PK\x03\x04<script>alert(2)</script>"
    assert b"tEXt" in dirty and b"eXIf" in dirty and b"iCCP" in dirty
    assert _put(ada, mid, dirty, sig="m1").status_code == 200
    kept = _kept(mid)
    assert kept and kept != dirty
    for what in (b"tEXt", b"zTXt", b"iTXt", b"eXIf", b"iCCP", b"script", b"PK\x03\x04", b"secret"):
        assert what not in kept, what
    assert kept.endswith(_chunk(b"IEND", b""))
    back = Image.open(io.BytesIO(kept))
    assert back.format == "PNG" and back.size == im.size and not {"Comment", "exif", "icc_profile"} & set(back.info)
    assert back.convert("RGBA").tobytes() == im.convert("RGBA").tobytes(), "the picture itself is unchanged"
    # a WebP's metadata goes the same way
    w = io.BytesIO()
    im.save(w, format="WEBP", lossless=True, exif=exif.tobytes(), icc_profile=b"\x00" * 128)
    assert _put(ada, mid, w.getvalue(), "image/webp").status_code == 200
    kept = _kept(mid)
    assert b"EXIF" not in kept and b"ICCP" not in kept and b"secret" not in kept
    assert Image.open(io.BytesIO(kept)).format == "WEBP"


# ── 3. caps ───────────────────────────────────────────────────────────────────────────────────
def test_the_size_cap_holds_while_the_upload_streams_before_anything_is_decoded(people, monkeypatch):
    ada, _, _ = people
    mid = _made(ada, "Too big")
    decoded = []
    real = memory_plane.cover_clean
    monkeypatch.setattr(memory_plane, "cover_clean", lambda data, kind: decoded.append(len(data)) or real(data, kind))
    _refused(_put(ada, mid, PNG + b"\x00" * (512 * 1024)), "512 KB")

    def body():
        # sent in pieces, with no length said
        for _ in range(16):
            yield PNG[:8] + b"\x00" * (64 * 1024 - 8)
    _refused(_put(ada, mid, body()), "512 KB")
    assert decoded == [], "nothing that big is ever decoded"
    assert _kept(mid) is None
    # 512 KB itself is taken
    assert _put(ada, mid, PNG + b"\x00" * (512 * 1024 - len(PNG))).status_code == 200


def test_the_body_is_read_no_further_than_one_byte_past_the_cap():
    import memory_routes
    pulled = []

    class Req:
        def __init__(self, length=""):
            self.headers = {"content-length": length} if length else {}

        async def stream(self):
            for _ in range(64):                      # 4 MB, if it were all read
                pulled.append(64 * 1024)
                yield b"\x00" * (64 * 1024)
    with pytest.raises(Exception) as e:
        run(memory_routes._cover_bytes(Req()))
    assert getattr(e.value, "status_code", None) == 422
    assert sum(pulled) <= 512 * 1024 + 64 * 1024, f"{sum(pulled)} bytes read"
    # a length that says it is too big: nothing is read at all
    pulled.clear()
    with pytest.raises(Exception):
        run(memory_routes._cover_bytes(Req(str(512 * 1024 + 1))))
    assert pulled == []


def test_a_picture_of_too_many_pixels_is_refused_before_its_pixels_are_read(people, monkeypatch):
    ada, _, _ = people
    mid = _made(ada, "Bomb")
    big = _pic("PNG", size=(5000, 5000), mode="1", optimize=True)
    wide = _pic("PNG", size=(4097, 1), mode="1")
    assert len(big) < 512 * 1024
    from PIL import ImageFile
    loaded = []
    real_load = ImageFile.ImageFile.load
    monkeypatch.setattr(ImageFile.ImageFile, "load", lambda self: loaded.append(self.size) or real_load(self))
    _refused(_put(ada, mid, big), "4096")
    assert (5000, 5000) not in loaded, "its pixels were never read"
    _refused(_put(ada, mid, wide), "4096")
    assert loaded == [], "no pixel of either was read"
    assert Image.MAX_IMAGE_PIXELS == 4096 * 4096
    assert _put(ada, mid, _pic("PNG", size=(4096, 4), mode="1")).status_code == 200


# ── 2. serving ────────────────────────────────────────────────────────────────────────────────
def test_the_picture_is_served_with_its_kept_type_and_headers_that_never_run_it(people):
    ada, _, _ = people
    mid = _made(ada, "Served")
    r = ada.get(f"/v1/memories/{mid}/cover")
    assert r.status_code == 404 and _code(r) == "memory_not_found"
    put = _put(ada, mid, PNG, sig="s1").json()
    assert put["object"] == "memory.cover" and put["memory_id"] == mid and put["cover_sig"] == "s1"
    assert isinstance(put["cover_at"], int) and put["cover_at"] > 0
    # what the reader asks for has no say in what it is served as
    r = ada.get(f"/v1/memories/{mid}/cover", params={"v": put["cover_at"]},
                headers={"accept": "text/html", "content-type": "text/html"})
    assert r.status_code == 200 and r.content == _kept(mid)
    assert r.headers["content-type"] == "image/png"
    assert r.headers["content-disposition"] == 'inline; filename="cover.png"'
    assert r.headers["content-security-policy"] == "default-src 'none'"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "private, max-age=31536000, immutable"
    m = ada.get(f"/v1/memories/{mid}").json()
    assert (m["cover_at"], m["cover_sig"]) == (put["cover_at"], "s1")
    again = _put(ada, mid, WEBP, kind="image/webp; charset=binary").json()
    assert again["cover_at"] >= put["cover_at"] and again["cover_sig"] is None
    r = ada.get(f"/v1/memories/{mid}/cover", params={"v": again["cover_at"]})
    assert r.headers["content-type"] == "image/webp" and r.headers["content-disposition"] == 'inline; filename="cover.webp"'
    assert Image.open(io.BytesIO(r.content)).format == "WEBP"


# ── 4. access ─────────────────────────────────────────────────────────────────────────────────
def test_only_someone_who_may_write_sets_it_and_only_a_reader_sees_it(people):
    ada, ben, carl = people
    mid = _made(ada)
    # holding nothing on it: not found, set or read
    for who in (ben, carl):
        r = _put(who, mid, PNG)
        assert r.status_code == 404 and _code(r) == "memory_not_found"
    ada.post(f"/v1/memories/{mid}/grants", json={"principal": "member:ben@example.com", "privileges": ["read"]})
    r = _put(ben, mid, PNG)
    assert r.status_code == 403 and _code(r) == "memory_forbidden"
    assert _put(ada, mid, PNG, sig="a1b2c3").status_code == 200
    # read, as for recall, is enough to see it; another organization never learns it is there
    assert ben.get(f"/v1/memories/{mid}/cover").status_code == 200
    r = carl.get(f"/v1/memories/{mid}/cover")
    assert r.status_code == 404 and _code(r) == "memory_not_found"
    # a restricted memory below (one person's own) stays its own: a reader of the one above doesn't see its cover
    own = _made(ada, "Kim's own", parent_id=mid, restricted=True)
    assert _put(ada, own, PNG).status_code == 200
    assert ben.post(f"/v1/memories/{own}/recall", json={"query": "x"}).status_code == 404
    r = ben.get(f"/v1/memories/{own}/cover")
    assert r.status_code == 404 and _code(r) == "memory_not_found"
    assert ada.get(f"/v1/memories/{own}/cover").status_code == 200


def test_the_key_is_the_organization_and_the_memory_alone(people):
    ada, _, _ = people
    mid = _made(ada, "Keyed")
    key = memory_plane.cover_key(ORG, mid)
    assert key == f"memory-covers/{hashlib.sha256(ORG.encode()).hexdigest()[:32]}/{mid}"
    assert memory_plane.cover_key(OTHER, mid) != key
    # nothing the client sends moves it
    r = _put(ada, mid, PNG, sig="k", **{"content-disposition": 'attachment; filename="../../x"', "x-cover-key": "../x",
                                        "x-harness-workspace": "elsewhere"})
    assert r.status_code == 200
    assert _kept(mid) is not None
    root = os.path.join(os.environ["HR_DATA_DIR"])
    found = [os.path.relpath(os.path.join(d, f), root) for d, _, fs in os.walk(root) for f in fs if mid in f]
    assert found and all(p.endswith(key) for p in found), found


def test_the_list_says_when_each_cover_was_made_and_which_drawing_it_shows(people):
    ada, _, _ = people
    a, b = _made(ada, "Listed with a cover"), _made(ada, "Listed without")
    put = _put(ada, a, PNG, sig="k9").json()
    for counts in ("false", "true"):
        rows = {x["id"]: x for x in ada.get("/v1/memories", params={"counts": counts}).json()["data"]}
        assert (rows[a]["cover_at"], rows[a]["cover_sig"]) == (put["cover_at"], "k9")
        assert (rows[b]["cover_at"], rows[b]["cover_sig"]) == (None, None)


# ── 5. deletion ───────────────────────────────────────────────────────────────────────────────
def test_the_cover_goes_with_the_memory_and_with_every_memory_below_it(people):
    ada, _, _ = people
    top = _made(ada, "Going")
    kid = _made(ada, "Going too", parent_id=top)
    assert _put(ada, top, PNG).status_code == 200 and _put(ada, kid, WEBP, kind="image/webp").status_code == 200
    assert _kept(top) and _kept(kid)
    assert sorted(ada.delete(f"/v1/memories/{top}").json()["memories"]) == sorted([top, kid])
    assert _kept(top) is None and _kept(kid) is None
    assert ada.get(f"/v1/memories/{top}/cover").status_code == 404
