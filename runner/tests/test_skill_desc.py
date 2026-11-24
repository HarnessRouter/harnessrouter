"""What the agent is told a skill does (the "Available skills" list in its instructions) is the skill's
SKILL.md description, read the way the gateway's _plugin_frontmatter reads it. A one-line regex told
it `>-` for a folded description and kept the escapes of the quoted form the console writes."""
import os
import sys

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
