"""Root must never read or run what the product user can change (GHSA-mm72-wr37-26pv).

The gateway and the console run as `agent`, and face the network and the agents. The entrypoint and the runner run as root.
Anything of root's that `agent` can write turns any bug in those two into root, at the next start or the next console restart.
The release gate reads the same rules off a running container (.github/workflows/release.yml)."""
import os
import pathlib
import re
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
EP = (ROOT / "docker" / "entrypoint.sh").read_text()
DF = (ROOT / "Dockerfile").read_text()


def test_the_image_gives_the_product_user_nothing_of_what_root_runs():
    assert "HOME=/home/agent" not in DF, "root would inherit a HOME the product user writes: its .npmrc, pip.conf and site-packages"
    grants = re.findall(r"chown -R agent:agent ([^\\\n&]+)", DF)
    assert grants, "the product user owns nothing at all"
    named = " ".join(grants).split()
    assert not [p for p in named if p == "/app" or (p.startswith("/app/") and p != "/app/ui/.next/cache")], named
    assert DF.index("chown -R root:root /app") < DF.index("chown -R agent:agent")


def test_root_has_its_own_home_and_the_drops_give_the_product_its_own():
    assert EP.index("export HOME=/root") < EP.index("install_backends()")
    assert re.search(r'^AS_PRODUCT="env HOME=/home/agent setpriv ', EP, re.M)
    for use in re.findall(r".*\$AS_PRODUCT .*", EP):
        assert "umask 077" in use, use


def test_python_as_root_takes_no_module_from_its_directory():
    """A script on stdin or -c puts the current directory first on sys.path. The console's restart loop ran one from /app/ui:
    a json.py planted there ran as root at the next console restart, with no container restart needed."""
    for line in EP.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or '"$PY"' not in line or "$AS_PRODUCT" in line:
            continue
        if "-m uvicorn server:app" in line:   # the runner, from /app/runner, which is root's
            continue
        if line.lstrip().startswith("install_pinned_venv "):   # runs it as "$pv_py" -I, checked below
            continue
        assert '"$PY" -I ' in line, line
    for helper in ("lv_py", "uv_py"):
        assert f'"${helper}" -I -m venv' in EP, helper


def test_nothing_on_the_volume_is_followed_by_a_chown_or_a_chmod_of_root():
    """The product can write the volume's top level, so a name there can be a link to anything."""
    assert not re.search(r'for \w+ in "\$DATA_DIR', EP), "a name from the volume reaches chown or chmod by way of a loop"
    assert re.search(r"find \"\$DATA_DIR\" -maxdepth 1 -type f -links 1 ", EP)
    assert re.search(r"find \"\$DATA_DIR\" -maxdepth 1 -type d ", EP)
    assert 'chown "root:$PRODUCT" "$DATA_DIR"' in EP and 'chmod 1771 "$DATA_DIR"' in EP
    for var in ("HARNESS_WORKSPACE", "HR_WS_MARKER_DIR", "HR_ENV_ROOT"):
        assert f'root_dir "${var}"' in EP, var
    assert 'root_file "$HR_INITIAL_PASSWORD_FILE"' in EP
    assert EP.index('root_file "$HR_INITIAL_PASSWORD_FILE"') < EP.index('> "$HR_INITIAL_PASSWORD_FILE"')


def _helpers(tmp_path):
    """The entrypoint's two helpers, run for real, with a stand-in for chown so this works without root."""
    start = EP.index("root_dir() {"); end = EP.index("\n}\n", EP.index("root_file() {")) + 3
    stub = tmp_path / "bin"; stub.mkdir(); (stub / "chown").write_text("#!/bin/sh\nexit 0\n"); (stub / "chown").chmod(0o755)
    script = tmp_path / "helpers.sh"; script.write_text(EP[start:end])
    return script, {**os.environ, "PATH": f"{stub}:{os.environ['PATH']}"}


def _run(script, env, call):
    subprocess.run(["bash", "-c", f'. "{script}"; {call}'], check=True, env=env)


def test_a_link_where_root_keeps_a_directory_is_removed_and_its_target_untouched(tmp_path):
    script, env = _helpers(tmp_path)
    target = tmp_path / "outside"; target.mkdir(); (target / "keep").write_text("x")
    link = tmp_path / "ws-markers"; link.symlink_to(target)
    _run(script, env, f'root_dir "{link}"')
    assert link.is_dir() and not link.is_symlink() and (target / "keep").read_text() == "x"
    plain = tmp_path / "environments"; plain.write_text("a file")
    _run(script, env, f'root_dir "{plain}"')
    assert plain.is_dir()
    kept = tmp_path / "workspaces"; kept.mkdir(); (kept / "s1").mkdir()
    _run(script, env, f'root_dir "{kept}"')
    assert (kept / "s1").is_dir(), "a real directory keeps what it holds"


def test_only_roots_own_single_file_survives_as_a_file_root_uses(tmp_path):
    if os.getuid() == 0:
        pytest.skip("as root every file here is already root's")
    script, env = _helpers(tmp_path)
    target = tmp_path / "secret"; target.write_text("x")
    link = tmp_path / "selfhost-initial-password"; link.symlink_to(target)
    _run(script, env, f'root_file "{link}"')
    assert not link.is_symlink() and not link.exists() and target.read_text() == "x"
    mine = tmp_path / "planted"; mine.write_text("known password")     # owned by this uid, which is not root
    _run(script, env, f'root_file "{mine}"')
    assert not mine.exists()
    _run(script, env, f'root_file "{tmp_path / "absent"}"')


def test_the_gateways_signatures_never_use_a_constant_anyone_can_read():
    src = (ROOT / "gateway" / "app.py").read_text()
    assert "dev-insecure" not in src


def test_the_tools_are_sealed_after_the_installers_as_well_as_before():
    """A mark written before the installers ran let a fresh install keep its archives' owners and modes: the release gate found 7351 such paths."""
    text = pathlib.Path(__file__).resolve().parents[2].joinpath("docker", "entrypoint.sh").read_text()
    calls = [m.start() for m in re.finditer(r"^seal_tools\b(?!\(\))", text, re.M)]
    start = re.search(r"^install_backends$", text, re.M).start()
    assert len(calls) == 2 and calls[0] < start < calls[1], calls
    assert ".root-owned" not in text, "no mark: the walk decides from what is on disk"
    assert text.index("uvicorn server:app") > calls[1], "nothing runs a tool for a session before the second seal"
