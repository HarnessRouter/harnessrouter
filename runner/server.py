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
import http.server
import json
import mimetypes
import os
import pathlib
import re
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
import urllib.request
import uuid

import yaml
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

app = FastAPI(title="harness-runner")

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
            try:
                _ws_marker_path(e.name).unlink()
            except OSError:
                pass
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


def _as_session(ws: str) -> dict:
    """Popen/run keyword arguments that make a child act as this session. Empty when the wall is
    off, so every spawn site reads the same with or without it."""
    uid = _session_uid(ws)
    return {"user": uid, "group": uid, "extra_groups": []} if uid is not None else {}


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
                      # dsh: the MCP cordis overlay can carry auth headers (same standing as
                      # claude's .mcp.json); the provider KEY itself never lands anywhere —
                      # it lives only in the driver process (see dsh_driver.py's relay).
                      "./.harness/home/.dsh/cordis.yml",
                      # Dependency/scratch dirs (any depth): re-creatable by the agent, and they
                      # dominate checkpoint size — a node project checkpointed 200MB+ and paid
                      # that again on every hydrate. The agent reinstalls when it needs them.
                      "node_modules", ".venv", "venv", "__pycache__", ".pnpm-store",
                      ".cache/pip", ".npm/_cacache"]
_GIT_ENV = {"GIT_AUTHOR_NAME": "harness", "GIT_AUTHOR_EMAIL": "harness@agentstudio.local",
            "GIT_COMMITTER_NAME": "harness", "GIT_COMMITTER_EMAIL": "harness@agentstudio.local"}
CLAUDE_DEFAULT_MODEL = os.environ.get("CLAUDE_DEFAULT_MODEL", "claude-sonnet-4.6")
CODEX_DEFAULT_MODEL = os.environ.get("CODEX_DEFAULT_MODEL", "gpt-5.4")
# Hermes default (the gateway maps friendly names to provider ids before the /turn call).
HERMES_DEFAULT_MODEL = os.environ.get("HERMES_DEFAULT_MODEL", "gpt-5.4")
# Pi default — pi is multi-family the same way hermes is; same reasoning, same default.
PI_DEFAULT_MODEL = os.environ.get("PI_DEFAULT_MODEL", "gpt-5.4")
DSH_DEFAULT_MODEL = os.environ.get("DSH_DEFAULT_MODEL", "deepseek-v4-pro")
CODEX_REASONING_EFFORT = os.environ.get("CODEX_REASONING_EFFORT", "medium")
CODEX_CONTEXT_WINDOW = os.environ.get("CODEX_CONTEXT_WINDOW", "400000")
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
def _git(ws: str, *args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", ws, *args], capture_output=True, text=True,
                          env={**os.environ, **_GIT_ENV}, check=check, **_as_session(ws))


def _git_ensure(ws: str) -> None:
    """Make /workspace a git repo with a secret-safe .gitignore (so .git, which travels in the
    checkpoint tarball, never carries credentials)."""
    p = pathlib.Path(ws)
    p.mkdir(parents=True, exist_ok=True)
    (p / ".gitignore").write_text("\n".join([
        "# harness: never persist secrets/scratch in the session checkpoint",
        "tmp/", ".gcp-sa.json", ".codex/", ".credentials.json", ".harness/**/.credentials.json",
        ".harness/home/.hermes/.env", ".harness/home/.hermes/auth.json",
        ".harness/home/.pi/agent/auth.json", ".harness/home/.pi/agent/models.json",
        "",
    ]))
    if not (p / ".git").exists():
        _git(ws, "init", "-q")
        _git(ws, "config", "user.email", _GIT_ENV["GIT_AUTHOR_EMAIL"])
        _git(ws, "config", "user.name", _GIT_ENV["GIT_AUTHOR_NAME"])


