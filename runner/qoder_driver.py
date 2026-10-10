"""One Qoder Cloud Agent turn, as a runner subprocess.

Spawned per turn by server.py under the same contract as every other backend: `__hr_init` first,
one `{"m": ..., "p": ...}` JSON line per event on stdout, `__hr_result` last, and server.py's
normaliser (_qoder_to_claude) unaware of the wire. What differs is that the agent loop runs in
Qoder's cloud, not in this sandbox: this process is an HTTP client to a REST + SSE API (Managed
mode, `/api/v1/cloud`), so what a CLI driver spends on a subprocess this one spends on a session.

The credential never enters this process. The job carries the runner's loopback relay as the
base and a placeholder bearer; the relay holds the PAT and forwards this route verbatim (no body
rewrites, no served-model or usage taps, see _qoder_relay_route in server.py). The one network
call that bypasses the relay is the presigned artifact download, which carries no credential.

Everything the turn creates at Qoder — the Environment, the Agent, the Session, uploaded input
files, delivered artifact files, a Vault for MCP bearers, Skill resources — is recorded in
<cwd>/.harness/qoder/state.json, which travels in the checkpoint. A follow-up turn finds the
session to continue there; `DELETE /workspace` runs this file in purge mode so a delete reaches
Qoder (nothing the session created outlives it).

Cancellation: the runner sends SIGTERM and waits a bounded grace before its SIGKILL (a remote
backend, BACKENDS[...]["remote"]). The handler raises out of whatever read is in flight, the
turn posts `POST /sessions/{id}/cancel`, says on stdout whether that was accepted, and exits.
Without that call the remote turn would keep running and billing after the local process died.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import mimetypes
import os
import pathlib
import re
import shutil
import signal
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

STATE_REL = os.path.join(".harness", "qoder", "state.json")

# The built-in tools of agent_toolset_20260401 (agents/schemas.md, "内置工具名"), the names
# `tools_disabled` matches exactly. The gateway's catalog is pinned equal to this tuple.
TOOLS = ("Bash", "DeliverArtifacts", "Edit", "Glob", "Grep", "ImageGen", "ImageSearch", "Read",
         "WebFetch", "WebSearch", "Write")
TOOLSET = "agent_toolset_20260401"
EFFORTS = ("none", "low", "medium", "high", "xhigh", "max")

# Files the upload endpoint accepts (files/schemas.md): text MIME types, and this extension list.
# Anything else is refused by Qoder with a 400, so it is refused here first, naming the file.
UPLOAD_MIME_PREFIX = "text/"
UPLOAD_MIME = {"application/json", "application/xml", "application/javascript", "application/x-yaml",
               "application/x-toml"}
UPLOAD_EXT = {".txt", ".md", ".csv", ".json", ".xml", ".yaml", ".yml", ".toml", ".ini", ".conf", ".cfg",
              ".env", ".log", ".html", ".htm", ".css", ".scss", ".less", ".js", ".jsx", ".ts", ".tsx",
              ".vue", ".svelte", ".py", ".go", ".rs", ".java", ".kt", ".scala", ".c", ".cpp", ".cc", ".h",
              ".hpp", ".rb", ".php", ".swift", ".r", ".lua", ".pl", ".sh", ".bash", ".zsh", ".fish",
              ".ps1", ".sql", ".graphql", ".gql", ".proto", ".dockerfile", ".makefile", ".gitignore",
              ".editorconfig", ".eslintrc", ".prettierrc", ".tex", ".rst", ".adoc", ".org", ".svg"}
UPLOAD_BARE = {"dockerfile", "makefile", "gemfile", "rakefile", "procfile", "vagrantfile", "justfile",
               "brewfile"}
UPLOAD_MAX_BYTES = 5 * 1024 * 1024
MOUNT_ROOT = "/mnt/session/uploads"
# The largest delivered artifact landed in the workspace. A download goes to disk as it arrives (never
# held whole in memory) and is cut off past this.
ARTIFACT_MAX_BYTES = int(os.environ.get("HR_QODER_ARTIFACT_MAX_BYTES") or 2 * 1024 ** 3)

# How long one call may take, and how long a stream read may go without a byte. The stream
# carries a heartbeat about every 15 s, so a read that waits this long is a dead connection, and
# the turn reconnects from the last event id rather than hanging on it.
CALL_TIMEOUT_S = 120.0
STREAM_READ_TIMEOUT_S = 90.0
STREAM_RECONNECTS = 20

_SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def _emit(method: str, payload) -> None:
    sys.stdout.write(json.dumps({"m": method, "p": payload}, default=str) + "\n")
    sys.stdout.flush()


class Cancelled(BaseException):
    """The runner asked the turn to stop (SIGTERM). A BaseException so no `except Exception`
    on the way out swallows it."""


class ApiError(Exception):
    def __init__(self, status: int, kind: str, message: str, path: str = ""):
        super().__init__(f"{status} {kind}: {message}")
        self.status, self.kind, self.message, self.path = status, kind, message, path


# ── HTTP ────────────────────────────────────────────────────────────────────────────────────────
class Api:
    """The Managed API through the relay: `base` is the relay's address, `token` a placeholder."""

    def __init__(self, base: str, token: str):
        self.base = base.rstrip("/")
        self.token = token

    def _headers(self, extra: dict | None = None) -> dict:
        h = {"authorization": f"Bearer {self.token}", "accept": "application/json"}
        if extra:
            h.update(extra)
        return h

    def request(self, method: str, path: str, body: dict | None = None, *, data: bytes | None = None,
                headers: dict | None = None, timeout: float = CALL_TIMEOUT_S):
        """One call; the parsed JSON answer (None for an empty body). Raises ApiError on 4xx/5xx
        with the envelope's type and message, urllib.error.URLError when nothing answered."""
        hdrs = self._headers(headers)
        payload = data
        if body is not None:
            payload = json.dumps(body).encode()
            hdrs["content-type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=payload, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            raw = e.read()
            kind, msg = _error_fields(raw)
            raise ApiError(e.code, kind, msg or raw[:300].decode("utf-8", "replace"), path) from None
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return {"_raw": raw[:300].decode("utf-8", "replace")}

    def stream(self, path: str, last_event_id: str = ""):
        """An open SSE response for `path` (a GET); the caller reads it with iter_sse."""
        hdrs = self._headers({"accept": "text/event-stream"})
        if last_event_id:
            hdrs["last-event-id"] = last_event_id
        req = urllib.request.Request(self.base + path, method="GET", headers=hdrs)
        try:
            return urllib.request.urlopen(req, timeout=STREAM_READ_TIMEOUT_S)
        except urllib.error.HTTPError as e:
            raw = e.read()
            kind, msg = _error_fields(raw)
            raise ApiError(e.code, kind, msg or raw[:300].decode("utf-8", "replace"), path) from None


def _error_fields(raw: bytes) -> tuple[str, str]:
    try:
        doc = json.loads(raw)
        err = doc.get("error") if isinstance(doc, dict) else None
        if isinstance(err, dict):
            return str(err.get("type") or ""), str(err.get("message") or "")
    except ValueError:
        pass
    return "", ""


def multipart(parts: list[tuple[str, str | None, str, bytes]]) -> tuple[bytes, str]:
    """A multipart/form-data body from (field, filename or None, content type, bytes) parts;
    returns (body, content-type header)."""
    boundary = "----hr" + uuid.uuid4().hex
    out = bytearray()
    for field, filename, ctype, data in parts:
        out += f"--{boundary}\r\n".encode()
        disp = f'form-data; name="{field}"'
        if filename is not None:
            disp += f'; filename="{filename.replace(chr(34), "_")}"'
        out += f"Content-Disposition: {disp}\r\n".encode()
        if filename is not None:
            out += f"Content-Type: {ctype}\r\n".encode()
        out += b"\r\n" + data + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def iter_sse(resp):
    """(id, event, data) per SSE message off an open response; a comment line is skipped. Ends
    at EOF; a socket timeout or a dropped connection raises out (the caller reconnects)."""
    sid, ev, data = "", "", []
    while True:
        line = resp.readline()
        if not line:
            return
        line = line.rstrip(b"\r\n").decode("utf-8", "replace")
        if line == "":
            if ev or data:
                yield sid, ev, "\n".join(data)
            sid, ev, data = "", "", []
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if field == "id":
            sid = value
        elif field == "event":
            ev = value
        elif field == "data":
            data.append(value)


# ── state ────────────────────────────────────────────────────────────────────────────────────────
def state_path(cwd: str) -> pathlib.Path:
    return pathlib.Path(cwd) / STATE_REL


def load_state(cwd: str) -> dict:
    try:
        doc = json.loads(state_path(cwd).read_text())
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(cwd: str, st: dict) -> None:
    p = state_path(cwd)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(st, indent=1, sort_keys=True))
    os.replace(tmp, p)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── artifacts ────────────────────────────────────────────────────────────────────────────────────
