"""System One's Chromium follows its Playwright (docker/entrypoint.sh: chromium_builds, chromium_current).

A Playwright pin change installs a new Playwright beside the build the old one downloaded. The
entrypoint checked for any `chromium-*` under PLAYWRIGHT_BROWSERS_PATH, so the build the new one
launches was never downloaded, and on a volume that came through the 1.64.1 pin every launch failed
("Executable doesn't exist at .../chromium_headless_shell-1248/..."). These run the entrypoint's own
functions, cut out of the script, against a venv and a browsers directory laid out the way Playwright
lays them out.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess

import pytest

ENTRYPOINT = pathlib.Path(__file__).resolve().parents[2] / "docker" / "entrypoint.sh"
SRC = ENTRYPOINT.read_text(encoding="utf-8")


def _function(name: str) -> str:
    m = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", SRC, flags=re.S | re.M)
    assert m, f"{name} is not defined in the entrypoint"
    return m.group(0)


def _run(tools: pathlib.Path, call: str) -> subprocess.CompletedProcess:
    script = (f'TOOLS="{tools}"; PLAYWRIGHT_BROWSERS_PATH="{tools}/ms-playwright"\n'
              + _function("chromium_builds") + _function("chromium_current") + call)
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)


def _venv(tools: pathlib.Path, browsers: list[dict]) -> None:
    pkg = tools / "systemone-venv/lib/python3.12/site-packages/playwright/driver/package"
    pkg.mkdir(parents=True)
    (pkg / "browsers.json").write_text(json.dumps({"comment": "", "browsers": browsers}))


PW_1641 = [{"name": "chromium", "revision": "1248", "installByDefault": True},
           {"name": "chromium-headless-shell", "revision": "1248", "installByDefault": True},
           {"name": "firefox", "revision": "1555", "installByDefault": True},
           {"name": "ffmpeg", "revision": "1013", "installByDefault": True}]


def _build(tools: pathlib.Path, name: str, complete: bool = True) -> None:
    d = tools / "ms-playwright" / name
    d.mkdir(parents=True)
    if complete:
        (d / "INSTALLATION_COMPLETE").write_text("")


def test_the_builds_are_the_venvs_playwrights_chromium_and_its_headless_shell(tmp_path):
    _venv(tmp_path, PW_1641)
    r = _run(tmp_path, "chromium_builds")
    assert r.stdout.split() == ["chromium-1248", "chromium_headless_shell-1248"], r.stderr


def test_an_older_build_left_by_an_earlier_playwright_is_not_current(tmp_path):
    """The volume sslip had: Playwright 1.64.1 in the venv, the 1243 builds on the volume."""
    _venv(tmp_path, PW_1641)
    _build(tmp_path, "chromium-1243")
    _build(tmp_path, "chromium_headless_shell-1243")
    assert _run(tmp_path, "chromium_current").returncode == 1


def test_the_builds_this_playwright_launches_are_current(tmp_path):
    _venv(tmp_path, PW_1641)
    _build(tmp_path, "chromium-1248")
    _build(tmp_path, "chromium_headless_shell-1248")
    assert _run(tmp_path, "chromium_current").returncode == 0


@pytest.mark.parametrize("missing", ["chromium-1248", "chromium_headless_shell-1248"])
def test_one_build_missing_is_not_current(tmp_path, missing):
    _venv(tmp_path, PW_1641)
    for b in ("chromium-1248", "chromium_headless_shell-1248"):
        if b != missing:
            _build(tmp_path, b)
    assert _run(tmp_path, "chromium_current").returncode == 1


def test_a_download_cut_short_is_not_current(tmp_path):
    _venv(tmp_path, PW_1641)
    _build(tmp_path, "chromium-1248", complete=False)
    _build(tmp_path, "chromium_headless_shell-1248")
    assert _run(tmp_path, "chromium_current").returncode == 1


def test_no_browsers_json_is_not_current(tmp_path):
    (tmp_path / "systemone-venv").mkdir()
    _build(tmp_path, "chromium-1248")
    assert _run(tmp_path, "chromium_current").returncode == 1


def test_a_revision_that_is_not_a_number_names_no_path(tmp_path):
    _venv(tmp_path, [{"name": "chromium", "revision": "../../etc"},
                     {"name": "chromium-headless-shell", "revision": "1248"}])
    assert _run(tmp_path, "chromium_builds").stdout.split() == ["chromium_headless_shell-1248"]


def test_install_and_every_start_download_a_build_that_is_not_current():
    inst = _function("install_systemone")
    assert "chromium_current || chromium_download" in inst
    assert 'ls "$PLAYWRIGHT_BROWSERS_PATH"/chromium-*' not in SRC, "any chromium-* is not the build this Playwright launches"
    start = SRC[SRC.index('if wanted systemone && [ -x "$TOOLS/systemone-venv/bin/playwright" ]; then'):]
    assert start.index("chromium_current || chromium_download") < start.index("chromium_libs ||")


def test_root_runs_apt_before_the_tools_tree_is_on_its_path():
    """chromium_libs runs apt-get as root; $TOOLS/bin is filled by the install uids, so a call after
    the line that puts it first on PATH would run whatever apt-get an install planted there."""
    call = SRC.index('chromium_libs || echo "[harnessrouter]   WARNING: Chromium')
    first = re.search(r'^export PATH="\$TOOLS/bin:\$PATH"', SRC, flags=re.M)
    assert first and call < first.start()
