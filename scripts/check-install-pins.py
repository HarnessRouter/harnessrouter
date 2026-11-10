#!/usr/bin/env python3
"""What the image installs at first start is pinned, and stays pinned (#623).

docker/entrypoint.sh installs every agent CLI on the data volume at first start, as root. Each of
these lines would let what a volume runs move with an upstream, without a change here:

  releases/latest           a release asset that is whatever upstream published last
  npm install, no version   an npm package that is whatever the registry serves that day
  pip install, no ==        a PyPI requirement resolved fresh at install, unless the install is
                            --require-hashes from a lock, or a local file checked against a digest
  a fetched sums file       a SHA256SUMS downloaded from the same release as the asset proves the
                            transfer, not the build: a replaced release ships with a matching one
  curl | sh                 a vendor's install script, run as root

It also holds who runs an install (#623, step 3). In docker/entrypoint.sh, root never runs a package
manager on a base's tree, unpacks a downloaded archive, or runs a file out of an installed tree: npm
ci, npm rebuild, npm install, pip install, tar -x, node loading a package, and any command that is a
path into the tools tree or a venv run as the base's own install uid, written `iu <command>`.

The check reads the source, so it runs in the tests job with nothing installed. ALLOWED and ROOT_RUNS
name the lines that are known and accepted for now; each PR that fixes one removes it, and an entry
that no longer matches anything fails too, so the lists can only shrink.

  python3 scripts/check-install-pins.py [file ...]
"""
import os
import re
import sys
from typing import Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = ["docker/entrypoint.sh", "docker/install-skills.sh", "docker/install-kits.sh", "Dockerfile"]

# (file, a substring of the offending line, why it is accepted for now). Empty is the goal.
ALLOWED: list[tuple[str, str, str]] = [
    ("Dockerfile", "deb.nodesource.com/setup_22.x",
     "build time: NodeSource's apt setup script, run once in CI to add its signed apt repository"),
    ("Dockerfile", "pip install --no-cache-dir playwright",
     "build time, and only with WITH_BROWSER=1, which the published image does not set"),
    ("Dockerfile", "/app/gateway/req.local.txt",
     "build time: the gateway's and runner's requirements, version-pinned but not hashed"),
]

# (file, a substring of the line, why root still runs it). An entry is a step after a base's own
# install that runs its installed code as root: the package managers themselves all run as the install
# uid. Moving a step under `iu` removes its entry. Empty, since the last one went: System One's browser
# libraries came from `playwright install-deps` run as root, and come from apt with the list written in
# the entrypoint (CHROMIUM_LIBS, held to the pinned Playwright's by scripts/check-chromium-libs.py).
ROOT_RUNS: list[tuple[str, str, str]] = []

# The code a ROOT_RUNS entry runs, pinned here as well: the lock's entry for it, its version and every
# hash. A lock update that changes what root runs fails this check until the pin below changes with it,
# so the change shows in review next to the exception, never only as a regenerated lock. Empty while
# ROOT_RUNS is; an entry there needs one here.
ROOT_RUN_PINS: list[tuple[str, str, frozenset[str]]] = []

# npm itself, or npm_g (an `npm install -g --prefix $TOOLS`, gone since #623 step 3) called rather than defined.
NPM_INSTALL = re.compile(r"\bnpm\s+(?:install|i|add)\b|\bnpm_g\s+(?!\()")
# pip, however it is named: pip3, a venv's bin/pip in quotes, python -m pip.
PIP_INSTALL = re.compile(r"\bpip3?[\"']?\s+install\b|-m\s+pip\s+install\b")
FUNC_HEADER = re.compile(r"^\s*[\w-]+\s*\(\)\s*\{")


def logical_lines(text: str):
    """(first line number, joined text) for each logical shell line: backslash continuations joined,
    comments dropped, so a command is judged on all of its arguments."""
    out, buf, start = [], "", 0
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        stripped = line.lstrip()
        if not buf and (not stripped or stripped.startswith("#")):
            continue
        if not buf:
            start = n
        if line.endswith("\\"):
            buf += line[:-1] + " "
            continue
        buf += line
        # sh -c "...\"$X\" install ..." is a command too: judge it with its quotes unescaped.
        out.append((start, buf.replace('\\"', '"')))
        buf = ""
    if buf:
        out.append((start, buf))
    return out


def npm_unpinned(cmd: str) -> list[str]:
    """The package arguments of an npm install that carry no exact version."""
    bad = []
    m = NPM_INSTALL.search(cmd)
    if not m:
        return bad
    rest = cmd[m.end():]
    rest = re.split(r"\|\||&&|;|\||\s\)", rest)[0]
    for tok in rest.split():
        tok = tok.strip("'\"")
        if not tok or tok.startswith("-") or tok.startswith("$TOOLS") or tok in ('"$@"', "$@"):
            continue
        if tok.startswith(('"$', "$")) and ("tgz" in tok or "tar" in tok):
            continue  # a local tarball, checked against a digest before this line
        if re.search(r"\.(tgz|tar\.gz)\b", tok):
            continue
        name, _, ver = tok.rpartition("@") if tok.count("@") > (1 if tok.startswith("@") else 0) else (tok, "", "")
        if not ver:
            bad.append(tok)
            continue
        if ver in ("latest", "next") or re.search(r"[\^~*<>|x]|\s", ver) or ver.startswith(">="):
            bad.append(tok)
    return bad