def artifact_name(original: str) -> tuple[str, str]:
    """(the plain name to write under the workspace root, "") or ("", why it was refused).

    `original_filename` comes from the remote run, and in the end from the model: a name is
    input. Only a plain file name lands: no path separator of either kind, no `..`, nothing that
    opens a dot directory the runner owns, no control characters, and nothing that is only dots
    or whitespace."""
    name = (original or "").strip()
    if not name:
        return "", "empty artifact name"
    if "/" in name or "\\" in name or "\0" in name:
        return "", f"artifact name carries a path: {original!r}"
    if name in (".", "..") or name.startswith(".."):
        return "", f"artifact name is a traversal: {original!r}"
    if any(ord(c) < 32 for c in name):
        return "", f"artifact name carries control characters: {original!r}"
    if name.startswith("."):
        # .harness, .git and the CLI homes live here, and a hidden file is never a deliverable
        return "", f"artifact name opens a dot directory or hidden file: {original!r}"
    if len(name.encode("utf-8")) > 240:
        # a file name is at most 255 BYTES; cut by bytes, keeping the extension and room for " (n)"
        stem, ext = os.path.splitext(name)
        ext = ext if len(ext.encode("utf-8")) <= 16 else ""
        name = stem.encode("utf-8")[:240 - len(ext.encode("utf-8"))].decode("utf-8", "ignore").rstrip() + ext
    return name, ""


def land_artifact(cwd: str, name: str, data: bytes | pathlib.Path) -> tuple[str, str]:
    """Write `data` as `name` under the workspace root; (the relative path written, a note).

    An existing path is never overwritten and a symlink is never followed: a second artifact of
    the same name in one session (or a file the agent of an earlier turn left) lands beside it as
    `name (2).ext`, and the note says so. The write is to a temporary name and renamed into place
    with O_EXCL semantics, so a race with the agent's own files cannot replace one."""
    root = pathlib.Path(cwd)
    stem, ext = os.path.splitext(name)
    candidate, n, note = name, 1, ""
    while True:
        target = root / candidate
        if target.is_symlink():
            n += 1
            candidate = f"{stem} ({n}){ext}"
            note = f"{name!r} was a symlink; written as {candidate!r}"
            continue
        try:
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            n += 1
            candidate = f"{stem} ({n}){ext}"
            note = f"{name!r} already existed; written as {candidate!r}"
            continue
        with os.fdopen(fd, "wb") as f:
            if isinstance(data, (bytes, bytearray)):
                f.write(data)
            else:                                   # a download already on disk (see Turn.artifact)
                with open(data, "rb") as src:
                    shutil.copyfileobj(src, f, 1 << 20)
        return candidate, note


# ── the Agent definition ────────────────────────────────────────────────────────────────────────
def tools_config(disabled: list[str]) -> list[dict]:
    """The toolset entry: the enabled built-ins as a strict whitelist, each `always_allow` so no
    call ever pauses for a confirmation nobody is here to give, and the disabled ones named in
    `disallowed_tools` as well. Both lists, because an EMPTY `enabled_tools` means "the default
    set" to Qoder, not "nothing"."""
    off = {t for t in (disabled or []) if t in TOOLS}
    on = [t for t in TOOLS if t not in off]
    entry: dict = {"type": TOOLSET,
                   "configs": [{"name": t, "enabled": True, "permission_policy": {"type": "always_allow"}}
                               for t in on]}
    if on:
        entry["enabled_tools"] = on
    if off:
        entry["disallowed_tools"] = sorted(off)
        entry["configs"] += [{"name": t, "enabled": False} for t in sorted(off)]
    return [entry]


