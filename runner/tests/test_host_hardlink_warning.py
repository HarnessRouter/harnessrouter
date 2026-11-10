"""The container says once, at start, when its host lets one user hard-link another user's file.

Each session runs as its own uid, and the host's fs.protected_hardlinks decides whether a user may make a hard
link to a file it does not own. The container cannot set it, so the entrypoint reads it and prints one warning
line when it is 0; when it is 1, or cannot be read, it prints nothing.
"""
import pathlib
import re
import subprocess

import pytest

ENTRY = pathlib.Path(__file__).resolve().parents[2] / "docker" / "entrypoint.sh"


def _function() -> str:
    text = ENTRY.read_text()
    m = re.search(r"^protected_hardlinks_warning\(\) \{\n.*?^\}\n", text, re.S | re.M)
    assert m, "the entrypoint has no protected_hardlinks_warning"
    return m.group(0)


def _say(setting: str | None, tmp_path) -> str:
    f = tmp_path / "protected_hardlinks"
    if setting is not None:
        f.write_text(setting)
    script = "set -euo pipefail\n" + _function() + f'protected_hardlinks_warning "{f}"\necho done\n'
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert out.stdout.endswith("done\n"), "the check stopped the entrypoint"
    return out.stdout.removesuffix("done\n")


def test_a_host_that_allows_it_gets_one_line(tmp_path):
    said = _say("0\n", tmp_path)
    assert said.count("\n") == 1 and said.startswith("[harnessrouter] WARN:") and "fs.protected_hardlinks=0" in said


@pytest.mark.parametrize("setting", ["1\n", "2\n", None], ids=["protected", "stricter", "unreadable"])
def test_a_host_that_protects_them_or_cannot_say_gets_nothing(tmp_path, setting):
    assert _say(setting, tmp_path) == ""


def test_the_entrypoint_runs_the_check_at_start():
    text = ENTRY.read_text()
    assert text.index("\nprotected_hardlinks_warning\n") < text.index("uvicorn server:app"), "not checked before the runner starts"
