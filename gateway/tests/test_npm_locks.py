"""The npm bases' lockfiles (#623, step 2, the npm half) and the pins in docker/entrypoint.sh describe
the same packages.

A base installs from its lock only when the entrypoint's spec equals the lock's package.json, so a pin
bumped in one place and not the other fails nothing at install: every volume quietly drops to an
unverified `npm install -g`. These tests make that a failure here instead."""
import json
import os
import re
import subprocess

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
ENTRYPOINT = os.path.join(ROOT, "docker", "entrypoint.sh")
LOCKS = os.path.join(ROOT, "docker", "locks", "npm")
SRC = open(ENTRYPOINT).read()

# lock name -> the entrypoint variable holding its spec
SPECS = {
    "claude": "CLAUDE_SPEC", "qwen": "QWEN_SPEC", "gemini": "GEMINI_SPEC", "cline": "CLINE_SPEC",
    "codex": "CODEX_SPEC", "pi": "PI_SPEC", "pi-mcp-adapter": "PI_MCP_SPEC", "mimo": "MIMO_SPEC",
    "minimax": "MINIMAX_SPEC",
}


def assignments() -> str:
    """Every line of the entrypoint that sets a pin or a spec, in order, for bash to evaluate."""
    keep = re.compile(r"^(export )?[A-Z_]+(_PIN|_VERSION|_SPEC|_URL)=")
    return "\n".join(line for line in SRC.splitlines() if keep.match(line))


def default_specs() -> dict[str, str]:
    script = assignments() + "\n" + "\n".join(f'echo "{v}=${v}"' for v in SPECS.values())
    out = subprocess.run(["env", "-i", "bash", "-c", script], capture_output=True, text=True, check=True).stdout
    return dict(line.split("=", 1) for line in out.splitlines())


def lock_spec(name: str) -> str:
    deps = json.load(open(os.path.join(LOCKS, name, "package.json")))["dependencies"]
    return " ".join(f"{k}@{v}" for k, v in deps.items())


def lock(name: str) -> dict:
    return json.load(open(os.path.join(LOCKS, name, "package-lock.json")))


def test_every_lock_dir_is_used():
    assert sorted(os.listdir(LOCKS)) == sorted(SPECS)


@pytest.mark.parametrize("name", sorted(SPECS))
def test_default_spec_is_the_lock(name):
    assert default_specs()[SPECS[name]] == lock_spec(name)


@pytest.mark.parametrize("name", sorted(SPECS))
def test_lock_matches_its_package_json(name):
    lk = lock(name)
    assert lk["lockfileVersion"] == 3
    assert lk["packages"][""]["dependencies"] == json.load(open(os.path.join(LOCKS, name, "package.json")))["dependencies"]


@pytest.mark.parametrize("name", sorted(SPECS))
def test_every_package_is_fetched_by_url_and_digest(name):
    """No link, path or git dependency: `npm ci` installs those without an integrity check."""
    for key, entry in lock(name)["packages"].items():
        if not key:
            continue
        assert key.startswith("node_modules/"), key
        assert entry.get("resolved", "").startswith("https://"), key
        assert entry.get("integrity", "").startswith("sha512-"), key
        # The registry, or for minimax's own package the release archive its spec names; no other
        # host and no git or github: shorthand.
        if name == "minimax" and key == "node_modules/@minimax-ai/code":
            assert entry["resolved"] == default_specs()["MINIMAX_SPEC"].split("@", 2)[2], key
        else:
            assert entry["resolved"].startswith("https://registry.npmjs.org/"), key


@pytest.mark.parametrize("name", sorted(SPECS))
def test_musl_builds_carry_libc(name):
    """npm 10 skips a package whose lock entry names another libc, and writes no libc itself
    (scripts/lock-npm.sh adds it, from the registry or from the lock's libc.json). Without it,
    `npm ci` installs every musl build on glibc."""
    musl = [(k, e) for k, e in lock(name)["packages"].items()
            if e.get("os") == ["linux"] and "musl" in k.rsplit("/", 1)[-1]]
    if name in ("claude", "qwen", "pi-mcp-adapter", "minimax", "mimo"):
        assert musl, "this lock was expected to hold musl builds"
    for key, entry in musl:
        assert entry.get("libc") == ["musl"], key


@pytest.mark.parametrize("name", sorted(SPECS))
def test_libc_json_is_in_the_lock(name):
    """A libc.json entry is a statement about a package the lock holds, applied to it."""
    path = os.path.join(LOCKS, name, "libc.json")
    if not os.path.exists(path):
        return
    packages = lock(name)["packages"]
    for pkg, libc in json.load(open(path)).items():
        entry = packages.get(f"node_modules/{pkg}")
        assert entry is not None, pkg
        assert entry.get("libc") == libc, pkg


def test_minimax_sqlite_binding_is_the_locks_version():
    pin = re.search(r'^MINIMAX_SQLITE_PIN="([^"]+)"', SRC, re.M).group(1)
    assert lock("minimax")["packages"]["node_modules/better-sqlite3"]["version"] == pin


def test_no_npm_base_installs_with_npm_g_directly():
    """The global install is the override path only (npm_unlocked); a base calling npm_g itself
    would install unlocked even at the default pin."""
    calls = [line.strip() for line in SRC.splitlines()
             if re.search(r"\bnpm_g\s", line) and not line.strip().startswith(("#", "npm_g()"))]
    assert calls == ['npm_g "$@"']


def test_npm_ci_runs_no_install_scripts():
    assert '( cd "$nl_dir" && npm ci --ignore-scripts --no-audit --no-fund )' in SRC
    # The scripts that do run are named, one call each.
    assert re.findall(r"install_npm \w+ \"\$\w+\" (@[^\s;]+)", SRC) == ["@anthropic-ai/claude-code"]


def test_the_one_install_script_is_claudes():
    """Every locked npm install runs with --ignore-scripts; the only package whose own script runs is
    Claude Code's (npm rebuild of exactly that package). A second name, on install_npm or on a direct
    npm_locked call, or a second rebuild, fails here rather than widening what runs as root."""
    code = "\n".join(l for l in SRC.splitlines() if not l.lstrip().startswith("#"))
    calls = re.findall(r"\b(?:install_npm \w+ \"\$\w+\"|npm_locked [\w-]+)([^;|)\n]*)", code)
    extra = [c.split("||")[0].strip() for c in calls]
    assert [e for e in extra if e] == ["@anthropic-ai/claude-code"], calls
    assert len(re.findall(r"\bnpm rebuild\b", code)) == 1
    assert len(re.findall(r"\bnpm ci\b", code)) == 1 and "npm ci --ignore-scripts" in code