def mcp_config(servers: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """(mcp_servers for the Agent, the servers whose bearer needs a Vault credential, the ones this
    backend cannot offer). Only a Streamable HTTP URL reaches Qoder; a plugin's stdio server is a
    process on this box, which Qoder's cloud cannot dial. A header other than a bearer has no
    home in a Vault credential either."""
    out, creds, dropped = [], [], []
    seen: set[str] = set()
    for i, s in enumerate(servers or []):
        if not isinstance(s, dict):
            continue
        raw_name = str(s.get("name") or s.get("id") or f"mcp{i}")
        name = re.sub(r"[^A-Za-z0-9_-]+", "-", raw_name).strip("-") or f"mcp{i}"
        url = str(s.get("url") or "").strip()
        if not url:
            dropped.append({"name": raw_name, "reason": "stdio server: a process on the runner's box"})
            continue
        if name in seen:
            name = f"{name}-{i}"
        seen.add(name)
        out.append({"name": name, "type": "url", "url": url})
        auth = s.get("auth")
        hdrs = s.get("headers") if isinstance(s.get("headers"), dict) else {}
        bearer = ""
        if auth:
            bearer = str(auth)
        for k, v in hdrs.items():
            if str(k).lower() == "authorization" and v:
                bearer = str(v)
            elif v:
                dropped.append({"name": raw_name, "reason": f"header {k} cannot travel: Qoder takes a bearer in a Vault only"})
        if bearer:
            if bearer.lower().startswith("bearer "):
                bearer = bearer[7:].strip()
            creds.append({"url": url, "token": bearer})
    return out, creds, dropped


def agent_body(job: dict, skills: list[dict], mcp_servers: list[dict]) -> dict:
    model: str | dict = str(job.get("model") or "ultimate")
    effort = str(job.get("effort") or "").strip().lower()
    if effort and effort in EFFORTS:
        model = {"id": model, "effort": effort}
    name = f"harnessrouter {pathlib.Path(str(job.get('cwd') or '')).name or 'session'}"[:256]
    return {"name": name, "model": model,
            "description": "Created by HarnessRouter for one session; deleted with it.",
            "system": system_prompt(job),
            "tools": tools_config(job.get("tools_disabled") or []),
            "mcp_servers": mcp_servers,
            "skills": [{"type": "custom", "skill_id": s["id"], "version": s["version"]} for s in skills],
            "metadata": {"harnessrouter": "1"}}


def system_prompt(job: dict) -> str:
    """The harness's instructions, then the contract this runtime has instead of a workspace: a
    file reaches the person only when it is delivered. A file written in Qoder's sandbox and never
    passed to DeliverArtifacts does not exist to the user, and the artifact scenario measures it."""
    base = str(job.get("agent_doc") or "").strip()
    lines = ["## Delivering files", "",
             "You run in a remote sandbox. The user sees NO file you write unless you deliver it: when "
             "a task produces a deliverable (a document, a deck, code, an export), save it and then call "
             "DeliverArtifacts with its path. Deliver each file once, by a plain file name; an "
             "undelivered file is lost to the user.",
             "", f"Files the user attaches are mounted read-only under `{MOUNT_ROOT}/`; each message "
             "names the ones it brought."]
    block = "\n".join(lines)
    return (base + "\n\n" + block) if base else block


def config_hash(body: dict) -> str:
    return _sha(json.dumps(body, sort_keys=True).encode())


# ── skills ───────────────────────────────────────────────────────────────────────────────────────
def skill_tree(folder: str) -> tuple[str, list[tuple[str, bytes]], str]:
    """(the frontmatter name, [(relative path, bytes)], "") for a skill folder, or ("", [], why).
    Qoder requires the package's single top-level directory to equal SKILL.md's `name`, which
    must match ^[a-z0-9][a-z0-9_-]*$ — a bundle whose name does not cannot be published."""
    root = pathlib.Path(folder)
    manifest = root / "SKILL.md"
    if not manifest.is_file():
        return "", [], f"{root.name}: no SKILL.md"
    name = ""
    try:
        head = manifest.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return "", [], f"{root.name}: {e}"
    if head.startswith("---"):
        for ln in head.split("\n")[1:60]:
            if ln.strip() == "---":
                break
            if ln.startswith("name:"):
                name = ln.split(":", 1)[1].strip().strip("'\"")
    if not name or not _SKILL_NAME_RE.match(name) or len(name) > 64:
        return "", [], f"{root.name}: SKILL.md name {name!r} is not a Qoder skill name"
    files: list[tuple[str, bytes]] = []
    total = 0
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.is_symlink():
            data = p.read_bytes()
            total += len(data)
            files.append((f"{name}/{p.relative_to(root).as_posix()}", data))
    if total > 50 * 1024 * 1024:
        return "", [], f"{root.name}: {total} bytes, over the 50 MB package limit"
    return name, files, ""


def publish_skills(api: Api, st: dict, skills: list[dict], notes: list[str]) -> list[dict]:
    """Each harness skill bundle as a Qoder custom Skill (a new version when its bytes changed),
    reused across the session's turns by content hash; → the bindings for the Agent."""
    known: dict = st.setdefault("skills", {})
    out: list[dict] = []
    for s in skills or []:
        folder = str((s or {}).get("dir") or "")
        name, files, why = skill_tree(folder)
        if why:
            notes.append(f"skill not published: {why}")
            continue
        digest = _sha(b"".join(_sha(d).encode() + p.encode() for p, d in files))
        rec = known.get(name) or {}
        if rec.get("id") and rec.get("sha") == digest and rec.get("version"):
            out.append({"id": rec["id"], "version": rec["version"]})
            continue
        parts = [("files", path, mimetypes.guess_type(path)[0] or "application/octet-stream", data)
                 for path, data in files]
        body, ctype = multipart(parts)
        if rec.get("id"):
            ver = api.request("POST", f"/skills/{rec['id']}/versions", data=body,
                              headers={"content-type": ctype})
            version = str((ver or {}).get("version") or "")
        else:
            created = api.request("POST", "/skills", data=body, headers={"content-type": ctype})
            rec = {"id": str((created or {}).get("id") or "")}
            version = str((created or {}).get("latest_version") or "")
        if not rec.get("id") or not version:
            notes.append(f"skill {name}: Qoder returned no id/version")
            continue
        rec.update(sha=digest, version=version)
        known[name] = rec
        out.append({"id": rec["id"], "version": version})
    return out


# ── input files ──────────────────────────────────────────────────────────────────────────────────
def upload_ok(rel: str, size: int) -> str:
    """"" when the upload endpoint takes this file, else why not."""
    base = os.path.basename(rel)
    ext = os.path.splitext(base)[1].lower()
    mime = (mimetypes.guess_type(base)[0] or "").lower()
    if size > UPLOAD_MAX_BYTES:
        return f"{rel}: {size} bytes, over Qoder's 5 MB upload limit"
    if ext in UPLOAD_EXT or base.lower() in UPLOAD_BARE or mime.startswith(UPLOAD_MIME_PREFIX) or mime in UPLOAD_MIME:
        return ""
    return f"{rel}: Qoder accepts text-type input files only (binary, image and archive files are refused)"


def upload_inputs(api: Api, st: dict, cwd: str, rels: list[str]) -> list[dict]:
    """Upload the runner's staged input files once each (by content hash); → the file resources
    to mount, with the mount path the model is told."""
    known: dict = st.setdefault("files", {})
    out: list[dict] = []
    for rel in rels or []:
        p = pathlib.Path(cwd) / rel
        try:
            data = p.read_bytes()
        except OSError:
            continue
        digest = _sha(data)
        rec = known.get(rel) or {}
        if not (rec.get("id") and rec.get("sha") == digest):
            body, ctype = multipart([("file", os.path.basename(rel),
                                      mimetypes.guess_type(rel)[0] or "text/plain", data),
                                     ("name", None, "", os.path.basename(rel).encode())])
            created = api.request("POST", "/files", data=body, headers={"content-type": ctype})
            rec = {"id": str((created or {}).get("id") or ""), "sha": digest, "mounted": []}
            known[rel] = rec
        mount = f"{MOUNT_ROOT}/{rel.lstrip('/')}"
        out.append({"type": "file", "file_id": rec["id"], "mount_path": mount, "_rel": rel})
    return out


# ── the turn ─────────────────────────────────────────────────────────────────────────────────────
class Turn:
    def __init__(self, job: dict):
        self.job = job
        self.cwd = str(job.get("cwd") or os.getcwd())
        self.api = Api(str(job.get("base_url") or ""), str(job.get("api_key") or ""))
        self.st = load_state(self.cwd)
        self.notes: list[str] = []
        self.session_id = ""
        self.final = ""
        self.streamed: dict[str, str] = {}      # delta text already emitted, by event id
        self.declared: list[dict] = []          # artifacts the stream announced
        self.landed: list[dict] = []
        self.artifact_failures: list[str] = []
        self.usage: dict | None = None
        self.error: dict | None = None
        self.stop_reason: dict | None = None
        self.terminated = False
        self.last_event_id = ""
        self.pending_confirm: list[str] = []
        self.deny_ids: set[str] = set()         # pending confirmations of tools the harness disabled
        self.replaying: dict[str, int] = {}     # a reconnect is replaying deltas of this message: bytes seen
        self.disabled = {str(t) for t in (job.get("tools_disabled") or [])}
        self.mounts: list[str] = []             # where this turn's attached files are mounted
        self.written: list[str] = []            # paths the agent wrote or edited this turn
        self.delivered_paths: set[str] = set()  # paths it passed to DeliverArtifacts
        self.nudging = False                    # the delivery round (deliver_written) is running

    # ── remote objects ──
    def ensure_environment(self) -> str:
        env_id = str(self.st.get("environment_id") or "")
        if env_id:
            return env_id
        created = self.api.request("POST", "/environments", {
            "name": f"harnessrouter {pathlib.Path(self.cwd).name}"[:256],
            "description": "Created by HarnessRouter for one session; deleted with it.",
            "config": {"type": "cloud"}, "metadata": {"harnessrouter": "1"}})
        env_id = str((created or {}).get("id") or "")
        if not env_id:
            raise ApiError(0, "api_error", "environment create returned no id", "/environments")
        self.st["environment_id"] = env_id
        save_state(self.cwd, self.st)
        return env_id

    def ensure_vault(self, creds: list[dict]) -> list[str]:
        """The session's Vault, holding one active static_bearer credential per MCP server URL with
        THIS turn's token. A server URL is unique among a vault's active credentials, so a token that
        changed since the last turn (a rotated key, or the per-turn credential the gateway mints for
        a server it hosts itself, which expires) archives the old credential and creates the new one:
        a vault that kept the first turn's token fails that server on every later turn. Only a hash
        of each token is kept in the state, never the token."""
        if not creds:
            return [self.st["vault_id"]] if self.st.get("vault_id") else []
        vid = str(self.st.get("vault_id") or "")
        if not vid:
            created = self.api.request("POST", "/vaults", {
                "display_name": f"harnessrouter {pathlib.Path(self.cwd).name}"[:255],
                "metadata": {"harnessrouter": "1"}})
            vid = str((created or {}).get("id") or "")
            if not vid:
                raise ApiError(0, "api_error", "vault create returned no id", "/vaults")
            self.st["vault_id"] = vid
            save_state(self.cwd, self.st)
        have: dict = self.st.setdefault("vault_creds", {})       # url -> {"id", "sha"}
        for c in creds:
            sha = _sha(c["token"].encode())
            cur = have.get(c["url"]) or {}
            if cur.get("id") and cur.get("sha") == sha:
                continue
            if cur.get("id"):
                self._archive_credential(vid, cur["id"])
            have[c["url"]] = {"id": self._create_credential(vid, c), "sha": sha}
            save_state(self.cwd, self.st)
        return [vid]

    def _create_credential(self, vid: str, c: dict) -> str:
        body = {"auth": {"type": "static_bearer", "mcp_server_url": c["url"], "token": c["token"]}}
        try:
            doc = self.api.request("POST", f"/vaults/{vid}/credentials", body)
        except ApiError as e:
            if e.status != 409:
                raise
            # an active credential for this URL that the state does not know: archived, then made anew
            for old in self._active_credentials(vid, c["url"]):
                self._archive_credential(vid, old)
            doc = self.api.request("POST", f"/vaults/{vid}/credentials", body)
        cid = str((doc or {}).get("id") or "")
        if not cid:
            raise ApiError(0, "api_error", "credential create returned no id", f"/vaults/{vid}/credentials")
        return cid

    def _active_credentials(self, vid: str, url: str) -> list[str]:
        doc = self.api.request("GET", f"/vaults/{vid}/credentials")
        out = []
        for x in (doc or {}).get("data") or []:
            if not isinstance(x, dict) or not x.get("id") or x.get("archived_at"):
                continue
            if url in (x.get("mcp_server_url"), (x.get("auth") or {}).get("mcp_server_url")):
                out.append(str(x["id"]))
        return out

    def _archive_credential(self, vid: str, cid: str) -> None:
        try:
            self.api.request("POST", f"/vaults/{vid}/credentials/{cid}/archive")
        except ApiError as e:
            if e.status not in (404, 409):       # gone, or archived already
                raise

    def ensure_agent(self, body: dict) -> tuple[str, int, bool]:
        """(agent id, version, whether the configuration changed this turn)."""
        digest = config_hash(body)
        aid = str(self.st.get("agent_id") or "")
        if aid and self.st.get("agent_hash") == digest and self.st.get("agent_version"):
            return aid, int(self.st["agent_version"]), False
        if aid:
            current = self.api.request("GET", f"/agents/{aid}")
            version = int((current or {}).get("version") or 1)
            updated = self.api.request("POST", f"/agents/{aid}", {**body, "version": version})
        else:
            updated = self.api.request("POST", "/agents", body)
            aid = str((updated or {}).get("id") or "")
        version = int((updated or {}).get("version") or 1)
        if not aid:
            raise ApiError(0, "api_error", "agent create returned no id", "/agents")
        self.st.update(agent_id=aid, agent_version=version, agent_hash=digest)
        save_state(self.cwd, self.st)
        return aid, version, True

    def find_session(self, resume: str) -> tuple[str, bool]:
        """(the session to continue, False) or ("", lost): the id the caller named, when the state
        knows it and Qoder still has it in a state that takes a message."""
        if not resume:
            return "", False
        if resume != str(self.st.get("session_id") or ""):
            return "", True
        try:
            doc = self.api.request("GET", f"/sessions/{resume}")
        except ApiError as e:
            if e.status == 404:
                return "", True
            raise
        if not isinstance(doc, dict) or doc.get("archived_at") or doc.get("status") == "terminated":
            return "", True
        if doc.get("status") in ("running", "rescheduling"):
            raise ApiError(409, "invalid_request_error",
                           "the Qoder session is still processing an earlier turn; cancel it or wait",
                           f"/sessions/{resume}")
        return resume, False

    def create_session(self, aid: str, version: int, env_id: str, vault_ids: list[str],
                       resources: list[dict]) -> str:
        body: dict = {"agent": {"id": aid, "type": "agent", "version": version},
                      "environment_id": env_id,
                      "title": f"HarnessRouter {pathlib.Path(self.cwd).name}"[:200],
                      "metadata": {"harnessrouter": "1"}}
        if vault_ids:
            body["vault_ids"] = vault_ids
        if resources:
            body["resources"] = [{k: v for k, v in r.items() if not k.startswith("_")} for r in resources]
        doc = self.api.request("POST", "/sessions", body)
        sid = str((doc or {}).get("id") or "")
        if not sid:
            raise ApiError(0, "api_error", "session create returned no id", "/sessions")
        self.st["session_id"] = sid
        self.st.setdefault("sessions", [])
        if sid not in self.st["sessions"]:
            self.st["sessions"].append(sid)
        for r in resources:
            self.st["files"][r["_rel"]].setdefault("mounted", []).append(sid)
        save_state(self.cwd, self.st)
        return sid

    def mount_resources(self, sid: str, resources: list[dict]) -> None:
        for r in resources:
            rec = self.st["files"][r["_rel"]]
            if sid in (rec.get("mounted") or []):
                continue
            try:
                self.api.request("POST", f"/sessions/{sid}/resources",
                                 {"type": "file", "file_id": r["file_id"], "mount_path": r["mount_path"]})
            except ApiError as e:
                if e.status != 409:
                    raise
            rec.setdefault("mounted", []).append(sid)
        save_state(self.cwd, self.st)

    # ── the stream ──
    def handle(self, eid: str, ev: str, data: str, posted_id: str, started: list[bool]) -> bool:
        """One SSE message; True when the turn is over."""
        try:
            doc = json.loads(data) if data else {}
        except ValueError:
            return False
        if not isinstance(doc, dict):
            return False
        t = str(doc.get("type") or ev or "")
        if t == "heartbeat":
            return False
        if eid and t not in ("event_start", "event_delta"):
            self.last_event_id = eid
        if not started[0]:
            # events before this turn's message are history, not this turn
            if (t == "user.message" and doc.get("id") == posted_id) or t == "session.status_running":
                started[0] = True
            return False
        if t == "event_start":
            e = doc.get("event") or {}
            if e.get("type") == "agent.message" and e.get("id"):
                mid = str(e["id"])
                if mid in self.streamed:
                    # a reconnect replays the message's start and its retained deltas: what was
                    # already written is not written twice
                    self.replaying[mid] = 0
                else:
                    self.streamed[mid] = ""
            return False
        if t == "event_delta":
            if self.nudging:
                return False        # the delivery round's own words are not the turn's answer
            d = doc.get("delta") or {}
            c = d.get("content") or {}
            txt = str(c.get("text") or "") if c.get("type") == "text" else ""
            mid = str(doc.get("event_id") or "")
            if not txt or not mid:
                return False
            if mid in self.replaying:
                pos, have = self.replaying[mid], len(self.streamed.get(mid, ""))
                if pos + len(txt) <= have:
                    self.replaying[mid] = pos + len(txt)
                    return False
                txt = txt[max(0, have - pos):]
                del self.replaying[mid]
            self.streamed[mid] = self.streamed.get(mid, "") + txt
            _emit("text", {"text": txt})
            return False
        if t == "agent.message":
            full = "".join(str(c.get("text") or "") for c in (doc.get("content") or [])
                           if isinstance(c, dict) and c.get("type") == "text")
            seen = self.streamed.pop(str(doc.get("id") or ""), "")
            if self.nudging:
                return False
            if full:
                self.final = full
            if full and full != seen:
                if not seen:
                    _emit("text", {"text": full})
                elif full.startswith(seen):
                    _emit("text", {"text": full[len(seen):]})
            return False
        if t == "agent.thinking":
            return False       # the content is not public; the event is only a marker
        if t in ("agent.tool_use", "agent.mcp_tool_use", "agent.custom_tool_use"):
            name = str(doc.get("name") or "tool")
            if t == "agent.mcp_tool_use" and doc.get("mcp_server_name"):
                name = f"mcp__{doc['mcp_server_name']}__{name}"
            inp = doc.get("input") if isinstance(doc.get("input"), dict) else {}
            _emit("tool_use", {"id": str(doc.get("id") or ""), "name": name, "input": inp,
                               "permission": doc.get("evaluated_permission")})
            if t == "agent.tool_use" and name in ("Write", "Edit") and inp.get("file_path"):
                if str(inp["file_path"]) not in self.written:
                    self.written.append(str(inp["file_path"]))
            if t == "agent.tool_use" and name == "DeliverArtifacts":
                for f in inp.get("files") or []:
                    if isinstance(f, dict) and f.get("path"):
                        self.delivered_paths.add(str(f["path"]))
            if doc.get("evaluated_permission") == "ask" and doc.get("id"):
                self.pending_confirm.append(str(doc["id"]))
                bare = str(doc.get("name") or "")
                if name in self.disabled or bare in self.disabled:
                    self.deny_ids.add(str(doc["id"]))
            return False
        if t in ("agent.tool_result", "agent.mcp_tool_result"):
            text = "\n".join(str(c.get("text") or "") for c in (doc.get("content") or [])
                             if isinstance(c, dict) and c.get("type") == "text")
            _emit("tool_result", {"tool_use_id": str(doc.get("tool_use_id") or doc.get("mcp_tool_use_id") or ""),
                                  "text": text, "is_error": bool(doc.get("is_error"))})
            return False
        if t == "agent.artifact_delivered":
            self.artifact(doc)
            return False
        if t == "session.usage":
            self.usage = {k: doc.get(k) for k in ("model_credits", "sandbox_runtime_credits", "total_credits")}
            return False
        if t == "session.error":
            err = doc.get("error") if isinstance(doc.get("error"), dict) else {}
            retry = str(((err.get("retry_status") or {}).get("type")) or "")
            self.error = {"message": str(err.get("message") or "Qoder reported an error"),
                          "type": str(err.get("type") or ""), "retry": retry}
            _emit("error", self.error)
            return False
        if t == "session.status_rescheduled":
            _emit("notice", {"text": "Qoder is retrying the model request (rescheduling)"})
            return False
        if t == "session.status_idle":
            self.stop_reason = doc.get("stop_reason") if isinstance(doc.get("stop_reason"), dict) else {"type": ""}
            if self.stop_reason.get("type") == "requires_action":
                self.confirm(list(self.stop_reason.get("event_ids") or []) or self.pending_confirm)
                self.pending_confirm = []
                self.stop_reason = None        # the turn goes on; its real stop is still to come
                return False
            return True
        if t in ("session.status_terminated", "session.deleted"):
            self.terminated = True
            return True
        return False

    def confirm(self, event_ids: list[str]) -> None:
        """Answer every pending tool confirmation: deny a tool the harness disabled, allow the rest.
        The Agent's permission policy makes this path rare (always_allow on every built-in); an MCP
        tool whose server-side default asks still gets its answer here instead of parking the
        session, which never times out on its own."""
        events = []
        for eid in event_ids:
            deny = eid in self.deny_ids
            ev: dict = {"type": "user.tool_confirmation", "tool_use_id": eid, "result": "deny" if deny else "allow"}
            if deny:
                ev["deny_message"] = "This tool is disabled for this harness."
            events.append(ev)
        if events:
            self.api.request("POST", f"/sessions/{self.session_id}/events", {"events": events})

    def artifact(self, doc: dict) -> None:
        fid = str(doc.get("file_id") or "")
        original = str(doc.get("original_filename") or "")
        size = doc.get("size")
        rec = {"file_id": fid, "name": original, "size": size}
        self.declared.append(rec)
        self.st.setdefault("artifacts", [])
        if fid and fid not in self.st["artifacts"]:
            self.st["artifacts"].append(fid)
            save_state(self.cwd, self.st)
        name, why = artifact_name(original)
        if not why and isinstance(size, int) and size > ARTIFACT_MAX_BYTES:
            why = f"{original}: {size} bytes declared, over the {ARTIFACT_MAX_BYTES}-byte artifact limit"
        if why:
            self.artifact_failures.append(why)
            _emit("artifact", {**rec, "status": "refused", "reason": why})
            return
        # The download goes to disk as it arrives, under .harness/ (never a produced file), and is
        # landed from there; nothing about one artifact (a full disk, a name the filesystem will not
        # take) is let out of here, where it would read as a dropped stream and lose its reason.
        part = pathlib.Path(self.cwd) / ".harness" / "qoder" / f"download-{uuid.uuid4().hex}.part"
        try:
            got, why = self._download(fid, original, part)
            if got is not None and isinstance(size, int) and size >= 0 and got != size:
                why, got = f"{original}: {got} bytes landed, {size} declared", None
            if got is None:
                self.artifact_failures.append(why or f"{original}: download failed")
                _emit("artifact", {**rec, "status": "failed", "reason": why})
                return
            try:
                written, note = land_artifact(self.cwd, name, part)
            except OSError as e:
                why = f"{original}: could not be written: {type(e).__name__}: {e}"[:300]
                self.artifact_failures.append(why)
                _emit("artifact", {**rec, "status": "failed", "reason": why})
                return
        finally:
            try:
                part.unlink()
            except OSError:
                pass
        if note:
            self.notes.append(note)
        self.landed.append({**rec, "path": written})
        _emit("artifact", {**rec, "status": "landed", "path": written})

    def _download(self, fid: str, original: str, part: pathlib.Path) -> tuple[int | None, str]:
        """(bytes written to `part`, "") or (None, why). The presigned link is asked for again once
        if the first one fails (its lifetime is not documented); a refused file is not retried."""
        why = ""
        for _attempt in (0, 1):
            try:
                link = self.api.request("GET", f"/files/{fid}/content")
                url = str((link or {}).get("url") or "")
                if not url:
                    return None, f"{original}: no download url"
                if urllib.parse.urlsplit(url).scheme.lower() not in ("https", "http"):
                    # urllib also opens file:, ftp: and data: URLs; a link that is not a web address
                    # would land a file of this box (or anything else) as the artifact
                    return None, f"{original}: the download link is not a web address"
                req = urllib.request.Request(url, method="GET")       # presigned: no credential travels
                part.parent.mkdir(parents=True, exist_ok=True)
                n = 0
                with urllib.request.urlopen(req, timeout=CALL_TIMEOUT_S) as resp, open(part, "wb") as out:
                    while True:
                        chunk = resp.read(1 << 20)
                        if not chunk:
                            break
                        n += len(chunk)
                        if n > ARTIFACT_MAX_BYTES:
                            return None, f"{original}: over the {ARTIFACT_MAX_BYTES}-byte artifact limit"
                        out.write(chunk)
                return n, ""
            except ApiError as e:
                why = f"{original}: {e}"
                if e.status in (404, 410, 403):
                    break
            except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError) as e:
                why = f"{original}: download failed: {type(e).__name__}: {e}"[:300]
        return None, why

    def run_stream(self, posted_id: str) -> None:
        """Read the session's stream until this turn ends, reconnecting from the last event id on
        a drop; the message is never sent again.

        The stream is opened AFTER the message is posted, with the message's own event id as the
        cursor: the server replays from there, so nothing of this turn is missed however long the
        open took, and nothing of an earlier turn is read as this one's."""
        started = [bool(posted_id)]
        self.last_event_id = posted_id
        path = f"/sessions/{self.session_id}/events/stream?event_deltas%5B%5D=agent.message"
        attempts = 0
        idle_eofs = 0
        while True:
            try:
                resp = self.api.stream(path, self.last_event_id)
            except ApiError as e:
                if e.status in (400, 404) and self.last_event_id:
                    self.last_event_id = ""          # the cursor is gone; start from now
                    attempts += 1
                    if attempts <= STREAM_RECONNECTS:
                        continue
                raise
            except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError) as e:
                attempts += 1
                if attempts > STREAM_RECONNECTS:
                    raise ApiError(0, "stream", f"the event stream could not be opened: {e}"[:300])
                time.sleep(min(2.0 * attempts, 15.0))
                continue
            try:
                for eid, ev, data in iter_sse(resp):
                    if self.handle(eid, ev, data, posted_id, started):
                        return
            except (http.client.HTTPException, TimeoutError, OSError) as e:
                attempts += 1
                _emit("notice", {"text": f"event stream dropped ({type(e).__name__}); resuming from {self.last_event_id or 'now'}"})
                if attempts > STREAM_RECONNECTS:
                    raise ApiError(0, "stream", f"the event stream kept dropping: {e}"[:300])
                time.sleep(min(2.0 * attempts, 15.0))
                continue
            finally:
                try:
                    resp.close()
                except Exception:  # noqa: BLE001
                    pass
            # EOF without a terminal event: the server closed the stream. Where the session stands
            # decides: terminated ends the turn; running (or a turn resumed after a confirmation)
            # means reconnect from the cursor; idle twice in a row with no idle event seen means
            # the event was lost on the wire and the turn is over.
            doc = self.api.request("GET", f"/sessions/{self.session_id}")
            status = str((doc or {}).get("status") or "")
            if status == "terminated":
                self.terminated = True
                return
            if status == "idle" and started[0]:
                idle_eofs += 1
                if idle_eofs >= 2:
                    if (self.stop_reason or {}).get("type") != "requires_action":
                        self.stop_reason = self.stop_reason or {"type": "end_turn"}
                        return
            attempts += 1
            if attempts > STREAM_RECONNECTS:
                raise ApiError(0, "stream", "the event stream ended without a terminal event")
            time.sleep(min(0.5 * attempts, 5.0))

    def post_message(self, text: str | None = None) -> str:
        """Send the turn's message once (or `text`, the delivery round's); → the user.message event
        id. If the call itself fails after it may have been delivered, the session's history says
        whether it was, and the message is never sent a second time."""
        before = self.last_history_id()
        if text is None:
            text = str(self.job.get("prompt") or "")
            if self.mounts:
                text = ("[Attached files, mounted read-only: " + ", ".join(f"`{m}`" for m in self.mounts) + "]\n\n" + text)
        body = {"events": [{"type": "user.message", "content": [{"type": "text", "text": text}]}]}
        try:
            doc = self.api.request("POST", f"/sessions/{self.session_id}/events", body)
            for e in (doc or {}).get("data") or []:
                if isinstance(e, dict) and e.get("type") == "user.message":
                    return str(e.get("id") or "")
            return ""
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError):
            q = "/events?limit=20&order=asc&types=user.message" + (f"&after_id={before}" if before else "")
            try:
                doc = self.api.request("GET", f"/sessions/{self.session_id}{q}")
            except ApiError:
                doc = None
            for e in (doc or {}).get("data") or []:
                if isinstance(e, dict) and e.get("type") == "user.message":
                    _emit("notice", {"text": "the message's acknowledgement was lost; the session history shows it arrived"})
                    return str(e.get("id") or "")
            raise ApiError(0, "api_error", "the message could not be delivered", f"/sessions/{self.session_id}/events")

    def undelivered(self) -> list[str]:
        """Files the agent wrote or edited this turn that never reached the person: not passed to
        DeliverArtifacts and not among the delivered names. Scratch space, the read-only uploads and
        dot paths are not deliverables."""
        names = {str(d.get("name") or "") for d in self.declared}
        out: list[str] = []
        for p in self.written:
            if p in out or p in self.delivered_paths or os.path.basename(p) in names:
                continue
            if p.startswith(("/tmp/", MOUNT_ROOT + "/")) or any(s.startswith(".") for s in p.split("/") if s):
                continue
            out.append(p)
        return out

    def deliver_written(self) -> None:
        """A file the agent wrote and did not deliver is lost to the person: Qoder's sandbox is
        not this workspace, and DeliverArtifacts is the only way a file comes back. Every local
        base gets what its turn wrote (the runner collects the workspace), so here a turn that ended
        normally with such files asks the session, once, to deliver them. Measured 2026-10-10 on
        0.33.0-rc.3: `auto` wrote the file the matrix's artifact scenario asked for and answered DONE
        without delivering it, though the system prompt says to twice. The round's own words are
        not shown or kept as the answer; what it delivers lands like any artifact."""
        if self.terminated or (self.stop_reason or {}).get("type") != "end_turn":
            return
        missing = self.undelivered()
        if not missing:
            return
        line = f"asked Qoder to deliver {len(missing)} file(s) the agent wrote but did not deliver: {', '.join(missing)}"
        self.notes.append(line)
        _emit("notice", {"text": line})
        self.nudging, self.stop_reason = True, None
        try:
            posted = self.post_message("Deliver these files you wrote to the user now with DeliverArtifacts, in one "
                                       "call, without changing them: " + ", ".join(missing) +
                                       ". Then reply with only: DELIVERED")
            self.run_stream(posted)
        finally:
            self.nudging = False

    def last_history_id(self) -> str:
        try:
            doc = self.api.request("GET", f"/sessions/{self.session_id}/events?limit=1&order=desc")
            return str((doc or {}).get("first_id") or "")
        except (ApiError, urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError):
            return ""

    def snapshot_usage(self) -> None:
        try:
            doc = self.api.request("GET", f"/sessions/{self.session_id}")
            u = (doc or {}).get("usage")
            if isinstance(u, dict) and u:
                self.usage = {k: u.get(k) for k in ("model_credits", "sandbox_runtime_credits", "total_credits")}
        except (ApiError, urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError):
            pass

    def charge(self) -> dict | None:
        """This turn's charge: the session's usage now, less what the session had used when the
        turn began. Qoder's usage is the SESSION's running total (the recorded live session read
        0.35 credits after its first turn and 0.61 after its second), so the snapshot as it stands
        would bill every earlier turn again on each new one. Sandbox credits settle after idle, so
        what settles late is counted on the next turn rather than lost or counted twice."""
        if not self.usage or self.usage.get("total_credits") is None:
            return None
        before = (self.st.get("usage_seen") or {}).get(self.session_id) or {}

        def spent(k: str):
            now = self.usage.get(k)
            if not isinstance(now, (int, float)):
                return now
            was = before.get(k)
            return round(max(now - (was if isinstance(was, (int, float)) else 0), 0), 6)

        return {"amount": spent("total_credits"), "unit": "qoder_credits", "basis": "snapshot",
                "model_credits": spent("model_credits"),
                "sandbox_runtime_credits": spent("sandbox_runtime_credits"),
                "session_total": self.usage.get("total_credits")}

    def cancel_remote(self) -> str:
        """Stop the remote turn; → the line the record keeps about it."""
        if not self.session_id:
            return "cancelled before a Qoder session existed"
        try:
            self.api.request("POST", f"/sessions/{self.session_id}/cancel", timeout=20.0)
            return f"cancel accepted by Qoder for session {self.session_id}"
        except Exception as e:  # noqa: BLE001
            return f"cancel failed ({str(e)[:200]}); Qoder session {self.session_id} may still be running"

    # ── main ──
    def run(self) -> int:
        job = self.job
        resume = str(job.get("resume_session_id") or "")
        sid, lost = self.find_session(resume)
        if lost:
            _emit("resume_lost", {"requested_session_id": resume})
        _emit("__hr_init", {"session_id": sid, "agent_id": self.st.get("agent_id") or ""})

        # input files first: a file Qoder cannot take fails the turn before anything is created
        rels = [str(r) for r in (job.get("input_files") or [])]
        for rel in rels:
            try:
                size = os.path.getsize(os.path.join(self.cwd, rel))
            except OSError:
                continue
            why = upload_ok(rel, size)
            if why:
                self.result("failed", why)
                return 0
        env_id = self.ensure_environment()
        servers, creds, dropped = mcp_config(job.get("mcp_servers") or [])
        if dropped:
            _emit("mcp_unavailable", {"servers": dropped})
        vault_ids = self.ensure_vault(creds)
        bindings = publish_skills(self.api, self.st, job.get("skills") or [], self.notes)
        save_state(self.cwd, self.st)
        resources = upload_inputs(self.api, self.st, self.cwd, rels)
        save_state(self.cwd, self.st)
        # The files this message brought are named IN the message. The Agent's system prompt cannot
        # carry them: a session keeps the Agent version it was created with, so a file attached on a
        # later turn was mounted and never mentioned, and the model did not know it was there.
        self.mounts = [r["mount_path"] for r in resources]
        body = agent_body(job, bindings, servers)
        aid, version, changed = self.ensure_agent(body)
        if sid:
            if changed:
                # a session pins its Agent version; its tools and servers are what it lets a
                # later turn replace, so a tool disabled between turns is withheld on this one
                self.api.request("POST", f"/sessions/{sid}", {"agent": {"tools": body["tools"],
                                                                        "mcp_servers": body["mcp_servers"]}})
            self.mount_resources(sid, resources)
        else:
            sid = self.create_session(aid, version, env_id, vault_ids, resources)
        self.session_id = sid
        _emit("session", {"session_id": sid, "agent_id": aid, "agent_version": version,
                          "environment_id": env_id})
        posted = self.post_message()
        self.run_stream(posted)
        self.deliver_written()
        self.snapshot_usage()
        save_state(self.cwd, self.st)

        missing = [d for d in self.declared if not any(l["file_id"] == d["file_id"] for l in self.landed)]
        lost = self.undelivered()
        if self.terminated:
            self.result("failed", (self.error or {}).get("message") or "the Qoder session was terminated")
        elif self.error and self.error.get("retry") in ("terminal", "exhausted") and not self.final:
            self.result("failed", self.error["message"])
        elif str((self.stop_reason or {}).get("type") or "") != "end_turn":
            self.result("incomplete", f"stop_reason {json.dumps(self.stop_reason or {})}")
        elif missing or self.artifact_failures or lost:
            self.result("incomplete", "artifact not delivered: " + "; ".join(
                self.artifact_failures + [m["name"] for m in missing] + [f"{p} (written, never delivered)" for p in lost]))
        else:
            self.result("completed", "")
        return 0

    def result(self, status: str, reason: str) -> None:
        charge = self.charge()
        if charge and self.session_id:
            # what the session had used by the end of this turn: the next turn's charge starts here
            self.st.setdefault("usage_seen", {})[self.session_id] = dict(self.usage or {})
            try:
                save_state(self.cwd, self.st)
            except OSError:
                pass
        _emit("__hr_result", {"status": status, "reason": reason, "final": self.final,
                              "session_id": self.session_id or self.st.get("session_id") or "",
                              "charge": charge, "notes": self.notes,
                              "artifacts": self.landed})


