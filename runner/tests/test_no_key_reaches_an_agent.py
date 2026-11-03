"""No provider credential reaches an agent turn, on any base, on any connection a base takes (#615).

An agent turn runs the customer's agent with real bash, as the session's uid: everything in the CLI's
environment, on its command line, or in a file under its workspace is the agent's to read (`env`,
/proc/<pid>/environ, `cat`), and a prompt injection that reaches the agent can read it too. The real key
belongs in the runner and its loopback relay only; the turn gets the relay and a placeholder.

Every base in BACKENDS, every provider it takes, with a base URL, without one, and on a custom endpoint, with
an image credential and (hermes) a vision credential on top, goes through /turn as the gateway sends it. What
the turn would start is recorded instead of run, and the canary key must not be in it, nor in any file the
turn wrote. A base added later without the relay fails here instead of shipping.
"""
import io
import json
import pathlib
import sys
import tempfile
import time

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server  # noqa: E402

KEY = "sk-canary-chat-0123456789abcdef"
IMG_KEY = "sk-canary-image-0123456789abcdef"
VIS_KEY = "sk-canary-vision-0123456789abcdef"
AWS = {"aws_region": "us-east-1", "aws_access_key_id": "AKIA_CANARY_NOT_A_KEY_01",
       "aws_secret_access_key": "canary-aws-secret-0123456789abcdef", "aws_session_token": "canary-aws-session-0123456789",
       "aws_bearer_token": "canary-bedrock-bearer-0123456789"}
SA = json.dumps({"type": "service_account", "client_email": "x@p.iam.gserviceaccount.com",
                 "private_key": "-----BEGIN " "PRIVATE KEY-----\ncanary-gcp-private-key-0123456789\n-----END PRIVATE KEY-----\n",
                 "token_uri": "https://oauth2.googleapis.com/token"})
SECRETS = (KEY, IMG_KEY, VIS_KEY, *[v for k, v in AWS.items() if k != "aws_region"], "canary-gcp-private-key-0123456789")

BASES = {"anthropic": "https://api.anthropic.com/v1", "openai": "https://api.openai.com/v1",
         "openai-api": "https://up.example/v1", "azure": "https://res.openai.azure.com/openai/v1",
         "azure-foundry": "https://res.openai.azure.com/openai/v1",
         "google": "https://generativelanguage.googleapis.com/v1beta/openai",
         "tokenrouter": "https://api.tokenrouter.com/v1", "openrouter": "https://openrouter.ai/api/v1",
         "deepseek": "https://api.deepseek.com/v1"}


def _shapes(provider: str):
    if provider == "bedrock":
        return [("iam+bearer", dict(AWS))]
    if provider == "vertex":
        return [("service account", {"gcp_project": "p", "gcp_region": "us-east5", "gcp_sa_json": SA})]
    base = BASES.get(provider, "https://up.example/v1")
    out = [("base", {"api_key": KEY, "base_url": base}), ("no base", {"api_key": KEY})]
    if provider in ("openai-api", "tokenrouter", "custom"):
        out += [("custom openai", {"api_key": KEY, "base_url": "https://host.example/api/coding/v3", "api_format": "openai"}),
                ("custom anthropic", {"api_key": KEY, "base_url": "https://host.example/anthropic", "api_format": "anthropic"})]
    return out


CASES = []
for _backend, _spec in sorted(server.BACKENDS.items()):
    for _provider in _spec["providers"]:
        for _label, _auth in _shapes(_provider):
            CASES.append(pytest.param(_backend, _provider, _auth, id=f"{_backend}-{_provider}-{_label}"))


class _Proc:
    """A process that starts, says nothing and exits: what the turn would have run, recorded."""
    def __init__(self, cmd, **kw):
        self.args, self.pid, self.returncode = cmd, 999999, 0
        empty = "" if kw.get("text") or kw.get("universal_newlines") or kw.get("encoding") else b""
        self.stdout = io.StringIO(empty) if isinstance(empty, str) else io.BytesIO(empty)
        self.stderr = io.StringIO(empty) if isinstance(empty, str) else io.BytesIO(empty)
        self.stdin = io.StringIO() if isinstance(empty, str) else io.BytesIO()

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0

    def communicate(self, *a, **k):
        return (self.stdout.read(), self.stderr.read())

    def kill(self):
        pass

    terminate = send_signal = kill

    def __enter__(self):                          # subprocess.run uses it as a context manager
        return self

    def __exit__(self, *exc):
        return False


@pytest.mark.parametrize("backend,provider,auth", CASES)
def test_no_credential_reaches_the_turn(backend, provider, auth, monkeypatch):
    spawned = []

    def popen(cmd, *a, **kw):
        spawned.append({"cmd": cmd, "env": kw.get("env")})
        return _Proc(cmd, **kw)
    monkeypatch.setattr(server.subprocess, "Popen", popen)
    d = tempfile.mkdtemp()
    body = {"backend": backend, "provider": provider, "model": server.BACKENDS[backend]["default_model"],
            "prompt": "hi", "cwd": d, "auth": auth,
            "image_auth": {"base_url": "https://images.example/v1", "api_key": IMG_KEY, "model": "gpt-image-1"}}
    if backend == "hermes":
        body["vision_auth"] = {"provider": "anthropic", "model": "claude-x", "api_key": VIS_KEY}
    r = TestClient(server.app).post("/turn", json=body)
    seen = [json.dumps(r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text)]
    if r.status_code == 200:
        tid = r.json().get("turn_id")
        for _ in range(40):                       # the turn's process starts on its own thread
            if spawned:
                break
            time.sleep(0.05)
        time.sleep(0.2)
        if tid:
            seen.append(json.dumps(TestClient(server.app).get(f"/turn/{tid}").json()))
    else:
        assert r.status_code in (400, 422), (r.status_code, r.text[:300])   # refused: nothing was handed over
    for s in spawned:
        seen += [json.dumps(s["cmd"]), json.dumps(s["env"] or {})]
    for f in pathlib.Path(d).rglob("*"):
        if f.is_file() and f.stat().st_size < (8 << 20):
            seen.append(f"{f}: " + f.read_bytes().decode("utf-8", "replace"))
    blob = "\n".join(seen)
    leaked = [s for s in SECRETS if s in blob]
    assert not leaked, f"{backend}/{provider}: {leaked} reached the turn"
    for s in spawned:                             # a command line is every uid's to read (/proc/<pid>/cmdline)
        assert "hr-relay-" not in json.dumps(s["cmd"]), f"{backend}/{provider}: a relay token on argv"
        job = json.loads((s["env"] or {}).get("HR_DRIVER_JOB") or "{}")
        assert "hr-relay-" not in json.dumps(job.get("argv") or []), f"{backend}/{provider}: a relay token on the CLI's argv"
    if r.status_code == 200 and spawned and auth.get("api_key"):
        assert "hr-relay-" in blob, f"{backend}/{provider}: started without a relay placeholder"
