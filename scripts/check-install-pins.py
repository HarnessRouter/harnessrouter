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

The check reads the source, so it runs in the tests job with nothing installed. ALLOWED names the
lines that are known and accepted for now; each PR that pins one removes it, and an entry that no
longer matches anything fails too, so the list can only shrink.

  python3 scripts/check-install-pins.py [file ...]
"""
import os
import re
import sys

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

# npm itself, or npm_g (entrypoint.sh's `npm install -g --prefix $TOOLS`) called rather than defined.
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
    rest = re.split(r"\|\||&&|;|\|", rest)[0]
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


def run(files: list[str]) -> int:
    found = []
    for rel in files:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            found += check_text(rel, f.read())
    used, bad = set(), []
    for item in found:
        hit = next((a for a in ALLOWED if a[0] == item[0] and a[1] in item[3]), None)
        if hit:
            used.add(hit)
        else:
            bad.append(item)
    for path, n, why, line in bad:
        print(f"{path}:{n}: {why}\n    {line.strip()[:200]}")
    stale = [a for a in ALLOWED if a not in used]
    for a in stale:
        print(f"ALLOWED entry matches nothing any more, remove it: {a[0]}: {a[1]!r}")
    if bad or stale:
        return 1
    print(f"install pins hold ({len(files)} files, {len(ALLOWED)} allowed exceptions)")
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:] or FILES))
