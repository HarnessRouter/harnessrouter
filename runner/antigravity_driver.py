"""One turn of Google's managed Antigravity agent, as a runner subprocess.

The agent loop runs in Google's cloud, in a Linux sandbox Google hosts (an "environment"), reached
over the Gemini API's Interactions API. This process is a client of it, under the same contract as
every other backend: `__hr_init` first, one `{"m": ..., "p": ...}` JSON line per event on stdout,
`__hr_result` last, and server.py's normaliser (_antigravity_to_claude) unaware of the wire. The
standard library is all it needs: nothing is installed for this base.

A HarnessRouter session is ONE environment plus a chain of interactions. The first turn creates the
environment (POST /v1beta/environments), each turn sends its message as an interaction on it
(`environment` = its id, `previous_interaction_id` = the last turn's interaction), and the ids are
recorded in <cwd>/.harness/antigravity/state.json, which travels in the checkpoint. The environment
id is the session id the runner hands back for the next turn. `DELETE /workspace` runs this file in
purge mode, which deletes every interaction and environment the state recorded.

Files. The session's workspace goes up as one archive extracted into the environment's `workspace/`
directory (PUT /upload/v1beta/environments/{id}/files/workspace?uploadType=media&extract=true), the
agent's working directory (measured: `pwd` answers /workspace), made by the same tar
command the checkpoint makes, with its exclusions (the runner hands the command over in the job,
server.CHECKPOINT_EXCLUDE plus .harness and .git), so what leaves this box for Google is never more
than what a checkpoint keeps. It goes up only when the workspace changed since the last sync, and a
size cap is checked before anything is read. After the interaction, what the agent changed under
`workspace/` comes back (GET /v1beta/environments/{id}/files/workspace?recursive=true, then each
file with ?alt=media): a path from Google is input, so only a plain relative path under the
workspace lands, never one into .harness or .git, never through a symlink, never over the caps; a
file that could not land makes the turn `incomplete` and is named, so the console's produced files
are what is really there.

The credential never enters this process. The job carries the runner's loopback relay as the base
and a placeholder in `x-goog-api-key`; the relay holds the key and puts it on the way out
(_antigravity_relay_route in server.py), for this API's paths only. Everything this process emits
goes through scrub(): the placeholder, anything shaped like a Google API key, and the header values
of the MCP servers it handed to Google are replaced before a line is written.

Cancellation: the runner sends SIGTERM and waits a bounded grace before its SIGKILL (a remote backend,
BACKENDS[...]["remote"]). The handler raises out of whatever read is in flight, the turn posts
`POST /v1beta/interactions/{id}:cancel`, says on stdout whether that was accepted, and exits.
"""
from __future__ import annotations

import base64
import hashlib
import http.client
import json
import mimetypes
import os
import pathlib
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

AGENT = "antigravity-preview-09-2026"
# The schema revision every call pins (the steps schema; the docs' background examples send it).
API_REVISION = "2026-05-20"
STATE_REL = os.path.join(".harness", "antigravity", "state.json")
# Where the session's files live in Google's sandbox (/workspace), as the files API names it.
REMOTE_ROOT = "workspace"
# Where the Antigravity runtime discovers skills (.agents/skills/<name>/SKILL.md).
SKILLS_ROOT = ".agents/skills"

# The models agent_config.model takes on this agent, the default first (Google's model selection
# table for antigravity-preview-09-2026). The gateway's catalog is pinned equal to this tuple.
MODELS = ("gemini-4-hydrogen", "gemini-4-carbon", "gemini-4-argon", "gemini-3.8-flash", "gemini-3.6-flash",
          "gemini-3.5-flash-lite")
DEFAULT_MODEL = MODELS[0]

# The built-in tools a harness can switch off, in the API's own type names; each is sent in `tools`
# only while it is on. The filesystem tools come with the environment and have no switch. The
# gateway's catalog is pinned equal to this tuple.
TOOLS = ("code_execution", "google_search", "url_context")
# The step types each switch covers: such a step in a turn whose switch is off is Google running a
# tool it was not offered, and the turn says so rather than passing it off as the owner's choice.
TOOL_STEPS = {"code_execution": ("code_execution_call", "code_execution_result"),
              "google_search": ("google_search_call", "google_search_result"),
              "url_context": ("url_context_call", "url_context_result")}

# The caps. Each is checked before the work it bounds, never after.
UPLOAD_MAX_BYTES = 100 * 1024 * 1024        # the workspace sent to Google, summed before the archive is made
FILE_MAX_BYTES = 100 * 1024 * 1024          # one file brought back
RETURN_MAX_BYTES = 1024 * 1024 * 1024       # everything brought back in one turn
RETURN_MAX_FILES = 2000
IMAGE_MAX_BYTES = 5 * 1024 * 1024           # an attached image also sent inline with the message
IMAGES_MAX = 8
IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}

LISTING_MAX_PAGES = 50                      # of up to 1000 entries each
SSE_LINE_MAX = 32 * 1024 * 1024

CALL_TIMEOUT_S = 120.0
# A stream read that waits this long without a byte is a dead connection: the turn reads the
# interaction's stream again (or polls the interaction) rather than hanging on it.
STREAM_READ_TIMEOUT_S = 150.0
STREAM_RECONNECTS = 20
POLL_S = 3.0

# Directories never sent to Google and never written from what comes back.
NEVER_SYNCED = (".harness", ".git")
# A download link Google may redirect a file to: followed only over https to Google's own hosts, and
# with no credential (the placeholder stays on the relay's calls).
_DOWNLOAD_HOSTS = (".googleapis.com", ".googleusercontent.com")

_MCP_NAME_RE = re.compile(r"[^a-z0-9_-]+")
_SKILL_DIR_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_GOOGLE_KEY_RE = re.compile(r"AIza[0-9A-Za-z_\-]{20,}")
_KEY_PARAM_RE = re.compile(r"([?&](?:key|api_key|upload_id)=)[^&\s\"']+", re.I)
_CRED_HEADER_RE = re.compile(r"(?i)\b(x-goog-api-key|authorization|api-key|x-api-key)(\"?\s*[:=]\s*\"?)(bearer\s+)?[^\s\",}]+")


def _emit(method: str, payload) -> None:
    sys.stdout.write(json.dumps({"m": method, "p": _SCRUB.clean(payload)}, default=str) + "\n")
    sys.stdout.flush()


