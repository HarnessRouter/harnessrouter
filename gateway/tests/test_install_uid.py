"""Root runs nothing an install brought (#623, step 3).

docker/entrypoint.sh installs every agent CLI at first start, as root. The steps that run code out of a
download, or let a package manager write a base's tree, run as that base's own install uid instead:
install_base runs each install through install_as_uid, the helpers hand the uid the one directory it
fills (iu_take) and take it back before root acts on it (iu_give), and root links the npm bases'
commands from a tree that is root's again, checking what each package asks for. scripts/check-install-pins.py
holds the source to `iu` for every such step; these hold the uids themselves and the link step, which
runs as root."""
import json
import os
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
EP = (ROOT / "docker" / "entrypoint.sh").read_text()


def _func(name: str) -> str:
    m = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", EP, re.S | re.M)
    assert m, f"docker/entrypoint.sh has no {name}()"
    return m.group(0)


def _bash(script: str, **env) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                          env={"PATH": os.environ["PATH"], **env})


def _bash_has_maps() -> bool:
    """The entrypoint's bash (Debian's, 5.x) has associative arrays; macOS's /bin/bash 3.2 does not."""
    r = subprocess.run(["bash", "-ec", 'declare -A m=(); m[/a/b]=1; [ "${m[/a/b]}" = 1 ]'], capture_output=True)
    return r.returncode == 0


def _order() -> list[str]:
    m = re.search(r'^INSTALL_UID_ORDER=" (.*) "$', EP, re.M)
    assert m
    return m.group(1).split()


def test_every_base_has_an_install_uid_of_its_own_below_the_sessions():
    """A base missing from the order cannot install at all (install_as_uid refuses it), so every base the
    entrypoint knows is in it, once."""
    table = _func("backend_bin")
    bases = re.findall(r"^\s+([a-z][a-z0-9-]*)\)\s", table, re.M)
    order = _order()
    assert len(order) == len(set(order))
    assert sorted(order) == sorted(bases), set(order) ^ set(bases)
    base = int(re.search(r"^INSTALL_UID_BASE=(\d+)$", EP, re.M).group(1))
    script = f'INSTALL_UID_BASE={base}\nINSTALL_UID_ORDER=" {" ".join(order)} "\n{_func("install_uid")}' + \
        "".join(f'install_uid {b}\n' for b in order) + "install_uid not-a-base || echo none\n"
    out = _bash(script).stdout.split()
    uids = [int(u) for u in out[:-1]]
    assert out[-1] == "none"
    assert uids == list(range(base + 1, base + 1 + len(order)))
    # below the runner's session uids (20000 up) and above the product's (10001)
    assert 10001 < min(uids) and max(uids) < 20000
    assert 'HR_SESSION_UID_BASE:-20000' in _func("install_as_uid")


def test_every_install_goes_through_its_uid_and_drops_everything():
    assert 'try_install "$ib_label" install_as_uid "$ib_base" "$@"' in _func("install_base")
    iu = _func("iu")
    assert "setpriv --reuid=\"$IU_UID\" --regid=\"$IU_UID\" --clear-groups --no-new-privs" in iu
    assert 'HOME="$IU_HOME"' in iu
    ia = _func("install_as_uid")
    # what the uid held is given back, its processes are killed, its HOME goes, whatever the install did
    assert ia.index('"$@"; ia_rc=$?') < ia.index("iu_give") < ia.index("iu_kill || ia_rc=1") < ia.rindex('rm -rf -- "$IU_HOME"')
    give = _func("iu_give")
    assert give.index("iu_kill") < give.index("-links +1") < give.index("iu_links_out") \
        < give.index("chown -hR root:root") < give.index("ug-s,go-w,a+rX")


def test_nothing_of_an_install_uid_is_left_anywhere_before_the_seal():
    # after the last install and before the tools are sealed and anything else starts
    tail = EP[EP.rindex("\ninstall_backends\n"):]
    assert tail.index("\niu_sweep ||") < tail.index("\nseal_tools") < tail.index("server:app")
    sw = _func("iu_sweep")
    # every install uid: the range comes from INSTALL_UID_ORDER, so a base added at the end is in it
    assert 'read -ra sw_w <<<"$INSTALL_UID_ORDER"' in sw and "sw_hi=$((INSTALL_UID_BASE + ${#sw_w[@]}))" in sw
    # its processes first, then what it owns, files and directories, by owner or by group
    assert sw.index("/proc/[0-9]*/status") < sw.index("iu_kill") < sw.index("find ")
    assert "-uid +$((sw_lo - 1)) -uid -$((sw_hi + 1)) -o -gid +$((sw_lo - 1)) -gid -$((sw_hi + 1))" in sw
    # every mounted file system (tmpfs /dev/shm, the message queues) but proc and sys; the volume only as the tools
    assert "done < /proc/mounts" in sw and 'sw_roots+=("$TOOLS")' in sw and '-path "$DATA_DIR" -prune' in sw
    assert 'rm -rf -- "$sw_p" || return 1' in sw


