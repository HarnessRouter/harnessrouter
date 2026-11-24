"""What the agent is told a skill does (the "Available skills" list in its instructions) is the skill's
SKILL.md description, read the way the gateway's _plugin_frontmatter reads it. A one-line regex told
it `>-` for a folded description and kept the escapes of the quoted form the console writes."""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import server  # noqa: E402


@pytest.mark.parametrize(("md", "desc"), [
    ("---\nname: tone\ndescription: >-\n  How the shop writes\n  to customers.\n---\nBody\n", "How the shop writes to customers."),
    ("---\nname: tone\ndescription: |\n  Line one.\n  Line two.\n---\nBody\n", "Line one. Line two."),
    ('---\nname: tone\ndescription: "Formats issues like #123 and says \\"done\\""\n---\nBody\n',
     'Formats issues like #123 and says "done"'),
    ('---\nname: tone\ndescription: "Quoted value" # note\n---\nBody\n', "Quoted value"),
    ("---\nname: tone\ndescription: 'It''s the shop voice'\n---\nBody\n", "It's the shop voice"),
    ("---\nname: tone\ndescription: Writes replies # how\n  in the shop's voice.\n---\nBody\n", "Writes replies in the shop's voice."),
    ("---\nname: tone\ndescription:\n  Writes replies in the shop's voice.\n---\nBody\n", "Writes replies in the shop's voice."),
    ("﻿---\r\nname: tone\r\ndescription: Windows line ends\r\n---\r\nBody\r\n", "Windows line ends"),
    # No description: the body's first line of prose, never a frontmatter line or a body `description:`.
    ("---\nname: tone\nlicense: MIT\n---\n# Shop tone\ndescription: body only\n", "Shop tone"),
    ("# Shop tone\n\nWrites replies.\n", "Shop tone"),
], ids=["folded", "literal", "console-json", "quoted-comment", "single-quoted", "plain-continued",
        "plain-on-next-lines", "bom-crlf", "no-description", "no-frontmatter"])
def test_a_skill_is_described_by_its_frontmatter(md, desc):
    assert server._skill_desc([{"path": "SKILL.md", "content": md}]) == desc


def test_the_instructions_name_the_skill_by_its_description(tmp_path):
    md = "---\nname: shop-tone\ndescription: >-\n  How the shop writes\n  to customers.\n---\nBody\n"
    meta = server._write_skills(str(tmp_path), [{"name": "shop-tone", "files": [{"path": "SKILL.md", "content": md}]}])
    assert [m["desc"] for m in meta] == ["How the shop writes to customers."]


def test_a_second_paragraph_and_a_leading_hash():
    two = "---\nname: tone\ndescription: >\n  Paragraph one.\n\n  Paragraph two.\n---\nBody\n"
    assert server._skill_desc([{"path": "SKILL.md", "content": two}]) == "Paragraph one. Paragraph two."
    # After `: `, a # starts a YAML comment: no description, so the body's first line.
    hashed = "---\nname: tone\ndescription: #1 tool\n---\nThe best tool.\n"
    assert server._skill_desc([{"path": "SKILL.md", "content": hashed}]) == "The best tool."


def _best_of_3(fn, *a) -> float:
    best = 1e9
    for _ in range(3):
        t0 = time.perf_counter(); fn(*a); best = min(best, time.perf_counter() - t0)
    return best


SPACES = " " * 200_000


@pytest.mark.parametrize(("first", "more"), [
    ("x" + SPACES + "y", []), ("x", [SPACES + "y"]), ("x" + SPACES, [SPACES + "y" + SPACES]),
])
def test_a_long_run_of_spaces_reads_in_linear_time(first, more):
    # `(^|\s+)#.*$` backtracked here: 20K spaces took 1.7 s, 200K minutes.
    assert _best_of_3(server._frontmatter_value, first, more) < 0.05


def test_the_reader_reads_only_the_first_64_kb():
    huge = "---\nname: tone\ndescription: x\n" + (SPACES + "\n") * 50 + "---\nBody line.\n"
    assert _best_of_3(server._frontmatter, huge) < 0.05
    fm, body = server._frontmatter("---\nname: tone\ndescription: d\n---\n" + "Body " * 20_000)
    assert fm["description"] == "d" and len(body) == 100_000, "the body is not cut, only the frontmatter read"