# ── input/output file plumbing (OpenAI Responses input_file blocks + container files) ──
# Paths never reported as agent-produced output (internal state / scratch / secrets / vcs).
_PRODUCED_EXCLUDE_PREFIX = (".harness/", "tmp/", ".codex/", ".git/", ".claude/", ".pi/",
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


def _mcp_name(s: str) -> str:
    """Sanitize an MCP server name into a CLI-safe identifier (alnum + underscore)."""
    n = _MCP_NAME_RE.sub("_", (s or "").strip()).strip("_")
    return n or "mcp"


def _write_mcp_config_claude(cwd: str, servers: list[dict]) -> str | None:
    """Write a Claude Code .mcp.json for the enabled MCP servers. Returns its path
    (passed via --mcp-config), or None if there are none.

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
            auth = s.get("auth")
            if auth:  # bearer token (resolved by the gateway) -> Authorization header
                hdr = auth if str(auth).lower().startswith("bearer ") else f"Bearer {auth}"
                entry["headers"] = {"Authorization": hdr}
            if isinstance(s.get("headers"), dict):
                entry.setdefault("headers", {}).update(s["headers"])
        elif command:
            entry = {"type": "stdio", "command": command, "args": s.get("args") or []}
            if isinstance(s.get("env"), dict):
                entry["env"] = s["env"]
        else:
            continue
        entries[name] = entry
    if not entries:
        return None
    path = pathlib.Path(cwd) / HARNESS_STATE / "mcp.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mcpServers": entries}, indent=2))
    return str(path)


def _codex_mcp_toml(servers: list[dict]) -> str:
    """Render [mcp_servers.*] config.toml blocks for Codex's experimental remote-MCP (rmcp)
    HTTP client. Returns '' if there are no HTTP servers to add."""
    blocks: list[str] = []
    for s in servers or []:
        url = (s or {}).get("url")
        if not url:
            continue
        name = _mcp_name((s or {}).get("name") or (s or {}).get("id") or "mcp")
        auth = (s or {}).get("auth")
        lines = [f"[mcp_servers.{name}]", f'url = "{url}"']
        # One http_headers inline table: Authorization from `auth` + any extra headers the
        # gateway resolved (e.g. Additional Headers / $headers.{name} app-auth values).
        hdrs: dict[str, str] = {}
        if auth:
            hdrs["Authorization"] = auth if str(auth).lower().startswith("bearer ") else f"Bearer {auth}"
        extra = (s or {}).get("headers")
        if isinstance(extra, dict):
            for k, v in extra.items():
                if k and v is not None:
                    hdrs[str(k)] = str(v)
        if hdrs:
            def _tesc(x: str) -> str:
                return x.replace("\\", "\\\\").replace('"', '\\"')
            inner = ", ".join(f'"{_tesc(k)}" = "{_tesc(v)}"' for k, v in hdrs.items())
            lines.append(f"http_headers = {{ {inner} }}")
        blocks.append("\n".join(lines))
    if not blocks:
        return ""
    # rmcp HTTP client is opt-in in Codex; enable it when any HTTP MCP server is configured.
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
    if backend == "claude":
        rootrels = [".harness/home/.claude/skills", ".claude/skills"]
        entryroot = ".claude/skills"
    elif backend == "pi":
        rootrels = [".harness/home/.pi/agent/skills"]
        entryroot = ".harness/home/.pi/agent/skills"
    else:
        rootrels = [".harness/skills"]
        entryroot = ".harness/skills"
    installed: list[dict] = []
    for sk in skills or []:
        name = _mcp_name((sk or {}).get("name") or (sk or {}).get("id") or "")
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
    """Materialize enabled Claude Code plugins into the workspace, one directory per plugin
    under `.harness/plugins/<name>/`. Each plugin: {name, files:[{path, content|content_b64,
    executable?}]}. Returns the absolute paths written, in order — the caller turns each into
    one `--plugin-dir <path>` argument to `_build_claude`.

    A single root, unlike skills: a plugin is loaded exclusively through --plugin-dir, so
    there is no discovery path to also mirror it under, and a stray second copy under
    .claude/ would risk Claude Code loading the same plugin twice."""
    installed: list[str] = []
    for pg in plugins or []:
        pg = pg or {}
        name = _mcp_name(pg.get("name") or pg.get("id") or "")
        files = pg.get("files")
        if not name or not files:
            continue
        root = _safe_join(cwd, f".harness/plugins/{name}")
        if root is None:
            continue
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
                if content_b64 is not None:
                    dest.write_bytes(base64.b64decode(content_b64))
                else:
                    dest.write_text(content)
                if _plugin_file_is_executable(rel, f.get("executable")):
                    dest.chmod(dest.stat().st_mode | 0o111)
                wrote = True
            except Exception:  # noqa: BLE001
                continue
        if wrote:
            installed.append(str(root))
    return installed


_AGENTS_BEGIN = "<!-- harness-skills:begin -->"
_AGENTS_END = "<!-- harness-skills:end -->"


def _agent_doc_path(cwd: str, backend: str) -> pathlib.Path:
    """The agent's instruction file: AGENTS.md for Codex, Hermes, Pi and dsh (all four read
    AGENTS.md from the cwd — pi as a context file before its trust gate, dsh via its
    dsh-agent-instructions workspace loader), CLAUDE.md for Claude Code."""
    return pathlib.Path(cwd) / ("AGENTS.md" if backend in ("codex", "hermes", "pi", "dsh") else "CLAUDE.md")


def _write_agent_doc(cwd: str, backend: str, agent_doc: str | None, skills_meta: list[dict]) -> None:
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
    p = _agent_doc_path(cwd, backend)
    base = (agent_doc or "").strip()
    lines = [_AGENTS_BEGIN, "## Workspace", "",
             "Your working directory is this task's workspace and the ONLY place the user can see "
             "files. Save every deliverable (documents, decks, code, exports) to a relative path "
             "under it. Never write output to an absolute path outside it (/tmp, /app, the "
             "workspace parent directory, or your home directory): those files are not collected, "
             "and the user will never see them.", ""]
    if skills_meta:
        lines += ["## Available skills", "",
                  "These skills are installed in this workspace. When a task matches one, read its "
                  "SKILL.md first and follow its instructions and bundled scripts.", ""]
        for s in skills_meta:
            d = f" — {s['desc']}" if s.get("desc") else ""
            lines.append(f"- **{s['name']}**{d} (`{s['entry']}`)")
        lines.append("")
    block = "\n".join(lines).rstrip("\n") + "\n" + _AGENTS_END + "\n"
    body = ((base + "\n\n") if base else "") + block
    try:
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


# ── canonical-event normalizers ──────────────────────────────────────────────────
import re as _re
# Claude Code injects transient provider errors into the stream AS assistant text
# ("API Error: 400 ...", "API Error: 429 ..."), then usually retries and continues. That
# diagnostic is the CLI's own UX, not model output — rendering it as the reply is wrong (it made
# a working opus-4.7/4.8 turn look failed). Drop assistant text blocks that ARE such an error line.
_CLAUDE_ERR_RE = _re.compile(r"^\s*API Error:\s*\d{3}\b", _re.IGNORECASE)


def _strip_claude_error_text(obj: dict) -> dict | None:
    """Remove CLI-injected 'API Error: <code> …' text blocks from an assistant message. Returns the
    message with those blocks dropped (None if nothing renderable remains), or the object unchanged
    when it carries no such block."""
    if obj.get("type") != "assistant":
        return obj
    content = (obj.get("message") or {}).get("content")
    if not isinstance(content, list):
        return obj
    kept = [c for c in content
            if not (isinstance(c, dict) and c.get("type") == "text"
                    and _CLAUDE_ERR_RE.match(str(c.get("text") or "")))]
    if len(kept) == len(content):
        return obj                      # no error block — untouched
    if not kept:
        return None                     # the message was ONLY the error line — drop it entirely
    return {**obj, "message": {**(obj.get("message") or {}), "content": kept}}


def _claude_passthrough(obj: dict, state: dict) -> list[dict]:
    # Filter out CLI-injected "API Error: NNN …" diagnostics rendered as assistant text (they are
    # not model output; the CLI retries around them). Applies to both batch + partial modes.
    obj2 = _strip_claude_error_text(obj)
    if obj2 is None:
        return []
    obj = obj2
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


def _codex_tool_item(it: dict) -> list[dict]:
    """A completed codex tool item (command/file/mcp) -> canonical tool_use + tool_result events.
    Shared by the exec normalizer and the app-server driver (the `item` shape is the same)."""
    kind = it.get("type")
    if kind == "command_execution":
        tuid = it.get("id") or "cmd"
        out = it.get("aggregated_output") or it.get("output") or ""
        ec = it.get("exit_code")
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
    if kind == "mcp_tool_call":
        tuid = it.get("id") or "mcp"
        name = f"{it.get('server', 'mcp')}.{it.get('tool', 'call')}"
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
            env["ANTHROPIC_BASE_URL"] = auth.base_url
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
_CODEX_CONFIG_TMPL = """model = "{model}"
model_provider = "{provider}"
model_reasoning_effort = "{effort}"
approval_policy = "never"
sandbox_mode = "danger-full-access"
model_context_window = {ctx}
[model_providers.{provider}]
name = "{name}"
base_url = "{base_url}"
env_key = "{env_key}"
wire_api = "{wire_api}"
[sandbox_workspace_write]
network_access = true
exclude_slash_tmp = false
"""


def _codex_prepare_env(provider: str, auth: Auth, model: str, cwd: str,
                       env: dict, mcp_toml: str = "") -> "pathlib.Path":
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
    cfg = _CODEX_CONFIG_TMPL.format(
        model=model, provider=f"hr-{p}", effort=CODEX_REASONING_EFFORT, ctx=CODEX_CONTEXT_WINDOW,
        name=spec["name"], base_url=base_url, env_key=spec["env_key"],
        wire_api=auth.wire_api or "responses")
    if mcp_toml:   # owner-attached MCP servers via Codex's experimental rmcp HTTP client
        cfg += mcp_toml
    (cfg_dir / "config.toml").write_text(cfg)
    env["CODEX_HOME"] = str(cfg_dir)
    env["TMPDIR"] = str(pathlib.Path(cwd) / "tmp")
    pathlib.Path(env["TMPDIR"]).mkdir(parents=True, exist_ok=True)
    if auth.api_key:
        env[spec["env_key"]] = auth.api_key
    return cfg_dir


def _sanitize_codex_rollout(rollouts: list[str]) -> dict:
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

        # Pass 1 — drop the account-bound blob, keep the item and its id.
        has_reasoning = False
        for i, (line, o) in enumerate(parsed):
            if not o or o.get("type") != "response_item":
                continue
            pay = o.get("payload")
            if not isinstance(pay, dict) or pay.get("type") != "reasoning":
                continue
            has_reasoning = True
            if pay.pop("encrypted_content", None) is not None:
                counts["reasoning"] += 1
                parsed[i] = (json.dumps(o), o)

        # Pass 2 — repair a rollout the old delete-based strip already damaged. Only when there is
        # no reasoning item left to anchor the ids: with reasoning present the references resolve
        # and stripping ids would needlessly discard continuity.
        minted = [
            (i, o) for i, (line, o) in enumerate(parsed)
            if o and o.get("type") == "response_item" and isinstance(o.get("payload"), dict)
            and str((o["payload"] or {}).get("id") or "").startswith(MINTED)
        ]
        if minted and not has_reasoning:
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
                 env: dict, mcp_toml: str = "", resume_session_id: str | None = None) -> list[str]:
    cfg_dir = _codex_prepare_env(provider, auth, model, cwd, env, mcp_toml)
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
            c = _sanitize_codex_rollout(rollouts)
            print(f"[resume] codex: sanitised rollout — dropped {c['reasoning']} reasoning blob(s), "
                  f"de-referenced {c['deref']} id(s) across {c['damaged']} damaged file(s)", flush=True)
            # CODEX_HOME is PER-SESSION (hydrate wipes + restores only THIS session's workspace), so
            # the most-recent rollout here IS this conversation. Resume by --last instead of matching
            # the thread UUID to the rollout filename (that match is codex-version-fragile and missed
            # ~1/3 of the time). --last is exact here precisely because the home is session-isolated.
            return ["codex", "exec", "resume", "--last", *common, prompt]
        print(f"[resume] codex: no rollout in workspace for {resume_session_id} — starting fresh", flush=True)
    return ["codex", "exec", *common, "--cd", cwd, prompt]


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
    if not base.rstrip("/").endswith("/v1"):
        base = base.rstrip("/") + "/v1"   # the relay joins upstream paths against a /v1 base
    # HR_DSH_*: consumed and scrubbed by the driver before the runtime starts. The runtime gets
    # a loopback relay URL and a placeholder key — the credential never enters its environment.
    env["HR_DSH_BASE_URL"] = base
    env["HR_DSH_API_KEY"] = auth.api_key or ""
    # No system_prompt in the job: harness instructions land in AGENTS.md (dsh reads it via
    # its dsh-agent-instructions loader), same mechanism as codex/hermes/pi.
    job = {"prompt": prompt, "model": model, "cwd": cwd,
           "session_id": resume_session_id or "",
           "mcp_servers": [s for s in (mcp_servers or []) if (s or {}).get("url")]}
    if not _DSH_DEEPSEEK_MODEL.search(model or ""):
        # Family decides the route, not the integration's name: deepseek models keep the
        # verified dsh-llm-deepseek launch path whichever endpoint serves them; every other
        # family rides the pi-ai route. api by family — the same routing the pi backend
        # live-verified on these channels.
        if pr == "anthropic" or _PI_CLAUDE_MODEL.search(model or ""):
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
                    vision: bool = True) -> str:
    """A one-provider ~/.pi/agent/models.json ("hr") for a custom endpoint. Pi's anthropic client
    appends /v1/messages to baseUrl while its openai clients expect the /v1 to already be there
    (both read straight off pi's own docs/models.md examples), so the /v1 suffix is normalized
    per api instead of trusting how the integration happened to store the URL.

    `input` is pi's capability gate, and it is load-bearing on RESUME: a session that once ran a
    vision model can carry an image tool-result, which pi replays to the current model as a user
    message with an image part — verified against a capturing sink. Declared text-only, pi drops
    the image and the turn runs; declared vision on a model whose channel refuses images, the
    whole turn dies on the provider's 400. The gateway says which models are text-only, from
    live probes, so vision stays the default."""
    base = (base_url or "").rstrip("/")
    if api == "anthropic-messages":
        base = base.removesuffix("/v1")
    elif not base.endswith("/v1"):
        base += "/v1"
    return json.dumps({"providers": {"hr": {
        "baseUrl": base, "api": api, "apiKey": api_key,
        "models": [{"id": model, "name": model, "reasoning": False,
                    "input": ["text", "image"] if vision else ["text"],
                    "contextWindow": 200000, "maxTokens": 32000}],
    }}}, indent=2)


def _pi_write_mcp(home: pathlib.Path, servers: list[dict] | None) -> bool:
    """Write $HOME/.pi/agent/mcp.json for pi-mcp-adapter (same input contract as the claude/codex
    writers: url + optional auth/headers). Returns whether any server was written. The agent-dir
    location is deliberate: project-local .pi/mcp.json sits behind pi's trust gate; the agent dir
    does not."""
    entries: dict = {}
    for s in servers or []:
        url = (s or {}).get("url")
        if not url:
            continue
        name = _mcp_name((s or {}).get("name") or (s or {}).get("id") or "mcp")
        entry: dict = {"url": url}
        auth = (s or {}).get("auth")
        if auth:
            hdr = auth if str(auth).lower().startswith("bearer ") else f"Bearer {auth}"
            entry["headers"] = {"Authorization": hdr}
        if isinstance((s or {}).get("headers"), dict):
            entry.setdefault("headers", {}).update({str(k): str(v) for k, v in s["headers"].items()
                                                    if k and v is not None})
        entries[name] = entry
    if not entries:
        return False
    path = home / ".pi" / "agent" / "mcp.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mcpServers": entries}, indent=2))
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
        if pr == "anthropic" or (pr == "tokenrouter" and _PI_CLAUDE_MODEL.search(model or "")):
            api = "anthropic-messages"
        elif pr == "azure" or _HERMES_RESPONSES_API_MODEL.search(model or ""):
            api = "openai-responses"
        else:
            api = "openai-completions"
        (home / ".pi" / "agent" / "models.json").write_text(
            _pi_models_json(api, auth.base_url, auth.api_key or "", model, vision=vision))
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
        err = state.get("_pi_error")
        usage = dict(state.get("_pi_usage") or {})
        usage = {k: v for k, v in usage.items() if v}
        if err:
            return [{"type": "result", "subtype": "error", "is_error": True,
                     "result": err, "usage": usage}]
        return [{"type": "result", "subtype": "success", "is_error": False,
                 "result": state.get("final", ""), "usage": usage}]
    return []


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
_HERMES_RESPONSES_API_MODEL = re.compile(r"(?:^|/)(?:gpt-5|o[1-4])|codex", re.I)


def _hermes_api_mode(provider: str, model: str) -> str | None:
    """`model.api_mode` for config.yaml, or None to leave hermes' own detection alone.

    Only for the generic OpenAI-compatible provider: that is the one whose transport hermes infers
    from the URL. bedrock/anthropic/azure-foundry/openrouter each have their own resolution in the
    CLI, and overriding those would replace working logic with a guess.
    """
    if provider != "openai-api" or not model:
        return None
    return "codex_responses" if _HERMES_RESPONSES_API_MODEL.search(model) else None



def _hermes_mcp_section(servers: list[dict] | None) -> dict:
    """config.yaml `mcp_servers:` entries for the enabled remote MCP servers (hermes supports
    Streamable HTTP by url, SSE via `transport: sse`, and per-server headers). Same input contract
    as the claude/codex materializers: [{name, url, transport?, auth?, headers?}]."""
    out: dict = {}
    for s in servers or []:
        url = (s or {}).get("url")
        if not url:
            continue
        name = _mcp_name((s or {}).get("name") or (s or {}).get("id") or "mcp")
        entry: dict = {"url": url}
        if ((s or {}).get("transport") or "").lower() == "sse":
            entry["transport"] = "sse"
        hdrs: dict[str, str] = {}
        auth = (s or {}).get("auth")
        if auth:  # bearer token (resolved by the gateway) -> Authorization header
            hdrs["Authorization"] = auth if str(auth).lower().startswith("bearer ") else f"Bearer {auth}"
        if isinstance((s or {}).get("headers"), dict):
            hdrs.update({str(k): str(v) for k, v in s["headers"].items() if k and v is not None})
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


def _normalize_openai_chat_body(body: bytes) -> bytes:
    """Repair OpenAI-legal-but-translator-fatal message shapes in one chat-completions body.

    Surgical, matched to what was captured live: an assistant tool-call message whose `content`
    is the empty string becomes `content: null` (equally legal, and translators emit no text
    block for it), and empty `{"type": "text", "text": ""}` parts are dropped from list-shaped
    content (if that empties a tool-call message's list, it becomes null too). Anything else —
    other roles, non-empty text, unparseable bodies — passes through byte-identical."""
    try:
        obj = json.loads(body)
        if not isinstance(obj, dict) or not isinstance(obj.get("messages"), list):
            return body
        changed = False
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
        if not changed:
            return body
        return json.dumps(obj, separators=(",", ":")).encode()
    except Exception:  # noqa: BLE001 — a body we cannot parse is a body we must not alter
        return body


class _HermesRelayHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _upstream(self) -> tuple[str, str] | None:
        tok = (self.headers.get("authorization") or "").removeprefix("Bearer ").strip()
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
        base, key = route
        tail = self.path.removeprefix("/v1") if self.path.startswith("/v1/") else self.path
        drop = {"host", "content-length", "authorization", "connection",
                "accept-encoding", "transfer-encoding"}
        headers = {k: v for k, v in self.headers.items() if k.lower() not in drop}
        headers["authorization"] = f"Bearer {key}"
        headers.setdefault("accept", "*/*")
        if body is not None and self.path.endswith("/chat/completions"):
            body = _normalize_openai_chat_body(body)
            headers["content-length"] = str(len(body))
        req = urllib.request.Request(base.rstrip("/") + tail, data=body,
                                     method=self.command, headers=headers)
        try:
            resp = urllib.request.urlopen(req, timeout=600)
        except urllib.error.HTTPError as e:  # pass provider errors through verbatim
            data = e.read()
            self.send_response(e.code)
            self.send_header("content-type", e.headers.get("content-type") or "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        ctype = resp.headers.get("content-type") or ""
        self.send_response(resp.status)
        self.send_header("content-type", ctype)
        if "text/event-stream" in ctype:   # responses stream through untouched — the fix is request-side
            self.send_header("transfer-encoding", "chunked")
            self.end_headers()
            while True:
                chunk = resp.read(4096)
                if not chunk:
                    break
                self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
                self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n")
        else:
            data = resp.read()
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    def do_POST(self):  # noqa: N802
        self._forward(self.rfile.read(int(self.headers.get("content-length") or 0)))

    def do_GET(self):   # noqa: N802 — model listings and the like
        self._forward(None)

    def log_message(self, *a):  # diagnostics belong on stderr, never stdout
        pass


def _hermes_relay_route(base_url: str, api_key: str) -> tuple[str, str]:
    """Register one turn's upstream; → (relay base_url, placeholder bearer for the CLI)."""
    with _HERMES_RELAY["lock"]:
        if _HERMES_RELAY["server"] is None:
            srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _HermesRelayHandler)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            _HERMES_RELAY["server"], _HERMES_RELAY["port"] = srv, srv.server_address[1]
        tok = "hr-relay-" + uuid.uuid4().hex
        _HERMES_RELAY["routes"][tok] = (base_url, api_key)
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
        if auth.api_key:
            env["ANTHROPIC_API_KEY"] = auth.api_key
        if auth.base_url:
            env["ANTHROPIC_BASE_URL"] = auth.base_url
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


# Registry — providers/default_model/normalize per backend. The cmd build + run loop is dispatched
# in turn(): claude/codex run through _run_turn_bg over stdout JSONL; hermes has its own driver
# (_run_hermes_bg — DB-polling, no stdout events), so it carries no normalizer.
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
}


