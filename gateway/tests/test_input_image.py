"""An input_image reaches the agent.

A client sent screenshots as `input_image`, the OpenAI Responses shape and one the protocol says a server
at Extended accepts (Tasks §2, "An image, inline or by file_id"). The gateway kept the part in the turn's
record and nowhere else: nothing was written to the agent's working directory, the request answered 200,
and the agent said no screenshot was attached. Sent as `input_file`, the same image was read.

Now an input_image is a file in the working directory, as an input_file is: inline as a data URL (a
string, or {"url": ...} as Chat Completions spells it), or by file_id from POST /v1/files. A URL is not
fetched, and a part that can't be read is refused by name, never dropped."""
from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import app as gw  # noqa: E402
from test_input_history import PNG, _post, _setup, env  # noqa: E402,F401  (env is the fixture)

PNG_B64 = PNG.split(",", 1)[1]


def _image(url=PNG, **extra) -> list:
    return [{"role": "user", "content": [{"type": "input_text", "text": "What is in this screenshot?"},
                                         {"type": "input_image", "image_url": url, **extra}]}]


# ── the parse ────────────────────────────────────────────────────────────────────────────────────
def test_an_inline_image_is_a_file_named_from_its_bytes_and_the_record_keeps_the_name_only():
    prompt, files, items = gw._parse_input(_image())
    assert prompt == "What is in this screenshot?"
    [f] = files
    assert f["content_b64"] == PNG_B64 and f["media_type"] == "image/png" and f["file_id"] is None
    assert f["filename"].startswith("image-") and f["filename"].endswith(".png")
    # the same picture is the same name, so one image under two turns is one file
    assert gw._parse_input(_image())[1][0]["filename"] == f["filename"]
    part = items[0]["content"][1]
    assert part == {"type": "input_image", "filename": f["filename"], "file_id": None}
    assert PNG_B64 not in str(items)                       # no bytes in the turn's record


def test_the_chat_completions_spelling_a_jpeg_and_a_named_part_are_read():
    jpg = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQ=="
    assert gw._parse_input(_image({"url": jpg, "detail": "high"}))[1][0]["filename"].endswith(".jpg")
    assert gw._parse_input(_image(filename="lap-3.png"))[1][0]["filename"] == "lap-3.png"


def test_an_image_by_file_id_is_resolved_like_an_input_file():
    _, files, items = gw._parse_input([{"role": "user", "content": [{"type": "input_image", "file_id": "file_abc"}]}])
    assert files == [{"filename": None, "content_b64": None, "file_id": "file_abc", "media_type": None}]
    assert items[0]["content"] == [{"type": "input_image", "filename": None, "file_id": "file_abc"}]


@pytest.mark.parametrize("url,words", [
    ("https://example.com/shot.png", "an image URL is not fetched"),
    ("http://169.254.169.254/latest/meta-data", "an image URL is not fetched"),
    ("data:text/plain;base64,aGk=", "base64 image"),
    ("data:image/png,rawbytes", "base64 image"),
    ("data:image/png;base64,", "base64 image"),
])
def test_a_url_or_a_part_that_is_not_a_base64_image_is_refused_by_name(url, words):
    with pytest.raises(gw.HTTPException) as e:
        gw._parse_input(_image(url))
    assert e.value.status_code == 400 and words in str(e.value.detail)


def test_a_payload_that_is_not_base64_is_refused_here_not_skipped_by_the_runner():
    # The runner skips a file whose bytes do not decode, while the prompt still says it was attached.
    for bad in ("data:image/png;base64,@@not*base64@@", "data:image/png;base64,iVBORw0KGgo=====x"):
        with pytest.raises(gw.HTTPException) as e:
            gw._parse_input(_image(bad))
        assert e.value.status_code == 400 and "base64 image" in str(e.value.detail)


def test_a_payload_wrapped_over_lines_is_the_same_image():
    wrapped = "data:image/png;base64," + "\n".join(PNG_B64[i:i + 16] for i in range(0, len(PNG_B64), 16))
    [f] = gw._parse_input(_image(wrapped))[1]
    assert f["content_b64"] == PNG_B64
    assert f["filename"] == gw._parse_input(_image())[1][0]["filename"]


@pytest.mark.parametrize("name", [5, {"x": 1}, ["a.png"], "", "   "])
def test_a_filename_that_is_not_a_name_is_no_name(name):
    [f] = gw._parse_input(_image(filename=name))[1]
    assert f["filename"].startswith("image-") and f["filename"].endswith(".png")
    [f] = gw._parse_input([{"role": "user", "content": [{"type": "input_image", "file_id": "file_abc",
                                                         "filename": name}]}])[1]
    assert f["filename"] is None                           # the upload's own name is used at resolution


def _file(**part) -> list:
    return [{"role": "user", "content": [{"type": "input_text", "text": "Read this."}, {"type": "input_file", **part}]}]


