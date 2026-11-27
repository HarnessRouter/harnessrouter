"""Skills on the realtime base: which are offered, what the model is told, and what the tools return.

realtime_skills.py needs nothing but the standard library, so this runs wherever the runner's tests
do. The wrapped executor here is a stand-in with the Realtime Harness's ToolExecutor's shape; the
driver's own tests (test_realtime_driver.py) run the same thing on the real one, through a turn.
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import realtime_skills as rs  # noqa: E402

REVIEW = "---\nname: review\ndescription: How to review a pull request.\n---\n\n# Review\n\nRead the diff first.\n"


def put(cwd: pathlib.Path, name: str, files: dict[str, str | bytes], desc: str = "") -> dict:
    """A skill as the runner writes it, and the entry it hands the driver."""
    root = cwd / ".harness" / "skills" / name
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    return {"name": name, "desc": desc, "entry": f".harness/skills/{name}/SKILL.md"}


class Inner:
    """The wrapped executor: one MCP tool, and a record of what it was asked to run."""

    def __init__(self, *names: str):
        self.tools = {n: object() for n in names or ("search",)}
        self.left_out = {"server:down": "unreachable"}
        self.ran: list[tuple] = []
        self.opened = False

    async def open(self):
        self.opened = True

    def functions(self):
        return [{"type": "function", "name": n, "description": "", "parameters": {}} for n in self.tools]

    async def call(self, name, arguments):
        self.ran.append((name, arguments))
        return {"status": "done", "output": "from the server"}


def tools(cwd, metas, *, inner=None, disabled=None) -> tuple[rs.SkillTools, list[dict]]:
    skills, left = rs.read(cwd, metas)
    t = rs.SkillTools(inner or Inner(), skills, disabled)
    t.settle()
    return t, left + t.not_offered


def call(t: rs.SkillTools, name: str, arguments) -> dict:
    return asyncio.run(t.call(name, arguments))


# ── which skills are offered ────────────────────────────────────────────────────────────────────
def test_a_skill_of_instructions_is_offered_with_its_description_and_its_body_without_the_frontmatter(tmp_path):
    skills, left = rs.read(tmp_path, [put(tmp_path, "review", {"SKILL.md": REVIEW}, "How to review a pull request.")])
    assert left == []
    assert [(s.name, s.description, s.body) for s in skills] == [
        ("review", "How to review a pull request.", "# Review\n\nRead the diff first.")]


@pytest.mark.parametrize("files", [
    {"SKILL.md": REVIEW, "scripts/run.py": "print(1)"},
    {"SKILL.md": REVIEW, "scripts/README.txt": "how to run"},       # anything under scripts/ is for a shell
    {"SKILL.md": REVIEW, "tool.sh": "#!/bin/sh"},
    {"SKILL.md": REVIEW, "lib/convert.JS": "x"},
])
def test_a_skill_that_carries_scripts_is_left_out_and_named(tmp_path, files):
    skills, left = rs.read(tmp_path, [put(tmp_path, "pdf", files)])
    assert skills == [] and left == [{"name": "pdf", "reason": rs.HAS_SCRIPTS}]


def test_a_skill_with_no_instructions_or_no_file_is_left_out_and_named(tmp_path):
    empty = put(tmp_path, "empty", {"SKILL.md": "---\nname: empty\ndescription: d\n---\n\n   \n"})
    gone = {"name": "gone", "desc": "", "entry": ".harness/skills/gone/SKILL.md"}
    binary = put(tmp_path, "binary", {"SKILL.md": b"\xff\xfe\x00\x01"})
    skills, left = rs.read(tmp_path, [empty, gone, binary])
    assert skills == []
    assert left == [{"name": "empty", "reason": rs.NO_BODY}, {"name": "gone", "reason": rs.NO_ENTRY},
                    {"name": "binary", "reason": rs.NO_ENTRY}]


@pytest.mark.parametrize("entry", ["../outside/SKILL.md", ".harness/skills/x/notes.md", ""])
def test_an_entry_that_is_not_a_skill_file_in_the_workspace_is_not_read(tmp_path, entry):
    (tmp_path.parent / "outside").mkdir(exist_ok=True)
    (tmp_path.parent / "outside" / "SKILL.md").write_text("# Outside\n\nNot this workspace's.\n")
    put(tmp_path, "x", {"notes.md": "notes"})
    skills, left = rs.read(tmp_path, [{"name": "x", "desc": "", "entry": entry}])
    assert skills == [] and left == [{"name": "x", "reason": rs.NO_ENTRY}]


def test_a_name_given_twice_is_one_skill_and_what_is_not_a_skill_is_passed_over(tmp_path):
    m = put(tmp_path, "review", {"SKILL.md": REVIEW})
    skills, left = rs.read(tmp_path, [m, dict(m), "review", None, {"name": ""}])
    assert [s.name for s in skills] == ["review"] and left == []


def test_the_list_has_a_ceiling_and_what_does_not_fit_is_named(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "CATALOG_CHARS", len(rs.INTRO) + 60)
    metas = [put(tmp_path, n, {"SKILL.md": REVIEW}, "d" * 40) for n in ("a", "b", "c")]
    skills, left = rs.read(tmp_path, metas)
    assert [s.name for s in skills] == ["a"]
    assert left == [{"name": "b", "reason": rs.NO_ROOM}, {"name": "c", "reason": rs.NO_ROOM}]
    assert len(rs.catalog(skills)) <= rs.CATALOG_CHARS + 1


def test_a_description_is_one_line_and_no_longer_than_the_format_allows(tmp_path):
    skills, _ = rs.read(tmp_path, [put(tmp_path, "review", {"SKILL.md": REVIEW}, "two\n  lines " + "x" * 2000)])
    assert skills[0].description.startswith("two lines x") and len(skills[0].description) == rs.DESCRIPTION_MAX


# ── what the model is told ──────────────────────────────────────────────────────────────────────
def test_the_instructions_gain_the_list_after_the_harnesss_own(tmp_path):
    skills, _ = rs.read(tmp_path, [put(tmp_path, "review", {"SKILL.md": REVIEW}, "How to review."),
                                   put(tmp_path, "plain", {"SKILL.md": "# Plain\n\nBe plain.\n"})])
    text = rs.with_catalog("You answer for the store.\n", skills)
    assert text.startswith("You answer for the store.\n\n## Skills\n")
    assert "`load_skill`" in text and text.endswith("- review: How to review.\n- plain\n")
    assert rs.with_catalog("", skills).startswith("## Skills")


def test_a_harness_with_no_skills_is_told_nothing_about_them_and_gets_no_tool(tmp_path):
    t, left = tools(tmp_path, [])
    assert rs.with_catalog("You answer for the store.", t.skills) == "You answer for the store."
    assert [f["name"] for f in t.functions()] == ["search"] and left == []
    # and a call by that name goes to the servers, which refuse it in their own words
    call(t, "load_skill", {"name": "review"})
    assert t.ran == [("load_skill", {"name": "review"})]


def test_the_tools_sit_beside_the_servers_tools_and_name_the_skills(tmp_path):
    t, _ = tools(tmp_path, [put(tmp_path, "review", {"SKILL.md": REVIEW}),
                            put(tmp_path, "style", {"SKILL.md": REVIEW, "references/tone.md": "Warm."})])
    fns = {f["name"]: f for f in t.functions()}
    assert list(fns) == ["search", "load_skill", "read_skill_resource"]
    assert fns["load_skill"]["parameters"]["properties"]["name"]["enum"] == ["review", "style"]
    assert fns["read_skill_resource"]["parameters"]["properties"]["name"]["enum"] == ["style"]
    json.dumps(t.functions())                                   # what goes on the wire


def test_the_resource_tool_is_offered_only_when_a_skill_has_a_file_to_read(tmp_path):
    t, _ = tools(tmp_path, [put(tmp_path, "review", {"SKILL.md": REVIEW})])
    assert [f["name"] for f in t.functions()] == ["search", "load_skill"]
    assert not t.owns("read_skill_resource")


def test_everything_else_is_the_wrapped_executors_own(tmp_path):
    inner = Inner()
    t, _ = tools(tmp_path, [put(tmp_path, "review", {"SKILL.md": REVIEW})], inner=inner)
    asyncio.run(t.open())
    assert inner.opened and t.tools is inner.tools and t.left_out is inner.left_out
    assert call(t, "search", '{"q": "x"}') == {"status": "done", "output": "from the server"}
    assert inner.ran == [("search", '{"q": "x"}')]


# ── what the tools return ───────────────────────────────────────────────────────────────────────
def test_loading_a_skill_returns_its_instructions_and_lists_its_files(tmp_path):
    t, _ = tools(tmp_path, [put(tmp_path, "style", {"SKILL.md": REVIEW, "references/tone.md": "Warm.",
                                                    "assets/logo.png": b"\x89PNG\x00\x00"})])
    out = call(t, "load_skill", '{"name": "style"}')
    assert out["status"] == "done"
    assert out["output"].startswith('<skill_content name="style">\n# Review\n\nRead the diff first.\n</skill_content>')
    assert "description:" not in out["output"]                    # the frontmatter is not the instructions
    assert "read with `read_skill_resource`:\n- references/tone.md\n" in out["output"]
    assert "cannot be read here (not text, or too large): assets/logo.png" in out["output"]
    assert t.ran == []                                           # no server was asked


def test_a_long_skill_comes_in_parts_and_none_of_it_is_cut(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "PART_CHARS", 100)
    body = "# Long\n\n" + "".join(f"Line {i}.\n" for i in range(60))
    t, _ = tools(tmp_path, [put(tmp_path, "long", {"SKILL.md": body})])
    first = call(t, "load_skill", {"name": "long"})["output"]
    assert first.startswith("[part 1 of ") and "Call again with part 2" in first
    n = int(first.split(" of ")[1].split(".")[0])
    whole = ""
    for i in range(1, n + 1):
        part = call(t, "load_skill", {"name": "long", "part": i})["output"]
        assert ("This is the last." in part) == (i == n)
        whole += part.split("]\n", 1)[1]
    assert whole == f'<skill_content name="long">\n{body.strip()}\n</skill_content>'
    assert call(t, "load_skill", {"name": "long", "part": n + 1}) == {
        "error": "refused", "detail": f"this skill has {n} parts"}
    assert call(t, "load_skill", {"name": "long", "part": "two"})["error"] == "refused"


def test_a_skill_that_is_not_one_and_arguments_that_are_not_are_refused_in_words(tmp_path):
    t, _ = tools(tmp_path, [put(tmp_path, "review", {"SKILL.md": REVIEW})])
    assert call(t, "load_skill", {"name": "nope"}) == {
        "error": "refused", "detail": "no skill of that name; the skills are review"}
    assert call(t, "load_skill", "{not json")["detail"] == "the arguments are not JSON"
    assert call(t, "load_skill", "[1]")["detail"] == "the arguments are not a JSON object"


def test_a_resource_is_read_by_a_path_the_skill_listed_and_by_no_other(tmp_path):
    (tmp_path / "secret.txt").write_text("the workspace's own file")
    t, _ = tools(tmp_path, [put(tmp_path, "style", {"SKILL.md": REVIEW, "references/tone.md": "Warm."}),
                            put(tmp_path, "other", {"SKILL.md": REVIEW, "notes.md": "Other's notes."})])
    assert call(t, "read_skill_resource", {"name": "style", "path": "references/tone.md"}) == {
        "status": "done", "output": "Warm."}
    assert call(t, "read_skill_resource", {"name": "style", "path": "./references\\tone.md"})["output"] == "Warm."
    for path in ("../../../secret.txt", "../other/notes.md", "SKILL.md", str(tmp_path / "secret.txt"), "", "references"):
        out = call(t, "read_skill_resource", {"name": "style", "path": path})
        assert out["error"] == "refused" and "its files are references/tone.md" in out["detail"], path


@pytest.mark.skipif(not hasattr(os, "symlink") or sys.platform == "win32", reason="needs symbolic links")
def test_a_link_out_of_the_skills_folder_is_not_a_file_of_the_skill(tmp_path):
    (tmp_path / "secret.txt").write_text("the workspace's own file")
    meta = put(tmp_path, "style", {"SKILL.md": REVIEW})
    os.symlink(tmp_path / "secret.txt", tmp_path / ".harness" / "skills" / "style" / "leak.md")
    skills, _ = rs.read(tmp_path, [meta])
    assert skills[0].resources == () and skills[0].unreadable == ("leak.md",)


def test_a_file_that_is_too_large_or_not_text_is_named_and_not_readable(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "RESOURCE_BYTES", 10)
    t, _ = tools(tmp_path, [put(tmp_path, "style", {"SKILL.md": "# S\n", "big.md": "x" * 11, "ok.md": "fine",
                                                    "data.bin": b"\x00\x01"})])
    s = t.skills[0]
    assert s.resources == ("ok.md",) and s.unreadable == ("big.md", "data.bin")
    assert call(t, "read_skill_resource", {"name": "style", "path": "big.md"})["error"] == "refused"


# ── when the skills are withdrawn ───────────────────────────────────────────────────────────────
def test_a_harness_that_disables_load_skill_is_offered_no_skills_and_it_is_said(tmp_path):
    t, left = tools(tmp_path, [put(tmp_path, "review", {"SKILL.md": REVIEW})], disabled=["load_skill"])
    assert [f["name"] for f in t.functions()] == ["search"] and t.skills == []
    assert left == [{"name": "review", "reason": rs.SWITCHED_OFF}]
    assert rs.with_catalog("Base.", t.skills) == "Base."


def test_a_servers_tool_of_the_same_name_keeps_the_name_and_the_skills_are_withdrawn(tmp_path):
    inner = Inner("load_skill")
    t, left = tools(tmp_path, [put(tmp_path, "review", {"SKILL.md": REVIEW})], inner=inner)
    assert [f["name"] for f in t.functions()] == ["load_skill"]              # the server's, once
    assert left == [{"name": "review", "reason": "an MCP server has a tool named load_skill"}]
    call(t, "load_skill", {"name": "review"})
    assert inner.ran == [("load_skill", {"name": "review"})]


def test_disabling_only_the_resource_tool_keeps_the_skills(tmp_path):
    t, left = tools(tmp_path, [put(tmp_path, "style", {"SKILL.md": REVIEW, "tone.md": "Warm."})],
                    disabled=["read_skill_resource"])
    assert [f["name"] for f in t.functions()] == ["search", "load_skill"] and left == []
