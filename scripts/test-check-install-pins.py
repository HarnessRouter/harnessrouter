#!/usr/bin/env python3
"""The install-pin check has to be able to fail: a check that passes everything is worse than none.
Each line below is one way a first-start install has moved with an upstream (most of them were in
docker/entrypoint.sh until #623), and each has to be caught; the pinned forms beside them must not."""
import contextlib
import importlib.util
import io
import os

here = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("cip", os.path.join(here, "check-install-pins.py"))
cip = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cip)
REAL_ROOT_RUNS, REAL_ROOT_RUN_PINS = list(cip.ROOT_RUNS), list(cip.ROOT_RUN_PINS)


def caught(src: str) -> list[str]:
    return [why for _, _, why, _ in cip.check_text("t.sh", src)]


BAD = {
    "latest asset": 'oc_url="https://github.com/anomalyco/opencode/releases/latest/download/opencode-linux-x64.tar.gz"',
    "fetched sums": 'curl -fsSL "$omp_base/SHA256SUMS.txt" -o "$omp_tmp/SHA256SUMS.txt" || return 1',
    "fetched .sha256": 'curl -fsSL "$url.sha256" -o x.sha256',
    "curl | sh": "curl -fsSL https://example.com/install.sh | sh",
    "curl | bash -": "curl -fsSL https://example.com/setup | bash -",
    "npm, no version": 'try_install "Qwen Code" npm install -g --prefix "$TOOLS" --no-audit --no-fund @qwen-code/qwen-code || true',
    "npm, continued line": 'try_install "Pi" npm install -g --prefix "$TOOLS" --ignore-scripts \\\n    @earendil-works/pi-coding-agent || true',
    "npm, latest tag": "npm install -g foo@latest",
    "npm, a range": "npm install -g 'foo@^1.2.0'",
    "npm_g, no version": 'install_base qwen "Qwen Code" npm_g @qwen-code/qwen-code || true',
    "pip, bare name": '"$TOOLS/venv/bin/pip" install --no-cache-dir -q boto3 >/dev/null 2>&1 || true',
    "pip, a range": "\"$TOOLS/venv/bin/pip\" install 'mcp>=1.9,<2'",
    "pip in sh -c": 'sh -c "\\"$TOOLS/venv/bin/pip\\" install --no-cache-dir -q \'hermes-agent[anthropic]==0.19.0\' boto3"',
    "pip, unhashed -r": '"$V/bin/pip" install -q -r "$tmp/requirements.txt"',
    "pip, a git tag": 'pip install "pkg @ git+https://github.com/o/r@v0.4.0"',
    "pip3": "pip3 install requests",
    "python -m pip": "python3 -m pip install requests",
}
GOOD = {
    "pinned asset": 'curl -fsSL "https://github.com/o/r/releases/download/v${PIN}/x.tar.gz" -o "$t/x.tar.gz"',
    "npm, exact": 'npm install -g --prefix "$TOOLS" --no-audit --no-fund "@openai/codex@$CODEX_PIN"',
    "npm, exact literal": "npm install -g cline@3.0.60",
    "npm_g, exact": 'install_base pi "Pi" npm_g --ignore-scripts "@earendil-works/pi-coding-agent@$PI_PIN"',
    "npm_g definition": 'npm_g() { npm install -g --prefix "$TOOLS" --no-audit --no-fund "$@"; }',
    "npm, local tarball": 'npm install -g --prefix "$TOOLS" --include=optional "$mm_tgz"',
    "npm, an override's arguments in a subshell": '( cd "$nu_dir" && iu npm install --no-audit --no-fund "$@" ) || return 1',
    "pip, ==": '"$TOOLS/venv/bin/pip" install -q "boto3==$HERMES_BOTO3_PIN" "mcp==$HERMES_MCP_PIN"',
    "pip, hashed lock": '"$lv_venv/bin/pip" install -q --require-hashes --no-deps -r "$lv_lock"',
    "pip, checked wheel": '"$TOOLS/qoder-venv/bin/pip" install -q --disable-pip-version-check "$qd_whl"',
    "pip, commit": 'pip install "pkg @ git+https://github.com/o/r@3266a17537e283dc5539439835c0b4cab02bf5c0"',
    "pip download": '"$V/bin/pip" download -q --no-deps -d "$t" "qca-sdk==$QODER_PIN"',
    "a message": 'echo "skills: pip install $(echo "$PIPREQ")"',
    "a comment": "# npm install -g foo, which this used to do",
}