@pytest.mark.parametrize("part,words", [
    ({"file_data": PNG}, "carries a filename"),                              # it was dropped in silence
    ({"file_data": PNG, "filename": 7}, "carries a filename"),
    ({"file_data": "data:text/plain;base64,@@not base64@@", "filename": "a.txt"}, "is base64"),
    ({"file_data": "data:text/plain,hello", "filename": "a.txt"}, "is base64"),
    ({"filename": "a.txt"}, "file_data (inline) or file_id"),
])
def test_an_input_file_that_cannot_reach_the_agent_is_refused_by_name(part, words):
    with pytest.raises(gw.HTTPException) as e:
        gw._parse_input(_file(**part))
    assert e.value.status_code == 400 and words in str(e.value.detail)


def test_an_empty_input_file_is_kept_as_before_not_refused():
    # the console sends "data:<type>;base64," for a zero-byte attachment; a 400 would fail the whole turn
    [f] = gw._parse_input(_file(filename="empty.txt", file_data="data:text/plain;base64,"))[1]
    assert f["filename"] == "empty.txt" and f["content_b64"] == ""


def test_an_input_file_reads_as_before():
    [f] = gw._parse_input(_file(filename="q3.txt", file_data="data:text/plain;base64,aGVsbG8=\n"))[1]
    assert f == {"filename": "q3.txt", "content_b64": "aGVsbG8=", "file_id": None, "media_type": "text/plain"}
    [f] = gw._parse_input(_file(file_id="file_abc"))[1]
    assert f == {"filename": None, "content_b64": None, "file_id": "file_abc", "media_type": None}


def test_an_image_part_with_nothing_in_it_is_refused():
    with pytest.raises(gw.HTTPException) as e:
        gw._parse_input([{"role": "user", "content": [{"type": "input_image"}]}])
    assert e.value.status_code == 400 and "image_url" in str(e.value.detail)


# ── through the app ──────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def seen(env, monkeypatch):
    """The files the turn's execution is handed, bytes and all."""
    got: list[list[dict]] = []
    inner = gw._resp_execute

    async def execute(tr, **kw):
        got.append([dict(f) for f in kw["files_in"]])
        return await inner(tr, **kw)
    monkeypatch.setattr(gw, "_resp_execute", execute)
    return got


def test_a_screenshot_sent_as_input_image_is_in_the_agents_working_directory(env, seen):
    hid = _setup(env)
    r = _post(env, hid, _image())
    assert r.status_code == 200, r.text
    [[f]] = seen
    assert base64.b64decode(f["content_b64"]) == base64.b64decode(PNG_B64)
    ran = env["turns"].ran[0]
    assert ran["prompt"].startswith(f"[Attached files saved in your working directory: {f['filename']}]")
    assert ran["user_text"] == "What is in this screenshot?"


def test_an_image_alone_is_a_turn(env, seen):
    hid = _setup(env)
    r = _post(env, hid, [{"role": "user", "content": [{"type": "input_image", "image_url": PNG}]}])
    assert r.status_code == 200, r.text
    assert len(seen[0]) == 1


def test_an_image_url_answers_400_and_nothing_runs(env, seen):
    hid = _setup(env)
    r = _post(env, hid, _image("https://example.com/shot.png"))
    assert r.status_code == 400, r.text
    assert "not fetched" in r.text
    assert seen == [] and env["turns"].ran == []


def test_an_uploaded_image_by_file_id_reaches_the_agent_under_its_uploaded_name(env, seen):
    hid = _setup(env)
    org = env["who"]["p"]["org"]
    fid = "file_" + "a1" * 12                              # an upload of this organization's, as POST /v1/files leaves it
    asyncio.run(gw._blob_put(f"uploads/{fid}", base64.b64decode(PNG_B64), kb=gw.RESP_BLOB_KB))
    asyncio.run(gw._blob_put(f"uploads/{fid}.meta", json.dumps({"org": org, "filename": "lap-3.png"}).encode(), kb=gw.RESP_BLOB_KB))
    r = _post(env, hid, [{"role": "user", "content": [{"type": "input_text", "text": "Read it."},
                                                      {"type": "input_image", "file_id": fid}]}])
    assert r.status_code == 200, r.text
    [[f]] = seen
    assert f["filename"] == "lap-3.png"
    assert base64.b64decode(f["content_b64"]) == base64.b64decode(PNG_B64)


def test_another_organizations_upload_by_file_id_is_404_as_for_an_input_file(env, seen):
    hid = _setup(env)
    fid = "file_" + "b2" * 12
    asyncio.run(gw._blob_put(f"uploads/{fid}", base64.b64decode(PNG_B64), kb=gw.RESP_BLOB_KB))
    asyncio.run(gw._blob_put(f"uploads/{fid}.meta", json.dumps({"org": "org.someone-else"}).encode(), kb=gw.RESP_BLOB_KB))
    r = _post(env, hid, [{"role": "user", "content": [{"type": "input_image", "file_id": fid}]}])
    assert r.status_code == 404, r.text
    assert seen == []