class Scrub:
    """What may never leave this process in a line, a record or an error: the relay's placeholder,
    anything shaped like a Google API key or a credential header, a `key=` query parameter, and the
    header values this turn handed to Google for its MCP servers. Applied to every string of every
    payload _emit writes."""

    def __init__(self):
        self.values: set[str] = set()

    def add(self, value) -> None:
        v = str(value or "")
        if len(v) >= 8:
            self.values.add(v)
            if v.lower().startswith("bearer ") and len(v) > 15:
                self.values.add(v[7:].strip())

    def text(self, s: str) -> str:
        for v in sorted(self.values, key=len, reverse=True):
            if v in s:
                s = s.replace(v, "<redacted>")
        s = _GOOGLE_KEY_RE.sub("<redacted>", s)
        return _KEY_PARAM_RE.sub(r"\1<redacted>", s)

    def error(self, s: str) -> str:
        """An error's words: also no credential header's value, whatever it is called. Not applied to
        the agent's own text, where "Authorization: Bearer" in a document it writes is prose."""
        return _CRED_HEADER_RE.sub(lambda m: m.group(1) + m.group(2) + "<redacted>", self.text(s))

    def clean(self, obj):
        if isinstance(obj, str):
            return self.text(obj)
        if isinstance(obj, dict):
            return {k: self.clean(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [self.clean(v) for v in obj]
        return obj


_SCRUB = Scrub()


class Cancelled(BaseException):
    """The runner asked the turn to stop (SIGTERM). A BaseException so no `except Exception` on the
    way out swallows it."""


class Refused(Exception):
    """This turn cannot run as asked (a workspace over the cap, a session still running an earlier
    turn): the reason is the person's to read, and nothing was sent."""


class ApiError(Exception):
    """Google answered with an error: the HTTP status, Google's status or code word, its sentence."""

    def __init__(self, status: int, code: str, message: str, path: str = ""):
        super().__init__(f"{status} {code}: {message}")
        self.status, self.code, self.message, self.path = status, code, message, path


class NetError(Exception):
    """Nothing answered: the connection was refused, dropped, or timed out."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def plain_error(e: ApiError) -> str:
    """Google's refusal in words a person acts on, with Google's own sentence after it."""
    m = e.message or e.code or "no detail"
    if e.status in (401, 403):
        lead = "Google refused the key of the Google AI Studio connection"
    elif e.status == 429:
        lead = "Google's quota or rate limit for this key was reached"
    elif e.status == 404:
        lead = "Google does not have what was asked for"
    elif e.status == 400:
        lead = "Google refused the request"
    elif e.status >= 500:
        lead = "Google's service did not complete the request"
    elif e.status == 0:
        lead = "Google's answer could not be used"
    else:
        lead = f"Google answered {e.status}"
    return _SCRUB.error(f"{lead}: {m}")[:600]


# ── the wire ─────────────────────────────────────────────────────────────────────────────────────
def _segments(path: str) -> str:
    """A path inside an environment as URL path segments, each one quoted on its own."""
    return "/".join(urllib.parse.quote(s, safe="") for s in path.split("/") if s)


class Client:
    """The Interactions and Environments APIs through the relay: `base` is the relay's address,
    `token` its placeholder. Every method answers plain dicts and raises ApiError or NetError."""

    def __init__(self, base: str, token: str):
        self.base = base.rstrip("/")
        self.token = token
        _SCRUB.add(token)

    def _open(self, method: str, path: str, *, body=None, data=None, query: dict | None = None,
              ctype: str = "", timeout: float = CALL_TIMEOUT_S, accept: str = "application/json",
              length: int | None = None):
        url = self.base + path + (("?" + urllib.parse.urlencode(query)) if query else "")
        headers = {"x-goog-api-key": self.token, "Api-Revision": API_REVISION, "accept": accept}
        if body is not None:
            data = json.dumps(body).encode()
            ctype = "application/json"
        if ctype:
            headers["content-type"] = ctype
        if length is not None:
            headers["content-length"] = str(length)
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            return _OPENER.open(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                return e            # the caller decides about a redirect (downloads only)
            raise self._error(e.code, e.read(), path) from None
        except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
            raise NetError(_SCRUB.error(f"{type(e).__name__}: {e}")[:300]) from None

    @staticmethod
    def _error(status: int, raw: bytes, path: str) -> ApiError:
        try:
            doc = json.loads(raw or b"{}")
        except ValueError:
            doc = {}
        err = doc.get("error") if isinstance(doc, dict) and isinstance(doc.get("error"), dict) else {}
        code = str(err.get("status") or err.get("code") or "")
        msg = str(err.get("message") or (raw or b"")[:300].decode("utf-8", "replace") or "")
        return ApiError(int(status), _SCRUB.error(code)[:80], _SCRUB.error(msg)[:400], path)

    def call(self, method: str, path: str, body=None, query: dict | None = None) -> dict:
        resp = self._open(method, path, body=body, query=query)
        try:
            raw = resp.read()
        except (http.client.HTTPException, OSError) as e:
            raise NetError(f"the answer stopped mid-body: {type(e).__name__}") from None
        finally:
            resp.close()
        if getattr(resp, "status", 200) in (301, 302, 303, 307, 308):
            raise ApiError(int(resp.status), "redirect", "an unexpected redirect", path)
        try:
            doc = json.loads(raw) if raw.strip() else {}
        except ValueError:
            raise ApiError(0, "api_error", "an answer that is not JSON", path) from None
        return doc if isinstance(doc, dict) else {}

    # environments
    def environment_create(self) -> dict:
        return self.call("POST", "/v1beta/environments", {})

    def environment_get(self, eid: str) -> dict:
        return self.call("GET", f"/v1beta/environments/{_segments(eid)}")

    def environment_delete(self, eid: str) -> dict:
        return self.call("DELETE", f"/v1beta/environments/{_segments(eid)}")

    def files_list(self, eid: str, path: str) -> list[dict]:
        """Every entry under `path`, recursively, every page."""
        out: list[dict] = []
        token = ""
        for _ in range(LISTING_MAX_PAGES):
            q = {"recursive": "true", "page_size": "1000", **({"page_token": token} if token else {})}
            doc = self.call("GET", f"/v1beta/environments/{_segments(eid)}/files/{_segments(path)}", query=q)
            out += [f for f in (doc.get("files") or []) if isinstance(f, dict)]
            token = str(doc.get("next_page_token") or "")
            if not token:
                return out
        raise ApiError(0, "api_error", f"the file listing ran past {LISTING_MAX_PAGES} pages", path)

    def upload_archive(self, eid: str, path: str, archive: str) -> dict:
        """The archive, unpacked into `path` over what is there. A simple upload: `uploadType=media`
        (measured 2026-11-14: without it Google reads the body as a JSON request and answers 500,
        "Invalid JSON payload"). The answer lists every file written."""
        size = os.path.getsize(archive)
        with open(archive, "rb") as f:
            resp = self._open("PUT", f"/upload/v1beta/environments/{_segments(eid)}/files/{_segments(path)}",
                              data=f, query={"uploadType": "media", "extract": "true", "overwrite": "true"},
                              ctype="application/gzip", length=size, timeout=600.0)
        try:
            raw = resp.read()
        finally:
            resp.close()
        try:
            doc = json.loads(raw) if raw.strip() else {}
        except ValueError:
            doc = {}
        return doc if isinstance(doc, dict) else {}

    def download(self, eid: str, path: str, dest: pathlib.Path, cap: int) -> int:
        """The file's bytes written to `dest` as they arrive; their count. Over `cap` is refused
        mid-stream. A redirect is followed once, over https to Google's own hosts, without the
        placeholder."""
        resp = self._open("GET", f"/v1beta/environments/{_segments(eid)}/files/{_segments(path)}",
                          query={"alt": "media"}, accept="*/*", timeout=300.0)
        if getattr(resp, "status", 200) in (301, 302, 303, 307, 308) or getattr(resp, "code", 200) in (301, 302, 303, 307, 308):
            loc = str(resp.headers.get("location") or "")
            resp.close()
            u = urllib.parse.urlsplit(loc)
            host = (u.hostname or "").lower()
            if u.scheme != "https" or not host.endswith(_DOWNLOAD_HOSTS):
                raise ApiError(0, "redirect", "the file's download link is not one of Google's https addresses", path)
            try:
                resp = _OPENER.open(urllib.request.Request(loc, headers={"accept": "*/*"}), timeout=300.0)
            except urllib.error.HTTPError as e:
                raise ApiError(e.code, "download", "the storage host refused the download link", path) from None
            except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
                raise NetError(f"{type(e).__name__}") from None
        n = 0
        try:
            with open(dest, "wb") as out:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    n += len(chunk)
                    if n > cap:
                        raise ApiError(0, "too_large", f"over the {cap}-byte limit for one file", path)
                    out.write(chunk)
        except (http.client.HTTPException, TimeoutError) as e:
            raise NetError(f"the download stopped: {type(e).__name__}") from None
        finally:
            resp.close()
        return n

    # interactions
    def interaction_create(self, body: dict):
        """The open SSE stream of a new interaction (body["stream"] is true)."""
        return self._open("POST", "/v1beta/interactions", body=body, accept="text/event-stream",
                          timeout=STREAM_READ_TIMEOUT_S)

    def interaction_stream(self, iid: str, last_event_id: str):
        q = {"stream": "true", **({"last_event_id": last_event_id} if last_event_id else {})}
        return self._open("GET", f"/v1beta/interactions/{_segments(iid)}", query=q, accept="text/event-stream",
                          timeout=STREAM_READ_TIMEOUT_S)

    def interaction_get(self, iid: str) -> dict:
        return self.call("GET", f"/v1beta/interactions/{_segments(iid)}")

    def interaction_cancel(self, iid: str) -> dict:
        # `{id}/cancel`, the background guide's form; the reference's `{id}:cancel` answered 404
        # "Method not found." (measured 2026-11-14), and is tried only if the first is not found.
        try:
            return self.call("POST", f"/v1beta/interactions/{_segments(iid)}/cancel", {})
        except ApiError as e:
            if e.status != 404:
                raise
        return self.call("POST", f"/v1beta/interactions/{_segments(iid)}:cancel", {})

    def interaction_delete(self, iid: str) -> dict:
        return self.call("DELETE", f"/v1beta/interactions/{_segments(iid)}")


def sse_events(resp):
    """(event, data, id) per server-sent event, until the stream ends. A line is read up to
    SSE_LINE_MAX bytes (an inline image is the longest a stream carries), so a stream that never
    ends a line cannot fill memory: what is cut reads as an event that does not parse, and is skipped."""
    event, data, eid = "", [], ""
    while True:
        line = resp.readline(SSE_LINE_MAX)
        if not line:
            if data:
                yield event, "\n".join(data), eid
            return
        text = line.decode("utf-8", "replace").rstrip("\r\n")
        if not text:
            if data:
                yield event, "\n".join(data), eid
            event, data = "", []
            continue
        if text.startswith(":"):
            continue
        field, _, value = text.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if field == "event":
            event = value
        elif field == "data":
            data.append(value)
        elif field == "id":
            eid = value


# ── state ────────────────────────────────────────────────────────────────────────────────────────
def state_path(cwd: str) -> pathlib.Path:
    return pathlib.Path(cwd) / STATE_REL


def load_state(cwd: str) -> dict:
    p = state_path(cwd)
    try:
        if p.is_symlink():
            return {}
        doc = json.loads(p.read_text())
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(cwd: str, st: dict) -> None:
    p = state_path(cwd)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".state.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(st, indent=1, sort_keys=True))
    os.replace(tmp, p)


def _sha_file(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ── paths: what goes up, what may come back ──────────────────────────────────────────────────────
def excluded(rel: str, patterns: list[str]) -> bool:
    """Whether a workspace path falls under one of the checkpoint's exclusions, read the way its tar
    reads them: `./x` is that path from the workspace root and everything below it; a pattern
    without `./` (node_modules, .cache/pip) is those names at any depth. Or a directory never
    synced. The archive itself is made by tar with the same list; this answers only which paths the
    size cap counts, which changes are worth an upload, and which returned paths never land."""
    parts = rel.split("/")
    if parts[0] in NEVER_SYNCED:
        return True
    for raw in patterns or []:
        p = str(raw)
        anchored = p.startswith("./")
        want = [s for s in p.removeprefix("./").strip("/").split("/") if s]
        if not want:
            continue
        starts = [0] if anchored else range(0, len(parts) - len(want) + 1)
        if any(parts[i:i + len(want)] == want for i in starts):
            return True
    return False


def tar_command(job: dict, archive: str, folder: str, excludes: list[str]) -> list[str]:
    """The archive's command: the checkpoint's own tar and flags (the runner hands them over in the
    job: server._WORKSPACE_TAR), into `archive`, with each exclusion, from `folder`. In the shape
    server._workspace_tar_argv builds for the checkpoint, so the two are the same command."""
    argv = [str(a) for a in ((job.get("tar") or {}).get("argv") or ["tar", "-czf"])]
    return argv + [archive] + [f"--exclude={p}" for p in excludes] + ["-C", folder, "."]


def local_manifest(cwd: str, patterns: list[str], cap: int, links: list[str] | None = None) -> dict[str, dict]:
    """{relative path: {size, sha}} of the regular files the workspace would send. A link (or any
    other entry that is not a plain file or directory) is never followed, never listed, and named in
    `links`, which the archive then leaves out by name; the sizes are summed before any file is
    read, and over `cap` the turn is refused here, before anything is made or sent."""
    root = pathlib.Path(cwd)
    found: list[tuple[str, int]] = []
    odd = links if links is not None else []
    total = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = pathlib.Path(dirpath)
        rel_dir = here.relative_to(root).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir
        keep = []
        for d in dirnames:
            rel = f"{rel_dir}/{d}" if rel_dir else d
            if excluded(rel, patterns):
                continue
            if (here / d).is_symlink():
                odd.append(rel)
                continue
            keep.append(d)
        dirnames[:] = keep
        for name in filenames:
            rel = f"{rel_dir}/{name}" if rel_dir else name
            if excluded(rel, patterns):
                continue
            try:
                st = os.lstat(here / name)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode):
                odd.append(rel)         # a link, a socket, a device: never sent
                continue
            total += st.st_size
            found.append((rel, st.st_size))
    if total > cap:
        raise Refused(f"the workspace holds {total} bytes of files, over the {cap}-byte limit for sending "
                      "a task's files to Google's service; remove large files from the task first")
    out: dict[str, dict] = {}
    for rel, size in found:
        try:
            out[rel] = {"size": size, "sha": _sha_file(root / rel)}
        except OSError:
            continue
    return out


def safe_rel(path: str) -> tuple[str, str]:
    """(the workspace-relative path a file from Google may land at, "") or ("", why not).

    The path is Google's (and in the end the agent's), so it is input: only a plain relative path
    under the remote workspace root lands. No absolute path, no `..`, no empty or `.` segment, no
    backslash, no control character, nothing into .harness or .git."""
    p = str(path or "")
    if "\0" in p or "\\" in p or any(ord(c) < 32 for c in p):
        return "", f"{p!r}: carries a control character or a backslash"
    if p.startswith("/"):
        return "", f"{p!r}: an absolute path"
    if not p.startswith(REMOTE_ROOT + "/"):
        return "", f"{p!r}: outside the task's folder"
    rel = p[len(REMOTE_ROOT) + 1:]
    parts = rel.split("/")
    if not rel or any(s in ("", ".", "..") for s in parts):
        return "", f"{p!r}: not a plain relative path"
    if parts[0] in NEVER_SYNCED:
        return "", f"{p!r}: inside {parts[0]}, which a task's files never reach"
    if len(rel.encode("utf-8")) > 4000 or any(len(s.encode("utf-8")) > 255 for s in parts):
        return "", f"{p!r}: a name too long for this filesystem"
    return rel, ""


def land(cwd: str, rel: str, src: pathlib.Path) -> None:
    """Move a downloaded file into the workspace at `rel` (already safe_rel's). Every directory on the
    way is checked: one that is a symlink (or a file) refuses the landing, and a missing one is made.
    A symlink at the destination is never written through, and a directory there is never replaced."""
    root = pathlib.Path(cwd)
    parts = rel.split("/")
    cur = root
    for seg in parts[:-1]:
        cur = cur / seg
        try:
            st = os.lstat(cur)
        except FileNotFoundError:
            os.mkdir(cur, 0o755)
            continue
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
            raise OSError(f"{rel}: {cur.relative_to(root).as_posix()} is not a plain directory")
    dest = cur / parts[-1]
    try:
        st = os.lstat(dest)
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
            raise OSError(f"{rel}: something other than a plain file is at this path")
    except FileNotFoundError:
        pass
    tmp = cur / f".{parts[-1][:200]}.{uuid.uuid4().hex}.landing"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
    try:
        with os.fdopen(fd, "wb") as out, open(src, "rb") as f:
            while True:
                chunk = f.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
        os.replace(tmp, dest)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ── tools and MCP servers ────────────────────────────────────────────────────────────────────────
def _host_is_public(host: str) -> bool:
    h = (host or "").strip("[]").lower()
    if not h or h == "localhost" or h.endswith((".localhost", ".local", ".internal")):
        return False
    if re.fullmatch(r"[0-9.]+", h) or ":" in h:
        import ipaddress  # noqa: PLC0415
        try:
            ip = ipaddress.ip_address(h)
        except ValueError:
            return False
        return ip.is_global
    return "." in h


def mcp_tools(servers: list[dict], withheld: list[dict]) -> tuple[list[dict], list[dict]]:
    """(the `mcp_server` tools for Google, the servers left out with why). The gateway has already
    left out what may not go to Google (a stored secret, a server it hosts itself) and said why in
    `withheld`; what reaches this point is checked again here: only a streamable HTTP server at a
    public https address goes, since Google's sandbox dials it and a process or a loopback address
    on this box is out of its reach. Names are made what the API takes, ^[a-z0-9_-]+$."""
    out: list[dict] = []
    dropped = [{"name": str(w.get("name") or "mcp"), "reason": str(w.get("reason") or "not sent to Google")}
               for w in withheld or [] if isinstance(w, dict)]
    seen: set[str] = set()
    for i, s in enumerate(servers or []):
        if not isinstance(s, dict):
            continue
        raw_name = str(s.get("name") or s.get("id") or f"mcp{i}")
        url = str(s.get("url") or "").strip()
        transport = str(s.get("transport") or "http").lower()
        if not url:
            dropped.append({"name": raw_name, "reason": "a process on this box (stdio), which Google's sandbox cannot run"})
            continue
        if transport not in ("http", "streamable-http", "streamable_http", "streamablehttp"):
            dropped.append({"name": raw_name, "reason": f"{transport} transport: Google's sandbox takes streamable HTTP only"})
            continue
        u = urllib.parse.urlsplit(url)
        if u.scheme != "https" or not _host_is_public(u.hostname or "") or u.username or u.password:
            dropped.append({"name": raw_name, "reason": "not a public https address, which Google's sandbox needs to reach it"})
            continue
        name = _MCP_NAME_RE.sub("-", raw_name.lower()).strip("-")[:63] or f"mcp{i}"
        if name in seen:
            name = f"{name}-{i}"
        seen.add(name)
        headers: dict[str, str] = {}
        auth = str(s.get("auth") or "").strip()
        if auth:
            headers["Authorization"] = auth if " " in auth else f"Bearer {auth}"
        for k, v in (s.get("headers") or {}).items() if isinstance(s.get("headers"), dict) else ():
            if v not in (None, ""):
                headers[str(k)] = str(v)
        for v in headers.values():
            _SCRUB.add(v)
        tool: dict = {"type": "mcp_server", "name": name, "url": url}
        if headers:
            tool["headers"] = headers
        out.append(tool)
    return out, dropped


def tools_config(disabled: list[str], mcp: list[dict]) -> list[dict]:
    """The built-ins that are on, by their type names, then the MCP servers. Always the explicit
    list. A list with every built-in left out and no server would be empty, and Google reads an
    empty list as the default set (measured 2026-11-14: `tools: []` and the agent searched Google),
    so that turn is refused here rather than run with the switches ignored; a non-empty list is
    honoured (measured: with url_context alone the agent had no shell and no search)."""
    off = {str(t) for t in (disabled or [])}
    tools = [{"type": t} for t in TOOLS if t not in off] + list(mcp)
    if not tools:
        raise Refused("every built-in tool of this agent is switched off and it has no MCP server, and Google's "
                      "agent reads an empty tool list as all of its tools on; switch one on")
    return tools


def system_instruction(job: dict) -> str:
    base = str(job.get("agent_doc") or "").strip()
    block = "\n".join([
        "## Your workspace", "",
        f"The task's files are in /{REMOTE_ROOT}, and it is the only place the user can see files. Work "
        f"there: save every deliverable (documents, decks, code, exports) under /{REMOTE_ROOT}. A file "
        f"written anywhere else in this sandbox never reaches the user. Scratch files go in "
        f"/{REMOTE_ROOT}/tmp, which is never returned."])
    return (base + "\n\n" + block) if base else block


# ── the turn ─────────────────────────────────────────────────────────────────────────────────────
class Turn:
    def __init__(self, job: dict):
        self.job = job
        self.cwd = str(job.get("cwd") or os.getcwd())
        self.api = Client(str(job.get("base_url") or ""), str(job.get("api_key") or ""))
        self.st = load_state(self.cwd)
        self.model = str(job.get("model") or DEFAULT_MODEL)
        self.disabled = {str(t) for t in (job.get("tools_disabled") or [])}
        self.caps = {"upload": int(job.get("upload_max_bytes") or UPLOAD_MAX_BYTES),
                     "file": int(job.get("file_max_bytes") or FILE_MAX_BYTES),
                     "total": int(job.get("return_max_bytes") or RETURN_MAX_BYTES),
                     "files": int(job.get("return_max_files") or RETURN_MAX_FILES)}
        self.max_total_tokens = int(job.get("max_total_tokens") or 0)
        self.excludes = [str(p) for p in (job.get("exclude") or [])]
        self.links: list[str] = []              # workspace entries that are not plain files: never sent
        self.notes: list[str] = []
        self.env_id = ""
        self.interaction_id = ""
        self.status = ""
        self.usage_doc: dict | None = None
        self.error: str = ""
        self.last_event_id = ""
        self.steps: dict[int, dict] = {}
        self.stopped: set[int] = set()
        self.texts: list[str] = []              # each model_output step's text, in order
        self.violations: list[str] = []
        self.finished = False                   # the interaction reached its end
        self.landed: list[str] = []
        self.failures: list[str] = []
        self.images = 0

    # ── the environment ──
    def find_environment(self, resume: str) -> tuple[str, str, bool]:
        """(environment id, the interaction to chain from, whether the named session was lost)."""
        if not resume:
            return "", "", False
        if resume != str(self.st.get("environment_id") or ""):
            return "", "", True
        try:
            doc = self.api.environment_get(resume)
        except ApiError as e:
            if e.status == 404:
                return "", "", True
            raise
        if str(doc.get("status") or "").lower() == "expired":
            return "", "", True
        prev = str(self.st.get("last_interaction_id") or "")
        if prev:
            try:
                last = self.api.interaction_get(prev)
            except ApiError as e:
                if e.status != 404:
                    raise
                self.notes.append("Google no longer keeps the earlier messages of this conversation; it "
                                  "continues in the same files without them")
                _emit("notice", {"text": self.notes[-1]})
                return resume, "", True
            status = str(last.get("status") or "")
            if status == "in_progress":
                raise Refused("Google is still working on an earlier message of this conversation; stop it or "
                              "wait for it to finish")
            if status in ("requires_action", "requires_continuation"):
                prev = ""           # nothing of ours answers it: the next message starts a new chain here
        return resume, prev, False

    def create_environment(self) -> str:
        doc = self.api.environment_create()
        eid = str(doc.get("id") or "").removeprefix("environments/")
        if not eid:
            raise ApiError(0, "api_error", "environment create returned no id", "/v1beta/environments")
        self.st["environment_id"] = eid
        self.st.setdefault("environments", [])
        if eid not in self.st["environments"]:
            self.st["environments"].append(eid)
        for k in ("synced", "remote", "skills", "last_interaction_id"):
            self.st.pop(k, None)
        save_state(self.cwd, self.st)
        return eid

    # ── files up ──
    def sync_up(self, manifest: dict[str, dict]) -> list[str]:
        """Send the workspace when it changed since the last sync (and on a new environment's first
        turn, so /workspace exists); → the files new this turn, named in the message. The archive is
        the checkpoint's tar, excluding what the checkpoint excludes."""
        first = not isinstance(self.st.get("synced"), dict)
        synced = self.st.get("synced") if not first else {}
        changed = sorted(r for r, m in manifest.items() if (synced.get(r) or {}).get("sha") != m["sha"])
        if changed or first:
            self._upload_tree(self.cwd, REMOTE_ROOT, self.excludes + [f"./{d}" for d in NEVER_SYNCED]
                              + [f"./{r}" for r in self.links])
        self.st["synced"] = manifest
        if changed or first or not isinstance(self.st.get("remote"), dict):
            self.st["remote"] = self._remote_manifest()
        save_state(self.cwd, self.st)
        return [r for r in changed if r not in synced]

    def _listing(self) -> list[dict]:
        """The remote workspace's files; none when the folder is not there (nothing was sent yet)."""
        try:
            return self.api.files_list(self.env_id, REMOTE_ROOT)
        except ApiError as e:
            if e.status == 404:
                return []
            raise

    def _upload_tree(self, folder: str, target: str, excludes: list[str]) -> None:
        fd, archive = tempfile.mkstemp(suffix=".tgz")
        os.close(fd)
        try:
            cmd = tar_command(self.job, archive, folder, excludes)
            # tar starts from nothing of this process's environment: not the job, not the placeholder
            env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8", "HOME": "/nonexistent"}
            proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=env, timeout=600)
            if proc.returncode not in (0, 1):     # 1: a file changed or could not be read, as the checkpoint allows
                raise OSError(f"the archive of {target} could not be made: {proc.stderr.decode(errors='replace')[:200]}")
            if os.path.getsize(archive) > self.caps["upload"]:
                raise Refused(f"the archive of the task's files is over the {self.caps['upload']}-byte limit for "
                              "sending them to Google's service")
            self.api.upload_archive(self.env_id, target, archive)
        finally:
            try:
                os.unlink(archive)
            except OSError:
                pass

    def sync_skills(self) -> None:
        """Each skill folder the runner staged, into .agents/skills/<name>/ in the sandbox, when its
        bytes changed. A skill switched off since is replaced with one that says so: the files API
        deletes nothing, and a stale skill must not read as on."""
        have: dict = self.st.setdefault("skills", {})
        now: set[str] = set()
        for s in self.job.get("skills") or []:
            folder = pathlib.Path(str((s or {}).get("dir") or ""))
            name = folder.name
            if not _SKILL_DIR_RE.match(name) or not folder.is_dir() or folder.is_symlink():
                self.notes.append(f"skill not sent: {name!r}")
                continue
            now.add(name)
            digest = hashlib.sha256()
            for p in sorted(folder.rglob("*")):
                if p.is_file() and not p.is_symlink():
                    digest.update(p.relative_to(folder).as_posix().encode() + b"\0" + _sha_file(p).encode())
            sha = digest.hexdigest()
            if have.get(name) == sha:
                continue
            self._upload_tree(str(folder), f"{SKILLS_ROOT}/{name}", [])
            have[name] = sha
            save_state(self.cwd, self.st)
        for name in [n for n in list(have) if n not in now]:
            off = tempfile.mkdtemp()
            try:
                pathlib.Path(off, "SKILL.md").write_text(
                    f"---\nname: {name}\ndescription: Switched off for this agent. Do not use it.\n---\n\n"
                    "This skill was switched off. Do not use it or its files.\n")
                self._upload_tree(off, f"{SKILLS_ROOT}/{name}", [])
            finally:
                for f in pathlib.Path(off).iterdir():
                    f.unlink()
                os.rmdir(off)
            del have[name]
            save_state(self.cwd, self.st)

    def _remote_manifest(self) -> dict[str, list]:
        """{relative path: [size, modified]} of the files under the remote workspace now."""
        out: dict[str, list] = {}
        for f in self._listing():
            if str(f.get("type") or "").lower() != "file":
                continue
            rel, why = safe_rel(str(f.get("path") or ""))
            if not why:
                out[rel] = [str(f.get("size_bytes") or ""), str(f.get("modified") or "")]
        return out

    # ── files back ──
    def sync_down(self) -> None:
        """What the agent added, changed or removed under the remote workspace, brought back. A file
        that cannot land is named in the turn's reason; one the checkpoint would not keep (tmp/, a
        credential file name it excludes) is left where it is."""
        before = self.st.get("remote") if isinstance(self.st.get("remote"), dict) else {}
        listing = self._listing()
        now: dict[str, list] = {}
        listed: set[str] = set()
        todo: list[tuple[str, int]] = []
        for f in listing:
            if str(f.get("type") or "").lower() != "file":
                continue
            rel, why = safe_rel(str(f.get("path") or ""))
            if why:
                self.failures.append(f"not brought back: {why}")
                continue
            listed.add(rel)
            if excluded(rel, self.excludes):
                continue
            meta = [str(f.get("size_bytes") or ""), str(f.get("modified") or "")]
            now[rel] = meta
            if before.get(rel) != meta:
                try:
                    size = int(meta[0] or 0)
                except ValueError:
                    size = 0
                todo.append((rel, size))
        synced = self.st.get("synced") if isinstance(self.st.get("synced"), dict) else {}
        if len(todo) > self.caps["files"]:
            self.failures.append(f"{len(todo)} changed files, over the {self.caps['files']}-file limit for one turn; "
                                 f"{len(todo) - self.caps['files']} not brought back")
            todo = todo[:self.caps["files"]]
        total = 0
        part_dir = pathlib.Path(self.cwd) / ".harness" / "antigravity"
        part_dir.mkdir(parents=True, exist_ok=True)
        for rel, size in todo:
            if size > self.caps["file"]:
                self.failures.append(f"{rel}: {size} bytes, over the {self.caps['file']}-byte limit for one file")
                now.pop(rel, None)
                continue
            if total + size > self.caps["total"]:
                self.failures.append(f"{rel}: over the {self.caps['total']}-byte limit for one turn")
                now.pop(rel, None)
                continue
            part = part_dir / f"download-{uuid.uuid4().hex}.part"
            try:
                got = self.api.download(self.env_id, f"{REMOTE_ROOT}/{rel}", part, self.caps["file"])
                total += got
                land(self.cwd, rel, part)
                synced[rel] = {"size": got, "sha": _sha_file(pathlib.Path(self.cwd) / rel)}
                self.landed.append(rel)
            except (ApiError, NetError, OSError) as e:
                self.failures.append(f"{rel}: {e}"[:300])
                now.pop(rel, None)          # asked for again next turn
            finally:
                try:
                    part.unlink()
                except OSError:
                    pass
        # What the agent removed: the copy here goes only when it is still the copy that was synced,
        # so a file changed on this side since is never lost.
        for rel in [r for r in before if r not in listed and not excluded(r, self.excludes)]:
            p = pathlib.Path(self.cwd) / rel
            try:
                if p.is_file() and not p.is_symlink() and (synced.get(rel) or {}).get("sha") == _sha_file(p):
                    p.unlink()
                    self.landed.append(rel)
            except OSError:
                pass
            synced.pop(rel, None)
        self.st["remote"] = now
        self.st["synced"] = synced
        save_state(self.cwd, self.st)
        if self.landed:
            _emit("files", {"paths": self.landed})

    # ── the message ──
    def input_parts(self, new_files: list[str]) -> list[dict]:
        text = str(self.job.get("prompt") or "")
        attached = [str(r) for r in (self.job.get("input_files") or [])]
        named = sorted(set(attached) | set(new_files))
        if named:
            text = (f"[Files in /{REMOTE_ROOT} new with this message: " + ", ".join(named[:50])
                    + (f" and {len(named) - 50} more" if len(named) > 50 else "") + "]\n\n" + text)
        parts: list[dict] = [{"type": "text", "text": text}]
        budget = IMAGE_MAX_BYTES * IMAGES_MAX
        for rel in attached:
            mime = (mimetypes.guess_type(rel)[0] or "").lower()
            p = pathlib.Path(self.cwd) / rel
            if mime not in IMAGE_TYPES or p.is_symlink() or not p.is_file():
                continue
            size = p.stat().st_size
            if self.images >= IMAGES_MAX or size > IMAGE_MAX_BYTES or size > budget:
                self.notes.append(f"{rel}: sent as a file only (too large or too many to show the model inline)")
                continue
            parts.append({"type": "image", "mime_type": mime, "data": base64.b64encode(p.read_bytes()).decode()})
            budget -= size
            self.images += 1
        return parts

    def body(self, prev: str, parts: list[dict], tools: list[dict]) -> dict:
        cfg: dict = {"type": "antigravity", "model": self.model}
        if self.max_total_tokens > 0:
            cfg["max_total_tokens"] = self.max_total_tokens
        b = {"agent": AGENT, "input": parts, "environment": self.env_id,
             "system_instruction": system_instruction(self.job), "tools": tools, "agent_config": cfg,
             "stream": True, "background": True, "store": True}
        if prev:
            b["previous_interaction_id"] = prev
        return b

    # ── the stream ──
    def handle(self, event: str, data: str) -> bool:
        """One server-sent event; True when the interaction is over."""
        if data.strip() == "[DONE]":
            return False
        try:
            doc = json.loads(data)
        except ValueError:
            return False
        if not isinstance(doc, dict):
            return False
        kind = str(doc.get("event_type") or event or "")
        if doc.get("event_id"):
            self.last_event_id = str(doc["event_id"])
        if kind == "interaction.created":
            it = doc.get("interaction") if isinstance(doc.get("interaction"), dict) else {}
            self._saw_interaction(it)
            return False
        if kind == "interaction.status_update":
            self.status = str(doc.get("status") or self.status)
            return False
        if kind == "step.start":
            idx = int(doc.get("index") or 0)
            step = doc.get("step") if isinstance(doc.get("step"), dict) else {}
            if idx in self.stopped:
                return False                    # a replayed step, already handled
            if idx not in self.steps:
                self.steps[idx] = {**step, "_text": "", "_args": "", "_seen": 0}
            else:
                self.steps[idx]["_seen"] = 0    # a reconnect replays this step from its start
            return False
        if kind == "step.delta":
            idx = int(doc.get("index") or 0)
            if idx in self.stopped:
                return False
            step = self.steps.setdefault(idx, {"type": "", "_text": "", "_args": "", "_seen": 0})
            self._delta(step, doc.get("delta") if isinstance(doc.get("delta"), dict) else {})
            return False
        if kind == "step.stop":
            idx = int(doc.get("index") or 0)
            if isinstance(doc.get("usage"), dict):
                self.usage_doc = doc["usage"]
            if idx not in self.stopped:
                self.stopped.add(idx)
                self._finish(self.steps.get(idx) or {})
            return False
        if kind == "interaction.completed":
            it = doc.get("interaction") if isinstance(doc.get("interaction"), dict) else {}
            self._saw_interaction(it)
            self.status = str(it.get("status") or self.status or "completed")
            if isinstance(it.get("usage"), dict):
                self.usage_doc = it["usage"]
            return True
        if kind == "error":
            err = doc.get("error") if isinstance(doc.get("error"), dict) else {}
            self.error = _SCRUB.error(f"{err.get('code') or 'error'}: {err.get('message') or 'Google reported an error'}")[:500]
            _emit("notice", {"text": f"Google's stream reported {self.error}"})
            return False
        return False                            # an event this driver does not know: skipped

    def _saw_interaction(self, it: dict) -> None:
        iid = str(it.get("id") or "")
        if iid and iid != self.interaction_id:
            self.interaction_id = iid
            self.st.setdefault("interactions", [])
            if iid not in self.st["interactions"]:
                self.st["interactions"].append(iid)
            self.st["pending_interaction_id"] = iid
            save_state(self.cwd, self.st)
            _emit("interaction", {"interaction_id": iid, "environment_id": self.env_id})
        env = str(it.get("environment_id") or "")
        if env and env != self.env_id:
            self.notes.append(f"Google ran this message in environment {env}")

    def _delta(self, step: dict, d: dict) -> None:
        t = str(d.get("type") or "")
        stype = str(step.get("type") or "")
        if t == "text":
            txt = str(d.get("text") or "")
            seen = step["_seen"]
            step["_seen"] = seen + len(txt)
            if seen + len(txt) <= len(step["_text"]):
                return                          # replayed after a reconnect: already written
            new = txt[max(0, len(step["_text"]) - seen):]
            step["_text"] += new
            if new:
                _emit("text", {"text": new})
            return
        if t == "thought_summary":
            c = d.get("content") if isinstance(d.get("content"), dict) else {}
            if c.get("text"):
                _emit("thinking", {"text": str(c["text"])})
            return
        if t == "arguments_delta":
            step["_args"] += str(d.get("arguments") or "")
            return
        if t == "image" and stype == "model_output" and d.get("data"):
            self._inline_image(d)
            return
        if t.endswith("_call") and isinstance(d.get("arguments"), dict):
            step["arguments"] = d["arguments"]
            return
        if t.endswith("_result"):
            if "result" in d:
                step["result"] = d["result"]
            if "is_error" in d:
                step["is_error"] = bool(d["is_error"])
            return

    def _finish(self, step: dict) -> None:
        stype = str(step.get("type") or "")
        for tool, kinds in TOOL_STEPS.items():
            if stype in kinds and tool in self.disabled and tool not in self.violations:
                self.violations.append(tool)
                _emit("notice", {"text": f"Google ran {tool} although it is switched off for this agent"})
        if stype == "model_output":
            text = step.get("_text") or "".join(str(c.get("text") or "") for c in step.get("content") or []
                                               if isinstance(c, dict) and c.get("type") == "text")
            if text and not step.get("_text"):
                _emit("text", {"text": text})
            if text:
                self.texts.append(text)
            return
        if stype == "function_call" or stype.endswith("_call"):
            args = step.get("arguments") if isinstance(step.get("arguments"), dict) else {}
            if not args and step.get("_args"):
                try:
                    parsed = json.loads(step["_args"])
                    args = parsed if isinstance(parsed, dict) else {"arguments": parsed}
                except ValueError:
                    args = {"arguments": step["_args"]}
            name = str(step.get("name") or stype.removesuffix("_call") or "tool")
            if stype == "mcp_server_tool_call" and step.get("server_name"):
                name = f"mcp__{step['server_name']}__{step.get('name') or 'tool'}"
            _emit("tool_use", {"id": str(step.get("id") or ""), "name": name, "input": args})
            return
        if stype.endswith("_result"):
            res = step.get("result")
            if isinstance(res, list):
                text = "\n".join(str(c.get("text") or "") if isinstance(c, dict) else str(c) for c in res)
            elif isinstance(res, (dict, int, float, bool)):
                text = json.dumps(res)[:20000]
            else:
                text = str(res or "")
            _emit("tool_result", {"tool_use_id": str(step.get("call_id") or ""), "text": text[:20000],
                                  "is_error": bool(step.get("is_error"))})

    def _inline_image(self, d: dict) -> None:
        """An image the agent answered with inline lands as a file of the workspace's root, under a
        name this driver makes, never one from the stream."""
        ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}.get(
            str(d.get("mime_type") or "").lower(), "")
        if not ext:
            return
        try:
            raw = base64.b64decode(str(d["data"]), validate=False)
        except (ValueError, TypeError):
            return
        if len(raw) > self.caps["file"]:
            self.failures.append(f"an inline image of {len(raw)} bytes, over the limit for one file")
            return
        part = pathlib.Path(self.cwd) / ".harness" / "antigravity" / f"image-{uuid.uuid4().hex}.part"
        part.parent.mkdir(parents=True, exist_ok=True)
        part.write_bytes(raw)
        n = 1
        while (pathlib.Path(self.cwd) / f"image-{n}{ext}").exists() or (pathlib.Path(self.cwd) / f"image-{n}{ext}").is_symlink():
            n += 1
        try:
            land(self.cwd, f"image-{n}{ext}", part)
            self.landed.append(f"image-{n}{ext}")
        except OSError as e:
            self.failures.append(f"an inline image could not be written: {e}"[:300])
        finally:
            try:
                part.unlink()
            except OSError:
                pass

    def run_interaction(self, body: dict) -> None:
        """Create the interaction and read its stream to the end. On a drop, the interaction's stream
        is read again (GET ?stream=true): Google sends no event ids (measured 2026-11-14: no `id:`
        line, no `event_id` field), so the stream is replayed from its start, and a step already
        handled is skipped and a step's text already written is not written again. When the stream
        cannot be had again, the interaction is polled. The message is never sent twice: a create
        whose answer was lost before the interaction's id arrived fails the turn in words (Google
        has no list of interactions to find it in), rather than run again."""
        resp = None
        for _ in range(3):
            try:
                resp = self.api.interaction_create(body)
                break
            except ApiError as e:
                said = e.message.lower()
                if e.status in (400, 404) and body.get("previous_interaction_id") and "previous" in said:
                    # nothing was created: the chain's head is gone (a free-tier project keeps an
                    # interaction for a day), and the message goes on in the same files without it
                    self.notes.append("Google no longer continues the earlier messages; this message starts "
                                      "afresh in the same files")
                    _emit("notice", {"text": self.notes[-1]})
                    body = {k: v for k, v in body.items() if k != "previous_interaction_id"}
                elif e.status == 400 and body.get("background") and "background" in said:
                    body = {k: v for k, v in body.items() if k != "background"}
                elif e.status == 404 and "not found" in said:
                    # measured 2026-11-14: an agent_config.model the agent does not take is a 404,
                    # "Requested entity was not found."
                    raise Refused(f"Google's Antigravity agent did not take the model {self.model!r} "
                                  f"({e.message or 'not found'})") from None
                else:
                    raise
        if resp is None:
            raise ApiError(0, "api_error", "the interaction could not be started", "/v1beta/interactions")
        attempts = 0
        while True:
            done = False
            try:
                for event, data, eid in sse_events(resp):
                    if eid:
                        self.last_event_id = eid
                    if self.handle(event, data):
                        done = True
                        break
            except (TimeoutError, OSError, http.client.HTTPException) as e:
                _emit("notice", {"text": f"the event stream dropped ({type(e).__name__}); resuming"})
            finally:
                try:
                    resp.close()
                except Exception:  # noqa: BLE001
                    pass
            if done:
                return
            if not self.interaction_id:
                raise ApiError(0, "stream", self.error or "the stream ended before Google named the interaction",
                               "/v1beta/interactions")
            # The stream ended without the interaction's end: where it stands decides.
            doc = self.api.interaction_get(self.interaction_id)
            status = str(doc.get("status") or "")
            if status and status != "in_progress":
                self._from_document(doc)
                return
            attempts += 1
            if attempts > STREAM_RECONNECTS:
                self._poll()
                return
            time.sleep(min(1.0 * attempts, 10.0))
            try:
                resp = self.api.interaction_stream(self.interaction_id, self.last_event_id)
            except (ApiError, NetError):
                self._poll()
                return

    def _poll(self) -> None:
        while True:
            doc = self.api.interaction_get(self.interaction_id)
            if str(doc.get("status") or "") not in ("", "in_progress"):
                self._from_document(doc)
                return
            time.sleep(POLL_S)

    def _from_document(self, doc: dict) -> None:
        """The end of an interaction read from its document rather than its stream: its status and
        usage, and the steps the stream did not deliver."""
        self.status = str(doc.get("status") or self.status)
        if isinstance(doc.get("usage"), dict):
            self.usage_doc = doc["usage"]
        steps = [s for s in (doc.get("steps") or []) if isinstance(s, dict)]
        # the GET timeline opens with the message's own user_input step; what follows it is this turn's
        last_input = max((i for i, s in enumerate(steps) if s.get("type") == "user_input"), default=-1)
        mine = steps[last_input + 1:]
        # an answer the stream had begun: the document's copy of it continues from what was written
        partial = "".join(st.get("_text") or "" for i, st in sorted(self.steps.items())
                          if i not in self.stopped and st.get("type") == "model_output")
        if not self.stopped:
            todo = mine                 # nothing finished over the stream: the document is the turn
        elif not self.texts:
            # the stream carried the work and lost the answer: the last model_output is the answer
            todo = [s for s in reversed(mine) if s.get("type") == "model_output"][:1]
        else:
            todo = []
        for s in todo:
            if s.get("type") == "model_output" and partial:
                full = "".join(str(c.get("text") or "") for c in s.get("content") or []
                               if isinstance(c, dict) and c.get("type") == "text")
                if full.startswith(partial):
                    if full[len(partial):]:
                        _emit("text", {"text": full[len(partial):]})
                    self.texts.append(full)
                    partial = ""
                    continue
            self._finish({**s, "_text": "", "_args": ""})
        err = doc.get("error") if isinstance(doc.get("error"), dict) else None
        if err and not self.error:
            self.error = _SCRUB.text(f"{err.get('code') or err.get('status') or 'error'}: {err.get('message') or ''}")[:500]

    def cancel_remote(self) -> str:
        iid = self.interaction_id or str(self.st.get("pending_interaction_id") or "")
        if not iid:
            return "stopped before Google started the interaction"
        if self.finished:
            return f"stopped while bringing the agent's files back; Google's interaction {iid} had already ended"
        try:
            self.api.interaction_cancel(iid)
            return f"cancel accepted by Google for interaction {iid}"
        except Exception as e:  # noqa: BLE001
            return _SCRUB.error(f"cancel failed ({str(e)[:200]}); Google's interaction {iid} may still be running")

    # ── main ──
    def run(self) -> int:
        resume = str(self.job.get("resume_session_id") or "")
        eid, prev, lost = self.find_environment(resume)
        if lost and not eid:
            _emit("resume_lost", {"requested_session_id": resume})
        elif lost:
            _emit("resume_lost", {"requested_session_id": resume, "files_kept": True})
        _emit("__hr_init", {"session_id": eid})
        servers, dropped = mcp_tools(self.job.get("mcp_servers") or [], self.job.get("mcp_withheld") or [])
        if dropped:
            # left out on purpose, each with why: the reply's note says so, not "could not be reached"
            _emit("mcp_unavailable", {"servers": [{**d, "withheld": True} for d in dropped]})
        tools = tools_config(list(self.disabled), servers)        # refused here, before anything is made
        # the workspace's size is checked before anything is made at Google
        manifest = local_manifest(self.cwd, self.excludes, self.caps["upload"], self.links)
        if not eid:
            eid = self.create_environment()
        self.env_id = eid
        _emit("session", {"session_id": eid, "environment_id": eid})
        new_files = self.sync_up(manifest)
        self.sync_skills()
        body = self.body(prev, self.input_parts(new_files), tools)
        self.run_interaction(body)
        self.finished = True
        if self.interaction_id:
            self.st["last_interaction_id"] = self.interaction_id
            self.st.pop("pending_interaction_id", None)
            save_state(self.cwd, self.st)
        try:
            self.sync_down()
        except (ApiError, NetError) as e:
            self.failures.append(f"the agent's files could not be listed: {e}"[:300])
        status = self.status or "failed"
        if status == "completed":
            if self.violations:
                self.result("incomplete", "Google ran " + ", ".join(self.violations)
                            + " although switched off for this agent")
            elif self.failures:
                self.result("incomplete", "files not brought back from Google's sandbox: " + "; ".join(self.failures))
            else:
                self.result("completed", "")
        elif status == "incomplete":
            why = (f"the agent reached its token budget ({self.max_total_tokens} tokens, max_total_tokens); its work "
                   "so far is kept, and the next message continues it" if self.max_total_tokens else
                   "Google ended the interaction incomplete")
            self.result("incomplete", why + ("; files not brought back: " + "; ".join(self.failures) if self.failures else ""))
        elif status in ("requires_action", "requires_continuation"):
            self.result("incomplete", f"the agent stopped for an action this base does not answer ({status})")
        elif status == "cancelled":
            self.result("cancelled", "the interaction was cancelled at Google")
        else:
            self.result("failed", self.error or f"Google ended the interaction {status}")
        return 0

    def result(self, status: str, reason: str) -> None:
        _emit("__hr_result", {"status": status, "reason": reason,
                              "final": self.texts[-1] if self.texts else "",
                              "session_id": self.env_id or str(self.st.get("environment_id") or ""),
                              "interaction_id": self.interaction_id,
                              "usage": usage_of(self.usage_doc), "notes": self.notes, "files": self.landed})


