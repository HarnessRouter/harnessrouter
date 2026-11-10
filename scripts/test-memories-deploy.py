#!/usr/bin/env python3
"""deploy/memories/up.sh, the parts that need no Docker: the real functions, cut from the script and run here.

- .env is written at mode 600, one line per key, and a value comes back exactly as it went in;
- a running HarnessRouter is told apart by its image's name, and this stack's own containers never are;
- what runs inside the HarnessRouter container is valid Python, and the script is valid bash;
- the image carries deploy/memories but never a .env from it, and each engine calls models with its own
  credential, on a network that outlives the engines.
The whole flow, with Docker, is run by hand: see the Memories section of docs/self-hosting-guide.md."""
import os
import re
import stat
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
UP = os.path.join(ROOT, "deploy", "memories", "up.sh")
src = open(UP).read()
bad = []


def check(ok: bool, what: str) -> None:
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        bad.append(what)


def func(name: str) -> str:
    m = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n|^{name}\(\) \{{[^\n]*\}}\n", src, re.S | re.M)
    if not m:
        sys.exit(f"up.sh has no {name}()")
    return m.group(0)


check(subprocess.run(["bash", "-n", UP]).returncode == 0, "up.sh is valid bash")
check(bool(os.stat(UP).st_mode & stat.S_IXUSR), "up.sh is executable")

py = re.search(r"^HR_PY='\n(.*?)^'\n", src, re.S | re.M)
check(bool(py) and "'" not in py.group(1), "the in-container Python is one single-quoted block")
try:
    compile(py.group(1), "HR_PY", "exec")
    check(True, "the in-container Python compiles")
except SyntaxError as e:
    check(False, f"the in-container Python compiles ({e})")

# .env: mode 600, replaced in place, appended when new, values kept byte for byte
with tempfile.TemporaryDirectory() as d:
    env = os.path.join(d, ".env")
    with open(env, "w") as f:
        f.write("# a comment\nKEEP=1\nMEM0_MODEL_KEY=old\n")
    os.chmod(env, 0o644)
    odd = r"a&b/c\nd=e $f"
    script = (f'HERE="{d}"\nENV_FILE="{env}"\n' + func("env_get") + func("env_set")
              + 'env_set MEM0_MODEL_KEY "$1"\nenv_set NEW_KEY two\nenv_get MEM0_MODEL_KEY\n')
    out = subprocess.run(["bash", "-c", script, "bash", odd], capture_output=True, text=True)
    lines = open(env).read().splitlines()
    check(out.stdout.rstrip("\n") == odd, "env_set then env_get gives the value back exactly" + (f" ({out.stderr.strip()})" if out.stderr else ""))
    check(lines == ["# a comment", "KEEP=1", f"MEM0_MODEL_KEY={odd}", "NEW_KEY=two"], "other lines stay, a key is replaced in place, a new one is added")
    check(stat.S_IMODE(os.stat(env).st_mode) == 0o600, ".env is mode 600 after a write")
    check(not [n for n in os.listdir(d) if n != ".env"], "no temporary file is left beside .env")

# the HarnessRouter container, by image name, when no container carries the label
awk = re.search(r"awk -v me=\"\$NAME\" '(.*?)'\)\"", src, re.S)
check(bool(awk), "find_hr matches image names with awk")
rows = {
    "hr1 harnessrouter/harnessrouter:0.40.0 ": True,
    "hr2 harnessrouter:local ": True,
    "hr3 ghcr.io/acme/harnessrouter@sha256:0123 ": True,
    "hr4 harnessrouter/harnessrouter ": True,
    "e1 harnessrouter-memories-mem0 harnessrouter-memories": False,
    "e2 ghcr.io/vectorize-io/hindsight:latest harnessrouter-memories": False,
    "e3 harnessrouter/harnessrouter:0.40.0 harnessrouter-memories": False,
    "o1 acme/harnessrouter-proxy:1 ": False,
    "o2 postgres:17 ": False,
}
got = subprocess.run(["awk", "-v", "me=harnessrouter-memories", awk.group(1)], input="\n".join(rows) + "\n",
                     capture_output=True, text=True).stdout.split()
check(got == [r.split()[0] for r, want in rows.items() if want], f"picked {got}: HarnessRouter images only, never this stack's")

# the image, the compose file and .dockerignore agree with up.sh
dockerfile = open(os.path.join(ROOT, "Dockerfile")).read()
ignore = open(os.path.join(ROOT, ".dockerignore")).read().split()
compose = open(os.path.join(ROOT, "deploy", "memories", "docker-compose.yml")).read()
check("COPY deploy/memories/ /app/deploy/memories/" in dockerfile, "the image carries deploy/memories at /app/deploy/memories")
check("LABEL io.harnessrouter.role=instance" in dockerfile and "io.harnessrouter.role=instance" in src, "the image's label is the one up.sh looks for")
check("**/.env" in ignore and "**/.env.*" in ignore, "a .env at any depth stays out of the image")
for eng in ("MEM0", "GRAPHITI", "HINDSIGHT", "REME"):
    check(f"${{OPENAI_API_KEY:-${{{eng}_MODEL_KEY:-}}}}" in compose, f"{eng.lower()} calls models with its own credential, or your own key")
check(re.search(r"networks:\n  default:\n    name: \$\{HR_MEMORIES_NAME:-harnessrouter-memories\}\n    external: true", compose) is not None,
      "the network is made by up.sh and kept when the engines stop")
for eng, port in (("mem0", 8000), ("graphiti", 8000), ("hindsight", 8888), ("reme", 2333)):
    check(f"{eng}) echo http://{eng}:{port}" in src, f"up.sh's address for {eng} is :{port}")

if bad:
    sys.exit(f"{len(bad)} check(s) failed")
print("deploy/memories holds")