# ── async turn registry (background execution; turns can run seconds → the 6h cap) ──
_turns: dict[str, dict] = {}
_turn_by_key: dict[str, str] = {}   # idempotency_key -> turn_id (dedup a retried /turn; see turn())
_turns_lock = threading.Lock()


def _kill_proc_tree(proc: subprocess.Popen) -> None:
    """SIGKILL the CLI's whole process GROUP (Popen uses start_new_session). Killing only
    the CLI leaves its shell children (e.g. a `sleep`) holding the inherited stdout pipe,
    which keeps the reader loop blocked until the child exits — a cancel/timeout then
    appears to hang for the child's full duration."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


def _kill_capped(proc: subprocess.Popen, rec: dict) -> None:
    rec["capped"] = True
    _kill_proc_tree(proc)


def _run_turn_bg(turn_id: str, cmd: list[str], env: dict, cwd: str, normalize, model: str,
                 timeout_seconds: int | None = None, partial: bool = False) -> None:
    rec = _turns[turn_id]
    state = {"model": model, "final": "", "partial": partial}
    result_ev = None
    try:
        # start_new_session: own process group so cancel/timeout can killpg the CLI AND its
        # shell children (see _kill_proc_tree) instead of orphaning a pipe-holding child.
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, text=True, bufsize=1,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                start_new_session=True, **_as_session(cwd))
    except Exception as e:  # noqa: BLE001
        rec.update(status="failed", error=f"spawn: {e}"[:500], done=True)
        return
    rec["pid"] = proc.pid
    rec["proc"] = proc   # live handle so POST /turn/{id}/cancel can kill on demand
    if rec.get("cancelled"):
        _kill_proc_tree(proc)   # Stop raced the spawn — kill immediately, not at pipe EOF
    # Hard wall-clock cap — the caller's timeout_seconds (harness config / request override),
    # bounded by the global MAX_TURN_SECONDS ceiling (resource abuse backstop).
    cap = min(timeout_seconds, MAX_TURN_SECONDS) if timeout_seconds else MAX_TURN_SECONDS
    killer = threading.Timer(cap, _kill_capped, args=(proc, rec))
    killer.daemon = True
    killer.start()
    errbuf: list[str] = []   # non-JSON output (CLI stderr is merged into stdout) — the REAL error text
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
                continue
            try:
                obj = json.loads(raw)
            except Exception:  # noqa: BLE001
                continue
            for ev in normalize(obj, state):
                ev["_ts"] = time.time()
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
    rec["exit_code"] = rc
    rec["result"] = state.get("final", "")
    rec["status"] = ("cancelled" if rec.get("cancelled")
                     else "timeout" if rec.get("capped")
                     else _status_from_result(result_ev, rc))
    # Never leave a failure opaque: surface the captured CLI stderr (and result-event error) so the
    # gateway/trace shows WHY it failed (throttling, model error, etc.) instead of an empty string.
    if rec["status"] in ("failed", "error", "timeout"):
        tail = "\n".join(errbuf[-30:]).strip()
        ev_err = (result_ev or {}).get("result") or (result_ev or {}).get("error") or ""
        rec["error"] = (str(ev_err).strip() or tail or f"exit_code={rc}, no diagnostic output")[:2000]
        if result_ev is not None and not str(result_ev.get("result") or "").strip() and tail:
            result_ev["result"] = tail[:2000]   # so the trace's result event isn't empty either
    rec["done"] = True


# Codex app-server JSON-RPC driver — the ONLY codex mode that streams assistant text (via
# item/agentMessage/delta). Flag-gated; the default codex path stays `codex exec` (batch). We run
# one turn per app-server process (spawn -> initialize -> thread start/resume -> turn -> done), a
# single-threaded read loop that also writes the follow-up requests inline as responses arrive.
_CODEX_SANDBOX = os.environ.get("CODEX_APPSERVER_SANDBOX", "danger-full-access")  # kebab enum; env-tunable


def _run_codex_appserver_bg(turn_id: str, cwd: str, env: dict, model: str, prompt: str,
                            resume_session_id: str | None, timeout_seconds: int | None) -> None:
    rec = _turns[turn_id]
    state = {"final": ""}

    def append(ev: dict) -> None:
        ev["_ts"] = time.time()
        with _turns_lock:
            rec["events"].append(ev)

    try:
        proc = subprocess.Popen(["codex", "app-server"], cwd=cwd, env=env, text=True, bufsize=1,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                start_new_session=True, **_as_session(cwd))
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
                    id_thread = (send("thread/resume", {"threadId": resume_session_id}) if resume_session_id
                                 else send("thread/start", {"cwd": cwd, "model": model,
                                           "sandbox": _CODEX_SANDBOX, "approvalPolicy": "never"}))
                elif mid == id_thread:
                    thread_id = ((res.get("thread") or {}).get("id")) or resume_session_id or ""
                    if thread_id:
                        append({"type": "system", "subtype": "init", "session_id": thread_id, "model": model})
                        rec["session_id"] = thread_id
                    id_turn = send("turn/start", {"threadId": thread_id, "model": model,
                                   "approvalPolicy": "never", "input": [{"type": "text", "text": prompt}]})
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
                if it.get("type") not in ("agent_message", "reasoning"):   # already streamed as deltas
                    for ev in _codex_tool_item(it):
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
            elif method in ("turn/failed", "error"):
                errbuf.append(str(p.get("message") or (p.get("error") or {}).get("message") or "codex error"))
                turn_status = "failed"
                break
    except Exception as e:  # noqa: BLE001
        errbuf.append(f"{type(e).__name__}: {str(e)[:150]}")
        turn_status = turn_status or "failed"
    finally:
        killer.cancel()
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
        ev["_ts"] = time.time()
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
                                start_new_session=True, **_as_session(cwd))
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
    append({"type": "result", "subtype": "success" if ok else "error", "is_error": not ok,
            "result": res_txt, "usage": usage})
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
            if _ws_marker_get(identifier) == probe:
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


@app.get("/produced")
def produced(identifier: str = "") -> dict:
    """Files created/modified during the current turn (uncommitted vs the hydrated checkpoint).
    Call BEFORE /checkpoint commits them. Excludes internal state / scratch / secrets / vcs."""
    ws = _ws(identifier)
    _git_ensure(ws)
    p = _git(ws, "status", "--porcelain", "-uall")
    out = []
    for line in (p.stdout or "").splitlines():
        if len(line) < 4:
            continue
        status, path = line[:2], line[3:]
        if " -> " in path:                       # rename: take the new path
            path = path.split(" -> ", 1)[1]
        path = path.strip().strip('"')
        if not path or path.endswith("/") or status == "D ":
            continue
        if path in _PRODUCED_EXCLUDE_NAMES or path.startswith(_PRODUCED_EXCLUDE_PREFIX):
            continue
        if _is_produced_noise(path):
            continue
        out.append({"path": path, "status": status.strip() or "?"})
    return {"files": out, "count": len(out)}


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
    idempotency_key: str = ""              # dedup a retried /turn: same key -> same turn, no re-exec
    partial_messages: bool = False         # claude: stream token-level deltas (--include-partial-messages)
    vision: bool = True                    # pi: whether the model's channel accepts image input
    vision_auth: dict | None = None        # hermes: {provider, model, base_url, api_key} for its image questions
    codex_appserver: bool = False          # codex: run via app-server (streams item/agentMessage/delta)


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
    installed_skills = _write_skills(
        cwd, [s for s in (req.skills or []) if (s.get("name") or s.get("id")) not in _skip], backend,
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
    agent_doc = req.agent_doc or ""
    if backend in ("codex", "hermes", "dsh") and req.tools_disabled:
        _off = ", ".join(t for t in req.tools_disabled if t)
        if _off:
            agent_doc = ((agent_doc + "\n\n") if agent_doc.strip() else "") + \
                f"## Disabled tools\n\nDo NOT use these tools — they are disabled for this harness: {_off}."
    _write_agent_doc(cwd, backend, agent_doc, installed_skills)
    env = _child_env()
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
    auth = req.auth or Auth()
    model = req.model or spec["default_model"]
    use_appserver = backend == "codex" and bool(req.codex_appserver)
    cmd = None
    hermes_provider = ""
    hermes_mcp: list[str] = []
    if backend == "codex":
        model = model or CODEX_DEFAULT_MODEL
        mcp_toml = _codex_mcp_toml(req.mcp_servers)
        if use_appserver:
            _codex_prepare_env(req.provider, auth, model, cwd, env, mcp_toml)   # config.toml + CODEX_HOME + auth
        else:
            cmd = _build_codex(req.provider, auth, model, req.prompt, cwd, env,
                               mcp_toml=mcp_toml, resume_session_id=req.resume_session_id)
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
    else:
        mcp_config = _write_mcp_config_claude(cwd, req.mcp_servers)
        plugin_dirs = _write_plugins(cwd, req.plugins)
        cmd = _build_claude(req.provider, auth, model, req.prompt, req.max_turns, cwd, env,
                            resume_session_id=req.resume_session_id, mcp_config=mcp_config,
                            disallowed_tools=req.tools_disabled, partial=bool(req.partial_messages),
                            plugin_dirs=plugin_dirs)
    _isolate_session(cwd)   # everything the runner just wrote into the session is the session's now
    turn_id = "turn" + uuid.uuid4().hex
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
                           "backend": backend, "model": model, "started": time.time()}
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
        _kill_proc_tree(proc)
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
    return {"turn_id": turn_id, "status": rec["status"], "done": rec["done"],
            "result": rec.get("result", ""), "exit_code": rec.get("exit_code"),
            "error": rec.get("error"), "backend": rec["backend"], "model": rec["model"],
            "session_id": rec.get("session_id"),
            "events": evs, "n_total": n, "elapsed": round(time.time() - rec["started"], 1)}