def usage_of(u: dict | None) -> dict:
    """Google's usage in the runner's contract. `total_input_tokens` is the whole prompt with its cached
    part (`total_cached_tokens`), so the fresh input is the difference; the tool-use prompt tokens are
    prompt-side and counted with the input. Output is the generated tokens AND the thinking, with the
    thinking also reported as reasoning_tokens, a subset of it (never more than the output)."""
    if not isinstance(u, dict) or not u:
        return {}

    def n(k: str) -> int:
        try:
            return max(int(u.get(k) or 0), 0)
        except (TypeError, ValueError):
            return 0

    cached = n("total_cached_tokens")
    thought = n("total_thought_tokens")
    return {"input_tokens": max(n("total_input_tokens") + n("total_tool_use_tokens") - cached, 0),
            "output_tokens": n("total_output_tokens") + thought,
            "cache_read_tokens": cached, "reasoning_tokens": thought}


# ── purge ────────────────────────────────────────────────────────────────────────────────────────
def purge(job: dict) -> int:
    """Delete at Google everything the session's turns created there: every interaction (its stored
    conversation), then every environment (the sandbox and its files). Each failure is reported with
    its id, never swallowed. Exit 0 when nothing failed."""
    cwd = str(job.get("cwd") or os.getcwd())
    st = load_state(cwd)
    api = Client(str(job.get("base_url") or ""), str(job.get("api_key") or ""))
    done: list[str] = []
    failed: list[dict] = []

    def attempt(label: str, fn, *a) -> None:
        try:
            fn(*a)
            done.append(label)
        except ApiError as e:
            if e.status == 404:
                done.append(label + " (already gone)")
            else:
                failed.append({"what": label, "error": str(e)})
        except Exception as e:  # noqa: BLE001
            failed.append({"what": label, "error": _SCRUB.error(f"{type(e).__name__}: {e}")[:300]})

    pending = str(st.get("pending_interaction_id") or "")
    if pending:
        try:
            api.interaction_cancel(pending)
        except Exception:  # noqa: BLE001 — a finished interaction answers an error here; the delete decides
            pass
    for iid in list(st.get("interactions") or []):
        attempt(f"delete interaction {iid}", api.interaction_delete, str(iid))
    envs = list(st.get("environments") or ([st["environment_id"]] if st.get("environment_id") else []))
    for eid in envs:
        attempt(f"delete environment {eid}", api.environment_delete, str(eid))
    _emit("purge", {"done": done, "failed": failed, "state": STATE_REL})
    return 0 if not failed else 1


# ── entry ────────────────────────────────────────────────────────────────────────────────────────
def main() -> int:
    job = json.loads(sys.argv[1] if len(sys.argv) > 1 else os.environ.pop("HR_DRIVER_JOB"))
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
    except Refused as e:
        turn.result("failed", str(e))
        return 0
    except ApiError as e:
        turn.result("failed", plain_error(e))
        return 0
    except NetError as e:
        turn.result("failed", f"Google's service did not answer: {e}"[:600])
        return 0
    except OSError as e:
        # this box, not Google: a workspace file that could not be read or written
        turn.result("failed", _SCRUB.error(f"the workspace: {type(e).__name__}: {e}")[:600])
        return 0


if __name__ == "__main__":
    sys.exit(main())