def pip_unpinned(cmd: str) -> list[str]:
    """The requirement arguments of a pip install that are neither ==, nor hashed, nor a local file."""
    m = PIP_INSTALL.search(cmd)
    if not m:
        return []
    if "--require-hashes" in cmd:
        return []
    rest = re.split(r"\|\||&&|;|\|", cmd[m.end():])[0]
    toks = re.findall(r"'[^']*'|\"[^\"]*\"|\S+", rest)
    bad, skip = [], False
    for raw in toks:
        tok = raw.strip("'\"")
        if skip:
            skip = False
            continue
        if tok in ("-r", "-c", "--requirement", "--constraint", "-d", "--target", "-t", "--prefix"):
            skip = True  # the next token is the file or directory, judged here, not as a requirement
            if tok in ("-r", "--requirement"):
                bad.append("-r " + "(a requirements file without --require-hashes)")
            continue
        if not tok or re.match(r"^\d*[<>]", tok):
            continue  # a redirection (>/dev/null, 2>&1), or nothing; a requirement starts with its name
        if tok.startswith("-") or tok.startswith('"${') and tok.endswith('[@]}"'):
            continue
        if tok.startswith("${") and tok.endswith("[@]}"):
            continue
        if tok in ("$@", '"$@"'):
            continue
        if re.search(r"\.whl$", tok) or tok.startswith(("$qd_whl", "$cc_whl", "$sq_tmp")):
            continue  # a wheel downloaded and checked against a committed digest first
        if "git+" in tok:
            if not re.search(r"@[0-9a-f]{40}\b", tok) and "${SYSTEMONE_REF}" not in tok:
                bad.append(tok)
            continue
        if tok.startswith('"$') or tok.startswith("$"):
            # a whole requirement in a variable: judged where the variable is set
            if not re.fullmatch(r"\$\{?[A-Z_]+\}?", tok.strip('"')):
                bad.append(tok)
            continue
        if "==" not in tok:
            bad.append(tok)
    return bad


def check_text(path: str, text: str) -> list[tuple[str, int, str, str]]:
    found = []
    for n, line in logical_lines(text):
        if re.match(r"\s*(echo|printf)\b", line):
            continue  # a message about a command, not the command
        line = FUNC_HEADER.sub("", line)
        if "releases/latest" in line:
            found.append((path, n, "a release asset by `latest`", line))
        if re.search(r"curl\b[^|]*\|\s*(ba|z|da)?sh\b", line) or re.search(r"\bsh\s+-c\s+\"\$\(curl", line):
            found.append((path, n, "a remote script piped into a shell", line))
        if re.search(r"(curl|wget)\b.*(SHA256SUMS|sha256sums|checksums\.txt|\.sha256\b)", line):
            found.append((path, n, "a sums file fetched beside the asset", line))
        for tok in npm_unpinned(line):
            found.append((path, n, f"npm install of {tok} without an exact version", line))
        for tok in pip_unpinned(line):
            found.append((path, n, f"pip install of {tok} without == or --require-hashes", line))
    return found


# ── who runs it ──────────────────────────────────────────────────────────────────────────────────
# A word that runs a package manager, unpacks an archive (as root, a crafted entry or a tar bug reaches
# anything), or runs a file out of an installed tree: a path under $TOOLS or a venv's bin, held in
# quotes or not. `-m pip` is judged by the interpreter before it.
_PATHWORD = r"\"?\$\{?(?:TOOLS\}?/[^\s\"]*|\w*venv\}?/bin/[^\s\"]*)\"?"
_RUNNER = re.compile(rf"(?P<w>{_PATHWORD}|\bnpm\s+(?:ci|rebuild|install|i|add|exec|run|x)\b|\bnpx\b|\bpip3?\s+install\b"
                     r"|\btar\s+(?:-[A-Za-z]*x[A-Za-z]*|x[A-Za-z]*|--extract)\b)")
# What may come before a word for the word to be the command: the start of the line or of a command,
# then any VAR=value assignments.
_CMD_START = re.compile(r"(?:^|[;&|(!{`]|\$\(|\b(?:then|do|else|if|while|until|exec)\b)\s*$")
_ASSIGN = re.compile(r"\b[A-Za-z_]\w*=(?:\"[^\"]*\"|'[^']*'|(?:(?!\$\()\S)*)\s*$")
# node loading a package by name (not one of node's own modules) out of an installed tree
_NODE_PKG = re.compile(r"\bnode\s+-[ep]\b.*\brequire\(\s*[\"'](?!(?:node:)?(?:fs|path|os|child_process|util)[\"'])[^\"']+[\"']")


