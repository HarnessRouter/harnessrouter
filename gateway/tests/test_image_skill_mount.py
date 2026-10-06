"""The built-in image skill does not stand in front of an image tool that works.

It works through the turn's image credential alone; without one its script refuses, and an agent took
the refusal as final although its harness had the media tools (found on the hosted service,
2026-10-06). Here the skill is dropped only where the turn carries the media tools: with no other
way to make an image, its refusal is what tells a self-hosting operator what to add.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402
import pytest  # noqa: E402

BUILTIN = {"name": "imagegen", "files": [{"path": "SKILL.md", "content": "x"}], "content": None}
DOCX = {"name": "docx", "files": [{"path": "SKILL.md", "content": "y"}], "content": None}
MEDIA = [{"name": "media", "url": "http://127.0.0.1:3000/api/harness/v1/mcp/media"}]
OTHER = [{"name": "deepwiki", "url": "https://mcp.deepwiki.com/mcp"}, {"name": "db", "url": "http://127.0.0.1:3000/api/harness/v1/mcp/database"}]
CRED = {"base_url": "https://b", "api_key": "sk-x"}


@pytest.fixture(autouse=True)
def image_built_in(monkeypatch):
    monkeypatch.setattr(gw, "_builtin_skills", lambda: {"imagegen": {"files": BUILTIN["files"]}, "docx": {"files": DOCX["files"]}})


def test_with_the_media_tools_and_no_image_credential_the_builtin_is_dropped_and_suppressed():
    skills, off = gw._without_shadowing_image_skill([BUILTIN, DOCX], [], None, MEDIA)
    assert [s["name"] for s in skills] == ["docx"] and off == ["imagegen"]
    skills, off = gw._without_shadowing_image_skill([DOCX], ["pptx"], None, MEDIA + OTHER)   # never mentioned: still suppressed
    assert [s["name"] for s in skills] == ["docx"] and off == ["pptx", "imagegen"]
    assert gw._without_shadowing_image_skill([BUILTIN], ["imagegen"], None, MEDIA) == ([], ["imagegen"])


def test_with_no_other_way_to_make_an_image_the_skill_stays_to_say_what_is_missing():
    for servers in ([], OTHER, None):
        assert gw._without_shadowing_image_skill([BUILTIN, DOCX], [], None, servers) == ([BUILTIN, DOCX], [])


def test_with_an_image_credential_nothing_changes():
    assert gw._without_shadowing_image_skill([BUILTIN, DOCX], [], CRED, MEDIA) == ([BUILTIN, DOCX], [])


def test_a_harnesses_own_image_skill_stays():
    own = {"name": "imagegen", "files": [{"path": "SKILL.md", "content": "my own"}], "content": None}
    from_plugin = {"name": "imagegen", "files": BUILTIN["files"], "plugin": "studio"}
    assert gw._without_shadowing_image_skill([own, DOCX], [], None, MEDIA) == ([own, DOCX], [])
    assert gw._without_shadowing_image_skill([from_plugin], [], None, MEDIA) == ([from_plugin], [])


def test_an_image_built_without_the_skill_changes_nothing(monkeypatch):
    monkeypatch.setattr(gw, "_builtin_skills", lambda: {})
    assert gw._without_shadowing_image_skill([DOCX], [], None, MEDIA) == ([DOCX], [])


def test_the_media_server_is_known_by_its_own_path_whatever_it_was_named():
    renamed = [{"name": "studio tools", "url": "https://my.host/api/harness/v1/mcp/media/"}]
    assert gw._without_shadowing_image_skill([BUILTIN], [], None, renamed) == ([], ["imagegen"])
    lookalike = [{"name": "media", "url": "https://elsewhere.example/v1/mcp/mediaplayer"}]
    assert gw._without_shadowing_image_skill([BUILTIN], [], None, lookalike) == ([BUILTIN], [])


def test_the_turn_applies_it_right_after_its_image_credential_is_read():
    src = (Path(__file__).resolve().parents[1] / "app.py").read_text()
    assert ("    image_auth = await _image_auth(sid, backend)\n"
            "    skills, skills_suppressed = _without_shadowing_image_skill(skills, skills_suppressed, image_auth, mcp_servers)\n") in src
