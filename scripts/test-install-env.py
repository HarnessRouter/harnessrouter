#!/usr/bin/env python3
"""What an installer's processes can read of the container's environment (#623 step 3, its environment
half). docker/entrypoint.sh's try_install runs each base's install with every variable outside a fixed
allow-list taken off the export list. Here the real functions, cut from the entrypoint, run an install
that is a child process printing its own environment, under the secrets the container holds and a
sample of what an operator passes with -e. None of them may reach it; what fetching and building need
must; and the install's own shell must still read every value (only the export is taken away)."""
import os
import re
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(here, "..", "docker", "entrypoint.sh")).read()


def func(name: str) -> str:
    m = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", src, re.S | re.M)
    if not m:
        sys.exit(f"docker/entrypoint.sh has no {name}()")
    return m.group(0)


SECRETS = {
    "HARNESS_INTERNAL_KEY": "internal-key-not-real", "HR_AUTH_PASSWORD": "console-password-not-real",
    "HR_SECRET_KEY": "store-key-not-real", "OPENAI_API_KEY": "sk-not-real", "ANTHROPIC_API_KEY": "sk-ant-not-real",
    "AZURE_OPENAI_API_KEY": "az-not-real", "GITHUB_TOKEN": "ghp-not-real", "HF_TOKEN": "hf-not-real",
    "AWS_SECRET_ACCESS_KEY": "aws-not-real", "AWS_SESSION_TOKEN": "aws-session-not-real",
    "CLIENT_SECRET": "client-secret-not-real", "BROWSER_USE_API_KEY": "bu-not-real", "HR_AUTH_USER": "operator",
}
KEPT = {
    "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": "/root", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
    "HTTPS_PROXY": "http://proxy.example:3128", "no_proxy": "localhost", "SSL_CERT_FILE": "/etc/ssl/certs/ca.pem",
    "NODE_EXTRA_CA_CERTS": "/etc/ssl/certs/ca.pem", "PIP_INDEX_URL": "https://pypi.example/simple",
    "NPM_CONFIG_REGISTRY": "https://npm.example/", "UV_INDEX_URL": "https://pypi.example/simple",
    "NODE_PATH": "/data/agent-tools/lib/node_modules", "PLAYWRIGHT_BROWSERS_PATH": "/data/agent-tools/ms-playwright",
}
script = "\n".join([
    "set -euo pipefail",
    func("install_env_ok"), func("install_env_only"), func("try_install"),
    # the install: its own shell reads a secret it was handed (it may), then a child prints what it can see
    'fake_install() { [ "$HARNESS_INTERNAL_KEY" = internal-key-not-real ] || return 9; env > "$OUT"; }',
    'try_install "test base" fake_install',
    # after the install, this script's own environment is as it was: only the install's subshell changed
    'env > "$OUT.after"',
])
out = os.path.join(os.environ.get("TMPDIR", "/tmp"), f"hr-install-env-{os.getpid()}")
env = {**SECRETS, **KEPT, "OUT": out}
r = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)
try:
    if r.returncode != 0:
        sys.exit(f"the install did not run (rc={r.returncode}): {r.stdout[-400:]}{r.stderr[-400:]}")
    seen = dict(line.split("=", 1) for line in open(out).read().splitlines() if "=" in line)
    after = dict(line.split("=", 1) for line in open(out + ".after").read().splitlines() if "=" in line)
finally:
    for p in (out, out + ".after"):
        if os.path.exists(p):
            os.unlink(p)
bad = [k for k in SECRETS if k in seen] + [k for k, v in SECRETS.items() if any(v == x for x in seen.values())]
missing = [k for k, v in KEPT.items() if seen.get(k) != v]
lost = [k for k in {**SECRETS, **KEPT} if after.get(k) != {**SECRETS, **KEPT}[k]]
if bad or missing or lost:
    sys.exit(f"reached the install: {sorted(set(bad))}; withheld from it: {missing}; changed outside it: {lost}")
print(f"install environment: {len(SECRETS)} secret names withheld, {len(KEPT)} fetch and build settings passed, "
      "the script's own environment unchanged")