def _as_root(prefix: str, after: str) -> bool:
    """True when the word between <prefix> and <after> is a command that runs as root (not after `iu`).
    A value being assigned (X="$TOOLS/...") and a case pattern ("$TOOLS/bin"|...) are not commands."""
    if prefix.endswith("=") or re.match(r"[*?]*[|)]", after):
        return False
    prefix = re.sub(r"\"\$\($", "$(", prefix.rstrip())
    while True:   # VAR=value assignments, and a launcher that runs the word as the same user
        m = _ASSIGN.search(prefix) or re.search(r"\b(?:env|nohup|setsid|nice|timeout\s+\S+)$", prefix)
        if not m:
            break
        prefix = prefix[:m.start()].rstrip()
    if re.search(r"(?:^|\s|[;&|(!{`])iu$", prefix):
        return False
    return bool(_CMD_START.search(prefix))


def root_runs_text(path: str, text: str) -> list[tuple[str, int, str, str]]:
    """The lines of the entrypoint where root runs what an install brought, rather than `iu`."""
    if not path.endswith("entrypoint.sh"):
        return []
    found = []
    for n, line in logical_lines(text):
        if re.match(r"\s*(echo|printf)\b", line):
            continue
        line = FUNC_HEADER.sub("", line)
        for m in _RUNNER.finditer(line):
            word = m.group("w")
            if _as_root(line[:m.start()], line[m.end():]):
                found.append((path, n, f"root runs {word.strip(chr(34))} (not `iu`)", line))
        if _NODE_PKG.search(line) and not re.search(r"\biu\s+node\b", line):
            found.append((path, n, "root runs node on an installed package (not `iu`)", line))
    return found


def lock_entry(text: str, name: str) -> "Optional[tuple[str, frozenset[str]]]":
    """(name==version, its hashes) for one package of a hashed pip lock, or None if it isn't there."""
    m = re.search(rf"^({re.escape(name)}==\S+)((?:\s*\\\n\s*--hash=sha256:[0-9a-f]{{64}})+)", text, re.M | re.I)
    if not m:
        return None
    return m.group(1), frozenset(re.findall(r"--hash=sha256:([0-9a-f]{64})", m.group(2)))


def root_run_pins() -> list[str]:
    """What differs between ROOT_RUN_PINS and the locks: each line is a reason to fail."""
    out = []
    if ROOT_RUN_PINS and not ROOT_RUNS:
        out.append("ROOT_RUN_PINS pins code no ROOT_RUNS entry runs any more: remove the pins too")
    if ROOT_RUNS and not ROOT_RUN_PINS:
        out.append("ROOT_RUNS names a step root runs with nothing in ROOT_RUN_PINS: pin the lock entry of what it runs")
    for rel, want, hashes in ROOT_RUN_PINS:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            out.append(f"{rel}: the lock ROOT_RUN_PINS names is gone")
            continue
        with open(p, encoding="utf-8") as f:
            got = lock_entry(f.read(), want.split("==")[0])
        if got is None:
            out.append(f"{rel}: no hashed entry for {want.split('==')[0]}")
        elif got != (want, hashes):
            out.append(f"{rel}: {got[0]} with {len(got[1])} hashes is not the {want} with {len(hashes)} hashes that "
                       "ROOT_RUN_PINS allows root to run: change the pin in the same review, or move the step under `iu`")
    return out


def run(files: list[str]) -> int:
    found, root_found = [], []
    for rel in files:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            text = f.read()
        found += check_text(rel, text)
        root_found += root_runs_text(rel, text)
    bad, stale = [], []
    for items, allowed, label in ((found, ALLOWED, "ALLOWED"), (root_found, ROOT_RUNS, "ROOT_RUNS")):
        used = set()
        for item in items:
            hit = next((a for a in allowed if a[0] == item[0] and a[1] in item[3]), None)
            if hit:
                used.add(hit)
            else:
                bad.append(item)
        stale += [(label, a) for a in allowed if a not in used]
    for path, n, why, line in bad:
        print(f"{path}:{n}: {why}\n    {line.strip()[:200]}")
    for label, a in stale:
        print(f"{label} entry matches nothing any more, remove it: {a[0]}: {a[1]!r}")
    pins = root_run_pins()
    for line in pins:
        print(line)
    if bad or stale or pins:
        return 1
    tail = (f"except {len(ROOT_RUNS)} step{'s' if len(ROOT_RUNS) != 1 else ''} named in ROOT_RUNS" if ROOT_RUNS
            else "and ROOT_RUNS is empty")
    print(f"install pins hold ({len(files)} files, {len(ALLOWED)} allowed exceptions); root runs nothing an install brought, {tail}")
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:] or FILES))