for name, src in BAD.items():
    assert caught(src), f"not caught: {name}: {src}"
for name, src in GOOD.items():
    assert not caught(src), f"wrongly caught: {name}: {caught(src)}"


# Root runs nothing an install brought (#623, step 3): each of these ran as root in the entrypoint
# until then, and each must be caught; the same steps through `iu`, and root's own uses of a tools path
# (a test, an assignment, a removal, a case pattern, a message), must not.
def root_runs(src: str) -> list[str]:
    return [why for _, _, why, _ in cip.root_runs_text("docker/entrypoint.sh", src)]


ROOT_BAD = {
    "a venv's python": """  "$TOOLS/venv/bin/python" -c 'import boto3' || return 1""",
    "in a substitution": """  _hmt=$("$TOOLS/venv/bin/python" -c "print(1)" 2>/dev/null) || _hmt=\"\"""",
    "in a quoted substitution": """  jc_got="$("$TOOLS/bin/jcode" --version 2>/dev/null | awk '{print $2}')\"""",
    "after an assignment": """  mimo_got="$(HOME="$mimo_warm" "$TOOLS/bin/mimo" --version 2>/dev/null | head -n 1)\"""",
    "assignment then command": """  HOME="$TOOLS/dcode-venv" "$TOOLS/dcode-venv/bin/dcode" tools install --json""",
    "through env": """  env HOME=/tmp/x "$TOOLS/bin/x" --version""",
    "after cd": """  ( cd "$TOOLS/agentzero-src" && "$TOOLS/agentzero-venv/bin/python" -c 'import agent' )""",
    "npm ci": """  ( cd "$nl_dir" && npm ci --ignore-scripts --no-audit --no-fund ) || return 1""",
    "npm rebuild": """  ( cd "$nl_dir" && npm rebuild --foreground-scripts "$@" ) || return 1""",
    "npm install -g": """npm_g() { npm install -g --prefix "$TOOLS" --no-audit --no-fund "$@"; }""",
    "a venv variable's pip": """  "$lv_venv/bin/pip" install -q --require-hashes -r "$lv_lock" || return 1""",
    "node loading a package": """  ( cd "$TOOLS/npm/minimax" && node -e 'new (require("better-sqlite3"))(":memory:")' )""",
    "in an if": """  if "$TOOLS/bin/x" --version; then :; fi""",
    "root's tar": """  tar -xzf "$oc_tmp/opencode.tar.gz" --no-same-owner -C "$oc_tmp" || return 1""",
    "root's tar, old style": """  mkdir "$km_tmp/x" && tar xzf "$km_tmp/kimi.tar.gz" -C "$km_tmp/x" """,
    "playwright install-deps": """  "$TOOLS/systemone-venv/bin/playwright" install-deps chromium >/dev/null 2>&1 || return 1""",
}
ROOT_GOOD = {
    "iu, a venv's python": """  iu "$TOOLS/venv/bin/python" -c 'import boto3' || return 1""",
    "iu in a substitution": """  _hmt=$(iu "$TOOLS/venv/bin/python" -c "print(1)" 2>/dev/null) || _hmt=\"\"""",
    "iu in a quoted substitution": """  jc_got="$(iu "$TOOLS/bin/jcode" --version 2>/dev/null | awk '{print $2}')\"""",
    "iu env": """  iu env HOME="$TOOLS/dcode-venv" "$TOOLS/dcode-venv/bin/dcode" tools install --json""",
    "iu npm ci": """  ( cd "$nl_dir" && iu npm ci --ignore-scripts --no-audit --no-fund ) || return 1""",
    "iu pip": """  iu "$lv_venv/bin/pip" install -q --require-hashes -r "$lv_lock" || return 1""",
    "iu node": """  ( cd "$TOOLS/npm/minimax" && iu node -e 'new (require("better-sqlite3"))(":memory:")' )""",
    "a test": """  [ -x "$TOOLS/bin/qwen" ] && [ ! -L "$TOOLS/venv/bin/python" ]""",
    "an assignment": """  nl_src="$HR_LOCKS_DIR/npm/$nl_name"; nl_dir="$TOOLS/npm/$nl_name\"""",
    "an export": """  export HR_DSH_PYTHON="$TOOLS/dsh-venv/bin/python\"""",
    "a removal": """  rm -rf "$TOOLS/venv" "$TOOLS/bin/qwen\"""",
    "a case pattern": """    "$TOOLS/bin"|"$TOOLS/bin/"*|"$TOOLS/lib") echo shared ;;""",
    "a message": """  echo "[harnessrouter] installed $TOOLS/bin/qwen\"""",
    "node reading json": """  node -e 'const d=require(process.argv[1]).dependencies' "$f\"""",
    "node's own modules": """  node -e 'const fs = require("fs"), path = require("path");' """,
    "the image's python making a venv": """  "$PY" -I -m venv "$TOOLS/venv\"""",
    "iu tar": """  iu tar -xzf - --no-same-owner -C "$ut_dir" "$@" < "$ut_archive"; ut_rc=$?""",
    "tar listing": """  tar -tzf "$x" | head -1""",
    "apt, the image's": """  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends "${CHROMIUM_LIBS[@]}" 2>&1)"; then""",
}
for name, src in ROOT_BAD.items():
    assert root_runs(src), f"root run not caught: {name}: {src}"
