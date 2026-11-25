"""The realtime base: a text turn on a realtime speech model (runner/realtime_driver.py is the turn).

What the runner needs to know about it, kept in one place: its providers and default model, the
venv its driver runs in, how one turn's job is built, and how the session is found again.

The model is reached over a WebSocket, which the relay does not forward. So the turn's relay route
carries ONE call, the provider's own client-secret mint (`POST …/realtime/client_secrets`), and the
driver opens the socket itself with the secret that call answers. The route is registered to
forward that call and no other: a sandbox holding its placeholder can mint a session secret and
nothing else on the connection's key.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import urllib.parse

# Azure OpenAI is the one provider measured (Realtime Harness design §1.7, gpt-realtime-2.1). OpenAI
# speaks the same wire and is added when it has a measured column.
PROVIDERS = {"azure-foundry"}
DEFAULT_MODEL = "gpt-realtime-2.1"
PYTHON = os.environ.get("HR_REALTIME_PYTHON", "/data/agent-tools/realtime-venv/bin/python")
DRIVER = str(pathlib.Path(__file__).with_name("realtime_driver.py"))
MINT_PATH = "/realtime/client_secrets"
# what the turn's relay route forwards, and nothing else: (method, path under the connection's base)
ROUTE_ONLY = (("POST", MINT_PATH),)
_SID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def socket_url(base_url: str, model: str) -> str:
    """The model's WebSocket address on the connection's base: the same host and path, the socket's
    scheme, `/realtime`, and the model (on Azure, the deployment). "" when the base is not a web
    address with a host, so a connection with nothing to dial is refused before a process starts."""
    try:
        u = urllib.parse.urlsplit((base_url or "").strip())
    except ValueError:
        return ""
    scheme = {"https": "wss", "http": "ws"}.get(u.scheme.lower())
    if not scheme or not u.hostname:
        return ""
    return urllib.parse.urlunsplit((scheme, u.netloc, u.path.rstrip("/") + "/realtime",
                                    urllib.parse.urlencode({"model": model}), ""))


def build(provider, auth, model, prompt, cwd, env, *, relay, driver_cmd, resume_session_id=None,
          mcp_servers=None, tools_disabled=None, max_turns=None, timeout_seconds=None, agent_doc="",
          partial=False):
    """One realtime turn's command line, its job in the environment (driver_cmd).

    `relay(base_url, api_key) -> (relay base, placeholder)` registers the turn's route. The driver
    is handed the placeholder and the relay's address for the mint, and the provider's own address
    for the socket, which carries no credential. The harness's instructions travel in the job: this
    base reads no workspace file (the systemone precedent)."""
    from fastapi import HTTPException
    pr = provider or "azure-foundry"
    if pr not in PROVIDERS:
        raise HTTPException(400, f"unknown realtime provider '{pr}' (one of {sorted(PROVIDERS)})")
    if not auth.api_key or not auth.base_url:
        raise HTTPException(400, "realtime needs a base_url and an API key (none configured)")
    ws = socket_url(auth.base_url, model)
    if not ws:
        raise HTTPException(400, "realtime needs a base_url that is a web address")
    relay_base, token = relay(auth.base_url, auth.api_key)
    env["HR_REALTIME_KEY"] = token          # the placeholder; the route is found by it, and holds no tap
    job = {"cwd": cwd, "model": model, "prompt": prompt, "provider": pr,
           "mint_url": relay_base.rstrip("/") + MINT_PATH, "api_key": token, "ws_url": ws,
           "resume_session_id": resume_session_id or "",
           "mcp_servers": [s for s in (mcp_servers or []) if isinstance(s, dict) and (s.get("url") or s.get("command"))],
           "tools_disabled": [str(t) for t in (tools_disabled or []) if t],
           "max_turns": max_turns, "timeout_seconds": timeout_seconds,
           "agent_doc": agent_doc or "", "partial": bool(partial)}
    return driver_cmd(PYTHON, DRIVER, job, env)


def session_present(cwd: str, cmd: list, sid: str) -> bool:
    """Whether the session a turn was asked to continue is in this workspace (the runner's
    _SESSION_PRESENT probe): its items file, the only place the conversation exists."""
    del cmd
    if not _SID_RE.match(sid or ""):
        return False
    path = pathlib.Path(cwd) / ".harness" / "realtime" / sid / "items.json"
    try:
        return isinstance(json.loads(path.read_text(encoding="utf-8")), list)
    except (OSError, ValueError):
        return False


def route_allows(flags: dict, method: str, tail: str) -> bool:
    """Whether a route forwards this request: a route with `only` forwards the (method, path)
    pairs it names and nothing else; a route without it forwards as it always did. The path is
    compared without its query string."""
    only = flags.get("only")
    if not only:
        return True
    return (method.upper(), tail.split("?", 1)[0]) in {(m.upper(), p) for m, p in only}