def _gnu_realpath() -> bool:
    return subprocess.run(["realpath", "-e", "--", "/"], capture_output=True).returncode == 0


@pytest.mark.skipif(not _gnu_realpath(), reason="needs GNU realpath -e (the image's coreutils)")
def test_a_link_that_leads_out_of_a_base_is_removed_and_nothing_reads_through_it(tmp_path):
    secret = tmp_path / "secret"; secret.write_text("k")
    beside = tmp_path / "tools" / "x-python"; (beside / "bin").mkdir(parents=True)
    (beside / "bin" / "python3").write_text("")              # what the same install unpacked beside it
    theirs = tmp_path / "tools" / "y-venv"; theirs.mkdir()
    (theirs / "python").write_text("")                        # another base's
    tree = tmp_path / "tools" / "npm" / "x"
    (tree / "node_modules" / "pkg").mkdir(parents=True)
    (tree / "node_modules" / ".bin").mkdir()
    (tree / "node_modules" / "pkg" / "cli.js").write_text("")
    keep = {
        "node_modules/.bin/cli": "../pkg/cli.js",        # npm's own links
        "lib64": "node_modules",                          # a venv's lib64 -> lib
        "python": "/usr/bin/env",                         # the image's interpreter
        "self": ".",
        "python3": str(beside / "bin" / "python3"),      # dcode's venv on its own Python build
    }
    out = {
        "to-secret": str(secret),                         # an instance secret
        "up": "../../../secret",                          # the same, relative
        "data": "/data/secrets/key",                      # a path that may exist later
        "proc": "/proc/1/environ",
        "via-usr": "/usr/../" + str(secret).lstrip("/"),  # /usr only after it is resolved
        "hop1": "hop2", "hop2": str(tmp_path),            # out through another link
        "loop1": "loop2", "loop2": "loop1",               # resolves nowhere
        "gone-inside": "node_modules/pkg/not-there",      # resolves nowhere yet
        "node_modules/pkg/deep": "../../../../secret",
        "other-base": str(theirs / "python"),             # a directory this install did not fill
    }
    for rel, target in {**keep, **out}.items():
        os.symlink(target, tree / rel)
    r = _bash(f'declare -A IU_MINE=(["{tree}"]=1 ["{beside}"]=1)\n{_func("iu_links_out")}iu_links_out "{tree}"')
    assert r.returncode == 0, r.stderr
    left = {str(p.relative_to(tree)) for p in tree.rglob("*") if p.is_symlink()}
    assert left == set(keep), (left, r.stdout)
    assert "removed a link that leads out of" in r.stdout and f"({len(out)} such links in all)" in r.stdout
    assert secret.read_text() == "k"


@pytest.mark.skipif(not _bash_has_maps(), reason="this bash has no associative arrays (the image's does)")
def test_the_uid_never_holds_what_every_base_shares(tmp_path):
    tools = tmp_path / "agent-tools"
    for d in ("bin", "lib", "npm/qwen", "venv", ".versions"):
        (tools / d).mkdir(parents=True)
    stub = tmp_path / "stub"; stub.mkdir()
    (stub / "chown").write_text("#!/bin/sh\nexit 0\n"); (stub / "chown").chmod(0o755)
    script = f'TOOLS="{tools}"; STAMPS="$TOOLS/.versions"; IU_UID=19008; declare -A IU_HELD=() IU_MINE=()\n{_func("iu_take")}' + \
        "for d in \"$@\"; do iu_take \"$d\" >/dev/null && echo \"took $d\" || echo \"refused $d\"; done\n"
    dirs = [f"{tools}", f"{tools}/bin", f"{tools}/lib", f"{tools}/npm", f"{tools}/.versions", f"{tools}/npm/../bin",
            f"{tmp_path}", f"{tools}/npm/qwen", f"{tools}/venv"]
    r = subprocess.run(["bash", "-c", script, "x", *dirs], capture_output=True, text=True,
                       env={"PATH": f"{stub}:{os.environ['PATH']}"})
    assert r.stdout.split("\n")[:-1] == [f"refused {d}" for d in dirs[:7]] + [f"took {d}" for d in dirs[7:]], r.stdout


# ── npm_link_bins: root links what a package declares, and checks it first ───────────────────────────
pytestmark_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def _package(tools: pathlib.Path, name: str, dep: str, bin_field, files: dict[str, str] | None = None) -> pathlib.Path:
    d = tools / "npm" / name
    pd = d / "node_modules" / dep
    pd.mkdir(parents=True)
    (d / "package.json").write_text(json.dumps({"private": True, "dependencies": {dep: "1.0.0"}}))
    (pd / "package.json").write_text(json.dumps({"name": dep, "version": "1.0.0", "bin": bin_field}))
    for f, body in (files or {"cli.js": "#!/usr/bin/env node\n"}).items():
        (pd / f).parent.mkdir(parents=True, exist_ok=True)
        (pd / f).write_text(body)
        (pd / f).chmod(0o644)
    return d