for name, src in ROOT_GOOD.items():
    assert not root_runs(src), f"wrongly caught as a root run: {name}: {root_runs(src)}"

# An allowance that matches nothing fails the run, so the list can only shrink.
cip.ALLOWED = [("docker/entrypoint.sh", "a line that is not there", "stale")]
with contextlib.redirect_stdout(io.StringIO()) as out:
    assert cip.run(["docker/entrypoint.sh"]) == 1
assert "matches nothing" in out.getvalue()
cip.ALLOWED = []
cip.ROOT_RUNS = [("docker/entrypoint.sh", "a line that is not there", "stale")]
with contextlib.redirect_stdout(io.StringIO()) as out:
    assert cip.run(["docker/entrypoint.sh"]) == 1
assert "ROOT_RUNS entry matches nothing" in out.getvalue()

# What a ROOT_RUNS entry runs is pinned too: a lock whose entry for it changes fails until the pin does.
# Both lists are empty now (the last entry, playwright install-deps, went with the apt list), so the
# mechanism is exercised with a pin made from a committed lock's entry; it has to keep failing for the
# day an entry comes back.
import tempfile
assert REAL_ROOT_RUNS == [] and REAL_ROOT_RUN_PINS == [], "root runs something an install brought; the lists only shrink"
rel = "docker/locks/systemone.lock.txt"
with open(os.path.join(cip.ROOT, rel), encoding="utf-8") as f:
    lock = f.read()
name = "playwright"
want, hashes = cip.lock_entry(lock, name) or (None, None)
assert want and hashes, f"{rel} has no hashed entry for {name} to make the test pin from"
one = sorted(hashes)[0]
TAMPERED = {
    "a hash replaced": lock.replace(one, "0" * 64),
    "a hash dropped": lock.replace(f" \\\n    --hash=sha256:{one}", ""),
    "a version bump": lock.replace(want + " \\", name + "==9.9.9 \\"),
    "the entry gone": lock.replace(want, name + "x==1.0"),
}
cip.ROOT_RUNS = [("docker/entrypoint.sh", "x", "y")]
with tempfile.TemporaryDirectory() as td:
    for label, text in TAMPERED.items():
        assert text != lock, f"the tamper did nothing: {label}"
        path = os.path.join(td, "lock.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        cip.ROOT_RUN_PINS = [(path, want, hashes)]
        assert cip.root_run_pins(), f"a changed lock passed: {label}"
    path = os.path.join(td, "lock.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(lock)
    cip.ROOT_RUN_PINS = [(path, want, hashes)]
    assert not cip.root_run_pins(), cip.root_run_pins()
# the two lists go together: pins with no step, and a step with no pin, both fail
cip.ROOT_RUNS = []
assert any("no ROOT_RUNS entry" in r for r in cip.root_run_pins()), "pins outlived their exception"
cip.ROOT_RUNS = [("docker/entrypoint.sh", "x", "y")]
cip.ROOT_RUN_PINS = []
assert any("nothing in ROOT_RUN_PINS" in r for r in cip.root_run_pins()), "a root run with no pin passed"
cip.ROOT_RUNS, cip.ROOT_RUN_PINS = [], []
assert not cip.root_run_pins()

print(f"install-pin check: {len(BAD)} unpinned forms caught, {len(GOOD)} pinned forms passed; "
      f"{len(ROOT_BAD)} root runs caught, {len(ROOT_GOOD)} uses passed; {len(TAMPERED)} changed locks caught; "
      "ROOT_RUNS and ROOT_RUN_PINS are empty")