# ── purge ────────────────────────────────────────────────────────────────────────────────────────
def purge(job: dict) -> int:
    """Delete at Qoder everything the session's turns created there, in dependency order; every
    failure is reported with its id, never swallowed. Exit 0 when nothing failed."""
    cwd = str(job.get("cwd") or os.getcwd())
    api = Api(str(job.get("base_url") or ""), str(job.get("api_key") or ""))
    st = load_state(cwd)
    done: list[str] = []
    failed: list[dict] = []

    def attempt(label: str, method: str, path: str, body: dict | None = None, ok_status=(404,)) -> bool:
        try:
            api.request(method, path, body)
            done.append(label)
            return True
        except ApiError as e:
            if e.status in ok_status:
                done.append(label + " (already gone)")
                return True
            failed.append({"what": label, "error": str(e)})
        except Exception as e:  # noqa: BLE001
            failed.append({"what": label, "error": f"{type(e).__name__}: {e}"[:300]})
        return False

    sessions = list(st.get("sessions") or ([st["session_id"]] if st.get("session_id") else []))
    for sid in sessions:
        attempt(f"cancel session {sid}", "POST", f"/sessions/{sid}/cancel", ok_status=(404, 409))
        attempt(f"delete session {sid}", "DELETE", f"/sessions/{sid}")
    for fid in list(st.get("artifacts") or []):
        attempt(f"delete artifact file {fid}", "DELETE", f"/files/{fid}")
    for rel, rec in (st.get("files") or {}).items():
        if isinstance(rec, dict) and rec.get("id"):
            attempt(f"delete input file {rec['id']} ({rel})", "DELETE", f"/files/{rec['id']}")
    if st.get("agent_id"):
        attempt(f"archive agent {st['agent_id']}", "POST", f"/agents/{st['agent_id']}/archive")
    if st.get("vault_id"):
        attempt(f"delete vault {st['vault_id']}", "DELETE", f"/vaults/{st['vault_id']}")
    for name, rec in (st.get("skills") or {}).items():
        if isinstance(rec, dict) and rec.get("id"):
            attempt(f"delete skill {rec['id']} ({name})", "DELETE", f"/skills/{rec['id']}")
    if st.get("environment_id"):
        eid = st["environment_id"]
        try:
            api.request("DELETE", f"/environments/{eid}")
            done.append(f"delete environment {eid}")
        except ApiError as e:
            if e.status == 404:
                done.append(f"delete environment {eid} (already gone)")
            elif e.status == 409:       # still referenced: the API says to archive it instead
                attempt(f"archive environment {eid}", "POST", f"/environments/{eid}/archive")
            else:
                failed.append({"what": f"delete environment {eid}", "error": str(e)})
        except Exception as e:  # noqa: BLE001
            failed.append({"what": f"delete environment {eid}", "error": f"{type(e).__name__}: {e}"[:300]})
    _emit("purge", {"done": done, "failed": failed, "state": STATE_REL})
    return 0 if not failed else 1


# ── entry ────────────────────────────────────────────────────────────────────────────────────────
def main() -> int:
    job = json.loads(sys.argv[1])
    if job.get("purge"):
        return purge(job)
    turn = Turn(job)

    def on_term(signum, frame):  # noqa: ARG001
        raise Cancelled()

    signal.signal(signal.SIGTERM, on_term)
    try:
        return turn.run()
    except Cancelled:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)      # the cancel call itself is not interrupted
        line = turn.cancel_remote()
        _emit("notice", {"text": line})
        turn.result("cancelled", line)
        return 0
    except ApiError as e:
        turn.result("failed", f"Qoder API {e.path}: {e}"[:1000])
        return 0
    except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError) as e:
        turn.result("failed", f"Qoder did not answer: {type(e).__name__}: {e}"[:1000])
        return 0


if __name__ == "__main__":
    sys.exit(main())
