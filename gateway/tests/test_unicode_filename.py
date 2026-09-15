"""A filename the header cannot spell must not cost the download (issue #187).

A response header is bytes: ASGI defines them as latin-1, so a name carrying a Chinese character
or an emoji cannot go into the quoted `filename` at all. It raised UnicodeEncodeError inside the
server, and the caller saw a 500 with nothing in it to explain why an ASCII name had worked a
moment earlier. Every route that names a file now builds the header the same way, through
`_content_disposition`: an ASCII fallback any client can read, plus RFC 6266 `filename*` carrying
the real name. These tests hold each route to that, and hold the builder to producing something a
header can actually carry, whatever it is handed.
"""
import pytest
from fastapi.testclient import TestClient

import app as gw

UNICODE_NAMES = ["notes.txt", "报告.txt", "plan-🚀.txt", "отчёт.md", "ملف.txt"]


async def _async_value(v):
    return v


def _client() -> TestClient:
    return TestClient(gw.app, raise_server_exceptions=False)


def _parts(header: str) -> tuple[str, str]:
    """(the quoted fallback, the percent-encoded filename*) of a Content-Disposition."""
    fallback = header.split('filename="', 1)[1].split('"', 1)[0]
    star = header.split("filename*=UTF-8''", 1)[1]
    return fallback, star


# ── the routes ────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("filename", UNICODE_NAMES)
def test_a_download_carries_any_filename(monkeypatch, filename):
    monkeypatch.setattr(gw, "_owned_session", lambda request, sid: _async_value(None))
    monkeypatch.setattr(gw, "_container_file_bytes",
                        lambda cid, fid: _async_value((b"example", "text/plain", filename)))
    r = _client().get("/v1/containers/s1/files/wf_x/content")
    assert r.status_code == 200 and r.content == b"example"
    cd = r.headers["content-disposition"]
    fallback, star = _parts(cd)
    assert cd.startswith("attachment; ")
    assert star == gw.urllib.parse.quote(filename, safe=""), "the real name rides in filename*"
    assert fallback.isascii() and fallback, "the fallback is spellable in a header"


@pytest.mark.parametrize("filename", UNICODE_NAMES)
def test_a_preview_carries_any_filename(monkeypatch, filename):
    monkeypatch.setattr(gw, "_session_shared", lambda sid: _async_value(True))
    monkeypatch.setattr(gw, "_container_file_bytes",
                        lambda sid, fid: _async_value((b"hello", "text/plain", filename)))
    r = _client().get(f"/w/h1/s1/workspace/{filename}")
    assert r.status_code == 200 and r.content == b"hello"
    cd = r.headers["content-disposition"]
    assert cd.startswith("inline; ") and _parts(cd)[1] == gw.urllib.parse.quote(filename, safe="")


def test_an_archive_names_itself_the_same_way(monkeypatch, tmp_path):
    monkeypatch.setattr(gw, "_owned_session", lambda request, sid: _async_value(None))
    monkeypatch.setattr(gw, "_reap_spool_dir", lambda: None)
    monkeypatch.setattr(gw, "_WS_TAR_DIR", str(tmp_path))
    monkeypatch.setattr(gw, "_container_file_bytes",
                        lambda sid, fid: _async_value((b"x", "text/plain", "报告.txt")))
    r = _client().get(f"/v1/sessions/s1/files/archive?files={gw._wf_id('报告.txt')}")
    assert r.status_code == 200
    cd = r.headers["content-disposition"]
    assert cd.startswith('attachment; filename="s1-turn-files.zip"') and "filename*=UTF-8''" in cd


# ── the builder ───────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", UNICODE_NAMES + [
    "deep/folder/notes.txt", "back\\slash\\x.bin", 'we"ird\\name.txt', "", ".", "..",
    "日本語", "a" * 300 + ".txt", "line\nbreak.txt", "tab\there.txt", "\x7f.bin",
])
def test_every_header_it_builds_is_one_a_header_can_carry(name):
    for kind in ("attachment", "inline"):
        value = gw._content_disposition(kind, name)
        value.encode("latin-1")            # what used to raise, which is the whole bug
        assert value.startswith(f"{kind}; filename=")
        fallback, star = _parts(value)
        assert fallback.isascii() and fallback.strip(" .") != ""
        assert '"' not in fallback and "\\" not in fallback
        assert not any(ord(c) < 32 or ord(c) == 127 for c in value)
        assert len(fallback) <= 120


def test_the_name_is_a_basename_and_never_empty():
    assert _parts(gw._content_disposition("attachment", "deep/folder/notes.txt")) == ("notes.txt", "notes.txt")
    assert _parts(gw._content_disposition("attachment", "back\\slash\\x.bin")) == ("x.bin", "x.bin")
    for empty in ("", "   ", ".", ".."):
        assert _parts(gw._content_disposition("attachment", empty)) == ("download", "download")


def test_an_ascii_name_is_unchanged_in_both_halves():
    assert (gw._content_disposition("attachment", "notes.txt")
            == 'attachment; filename="notes.txt"; filename*=UTF-8\'\'notes.txt')


def test_the_fallback_keeps_the_extension_so_a_save_stays_openable():
    fallback, _ = _parts(gw._content_disposition("attachment", "报告.txt"))
    assert fallback.endswith(".txt") and fallback == "__.txt"
    fallback, _ = _parts(gw._content_disposition("attachment", "plan-🚀.txt"))
    assert fallback == "plan-_.txt", "one placeholder per character, astral or not"