def _link(tools: pathlib.Path, name: str) -> subprocess.CompletedProcess:
    return _bash(f'TOOLS="{tools}"\n{_func("npm_link_bins")}npm_link_bins "{name}" "$TOOLS/npm/{name}"')


@pytestmark_node
def test_a_package_gets_its_command_linked(tmp_path):
    tools = tmp_path / "t"
    _package(tools, "qwen", "@qwen-code/qwen-code", {"qwen": "cli.js"})
    r = _link(tools, "qwen")
    assert r.returncode == 0, r.stderr
    link = tools / "bin" / "qwen"
    assert os.readlink(link) == "../npm/qwen/node_modules/@qwen-code/qwen-code/cli.js"
    assert (tools / "npm/qwen/node_modules/@qwen-code/qwen-code/cli.js").stat().st_mode & 0o777 == 0o755


@pytestmark_node
def test_a_string_bin_is_named_after_the_package_without_its_scope(tmp_path):
    tools = tmp_path / "t"
    _package(tools, "pi", "@earendil-works/pi", "cli.js")
    assert _link(tools, "pi").returncode == 0
    assert (tools / "bin" / "pi").is_symlink()


@pytestmark_node
@pytest.mark.parametrize("cmd", ["../escape", "a/b", ".hidden", "..", "-rf", "x y"])
def test_a_command_that_is_not_a_plain_name_is_refused(tmp_path, cmd):
    tools = tmp_path / "t"
    _package(tools, "x", "x", {cmd: "cli.js"})
    r = _link(tools, "x")
    assert r.returncode != 0 and "not a plain name" in r.stderr
    assert not (tools / "bin").exists() or not any((tools / "bin").iterdir())
    assert not (tmp_path / "escape").exists()


@pytestmark_node
def test_a_file_outside_the_tree_is_neither_linked_nor_chmodded(tmp_path):
    outside = tmp_path / "outside"; outside.write_text("root's"); outside.chmod(0o600)
    tools = tmp_path / "t"
    _package(tools, "x", "x", {"x": "../../../../outside"})
    r = _link(tools, "x")
    assert r.returncode != 0 and "not inside" in r.stderr
    assert outside.stat().st_mode & 0o777 == 0o600
    # the same through a link the package planted inside its own tree
    tools2 = tmp_path / "t2"
    d = _package(tools2, "y", "y", {"y": "cli.js"}, files={"other.js": ""})
    (d / "node_modules/y/cli.js").symlink_to(outside)
    r = _link(tools2, "y")
    assert r.returncode != 0 and "not inside" in r.stderr
    assert outside.stat().st_mode & 0o777 == 0o600 and not (tools2 / "bin" / "y").exists()


@pytestmark_node
@pytest.mark.parametrize("cmd", ["sh", "env"])
def test_a_command_that_would_hide_one_of_the_images_is_refused(tmp_path, cmd):
    """The runner is root and finds git, tar, node and npm by name, with $TOOLS/bin first on its PATH."""
    tools = tmp_path / "t"
    _package(tools, "x", "x", {cmd: "cli.js"})
    r = _link(tools, "x")
    assert r.returncode != 0 and "would hide the image" in r.stderr
    assert not (tools / "bin" / cmd).exists()


@pytestmark_node
def test_another_bases_command_is_not_taken_over(tmp_path):
    tools = tmp_path / "t"
    (tools / "bin").mkdir(parents=True)
    (tools / "bin" / "opencode").write_text("a release binary"); (tools / "bin" / "opencode").chmod(0o755)
    os.symlink("../npm/qwen/node_modules/@qwen-code/qwen-code/cli.js", tools / "bin" / "qwen")
    _package(tools, "pi", "pi", {"opencode": "cli.js"})
    r = _link(tools, "pi")
    assert r.returncode != 0 and "another base" in r.stderr
    assert (tools / "bin" / "opencode").read_text() == "a release binary"
    shutil.rmtree(tools / "npm" / "pi")
    _package(tools, "pi", "pi", {"qwen": "cli.js"})
    r = _link(tools, "pi")
    assert r.returncode != 0 and "another base" in r.stderr
    assert os.readlink(tools / "bin" / "qwen") == "../npm/qwen/node_modules/@qwen-code/qwen-code/cli.js"


@pytestmark_node
def test_its_own_earlier_link_and_its_global_install_are_replaced(tmp_path):
    tools = tmp_path / "t"
    (tools / "bin").mkdir(parents=True)
    os.symlink("../lib/node_modules/@qwen-code/qwen-code/dist/cli.js", tools / "bin" / "qwen")
    _package(tools, "qwen", "@qwen-code/qwen-code", {"qwen": "cli.js"})
    assert _link(tools, "qwen").returncode == 0
    assert os.readlink(tools / "bin" / "qwen") == "../npm/qwen/node_modules/@qwen-code/qwen-code/cli.js"
