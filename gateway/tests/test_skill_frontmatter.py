"""A SKILL.md's frontmatter is read as YAML reads the forms skills are written in, by every reader:
this one (the plugin check and the setup builder), the runner's _frontmatter (the agent's "Available
skills" list) and the console's splitSkillMd (the skill editor). The same shapes are pinned in all
three. A plugin's SKILL.md reaches this reader in a gateway every organization shares, so it must
take linear time on any input."""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app  # noqa: E402

FM = "---\nname: tone\n{}\nlicense: MIT\n---\nBody\n"


@pytest.mark.parametrize(("lines", "description"), [
    ("description: >-\n  How the shop writes\n  to customers.", "How the shop writes to customers."),
    ("description: |\n  Line one.\n  Line two.", "Line one. Line two."),
    ("description: >\n  Paragraph one.\n\n  Paragraph two.", "Paragraph one. Paragraph two."),
    # The console writes a description with JSON.stringify: the # is text and the escapes are decoded.
    ('description: "Formats issues like #123 and says \\"done\\""', 'Formats issues like #123 and says "done"'),
    ('description: "Quoted value" # note', "Quoted value"),
    ("description: 'It''s the shop voice' # note", "It's the shop voice"),
    ("description: Writes replies # how\n  in the shop's voice.", "Writes replies in the shop's voice."),
    ("description:\n  Writes replies\n\n  in the shop's voice.", "Writes replies in the shop's voice."),
    ('description: "Runs over\n  two lines"', "Runs over two lines"),
    ("description: Writes C# and F#", "Writes C# and F#"),
    # After `: `, a # starts a comment, as every YAML reader (and so the agent's CLI) takes it.
    ("description: #1 tool", ""),
], ids=["folded", "literal", "two-paragraphs", "console-json", "quoted-comment", "single-quoted",
        "plain-continued", "plain-on-next-lines", "quoted-two-lines", "hash-inside-a-word", "comment-only"])
def test_a_description_is_read_as_yaml_reads_it(lines, description):
    fm = app._plugin_frontmatter(FM.format(lines))
    assert fm == {"name": "tone", "description": description, "license": "MIT"}


def test_a_byte_order_mark_and_windows_line_ends():
    fm = app._plugin_frontmatter("﻿---\r\nname: tone\r\ndescription: Windows line ends\r\n---\r\nBody\r\n")
    assert fm == {"name": "tone", "description": "Windows line ends"}


def test_no_frontmatter_reads_as_none():
    assert app._plugin_frontmatter("# Tone\n\ndescription: body only\n") == {}


def _best_of_3(fn, *a) -> float:
    best = 1e9
    for _ in range(3):
        t0 = time.perf_counter(); fn(*a); best = min(best, time.perf_counter() - t0)
    return best


SPACES = " " * 200_000


@pytest.mark.parametrize(("first", "more"), [
    ("x" + SPACES + "y", []),                  # one line: a long run of spaces with no #
    ("x", [SPACES + "y"]),                     # the same as a continuation line
    ("x" + SPACES, [SPACES + "y" + SPACES]),   # both, with trailing runs
    ('"x' + SPACES, [SPACES + 'y"' + SPACES + "# c"]),
])
def test_a_long_run_of_spaces_reads_in_linear_time(first, more):
    # `(^|\s+)#.*$` backtracked here: 20K spaces took 1.7 s, 200K minutes.
    assert _best_of_3(app._frontmatter_value, first, more) < 0.05


def test_the_reader_reads_only_the_first_64_kb():
    ok = "---\nname: tone\ndescription: a" + " " * 60_000 + "b\n---\nBody\n"
    assert app._plugin_frontmatter(ok)["description"] == "a" + " " * 60_000 + "b"
    assert _best_of_3(app._plugin_frontmatter, ok) < 0.05
    assert app._plugin_frontmatter("---\nname: tone\ndescription: " + "x" * 70_000 + "\n---\n") == {}
    huge = "---\nname: tone\ndescription: x\n" + (SPACES + "\n") * 50 + "---\n"   # 10 MB
    assert _best_of_3(app._plugin_frontmatter, huge) < 0.05
