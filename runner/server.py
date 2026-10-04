"""In-sandbox harness runner server — multi-backend, multi-provider.

Runs INSIDE an ACA Dynamic Sessions custom-container sandbox (one per session, Hyper-V
isolated, warm-pooled). The `harness-gateway` allocates a session from the pool and proxies
turn requests here. The agent ALWAYS works on a real local POSIX git working tree at
/workspace with real bash + git — its native, trained environment (we never map VectorGraph
into the session; see docs/technical/HARNESS_AS_A_SERVICE_DESIGN.md S0.5).

A turn runs ONE backend CLI one-shot over /workspace and normalizes its events into a
single canonical schema (Claude Code `stream-json`) so everything downstream is uniform.

Backends + providers (registry-driven — pi was added as exactly that one entry):
  backend "claude" (Claude Code CLI), providers:
    - anthropic   : ANTHROPIC_API_KEY (+ optional ANTHROPIC_BASE_URL)
    - bedrock     : CLAUDE_CODE_USE_BEDROCK=1 + AWS creds/bearer + region
    - vertex      : CLAUDE_CODE_USE_VERTEX=1 + project/region + SA-JSON
    - tokenrouter : ANTHROPIC_BASE_URL=<router> + ANTHROPIC_AUTH_TOKEN
  backend "codex" (OpenAI Codex CLI), providers (config.toml [model_providers.*]):
    - openai      : api.openai.com/v1, OPENAI_API_KEY
    - azure       : <azure>/openai/v1, AZURE_OPENAI_API_KEY (wire_api=responses)
    - tokenrouter : <router base_url>, ROUTER_API_KEY
  backend "hermes" (NousResearch hermes-agent CLI; events tailed from its state.db —
  multi-family: runs any frontier model through the matching provider connection):
    - azure-foundry : AZURE_FOUNDRY_API_KEY + AZURE_FOUNDRY_BASE_URL (gpt family)
    - bedrock       : AWS_BEARER_TOKEN_BEDROCK (or key pair) + AWS_REGION (claude family)
    - anthropic     : ANTHROPIC_API_KEY (+ optional ANTHROPIC_BASE_URL)
  backend "dsh" (DeepSeek Harness; official Python SDK drives the bundled JSON-RPC
  runtime — runner/dsh_driver.py re-emits its session.events as NDJSON):
    - deepseek    : any OpenAI-compatible deepseek-family endpoint; DEEPSEEK-shaped auth
                    goes to the driver as HR_DSH_* and stays OUT of the runtime env
  backend "pi" (earendil-works pi coding agent; `pi -p --mode json` event stream,
  multi-family like hermes — custom providers via ~/.pi/agent/models.json):
    - anthropic     : ANTHROPIC_API_KEY (native), base_url via models.json when set
    - openai        : OPENAI_API_KEY (native), base_url via models.json when set
    - azure         : models.json openai-responses + base_url
    - openai-api    : models.json openai-completions + base_url (generic aggregator)
    - tokenrouter   : models.json, api by model family (claude -> anthropic-messages)

Creds are injected per-session via env (pool secrets) or a body `auth` override for spikes.
Phase 0b: buffered turn. SSE streaming, git hydrate/commit, mid-turn /input, and the Node
Yjs sidecar layer on next.
"""
from __future__ import annotations

import base64
import hashlib
import http.client
import http.server
import datetime
import json
import mimetypes
import os
import pathlib
import re
import shlex
import shutil
import signal
import socket
import sqlite3
import subprocess
import tempfile
import hmac
import pwd
import stat
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import yaml
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

import environments   # the read-only project layer a turn may name (runner/environments.py)

app = FastAPI(title="harness-runner")


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError):
    """Where and why a request failed, never what it carried: FastAPI's default repeats the
    failing value, which for a missing field is the whole body (the gateway has the same handler)."""
    errors = [{"loc": list(e.get("loc") or []), "msg": str(e.get("msg") or ""), "type": str(e.get("type") or "")} for e in exc.errors()]
    return JSONResponse({"detail": errors}, status_code=422)
app.include_router(environments.router)

WORKSPACE_ROOT = os.environ.get("HARNESS_WORKSPACE", "/workspace")
# Session ids are opaque to us and arrive over the wire, so they are sanitized before becoming a
# path component — a `..` would otherwise escape the root.
_SID_SAFE = re.compile(r"[^A-Za-z0-9._-]")


# "One sandbox per session" as a DEPLOYMENT INVARIANT, declared by the deployment itself (the
# hosted session pool sets it: ACA Dynamic Sessions gives each identifier its own
# Hyper-V-isolated container). Everything it changes fails CLOSED when unset — the self-hosted
# all-in-one container runs ONE runner for ALL sessions, where these behaviors would break
# session isolation. See _ws() and _reap_workspaces().
_SANDBOX_PER_SESSION = os.environ.get("HR_SANDBOX_PER_SESSION", "").strip().lower() in ("1", "true", "on")

# THE SESSION WRITE-WALL, the second deployment invariant, declared by the self-hosted entrypoint
# (HR_SESSION_UIDS=1). One runner serves every session there, so "the session workspace" cannot be
# a sandbox boundary the way it is on a per-session sandbox; it has to be a permission boundary.
# The runner runs as root and every process that acts for a session (the agent CLI, its sidecar,
# git, tar) runs as that session's OWN uid, which owns its session directory and nothing else:
# the workspace root, the data volume, the product's processes and the shared scratch directories
# belong to other uids. A deliverable written to "/tmp/X", to the workspace parent or into another
# session's directory is then not lost and not stolen: it fails with EACCES at the write, the one
# moment the model is still there to pick the right path. Not an instruction (2026-08-21: an
# instruction binds only models that follow instructions), not a post-hoc adoption pass (on a shared
# root a stray file's name, content and mtime are attacker-controlled). A path the process cannot
# materialise is a path it cannot use.
#
# Mutually exclusive with the per-session sandbox: there the root IS the workspace and one uid is
# correct. Fails CLOSED: declared but not root means the wall cannot be built, and the runner
# refuses to start rather than quietly sharing one uid across sessions.
_SESSION_UIDS = os.environ.get("HR_SESSION_UIDS", "").strip().lower() in ("1", "true", "on")
_SESSION_UID_BASE = int(os.environ.get("HR_SESSION_UID_BASE", "20000") or 20000)
_SESSION_UID_SPAN = 40000
if _SESSION_UIDS and _SANDBOX_PER_SESSION:
    raise RuntimeError("HR_SESSION_UIDS and HR_SANDBOX_PER_SESSION are mutually exclusive: "
                       "a per-session sandbox needs no per-session uid")
if _SESSION_UIDS and os.geteuid() != 0:
    raise RuntimeError("HR_SESSION_UIDS=1 requires the runner to run as root (it switches to a "
                       "per-session uid for every agent process); refusing to start on a shared uid")
if _SESSION_UIDS:
    _secured = environments.secure_store()   # environments from before per-environment groups
    if _secured:
        print(f"[runner] environments: {_secured} older environment(s) now readable by their own group only", flush=True)
# Names an agent process must never inherit from the runner's environment. The turn sets the
# credential it needs explicitly (see turn()); everything else secret-shaped is the product's.
_SECRET_ENV = re.compile(r"^(HARNESS_INTERNAL_KEY|HR_AUTH_.*|HR_SECRET_KEY|HR_SESSION_KEY|HR_POOL_.*)$"
                         r"|_API_KEY$|_SECRET(_|$)|_TOKEN$|PASSWORD", re.I)
_INTERNAL_KEY = os.environ.get("HARNESS_INTERNAL_KEY", "")
_uid_lock = threading.Lock()

# How long an untouched session workspace is kept. Sessions are resumable from their checkpoint,
# so a reaped directory costs a rehydrate, not the work — but keeping every one forever fills the
# disk of a box nobody is watching. 0 disables.
WS_TTL_HOURS = float(os.environ.get("HR_WORKSPACE_TTL_HOURS", "72") or 0)


def _reap_workspaces(keep: str = "") -> int:
    """Delete session workspaces untouched for longer than the TTL. Cheap, and only ever called
    at hydrate — the moment we already know a session is starting fresh."""
    if _SANDBOX_PER_SESSION:
        # The workspace root IS the session workspace (see _ws): iterating it would reap the
        # session's own project subdirectories as if they were idle sessions. The sandbox's own
        # lifecycle (pool cooldown) is the cleanup mechanism in this mode.
        return 0
    if WS_TTL_HOURS <= 0:
        return 0
    cutoff = time.time() - WS_TTL_HOURS * 3600
    removed = 0
    try:
        entries = list(os.scandir(WORKSPACE_ROOT))
    except OSError:
        return 0
    for e in entries:
        if not e.is_dir() or e.name == keep:
            continue
        try:
            # mtime of the directory tracks the last write into it; a running turn keeps it fresh.
            if e.stat().st_mtime >= cutoff:
                continue
            shutil.rmtree(e.path, ignore_errors=True)
            _ws_marker_clear(e.name)
            removed += 1
        except OSError:
            continue
    if removed:
        print(f"[reap] removed {removed} workspace(s) idle > {WS_TTL_HOURS}h", flush=True)
    return removed


def _ws(identifier: str = "") -> str:
    """This session's workspace directory.

    The workspace has ALWAYS been per session; the hosted deployment just satisfies that by
    giving each session its own sandbox, so a single directory was enough there. Run several
    sessions in ONE container — which self-hosting does — and that implicit assumption becomes
    false: /hydrate wipes and restores, so two sessions would destroy each other's files.

    The gateway already addresses every runner call as ?identifier=<session_id>, so the session
    id IS the directory and nothing on the wire changes.

    UNDER THE PER-SESSION-SANDBOX INVARIANT (HR_SANDBOX_PER_SESSION, declared by the hosted
    pool: each identifier gets its own Hyper-V-isolated container), the session workspace IS
    WORKSPACE_ROOT itself. This is the mechanical fix for deliverables written to "/workspace/X"
    — the path models reach for when told they work in a workspace. With a per-session
    subdirectory, that path was a writable trap OUTSIDE the git tree: never collected, never
    checkpointed, invisible to the user (two live incidents on 2026-08-21, deepseek family,
    one of them DESPITE the AGENTS.md contract — an instruction binds only models that follow
    instructions). With the root as the workspace, the wrong folder does not exist: /workspace/X
    is inside the collected tree by construction. No instruction, no post-hoc adoption (an
    adoption pass on a SHARED root would be a cross-session attack plane: name, content and
    mtime of a stray file are all attacker-controlled). Shared deployments (self-host: one
    runner, many sessions) keep per-session subdirectories, because there they ARE the
    session isolation."""
    if _SANDBOX_PER_SESSION:
        return WORKSPACE_ROOT
    sid = _SID_SAFE.sub("_", (identifier or "").strip())[:120] or "_default"
    return os.path.join(WORKSPACE_ROOT, sid)
def _session_uid(ws: str) -> int | None:
    """The uid this session's processes run as, or None when the write-wall is off or the
    directory has not been isolated yet. The directory's owner IS the record: nothing to keep in
    sync, and it survives a restart because ownership lives on the volume."""
    if not _SESSION_UIDS:
        return None
    try:
        uid = os.stat(ws).st_uid
    except OSError:
        return None
    return uid if _SESSION_UID_BASE <= uid < _SESSION_UID_BASE + _SESSION_UID_SPAN else None


def _as_session(ws: str, env: dict | None = None) -> dict:
    """Popen/run keyword arguments that make a child act as this session. Empty when the wall is
    off, so every spawn site reads the same with or without it. A turn's agent process (the sites
    that pass the turn's env) also joins the group of the one environment the turn names, which is
    what lets it read that environment and no other (runner/environments.py)."""
    uid = _session_uid(ws)
    if uid is None:
        return {}
    gid = environments.reader_gid((env or {}).get("HR_ENVIRONMENT"))
    return {"user": uid, "group": uid, "extra_groups": [gid] if gid is not None else []}


def _ensure_passwd(uid: int, home: str) -> None:
    """A passwd entry for the session uid. The CLIs run without one (verified: all five start as
    an unlisted uid), but os.userInfo()-style lookups throw, and the entry costs nothing."""
    try:
        pwd.getpwuid(uid)
        return
    except KeyError:
        pass
    name = f"hs{uid}"
    try:
        subprocess.run(["groupadd", "-g", str(uid), name], capture_output=True)
        subprocess.run(["useradd", "-M", "-u", str(uid), "-g", str(uid), "-s", "/bin/bash",
                        "-d", home, name], capture_output=True)
    except OSError:
        pass


def _own_tree(root: str, uid: int, from_uids: set[int]) -> None:
    """chown everything under root that currently belongs to one of from_uids. Only those: a
    session can plant a hard link to a file it does not own, and chowning by position rather
    than by current owner would hand it that file. Symlinks are re-owned as links, never
    followed."""
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            path = os.path.join(dirpath, name)
            try:
                st = os.lstat(path)
                if st.st_uid in from_uids and not (stat.S_ISREG(st.st_mode) and st.st_nlink > 1):
                    os.lchown(path, uid, uid)
            except OSError:
                continue


def _aider_session_present(cwd: str, cmd: list[str], session_id: str) -> bool:
    """aider has no session id at all: its continuation is a chat-history FILE, and a missing one
    resumes silently with no output difference whatsoever (measured on 0.86.2). So the question
    "is the conversation there?" is "does the history hold at least one message?", asked with
    aider's own parser rather than by eyeballing the markdown.

    The driver relocates that file under .harness/ so it is neither a produced file nor a name the
    user sees; the runner mints the session id, as it does for kimi."""
    hist = pathlib.Path(cwd) / ".harness" / "aider" / "chat.history.md"
    if not hist.is_file():
        return False
    try:
        text = hist.read_text(errors="replace")
    except OSError:
        return False
    # aider's own marker for a recorded exchange: split_chat_history_markdown keys on the "####"
    # user-message heading. Matching it here is reading aider's format, not guessing at prose.
    return any(line.startswith("####") for line in text.splitlines())


def _cheetahclaws_home(cwd: str) -> pathlib.Path:
    """~/.cheetahclaws under the redirected HOME (turn() points HOME at .harness/home)."""
    return pathlib.Path(cwd) / ".harness" / "home" / ".cheetahclaws"


def _cheetahclaws_session_present(cwd: str, cmd: list[str], session_id: str) -> bool:
    """CheetahClaws has no resume flag: `-p` always starts from an empty state, and continuing is
    the REPL's /resume, which loads the autosaved session_latest.json. So this asks that file, read
    the way /resume reads it: the session is there when the file names this id and holds a message.
    The file is one per HOME, and HOME is redirected into the session's workspace, so "latest" is
    this session's own; it travels in the checkpoint with the rest of the home."""
    path = _cheetahclaws_home(cwd) / "sessions" / "mr_sessions" / "session_latest.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return (isinstance(data, dict) and data.get("session_id") == session_id
            and isinstance(data.get("messages"), list) and bool(data["messages"]))


def _argv_session_present(cwd: str, cmd: list[str], session_id: str) -> bool:
    """The builder looked the session up and said so in argv: claude's --resume, opencode's
    --session and kimi's -r carry the id only when it was found in this workspace."""
    return session_id in cmd


def _goose_session_present(cwd: str, cmd: list[str], session_id: str) -> bool:
    """goose carries the id as `-n <name>` on EVERY turn — it names a fresh session as well as
    selecting an existing one — so the id being present in cmd says nothing. `-r` is the flag that
    means "continue", and _build_goose adds it only once the session was found in this workspace's
    database."""
    return "-r" in cmd


# How each backend answers "is the conversation the caller asked to continue actually there?".
#
# ASK THE STORE, DO NOT SEARCH IT. goose's first version searched the sessions database for the
# session NAME; the name was `harness`, which also occurs in the workspace path that tool output
# carries, so a database holding one message and no session matched — a false positive that added
# -r and failed the turn with "No session found", the very failure the check existed to prevent.
# A backend whose builder already performs the lookup can answer from argv (that IS the builder's
# conclusion, not a guess about it); a backend that cannot must query its store the way the CLI
# queries it.
#
# A backend absent from this table cannot lose a session, or has not been measured — either way it
# never reports one lost. Adding a backend here is registration point 5.
def _openhands_session_present(cwd: str, cmd: list[str], session_id: str) -> bool:
    """Ask the agent-server's own store whether this conversation is there.

    It cannot be read off argv: the driver mints the id and passes it whatever the store holds, and
    the server creates a conversation for an id it does not know. The store is a directory named for
    the id with the dashes removed, holding base_state.json and an events log — the shape the driver
    read back after killing one server and querying another."""
    home = pathlib.Path(cwd) / ".harness" / "openhands" / "conversations"
    if not home.is_dir():
        return False
    return any((d / "base_state.json").is_file() for d in home.iterdir() if d.is_dir())


def _agentzero_session_present(cwd: str, cmd: list[str], session_id: str) -> bool:
    """Ask Agent Zero's own store: the context the driver resumes is usr/chats/<id>/chat.json under
    the workspace's base, and it is loaded with Agent Zero's own deserialiser. A file that is there
    but holds no agent history is a conversation that is not there — the driver would build a
    fresh context over it. The id is the driver's constant, so it cannot be read off argv, and the
    driver itself creates a context for an id it does not find, silently."""
    chat = (pathlib.Path(cwd) / ".harness" / "agentzero" / "base" / "usr" / "chats"
            / (session_id or "harness") / "chat.json")
    try:
        doc = json.loads(chat.read_text())
    except (OSError, ValueError):
        return False
    agents = doc.get("agents") if isinstance(doc, dict) else None
    return bool(agents) and bool((agents[0] or {}).get("history"))


_SESSION_PRESENT = {
    "claude": _argv_session_present,
    "opencode": _argv_session_present,
    "kilo": _argv_session_present,        # _build_kilo asks kilo.db before it passes --session
    "goose": _goose_session_present,
    "kimi": _argv_session_present,
    # minimax: _build_minimax asks the CLI's own sqlite store and passes --session only when the
    # conversation is there, so the id in argv IS that lookup's conclusion (an unknown id would be
    # a hard exit 4 on this CLI, never a silent new conversation).
    "minimax": _argv_session_present,
    # grok: _build_grok passes -r only when _grok_has_session found the id in the store, and a fresh
    # -s uuid otherwise, so the id in argv IS the builder's lookup.
    "grok": _argv_session_present,
    "aider": _aider_session_present,
    "openhands": _openhands_session_present,
    "cheetahclaws": _cheetahclaws_session_present,
    "agentzero": _agentzero_session_present,
}


def _resume_lost(backend: str, cmd: list[str], resume_session_id: str | None,
                 cwd: str = "") -> str | None:
    """The session id the caller asked to continue when that conversation is not there: the turn
    will run, and it will answer from an empty history unless someone says so.

    Four hosted opencode sessions answered three recalls each with "there is no earlier message" as
    completed turns (2026-09-08): the history was lost to the 2026-09-06 restore burst, and nothing
    told the person. The gateway renders the event this produces as a note at the top of the reply.

    hermes says so itself and codex carries its own note, so neither is in the table."""
    probe = _SESSION_PRESENT.get(backend)
    if probe is None or not resume_session_id:
        return None
    return None if probe(cwd, cmd, resume_session_id) else resume_session_id


def _isolate_session(ws: str) -> None:
    """Make the session directory the one place its uid can write, and make everything in it
    that uid's. Allocation happens once, under a lock, from the owners of the directories that
    exist: a uid is free when no session directory carries it, so two sessions can never share
    one, and a reaped directory returns its uid. Every call after that re-owns what the runner
    wrote into the directory as root since the last one (agent doc, skills, input files, MCP
    configuration, the restored checkpoint)."""
    if not _SESSION_UIDS:
        return
    uid = _session_uid(ws)
    previous: set[int] = {0}
    if uid is None:
        with _uid_lock:
            uid = _session_uid(ws)
            if uid is None:
                used: set[int] = set()
                try:
                    for e in os.scandir(WORKSPACE_ROOT):
                        try:
                            if e.is_dir(follow_symlinks=False):
                                used.add(e.stat(follow_symlinks=False).st_uid)
                        except OSError:
                            continue
                except OSError:
                    pass
                uid = next((u for u in range(_SESSION_UID_BASE, _SESSION_UID_BASE + _SESSION_UID_SPAN)
                            if u not in used), None)
                if uid is None:
                    raise HTTPException(503, "no free session uid")
                previous.add(os.stat(ws).st_uid)   # a legacy directory: re-own its files too
                _ensure_passwd(uid, os.path.join(ws, HARNESS_STATE, "home"))
                os.chown(ws, uid, uid)
    os.chmod(ws, 0o700)
    _own_tree(ws, uid, previous)


_CALLER_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Prefixes the runner sets for the agent's own credentials, and the dynamic loader's; names that
# would redirect an interpreter's imports, a process's trust roots or its network path.
_CALLER_ENV_RESERVED = ("HR_", "HARNESS_", "OPENAI_", "ANTHROPIC_", "GEMINI_", "GOOGLE_", "AWS_", "AZURE_", "LD_", "DYLD_")
_CALLER_ENV_RESERVED_NAMES = {"PATH", "HOME", "USER", "SHELL", "TERM", "LANG", "PWD", "TMPDIR",
                              "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "NODE_OPTIONS", "NODE_EXTRA_CA_CERTS",
                              "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
                              "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"}


def _caller_env(env: dict | None) -> dict:
    """A harness's environment variables as the gateway resolved them: shell-safe names only, and
    none under a prefix the runner uses for the agent's own credentials and paths."""
    out = {}
    for k, v in (env or {}).items():
        name = str(k or "")
        if not _CALLER_ENV_NAME.match(name) or name.upper().startswith(_CALLER_ENV_RESERVED) \
                or name.upper() in _CALLER_ENV_RESERVED_NAMES:
            continue
        if v is None:
            continue
        out[name] = str(v)
    return out


_SCRUB_MIN = 8   # shorter values are not scrubbed: replacing "yes" everywhere would mangle the record


def _turn_secrets(env: dict, names: list | None) -> list[str]:
    """The values of a turn's environment that came through a reference (the gateway names them):
    what the agent may read but the record may not carry. Longest first, so a value that contains
    another is replaced whole."""
    vals = {str(env[n]) for n in (names or []) if isinstance(n, str) and env.get(n) and len(str(env[n])) >= _SCRUB_MIN}
    return sorted(vals, key=len, reverse=True)


def _scrub_secrets(text: str, secrets: list[str] | None) -> str:
    """Every occurrence of a turn's secret values replaced in a serialized record. Applied where
    the gateway reads the turn, so no event, result or error leaves the sandbox with one."""
    for sec in secrets or []:
        if sec and sec in text:
            text = text.replace(sec, "[redacted]")
    return text


def _child_env() -> dict:
    """The environment an agent process starts from: the runner's, minus anything secret-shaped.
    On the self-hosted box the runner's environment is the container's, and that carried the
    console password, the internal key and the secret-store key into every agent process."""
    return {k: v for k, v in os.environ.items() if not _SECRET_ENV.search(k)}


@app.middleware("http")
async def _internal_callers_only(request: Request, call_next):
    """Behind the write-wall the runner is reachable from every agent process on loopback, and its
    routes address any session by identifier. The gateway presents the internal key (which
    _child_env strips from agent processes); nothing else may drive this API."""
    if _SESSION_UIDS and _INTERNAL_KEY and request.url.path != "/healthz":
        if not hmac.compare_digest(request.headers.get("x-harness-internal", ""), _INTERNAL_KEY):
            return JSONResponse({"error": "internal key required"}, status_code=401)
    return await call_next(request)


# Where checkpoint/hydrate tarballs spool to disk (HR-INF-015 — never a RAM buffer). MUST be
# OUTSIDE the workspace (so a leftover temp file can never be caught by a later `git add -A` or
# re-tarred) AND on a real DISK, not a RAM-backed tmpfs (which would defeat the memory saving).
# Default: a dedicated dir on the container's disk-backed rootfs (same overlay as /workspace on
# ACA Dynamic Sessions), created at import. Override with HARNESS_SPOOL_DIR if the runtime differs.
SPOOL_DIR = os.environ.get("HARNESS_SPOOL_DIR", "/var/tmp/harness-spool")
try:
    os.makedirs(SPOOL_DIR, exist_ok=True)
except OSError:
    SPOOL_DIR = None   # fall back to the OS tmpdir if that path isn't writable
_SPOOL_STALE_S = 3600  # a spool file older than this can't belong to a live transfer


def _reap_spool() -> None:
    """Remove stale spool tarballs (HR-INF-015 review, LOW). Normal cleanup is a BackgroundTask /
    finally, but a client disconnect mid-checkpoint-stream skips the BackgroundTask, leaking the
    temp file. On a warm-pooled sandbox reused across many turns these would slowly fill the disk,
    so sweep files older than the max transfer window on each checkpoint. Best-effort; never raises."""
    if not SPOOL_DIR:
        return
    import glob as _glob
    now = time.time()
    for f in _glob.glob(os.path.join(SPOOL_DIR, "*.tgz")):
        try:
            if now - os.path.getmtime(f) > _SPOOL_STALE_S:
                os.unlink(f)
        except OSError:
            pass
# CLI conversation/rollout state lives INSIDE the workspace so a single checkpoint captures both
# the working tree AND the conversation — that's what makes `--resume` work on any sandbox.
HARNESS_STATE = ".harness"
# Paths never persisted in a checkpoint (secrets + regenerated/scratch). Relative to /workspace.
# .git history travels in the tarball, so these must be git-ignored too (see _git_ensure).
# Persist conversation transcripts ($HOME -> .harness/home: ~/.claude/projects, ~/.codex/sessions)
# so --resume survives sandbox recycling — but NEVER persist credentials inside them.
CHECKPOINT_EXCLUDE = ["./tmp", "./.gcp-sa.json", "./.codex", "./.credentials.json",
                      "./.harness/claude/.credentials.json",
                      "./.harness/home/.claude/.credentials.json",
                      "./.harness/home/.codex/auth.json",
                      # hermes state (state.db conversations) IS checkpointed; its cred files are not.
                      "./.harness/home/.hermes/.env",
                      "./.harness/home/.hermes/auth.json",
                      # pi stores provider keys in auth.json, and models.json carries the literal
                      # key for custom providers — neither may travel in a checkpoint tarball.
                      "./.harness/home/.pi/agent/auth.json",
                      "./.harness/home/.pi/agent/models.json",
                      # omp models / auth
                      "./.harness/home/.omp/agent/auth.json",
                      "./.harness/home/.omp/agent/models.json",
                      "./.harness/home/.omp/agent/models.yml",
                      # goose keeps provider keys in its own secrets.yaml beside config.yaml. The
                      # runner never writes it (credentials go in the env, and only the relay's
                      # per-turn placeholder at that), but `goose configure` inside a task would,
                      # and a secret that reaches a checkpoint tarball is published — the hole
                      # pi's auth.json and hermes's .env each had to be closed for.
                      "./.harness/goose/config/secrets.yaml",
                      # dsh: the MCP cordis overlay can carry auth headers (same standing as
                      # claude's .mcp.json); the provider KEY itself never lands anywhere —
                      # it lives only in the driver process (see dsh_driver.py's relay).
                      "./.harness/home/.dsh/cordis.yml",
                      # The per-turn config files the runner writes OUTSIDE the CLI home, each of
                      # which can carry an MCP server's Authorization header or a stdio server's
                      # env: opencode's and Kilo's config (their `mcp` map), Claude Code's
                      # --mcp-config file, and the bridge launchers (`export HR_MCP_HEADERS=…`).
                      # Every one is rewritten at the start of every turn, so none needs to travel,
                      # and a credential in a checkpoint outlives the server's removal from the
                      # harness. kilo.json arrived without this; the other three predate it.
                      "./.harness/opencode.json",
                      "./.harness/kilo.json",
                      "./.harness/mcp.json",
                      "./.harness/mcp-bridge",
                      # Agent Zero keeps its dotenv and its secrets store in usr/ (helpers/dotenv.py,
                      # helpers/secrets.py). The driver writes neither — the key rides the turn's
                      # environment, and only the relay's placeholder at that — but its settings
                      # save path writes API_KEY_* into usr/.env, and a task can reach it.
                      "./.harness/agentzero/base/usr/.env",
                      "./.harness/agentzero/base/usr/secrets.env",
                      # opencode's undo/revert history: a git repo of the workspace that grew to
                      # 699 MB / 71k files in twenty turns (#193). _opencode_config turns it off;
                      # this keeps a workspace that already carries one from dragging it through
                      # every later checkpoint. Nothing reads it once snapshots are off.
                      "./.harness/home/.local/share/opencode/snapshot",
                      # Kilo CLI is opencode's fork and keeps the same tree under kilo/: snapshots
                      # are off in its config for the same reason, and its log directory is the one
                      # place the CLI writes what it was handed (request metadata, the relay URL).
                      "./.harness/home/.local/share/kilo/snapshot",
                      "./.harness/home/.local/share/kilo/log",
                      # Kilo's credential store. The runner never writes it (the key is an env var
                      # named in kilo.json, and only the relay's placeholder at that), but a
                      # `kilo auth login` inside a task would, and it must not travel.
                      "./.harness/home/.local/share/kilo/auth.json",
                      # Dependency/scratch dirs (any depth): re-creatable by the agent, and they
                      # dominate checkpoint size — a node project checkpointed 200MB+ and paid
                      # that again on every hydrate. The agent reinstalls when it needs them.
                      "node_modules", ".venv", "venv", "__pycache__", ".pnpm-store",
                      ".cache/pip", ".npm/_cacache",
                      # Kimi Code CLI: sessions/ is what a resume reads and it travels; its logs,
                      # response cache and update-check state do not need to, and a log is the one
                      # place a CLI may print what it was handed. The key itself is never at rest:
                      # the model is defined from the environment (see _build_kimi).
                      "./.harness/home/.kimi-code/logs",
                      "./.harness/home/.kimi-code/cache",
                      "./.harness/home/.kimi-code/updates",
                      # CheetahClaws: sessions/ is what the next turn resumes from and it travels.
                      # Its task tracker is written to the WORKSPACE (<cwd>/.cheetahclaws/
                      # tasks.json, task/store.py) and is scratch; its mcp.json can carry an MCP
                      # server's auth headers (the standing of claude's .mcp.json); its log is
                      # the one place it prints what went wrong in full. The provider key is
                      # never at rest: the CLI is handed the relay's placeholder in its env.
                      "./.cheetahclaws/tasks.json",
                      "./.harness/home/.cheetahclaws/mcp.json",
                      "./.harness/home/.cheetahclaws/logs",
                      # MiniMax Code: v2/sqlite + v2/sessions are what a --session resume reads and
                      # they travel. config.yaml holds the relay's per-turn placeholder as a literal
                      # apiKey (the CLI reads no env reference) and mcp.json can carry MCP auth
                      # headers; auth/ is its own login store (never used here, a credential if it
                      # were). Logs, background-command output, caches and the 12 MB of bundled
                      # skills it re-seeds on every start do not need to travel.
                      "./.harness/home/.minimax/config.yaml",
                      "./.harness/home/.minimax/mcp.json",
                      "./.harness/home/.minimax/auth",
                      "./.harness/home/.minimax/v2/observability",
                      "./.harness/home/.minimax/background-tasks",
                      "./.harness/home/.minimax/cache",
                      "./.harness/home/.minimax/.builtin-skills",
                      # ...and its agent bash puts an `rm` shim first on PATH that MOVES a deleted
                      # file to the XDG trash under $HOME (measured on 0.5.4: shims/rm ->
                      # bin/mavis-trash -> ~/.local/share/Trash on Linux). HOME is in the checkpoint,
                      # so without this every file the agent ever deleted would travel with it.
                      "./.harness/home/.local/share/Trash",
                      # Grok Build: sessions/ is what a resume reads and it travels. config.toml is
                      # rewritten every turn and carries each MCP server's Authorization header;
                      # auth.json is where `grok login` would keep an xAI credential and
                      # mcp_credentials.json an MCP server's OAuth tokens, both mode 0600 (the runner
                      # starts neither flow — see _grok_config — but a task could). logs/ can hold
                      # what the CLI was handed;
                      # docs/ and bundled/ are re-materialised from the binary on every run.
                      "./.harness/home/.grok/config.toml",
                      "./.harness/home/.grok/auth.json",
                      "./.harness/home/.grok/mcp_credentials.json",
                      "./.harness/home/.grok/logs",
                      "./.harness/home/.grok/docs",
                      "./.harness/home/.grok/bundled",
                      "./.harness/home/.grok/downloads"]
_GIT_ENV = {"GIT_AUTHOR_NAME": "harness", "GIT_AUTHOR_EMAIL": "harness@agentstudio.local",
            "GIT_COMMITTER_NAME": "harness", "GIT_COMMITTER_EMAIL": "harness@agentstudio.local"}
CLAUDE_DEFAULT_MODEL = os.environ.get("CLAUDE_DEFAULT_MODEL", "claude-sonnet-4.6")
CODEX_DEFAULT_MODEL = os.environ.get("CODEX_DEFAULT_MODEL", "gpt-5.4")
# Hermes default (the gateway maps friendly names to provider ids before the /turn call).
HERMES_DEFAULT_MODEL = os.environ.get("HERMES_DEFAULT_MODEL", "gpt-5.4")
# Pi default — pi is multi-family the same way hermes is; same reasoning, same default.
PI_DEFAULT_MODEL = os.environ.get("PI_DEFAULT_MODEL", "gpt-5.4")
OPENCODE_DEFAULT_MODEL = os.environ.get("OPENCODE_DEFAULT_MODEL", "gpt-5.4")
KILO_DEFAULT_MODEL = os.environ.get("KILO_DEFAULT_MODEL", "gpt-5.4")
QWEN_DEFAULT_MODEL = os.environ.get("QWEN_DEFAULT_MODEL", "qwen3.7-max")
GEMINI_DEFAULT_MODEL = os.environ.get("GEMINI_DEFAULT_MODEL", "gemini-3.8-flash")
CLINE_DEFAULT_MODEL = os.environ.get("CLINE_DEFAULT_MODEL", "gpt-5.4")
DSH_DEFAULT_MODEL = os.environ.get("DSH_DEFAULT_MODEL", "deepseek-v4-pro")
OMP_DEFAULT_MODEL = os.environ.get("OMP_DEFAULT_MODEL", "gpt-5.4")
GOOSE_DEFAULT_MODEL = os.environ.get("GOOSE_DEFAULT_MODEL", "gpt-5.4")
KIMI_DEFAULT_MODEL = os.environ.get("KIMI_DEFAULT_MODEL", "kimi-k3")
# MiniMax Code runs any OpenAI-compatible model; its vendor's own is the natural default.
MINIMAX_DEFAULT_MODEL = os.environ.get("MINIMAX_DEFAULT_MODEL", "minimax-m3")
GROK_DEFAULT_MODEL = os.environ.get("GROK_DEFAULT_MODEL", "grok-4.6")
AIDER_DEFAULT_MODEL = os.environ.get("AIDER_DEFAULT_MODEL", "gpt-5.4")
OPENHANDS_DEFAULT_MODEL = os.environ.get("OPENHANDS_DEFAULT_MODEL", "gpt-5.4")
CHEETAHCLAWS_DEFAULT_MODEL = os.environ.get("CHEETAHCLAWS_DEFAULT_MODEL", "gpt-5.4")
AGENTZERO_DEFAULT_MODEL = os.environ.get("AGENTZERO_DEFAULT_MODEL", "gpt-5.4")
CODEX_REASONING_EFFORT = os.environ.get("CODEX_REASONING_EFFORT", "medium")
# The window Codex plans compaction against. Its own catalog says 272k for every gpt-5.x; a larger
# number here made it compact late and let a long thread overflow the real window first.
CODEX_CONTEXT_WINDOW = os.environ.get("CODEX_CONTEXT_WINDOW", "272000")
# Kimi Code CLI takes the model's window as KIMI_MODEL_MAX_CONTEXT_SIZE (its own default is 256k) and
# plans compaction against it. The same problem codex has above, solved the same way and for the
# same reason: a number that is too LARGE compacts late and lets the thread overflow the real window
# (the provider then 400s); too small compacts early and wastes tokens on a turn that would have
# fit. One value across the catalog is a known approximation: it is honest only because being wrong
# changes WHEN the agent compacts, never whether it answers. A per-id window belongs in the catalog.
KIMI_CONTEXT_WINDOW = os.environ.get("KIMI_CONTEXT_WINDOW", "272000")
# Provider defaults (overridable per-turn via auth.base_url). Wired from pool env.
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
AZURE_OPENAI_BASE_URL = os.environ.get("AZURE_OPENAI_BASE_URL", "")
# Hard wall-clock cap per turn — resource-abuse protection. A runaway/abusive run is killed
# at this many seconds (default 6h). The agent finishing earlier ends the turn promptly.
MAX_TURN_SECONDS = int(os.environ.get("MAX_TURN_SECONDS", "21600"))

# ── Yjs blackboard sidecar (realtime co-edit; bridges a workspace file <-> a Hocuspocus room) ──
# The sidecar is a Node child process baked into the image at /app/sidecar. It is (re)started per
# session from /hydrate with the session's COLLAB_URL + room (passed as query params by the gateway).
_SIDECAR_JS = "/app/sidecar/sidecar.mjs"
_BLACKBOARD_REL = os.path.join(HARNESS_STATE, "BLACKBOARD.md")   # /workspace/.harness/BLACKBOARD.md
_sidecars: dict[str, dict] = {}          # session id -> {proc, room, error}
_sidecar_lock = threading.Lock()


def _start_sidecar(sid: str, collab_url: str, room: str, token: str = "") -> None:
    """(Re)start the blackboard sidecar for THIS session. Kill+respawn on every hydrate — a reused
    warm-pool sandbox may carry a prior tenant's sidecar (same isolation reasoning as the /workspace
    wipe). Best-effort: a sidecar failure must never affect the turn."""
    ws = _ws(sid)
    file = os.path.join(ws, _BLACKBOARD_REL)
    with _sidecar_lock:
        entry = _sidecars.setdefault(sid, {"proc": None, "room": None})
        old = entry.get("proc")
        if old is not None and old.poll() is None:
            try:
                old.terminate()
            except Exception:  # noqa: BLE001
                pass
        if not (collab_url and room and os.path.exists(_SIDECAR_JS)):
            entry.update(proc=None, room=None)
            return
        try:
            pathlib.Path(file).parent.mkdir(parents=True, exist_ok=True)
            if not pathlib.Path(file).exists():
                pathlib.Path(file).write_text("")
            env = {**os.environ, "COLLAB_URL": collab_url, "ROOM": room,
                   "BLACKBOARD_FILE": file, "COLLAB_TOKEN": token or ""}
            logf = open(os.path.join(ws, HARNESS_STATE, "sidecar.log"), "ab")  # diagnostics
            entry.update(proc=subprocess.Popen(["node", _SIDECAR_JS], cwd=ws, env=env,
                                               stdout=logf, stderr=logf, **_as_session(ws)),
                         room=room, error=None)
        except Exception as e:  # noqa: BLE001
            entry.update(proc=None, room=None, error=str(e)[:200])


def _sidecar_alive(sid: str = "") -> bool:
    p = (_sidecars.get(sid) or {}).get("proc")
    return bool(p is not None and p.poll() is None)


def _ver(cmd: list[str]) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return (p.stdout or p.stderr).strip()
    except Exception as e:  # noqa: BLE001
        return f"(unavailable: {e})"


# ── git-backed workspace (hydrate at turn start, checkpoint at turn end) ───────────
def _git(ws: str, *args: str, check: bool = False, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", ws, *args], capture_output=True, text=True,
                          env={**os.environ, **_GIT_ENV, **(env or {})}, check=check, **_as_session(ws))


# Config the runner rewrites every turn and that can carry MCP credentials (see CHECKPOINT_EXCLUDE).
_PER_TURN_CONFIG = (".harness/opencode.json", ".harness/kilo.json", ".harness/mcp.json",
                    ".harness/mcp-bridge/")


def _git_ensure(ws: str) -> None:
    """Make /workspace a git repo with a secret-safe .gitignore (so .git, which travels in the
    checkpoint tarball, never carries credentials).

    The CLI home (.harness/home) is ignored here too. The repo has one reader, /produced, and it
    already drops every `.harness/` path (_PRODUCED_EXCLUDE_PREFIX); the home still travels
    between turns because the checkpoint is a tar of the directory, not a `git archive`, so
    --resume is unaffected. Committing it gave every transcript and session database a second
    copy in .git/objects per checkpoint — and on opencode the two fed each other, its snapshot
    repo (work tree = the workspace) capturing our .git while we committed its snapshots: twenty
    turns of one small file reached a 1.4 GB tarball for ~220 KB of output and the gateway OOMed
    (#193, 2026-09-16)."""
    p = pathlib.Path(ws)
    p.mkdir(parents=True, exist_ok=True)
    (p / ".gitignore").write_text("\n".join([
        "# harness: never persist secrets/scratch in the session checkpoint",
        "tmp/", ".gcp-sa.json", ".codex/", ".credentials.json", ".harness/**/.credentials.json",
        ".harness/home/.hermes/.env", ".harness/home/.hermes/auth.json",
        ".harness/home/.pi/agent/auth.json", ".harness/home/.pi/agent/models.json",
        ".harness/goose/config/secrets.yaml",
        ".cheetahclaws/tasks.json",
        ".harness/agentzero/base/usr/.env", ".harness/agentzero/base/usr/secrets.env",
        *_PER_TURN_CONFIG,
        "# harness: the CLI home is checkpointed by tar, not by this repo (see _git_ensure)",
        ".harness/home/",
        # Agent Zero's whole base, for the #193 reason: its chat.json stores the full rendered
        # prompt (ctx_window) on every save, so committing it would put a new copy of the system
        # prompt into .git/objects each turn. It travels in the tar like the CLI home does.
        ".harness/agentzero/",
        "",
    ]))
    if not (p / ".git").exists():
        _git(ws, "init", "-q")
        _git(ws, "config", "user.email", _GIT_ENV["GIT_AUTHOR_EMAIL"])
        _git(ws, "config", "user.name", _GIT_ENV["GIT_AUTHOR_NAME"])
    else:
        # An ignore rule does not release what an earlier checkpoint already committed: a
        # tracked path is re-added by every `git add -A` regardless of .gitignore, so a session
        # hydrated from before this rule would keep growing exactly as before. Drop the CLI
        # home from the index (not from disk); from then on the ignore rule holds.
        # The same for the per-turn config files: a session checkpointed before they were ignored
        # tracks them, and an ignore rule alone would keep committing each turn's credentials.
        _git(ws, "rm", "-r", "-q", "--cached", "--ignore-unmatch", "--", *_PER_TURN_CONFIG)
        tracked = bool(_git(ws, "ls-files", "--", ".harness/home").stdout.strip())
        if tracked:
            _git(ws, "rm", "-r", "-q", "--cached", "--ignore-unmatch", "--", ".harness/home")
        # Untracking releases the index, not .git/objects: every copy the old checkpoints
        # committed stays reachable from those commits and rides in every later tarball of the
        # session (722 MB of the 1.4 GB in #193). The gate is the index or the tip's tree, both
        # O(1): before the rule every checkpoint re-added the home with `add -A`, so a history
        # that holds it also holds it at the tip (the one gap, the index released but the tip
        # not yet rewritten, is a crash between the two calls above and below, and the tip
        # covers it). A walk of the history (`rev-list -- .harness/home`) would find the same
        # repos and cost 130 ms per call at a thousand commits, four calls a turn, for the life
        # of every session. Once per session: the shed leaves no home in either tree it keeps.
        if tracked or _git(ws, "rev-parse", "-q", "--verify", "HEAD:.harness/home").returncode == 0:
            _git_shed_cli_home_history(ws)


def _git_shed_cli_home_history(ws: str) -> None:
    """Rewrite a pre-#193 workspace repo down to what /produced reads — the collected cursor's
    tree and HEAD's tree, each without .harness/home — and prune everything else.

    /produced is the repo's one reader, and it reads two things: `diff refs/hr/collected` against
    the worktree, and `status` (see _produced_list). Neither looks past those two trees, so the
    history between and before them is dead weight, and for a session checkpointed before the
    ignore rule it is where every earlier copy of the CLI home lives. Untracking alone leaves those
    blobs reachable from the old commits, so the tarball would carry them on every later turn.
    Each tree is rebuilt in a scratch index minus .harness/home (a path /produced excludes anyway),
    so the cursor→worktree diff a caller sees before and after this is the same set of files.
    gc prunes the unreachable blobs; on the reported repo that is the one-off cost of one gc,
    paid at the session's first turn after upgrade."""
    if _git(ws, "rev-parse", "-q", "--verify", "HEAD").returncode != 0:
        return                                   # nothing committed yet: nothing to shed
    scratch = os.path.join(ws, ".git", "hr-shed-index")   # owned by the session, like the rest of .git

    def _tree_without_home(commit: str) -> str:
        env = {"GIT_INDEX_FILE": scratch}
        _git(ws, "read-tree", commit, env=env)
        _git(ws, "rm", "-r", "-q", "--cached", "--ignore-unmatch", "--", ".harness/home", env=env)
        return _git(ws, "write-tree", env=env).stdout.strip()

    try:
        parent: list[str] = []
        if _git(ws, "rev-parse", "-q", "--verify", _COLLECTED_REF).returncode == 0:
            c_tree = _tree_without_home(_COLLECTED_REF)
            c_new = _git(ws, "commit-tree", c_tree, "-m", "collected (cli home history shed)").stdout.strip()
            if c_new:
                _git(ws, "update-ref", _COLLECTED_REF, c_new)
                parent = ["-p", c_new]
        h_tree = _tree_without_home("HEAD")
        h_new = _git(ws, "commit-tree", h_tree, *parent, "-m", "checkpoint (cli home history shed)").stdout.strip()
        if h_new:
            _git(ws, "update-ref", "HEAD", h_new)      # HEAD is symbolic: this moves the branch
    finally:
        try:
            os.unlink(scratch)
        except OSError:
            pass
    _git(ws, "reflog", "expire", "--expire=now", "--all")
    _git(ws, "gc", "-q", "--prune=now")


# ── input/output file plumbing (OpenAI Responses input_file blocks + container files) ──
# Paths never reported as agent-produced output (internal state / scratch / secrets / vcs).
_PRODUCED_EXCLUDE_PREFIX = (".harness/", "tmp/", ".codex/", ".git/", ".claude/", ".pi/",
                            # cheetahclaws: its project-level skills folder (written by
                            # _write_skills) and its task tracker, both CLI state
                            ".cheetahclaws/",
                            "node_modules/", ".venv/", "venv/", "__pycache__/", ".cache/", ".next/")
_PRODUCED_EXCLUDE_NAMES = {".gitignore", ".gcp-sa.json", ".credentials.json"}
# Dependency / install / build-cache noise the agent pulls in (apt debs, npm/py deps, byte-compiled
# files). These are NOT the user's artifact — keep real build OUTPUT (dist/, build/) but drop the
# package machinery so the produced-files list shows the deliverable, not chrome-deps/*.deb etc.
_NOISE_SEG = {"node_modules", "chrome-deps", "debs", ".venv", "venv", "site-packages", "vendor",
              "__pycache__", ".cache", ".git", ".next", ".pytest_cache", ".mypy_cache", ".npm",
              ".harness", ".codex", ".claude", "bower_components", ".gradle", ".tox"}
_NOISE_EXT = (".deb", ".whl", ".pyc", ".pyo", ".so", ".o", ".a", ".class", ".rpm", ".apk")


def _is_produced_noise(path: str) -> bool:
    if any(seg in _NOISE_SEG for seg in path.split("/")):
        return True
    return path.lower().endswith(_NOISE_EXT)


def _safe_join(cwd: str, rel: str) -> pathlib.Path | None:
    """Resolve rel under cwd, rejecting absolute/traversal escapes (multi-tenant safety)."""
    base = pathlib.Path(cwd).resolve()
    p = (base / rel.lstrip("/")).resolve()
    try:
        p.relative_to(base)
    except ValueError:
        return None
    return p


def _write_input_files(cwd: str, files: list[dict] | None) -> list[str]:
    """Write caller-attached input files (base64) into the workspace so the agent can read them."""
    written: list[str] = []
    for f in (files or []):
        name = (f or {}).get("filename")
        b64 = (f or {}).get("content_b64")
        if not name or b64 is None:
            continue
        dest = _safe_join(cwd, name)
        if dest is None:
            continue
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(base64.b64decode(b64))
            written.append(name)
        except Exception:  # noqa: BLE001
            continue
    return written


# ── plugins: MCP servers + Skills (materialized into the workspace per turn) ─────────
# Both are config the harness owner attaches (gateway resolves them from the Harness vertex
# and any vault token refs, passes only the ENABLED ones here). MCP servers become a
# .mcp.json the CLI loads; skills become folders the CLI auto-discovers.
_MCP_NAME_RE = __import__("re").compile(r"[^a-zA-Z0-9_]+")


_SKILL_NAME_RE = re.compile(r"[^A-Za-z0-9_-]+")


def _skill_dir_name(s: str) -> str:
    """A skill's directory name: what the author called it, minus anything that could leave the
    directory. Hyphens are KEPT — kebab-case is the skill format's own convention, every SKILL.md
    frontmatter uses it, and the CLIs match a skill by that name. Renaming `test-skill` to
    `test_skill` (the MCP sanitizer, built for a different job) made the directory disagree with
    the frontmatter inside it and with what the user asked for by name."""
    n = _SKILL_NAME_RE.sub("-", (s or "").strip()).strip("-_")
    return n or "skill"


def _mcp_headers(s: dict | None) -> dict[str, str]:
    """A remote server's HTTP headers: `auth` (the bearer the gateway resolved for the harness)
    as Authorization, then the declared headers, which win on a clash. EVERY writer and the
    bridge take a server's headers from here and nowhere else: eight writers took only the
    declared headers and dropped `auth`, so the plugs server (hosted, auth minted per turn)
    answered 401 to kimi, aider, opencode, qwen, gemini, goose, openhands and cline, and those
    bases had no browser at all (the browser column on hr-test, 2026-09-27)."""
    out: dict[str, str] = {}
    auth = (s or {}).get("auth")
    if auth:
        out["Authorization"] = auth if str(auth).lower().startswith("bearer ") else f"Bearer {auth}"
    hdrs = (s or {}).get("headers")
    if isinstance(hdrs, dict):
        out.update({str(k): str(v) for k, v in hdrs.items() if k and v is not None})
    return out


def _mcp_name(s: str) -> str:
    """Sanitize an MCP server name into a CLI-safe identifier (alnum + underscore)."""
    n = _MCP_NAME_RE.sub("_", (s or "").strip()).strip("_")
    return n or "mcp"


def _write_mcp_config_claude(cwd: str, servers: list[dict],
                             dest: pathlib.Path | None = None) -> str | None:
    """Write a Claude Code .mcp.json for the enabled MCP servers. Returns its path
    (passed via --mcp-config), or None if there are none. `dest` puts the same document where
    another CLI that reads this format looks for it (cheetahclaws: ~/.cheetahclaws/mcp.json).

    Both remote (http/sse, keyed on `url`) and local (stdio, keyed on `command`) servers
    are supported — stdio is the CLI's own default transport (`claude mcp add` defaults to
    it, and a stdio entry is just `{"type": "stdio", "command": ..., "args": [...]}` in the
    same .mcp.json this already writes), so accepting one here is not a new format, only a
    second field this function previously never looked at."""
    entries: dict = {}
    for s in servers or []:
        s = s or {}
        name = _mcp_name(s.get("name") or s.get("id") or "mcp")
        url = s.get("url")
        command = s.get("command")
        if url:
            transport = (s.get("transport") or "http").lower()
            entry = {"type": "sse" if transport == "sse" else "http", "url": url}
            if _mcp_headers(s):
                entry["headers"] = _mcp_headers(s)
        elif command:
            entry = {"type": "stdio", "command": command, "args": s.get("args") or []}
            if isinstance(s.get("env"), dict):
                entry["env"] = s["env"]
        else:
            continue
        entries[name] = entry
    if not entries:
        return None
    path = dest or pathlib.Path(cwd) / HARNESS_STATE / "mcp.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mcpServers": entries}, indent=2))
    return str(path)


def _codex_mcp_toml(servers: list[dict]) -> str:
    """Render [mcp_servers.*] config.toml blocks for Codex's experimental remote-MCP (rmcp)
    HTTP client. Returns '' if there are no HTTP servers to add."""
    blocks: list[str] = []
    for s in servers or []:
        url = (s or {}).get("url")
        name = _mcp_name((s or {}).get("name") or (s or {}).get("id") or "mcp")
        if not url and (s or {}).get("command"):
            # A stdio server (a plugin's, through its launcher): Codex's native shape.
            def _tq(x: str) -> str:
                s2 = str(x).replace("\\", "\\\\").replace('"', '\\"')
                s2 = s2.replace("\n", "\\n").replace("\t", "\\t").replace("\r", "\\r")
                s2 = "".join(c if ord(c) >= 32 and c != "\x7f" else f"\\u{ord(c):04X}" for c in s2)
                return '"' + s2 + '"'
            blocks.append("\n".join([f"[mcp_servers.{name}]", f"command = {_tq(s['command'])}",
                                     "args = [" + ", ".join(_tq(a) for a in (s.get("args") or [])) + "]"]))
            continue
        if not url:
            continue
        lines = [f"[mcp_servers.{name}]", f'url = "{url}"']
        # One http_headers inline table: Authorization from `auth` + any extra headers the
        # gateway resolved (e.g. Additional Headers / $headers.{name} app-auth values).
        hdrs = _mcp_headers(s)
        if hdrs:
            def _tesc(x: str) -> str:
                return x.replace("\\", "\\\\").replace('"', '\\"')
            inner = ", ".join(f'"{_tesc(k)}" = "{_tesc(v)}"' for k, v in hdrs.items())
            lines.append(f"http_headers = {{ {inner} }}")
        blocks.append("\n".join(lines))
    if not blocks:
        return ""
    # rmcp HTTP client is opt-in in Codex; enable it when any HTTP MCP server is configured.
    # (stdio servers need no switch; the flag is harmless beside them.)
    return "\nexperimental_use_rmcp_client = true\n" + "\n".join(blocks) + "\n"


def _skill_desc(files: list[dict]) -> str:
    """Best-effort one-line description from a skill's SKILL.md (YAML `description:` or first prose)."""
    for f in files or []:
        if str((f or {}).get("path", "")).lower().endswith("skill.md"):
            txt = (f or {}).get("content") or ""
            m = re.search(r"(?im)^description:\s*(.+)$", txt)
            if m:
                return m.group(1).strip().strip("\"'")
            for line in txt.splitlines():
                s = line.strip().lstrip("#").strip()
                if s and not s.startswith("---") and not s.lower().startswith("name:"):
                    return s[:200]
    return ""


def _write_skills(cwd: str, skills: list[dict], backend: str = "claude") -> list[dict]:
    """Materialize enabled skills for the harness's backend (HRP-008):
      - claude: `.harness/home/.claude/skills/<name>/` — the CLI discovers personal skills
        under $CLAUDE_CONFIG_DIR/skills, and the config dir is redirected to
        <cwd>/.harness/home/.claude (see _build_claude). ALSO mirrored to the project
        `.claude/skills/<name>/` so direct reads and project-scoped discovery both work.
      - codex:  .harness/skills/<name>/ (surfaced via AGENTS.md; .harness/ stays out of outputs)
      - pi:     .harness/home/.pi/agent/skills/<name>/ — pi's USER-GLOBAL skills dir under the
        redirected $HOME. User-global on purpose: pi gates project-local files behind its trust
        decision, and user-global skills load unconditionally (agentskills.io format, which is
        the same SKILL.md this product already stores).
    Each skill: {name, files:[{path, content}]} (or {content} -> SKILL.md).
    Returns [{name, desc, entry}] for the skills actually installed (entry = SKILL.md path)."""
    # EVERY CLI WITH A SKILL LOADER GETS ITS SKILLS WHERE THAT LOADER LOOKS. The CLI then presents
    # each skill to the model with its directory and its own rules about relative paths, which is
    # the mechanism that makes skills work at all. Codex and hermes used to get a directory of
    # our own invention (.harness/skills) plus prose in AGENTS.md; a weaker model read the
    # SKILL.md at the path we gave it, then ran its "test.py" in the workspace root, twice, and
    # `rg --files` never showed it the file because the tree was hidden (2026-08-23).
    if backend == "claude":
        rootrels = [".harness/home/.claude/skills", ".claude/skills"]
        entryroot = ".claude/skills"
    elif backend == "pi":
        rootrels = [".harness/home/.pi/agent/skills"]
        entryroot = ".harness/home/.pi/agent/skills"
    elif backend == "omp":
        rootrels = [".harness/home/.omp/agent/skills"]
        entryroot = ".harness/home/.omp/agent/skills"
    elif backend == "codex":
        # $CODEX_HOME/skills/<name>/SKILL.md, and CODEX_HOME is redirected into the workspace
        rootrels = [".harness/home/.codex/skills"]
        entryroot = ".harness/home/.codex/skills"
    elif backend == "hermes":
        # $HERMES_HOME/skills/<name>/SKILL.md: the <available_skills> index hermes builds itself
        rootrels = [".harness/home/.hermes/skills"]
        entryroot = ".harness/home/.hermes/skills"
    elif backend == "qwen":
        # ~/.qwen/skills under the redirected HOME — the dir the shipped 0.22.1 creates itself.
        rootrels = [".harness/home/.qwen/skills"]
        entryroot = ".harness/home/.qwen/skills"
    elif backend == "gemini":
        # ~/.gemini/skills under the redirected HOME — live-verified (2026-09-06, 0.58.0): the
        # slides/sheets/videos starter-kit skills all activated correctly from this path via the
        # real activate_skill tool ("Resources loaded from .../.gemini/skills/<name>"), same
        # directory-drop shape as qwen's despite gemini-cli's own settings.json also documenting a
        # separate skills.enabled/disabled key — that key toggles skills, it doesn't relocate them.
        rootrels = [".harness/home/.gemini/skills"]
        entryroot = ".harness/home/.gemini/skills"
    elif backend == "goose":
        # <GOOSE_PATH_ROOT>/config/skills — a GLOBAL, writable skills root in goose's own
        # discovery list (all_skill_dirs_with_config pushes Paths::config_dir().join("skills"),
        # crates/goose/src/skills/mod.rs). Deliberately NOT the project root's .agents/skills,
        # which goose also reads: that lives in the workspace, and _PRODUCED_EXCLUDE_PREFIX does
        # not exclude .agents/, so every harness skill would be handed back to the user as a
        # deliverable on every turn. This path is under .harness/ and is therefore already
        # excluded and already checkpointed. Note goose refuses a skill whose SKILL.md `name`
        # frontmatter does not match its directory name.
        rootrels = [".harness/goose/config/skills"]
        entryroot = ".harness/goose/config/skills"
    elif backend == "cheetahclaws":
        # <cwd>/.cheetahclaws/skills — the PROJECT-level root of the CLI's loader
        # (skill/loader.py _get_skill_paths: project first, then ~/.cheetahclaws/skills, then the
        # built-ins, deduplicated in that order), so a harness skill wins over a built-in of the
        # same name. It is in the workspace, and `.cheetahclaws/` is in _PRODUCED_EXCLUDE_PREFIX
        # for that reason: the bundle is never handed back as a deliverable. The loader reads
        # `SKILL.md` or `skill.md` with the Claude Code frontmatter, and the agent reaches a skill
        # through its own `Skill` and `SkillList` tools.
        rootrels = [".cheetahclaws/skills"]
        entryroot = ".cheetahclaws/skills"
    elif backend == "kimi":
        # --skills-dir "Overrides default discovery" (repeatable), so like opencode the loader
        # adapts to us and there is no per-CLI home directory to guess. Verified on 1.50.0: a skill
        # written here appeared in the system prompt under an "### Extra" scope heading with its
        # path and its frontmatter description. Default discovery would otherwise sweep
        # .kimi/skills, .claude/skills, .codex/skills and .agents/skills — including trees another
        # backend wrote — which is a second reason to name the directory explicitly.
        rootrels = [".harness/skills"]
        entryroot = ".harness/skills"
    elif backend == "grok":
        # $GROK_HOME/skills/<name>/SKILL.md, grok's user skill root, with GROK_HOME redirected to
        # .harness/home/.grok. Verified on 1.0.41: a skill here was listed to the model with its
        # description. Not the project's .grok/skills: the workspace root is collected.
        rootrels = [".harness/home/.grok/skills"]
        entryroot = ".harness/home/.grok/skills"
    elif backend == "minimax":
        # $MINIMAX_DATA_DIR/skills/<name>/SKILL.md, the CLI's user-global root (skills/roots.ts,
        # 0.5.4). Measured at a stub: the skill's description reached the system prompt and its body
        # did not (loaded on demand through the `skill` tool). External discovery — the workspace's
        # .minimax/.claude/.agents skills with walk-up, and the home ones — is switched off in
        # config.yaml, so a tree another backend wrote is not swept in (kimi's reason).
        rootrels = [".harness/home/.minimax/skills"]
        entryroot = ".harness/home/.minimax/skills"
    elif backend in ("opencode", "kilo"):
        # Kilo CLI is opencode's fork and keeps the same `skills.paths` key (core/src/v1/config/
        # skills.ts at 7.8.1), so it takes the same directory.
        # opencode's `skills` config key takes ARBITRARY paths ("Additional paths or URLs to
        # discover skills from"), so there is no per-CLI home directory to guess here — we write
        # one directory and name it in opencode.json. This is the only backend where the loader
        # adapts to us instead of the other way round.
        rootrels = [".harness/skills"]
        entryroot = ".harness/skills"
    elif backend == "agentzero":
        # usr/skills/<name>/SKILL.md under the workspace's Agent Zero base — the user skills root its
        # own loader scans (helpers/skills.get_skill_roots: files.get_abs_path("usr/skills")), and
        # the driver makes that base's usr/ this directory. Under .harness/, so excluded from
        # produced files and carried in the checkpoint.
        rootrels = [".harness/agentzero/base/usr/skills"]
        entryroot = ".harness/agentzero/base/usr/skills"
    else:
        # dsh has no skill loader; the AGENTS.md block below is the only door.
        # aider lands here on purpose too, and for a stronger reason: it has no skill loader AND no
        # instruction-file discovery, so its turn builder passes every file under this directory to
        # --read explicitly. Under .harness/ the bundle is excluded from produced files, so a skill
        # is never handed back to the user as a deliverable of their own task.
        rootrels = [".harness/skills"]
        entryroot = ".harness/skills"
    # cline lands in the else on purpose, with the evidence written down so nobody "fixes" it:
    # its own `skill list` attributes ~/.agents/skills to agent "Cline" and .claude/skills to
    # "Claude Code", but a headless 3.0.60 run injects NEITHER into the system prompt — probed
    # with skills installed at .claude/skills, ~/.agents/skills and ./.agents/skills against a
    # stub upstream that dumps the system message: zero mentions, all three locations. So the
    # loader that its tooling implies does not run headless, and the AGENTS.md advertisement is
    # the one mechanism that verifiably reaches the model.
    installed: list[dict] = []
    for sk in skills or []:
        name = _skill_dir_name((sk or {}).get("name") or (sk or {}).get("id") or "")
        if not name:
            continue
        files = (sk or {}).get("files")
        if not files and (sk or {}).get("content"):
            files = [{"path": "SKILL.md", "content": sk["content"]}]
        if not files:
            continue
        wrote = False
        for f in files:
            rel = (f or {}).get("path")
            content = (f or {}).get("content")
            content_b64 = (f or {}).get("content_b64")
            if not rel or (content is None and content_b64 is None):
                continue
            for rootrel in rootrels:
                dest = _safe_join(str(pathlib.Path(cwd) / rootrel / name), rel)
                if dest is None:
                    continue
                try:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if content_b64 is not None:
                        dest.write_bytes(base64.b64decode(content_b64))
                    else:
                        dest.write_text(content)
                    wrote = True
                except Exception:  # noqa: BLE001
                    continue
        if wrote:
            installed.append({"name": name, "desc": _skill_desc(files),
                              "entry": f"{entryroot}/{name}/SKILL.md"})
    # Skills this runner wrote on an earlier turn of the session that this turn does not name
    # (disabled, removed, or a plugin's that is now off) are removed, so the CLI cannot keep
    # offering them. Only what this runner wrote is touched: the record of that is its own.
    now_names = {s["name"] for s in installed}
    ledger = _safe_join(cwd, ".harness/skills-written.json")
    if ledger is not None:
        before: list[str] = []
        try:
            before = [str(n) for n in json.loads(ledger.read_text())] if ledger.is_file() else []
        except Exception:  # noqa: BLE001
            before = []
        for old in before:
            if old in now_names or not old:
                continue
            for rootrel in rootrels:
                d = _safe_join(str(pathlib.Path(cwd) / rootrel), old)
                if d is not None and d.is_dir() and not d.is_symlink():
                    shutil.rmtree(d, ignore_errors=True)
        try:
            ledger.parent.mkdir(parents=True, exist_ok=True)
            ledger.write_text(json.dumps(sorted(now_names)))
        except Exception:  # noqa: BLE001
            pass
    return installed


# A plugin's hooks and CLI entry points are run directly by the shell, not by an interpreter
# named on the command line — Claude Code's own convention (see any real plugin's hooks.json,
# which invokes hooks/*.sh with no leading `sh`) requires the executable bit on disk. JSON has
# no file-mode concept, so a caller may say so explicitly (`{"executable": true}` per file); where
# it does not, the well-known locations a Claude Code plugin's own manifest format expects
# scripts to live in — `bin/*` and `hooks/*.sh` — are treated as executable by convention, the
# same convention the format itself already relies on. Verified the hard way: without this,
# --plugin-dir loads the plugin's manifest fine and every hook invocation then fails with
# "Permission denied" — a difference invisible until a hook actually fires.
_PLUGIN_EXEC_PATTERNS = (re.compile(r"^bin/[^/]+$"), re.compile(r"^hooks/[^/]+\.sh$"))


def _plugin_file_is_executable(rel: str, declared: bool | None) -> bool:
    if declared is not None:
        return bool(declared)
    return any(p.match(rel) for p in _PLUGIN_EXEC_PATTERNS)


def _write_plugins(cwd: str, plugins: list[dict]) -> list[str]:
    """Materialize each installed plugin package whole, at its own root under
    `.harness/plugins/<name>/`, with a writable data directory beside it under
    `.harness/plugin-data/<name>/` (UHP Plugins §6: PLUGIN_ROOT and PLUGIN_DATA). Each plugin:
    {name, files:[{path, content|content_b64, executable?}]}. Returns the roots written, in order.

    The package's skills reach the agent through the ordinary skill path (the gateway lists them
    in `skills`); its stdio servers run from this root through the launchers _plugin_launchers
    writes. A package that also carries `.claude-plugin/plugin.json` is a Claude Code plugin
    besides, and the claude branch hands that root to `--plugin-dir`: one root, never a second
    copy under .claude/, which would risk Claude Code loading the same plugin twice."""
    installed: list[str] = []
    wanted: set[str] = set()
    for pg in plugins or []:
        pg = pg or {}
        name = _mcp_name(pg.get("name") or pg.get("id") or "")
        files = pg.get("files")
        if not name or not files:
            continue
        root = _safe_join(cwd, f".harness/plugins/{name}")
        data = _safe_join(cwd, f".harness/plugin-data/{name}")
        if root is None or data is None:
            continue
        wanted.add(name)
        # The runner writes as itself and the agent ran as the session's uid last turn: a root
        # or data directory it replaced with a symlink would redirect these writes, so the link
        # itself (the unresolved path) is removed before anything is written through it, and the
        # root is rebuilt from the package every turn so nothing from an older version lingers.
        for raw in (pathlib.Path(cwd) / ".harness" / "plugins" / name,
                    pathlib.Path(cwd) / ".harness" / "plugin-data" / name):
            if raw.is_symlink():
                raw.unlink()
        root = _safe_join(cwd, f".harness/plugins/{name}")
        data = _safe_join(cwd, f".harness/plugin-data/{name}")
        if root is None or data is None:
            continue
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)
        data.mkdir(parents=True, exist_ok=True)
        wrote = False
        for f in files:
            f = f or {}
            rel = f.get("path")
            content = f.get("content")
            content_b64 = f.get("content_b64")
            if not rel or (content is None and content_b64 is None):
                continue
            dest = _safe_join(str(root), rel)
            if dest is None:
                continue
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                # Written beside and renamed over: a binary a still-running server has open
                # cannot be truncated in place (ETXTBSY), and a rename replaces it regardless.
                tmp = dest.with_name(dest.name + ".hr-tmp")
                if content_b64 is not None:
                    tmp.write_bytes(base64.b64decode(content_b64))
                else:
                    tmp.write_text(content)
                if _plugin_file_is_executable(rel, f.get("executable")):
                    tmp.chmod(tmp.stat().st_mode | 0o111)
                os.replace(tmp, dest)
                wrote = True
            except Exception:  # noqa: BLE001
                continue
        if wrote:
            installed.append(str(root))
    # A plugin removed or disabled since the last turn leaves nothing runnable behind.
    plugroot = _safe_join(cwd, ".harness/plugins")
    if plugroot is not None and plugroot.is_dir():
        for d in plugroot.iterdir():
            if d.name not in wanted:
                if d.is_symlink():
                    d.unlink()
                else:
                    shutil.rmtree(d, ignore_errors=True)
    return installed


_PLUGIN_PLACEHOLDER = re.compile(r"\$\{PLUGIN_(ROOT|DATA)\}")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# Remote transports a client cannot reach on its own, by backend: goose 1.50.0's ExtensionConfig
# has no sse variant, dsh-mcp-client's config is a union of stdio and streamable-http, codex's
# client takes streamable HTTP and stdio, and CheetahClaws 3.5.88's own streamable-HTTP client is
# answered 400 on initialize by a standard server (the public probe; its SSE and stdio work).
# Every one of them launches a stdio server, so the runner hands them the bridge (mcp_bridge.py)
# as one, and the bridge speaks the remote transport with the reference SDK. The server reaches
# the agent on every base the same way; nothing is declared unsupported.
#
# grok is here for a sharper reason: it ADVERTISES SSE and then does not speak it. `type = "sse"`
# beside the url is the shape its own `grok mcp add --transport sse` writes, and 1.0.41 accepts that
# and dials the url with its STREAMABLE-HTTP client — the error names the worker
# (`StreamableHttpClientWorker … HTTP 405 Method Not Allowed, when send initialize request`) and the
# server's log shows a POST to an endpoint that answers GET. Measured 2026-09-28 against a local SSE
# server with BOTH the vendor-written config and this runner's, and reproduced by `grok mcp doctor`,
# so it is the CLI's defect rather than this file's config. Untreated it is silent: the tools never
# arrive, `search_tool` answers "No MCP tools are available in this session", and the turn runs
# without them. Its streamable-HTTP client is fine (verified against a local server and the public
# deepwiki one, tools discovered and called), so only SSE is bridged.
_BRIDGED_TRANSPORTS = {"codex": ("sse",), "dsh": ("sse",), "goose": ("sse",), "grok": ("sse",),
                       "cheetahclaws": ("http",)}
_MCP_BRIDGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_bridge.py")


def _sse_bridges(cwd: str, servers: list[dict] | None, backend: str) -> list[dict]:
    """Each remote server whose transport this backend's client cannot reach becomes a stdio
    launcher that runs the bridge with the url, the transport and the headers in its environment
    (never on the command line, where a ps listing would show an Authorization header). A url
    without a transport is streamable HTTP, as everywhere else in this file. Other servers and
    backends pass untouched."""
    bridged = _BRIDGED_TRANSPORTS.get(backend)
    if not bridged:
        return list(servers or [])
    out: list[dict] = []
    for s in servers or []:
        s = s or {}
        url = str(s.get("url") or "").strip()
        transport = str(s.get("transport") or "http").lower()
        if not url or transport not in bridged:
            out.append(s)
            continue
        name = _mcp_name(str(s.get("name") or s.get("id") or "mcp"))
        headers = _mcp_headers(s)
        bdir = pathlib.Path(_safe_join(cwd, ".harness/mcp-bridge"))
        bdir.mkdir(parents=True, exist_ok=True)
        launcher = bdir / f"{name}.sh"
        lines = ["#!/bin/sh", f"# written by the harness runner: this client cannot reach a {transport} server, so the bridge speaks it over stdio",
                 f"export HR_MCP_URL={shlex.quote(url)}", f"export HR_MCP_TRANSPORT={transport}",
                 f"export HR_MCP_HEADERS={shlex.quote(json.dumps(headers))}",
                 f"exec python3 {shlex.quote(_MCP_BRIDGE)}", ""]
        if launcher.is_symlink() or (launcher.exists() and not launcher.is_file()):
            launcher.unlink()
        fd = os.open(str(launcher), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o755)
        with os.fdopen(fd, "w") as fh:
            fh.write("\n".join(lines))
        launcher.chmod(0o755)
        out.append({k: v for k, v in s.items() if k not in ("url", "transport", "auth", "headers")} | {"name": s.get("name") or name, "command": str(launcher), "args": []})
    return out


def _plugin_launchers(cwd: str, servers: list[dict] | None) -> list[dict]:
    """The stdio servers a plugin declares, made runnable (UHP Plugins §6, Agent Plugins §7.2.1
    and §9): the two placeholders expanded once and non-recursively in args, env and cwd; a
    `./` command resolved against the plugin root and refused if it escapes; cwd defaulting to the
    root and confined to the root or the data directory; PLUGIN_ROOT and PLUGIN_DATA set last.

    All of that lands in one launcher script per server in the plugin's data directory, so every
    backend writer sees the same shape it already understands, {name, command, args}, and none of
    the nine has to learn env or cwd. The user's command is exec'd with its args as argv, never
    parsed by the shell. Servers that are not a plugin's pass through untouched."""
    out: list[dict] = []
    for s in servers or []:
        s = s or {}
        pname = s.get("plugin")
        if not pname or not s.get("command") or s.get("url"):
            out.append(s)
            continue
        dname = _mcp_name(str(pname))
        raw_data = pathlib.Path(cwd) / ".harness" / "plugin-data" / dname
        if raw_data.is_symlink():          # never write the launcher through a planted link
            raw_data.unlink()
        root = _safe_join(cwd, f".harness/plugins/{dname}")
        data = _safe_join(cwd, f".harness/plugin-data/{dname}")
        if root is None or data is None or not root.is_dir():
            print(f"[plugins] '{s.get('name')}': plugin {pname} has no root in this workspace — skipped", flush=True)
            continue
        data.mkdir(parents=True, exist_ok=True)
        subst = {"ROOT": str(root), "DATA": str(data)}

        def expand(x) -> str:
            return _PLUGIN_PLACEHOLDER.sub(lambda m: subst[m.group(1)], str(x))

        cmd = str(s["command"])
        if cmd.startswith("./"):
            target = _safe_join(str(root), cmd[2:])
            if target is None:
                print(f"[plugins] '{s.get('name')}': command escapes the plugin root — skipped", flush=True)
                continue
            # A package's own script is what the entry says to run; JSON has no file mode, so
            # the bit is set here rather than left to a naming convention.
            try:
                if target.is_file() and not target.is_symlink():
                    target.chmod(target.stat().st_mode | 0o111)
            except Exception:  # noqa: BLE001
                pass
            command = str(target)
        else:
            command = cmd                            # a bare name, resolved on PATH at exec
        raw_cwd = str(s.get("cwd") or "")
        if not raw_cwd or raw_cwd == ".":
            wd = root
        elif raw_cwd.startswith("./"):
            wd = _safe_join(str(root), raw_cwd[2:])
        else:
            candidate = pathlib.Path(expand(raw_cwd))
            wd = None
            for base in (root, data):
                try:
                    candidate.resolve().relative_to(base.resolve())
                    wd = candidate
                    break
                except ValueError:
                    continue
        if wd is None:
            print(f"[plugins] '{s.get('name')}': cwd escapes the plugin root and data directory — skipped", flush=True)
            continue
        args = [expand(a) for a in (s.get("args") or [])]
        env = {str(k): expand(v) for k, v in (s.get("env") or {}).items()
               if _ENV_NAME.match(str(k)) and str(k).upper() not in ("PLUGIN_ROOT", "PLUGIN_DATA")}
        launcher = data / f".launch-{_mcp_name(str(s.get('name') or 'mcp'))}.sh"
        lines = ["#!/bin/sh", "# written by the harness runner for one plugin MCP server; not user content"]
        lines += [f"export {k}={shlex.quote(v)}" for k, v in env.items()]
        lines += [f"export PLUGIN_ROOT={shlex.quote(str(root))}",
                  f"export PLUGIN_DATA={shlex.quote(str(data))}",
                  f"mkdir -p {shlex.quote(str(wd))} && cd {shlex.quote(str(wd))} || exit 1",
                  f'exec {shlex.quote(command)} "$@"', ""]
        # Never through a link the session may have planted where the launcher goes: the data
        # directory is the agent's to write, and the runner writes here as itself.
        if launcher.is_symlink() or (launcher.exists() and not launcher.is_file()):
            launcher.unlink()
        fd = os.open(str(launcher), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o755)
        with os.fdopen(fd, "w") as fh:
            fh.write("\n".join(lines))
        launcher.chmod(0o755)
        out.append({"name": s.get("name"), "command": str(launcher), "args": args, "plugin": pname})
    return out


_AGENTS_BEGIN = "<!-- harness-skills:begin -->"
_AGENTS_END = "<!-- harness-skills:end -->"


def _agent_doc_path(cwd: str, backend: str) -> pathlib.Path:
    """The agent's instruction file: AGENTS.md for Codex, Hermes, Pi, dsh and opencode (all read
    AGENTS.md from the cwd — pi as a context file before its trust gate, dsh via its
    dsh-agent-instructions workspace loader, opencode via instruction-context.ts, whose discovery
    targets are literally ["AGENTS.md"]), CLAUDE.md for Claude Code.

    Getting this wrong is silent: the file is written either way, and a backend that does not read
    the name we chose simply never sees the harness's instructions."""
    if backend == "qwen":
        return pathlib.Path(cwd) / "QWEN.md"   # qwen-code's own context file (bundle default)
    if backend == "gemini":
        return pathlib.Path(cwd) / "GEMINI.md"   # gemini-cli's own context.fileName default
    if backend == "minimax":
        # MiniMax Code reads TWO instruction files and merges them: the GLOBAL $MINIMAX_DATA_DIR/
        # AGENTS.md, and ONE project file — the workspace's CLAUDE.md if it has content, else its
        # AGENTS.md (static-prompt-reader.ts, 0.5.4; both measured reaching the system prompt). A
        # root AGENTS.md would therefore be silently SHADOWED by any CLAUDE.md in the workspace,
        # the user's own or one another harness left there. The global file is read whatever the
        # workspace holds, and it sits under .harness/, so it is never a produced file.
        return _minimax_home(pathlib.Path(cwd)) / "AGENTS.md"
    return pathlib.Path(cwd) / (
        # goose reads AGENTS.md natively and first: its default context-file list is
        # ["AGENTS.md", ".goosehints"], overridable only via CONTEXT_FILE_NAMES.
        # kimi reads AGENTS.md and nothing else (no KIMI.md, no CLAUDE.md - grepped the whole
        # 1.50.0 package), merging from the project root down to the work dir, and injects the
        # content VERBATIM into the system prompt: verified live, inside a
        # "<!-- From: .../AGENTS.md -->" fence, with a behavioural instruction in it obeyed.
        # aider has no instruction-file convention of its own (no AGENTS.md discovery, no
        # CLAUDE.md): the file is written here and the driver puts it into aider's system message.
        # cheetahclaws reads CLAUDE.md and ONLY CLAUDE.md (context.py get_claude_md: the first one
        # walking up from the cwd, plus ~/.claude/CLAUDE.md; no source hit for AGENTS.md in
        # 3.5.88), so it takes the CLAUDE.md branch below, and an AGENTS.md in the workspace is
        # never loaded whether or not a CLAUDE.md is there.
        # kilo reads AGENTS.md first (session/instruction.ts: ["AGENTS.md", "CLAUDE.md",
        # "CONTEXT.md"], first match wins) — verified on 7.8.1: the request's system prompt carried
        # "Instructions from: <ws>/AGENTS.md" and the file's body.
        # grok loads AGENTS.md (and CLAUDE.md, AGENT.md …) at every level from the repo root down to
        # the cwd, once the folder is trusted; _build_grok sets GROK_FOLDER_TRUST=0. Verified on
        # 1.0.41: a token written in AGENTS.md was in the model request.
        "AGENTS.md" if backend in ("codex", "hermes", "pi", "dsh", "opencode", "cline", "omp",
                                   "goose", "kimi", "aider", "openhands", "kilo", "grok", "agentzero")
        else "CLAUDE.md")


def _write_agent_doc(cwd: str, backend: str, agent_doc: str | None, skills_meta: list[dict],
                     environment: dict | None = None) -> None:
    """Compose the agent's instruction file from (1) the harness's user-authored doc and (2) a managed
    block: the workspace contract, always, plus an 'Available skills' section when skills are
    installed. The user doc is the base; the managed block is appended inside HTML-comment markers.
    Source of truth is the harness config, so this OVERWRITES any stale file each turn.

    THE WORKSPACE CONTRACT IS ALWAYS PRESENT, so the file now always exists. Produced files are
    collected from the session directory only (/produced runs git status in _ws), so a deliverable
    written to an absolute path outside it — the workspace parent, /tmp, /app, $HOME — is invisible
    to the user and is not even checkpointed. Nothing ever told the model that: four backends write
    relative paths by habit, and the first dsh deck task (deepseek-v4-pro, 2026-08-21) saved to the
    workspace PARENT, the user saw an empty turn, and three turns went to copying files into view.
    An instruction is the right mechanism here: writes cannot be walled in a sandbox whose point is
    real bash, and widening collection would ship every scratch file as a deliverable."""
    if backend == "systemone":
        return                  # reads no workspace; its instructions travel in the job (see _build_systemone)
    p = _agent_doc_path(cwd, backend)
    base = (agent_doc or "").strip()
    lines = [_AGENTS_BEGIN, "## Workspace", "",
             "Your working directory is this task's workspace and the ONLY place the user can see "
             "files. Save every deliverable (documents, decks, code, exports) to a relative path "
             "under it. Never write output to an absolute path outside it (/tmp, /app, the "
             "workspace parent directory, or your home directory): those files are not collected, "
             "and the user will never see them.", ""]
    lines += environments.doc_section(environment)
    if skills_meta:
        lines += ["## Available skills", "",
                  "These skills are installed in this workspace. When a task matches one, read its "
                  "SKILL.md first and follow its instructions and bundled scripts. Every path a "
                  "skill mentions (`test.py`, `scripts/run.sh`) is relative to THAT SKILL'S "
                  "FOLDER below, never to this workspace: prefix it with the folder, or cd there "
                  "first. The folder is where its bundled scripts and data already are.", ""]
        for s in skills_meta:
            d = f" — {s['desc']}" if s.get("desc") else ""
            # ABSOLUTE, and the directory rather than the file: a skill that says "run test.py"
            # is then one join away from a command that works, with nothing to infer. The
            # relative path this replaced left the model to compose a path from two places, and
            # a weaker one ran the bare filename in the workspace root instead (2026-08-23).
            folder = os.path.dirname(os.path.join(cwd, s["entry"]))
            lines.append(f"- **{s['name']}**{d} — files in `{folder}/` (start with `SKILL.md` there)")
        lines.append("")
    block = "\n".join(lines).rstrip("\n") + "\n" + _AGENTS_END + "\n"
    body = ((base + "\n\n") if base else "") + block
    try:
        # minimax's file lives in the CLI's home, which does not exist before its first turn.
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body if body.endswith("\n") else body + "\n")
    except Exception:  # noqa: BLE001
        pass


# ── auth / provider model ────────────────────────────────────────────────────────
class Auth(BaseModel):
    """One-of by provider; the gateway (or a spike body) fills the relevant fields."""
    api_key: str | None = None             # anthropic / openai / azure / router key|token
    base_url: str | None = None            # azure endpoint or router/proxy base url
    # AWS Bedrock
    aws_region: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_session_token: str | None = None
    aws_bearer_token: str | None = None    # AWS_BEARER_TOKEN_BEDROCK (simplest)
    # GCP Vertex
    gcp_project: str | None = None
    gcp_region: str | None = None
    gcp_sa_json: str | None = None         # service-account JSON (string) → file
    # Codex provider tuning
    wire_api: str | None = None            # responses | chat (default responses)
    # Custom provider
    api_format: str | None = None          # "openai" | "responses" | "anthropic" (custom integration)
    full_url: str | None = None            # "1" when the URL is a complete request URL
    namespace_tools: bool | str | None = None  # "1"/true to opt into namespace tools
    web_search: bool | str | None = None       # "1"/true to opt into built-in web search


# ── canonical-event normalizers ──────────────────────────────────────────────────
import re as _re
# Claude Code injects transient provider errors into the stream AS assistant text
# ("API Error: 400 ...", "API Error: 429 ..."), then usually retries and continues. That
# diagnostic is the CLI's own UX, not model output — rendering it as the reply is wrong (it made
# a working opus-4.7/4.8 turn look failed). Drop assistant text blocks that ARE such an error line.
# The same line without a status code is the CLI's own account of a turn that ended on an error:
# Claude Code's "API Error: Opus 5's safeguards flagged this message …" and Qwen Code's
# "[API Error: Model stream ended with empty response text.]" (both 2026-09-08, hosted's
# claude-opus-5 recall). Neither is an answer. The text is kept aside as the turn's reason.
_CLAUDE_ERR_RE = _re.compile(r"^\s*\[?API Error:", _re.IGNORECASE)


def _strip_claude_error_text(obj: dict, state: dict | None = None) -> dict | None:
    """Remove CLI-injected 'API Error: …' text blocks from an assistant message. Returns the
    message with those blocks dropped (None if nothing renderable remains), or the object unchanged
    when it carries no such block. The dropped text is remembered on `state` ("_cli_error") so a
    turn that ends with no answer can fail with it as the reason."""
    if obj.get("type") != "assistant":
        return obj
    content = (obj.get("message") or {}).get("content")
    if not isinstance(content, list):
        return obj
    if state is not None:
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text" and _CLAUDE_ERR_RE.match(str(c.get("text") or "")):
                state["_cli_error"] = str(c.get("text") or "").strip().strip("[]").strip()[:400]
    kept = [c for c in content
            if not (isinstance(c, dict) and c.get("type") == "text"
                    and _CLAUDE_ERR_RE.match(str(c.get("text") or "")))]
    if len(kept) == len(content):
        return obj                      # no error block — untouched
    if not kept:
        return None                     # the message was ONLY the error line — drop it entirely
    return {**obj, "message": {**(obj.get("message") or {}), "content": kept}}


def _claude_model_used(result: dict) -> str:
    """The model that answered, from the CLI's modelUsage (usage keyed by model id): the id with the
    most output tokens, so a subagent's or a helper's few tokens never name the turn."""
    mu = result.get("modelUsage")
    if not isinstance(mu, dict) or not mu:
        return ""
    def out_tokens(v) -> int:
        try:
            return int((v or {}).get("outputTokens") or (v or {}).get("output_tokens") or 0)
        except (TypeError, ValueError, AttributeError):
            return 0
    return str(max(mu.items(), key=lambda kv: out_tokens(kv[1]))[0] or "")


def _claude_passthrough(obj: dict, state: dict) -> list[dict]:
    # Filter out CLI-injected "API Error: …" diagnostics rendered as assistant text (they are
    # not model output; the CLI retries around them). Applies to both batch + partial modes.
    obj2 = _strip_claude_error_text(obj, state)
    if obj2 is None:
        return []
    obj = obj2
    if obj.get("type") == "result":
        # A turn whose only "answer" is the CLI's error line is a failed turn with that reason: a
        # Qwen Code turn Opus 5 refused completed with "[API Error: Model stream ended with empty
        # response text.]" as its reply (hosted, 2026-09-08). A real answer after a retried error
        # keeps the answer.
        answer = str(state.get("final") or obj.get("result") or "")
        if _CLAUDE_ERR_RE.match(answer):
            state["_cli_error"] = answer.strip().strip("[]").strip()[:400]
            answer = ""
        if not answer.strip() and state.get("_cli_error") and not obj.get("is_error"):
            return [{**obj, "subtype": "error", "is_error": True, "result": state["_cli_error"]}]
        if obj.get("is_error") and not str(obj.get("result") or "").strip() and state.get("_cli_error"):
            return [{**obj, "result": state["_cli_error"]}]
    if obj.get("type") == "result" and not obj.get("model"):
        # The CLI names no model on its result; it lists usage BY model (modelUsage). The one that
        # produced the output is the served model, which a direct Anthropic key never sent through
        # the relay (served_model stayed empty on every Claude Code run of a benchmark, 2026-09-30).
        served = _claude_model_used(obj)
        if served:
            obj = {**obj, "model": served}
    # Default (batch) mode: pass the CLI's stream-json through unchanged — the CLI emits one event
    # per COMPLETE assistant message, so text lands in a batch.
    if not state.get("partial"):
        return [obj]
    # Partial mode (--include-partial-messages): the CLI additionally emits `stream_event` wrappers
    # around Anthropic streaming events. Turn each text/thinking DELTA into a small canonical
    # assistant event (the gateway renders it as an incremental response.output_text.delta), and
    # STRIP text/thinking from the final complete assistant message so it isn't rendered twice.
    t = obj.get("type")
    if t == "stream_event":
        se = obj.get("event") or {}
        if se.get("type") == "content_block_delta":
            d = se.get("delta") or {}
            if d.get("type") == "text_delta" and d.get("text"):
                state["final"] = state.get("final", "") + d["text"]
                return [{"type": "assistant", "message": {"content": [{"type": "text", "text": d["text"]}]}}]
            if d.get("type") == "thinking_delta" and d.get("thinking"):
                return [{"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": d["thinking"]}]}}]
        return []   # message_start/stop, content_block_start/stop, ping, etc. — nothing to render
    if t == "assistant":
        # deltas already carried text/thinking; keep only non-text blocks (tool_use) from the
        # complete message so tool calls still render and text isn't duplicated.
        content = (obj.get("message") or {}).get("content")
        kept = [c for c in (content if isinstance(content, list) else [])
                if isinstance(c, dict) and c.get("type") not in ("text", "thinking")]
        if not kept:
            return []
        return [{"type": "assistant", "message": {**(obj.get("message") or {}), "content": kept}}]
    if t == "result":
        # keep the accumulated streamed text as the authoritative final (matches what the user saw)
        return [{**obj, "result": state.get("final") or obj.get("result") or ""}]
    return [obj]   # system init, user tool_result, etc.


def _norm_token_usage(u: dict | None) -> dict:
    """Normalize a codex/hermes token-usage object into {input_tokens, output_tokens,
    cache_read_tokens, cache_write_tokens}.

    Verified codex app-server shape (2026-07-23): the notification carries
    `tokenUsage.total.{inputTokens,outputTokens,cachedInputTokens,cacheWriteInputTokens}` — the
    counts sit TWO levels deep (tokenUsage → total). codex-exec's turn.completed puts snake_case
    counts at the top level. Unwrap the known nesting keys, then pick by name across camel/snake.
    Note: codex's inputTokens already INCLUDES the cached read, so we SUBTRACT it here to make the
    contract uniform with the Anthropic path (input_tokens = FRESH input only; cache_read_tokens =
    the cached subset). Billing then charges input_1k on fresh input and the cheaper cache_read rate
    on the cached subset — without the subtraction the cached tokens were billed at the full input
    rate (~10x), which on a long conversation (each turn resends the whole cache-hit transcript)
    inflated cost several-fold. Accepting every field shape means a name drift can never silently
    zero out billing again."""
    if not isinstance(u, dict):
        return {}
    # Unwrap the running-total nesting: tokenUsage/total_token_usage/… then .total/.last.
    for key in ("tokenUsage", "total_token_usage", "totalTokenUsage", "info", "usage"):
        inner = u.get(key)
        if isinstance(inner, dict):
            u = inner
            break
    for key in ("total", "last"):
        inner = u.get(key)
        if isinstance(inner, dict):
            u = inner
            break

    def _pick(*names) -> int:
        for n in names:
            v = u.get(n)
            if isinstance(v, (int, float)) and v:
                return int(v)
        return 0

    inp = _pick("input_tokens", "inputTokens", "prompt_tokens", "promptTokens", "totalInputTokens")
    out = _pick("output_tokens", "outputTokens", "completion_tokens", "completionTokens")
    cache_read = _pick("cache_read_tokens", "cacheReadTokens",
                       "cached_input_tokens", "cachedInputTokens",
                       "cache_read_input_tokens", "cacheReadInputTokens")
    cache_write = _pick("cache_write_tokens", "cacheWriteTokens",
                        "cache_creation_input_tokens", "cacheWriteInputTokens")
    # codex reports gross input (fresh + cached read). Net the cached read out so input_tokens is
    # FRESH only — uniform with the Anthropic contract and priced correctly by the biller. Guard
    # against a provider that already reports net input (cache_read > input) so we never go negative.
    fresh = max(inp - cache_read, 0) if cache_read else inp
    res = {"input_tokens": fresh, "output_tokens": out}
    if cache_read:
        res["cache_read_tokens"] = cache_read
    if cache_write:
        res["cache_write_tokens"] = cache_write
    return res


_CAMEL = re.compile(r"(?<=[a-z0-9])([A-Z])")


def _codex_item_kind(it: dict) -> str:
    """The item's type in one spelling. `codex exec --json` names items in snake_case
    (command_execution, mcp_tool_call); the app-server names the same items in camelCase
    (commandExecution, mcpToolCall, userMessage, agentMessage). Read in camelCase, every item
    fell through to the generic branch: the record listed userMessage and agentMessage as tools
    and an MCP call as "mcpToolCall" with no server or tool name (the custom-harness dimension,
    codex, hosted 2026-09-10; the same code here, on the app-server path nobody had exercised)."""
    return _CAMEL.sub(lambda m: "_" + m.group(1).lower(), str(it.get("type") or "")).lower()


def _codex_tool_item(it: dict) -> list[dict]:
    """A completed codex tool item (command/file/mcp) -> canonical tool_use + tool_result events.
    Shared by the exec normalizer and the app-server driver (the `item` shape is the same, the
    type spelling is not: see _codex_item_kind). A message or reasoning item is not a tool and
    yields nothing here (its text streams as deltas)."""
    kind = _codex_item_kind(it)
    if kind in ("user_message", "agent_message", "reasoning"):
        return []
    if kind == "command_execution":
        tuid = it.get("id") or "cmd"
        out = it.get("aggregated_output") or it.get("aggregatedOutput") or it.get("output") or ""
        ec = it.get("exit_code", it.get("exitCode"))
        return [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": tuid, "name": "Bash",
                 "input": {"command": it.get("command") or ""}}]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": tuid,
                 "is_error": bool(ec not in (0, None)), "content": str(out)}]}},
        ]
    if kind == "file_change":
        changes = it.get("changes") or []
        summary = "\n".join(f"{c.get('kind', 'change')}: {c.get('path', '')}"
                            for c in changes) or json.dumps(it)
        return [{"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": it.get("id") or "edit", "name": "Edit",
             "input": {"changes": changes}}]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": it.get("id") or "edit",
                 "content": summary}]}}]
    if kind == "web_search":
        tuid = it.get("id") or "search"
        return [{"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": tuid, "name": "WebSearch", "input": {"query": it.get("query") or ""}}]}}]
    if kind == "mcp_tool_call":
        tuid = it.get("id") or "mcp"
        name = f"{it.get('server') or it.get('serverName') or 'mcp'}.{it.get('tool') or it.get('toolName') or 'call'}"
        return [{"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": tuid, "name": name,
             "input": it.get("arguments") or {}}]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": tuid,
                 "content": json.dumps(it.get("result") or it, default=str)}]}}]
    return [{"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": it.get("id") or kind or "item",
         "name": kind or "codex_item", "input": it}]}}]


def _codex_text_delta(it: dict, state: dict) -> str:
    """Incremental text for a codex agent_message/reasoning item, by diffing the accumulating
    `item.text` against what we've already streamed for this item id. Returns '' if nothing new
    (or if the text isn't a prefix-extension, which shouldn't happen — codex text grows append-only).
    Self-healing: when codex never emits item.updated, `seen` stays empty and item.completed's tail
    equals the full text — i.e. the current batch behavior."""
    iid = it.get("id") or "item"
    full = it.get("text") or ""
    seen = state.setdefault("_seen", {}).get(iid, "")
    if full == seen or not full.startswith(seen):
        # no growth, or a non-append revision — fall back to emitting the whole thing once
        if full and full != seen:
            state["_seen"][iid] = full
            return full
        return ""
    state["_seen"][iid] = full
    return full[len(seen):]


def _codex_to_claude(obj: dict, state: dict) -> list[dict]:
    """Map ONE Codex `exec --json` event to zero+ canonical claude stream-json events."""
    partial = state.get("partial")
    t = obj.get("type")
    if t == "thread.started":
        return [{"type": "system", "subtype": "init",
                 "session_id": obj.get("thread_id"), "model": state.get("model")}]
    if partial and t in ("item.started", "item.updated"):
        it = obj.get("item") or {}
        kind = it.get("type")
        if kind in ("agent_message", "reasoning"):
            d = _codex_text_delta(it, state)
            if not d:
                return []
            if kind == "agent_message":
                state["final"] = state.get("_seen", {}).get(it.get("id") or "item", "")
                return [{"type": "assistant", "message": {"content": [{"type": "text", "text": d}]}}]
            return [{"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": d}]}}]
        return []   # command/file/mcp items render on completion (below), not while updating
    if t == "item.completed":
        it = obj.get("item") or {}
        kind = it.get("type")
        if kind == "agent_message":
            if partial:
                d = _codex_text_delta(it, state)   # only the un-streamed tail (== full text if no updates)
                state["final"] = it.get("text") or state.get("final", "")
                return [{"type": "assistant", "message": {"content": [{"type": "text", "text": d}]}}] if d else []
            txt = it.get("text") or ""
            state["final"] = txt
            return [{"type": "assistant", "message": {"content": [{"type": "text", "text": txt}]}}]
        if kind == "reasoning":
            if partial:
                d = _codex_text_delta(it, state)
                return [{"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": d}]}}] if d else []
            return [{"type": "assistant",
                     "message": {"content": [{"type": "thinking", "thinking": it.get("text") or ""}]}}]
        return _codex_tool_item(it)   # command_execution / file_change / mcp_tool_call / other
    if t == "turn.completed":
        return [{"type": "result", "subtype": "success", "is_error": False,
                 "result": state.get("final", ""),
                 "usage": _norm_token_usage(obj.get("usage"))}]
    if t in ("error", "turn.failed"):
        msg = obj.get("message") or (obj.get("error") or {}).get("message") or "codex error"
        return [{"type": "result", "subtype": "error", "is_error": True, "result": msg}]
    return [obj]


def _status_from_result(result_ev: dict | None, exit_code: int) -> str:
    if result_ev is not None:
        sub = result_ev.get("subtype")
        if sub == "success" and not result_ev.get("is_error"):
            return "done"
        if sub == "error_max_turns":
            return "max_turns"
        if sub == "incomplete" and not result_ev.get("is_error"):
            # The loop stopped for a reason of its own that is neither a failure nor a budget: the
            # model asked for help, or would not clear the confidence a destructive action needs
            # (systemone). The reason rides the result event and the poll body, and the gateway
            # reports it as the task's incomplete_details.
            return "incomplete"
        return "failed"
    return "done" if exit_code == 0 else "failed"


# ── per-backend turn builders (env + argv) ───────────────────────────────────────
CLAUDE_PROVIDERS = {"anthropic", "bedrock", "vertex", "tokenrouter"}

# Claude Code decides its own thinking/effort fields per model, and gets two of them wrong against
# the current API. Both were verified by calling /v1/messages directly: the same request succeeds
# plain and fails with these fields attached.
#
#   thinking:{type:"enabled"}   -> 400 on the opus-4.7/4.8 line
#                                  '"..enabled" is not supported for this model. Use "..adaptive"'
#   output_config.effort        -> 400 on haiku-4.5
#                                  'This model does not support the effort parameter.'
#
# The broker strips both centrally (_strip_unsupported in harness_gateway) — but only for traffic
# that goes THROUGH the broker. A self-hosted instance is bring-your-own-key: the CLI holds the
# credential and calls the provider directly, so nothing on that path ever sees the body. The CLI
# therefore has to be told not to send them.
_CLAUDE_NO_THINKING = re.compile(r"opus-4[._-]?[78]", re.I)


def _claude_thinking_env(model: str) -> dict:
    """Env that stops Claude Code sending fields the target model rejects.

    EFFORT_LEVEL=auto is unconditional: it hands the choice back to the CLI's own per-model
    table, which is right for every model tested (it fixes haiku-4.5 and changes nothing for
    opus-5, sonnet-4.6 or the rest).

    MAX_THINKING_TOKENS=0 is NOT unconditional, because it disables extended thinking — a real
    capability. Only the models whose API rejects the field get it; a blanket setting would trade
    every model's reasoning away to fix two.
    """
    env = {"CLAUDE_CODE_EFFORT_LEVEL": "auto"}
    if _CLAUDE_NO_THINKING.search(model or ""):
        env["MAX_THINKING_TOKENS"] = "0"
    return env



def _build_claude(provider: str, auth: Auth, model: str, prompt: str, max_turns: int,
                  cwd: str, env: dict, resume_session_id: str | None = None,
                  mcp_config: str | None = None, disallowed_tools: list[str] | None = None,
                  partial: bool = False, plugin_dirs: list[str] | None = None) -> list[str]:
    p = provider or "anthropic"
    if p not in CLAUDE_PROVIDERS:
        raise HTTPException(400, f"unknown claude provider '{p}' (one of {sorted(CLAUDE_PROVIDERS)})")
    # Keep conversation state inside the workspace so the checkpoint captures it (resume-anywhere).
    # $HOME was redirected to <cwd>/.harness/home, and Claude writes BOTH config and the session
    # transcripts (projects/*.jsonl) under $HOME/.claude — so that's the config dir AND where the
    # resume-existence check below looks. This is the per-session, checkpointed location.
    cfg_dir = pathlib.Path(env.get("HOME") or cwd) / ".claude"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    env["CLAUDE_CONFIG_DIR"] = str(cfg_dir)
    # Stop the CLI emitting thinking/effort fields the target model rejects. The broker strips
    # these for brokered traffic; bring-your-own-key traffic never reaches the broker, so this is
    # the only thing standing between a self-hosted user and a 400 (see _claude_thinking_env).
    env.update(_claude_thinking_env(model))
    if p == "anthropic":
        if auth.api_key:
            env["ANTHROPIC_API_KEY"] = auth.api_key
        if auth.base_url:
            # The CLI appends /v1/messages itself, so a base that carries the "/v1" the broker and
            # the catalog use (https://api.anthropic.com/v1) doubled it and the CLI answered "you
            # may not have access to it" (2026-09-06, measured on the self-hosted instance). The
            # router branch below has always stripped it; a direct key gets the same rule.
            env["ANTHROPIC_BASE_URL"] = auth.base_url.rstrip("/").removesuffix("/v1")
    elif p == "bedrock":
        env["CLAUDE_CODE_USE_BEDROCK"] = "1"
        if auth.aws_region:
            env["AWS_REGION"] = env["AWS_DEFAULT_REGION"] = auth.aws_region
        if auth.aws_bearer_token:
            env["AWS_BEARER_TOKEN_BEDROCK"] = auth.aws_bearer_token
        if auth.aws_access_key_id:
            env["AWS_ACCESS_KEY_ID"] = auth.aws_access_key_id
        if auth.aws_secret_access_key:
            env["AWS_SECRET_ACCESS_KEY"] = auth.aws_secret_access_key
        if auth.aws_session_token:
            env["AWS_SESSION_TOKEN"] = auth.aws_session_token
    elif p == "vertex":
        env["CLAUDE_CODE_USE_VERTEX"] = "1"
        if auth.gcp_project:
            env["ANTHROPIC_VERTEX_PROJECT_ID"] = auth.gcp_project
        if auth.gcp_region:
            env["CLOUD_ML_REGION"] = auth.gcp_region
        if auth.gcp_sa_json:
            sa = pathlib.Path(cwd) / ".gcp-sa.json"
            sa.write_text(auth.gcp_sa_json)
            env["GOOGLE_APPLICATION_CREDENTIALS"] = str(sa)
    elif p == "tokenrouter":
        # tokenrouter speaks Anthropic on the claude backend. A custom integration with
        # api_format=openai cannot be served here — the CLI only speaks Anthropic Messages.
        if auth.api_format == "openai":
            raise HTTPException(400, "claude backend cannot serve an OpenAI-format custom integration "
                                 "(use a backend that supports openai-api, like hermes or opencode)")
        if auth.base_url:
            # Claude Code appends /v1/messages itself — a base_url stored with /v1 (the
            # OpenAI-compat form) would double the segment and 404 every call.
            env["ANTHROPIC_BASE_URL"] = auth.base_url.rstrip("/").removesuffix("/v1")
        if auth.api_key:
            env["ANTHROPIC_AUTH_TOKEN"] = auth.api_key
    cmd = ["claude", "-p", prompt, "--output-format", "stream-json",
           "--verbose", "--dangerously-skip-permissions", "--max-turns", str(max_turns)]
    if partial:   # token-level streaming: emit content_block_delta events (see _claude_passthrough)
        cmd.append("--include-partial-messages")
    if mcp_config:   # owner-attached MCP servers (.harness/mcp.json) — adds their tools this turn
        cmd += ["--mcp-config", mcp_config]
    for pd in (plugin_dirs or []):   # owner-attached Claude Code plugins, one --plugin-dir each
        cmd += ["--plugin-dir", pd]
    # Disabled tools go in settings.json, NOT on the command line. `--disallowedTools` is part of
    # the permission prompt system, and we pass --dangerously-skip-permissions (autonomous runs
    # cannot answer a prompt), which disables that system wholesale — so the flag was accepted,
    # ignored, and the console showed "Disabled" next to a tool the agent went on using. Verified
    # both ways against the CLI: with the flag the agent still ran bash; with this deny list it
    # reported having no shell tool and did not run it.
    if disallowed_tools:
        names = [t.split(" (")[0].strip() for t in disallowed_tools if t and t.strip()]
        if names:
            settings_path = cfg_dir / "settings.json"
            try:
                current = json.loads(settings_path.read_text()) if settings_path.exists() else {}
                if not isinstance(current, dict):
                    current = {}
            except Exception:  # noqa: BLE001 — a corrupt file must not lose the restriction
                current = {}
            perms = current.get("permissions") if isinstance(current.get("permissions"), dict) else {}
            perms["deny"] = names
            current["permissions"] = perms
            settings_path.write_text(json.dumps(current, indent=2))
    if resume_session_id:
        # Only resume if the conversation file is ACTUALLY in the (re)hydrated workspace. A prior turn
        # can record a cli_session_id but fail before checkpointing its .jsonl — then `--resume <id>`
        # hits a missing session and dies with error_during_execution on EVERY follow-up, permanently
        # wedging the conversation. If it's absent, start a fresh CLI thread in the SAME workspace
        # (files preserved) so the follow-up always runs instead of hard-failing.
        import glob as _glob
        found = _glob.glob(str(cfg_dir / "projects" / "*" / f"{resume_session_id}.jsonl")) \
            or _glob.glob(str(cfg_dir / "**" / f"{resume_session_id}.jsonl"), recursive=True)
        if found:
            cmd += ["--resume", resume_session_id]   # continue the prior turn's conversation
        else:
            print(f"[resume] session {resume_session_id} not found in workspace — starting fresh", flush=True)
    if model:
        cmd += ["--model", model]
    return cmd


CODEX_PROVIDERS = {
    "openai": {"name": "OpenAI", "default_base": OPENAI_BASE_URL, "env_key": "OPENAI_API_KEY"},
    "azure": {"name": "Azure OpenAI", "default_base": AZURE_OPENAI_BASE_URL, "env_key": "AZURE_OPENAI_API_KEY"},
    "tokenrouter": {"name": "TokenRouter", "default_base": "", "env_key": "ROUTER_API_KEY"},
}
# sandbox_mode = danger-full-access is REQUIRED for the app-server path: `codex exec` disables the
# sandbox via --dangerously-bypass-approvals-and-sandbox, but `codex app-server` has no such flag and
# reads its policy from config.toml. Without this it defaults to read-only, so with approval_policy
# "never" (never escalate) every apply_patch/file write is silently rejected and the agent gives up
# ("workspace mounted read-only"). We already run one Hyper-V-isolated sandbox per session, so full
# access INSIDE it matches the exec path's behavior. The [sandbox_workspace_write] block is inert
# under danger-full-access but kept for anyone who flips the mode down to workspace-write.
# The provider KEY is ours to choose — it only has to match `model_provider`. It is namespaced
# because Codex reserves its built-in ids: a [model_providers.openai] block is rejected outright
# ("Built-in providers cannot be overridden"), which broke every bring-your-own OpenAI key. All
# providers are namespaced rather than just that one, so a future reserved id can't break us again.
# mcp_optional_startup_grace_ms = 0: codex builds its initial tool catalog after a shared grace of
# one second by default and drops any MCP server still starting; the runner's SSE bridge takes about
# that long to open its remote connection, so a plugin's SSE server was in the catalog on one turn
# and missing on the next (hosted, 2026-09-15). Zero makes codex wait each server's own
# startup_timeout_sec (10 s) instead.
_CODEX_CONFIG_TMPL = """model = "{model}"
model_provider = "{provider}"
model_reasoning_effort = "{effort}"
approval_policy = "never"
sandbox_mode = "danger-full-access"
model_context_window = {ctx}
mcp_optional_startup_grace_ms = 0
[model_providers.{provider}]
name = "{name}"
base_url = "{base_url}"
env_key = "{env_key}"
wire_api = "{wire_api}"
[sandbox_workspace_write]
network_access = true
exclude_slash_tmp = false
"""
_CODEX_ALIAS_TMPL = """[model_providers.{alias}]
name = "{name}"
base_url = "{base_url}"
env_key = "{env_key}"
wire_api = "{wire_api}"
"""


_PROVIDER_REFUSAL = re.compile(r"\b(401|403|429|5\d\d)\b|unauthori[sz]ed|incorrect api key|invalid_api_key|invalid api key|"
                               r"insufficient_quota|rate limit|quota|forbidden", re.IGNORECASE)


def _codex_session_provider_ids(cfg_dir: "pathlib.Path") -> list[str]:
    """Every model provider id the session's rollouts name. Codex looks the recorded id up in the
    config on resume, so a session started under another provider (or under the bare ids of
    before the namespacing) fails to load unless the config still declares it."""
    import glob as _glob
    ids: list[str] = []
    for path in _glob.glob(str(cfg_dir / "sessions" / "**" / "*.jsonl"), recursive=True):
        try:
            for line in pathlib.Path(path).read_text().splitlines():
                if '"model_provider"' not in line:
                    continue
                for m in re.finditer(r'"model_provider"\s*:\s*"([^"]+)"', line):
                    if m.group(1) not in ids:
                        ids.append(m.group(1))
        except OSError:
            continue
    return ids


# What a follow-up reads when its Codex history is not in the workspace any more: the task goes
# on in the same workspace with its files, without the earlier exchanges.
_CODEX_NO_ROLLOUT_NOTE = "The earlier conversation of this task is no longer available to Codex. Continuing in the same workspace with its files."


def _codex_resume_thread_id(cfg_dir: "pathlib.Path", wanted: str | None) -> str | None:
    """The thread id the app-server can resume in this CODEX_HOME: the wanted one when its rollout
    is here, else the newest rollout's own id (the home is per session, so the newest rollout IS
    this conversation, the same rule `exec resume --last` relies on; matching the wanted id alone
    missed about a third of the time and answered "no rollout found for thread id"). None when
    there is no rollout at all."""
    import glob as _glob
    paths = _glob.glob(str(cfg_dir / "sessions" / "**" / "*.jsonl"), recursive=True)
    if not paths:
        return None
    ids: list[tuple[float, str]] = []
    for path in paths:
        try:
            with open(path) as fh:
                for line in fh:
                    if '"session_meta"' not in line:
                        continue
                    m = re.search(r'"id"\s*:\s*"([^"]+)"', line)
                    if m:
                        ids.append((os.path.getmtime(path), m.group(1)))
                    break
        except OSError:
            continue
    if wanted and any(i == wanted for _, i in ids):
        return wanted
    return max(ids)[1] if ids else None


def _codex_web_search_off(tools_disabled: list[str] | None) -> bool:
    """Whether the turn's disabled list names codex's built-in web search (either spelling)."""
    return any(x.split(" (")[0].strip().lower().replace("-", "_") in ("web_search", "websearch")
               for x in (tools_disabled or []) if x and x.strip())


def _codex_flag(value: str | bool | None) -> bool | None:
    """Parse a connection's optional on/off flag, preserving an unset value."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        return value
    return value.strip().lower() in ("1", "true", "yes", "on")


def _codex_custom_responses(auth: Auth) -> bool:
    """Whether this Codex turn targets a custom OpenAI Responses integration."""
    return str(auth.api_format or "").strip().lower() == "responses"


_CODEX_CUSTOM_EDITING = (
    "## Editing files on this connection\n\n"
    "There is no `apply_patch` tool here: Codex offers none on a custom endpoint (measured on Codex "
    "0.154.0: no model gets it, known or not). A call to a tool named `apply_patch` is refused with "
    "\"unsupported call\"; do not make it and do not retry it. Edit files through the shell tool: write "
    "a file with a heredoc, change lines with sed or a short python script, or use an editor command, "
    "then read the file back to check the change.")


def _codex_custom_editing_note(backend: str, auth: Auth | None) -> str:
    """The instruction a Codex turn on a custom Responses endpoint carries about editing files.

    Issue #202 (lab1207's investigation, PR #332): a model Codex does not know called a tool named
    apply_patch and looped on "unsupported call". The tool is registered only inside Codex's own
    multi-environment executors (spec_plan.rs: has_environment() and the catalog's
    apply_patch_tool_type), never for a config.toml key, and never on a custom provider in our
    deployments: with a stub endpoint recording the request, gpt-5-codex and an unknown model sent
    the same tool list, without apply_patch, with or without a model catalog declaring it. So the
    remedy is what the model is told, not a switch: edits go through the shell tool."""
    if backend != "codex" or auth is None or not _codex_custom_responses(auth):
        return ""
    return _CODEX_CUSTOM_EDITING


def _codex_namespace_tools_off(auth: Auth) -> bool:
    """Keep Codex's multi-agent namespace out of custom endpoints unless opted in."""
    return _codex_custom_responses(auth) and _codex_flag(auth.namespace_tools) is not True


def _codex_web_search_off_for_auth(auth: Auth, tools_disabled: list[str] | None) -> bool:
    """Apply the connection opt-in without weakening the existing disabled-tools switch."""
    return _codex_web_search_off(tools_disabled) or (
        _codex_custom_responses(auth) and _codex_flag(auth.web_search) is not True)


def _codex_insert_top_level(cfg: str, value: str) -> str:
    """Insert a setting before the first TOML table so it stays at the document's top level."""
    head, sep, tail = cfg.partition("\n[")
    return head + "\n" + value + sep + tail if sep else cfg + "\n" + value + "\n"


def _codex_prepare_env(provider: str, auth: Auth, model: str, cwd: str,
                       env: dict, mcp_toml: str = "", resume: bool = False,
                       tools_disabled: list[str] | None = None) -> "pathlib.Path":
    """Shared codex setup for BOTH exec and app-server: write config.toml (model/provider/base_url +
    MCP), point CODEX_HOME at the checkpointed workspace, set provider auth + TMPDIR. Returns the
    CODEX_HOME dir. Mutates env."""
    p = provider or "azure"
    spec = CODEX_PROVIDERS.get(p)
    if not spec:
        raise HTTPException(400, f"unknown codex provider '{p}' (one of {sorted(CODEX_PROVIDERS)})")
    base_url = auth.base_url or spec["default_base"]
    if not base_url:
        raise HTTPException(400, f"codex provider '{p}' needs a base_url (none configured)")
    # CODEX_HOME under $HOME (.harness/home/.codex) so codex's sessions/rollouts are CHECKPOINTED
    # and survive sandbox recycling — the top-level ./.codex is excluded from the checkpoint, which is
    # why codex state used to vanish. (auth.json inside is still creds-excluded.)
    cfg_dir = pathlib.Path(env.get("HOME") or cwd) / ".codex"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    # Which account serves this turn, as a fingerprint that never names the key. A resume under the
    # account that minted the history keeps it whole; under another it is replayed as content
    # (see _sanitize_codex_rollout). The marker lives in the checkpointed home, beside the rollouts.
    fp = hashlib.sha256(f"{p}|{base_url}|{auth.api_key or ''}".encode()).hexdigest()[:16]
    marker = cfg_dir / "hr-account"
    try:
        prior = marker.read_text().strip()
    except OSError:
        prior = ""
    env["HR_CODEX_ACCOUNT_CHANGED"] = "0" if prior == fp else "1"
    try:
        marker.write_text(fp)
    except OSError:
        pass
    # codex only speaks the OpenAI Responses API now — current releases removed
    # `wire_api = "chat"` entirely, so a custom chat-completions endpoint cannot be driven by
    # codex at all (the gateway greys codex out for those integrations). Always the supported
    # "responses" value; a custom-endpoint turn against chat-only would 404 clearly rather than
    # crash on config load.
    cfg = _CODEX_CONFIG_TMPL.format(
        model=model, provider=f"hr-{p}", effort=CODEX_REASONING_EFFORT, ctx=CODEX_CONTEXT_WINDOW,
        name=spec["name"], base_url=base_url, env_key=spec["env_key"],
        wire_api=auth.wire_api or "responses")
    if _codex_namespace_tools_off(auth):
        # Codex enables its multi-agent namespace by default. Most custom Responses endpoints
        # only accept function tools, so custom integrations opt in explicitly when they support
        # this Codex-specific tool family.
        cfg = _codex_insert_top_level(cfg, "[agents]\nenabled = false")
    if _codex_web_search_off_for_auth(auth, tools_disabled):
        # The one built-in codex tool with a hard switch. Codex offers web_search by default on
        # the Responses wire and an endpoint that gates it per model answers 400 "The following
        # tool is not allowed" on every turn (issue #150); the TOP-LEVEL key is the only knob
        # (verified on codex 0.147 and 0.154: `[tools] web_search = false` parses and does
        # nothing). It goes before the first table header: appended at the end it would belong
        # to the last table and switch nothing (measured on rc.1: the tool stayed in the request).
        cfg = _codex_insert_top_level(cfg, 'web_search = "disabled"')
    if resume:
        # A resumed session keeps the provider id it started under; Codex looks that id up in the
        # config and refuses to load without it ("Model provider `azure` not found", a July
        # session continued on 2026-09-05; "hr-tokenrouter not found", a session continued on the
        # org's own key). Every id the session ever ran under is declared, at THIS turn's endpoint.
        for alias in _codex_session_provider_ids(cfg_dir):
            if alias == f"hr-{p}" or alias == "openai":     # the current one; a reserved built-in
                continue
            cfg += _CODEX_ALIAS_TMPL.format(alias=alias, name=spec["name"], base_url=base_url,
                                            env_key=spec["env_key"], wire_api=auth.wire_api or "responses")
    if mcp_toml:   # owner-attached MCP servers via Codex's experimental rmcp HTTP client
        cfg += mcp_toml
    (cfg_dir / "config.toml").write_text(cfg)
    env["CODEX_HOME"] = str(cfg_dir)
    env["TMPDIR"] = str(pathlib.Path(cwd) / "tmp")
    pathlib.Path(env["TMPDIR"]).mkdir(parents=True, exist_ok=True)
    if auth.api_key:
        env[spec["env_key"]] = auth.api_key
    return cfg_dir


def _sanitize_codex_rollout(rollouts: list[str], *, content_only: bool = True) -> dict:
    """Make a codex rollout safe to replay, without destroying any of it.

    Two hazards live in the same file, and the fix for one used to create the other.

    1. ACCOUNT BINDING. A reasoning item carries `encrypted_content` (the `gAAA…` chain-of-thought
       blob) that only the account which minted it can decrypt. A follow-up served by a DIFFERENT
       account (chain fallback, key rotation, a load-balanced proxy) 400s with
       `invalid_encrypted_content`, and because the item stays in the rollout, EVERY later resume
       fails identically — a permanently wedged session.

    2. REFERENTIAL INTEGRITY. Against a provider that stores responses (codex sends `store: true`
       to Azure Responses endpoints), an item `id` replayed in `input` is a REFERENCE into
       server-side state. The server looks up the response that minted it and requires its
       siblings. Delete the reasoning item but keep the `msg_…` that was minted beside it and the
       reference dangles:
           Item 'msg_…' of type 'message' was provided without its required 'reasoning' item: 'rs_…'
       Deterministic, not flaky: every follow-up replays at least one such item, so the first turn
       succeeds and every one after it fails.

    This function previously deleted whole reasoning lines to solve (1), which is precisely what
    caused (2). It no longer deletes anything. The two concerns turn out to be separable: the
    `encrypted_content` is what the ACCOUNT owns, the `id` is what the SERVER checks, so keeping
    the item while dropping the blob satisfies both.

    So:
      - reasoning items are KEPT, with their `id`, minus `encrypted_content`;
      - a rollout already damaged by the old behaviour (id-bearing items, no reasoning left to
        anchor them) is repaired by removing `id` from every provider-minted item, which turns the
        replay into ordinary content the server does not try to resolve. `call_id`, `phase`,
        `role`, `content`, `name` and `arguments` are preserved, so tool pairing and transcript
        survive. Half-measures do not work here: leaving an id on any one item type just moves the
        error to that type.

    Never deletes a line and never changes the line count, so it is idempotent and cannot shift a
    byte offset that a future codex version might project history from.

    Returns counts for logging: {"reasoning": n_blobs_dropped, "deref": n_ids_removed,
                                 "damaged": n_files_repaired}.
    """
    # Item id prefixes the provider mints and will therefore try to resolve. `fcr_` is the
    # function_call_output form; `ctc_` the custom_tool_call form.
    MINTED = ("msg_", "rs_", "fc_", "fcr_", "ctc_")
    counts = {"reasoning": 0, "deref": 0, "damaged": 0}
    # The same account serving the resume can resolve its own ids and decrypt its own blobs, and
    # keeping both is what lets a model switch inside one resource (two Azure deployments) and a
    # follow-up on one key keep their reasoning continuity. Only a resume under another account
    # (the July thread born on Azure, resumed on the org's own OpenAI key; a chain fallback; a
    # rotated key) is turned into content. Richard's rule (2026-09-06): a session that changes
    # provider is not supported; everything on one provider must work.
    if not content_only:
        return counts

    for path in rollouts:
        try:
            raw = pathlib.Path(path).read_text()
        except OSError:
            continue
        lines = raw.splitlines()

        parsed: list[tuple[str, dict | None]] = []
        for line in lines:
            if '"response_item"' not in line:
                parsed.append((line, None))
                continue
            try:
                parsed.append((line, json.loads(line)))
            except ValueError:
                parsed.append((line, None))   # unparseable: preserve verbatim

        # Pass 1 — drop the account-bound blob, keep the item; its id goes in pass 2.
        for i, (line, o) in enumerate(parsed):
            if not o or o.get("type") != "response_item":
                continue
            pay = o.get("payload")
            if not isinstance(pay, dict) or pay.get("type") != "reasoning":
                continue
            if pay.pop("encrypted_content", None) is not None:
                counts["reasoning"] += 1
                parsed[i] = (json.dumps(o), o)

        # Pass 2 — a replayed history is content, never a reference. Every provider-minted id is
        # removed on every resume: an id is a lookup into the state of the deployment or account
        # that minted it, and a resumed thread is routinely served by another one (a July thread
        # born on Azure resumed on the org's own OpenAI key answered 404 on every turn; a switch
        # between two deployments of one Azure resource answered "message provided without its
        # required reasoning item"; both 2026-09-06). With the ids gone the provider reads the
        # items as ordinary content; `call_id`, `phase`, `role`, `content`, `name` and `arguments`
        # stay, so tool pairing and the transcript survive. This trades server-side reasoning
        # continuity for a replay that works wherever the next turn runs.
        minted = [
            (i, o) for i, (line, o) in enumerate(parsed)
            if o and o.get("type") == "response_item" and isinstance(o.get("payload"), dict)
            and str((o["payload"] or {}).get("id") or "").startswith(MINTED)
        ]
        if minted:
            counts["damaged"] += 1
            for i, o in minted:
                o["payload"].pop("id", None)
                counts["deref"] += 1
                parsed[i] = (json.dumps(o), o)

        out = [line for line, _ in parsed]
        if out != lines:
            pathlib.Path(path).write_text("\n".join(out) + ("\n" if out else ""))

    return counts


def _build_codex(provider: str, auth: Auth, model: str, prompt: str, cwd: str,
                 env: dict, mcp_toml: str = "", resume_session_id: str | None = None,
                 tools_disabled: list[str] | None = None) -> tuple[list[str], str]:
    """The exec command, and the note the transcript must carry when a follow-up's rollout is gone."""
    cfg_dir = _codex_prepare_env(provider, auth, model, cwd, env, mcp_toml, resume=bool(resume_session_id),
                                 tools_disabled=tools_disabled)
    # Drop --ephemeral so codex PERSISTS the rollout to $CODEX_HOME/sessions (inside the checkpointed
    # workspace) — that's what makes a follow-up history-aware. Mirror the claude resume guard: only
    # `resume <id>` if the rollout is actually present in the (re)hydrated workspace, else start fresh
    # in the SAME workspace (files preserved) so a follow-up never hard-fails on a missing session.
    common = ["--dangerously-bypass-approvals-and-sandbox", "--skip-git-repo-check", "--json",
              "-c", f"model={model}"]
    if resume_session_id:
        import glob as _glob
        rollouts = _glob.glob(str(cfg_dir / "sessions" / "**" / "*.jsonl"), recursive=True)
        if rollouts:
            # Make the rollout safe to replay: drop account-bound reasoning blobs, and repair a
            # rollout an older build already damaged (see the helper). Logged unconditionally —
            # staying silent at zero is what hid this step during the investigation.
            c = _sanitize_codex_rollout(rollouts, content_only=env.get("HR_CODEX_ACCOUNT_CHANGED") != "0")
            print(f"[resume] codex: sanitised rollout — dropped {c['reasoning']} reasoning blob(s), "
                  f"de-referenced {c['deref']} id(s) across {c['damaged']} damaged file(s)", flush=True)
            # CODEX_HOME is PER-SESSION (hydrate wipes + restores only THIS session's workspace), so
            # the most-recent rollout here IS this conversation. Resume by --last instead of matching
            # the thread UUID to the rollout filename (that match is codex-version-fragile and missed
            # ~1/3 of the time). --last is exact here precisely because the home is session-isolated.
            return ["codex", "exec", "resume", "--last", *common, prompt], ""
        print(f"[resume] codex: no rollout in workspace for {resume_session_id} — starting fresh", flush=True)
        return ["codex", "exec", *common, "--cd", cwd, prompt], _CODEX_NO_ROLLOUT_NOTE
    return ["codex", "exec", *common, "--cd", cwd, prompt], ""


# ── dsh (DeepSeek Harness) ──────────────────────────────────────────────────────
# The turn process is runner/dsh_driver.py inside the pinned dsh venv: the official Python SDK
# launches the bundled runtime executable, and every session.event notification comes back as
# one NDJSON line {"m": method, "p": payload}. Cancel stays a process-group kill — the SDK's
# close ladder never runs on a killed driver, and the runtime dies with the group.
# "deepseek" is the launch provider (dsh's own adapter, auto-mounted); everything else rides
# dsh-llm-pi-ai — pi's unified LLM library as a Cordis plugin — through a hand-declared route
# at the driver's relay, so the api-by-family rules are the ones the pi backend already proved.
DSH_PROVIDERS = {"deepseek", "anthropic", "openai", "azure", "openai-api", "tokenrouter"}
_DSH_DEFAULT_BASE = {"anthropic": "https://api.anthropic.com/v1",
                     "openai": "https://api.openai.com/v1",
                     "deepseek": "https://api.deepseek.com/v1"}
DSH_PYTHON = os.environ.get("HR_DSH_PYTHON", "/data/agent-tools/dsh-venv/bin/python")
_DSH_DEEPSEEK_MODEL = re.compile(r"(?:^|/)deepseek", re.I)
DSH_DRIVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dsh_driver.py")


def _build_dsh(provider: str, auth: Auth, model: str, prompt: str, cwd: str, env: dict,
               resume_session_id: str | None = None,
               mcp_servers: list[dict] | None = None, vision: bool = True) -> list[str]:
    pr = provider or "deepseek"
    if pr not in DSH_PROVIDERS:
        raise HTTPException(400, f"unknown dsh provider '{pr}' (one of {sorted(DSH_PROVIDERS)})")
    base = auth.base_url or _DSH_DEFAULT_BASE.get(pr, "")
    if not base:
        raise HTTPException(400, f"dsh provider '{pr}' needs a base_url (none configured)")
    # The relay joins upstream paths against a /v1 base for known providers. But a CUSTOM
    # openai endpoint carries its own version path (https://host/api/coding/v3) — appending
    # /v1 would make /v3/v1 and 404, so a custom base is used as-is.
    if auth.api_format != "openai" and not base.rstrip("/").endswith("/v1"):
        base = base.rstrip("/") + "/v1"   # the relay joins upstream paths against a /v1 base
    # HR_DSH_*: consumed and scrubbed by the driver before the runtime starts. The runtime gets
    # a loopback relay URL and a placeholder key — the credential never enters its environment.
    env["HR_DSH_BASE_URL"] = base
    env["HR_DSH_API_KEY"] = auth.api_key or ""
    # The driver's own relay waits on the provider as long as this one does (dsh_driver._upstream_wait).
    env["HR_RELAY_UPSTREAM_TIMEOUT_S"] = f"{HR_RELAY_UPSTREAM_TIMEOUT_S:g}"
    # No system_prompt in the job: harness instructions land in AGENTS.md (dsh reads it via
    # its dsh-agent-instructions loader), same mechanism as codex/hermes/pi.
    job = {"prompt": prompt, "model": model, "cwd": cwd,
           "session_id": resume_session_id or "",
           # a server is a url or, for a plugin's stdio server, the launcher the runner wrote
           "mcp_servers": [s for s in (mcp_servers or []) if (s or {}).get("url") or (s or {}).get("command")]}
    if not _DSH_DEEPSEEK_MODEL.search(model or ""):
        # Family decides the route, not the integration's name: deepseek models keep the
        # verified dsh-llm-deepseek launch path whichever endpoint serves them; every other
        # family rides the pi-ai route. api by family — the same routing the pi backend
        # live-verified on these channels. When api_format is set (custom integration), the
        # user's explicit choice wins.
        if auth.api_format == "anthropic":
            api = "anthropic-messages"
        elif auth.api_format == "openai":
            api = "openai-completions"
        elif pr == "anthropic" or _PI_CLAUDE_MODEL.search(model or ""):
            api = "anthropic-messages"
        elif pr == "azure" or _HERMES_RESPONSES_API_MODEL.search(model or ""):
            api = "openai-responses"
        else:
            api = "openai-completions"
        job["llm"] = {"api": api, "vision": vision}
    return [DSH_PYTHON, DSH_DRIVER, json.dumps(job)]


def _dsh_tool_result_text(msg: dict) -> tuple[str, str, bool]:
    """(tool_use_id, text, is_error) from a dsh tool/result data.message."""
    tuid, text, err = "", "", False
    for c in (msg.get("content") or []):
        if isinstance(c, dict) and c.get("type") == "tool-result":
            tuid = str(c.get("toolCallId") or "")
            err = bool(c.get("isError"))
            parts = [x.get("text") or "" for x in (c.get("content") or [])
                     if isinstance(x, dict) and x.get("type") == "text"]
            text = "\n".join(x for x in parts if x)
    return tuid, text, err


def _dsh_to_claude(obj: dict, state: dict) -> list[dict]:
    """Map ONE driver NDJSON line to zero+ canonical claude stream-json events.

    Shapes are the live captures of 2026-08-20 (bad-key run, tool run, retry run) — see the
    fixtures in tests/test_dsh_normalize.py. Two audit rules are load-bearing here: usage is
    keyed by (turn, step) and REPLACED, never summed twice; and the terminal status comes from
    the last turn/end reason — the driver exits 0 either way."""
    m, p = obj.get("m"), obj.get("p") or {}
    if m == "__hr_init":
        sid = p.get("session_id") or ""
        if sid:
            state["_dsh_init"] = True
            return [{"type": "system", "subtype": "init", "session_id": sid,
                     "model": state.get("model")}]
        return []
    if m == "__hr_result":
        usage_map = state.get("_dsh_usage") or {}
        usage: dict = {}
        for u in usage_map.values():
            for k, v in u.items():
                usage[k] = usage.get(k, 0) + v
        usage = {k: v for k, v in usage.items() if v}
        reason = p.get("reason")
        final = p.get("final") or state.get("final", "")
        state["final"] = final
        if reason == "completed" or (reason is None and final):
            return [{"type": "result", "subtype": "success", "is_error": False,
                     "result": final, "usage": usage}]
        if reason == "max-tokens":
            return [{"type": "result", "subtype": "error_max_turns", "is_error": False,
                     "result": final, "usage": usage}]
        err = state.get("_dsh_error") or f"deepseek-harness turn ended: {reason}"
        return [{"type": "result", "subtype": "error", "is_error": True,
                 "result": err, "usage": usage}]
    if m != "session.event":
        return []
    ev = p.get("event") or {}
    t = ev.get("type")
    d = ev.get("data") or {}
    if not state.get("_dsh_init") and p.get("sessionId"):
        state["_dsh_init"] = True
        return [{"type": "system", "subtype": "init", "session_id": p["sessionId"],
                 "model": state.get("model")}] + _dsh_to_claude(obj, state)
    if t == "assistant/chunk":
        c = d.get("chunk") or {}
        ct = c.get("type")
        if ct == "text-delta" and c.get("text"):
            state["_dsh_text"] = state.get("_dsh_text", "") + c["text"]
            state["final"] = state["_dsh_text"]
            return [{"type": "assistant", "message": {"content": [{"type": "text", "text": c["text"]}]}}]
        if ct == "reasoning-delta" and c.get("text"):
            return [{"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": c["text"]}]}}]
        if ct == "usage":
            u = c.get("usage") or {}
            mapped = {"input_tokens": int(u.get("inputTokens") or 0),
                      "output_tokens": int(u.get("outputTokens") or 0)}
            if u.get("cacheReadTokens"):
                mapped["cache_read_tokens"] = int(u["cacheReadTokens"])
            if u.get("cacheWriteTokens"):
                mapped["cache_write_tokens"] = int(u["cacheWriteTokens"])
            # replace-by-(turn,step): retries re-report the same step; summing would double-bill
            state.setdefault("_dsh_usage", {})[(d.get("turn"), d.get("step"))] = mapped
            return []
        return []   # block-start/block-end/tool-call-delta/finish: committed events cover them
    if t == "assistant/message":
        msg = d.get("message") or {}
        full = "".join(c.get("text") or "" for c in (msg.get("content") or [])
                       if isinstance(c, dict) and c.get("type") == "text")
        streamed = state.get("_dsh_text", "")
        state["_dsh_text"] = ""
        if full:
            state["final"] = full
        if full and full != streamed:
            if not streamed:
                return [{"type": "assistant", "message": {"content": [{"type": "text", "text": full}]}}]
            if full.startswith(streamed):
                return [{"type": "assistant", "message": {"content": [{"type": "text", "text": full[len(streamed):]}]}}]
        return []   # matches, or a non-prefix revision (already painted — the pi lesson)
    if t == "tool/call":
        try:
            args = json.loads(d.get("arguments") or "{}")
        except Exception:  # noqa: BLE001
            args = {"raw": d.get("arguments")}
        return [{"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": d.get("callId") or f"dsh{ev.get('seq', 0)}",
             "name": d.get("name") or "tool", "input": args}]}}]
    if t == "tool/result":
        tuid, text, err = _dsh_tool_result_text(d.get("message") or {})
        return [{"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": tuid or "dsh",
             "is_error": err, "content": text}]}}]
    if t == "turn/end":
        reason = (d.get("reason") or {})
        if reason.get("kind") == "error":
            state["_dsh_error"] = str((reason.get("error") or {}).get("message") or "dsh error")
        return []
    return []


# ── pi (earendil-works pi coding agent) ─────────────────────────────────────────
# One-shot turns run `pi -p --mode json`: a JSONL event stream on stdout (session header,
# message deltas, tool executions, agent_end). Sessions are JSONL trees under
# $HOME/.pi/agent/sessions/<cwd-slug>/ — inside the checkpointed workspace, so `--session-id`
# resumes across sandbox recycling. `--session-id` CREATES the session when the file is missing,
# which is exactly the fallback the claude/codex paths need explicit existence checks for.
#
# The CLI exits 0 even when the provider call fails (verified against 0.84.2 with a bad key:
# the failure is stopReason="error" + errorMessage ON THE MESSAGE, not an error event, not a
# nonzero exit). Status therefore comes from the event stream — never from the exit code.
PI_PROVIDERS = {"anthropic", "openai", "azure", "openai-api", "tokenrouter"}

# api field for models.json, by how the endpoint actually speaks. openai-responses vs
# openai-completions matters for the same reason it does on hermes: the gpt-5 line refuses
# tool-carrying requests on /v1/chat/completions (see _HERMES_RESPONSES_API_MODEL).
_PI_CLAUDE_MODEL = re.compile(r"(?:^|/)(?:us\.anthropic\.)?claude", re.I)


def _pi_models_json(api: str, base_url: str, api_key: str, model: str,
                    vision: bool = True, custom_openai: bool = False) -> str:
    """A one-provider ~/.pi/agent/models.json ("hr") for a custom endpoint. Pi's anthropic client
    appends /v1/messages to baseUrl while its openai clients expect the /v1 to already be there
    (both read straight off pi's own docs/models.md examples), so the /v1 suffix is normalized
    per api instead of trusting how the integration happened to store the URL.

    `input` is pi's capability gate, and it is load-bearing on RESUME: a session that once ran a
    vision model can carry an image tool-result, which pi replays to the current model as a user
    message with an image part — verified against a capturing sink. Declared text-only, pi drops
    the image and the turn runs; declared vision on a model whose channel refuses images, the
    whole turn dies on the provider's 400. The gateway says which models are text-only, from
    live probes, so vision stays the default.

    `custom_openai`: a CUSTOM OpenAI endpoint carries its own version path (e.g. https://host/
    api/coding/v3) — appending our own /v1 would make /v3/v1 and 404. So for a custom endpoint
    the base_url is used as-is and only /chat/completions is joined."""
    base = (base_url or "").rstrip("/")
    if api == "anthropic-messages":
        base = base.removesuffix("/v1")
    elif not custom_openai and not base.endswith("/v1"):
        base += "/v1"
    return json.dumps({"providers": {"hr": {
        "baseUrl": base, "api": api, "apiKey": api_key,
        "models": [{"id": model, "name": model, "reasoning": False,
                    "input": ["text", "image"] if vision else ["text"],
                    "contextWindow": 200000, "maxTokens": 32000}],
    }}}, indent=2)


def _pi_write_mcp(home: pathlib.Path, servers: list[dict] | None) -> bool:
    """Write $HOME/.pi/agent/mcp-adapter.json for pi-mcp-adapter (same input contract as the
    claude/codex writers: url + optional auth/headers, or command + args for a plugin's stdio
    server). Returns whether any server was written. The agent-dir location is deliberate:
    project-local .pi/mcp.json sits behind pi's trust gate; the agent dir does not.

    THE FILE IS NAMED FOR ADAPTER 3.x. pi-mcp-adapter 3 reads .mcp.json, ~/.config/mcp/mcp.json
    and <agent dir>/mcp-adapter.json and, its README says, "does not read Pi's <agent dir>/mcp.json
    or .pi/mcp.json at all"; 2.x read mcp.json. A volume that installed 2.x at its first boot kept
    working on the old name while a fresh one resolved 3.x and saw no server at all (hosted,
    2026-09-27: pi listed no MCP tool and grepped the workspace for the tool's name). The
    entrypoint pins the adapter's version, so the name here is the one that version reads."""
    entries: dict = {}
    for s in servers or []:
        name = _mcp_name((s or {}).get("name") or (s or {}).get("id") or "mcp")
        url = (s or {}).get("url")
        if not url:
            # A plugin's stdio server: the adapter spawns `command` itself (its stdio transport,
            # mutually exclusive with url), and the launcher the runner wrote carries env and cwd.
            if (s or {}).get("command"):
                entries[name] = {"command": s["command"], "args": list(s.get("args") or [])}
            continue
        entry: dict = {"url": url}
        if _mcp_headers(s):
            entry["headers"] = _mcp_headers(s)
        entries[name] = entry
    if not entries:
        return False
    path = home / ".pi" / "agent" / "mcp-adapter.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    # directTools: the tools are registered on the agent one by one, as every other CLI lists
    # MCP tools. The adapter's default hides them behind one `mcp` proxy tool (search, then call),
    # and a model that is not told to search answers that it has no such tool: a harness with the
    # browser plugin included said "I can't directly control a browser here" to Richard on
    # 2026-09-25 while all thirteen tools sat in the adapter's cache. The proxy goes with it, so
    # the model has one way to a tool, not two.
    path.write_text(json.dumps({"settings": {"directTools": True, "disableProxyTool": True},
                                "mcpServers": entries}, indent=2))
    return True


def _build_pi(provider: str, auth: Auth, model: str, prompt: str, cwd: str, env: dict,
              resume_session_id: str | None = None, mcp_servers: list[dict] | None = None,
              tools_disabled: list[str] | None = None, vision: bool = True) -> list[str]:
    pr = provider or "anthropic"
    if pr not in PI_PROVIDERS:
        raise HTTPException(400, f"unknown pi provider '{pr}' (one of {sorted(PI_PROVIDERS)})")
    home = pathlib.Path(env.get("HOME") or cwd)
    (home / ".pi" / "agent").mkdir(parents=True, exist_ok=True)

    # Provider: native env for the two vendors pi speaks natively WITHOUT a base_url override;
    # everything else (and any base_url override) goes through a models.json custom provider,
    # because that is the only place pi accepts an endpoint from.
    use_custom = bool(auth.base_url) or pr in ("azure", "openai-api", "tokenrouter")
    if use_custom:
        if not auth.base_url:
            raise HTTPException(400, f"pi provider '{pr}' needs a base_url (none configured)")
        # When api_format is set (custom integration), use the user's explicit choice. Otherwise
        # pick by model family — the same routing the hermes backend already proved.
        if auth.api_format == "anthropic":
            api = "anthropic-messages"
        elif auth.api_format == "openai":
            api = "openai-completions"
        elif pr == "anthropic" or (pr == "tokenrouter" and _PI_CLAUDE_MODEL.search(model or "")):
            api = "anthropic-messages"
        elif pr == "azure" or _HERMES_RESPONSES_API_MODEL.search(model or ""):
            api = "openai-responses"
        else:
            api = "openai-completions"
        if api in ("openai-completions", "openai-responses") and auth.api_key and not auth.api_format:
            # An OpenAI-shape turn rides the loopback relay, as every qwen and cline turn does: the
            # relay repairs the request shape in flight (Google's OpenAI-compatible endpoint refuses
            # OpenAI's optional fields, measured 2026-09-06) and the key never lands in the
            # workspace's models.json, which is checkpointed. A custom endpoint keeps its own URL.
            relay_base, relay_tok = _hermes_relay_route(auth.base_url, auth.api_key)
            auth = auth.model_copy(update={"base_url": relay_base, "api_key": relay_tok})
        (home / ".pi" / "agent" / "models.json").write_text(
            _pi_models_json(api, auth.base_url, auth.api_key or "", model, vision=vision,
                            custom_openai=bool(auth.api_format)))
        pname = "hr"
    else:
        pname = pr
        if pr == "anthropic" and auth.api_key:
            env["ANTHROPIC_API_KEY"] = auth.api_key
        elif pr == "openai" and auth.api_key:
            env["OPENAI_API_KEY"] = auth.api_key

    cmd = ["pi", "-p", "--mode", "json", "--provider", pname, "--model", model,
           # The sandbox is the trust boundary (one Hyper-V-isolated box per session), so
           # project-local files are trusted the same way claude gets
           # --dangerously-skip-permissions: explicitly, because nobody is there to answer.
           "--approve",
           # Discovery off, mounts explicit: a task could drop .pi/extensions/ into the
           # workspace and have the next turn execute it. -e paths still load.
           "--no-extensions"]
    if resume_session_id:
        # --session-id resumes the project session when its file is in the (re)hydrated
        # workspace and CREATES it when not — the fresh-start fallback the other backends
        # implement by hand is pi's documented behavior, so no existence check here.
        cmd += ["--session-id", resume_session_id]
    if tools_disabled:
        # Pi has a real per-tool switch (-xt) — enforcement, not instruction. Names are pi's
        # own (bash/read/write/edit); catalog labels arrive as "bash (Shell)"-style, keep the id.
        names = ",".join(sorted({x.split(" (")[0].strip() for x in tools_disabled if x and x.strip()}))
        if names:
            cmd += ["--exclude-tools", names]
    if _pi_write_mcp(home, mcp_servers):
        ext = os.environ.get("HR_PI_MCP_EXT", "")
        if ext and os.path.exists(ext):
            cmd += ["--extension", ext]
        else:
            # Servers were configured but the adapter isn't installed: say so in the stream
            # (errbuf tail) instead of silently running a turn with no tools.
            print("[pi] MCP servers configured but pi-mcp-adapter not installed "
                  "(HR_PI_MCP_EXT unset or missing) — this turn runs without them", flush=True)
    cmd.append(prompt)
    return cmd


def _pi_usage_add(state: dict, u: dict | None) -> None:
    """Accumulate pi per-message usage {input, output, cacheRead, cacheWrite} into the turn total.
    Pi already reports input as fresh-only (cacheRead separate), matching the canonical contract."""
    if not isinstance(u, dict):
        return
    tot = state.setdefault("_pi_usage", {"input_tokens": 0, "output_tokens": 0,
                                         "cache_read_tokens": 0, "cache_write_tokens": 0})
    for src, dst in (("input", "input_tokens"), ("output", "output_tokens"),
                     ("cacheRead", "cache_read_tokens"), ("cacheWrite", "cache_write_tokens")):
        v = u.get(src)
        if isinstance(v, (int, float)):
            tot[dst] += int(v)


_MODEL_SNAPSHOT_DATE = re.compile(r"-\d{8}$")


def _same_model(requested: str, served: str) -> bool:
    """Whether two ids name the same model. The check is about substitution (Richard: the models
    are honest, no fallback), not spelling: a vendor names its model its own way in the response,
    and pi puts THAT on the assistant message for an Anthropic-shaped stream (pi-ai 0.85.1
    anthropic-messages.js: `output.model = event.message.model` on message_start; its OpenAI
    clients stamp the configured id). Through an aggregator the requested id is the routed one,
    `anthropic/claude-opus-4.8`, and Anthropic answers `claude-opus-4-8`; `claude-haiku-4.5` comes
    back as the dated snapshot `claude-haiku-4-5-20251001`. Same model, so: a vendor prefix, case,
    dots against dashes and a trailing snapshot date do not count (every hosted pi restore on an
    Anthropic id failed as a substitution, 2026-09-08). `gemini-3-flash-preview` for
    `gemini-3.8-flash` stays a substitution."""
    def canon(m: str) -> str:
        m = (m or "").strip().lower().rsplit("/", 1)[-1].replace(".", "-")
        return _MODEL_SNAPSHOT_DATE.sub("", m)
    return bool(requested) and bool(served) and canon(requested) == canon(served)


def _pi_to_claude(obj: dict, state: dict) -> list[dict]:
    """Map ONE pi `--mode json` event to zero+ canonical claude stream-json events.

    Text streams from message_update deltas; message_end re-emits only the un-streamed tail
    (the same self-healing contract as _codex_text_delta: if deltas never arrive, the tail is
    the whole text). Failure is stopReason=="error" on the assistant message — the CLI exits 0
    on provider errors, so the result event synthesized at agent_end is the ONLY truthful
    status signal."""
    t = obj.get("type")
    if t == "session":
        return [{"type": "system", "subtype": "init",
                 "session_id": obj.get("id"), "model": state.get("model")}]
    if t == "message_update":
        ev = obj.get("assistantMessageEvent") or {}
        et = ev.get("type")
        if et == "text_delta" and ev.get("delta"):
            state["_pi_text"] = state.get("_pi_text", "") + ev["delta"]
            state["final"] = state["_pi_text"]   # the CURRENT message is the candidate final text
            return [{"type": "assistant", "message": {"content": [{"type": "text", "text": ev["delta"]}]}}]
        if et == "thinking_delta" and ev.get("delta"):
            return [{"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": ev["delta"]}]}}]
        return []
    if t == "message_end":
        msg = obj.get("message") or {}
        if msg.get("role") != "assistant":
            return []
        _pi_usage_add(state, msg.get("usage"))
        if msg.get("model"):
            # the model the CLI ran this message on (pi and omp name it on every assistant message)
            state.setdefault("_served", []).append(str(msg["model"]))
        if msg.get("stopReason") == "error":
            state["_pi_error"] = str(msg.get("errorMessage") or "pi provider error")
            return []
        full = "".join(c.get("text") or "" for c in (msg.get("content") or [])
                       if isinstance(c, dict) and c.get("type") == "text")
        streamed = state.get("_pi_text", "")
        state["_pi_text"] = ""
        # `final` is the LAST assistant message's text (claude result semantics), so message_end
        # REPLACES it — a mid-run "let me look" followed by the answer must not concatenate.
        if full:
            state["final"] = full
        if full and full != streamed:
            if not streamed:
                # no deltas arrived — emit the whole text once (the no-streaming path)
                return [{"type": "assistant", "message": {"content": [{"type": "text", "text": full}]}}]
            if full.startswith(streamed):
                # normal self-healing: emit only the un-streamed tail
                return [{"type": "assistant", "message": {"content": [{"type": "text", "text": full[len(streamed):]}]}}]
            # Non-prefix revision (seen live: a kimi channel whose deltas and final text
            # disagree). The streamed text is already on the user's screen — re-emitting the
            # full text painted the whole answer twice. Emit nothing: the result event and
            # state["final"] already carry the authoritative text.
            return []
        return []
    if t == "tool_execution_start":
        return [{"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": obj.get("toolCallId") or "tool",
             "name": obj.get("toolName") or "tool", "input": obj.get("args") or {}}]}}]
    if t == "tool_execution_end":
        res = obj.get("result")
        if isinstance(res, dict):
            # pi ToolResult: {content:[{type:text,...}], details?} — flatten the text blocks
            parts = [c.get("text") or "" for c in (res.get("content") or [])
                     if isinstance(c, dict) and c.get("type") == "text"]
            content = "\n".join(x for x in parts if x) or json.dumps(res, default=str)[:4000]
        else:
            content = str(res or "")
        return [{"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": obj.get("toolCallId") or "tool",
             "is_error": bool(obj.get("isError")), "content": content}]}}]
    if t == "agent_end":
        if obj.get("willRetry"):
            # pi retries a retryable provider error itself (settings.retry: three attempts by
            # default), a reply stream cut mid-message among them, and says so on the agent_end it
            # emits before retrying. That agent_end is not the end of the turn: the attempt's error
            # and its half-streamed text give way to the retry's. Taking it as the end failed a
            # GDPval turn whose relay cut the last line of its reply (2026-09-26) while pi retried
            # and finished; the error also outlived a successful retry, so the true end failed too.
            state.pop("_pi_error", None)
            state["_pi_text"] = ""
            return []
        err = state.get("_pi_error")
        usage = dict(state.get("_pi_usage") or {})
        usage = {k: v for k, v in usage.items() if v}
        served = sorted(set(state.get("_served") or []))
        requested = str(state.get("model") or "")
        other = [m for m in served if requested and not _same_model(requested, m)]
        if other and not err:
            # the models are honest, no fallback: a turn the CLI ran on another model than the one
            # asked for fails with the reason on the record, never completes (the served-model rule
            # the support matrix judges by, enforced for the user)
            err = f"the CLI ran {', '.join(other)} instead of {requested}"
        ev = {"type": "result", "subtype": "error" if err else "success", "is_error": bool(err),
              "result": err or state.get("final", ""), "usage": usage}
        if served:
            ev["model"] = ",".join(served)
        return [ev]
    return []


# ── omp (Oh My Pi, can1357/oh-my-pi CLI) ─────────────────────────────────────────
# OMP is built on the Pi lineage and shares its JSON event stream contract (--mode json), so it
# shares _pi_to_claude too. Unlike raw Pi, OMP has native MCP support via <agent_dir>/mcp.json and
# a richer built-in tool set (bash, read, write, edit, glob, grep, lsp, python, todo, task, etc.).
# Measured on 18.1.13 (2026-09-07): -p --mode json --model --auto-approve --no-extensions --resume
# --tools/--no-tools are its flags, PI_CODING_AGENT_DIR is honoured, sessions land under
# <agent_dir>/sessions/<cwd slug>/<ts>_<id>.jsonl, -r <id> recalls the first message, --tools=read
# leaves a write unwritten, and every assistant message names the model it ran.
OMP_PROVIDERS = {"anthropic", "openai", "azure", "openrouter", "tokenrouter", "openai-api"}
# The built-in tools omp 18.1.13 accepts on --tools, read off the binary by probing each name (a
# rejected name kills the turn: "Unknown tool in --tools"). "python" and "browser" were in this
# list and are not tools of this build, so every harness that disabled ANY tool sent an allowlist
# omp refused, and every one of its turns died with a stack trace (found by the custom-harness
# matrix dimension, 2026-09-08). A CLI bump re-probes this list; the test beside it pins it.
ALL_OMP_TOOLS = {"bash", "read", "write", "edit", "glob", "grep", "lsp", "todo", "task", "web_search"}


def _omp_has_session(agent_dir: pathlib.Path, session_id: str) -> bool:
    """Is this session actually in this agent directory?

    OMP writes session logs under <agent_dir>/sessions/ as *.jsonl files named with
    the session id. If the session is missing, passing --resume would exit with an error.
    """
    if not session_id or not agent_dir.exists():
        return False
    sess_dir = agent_dir / "sessions"
    if not sess_dir.exists():
        return False
    try:
        for path in sess_dir.rglob(f"*{session_id}*.jsonl"):
            if path.is_file():
                return True
    except Exception:  # noqa: BLE001
        return False
    return False


def _omp_write_mcp(agent_dir: pathlib.Path, servers: list[dict] | None) -> bool:
    """Write <agent_dir>/mcp.json for OMP native MCP support.

    OMP reads the user file at <agent_dir>/mcp.json (PI_CODING_AGENT_DIR) with the standard
    mcpServers schema. `type: "http"` is what docs/mcp-config.md requires on an HTTP entry ("http
    transport: Required: type, url"), so the entry says it. Measured on 18.1.13 (2026-09-08): the
    loader also infers it, `transport ?? (command ? "stdio" : url ? "http" : "stdio")`, so an
    untyped entry with a url was served too; the dimension's earlier miss on omp was its judge,
    which reads tool names, while omp dispatches MCP as a `write` to
    xd://mcp__<server>_<tool>. Returns whether any server was written.
    """
    entries: dict = {}
    for s in servers or []:
        url = (s or {}).get("url")
        name = _mcp_name((s or {}).get("name") or (s or {}).get("id") or "mcp")
        if not url and (s or {}).get("command"):
            # A stdio server (a plugin's, through its launcher): the standard mcpServers shape,
            # which the loader infers as stdio from `command` and which `type` states outright.
            entries[name] = {"type": "stdio", "command": str(s["command"]),
                             "args": [str(a) for a in (s.get("args") or [])]}
            continue
        if not url:
            continue
        entry: dict = {"type": "sse" if str((s or {}).get("transport") or "").lower() == "sse" else "http", "url": url}
        if _mcp_headers(s):
            entry["headers"] = _mcp_headers(s)
        entries[name] = entry
    if not entries:
        return False
    path = agent_dir / "mcp.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mcpServers": entries}, indent=2))
    return True


def _build_omp(provider: str, auth: Auth, model: str, prompt: str, cwd: str, env: dict,
               resume_session_id: str | None = None, mcp_servers: list[dict] | None = None,
               tools_disabled: list[str] | None = None, vision: bool = True) -> list[str]:
    pr = provider or "anthropic"
    if pr not in OMP_PROVIDERS:
        raise HTTPException(400, f"unknown omp provider '{pr}' (one of {sorted(OMP_PROVIDERS)})")
    home = pathlib.Path(env.get("HOME") or cwd)
    omp_agent_dir = home / ".omp" / "agent"
    omp_agent_dir.mkdir(parents=True, exist_ok=True)
    env["PI_CODING_AGENT_DIR"] = str(omp_agent_dir)
    env.pop("OMP_PROFILE", None)
    env.pop("PI_PROFILE", None)

    use_custom = bool(auth.base_url) or pr in ("azure", "openai-api", "tokenrouter")
    if use_custom:
        if not auth.base_url:
            raise HTTPException(400, f"omp provider '{pr}' needs a base_url (none configured)")
        if auth.api_format == "anthropic":
            api = "anthropic-messages"
        elif auth.api_format == "openai":
            api = "openai-completions"
        elif pr == "anthropic" or (pr == "tokenrouter" and _PI_CLAUDE_MODEL.search(model or "")):
            api = "anthropic-messages"
        elif pr == "azure" or _HERMES_RESPONSES_API_MODEL.search(model or ""):
            api = "openai-responses"
        else:
            api = "openai-completions"
        if api in ("openai-completions", "openai-responses") and auth.api_key and not auth.api_format:
            # An OpenAI-shape turn rides the loopback relay, as pi's and qwen's do: the relay repairs
            # the request shape in flight (Gemini 3's thought signatures, TokenRouter's schema subset,
            # Azure's max_tokens), and the real key never lands in the workspace's models.yml. A
            # custom endpoint keeps its own URL.
            relay_base, relay_tok = _hermes_relay_route(auth.base_url, auth.api_key)
            auth = auth.model_copy(update={"base_url": relay_base, "api_key": relay_tok})
        models_content = _pi_models_json(api, auth.base_url, auth.api_key or "", model, vision=vision,
                                          custom_openai=bool(auth.api_format))
        # omp reads custom providers from models.yml (its README's file; YAML takes the JSON as is);
        # models.json is kept beside it for the pi-lineage census
        (omp_agent_dir / "models.json").write_text(models_content)
        (omp_agent_dir / "models.yml").write_text(models_content)
        pname = "hr"
    else:
        pname = pr
        if pr == "anthropic" and auth.api_key:
            env["ANTHROPIC_API_KEY"] = auth.api_key
        elif pr == "openai" and auth.api_key:
            env["OPENAI_API_KEY"] = auth.api_key

    cmd = ["omp", "-p", "--mode", "json",
           "--model", f"{pname}/{model}" if pname == "hr" else model,
           "--auto-approve",
           "--no-extensions"]
    if resume_session_id and _omp_has_session(omp_agent_dir, resume_session_id):
        cmd += ["--resume", resume_session_id]
    if tools_disabled:
        disabled = {x.split(" (")[0].strip().lower() for x in tools_disabled if x and x.strip()}
        enabled = [t for t in sorted(ALL_OMP_TOOLS) if t not in disabled]
        # A disable list that names none of omp's tools (a name from another runtime, say) changes
        # nothing, so nothing is sent: an allowlist is only a constraint when it removes something.
        if len(enabled) == len(ALL_OMP_TOOLS):
            pass
        elif not enabled:
            cmd += ["--no-tools"]
        else:
            cmd += [f"--tools={','.join(enabled)}"]
    _omp_write_mcp(omp_agent_dir, mcp_servers)
    cmd.append(prompt)
    return cmd


# ── hermes (NousResearch hermes-agent CLI) ──────────────────────────────────────────
# One-shot turns run `hermes -z` (auto-approves, prints ONLY the final text on stdout, writes a
# JSON usage report via --usage-file); follow-up turns run `hermes chat -q -r <sid>` because the
# oneshot path has no resume parameter (verified against 0.19.0 source). The CLI emits NO event
# stream on stdout — tool calls and assistant text are flushed incrementally into $HERMES_HOME/
# state.db (SQLite, WAL), which _run_hermes_bg polls to synthesize the canonical claude
# stream-json events every other backend produces.
HERMES_PROVIDERS = {"anthropic", "bedrock", "azure-foundry", "openrouter", "openai-api"}

# OpenAI's GPT-5.x line will not serve an agent turn over /v1/chat/completions: a request carrying
# both function tools and a reasoning effort is rejected with
#   HTTP 400 Function tools with reasoning_effort are not supported ... use /v1/responses
# and the codex-tuned ids reject that endpoint outright with
#   HTTP 404 This model is not supported in the v1/chat/completions endpoint.
# hermes picks its transport per config and auto-detects only api.openai.com and api.x.ai, so a
# relay sitting in front of OpenAI — an aggregator, a company gateway — is transported as generic
# chat-completions and every one of these models fails on send. The endpoint is a property of the
# MODEL, not of the host in front of it, so it is decided from the model id here.
#
# Matched against the provider-native id, which may be bare (gpt-5.6-sol) or vendor-qualified
# (openai/gpt-5.6-sol) depending on the integration.
# gpt-6-astra answers function tools on /v1/responses and is refused on /v1/chat/completions with
# the same sentence the gpt-5.x line gives, so the family test is the major version, not the 5
# (measured against OpenAI directly, 2026-09-07). Written as a range so the next line lands
# routed rather than 400-ing on its first turn.
_HERMES_RESPONSES_API_MODEL = re.compile(r"(?:^|/)(?:gpt-(?:[5-9]|\d{2,})|o[1-4])|codex", re.I)


def _hermes_api_mode(provider: str, model: str) -> str | None:
    """`model.api_mode` for config.yaml, or None to leave hermes' own detection alone.

    The generic OpenAI-compatible provider is the one whose transport hermes infers from the URL,
    so the Responses family is named for it. Azure is named too: hermes 0.19.0 infers the
    Responses API there from the prefixes codex, gpt-5, o1, o3 and o4 (hermes_cli/models.py,
    azure_foundry_model_api_mode) and reads the config's api_mode first (runtime_provider.py), so
    gpt-6-astra, none of those prefixes, went to chat completions, which Azure refuses for
    function tools with reasoning (the astra column, 2026-09-08; every other Azure pair passed).
    The same family test as the generic provider, so the next line lands routed. bedrock,
    anthropic and openrouter keep the CLI's own resolution.
    """
    if provider not in ("openai-api", "azure-foundry") or not model:
        return None
    return "codex_responses" if _HERMES_RESPONSES_API_MODEL.search(model) else None



def _hermes_mcp_section(servers: list[dict] | None) -> dict:
    """config.yaml `mcp_servers:` entries for the enabled remote MCP servers (hermes supports
    Streamable HTTP by url, SSE via `transport: sse`, and per-server headers). Same input contract
    as the claude/codex materializers: [{name, url, transport?, auth?, headers?}]."""
    out: dict = {}
    for s in servers or []:
        url = (s or {}).get("url")
        name = _mcp_name((s or {}).get("name") or (s or {}).get("id") or "mcp")
        if not url and (s or {}).get("command"):
            # A stdio server (a plugin's, through its launcher): hermes's own command/args shape.
            out[name] = {"command": str(s["command"]), "args": [str(a) for a in (s.get("args") or [])]}
            continue
        if not url:
            continue
        entry: dict = {"url": url}
        if ((s or {}).get("transport") or "").lower() == "sse":
            entry["transport"] = "sse"
        hdrs = _mcp_headers(s)
        if hdrs:
            entry["headers"] = hdrs
        out[name] = entry
    return out


# ── hermes loopback relay (openai-api path) ─────────────────────────────────────────────────
# hermes emits OpenAI-LEGAL messages that aggregator translators reject: a tool-call assistant
# message may carry `content: ""`, and TokenRouter's OpenAI→Anthropic translation forwards that
# as an empty text content block, which Anthropic refuses — 'HTTP 400: messages: text content
# blocks must be non-empty', captured 2026-08-20 by conformance X-05 on claude-haiku-4.5, and
# intermittent because whether a given tool-call message carries empty content is up to the
# model (issue #12). Nothing sat between hermes and the provider to repair it, and the failure
# killed the turn: a 400 is never retried, and re-running on the next chain connection re-runs
# the whole task. So the openai-api path now routes through the same kind of loopback relay the
# dsh backend already has (runner/dsh_driver.py): requests are normalized BEFORE the provider
# sees them — prevention, not retry — and as with dsh, the real credential stays in this
# process; hermes gets a placeholder token the relay resolves per request, so the key never
# enters the CLI's env, its state.db, or anything it could checkpoint.
#
# One shared server, routes resolved from the placeholder bearer token: hermes is spawned per
# turn with a fresh env, so each turn registers its upstream and the entry simply outlives the
# turn (a few dozen bytes per turn, process lifetime — the sandbox recycles long before this
# matters).
_HERMES_RELAY: dict = {"server": None, "port": 0, "routes": {}, "lock": threading.Lock()}


def _with_anthropic_cache(body: bytes) -> bytes:
    """A Messages request for a Claude model with no cache_control of its own, with two breakpoints:
    the last system block and the last block of the last user message. Everything before a
    breakpoint is cached (tools, system, the conversation so far), so in an agent loop each call
    reads the previous call's prefix and writes only the new tail; this is the shape the Claude
    CLI and hermes send on their own. A request that already carries a breakpoint is the client's
    own policy and goes through untouched; a model that is not Claude is left alone, since an
    aggregator may refuse the field for it."""
    if b"cache_control" in body or b"claude" not in body.lower():
        return body
    try:
        doc = json.loads(body)
    except ValueError:
        return body
    if not isinstance(doc, dict) or "claude" not in str(doc.get("model") or "").lower():
        return body
    mark = {"type": "ephemeral"}
    changed = False
    system = doc.get("system")
    if isinstance(system, str) and system.strip():
        doc["system"] = [{"type": "text", "text": system, "cache_control": mark}]
        changed = True
    elif isinstance(system, list) and system and isinstance(system[-1], dict) and system[-1].get("type") == "text":
        system[-1]["cache_control"] = mark
        changed = True
    msgs = doc.get("messages")
    if isinstance(msgs, list) and msgs and isinstance(msgs[-1], dict) and msgs[-1].get("role") == "user":
        last = msgs[-1]
        content = last.get("content")
        if isinstance(content, str) and content.strip():
            last["content"] = [{"type": "text", "text": content, "cache_control": mark}]
            changed = True
        elif (isinstance(content, list) and content and isinstance(content[-1], dict)
              and content[-1].get("type") in ("text", "tool_result", "image", "document")):
            content[-1]["cache_control"] = mark
            changed = True
    return json.dumps(doc).encode() if changed else body


def _relay_origin(base_url: str) -> str:
    """The relay's origin (scheme://host:port) for a client that appends /v1/messages itself:
    goose's anthropic provider (ANTHROPIC_HOST), the Anthropic SDK hermes uses (ANTHROPIC_BASE_URL)
    and litellm's anthropic/ route (ANTHROPIC_API_BASE) all do, and the relay strips that /v1
    before joining the resource onto the upstream base, which carries its own."""
    u = urllib.parse.urlsplit((base_url or "").rstrip("/"))
    return f"{u.scheme}://{u.netloc}" if u.scheme and u.netloc else (base_url or "").rstrip("/")


def _anthropic_native(provider: str, auth: Auth) -> bool:
    """Whether this turn's endpoint speaks Anthropic Messages: the anthropic provider, or a custom
    endpoint declared in that format."""
    return (provider or "").lower() == "anthropic" or str(auth.api_format or "").strip().lower() == "anthropic"


def _normalize_openai_chat_body(body: bytes) -> bytes:
    """Repair OpenAI-legal-but-translator-fatal message shapes in one chat-completions body.

    Surgical, matched to what was captured live: an assistant tool-call message whose `content`
    is the empty string becomes `content: null` (equally legal, and translators emit no text
    block for it), and empty `{"type": "text", "text": ""}` parts are dropped from list-shaped
    content (if that empties a tool-call message's list, it becomes null too). An EMPTY
    `reasoning_content` is deleted outright: qwen-code echoes DeepSeek's extension field back
    verbatim, and LLMTR's validator requires it non-empty when present ('String must contain at
    least 1 character(s)', measured live on deepseek-v4-pro 2026-08-27 — the turn died right
    after its tool call). A non-empty one is meaningful interleaved thinking and passes through.
    A top-level `reasoning_effort: null` is deleted: kimi sends the key with a null value on every
    request, and Vercel's AI Gateway answers that with HTTP 400 ("Invalid option: expected one of
    \"none\"|\"minimal\"|…", measured twice in one live turn on 1.50.0), so on that gateway every
    kimi turn would fail before it began. Null is not one of the enum's options, and a client that
    sends it means "unset" — deleting it says the same thing in a shape every endpoint accepts.
    Only null is touched; a real effort value is the caller's choice and passes through, as does
    the `reasoning_effort: "none"` that _set_reasoning_effort_none sets deliberately.

    Anything else — other roles, non-empty text, unparseable bodies — passes through
    byte-identical."""
    try:
        obj = json.loads(body)
        if not isinstance(obj, dict):
            return body
        changed = False
        if "reasoning_effort" in obj and obj["reasoning_effort"] is None:
            del obj["reasoning_effort"]
            changed = True
        if not isinstance(obj.get("messages"), list):
            return json.dumps(obj, separators=(",", ":")).encode() if changed else body
        for m in obj["messages"]:
            if not isinstance(m, dict):
                continue
            content = m.get("content")
            if isinstance(content, list):
                kept = [p for p in content
                        if not (isinstance(p, dict) and p.get("type") == "text"
                                and p.get("text") == "")]
                if len(kept) != len(content):
                    m["content"] = kept if kept or not m.get("tool_calls") else None
                    changed = True
            elif content == "" and m.get("tool_calls"):
                m["content"] = None
                changed = True
            if m.get("role") == "assistant" and m.get("reasoning_content") in ("", None) \
                    and "reasoning_content" in m:
                del m["reasoning_content"]
                changed = True
        if not changed:
            return body
        return json.dumps(obj, separators=(",", ":")).encode()
    except Exception:  # noqa: BLE001 — a body we cannot parse is a body we must not alter
        return body


def _stringify_tool_content(body: bytes) -> bytes:
    """Tool-role message content: array-of-parts -> plain string, in one chat-completions body.

    OpenAI accepts both shapes; qwen-code sends the array form and stricter endpoints refuse it
    ('400 tool message content must be a string' — LLMTR, measured live 2026-08-27, killing the
    request AFTER the tool call, so the turn died mid-flight). Only text parts exist in a shell
    tool result, so the flatten is lossless where it applies; applied only after a provider says
    exactly that."""
    try:
        obj = json.loads(body)
        changed = False
        for m in obj.get("messages") or []:
            if isinstance(m, dict) and m.get("role") == "tool" and isinstance(m.get("content"), list):
                m["content"] = "".join(p.get("text", "") for p in m["content"]
                                       if isinstance(p, dict))
                changed = True
        if changed:
            return json.dumps(obj, separators=(",", ":")).encode()
    except Exception:  # noqa: BLE001 — a body we cannot parse is a body we must not alter
        pass
    return body


_IMAGE_PLACEHOLDER = ("[an image was returned here; the model serving this turn takes no image in a "
                      "tool result, so it is not shown]")


def _tool_images_as_text(body: bytes) -> bytes:
    """Tool-role messages whose content carries an image part, with the image replaced by a sentence
    and the content flattened to a string, in one chat-completions body.

    A model that sees images reads one through a tool (Grok Build's read_file on a PNG: the deck's
    own screenshot, on the family tour's first turn), and the client then replays that tool result
    in every later request of the conversation. The next model need not take it: measured on
    hr-test 2026-10-03, one conversation, seven of fourteen families — an aggregator's Anthropic
    translation refuses the part ("tool_result.content.1: Input tag 'image_url' … does not match"),
    Moonshot refuses the shape ("did not match any variant of untagged enum
    ChatCompletionRequestToolMessageContent"), and OpenRouter has "No endpoints found that support
    image input" for llama, hunyuan and nemotron. So one screenshot ended the conversation for every
    model after the one that took it. Applied only after a provider refuses, for that model on that
    route: a model that takes the image keeps it."""
    try:
        obj = json.loads(body)
        changed = False
        for m in obj.get("messages") or []:
            if not (isinstance(m, dict) and m.get("role") == "tool" and isinstance(m.get("content"), list)):
                continue
            parts = [p for p in m["content"] if isinstance(p, dict)]
            if not any(p.get("type") not in ("text", None) for p in parts):
                continue
            m["content"] = "\n".join((p.get("text") or "") if p.get("type") in ("text", None)
                                     else _IMAGE_PLACEHOLDER for p in parts)
            changed = True
        if changed:
            return json.dumps(obj, separators=(",", ":")).encode()
    except Exception:  # noqa: BLE001 — a body we cannot parse is a body we must not alter
        pass
    return body


_EMPTY_CALL_ID = re.compile(rb'"(?:tool_call_)?id"\s*:\s*""')


def _repair_tool_call_ids(body: bytes, dedupe: bool = False) -> bytes:
    """A chat-completions body in which every tool call has an id of its own and every tool message
    names the call it answers.

    Two shapes a conversation inherits from a model that wrote them and a later, stricter provider
    refuses — both measured on the family tour, hr-test 2026-10-03, and both end the conversation
    for every such provider from then on:
      an EMPTY id. One family's stream carried tool calls with `"id": ""`; the client stored and
        replayed them, and Mistral and StepFun answered `tool messages must include a non-empty
        string tool_call_id` (grok, two of fourteen families).
      a DUPLICATE id inside one assistant message (parallel calls a provider numbered alike):
        Mistral, `Duplicate tool call id in assistant message` (kilo, one of fourteen).
    An empty id is never valid, so it is filled whenever one is present. Duplicates are renamed only
    when `dedupe` is set (after a provider says so): tool messages are matched to calls in order, the
    order every client writes them in."""
    try:
        obj = json.loads(body)
        msgs = obj.get("messages")
        if not isinstance(msgs, list):
            return body
        changed = False
        owed: list[tuple[str, str]] = []     # (the id as the client wrote it, the id it has now), in call order
        for mi, m in enumerate(msgs):
            if not isinstance(m, dict):
                continue
            if m.get("role") == "assistant" and isinstance(m.get("tool_calls"), list):
                owed, seen = [], set()
                for ci, c in enumerate(m["tool_calls"]):
                    if not isinstance(c, dict):
                        continue
                    old = c.get("id") if isinstance(c.get("id"), str) else ""
                    new = old
                    if not old or (dedupe and old in seen):
                        new = f"call_hr_{mi}_{ci}"
                        c["id"] = new
                        changed = True
                    seen.add(new)
                    owed.append((old, new))
            elif m.get("role") == "tool":
                tid = m.get("tool_call_id") if isinstance(m.get("tool_call_id"), str) else ""
                hit = next((i for i, (old, _) in enumerate(owed) if old == tid), None)
                if hit is not None:
                    _, new = owed.pop(hit)
                    if new != tid:
                        m["tool_call_id"] = new
                        changed = True
        if changed:
            return json.dumps(obj, separators=(",", ":")).encode()
    except Exception:  # noqa: BLE001 — a body we cannot parse is a body we must not alter
        pass
    return body


def _image_in_tool_result_refused(code: int, data: bytes) -> bool:
    """Whether a provider's refusal is about an image it was handed (see _tool_images_as_text)."""
    low = data.lower()
    return code in (400, 404, 415, 422) and (b"image" in low or b"toolmessagecontent" in low)


def _stringify_assistant_content(body: bytes) -> bytes:
    """Assistant-role message content: array-of-parts -> plain string, in one chat-completions body.

    The tool-role twin above, one role over. OpenAI accepts both shapes and the OpenHands SDK sends
    the array form for every assistant turn it replays, which Vercel's mistral endpoint refuses —
    and refuses MISLEADINGLY: `400 Assistant message must have either content or tool_calls, but
    not none.` about a message whose content is right there. Isolated against the live endpoint
    (2026-09-18): the identical request answers 200 with `content: "M1"` and 400 with
    `content: [{"type": "text", "text": "M1"}]`.

    It only bites once a conversation HAS an assistant turn, so a first turn passes and every one
    after it fails — which is exactly how it presented, four of five scenarios on
    vercel|openhands|mistral-medium-3.5. Text parts are all an assistant message carries here, so
    the flatten is lossless; applied only after a provider says exactly that."""
    try:
        obj = json.loads(body)
        changed = False
        for m in obj.get("messages") or []:
            if (isinstance(m, dict) and m.get("role") == "assistant"
                    and isinstance(m.get("content"), list)):
                m["content"] = "".join(p.get("text", "") for p in m["content"]
                                       if isinstance(p, dict))
                changed = True
        if changed:
            return json.dumps(obj, separators=(",", ":")).encode()
    except Exception:  # noqa: BLE001 — a body we cannot parse is a body we must not alter
        pass
    return body


_EFFORT_SHAPE_REFUSED_RE = re.compile(rb"is not supported for this model\. Use .{0,80}adaptive", re.S)


def _effort_shape_refused(data: bytes) -> bool:
    """Whether a chat-completions request's `reasoning_effort` came back as Anthropic's refusal of
    the legacy thinking block: '"thinking.type: enabled" is not supported for this model. Use
    "thinking.type: adaptive" and "output_config.effort"'. The harness sent effort the OpenAI way
    (OpenHands sends `reasoning_effort: high` for every model, and its SDK already treats Claude 5
    as adaptive); the aggregator's chat-completions translation made it the block Claude 5, 4.7 and
    4.8 refuse (TokenRouter, measured on hr-test 0.25.13, 2026-09-28)."""
    return bool(_EFFORT_SHAPE_REFUSED_RE.search(data or b""))


def _set_reasoning_effort_none(body: bytes) -> bytes:
    """Set `reasoning_effort: "none"` in one chat-completions body.

    OpenAI's gpt-5.6 family refuses function tools on /v1/chat/completions unless
    reasoning_effort is 'none', and says so verbatim ("Function tools with reasoning_effort are
    not supported ... set reasoning_effort to 'none'" — surfaced live through LLMTR 2026-08-27).
    Applied only on that complaint, and remembered per (route, model) — never route-wide,
    because other models on the same aggregator reject the parameter outright."""
    try:
        obj = json.loads(body)
        if isinstance(obj, dict) and obj.get("reasoning_effort") != "none":
            obj["reasoning_effort"] = "none"
            return json.dumps(obj, separators=(",", ":")).encode()
    except Exception:  # noqa: BLE001 — a body we cannot parse is a body we must not alter
        pass
    return body


def _drop_stream_options(body: bytes) -> bytes:
    """Remove `stream_options` from one chat-completions body.

    Spec-legal and honored by most models, but LLMTR's openai/gpt-5.x upstream 400s any
    streaming request carrying it (isolated live 2026-08-27: the identical body succeeds the
    moment stream_options goes; every other model there accepts it). The error is the generic
    'The model provider rejected the request', so there is nothing to pattern-match — the relay
    instead retries a 400 once without the field, and keeps doing so for the route only when
    that retry is what made it work. Cost: streamed responses stop carrying usage totals."""
    try:
        obj = json.loads(body)
        if isinstance(obj, dict) and "stream_options" in obj:
            del obj["stream_options"]
            return json.dumps(obj, separators=(",", ":")).encode()
    except Exception:  # noqa: BLE001 — a body we cannot parse is a body we must not alter
        pass
    return body


def _request_stream_usage(body: bytes) -> bytes:
    """Ask for the usage chunk on a streamed chat-completions body that does not ask for it.

    OpenAI-shaped endpoints report usage on a stream only when the request carries
    `stream_options: {"include_usage": true}`, and a client that leaves it out gets a turn the
    relay cannot count. CheetahClaws's `custom/` client is one (3.5.88, stream_openai_compat sends
    model, messages, stream, tools, tool_choice and max_tokens, nothing else), and its session file
    carries no usage the runner can use. Set only on the routes that ask for it, and only when the
    body streams and names no stream_options of its own; a provider that refuses the field meets
    the relay's existing one-time retry without it (_drop_stream_options), which then sticks."""
    try:
        obj = json.loads(body)
        if isinstance(obj, dict) and obj.get("stream") is True and "stream_options" not in obj:
            obj["stream_options"] = {"include_usage": True}
            return json.dumps(obj, separators=(",", ":")).encode()
    except Exception:  # noqa: BLE001 — a body we cannot parse is a body we must not alter
        pass
    return body


def _rename_max_tokens(body: bytes) -> bytes:
    """max_tokens -> max_completion_tokens in one chat-completions body.

    OpenAI deprecated max_tokens for its reasoning models and Azure ENFORCES that: a gpt-5.x
    deployment answers 400 'Unsupported parameter: max_tokens is not supported with this model.
    Use max_completion_tokens instead.' (captured live 2026-08-27, opencode x custom-Azure).
    Applied only after a provider says exactly that — aggregators that still take max_tokens
    never see a renamed request."""
    try:
        obj = json.loads(body)
        if isinstance(obj, dict) and "max_tokens" in obj and "max_completion_tokens" not in obj:
            obj["max_completion_tokens"] = obj.pop("max_tokens")
            return json.dumps(obj, separators=(",", ":")).encode()
    except Exception:  # noqa: BLE001 — a body we cannot parse is a body we must not alter
        pass
    return body


def _pop_json_path(obj, path: str) -> bool:
    """Remove the value at a dotted path; -> True if anything was removed.

    A numeric segment ('tools.0.custom.x') strips the leaf from EVERY element of that list,
    not just the named index: the provider complains about the first offending entry, but a
    client that sends the field sends it on all of them (dsh puts eager_input_streaming on
    every tool — measured live), and stripping one per round trip never converges."""
    def walk(node, parts) -> bool:
        if not parts:
            return False
        head, rest = parts[0], parts[1:]
        if isinstance(node, list):
            if head.isdigit() and not rest:
                try:
                    del node[int(head)]
                    return True
                except IndexError:
                    return False
            hit = False
            for item in node:
                hit = walk(item, rest if head.isdigit() else parts) or hit
            return hit
        if not isinstance(node, dict):
            return False
        if not rest:
            if head in node:
                del node[head]
                return True
            return False
        if head in node:
            return walk(node[head], rest)
        # A segment that is not a real key is the validator's UNION DISCRIMINATOR leaking into
        # the path: Bedrock reports tools.0.custom.eager_input_streaming for a tool whose JSON
        # has no "custom" wrapper at all (measured live). Skip the phantom segment and keep
        # walking at the same node.
        return walk(node, rest)
    return walk(obj, path.split("."))


def _aws_eventstream_frames(resp):
    """Yield (headers, payload) per AWS eventstream frame, from a streaming HTTP response.

    Frame: [4B total len][4B headers len][4B prelude CRC][headers][payload][4B message CRC],
    big-endian; header entries are {1B name len, name, 1B type, value}. Bedrock only sends
    string-typed (7) headers, so anything else conservatively ends header parsing for that
    frame. CRCs are skipped on purpose: TLS already guarantees integrity end-to-end, and a
    stdlib-only parser that verifies CRC32 buys nothing but code."""
    import struct
    buf = b""
    while True:
        # read1, for the reason _forward reads that way: `read(65536)` waits for 64 KB or the end
        # of the stream, so an answer shorter than that reached the client all at once at the end.
        chunk = resp.read1(65536)
        buf += chunk
        while len(buf) >= 16:
            total = struct.unpack(">I", buf[:4])[0]
            if len(buf) < total:
                break
            hlen = struct.unpack(">I", buf[4:8])[0]
            raw = buf[12:12 + hlen]
            payload = buf[12 + hlen:total - 4]
            buf = buf[total:]
            headers = {}
            i = 0
            while i + 2 <= len(raw):
                nlen = raw[i]; i += 1
                name = raw[i:i + nlen].decode("utf-8", "replace"); i += nlen
                if i >= len(raw) or raw[i] != 7:   # not a string header: bail for this frame
                    break
                i += 1
                vlen = struct.unpack(">H", raw[i:i + 2])[0]; i += 2
                headers[name] = raw[i:i + vlen].decode("utf-8", "replace"); i += vlen
            yield headers, payload
        if not chunk:
            return


_GOOGLE_UNKNOWN_RE = re.compile(r'Unknown name \\?"([A-Za-z_][A-Za-z0-9_]*)\\?"(?! at \')')


def _google_unknown_field(refused: bytes) -> str:
    """The top-level request field Google's OpenAI-compatible endpoint refused as unknown, or "".
    Google names one field per 400 ("Unknown name \"store\": Cannot find field."); a field named
    inside an object ("at 'tools[0].function'") is not one the relay drops."""
    text = refused.decode("utf-8", "replace") if isinstance(refused, (bytes, bytearray)) else str(refused)
    if "Cannot find field" not in text:
        return ""
    m = _GOOGLE_UNKNOWN_RE.search(text)
    return m.group(1) if m else ""


# Gemini 3 requires each replayed tool call's thought signature: Google's OpenAI-compatible endpoint
# streams it on every function call (tool_calls[].extra_content.google.thought_signature) and refuses
# the next request without it, 400 "Function call is missing a thought_signature in functionCall
# parts" (measured 2026-09-06 on the artifact turn of pi, dsh, qwen and opencode). OpenAI-shaped
# clients drop extra_content when they rebuild the assistant message; in owner trust this relay is
# the only thing between the harness and the provider, so it remembers each signature under its
# tool call id as the answer streams past and puts it back on the replay. A call it never saw gets
# Google's sentinel, which skips the check instead of failing the turn. The broker does the same
# for brokered traffic.
_GOOGLE_SIG_SKIP = "skip_thought_signature_validator"
_GOOGLE_HOST = "generativelanguage.googleapis.com"


# The relay's route carries no provider, only the upstream: a Gemini channel is known by its host.
# TokenRouter serves Google's native API under its own root, and the hosted HarnessRouter service
# (HR_HOSTED_BASE, the same knob the gateway reads) fronts TokenRouter's channel for Gemini.
_STRICT_GEMINI_HOSTS = tuple(h for h in (
    "api.tokenrouter.com",
    urllib.parse.urlsplit(os.environ.get("HR_HOSTED_BASE", "https://api.harnessrouter.ai")).netloc) if h)


def _gemini_channel(base: str) -> bool:
    """Whether `base` is a provider that serves Google's native API under its own root."""
    return any(h in base for h in _STRICT_GEMINI_HOSTS)
# ── Gemini function declarations through a strict channel ────────────────────────────────
# Google's native API validates function declarations against its own Schema (type, format,
# description, nullable, enum, properties, required, items, min/max, anyOf and a few more) and
# refuses anything else: "Unknown name \"$schema\" at 'tools[0].function_declarations[0].parameters'",
# "Unknown name \"exclusiveMinimum\"", "schema didn't specify the schema type field". Google's own
# OpenAI-compatible endpoint, OpenRouter and Vercel normalise a harness's JSON-schema declarations
# before they reach it; TokenRouter's Gemini channels forward them as sent, so the first turn of a
# task on opencode ($schema) and cline (exclusiveMinimum, a property without type) failed on the
# ids those channels serve natively, gemini-3.8-flash for one (measured 2026-09-06, the platform
# column). Until TokenRouter normalises them itself, this relay does, for that channel only.
_GEMINI_SCHEMA_KEYS = {"type", "format", "title", "description", "nullable", "enum", "maxItems", "minItems",
                       "properties", "required", "minProperties", "maxProperties", "minLength", "maxLength",
                       "pattern", "example", "anyOf", "propertyOrdering", "default", "items", "minimum", "maximum"}


def _gemini_schema(node):
    """One JSON schema node as Google's function-declaration validator accepts it: only the keys it
    names, `oneOf` as `anyOf`, `const` as a one-value enum, an exclusive bound as the bound, a type
    list as one type plus nullable, a type on every node (inferred from its shape when left out),
    items on every array, and `required` limited to properties that exist."""
    if not isinstance(node, dict):
        return node
    out: dict = {}
    for k, v in node.items():
        if k == "oneOf" and isinstance(v, list):
            out.setdefault("anyOf", [_gemini_schema(x) for x in v])
        elif k == "const":
            out["enum"] = [v]
        elif k == "exclusiveMinimum" and isinstance(v, (int, float)) and not isinstance(v, bool):
            out.setdefault("minimum", v)
        elif k == "exclusiveMaximum" and isinstance(v, (int, float)) and not isinstance(v, bool):
            out.setdefault("maximum", v)
        elif k not in _GEMINI_SCHEMA_KEYS:
            continue
        elif k == "properties" and isinstance(v, dict):
            out[k] = {pk: _gemini_schema(pv) for pk, pv in v.items()}
        elif k == "items":
            out[k] = _gemini_schema(v) if isinstance(v, dict) else (_gemini_schema(v[0]) if isinstance(v, list) and v else {"type": "string"})
        elif k == "anyOf" and isinstance(v, list):
            out[k] = [_gemini_schema(x) for x in v]
        else:
            out[k] = v
    t = out.get("type")
    if isinstance(t, list):
        non_null = [x for x in t if x != "null"]
        out["type"] = non_null[0] if non_null else "string"
        if "null" in t:
            out["nullable"] = True
    if isinstance(out.get("anyOf"), list):
        # No anyOf leaves this relay: one channel refuses an anyOf node without a type ("schema
        # didn't specify the schema type field", gemini-3.5-flash) and another refuses one with
        # anything beside it ("schema specified other fields alongside any_of", gemini-3.6-flash,
        # both measured 2026-09-06 on TokenRouter). The null member becomes `nullable`; a choice of
        # constants becomes one enum; any other choice becomes its first member under the node's
        # own description, which is what the model reads.
        members = [m for m in out.pop("anyOf") if isinstance(m, dict) and m.get("type") != "null"]
        if len(members) < len(node.get("anyOf") or []):
            out["nullable"] = True
        if members and all("enum" in m and "properties" not in m and "items" not in m for m in members):
            out = {**members[0], **out, "enum": [x for m in members for x in m["enum"]]}
            out.setdefault("type", "string")
        elif members:
            out = {**members[0], **out}
            out.setdefault("type", members[0].get("type") or "string")
    if isinstance(out.get("enum"), list) and None in out["enum"]:
        # A nullable enum spelled the JSON-schema way ({"type": ["string", "null"], "enum": [..., null]},
        # grok's todo_write status) is refused whole: "Enum values must share one supported primitive
        # type" (gemini-3.5-flash-lite through Vercel, 2026-09-27). The null member is `nullable`.
        out["enum"] = [x for x in out["enum"] if x is not None]
        out["nullable"] = True
        if not out["enum"]:
            out.pop("enum")
    if "type" not in out and "anyOf" not in out:
        out["type"] = "object" if "properties" in out else ("array" if "items" in out else "string")
    if out.get("type") == "array" and "items" not in out:
        out["items"] = {"type": "string"}
    if out.get("type") == "object" and not out.get("properties"):
        out.pop("properties", None)                 # an empty properties object is refused too
        out.pop("required", None)
    elif isinstance(out.get("required"), list) and isinstance(out.get("properties"), dict):
        req = [r for r in out["required"] if r in out["properties"]]
        if req:
            out["required"] = req
        else:
            out.pop("required")
    return out


def _with_gemini_schemas(body: bytes) -> bytes:
    """The chat request with every tool's parameters normalised for Google's validator; a tool
    that declares no parameter loses the empty declaration. A body without tools is untouched."""
    if b'"tools"' not in body:
        return body
    try:
        doc = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return body
    if not isinstance(doc, dict) or not isinstance(doc.get("tools"), list):
        return body
    changed = False
    for tool in doc["tools"]:
        fn = tool.get("function") if isinstance(tool, dict) else None
        if not isinstance(fn, dict) or not isinstance(fn.get("parameters"), dict):
            continue
        params = _gemini_schema(fn["parameters"])
        if params.get("type") == "object" and not params.get("properties"):
            fn.pop("parameters")
        else:
            fn["parameters"] = params
        changed = True
    return json.dumps(doc).encode() if changed else body


# ── Tool declarations through Anthropic's validator ──────────────────────────────────────────────
# Anthropic's Messages API refuses a tool whose input_schema has a combinator at the TOP level:
# `tools.14.custom.input_schema: input_schema does not support oneOf, allOf, or anyOf at the top
# level` (measured 2026-09-28 on claude-haiku-4.5 and claude-sonnet-4.6 through Vercel's gateway,
# which translates an OpenAI tool into Anthropic's shape). A nested combinator is fine; only the
# root is refused.
#
# Grok Build's `use_tool` declares exactly that: a root `oneOf` over its three call forms (inline
# arguments, an arguments file, a document), each branch a `required` set plus a `not` forbidding the
# other forms' keys. So EVERY claude id the grok base offers failed its first turn — the request was
# refused before inference, on all five scenarios. The sanitiser below is the Anthropic counterpart
# of _gemini_schema: one provider's validator, repaired in flight for every client, rather than a
# catalog pruned of ten models the harness can otherwise drive.
_ANTHROPIC_COMBINATORS = ("oneOf", "anyOf", "allOf")


def _anthropic_tool_schema(node):
    """One tool's parameter schema as Anthropic's input_schema validator accepts it: no combinator at
    the root. The branches' own constraints cannot survive flattening — a root schema can express
    "these properties" but not "exactly one of these shapes" — so what is kept is everything a
    caller needs to build a valid call, and what is dropped is the exclusivity:

      properties  the union of the root's and every branch's, root first (a branch that redeclares a
                  property does not override the root's description of it)
      required    what every call needs whichever shape it takes: the root's own list, every
                  allOf branch's (all of those apply), and of oneOf/anyOf only what EVERY branch
                  requires, because a key one alternative alone demands is not required of the call
                  the model actually makes. For grok's `use_tool` that is the empty set, so
                  `required` goes: two of its three forms do not take `tool_name`.
      the rest    every other root key except the combinators and the `not` that rode with them

    The exclusivity then lives where the model reads it anyway: `use_tool`'s own description says
    "Supply exactly one form", and the tool itself validates its arguments (measured: a call missing
    a required field comes back as a tool_result error, not a crash). Nested combinators are
    untouched — Anthropic accepts those, and a property's own anyOf is how a nullable field is
    spelled."""
    if not isinstance(node, dict):
        return node
    branches = [b for k in _ANTHROPIC_COMBINATORS for b in (node.get(k) or [])
                if isinstance(b, dict)]
    if not branches:
        return node
    out = {k: v for k, v in node.items() if k not in _ANTHROPIC_COMBINATORS and k != "not"}
    props = dict(out.get("properties") or {})
    for b in branches:
        for name, spec in (b.get("properties") or {}).items():
            props.setdefault(name, spec)
    if props:
        out["properties"] = props
    def _req(b):
        return [r for r in b["required"] if isinstance(r, str)] if isinstance(b.get("required"), list) else []
    required = _req(node)
    for b in node.get("allOf") or []:
        if isinstance(b, dict):
            required += [r for r in _req(b) if r not in required]
    for k in ("oneOf", "anyOf"):
        alts = [set(_req(b)) for b in (node.get(k) or []) if isinstance(b, dict)]
        if alts:
            required += [r for r in sorted(set.intersection(*alts)) if r not in required]
    if required:
        out["required"] = required
    else:
        out.pop("required", None)
    out.setdefault("type", "object")
    return out


def _with_anthropic_schemas(body: bytes) -> bytes:
    """The request with every tool's parameter schema flattened for Anthropic's validator. Both wire
    shapes are handled, because both reach Anthropic: an OpenAI chat/completions body, whose
    `tools[].function.parameters` an aggregator translates into `input_schema`, and an Anthropic
    Messages body, which carries `tools[].input_schema` itself. A body without tools is untouched,
    and a body no tool of which has a root combinator comes back byte-identical."""
    if b'"tools"' not in body or not any(c.encode() in body for c in _ANTHROPIC_COMBINATORS):
        return body
    try:
        doc = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return body
    if not isinstance(doc, dict) or not isinstance(doc.get("tools"), list):
        return body
    changed = False
    for tool in doc["tools"]:
        if not isinstance(tool, dict):
            continue
        fn = tool.get("function") if isinstance(tool.get("function"), dict) else None
        holder, key = (fn, "parameters") if fn is not None else (tool, "input_schema")
        schema = holder.get(key)
        if not isinstance(schema, dict):
            continue
        flat = _anthropic_tool_schema(schema)
        if flat is not schema and flat != schema:
            holder[key] = flat
            changed = True
    return json.dumps(doc).encode() if changed else body


def _anthropic_family(model: str) -> bool:
    """Whether this model id is served by Anthropic's own API, whoever fronts it. The vendor prefix
    an aggregator adds (anthropic/claude-haiku-4.5) and the bare id both count; `claude` is the one
    token every id in the family carries, as `gemini` is for Google's."""
    return "claude" in (model or "").lower()

def _google_signatures_in(doc: dict) -> list[tuple[str, str]]:
    """The (tool call id, thought signature) pairs one answer (a chunk or a whole message) carries."""
    found: list[tuple[str, str]] = []
    for ch in doc.get("choices") or []:
        if not isinstance(ch, dict):
            continue
        holder = ch.get("delta") if isinstance(ch.get("delta"), dict) else ch.get("message")
        if not isinstance(holder, dict):
            continue
        for tc in holder.get("tool_calls") or []:
            if not isinstance(tc, dict):
                continue
            ec = tc.get("extra_content")
            sig = ((ec or {}).get("google") or {}).get("thought_signature") if isinstance(ec, dict) else None
            cid = tc.get("id")
            if isinstance(sig, str) and sig and isinstance(cid, str) and cid:
                found.append((cid, sig))
    return found


def _google_signatures_in_line(line: bytes) -> list[tuple[str, str]]:
    """The signatures one SSE line carries; a line without one costs a substring check."""
    if not line.startswith(b"data:") or b"thought_signature" not in line:
        return []
    try:
        doc = json.loads(line[5:].strip())
    except ValueError:
        return []
    return _google_signatures_in(doc) if isinstance(doc, dict) else []


def _google_with_signatures(body: bytes, sigs: dict) -> bytes:
    """The request with every replayed assistant tool call carrying a thought signature: the one
    this relay saw on the answer, else Google's sentinel. A body without tool calls is untouched."""
    if b"tool_calls" not in body:
        return body
    try:
        doc = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return body
    if not isinstance(doc, dict) or not isinstance(doc.get("messages"), list):
        return body
    changed = False
    for msg in doc["messages"]:
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls") or []:
            if not isinstance(tc, dict):
                continue
            ec = tc.get("extra_content")
            if isinstance(ec, dict) and isinstance(ec.get("google"), dict) and ec["google"].get("thought_signature"):
                continue
            cid = str(tc.get("id") or "")
            tc["extra_content"] = {"google": {"thought_signature": sigs.get(cid) or _GOOGLE_SIG_SKIP}}
            changed = True
    return json.dumps(doc).encode() if changed else body


def _drop_top_level_field(body: bytes, field: str) -> bytes:
    """The JSON request without one top-level field; anything else is returned as it came."""
    try:
        doc = json.loads(body or b"")
    except (ValueError, UnicodeDecodeError):
        return body
    if not isinstance(doc, dict) or field not in doc:
        return body
    doc.pop(field)
    return json.dumps(doc).encode()


_SERVED_MODEL_RE = re.compile(rb'"model"\s*:\s*"([^"]{1,200})"')


def _served_model_in(data: bytes) -> str:
    """The `model` an OpenAI- or Anthropic-shaped answer names, read off the bytes as they pass the
    relay: the first "model":"…" in a JSON body or an SSE line. This is the provider's own statement
    of what it ran, available for every backend that rides the relay, whether or not the CLI
    reports one (goose never does; cline and qwen do not either)."""
    m = _SERVED_MODEL_RE.search(data)
    return m.group(1).decode("utf-8", "replace") if m else ""


# The hyphen is not cosmetic: Vercel's AI Gateway reports a declined request as "content-filter"
# while OpenAI's own spelling is "content_filter" (measured 2026-10-01 against ai-gateway.vercel.sh
# on anthropic/claude-fable-5.1 and anthropic/claude-opus-5 — two SSE events, no content, no
# reasoning, finish_reason "content-filter"). A pattern that admitted only the underscore matched
# nothing on that channel, so the one check that turns a provider's refusal into a stated reason was
# never evaluated there — the person got whatever the CLI made of an empty answer instead
# (agentzero: "Agent stopped after 5 consecutive unusable model responses", its own loop guard).
# _finish_reason_in normalises both spellings to the underscore one, so callers compare one form.
_FINISH_RE = re.compile(rb'"finish_reason"\s*:\s*"([a-z_-]{1,40})"')


def _usage_fields(u) -> dict:
    """One provider usage object, in the runner's contract: {input_tokens (FRESH input only),
    output_tokens, cache_read_tokens, cache_write_tokens}, only the fields the object carries.

    Three shapes pass the relay. OpenAI chat: prompt_tokens is GROSS (cache hits included) with the
    cached part under prompt_tokens_details.cached_tokens, so it is netted here the way
    _norm_token_usage nets codex's. Anthropic messages: input_tokens is already net, the cache
    counters are their own fields. Gemini's usageMetadata: promptTokenCount is gross with
    cachedContentTokenCount the cached part."""
    if not isinstance(u, dict):
        return {}

    def n(v) -> int:
        try:
            return max(int(v or 0), 0)
        except (TypeError, ValueError):
            return 0

    if "prompt_tokens" in u or "completion_tokens" in u:
        det = u.get("prompt_tokens_details")
        cached = n(det.get("cached_tokens")) if isinstance(det, dict) else 0
        return {"input_tokens": max(n(u.get("prompt_tokens")) - cached, 0),
                "output_tokens": n(u.get("completion_tokens")), "cache_read_tokens": cached}
    if "input_tokens" in u or "output_tokens" in u:
        out = {}
        for src, dst in (("input_tokens", "input_tokens"), ("output_tokens", "output_tokens"),
                         ("cache_read_input_tokens", "cache_read_tokens"),
                         ("cache_creation_input_tokens", "cache_write_tokens")):
            if u.get(src) is not None:
                out[dst] = n(u[src])
        return out
    if "promptTokenCount" in u or "candidatesTokenCount" in u:
        cached = n(u.get("cachedContentTokenCount"))
        return {"input_tokens": max(n(u.get("promptTokenCount")) - cached, 0),
                "output_tokens": n(u.get("candidatesTokenCount")), "cache_read_tokens": cached}
    return {}


def _usage_in_doc(doc) -> dict:
    """The usage a response document or stream event carries, if any. Anthropic's stream puts the
    input side on message_start (under message.usage) and the output side on message_delta, so a
    call's usage is the union of what its events said, later values replacing earlier ones."""
    if not isinstance(doc, dict):
        return {}
    for u in (doc.get("usage"), doc.get("usageMetadata"),
              (doc.get("message") or {}).get("usage") if isinstance(doc.get("message"), dict) else None):
        got = _usage_fields(u)
        if got:
            return got
    return {}


def _usage_in_sse_line(line: bytes) -> dict:
    """One SSE line as it passes the relay → the usage it carries, {} for anything else."""
    if not line.startswith(b"data:") or b"sage" not in line:
        return {}
    try:
        return _usage_in_doc(json.loads(line[5:].strip()))
    except ValueError:
        return {}


def _usage_add(flags: dict, call_usage: dict) -> None:
    """Fold one call's usage into the route's running total: a turn is many provider calls."""
    if not call_usage:
        return
    total = flags.setdefault("usage", {})
    for k, v in call_usage.items():
        total[k] = int(total.get(k, 0)) + int(v)


def _model_metadata_with_context_length(data: bytes) -> bytes:
    """A model listing (GET /models or /models/<id>) with the window also under `context_length`.

    Vercel's model bodies name the window `context_window`. hermes reads this loopback relay as
    a local server and takes `max_model_len`, `context_length` or `max_tokens` from the
    per-model body, in that order, so on Vercel it read the OUTPUT cap as the window (32,768 for
    deepseek-v4.1-flash, below its 64K minimum, and the turn never started; measured 2026-09-13).
    The window travels under the name every client reads; a body that already carries it, or
    is not a model listing, goes back unchanged."""
    try:
        doc = json.loads(data)
    except ValueError:
        return data
    entries = doc.get("data") if isinstance(doc, dict) and isinstance(doc.get("data"), list) else [doc]
    changed = False
    for e in entries:
        if isinstance(e, dict) and "context_length" not in e and isinstance(e.get("context_window"), int):
            e["context_length"] = e["context_window"]
            changed = True
    return json.dumps(doc).encode() if changed else data


def _finish_reason_in(data: bytes) -> str:
    """The last finish_reason an OpenAI-shaped answer names in these bytes ("" when none)."""
    hits = _FINISH_RE.findall(data)
    return hits[-1].decode().replace("-", "_") if hits else ""


def _relay_last_finish(env: dict) -> str:
    """The finish_reason of the LAST provider answer on this turn's route, as the relay saw it.
    A "content_filter" here is the provider declining the request; a CLI that reports it as an
    empty answer (goose: "The model returned an empty response") has hidden a failure."""
    for v in env.values():
        if isinstance(v, str) and v.startswith("hr-relay-"):
            route = _HERMES_RELAY["routes"].get(v)
            if route:
                # normalised the way _finish_reason_in normalises, so a caller compares one
                # spelling whoever wrote the flag (Vercel says "content-filter", OpenAI
                # "content_filter")
                return str((route[2] or {}).get("last_finish") or "").replace("-", "_")
    return ""


def _relay_served_model(env: dict) -> str:
    """What the relay saw the provider serve on this turn's route, "" when the turn did not ride
    the relay or nothing answered yet. The route is found by the placeholder bearer the CLI was
    handed, whichever variable the backend keeps it in.

    ONE relay token per env is the invariant this rests on — the first one found is taken as the
    turn's chat route. It holds for every backend that reaches here: only _hermes_prepare_env
    registers a second route (the auxiliary vision model, HR_VISION_API_KEY), and hermes runs on
    _run_hermes_bg, which does not call this. A backend that ever hands its CLI two relay bearers
    must distinguish them here first: reading the vision route would stamp the image model as the
    turn's served model, which rule 2 of docs/harness-verification.md reads as a substitution —
    a finding invented out of nothing."""
    for v in env.values():
        if isinstance(v, str) and v.startswith("hr-relay-"):
            route = _HERMES_RELAY["routes"].get(v)
            if route:
                return str((route[2] or {}).get("served_model") or "")
    return ""


def _fill_relay_usage(ev: dict, env: dict) -> None:
    """The result's usage from the relay when the CLI reported none, and ALSO when the CLI's count
    has no cache split while the provider's does: a CLI that sums the provider's input and cache
    reads into one number bills every cached token at the full input rate (goose and OpenHands
    on Claude, read at list price in a customer's cost sheet, 2026-09-30). The provider's own
    statement is the one that prices."""
    relay = _relay_usage(env)
    if not relay:
        return
    own = ev.get("usage")
    cached = ("cache_read_tokens", "cache_write_tokens")
    if not own or (any(relay.get(k) for k in cached) and not any((own or {}).get(k) for k in cached)):
        ev["usage"] = relay


def _relay_usage(env: dict) -> dict:
    """The tokens the provider reported on this turn's route, summed over its calls; {} when the
    turn did not ride the relay or nothing carried usage. Found by the placeholder bearer, exactly
    as _relay_served_model finds the served model, and subject to the same one-route invariant.

    This is the usage of every backend whose own stream reports none (kimi, aider): the provider's
    statement of what it counted, read off the bytes as they pass, rather than a number the CLI
    estimated or nothing at all. A backend that reports its own usage keeps it; this only fills a
    result event that arrived empty."""
    for v in env.values():
        if isinstance(v, str) and v.startswith("hr-relay-"):
            route = _HERMES_RELAY["routes"].get(v)
            if route:
                u = (route[2] or {}).get("usage")
                return dict(u) if isinstance(u, dict) and u else {}
    return {}


class _HermesRelayHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _upstream(self) -> tuple[str, str] | None:
        tok = (self.headers.get("authorization") or "").removeprefix("Bearer ").strip()
        if not tok:
            tok = (self.headers.get("x-goog-api-key") or "").strip()     # gemini-cli's header for its key
        if not tok:
            tok = (self.headers.get("x-api-key") or "").strip()          # an Anthropic Messages client's header
        return _HERMES_RELAY["routes"].get(tok)

    def _forward(self, body: bytes | None) -> None:
        route = self._upstream()
        if not route:
            self.send_response(401)
            data = b'{"error": "unknown relay token"}'
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        base, key, flags = route
        tail = self.path.removeprefix("/v1") if self.path.startswith("/v1/") else self.path
        drop = {"host", "content-length", "authorization", "x-goog-api-key", "x-api-key", "connection",
                "accept-encoding", "transfer-encoding"}
        headers = {k: v for k, v in self.headers.items() if k.lower() not in drop}
        headers["authorization"] = f"Bearer {key}"
        headers.setdefault("accept", "*/*")
        if tail.split("?", 1)[0] == "/messages" and not flags.get("bedrock_anthropic"):
            # An Anthropic Messages call (goose's and hermes's anthropic providers, litellm's
            # anthropic/ route, the claude CLI on a custom endpoint). Anthropic reads the key from
            # x-api-key and nothing else; an aggregator's Messages surface reads a bearer, so both
            # travel except to Anthropic itself. The body gets cache breakpoints when the client set
            # none: on the OpenAI-compatible surface these clients used before 2026-09-30 nothing
            # could be cached, and a benchmark paid 6 to 8 times the Claude Code price for the
            # same task on goose and OpenHands.
            headers["x-api-key"] = key
            if (urllib.parse.urlsplit(base).hostname or "").lower() == "api.anthropic.com":
                headers.pop("authorization", None)
            if body is not None:
                body = _with_anthropic_cache(body)
                headers["content-length"] = str(len(body))
        if flags.get("google_native"):
            # Google's native API on a provider that serves it (TokenRouter: models/google/<id>:
            # generateContent, measured 2026-09-07). The CLI asks for the canonical id, which its tables
            # and the served-model check key by; the relay names it the way the provider does on the
            # path, as the hosted broker does, and the key rides x-goog-api-key.
            m, nm = str(flags.get("model") or ""), str(flags.get("native_model") or "")
            if m and nm and nm != m:
                tail = tail.replace(f"/models/{m}:", f"/models/{nm}:", 1)
            headers["x-goog-api-key"] = key
        # Compare the PATH only: anthropic clients append query strings (claude-code sends
        # /v1/messages?beta=true on streaming requests), and matching the raw tail let those
        # fall through to a generic forward against a host with no such route.
        if (flags.get("bedrock_anthropic") and tail.split("?", 1)[0] == "/messages"
                and body is not None):
            self._bedrock_anthropic(base, key, body)
            return
        try:
            _body_model = json.loads(body or b"{}").get("model") or ""
        except Exception:  # noqa: BLE001
            _body_model = ""
        if body is not None and self.path.endswith("/chat/completions"):
            body = _normalize_openai_chat_body(body)
            if flags.get("stream_usage"):
                body = _request_stream_usage(body)
            if flags.get("rename_max_tokens"):
                body = _rename_max_tokens(body)
            if flags.get("stringify_tool_content"):
                body = _stringify_tool_content(body)
            if flags.get(f"tool_images_as_text:{_body_model}"):
                body = _tool_images_as_text(body)
            if flags.get("dedupe_tool_call_ids") or _EMPTY_CALL_ID.search(body):
                body = _repair_tool_call_ids(body, dedupe=bool(flags.get("dedupe_tool_call_ids")))
            if flags.get("stringify_assistant_content"):
                body = _stringify_assistant_content(body)
            if flags.get("drop_stream_options"):
                body = _drop_stream_options(body)
            if flags.get(f"reasoning_effort_none:{_body_model}"):
                body = _set_reasoning_effort_none(body)
            if flags.get(f"drop_reasoning_effort:{_body_model}"):
                body = _drop_top_level_field(body, "reasoning_effort")
            for field in flags.get("drop_fields", ()):
                body = _drop_top_level_field(body, field)
            headers["content-length"] = str(len(body))
        google = _GOOGLE_HOST in base or bool(flags.get("thought_signature"))
        if google and body is not None and self.path.endswith("/chat/completions"):
            body = _google_with_signatures(body, flags.setdefault("google_sigs", {}))
            headers["content-length"] = str(len(body))
        if ((_gemini_channel(base) or flags.get("gemini_schemas")) and "gemini" in str(_body_model).lower()
                and body is not None and self.path.endswith("/chat/completions")):
            # TokenRouter's Gemini channels hand a harness's JSON-schema tool declarations to Google's
            # validator as sent; the broker does the same normalisation for brokered traffic
            body = _with_gemini_schemas(body)
            headers["content-length"] = str(len(body))
        if body is not None:
            # A tool whose parameter schema has a combinator at its root is refused by Anthropic
            # ("input_schema does not support oneOf, allOf, or anyOf at the top level") AND by
            # OpenAI ("schema must have type 'object' and not have 'oneOf'/'anyOf'/'allOf'/… at the
            # top level": grok's `use_tool` on gpt-6.1-sol through TokenRouter, hr-test 2026-10-03,
            # where every turn of that pair died before inference), on their own APIs and through
            # the aggregators that pass the schema on. No provider needs one there, so the shape is
            # flattened for every model: a test by family repaired one vendor and left the other.
            fixed = _with_anthropic_schemas(body)
            if fixed != body:
                body = fixed
                headers["content-length"] = str(len(body))
        resp = None
        tried_slim = False
        dropped_once = False
        for attempt in (0, 1, 2):
            req = urllib.request.Request(base.rstrip("/") + tail, data=body,
                                         method=self.command, headers=headers)
            try:
                resp = urllib.request.urlopen(req, timeout=HR_RELAY_UPSTREAM_TIMEOUT_S)
                if attempt > 0 and tried_slim:
                    # the blind no-stream_options retry is part of what made this route work
                    flags["drop_stream_options"] = True
                break
            except urllib.error.HTTPError as e:
                data = e.read()
                renamed = _rename_max_tokens(body) if body is not None else None
                if (attempt < 2 and e.code == 400 and b"max_completion_tokens" in data
                        and renamed is not None and renamed != body):
                    # The provider named the fix itself; apply it, remember it for this route.
                    flags["rename_max_tokens"] = True
                    body = renamed
                    headers["content-length"] = str(len(body))
                    continue
                stringified = _stringify_tool_content(body) if body is not None else None
                if (attempt < 2 and e.code == 400 and b"content must be a string" in data
                        and stringified is not None and stringified != body):
                    flags["stringify_tool_content"] = True
                    body = stringified
                    headers["content-length"] = str(len(body))
                    continue
                if (attempt < 2 and e.code in (400, 422) and b"uplicate tool call id" in data
                        and body is not None and not flags.get("dedupe_tool_call_ids")):
                    unique = _repair_tool_call_ids(body, dedupe=True)
                    if unique != body:
                        flags["dedupe_tool_call_ids"] = True
                        body = unique
                        headers["content-length"] = str(len(body))
                        print(f"[relay] provider refused a duplicate tool call id for model={_body_model}; "
                              f"sent again with ids of their own", flush=True)
                        continue
                imageless = _tool_images_as_text(body) if body is not None else None
                if (attempt < 2 and _image_in_tool_result_refused(e.code, data)
                        and imageless is not None and imageless != body):
                    # this model takes no image in a tool result; remember it for this model only
                    flags[f"tool_images_as_text:{_body_model}"] = True
                    body = imageless
                    headers["content-length"] = str(len(body))
                    print(f"[relay] provider refused an image in a tool result for model={_body_model}; "
                          f"sent again with the image named in words", flush=True)
                    continue
                assistant = _stringify_assistant_content(body) if body is not None else None
                if (attempt < 2 and e.code == 400
                        and b"Assistant message must have either content" in data
                        and assistant is not None and assistant != body):
                    flags["stringify_assistant_content"] = True
                    body = assistant
                    headers["content-length"] = str(len(body))
                    continue
                effort = _set_reasoning_effort_none(body) if body is not None else None
                if (attempt < 2 and e.code == 400 and b"reasoning_effort" in data
                        and b"'none'" in data and effort is not None and effort != body):
                    # the provider named the fix itself; remember it for this model only
                    flags[f"reasoning_effort_none:{_body_model}"] = True
                    body = effort
                    headers["content-length"] = str(len(body))
                    continue
                if (attempt < 2 and e.code == 400 and body is not None and b"reasoning_effort" in body
                        and _effort_shape_refused(data)):
                    # An aggregator that turns `reasoning_effort` into Anthropic's legacy thinking
                    # block is refused by the newer Claude models. The effort goes, for this model on
                    # this route, and the request goes again at the model's own default; the broker
                    # does the same for brokered traffic.
                    flags[f"drop_reasoning_effort:{_body_model}"] = True
                    body = _drop_top_level_field(body, "reasoning_effort")
                    headers["content-length"] = str(len(body))
                    print(f"[relay] provider refused reasoning_effort's thinking shape for model={_body_model}; "
                          f"sent again without it", flush=True)
                    continue
                flat = _with_anthropic_schemas(body) if body is not None else None
                if (attempt < 2 and e.code == 400 and b"input_schema" in data
                        and any(c.encode() in data for c in _ANTHROPIC_COMBINATORS)
                        and flat is not None and flat != body):
                    # The provider named the fix itself ("input_schema does not support oneOf, allOf,
                    # or anyOf at the top level"), so a channel this relay does not recognise as
                    # Anthropic — or a model id that does not carry the family's name — is repaired on
                    # the complaint and remembered, the max_completion_tokens pattern. This bounds the
                    # shape to ONE extra request even where the proactive pass above does not fire.
                    flags["anthropic_schemas"] = True
                    body = flat
                    headers["content-length"] = str(len(body))
                    continue
                if e.code in (400, 422):
                    # The provider's own words, kept here for every provider: a harness shows a
                    # refusal as "400 (no body)" (Gemini CLI) or cuts it to a few dozen characters
                    # (CheetahClaws), and a matrix row that fails must carry the reproduced text
                    # (docs/harness-verification.md). A llama-3.3-70b turn on a compacted history
                    # was refused as "malformed" on 2026-09-27 with the reason cut off.
                    print(f"[relay] {'google' if google else 'provider'} refused {tail} model={_body_model} "
                          f"status={e.code}: {data[:300]!r}", flush=True)
                if (attempt < 2 and e.code == 400 and b"thought_signature" in data
                        and not flags.get("thought_signature") and body is not None):
                    # a Gemini 3 endpoint this relay did not recognise as Google names the need itself
                    flags["thought_signature"] = True
                    google = True
                    body = _google_with_signatures(body, flags.setdefault("google_sigs", {}))
                    headers["content-length"] = str(len(body))
                    continue
                unknown = _google_unknown_field(data) if e.code == 400 else ""
                dropped = _drop_top_level_field(body, unknown) if (unknown and body is not None) else None
                if attempt < 2 and dropped is not None and dropped != body:
                    # Google's OpenAI-compatible endpoint refuses any field it does not know (pi and
                    # dsh send OpenAI's optional store and seed; measured 2026-09-06 on
                    # gemini-3.6-flash). The refusal names the field: drop it, remember it for the
                    # route, send again. The broker does the same for brokered traffic; in owner
                    # trust the relay is the only thing between the harness and the provider.
                    flags["drop_fields"] = tuple(flags.get("drop_fields", ())) + (unknown,)
                    body = dropped
                    headers["content-length"] = str(len(body))
                    continue
                slim = _drop_stream_options(body) if body is not None else None
                if attempt < 2 and e.code == 400 and slim is not None and slim != body:
                    tried_slim = True
                    # Generic 400 with stream_options aboard: blind single retry without it
                    # (LLMTR's gpt-5.x upstream names nothing better). Sticks only if it works.
                    body = slim
                    headers["content-length"] = str(len(body))
                    continue
                # pass provider errors through verbatim
                self.send_response(e.code)
                self.send_header("content-type", e.headers.get("content-type") or "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError) as e:
                # THE PROVIDER DID NOT ANSWER: the connection was refused, dropped mid-request, or
                # went silent past HR_RELAY_UPSTREAM_TIMEOUT_S. Only HTTPError was caught here, so
                # such a failure escaped _forward, ThreadingHTTPServer printed a traceback and closed
                # the socket WITH NO RESPONSE AT ALL — the CLI was left holding a dead connection and
                # the turn hung until something above killed it. Measured on a support-matrix
                # instance on 2026-09-29: ten of these, `http.client.RemoteDisconnected: Remote end
                # closed connection without response`, two inside the family tour's failing window.
                # A refusal the person can read beats a socket that simply stops.
                reason = f"{type(e).__name__}: {e}"[:300]
                if not dropped_once and attempt < 2 and isinstance(e, (http.client.RemoteDisconnected, ConnectionResetError)):
                    dropped_once = True
                    # A connection dropped before any byte of the answer is the one transport failure
                    # worth one more go: it costs nothing upstream (nothing was generated) and an
                    # aggregator sheds load this way. A timeout is NOT retried — the provider may be
                    # generating, and a second request would be a second bill.
                    print(f"[relay] upstream dropped the connection for {tail} model={_body_model}; "
                          "sending again, once", flush=True)
                    continue
                print(f"[relay] upstream did not answer {tail} model={_body_model}: {reason}", flush=True)
                payload = json.dumps({"error": {
                    "message": f"the provider did not answer: {reason}",
                    "type": "upstream_unavailable",
                    "code": "upstream_unavailable"}}).encode()
                # 504 for a silence we timed out on, 502 for a connection that failed or was dropped.
                status = 504 if isinstance(e, TimeoutError) or "timed out" in str(e) else 502
                try:
                    self.send_response(status)
                    self.send_header("content-type", "application/json")
                    self.send_header("content-length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except OSError:
                    pass          # the client hung up first; nothing left to tell
                return
        ctype = resp.headers.get("content-type") or ""
        # the bytes go through untouched; a Google answer's tool-call signatures are read as they pass
        sigs = flags.setdefault("google_sigs", {}) if google else None
        if "text/event-stream" in ctype:
            self.send_response(resp.status)
            self.send_header("content-type", ctype)
            self.send_header("transfer-encoding", "chunked")
            self.end_headers()
            pending = b""
            carry = b""      # tail of the previous chunk, so a split "model":"…" is still seen
            fcarry = b""     # tail of the previous chunk, for the finish_reason field
            call_usage: dict = {}   # what this call's events said about tokens, unioned

            def _stopped(why: str) -> None:
                # The answer began and then stopped: the provider went silent past the socket's
                # timeout, dropped the connection mid-stream, or kept the socket warm and sent no
                # event. The status line is long gone, so the reason travels as the stream's own
                # error event (the shape of the API being spoken) and the chunked body is then left
                # UNTERMINATED with the connection closed. Ending it with the zero chunk would hand
                # the client a well-formed, complete answer that merely lacks its last events —
                # measured at a stub: one event, a stall, and the client read 200 with nothing wrong.
                print(f"[relay] upstream stopped mid-answer on {tail} model={_body_model}: {why}",
                      flush=True)
                msg = f"the provider stopped answering mid-stream: {why}"
                if "/messages" in tail:
                    ev = "event: error\ndata: " + json.dumps(
                        {"type": "error", "error": {"type": "api_error", "message": msg}}) + "\n\n"
                else:
                    ev = "data: " + json.dumps({"error": {
                        "message": msg, "type": "upstream_unavailable",
                        "code": "upstream_unavailable"}}) + "\n\n"
                call_usage.update(_usage_in_sse_line(pending.strip()))
                _usage_add(flags, call_usage)
                try:
                    raw = ev.encode()
                    self.wfile.write(f"{len(raw):x}\r\n".encode() + raw + b"\r\n")
                    self.wfile.flush()
                except OSError:
                    pass
                self.close_connection = True

            # When the provider last sent an EVENT (or the answer began). Bytes are not the measure:
            # an aggregator trickles comment lines (": OPENROUTER PROCESSING") for as long as its own
            # upstream says nothing, so the socket never goes quiet and its timeout never fires.
            last_event = time.monotonic()
            while True:
                try:
                    # read1: what has arrived, as it arrives. `read(4096)` on an HTTP response waits
                    # for 4096 BYTES or the end of the stream, so a short first event sat here until
                    # the rest of the answer filled the block (an answer under 4 KB reached the client
                    # all at once, at its end), and a provider that sent a little and then stalled,
                    # or only kept the connection warm, delivered nothing at all and was never timed
                    # out. Both reproduced at a stub (runner/tests/test_relay_upstream_failure.py);
                    # neither has been caught on a live provider, where the long turns looked at so
                    # far were a model streaming reasoning without end, which is an answer arriving
                    # and is rightly left alone here.
                    chunk = resp.read1(65536)
                except (http.client.HTTPException, TimeoutError, OSError) as e:
                    _stopped(f"{type(e).__name__}: {e}"[:300])
                    return
                if not chunk:
                    break
                if not flags.get("served_model"):
                    sm = _served_model_in(carry + chunk)
                    if sm:
                        flags["served_model"] = sm
                    else:
                        # A read boundary can fall inside the field, and a miss here is silent:
                        # served_model stays empty and the turn is simply not substitution-checked.
                        # 256 bytes covers the longest id this can carry (the regex caps at 200).
                        # The tail of the STREAM, not of the last read: a read returns whatever has
                        # arrived, so the field can span three of them.
                        carry = (carry + chunk)[-256:]
                # the last finish_reason, across read boundaries (64 bytes covers the field)
                fr = _finish_reason_in(fcarry + chunk)
                if fr:
                    flags["last_finish"] = fr
                fcarry = (fcarry + chunk)[-64:]
                # usage (and Google's tool-call signatures) live on whole SSE lines, so the
                # stream is line-buffered as it passes; the bytes still go through untouched
                pending += chunk
                # a route that rewrites usage forwards whole lines (as rewritten) instead of the
                # raw read, so a rewrite never straddles two reads
                out_lines = [] if flags.get("usage_no_nulls") else None
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    if out_lines is not None:
                        out_lines.append(_usage_without_nulls(line) + b"\n")
                    line = line.strip()
                    if line and not line.startswith(b":"):
                        last_event = time.monotonic()     # an event's line; a comment is not one
                    call_usage.update(_usage_in_sse_line(line))
                    if sigs is not None:
                        for cid, sig in _google_signatures_in_line(line):
                            sigs[cid] = sig
                if out_lines is not None:
                    chunk = b"".join(out_lines)
                if chunk:
                    self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
                    self.wfile.flush()
                if time.monotonic() - last_event > HR_RELAY_UPSTREAM_TIMEOUT_S:
                    # No event for the whole of the relay's wait, only lines that keep the connection
                    # open: the same silence the socket's timeout reports, by another door.
                    _stopped(f"no data for {HR_RELAY_UPSTREAM_TIMEOUT_S:g} s, only keep-alive lines")
                    return
            call_usage.update(_usage_in_sse_line(pending.strip()))
            _usage_add(flags, call_usage)
            if flags.get("usage_no_nulls") and pending:
                tail_bytes = _usage_without_nulls(pending)      # a last line with no newline after it
                self.wfile.write(f"{len(tail_bytes):x}\r\n".encode() + tail_bytes + b"\r\n")
            self.wfile.write(b"0\r\n\r\n")
        else:
            try:
                data = resp.read()
            except (http.client.HTTPException, TimeoutError, OSError) as e:
                # The body stopped arriving. Nothing has been sent to the client yet (the status
                # line is only written below), so this is answered as the provider failure it is
                # rather than as the provider's own 200 with an empty body.
                why = f"{type(e).__name__}: {e}"[:300]
                print(f"[relay] upstream stopped mid-body on {tail} model={_body_model}: {why}",
                      flush=True)
                payload = json.dumps({"error": {
                    "message": f"the provider stopped answering mid-body: {why}",
                    "type": "upstream_unavailable", "code": "upstream_unavailable"}}).encode()
                try:
                    self.send_response(504 if isinstance(e, TimeoutError) or "timed out" in str(e) else 502)
                    self.send_header("content-type", "application/json")
                    self.send_header("content-length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except OSError:
                    pass
                return
            self.send_response(resp.status)
            self.send_header("content-type", ctype)
            if not flags.get("served_model"):
                sm = _served_model_in(data[:65536])
                if sm:
                    flags["served_model"] = sm
            fr = _finish_reason_in(data[-65536:])
            if fr:
                flags["last_finish"] = fr
            if body is not None and b"sage" in data:
                try:
                    _usage_add(flags, _usage_in_doc(json.loads(data)))
                except ValueError:
                    pass
            if body is None and "/models" in tail.split("?", 1)[0]:
                data = _model_metadata_with_context_length(data)
            if flags.get("usage_no_nulls"):
                data = _usage_without_nulls(data)
            if sigs is not None and b"thought_signature" in data:
                try:
                    doc = json.loads(data)
                except ValueError:
                    doc = None
                if isinstance(doc, dict):
                    sigs.update(_google_signatures_in(doc))
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    def _bedrock_anthropic(self, origin: str, key: str, body: bytes) -> None:
        """Anthropic Messages -> Bedrock InvokeModel, both directions.

        Bedrock has NO bearer-auth /v1/messages surface (the path answers HTTP 200 wrapping
        UnknownOperationException - measured 2026-08-27). Its InvokeModel API takes the SAME
        Anthropic Messages body with exactly three differences, all applied here: the model
        moves from the body into the URL path, anthropic_version moves into the body, and
        stream becomes a different endpoint whose reply is AWS binary eventstream framing -
        each frame's payload is {"bytes": base64(<anthropic SSE event JSON>)}, re-emitted
        here as ordinary SSE so every Messages client streams unchanged."""
        model, stream, obj = "", False, {}
        try:
            obj = json.loads(body)
            model = str(obj.pop("model", "") or "")
            stream = bool(obj.pop("stream", False))
            obj["anthropic_version"] = "bedrock-2023-05-31"
        except Exception:  # noqa: BLE001
            model = ""
        if not model:
            data = (b'{"type":"error","error":{"type":"invalid_request_error",'
                    b'"message":"bedrock adapter: request body needs a model"}}')
            self.send_response(400)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        op = "invoke-with-response-stream" if stream else "invoke"
        url = f"{origin.rstrip('/')}/model/{urllib.parse.quote(model, safe='')}/{op}"
        # Bedrock's InvokeModel schema trails the first-party Messages API: fields the CLI
        # sends for newer features get '<field>: Extra inputs are not permitted' (measured:
        # claude-code's context_management, 2026-08-27). Strip exactly the field the provider
        # names and retry — a fixed strip-list would silently rot as either side moves.
        resp = None
        for _ in range(4):
            req = urllib.request.Request(url, data=json.dumps(obj).encode(), method="POST",
                                         headers={"authorization": f"Bearer {key}",
                                                  "content-type": "application/json",
                                                  "accept": "*/*"})
            try:
                resp = urllib.request.urlopen(req, timeout=600)
                break
            except urllib.error.HTTPError as e:
                data = e.read()
                m = (re.search(rb'"?([\w.]+)"?: Extra inputs are not permitted', data)
                     if e.code == 400 else None)
                # The complaint names a dotted path (tools.0.custom.eager_input_streaming was
                # measured live from dsh's client); walk it — ints are list indices — and pop
                # the leaf. A path that no longer resolves means we already stripped it and the
                # provider is complaining about something else: fall through and surface it.
                if m and _pop_json_path(obj, m.group(1).decode()):
                    continue
                self.send_response(e.code)
                self.send_header("content-type", e.headers.get("content-type") or "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
        if not stream:
            data = resp.read()   # already an Anthropic message response, verbatim
            self.send_response(resp.status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("transfer-encoding", "chunked")
        self.end_headers()

        def emit(block: bytes) -> None:
            self.wfile.write(f"{len(block):x}\r\n".encode() + block + b"\r\n")
            self.wfile.flush()

        for headers, payload in _aws_eventstream_frames(resp):
            try:
                ev_raw = base64.b64decode(json.loads(payload)["bytes"])
                ev_type = json.loads(ev_raw).get("type", "message")
            except Exception:  # noqa: BLE001 - an exception frame, or a shape we don't know
                err = json.dumps({"type": "error", "error": {
                    "type": headers.get(":exception-type", "api_error"),
                    "message": payload.decode("utf-8", "replace")[:300]}}).encode()
                emit(b"event: error\ndata: " + err + b"\n\n")
                continue
            emit(b"event: " + ev_type.encode() + b"\ndata: " + ev_raw + b"\n\n")
        self.wfile.write(b"0\r\n\r\n")

    def do_POST(self):  # noqa: N802
        self._forward(self.rfile.read(int(self.headers.get("content-length") or 0)))

    def do_GET(self):   # noqa: N802 — model listings and the like
        self._forward(None)

    def log_message(self, *a):  # diagnostics belong on stderr, never stdout
        pass


def _bedrock_anthropic_route(origin: str, api_key: str) -> tuple[str, str]:
    """Register a Bedrock-Anthropic adapter route; -> (relay base_url, placeholder bearer)."""
    with _HERMES_RELAY["lock"]:
        if _HERMES_RELAY["server"] is None:
            srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _HermesRelayHandler)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            _HERMES_RELAY["server"], _HERMES_RELAY["port"] = srv, srv.server_address[1]
        tok = "hr-relay-" + uuid.uuid4().hex
        _HERMES_RELAY["routes"][tok] = (origin, api_key, {"bedrock_anthropic": True})
    return f"http://127.0.0.1:{_HERMES_RELAY['port']}/v1", tok


def _adapt_custom_auth(auth):
    """An anthropic-format custom integration pointing at bedrock-runtime rides the adapter.

    Every anthropic-format backend path converges on POST <base>/v1/messages (claude's CLI and
    pi's client append it themselves; dsh chains its own relay into ours), so rewriting the auth
    ONCE here covers all of them - and the real Bedrock key stays in this process, the same
    credential win the hermes and dsh relays already have."""
    if auth.api_format != "anthropic" or not (auth.base_url and auth.api_key):
        return auth
    host = urllib.parse.urlsplit(auth.base_url).hostname or ""
    if not (host.startswith("bedrock-runtime.") and host.endswith(".amazonaws.com")):
        return auth
    base, tok = _bedrock_anthropic_route(f"https://{host}", auth.api_key)
    return auth.model_copy(update={"base_url": base, "api_key": tok})


# How long the relay waits for the provider on ONE upstream call, and how long an answer already
# begun may go without an EVENT (it is the socket's timeout: connect, the wait for the status line,
# and every later read; and, in a stream, the longest run of keep-alive lines with no event between
# them, since those keep the socket from ever timing out). It must stay BELOW the turn cap above it, or a provider that accepts a
# request and then goes silent is indistinguishable from a working turn: the cap fires first and the
# turn is cancelled with no served model, no tool call and no reason. The default is the 600 s this
# relay has always waited, far under MAX_TURN_SECONDS: a reasoning model answering a non-streaming
# call can be silent for minutes and that is an answer on its way, not a failure. An instance whose
# own cap is shorter sets this lower: the support-matrix suite caps a turn at 600 s, so the instance
# it measures runs with HR_RELAY_UPSTREAM_TIMEOUT_S=180 (seven of fourteen tour families were "not
# settled in 600s" on 2026-09-29 with the two equal). A value that is not a positive number is ignored.
def _relay_upstream_timeout() -> float:
    try:
        v = float(os.environ.get("HR_RELAY_UPSTREAM_TIMEOUT_S") or 600)
    except ValueError:
        return 600.0
    return v if v > 0 else 600.0


HR_RELAY_UPSTREAM_TIMEOUT_S = _relay_upstream_timeout()


_USAGE_NULL_COUNT = re.compile(rb'("[a-z_]*_tokens"\s*:\s*)null')


def _usage_without_nulls(line: bytes) -> bytes:
    """One answer line (an SSE event or a whole body) with every null token count inside its usage
    written as 0. Moonshot's kimi-k3 through TokenRouter ends a stream with
    `"prompt_tokens_details":{"audio_tokens":null,"cached_tokens":0}`; Grok Build 1.0.41 parses the
    counts as u32 and failed the whole turn on it AFTER the answer had arrived ("serialization
    error: invalid type: null, expected u32", hr-test 2026-10-03, every kimi-k3 turn). A count that
    is absent and a count of none are the same number. `"usage":null` itself is left alone (clients
    read it as "not yet"), as is everything before the usage key."""
    i = line.find(b'"usage"')
    if i < 0 or b"null" not in line[i:]:
        return line
    return line[:i] + _USAGE_NULL_COUNT.sub(rb"\g<1>0", line[i:])


def _relay_base_with_version(base_url: str) -> str:
    """A relay base ends with /v1 unless it is an AWS host or already names an API version."""
    base = (base_url or "").rstrip("/")
    if not base or ".amazonaws.com" in base or re.search(r"/v\d+[a-z]*(/|$)", base):   # /v1, /v1beta/openai
        return base
    return base + "/v1"


def _gemini_relay_route(host_root: str, api_key: str, model: str = "", native_model: str = "") -> tuple[str, str]:
    """Register one gemini turn's upstream for Google's native API on a provider that serves it: the
    connection's base without its /v1 version segment (TokenRouter's host root, the hosted service's
    /v1/provider door), since the CLI appends /v1beta/models/<id>:... itself and names the model the
    way the gateway resolved it through the connection's vendor table (google/<id> on TokenRouter,
    the canonical id on the hosted door). The same shape as the hosted broker's native path: re-rooted
    at the provider's base, the key in x-goog-api-key. → (GOOGLE_GEMINI_BASE_URL, placeholder key)."""
    with _HERMES_RELAY["lock"]:
        if _HERMES_RELAY["server"] is None:
            srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _HermesRelayHandler)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            _HERMES_RELAY["server"], _HERMES_RELAY["port"] = srv, srv.server_address[1]
        tok = "hr-relay-" + uuid.uuid4().hex
        _HERMES_RELAY["routes"][tok] = (host_root.rstrip("/"), api_key,
                                        {"google_native": True, "model": model, "native_model": native_model})
    return f"http://127.0.0.1:{_HERMES_RELAY['port']}/v1", tok


def _hermes_relay_route(base_url: str, api_key: str, drop_fields: tuple[str, ...] = (),
                        stream_usage: bool = False, gemini_schemas: bool = False,
                        usage_no_nulls: bool = False) -> tuple[str, str]:
    """Register one turn's upstream; → (relay base_url, placeholder bearer for the CLI).

    `drop_fields` names top-level request fields this route's client sends on its own initiative and
    the harness never asked for; they are removed before the provider sees them (the same list the
    relay grows by itself when a provider names an unknown field). `stream_usage` asks the provider
    for a streamed call's usage when the client does not (_request_stream_usage). `gemini_schemas`
    normalises a gemini model's tool declarations on this route whatever the channel (see
    _build_grok for the one client that needs it). `usage_no_nulls` rewrites a null token count in an
    answer's usage to 0 for a client whose parser takes only a number there (_usage_without_nulls)."""
    with _HERMES_RELAY["lock"]:
        if _HERMES_RELAY["server"] is None:
            srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _HermesRelayHandler)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            _HERMES_RELAY["server"], _HERMES_RELAY["port"] = srv, srv.server_address[1]
        tok = "hr-relay-" + uuid.uuid4().hex
        # The relay joins the client's resource ("/chat/completions", "/messages") onto this base,
        # so the base must carry its "/v1" the way every aggregator's does. A direct Anthropic key
        # stored with the catalog's former default https://api.anthropic.com sent cline and qwen to
        # https://api.anthropic.com/chat/completions, a 404 with no body (2026-09-06 support
        # matrix; Anthropic's OpenAI-compatible surface lives under /v1). Bedrock keeps its host
        # (its own path is built in _bedrock_anthropic).
        _HERMES_RELAY["routes"][tok] = (_relay_base_with_version(base_url), api_key,
                                        {"rename_max_tokens": False, "drop_fields": tuple(drop_fields),
                                         "stream_usage": bool(stream_usage),
                                         "gemini_schemas": bool(gemini_schemas),
                                         "usage_no_nulls": bool(usage_no_nulls)})
    return f"http://127.0.0.1:{_HERMES_RELAY['port']}/v1", tok


def _hermes_prepare_env(provider: str | None, auth: Auth, cwd: str, env: dict,
                        model: str = "", max_turns: int | None = None,
                        mcp_servers: list[dict] | None = None,
                        vision_auth: dict | None = None) -> list[str]:
    """Point HERMES_HOME inside the checkpointed workspace home (CODEX_HOME precedent) so the
    conversation state (state.db) survives sandbox recycling, and inject provider creds as env.
    Writes config.yaml fresh each turn (harness config is the source of truth, like the agent doc).
    The model/provider MUST be in config.yaml, not only flags: the chat path's first-run guard
    treats a default-model config as 'unconfigured' and exits into the setup wizard (verified on
    0.19.0 — bedrock bearer creds alone don't satisfy it). The -z/-m flags still take precedence."""
    p = (provider or "bedrock").lower()
    if str(auth.api_format or "").strip().lower() == "anthropic":
        p = "anthropic"             # a custom endpoint in the Messages format is hermes's anthropic provider
    if p not in HERMES_PROVIDERS:
        raise HTTPException(400, f"unknown hermes provider '{p}' (one of {sorted(HERMES_PROVIDERS)})")
    hermes_home = pathlib.Path(env.get("HOME") or cwd) / ".hermes"
    hermes_home.mkdir(parents=True, exist_ok=True)
    env["HERMES_HOME"] = str(hermes_home)
    # Seal runtime lazy-installs (hermes pip-installs undeclared deps at first use — its own
    # hosted image does the same): everything the shipped features need is baked into the image.
    env["HERMES_DISABLE_LAZY_INSTALLS"] = "1"
    cfg: dict = {"model": {"provider": p, "default": model}}
    api_mode = _hermes_api_mode(p, model)
    if api_mode:
        cfg["model"]["api_mode"] = api_mode
    if p == "bedrock":
        cfg["bedrock"] = {"region": auth.aws_region or "us-east-1"}
    if max_turns:
        # hermes 0.19.0 has no --max-turns CLI flag; agent.max_turns in config.yaml is the knob.
        cfg["agent"] = {"max_turns": int(max_turns)}
    if vision_auth and vision_auth.get("model"):
        # hermes asks its image questions separately from the conversation (vision_analyze, the
        # browser tools) and, left alone, asks the model the harness writes with. That made a
        # capability we list as supported depend on which model the operator picked: one that is
        # slow or unwilling with images returns "Request timed out" after the tool's 120 second
        # ceiling, and the agent re-renders and asks again. The gateway resolved which integration
        # on this instance answers image questions (any integration, not only the turn's) and
        # hands it over whole: provider, model, endpoint, credential. hermes' auxiliary router
        # takes exactly that per task, so only the question about the picture goes elsewhere.
        #
        # The credential takes the same road as the chat one. For an OpenAI-compatible endpoint
        # that is the loopback relay: the CLI sees a placeholder bearer, never the key.
        vp = str(vision_auth.get("provider") or "").lower()
        vision: dict = {"provider": vp, "model": str(vision_auth["model"])}
        vkey, vbase = vision_auth.get("api_key") or "", vision_auth.get("base_url") or ""
        if vp == "openai-api" and vkey and vbase:
            vbase, vkey = _hermes_relay_route(vbase, vkey)
        if vbase:
            vision["base_url"] = vbase
        if vkey:
            # Through the environment, not the file: config.yaml is checkpointed with the
            # workspace and a credential in it would travel in the tarball.
            env["HR_VISION_API_KEY"] = vkey
            vision["key_env"] = "HR_VISION_API_KEY"
        cfg["auxiliary"] = {"vision": vision}
    # Provider credentials as env — the CLI resolves them at call time.
    if p == "anthropic":
        if auth.api_key and auth.base_url:
            # Through the relay, as every other hermes route: the real key stays here, the served
            # model and the provider's own usage (cache reads included) are read as they pass, and
            # the SDK joins /v1/messages onto the relay's origin. hermes sets its own cache
            # breakpoints (anthropic_prompt_cache_policy).
            relay_base, relay_tok = _hermes_relay_route(auth.base_url, auth.api_key)
            env["ANTHROPIC_API_KEY"] = relay_tok
            env["ANTHROPIC_BASE_URL"] = _relay_origin(relay_base)
        elif auth.api_key:
            env["ANTHROPIC_API_KEY"] = auth.api_key
    elif p == "azure-foundry":  # Azure OpenAI (gpt family) — OpenAI-style endpoint + key
        if auth.api_key:
            env["AZURE_FOUNDRY_API_KEY"] = auth.api_key
        if auth.base_url:
            env["AZURE_FOUNDRY_BASE_URL"] = auth.base_url
    elif p == "openrouter":  # OpenRouter aggregator (vendor/model ids)
        if auth.api_key:
            env["OPENROUTER_API_KEY"] = auth.api_key
        if auth.base_url:
            env["OPENROUTER_BASE_URL"] = auth.base_url
    elif p == "openai-api":  # any OpenAI-compatible endpoint (OpenAI official, TokenRouter, ...)
        if auth.api_key and auth.base_url:
            # Through the loopback relay (see _HermesRelayHandler above): request shapes that
            # are OpenAI-legal but fatal to aggregator translation are repaired before the
            # provider sees them, and the real key never enters the CLI's environment.
            env["OPENAI_BASE_URL"], env["OPENAI_API_KEY"] = _hermes_relay_route(
                auth.base_url, auth.api_key)
        elif auth.api_key:
            env["OPENAI_API_KEY"] = auth.api_key
        elif auth.base_url:
            env["OPENAI_BASE_URL"] = auth.base_url
    else:  # bedrock — bearer-token (Bedrock API key) or the standard AWS credential chain
        region = auth.aws_region or "us-east-1"
        env["AWS_REGION"] = region
        env["AWS_DEFAULT_REGION"] = region
        if auth.aws_bearer_token:
            env["AWS_BEARER_TOKEN_BEDROCK"] = auth.aws_bearer_token
        if auth.aws_access_key_id:
            env["AWS_ACCESS_KEY_ID"] = auth.aws_access_key_id
        if auth.aws_secret_access_key:
            env["AWS_SECRET_ACCESS_KEY"] = auth.aws_secret_access_key
        if auth.aws_session_token:
            env["AWS_SESSION_TOKEN"] = auth.aws_session_token
    mcp = _hermes_mcp_section(mcp_servers)
    if mcp:
        cfg["mcp_servers"] = mcp
        # chat mode JOINS background MCP discovery before the first tool snapshot, bounded by
        # this timeout (default 1.5s — too short for a cold remote connect). The driver runs
        # MCP turns through chat -q precisely for that join; give real servers time to attach.
        cfg["mcp_discovery_timeout"] = 20
    (hermes_home / "config.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))
    return list(mcp)


QWEN_PROVIDERS = {"anthropic", "openai", "azure", "openai-api", "tokenrouter"}


def _qwen_settings(home: pathlib.Path, mcp_servers: list[dict] | None) -> None:
    """~/.qwen/settings.json under the redirected HOME. Only mcpServers is written (gemini-cli
    schema: command/args/env for stdio, url/httpUrl for remote); auth stays in the ENVIRONMENT
    (OPENAI_API_KEY / OPENAI_BASE_URL + --auth-type openai), so unlike pi and opencode no
    credential ever lands on disk for this backend."""
    qdir = home / ".qwen"
    qdir.mkdir(parents=True, exist_ok=True)
    servers: dict = {}
    for i, sv in enumerate(mcp_servers or []):
        if not isinstance(sv, dict):
            continue
        name = _skill_dir_name(sv.get("name") or sv.get("id") or f"server{i}")
        url = (sv.get("url") or "").strip()
        if url:
            # Their schema names the transport by the key: `url` is an SSE endpoint, `httpUrl` a
            # streamable HTTP one; a server declared sse under httpUrl is silently never loaded.
            entry: dict = {"url": url} if str(sv.get("transport") or "").lower() == "sse" else {"httpUrl": url}
            hdrs = _mcp_headers(sv)
            if hdrs:
                entry["headers"] = hdrs
        elif sv.get("command"):
            cmd = sv["command"]
            argv = cmd if isinstance(cmd, list) else [str(cmd)]
            entry = {"command": argv[0], "args": [str(x) for x in argv[1:]] + [str(x) for x in (sv.get("args") or [])]}
            envv = sv.get("env")
            if isinstance(envv, dict) and envv:
                entry["env"] = {str(k): str(v) for k, v in envv.items()}
        else:
            continue
        servers[name] = entry
    cfg: dict = {}
    if servers:
        cfg["mcpServers"] = servers
    (qdir / "settings.json").write_text(json.dumps(cfg, indent=2))


def _build_qwen(provider: str, auth: Auth, model: str, prompt: str, cwd: str, env: dict,
                resume_session_id: str | None = None, mcp_servers: list[dict] | None = None) -> list[str]:
    pr = provider or "openai-api"
    if pr not in QWEN_PROVIDERS:
        raise HTTPException(400, f"unknown qwen provider '{pr}' (one of {sorted(QWEN_PROVIDERS)})")
    if not auth.base_url:
        raise HTTPException(400, "qwen needs a base_url (none configured)")
    if auth.api_key:
        # EVERY qwen turn rides the loopback relay, not just custom endpoints: request shapes
        # strict endpoints refuse are repaired in flight (qwen sends tool-result content as an
        # array of parts, which aggregators 400 with 'content must be a string' — measured live
        # against LLMTR; Azure's gpt-5.x deployments 400 on max_tokens), and the real key never
        # enters the CLI's environment — which matters more here than anywhere, because qwen
        # takes its credential ONLY via env.
        relay_base, relay_tok = _hermes_relay_route(auth.base_url, auth.api_key)
        auth = auth.model_copy(update={"base_url": relay_base, "api_key": relay_tok})
    home = pathlib.Path(cwd) / ".harness" / "home"
    home.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(home)                      # sessions/skills/settings live INSIDE the workspace
    env["OPENAI_API_KEY"] = auth.api_key or ""
    env["OPENAI_BASE_URL"] = auth.base_url
    _qwen_settings(home, mcp_servers)
    cmd = ["qwen", "-p", prompt, "-o", "stream-json", "-m", model,
           # Resume REQUIRES an explicit auth type in non-interactive mode (verified on 0.22.1:
           # without it every -r run dies "No auth type is selected"); fresh runs take it too for
           # one deterministic path.
           "--auth-type", "openai",
           # WITHOUT --yolo a headless run registers NO shell, write or edit tool at all — the
           # default "auto" permission mode simply omits them, and the agent announces "I don't
           # have a shell tool registered" and tries to delegate. Verified both ways on 0.22.1:
           # default init tools lack shell/write/edit; with --yolo they are present, perm mode
           # "yolo", and a real command wrote a file. The sandbox is the trust boundary here, the
           # same rationale as claude --dangerously-skip-permissions, pi --approve and opencode
           # --auto.
           "--yolo"]
    if resume_session_id:
        cmd += ["-r", resume_session_id]
    return cmd


KIMI_PROVIDERS = {"anthropic", "openai", "azure", "openai-api", "tokenrouter"}

# Every built-in tool Kimi Code CLI declares to the model, by the exact name its agent files match.
#
# MEASURED, not read off the docs: the `tools` array of a live 2.0.0 request, captured at a local
# stub with no provider involved. The console offers exactly these as toggles, and
# test_catalog_kimi_tool_paths.py pins _BASE_CATALOG["kimi"]'s tool ids equal to this tuple so the
# catalog can never offer a name the CLI would not recognise (an unknown name in disallowedTools
# "never matches anything", per the agents reference, which would be a toggle that does nothing).
# WebSearch is absent on purpose: it is declared only with a Moonshot search service configured.
_KIMI_TOOLS = ("Agent", "AgentSwarm", "AskUserQuestion", "Bash", "CreateGoal", "CronCreate",
               "CronDelete", "CronList", "Edit", "EnterPlanMode", "ExitPlanMode", "FetchURL",
               "GetGoal", "Glob", "Grep", "Read", "ReadMediaFile", "SetGoalBudget", "Skill",
               "TaskList", "TaskOutput", "TaskStop", "TodoList", "UpdateGoal", "WaitFor", "Write")


# Two request fields Kimi Code CLI sends on its own initiative, captured at a stub on 2.0.0, that no
# person configured and that break models which are fine without them:
#   max_tokens: 131072 on EVERY request, an output budget derived from a Kimi-sized window. OpenAI,
#     Anthropic and Google each refuse the whole request (limits 128000, 128000, 65536), and on a
#     131k-window model the budget alone overflows the context (llama-3.3-70b: "requested about
#     154972 tokens ... 131072 in the output"). There is no knob for it on the openai provider type.
#   reasoning_effort: "high" whenever the MODEL NAME looks like a reasoning model (claude-*), whatever
#     capabilities are declared. TokenRouter turns that into thinking.type.enabled, which the newer
#     Claude models refuse outright ("not supported for this model. Use thinking.type.adaptive"): five
#     ids failed their first turn on it.
# The budget travels under a second name for an OpenAI-named model (gpt-*, o*): the CLI sends
# max_completion_tokens: 131072 there instead, captured at the same stub across ten model families,
# and gpt-5.4-mini refused it exactly as the others refused max_tokens. prompt_cache_key, the one
# other extra it sends, is a caching hint no endpoint here objects to and stays.
# Every other base here sends none of these and the provider's defaults apply; this base now does too.
_KIMI_DROP_FIELDS = ("max_tokens", "max_completion_tokens", "reasoning_effort")


def _kimi_home(ws: pathlib.Path) -> pathlib.Path:
    """KIMI_CODE_HOME for this workspace: config, sessions, logs and mcp.json all land under it
    (env-vars reference). It sits under .harness/home so the sessions travel with the checkpoint
    and a resume survives a recycled sandbox, and so nothing of it shows up as a produced file."""
    return ws / ".harness" / "home" / ".kimi-code"


def _kimi_has_session(home: pathlib.Path, session_id: str) -> bool:
    """Is this conversation in the store? Sessions live at sessions/<workdir key>/<session id>/
    (measured on 2.0.0; the key is `wd_<dirname>_<hash>`), so the id is looked up under any key
    rather than recomputing a hash this code does not own. It matters because `kimi -r <unknown id>`
    is a hard failure on this CLI, exit 1 with `Session "<id>" not found`, where its predecessor
    silently started a new conversation: the runner must not pass an id the store does not hold."""
    sid = (session_id or "").strip()
    if not sid or "/" in sid or sid.startswith("."):
        return False
    return any((home / "sessions").glob(f"*/{sid}"))


def _kimi_agent_file(ws: pathlib.Path, tools_disabled: list[str] | None) -> pathlib.Path | None:
    """A per-session agent file that withholds tools, or None when nothing is disabled.

    An agent file is Markdown with a frontmatter block; `disallowedTools` matches built-in tools by
    exact, case-sensitive name, shapes the tools shown to the model AND is enforced again before
    execution (agents reference), which is what makes tool_enforcement "hard" here. Measured on
    2.0.0: with Bash disallowed and asked for the machine's boot id, the agent called no tool and
    answered that it had no shell. The body is ${base_prompt} so the workspace instructions, skills
    and plugin injections of the default prompt stay in effect."""
    names = [t for t in (tools_disabled or []) if t in _KIMI_TOOLS]
    if not names:
        return None
    path = ws / ".harness" / "kimi-agent.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    # `subagents: []` is part of the policy, not decoration. Measured through the product on 2.0.0:
    # with only Bash disallowed, kimi-k3 answered "I don't have a direct shell tool, but I can
    # dispatch a subagent that does" and called Agent; the built-in coder subagent carries its own
    # tool list, so a withheld tool came back by delegation. With the allowlist empty the Agent tools
    # have nobody to dispatch to and the same prompt answers that it has no shell.
    path.write_text("---\nname: harness\n"
                    "description: The harness agent with its tool policy applied.\n"
                    "disallowedTools:\n" + "".join(f"  - {n}\n" for n in names) +
                    "subagents: []\n"
                    "---\n${base_prompt}\n")
    return path


def _kimi_mcp_config(home: pathlib.Path, mcp_servers: list[dict] | None) -> pathlib.Path:
    """$KIMI_CODE_HOME/mcp.json, the user-level file (the project-level one raises a trust prompt
    for an untrusted folder). Written on EVERY turn, empty included, so a server removed from the
    harness is gone from the next turn instead of lingering in the file.

    Shapes per the MCP reference, each measured on 2.0.0: a `command` entry is stdio (args, env and
    cwd honoured, which is what a plugin launcher needs); a `url` entry with no transport is
    streamable HTTP; a legacy SSE server says `transport: "sse"` explicitly. The harness's declared
    transport decides, never the url's spelling."""
    servers: dict = {}
    for i, sv in enumerate(mcp_servers or []):
        if not isinstance(sv, dict):
            continue
        name = _skill_dir_name(sv.get("name") or sv.get("id") or f"server{i}")
        url = (sv.get("url") or "").strip()
        if url:
            entry: dict = {"url": url}
            if str(sv.get("transport") or "").lower() == "sse":
                entry["transport"] = "sse"
            hdrs = _mcp_headers(sv)
            if hdrs:
                entry["headers"] = hdrs
        elif sv.get("command"):
            cmd = sv["command"]
            argv = cmd if isinstance(cmd, list) else [str(cmd)]
            entry = {"command": argv[0],
                     "args": [str(x) for x in argv[1:]] + [str(x) for x in (sv.get("args") or [])]}
            envv = sv.get("env")
            if isinstance(envv, dict) and envv:
                entry["env"] = {str(k): str(v) for k, v in envv.items()}
            if sv.get("cwd"):
                entry["cwd"] = str(sv["cwd"])
        else:
            continue
        servers[name] = entry
    home.mkdir(parents=True, exist_ok=True)
    path = home / "mcp.json"
    path.write_text(json.dumps({"mcpServers": servers}, indent=2))
    return path


def _build_kimi(provider: str, auth: Auth, model: str, prompt: str, cwd: str, env: dict,
                resume_session_id: str | None = None, mcp_servers: list[dict] | None = None,
                skills_dir: str | None = None, tools_disabled: list[str] | None = None,
                max_turns: int | None = None) -> list[str]:
    """Kimi Code CLI (MoonshotAI/kimi-code, 2.0.0), the successor its vendor moved Kimi CLI to.

    The model is defined from the ENVIRONMENT alone: with KIMI_MODEL_NAME set the CLI synthesises a
    provider in memory and persists nothing (env-vars reference), so no config file is written and
    no credential exists at rest. Measured: after a full session the data home held no trace of the
    key. Every turn rides the loopback relay, the qwen rationale unchanged: the real key never
    enters the CLI's environment, request shapes strict endpoints refuse are repaired in flight,
    and the provider's own "model" passes through for the served-model check."""
    pr = provider or "openai-api"
    if pr not in KIMI_PROVIDERS:
        raise HTTPException(400, f"unknown kimi provider '{pr}' (one of {sorted(KIMI_PROVIDERS)})")
    if not auth.base_url:
        raise HTTPException(400, "kimi needs a base_url (none configured)")
    if auth.api_key:
        relay_base, relay_tok = _hermes_relay_route(auth.base_url, auth.api_key, drop_fields=_KIMI_DROP_FIELDS)
        auth = auth.model_copy(update={"base_url": relay_base, "api_key": relay_tok})
    ws = pathlib.Path(cwd)
    home = _kimi_home(ws)
    home.mkdir(parents=True, exist_ok=True)
    env["KIMI_CODE_HOME"] = str(home)
    env["KIMI_DISABLE_TELEMETRY"] = "1"
    # An agent that replaces its own binary mid-turn is not a pinned backend: the update preflight
    # (check, background install, prompt) is switched off; the image decides the version.
    env["KIMI_CODE_NO_AUTO_UPDATE"] = "1"
    env["KIMI_MODEL_NAME"] = model
    env["KIMI_MODEL_PROVIDER_TYPE"] = "openai"
    env["KIMI_MODEL_BASE_URL"] = auth.base_url
    env["KIMI_MODEL_API_KEY"] = auth.api_key or ""
    env["KIMI_MODEL_MAX_CONTEXT_SIZE"] = str(KIMI_CONTEXT_WINDOW)
    env["NO_COLOR"] = "1"
    # The CLI retries a failing step up to ten times, a provider's flat 400 included: measured, a
    # request a model refuses outright took 143 to 178 s to fail. Three total attempts still rides
    # out a transient error and lets a real refusal reach the person in seconds.
    env["KIMI_LOOP_MAX_ATTEMPTS_PER_STEP"] = "3"
    if max_turns:
        # THE BUDGET. Unset means unlimited on this CLI, and on a slow reasoning model that was
        # hours on its predecessor. Reaching it is loud: exit 1 with loop.max_steps_exceeded.
        env["KIMI_LOOP_MAX_STEPS_PER_TURN"] = str(int(max_turns))
    _kimi_mcp_config(home, mcp_servers)
    # -p runs one prompt without the TUI, with automatic permission (it refuses --yolo/--auto
    # beside it); stream-json is one message per line. The process's cwd is the workspace.
    cmd = ["kimi", "-p", prompt, "--output-format", "stream-json"]
    if resume_session_id and _kimi_has_session(home, resume_session_id):
        cmd += ["-r", resume_session_id]
    else:
        # The agent is bound when a session is created and restored on resume, and the CLI refuses
        # --agent-file beside -r: the tool policy is set on the first turn of a conversation.
        agent_file = _kimi_agent_file(ws, tools_disabled)
        if agent_file is not None:
            cmd += ["--agent-file", str(agent_file)]
    if skills_dir:
        cmd += ["--skills-dir", skills_dir]
    return cmd


# ── minimax (MiniMax Code, `mcode`) ────────────────────────────────────────────────
MINIMAX_PROVIDERS = {"anthropic", "openai", "azure", "openai-api", "tokenrouter"}

# The provider id the runner gives the connection inside MiniMax Code's config. The CLI's model
# selector for a config-defined endpoint is `custom_provider:<id>/<model>`, and that prefix is not
# decoration: measured on 0.5.4, `<id>/<model>` resolves to the "configured_provider" route and the
# turn dies with `Model "hr/…" is not available for the "configured_provider" route` before any
# request (model-availability.ts). Everything after the first "/" is the model id, sent to the
# provider verbatim — `custom_provider:hr/minimax/minimax-m3` reached a stub as
# "model":"minimax/minimax-m3".
_MINIMAX_PROVIDER_ID = "hr"

# The built-in tools this runner can WITHHOLD, by the names the model sees them under. Measured on
# 0.5.4 from the `tools` array of a live request at a stub: read, write, edit, bash, grep, glob,
# todowrite, skill, web_fetch, web_search, task, task_append, task_query, task_output, task_stop,
# website_deploy, update_goal, get_goal (+ mcp__<server>__<tool> per MCP tool).
#   - the first eight are the config's `agents.default.tools` allowlist ids (AGENT_BUILTIN_TOOL_IDS);
#     a tool left out of the list is absent from the request — measured with bash;
#   - `task` (with task_append) is the delegation FEATURE, `features.delegation: false` removes both,
#     and it is withheld with anything else: a subagent carries its own tool list, the hole kimi's
#     agent file had to close the same way;
#   - web_search and website_deploy need a MiniMax account (search and hosting are MiniMax's own
#     services) and are never enabled, so they are not offered; nor are skill, update_goal and
#     get_goal, which have no switch. task_query/task_output/task_stop control background shell
#     commands and go with bash.
# test_catalog_minimax_tools.py pins _BASE_CATALOG["minimax"]'s ids equal to this tuple.
_MINIMAX_TOOLS = ("bash", "read", "write", "edit", "grep", "glob", "todowrite", "web_fetch", "task")
_MINIMAX_BASH_COMPANIONS = ("task_query", "task_output", "task_stop")


def _minimax_home(ws: pathlib.Path) -> pathlib.Path:
    """MINIMAX_DATA_DIR for this workspace: config, the session store (sqlite + transcripts), the
    global AGENTS.md, skills, mcp.json, logs. Under .harness/home so the sessions travel with the
    checkpoint (a resume survives a recycled sandbox) and nothing of it is a produced file. It is
    also the CLI's own default ($HOME/.minimax) under the runner's redirected HOME."""
    return ws / ".harness" / "home" / ".minimax"


def _minimax_has_session(home: pathlib.Path, session_id: str) -> bool:
    """Is this conversation in the store? ASK THE STORE (checklist #10): MiniMax Code keeps sessions
    in `v2/sqlite/runtime-state.sqlite`, table `local_runtime_sessions`, keyed by `session_id`
    (0.5.4). It matters because `mcode exec --session <unknown id>` is a hard failure — exit 4,
    `Session not found: <id>`, nothing on stdout (measured) — so an id the store does not hold must
    never be passed. Read-only, and sqlite reads the WAL itself."""
    sid = (session_id or "").strip()
    if not sid:
        return False
    db = home / "v2" / "sqlite" / "runtime-state.sqlite"
    if not db.is_file():
        return False
    try:
        con = sqlite3.connect(f"file:{urllib.parse.quote(str(db))}?mode=ro", uri=True, timeout=5)
        try:
            row = con.execute("SELECT 1 FROM local_runtime_sessions WHERE session_id = ? LIMIT 1",
                              (sid,)).fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return False
    return row is not None


def _minimax_tool_policy(tools_disabled: list[str] | None) -> dict:
    """`agents.default` for the config: which built-in tools, features and bundled capabilities the
    main agent has. Unknown names are ignored — an id outside _MINIMAX_TOOLS would be a toggle that
    disables nothing, and the catalog test keeps the console from offering one.

    THE ALLOWLIST CANNOT WITHHOLD ALL THREE TASK-CONTROL TOOLS, and that is the CLI's rule, not a
    choice here: its tolerant parser (parseTolerantAgentCapabilityConfig, the one `agents.default`
    goes through) does `if (!TASK_CONTROL_IDS.some(id => tools.includes(id))) tools.push(...ids)` —
    a list naming NONE of task_query/task_output/task_stop gets ALL THREE back, to preserve their
    old availability "even with tools: [] or delegation disabled". Measured on 0.5.4: a first
    attempt that simply dropped them with bash saw the CLI send all three to the provider. So one is
    named deliberately, and the other two are then excluded. task_stop is the one chosen because it
    is the only one that can neither start nor read anything: task_query lists background tasks and
    task_output reads their output logs, which on a session whose EARLIER turn had bash would hand a
    later bash-less turn the output of a command it was not allowed to run. None of the three can
    execute anything (a background task is created by the bash tool, which is withheld), so this is
    a smaller surface rather than a repaired hole."""
    off = {(t or "").split(" (")[0].strip().lower() for t in tools_disabled or []}
    allowed = [t for t in _MINIMAX_TOOLS if t != "task" and t not in off]
    allowed += list(_MINIMAX_BASH_COMPANIONS) if "bash" in allowed else ["task_stop"]
    return {
        "tools": allowed,
        # MiniMax's hosted media tools (image/video/speech generation and understanding) and its
        # bundled skills: the first need a MiniMax account; the second would sit beside the
        # harness's own skill bundles and cost prompt on every turn (18 skills, 12 MB seeded).
        "builtinTools": [],
        "skills": [],
        "features": {"webSearch": False,
                     # A subagent brings its own tools back: off whenever anything is withheld.
                     "delegation": not (off & set(_MINIMAX_TOOLS))},
    }


def _minimax_mcp_config(home: pathlib.Path, mcp_servers: list[dict] | None) -> pathlib.Path:
    """$MINIMAX_DATA_DIR/mcp.json, the PROFILE file. The project-level `.mcp.json` would have to sit
    at the workspace root, where it is a produced file handed back to the user on every turn.
    Written on EVERY turn, empty included, so a server removed from the harness is gone.

    Shapes per the runtime's own parser (0.5.4, service/mcp/runtime/config.ts): `command`/`args`/
    `env` is stdio; `type` http | streamable-http | sse with `url` and `headers` is remote. The
    declared transport travels (kimi's rule); a url with no declared transport is streamable HTTP.
    A bearer the gateway resolved (`auth`) becomes the Authorization header, as for claude."""
    servers: dict = {}
    for i, sv in enumerate(mcp_servers or []):
        if not isinstance(sv, dict):
            continue
        name = _mcp_name(sv.get("name") or sv.get("id") or f"server{i}")
        url = (sv.get("url") or "").strip()
        if url:
            entry: dict = {"type": "sse" if str(sv.get("transport") or "").lower() == "sse" else "http",
                           "url": url}
            # One place for a server's headers, for every writer and the bridge (_mcp_headers):
            # this writer had its own copy, which is how eight other writers came to drop `auth`
            # and lose the browser entirely. A copy that agrees today drifts tomorrow.
            hdrs = _mcp_headers(sv)
            if hdrs:
                entry["headers"] = hdrs
        elif sv.get("command"):
            cmd = sv["command"]
            argv = cmd if isinstance(cmd, list) else [str(cmd)]
            entry = {"command": str(argv[0]),
                     "args": [str(x) for x in argv[1:]] + [str(x) for x in (sv.get("args") or [])]}
            envv = sv.get("env")
            if isinstance(envv, dict) and envv:
                entry["env"] = {str(k): str(v) for k, v in envv.items()}
        else:
            continue
        servers[name] = entry
    home.mkdir(parents=True, exist_ok=True)
    path = home / "mcp.json"
    path.write_text(json.dumps({"mcpServers": servers}, indent=2))
    return path


def _minimax_config(home: pathlib.Path, base_url: str, api_key: str, model: str,
                    tools_disabled: list[str] | None) -> pathlib.Path:
    """$MINIMAX_DATA_DIR/config.yaml, rewritten on every turn.

    MiniMax Code takes a third-party endpoint only as a `custom_provider` entry in this file, and
    the key only as a literal `options.apiKey`: `provider add --api-key-env` copies the variable's
    VALUE into the file, and nothing in 0.5.4 reads an environment reference. What lands here is the
    relay's per-turn placeholder, never the provider key, and the file is kept out of every
    checkpoint (CHECKPOINT_EXCLUDE). The base URL is the relay's too, and a new runner means a new
    relay port — safe because a session stores neither: its record holds the workspace and nothing
    of the provider (measured), so a follow-up after a redeploy reads this turn's file.

    `openai-completions` is the api: the relay carries OpenAI chat/completions, and the id reaches
    the provider as written. External skill discovery is off (the workspace's .claude/.agents/
    .minimax skills and the home ones, with walk-up): the harness names its skills itself, in this
    home's skills/, which is kimi's --skills-dir reason. Telemetry is off in the file as well as by
    MCODE_DISABLE_TELEMETRY; it defaults off in 0.5.4 anyway."""
    cfg = {
        "defaultModel": f"custom_provider:{_MINIMAX_PROVIDER_ID}/{model}",
        "custom_provider": {_MINIMAX_PROVIDER_ID: {
            "name": "HarnessRouter", "kind": "custom", "enabled": True,
            "api": "openai-completions",
            "options": {"apiKey": api_key, "baseURL": base_url, "authMode": "api-key"},
            "models": {model: {}},
        }},
        "agents": {"default": _minimax_tool_policy(tools_disabled)},
        "skills": {"external": {"enabled": False}},
        "telemetry": {"enabled": False, "metrics": False, "diagnostics": False},
    }
    home.mkdir(parents=True, exist_ok=True)
    path = home / "config.yaml"
    # 0600 from the first byte: the CLI itself refuses a group/other-readable main config.
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(yaml.safe_dump(cfg, sort_keys=False))
    os.chmod(path, 0o600)
    return path


def _build_minimax(provider: str, auth: Auth, model: str, prompt: str, cwd: str, env: dict,
                   resume_session_id: str | None = None, mcp_servers: list[dict] | None = None,
                   tools_disabled: list[str] | None = None, max_turns: int | None = None) -> list[str]:
    """MiniMax Code (MiniMax-AI/minimax-code, MIT, the `mcode` CLI, 0.5.4) through `mcode exec`.

    Every turn rides the loopback relay, the kimi rationale unchanged: the real key never enters the
    sandbox, and the provider's own `model` and usage pass through for the served-model check and
    billing. The relay token is in the ENVIRONMENT as well as in config.yaml, because
    _relay_served_model and _relay_usage find the turn's route by the bearer in env (checklist #19).

    One conversation per harness session: the CLI mints the id (`mvs_…`) on the first turn and the
    stream announces it on every line; the next turn passes it back with --session, but only once
    the store holds it (_minimax_has_session), because an unknown id is a hard failure here."""
    pr = provider or "openai-api"
    if pr not in MINIMAX_PROVIDERS:
        raise HTTPException(400, f"unknown minimax provider '{pr}' (one of {sorted(MINIMAX_PROVIDERS)})")
    if not auth.base_url:
        raise HTTPException(400, "minimax needs a base_url (none configured)")
    if auth.api_key:
        relay_base, relay_tok = _hermes_relay_route(auth.base_url, auth.api_key)
        auth = auth.model_copy(update={"base_url": relay_base, "api_key": relay_tok})
    ws = pathlib.Path(cwd)
    home = _minimax_home(ws)
    # NO --timeout. It is a whole-run cap, and it is the wrong tool for this CLI's retry storm: with
    # `--timeout 8s` against a stub answering 401 the run did stop early, and the record became
    # `status: timeout` with an EMPTY error message — the provider's own sentence was lost. The turn's
    # cap is the runner's (_run_turn_bg's killer), which does not rewrite the reason. 0.5.4 retries
    # every error class five times with no setting anywhere to change it (the whole configurable
    # surface was walked: see docs/support-matrix-notes.md), so a refusal takes 20-28 s to arrive.
    _minimax_config(home, auth.base_url or "", auth.api_key or "", model, tools_disabled)
    _minimax_mcp_config(home, mcp_servers)
    env["MINIMAX_DATA_DIR"] = str(home)
    env["MCODE_PROVIDER_API_KEY"] = auth.api_key or ""   # the relay placeholder, read back by the relay helpers
    env["MCODE_DISABLE_TELEMETRY"] = "1"
    # The one request an exec run makes on its own is a public model catalog (no credential). The
    # release is built for region "cn", which fetches it from agent.minimax.cn; "en" takes it from
    # models.dev itself (measured with a connect/fetch logger, 0.5.4). Nothing else in exec differs.
    env["MAVIS_REGION"] = "en"
    env["NO_COLOR"] = "1"
    # --permission full: the sandbox is the boundary (claude --dangerously-skip-permissions, kimi
    # --yolo). The default `smart` also runs an LLM classifier on tool calls — extra provider calls
    # nobody asked for. stream-json is the versioned JSONL contract (schemaVersion 1).
    cmd = ["mcode", "exec", "--output-format", "stream-json", "--permission", "full",
           "--cwd", cwd, "--model", f"custom_provider:{_MINIMAX_PROVIDER_ID}/{model}"]
    if max_turns:
        # THE BUDGET: unset means unlimited. Reaching it is structural, status limit_exceeded.
        cmd += ["--max-steps", str(int(max_turns))]
    if resume_session_id and _minimax_has_session(home, resume_session_id):
        cmd += ["--session", resume_session_id]
    # `--` ends the options: a prompt that starts with "-" is still the prompt.
    return cmd + ["--", prompt]


# ── grok ─────────────────────────────────────────────────────────────────────────────────────────
# Grok Build (xai-org/grok-build, Apache-2.0), the `grok` binary 1.0.41, one headless `grok -p`
# process per turn. Everything below was measured against that binary at a logging stub (no xAI
# account, no login), and the internals it relies on are read from the Apache-2.0 source.
GROK_PROVIDERS = {"anthropic", "openai", "azure", "openai-api", "tokenrouter"}
# The model's window, for grok's auto-compaction. A custom model with none declared is planned
# against 200k; one value for the catalog is kimi's and codex's approximation, for their reason:
# being wrong changes WHEN the agent compacts, never whether it answers.
GROK_CONTEXT_WINDOW = os.environ.get("GROK_CONTEXT_WINDOW", "272000")
# The one catalog key the runner defines. A fixed NEUTRAL name, never the model id: a key equal to a
# built-in id (grok-4.6) is an OVERRIDE of that built-in, which keeps every field this file does not
# set from xAI's own entry (its wire API among them). What the key names — model, base_url — is
# rewritten on every turn and read from this file on every turn, a resumed session included
# (measured: turn 2 of one session went to a different model, port and key after a rewrite), so
# neither a model switch nor a relay port that changed with a redeploy is frozen into the session.
_GROK_MODEL_KEY = "harness"
_GROK_KEY_ENV = "HR_GROK_API_KEY"
_GROK_SESSION_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

# The console's tool ids are the names the model sees (the `tools` of a live 1.0.41 request); the
# CLI's --disallowed-tools matches its INTERNAL id, which is the same name except for the shell:
# the model calls `run_terminal_command`, the policy knows it as `run_terminal_cmd`, and the wire
# name matches nothing (measured: disallowing it left the tool in place). Only the tools that can be
# withheld ALONE are offered: read_file cannot (search_replace requires a read tool and the session
# then refuses to start), nor enter_plan_mode (exit_plan_mode requires it), nor the scheduler trio.
# spawn_subagent is withheld through the CLI's `Agent` entry, which removes the whole subagent family
# (spawn, its output and kill, and the scheduler that runs them) — measured.
# gateway/tests/test_catalog_grok_tools.py pins _BASE_CATALOG["grok"]'s ids equal to this mapping's keys.
_GROK_TOOL_POLICY_IDS = {
    "run_terminal_command": "run_terminal_cmd", "search_replace": "search_replace",
    "write": "write", "list_dir": "list_dir", "grep": "grep", "todo_write": "todo_write",
    "spawn_subagent": "Agent", "monitor": "monitor", "workflow": "workflow",
    "ask_user_question": "ask_user_question", "search_tool": "search_tool", "use_tool": "use_tool",
}
# WITHHOLDING THE SHELL MEANS WITHHOLDING EVERY SURFACE THAT RUNS A COMMAND, and grok has three
# besides `run_terminal_cmd`. MEASURED 2026-09-28, A/B with a real model on a real turn: with only
# run_terminal_command disabled, asked to run `echo <token> > shellproof.txt`, the agent called
# `monitor` with that exact command (the docs call it the streaming counterpart of /loop: it "streams
# events from a long-running script"), read the output back through
# get_command_or_subagent_output, and the file was there with the token in it. `tool_enforcement:
# "hard"` would have been an overstatement — UHP section 4.3 — on the strength of the tool list alone.
# The subagent family is the same hole one step further out (a subagent carries its own tools, kimi's
# lesson) and the scheduler runs commands on a timer; the CLI's `Agent` entry withholds all of them at
# once, measured. So the console's Shell switch withholds monitor and Agent with it.
_GROK_TOOL_IMPLIES = {"run_terminal_command": ("monitor", "Agent")}
# Withheld on every turn, whatever the harness says. The media tools call xAI's Imagine models by an
# xAI id at the turn's endpoint, which no other provider serves; send_feedback reports to xAI.
_GROK_ALWAYS_WITHHELD = ("image_gen", "image_edit", "image_to_video", "reference_to_video",
                         "send_feedback")


def _grok_home(ws: pathlib.Path) -> pathlib.Path:
    """GROK_HOME for this workspace: config.toml, sessions, skills and logs all resolve under it. It
    sits under .harness/home so the sessions travel in the checkpoint and a resume survives a
    recycled sandbox, and nothing of it is ever a produced file."""
    return ws / ".harness" / "home" / ".grok"


def _grok_has_session(home: pathlib.Path, session_id: str) -> bool:
    """Is this conversation in grok's store, asked the way the CLI asks it?

    Sessions live at sessions/<url-encoded cwd>/<id>/, and a directory is a resumable session only
    when it holds summary.json (the CLI's own is_persisted_session_dir predicate). The id is matched
    under ANY cwd key rather than re-encoding a path this code does not own; the CLI itself falls
    back to "found locally under a different cwd" the same way.

    This lookup is not only about continuity. `grok -r <id>` for an id the store does not hold
    tries to restore the conversation FROM xAI's servers and starts an xAI login (a device-code
    page) to do it — measured on 1.0.41. The runner therefore never passes -r for an id it did not
    find here, and session_registry off turns the remote restore off besides (measured: the same
    miss then fails in 0 s, "Session does not exist locally")."""
    sid = (session_id or "").strip().lower()
    if not _GROK_SESSION_ID_RE.match(sid):
        return False
    return any((home / "sessions").glob(f"*/{sid}/summary.json"))


def _toml_str(s) -> str:
    """A TOML basic string. JSON's string escapes are a subset of TOML's for everything json.dumps
    escapes without ensure_ascii (quotes, backslash, the control characters); with it a character
    outside the BMP became a surrogate PAIR of \\uXXXX escapes, which TOML refuses ("not a Unicode
    scalar value"), so one emoji in an MCP argument left the whole config unparseable. Characters
    go through as themselves; DEL, which JSON leaves alone and TOML forbids, is escaped."""
    return json.dumps(str(s), ensure_ascii=False).replace("\x7f", "\\u007F")


def _grok_config(home: pathlib.Path, model: str, base_url: str,
                 mcp_servers: list[dict] | None) -> pathlib.Path:
    """$GROK_HOME/config.toml, written on EVERY turn (a server removed from the harness is gone from
    the next turn; a model switch reaches a resumed session). It never holds the key: the model's
    `env_key` names the variable the relay's placeholder rides in.

    Each switch below is measured on 1.0.41 against a stub, and each one is here for a reason:
      remote_fetch/managed_config/campaigns off — no fetch of xAI's model catalog, managed policy or
        remote patches; with them off a run under a sandbox that DENIES all non-loopback network
        completed normally. telemetry off is the product-analytics master switch.
      session_summary = the same key — the session title is a side call that otherwise goes to a
        hard-coded `grok-4.6` AT THIS ENDPOINT: a 404 on any other provider, a second model's bill
        on xAI's. It is one short call on the first turn of a conversation, metered by the relay.
      turn_summary/title_refresh/session_recap off — a "dashboard line" call after EVERY turn and a
        title regeneration on early turns, each a full-history request nobody here reads. Measured:
        the environment variables of the same names did NOT stop them; these config keys do.
      max_retries = 2 — see _build_grok's retry note.
      session_registry off, use_leader off — the two doors to an xAI login (see _grok_has_session).
      compat.claude / compat.cursor off — grok also loads ~/.claude and ~/.cursor skills, rules,
        MCP servers and hooks, and under a shared $HOME those are trees another backend wrote.

    AN OAUTH MCP SERVER DOES NOT START A LOGIN HERE, and that is the headless path's own doing rather
    than a switch: `grok -p` sends `startupHints.nonInteractive`, and in that mode the OAuth probe
    resolves to "needs interactive login" without building an OAuth client, so nothing reaches the
    browser flow (which waits 600 s for a callback) and no tool call can escalate into it — the
    escalation asks the client whether it has an auth manager first. MEASURED against a local stub
    that answers 401 with a WWW-Authenticate challenge and serves the whole discovery chain: a
    headless turn made two MCP requests, fetched no discovery document, attempted no browser (a
    shimmed `open` recorded nothing), reported the server as `pending` in system/init and finished in
    1 s; the model calling that server's tool through use_tool was refused ("Tool not found"), also
    in 1 s. The SENSITIVITY PROOF that the rig could have seen it: the same stub under `grok mcp
    doctor`, which probes interactively, fetched both well-known documents.
    MCP: a stdio server is command/args/env/cwd; a remote one is url + headers, with `type = "sse"`
    for an SSE server. In practice one does not reach this function as SSE: grok is in
    _BRIDGED_TRANSPORTS because its SSE client dials streamable HTTP instead (see there), so the
    runner has already turned such a server into a stdio launcher for the bridge. The branch stays
    for a server that arrives untouched, and writes the shape the CLI's own `mcp add --transport sse`
    writes. A server's `auth` becomes its Authorization header, as on every other base."""
    lines = [
        "[features]", "telemetry = false", "remote_fetch = false", "managed_config = false",
        "campaigns = false", "turn_summary = false", "title_refresh = false", "session_recap = false",
        "", "[telemetry]", "trace_upload = false", "mixpanel_enabled = false",
        "", "[cli]", "auto_update = false", "session_registry = false", "use_leader = false",
        "", "[models]", f"default = {_toml_str(_GROK_MODEL_KEY)}",
        f"session_summary = {_toml_str(_GROK_MODEL_KEY)}", "max_retries = 2",
        "", f"[model.{_GROK_MODEL_KEY}]", f"model = {_toml_str(model)}",
        f"base_url = {_toml_str(base_url)}", f"env_key = {_toml_str(_GROK_KEY_ENV)}",
        f"name = {_toml_str(model)}", 'api_backend = "chat_completions"',
        f"context_window = {int(GROK_CONTEXT_WINDOW)}",
    ]
    for vendor in ("claude", "cursor"):
        lines += ["", f"[compat.{vendor}]"] + [f"{cell} = false" for cell in
                                               ("skills", "rules", "agents", "mcps", "hooks")]
    for i, sv in enumerate(mcp_servers or []):
        if not isinstance(sv, dict):
            continue
        name = _mcp_name(sv.get("name") or sv.get("id") or f"server{i}")
        url = (sv.get("url") or "").strip()
        block = ["", f"[mcp_servers.{name}]"]
        if url:
            block.append(f"url = {_toml_str(url)}")
            if str(sv.get("transport") or "").lower() == "sse":
                block.append('type = "sse"')
            hdrs: dict[str, str] = {}
            auth = sv.get("auth")
            if auth:
                hdrs["Authorization"] = auth if str(auth).lower().startswith("bearer ") else f"Bearer {auth}"
            if isinstance(sv.get("headers"), dict):
                hdrs.update({str(k): str(v) for k, v in sv["headers"].items() if k and v is not None})
            if hdrs:
                block.append("headers = { " + ", ".join(f"{_toml_str(k)} = {_toml_str(v)}"
                                                         for k, v in hdrs.items()) + " }")
        elif sv.get("command"):
            cmd = sv["command"]
            argv = cmd if isinstance(cmd, list) else [str(cmd)]
            args = [str(x) for x in argv[1:]] + [str(x) for x in (sv.get("args") or [])]
            block.append(f"command = {_toml_str(argv[0])}")
            block.append("args = [" + ", ".join(_toml_str(a) for a in args) + "]")
            envv = sv.get("env")
            if isinstance(envv, dict) and envv:
                block.append("env = { " + ", ".join(f"{_toml_str(k)} = {_toml_str(v)}"
                                                     for k, v in envv.items()) + " }")
            if sv.get("cwd"):
                block.append(f"cwd = {_toml_str(sv['cwd'])}")
        else:
            continue
        lines += block
    home.mkdir(parents=True, exist_ok=True)
    path = home / "config.toml"
    path.write_text("\n".join(lines) + "\n")
    return path


def _build_grok(provider: str, auth: Auth, model: str, prompt: str, cwd: str, env: dict,
                resume_session_id: str | None = None, mcp_servers: list[dict] | None = None,
                tools_disabled: list[str] | None = None, max_turns: int | None = None,
                partial: bool = False) -> list[str]:
    """Grok Build (1.0.41), headless: `grok -p … --output-format streaming-messages-json`, which is
    Claude Code's stream-json (system/init with session_id, assistant/user messages, a terminal
    result), so the normaliser is the claude passthrough plus two repairs (see _grok_to_claude).

    EVERY TURN RIDES THE LOOPBACK RELAY, for the qwen/kimi reasons and one of grok's own: its only
    usage report excludes side calls (the session title), so the relay's count of every call the
    provider answered is the bill. The placeholder rides HR_GROK_API_KEY, which the config's
    env_key names — the environment, where _relay_served_model and _relay_usage look for it. The
    model is a custom chat/completions entry; grok sends the configured id verbatim (no client-side
    rewriting, captured at the stub).

    No xAI login, ever: a key-only run needs none, and the two paths that would start one are shut
    (see _grok_has_session). stdin is not read in headless mode, so nothing can wait on it.

    Retries: the defaults stack a sampler retry loop under a turn-level transient retry (3 more
    attempts, backoff up to 35 s); a provider answering 500 every time took 29 requests and more
    than nine minutes to fail. max_retries = 2 plus GROK_TURN_TRANSIENT_RETRY=0: 3 requests, 3 s,
    and the provider's own sentence as the reason. A 401 or an unreachable endpoint fails in 1 s."""
    pr = provider or "openai-api"
    if pr not in GROK_PROVIDERS:
        raise HTTPException(400, f"unknown grok provider '{pr}' (one of {sorted(GROK_PROVIDERS)})")
    if not auth.base_url:
        raise HTTPException(400, "grok needs a base_url (none configured)")
    if not auth.api_key:
        raise HTTPException(400, "grok needs an API key")
    # gemini_schemas: grok declares nullable parameters as a JSON-schema type LIST (run_terminal_command's
    # `timeout` is {"type": ["integer", "null"], "format": "uint64", "minimum": 0, …}). Through
    # Vercel a gemini model took the first request of a turn and refused the next one, the one
    # carrying the tool result: "`run_terminal_command` functionDeclaration `parameters.timeout`
    # schema specified other fields alongside any_of" (gemini-3.5-flash-lite, measured 2026-09-27),
    # so a gemini turn died at its first tool call. The relay's Gemini normaliser (a type list
    # becomes one type plus nullable) is applied on this route for gemini ids on every channel.
    relay_base, relay_tok = _hermes_relay_route(auth.base_url, auth.api_key, gemini_schemas=True,
                                                usage_no_nulls=True)
    ws = pathlib.Path(cwd)
    home = _grok_home(ws)
    _grok_config(home, model, relay_base, mcp_servers)
    env["GROK_HOME"] = str(home)
    env[_GROK_KEY_ENV] = relay_tok
    # The global fallbacks grok would read for an xAI model: never the turn's credential.
    for k in ("XAI_API_KEY", "GROK_CODE_XAI_API_KEY", "GROK_MODELS_BASE_URL", "GROK_DEPLOYMENT_KEY"):
        env.pop(k, None)
    env["GROK_DISABLE_AUTOUPDATER"] = "1"
    env["GROK_TELEMETRY_ENABLED"] = "0"
    env["GROK_SESSION_REGISTRY"] = "0"
    env["GROK_TURN_TRANSIENT_RETRY"] = "0"
    # Cross-session memory is grok's own store outside the conversation; the harness's memory is the
    # session. Folder trust gates the workspace's AGENTS.md and skills behind an interactive grant a
    # headless run cannot give (docs: "Headless startup with these sources requires --trust"); the
    # sandbox is the trust boundary, the codex/qwen --yolo reasoning.
    env["GROK_MEMORY"] = "0"
    env["GROK_FOLDER_TRUST"] = "0"
    env["NO_COLOR"] = "1"
    sid = (resume_session_id or "").strip().lower()
    resumed = bool(sid) and _grok_has_session(home, sid)
    # `--single=<prompt>` so a prompt that begins with a dash is the prompt, not a flag (measured).
    cmd = ["grok", f"--single={prompt}", "-m", _GROK_MODEL_KEY,
           "--output-format", "streaming-messages-json", "--always-approve"]
    # The runner owns the conversation id: -s names a NEW session (a uuid the store must not hold),
    # -r continues one the store holds. The init event reports it, and the gateway sends it back.
    cmd += ["-r", sid] if resumed else ["-s", str(uuid.uuid4())]
    withheld = [_GROK_TOOL_POLICY_IDS[t] for t in (tools_disabled or []) if t in _GROK_TOOL_POLICY_IDS]
    for t in (tools_disabled or []):
        for implied in _GROK_TOOL_IMPLIES.get(t, ()):
            if implied not in withheld:
                withheld.append(implied)
    cmd += ["--disallowed-tools", ",".join(list(_GROK_ALWAYS_WITHHELD) + withheld)]
    if max_turns:
        # Unset is unbounded; reaching it ends the run as `error_max_turns`, which reads as failed.
        cmd += ["--max-turns", str(int(max_turns))]
    if partial:
        cmd.append("--include-partial-messages")
    return cmd


AIDER_PROVIDERS = {"anthropic", "openai", "azure", "openai-api", "tokenrouter"}
AIDER_PYTHON = os.environ.get("HR_AIDER_PYTHON", "/data/agent-tools/aider-venv/bin/python")
AIDER_DRIVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aider_driver.py")
# aider's MCP client, runner/aider_mcp_bridge.py, run by the aider venv's own interpreter. aider
# ships none of its own — zero source hits across the whole 0.86.2 tree — so rather than record the
# capability as missing, the harness brings one and lets the model reach it through the ONE tool
# surface aider has: a shell command it proposes. The maintainer's 2026-09-13 decision: bridge the
# capability, then measure the claim for real.
AIDER_MCP_BRIDGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aider_mcp_bridge.py")


def _aider_mcp_servers(mcp_servers: list[dict] | None) -> dict:
    """The declared servers, keyed by the NAME the model will use. Named rather than URL'd so the
    model cannot invent an endpoint: it says `hr-mcp call <name> …` and the mapping is ours.

    THE DECLARED TRANSPORT TRAVELS, for the reason _kimi_mcp_config states: the harness's
    declaration decides, never the url's spelling. It matters more here, because the bridge's SDK
    does not guess at all — `Client(<str>)` is hard-wired to streamable HTTP (client.py:393-394) —
    so an SSE server reached this backend as the wrong protocol and could not answer."""
    out: dict = {}
    for i, sv in enumerate(mcp_servers or []):
        if not isinstance(sv, dict):
            continue
        name = _skill_dir_name(sv.get("name") or sv.get("id") or f"server{i}")
        url = (sv.get("url") or "").strip()
        if url:
            entry: dict = {"url": url}
            if str(sv.get("transport") or "").lower() == "sse":
                entry["transport"] = "sse"
            hdrs = _mcp_headers(sv)
            if hdrs:
                entry["headers"] = hdrs
        elif sv.get("command"):
            cmd = sv["command"]
            argv = cmd if isinstance(cmd, list) else [str(cmd)]
            entry = {"command": argv[0],
                     "args": [str(x) for x in argv[1:]] + [str(x) for x in (sv.get("args") or [])]}
            envv = sv.get("env")
            if isinstance(envv, dict) and envv:
                entry["env"] = {str(k): str(v) for k, v in envv.items()}
        else:
            continue
        out[name] = entry
    return out


def _aider_working_notes(cwd: str, servers: dict | None = None) -> str:
    """How THIS workspace works, in the terms aider's own prompt uses.

    aider's system prompt tells the model that the USER adds files to the chat and that the
    user may run the shell commands it suggests. Here nobody sits at that keyboard: the driver
    answers every confirmation, adds a file the model names, runs a command it proposes and hands
    the output back in the same turn. Unless the model is told so it behaves as aider's prompt
    says, measured 2026-09-18 on hr-test: asked to use a skill it guessed the token instead of
    reading SKILL.md, asked to call an MCP tool it wrote "I'm constrained here to only return
    SEARCH/REPLACE blocks", asked for a streamable-HTTP tool it invented the result. Reading goes
    through the shell on purpose: aider's own file-mention route adds only files git already
    tracks, and on a session's first turn the skill files are not committed yet (measured: the
    model named the path exactly and the turn ended there). `cat` works on every turn. The paths
    are workspace-relative; the skills block above keeps its absolute folders for composing
    commands."""
    skills = sorted(p.relative_to(cwd).as_posix()
                    for p in (pathlib.Path(cwd) / ".harness" / "skills").glob("*/SKILL.md"))
    lines = ["\n## How this workspace works for you\n",
             "You cannot open files or run anything yourself; the harness does both for you "
             "between messages, without asking anyone.\n",
             "- To run a command, put it in a ```bash fenced block and end your reply. It is "
             "executed and its output is given back to you in the next message; then continue.",
             "- To read a file that is not in the chat, run `cat <path>` that way."]
    if skills:
        lines.append("  Read a skill before using it:")
        lines += [f"  - `cat {rel}`" for rel in skills]
    lines += ["- A skill's scripts run the same way (cd into the skill's folder first)"
              + (", and so do MCP tool calls (`hr-mcp`, below)." if servers else "."),
              "- Each line of a bash block runs as its own command. A program that needs more "
              "than one line goes into a file first (a SEARCH/REPLACE block creates it), then "
              "one line runs it.",
              "- Name a file in a SEARCH/REPLACE block by its path relative to this workspace "
              "(`deck.md`, `src/app.py`), never by an absolute path: a leading slash is refused "
              "and the workspace's own path repeated under it makes a nested copy.",
              "- Binary files (documents, decks, spreadsheets, images, PDFs) cannot be added to "
              "the chat or edited with SEARCH/REPLACE; inspect and change them with commands.",
              "- Report only output you were actually given. Never write the result you expect "
              "a command or a tool to produce; if you have not run it yet, run it first.\n"]
    return "\n".join(lines)


def _aider_mcp_block(servers: dict) -> str:
    """The bridge, in the context aider reads, in the exact form the driver's gate recognises.

    Listing the servers is all the runner can do from here: their tool NAMES are only knowable by
    asking the server, which needs a live connection at turn time. So `hr-mcp tools <server>` is
    part of the instruction — the model discovers the tools the way a person would — and
    `hr-mcp call` is what the gate matches, so a call made this way is recorded under the MCP
    tool's own name and the support matrix measures `mcp_called` from a command that actually ran
    rather than from a capability we claimed."""
    if not servers:
        return ""
    rows = []
    for name, entry in servers.items():
        if entry.get("url"):
            rows.append(f"- `{name}` — streamable HTTP")
        else:
            rows.append(f"- `{name}` — stdio")
    return ("\n## MCP servers\n\n"
            "These MCP servers are available to you through the `hr-mcp` command. They are real "
            "tools: use them when the task calls for one.\n\n"
            + "\n".join(rows) + "\n\n"
            "List a server's tools with `hr-mcp tools <server>`, and call one with\n\n"
            "```bash\n"
            "hr-mcp call <server> <tool> --params '{\"key\": \"value\"}'\n"
            "```\n\n"
            "Propose the command in a ```bash block as you would any other shell command.\n")


def _build_aider(provider: str, auth: Auth, model: str, prompt: str, cwd: str, env: dict,
                 mcp_servers: list[dict] | None = None, tools_disabled: list[str] | None = None,
                 skills_read: list[str] | None = None, max_turns: int | None = None) -> list[str]:
    pr = provider or "openai-api"
    if pr not in AIDER_PROVIDERS:
        raise HTTPException(400, f"unknown aider provider '{pr}' (one of {sorted(AIDER_PROVIDERS)})")
    if not auth.base_url:
        raise HTTPException(400, "aider needs a base_url (none configured)")
    if auth.api_key:
        # Every aider turn rides the loopback relay, the qwen rationale unchanged. It matters twice
        # over here: aider takes its credential only from the environment, and aider reports no
        # served model of its own, so _relay_served_model is what makes matrix rule 2 enforceable.
        relay_base, relay_tok = _hermes_relay_route(auth.base_url, auth.api_key)
        auth = auth.model_copy(update={"base_url": relay_base, "api_key": relay_tok})
    env["OPENAI_API_BASE"] = auth.base_url
    env["OPENAI_API_KEY"] = auth.api_key or ""
    env["HOME"] = str(pathlib.Path(cwd) / ".harness" / "home")
    pathlib.Path(env["HOME"]).mkdir(parents=True, exist_ok=True)
    # The MCP bridge, and the only reason aider can reach an MCP server at all. The shim is written
    # per turn rather than installed once because it has to name the aider venv's interpreter and
    # the bridge beside this file, both of which are known here and nowhere else.
    servers = _aider_mcp_servers(mcp_servers)
    bindir = pathlib.Path(cwd) / ".harness" / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    cfg = pathlib.Path(cwd) / ".harness" / "aider-mcp.json"
    # The disabled names ride with the servers: the bridge refuses a disabled tool itself, where
    # the call executes, so the policy holds whatever shell the model wraps the call in.
    cfg.write_text(json.dumps({"mcpServers": servers,
                               "disabledTools": [str(t) for t in (tools_disabled or [])]}, indent=2))
    shim = bindir / "hr-mcp"
    shim.write_text("#!/bin/sh\nexec %s %s --config %s \"$@\"\n"
                    % (shlex.quote(AIDER_PYTHON), shlex.quote(AIDER_MCP_BRIDGE), shlex.quote(str(cfg))))
    shim.chmod(0o755)
    env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", os.environ.get("PATH", ""))
    # The notes and the MCP block are APPENDED to the agent doc the turn already wrote, which
    # the driver puts into the system message. Without the block the bridge exists and the model is never told
    # it does — the defect this call site is here to prevent, caught because the block was
    # generated and never used.
    doc = _agent_doc_path(cwd, "aider")
    try:
        doc.write_text((doc.read_text() if doc.exists() else "")
                       + _aider_working_notes(cwd, servers) + _aider_mcp_block(servers))
    except OSError:
        pass
    # aider resolves a BARE id against its own MODEL_ALIASES table, which rewrites 21 of them —
    # `gemini-2.5-pro` among them, an id this product's catalog also serves. An `openai/` prefix
    # routes through litellm's openai provider verbatim and skips that table entirely, so the id the
    # picker offered is the id the provider is asked for.
    job = {"cwd": cwd, "model": f"openai/{model}", "prompt": prompt,
           "tools_disabled": list(tools_disabled or []),
           # the agent doc, which the driver puts into aider's system message
           "system_files": list(skills_read or []),
           # aider takes the budget as Coder.max_reflections, set in the driver: it has no CLI flag
           # for it, and only an in-process driver holds the object.
           "max_turns": max_turns}
    return [AIDER_PYTHON, AIDER_DRIVER, json.dumps(job)]


# ── cheetahclaws ────────────────────────────────────────────────────────────────
# CheetahClaws (SAIL-Research-Lab/cheetahclaws, PyPI `cheetahclaws`, Apache-2.0), pinned to 3.5.88.
# The turn process is runner/cheetahclaws_driver.py inside the pinned venv: the CLI's own agent loop
# is driven IN PROCESS and every event it yields is re-emitted as it happens (the aider shape, for
# the reasons the driver's docstring measures: `-p` has no event stream, the session file is
# written once per turn, a provider failure is prose with exit 0, and there is no resume flag).
#
# ONE provider type, measured: `custom/<model>` is CheetahClaws's OpenAI Chat Completions client
# (providers.py, stream_openai_compat) aimed at CUSTOM_BASE_URL with CUSTOM_API_KEY, which is
# exactly what the loopback relay fronts. So the runner providers are the chat-completions ones;
# no Anthropic Messages or Responses path is offered, because the CLI is not asked to speak one.
CHEETAHCLAWS_PROVIDERS = {"openai-api", "tokenrouter"}
CHEETAHCLAWS_PYTHON = os.environ.get("HR_CHEETAHCLAWS_PYTHON",
                                     "/data/agent-tools/cheetahclaws-venv/bin/python")
CHEETAHCLAWS_DRIVER = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "cheetahclaws_driver.py")
# The `tools` array a live 3.5.88 turn sent its provider, captured at a stub (the CLI's default
# "full" profile, bare package), minus what the driver withholds on every turn in this image:
# AskUserQuestion, ReadEmail and SendEmail (cheetahclaws_driver.ALWAYS_WITHHELD) and the four tools
# of optional extras that are not installed (OPTIONAL_TOOLS: WebBrowse, ReadPDF, ReadSpreadsheet,
# ReadImage). These are the names `disabled_tools` matches, exactly and case-sensitively; the
# gateway's catalog is pinned equal to this tuple (gateway/tests/test_catalog_cheetahclaws_tools.py),
# so a toggle the console shows always withholds a tool the model was actually offered.
CHEETAHCLAWS_TOOLS = ("Agent", "Bash", "CheckAgentResult", "Edit", "EnterPlanMode", "ExitPlanMode",
                      "GetDiagnostics", "Glob", "Grep", "ListAgentTasks", "ListAgentTypes",
                      "MemoryDelete", "MemoryList", "MemorySave", "MemorySearch", "MemoryVerify",
                      "NotebookEdit", "Read", "Research", "SendMessage", "Skill", "SkillList",
                      "SleepTimer", "SummarizeLargeFile", "TaskCreate", "TaskGet", "TaskList",
                      "TaskUpdate", "WebFetch", "WebSearch", "Write")


def _build_cheetahclaws(provider: str, auth: Auth, model: str, prompt: str, cwd: str, env: dict,
                        resume_session_id: str | None = None,
                        mcp_servers: list[dict] | None = None,
                        tools_disabled: list[str] | None = None,
                        max_turns: int | None = None) -> list[str]:
    pr = provider or "openai-api"
    if pr not in CHEETAHCLAWS_PROVIDERS:
        raise HTTPException(400, f"unknown cheetahclaws provider '{pr}' "
                                 f"(one of {sorted(CHEETAHCLAWS_PROVIDERS)})")
    if not auth.base_url:
        raise HTTPException(400, "cheetahclaws needs a base_url (none configured)")
    if auth.api_key:
        # Every turn rides the loopback relay: the CLI is handed the relay's address and a
        # per-turn placeholder, never the key, and the relay's taps supply what the CLI does not
        # report — the served model (matrix rule 2) and fresh / cached / output tokens. The session
        # file carries neither: its totals are the GROSS prompt tokens with no cache split, and it
        # names no model.
        relay_base, relay_tok = _hermes_relay_route(auth.base_url, auth.api_key, stream_usage=True)
        auth = auth.model_copy(update={"base_url": relay_base, "api_key": relay_tok})
    # The two names providers.py reads for `custom/`. custom_base_url in config.json would win
    # over the variable, and the driver writes no config.json, so the variable is what applies.
    env["CUSTOM_BASE_URL"] = auth.base_url
    env["CUSTOM_API_KEY"] = auth.api_key or ""
    home = _cheetahclaws_home(cwd)
    home.mkdir(parents=True, exist_ok=True)
    # MCP in the Claude Code `mcpServers` shape the CLI reads (mcp_client/config.py) at its
    # user-level path, rewritten every turn so a server the harness no longer names is gone. The
    # project-level <cwd>/.mcp.json is the user's own file and is left alone.
    mcp = home / "mcp.json"
    if not _write_mcp_config_claude(cwd, mcp_servers or [], dest=mcp):
        mcp.write_text(json.dumps({"mcpServers": {}}))
    have = _cheetahclaws_session_present(cwd, [], resume_session_id) if resume_session_id else False
    job = {"cwd": cwd, "model": f"custom/{model}", "prompt": prompt,
           # the session to continue, only when its file is here (see _resume_lost)
           "session_id": resume_session_id if have else "",
           # withheld from the tool schema by the CLI's own `disabled_tools` (the driver expands
           # an MCP tool's bare or server.tool name to its mcp__server__tool registry name)
           "tools_disabled": list(tools_disabled or []),
           # the loop has no step limit of its own; the driver stops it through run()'s
           # cancel_check once this many model calls have been made
           "max_turns": max_turns}
    return [CHEETAHCLAWS_PYTHON, CHEETAHCLAWS_DRIVER, json.dumps(job)]




# Path A only (Gemini API Key / Google AI Studio). Unlike qwen, upstream gemini-cli speaks NO
# OpenAI-compatible mode at all (that is a qwen-fork-only addition — see QWEN_PROVIDERS above),
# so there is no loopback-relay trick that lets any generic OpenAI/Anthropic-shaped integration
# drive this backend. A Vertex AI provider (service account) belongs here too in principle — the
# runner-side env is the same GOOGLE_APPLICATION_CREDENTIALS/GOOGLE_CLOUD_PROJECT/
# GOOGLE_CLOUD_LOCATION triple _build_claude's vertex branch already writes — but it is left OUT
# of this set until the gateway side decides how (or whether) to broker it; see the gateway's
# _BROKERABLE_PROVIDERS comment for bedrock/vertex.
GEMINI_PROVIDERS = {"google"}
# gemini-cli 0.58.0's model-config aliases that carry a model of their own (alias -> parent). Read
# off the CLI's DEFAULT_MODEL_CONFIGS table; a CLI bump re-reads it. The chat-model aliases
# (gemini-2.5-pro, ...) are not here: a turn runs its chat model through the id resolutions.
# "classifier" is the model router's own alias (flash-lite in the table, asked for by name through
# generateJson); it carries a model like the others and is pinned with them.
GEMINI_HELPER_ALIASES = {
    "gemini-2.5-flash-base": "base", "gemini-3-flash-base": "base", "gemini-3.5-flash-base": "base",
    "prompt-completion": "base", "fast-ack-helper": "base", "edit-corrector": "base",
    "summarizer-default": "base", "summarizer-shell": "base", "classifier": "base", "loop-detection-double-check": "base",
    "chat-compression-3-pro": "", "chat-compression-3-flash": "", "chat-compression-3.1-flash-lite": "",
    "chat-compression-2.5-pro": "", "chat-compression-2.5-flash": "", "chat-compression-2.5-flash-lite": "",
    "chat-compression-default": "", "agent-history-provider-summarizer": "",
}
# Every Gemini id the gateway's gemini catalog lists. gemini-cli's resolver rewrites ids on the
# API-key auth path (every "-flash" id to gemini-3.5-flash, 3.1-pro-preview to its customtools
# variant, and by context in its default resolution table); with dynamicModelConfiguration on, -m
# goes through the resolution table instead, and an entry with no contexts pins an id to itself.
# The settings deep-merge a user entry into the default one, so the contexts must be emptied
# explicitly (a plain default alone left gemini-2.5-flash rewritten, measured 2026-09-06 on 0.58.0).
# Every listed id is pinned, and the turn's own model with it, so no context can retarget any of
# them; a served model that still differs fails the turn (see _gemini_to_claude).
GEMINI_MODELS = ("gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash",
                 "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.1-pro-preview",
                 "gemini-3-flash-preview")


def _gemini_settings(home: pathlib.Path, mcp_servers: list[dict] | None, model: str = "") -> None:
    """~/.gemini/settings.json under the redirected HOME.

    mcpServers uses gemini-cli's own schema (command/args/env for stdio, url/httpUrl/headers for
    remote) — the same shape _qwen_settings already writes, because qwen inherited it unchanged
    from this fork point (confirmed against gemini-cli's published configuration reference).

    security.auth.selectedType is written explicitly rather than left to gemini-cli's own
    GEMINI_API_KEY auto-detection: every other backend in this file pins its auth type
    explicitly instead of relying on env-var presence alone (see qwen's --auth-type openai,
    passed even though OPENAI_API_KEY being set would likely auto-select it too), and gemini-cli
    publishes no non-interactive CLI flag equivalent to qwen's --auth-type — settings.json is the
    only documented way to pin it outside the interactive /auth prompt."""
    gdir = home / ".gemini"
    gdir.mkdir(parents=True, exist_ok=True)
    servers: dict = {}
    for i, sv in enumerate(mcp_servers or []):
        if not isinstance(sv, dict):
            continue
        name = _skill_dir_name(sv.get("name") or sv.get("id") or f"server{i}")
        url = (sv.get("url") or "").strip()
        if url:
            # Their schema names the transport by the key: `url` is an SSE endpoint, `httpUrl` a
            # streamable HTTP one; a server declared sse under httpUrl is silently never loaded.
            entry: dict = {"url": url} if str(sv.get("transport") or "").lower() == "sse" else {"httpUrl": url}
            hdrs = _mcp_headers(sv)
            if hdrs:
                entry["headers"] = hdrs
        elif sv.get("command"):
            cmd = sv["command"]
            argv = cmd if isinstance(cmd, list) else [str(cmd)]
            entry = {"command": argv[0], "args": [str(x) for x in argv[1:]] + [str(x) for x in (sv.get("args") or [])]}
            envv = sv.get("env")
            if isinstance(envv, dict) and envv:
                entry["env"] = {str(k): str(v) for k, v in envv.items()}
        else:
            continue
        servers[name] = entry
    pinned = sorted(set(GEMINI_MODELS) | ({model} if model else set()))
    # No fallback either: every chain the CLI can resolve for this turn is one policy, the turn's
    # own model, so its fallback handler has no candidate to switch to and the provider's error ends
    # the turn honestly (retries stay on the same model: sticky_retry on transient and unknown
    # failures). Measured after this landed: headless gemini-cli has no fallback handler, so the
    # chains were never the switch; the second model the 2026-09-07 02:10Z turn showed was the
    # classifier tier below. The chains stay as the guard they are.
    own = [{"model": model or GEMINI_DEFAULT_MODEL, "isLastResort": True, "maxAttempts": 3,
            "actions": {"terminal": "prompt", "transient": "prompt", "not_found": "prompt", "unknown": "prompt"},
            "stateTransitions": {"terminal": "terminal", "transient": "sticky_retry", "not_found": "terminal", "unknown": "sticky_retry"}}]
    turn_model = model or GEMINI_DEFAULT_MODEL
    # The tiers cover the classifier only. The CLI's other helpers (edit correction, the shell and
    # tool summarizers, the next-speaker and loop checks, web fetch, chat compression, the history
    # summarizer) are model-config ALIASES whose model is written into the alias table itself
    # ("gemini-3-flash-base" is gemini-3-flash-preview, "edit-corrector" is flash-lite, ...), and
    # an alias's model is never passed through the id resolutions. A one-pager build on
    # gemini-3.8-flash made three such calls on gemini-3-flash-preview and failed as a
    # substitution (hosted, 2026-09-07 04:58Z). Custom aliases replace the table's entries by
    # name, so every alias that names a model is rewritten to the turn's model, its parent kept.
    aliases = {name: ({"extends": parent} if parent else {}) | {"modelConfig": {"model": turn_model}}
               for name, parent in GEMINI_HELPER_ALIASES.items()}
    cfg: dict = {"security": {"auth": {"selectedType": "gemini-api-key"}},
                 # the ids are honest: -m resolves through this table, and each entry pins an id to itself
                 "experimental": {"dynamicModelConfiguration": True},
                 # The CLI's own housekeeping calls (model routing, plan mode, context compression, the
                 # next-speaker and loop checks) go to a "flash" or "pro" classifier tier that defaults to
                 # gemini-3-flash-preview or gemini-3-pro-preview, and those calls land in the turn's stats
                 # beside the answer model: a five-minute turn on gemini-3.8-flash showed
                 # "gemini-3-flash-preview" too and failed as a substitution (2026-09-07, both trees).
                 # Every model the CLI calls in a turn is the one asked for: both tiers pin to it.
                 "modelConfigs": {"modelIdResolutions": {m: {"default": m, "contexts": []} for m in pinned},
                                  "classifierIdResolutions": {t: {"default": turn_model, "contexts": []} for t in ("flash", "pro")},
                                  "customAliases": aliases,
                                  "modelChains": {k: own for k in ("preview", "default", "lite", "auto-preview", "auto-default")}}}
    if servers:
        cfg["mcpServers"] = servers
    (gdir / "settings.json").write_text(json.dumps(cfg, indent=2))


def _build_gemini(provider: str, auth: Auth, model: str, prompt: str, cwd: str, env: dict,
                  resume_session_id: str | None = None, mcp_servers: list[dict] | None = None,
                  native_model: str | None = None) -> list[str]:
    pr = provider or "google"
    if pr not in GEMINI_PROVIDERS:
        raise HTTPException(400, f"unknown gemini provider '{pr}' (one of {sorted(GEMINI_PROVIDERS)})")
    if not auth.api_key:
        raise HTTPException(400, "gemini needs an api_key (none configured)")
    home = pathlib.Path(cwd) / ".harness" / "home"
    home.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(home)                      # sessions/skills/settings live INSIDE the workspace
    if auth.base_url and _gemini_channel(auth.base_url):
        # A TokenRouter or hosted connection: it serves Google's native API under its own root and
        # its own name for the model (TokenRouter's vendor prefix, measured 2026-09-07 for the seven
        # Gemini ids its table carries; the hosted door takes the canonical id), so the CLI is pointed
        # at the loopback relay, which owns that name and the real key; the CLI keeps its own model
        # id, so the pinned resolutions and the served-model check below are unchanged.
        relay_base, relay_tok = _gemini_relay_route(auth.base_url.rstrip("/").removesuffix("/v1"), auth.api_key, model, native_model or "")
        env["GOOGLE_GEMINI_BASE_URL"] = relay_base
        env["GEMINI_API_KEY"] = relay_tok
    else:
        env["GEMINI_API_KEY"] = auth.api_key
    _gemini_settings(home, mcp_servers, model)
    cmd = ["gemini", "-p", prompt, "-o", "stream-json", "-m", model,
           # Load-bearing, same risk class as qwen's --yolo: gemini-cli gates tool use behind a
           # per-workspace "folder trust" prompt and an approval mode, neither of which can be
           # answered interactively in headless mode. --approval-mode=yolo is the current
           # (non-deprecated) form of the old --yolo/-y flag; --skip-trust bypasses the trust
           # prompt for a workspace that (like every turn here) has never been seen before. Both
           # confirmed live (2026-09-06, 0.58.0): without them a fresh workspace either hangs on
           # the trust prompt or the model has no shell/write tool at all, exactly qwen's failure
           # mode without --yolo; with them, real shell/write/skill-activation calls went through
           # across three starter-kit turns (slides, sheets, videos).
           "--approval-mode", "yolo", "--skip-trust"]
    if resume_session_id:
        # gemini-cli's --resume takes ONLY "latest" or a numeric index into this project's own
        # session list, never an arbitrary id (unlike claude/qwen's -r <uuid>) — so the id this
        # runner tracks per turn cannot be passed through directly. "latest" is still correct
        # here specifically because HOME is redirected into THIS workspace's own checkpoint
        # (same as qwen): there is exactly one project's session history under it, so "latest"
        # and "the session this resume call means" are the same session. Live-verified 2026-09-06:
        # a follow-up turn on an existing slides-kit session picked up its own prior context and
        # produced a real .pptx via the officecli skill, not a fresh unrelated session.
        cmd += ["--resume", "latest"]
    return cmd


CLINE_PROVIDERS = {"anthropic", "openai", "azure", "openai-api", "tokenrouter"}


def _cline_settings(home: pathlib.Path, base_url: str, api_key: str, model: str,
                    mcp_servers: list[dict] | None) -> None:
    """~/.cline/data/settings/{providers.json, cline_mcp_settings.json} under the redirected HOME.

    Written directly rather than through `cline auth` — the file is trivial, and a subprocess per
    turn to produce four JSON fields is a second mechanism for one behaviour. Shapes verified
    against what 3.0.60's own `auth` and `mcp install --yes` write, not inferred from source.

    The apiKey that lands on disk is the per-turn loopback relay token, never the provider key:
    every cline turn rides the hermes relay exactly as qwen's does. cline was verified to IGNORE
    CLINE_API_KEY/CLINE_API_BASE_URL for this provider (a stub upstream never saw the request;
    api.openai.com did), so the settings file is the only wiring that actually works — and inside
    the per-session sandbox it is readable only by the session's own uid, which can read its own
    process environment anyway.
    """
    sdir = home / ".cline" / "data" / "settings"
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "providers.json").write_text(json.dumps({
        "version": 1,
        "lastUsedProvider": "openai-compatible",
        "modes": {},
        "providers": {"openai-compatible": {
            "settings": {"provider": "openai-compatible", "apiKey": api_key,
                         "model": model, "baseUrl": base_url},
            # REQUIRED, not decoration: without updatedAt 3.0.60's settings schema rejects the
            # whole provider entry — silently — and the CLI dials api.openai.com with no key.
            # Bisected live: the identical file with only this field added runs; without it the
            # entry is rewritten down to {provider, model} and the turn dies on OpenAI's 401.
            "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
            "tokenSource": "manual"}},
    }, indent=2))
    servers: dict = {}
    for i, sv in enumerate(mcp_servers or []):
        if not isinstance(sv, dict) or sv.get("enabled") is False:
            continue
        url = (sv.get("url") or "").strip()
        name = _skill_dir_name(sv.get("name") or sv.get("id") or f"server{i}")
        if not url and sv.get("command"):
            # A stdio server (a plugin's, through its launcher), in the same transport-object
            # shape 3.0.60 writes for `mcp install` of a local server.
            servers[name] = {"transport": {"type": "stdio", "command": str(sv["command"]),
                                           "args": [str(a) for a in (sv.get("args") or [])]}}
            continue
        if not url:
            continue
        entry: dict = {"transport": {"type": "sse" if str(sv.get("transport") or "").lower() == "sse" else "streamableHttp", "url": url}}
        hdrs = _mcp_headers(sv)
        if hdrs:
            entry["transport"]["headers"] = hdrs
        servers[name] = entry
    (sdir / "cline_mcp_settings.json").write_text(json.dumps({"mcpServers": servers}, indent=2))


def _build_cline(provider: str, auth: Auth, model: str, prompt: str, cwd: str, env: dict,
                 resume_session_id: str | None = None,
                 mcp_servers: list[dict] | None = None) -> list[str]:
    pr = provider or "openai-api"
    if pr not in CLINE_PROVIDERS:
        raise HTTPException(400, f"unknown cline provider '{pr}' (one of {sorted(CLINE_PROVIDERS)})")
    if not auth.base_url:
        raise HTTPException(400, "cline needs a base_url (none configured)")
    if auth.api_key:
        # Every cline turn rides the loopback relay (the qwen rationale, verbatim): request shapes
        # strict endpoints refuse are repaired in flight, and the real key never reaches the CLI —
        # what lands in its settings file is a placeholder valid for this turn, from loopback only.
        relay_base, relay_tok = _hermes_relay_route(auth.base_url, auth.api_key)
        auth = auth.model_copy(update={"base_url": relay_base, "api_key": relay_tok})
    home = pathlib.Path(cwd) / ".harness" / "home"
    home.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(home)          # sessions/settings/db live INSIDE the checkpointed workspace
    _cline_settings(home, auth.base_url, auth.api_key or "", model, mcp_servers)
    # A prompt with no whitespace is parsed as a SUBCOMMAND ("Unknown command or unquoted
    # prompt: hi") and `--` does not rescue it. A trailing newline does, verified on 3.0.60,
    # and is invisible to the model.
    if prompt and not any(ch.isspace() for ch in prompt):
        prompt = prompt + "\n"
    # NO resume flag, deliberately. 3.0.60's `--json --id <session>` refuses every way of passing
    # a prompt (argument, =form, piped stdin — all verified individually, and the identical argv
    # without --id runs), so headless resume is unusable in this release. A follow-up turn starts
    # a fresh conversation over the same workspace: the files, AGENTS.md and the session store
    # under HOME all persist through the checkpoint, so when a release fixes the flag, resume
    # lights up here with no storage work.
    # `-z` (background hub daemon) must never be added: one process per turn is the runner's
    # execution model, and the hub is a resident service with its own update/restart lifecycle.
    return ["cline", prompt, "--json", "--auto-approve", "true",
            "-c", cwd, "-P", "openai-compatible", "-m", model]


def _cline_eof(state: dict, rc: int) -> list[dict]:
    """Synthesize the terminal result if the process dies before its own run_result event.

    cline DOES emit a terminal run_result (unlike opencode), so on a healthy turn this adds
    nothing — _cline_to_claude marks the state done and this returns []. It exists for the
    crash-mid-turn case, where otherwise the trace would end without a result event at all."""
    if state.get("_cl_done"):
        return []
    usage = state.get("_cl_usage") or {}
    err = state.get("_cl_error", "")
    if rc == 0 and not err:
        return [{"type": "result", "subtype": "success", "is_error": False,
                 "result": state.get("final", ""), "usage": usage}]
    return [{"type": "result", "subtype": "error", "is_error": True,
             "result": err or f"cline exited {rc} without reporting a result", "usage": usage}]


def _cline_to_claude(obj: dict, state: dict) -> list[dict]:
    """Map ONE `cline --json` line to zero+ canonical claude stream-json events.

    The emitter writes {ts, type, ...} per line, three types that matter here (verified on 3.0.60
    against a stub upstream, tool round-trip included):

      hook_event   agent_start/tool_call/tool_result/agent_end/agent_error — lifecycle markers;
                   agent_start carries taskId, the only session-ish id the stream has.
      agent_event  {event:{type: iteration_start|content_start|content_update|content_end|usage|
                   iteration_end|done|error}}. content_* carry contentType "text" or "tool";
                   text arrives WHOLE on content_start and again on content_end (chunk-level, not
                   token-level — do not advertise token streaming); tool carries toolName,
                   toolCallId and full input on start, output on end.
      run_result   the terminal event: finishReason, text, usage {inputTokens, outputTokens,
                   cacheReadTokens, cacheWriteTokens}. inputTokens is GROSS — the whole prompt,
                   cached part included — see the run_result branch.
    """
    t = obj.get("type")
    pre: list[dict] = []
    if t == "hook_event":
        if obj.get("hookEventName") == "agent_start" and not state.get("_cl_init"):
            state["_cl_init"] = True
            pre = [{"type": "system", "subtype": "init",
                    "session_id": str(obj.get("taskId") or ""), "model": state.get("model")}]
        return pre
    if t == "agent_event":
        e = obj.get("event") if isinstance(obj.get("event"), dict) else {}
        et = e.get("type")
        ct = e.get("contentType")
        if et == "content_end" and ct == "text":
            txt = e.get("text") or ""
            if not txt:
                return []
            state["final"] = txt        # claude result semantics: the LAST assistant text
            return [{"type": "assistant", "message": {"content": [{"type": "text", "text": txt}]}}]
        if et == "content_end" and ct in ("reasoning", "thinking"):
            txt = e.get("text") or ""
            return ([{"type": "assistant",
                      "message": {"content": [{"type": "thinking", "thinking": txt}]}}]
                    if txt else [])
        if et == "content_start" and ct == "tool":
            return [{"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": e.get("toolCallId") or "tool",
                 "name": e.get("toolName") or "tool", "input": e.get("input") or {}}]}}]
        if et == "content_end" and ct == "tool":
            out = e.get("output")
            body = out if isinstance(out, str) else json.dumps(out or [])
            return [{"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": e.get("toolCallId") or "tool",
                 "content": body}]}}]
        if et == "error":
            err = e.get("error")
            msg = str((err or {}).get("message") or err or "cline error")                 if isinstance(err, (dict, str)) else "cline error"
            state["_cl_error"] = msg
            return []
        return []
    if t == "run_result":
        u = obj.get("usage") or {}
        cache_read = int(u.get("cacheReadTokens") or 0)
        cache_write = int(u.get("cacheWriteTokens") or 0)
        # cline's inputTokens is the whole prompt, cached part included: its own cost formula bills
        # inputTokens - cacheReadTokens - cacheWriteTokens (sdk/packages/llms/src/providers/ai-sdk.ts,
        # calculateCost), and on the openai-compatible provider every turn here runs through it is the
        # sum of each request's prompt_tokens. Measured on 3.0.60 against deepseek-flash: eleven
        # requests summing to inputTokens 135208 / cacheReadTokens 122624, the second of them
        # 6999 / 6400 on a conversation of 6463 tokens so far. The contract is fresh input only
        # (_opencode_usage_add, _pi_usage_add, _norm_token_usage for codex), so net the cached part
        # out here as codex's path does; passed through, the biller charged the cached prefix at the
        # full input rate on top of the cache rate, and cline read as 30x opencode's tokens on the
        # same task.
        usage = {"input_tokens": max(int(u.get("inputTokens") or 0) - cache_read - cache_write, 0),
                 "output_tokens": int(u.get("outputTokens") or 0),
                 "cache_read_tokens": cache_read,
                 "cache_write_tokens": cache_write}
        state["_cl_usage"] = usage
        state["_cl_done"] = True
        reason = str(obj.get("finishReason") or "")
        ok = reason == "completed"
        txt = obj.get("text") or state.get("final", "")
        if ok:
            state["final"] = txt
        return [{"type": "result", "subtype": "success" if ok else "error",
                 "is_error": not ok,
                 "result": txt if ok else (state.get("_cl_error") or txt or f"cline ended: {reason}"),
                 "usage": usage}]
    if t == "error":
        state["_cl_error"] = str(obj.get("message") or "cline error")
        return []
    return []


_cline_to_claude.eof = _cline_eof   # type: ignore[attr-defined]


def _opencode_eof(state: dict, rc: int) -> list[dict]:
    """Synthesize the turn's result at end of stream.

    opencode emits only mid-turn events (text, reasoning, tool_use, step_start, step_finish,
    error); the process exiting is the terminal signal. Status therefore comes from the error
    event and the exit code together, and the final text is the last completed text part.

    A non-zero exit with no error event and no text is the case that produced
    "exit_code=1, no diagnostic output" on a live turn: say so explicitly rather than leaving the
    trace blank."""
    cli = state.get("_cli_name") or "opencode"
    usage = state.get("_oc_usage") or {}
    final = state.get("final", "")
    err = state.get("_oc_error", "")
    if err:
        return [{"type": "result", "subtype": "error", "is_error": True,
                 "result": err, "usage": usage}]
    if rc == 0:
        return [{"type": "result", "subtype": "success", "is_error": False,
                 "result": final, "usage": usage}]
    tools = state.get("_oc_tool_errors") or []
    why = ("; ".join(t for t in tools if t)[:500]
           or f"{cli} exited {rc} without reporting an error")
    return [{"type": "result", "subtype": "error", "is_error": True,
             "result": final or why, "usage": usage}]


OPENCODE_PROVIDERS = {"anthropic", "openai", "azure", "openai-api", "tokenrouter"}

# opencode resolves `{env:VAR}` inside its config at load time, so the provider key is named in
# opencode.json and read from the environment — the same discipline as hermes `key_env`. The key
# itself never lands on disk in the session workspace.
_OPENCODE_KEY_ENV = "HR_OPENCODE_KEY"

# The permission keys opencode actually understands (core/src/v1/config/permission.ts). Enforcement
# is HARD here: the action set is ask|allow|deny, so a denied tool is genuinely absent rather than
# merely discouraged. A key outside this set would be accepted by the record-with-rest schema and
# then silently match no tool, so unknown names are dropped rather than written.
_OPENCODE_PERMS = {"read", "edit", "glob", "grep", "list", "bash", "task", "external_directory",
                   "todowrite", "question", "webfetch", "websearch", "lsp", "doom_loop", "skill"}


def _opencode_denies(tools_disabled: list[str] | None) -> dict:
    """Harness tool ids -> {<key>: "deny"}. Catalog labels arrive "bash (Shell)"-style; keep the id."""
    out: dict = {}
    for raw in tools_disabled or []:
        name = (raw or "").split(" (")[0].strip().lower()
        if name in _OPENCODE_PERMS:
            out[name] = "deny"
    return out


def _opencode_mcp(servers: list[dict] | None) -> dict:
    """opencode `mcp.<name>`: a tagged union on `type`, local => {command:[...]},
    remote => {url, headers}. oauth is pinned false: an interactive OAuth dance has nowhere to
    happen in a sandbox, and leaving it unset invites one.

    Shape taken from the PUBLISHED schema (https://opencode.ai/config.json), not from the repo's
    source tree. The tree is ahead of the release and disagrees with it: source nests servers under
    `mcp.servers` and gives `timeout` an object, the shipped binary wants a flat `mcp.<name>` map."""
    out: dict = {}
    for i, sv in enumerate(servers or []):
        if not isinstance(sv, dict):
            continue
        name = _skill_dir_name(sv.get("name") or sv.get("id") or f"server{i}")
        url = (sv.get("url") or "").strip()
        cmd = sv.get("command")
        if url:
            entry: dict = {"type": "remote", "url": url, "oauth": False}
            hdrs = _mcp_headers(sv)
            if hdrs:
                entry["headers"] = hdrs
        elif cmd:
            argv = cmd if isinstance(cmd, list) else [str(cmd)]
            argv = [str(a) for a in argv] + [str(a) for a in (sv.get("args") or [])]
            entry = {"type": "local", "command": argv}
            envv = sv.get("env")
            if isinstance(envv, dict) and envv:
                entry["environment"] = {str(k): str(v) for k, v in envv.items()}
        else:
            continue
        out[name] = entry
    return out


def _opencode_npm(auth: Auth, model: str, pr: str) -> str:
    """Which ai-sdk package serves this turn: the wire format the connection speaks."""
    if auth.api_format == "anthropic":
        return "@ai-sdk/anthropic"
    if auth.api_format == "openai":
        return "@ai-sdk/openai-compatible"
    if pr == "anthropic" or (pr == "tokenrouter" and _PI_CLAUDE_MODEL.search(model or "")):
        return "@ai-sdk/anthropic"
    if pr == "azure" or _HERMES_RESPONSES_API_MODEL.search(model or ""):
        return "@ai-sdk/openai"          # /v1/responses
    return "@ai-sdk/openai-compatible"   # /v1/chat/completions


def _opencode_config(auth: Auth, model: str, cwd: str, mcp_servers: list[dict] | None,
                     skills_dir: str | None, tools_disabled: list[str] | None = None,
                     pr: str = "") -> str:
    """Write <cwd>/opencode.json and return the provider-qualified model id for --model."""
    if not auth.base_url:
        raise HTTPException(400, "opencode needs a base_url (none configured)")
    # Which ai-sdk package serves this turn. A turn runs exactly ONE model, so this is decided per
    # turn at provider level rather than per model entry — opencode resolves
    # `model.provider?.npm ?? provider.npm ?? "@ai-sdk/openai-compatible"`, so the provider-level
    # value is what a single-model config needs.
    #
    # The split MIRRORS _pi_models_json, because both reach the same relays over the same wire
    # formats: a claude model on an anthropic-native connection speaks Messages, not
    # chat/completions, and sending it to the openai-compatible package fails at the first call.
    # When api_format is set (custom integration), the user's explicit choice wins over any
    # model-family heuristic — the endpoint is the one they told us to reach.
    npm = _opencode_npm(auth, model, pr)
    # Every ai-sdk package appends its own resource to baseURL (@ai-sdk/anthropic "/messages",
    # @ai-sdk/openai "/responses", openai-compatible "/chat/completions") and expects the "/v1"
    # to be there already, the way pi's openai clients do (see _pi_models_json). A connection
    # stored without it (the catalog's own default for a direct Anthropic key is
    # https://api.anthropic.com) sent every opencode turn to https://api.anthropic.com/messages,
    # which Anthropic answers "Not Found" (2026-09-06 support matrix, every claude model; the same
    # key served pi and hermes, which normalise the suffix themselves). A custom endpoint is the
    # user's exact URL and is left alone.
    base = (auth.base_url or "").rstrip("/")
    if not auth.api_format and not base.endswith("/v1"):
        base += "/v1"
    cfg: dict = {
        "$schema": "https://opencode.ai/config.json",
        "provider": {
            "hr": {
                "npm": npm,
                "options": {"baseURL": base, "apiKey": "{env:%s}" % _OPENCODE_KEY_ENV},
                "models": {model: {}},
            }
        },
        # opencode's filesystem snapshots back the TUI's undo/revert; a fresh `run` per turn has
        # no one to undo for, and HarnessRouter's checkpoint is the rollback here. Left on, it is
        # a git repo of the workspace under $HOME — 699 MB of the 1.4 GB tarball in #193.
        "snapshot": False,
    }
    mcp = _opencode_mcp(mcp_servers)
    if mcp:
        cfg["mcp"] = mcp
    denies = _opencode_denies(tools_disabled)
    if denies:
        cfg["permission"] = denies
    if skills_dir:
        # `skills.paths` takes arbitrary directories, so the one _write_skills already produced is
        # named here directly. No mirroring into a per-CLI home, which is the trap codex and hermes
        # set. Shape is {paths, urls} per the published schema; the source tree's bare array is a
        # newer form the released binary rejects outright ("Expected object | undefined").
        cfg["skills"] = {"paths": [skills_dir]}
    # Into .harness/, NOT the workspace root. Produced files are `git status` of the workspace,
    # and a root-level opencode.json showed up as a deliverable on every turn — internal config
    # (relay URL, key env name, /data paths) handed to the user as if the agent had made it.
    # The binary honours OPENCODE_CONFIG (verified on 1.18.23: a config at this path is loaded
    # and reaches the provider); the env var is set in _build_opencode below.
    hdir = pathlib.Path(cwd, ".harness")
    hdir.mkdir(exist_ok=True)
    (hdir / "opencode.json").write_text(json.dumps(cfg, indent=2))
    return f"hr/{model}"


def _opencode_has_session(env: dict, session_id: str) -> bool:
    """Is this opencode session actually in this workspace's database?

    opencode stores conversations in SQLite rather than one file per session, so there is no path
    to stat the way claude's .jsonl or codex's rollout allows. The id is a distinctive token, so
    the check is whether the database bytes contain it — the same shape of evidence as globbing
    for a filename, and schema independent, which matters for a CLI pinned to a preview build.
    Both the main database and its write-ahead log are searched: a session written by the previous
    turn can still be sitting in the WAL.
    """
    home = pathlib.Path(env.get("HOME") or "")
    if not home or not session_id:
        return False
    base = home / ".local" / "share" / "opencode"
    needle = session_id.encode()
    for name in ("opencode.db", "opencode.db-wal"):
        f = base / name
        try:
            if f.exists() and needle in f.read_bytes():
                return True
        except Exception:  # noqa: BLE001 — unreadable is "not there", never a crash
            continue
    return False


def _build_opencode(provider: str, auth: Auth, model: str, prompt: str, cwd: str, env: dict,
                    resume_session_id: str | None = None, mcp_servers: list[dict] | None = None,
                    skills_dir: str | None = None, tools_disabled: list[str] | None = None) -> list[str]:
    pr = provider or "openai-api"
    if pr not in OPENCODE_PROVIDERS:
        raise HTTPException(400, f"unknown opencode provider '{pr}' (one of {sorted(OPENCODE_PROVIDERS)})")
    if auth.base_url and auth.api_key:
        # EVERY keyed turn rides the relay, the Messages shape included. It was left off the relay
        # when the relay read only a bearer; it reads x-api-key now and sends Anthropic's own API
        # the key that way (goose's Messages path, #352), so a direct Anthropic connection no longer
        # hands the CLI — and with it the agent's shell — the real key, and its turns record the
        # served model and usage like every other.
        # Every OpenAI-shape opencode turn rides the loopback relay, as pi's and qwen's do, not only
        # a custom endpoint: request shapes ai-sdk emits but strict endpoints refuse are repaired in
        # flight (Azure's gpt-5.x deployments 400 on max_tokens, captured live 2026-08-27), Gemini
        # 3's thought signatures are replayed (2026-09-06: with a Google key opencode reached Google
        # directly, and every artifact turn on a Gemini 3.x id failed while pi, dsh and qwen passed
        # through the relay), and the real key stays in this process; opencode's env gets a
        # per-turn placeholder.
        relay_base, relay_tok = _hermes_relay_route(auth.base_url, auth.api_key)
        auth = auth.model_copy(update={"base_url": relay_base, "api_key": relay_tok})
    if auth.api_key:
        env[_OPENCODE_KEY_ENV] = auth.api_key
    qualified = _opencode_config(auth, model, cwd, mcp_servers, skills_dir, tools_disabled, pr)
    env["OPENCODE_CONFIG"] = os.path.join(cwd, ".harness", "opencode.json")
    cmd = ["opencode", "run", "--format", "json", "--model", qualified,
           # The sandbox is the trust boundary, so permissions are granted up front: nobody is
           # attached to answer a prompt. Same rationale as pi --approve and claude
           # --dangerously-skip-permissions.
           "--auto",
           # Plugins off. `--pure` empties cfg.plugin_origins (plugin/index.ts:181), and project
           # config is a file IN the workspace: without this a task could write plugin_origins into
           # opencode.json and have the NEXT turn execute it. Same hole pi closes with
           # --no-extensions.
           "--pure",
           # Reasoning parts are emitted ONLY when this flag is set — run.ts gates the emit on
           # `part.type === "reasoning" && part.time?.end && thinking`. Without it the normalizer's
           # reasoning branch is unreachable and thinking silently never reaches the user.
           "--thinking"]
    if resume_session_id and _opencode_has_session(env, resume_session_id):
        cmd += ["--session", resume_session_id]   # continue the prior turn's conversation
    elif resume_session_id:
        # Same guard claude and codex already carry, and for the same reason. opencode keeps its
        # conversations in a SQLite database under $HOME/.local/share/opencode. When that database
        # is not the one the id was written to — the checkpoint did not carry it, the sandbox was
        # recycled, a prior turn died before it was written — `--session <id>` names a session that
        # is not there and opencode exits 1 IMMEDIATELY, before its init event, printing nothing.
        # The runner then reports "opencode exited 1 without reporting an error", and since every
        # later turn passes the same dead id, the conversation is wedged for good rather than for
        # one turn. Starting a fresh CLI thread in the SAME workspace keeps the files and lets the
        # follow-up run.
        print(f"[resume] opencode: session {resume_session_id} not in this workspace — starting fresh",
              flush=True)
    cmd += ["--", prompt] if prompt.startswith("-") else [prompt]
    return cmd


def _opencode_usage_add(state: dict, tk: dict | None) -> None:
    """step-finish carries Session.getUsage()'s `tokens`:
    {total, input, output, reasoning, cache:{read,write}}. `input` is ALREADY cache-exclusive
    (opencode subtracts read+write itself), which is the canonical contract — no adjustment.
    `output` is the visible text ONLY: getUsage (session/session.ts) sets
    `output: outputTokens - reasoningTokens` and carries the reasoning beside it, and bills both
    at the output rate. The contract here is output_tokens = everything the model generated,
    thinking included (pi's `output` is completion_tokens, "already includes reasoning_tokens";
    cline's and dsh's outputTokens are completion_tokens too), so the two are added back
    together. Measured on 1.18.31 against deepseek-flash, one task of 22 requests: opencode's
    rows summed output 7445 / reasoning 10582; the turn record said 7445, and beside pi's 11530
    for the same task the harness read as the cheapest by a factor it had not earned."""
    if not isinstance(tk, dict):
        return
    tot = state.setdefault("_oc_usage", {"input_tokens": 0, "output_tokens": 0,
                                         "cache_read_tokens": 0, "cache_write_tokens": 0})
    cache = tk.get("cache") if isinstance(tk.get("cache"), dict) else {}
    for v, dst in ((tk.get("input"), "input_tokens"), (tk.get("output"), "output_tokens"),
                   (tk.get("reasoning"), "output_tokens"),
                   (cache.get("read"), "cache_read_tokens"), (cache.get("write"), "cache_write_tokens")):
        if isinstance(v, (int, float)):
            tot[dst] += int(v)


def _opencode_to_claude(obj: dict, state: dict) -> list[dict]:
    """Map ONE `opencode run --format json` line to zero+ canonical claude stream-json events.

    The emitter (cli/cmd/run.ts) writes {type, timestamp, sessionID, ...data} per line and emits
    exactly six types: text, reasoning, tool_use, step_start, step_finish, error.

    IMPORTANT — this stream is CHUNK level, not token level. `text` and `reasoning` are emitted
    only once the part is complete (the emitter gates on `part.time?.end`), and `tool_use` only at
    completed/error, never running. So each text event is a whole part and is emitted once: there
    is no delta/tail self-healing to do here, unlike pi or codex. Do not advertise token streaming
    for this backend."""
    t = obj.get("type")
    sid = obj.get("sessionID")
    pre: list[dict] = []
    if sid and not state.get("_oc_init"):
        # Every event carries sessionID, so the session is captured off the first line of the
        # stream rather than from a separate lookup.
        state["_oc_init"] = True
        pre = [{"type": "system", "subtype": "init", "session_id": sid, "model": state.get("model")}]
    part = obj.get("part") if isinstance(obj.get("part"), dict) else {}
    if t == "text":
        txt = part.get("text") or ""
        if not txt:
            return pre
        # claude result semantics: `final` is the LAST assistant text, so a completed part
        # REPLACES it rather than accumulating a mid-run aside into the answer.
        state["final"] = txt
        return pre + [{"type": "assistant", "message": {"content": [{"type": "text", "text": txt}]}}]
    if t == "reasoning":
        txt = part.get("text") or ""
        if not txt:
            return pre
        return pre + [{"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": txt}]}}]
    if t == "tool_use":
        st = part.get("state") if isinstance(part.get("state"), dict) else {}
        if st.get("status") == "error":
            state.setdefault("_oc_tool_errors", []).append(str(st.get("error") or ""))
        # opencode reports a tool once it has finished, with its own clock (state.time, ms): the
        # call is stamped at its start and its result at its end, so the trace shows the seconds
        # the tool actually ran. Stamped at arrival, a 25 s command showed as the 15 s AFTER it.
        tid = part.get("id") or "tool"
        tm = st.get("time") if isinstance(st.get("time"), dict) else {}
        try:
            t_start = float(tm.get("start") or 0) / 1000.0
            t_end = float(tm.get("end") or 0) / 1000.0
        except (TypeError, ValueError):
            t_start = t_end = 0.0
        call = {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": tid, "name": part.get("tool") or "tool", "input": st.get("input") or {}}]}}
        if t_start > 0:
            call["_ts"] = t_start
        if st.get("status") not in ("completed", "error"):
            return pre + [call]
        res = {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": tid, "is_error": st.get("status") == "error",
             "content": str(st.get("output") or st.get("error") or "")}]}}
        if t_end > 0:
            res["_ts"] = max(t_end, t_start)
        return pre + [call, res]
    if t == "step_finish":
        _opencode_usage_add(state, part.get("tokens"))
        return pre
    if t == "error":
        # The CLI can exit 0 on a provider error, so this event is the only truthful failure
        # signal — the same trap pi has.
        # Real shape, captured from a live 401 against the relay:
        #   {"type":"error","sessionID":...,"error":{"name":"APIError",
        #    "data":{"message":"...","statusCode":401,...}}}
        # The message is nested under `data`, so reading `error.message` yields nothing and the
        # user gets a stringified dict. Try the nested form first, then the flat one.
        err = obj.get("error")
        msg = ""
        if isinstance(err, dict):
            data = err.get("data") if isinstance(err.get("data"), dict) else {}
            msg = str(data.get("message") or err.get("message") or err.get("name") or "")
        elif err:
            msg = str(err)
        state["_oc_error"] = msg or f"{state.get('_cli_name') or 'opencode'} error"
        return pre
    return pre


# opencode's stream has no terminal event, so the normalizer carries an `eof` the run loop calls
# when the process exits. See _run_turn_bg.
_opencode_to_claude.eof = _opencode_eof   # type: ignore[attr-defined]


# ── Kilo CLI (Kilo-Org/kilocode, MIT), pinned 7.8.1 ────────────────────────────────────────────
# An opencode fork ("Kilo CLI is a fork of OpenCode", its README): `kilo run --format json` is
# opencode's emitter, the config is opencode's schema read from KILO_CONFIG, and the provider block,
# the MCP map and `skills.paths` are the same shapes. So this backend reuses opencode's package
# choice, MCP translation and normaliser, and differs where Kilo does — every difference below was
# measured on the pinned binary against a logging stub (no provider, no key, no cost):
#   - it phones home unless told not to: us.i.posthog.com (telemetry), models.dev (catalog) and
#     api.kilo.ai (Kilo's own gateway and notifications). The env switches below and
#     `enabled_providers` in the config take all three to zero; each was checked by A/B through a
#     proxy that logged every CONNECT.
#   - it adds scheduling tools that resume the session LATER (schedule_wakeup, cron_*, goal), a
#     contract a one-process-per-turn backend cannot keep, so they are always denied;
#   - `write` and `apply_patch` are gated by the `edit` permission key (permission.disabled maps
#     all three onto it), so only `edit` withholds them — a `write` rule is a silent no-op;
#   - an unknown `--session` fails the run with nothing on stdout, so the store is asked first.

KILO_PROVIDERS = OPENCODE_PROVIDERS
_KILO_KEY_ENV = "HR_KILO_KEY"

# Permission keys that match a tool Kilo 7.8.1 offers the model (the request's `tools`, captured at
# a stub for gpt-5.4 and claude-sonnet-4.6), plus the keys its permission schema names. A deny on
# one of these removes the tool from the request — measured, not assumed. `write`/`apply_patch` are
# deliberately absent: they are edit's (see above), and accepting them would disable nothing.
_KILO_PERMS = {"bash", "read", "edit", "glob", "grep", "list", "task", "webfetch", "websearch",
               "todowrite", "question", "skill", "lsp", "background_process", "kilo_local_recall",
               "board_post", "board_read", "link_pr", "agent_manager", "agent_manager_models",
               "notebook_read", "notebook_edit", "notebook_execute"}

# Tools whose whole promise is a LATER turn the harness starts on its own ("the harness resumes this
# session with the prompt you give it", "the goal loop continues automatically after this turn").
# Here every turn is one process the gateway starts; nothing ever resumes the session unasked, so
# the model would tell the person it will come back and it never would. Always denied.
_KILO_ALWAYS_DENY = ("schedule_wakeup", "cancel_wakeup", "cron_create", "cron_delete", "cron_list",
                     "goal")

# The environment that keeps a turn inside the sandbox's own business. Each one names a request the
# binary otherwise makes (or a place it otherwise reads) on every turn.
_KILO_ENV = {
    "KILO_TELEMETRY_LEVEL": "off",          # PostHog; anything but "all" disables (kilo-telemetry)
    "KILO_DISABLE_MODELS_FETCH": "1",       # models.dev catalog download
    "KILO_DISABLE_AUTOUPDATE": "1",         # a pinned backend never replaces itself
    "KILO_DISABLE_SESSION_INGEST": "1",     # session upload to Kilo's cloud (needs a Kilo login anyway)
    "KILO_NO_DAEMON": "1",                  # never attach a turn to a daemon an earlier task started
    "KILO_DISABLE_CLAUDE_CODE": "1",        # ~/.claude and .claude/skills: another backend's trees
}


def _kilo_npm(auth: Auth, model: str, pr: str) -> str:
    """Which ai-sdk package serves this turn — opencode's choice with ONE clause dropped.

    opencode sends a claude id on an AGGREGATOR (`tokenrouter`, which is how vercel, llmtr,
    tokenrouter and the hosted door are all wired) through `@ai-sdk/anthropic`, and an
    Anthropic-shape turn cannot ride the loopback relay: the relay authenticates a route by the
    placeholder BEARER it handed out, while a Messages client sends `x-api-key`. The turn then runs
    with no relay in front of it, and the consequence is measured: on 2026-09-27/28, in one session
    on integration:vercel, `gpt-5.4-mini` recorded `served_model='openai/gpt-5.4-mini'` and
    `claude-haiku-4.5` recorded `served_model=None` — so rule 2 of docs/harness-verification.md
    could not be evaluated for the claude row at all, and a green row proved nothing about which
    model ran.

    An aggregator serves a claude id over chat/completions perfectly well: cline and qwen reach
    every claude id that way, and minimax measured `anthropic/claude-haiku-4.5` on this same
    provider and model id through the relay on 2026-09-28. So the package choice, not the protocol,
    was the reason the observability surface was dark, and on THIS backend the choice is ours.

    A DIRECT Anthropic connection keeps Messages: `api.anthropic.com` speaks nothing else. Since
    0.29.0 it rides the relay as well (the relay reads x-api-key and sends Anthropic the key that
    way), so its turns record the served model too and the CLI holds a placeholder."""
    if auth.api_format == "anthropic" or pr == "anthropic":
        return "@ai-sdk/anthropic"     # a direct Anthropic endpoint; no relay (see above)
    if auth.api_format == "openai":
        return "@ai-sdk/openai-compatible"
    if pr == "azure" or _HERMES_RESPONSES_API_MODEL.search(model or ""):
        return "@ai-sdk/openai"          # /v1/responses
    return "@ai-sdk/openai-compatible"   # /v1/chat/completions


def _kilo_denies(tools_disabled: list[str] | None) -> dict:
    """Harness tool ids -> {<key>: "deny"}, plus the always-denied scheduling tools. Catalog labels
    arrive "bash (Bash)"-style; the id is kept. Unknown names are dropped rather than written: the
    schema accepts any key, so a wrong one would be stored, reported as off, and match nothing."""
    out: dict = {t: "deny" for t in _KILO_ALWAYS_DENY}
    for raw in tools_disabled or []:
        name = (raw or "").split(" (")[0].strip().lower()
        if name in ("write", "apply_patch"):
            name = "edit"     # the one key that withholds them
        if name in _KILO_PERMS:
            out[name] = "deny"
    if out.get("bash") == "deny":
        # background_process runs shell commands too (`start`/`monitor` take a `command`), so with
        # only bash withheld the shell is still one tool away. Measured 2026-09-27: bash denied, the
        # model's bash call refused as "unavailable tool", background_process still offered.
        out["background_process"] = "deny"
    return out


def _kilo_config(auth: Auth, model: str, cwd: str, mcp_servers: list[dict] | None,
                 skills_dir: str | None, tools_disabled: list[str] | None = None,
                 pr: str = "") -> str:
    """Write <cwd>/.harness/kilo.json and return the provider-qualified model id for --model."""
    if not auth.base_url:
        raise HTTPException(400, "kilo needs a base_url (none configured)")
    base = (auth.base_url or "").rstrip("/")
    if not auth.api_format and not base.endswith("/v1"):
        base += "/v1"   # every ai-sdk package appends its own resource; see _opencode_config
    cfg: dict = {
        "$schema": "https://app.kilo.ai/config.json",
        "provider": {
            "hr": {
                "npm": _kilo_npm(auth, model, pr),
                "options": {"baseURL": base, "apiKey": "{env:%s}" % _KILO_KEY_ENV},
                "models": {model: {}},
            }
        },
        # Only our provider is loaded. Without this Kilo also initialises its own gateway provider
        # and calls api.kilo.ai on every turn, logged in or not (measured: two CONNECTs a turn,
        # zero with this key).
        "enabled_providers": ["hr"],
        "snapshot": False,   # opencode's undo history, the 699 MB half of #193; see _opencode_config
        "permission": _kilo_denies(tools_disabled),
    }
    mcp = _opencode_mcp(mcp_servers)
    if mcp:
        cfg["mcp"] = mcp
    if skills_dir:
        cfg["skills"] = {"paths": [skills_dir]}
    hdir = pathlib.Path(cwd, ".harness")
    hdir.mkdir(exist_ok=True)
    (hdir / "kilo.json").write_text(json.dumps(cfg, indent=2))
    return f"hr/{model}"


def _kilo_has_session(env: dict, session_id: str) -> bool:
    """Is this Kilo session in this workspace's database? Asked of the store, not searched for
    (checklist #10): kilo.db is SQLite with `session(id TEXT PRIMARY KEY, ...)` at 7.8.1, and
    `--session <id>` looks the id up in exactly that table. Read-only; sqlite reads the WAL itself,
    so the previous turn's not-yet-checkpointed write is visible."""
    home = env.get("HOME") or ""
    if not home or not session_id:
        return False
    db_path = pathlib.Path(home) / ".local" / "share" / "kilo" / "kilo.db"
    if not db_path.exists():
        return False
    db = None
    try:
        db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2)
        return db.execute("SELECT 1 FROM session WHERE id = ? LIMIT 1", (session_id,)).fetchone() is not None
    except Exception:  # noqa: BLE001 — no table yet, mid-write, unreadable: "not there"
        return False
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:  # noqa: BLE001
                pass


def _build_kilo(provider: str, auth: Auth, model: str, prompt: str, cwd: str, env: dict,
                resume_session_id: str | None = None, mcp_servers: list[dict] | None = None,
                skills_dir: str | None = None, tools_disabled: list[str] | None = None) -> list[str]:
    pr = provider or "openai-api"
    if pr not in KILO_PROVIDERS:
        raise HTTPException(400, f"unknown kilo provider '{pr}' (one of {sorted(KILO_PROVIDERS)})")
    if auth.base_url and auth.api_key:
        # EVERY keyed turn rides the relay, the Messages shape included. It was left off the relay
        # when the relay read only a bearer; it reads x-api-key now and sends Anthropic's own API
        # the key that way (goose's Messages path, #352), so a direct Anthropic connection no longer
        # hands the CLI — and with it the agent's shell — the real key, and its turns record the
        # served model and usage like every other.
        # opencode's rule, for opencode's reasons: every OpenAI-shape turn rides the loopback
        # relay (shape repairs, Gemini signatures, served model and usage read off the bytes), and
        # the real key stays in this process.
        relay_base, relay_tok = _hermes_relay_route(auth.base_url, auth.api_key)
        auth = auth.model_copy(update={"base_url": relay_base, "api_key": relay_tok})
    if auth.api_key:
        env[_KILO_KEY_ENV] = auth.api_key
    qualified = _kilo_config(auth, model, cwd, mcp_servers, skills_dir, tools_disabled, pr)
    env["KILO_CONFIG"] = os.path.join(cwd, ".harness", "kilo.json")
    env.update(_KILO_ENV)
    cmd = ["kilo", "run", "--format", "json", "--model", qualified,
           "--auto",       # nobody is attached to answer a permission ask; the sandbox is the boundary
           "--pure",       # no external plugins: project config is a file the task itself can write
           "--thinking"]   # reasoning events are emitted only with this flag (run.ts)
    if resume_session_id and _kilo_has_session(env, resume_session_id):
        cmd += ["--session", resume_session_id]
    elif resume_session_id:
        # An unknown id is "Error: Session not found" on stderr, exit 1, and nothing on stdout, and
        # every later turn would pass the same dead id. Start fresh in the same workspace;
        # _resume_lost reads the missing --session and the reply says the history is gone.
        print(f"[resume] kilo: session {resume_session_id} not in this workspace — starting fresh",
              flush=True)
    cmd += ["--", prompt] if prompt.startswith("-") else [prompt]
    return cmd


def _kilo_to_claude(obj: dict, state: dict) -> list[dict]:
    """opencode's normaliser under Kilo's name. The 7.8.1 emitter differs from opencode's in two
    ways the shared code already handles: an error event's `error` may be a bare STRING ("run
    ended without an assistant message; the model returned no output", an auto-rejected
    permission), and the process exits 1 on any error. A provider failure arrives as a structural
    error event (APIError with data.message; measured with a 401 and a 503), never as assistant
    text, so there is no prose prefix to strip."""
    state.setdefault("_cli_name", "kilo")
    return _opencode_to_claude(obj, state)


def _kilo_eof(state: dict, rc: int) -> list[dict]:
    state.setdefault("_cli_name", "kilo")
    return _opencode_eof(state, rc)


_kilo_to_claude.eof = _kilo_eof   # type: ignore[attr-defined]


def _gemini_to_claude(obj: dict, state: dict) -> list[dict]:
    """Map ONE gemini-cli `--output-format stream-json` event to zero+ canonical claude
    stream-json events.

    Field names verified 2026-09 against the shipped 0.58.0 binary's own source (the bundle
    ships de-minified enough to grep: bundle/gemini-*.js, StreamJsonFormatter.emitEvent call
    sites) — not the public docs, which name the event TYPES but publish no field-level JSON
    example. The first version of this function guessed field names from the docs alone and
    every guess for tool_use/tool_result was wrong (id/name/input do not exist on the wire);
    it shipped, ran for real against a live key, and every tool call rendered as a content-free
    "Tool" row — caught from an actual failed turn (slides kit, 2026-09-06), not from re-reading
    the docs harder. Confirmed shapes, straight from the emitEvent() call sites:

        init:        {type, timestamp, session_id, model}
        message:     {type, timestamp, role: "user"|"assistant", content: str, delta?: bool}
        tool_use:    {type, timestamp, tool_name, tool_id, parameters}
        tool_result: {type, timestamp, tool_id, status: "success"|"error", output?,
                      error?: {type, message}}
        result:      {type, timestamp, status: "success"|"error", stats,
                      error?: {type, message}}   — NO text field on success; the final answer
                      only ever arrives via accumulated `message` deltas, same as the one-shot
                      `--output-format json` mode's separate {response, stats, error} shape does
                      NOT apply here.
        error:       {type, timestamp, severity, message} — documented as "non-fatal", and
                      every fatal path in the source emits its OWN terminal `result` event
                      separately (verified: the max-turns-exceeded handler, tool fatal-error
                      handler, and top-level catch all construct `type:"result", status:"error"`
                      themselves) — so this type is informational, not a turn-ending signal, and
                      must not be promoted into a synthetic result the way v1 of this function did.
    """
    t = obj.get("type")
    if t == "init":
        return [{"type": "system", "subtype": "init",
                 "session_id": obj.get("session_id"),
                 "model": obj.get("model") or state.get("model")}]
    if t == "message":
        role = obj.get("role") or "assistant"
        text = obj.get("content") or ""
        if not text:
            return []
        if role == "assistant":
            state["final"] = state.get("final", "") + text
        return [{"type": role, "message": {"content": [{"type": "text", "text": text}]}}]
    if t == "tool_use":
        tuid = obj.get("tool_id") or "tool"
        name = obj.get("tool_name") or "tool"
        return [{"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": tuid, "name": name, "input": obj.get("parameters") or {}}]}}]
    if t == "tool_result":
        tuid = obj.get("tool_id") or "tool"
        err = obj.get("error") if isinstance(obj.get("error"), dict) else None
        content = obj.get("output") or (err or {}).get("message") or ""
        return [{"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": tuid,
             "is_error": obj.get("status") == "error", "content": content}]}}]
    if t == "error":
        return []   # non-fatal by contract; the fatal path always emits its own `result` too
    if t == "result":
        err = obj.get("error") if isinstance(obj.get("error"), dict) else None
        msg = err.get("message") if err else None
        stats = obj.get("stats") if isinstance(obj.get("stats"), dict) else {}
        # The stats are keyed by the model the CLI actually called (convertToStreamStats, 0.58.0),
        # and the CLI rewrites some requested ids on the way (every "-flash" id becomes
        # gemini-3.5-flash on the API-key auth path, measured 2026-09-06): the served model rides
        # the result so the gateway can record a substitution instead of believing the request.
        models = stats.get("models") if isinstance(stats.get("models"), dict) else {}
        served = ",".join(k for k in models if isinstance(k, str) and k)
        # A substitution is a failed turn, not a served one: the model the CLI ran is what the user
        # gets, and a turn that ran another model than the one asked for must say so, never read
        # completed. The settings pin every id to itself; this is the check that they held.
        requested = str(state.get("model") or "")
        other = [m for m in served.split(",") if m and requested and not _same_model(requested, m)]
        if other:
            # the substitution is the more specific cause; the CLI's own error, when it says one, rides along
            tail = f" (the CLI ended with {err.get('type') or 'an error'}: {err.get('message')})" if err and err.get("message") else ""
            err = {"type": "model_substituted", "message": f"the CLI ran {', '.join(other)} instead of {requested}{tail}"}
            msg = err["message"]
        elif err and not msg:
            # an error without a message: name its type, never the answer text (a failed turn whose
            # reason read as the finished answer, 2026-09-07)
            msg = f"the CLI ended the turn with an error ({err.get('type') or 'unknown'})"
        ev = {"type": "result", "subtype": "error" if err else "success", "is_error": bool(err),
              "result": msg or state.get("final", ""), "usage": _gemini_usage(stats)}
        if served:
            ev["model"] = served
        return [ev]
    return [obj]


def _gemini_usage(stats: dict) -> dict:
    """gemini-cli's result stats in the runner's usage contract. Its `input_tokens` is the whole
    prompt INCLUDING the cached part and `cached` is that part (its own `input` is the fresh count
    and agrees), so the fresh input is the difference, the same subtraction the codex path makes;
    without it the cached prefix (8k tokens of system prompt on a one-word turn) would be billed
    at the full input rate."""
    u = _norm_token_usage(stats)
    if isinstance(stats, dict) and isinstance(stats.get("cached"), (int, float)) and stats["cached"] > 0:
        cached = int(stats["cached"])
        u["cache_read_tokens"] = cached
        u["input_tokens"] = max(int(u.get("input_tokens") or 0) - cached, 0)
    return u


# ── goose (aaif-goose/goose, Apache-2.0 — the block/goose repo moved there) ────────────────────
# Every shape below was read off the v1.50.0 source tree the installer pins, never the docs: the
# docs name the stream-json event TYPES and publish no field-level example, which is the exact gap
# that made the first gemini normalizer guess id/name/input and render every tool call as a
# content-free row on a live turn.
GOOSE_PROVIDERS = {"anthropic", "openai", "azure", "openai-api", "tokenrouter"}

# The `developer` platform extension's tools, verbatim from DeveloperClient::get_tools()
# (crates/goose/src/agents/platform_extensions/developer/mod.rs). FIVE, and there is deliberately
# no file-read tool: reading is `shell` (cat) and `tree` lists a directory. Do NOT add a `read`
# here — a name matching no tool is dropped from available_tools below, which disables nothing
# while the console reports the tool as off: the silent no-op the opencode/qwen tables warn about.
# The definition carries unprefixed_tools: true, so the model sees these bare, not developer__x.
ALL_GOOSE_TOOLS = ("write", "edit", "shell", "tree", "read_image")
_GOOSE_DEV_EXT = "developer"

# ONE goose conversation per workspace, under a fixed name.
#
# goose emits no init event — its stream opens straight into `message` — so the id its session
# manager generates is never visible to us, and _run_turn_bg learns a conversation id ONLY from a
# normalized system/init event (it is what becomes the next turn's resume id). A name we choose is
# therefore the only id that can round-trip at all.
#
# It does not have to be unique: every session gets its own workspace, so it gets its own
# GOOSE_PATH_ROOT and its own sessions.db, and two sessions can no more collide here than they can
# in each other's files. Fixed rather than minted also means a restored checkpoint resumes by the
# same name it was written under, which is exactly what the recycle scenario asks for.
_GOOSE_SESSION_NAME = "harness"

# A PROVIDER ERROR ARRIVES AS ASSISTANT PROSE, not as the `error` event.
#
# When the upstream fails mid-turn, goose does not emit StreamEvent::Error: the agent loop catches
# it and pushes an assistant `message` whose text is this prefix plus the provider's sentence, then
# ends the run normally with `complete`. Measured on TokenRouter's 503 ("system disk overloaded")
# during the PR-164 support-matrix column: the turn read `status: completed` and its answer was
# "Ran into this error: Server error: …", so a failed turn reported as a success whose answer was
# the failure — and the next turn in that session answered from a history carrying that prose.
#
# Both prefixes are verbatim in the pinned v1.50.0 executable (`strings goose | grep "Ran into
# this error"` returns exactly these two and nothing else). This is the same shape claude injects
# as "API Error: …" and that _CLAUDE_ERR_RE turns into a failed result; goose gets the same
# treatment for the same reason. The trailing space is not required by the match: only the prefix
# through the colon is pinned, so a formatting change upstream still fails the turn correctly.
_GOOSE_ERR_RE = _re.compile(r"^\s*Ran into this error(?: trying to compact)?:", _re.IGNORECASE)


def _goose_root(cwd: str) -> pathlib.Path:
    """Everything goose keeps, under ONE directory inside the workspace.

    Paths::get_dir (crates/goose/src/config/paths.rs) reads GOOSE_PATH_ROOT first and, when it is
    an ABSOLUTE path, derives config/, data/ and state/ from it; only when it is unset does it fall
    back to the etcetera app-strategy (~/.config/goose on Linux). So one env var places the config
    file, the sessions database and the skills directory at once — no HOME redirection and no guess
    about XDG, which is what every other backend here has to make.

    Inside .harness/ on purpose, and that placement is load-bearing twice over: the directory
    travels in the checkpoint (HARNESS_STATE), which is what makes resume survive a recycled
    sandbox, and _PRODUCED_EXCLUDE_PREFIX already excludes it, so the config and the harness's own
    skill folders are never handed back to the user as deliverables — the trap _opencode_config
    records, where a root-level config file showed up as agent output on every turn."""
    return pathlib.Path(cwd, ".harness", "goose")


def _goose_split_base(base_url: str) -> tuple[str, str]:
    """(OPENAI_HOST, OPENAI_BASE_PATH) for one relay base.

    goose's OpenAI provider takes the endpoint in TWO pieces, not one: OPENAI_HOST is the origin
    and OPENAI_BASE_PATH the path it serves (both ConfigKeys in
    crates/goose-providers/src/openai.rs). Every other OpenAI-shape backend here takes a single
    base_url, so the relay keeps handing out one URL and it is split HERE rather than teaching the
    relay a second shape.

    Handing the whole relay URL to OPENAI_HOST instead would send every turn to
    /v1/v1/chat/completions, which the relay answers 404 with no body — indistinguishable, from the
    trace, from the CLI simply dying."""
    u = urllib.parse.urlsplit((base_url or "").rstrip("/"))
    host = f"{u.scheme}://{u.netloc}" if u.scheme and u.netloc else (base_url or "").rstrip("/")
    path = (u.path or "").strip("/")
    return host, (f"{path}/chat/completions" if path else "chat/completions")


def _goose_extensions(mcp_servers: list[dict] | None, tools_disabled: list[str] | None) -> dict:
    """config.yaml's `extensions` map: key -> {enabled, ...ExtensionConfig} (ExtensionEntry, which
    flattens the config's serde tag into the entry, crates/goose/src/config/extensions.rs).

    PARTIAL ON PURPOSE. A config-load migration seeds an entry for every platform extension this
    map does not mention, using that definition's own default_enabled (crates/goose/src/config/
    migrations.rs), and it PRESERVES available_tools on the entries that are already here. So
    naming `developer` to restrict its tools does not switch off Skills, Todo or Analyze, which is
    what writing a complete map would have done — and what would have silently broken every
    harness skill while every other scenario still passed.

    MCP servers become streamable_http entries rather than the --with-streamable-http-extension
    flag, because that flag's parser takes only a url and `timeout=N` and drops every other k=v
    (parse_streamable_http_extension in goose-cli/src/cli.rs). UHP §4.1 puts headers and auth in
    the contract, and a server that advertises MCP it cannot deliver is exactly what the spec
    forbids — so the config file, which has a real `headers` map, is the only honest door."""
    out: dict = {}
    off = {(raw or "").split(" (")[0].strip().lower() for raw in tools_disabled or []}
    keep = [t for t in ALL_GOOSE_TOOLS if t not in off]
    if off & set(ALL_GOOSE_TOOLS):
        # available_tools is an ALLOWLIST, so it is written only when something is actually
        # disabled: left empty (or absent) every tool is available, which is the default we want.
        out[_GOOSE_DEV_EXT] = {"enabled": True, "type": "platform", "name": _GOOSE_DEV_EXT,
                               "available_tools": keep}
    for i, sv in enumerate(mcp_servers or []):
        if not isinstance(sv, dict):
            continue
        name = _skill_dir_name(sv.get("name") or sv.get("id") or f"server{i}")
        url = (sv.get("url") or "").strip()
        cmd = sv.get("command")
        if url:
            entry: dict = {"enabled": True, "type": "streamable_http", "name": name,
                           "uri": url, "timeout": 300}
            hdrs = _mcp_headers(sv)
            if hdrs:
                entry["headers"] = hdrs
        elif cmd:
            argv = cmd if isinstance(cmd, list) else [str(cmd)]
            argv = [str(a) for a in argv] + [str(a) for a in (sv.get("args") or [])]
            entry = {"enabled": True, "type": "stdio", "name": name,
                     "cmd": argv[0], "args": argv[1:], "timeout": 300}
            envv = sv.get("env")
            if isinstance(envv, dict) and envv:
                entry["envs"] = {str(k): str(v) for k, v in envv.items()}
        else:
            continue
        out[name] = entry
    return out


def _goose_config(root: pathlib.Path, model: str, mcp_servers: list[dict] | None,
                  tools_disabled: list[str] | None, provider: str = "openai") -> None:
    """Write <root>/config/config.yaml fresh each turn — the harness config is the source of truth,
    the same contract the agent doc has, so a stale file never outlives the setting that made it.
    Same writer hermes's config.yaml already uses."""
    cdir = root / "config"
    cdir.mkdir(parents=True, exist_ok=True)
    cfg: dict = {"GOOSE_PROVIDER": provider, "GOOSE_MODEL": model}
    ext = _goose_extensions(mcp_servers, tools_disabled)
    if ext:
        cfg["extensions"] = ext
    (cdir / "config.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))


def _goose_has_session(root: pathlib.Path, name: str) -> bool:
    """Is this goose session actually in this workspace's database?

    goose keeps conversations in SQLite (data/sessions/sessions.db — SESSIONS_FOLDER + DB_NAME in
    crates/goose/src/session/session_manager.rs), so there is no per-session file to stat, and the
    question has to be put to the database.

    ASK IT, do not search its bytes. This was a substring search for the session name over the db
    and its write-ahead log, and that is only as good as the name is distinctive: `harness` also
    occurs in the workspace path (/data/workspaces/<sid>/.harness/...) that tool output and the
    AGENTS.md contract carry, so a database holding one message and no session could match. The
    consequence was bounded but exactly what the check exists to prevent — a false positive adds
    -r and the turn dies on "No session found". The query below cannot be fooled by a path.

    The schema is fixed by the pinned CLI (sessions: id TEXT PRIMARY KEY, name TEXT NOT NULL), and
    get_or_create_session_id matches s.name == name || s.id == name, so this asks precisely what
    the CLI will ask. A drift on a pin bump fails test_session_lookup_asks_the_database rather
    than a live turn. Opened read-only; sqlite reads the WAL itself, so the previous turn's
    not-yet-checkpointed write is visible without naming the -wal file.

    Without this check, `-r -n <name>` against a database that does not hold it fails the turn
    outright ("No session found with name '<name>'", get_or_create_session_id in
    goose-cli/src/cli.rs) — and since every later turn passes the same name, the conversation is
    wedged for good rather than for one turn."""
    if not name:
        return False
    db_path = root / "data" / "sessions" / "sessions.db"
    if not db_path.exists():
        return False
    db = None
    try:
        db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2)
        row = db.execute("SELECT 1 FROM sessions WHERE name = ? OR id = ? LIMIT 1",
                         (name, name)).fetchone()
        return row is not None
    except Exception:  # noqa: BLE001 — no table yet, mid-write, unreadable: "not there"
        return False
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:  # noqa: BLE001
                pass


def _build_goose(provider: str, auth: Auth, model: str, prompt: str, cwd: str, env: dict,
                 resume_session_id: str | None = None, mcp_servers: list[dict] | None = None,
                 tools_disabled: list[str] | None = None, max_turns: int | None = None) -> list[str]:
    pr = provider or "openai-api"
    if pr not in GOOSE_PROVIDERS:
        raise HTTPException(400, f"unknown goose provider '{pr}' (one of {sorted(GOOSE_PROVIDERS)})")
    if not auth.base_url:
        raise HTTPException(400, "goose needs a base_url (none configured)")
    if auth.api_key:
        # EVERY goose turn rides the loopback relay, as qwen's and cline's do: request shapes
        # strict endpoints refuse are repaired in flight, and the real key never enters the CLI's
        # environment — which matters here because goose takes its credential ONLY via env.
        relay_base, relay_tok = _hermes_relay_route(auth.base_url, auth.api_key)
        auth = auth.model_copy(update={"base_url": relay_base, "api_key": relay_tok})
    root = _goose_root(cwd)
    root.mkdir(parents=True, exist_ok=True)
    host, base_path = _goose_split_base(auth.base_url or "")
    env["GOOSE_PATH_ROOT"] = str(root)
    native = _anthropic_native(pr, auth)
    if native:
        # goose's own anthropic provider: ANTHROPIC_HOST is an origin and the provider joins
        # /v1/messages onto it, the key rides x-api-key, and the request carries goose's cache
        # breakpoints. Through the relay like the OpenAI path (the relay reads x-api-key and
        # sends the key the way Anthropic takes it). Until 2026-09-30 an Anthropic endpoint drove
        # goose over its OpenAI-compatible surface, which cannot cache: a benchmark's audit task
        # cost $15.80 on goose against $2.08 on Claude Code for the same model.
        env["ANTHROPIC_API_KEY"] = auth.api_key or ""
        env["ANTHROPIC_HOST"] = host
    else:
        env["OPENAI_API_KEY"] = auth.api_key or ""
        env["OPENAI_HOST"] = host
        env["OPENAI_BASE_PATH"] = base_path
    # The sandbox is the trust boundary, so tools are approved up front: nobody is attached to
    # answer a prompt. Same rationale as claude --dangerously-skip-permissions, pi --approve and
    # opencode --auto. NOTE this does NOT weaken disabled tools: auto returns Allow before the
    # permission table is consulted (permission_inspector.rs), but a tool left out of
    # available_tools is never put in the model's tool list at all (extension_manager.rs's
    # fetch_all_tools gates on config.is_tool_available), so the two are independent.
    env["GOOSE_MODE"] = "auto"
    # Otherwise every turn pays an extra background model call to invent a session name we never
    # read — the name is ours, set with -n below.
    env["GOOSE_DISABLE_SESSION_NAMING"] = "true"
    _goose_config(root, model, mcp_servers, tools_disabled, provider="anthropic" if native else "openai")
    # -n names the session on a fresh run and selects it on a resume (get_or_create_session_id
    # matches s.name == name || s.id == name), so it is the handle in both directions and nothing
    # has to be read back out of the stream. --session-id is NOT usable here: it sits in the same
    # clap group, which is multiple = false, and it is rejected outright without --resume.
    cmd = ["goose", "run", "--output-format", "stream-json", "--model", model,
           "-n", _GOOSE_SESSION_NAME, "-t", prompt]
    if max_turns:
        # The harness's step budget, which the gateway sends as max_turns (its max_step, default
        # 40). goose's own default is 1000, so without this the budget an operator set is ignored
        # by a factor of 25 and a looping task runs to goose's ceiling instead of theirs. Same
        # knob claude takes as --max-turns and hermes as agent.max_turns in its config.
        cmd += ["--max-turns", str(int(max_turns))]
    if resume_session_id:
        if _goose_has_session(root, _GOOSE_SESSION_NAME):
            cmd += ["-r"]
        else:
            # Same guard claude and opencode carry. The conversation is not in this workspace —
            # the checkpoint did not carry it, the sandbox was recycled, a prior turn died before
            # it was written — so start a fresh thread in the SAME workspace, which keeps the
            # files and lets the follow-up run, and say so (see _resume_lost) rather than
            # answering "there is no earlier message" as a completed turn. Passing -r anyway would
            # fail the turn outright: goose errors "No session found with name".
            print(f"[resume] goose: session {_GOOSE_SESSION_NAME} not in this workspace "
                  f"(asked for {resume_session_id}) — starting fresh", flush=True)
    return cmd


def _goose_usage(ev: dict) -> dict:
    """goose's terminal `complete` event in the runner's usage contract.

    Its cache counters are cache_read_input_tokens / cache_write_input_tokens (StreamEvent
    ::Complete, goose-cli/src/session/mod.rs). _norm_token_usage's picker already knows the READ
    name, but its write list carries cacheWriteInputTokens in camel and NOT the snake form goose
    emits — so the cache-write count would be silently dropped and billed as nothing. Named here
    rather than widened in the shared picker, the same way _gemini_usage handles gemini's `cached`.

    Whether `input_tokens` is gross (cache read included) or net is the provider's choice and goose
    passes it straight through (MessageUsage::from_provider_usage), so NO subtraction is made here
    until a live turn says one is needed — inventing one would under-report input on a provider
    that already reports net, which is the mirror of the bug the subtraction exists to fix."""
    u = _norm_token_usage(ev)
    w = ev.get("cache_write_input_tokens") if isinstance(ev, dict) else None
    if isinstance(w, (int, float)) and w:
        u["cache_write_tokens"] = int(w)
    return u


def _goose_to_claude(obj: dict, state: dict) -> list[dict]:
    """Map ONE `goose run --output-format stream-json` line to zero+ canonical claude events.

    Shapes verified 2026-09-11 against the v1.50.0 source the installer pins (StreamEvent and
    emit_stream_event in crates/goose-cli/src/session/mod.rs; Message, MessageContentBlock and
    tool_result_serde in crates/goose-provider-types/src/conversation/). One JSON object per line.

    TWO NAMING CONVENTIONS IN ONE STREAM, and getting either wrong is silent:
      - the top-level event tag is snake_case  (#[serde(tag="type", rename_all="snake_case")]):
            message | notification | error | complete
      - the content-block tag is camelCase     (#[serde(tag="type", rename_all="camelCase")]):
            text | thinking | redactedThinking | toolRequest | toolResponse | error

        message:      {type, message:{id, role:"user"|"assistant", created, content:[…], metadata}}
        toolRequest:  {type:"toolRequest", id, toolCall:{status:"success", value:{name, arguments}}}
                      — the call is TWO levels down, under toolCall.value, and `status` is Rust's
                      Result rendered by tool_result_serde: on failure it is
                      {status:"error", error:"<string>"}, a string and not an object.
        toolResponse: {type:"toolResponse", id, toolResult:{status, value:<CallToolResult>}}
        complete:     {type:"complete", total_tokens, input_tokens, output_tokens,
                       cache_read_input_tokens, cache_write_input_tokens, cost_usd}
                      — terminal, and carries NO text: the answer is only ever the accumulated
                      assistant text, the same as gemini's result event.
        error:        {type:"error", error:"<string>"} — emitted by handle_agent_error, which also
                      ends the run, so unlike gemini's non-fatal `error` this one IS terminal.
                      NOT the only way a turn fails: a provider error is narrated as assistant
                      text instead, and only _GOOSE_ERR_RE catches that one.

    The served model rides message.metadata.inference: {provider, requestedModel, resolvedModel}
    (InferenceMetadata, camelCase). That is a per-message statement of what the provider actually
    ran, so a substitution is visible without inferring it from usage stats the way gemini's is."""
    t = obj.get("type")
    if t == "message":
        msg = obj.get("message") if isinstance(obj.get("message"), dict) else {}
        role = msg.get("role") or "assistant"
        meta = msg.get("metadata") if isinstance(msg.get("metadata"), dict) else {}
        inf = meta.get("inference") if isinstance(meta.get("inference"), dict) else {}
        served = str(inf.get("resolvedModel") or "")
        if served:
            state["_goose_served"] = served
        out: list[dict] = []
        if not state.get("_goose_init"):
            # goose emits no init of its own, so one is synthesized off the first message. It MUST
            # carry a session id: _run_turn_bg records the conversation id only from this event,
            # and that recorded id is what the next turn resumes with — without it every follow-up
            # would silently start a new conversation.
            state["_goose_init"] = True
            out.append({"type": "system", "subtype": "init",
                        "session_id": _GOOSE_SESSION_NAME,
                        "model": served or state.get("model")})
        for c in (msg.get("content") if isinstance(msg.get("content"), list) else []):
            if not isinstance(c, dict):
                continue
            ct = c.get("type")
            if ct == "text":
                txt = c.get("text") or ""
                if not txt:
                    continue
                if role == "assistant" and _GOOSE_ERR_RE.match(txt):
                    # The provider failed and goose narrated it instead of raising it (see
                    # _GOOSE_ERR_RE). It is the turn's cause of death, not its answer: record it
                    # so `complete` yields subtype error, and drop the block rather than let it
                    # become `final` and be reported as what the model said. Dropping matches
                    # _strip_claude_error_text — the reason still reaches the caller, as the
                    # failed result's `result`.
                    state["_goose_error"] = txt.strip()[:400]
                    continue
                if role == "assistant":
                    # Each message carries a WHOLE text part (there is no delta flag on this
                    # stream), and claude's result semantics take the last assistant text as the
                    # answer, so a completed part replaces rather than accumulates — the same
                    # choice _opencode_to_claude makes and for the same reason.
                    state["final"] = txt
                out.append({"type": role, "message": {"content": [{"type": "text", "text": txt}]}})
            elif ct == "thinking":
                th = c.get("thinking") or ""
                if th:
                    out.append({"type": "assistant",
                                "message": {"content": [{"type": "thinking", "thinking": th}]}})
            elif ct == "toolRequest":
                call = c.get("toolCall") if isinstance(c.get("toolCall"), dict) else {}
                val = call.get("value") if isinstance(call.get("value"), dict) else {}
                if call.get("status") == "error":
                    state.setdefault("_goose_tool_errors", []).append(str(call.get("error") or ""))
                    continue
                out.append({"type": "assistant", "message": {"content": [
                    {"type": "tool_use", "id": c.get("id") or "tool",
                     "name": val.get("name") or "tool",
                     "input": val.get("arguments") or {}}]}})
            elif ct == "toolResponse":
                res = c.get("toolResult") if isinstance(c.get("toolResult"), dict) else {}
                is_err = res.get("status") == "error"
                if is_err:
                    body = str(res.get("error") or "")
                else:
                    # CallToolResult is MCP's own shape: {content:[{type:"text", text}], …}
                    val = res.get("value") if isinstance(res.get("value"), dict) else {}
                    parts = val.get("content") if isinstance(val.get("content"), list) else []
                    body = "".join(p.get("text") or "" for p in parts if isinstance(p, dict))
                out.append({"type": "user", "message": {"content": [
                    {"type": "tool_result", "tool_use_id": c.get("id") or "tool",
                     "is_error": is_err, "content": body}]}})
            elif ct == "error":
                state["_goose_error"] = str(c.get("message") or "goose error")
        return out
    if t == "error":
        # handle_agent_error emits this and then ends the run, so it is the turn's cause of death
        # and not an aside — the opposite of gemini's `error`, which is non-fatal by contract.
        state["_goose_error"] = str(obj.get("error") or "goose error")
        return []
    if t == "complete":
        state["_goose_completed"] = True   # the eof handler must not emit a second result
        err = state.get("_goose_error") or ""
        ev = {"type": "result", "subtype": "error" if err else "success", "is_error": bool(err),
              "result": err or state.get("final", ""), "usage": _goose_usage(obj)}
        served = state.get("_goose_served")
        if served:
            ev["model"] = served
        return [ev]
    return []   # notification: progress/log noise, nothing to render


def _goose_eof(state: dict, rc: int) -> list[dict]:
    """A run that ended without its `complete` event — the CLI died, was killed, or failed before
    the agent loop started. `complete` is emitted only on the normal path, so without this the turn
    would end with no result event at all and read as "finished, said nothing"."""
    if state.get("_goose_completed"):
        return []
    err = state.get("_goose_error") or ""
    tools = state.get("_goose_tool_errors") or []
    if not err and rc == 0:
        return [{"type": "result", "subtype": "success", "is_error": False,
                 "result": state.get("final", ""), "usage": {}}]
    why = "; ".join(t for t in tools if t)[:500] or f"goose exited {rc} without reporting an error"
    # A reported error outranks whatever text arrived before it: the turn died of that, and it is
    # the same answer `complete` would have given had the run reached it.
    return [{"type": "result", "subtype": "error", "is_error": True,
             "result": err or state.get("final") or why, "usage": {}}]


_goose_to_claude.eof = _goose_eof   # type: ignore[attr-defined]


# Goose 1.50.0 sends extension startup failures to stderr, not stream-json. The
# turn can still complete successfully without that extension, so the generic
# failure-only stderr tail would otherwise hide the missing MCP tools.
_GOOSE_EXTENSION_START_FAILURE = re.compile(
    r"Failed to start extension '([^'\r\n]{1,80})' \(.*\), continuing without it$"
)


def _goose_mcp_startup_failure(line: str) -> str:
    match = _GOOSE_EXTENSION_START_FAILURE.search(line)
    return match.group(1) if match else ""


# aider has NO conversation id of ANY kind — its continuation is the chat-history FILE — so the
# runner announces a synthetic one. Without it the gateway never records a conversation id, never
# treats a later turn as a follow-up, and every turn is a fresh thread: measured as the support
# matrix's recycle scenario failing on every aider row while first/follow-up/switch passed, because
# those three never ask the agent to remember anything.
_AIDER_SESSION_NAME = "harness"
# aider's in-chat command advice in a failure message: the line, and the heading it sits under
# when nothing else is left of that list.
_AIDER_CHAT_ADVICE = re.compile(r"^[ \t]*-?[ \t]*Use /\w+[^\n]*\n?", re.M)


# ── aider ────────────────────────────────────────────────────────────────────────
# The turn process is runner/aider_driver.py inside the pinned aider venv: aider is driven IN
# PROCESS through its own `main(..., return_coder=True)` entry point, and the driver re-emits what
# it observes as NDJSON — the dsh_driver shape ({"m": method, "p": payload}).
#
# THIS IS NOT A STYLE CHOICE. aider has no machine-readable output mode, and its stdout is one
# channel carrying the model's prose and aider's own diagnostics together. Measured on 0.86.2: a
# stub returning model prose whose second line began `litellm.AuthenticationError:` was
# BYTE-IDENTICAL on stdout to a real 401 on the same stream, same exit code 0, no colour under
# --no-pretty. A text-parsing normaliser would therefore report real answers as provider failures,
# which is worse than reporting nothing. In process the channels are separate at the source:
# io.tool_error carries failures, io.assistant_output carries prose, and `coder.usage_report` is
# None exactly when no completion came back.
def _aider_to_claude(obj: dict, state: dict) -> list[dict]:
    m = obj.get("m")
    p = obj.get("p") if isinstance(obj.get("p"), dict) else {}
    if not state.get("_aider_init"):
        # _run_turn_bg records the conversation id ONLY from a system/init event, and that recorded
        # id is what makes the next turn a follow-up rather than a new thread.
        state["_aider_init"] = True
        return ([{"type": "system", "subtype": "init", "session_id": _AIDER_SESSION_NAME,
                  "model": state.get("model")}]
                + _aider_event(obj, state, m, p))
    return _aider_event(obj, state, m, p)


def _aider_event(obj: dict, state: dict, m, p) -> list[dict]:
    if m == "text":
        txt = str(p.get("text") or "")
        if not txt.strip():
            return []
        state["final"] = txt
        # One event per response, a whole response each, and the console joins consecutive
        # text blocks as they come: without the blank line a closing fence ran into the next
        # response's first sentence and the rest of the turn rendered inside a code block
        # (2026-09-19). A paragraph break keeps each response its own markdown.
        return [{"type": "assistant", "message": {"content": [{"type": "text", "text": txt.rstrip() + "\n\n"}]}}]
    if m == "error":
        # Reached io.tool_error, which the model's prose cannot reach. Recorded, NOT rendered: it is
        # the turn's failure reason, not part of its answer. aider's advice about its own in-chat
        # commands (`- Use /drop …`, `- Use /clear …`, base_coder.py show_exhausted_error) is cut,
        # the same rule kimi's "To resume this session:" line earned: this product has no such
        # commands, and a reason that names them sends the user looking for a prompt that is not
        # there.
        state["_aider_error"] = _AIDER_CHAT_ADVICE.sub("", str(p.get("text") or "")).strip()
        return []
    if m == "warning":
        state.setdefault("_aider_warnings", []).append(str(p.get("text") or ""))
        return []
    if m == "shell_decision":
        # A command the model proposed. An approved one renders as a call whose result arrives on
        # the following shell_result; a REFUSED one is a complete pair here and now, because the
        # policy is the whole of its result and nothing ran.
        tuid = f"sh{len(state.setdefault('_aider_calls', []))}"
        state["_aider_calls"].append(tuid)
        call = {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": tuid, "name": str(p.get("tool") or "Shell"),
             "input": {"command": str(p.get("command") or "")}}]}}
        if p.get("approved"):
            state["_aider_last_call"] = tuid
            return [call]
        return [call, {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": tuid, "is_error": True,
             "content": str(p.get("reason") or "refused by the harness tool policy")}]}}]
    if m == "shell_result":
        tuid = state.get("_aider_last_call") or "sh0"
        return [{"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": tuid, "is_error": False,
             "content": str(p.get("output") or "")}]}}]
    if m == "edits":
        # Files aider's edit engine wrote this pass, one card each, the way every other base's
        # file edits render. The SEARCH/REPLACE markup that produced them is aider's wire format,
        # not the answer, and the driver strips it from the text.
        out: list[dict] = []
        for f in p.get("files") or []:
            tuid = f"ed{len(state.setdefault('_aider_calls', []))}"
            state["_aider_calls"].append(tuid)
            out.append({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": tuid, "name": "Edit", "input": {"file_path": str(f)}}]}})
            out.append({"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": tuid, "is_error": False, "content": "edited"}]}})
        return out
    if m == "result":
        # THE DRIVER'S VERDICT IS THE VERDICT. It holds the Coder and knows whether an error was
        # the last thing that happened or one the turn recovered from; this side only sees that
        # an error event passed. Failing here on any recorded error re-failed the recovered turns
        # (gpt-5.4 wrote an edit aider refused, was told, wrote it again, aider applied it, and
        # the record said "did not conform to the edit format", hr-test 2026-09-19).
        err = state.get("_aider_error") or ""
        ok = bool(p.get("ok"))
        final = str(p.get("final") or state.get("final") or "")
        if ok:
            state["final"] = final
        # usage is {} deliberately: per the 2026-09-13 decision no harness PR builds its own usage
        # pipeline. aider's own numbers would be the wrong ones anyway — with streaming it fills the
        # real field names with a tiktoken ESTIMATE (587 against a true 595, measured), and it reads
        # cache under names an OpenAI-shaped response never carries. _relay_usage stamps these rows.
        return [{"type": "result", "subtype": "success" if ok else "error", "is_error": not ok,
                 "result": final if ok else (err or p.get("reason") or ""), "usage": {}}]
    return []


def _aider_eof(state: dict, rc: int) -> list[dict]:
    """The driver emits its own result event, so this fires only when the process died before
    reaching it — a crash, a kill, an import failure. The reason then comes from io.tool_error if
    anything got that far, and otherwise from the errbuf tail _failure_reason prefers."""
    err = state.get("_aider_error") or ""
    if rc == 0 and not err:
        return [{"type": "result", "subtype": "success", "is_error": False,
                 "result": state.get("final", ""), "usage": {}}]
    return [{"type": "result", "subtype": "error", "is_error": True, "result": err, "usage": {}}]


_aider_to_claude.eof = _aider_eof   # type: ignore[attr-defined]


# ── cheetahclaws ───────────────────────────────────────────────────────────────
# One driver line → claude stream-json. The driver emits `__hr_init` first (the session id it
# loaded or minted), then the loop's events AS THEY ARE YIELDED — `text` is a streamed delta, so the
# console renders the answer while it is written — and `__hr_result` last, carrying the driver's
# verdict. The verdict is structural (see cheetahclaws_driver.verdict): nothing here reads prose to
# decide whether the turn failed. The CLI's own notices (`[Retry 1/3 …]`, `[Failed — …]`) arrive as
# `notice` and are never rendered as the answer; the last `[Failed — …]` is the failure's reason.
_CHEETAHCLAWS_ERR_RE = re.compile(r"^\s*\[?Failed — ")


def _cheetahclaws_to_claude(obj: dict, state: dict) -> list[dict]:
    m = obj.get("m")
    p = obj.get("p") if isinstance(obj.get("p"), dict) else {}
    if m == "__hr_init":
        state["_cc_init"] = True
        return [{"type": "system", "subtype": "init", "session_id": str(p.get("session_id") or ""),
                 "model": state.get("model")}]
    if m == "text":
        txt = str(p.get("text") or "")
        if not txt:
            return []
        state["_cc_text"] = state.get("_cc_text", "") + txt
        return [{"type": "assistant", "message": {"content": [{"type": "text", "text": txt}]}}]
    if m == "thinking":
        txt = str(p.get("text") or "")
        return [{"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": txt}]}}] if txt else []
    if m == "tool_start":
        # A new call ends the text before it: the next text is a new paragraph, not a run-on of
        # the sentence that announced the call.
        if state.get("_cc_text") and not state["_cc_text"].endswith("\n"):
            state["_cc_text"] += "\n\n"
        return [{"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": str(p.get("id") or ""), "name": str(p.get("name") or ""),
             "input": p.get("input") if isinstance(p.get("input"), dict) else {}}]}}]
    if m == "tool_end":
        result = str(p.get("result") or "")
        # The loop's own rule for an errored tool result (agent.py, its loop guard): a denial, or a
        # result that opens with "error"/"denied".
        head = result.lstrip()[:24].lower()
        err = (not p.get("permitted", True)) or head.startswith("error") or head.startswith("denied")
        return [{"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": str(p.get("id") or ""), "is_error": err,
             "content": result}]}}]
    if m == "notice":
        state.setdefault("_cc_notices", []).append(str(p.get("text") or ""))
        return []
    if m == "mcp_unavailable":
        # The CLI leaves a server that did not connect out of the turn and says nothing; the
        # gateway renders this as a note on the reply, as it does for kimi.
        servers = [s for s in (p.get("servers") or []) if isinstance(s, dict) and s.get("name")]
        return [{"type": "system", "subtype": "mcp_unavailable", "servers": servers}] if servers else []
    if m == "warning":
        state.setdefault("_cc_warnings", []).append(str(p.get("text") or ""))
        return []
    if m == "__hr_result":
        ok = bool(p.get("ok"))
        sub = str(p.get("subtype") or ("success" if ok else "error"))
        final = str(p.get("final") or "")
        if ok or sub == "error_max_turns":
            state["final"] = final
        # usage is {} on purpose: the relay's taps count what the provider reported (fresh, cached
        # and output tokens) and _run_turn_bg stamps them; the CLI's own totals are gross prompt
        # tokens with no cache split.
        return [{"type": "result", "subtype": sub, "is_error": not ok and sub != "error_max_turns",
                 "result": final if (ok or final) else str(p.get("reason") or ""),
                 "usage": {}}]
    return []


def _cheetahclaws_eof(state: dict, rc: int) -> list[dict]:
    """The driver emits its own result, so this fires only when it died before reaching it (an
    import failure, a kill). The reason is the last `[Failed — …]` notice if one got that far, and
    otherwise the errbuf tail _failure_reason prefers."""
    failed = [n for n in state.get("_cc_notices") or [] if _CHEETAHCLAWS_ERR_RE.match(n)]
    err = failed[-1].strip().strip("[]") if failed else ""
    if rc == 0 and not err and state.get("_cc_text"):
        return [{"type": "result", "subtype": "success", "is_error": False,
                 "result": state.get("_cc_text", ""), "usage": {}}]
    return [{"type": "result", "subtype": "error", "is_error": True, "result": err, "usage": {}}]


_cheetahclaws_to_claude.eof = _cheetahclaws_eof   # type: ignore[attr-defined]


# ── kimi ─────────────────────────────────────────────────────────────────────────


OPENHANDS_PROVIDERS = {"anthropic", "openai", "azure", "openai-api", "tokenrouter"}
# A field litellm sends on its own initiative, the kimi precedent: for an id its registry knows as
# Anthropic's (the provider-native `claude-haiku-4-5-20251001` a custom connection resolves to)
# it puts BOTH `max_tokens` and `max_completion_tokens` on the request, the same 64,000 in each,
# and Anthropic's OpenAI-compatible endpoint answers "Setting 'max_tokens' and
# 'max_completion_tokens' at the same time is not supported" (captured with a sink in the venv
# and against the live endpoint, 2026-09-19; every other id carries the second field alone, and
# every provider on the matrix takes it). The harness never asked for either; the one every
# provider takes stays.
_OPENHANDS_DROP_FIELDS = ("max_tokens",)
OPENHANDS_PYTHON = os.environ.get("HR_OPENHANDS_PYTHON",
                                  "/data/agent-tools/openhands-venv/bin/python")
OPENHANDS_DRIVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "openhands_driver.py")

# ── systemone: the System One Harness (github.com/HarnessRouter/SystemOneHarness, Apache-2.0) ──
# A loop over a decision model rather than a coding CLI: TypeSafe's Jev answers typed questions with
# probabilities and writes no text, so the harness compiles the environment's actions into one
# request per step and gates the answer by the action's risk. The turn process is
# runner/systemone_driver.py; the model id reaches the provider verbatim (`typesafe/jev-1.13`).
SYSTEMONE_DEFAULT_MODEL = os.environ.get("SYSTEMONE_DEFAULT_MODEL", "typesafe/jev-1.13")
SYSTEMONE_PROVIDERS = {"openrouter", "typesafe"}
SYSTEMONE_PYTHON = os.environ.get("HR_SYSTEMONE_PYTHON",
                                  "/data/agent-tools/systemone-venv/bin/python")
SYSTEMONE_DRIVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "systemone_driver.py")


def _systemone_relay_route(provider: str, base_url: str, api_key: str) -> tuple[str, str]:
    """Register one systemone turn's upstream; -> (relay base for the driver, placeholder bearer).

    OpenRouter serves decisions at /api/alpha/decisions and NOWHERE under /api/v1 (404 on the
    versioned path, measured 2026-09-19), so the route's base is the connection's API root with its
    version segment removed: the driver posts to <relay>/v1/alpha/decisions, the relay drops the
    /v1 it joins on and reaches https://openrouter.ai/api/alpha/decisions. TypeSafe's own endpoint
    is /v1/systemone, under the version, so that base keeps it. The relay reads the served model
    and the usage off the answer as it does for every backend: Jev's body names `model` and
    carries `usage.input_tokens` / `output_tokens`, both shapes the relay already parses."""
    base = (base_url or "").rstrip("/")
    if provider == "openrouter":
        base = re.sub(r"/v\d+[a-z]*$", "", base)
    else:
        base = _relay_base_with_version(base)
    with _HERMES_RELAY["lock"]:
        if _HERMES_RELAY["server"] is None:
            srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _HermesRelayHandler)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            _HERMES_RELAY["server"], _HERMES_RELAY["port"] = srv, srv.server_address[1]
        tok = "hr-relay-" + uuid.uuid4().hex
        _HERMES_RELAY["routes"][tok] = (base, api_key, {})
    return f"http://127.0.0.1:{_HERMES_RELAY['port']}/v1", tok


def _build_systemone(provider: str, auth: Auth, model: str, prompt: str, cwd: str, env: dict,
                     resume_session_id: str | None = None, mcp_servers: list[dict] | None = None,
                     tools_disabled: list[str] | None = None, max_turns: int | None = None,
                     timeout_seconds: int | None = None, agent_doc: str = "",
                     metadata: dict | None = None) -> list[str]:
    """The System One Harness, one turn: the job rides argv as JSON, the driver emits claude-shaped
    stream-json. The harness's MCP servers ARE the environment (the first one; the driver says so
    in the trace when there are more); with none, the built-in order desk. `tools_disabled` are
    actions withheld by omission from what the model is offered, the hardest enforcement there is.
    `agent_doc` is the harness's instructions and travels in the job, not as a file: this backend
    reads no workspace. The key rides the relay, like every backend; the driver holds a placeholder,
    and it is in the environment as well as the job so the served-model and usage taps find the
    route."""
    pr = provider or "openrouter"
    if pr not in SYSTEMONE_PROVIDERS:
        raise HTTPException(400, f"unknown systemone provider '{pr}' (one of {sorted(SYSTEMONE_PROVIDERS)})")
    if not auth.base_url:
        raise HTTPException(400, "systemone needs a base_url (none configured)")
    if auth.api_key:
        relay_base, relay_tok = _systemone_relay_route(pr, auth.base_url, auth.api_key)
        auth = auth.model_copy(update={"base_url": relay_base, "api_key": relay_tok})
    env["SYSTEMONE_API_KEY"] = auth.api_key or ""
    job = {"cwd": cwd, "model": model, "prompt": prompt, "provider": pr,
           "base_url": auth.base_url, "api_key": auth.api_key,
           "resume_session_id": resume_session_id,
           "mcp_servers": [s for s in (mcp_servers or []) if (s or {}).get("url") or (s or {}).get("command")],
           "tools_disabled": list(tools_disabled or []),
           "max_turns": max_turns, "timeout_seconds": timeout_seconds,
           "agent_doc": agent_doc or "", "metadata": metadata or None}
    return [SYSTEMONE_PYTHON, SYSTEMONE_DRIVER, json.dumps(job)]


def _openhands_mcp_config(mcp_servers: list[dict] | None) -> dict:
    """The declared servers as the SDK's `Agent.mcp_config`: {name: MCPServer}.

    This base needs no bridge — unlike aider, which ships no MCP client at all — because the agent
    server's own SDK takes the servers on the agent and dials them itself. Its MCPServer accepts
    `url`/`transport`/`headers` and the stdio trio `command`/`args`/`env`, so the harness's
    declaration maps across one field at a time and nothing is invented here.

    THE DECLARED TRANSPORT TRAVELS, the rule #191's review set for kimi: the harness says what a
    server speaks and the url's spelling decides nothing. The SDK's own values are
    stdio / http / streamable-http / sse, and anything else is dropped rather than guessed at —
    a server dialled with the wrong protocol cannot answer, and a config the SDK rejects would
    fail the whole turn rather than the one server.
    """
    out: dict = {}
    for i, sv in enumerate(mcp_servers or []):
        if not isinstance(sv, dict):
            continue
        name = _skill_dir_name(sv.get("name") or sv.get("id") or f"server{i}")
        url = (sv.get("url") or "").strip()
        entry: dict = {}
        if url:
            entry["url"] = url
            transport = str(sv.get("transport") or "").lower()
            if transport in ("stdio", "http", "streamable-http", "sse"):
                entry["transport"] = transport
            hdrs = _mcp_headers(sv)
            if hdrs:
                entry["headers"] = hdrs
        elif sv.get("command"):
            cmd = sv["command"]
            argv = cmd if isinstance(cmd, list) else [str(cmd)]
            entry["transport"] = "stdio"
            entry["command"] = argv[0]
            entry["args"] = [str(x) for x in argv[1:]] + [str(x) for x in (sv.get("args") or [])]
            envv = sv.get("env")
            if isinstance(envv, dict) and envv:
                entry["env"] = {str(k): str(v) for k, v in envv.items()}
            if sv.get("cwd"):
                entry["cwd"] = str(sv["cwd"])
        else:
            continue
        out[name] = entry
    return out


def _build_openhands(provider: str, auth: Auth, model: str, prompt: str, cwd: str, env: dict,
                     resume_session_id: str | None = None, mcp_servers: list[dict] | None = None,
                     tools_disabled: list[str] | None = None,
                     max_turns: int | None = None) -> list[str]:
    """OpenHands V1, driven through `openhands-agent-server` (OpenHands/agent-sdk, MIT).

    NOT the CLI. PyPI `openhands` is OpenHands/openhands-cli, whose README opens with "This project
    is no longer actively maintained" and whose last release is 1.16.0 of 2026-05-08; the agent
    server released 1.49.2 on 2026-09-17. The turn process is runner/openhands_driver.py, which
    starts a server on loopback, drives ONE turn over its HTTP + WebSocket API and exits — the same
    one-process-per-turn contract as every other backend, and the codex app-server precedent.

    THE MODEL ID IS SENT WITH A `litellm_proxy/` PREFIX and the key rides the driver's environment
    rather than the conversation. Both are forced by what the server persists: base_state.json
    carries the whole LLM spec with `api_key: None`, so a key passed on the create call reaches the
    first turn and nothing after it, and without an explicit provider litellm INFERS one from the
    base url — which is how a relay url produced `Vercel_ai_gatewayException … set the
    VERCEL_AI_GATEWAY_API_KEY` on a resumed turn. The prefix was `openai/` until 2026-09-27, and
    that one is stripped TWICE on the way to the wire (OpenHands' LLM and litellm 1.94.3 each take
    one off): a provider-native id that itself starts with `openai/` (openai/gpt-6-sol, what every
    aggregator calls the OpenAI family) reached TokenRouter as the bare `gpt-6-sol`, which it refuses
    with 503 model_not_found; Vercel resolves the bare id, which is why the Vercel column passed.
    Measured against a loopback recorder in the openhands venv on hr-test: openai/openai/gpt-6-sol
    -> gpt-6-sol, litellm_proxy/openai/gpt-6-sol -> openai/gpt-6-sol, litellm_proxy/gpt-6-sol ->
    gpt-6-sol. litellm's proxy provider is the documented way to say "an OpenAI-shaped server, send
    the id as it is", which is what the relay is. Every turn rides the loopback relay for the qwen
    reason: the real key never enters the agent's environment and the provider's own `model` passes
    through for the served-model check."""
    pr = provider or "openai-api"
    if pr not in OPENHANDS_PROVIDERS:
        raise HTTPException(400,
                            f"unknown openhands provider '{pr}' (one of {sorted(OPENHANDS_PROVIDERS)})")
    if not auth.base_url:
        raise HTTPException(400, "openhands needs a base_url (none configured)")
    # GUARDED ON THE KEY, as every other builder is. The relay holds the real credential and hands
    # the turn a token in its place; with nothing to hold it registers a route whose upstream key
    # is empty and the provider refuses the forwarded request — measured on the google integration,
    # whose `Please pass a valid API key` came back through a relay that had none to send.
    if auth.api_key:
        relay_base, relay_tok = _hermes_relay_route(auth.base_url, auth.api_key,
                                                    drop_fields=_OPENHANDS_DROP_FIELDS)
        auth = auth.model_copy(update={"base_url": relay_base, "api_key": relay_tok})
    # The relay token rides the turn's ENVIRONMENT as well as the job: _relay_served_model and
    # _relay_usage find the turn's route by the placeholder bearer in env (any variable, they scan
    # the values), and a token that lived only in the driver's argv left every openhands turn with
    # no served model and no usage (measured: usage None on three turns whose provider calls the
    # relay had counted). The PAIR IS THE PROXY PROVIDER'S, because that is what litellm reads for
    # a `litellm_proxy/` id: its chat path falls back to OPENAI_BASE_URL / OPENAI_API_KEY, its
    # Responses path does not ("api_base not set for LiteLLM Proxy responses API", the first hosted
    # turn on gpt-5.4, whose api_mode resolves to responses), and nothing else in the stack reads
    # the OpenAI pair once the id carries the proxy prefix (measured in the openhands venv on
    # hr-test, 2026-09-27, both paths, each pair alone and both together). One pair, one reader.
    if _anthropic_native(pr, auth):
        # litellm's own anthropic route: a Messages request with the cache breakpoints OpenHands
        # sets for a Claude model (caching_prompt, on by default), against ANTHROPIC_API_BASE,
        # which litellm 1.94.3 posts to AS GIVEN (get_complete_url returns it unchanged, measured
        # in the openhands venv on hr-test, 2026-09-30), so the relay's /v1/messages is named here.
        # The proxy route sent OpenAI chat requests to the endpoint's OpenAI-compatible surface,
        # where nothing is cached: a benchmark paid $12.28 for an audit task Claude Code did for
        # $2.08 on the same model.
        model_id = f"anthropic/{model}"
        provider_env = {"ANTHROPIC_API_KEY": auth.api_key or "",
                        "ANTHROPIC_API_BASE": auth.base_url.rstrip("/") + "/messages"}
    else:
        model_id = f"litellm_proxy/{model}"
        provider_env = {"LITELLM_PROXY_API_KEY": auth.api_key or "", "LITELLM_PROXY_API_BASE": auth.base_url}
    env.update(provider_env)
    job = {"cwd": cwd, "model": model_id, "prompt": prompt,
           "base_url": auth.base_url, "api_key": auth.api_key, "provider_env": provider_env,
           "tools_disabled": list(tools_disabled or []),
           # Declared MCP servers reach the agent itself; a parameter accepted and then dropped is
           # the defect aider's bridge already taught this repo, so the test suite pins the whole
           # chain rather than this line.
           "mcp_config": _openhands_mcp_config(mcp_servers),
           # the server's own default is 500 iterations per run; an operator's budget that the
           # backend drops is the quiet lie kimi shipped at 1000 steps
           "max_turns": max_turns}
    return [OPENHANDS_PYTHON, OPENHANDS_DRIVER, json.dumps(job)]


def _kimi_to_claude(obj: dict, state: dict) -> list[dict]:
    """Map ONE `kimi -p … --output-format stream-json` line to zero+ canonical claude events.

    Shapes captured live from Kimi Code CLI 2.0.0, one JSON object per line:

        version           {"role":"meta","type":"system.version","version":"2.0.0"}
        assistant text    {"role":"assistant","content":"…"}
        assistant call    {"role":"assistant","tool_calls":[{"id",…,"function":{"name","arguments"}}]}
        tool result       {"role":"tool","content":"…","tool_call_id":"…"}
        resume hint       {"role":"meta","type":"session.resume_hint","session_id":"session_<uuid>",…}

    The resume hint is the LAST line of a turn and the only place the session id appears, so the
    conversation id is announced from it; the run loop records an init event whenever it arrives.
    The stream carries no usage and no result event: usage is the relay's to stamp, and the process
    exiting is the end of the turn (see _kimi_eof)."""
    role = obj.get("role")
    if role == "meta":
        if obj.get("type") == "session.resume_hint" and obj.get("session_id"):
            return [{"type": "system", "subtype": "init", "session_id": str(obj["session_id"]),
                     "model": state.get("model")}]
        return []
    if role == "assistant":
        out: list[dict] = []
        content = obj.get("content")
        if isinstance(content, str):
            txt = content
        elif isinstance(content, list):
            txt = "".join(str(part.get("text") or "") for part in content
                          if isinstance(part, dict) and part.get("type") == "text")
        else:
            txt = ""
        if txt.strip():
            # The LAST assistant text is the turn's answer: there is no result event to take it
            # from, and a tool-carrying message has no content, so it never overwrites an answer.
            state["final"] = txt
            out.append({"type": "assistant", "message": {"content": [{"type": "text", "text": txt}]}})
        for call in obj.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            fn = call.get("function") if isinstance(call.get("function"), dict) else {}
            tuid = str(call.get("id") or "tool")
            args = fn.get("arguments")
            if isinstance(args, str):
                # arguments arrive as a JSON STRING (OpenAI's shape). A model can emit one that
                # does not parse; keep the raw text rather than dropping the call.
                try:
                    args = json.loads(args)
                except Exception:  # noqa: BLE001
                    args = {"arguments": args}
            if not isinstance(args, dict):
                args = {}
            out.append({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": tuid, "name": str(fn.get("name") or "tool"), "input": args}]}})
        return out
    if role == "tool":
        body = obj.get("content")
        text = body if isinstance(body, str) else json.dumps(body, default=str)
        # is_error is not on this line: the text itself carries the outcome to the reader.
        return [{"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": str(obj.get("tool_call_id") or "tool"),
             "is_error": False, "content": text}]}}]
    return []


def _kimi_eof(state: dict, rc: int) -> list[dict]:
    """Synthesize the turn's result at end of stream: there is no terminal event, so the process
    exiting IS the end of the turn, and THE EXIT CODE IS THE STATUS. Measured on 2.0.0: a provider
    refusal, an unknown session, a spent step budget and an MCP failure all exit 1 with one line on
    stderr, `error: failed to run prompt: <class>: <reason>` (provider.auth_error: 401 …,
    loop.max_steps_exceeded: …), which the run loop has already collected. Returning an EMPTY
    result on failure is deliberate: the run loop fills it from that line and _failure_reason
    prefers a provider refusal it matches inside it; a placeholder here would shadow the real
    reason. usage is {} because the stream carries none; the relay stamps it."""
    final = state.get("final", "")
    pre: list[dict] = []
    down = _kimi_mcp_unavailable(state)
    if down:
        pre = [{"type": "system", "subtype": "mcp_unavailable", "servers": down}]
    if rc == 0:
        return pre + [{"type": "result", "subtype": "success", "is_error": False,
                       "result": final, "usage": {}}]
    return pre + [{"type": "result", "subtype": "error", "is_error": True, "result": "", "usage": {}}]


_KIMI_MCP_DOWN = re.compile(
    r'^(\S+) ERROR mcp server unavailable\s+server=(\S+)\s+transport=\S+\s+status=\S+(?:\s+reason="([^"]*)")?')


def _kimi_mcp_unavailable(state: dict) -> list[dict]:
    """The MCP servers this turn could not reach, read from the CLI's own log.

    Kimi Code CLI runs the turn WITHOUT an unreachable server and says nothing about it: no stream
    line, nothing on stderr, exit 0 (measured on 2.0.0 against a dead endpoint; its predecessor
    failed the turn instead). The only trace is one line in $KIMI_CODE_HOME/logs/kimi-code.log,
    `<iso time> ERROR mcp server unavailable  server=<name> transport=<t> status=failed reason="…"`.
    A person whose tool silently was not there has no way to know why the agent never used it, so
    the lines written since this turn began become a system event the gateway renders as a note."""
    cwd = state.get("cwd")
    if not cwd:
        return []
    log = _kimi_home(pathlib.Path(cwd)) / "logs" / "kimi-code.log"
    try:
        lines = log.read_text(errors="replace").splitlines()[-400:]
    except OSError:
        return []
    since = float(state.get("started") or 0) - 2.0
    out: dict[str, dict] = {}
    for ln in lines:
        m = _KIMI_MCP_DOWN.match(ln)
        if not m:
            continue
        try:
            ts = datetime.datetime.fromisoformat(m.group(1).replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
        if ts >= since:
            out[m.group(2)] = {"name": m.group(2), "reason": (m.group(3) or "")[:200]}
    return list(out.values())


_kimi_to_claude.eof = _kimi_eof   # type: ignore[attr-defined]


def _minimax_text(v) -> str:
    """A tool output's text: MiniMax Code's tool results are `{content: [{type: text, text}], details}`
    (pi's shape); anything else is kept as JSON rather than dropped."""
    if isinstance(v, str):
        return v
    if isinstance(v, dict) and isinstance(v.get("content"), list):
        parts = [str(p.get("text") or "") for p in v["content"]
                 if isinstance(p, dict) and p.get("type") == "text"]
        if parts:
            return "".join(parts)
    if v is None:
        return ""
    return json.dumps(v, default=str)


def _minimax_to_claude(obj: dict, state: dict) -> list[dict]:
    """Map ONE `mcode exec --output-format stream-json` line to zero+ canonical claude events.

    The stream is MiniMax Code's versioned exec contract (schemaVersion 1, packages/tui/src/headless/
    events.ts in 0.5.4), confirmed line by line against a stub:

        exec.started / session.started | session.resumed / turn.started      every line: sessionId
        item.started | item.updated | item.completed  item.type agent_message | reasoning | tool_call
        turn.completed {model, usage, usageSource}  |  turn.failed {status, error{category,message}}
        exec.completed {result: {status, output, error, …}}                   always the last line

    Only COMPLETED items are rendered: a tool call's completed item carries its input, its output
    and its status together (1 start, 2 finished, 3 failed, 4 preparing, 5 prepared).

    A PROVIDER FAILURE IS STRUCTURAL here (checklist #8, measured with a 401 and a 503 at a stub):
    turn.failed carries `BYOK provider … upstream error: 401 …`, exit 4, and no agent_message at all
    — nothing is narrated as assistant text, so no prefix regex is needed, and one would only ever
    turn an answer that mentions an error into a failure.

    The result carries NO model and NO usage on purpose. The CLI's `model` is the id it was asked
    for, not what the provider served, and a result with a model is never checked against the relay
    (_run_turn_bg only fills an empty one): rule 2 would compare the request with itself. Both come
    from the relay, which reads the provider's own bytes."""
    t = obj.get("type")
    out: list[dict] = []
    sid = obj.get("sessionId")
    if sid and not state.get("_mm_init"):
        # _run_turn_bg records the conversation id only from a system/init event; without it every
        # follow-up would silently start a new conversation (the recycle lesson).
        state["_mm_init"] = True
        out.append({"type": "system", "subtype": "init", "session_id": str(sid),
                    "model": state.get("model")})
    if t == "item.completed":
        item = obj.get("item") if isinstance(obj.get("item"), dict) else {}
        it = item.get("type")
        if it == "agent_message":
            txt = item.get("content")
            if isinstance(txt, str) and txt.strip():
                state["final"] = txt
                out.append({"type": "assistant", "message": {"content": [{"type": "text", "text": txt}]}})
        elif it == "reasoning":
            txt = item.get("content")
            if isinstance(txt, str) and txt.strip():
                out.append({"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": txt}]}})
        elif it == "tool_call":
            call = item.get("toolCall") if isinstance(item.get("toolCall"), dict) else {}
            tuid = str(call.get("id") or item.get("id") or "tool")
            seen = state.setdefault("_mm_tools", set())
            if tuid in seen:
                return out
            seen.add(tuid)
            args = call.get("input")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {"arguments": args}
            if not isinstance(args, dict):
                args = {}
            failed = call.get("status") == 3 or bool(call.get("error"))
            body = _minimax_text(call.get("error") if failed and call.get("error") else call.get("output"))
            out.append({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": tuid, "name": str(call.get("name") or "tool"), "input": args}]}})
            out.append({"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": tuid, "is_error": failed, "content": body}]}})
        return out
    if t == "turn.failed":
        err = obj.get("error") if isinstance(obj.get("error"), dict) else {}
        state["_mm_error"] = str(err.get("message") or "")
        return out
    if t == "exec.completed":
        res = obj.get("result") if isinstance(obj.get("result"), dict) else {}
        status = res.get("status")
        state["_mm_done"] = True
        if status == "succeeded":
            answer = res.get("output")
            if not isinstance(answer, str):
                answer = state.get("final") or ("" if answer is None else json.dumps(answer, default=str))
            state["final"] = answer or state.get("final", "")
            out.append({"type": "result", "subtype": "success", "is_error": False,
                        "result": state["final"], "usage": {}})
            return out
        err = res.get("error") if isinstance(res.get("error"), dict) else {}
        msg = str(err.get("message") or state.get("_mm_error") or "")
        if status == "limit_exceeded":
            out.append({"type": "result", "subtype": "error_max_turns", "is_error": True,
                        "result": msg or "the run reached its step limit (--max-steps)", "usage": {}})
        else:
            if not msg and status == "timeout":
                msg = "the run timed out"
            out.append({"type": "result", "subtype": "error", "is_error": True, "result": msg,
                        "usage": {}})
        return out
    return out


def _minimax_eof(state: dict, rc: int) -> list[dict]:
    """The process ended without an exec.completed line: a failure before the stream began
    (`Session not found: <id>`, an invalid config, a crash) prints one line on stderr and exits
    non-zero. The result is left EMPTY so the run loop fills it from that line — a placeholder here
    would shadow the real reason, as in _kimi_eof."""
    if rc == 0 and state.get("final"):
        return [{"type": "result", "subtype": "success", "is_error": False,
                 "result": state["final"], "usage": {}}]
    return [{"type": "result", "subtype": "error", "is_error": True,
             "result": state.get("_mm_error", ""), "usage": {}}]


_minimax_to_claude.eof = _minimax_eof   # type: ignore[attr-defined]


# Registry — providers/default_model/normalize per backend. The cmd build + run loop is dispatched
# in turn(): claude/codex run through _run_turn_bg over stdout JSONL; hermes has its own driver
# (_run_hermes_bg — DB-polling, no stdout events), so it carries no normalizer.
# ── openhands ────────────────────────────────────────────────────────────────────
# The turn process is runner/openhands_driver.py, which re-emits what it observes on the
# agent-server's WebSocket as NDJSON in the dsh_driver shape. The driver has already decided what
# is prose, what is a tool call and what is a failure — it sees typed SDK events, not text — so
# this maps one shape to another and judges nothing.
_OPENHANDS_SESSION_NAME = "harness"


def _openhands_to_claude(obj: dict, state: dict) -> list[dict]:
    m = obj.get("m")
    p = obj.get("p") if isinstance(obj.get("p"), dict) else {}
    if not state.get("_oh_init"):
        # _run_turn_bg records the conversation id ONLY from a system/init event, and that recorded
        # id is what makes the next turn a follow-up rather than a new thread.
        state["_oh_init"] = True
        return ([{"type": "system", "subtype": "init", "session_id": _OPENHANDS_SESSION_NAME,
                  "model": state.get("model")}]
                + _openhands_event(obj, state, m, p))
    return _openhands_event(obj, state, m, p)


def _openhands_event(obj: dict, state: dict, m, p) -> list[dict]:
    if m == "text":
        txt = str(p.get("text") or "")
        if not txt.strip():
            return []
        state["final"] = txt
        return [{"type": "assistant", "message": {"content": [{"type": "text", "text": txt}]}}]
    if m == "tool_call":
        state["_oh_last_call"] = str(p.get("id") or "t0")
        return [{"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": state["_oh_last_call"], "name": str(p.get("name") or "Tool"),
             "input": p.get("input") or {}}]}}]
    if m == "tool_result":
        out = p.get("output")
        return [{"type": "user", "message": {"content": [
            {"type": "tool_result",
             "tool_use_id": str(p.get("id") or state.get("_oh_last_call") or "t0"),
             "is_error": bool(p.get("is_error")) or bool(isinstance(out, dict) and out.get("is_error")),
             "content": json.dumps(out, default=str) if not isinstance(out, str) else out}]}}]
    if m == "error":
        # Reached the conversation's error channel, which the model's prose cannot reach. Recorded,
        # NOT rendered: it is the turn's failure reason, not part of its answer.
        state["_oh_error"] = str(p.get("text") or "")
        return []
    if m == "warning":
        state.setdefault("_oh_warnings", []).append(str(p.get("text") or ""))
        return []
    if m == "init":
        state["_oh_conversation"] = str(p.get("conversation_id") or "")
        return []
    if m == "result":
        err = state.get("_oh_error") or ""
        ok = bool(p.get("ok")) and not err
        final = str(p.get("final") or state.get("final") or "")
        if ok:
            state["final"] = final
        # usage is {} deliberately: per the 2026-09-13 decision no harness PR builds its own usage
        # pipeline, and _relay_usage stamps these rows.
        return [{"type": "result", "subtype": "success" if ok else "error", "is_error": not ok,
                 "result": final if ok else (err or f"the turn ended {p.get('status') or 'unknown'}"),
                 "usage": {}}]
    return []


def _openhands_eof(state: dict, rc: int) -> list[dict]:
    """The driver emits its own result event, so this fires only when the process died before
    reaching it — a crash, a kill, an import failure."""
    err = state.get("_oh_error") or ""
    if rc == 0 and not err:
        return [{"type": "result", "subtype": "success", "is_error": False,
                 "result": state.get("final", ""), "usage": {}}]
    return [{"type": "result", "subtype": "error", "is_error": True, "result": err, "usage": {}}]


_openhands_to_claude.eof = _openhands_eof   # type: ignore[attr-defined]


def _grok_tool_output(content):
    """What a tool card shows for a grok tool result. The CLI serialises two envelopes into the
    tool_result's content string (measured on 1.0.41): the shell's record — {"type": "Bash",
    "output": [bytes…], "output_for_prompt": "exit: 0\\n<what it printed>", "exit_code", "command", …}
    — and ACP content blocks, [{"type": "content", "content": {"type": "text", "text": …}}], which is
    how a refused or failed call comes back. The reader wants the text the model was given, as on
    every other base's card; anything else is shown as it came."""
    if not isinstance(content, str):
        return content
    try:
        doc = json.loads(content)
    except ValueError:
        return content
    if isinstance(doc, dict) and isinstance(doc.get("output_for_prompt"), str):
        return doc["output_for_prompt"]
    if isinstance(doc, list) and doc and all(isinstance(b, dict) for b in doc):
        texts = []
        for b in doc:
            inner = b.get("content") if isinstance(b.get("content"), dict) else b
            if isinstance(inner.get("text"), str):
                texts.append(inner["text"])
        if texts:
            return "\n".join(texts)
    return content


def _grok_to_claude(obj: dict, state: dict) -> list[dict]:
    """Map ONE `grok --output-format streaming-messages-json` line to canonical claude events.

    The stream IS Claude Code's stream-json (measured on 1.0.41): system/init with the session id,
    assistant messages holding text/thinking/tool_use, user messages holding tool_result, and one
    terminal result — so every line goes through the claude passthrough, with two repairs to the
    result:

      A failure carries its reason in `errors[]` and no `result` at all. A provider failure is
      STRUCTURED, never narrated as assistant text: 401, 500 after retries and an unreachable
      endpoint each ended `subtype: error_during_execution, is_error: true, errors: ["Internal
      error: …Unauthorized (401) from …: Incorrect API key …"]` and exit 1 (all measured at a stub).
      So no error prefix has to be recognised in an answer — an answer that merely talks about an
      error is an answer — and the reason is lifted into `result`, where the run loop reads it.

      `usage` is dropped so the relay's count stamps the row. grok's own figure excludes side calls
      (the session title on a conversation's first turn: "Compaction and other side-model calls are
      excluded"), and the relay saw every call the provider answered. `model` is absent on the
      result and the init's `model` is the runner's catalog KEY, so the served model is the relay's
      too."""
    t = obj.get("type")
    if t == "system" and obj.get("subtype") == "init":
        # The init names the runner's catalog key ("harness"), not a model: say what was asked for.
        obj = {**obj, "model": state.get("model") or obj.get("model")}
    elif t == "user":
        content = (obj.get("message") or {}).get("content")
        if isinstance(content, list):
            fixed = [{**c, "content": _grok_tool_output(c.get("content"))}
                     if isinstance(c, dict) and c.get("type") == "tool_result" else c for c in content]
            obj = {**obj, "message": {**(obj.get("message") or {}), "content": fixed}}
    elif t == "result":
        obj = {k: v for k, v in obj.items() if k not in ("usage", "modelUsage", "total_cost_usd")}
        if obj.get("is_error") and not str(obj.get("result") or "").strip():
            errs = [str(e) for e in (obj.get("errors") or []) if str(e).strip()]
            reason = "; ".join(errs) or f"grok run ended {obj.get('subtype') or 'in error'}"
            obj["result"] = reason[:2000]
        obj["usage"] = {}
    return _claude_passthrough(obj, state)


def _grok_eof(state: dict, rc: int) -> list[dict]:
    """The process ended without a result line: a crash or a kill. A failure that happens before the
    session exists still writes its result (a refused --disallowed-tools set did, measured), so this
    is the rarer path. The result is left EMPTY so the run loop fills it from the captured stderr
    (`Error: …`), which _failure_reason prefers to a sentence of ours."""
    if rc == 0:
        return [{"type": "result", "subtype": "success", "is_error": False,
                 "result": state.get("final", ""), "usage": {}}]
    return [{"type": "result", "subtype": "error", "is_error": True, "result": "", "usage": {}}]


_grok_to_claude.eof = _grok_eof   # type: ignore[attr-defined]


# ── agentzero: Agent Zero (agent0ai/agent-zero, MIT), driven in process ────────────────────────────
# The turn process is runner/agentzero_driver.py under Agent Zero's own venv: it builds an
# AgentContext, sends the message, and re-emits what Agent Zero's extension hooks observe as NDJSON
# in the dsh_driver shape. The framework has no CLI and no headless mode (it is a web UI shipped as a
# Docker image), so driving the framework's own loop in process is the one-process-per-turn form it
# can take; see the driver's docstring for every door it goes through.
AGENTZERO_PROVIDERS = {"anthropic", "openai", "azure", "openai-api", "tokenrouter"}
AGENTZERO_PYTHON = os.environ.get("HR_AGENTZERO_PYTHON", "/data/agent-tools/agentzero-venv/bin/python")
AGENTZERO_SRC = os.environ.get("HR_AGENTZERO_SRC", "/data/agent-tools/agentzero-src")
AGENTZERO_DRIVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agentzero_driver.py")
# The conversation's context id: constant, because the store is in the workspace (the driver's
# SESSION_ID; a follow-up after a recycle finds it by the same name).
_AGENTZERO_SESSION = "harness"


def _build_agentzero(provider: str, auth: Auth, model: str, prompt: str, cwd: str, env: dict,
                     resume_session_id: str | None = None, mcp_servers: list[dict] | None = None,
                     tools_disabled: list[str] | None = None,
                     max_turns: int | None = None) -> list[str]:
    """Agent Zero v2.13, one turn: the job rides the environment as JSON (HR_AGENTZERO_JOB), the
    driver emits NDJSON. Not argv: /proc/<pid>/cmdline is readable by every session's uid in the
    container, and the job names the relay route and each MCP server's credentials.

    The model is Agent Zero's provider `other` ("Other OpenAI compatible": litellm's openai
    provider with an api_base) pointed at the loopback relay, so the id reaches the provider as
    written — Agent Zero sends `other` models as `openai/<id>` to litellm, which strips its own
    prefix and nothing else. The key is the relay's placeholder, in OTHER_API_KEY: the variable
    Agent Zero's models.get_api_key reads for provider `other`, and the ENVIRONMENT, which is where
    _relay_served_model and _relay_usage find the turn's route (the openhands lesson: a token that
    lived only in argv left every turn with no served model and no usage)."""
    pr = provider or "openai-api"
    if pr not in AGENTZERO_PROVIDERS:
        raise HTTPException(400,
                            f"unknown agentzero provider '{pr}' (one of {sorted(AGENTZERO_PROVIDERS)})")
    if not auth.base_url:
        raise HTTPException(400, "agentzero needs a base_url (none configured)")
    if auth.api_key:
        relay_base, relay_tok = _hermes_relay_route(auth.base_url, auth.api_key)
        auth = auth.model_copy(update={"base_url": relay_base, "api_key": relay_tok})
    env["OTHER_API_KEY"] = auth.api_key or ""
    job = {"cwd": cwd, "a0_src": AGENTZERO_SRC, "model": model, "prompt": prompt,
           "base_url": auth.base_url,
           "tools_disabled": list(tools_disabled or []),
           # Agent Zero's own MCP client dials these (stdio, sse, streamable-http); a parameter
           # accepted and then dropped is the defect aider's bridge taught this repo.
           # Headers through the one helper every writer shares: a server's `auth` IS its
           # Authorization header, and a writer that copied `headers` alone sent the plugs server
           # (browser, GitHub: `auth` and no headers) nothing at all.
           "mcp_servers": [{**{k: v for k, v in s.items() if k != "auth"}, "headers": _mcp_headers(s)}
                           for s in (mcp_servers or [])
                           if isinstance(s, dict) and (s.get("url") or s.get("command"))],
           # Agent Zero's loop has no step budget of its own; the driver counts model calls.
           "max_turns": max_turns,
           "agent_doc_name": "AGENTS.md"}
    env["HR_AGENTZERO_JOB"] = json.dumps(job)
    return [AGENTZERO_PYTHON, AGENTZERO_DRIVER]


# What the console calls Agent Zero's tools on a card, and the shape of the input it shows: the
# catalog lists them by Agent Zero's own names (the ids a disable carries), and the card reads
# better with the verb every other base uses. MCP tools (`server.tool`) keep their own names.
_AGENTZERO_CARD_NAMES = {"code_execution_tool": "Shell", "input": "Shell Input",
                         "text_editor": "Edit", "call_subordinate": "Subagent",
                         "skills_tool": "Skill", "parallel": "Parallel", "wait": "Wait",
                         "goal": "Goal"}


def _agentzero_card_input(name: str, args: dict) -> dict:
    """A shell call's command under `command`, the key every other base's shell card carries (the
    console previews it); Agent Zero names it `code`, and `keyboard` for the input tool."""
    out = dict(args or {})
    if name == "code_execution_tool" and "code" in out:
        out["command"] = out.pop("code")
    elif name == "input" and "keyboard" in out:
        out["command"] = out.pop("keyboard")
    return out


def _agentzero_to_claude(obj: dict, state: dict) -> list[dict]:
    """Map one driver line to canonical claude events. The driver has already decided what is the
    answer (the response tool's text), what is a tool call (Agent Zero's tool_execute_before/after
    hooks) and whether the turn failed (the loop raised, or never produced an answer); this maps
    one shape to another and judges nothing.

    Agent Zero reports a provider failure STRUCTURALLY, never as prose: the exception leaves the
    loop, its critical-exception handler writes an `error` log item and the task raises. Measured on
    v2.13 with a wrong key (401) and a dead base url (connection refused): no response-tool text at
    all, `task.result()` raises HandledException. So there is no error prefix to anchor a regex on,
    and the answer that merely mentions an error is an ordinary answer (see the tests)."""
    m = obj.get("m")
    p = obj.get("p") if isinstance(obj.get("p"), dict) else {}
    if m == "init":
        # _run_turn_bg records the conversation id ONLY from a system/init event, and that recorded
        # id is what makes the next turn a follow-up rather than a new thread.
        return [{"type": "system", "subtype": "init",
                 "session_id": str(p.get("session_id") or _AGENTZERO_SESSION),
                 "model": state.get("model")}]
    if m == "thinking":
        txt = str(p.get("text") or "")
        if not txt.strip():
            return []
        return [{"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": txt}]}}]
    if m == "tool_call":
        raw = str(p.get("name") or "tool")
        tid = str(p.get("id") or "a0")
        return [{"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": tid, "name": _AGENTZERO_CARD_NAMES.get(raw, raw),
             "input": _agentzero_card_input(raw, p.get("input") if isinstance(p.get("input"), dict) else {})}]}}]
    if m == "tool_result":
        out = p.get("output")
        return [{"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": str(p.get("id") or "a0"),
             "is_error": bool(p.get("is_error")),
             "content": out if isinstance(out, str) else json.dumps(out, default=str)}]}}]
    if m == "mcp_unavailable":
        return [{"type": "system", "subtype": "mcp_unavailable", "servers": p.get("servers") or []}]
    if m == "warning":
        state.setdefault("_a0_warnings", []).append(str(p.get("text") or ""))
        return []
    if m == "result":
        ok = bool(p.get("ok"))
        final = str(p.get("final") or "")
        if ok:
            state["final"] = final
            # The answer is one text block, emitted here rather than streamed: Agent Zero's answer
            # is the response tool's argument, which exists only once the model's JSON is complete.
            return [{"type": "assistant", "message": {"content": [{"type": "text", "text": final}]}},
                    {"type": "result", "subtype": "success", "is_error": False, "result": final,
                     "usage": {}}]
        state["_a0_error"] = str(p.get("error") or "")
        # usage is {} on purpose: the relay stamps it (_relay_usage), as for every backend whose
        # own record carries none — Agent Zero's LLMResult usage never leaves the process.
        return [{"type": "result", "subtype": "error", "is_error": True,
                 "result": state["_a0_error"] or "the turn failed", "usage": {}}]
    return []


def _agentzero_eof(state: dict, rc: int) -> list[dict]:
    """The driver emits its own result event, so this fires only when the process died before
    reaching it — a crash, a kill, an import failure. The reason then comes from stderr, which
    _failure_reason reads; a placeholder here would shadow it."""
    if rc == 0 and state.get("final"):
        return [{"type": "result", "subtype": "success", "is_error": False,
                 "result": state.get("final", ""), "usage": {}}]
    return [{"type": "result", "subtype": "error", "is_error": True,
             "result": state.get("_a0_error") or "", "usage": {}}]


_agentzero_to_claude.eof = _agentzero_eof   # type: ignore[attr-defined]


BACKENDS = {
    "claude": {"providers": sorted(CLAUDE_PROVIDERS), "default_model": CLAUDE_DEFAULT_MODEL,
               "normalize": _claude_passthrough},
    "codex": {"providers": sorted(CODEX_PROVIDERS), "default_model": CODEX_DEFAULT_MODEL,
              "normalize": _codex_to_claude},
    "hermes": {"providers": sorted(HERMES_PROVIDERS), "default_model": HERMES_DEFAULT_MODEL,
               "normalize": None},
    "pi": {"providers": sorted(PI_PROVIDERS), "default_model": PI_DEFAULT_MODEL,
           "normalize": _pi_to_claude},
    "dsh": {"providers": sorted(DSH_PROVIDERS), "default_model": DSH_DEFAULT_MODEL,
            "normalize": _dsh_to_claude},
    "opencode": {"providers": sorted(OPENCODE_PROVIDERS), "default_model": OPENCODE_DEFAULT_MODEL,
                 "normalize": _opencode_to_claude},
    # Kilo CLI is an opencode fork whose `run --format json` emitter is opencode's, unchanged at
    # 7.8.1 (the same six event types and framing), so it shares the normaliser; only the name in
    # its fallback messages differs.
    "kilo": {"providers": sorted(KILO_PROVIDERS), "default_model": KILO_DEFAULT_MODEL,
             "normalize": _kilo_to_claude},
    # qwen-code emits claude's stream-json natively (verified against the shipped 0.22.1:
    # system/init with session_id, assistant/message, result/subtype/usage in claude's field
    # names) — so its normalizer IS the claude passthrough.
    "qwen": {"providers": sorted(QWEN_PROVIDERS), "default_model": QWEN_DEFAULT_MODEL,
             "normalize": _claude_passthrough},
    # gemini's native stream-json is its OWN schema, not claude's — see _gemini_to_claude's
    # docstring for why this cannot reuse the qwen row's passthrough despite the fork lineage.
    "gemini": {"providers": sorted(GEMINI_PROVIDERS), "default_model": GEMINI_DEFAULT_MODEL,
               "normalize": _gemini_to_claude},
    "cline": {"providers": sorted(CLINE_PROVIDERS), "default_model": CLINE_DEFAULT_MODEL,
              "normalize": _cline_to_claude},
    # omp is pi's lineage and speaks pi's `--mode json` event stream unchanged (measured on 18.1.13:
    # session, message_update, message_end, tool_execution_start/end, agent_end, with the same
    # fields), so it shares pi's normaliser rather than carrying a copy.
    "omp": {"providers": sorted(OMP_PROVIDERS), "default_model": OMP_DEFAULT_MODEL,
            "normalize": _pi_to_claude},
    # goose's stream-json is its OWN schema (Rust serde, two rename rules in one stream), so it
    # carries its own normaliser rather than sharing one — see _goose_to_claude's docstring.
    "goose": {"providers": sorted(GOOSE_PROVIDERS), "default_model": GOOSE_DEFAULT_MODEL,
              "normalize": _goose_to_claude},
    # Kimi Code CLI's stream-json shares claude's FLAG NAME and nothing else: one message per line,
    # no usage and no result event, the session id on the last line, so it carries its own
    # normaliser and an eof rather than the passthrough qwen's claude-shaped stream can use.
    "kimi": {"providers": sorted(KIMI_PROVIDERS), "default_model": KIMI_DEFAULT_MODEL,
             "normalize": _kimi_to_claude},
    # MiniMax Code's exec stream is its own versioned schema (schemaVersion 1) — see
    # _minimax_to_claude — with a terminal exec.completed line, so the eof only covers a run that
    # died before the stream began.
    "minimax": {"providers": sorted(MINIMAX_PROVIDERS), "default_model": MINIMAX_DEFAULT_MODEL,
                "normalize": _minimax_to_claude},
    "aider": {"providers": sorted(AIDER_PROVIDERS), "default_model": AIDER_DEFAULT_MODEL,
              "normalize": _aider_to_claude},
    # Grok Build's streaming-messages-json is Claude Code's stream-json; the normaliser is the
    # passthrough with its result repaired (the reason lifted out of errors[], usage left to the relay).
    "grok": {"providers": sorted(GROK_PROVIDERS), "default_model": GROK_DEFAULT_MODEL,
             "normalize": _grok_to_claude},
    "openhands": {"providers": sorted(OPENHANDS_PROVIDERS),
                  "default_model": OPENHANDS_DEFAULT_MODEL,
                  "normalize": _openhands_to_claude},
    # The driver emits its own NDJSON (see _cheetahclaws_to_claude), with an eof for a driver that
    # died before its result.
    "cheetahclaws": {"providers": sorted(CHEETAHCLAWS_PROVIDERS),
                     "default_model": CHEETAHCLAWS_DEFAULT_MODEL,
                     "normalize": _cheetahclaws_to_claude},
    # Agent Zero, in process through runner/agentzero_driver.py (its own NDJSON, like openhands').
    "agentzero": {"providers": sorted(AGENTZERO_PROVIDERS),
                  "default_model": AGENTZERO_DEFAULT_MODEL,
                  "normalize": _agentzero_to_claude},
    # The System One driver emits claude's stream-json itself (system/init, assistant tool_use and
    # thinking blocks, user tool_result, result with usage and a `reason`), so its normaliser is the
    # passthrough, as qwen's is.
    "systemone": {"providers": sorted(SYSTEMONE_PROVIDERS),
                  "default_model": SYSTEMONE_DEFAULT_MODEL,
                  "normalize": _claude_passthrough},
}


# ── async turn registry (background execution; turns can run seconds → the 6h cap) ──
_turns: dict[str, dict] = {}


def _release_proc(rec: dict, proc: "subprocess.Popen | None") -> None:
    """The turn's process is over: close its pipes and drop the handle from the record.

    The handle was kept on the record so POST /turn/{id}/cancel could kill a live CLI, and it was
    never let go: every finished turn left its stdout (and stdin, for the app-server) pipe open in
    this process for as long as the record lived, which is forever. On the self-hosted test
    instance 506 turns later the runner sat at 1020 of 1024 descriptors and every new turn failed
    with "spawn: [Errno 24] Too many open files" (2026-09-06). A closed pipe on a finished
    process is free; nothing reads it after the turn."""
    if proc is None:
        return
    for stream in (proc.stdin, proc.stdout, proc.stderr):
        try:
            if stream is not None:
                stream.close()
        except OSError:
            pass
    if rec.get("proc") is proc:
        rec.pop("proc", None)


# Finished turn records are read by the gateway for a few seconds after the turn ends (its poll
# harvests the last events and persists them), then never again; they used to stay in memory,
# every event of every turn, for the life of the process. A record is dropped once it is done
# and older than the hard turn cap plus this grace, which no live poll can outlast.
_TURN_RETENTION_S = 30 * 60


def _evict_turns(now: float | None = None) -> int:
    now = now or time.time()
    gone = 0
    with _turns_lock:
        for tid, rec in list(_turns.items()):
            if rec.get("done") and now - float(rec.get("started") or now) > MAX_TURN_SECONDS + _TURN_RETENTION_S:
                _turns.pop(tid, None)
                gone += 1
        if gone:
            for key, tid in list(_turn_by_key.items()):
                if tid not in _turns:
                    _turn_by_key.pop(key, None)
    return gone
_turn_by_key: dict[str, str] = {}   # idempotency_key -> turn_id (dedup a retried /turn; see turn())
_turns_lock = threading.Lock()


# Every process a turn starts carries the turn's id in its environment (set on the CLI's env
# and inherited by everything below it), so what the process group misses can still be found.
_TURN_MARK = "HR_TURN_ID"


def _sweep_turn_processes(turn_id: str) -> int:
    """Kill every process still carrying this turn's marker, and remove the tmux socket
    directory such a process names. The group kill misses a process that put itself in a new
    session: openhands' terminal tool runs commands in tmux, whose server daemonises with
    setsid, so a cancelled or timed-out turn left the tmux server AND the agent's command
    running (`sleep 240` alive after cancel, hr-test 2026-09-19), and every turn's
    /tmp/oh<port> directory behind it. The marker is what makes the turn's processes findable
    whatever they did to their process group; /proc is read as the runner, which is root here."""
    if not turn_id:
        return 0
    want = f"{_TURN_MARK}={turn_id}".encode()
    killed = 0
    dirs: set[str] = set()
    me = os.getpid()
    for entry in os.listdir("/proc") if os.path.isdir("/proc") else []:
        if not entry.isdigit() or int(entry) == me:
            continue
        try:
            environ = pathlib.Path("/proc", entry, "environ").read_bytes()
        except OSError:
            continue
        if want not in environ.split(b"\0"):
            continue
        for kv in environ.split(b"\0"):
            if kv.startswith(b"TMUX_TMPDIR="):
                dirs.add(kv.split(b"=", 1)[1].decode(errors="replace"))
        try:
            os.kill(int(entry), signal.SIGKILL)
            killed += 1
        except OSError:
            pass
    for d in dirs:
        if d.startswith("/tmp/oh"):
            shutil.rmtree(d, ignore_errors=True)
    return killed


def _kill_proc_tree(proc: subprocess.Popen, turn_id: str = "") -> None:
    """SIGKILL the CLI's whole process GROUP (Popen uses start_new_session). Killing only
    the CLI leaves its shell children (e.g. a `sleep`) holding the inherited stdout pipe,
    which keeps the reader loop blocked until the child exits — a cancel/timeout then
    appears to hang for the child's full duration. Then the stragglers by marker.

    The CLI's DESCENDANTS go first, found by parent pid while the CLI is still alive to be their
    parent. A child that started its own session is outside the group: Grok Build runs every shell
    command that way (measured on 1.0.41: `sh -c 'sleep 90 && …'` in its own pgid, and after a
    cancel the sleep was still running with the turn marked cancelled; SIGTERM to grok leaves it too),
    and so does Muse Code. The marker sweep does not catch it on a default Docker host either: a
    session process runs as its own uid, and reading another uid's /proc/<pid>/environ needs
    CAP_SYS_PTRACE, which Docker does not grant. /proc/<pid>/stat is world-readable, so the tree is.
    The group is STOPPED first, so the CLI cannot start another command between the listing and the
    kill; a stopped process still takes SIGKILL."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGSTOP)
    except Exception:  # noqa: BLE001
        pass
    for pid in _descendant_pids(proc.pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
    if turn_id:
        try:
            _sweep_turn_processes(turn_id)
        except Exception:  # noqa: BLE001
            pass


def _descendant_pids(root: int) -> list[int]:
    """Every live descendant of `root`, from /proc/<pid>/stat's parent pid (field 4, after the
    parenthesised command name, which may itself contain spaces or parentheses). [] where there is
    no /proc."""
    children: dict[int, list[int]] = {}
    try:
        entries = os.listdir("/proc")
    except OSError:
        return []
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            stat = pathlib.Path("/proc", entry, "stat").read_text()
            ppid = int(stat[stat.rindex(")") + 2:].split()[1])
        except (OSError, ValueError, IndexError):
            continue
        children.setdefault(ppid, []).append(int(entry))
    out: list[int] = []
    todo = list(children.get(root, []))
    while todo:
        pid = todo.pop()
        if pid in out or pid == root:
            continue
        out.append(pid)
        todo.extend(children.get(pid, []))
    return out


def _kill_capped(proc: subprocess.Popen, rec: dict) -> None:
    rec["capped"] = True
    _kill_proc_tree(proc, str(rec.get("turn_id") or ""))


def _run_turn_bg(turn_id: str, cmd: list[str], env: dict, cwd: str, normalize, model: str,
                 timeout_seconds: int | None = None, partial: bool = False) -> None:
    rec = _turns[turn_id]
    rec["turn_id"] = turn_id
    state = {"model": model, "final": "", "partial": partial, "cwd": cwd, "started": time.time()}
    result_ev = None
    env = {**env, _TURN_MARK: turn_id}
    try:
        # start_new_session: own process group so cancel/timeout can killpg the CLI AND its
        # shell children (see _kill_proc_tree) instead of orphaning a pipe-holding child.
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, text=True, bufsize=1,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                start_new_session=True, **_as_session(cwd, env))
    except Exception as e:  # noqa: BLE001
        rec.update(status="failed", error=f"spawn: {e}"[:500], done=True)
        return
    rec["pid"] = proc.pid
    rec["proc"] = proc   # live handle so POST /turn/{id}/cancel can kill on demand
    if rec.get("cancelled"):
        _kill_proc_tree(proc, turn_id)   # Stop raced the spawn — kill immediately, not at pipe EOF
    # Hard wall-clock cap — the caller's timeout_seconds (harness config / request override),
    # bounded by the global MAX_TURN_SECONDS ceiling (resource abuse backstop).
    cap = min(timeout_seconds, MAX_TURN_SECONDS) if timeout_seconds else MAX_TURN_SECONDS
    killer = threading.Timer(cap, _kill_capped, args=(proc, rec))
    killer.daemon = True
    killer.start()
    errbuf: list[str] = []   # non-JSON output (CLI stderr is merged into stdout) — the REAL error text
    goose_mcp_down: set[str] = set()
    try:
        for raw in proc.stdout:  # type: ignore[union-attr]
            raw = raw.strip()
            if not raw:
                continue
            if not raw.startswith("{"):
                # diagnostics / stderr (e.g. "API Error ... ThrottlingException", rate limits). Keep a
                # bounded tail so a failure is never opaque — this is what surfaces the real cause.
                errbuf.append(raw)
                if len(errbuf) > 80:
                    del errbuf[0]
                if normalize is _goose_to_claude:
                    name = _goose_mcp_startup_failure(raw)
                    if name and name not in goose_mcp_down:
                        goose_mcp_down.add(name)
                        # Include only the extension name. Its raw stderr may contain secrets,
                        # and the gateway only needs the name to explain the missing tools.
                        with _turns_lock:
                            rec["events"].append({"type": "system", "subtype": "mcp_unavailable",
                                                  "servers": [{"name": name}], "_ts": time.time()})
                continue
            try:
                obj = json.loads(raw)
            except Exception:  # noqa: BLE001
                continue
            for ev in normalize(obj, state):
                ev.setdefault("_ts", time.time())
                if ev.get("type") == "result" and not ev.get("model"):
                    # The CLI did not say what ran; the relay saw the provider say it. Set before
                    # the event is visible, so the gateway never reads it unlabelled.
                    served = _relay_served_model(env)
                    if served:
                        ev["model"] = served
                if ev.get("type") == "result":
                    _fill_relay_usage(ev, env)
                with _turns_lock:
                    rec["events"].append(ev)
                if ev.get("type") == "system" and ev.get("subtype") == "init" and ev.get("session_id"):
                    rec["session_id"] = ev["session_id"]   # CLI conversation id → next turn's --resume
                if ev.get("type") == "result":
                    result_ev = ev
                    # Claude's stream-json carries the final assistant text on the result event;
                    # the codex normalizer already fills state['final'], so prefer that.
                    state["final"] = state.get("final") or ev.get("result") or ""
        rc = proc.wait()
    finally:
        killer.cancel()
        _release_proc(rec, proc)
    rec["exit_code"] = rc
    # Backends whose stream carries NO terminal event finish here: for them the process exiting IS
    # the end of the turn. claude/codex/pi/dsh all emit something terminal of their own and set
    # `result_ev` in the loop above, so they have no `eof` and this is skipped. opencode does not:
    # its six event types are all mid-turn, and without this a SUCCESSFUL turn produced no final
    # text, no usage, and a status inferred from the exit code alone.
    eof = getattr(normalize, "eof", None)
    if eof is not None and result_ev is None:
        for ev in eof(state, rc):
            ev.setdefault("_ts", time.time())
            if ev.get("type") == "result" and not ev.get("model"):
                served = _relay_served_model(env)
                if served:
                    ev["model"] = served
            if ev.get("type") == "result":
                _fill_relay_usage(ev, env)
            with _turns_lock:
                rec["events"].append(ev)
            if ev.get("type") == "result":
                result_ev = ev
                state["final"] = state.get("final") or ev.get("result") or ""
    if (result_ev is not None and not result_ev.get("is_error")
            and _relay_last_finish(env) == "content_filter"):
        # The provider declined the last request (finish_reason content_filter, seen by the relay)
        # and the CLI reported that as an answer (goose: "The model returned an empty response",
        # measured with claude-opus-5 after a model switch, 2026-09-12). The turn failed, and the
        # reason is the provider's, not a sentence of the CLI's.
        result_ev.update(subtype="error", is_error=True,
                         result="the provider declined the request (finish_reason content_filter)")
        state["final"] = result_ev["result"]
    rec["result"] = state.get("final", "")
    rec["status"] = ("cancelled" if rec.get("cancelled")
                     else "timeout" if rec.get("capped")
                     else _status_from_result(result_ev, rc))
    rec["reason"] = str((result_ev or {}).get("reason") or "")
    # The handoff a run ended on (systemone: the state it refused or escalated on), or None; it
    # rides the status body beside the reason so the gateway can report it without the trace.
    _ho = (result_ev or {}).get("handoff")
    rec["handoff"] = _ho if isinstance(_ho, dict) else None
    # Never leave a failure opaque: surface the captured CLI stderr (and result-event error) so the
    # gateway/trace shows WHY it failed (throttling, model error, etc.) instead of an empty string.
    if rec["status"] in ("failed", "error", "timeout"):
        tail = "\n".join(errbuf[-30:]).strip()
        ev_err = (result_ev or {}).get("result") or (result_ev or {}).get("error") or ""
        refusal = next((ln.strip() for ln in errbuf if _PROVIDER_REFUSAL.search(ln)), "")
        if not refusal and _relay_last_finish(env) == "content_filter":
            # THE PROVIDER DECLINED, and the CLI's own account of a failure it could not see is not
            # the reason. A refused request comes back as an answer with no content and no
            # reasoning, which each harness narrates in its own internal words: agentzero counts
            # five of them and stops with "Agent stopped after 5 consecutive unusable model
            # responses to prevent further API charges" — its loop guard, correct in itself and
            # about a counter nobody outside it can see. The relay watched the same exchange and
            # knows what the provider said. The successful-looking case is rewritten above; this is
            # the same statement for a turn that did fail, in the slot _failure_reason already
            # keeps for a provider's refusal.
            refusal = "the provider declined the request (finish_reason content_filter)"
        rec["error"] = _failure_reason(refusal, str(ev_err), tail, rc)
        if result_ev is not None and not str(result_ev.get("result") or "").strip() and tail:
            result_ev["result"] = tail[:2000]   # so the trace's result event isn't empty either
    rec["done"] = True


_NO_DIAGNOSTIC_RE = re.compile(r"\w[\w-]* exited -?\d+ without reporting an error")


_CLI_RESUME_HINT = re.compile(r"^(To resume this session:|See log: )")


def _failure_reason(refusal: str, ev_err: str, tail: str, rc: int) -> str:
    """The one line that explains a failed turn, in order of how much it says: the provider's
    refusal, the result event's own message, the CLI's last lines, the exit code. A normaliser's
    "<cli> exited N without reporting an error" says nothing the CLI's last lines do not, so those
    lines win over it: goose's tokio panic ("Permission denied (os error 13) at path /tmp/...")
    sat in the stderr behind that sentence and the record never showed it (2026-09-13)."""
    ev_err = ev_err.strip()
    # A CLI's notes to a person at its own terminal are not part of the reason: a "To resume this
    # session: <cli> -r <id>" hint (Kimi CLI printed one after every failure) and Kimi Code CLI's
    # "See log: <a path inside the sandbox>". The person reading the record has neither that CLI
    # nor that path, and both name internals the product does not show. The sentence before them
    # is the reason and stays.
    tail = "\n".join(ln for ln in tail.splitlines() if not _CLI_RESUME_HINT.match(ln.strip())).strip()
    if tail and _NO_DIAGNOSTIC_RE.fullmatch(ev_err):
        ev_err = ""
    return (refusal or ev_err or tail or f"exit_code={rc}, no diagnostic output")[:2000]


# Codex app-server JSON-RPC driver — the ONLY codex mode that streams assistant text (via
# item/agentMessage/delta). Flag-gated; the default codex path stays `codex exec` (batch). We run
# one turn per app-server process (spawn -> initialize -> thread start/resume -> turn -> done), a
# single-threaded read loop that also writes the follow-up requests inline as responses arrive.
def _codex_request_answer(method: str, params: dict) -> tuple[dict | None, str | None]:
    """The runner's answer to a request FROM the app-server, as (result, error): nobody is
    attached and the sandbox is the trust boundary, so every approval is granted and every
    question nobody can answer is declined. A request left pending parks the turn forever
    (thread status waitingOnApproval): codex 0.154 asks before any MCP tool not marked read-only
    through mcpServer/elicitation/request, and the runner's silence stalled every plug write
    (InsForge create_table, Vercel deploy) while reads sailed through (2026-09-30).

    Shapes are codex's own (app-server schema 0.154 to 0.156): permissions want the grant
    back, approvals want a decision, elicitations want an action (+ the form content on accept),
    user input wants answers. Anything else gets a JSON-RPC error so codex hears "no" at once."""
    if method == "item/permissions/requestApproval":
        return {"permissions": params.get("permissions") or {}}, None     # grant what it asked for
    if method.endswith("/requestApproval"):
        return {"decision": "accept"}, None
    if method == "mcpServer/elicitation/request":
        meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
        if meta.get("codex_approval_kind"):     # codex's own question about an MCP tool: approve it
            return {"action": "accept", "content": {}}, None
        return {"action": "decline"}, None      # the MCP server's question: nobody here can answer
    if method == "item/tool/requestUserInput":
        return {"answers": {}}, None
    return None, f"{method} is not answered by this client"



_CODEX_SANDBOX = os.environ.get("CODEX_APPSERVER_SANDBOX", "danger-full-access")  # kebab enum; env-tunable


# on-request: the app-server asks before a command its exec policy marks "prompt" (rm -f, among
# the default rules) and the loop accepts, since the sandbox is the trust boundary. "never" made
# the same policy reject the command outright, in the model's face, and the turn failed.
_CODEX_APPROVAL = "on-request"


def _codex_error_line(p: dict) -> tuple[str, bool]:
    """An `error` notification as one line for the record, and whether it is transient: the
    app-server says so (willRetry) while it reconnects a dropped provider stream, and the turn is
    still running. The underlying reason rides additionalDetails when the server has one; it is
    kept on the line so a failed turn names the HTTP error, not only "Reconnecting... 1/5"
    (gpt-5.6 on Azure, a customer benchmark, 2026-09-30)."""
    err = p.get("error") if isinstance(p.get("error"), dict) else {}
    msg = str(p.get("message") or err.get("message") or "codex error").strip()
    details = str(err.get("additionalDetails") or p.get("additionalDetails") or "").strip()
    line = f"{msg} ({details[:300]})" if details and details not in msg else msg
    transient = bool(p.get("willRetry")) or msg.lower().startswith("reconnecting")
    return line, transient


def _codex_thread_request(resume_session_id: str | None, cwd: str, model: str) -> tuple[str, dict]:
    """The app-server request that opens this turn's thread, with its params.

    A resumed thread takes THIS turn's model and settings too, not only its id: a thread resumed
    bare keeps the tool set of the model it started with, and a turn on another model family
    (gpt-5.3-codex after gpt-5.5) then narrates its work instead of calling tools (reproduced
    three times, 2026-09-05). One params dict serves both requests so they cannot drift."""
    params = {"cwd": cwd, "model": model, "sandbox": _CODEX_SANDBOX, "approvalPolicy": _CODEX_APPROVAL}
    if resume_session_id:
        return "thread/resume", {"threadId": resume_session_id, **params}
    return "thread/start", params


def _run_codex_appserver_bg(turn_id: str, cwd: str, env: dict, model: str, prompt: str,
                            resume_session_id: str | None, timeout_seconds: int | None) -> None:
    rec = _turns[turn_id]
    state = {"final": ""}

    def append(ev: dict) -> None:
        ev.setdefault("_ts", time.time())
        with _turns_lock:
            rec["events"].append(ev)

    # Resume what is actually in this home (see _codex_resume_thread_id), sanitised like the exec
    # path; a follow-up whose rollout is gone starts fresh in the same workspace and says so.
    resume_thread = None
    if resume_session_id:
        cfg_dir = pathlib.Path(env.get("CODEX_HOME") or (pathlib.Path(env.get("HOME") or cwd) / ".codex"))
        resume_thread = _codex_resume_thread_id(cfg_dir, resume_session_id)
        if resume_thread:
            import glob as _glob
            c = _sanitize_codex_rollout(_glob.glob(str(cfg_dir / "sessions" / "**" / "*.jsonl"), recursive=True),
                                        content_only=env.get("HR_CODEX_ACCOUNT_CHANGED") != "0")
            print(f"[resume] codex app-server: thread {resume_thread}{' (newest rollout, wanted ' + resume_session_id + ')' if resume_thread != resume_session_id else ''}; "
                  f"dropped {c['reasoning']} reasoning blob(s), de-referenced {c['deref']} id(s)", flush=True)
        else:
            print(f"[resume] codex app-server: no rollout in workspace for {resume_session_id} — starting fresh", flush=True)
            append({"type": "assistant", "message": {"content": [{"type": "text", "text": _CODEX_NO_ROLLOUT_NOTE}]}})
    try:
        proc = subprocess.Popen(["codex", "app-server"], cwd=cwd, env=env, text=True, bufsize=1,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                start_new_session=True, **_as_session(cwd, env))
    except Exception as e:  # noqa: BLE001
        rec.update(status="failed", error=f"spawn app-server: {e}"[:500], done=True)
        return
    rec["pid"] = proc.pid
    rec["proc"] = proc
    if rec.get("cancelled"):
        _kill_proc_tree(proc)   # Stop raced the spawn — kill immediately, not at pipe EOF
    cap = min(timeout_seconds, MAX_TURN_SECONDS) if timeout_seconds else MAX_TURN_SECONDS
    killer = threading.Timer(cap, _kill_capped, args=(proc, rec))
    killer.daemon = True
    killer.start()

    _nid = [0]
    def _rid() -> int:
        _nid[0] += 1
        return _nid[0]

    def send(method: str, params: dict, notify: bool = False):
        msg = {"method": method, "params": params}
        if not notify:
            msg["id"] = _rid()
        proc.stdin.write(json.dumps(msg) + "\n")  # type: ignore[union-attr]
        proc.stdin.flush()  # type: ignore[union-attr]
        return msg.get("id")

    def reply(mid, result: dict | None, error: str | None = None) -> None:
        body = {"id": mid, "error": {"code": -32601, "message": error}} if error else {"id": mid, "result": result}
        proc.stdin.write(json.dumps(body) + "\n")  # type: ignore[union-attr]
        proc.stdin.flush()  # type: ignore[union-attr]

    errbuf: list[str] = []
    usage: dict = {}
    turn_status = None
    thread_id = None
    id_init = id_thread = id_turn = None
    try:
        id_init = send("initialize", {"clientInfo": {"name": "harness-runner", "title": "HarnessRouter", "version": "1"},
                                      "capabilities": {"experimentalApi": True, "optOutNotificationMethods": []}})
        for raw in proc.stdout:  # type: ignore[union-attr]
            raw = raw.strip()
            if not raw:
                continue
            if not raw.startswith("{"):
                errbuf.append(raw)
                if len(errbuf) > 80:
                    del errbuf[0]
                continue
            try:
                msg = json.loads(raw)
            except Exception:  # noqa: BLE001
                continue
            mid = msg.get("id")
            method = msg.get("method")
            if method is None and mid is not None:              # a response to one of our requests
                if msg.get("error") and mid in (id_init, id_thread, id_turn):
                    errbuf.append(str((msg["error"] or {}).get("message") or "app-server error"))
                    turn_status = "failed"
                    break
                res = msg.get("result") or {}
                if mid == id_init:
                    send("initialized", {}, notify=True)
                    id_thread = send(*_codex_thread_request(resume_thread, cwd, model))
                elif mid == id_thread:
                    thread_id = ((res.get("thread") or {}).get("id")) or resume_session_id or ""
                    if thread_id:
                        append({"type": "system", "subtype": "init", "session_id": thread_id, "model": model})
                        rec["session_id"] = thread_id
                    id_turn = send("turn/start", {"threadId": thread_id, "model": model,
                                   "approvalPolicy": _CODEX_APPROVAL, "input": [{"type": "text", "text": prompt}]})
                continue
            if mid is not None and method:                      # a request FROM the app-server
                # Every request gets an answer at once (see _codex_request_answer): the exec
                # policy's "prompt" rules (rm -f among them), codex's question before a write MCP
                # tool, a permission grant. Under approvalPolicy never the same rules rejected the
                # command outright and the turn died; left unanswered, the turn parks (2026-09-30).
                result, err = _codex_request_answer(method, msg.get("params") or {})
                print(f"[codex] {method}: {'error ' + err if err else json.dumps(result)[:120]}", flush=True)
                reply(mid, result, err)
                continue
            p = msg.get("params") or {}                          # a notification
            if method == "item/agentMessage/delta":
                d = p.get("delta") or ""
                if d:
                    state["final"] += d
                    append({"type": "assistant", "message": {"content": [{"type": "text", "text": d}]}})
            elif method in ("item/reasoning/summaryTextDelta", "item/reasoning/textDelta"):
                d = p.get("summaryDelta") or p.get("delta") or ""
                if d:
                    append({"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": d}]}})
            elif method == "item/completed":
                it = p.get("item") or {}
                for ev in _codex_tool_item(it):     # messages and reasoning yield nothing: already streamed as deltas
                    append(ev)
            elif method == "turn/completed":
                # Final cumulative usage may also ride the completed turn; read it as a fallback.
                turn_obj = p.get("turn") or {}
                nu = _norm_token_usage(turn_obj or p)
                if nu.get("input_tokens") or nu.get("output_tokens"):
                    usage = nu
                turn_status = turn_obj.get("status") or "completed"
                break
            elif ("token" in method.lower() and "usage" in method.lower()) or method.lower().endswith("tokencount"):
                # codex app-server emits thread/tokenUsage/updated with the running total under
                # params.tokenUsage.total (verified 2026-07-23). Keep the LATEST (it's cumulative).
                # Matching on method SHAPE, not one exact string, so a rename can't zero billing.
                nu = _norm_token_usage(p)
                if nu.get("input_tokens") or nu.get("output_tokens"):
                    usage = nu
            elif method == "error":
                line, transient = _codex_error_line(p)
                errbuf.append(line)
                if transient:
                    continue        # the app-server is retrying the provider stream; the turn goes on
                turn_status = "failed"
                break
            elif method == "turn/failed":
                errbuf.append(str(p.get("message") or (p.get("error") or {}).get("message") or "codex error"))
                turn_status = "failed"
                break
    except Exception as e:  # noqa: BLE001
        errbuf.append(f"{type(e).__name__}: {str(e)[:150]}")
        turn_status = turn_status or "failed"
    finally:
        killer.cancel()
        _release_proc(rec, proc)
        try:
            if proc.poll() is None:
                _kill_proc_tree(proc)                            # one turn per process — never reuse
        except Exception:  # noqa: BLE001
            pass

    # A turn that produced a final agent answer SUCCEEDED from the caller's view — even if codex then
    # fumbles the turn close. gpt-5.5 refusals are the sharp case: the model returns a clean final
    # answer ("I'm sorry, but I cannot assist…"), after which codex app-server prints "Reconnecting…
    # N/5" and marks the turn failed. That mislabels a completed model response as broken infra. So:
    # if we captured a non-empty final answer and the only failure signal is reconnect/EOF noise (not a
    # real execution error), treat the turn as done and show the model's message cleanly.
    def _is_reconnect_noise(s: str) -> bool:
        low = s.strip().lower()
        return (not low) or ("reconnect" in low) or ("stream closed" in low) or low in ("eof", "connection closed")
    answered = bool(state["final"].strip())
    noise_only = all(_is_reconnect_noise(l) for l in errbuf) if errbuf else True
    ok = ((turn_status in ("completed", None)) or (answered and noise_only)) \
        and not rec.get("cancelled") and not rec.get("capped")
    err_txt = ("\n".join(errbuf[-30:]).strip() or f"app-server turn status: {turn_status}")[:2000]
    # On a genuine failure, lead with the agent's own last words (often the real reason, e.g.
    # "workspace is read-only") and follow with the technical error, so the Result row is never a
    # blank "Failed" with no explanation.
    if ok:
        res_txt = state["final"]
    else:
        res_txt = "\n\n".join(x for x in (state["final"].strip(), err_txt) if x)[:4000] or err_txt
    append({"type": "result", "subtype": "success" if ok else "error", "is_error": not ok,
            "result": res_txt, "usage": usage})   # surface the error in the trace
    rec["result"] = state["final"]
    rec["status"] = ("cancelled" if rec.get("cancelled") else "timeout" if rec.get("capped")
                     else "done" if ok else "failed")
    if not ok:
        rec["error"] = err_txt
        rec["tried"] = [{"connection": "codex-app-server", "error": err_txt[:400]}]  # -> gateway failure msg
    rec["done"] = True


# ── hermes driver — DB-polling turn runner ───────────────────────────────────────
# hermes-agent emits no event stream on stdout, but flushes every message (assistant text,
# OpenAI-style tool_calls, tool results) incrementally into $HERMES_HOME/state.db during the run.
# This driver spawns the CLI, tails that table, and synthesizes the same canonical claude
# stream-json events the other backends produce, so everything downstream stays uniform.
_HERMES_POLL_S = 0.8
# A fresh (non-resume) turn's cursor stays at "no session row yet" until the hermes CLI itself
# writes one to state.db — the driver has NO other progress signal before that. If the subprocess
# blocks on an unbounded network call (provider auth/model init) before ever reaching that write,
# the turn shows zero events with no error, indistinguishable from "still working," for as long as
# MAX_TURN_SECONDS / the caller's timeout_seconds allows (hours by default). This is a SEPARATE,
# much shorter bound on just that startup window, independent of the overall per-turn cap.
#
# "Started" means THE MODEL PRODUCED SOMETHING, not merely that a session row appeared. Those are
# different moments: hermes writes the session and echoes the user's prompt before it calls the
# provider, so keying the guard on the session row disarmed it a fraction of a second in, and a
# CLI that then produced nothing at all was left to run against the six-hour cap — the console
# showing "Working…" the whole time. Observed with z-ai/glm-5.2 on hermes 0.19.0, which returns a
# clean stream when called directly (2.2s, content "ok") and hangs inside the CLI after it.
#
# A tool call that legitimately runs for minutes is NOT affected: hermes writes the assistant
# message carrying the tool call before executing it, so output exists and the guard is disarmed.
_HERMES_STARTUP_TIMEOUT_S = float(os.environ.get("HERMES_STARTUP_TIMEOUT_S", "90"))


def _hermes_db_ro(db_path: str) -> sqlite3.Connection | None:
    try:
        db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2)
        db.row_factory = sqlite3.Row
        return db
    except Exception:  # noqa: BLE001 — db not created yet / mid-write
        return None


def _hermes_session_row(db_path: str, sid: str) -> dict | None:
    db = _hermes_db_ro(db_path)
    if db is None:
        return None
    try:
        # SELECT * (not a fixed column list): a schema drift in the token column names must not
        # throw and zero out billing. Normalize the token counters by name after the read.
        r = db.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
        if not r:
            return None
        d = dict(r)
        cols = {k.lower(): k for k in d.keys()}

        def _tok(*names) -> int:
            for n in names:
                col = cols.get(n)
                if col is not None and isinstance(d[col], (int, float)) and d[col]:
                    return int(d[col])
            return 0

        return {"id": d.get(cols.get("id", "id")),
                "input_tokens": _tok("input_tokens", "inputtokens", "prompt_tokens",
                                     "prompt_token_count", "total_input_tokens"),
                "output_tokens": _tok("output_tokens", "outputtokens", "completion_tokens",
                                      "completion_token_count", "total_output_tokens")}
    except Exception:  # noqa: BLE001
        return None
    finally:
        db.close()


def _hermes_msg_events(row: sqlite3.Row, state: dict) -> list[dict]:
    """Map ONE state.db message row to canonical events (the _codex_to_claude shapes)."""
    evs: list[dict] = []
    role = row["role"]
    content = row["content"] or ""
    if role == "assistant":
        keys = row.keys()
        reasoning = ((row["reasoning_content"] if "reasoning_content" in keys else None)
                     or (row["reasoning"] if "reasoning" in keys else None) or "")
        if str(reasoning).strip():
            evs.append({"type": "assistant", "message": {"content": [
                {"type": "thinking", "thinking": str(reasoning)}]}})
        if content.strip():
            evs.append({"type": "assistant", "message": {"content": [{"type": "text", "text": content}]}})
            state["final"] = content   # last assistant text wins
        for tc in json.loads(row["tool_calls"]) if row["tool_calls"] else []:
            fn = (tc or {}).get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except Exception:  # noqa: BLE001
                args = {"raw": fn.get("arguments")}
            evs.append({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": tc.get("id") or f"htool_{row['id']}",
                 "name": fn.get("name") or "tool", "input": args}]}})
    elif role == "tool":
        evs.append({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": row["tool_call_id"] or "",
             "is_error": False, "content": content[:20000]}]}})
    # role == "user" rows are the prompt echo — the gateway already has it; skip.
    return evs


def _run_hermes_bg(turn_id: str, cwd: str, env: dict, model: str, provider: str, prompt: str,
                   resume_session_id: str | None, timeout_seconds: int | None,
                   mcp_toolsets: list[str] | None = None) -> None:
    rec = _turns[turn_id]
    state: dict = {"final": ""}
    db_path = os.path.join(env["HERMES_HOME"], "state.db")
    t0 = time.time()

    def append(ev: dict) -> None:
        ev.setdefault("_ts", time.time())
        with _turns_lock:
            rec["events"].append(ev)

    # Resume guard (claude/codex precedent): only resume a session that actually exists in the
    # (re)hydrated state.db — a recorded-but-never-checkpointed id must start fresh, not wedge.
    resume = None
    pre = None
    if resume_session_id:
        pre = _hermes_session_row(db_path, resume_session_id)
        if pre:
            resume = resume_session_id
        else:
            print(f"[resume] hermes: session {resume_session_id} not in workspace — starting fresh", flush=True)
            # Make the lost continuity a VISIBLE event, not just a server log line — the caller
            # believed this was a continuation; silently starting fresh instead is a correctness
            # surprise (missing context) the user/gateway has no way to detect otherwise. Gateway
            # translates this subtype into a short note at the top of the reply (_blocks_from_canonical).
            append({"type": "system", "subtype": "resume_lost", "requested_session_id": resume_session_id})
    usage_path = os.path.join(env.get("TMPDIR") or tempfile.gettempdir(), f"hermes-usage-{turn_id}.json")
    # chat -q is REQUIRED for two cases; plain -z covers the rest (cleanest stdout/usage contract):
    #  - resume: oneshot has no resume parameter; chat honors -r.
    #  - MCP:    only chat's agent setup JOINS background MCP discovery before the first tool
    #            snapshot (bounded by config mcp_discovery_timeout). A one-shot races discovery
    #            and runs without the MCP tools (verified live on 0.19.0).
    use_chat = bool(resume) or bool(mcp_toolsets)
    if use_chat:
        # Final text + per-turn usage come from state.db (chat stdout carries banner noise).
        cmd = ["hermes", "chat", "-q", prompt, "-Q", "--yolo", "--accept-hooks",
               "--provider", provider, "--model", model]
        if resume:
            cmd += ["-r", resume]
    else:
        cmd = ["hermes", "-z", prompt, "--provider", provider, "--model", model,
               "--usage-file", usage_path]
    try:
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, text=True, bufsize=1,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True, **_as_session(cwd, env))
    except Exception as e:  # noqa: BLE001
        rec.update(status="failed", error=f"spawn: {e}"[:500], done=True)
        return
    rec["pid"] = proc.pid
    rec["proc"] = proc
    if rec.get("cancelled"):
        _kill_proc_tree(proc)
    cap = min(timeout_seconds, MAX_TURN_SECONDS) if timeout_seconds else MAX_TURN_SECONDS
    killer = threading.Timer(cap, _kill_capped, args=(proc, rec))
    killer.daemon = True
    killer.start()
    out_buf: list[str] = []
    err_buf: list[str] = []

    def _drain(pipe, buf, cap_lines=200):
        for line in pipe:
            buf.append(line.rstrip("\n"))
            if len(buf) > cap_lines:
                del buf[0]
    t_out = threading.Thread(target=_drain, args=(proc.stdout, out_buf), daemon=True)
    t_err = threading.Thread(target=_drain, args=(proc.stderr, err_buf), daemon=True)
    t_out.start(); t_err.start()

    sid = resume
    cursor = 0
    produced = False        # has the model emitted ANY message yet (see _HERMES_STARTUP_TIMEOUT_S)
    if resume:
        db = _hermes_db_ro(db_path)
        if db is not None:
            try:  # only rows appended by THIS turn become events
                cursor = db.execute("SELECT COALESCE(MAX(id),0) FROM messages WHERE session_id=?",
                                    (resume,)).fetchone()[0]
            except Exception:  # noqa: BLE001
                pass
            finally:
                db.close()
        append({"type": "system", "subtype": "init", "session_id": resume, "model": model})

    def _sweep() -> None:
        nonlocal sid, cursor, produced
        db = _hermes_db_ro(db_path)
        if db is None:
            return
        try:
            if sid is None:
                r = db.execute(
                    "SELECT id FROM sessions WHERE CAST(started_at AS REAL) >= ? ORDER BY started_at DESC LIMIT 1",
                    (t0 - 5,)).fetchone()
                if r:
                    sid = r["id"]
                    rec["session_id"] = sid
                    append({"type": "system", "subtype": "init", "session_id": sid, "model": model})
            if sid is None:
                return
            for row in db.execute(
                    "SELECT * FROM messages WHERE session_id=? AND id>? ORDER BY id", (sid, cursor)):
                cursor = row["id"]
                # The prompt hermes echoes back is not the model producing anything.
                if str(row["role"] or "").lower() != "user":
                    produced = True
                for ev in _hermes_msg_events(row, state):
                    append(ev)
        except Exception:  # noqa: BLE001 — mid-write reads can transiently fail; next poll catches up
            pass
        finally:
            db.close()

    try:
        while proc.poll() is None:
            _sweep()
            # Fires whether the session row never appeared or appeared and then produced nothing;
            # both mean the provider call hung before any output, and both used to be survivable
            # only by the six-hour cap.
            if not produced and (time.time() - t0) > _HERMES_STARTUP_TIMEOUT_S:
                rec["capped"] = True
                rec["startup_timeout"] = True
                _kill_proc_tree(proc)
                break
            time.sleep(_HERMES_POLL_S)
        t_out.join(timeout=5)
        t_err.join(timeout=5)
        _sweep()   # final drain after EOF so the last messages always land
    finally:
        killer.cancel()
        proc.wait()
        _release_proc(rec, proc)
    rc = proc.returncode
    if sid:
        rec["session_id"] = sid
    # Usage: the session row's cumulative token counters are the one uniform source — absolute
    # for a fresh session, diffed against the pre-read for a resume. The -z usage report is the
    # authority on the run's failed flag (exit 0 can still mean failure, verified live) and the
    # session-id fallback when the DB was never seen.
    usage = {"input_tokens": 0, "output_tokens": 0}
    run_failed = False
    if sid:
        post = _hermes_session_row(db_path, sid) or {}
        usage = {"input_tokens": max(0, int(post.get("input_tokens") or 0) - int((pre or {}).get("input_tokens") or 0)),
                 "output_tokens": max(0, int(post.get("output_tokens") or 0) - int((pre or {}).get("output_tokens") or 0))}
    if not use_chat:
        try:
            with open(usage_path) as f:
                u = json.load(f)
            run_failed = bool(u.get("failed"))
            if not usage["input_tokens"] and u.get("input_tokens"):
                usage = {"input_tokens": int(u.get("input_tokens") or 0),
                         "output_tokens": int(u.get("output_tokens") or 0)}
            if not sid and u.get("session_id"):
                sid = u["session_id"]
                rec["session_id"] = sid
                append({"type": "system", "subtype": "init", "session_id": sid, "model": model})
        except Exception:  # noqa: BLE001 — no report ⇒ judge by exit code alone
            pass
        finally:
            try:
                os.unlink(usage_path)
            except OSError:
                pass
    # -z prints ONLY the final text on stdout — authoritative there; chat runs read the DB
    # (their stdout carries banner noise).
    final = state.get("final", "")
    if not use_chat:
        final = "\n".join(out_buf).strip() or final
    ok = rc == 0 and not run_failed and not rec.get("cancelled") and not rec.get("capped") and bool(final.strip())
    err_txt = ("\n".join(err_buf[-30:]).strip() or f"exit_code={rc}")[:2000]
    if rec.get("startup_timeout"):
        # The generic exit_code/stderr text is useless here (the process was killed by US, not a
        # normal failure) — say what actually happened instead of leaving a cryptic "exit_code=-9".
        err_txt = (f"This model produced no output within {_HERMES_STARTUP_TIMEOUT_S:.0f}s and the "
                   f"turn was stopped. The provider call hung before returning anything.\n{err_txt}"
                   )[:2000]
    res_txt = final if ok else ("\n\n".join(x for x in (final.strip(), err_txt) if x)[:4000] or err_txt)
    ev = {"type": "result", "subtype": "success" if ok else "error", "is_error": not ok,
          "result": res_txt, "usage": usage}
    # What the relay saw the provider say: the served model, and the usage with its cache split.
    # hermes's session counters carry no cache figures, so a Claude turn through the relay read as
    # uncached and unlabelled on the result (hr-test, 2026-09-30) while the provider had cached it.
    served = _relay_served_model(env)
    if served:
        ev["model"] = served
    _fill_relay_usage(ev, env)
    append(ev)
    rec["exit_code"] = rc
    rec["result"] = final
    rec["status"] = ("cancelled" if rec.get("cancelled") else "timeout" if rec.get("capped")
                     else "done" if ok else "failed")
    if not ok and rec["status"] in ("failed", "timeout"):
        rec["error"] = err_txt
    rec["done"] = True


# ── HTTP surface ─────────────────────────────────────────────────────────────────
@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "host": socket.gethostname(),
            "sidecars": sum(1 for s in _sidecars if _sidecar_alive(s))}


@app.get("/backends")
def backends() -> dict:
    return {b: {"providers": v["providers"], "default_model": v["default_model"]}
            for b, v in BACKENDS.items()}


# sha256 of the checkpoint each session's workspace currently holds. PER SESSION, and outside
# the workspace so it survives the wipe: one shared marker meant a second session's hydrate
# answered the first session's "do you already have this checkpoint?" probe.
_WS_MARKER_DIR = "/tmp/hr-ws"


def _ws_marker_path(identifier: str) -> pathlib.Path:
    sid = _SID_SAFE.sub("_", (identifier or "").strip())[:120] or "_default"
    return pathlib.Path(_WS_MARKER_DIR) / f"{sid}.sha"


def _ws_marker_set(identifier: str, sha: str) -> None:
    try:
        p = _ws_marker_path(identifier)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(sha or "")
    except Exception:  # noqa: BLE001
        pass


def _ws_marker_get(identifier: str) -> str:
    try:
        return _ws_marker_path(identifier).read_text().strip()
    except Exception:  # noqa: BLE001
        return ""


def _ws_marker_clear(identifier: str) -> None:
    try:
        _ws_marker_path(identifier).unlink()
    except OSError:
        pass


def _ws_holds(identifier: str, ws_path: pathlib.Path, sha: str) -> bool:
    """Whether this session's workspace still holds checkpoint `sha`: the marker says so AND the
    folder is there to back it. The marker lives outside the workspace on purpose (it has to
    survive the wipe), which also lets it outlive the workspace: the folder deleted from the
    volume by hand while the runner container was merely stopped and started, or removed by
    DELETE /workspace before it learned to drop the marker. Either way the next probe answered
    "held", the gateway skipped the restore, and the turn ran on an empty folder — the CLI found
    no session to resume and the conversation started over (richard-epsilla, #194). A workspace
    restored from a checkpoint always carries its .git (the tarball does, and _git_ensure runs
    after every restore), so a folder without one holds nothing, whatever the marker says; the
    marker that vouched for it is dropped so the full hydrate that follows starts clean."""
    if _ws_marker_get(identifier) != sha:
        return False
    if (ws_path / ".git").is_dir():
        return True
    _ws_marker_clear(identifier)
    return False


@app.post("/hydrate")
async def hydrate(request: Request, identifier: str = "") -> dict:
    """Restore /workspace from a checkpoint tarball (the request body). Empty body = a fresh
    repo. The CLI conversation state under .harness/ is restored too, so `--resume` can continue
    a prior turn that ran on a DIFFERENT sandbox.

    The body is SPOOLED TO LOCAL DISK as it arrives (HR-INF-015): a GB checkpoint no longer
    materializes in the sandbox's ~2 GiB RAM. sha256 folds over the incoming stream; untar reads
    from the spooled file. CRITICALLY, the spool completes BEFORE the workspace wipe — a truncated
    upload (client disconnect) raises during spooling and leaves the current workspace untouched."""
    _reap_workspaces(keep=_SID_SAFE.sub("_", (identifier or "").strip())[:120] or "_default")
    ws = _ws(identifier)
    ws_path = pathlib.Path(ws)
    ws_path.mkdir(parents=True, exist_ok=True)
    _isolate_session(ws)
    fd, spool_path = tempfile.mkstemp(suffix=".tgz", dir=SPOOL_DIR)   # OUTSIDE the workspace
    h = hashlib.sha256()
    nbytes = 0
    try:
        with os.fdopen(fd, "wb") as out:
            async for chunk in request.stream():
                if chunk:
                    out.write(chunk)
                    h.update(chunk)
                    nbytes += len(chunk)
    except Exception as e:  # truncated/aborted upload: workspace NOT touched yet — safe to 400
        try:
            os.unlink(spool_path)
        except OSError:
            pass
        raise HTTPException(400, f"hydrate body incomplete: {str(e)[:200]}")
    try:
        # Probe: the gateway asks "do you already hold checkpoint <sha>?" BEFORE downloading and
        # re-pushing a potentially huge tarball. A warm sandbox that just ran the previous turn
        # answers yes — making follow-up turns start instantly instead of paying wipe + untar.
        probe = request.query_params.get("probe", "")
        if probe and nbytes == 0:
            if _ws_holds(identifier, ws_path, probe):
                collab_url = request.query_params.get("collab_url", "")
                room = request.query_params.get("room", "")
                if collab_url and room:
                    _start_sidecar(identifier, collab_url, room,
                                   request.query_params.get("collab_token", ""))
                return {"ok": True, "skipped": True, "restored": False,
                        "sidecar": _sidecar_alive(identifier),
                        "room": (_sidecars.get(identifier) or {}).get("room")}
            return {"ok": True, "skipped": False}
        # Warm-pool sandboxes are REUSED across sessions, so /workspace may hold a PRIOR session's
        # files (incl. another tenant's). Wipe it before restoring so this session starts from
        # exactly its own checkpoint (or empty) — multi-tenant isolation, not best-effort.
        for child in ws_path.iterdir():
            try:
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink()
            except Exception:  # noqa: BLE001
                pass
        restored = False
        if nbytes:
            with open(spool_path, "rb") as tar_in:
                proc = subprocess.run(["tar", "xzf", "-", "-C", ws], stdin=tar_in, capture_output=True,
                                      **_as_session(ws))
            if proc.returncode != 0:
                raise HTTPException(500, f"untar failed: {proc.stderr.decode(errors='replace')[:300]}")
            restored = True
        _ws_marker_set(identifier, h.hexdigest() if nbytes else "")
    finally:
        try:
            os.unlink(spool_path)
        except OSError:
            pass
    _git_ensure(ws)
    # (Re)start the realtime blackboard sidecar for this session if the gateway passed a room.
    collab_url = request.query_params.get("collab_url", "")
    room = request.query_params.get("room", "")
    if collab_url and room:
        _start_sidecar(identifier, collab_url, room, request.query_params.get("collab_token", ""))
    n = sum(1 for p in pathlib.Path(ws).rglob("*") if ".git" not in p.parts)
    return {"ok": True, "restored": restored, "bytes_in": nbytes, "files": n, "workspace": ws,
            "sidecar": _sidecar_alive(identifier),
            "room": (_sidecars.get(identifier) or {}).get("room")}


@app.get("/checkpoint")
def checkpoint(background_tasks: BackgroundTasks, identifier: str = "") -> Response:
    """Commit /workspace and return it as a gzip tarball (secrets/scratch excluded). The gateway
    persists this to durable blob storage; the next turn's /hydrate restores it on any sandbox.

    Spools the tar to LOCAL DISK instead of a RAM buffer (HR-INF-015): a big (GB) workspace no
    longer materializes the whole tarball in the sandbox's ~2 GiB RAM alongside the CLI. tar writes
    straight to a temp file; sha256 is folded over a chunked read of that file; FileResponse then
    streams it to the gateway. The temp file is removed after the response is sent."""
    _reap_spool()   # clear any spool file leaked by a prior mid-stream disconnect
    ws = _ws(identifier)
    _git_ensure(ws)
    _git(ws, "add", "-A")
    _git(ws, "commit", "-q", "-m", f"checkpoint {int(time.time())}", "--allow-empty")
    excl = [f"--exclude={p}" for p in CHECKPOINT_EXCLUDE]
    fd, tar_path = tempfile.mkstemp(suffix=".tgz", dir=SPOOL_DIR)   # OUTSIDE the workspace
    try:
        with os.fdopen(fd, "wb") as out:
            proc = subprocess.run(["tar", "-I", "gzip -1", "-cf", "-", *excl, "-C", ws, "."],
                                  stdout=out, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            os.unlink(tar_path)
            raise HTTPException(500, f"tar failed: {proc.stderr.decode(errors='replace')[:300]}")
        h = hashlib.sha256()
        nbytes = 0
        with open(tar_path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
                nbytes += len(chunk)
        head = _git(ws, "rev-parse", "--short", "HEAD").stdout.strip()
        _ws_marker_set(identifier, h.hexdigest())   # this session now HOLDS this checkpoint
        background_tasks.add_task(os.unlink, tar_path)   # cleanup after the response streams out
        return FileResponse(tar_path, media_type="application/gzip", background=background_tasks,
                            headers={"X-Checkpoint-Bytes": str(nbytes), "X-Git-Head": head})
    except HTTPException:
        raise
    except Exception:
        try:
            os.unlink(tar_path)
        except OSError:
            pass
        raise


# ── the COLLECTION cursor: a git ref advanced only when the gateway has captured the files ──────
# Collection used to be "uncommitted vs HEAD", which made HEAD double as the collection cursor —
# and /checkpoint moves HEAD unconditionally. Any terminal path that skipped collection (crash,
# cancel, OOM kill, sweep-settle) followed by any checkpoint therefore buried the turn's files:
# still on disk, permanently invisible to /produced. Watched happen live, twice, to the same deck
# (2026-08-25). The cursor is now its own ref, so "checkpointed" no longer implies "collected",
# and whatever a dead turn left behind is simply produced by the next turn that does collect.
_COLLECTED_REF = "refs/hr/collected"


def _collected_init(ws: str) -> None:
    """Point the cursor at the current HEAD if it does not exist yet — hydrate/first-turn
    semantics: what arrived in the checkpoint was not produced by any turn here."""
    if _git(ws, "rev-parse", "-q", "--verify", _COLLECTED_REF).returncode != 0:
        head = _git(ws, "rev-parse", "-q", "--verify", "HEAD")
        if head.returncode == 0:
            _git(ws, "update-ref", _COLLECTED_REF, head.stdout.strip())


def _produced_keep(status: str, path: str) -> bool:
    if not path or path.endswith("/") or status.startswith("D"):
        return False
    if path in _PRODUCED_EXCLUDE_NAMES or path.startswith(_PRODUCED_EXCLUDE_PREFIX):
        return False
    return not _is_produced_noise(path)


def _produced_list(ws: str) -> list[dict]:
    """Everything changed since the last ACKNOWLEDGED collection: committed changes past the
    cursor (diff <ref> → worktree) plus untracked files. NOT merely uncommitted-vs-HEAD."""
    _git_ensure(ws)
    _collected_init(ws)
    seen: dict[str, str] = {}
    if _git(ws, "rev-parse", "-q", "--verify", _COLLECTED_REF).returncode == 0:
        d = _git(ws, "diff", "--name-status", _COLLECTED_REF)
        for line in (d.stdout or "").splitlines():
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            status, path = parts[0], parts[-1].strip().strip('"')
            if _produced_keep(status, path):
                seen[path] = status[:1]
    p = _git(ws, "status", "--porcelain", "-uall")
    for line in (p.stdout or "").splitlines():
        if len(line) < 4:
            continue
        status, path = line[:2], line[3:]
        if " -> " in path:                       # rename: take the new path
            path = path.split(" -> ", 1)[1]
        path = path.strip().strip('"')
        if _produced_keep(status, path):
            seen.setdefault(path, status.strip() or "?")
    # mtime rides on each item so a reader can put the newest first: a response carries at most
    # HARNESS_RESP_MAX_FILES of them, and git's path order handed a Mario run its first 24 frames
    # of 1,400 (hosted, 2026-09-25). 0 when the file is gone (a deletion) or cannot be stat'ed.
    def _mtime(rel: str) -> float:
        try:
            return float(os.stat(os.path.join(ws, rel)).st_mtime)
        except OSError:
            return 0.0
    return [{"path": k, "status": v, "mtime": _mtime(k)} for k, v in seen.items()]


def _produced_ack(ws: str) -> str:
    """Advance the cursor: commit the current state and point the ref at it. Called by the gateway
    ONLY after it has captured the listed files, which is the one thing that makes 'collected'
    mean collected."""
    _git_ensure(ws)
    _git(ws, "add", "-A")
    _git(ws, "commit", "-q", "-m", f"collected {int(time.time())}", "--allow-empty")
    head = _git(ws, "rev-parse", "HEAD").stdout.strip()
    _git(ws, "update-ref", _COLLECTED_REF, head)
    return head


@app.get("/produced")
def produced(identifier: str = "") -> dict:
    """Files changed since the last acknowledged collection — surviving checkpoints, crashes and
    cancels in between. Excludes internal state / scratch / secrets / vcs."""
    ws = _ws(identifier)
    out = _produced_list(ws)
    return {"files": out, "count": len(out)}


@app.post("/produced/ack")
def produced_ack(identifier: str = "") -> dict:
    ws = _ws(identifier)
    return {"ok": True, "collected": _produced_ack(ws)}


@app.get("/file")
def get_file(path: str, identifier: str = "") -> Response:
    """Raw bytes of a workspace file (for downloading turn-produced container files)."""
    dest = _safe_join(_ws(identifier), path)
    if dest is None or not dest.is_file():
        raise HTTPException(404, "file not found")
    media = mimetypes.guess_type(str(dest))[0] or "application/octet-stream"
    return Response(content=dest.read_bytes(), media_type=media)


@app.put("/file")
async def put_file(request: Request, path: str, identifier: str = "") -> dict:
    """Write ONE file into a session's workspace, as that session.

    The runner is the only process that acts for a session, and behind the write-wall it is the
    only one that CAN: the session directory belongs to the session's own uid, so the product
    cannot reach into it (that is the point). A live app writing a file into a workspace comes
    through here instead. Written beside and renamed, so a reader mid-turn sees the old file or
    the new one, never a half-written one."""
    ws = _ws(identifier)
    dest = _safe_join(ws, path)
    if dest is None:
        raise HTTPException(400, "path escapes the workspace")
    data = await request.body()
    pathlib.Path(ws).mkdir(parents=True, exist_ok=True)
    _isolate_session(ws)
    uid = _session_uid(ws)
    missing: list[pathlib.Path] = []
    probe = dest.parent
    while not probe.exists():
        missing.append(probe)
        probe = probe.parent
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / f".hr-put-{uuid.uuid4().hex[:8]}"
    try:
        tmp.write_bytes(data)
        os.chmod(tmp, 0o644)
        if uid is not None:
            for d in missing:
                os.chown(d, uid, uid)
            os.chown(tmp, uid, uid)
        os.replace(tmp, dest)
    except OSError as e:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise HTTPException(500, f"write failed: {str(e)[:200]}")
    return {"ok": True, "path": str(dest.relative_to(ws)), "bytes": len(data)}


@app.get("/capabilities")
def capabilities(identifier: str = "") -> dict:
    _wsdir = _ws(identifier)
    return {
        "host": socket.gethostname(),
        "workspace": _wsdir,
        "workspace_writable": os.path.isdir(_wsdir) and os.access(_wsdir, os.W_OK),
        "user": _ver(["whoami"]),
        "git": _ver(["git", "--version"]),
        "node": _ver(["node", "--version"]),
        "backends": {"claude": _ver(["claude", "--version"]), "codex": _ver(["codex", "--version"]),
                     "hermes": _ver(["hermes", "--version"])},
        "providers": {b: v["providers"] for b, v in BACKENDS.items()},
    }


class TurnReq(BaseModel):
    backend: str = "claude"          # claude | codex | hermes | pi | dsh
    provider: str | None = None      # see BACKENDS[...].providers
    model: str | None = None
    native_model: str | None = None   # gemini: the provider's own name for `model` on the native path (TokenRouter's google/<id>)
    prompt: str
    max_turns: int = 400
    timeout_seconds: int | None = None     # per-turn wall-clock cap (bounded by MAX_TURN_SECONDS)
    cwd: str | None = None
    auth: Auth | None = None
    resume_session_id: str | None = None   # claude session id of a prior turn → conversational resume
    files: list[dict] | None = None        # caller-attached input files: [{filename, content_b64}]
    mcp_servers: list[dict] | None = None  # enabled MCP servers: [{name, url, transport?, auth?, headers?}]
    skills: list[dict] | None = None       # enabled skills: [{name, files:[{path, content|content_b64}]}]
    plugins: list[dict] | None = None      # enabled Claude Code plugins: [{name, files:[{path, content|content_b64}]}]
    agent_doc: str | None = None           # harness instruction doc → AGENTS.md (codex) / CLAUDE.md (claude)
    skills_suppressed: list[str] | None = None  # built-in skill names to NOT mount (harness disabled them)
    tools_disabled: list[str] | None = None     # built-in tool names to disable (claude: --disallowedTools)
    image_auth: dict | None = None         # {base_url, api_key, model} for image generation via the broker
    env: dict | None = None                # variables for the turn process: the harness's own (resolved by the
                                           # gateway, see _caller_env) and the platform's HR_ names (a harness
                                           # that drives another one gets HR_API_URL + HR_CALIBRATION_TOKEN)
    env_secret: list[str] | None = None    # the names in env whose values came through a reference: never
                                           # in anything the gateway reads back (see _turn_secrets)
    metadata: dict | None = None           # systemone: {"systemone": {"script": [...]}} selects a scripted provider (a probe)
    idempotency_key: str = ""              # dedup a retried /turn: same key -> same turn, no re-exec
    partial_messages: bool = False         # claude: stream token-level deltas (--include-partial-messages)
    vision: bool = True                    # pi: whether the model's channel accepts image input
    vision_auth: dict | None = None        # hermes: {provider, model, base_url, api_key} for its image questions
    codex_appserver: bool = False          # codex: run via app-server (streams item/agentMessage/delta)
    environment: dict | None = None        # {id, slug, entry}: the project layer at /env/<slug>, read-only (environments.py)


@app.post("/turn")
def turn(req: TurnReq, identifier: str = "") -> dict:
    """Start a turn asynchronously and return immediately. Poll GET /turn/{id} for progress —
    a turn may run seconds to the 6h cap, far beyond a synchronous HTTP request.

    Idempotent by idempotency_key: the gateway retries this call on a lost/slow reply (a turn can
    take minutes to acknowledge), and without dedup each retry would start a SECOND CLI process in
    this sandbox — the same request executed twice. A key seen before returns the existing turn."""
    key = (req.idempotency_key or "").strip()
    if key:
        with _turns_lock:
            prior_id = _turn_by_key.get(key)
            if prior_id and prior_id in _turns:
                r = _turns[prior_id]
                return {"turn_id": prior_id, "status": r.get("status", "running"),
                        "backend": r.get("backend", ""), "model": r.get("model", ""),
                        "host": socket.gethostname(), "deduplicated": True,
                        "max_seconds": MAX_TURN_SECONDS}
    backend = (req.backend or "claude").lower()
    spec = BACKENDS.get(backend)
    if not spec:
        raise HTTPException(400, f"unknown backend '{backend}' (one of {sorted(BACKENDS)})")
    cwd = req.cwd or _ws(identifier)
    if _SESSION_UIDS and req.cwd and os.path.realpath(req.cwd) != os.path.realpath(_ws(identifier)):
        # Behind the wall the directory decides which uid a turn runs as; a caller-chosen one
        # would be a turn in another session's identity.
        raise HTTPException(400, "cwd is decided by the session identifier")
    os.makedirs(cwd, exist_ok=True)
    _write_input_files(cwd, req.files)   # land caller-attached files in the workspace pre-run
    # Built-in skills the harness disabled must NOT be mounted. On BusinessOS built-ins aren't
    # image-mounted (there is no _mount_builtin_skills), and the gateway already drops suppress markers
    # from req.skills, so this filter is a parity guard: never write a skill whose name is suppressed.
    _skip = set(req.skills_suppressed or [])
    # Installed plugin packages, whole, at their roots; then every stdio server a plugin declares
    # becomes a launcher every backend writer below already knows how to hand to its CLI.
    plugin_roots = _write_plugins(cwd, req.plugins)
    req.mcp_servers = _sse_bridges(cwd, _plugin_launchers(cwd, req.mcp_servers), req.backend)
    # A package that is also a Claude Code plugin reaches the claude CLI whole through
    # --plugin-dir, which loads its skills/ itself; folding those skills into the skills
    # directory too would offer each one twice.
    claude_native = {pathlib.Path(d).name for d in plugin_roots
                     if (pathlib.Path(d) / ".claude-plugin" / "plugin.json").is_file()} if backend == "claude" else set()
    installed_skills = _write_skills(
        cwd, [s for s in (req.skills or []) if (s.get("name") or s.get("id")) not in _skip
              and _mcp_name(str(s.get("plugin") or "")) not in claude_native], backend,
    )   # materialize enabled skills for this backend (minus suppressed built-ins)
    # Seed the agent's instruction file (AGENTS.md/CLAUDE.md) from the harness doc + installed skills.
    # The model's system prompt stays the CLI default; persistent instructions live in this file.
    #
    # Disabled tools, by what each CLI can actually enforce:
    #   claude — a `permissions.deny` list in settings.json, a hard block (see _build_claude). The
    #     agent reports having no such tool. NOT `--disallowedTools`: that belongs to the permission
    #     prompt system, which --dangerously-skip-permissions turns off.
    #   codex, hermes — no per-tool switch exists. Codex has none at all; hermes only disables whole
    #     TOOLSETS, which is a different granularity from the per-tool names a harness configures.
    #     Both read the agent doc, so both get the same instruction. It is a request to the model,
    #     not a guarantee — verified reaching the agent on both, and verified as a request: hermes
    #     complied, codex used the tool anyway. That is why the console calls it a request rather
    #     than a block. Written here once rather than as two divergent branches — hermes previously
    #     had neither, and silently ignored every disabled tool.
    #   gemini — same tier, no confirmed per-tool switch in headless mode (see _BASE_CATALOG's
    #     "gemini" entry). UHP §4.3 requires this be conveyed as a standing instruction rather than
    #     silently dropped wherever it can't be a hard block, so it goes in this set rather than
    #     being left out of it — the same class of gap this comment already names for hermes.
    agent_doc = req.agent_doc or ""
    if backend in ("codex", "hermes", "dsh", "gemini") and req.tools_disabled:
        _off = ", ".join(t for t in req.tools_disabled if t)
        if _off:
            agent_doc = ((agent_doc + "\n\n") if agent_doc.strip() else "") + \
                f"## Disabled tools\n\nDo NOT use these tools — they are disabled for this harness: {_off}."
    note = _codex_custom_editing_note(backend, req.auth)
    if note:
        agent_doc = ((agent_doc + "\n\n") if agent_doc.strip() else "") + note
    turn_environment = environments.resolve(req.environment)   # 409 when nothing is built: before any process starts
    _write_agent_doc(cwd, backend, agent_doc, installed_skills, environment=turn_environment)
    # The harness's own variables under the runner's, so nothing a caller names shadows the
    # runner's credentials or paths; the platform's HR_ names come after and win (below).
    env = {**_caller_env(req.env), **_child_env()}
    # Image generation. Deliberately NOT the OPENAI_* names: on a codex harness those already
    # point at the CHAT connection, which is often a different provider, and one env pair can
    # only carry one credential. The imagegen skill's wrapper reads these and passes them to the
    # SDK explicitly, so images work the same on every base. The value is a per-turn broker
    # credential, never a provider key.
    if req.image_auth:
        for k, v in (("HR_IMAGE_BASE_URL", req.image_auth.get("base_url")),
                     ("HR_IMAGE_KEY", req.image_auth.get("api_key")),
                     ("HR_IMAGE_MODEL", req.image_auth.get("model"))):
            if v:
                env[k] = str(v)
    # Names the gateway hands the turn process for the platform's own API: a harness that drives
    # another one gets HR_API_URL and HR_CALIBRATION_TOKEN, a credential scoped to that harness
    # and expiring with the turn. HR_-prefixed only, so nothing here shadows a CLI's own variable.
    for k, val in (req.env or {}).items():
        if isinstance(k, str) and k.startswith("HR_") and val not in (None, ""):
            env[k] = str(val)
    # CRITICAL for resume: both CLIs write their conversation transcripts under $HOME
    # (~/.claude/projects/*.jsonl, ~/.codex/sessions/*) — NOT under CLAUDE_CONFIG_DIR. The default
    # $HOME is outside /workspace, so transcripts were never checkpointed and `--resume` found nothing
    # after a sandbox recycled (every follow-up on an older session failed). Redirect $HOME INTO the
    # checkpointed workspace so the transcript travels in the tarball and resume works WITH history.
    home = os.path.join(cwd, ".harness", "home")
    os.makedirs(home, exist_ok=True)
    env["HOME"] = home
    if _SESSION_UIDS:
        # The shared scratch directories are closed to session uids, so the session's own scratch
        # (checkpoint- and collection-excluded by design) is what tempfile, os.tmpdir() and the
        # CLIs' temp files use.
        scratch = os.path.join(cwd, "tmp")
        os.makedirs(scratch, exist_ok=True)
        env["TMPDIR"] = env["TMP"] = env["TEMP"] = scratch
    # PWD must agree with the cwd the process is spawned in. _child_env copies the runner's own
    # environment, whose PWD is /app/runner; Popen(cwd=...) changes the directory but not the
    # variable, and Bun-based CLIs trust $PWD over getcwd(). opencode therefore believed it was
    # running inside /app/runner — unreadable to the session uid — and every turn died with an
    # opaque UnknownError. Proven by env bisection on a live failure: with 40 inherited variables,
    # removing or correcting PWD alone flips the turn from failing to passing.
    env["PWD"] = cwd
    environments.apply_env(env, turn_environment)
    auth = _adapt_custom_auth(req.auth or Auth())
    model = req.model or spec["default_model"]
    use_appserver = backend == "codex" and bool(req.codex_appserver)
    cmd = None
    codex_note = ""
    hermes_provider = ""
    hermes_mcp: list[str] = []
    if backend == "codex":
        model = model or CODEX_DEFAULT_MODEL
        mcp_toml = _codex_mcp_toml(req.mcp_servers)
        if use_appserver:
            _codex_prepare_env(req.provider, auth, model, cwd, env, mcp_toml, resume=bool(req.resume_session_id),
                               tools_disabled=req.tools_disabled)   # config.toml + CODEX_HOME + auth
        else:
            cmd, codex_note = _build_codex(req.provider, auth, model, req.prompt, cwd, env,
                                           mcp_toml=mcp_toml, resume_session_id=req.resume_session_id, tools_disabled=req.tools_disabled)
    elif backend == "hermes":
        model = model or HERMES_DEFAULT_MODEL
        hermes_provider = (req.provider or "bedrock").lower()
        hermes_mcp = _hermes_prepare_env(hermes_provider, auth, cwd, env, model=model,
                                         max_turns=req.max_turns, mcp_servers=req.mcp_servers,
                                         vision_auth=req.vision_auth)
    elif backend == "dsh":
        model = model or DSH_DEFAULT_MODEL
        cmd = _build_dsh(req.provider, auth, model, req.prompt, cwd, env,
                         resume_session_id=req.resume_session_id, mcp_servers=req.mcp_servers,
                         vision=bool(req.vision))
    elif backend == "pi":
        model = model or PI_DEFAULT_MODEL
        cmd = _build_pi(req.provider, auth, model, req.prompt, cwd, env,
                        resume_session_id=req.resume_session_id, mcp_servers=req.mcp_servers,
                        tools_disabled=req.tools_disabled, vision=bool(req.vision))
    elif backend == "omp":
        model = model or OMP_DEFAULT_MODEL
        cmd = _build_omp(req.provider, auth, model, req.prompt, cwd, env,
                         resume_session_id=req.resume_session_id, mcp_servers=req.mcp_servers,
                         tools_disabled=req.tools_disabled, vision=bool(req.vision))
    elif backend == "qwen":
        model = model or QWEN_DEFAULT_MODEL
        cmd = _build_qwen(req.provider, auth, model, req.prompt, cwd, env,
                          resume_session_id=req.resume_session_id, mcp_servers=req.mcp_servers)
    elif backend == "kimi":
        model = model or KIMI_DEFAULT_MODEL
        # _write_skills has already run, so the directory is on disk and can simply be named:
        # --skills-dir "Overrides default discovery", the opencode shape, so there is no per-CLI
        # home directory to guess here.
        kimi_skills = os.path.join(cwd, ".harness", "skills") if installed_skills else None
        cmd = _build_kimi(req.provider, auth, model, req.prompt, cwd, env,
                          resume_session_id=req.resume_session_id, mcp_servers=req.mcp_servers,
                          skills_dir=kimi_skills, tools_disabled=req.tools_disabled,
                          max_turns=req.max_turns)
    elif backend == "minimax":
        model = model or MINIMAX_DEFAULT_MODEL
        # Skills are already on disk in the home _write_skills chose, which the CLI discovers itself;
        # the agent doc is its global AGENTS.md (see _agent_doc_path).
        cmd = _build_minimax(req.provider, auth, model, req.prompt, cwd, env,
                             resume_session_id=req.resume_session_id, mcp_servers=req.mcp_servers,
                             tools_disabled=req.tools_disabled, max_turns=req.max_turns)
    elif backend == "grok":
        model = model or GROK_DEFAULT_MODEL
        # Skills are already on disk under $GROK_HOME/skills (_write_skills), where grok's loader
        # looks; nothing names them here.
        cmd = _build_grok(req.provider, auth, model, req.prompt, cwd, env,
                          resume_session_id=req.resume_session_id, mcp_servers=req.mcp_servers,
                          tools_disabled=req.tools_disabled, max_turns=req.max_turns,
                          partial=bool(req.partial_messages))
    elif backend == "aider":
        model = model or AIDER_DEFAULT_MODEL
        # aider has no skill loader and no instruction-file convention: the driver puts the agent
        # doc into aider's system message (the Model's system_prompt_prefix, aider's own hook). The
        # agent doc alone goes through it. Its
        # skills block names each installed skill with its description and folder, and the model
        # reaches a skill's files ON DEMAND through the one tool surface it has, a shell command
        # (`cat <folder>/SKILL.md`), whose output the driver feeds back in the same turn, or by
        # naming a tracked file, which aider adds to the chat itself. That is the door every base
        # without a loader uses (dsh reads them with its file tools). The PR read EVERY file of every
        # bundle on every turn: measured on hr-test 2026-09-18, the three built-in bundles are 27
        # files and 264 KB, licences and a PNG among them, and "Reply with exactly: …" cost 45,030
        # input tokens. A skill's content is loaded when a task calls for it, never as a tax on
        # every turn.
        aider_read: list[str] = []
        doc = _agent_doc_path(cwd, backend)
        if doc.exists():
            aider_read.append(str(doc))
        cmd = _build_aider(req.provider, auth, model, req.prompt, cwd, env,
                           mcp_servers=req.mcp_servers, tools_disabled=req.tools_disabled,
                           skills_read=aider_read, max_turns=req.max_turns)
    elif backend == "cheetahclaws":
        model = model or CHEETAHCLAWS_DEFAULT_MODEL
        # Skills are already in <cwd>/.cheetahclaws/skills (_write_skills) and the agent doc in
        # CLAUDE.md, both where the CLI's own loaders look; the builder adds the model, the relay,
        # MCP and the tool policy.
        cmd = _build_cheetahclaws(req.provider, auth, model, req.prompt, cwd, env,
                                  resume_session_id=req.resume_session_id,
                                  mcp_servers=req.mcp_servers,
                                  tools_disabled=req.tools_disabled, max_turns=req.max_turns)
    elif backend == "openhands":
        model = model or OPENHANDS_DEFAULT_MODEL
        cmd = _build_openhands(req.provider, auth, model, req.prompt, cwd, env,
                               resume_session_id=req.resume_session_id,
                               mcp_servers=req.mcp_servers,
                               tools_disabled=req.tools_disabled, max_turns=req.max_turns)
    elif backend == "agentzero":
        model = model or AGENTZERO_DEFAULT_MODEL
        cmd = _build_agentzero(req.provider, auth, model, req.prompt, cwd, env,
                               resume_session_id=req.resume_session_id,
                               mcp_servers=req.mcp_servers,
                               tools_disabled=req.tools_disabled, max_turns=req.max_turns)
    elif backend == "systemone":
        model = model or SYSTEMONE_DEFAULT_MODEL
        cmd = _build_systemone(req.provider, auth, model, req.prompt, cwd, env,
                               resume_session_id=req.resume_session_id, mcp_servers=req.mcp_servers,
                               tools_disabled=req.tools_disabled, max_turns=req.max_turns,
                               timeout_seconds=req.timeout_seconds, agent_doc=agent_doc,
                               metadata=req.metadata)
    elif backend == "gemini":
        model = model or GEMINI_DEFAULT_MODEL
        cmd = _build_gemini(req.provider, auth, model, req.prompt, cwd, env,
                            resume_session_id=req.resume_session_id, mcp_servers=req.mcp_servers,
                            native_model=req.native_model)
    elif backend == "cline":
        model = model or CLINE_DEFAULT_MODEL
        cmd = _build_cline(req.provider, auth, model, req.prompt, cwd, env,
                           resume_session_id=req.resume_session_id, mcp_servers=req.mcp_servers)
    elif backend == "goose":
        model = model or GOOSE_DEFAULT_MODEL
        cmd = _build_goose(req.provider, auth, model, req.prompt, cwd, env,
                           resume_session_id=req.resume_session_id, mcp_servers=req.mcp_servers,
                           tools_disabled=req.tools_disabled, max_turns=req.max_turns)
    elif backend == "opencode":
        model = model or OPENCODE_DEFAULT_MODEL
        # _write_skills already ran for this backend, so the directory it produced is on disk and
        # can simply be named in opencode.json (its `skills` key takes arbitrary paths).
        skills_dir = os.path.join(cwd, ".harness", "skills") if installed_skills else None
        cmd = _build_opencode(req.provider, auth, model, req.prompt, cwd, env,
                              resume_session_id=req.resume_session_id, mcp_servers=req.mcp_servers,
                              skills_dir=skills_dir, tools_disabled=req.tools_disabled)
    elif backend == "kilo":
        model = model or KILO_DEFAULT_MODEL
        skills_dir = os.path.join(cwd, ".harness", "skills") if installed_skills else None
        cmd = _build_kilo(req.provider, auth, model, req.prompt, cwd, env,
                          resume_session_id=req.resume_session_id, mcp_servers=req.mcp_servers,
                          skills_dir=skills_dir, tools_disabled=req.tools_disabled)
    else:
        mcp_config = _write_mcp_config_claude(cwd, req.mcp_servers)
        # Only a package that is ALSO a Claude Code plugin gets --plugin-dir; an Agent Plugins
        # package without .claude-plugin/plugin.json would make the CLI refuse the flag.
        plugin_dirs = [d for d in plugin_roots
                       if (pathlib.Path(d) / ".claude-plugin" / "plugin.json").is_file()]
        cmd = _build_claude(req.provider, auth, model, req.prompt, req.max_turns, cwd, env,
                            resume_session_id=req.resume_session_id, mcp_config=mcp_config,
                            disallowed_tools=req.tools_disabled, partial=bool(req.partial_messages),
                            plugin_dirs=plugin_dirs)
    resume_lost = _resume_lost(backend, cmd, req.resume_session_id, cwd)
    _isolate_session(cwd)   # everything the runner just wrote into the session is the session's now
    turn_id = "turn" + uuid.uuid4().hex
    _evict_turns()
    with _turns_lock:
        # Double-check under the lock: a concurrent retry with the same key may have raced past the
        # top-of-handler check before this one recorded the key. If so, use the winner and let this
        # freshly-built cmd drop (no thread started for it).
        if key and _turn_by_key.get(key) in _turns:
            prior_id = _turn_by_key[key]; r = _turns[prior_id]
            return {"turn_id": prior_id, "status": r.get("status", "running"),
                    "backend": r.get("backend", ""), "model": r.get("model", ""),
                    "host": socket.gethostname(), "deduplicated": True, "max_seconds": MAX_TURN_SECONDS}
        _turns[turn_id] = {"status": "running", "events": [], "result": "", "done": False,
                           "backend": backend, "model": model, "started": time.time(),
                           # the values the record may not carry (see get_turn)
                           "secrets": _turn_secrets(_caller_env(req.env), req.env_secret)}
        if codex_note:   # the follow-up's Codex history was not here: the transcript says so first
            _turns[turn_id]["events"].append({"type": "assistant", "_ts": time.time(),
                                              "message": {"content": [{"type": "text", "text": codex_note}]}})
        if resume_lost:  # the same for claude and opencode: the reply opens with the note, never a silent restart
            _turns[turn_id]["events"].append({"type": "system", "subtype": "resume_lost", "_ts": time.time(),
                                              "requested_session_id": resume_lost})
        if key:
            _turn_by_key[key] = turn_id
    if use_appserver:
        threading.Thread(target=_run_codex_appserver_bg,
                         args=(turn_id, cwd, env, model, req.prompt, req.resume_session_id, req.timeout_seconds),
                         daemon=True).start()
    elif backend == "hermes":
        threading.Thread(target=_run_hermes_bg,
                         args=(turn_id, cwd, env, model, hermes_provider, req.prompt,
                               req.resume_session_id, req.timeout_seconds, hermes_mcp),
                         daemon=True).start()
    else:
        threading.Thread(target=_run_turn_bg,
                         args=(turn_id, cmd, env, cwd, spec["normalize"], model, req.timeout_seconds,
                               bool(req.partial_messages)),   # claude: CLI flag added above
                         daemon=True).start()
    cap = min(req.timeout_seconds, MAX_TURN_SECONDS) if req.timeout_seconds else MAX_TURN_SECONDS
    return {"turn_id": turn_id, "status": "running", "backend": backend, "model": model,
            "host": socket.gethostname(), "max_seconds": cap}


@app.delete("/workspace")
async def delete_workspace(identifier: str = "") -> dict:
    """Remove a session's working folder for good (session delete, Sessions §6).

    This lives in the runner and not the gateway on purpose: the gateway runs as an unprivileged
    user and each session's folder belongs to that session's own uid (mode 700), so only the
    process that made the wall can take it down. The folder is the session's memory on this box;
    the durable tarball is the gateway's to delete. A shared root (sandbox-per-session) is never
    removed. The gateway stops any live turn before asking; turn records here carry no session
    identity, so this end cannot second-guess that."""
    ident = (identifier or "").strip()
    if not ident:
        raise HTTPException(status_code=400, detail="identifier required")
    if _SANDBOX_PER_SESSION:
        return {"identifier": ident, "removed": False, "reason": "shared workspace root"}
    ws = _ws(ident)
    if os.path.realpath(ws) in (os.path.realpath(WORKSPACE_ROOT), "/"):
        raise HTTPException(status_code=400, detail="refusing to remove the workspace root")
    # Whether or not the folder is still there: after this call the session holds nothing on
    # this box, and the marker is part of that. Cleared before the "no folder" answer below,
    # since a folder already gone behind its marker is exactly the case in which a marker left
    # behind would answer the next probe "held" (as the reaper does when it removes a folder).
    _ws_marker_clear(ident)
    if not os.path.isdir(ws):
        return {"identifier": ident, "removed": False, "reason": "no folder"}
    uid = _session_uid(ws)
    shutil.rmtree(ws, ignore_errors=True)
    if uid is not None:
        # the session's passwd/group entries were only ever for this folder
        try:
            subprocess.run(["userdel", f"hs{uid}"], capture_output=True)
            subprocess.run(["groupdel", f"hs{uid}"], capture_output=True)
        except OSError:
            pass
    return {"identifier": ident, "removed": not os.path.isdir(ws)}


@app.post("/turn/{turn_id}/cancel")
def cancel_turn(turn_id: str) -> dict:
    """Kill a running turn's CLI process on demand (user-initiated stop). The reader loop
    in _run_turn_bg then drains and finalizes the record with status='cancelled'."""
    rec = _turns.get(turn_id)
    if not rec:
        raise HTTPException(404, "turn not found")
    if rec.get("done"):
        return {"turn_id": turn_id, "status": rec["status"], "cancelled": False}
    rec["cancelled"] = True
    proc = rec.get("proc")
    if proc is not None:
        _kill_proc_tree(proc, turn_id)
    return {"turn_id": turn_id, "status": "cancelling", "cancelled": True}


@app.get("/turn/{turn_id}")
def get_turn(turn_id: str, since: int = 0) -> dict:
    """Incremental turn status + normalized events (events[since:]). Polling also keeps the
    Timed sandbox alive (every request resets the idle cooldown)."""
    rec = _turns.get(turn_id)
    if not rec:
        raise HTTPException(404, "turn not found")
    with _turns_lock:
        evs = rec["events"][since:]
        n = len(rec["events"])
    out = {"turn_id": turn_id, "status": rec["status"], "done": rec["done"],
           "result": rec.get("result", ""), "exit_code": rec.get("exit_code"),
           "error": rec.get("error"), "backend": rec["backend"], "model": rec["model"],
           "session_id": rec.get("session_id"), "reason": rec.get("reason") or "",
           "handoff": rec.get("handoff"),
           "events": evs, "n_total": n, "elapsed": round(time.time() - rec["started"], 1)}
    sec = rec.get("secrets")
    return json.loads(_scrub_secrets(json.dumps(out, default=str), sec)) if sec else out
