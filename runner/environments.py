"""Environments: a project's files and its installed dependencies, built once and read by every
session that names it.

The contract a session sees (UHP 2026-09-28, Environments chapter):

    /env/<slug>                 the environment, READ-ONLY, shared by every session that uses it
    <cwd>                       the session's own workspace: writable, private, where artifacts land
    PROJECT_ROOT=/env/<slug>    plus the environment's venv and node_modules on PATH/PYTHONPATH/NODE_PATH

Why a layer beside the workspace and not a copy into it: the workspace is checkpointed after every
turn and restored before the next one, and dependency directories are excluded from that tarball
because they are large and reinstallable (CHECKPOINT_EXCLUDE). An environment is the opposite
kind of thing: installed once, never checkpointed, never reinstalled, read by many sessions at
once. Putting it beside the workspace keeps both facts true at zero copy per session.

Layout on disk (ENV_ROOT, on the data volume):

    <ENV_ROOT>/<id>/source/           the editable project: what the console's file tree shows
    <ENV_ROOT>/<id>/versions/<n>/     one build: the source copied, then .venv and node_modules
                                      installed into it, then made read-only (root-owned, a+rX)
    <ENV_ROOT>/<id>/versions/<n>/.hr-build.json   the build's record: status, log, packages, size
    <ENV_ROOT>/<id>/active            symlink -> versions/<n>: the version sessions see
    <ENV_MOUNT>/<slug>                symlink -> <ENV_ROOT>/<id>/active: the path the agent is told

A build is a snapshot: editing the source after it changes nothing a session sees until the next
build. Rolling back is pointing `active` at an older version. Behind the write-wall
(HR_SESSION_UIDS) a session runs as its own uid and the layer is root's, so a write into it fails
with EACCES; that is the enforcement, not an instruction.
"""
from __future__ import annotations

import grp
import hashlib
import json
import mimetypes
import platform
import pwd
import re
import os
import pathlib
import shutil
import stat
import subprocess
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse

ENV_ROOT = os.environ.get("HR_ENV_ROOT") or os.path.join(
    os.path.dirname(os.environ.get("HARNESS_WORKSPACE", "/data/workspaces").rstrip("/")) or "/data", "environments")
ENV_MOUNT = os.environ.get("HR_ENV_MOUNT", "/env")
BUILD_TIMEOUT = int(os.environ.get("HR_ENV_BUILD_TIMEOUT", "1800"))     # the whole build, seconds
LOG_MAX = 200_000                                                        # characters of build log kept
TREE_MAX = 20_000                                                        # entries a tree listing returns
# Dependency and cache directories never copied from the source into a build: the build installs
# its own, from the manifests, in the image's own toolchain (a venv copied from a laptop is the
# thing SPI-001 says not to trust).
NOT_COPIED = {".venv", "venv", "node_modules", "__pycache__", ".pnpm-store", ".cache", ".hr-build.json"}
_ID_SAFE = set("abcdefghijklmnopqrstuvwxyz0123456789_-")
_SPEC_RE = re.compile(r"^@?[A-Za-z0-9][A-Za-z0-9._/+-]{0,99}(?:(?:==|>=|<=|~=|!=|@|=)[A-Za-z0-9._*+^~<>-]{0,60})?$")   # one declared package
_ARCH_DIRS = {"amd64": "x86_64-linux-gnu", "arm64": "aarch64-linux-gnu"}

# ── who may read an environment ─────────────────────────────────────────────────────────────────
# One group per environment, and the environment directory's group IS the record (as a session's
# uid is its workspace's owner: nothing to keep in sync, and it survives a restart because it lives
# on the volume). The runner alone reads the source (0700). A built version is the group's to read
# (0750 / 0640), and an agent process joins that group only for a turn whose harness names the
# environment, so a session reads the one environment it was given and no other. The store root
# and the mount directory are traversable, not listable: a session cannot enumerate the rest.
# Package installs run the packages' own code, so they run as the environment's build identity
# (uid = gid = the environment's number), never as root. Ownership needs root: a runner that is not
# root (a dev box, the per-session sandbox, the tests) applies the modes and nothing else.
GID_BASE = int(os.environ.get("HR_ENV_GID_BASE", "60000") or 60000)
GID_SPAN = 40000
_gid_lock = threading.Lock()

router = APIRouter()
_builds_lock = threading.Lock()
_builds: dict[str, threading.Thread] = {}   # "<id>:<n>" -> the thread building it


# ── paths ───────────────────────────────────────────────────────────────────────────────────────
def _check_id(env_id: str) -> str:
    s = str(env_id or "").strip()
    if not s or len(s) > 80 or any(c not in _ID_SAFE for c in s.lower()):
        raise HTTPException(400, "environment id must be a short [a-z0-9_-] token")
    return s


def slug_ok(slug: str) -> bool:
    s = str(slug or "")
    return bool(s) and len(s) <= 64 and s[0].isalnum() and all(c.isalnum() or c in "-_." for c in s) and ".." not in s


def env_dir(env_id: str) -> pathlib.Path:
    return pathlib.Path(ENV_ROOT) / _check_id(env_id)


def source_dir(env_id: str) -> pathlib.Path:
    return env_dir(env_id) / "source"


def version_dir(env_id: str, n: int) -> pathlib.Path:
    return env_dir(env_id) / "versions" / str(int(n))


def active_link(env_id: str) -> pathlib.Path:
    return env_dir(env_id) / "active"


def mount_path(slug: str) -> str:
    return os.path.join(ENV_MOUNT, slug)


def _root() -> bool:
    return os.geteuid() == 0


def _in_range(gid: int) -> int | None:
    return gid if GID_BASE <= gid < GID_BASE + GID_SPAN else None


def env_gid(env_id: str) -> int | None:
    """The group that reads this environment's builds, from its directory; None when the
    directory is not there or predates groups (secure_store gives it one)."""
    try:
        return _in_range(os.stat(env_dir(env_id)).st_gid)
    except OSError:
        return None


def reader_gid(mount: str | None) -> int | None:
    """The group a turn's process joins for the environment at `mount` (the link the agent is
    told), read from the active version the link points at; None when there is none."""
    if not mount:
        return None
    try:
        return _in_range(os.stat(mount).st_gid)
    except OSError:
        return None


def _account(n: int) -> None:
    """A group and passwd entry for an environment's number, so a tool that looks itself up (npm
    does) finds one. Best effort: nothing here needs the entry to exist."""
    try:
        grp.getgrgid(n)
    except KeyError:
        subprocess.run(["groupadd", "-g", str(n), f"henv{n}"], capture_output=True)
    try:
        pwd.getpwuid(n)
    except KeyError:
        subprocess.run(["useradd", "-M", "-u", str(n), "-g", str(n), "-s", "/usr/sbin/nologin", "-d", "/nonexistent", f"henv{n}"],
                       capture_output=True)


def _claim(env_id: str) -> pathlib.Path:
    """The environment's directory with a group of its own: made on first use, its group derived
    from the id and bumped past any sibling that already holds it, traversable by that group only."""
    d = env_dir(env_id)
    if env_gid(env_id) is not None:
        return d
    d.mkdir(parents=True, exist_ok=True)
    if not _root():
        return d
    with _gid_lock:
        taken = set()
        for sib in pathlib.Path(ENV_ROOT).iterdir():
            try:
                taken.add(os.stat(sib).st_gid)
            except OSError:
                pass
        gid = GID_BASE + int(hashlib.sha256(env_id.encode()).hexdigest()[:8], 16) % GID_SPAN
        while gid in taken:
            gid = GID_BASE + (gid - GID_BASE + 1) % GID_SPAN
        os.chown(d, 0, gid)
        os.chmod(d, 0o750)
        _account(gid)
    return d


def _source(env_id: str) -> pathlib.Path:
    """The source directory, the runner's alone."""
    _claim(env_id)
    src = source_dir(env_id)
    src.mkdir(exist_ok=True)
    os.chmod(src, 0o700)
    return src


def _build_as(env_id: str) -> dict:
    """Popen/run arguments that make a build step run as the environment's own identity; empty
    off root, so every step reads the same with or without it."""
    gid = env_gid(env_id)
    return {"user": gid, "group": gid, "extra_groups": []} if gid is not None and _root() else {}


def _own(path: pathlib.Path, uid: int, gid: int) -> None:
    """chown -R, a link as itself rather than what it points at."""
    try:
        os.lchown(path, uid, gid)
    except OSError:
        pass
    for dirpath, dirnames, filenames in os.walk(path):
        for name in dirnames + filenames:
            try:
                os.lchown(os.path.join(dirpath, name), uid, gid)
            except OSError:
                pass


def secure_store() -> int:
    """Every environment made before groups existed (its directory has no group of its own) gets
    one, its source the runner's alone, its versions the group's: the migration a restart on a box
    with older environments runs once. Returns how many it changed."""
    if not _root():
        return 0
    root = pathlib.Path(ENV_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, 0o751)
    n = 0
    for d in root.iterdir():
        try:
            if not d.is_dir() or env_gid(d.name) is not None:
                continue
            _claim(d.name)
            gid = env_gid(d.name)
            if gid is None:
                continue
            if source_dir(d.name).is_dir():
                os.chmod(source_dir(d.name), 0o700)
            vers = d / "versions"
            if vers.is_dir():
                os.chown(vers, 0, gid)
                os.chmod(vers, 0o750)
                for v in vers.iterdir():
                    _read_only(v, gid)
            n += 1
        except Exception:  # noqa: BLE001 — one odd directory must not stop the rest
            continue
    return n


def _safe_rel(root: pathlib.Path, rel: str) -> pathlib.Path:
    """A path under root, or 400. Symlinks inside the source are followed for the containment check
    so a link that points out of the tree cannot be read or written through."""
    raw = str(rel or "").replace("\\", "/")
    if raw.startswith("/") or (len(raw) > 1 and raw[1] == ":"):
        raise HTTPException(400, "path must be relative to the environment, not absolute")
    rel = raw.strip("/")
    if not rel or any(part in ("", ".", "..") for part in rel.split("/")):
        raise HTTPException(400, "path must be relative, without . or .. segments")
    base = root.resolve()
    p = (base / rel).resolve()
    try:
        p.relative_to(base)
    except ValueError:
        raise HTTPException(400, "path escapes the environment")
    return p


# ── the source: files a person edits ─────────────────────────────────────────────────────────────
def tree(env_id: str) -> list[dict]:
    """Every entry under the source, deepest last within a directory, as the console's tree wants
    it: path, dir flag, bytes, mtime. Symlinks are listed as what they are and never followed."""
    src = source_dir(env_id)
    out: list[dict] = []
    if not src.is_dir():
        return out
    for dirpath, dirnames, filenames in os.walk(src):
        dirnames.sort()
        rel_dir = os.path.relpath(dirpath, src)
        for d in dirnames:
            out.append({"path": os.path.normpath(os.path.join(rel_dir, d)), "dir": True, "bytes": 0, "mtime": 0})
        for f in sorted(filenames):
            full = os.path.join(dirpath, f)
            try:
                st = os.lstat(full)
            except OSError:
                continue
            out.append({"path": os.path.normpath(os.path.join(rel_dir, f)), "dir": False,
                        "bytes": int(st.st_size), "mtime": int(st.st_mtime),
                        **({"link": True} if stat.S_ISLNK(st.st_mode) else {})})
        if len(out) >= TREE_MAX:
            break
    return out[:TREE_MAX]


def source_stat(env_id: str) -> dict:
    n = b = 0
    for e in tree(env_id):
        if not e["dir"]:
            n += 1
            b += e["bytes"]
    return {"count": n, "bytes": b}


def read_file(env_id: str, rel: str) -> tuple[bytes, str]:
    p = _safe_rel(source_dir(env_id), rel)
    if not p.is_file():
        raise HTTPException(404, "no such file in the environment")
    return p.read_bytes(), (mimetypes.guess_type(p.name)[0] or "application/octet-stream")


def write_file(env_id: str, rel: str, data: bytes) -> dict:
    src = _source(env_id)
    p = _safe_rel(src, rel)
    if p.is_dir():
        raise HTTPException(409, "a directory is at that path")
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".hr-tmp")
    tmp.write_bytes(data)
    os.replace(tmp, p)
    return {"path": rel.strip("/"), "bytes": len(data)}


def make_dir(env_id: str, rel: str) -> dict:
    src = _source(env_id)
    p = _safe_rel(src, rel)
    p.mkdir(parents=True, exist_ok=True)
    return {"path": rel.strip("/"), "dir": True}


def delete_path(env_id: str, rel: str) -> dict:
    p = _safe_rel(source_dir(env_id), rel)
    if p.is_dir() and not p.is_symlink():
        shutil.rmtree(p)
    elif p.exists() or p.is_symlink():
        p.unlink()
    else:
        raise HTTPException(404, "nothing at that path")
    return {"path": rel.strip("/"), "deleted": True}


def _members_zip(zf: zipfile.ZipFile) -> list[tuple[str, bool, int]]:
    return [(i.filename, i.is_dir(), i.file_size) for i in zf.infolist()]


def _strip_common_root(names: list[str]) -> str:
    """GitHub's archives and most folder zips wrap everything in one directory; the project is
    what is inside it. The common first segment, when EVERY entry has the same one and nothing sits
    beside it, is stripped."""
    firsts = {n.split("/", 1)[0] for n in names if n.strip("/")}
    if len(firsts) == 1:
        root = next(iter(firsts))
        if all(n == root or n == root + "/" or n.startswith(root + "/") for n in names if n.strip("/")):
            return root + "/"
    return ""


def _member_ok(name: str) -> str | None:
    """The relative path a member may land at, or None for one that must not land at all."""
    n = name.replace("\\", "/")
    if n.startswith("/") or any(part in ("..", "") for part in n.strip("/").split("/") if n.strip("/")):
        return None
    return n.strip("/")


def import_archive(env_id: str, data_path: str, *, replace: bool = False) -> dict:
    """Extract a zip or tar archive into the source. Only regular files and directories land:
    symlinks, hard links, devices and any member that names a path outside the source are
    dropped and counted, never written. A single wrapping directory is stripped."""
    src = source_dir(env_id)
    if replace and src.exists():
        shutil.rmtree(src)
    src = _source(env_id)
    written = skipped = 0
    if zipfile.is_zipfile(data_path):
        with zipfile.ZipFile(data_path) as zf:
            names = [i.filename for i in zf.infolist()]
            root = _strip_common_root(names)
            for info in zf.infolist():
                rel = _member_ok(info.filename)
                if rel is None or (root and not (rel + "/").startswith(root)):
                    skipped += 1
                    continue
                rel = rel[len(root):] if root else rel
                if not rel:
                    continue
                mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_ISLNK(mode):
                    skipped += 1
                    continue
                dest = _safe_rel(src, rel)
                if info.is_dir():
                    dest.mkdir(parents=True, exist_ok=True)
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as fin, open(dest, "wb") as fout:
                    shutil.copyfileobj(fin, fout)
                if mode & 0o111:
                    os.chmod(dest, 0o755)
                written += 1
    elif tarfile.is_tarfile(data_path):
        with tarfile.open(data_path) as tf:
            members = tf.getmembers()
            root = _strip_common_root([m.name for m in members])
            for m in members:
                rel = _member_ok(m.name)
                if rel is None or (root and not (rel + "/").startswith(root)):
                    skipped += 1
                    continue
                rel = rel[len(root):] if root else rel
                if not rel:
                    continue
                if not (m.isreg() or m.isdir()):
                    skipped += 1
                    continue
                dest = _safe_rel(src, rel)
                if m.isdir():
                    dest.mkdir(parents=True, exist_ok=True)
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                fin = tf.extractfile(m)
                if fin is None:
                    skipped += 1
                    continue
                with fin, open(dest, "wb") as fout:
                    shutil.copyfileobj(fin, fout)
                if m.mode & 0o111:
                    os.chmod(dest, 0o755)
                written += 1
    else:
        raise HTTPException(400, "the upload is neither a zip nor a tar archive")
    return {"written": written, "skipped": skipped, **source_stat(env_id)}


def import_git(env_id: str, url: str, ref: str = "", *, replace: bool = False) -> dict:
    """Clone a repository's tree (shallow, one ref) into the source, without its .git."""
    if not str(url).startswith(("https://", "http://", "git@", "ssh://")):
        raise HTTPException(400, "git url must be https://, http://, ssh:// or git@")
    with tempfile.TemporaryDirectory(prefix="hr-env-git-") as tmp:
        cmd = ["git", "clone", "--depth", "1", "--quiet"] + (["--branch", ref] if ref else []) + [url, tmp + "/repo"]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=600,
                           env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        except subprocess.CalledProcessError as e:
            raise HTTPException(400, f"git clone failed: {(e.stderr or '')[-400:].strip()}")
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "git clone did not finish in 10 minutes")
        shutil.rmtree(tmp + "/repo/.git", ignore_errors=True)
        src = source_dir(env_id)
        if replace and src.exists():
            shutil.rmtree(src)
        src.mkdir(parents=True, exist_ok=True)
        shutil.copytree(tmp + "/repo", src, dirs_exist_ok=True, symlinks=False)
    return {"imported": "git", "url": url, "ref": ref, **source_stat(env_id)}


# ── runtimes ────────────────────────────────────────────────────────────────────────────────────
def runtimes() -> dict:
    """What a build can be made with, on this box: the Python minors present as python3.N binaries,
    the Node major, the OS release for apt. Only what is here; nothing offered that is not."""
    env = _tool_env()
    pythons = []
    for minor in range(8, 20):
        if shutil.which(f"python3.{minor}", path=env.get("PATH")):
            pythons.append(f"3.{minor}")
    node = ""
    try:
        node = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=10, env=env).stdout.strip().lstrip("v").split(".")[0]
    except (OSError, subprocess.TimeoutExpired):
        pass
    os_name = os_ver = ""
    try:
        for line in open("/etc/os-release"):
            k, _, v = line.strip().partition("=")
            if k == "ID":
                os_name = v.strip('"')
            elif k == "VERSION_ID":
                os_ver = v.strip('"')
    except OSError:
        pass
    return {"python": pythons, "node": [node] if node else [], "os": {"name": os_name, "version": os_ver},
            "apt": bool(shutil.which("apt-get") and shutil.which("dpkg"))}


REGISTRY_TIMEOUT = 8
_apt_lists_at = 0.0


def spec_parts(spec: str, manager: str) -> tuple[str, str]:
    """A spec's name and exact pin: npm's name@version, pip's name==version, apt's name=version.
    A range (>=, ~=, ...) is a name with no pin; the installer resolves it at build time."""
    s = spec.strip()
    if manager == "npm":
        i = s.rfind("@")
        return (s[:i], s[i + 1:]) if i > 0 else (s, "")
    for sep in ("==", "="):
        if sep in s:
            n, v = s.split(sep, 1)
            return n.strip(), v.strip()
    for sep in (">=", "<=", "~=", "!=", ">", "<"):
        if sep in s:
            return s.split(sep, 1)[0].strip(), ""
    return s, ""


def _http_json(url: str) -> tuple[int, dict]:
    req = urllib.request.Request(url, headers={"User-Agent": "harnessrouter-environments/1", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=REGISTRY_TIMEOUT) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        return e.code, {}


def _apt_lists() -> None:
    """apt's package lists, refreshed at most every six hours: what a build's apt would see."""
    global _apt_lists_at
    if time.time() - _apt_lists_at < 6 * 3600:
        return
    subprocess.run(["apt-get", "update", "-qq"], capture_output=True, timeout=180, env=_tool_env())
    _apt_lists_at = time.time()


def check_package(manager: str, spec: str) -> dict:
    """What the manager's registry says about a declared package before any build: whether the
    name exists, its latest version, and whether an exact pin is published. pip asks PyPI, npm the
    npm registry, apt this box's own package lists (the ones a build would download from). A typo
    is refused at the moment it is typed instead of failing a build minutes later. `exists` is
    None when the registry could not be asked; the build is then the check."""
    manager = (manager or "").strip().lower()
    if manager not in ("pip", "npm", "apt"):
        raise HTTPException(400, "manager must be pip, npm or apt")
    spec = (spec or "").strip()
    if not _SPEC_RE.match(spec):
        raise HTTPException(400, "that is not a package spec")
    name, pin = spec_parts(spec, manager)
    out = {"manager": manager, "name": name, "spec": spec, "exists": None, "latest": "", "version": "", "error": ""}
    try:
        if manager == "pip":
            st, j = _http_json(f"https://pypi.org/pypi/{urllib.parse.quote(name)}/json")
            if st == 404:
                out.update(exists=False, error=f"{name} is not on PyPI")
                return out
            if st != 200:
                raise RuntimeError(f"PyPI answered {st}")
            info = j.get("info") or {}
            out.update(exists=True, latest=str(info.get("version") or ""), name=str(info.get("name") or name))
            versions = set((j.get("releases") or {}).keys())
        elif manager == "npm":
            st, j = _http_json("https://registry.npmjs.org/" + urllib.parse.quote(name, safe="@").replace("/", "%2F"))
            if st == 404:
                out.update(exists=False, error=f"{name} is not on the npm registry")
                return out
            if st != 200:
                raise RuntimeError(f"the npm registry answered {st}")
            out.update(exists=True, latest=str((j.get("dist-tags") or {}).get("latest") or ""))
            versions = set((j.get("versions") or {}).keys())
        else:
            _apt_lists()
            env = _tool_env()
            r = subprocess.run(["apt-cache", "policy", name], capture_output=True, text=True, timeout=60, env=env)
            cand = next((ln.split(":", 1)[1].strip() for ln in r.stdout.splitlines() if ln.strip().startswith("Candidate:")), "")
            if not cand or cand == "(none)":
                out.update(exists=False, error=f"{name} is not in this server's apt sources")
                return out
            out.update(exists=True, latest=cand)
            m = subprocess.run(["apt-cache", "madison", name], capture_output=True, text=True, timeout=60, env=env)
            versions = {ln.split("|")[1].strip() for ln in m.stdout.splitlines() if ln.count("|") >= 2}
        if pin:
            if pin in versions:
                out["version"] = pin
            else:
                out["error"] = f"{name} {pin} is not published; the latest is {out['latest']}"
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as e:
        out.update(exists=None, error=f"the registry could not be asked: {str(e)[:120]}")
    return out


def clean_specs(specs) -> list[str]:
    """Declared packages as short spec strings, each checked against one shape."""
    out: list[str] = []
    for x in (specs or []):
        t = str(x or "").strip()
        if t and _SPEC_RE.match(t) and t not in out and len(out) < 200:
            out.append(t)
    return out


# ── builds ──────────────────────────────────────────────────────────────────────────────────────
def build_record(env_id: str, n: int) -> dict | None:
    p = version_dir(env_id, n) / ".hr-build.json"
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def versions(env_id: str) -> list[dict]:
    root = env_dir(env_id) / "versions"
    out = []
    if root.is_dir():
        for e in sorted(root.iterdir(), key=lambda x: int(x.name) if x.name.isdigit() else 0):
            if e.name.isdigit():
                rec = build_record(env_id, int(e.name)) or {"version": int(e.name), "status": "unknown"}
                out.append({k: rec.get(k) for k in ("version", "status", "started_at", "finished_at", "error", "files", "bytes")
                            } | {"packages": len(rec.get("packages") or [])})
    return out


def active_version(env_id: str) -> int | None:
    try:
        target = os.readlink(active_link(env_id))
    except OSError:
        return None
    name = os.path.basename(target.rstrip("/"))
    return int(name) if name.isdigit() else None


def _tool_env() -> dict:
    """The environment the build's commands run in: the runner's own (the image's toolchain, the
    same python3 and node an agent gets), minus anything secret-shaped, with caches kept out of
    the layer."""
    from server import _child_env   # the same scrub agents get; imported late to avoid a cycle
    env = _child_env()
    env["PIP_NO_CACHE_DIR"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["npm_config_fund"] = env["npm_config_audit"] = "false"
    env["npm_config_update_notifier"] = "false"
    return env


def _run(log: list[str], cmd: list[str], cwd: str, env: dict, deadline: float, run_as: dict | None = None,
         flush=None) -> None:
    """One build command. `flush` writes the record after the command line and again after its
    output, so a build's log is readable while the build runs, not only when it ends."""
    left = max(1, int(deadline - time.time()))
    log.append(f"$ {' '.join(cmd)}")
    if flush:
        flush()
    try:
        r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=left, **(run_as or {}))
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{cmd[0]} did not finish within the build's {BUILD_TIMEOUT}s")
    if r.stdout.strip():
        log.append(r.stdout.rstrip()[-20000:])
    if r.stderr.strip():
        log.append(r.stderr.rstrip()[-20000:])
    if flush:
        flush()
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} exited {r.returncode}")


def _packages(dst: pathlib.Path, env: dict, run_as: dict | None = None) -> list[dict]:
    out: list[dict] = []
    run_as = run_as or {}
    pip = dst / ".venv" / "bin" / "pip"
    if pip.is_file():
        try:
            r = subprocess.run([str(pip), "list", "--format=json"], capture_output=True, text=True, timeout=120, env=env, **run_as)
            for row in json.loads(r.stdout or "[]"):
                out.append({"manager": "pip", "name": str(row.get("name")), "version": str(row.get("version"))})
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    if (dst / "node_modules").is_dir():
        try:
            r = subprocess.run(["npm", "ls", "--json", "--depth=0"], cwd=str(dst), capture_output=True, text=True,
                               timeout=120, env=env, **run_as)
            deps = (json.loads(r.stdout or "{}") or {}).get("dependencies") or {}
            for name, info in sorted(deps.items()):
                out.append({"manager": "npm", "name": name, "version": str((info or {}).get("version") or "")})
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    return out


def _apt_into_layer(log: list[str], dst: pathlib.Path, names: list[str], env: dict, scratch: str, deadline: float, flush=None) -> None:
    """System packages, unpacked into the layer rather than installed into the box: apt resolves
    and downloads each named package with the dependencies the image lacks, and dpkg unpacks every
    archive under <version>/apt, which a turn puts on PATH and LD_LIBRARY_PATH. The image's own
    packages stay the image's; nothing here changes the container."""
    cache = pathlib.Path(scratch) / "apt-archives"
    cache.mkdir(parents=True, exist_ok=True)
    _run(log, ["apt-get", "update", "-qq"], str(dst), env, deadline, flush=flush)
    _run(log, ["apt-get", "install", "-y", "--download-only", "--reinstall", "-o", f"Dir::Cache::archives={cache}",
               "-o", "Debug::NoLocking=1", *[n.split("=", 1)[0] if "=" in n and not n.startswith("=") else n for n in names]],
         str(dst), env, deadline, flush=flush)
    debs = sorted(cache.glob("*.deb"))
    if not debs:
        raise RuntimeError("apt downloaded nothing for " + ", ".join(names))
    out = dst / "apt"
    out.mkdir(exist_ok=True)
    for deb in debs:
        _run(log, ["dpkg", "-x", str(deb), str(out)], str(dst), env, deadline, flush=flush)
    (out / ".packages").write_text("\n".join(d.name for d in debs) + "\n")
    log.append(f"apt: unpacked {len(debs)} archive(s) into apt/")


def _apt_packages(dst: pathlib.Path) -> list[dict]:
    """The archives a build unpacked, as manager/name/version, from their file names."""
    out = []
    try:
        for name in (dst / "apt" / ".packages").read_text().split():
            parts = name[:-4].split("_") if name.endswith(".deb") else []
            if len(parts) >= 2:
                out.append({"manager": "apt", "name": parts[0], "version": parts[1].replace("%3a", ":")})
    except OSError:
        pass
    return out


def _read_only(dst: pathlib.Path, gid: int | None = None) -> None:
    """Root's, the environment's group's to read, writable by nobody: directories 750, files 640
    keeping their execute bit (750). Nobody outside the group sees a byte of it."""
    own = gid is not None and _root()

    def one(p: str, is_dir: bool) -> None:
        try:
            st = os.lstat(p)
            if own:
                os.lchown(p, 0, gid)
            if not stat.S_ISLNK(st.st_mode):
                os.chmod(p, 0o750 if is_dir or st.st_mode & 0o111 else 0o640)
        except OSError:
            pass

    one(str(dst), True)
    for dirpath, dirnames, filenames in os.walk(dst):
        for d in dirnames:
            one(os.path.join(dirpath, d), True)
        for f in filenames:
            one(os.path.join(dirpath, f), False)


def _size(dst: pathlib.Path) -> tuple[int, int]:
    n = b = 0
    for dirpath, _, filenames in os.walk(dst):
        for f in filenames:
            try:
                st = os.lstat(os.path.join(dirpath, f))
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode):
                n += 1
                b += st.st_size
    return n, b


def _write_record(dst: pathlib.Path, rec: dict) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    rec = dict(rec)
    if isinstance(rec.get("log"), list):
        text = "\n".join(rec["log"])
        rec["log"] = text[-LOG_MAX:] if len(text) > LOG_MAX else text
    tmp = dst / ".hr-build.json.tmp"
    tmp.write_text(json.dumps(rec, indent=1))
    os.replace(tmp, dst / ".hr-build.json")


def _build(env_id: str, n: int, slug: str, activate: bool, spec: dict | None = None) -> None:
    spec = spec or {}
    pip_specs, npm_specs, apt_specs = clean_specs(spec.get("pip")), clean_specs(spec.get("npm")), clean_specs(spec.get("apt"))
    want_py = str(spec.get("python") or "")   # the node major is the box's one; recorded, not chosen
    src, dst = source_dir(env_id), version_dir(env_id, n)
    started = int(time.time())
    log: list[str] = []
    rec = {"version": n, "status": "building", "started_at": started, "finished_at": None, "error": "",
           "packages": [], "files": 0, "bytes": 0, "log": log, "runtime": {}, "stage": "starting",
           "declared": {"pip": pip_specs, "npm": npm_specs, "apt": apt_specs}}

    def flush() -> None:
        """The record on disk IS what the owner sees while the build runs: written as each step ends."""
        try:
            _write_record(dst, rec)
        except OSError:
            pass

    def stage(name: str) -> None:
        rec["stage"] = name
        flush()

    try:
        _claim(env_id)
        gid = env_gid(env_id)
        if dst.exists():
            shutil.rmtree(dst)
        _write_record(dst, rec)
        if gid is not None:
            os.chown(dst.parent, 0, gid)
            os.chmod(dst.parent, 0o750)
        deadline = time.time() + BUILD_TIMEOUT
        env = _tool_env()
        stage("copying files")
        log.append(f"copying the project ({source_stat(env_id)['count']} files)")
        shutil.copytree(src, dst, symlinks=False, dirs_exist_ok=True,
                        ignore=lambda d, names: [x for x in names if x in NOT_COPIED])
        as_build = _build_as(env_id)
        with tempfile.TemporaryDirectory(prefix="hr-env-build-") as scratch:
            env["HOME"] = env["TMPDIR"] = scratch
            env["npm_config_cache"] = os.path.join(scratch, "npm-cache")
            if as_build:
                # pip, npm and setup.sh run the project's and its packages' own code: as the
                # environment's identity, which owns this layer and the scratch and nothing else.
                _own(dst, gid, gid)
                os.chown(scratch, gid, gid)
            if pip_specs or (dst / "requirements.txt").is_file() or (dst / "pyproject.toml").is_file():
                stage("python packages")
                # The interpreter the owner chose, when the box has it; the image's python3 otherwise.
                python = (shutil.which(f"python{want_py}", path=env.get("PATH")) if want_py else None) \
                    or shutil.which("python3", path=env.get("PATH")) or "python3"
                _run(log, [python, "-m", "venv", ".venv"], str(dst), env, deadline, as_build, flush)
                pip = str(dst / ".venv" / "bin" / "pip")
                if (dst / "requirements.txt").is_file():
                    _run(log, [pip, "install", "-r", "requirements.txt"], str(dst), env, deadline, as_build, flush)
                if (dst / "pyproject.toml").is_file():
                    _run(log, [pip, "install", "."], str(dst), env, deadline, as_build, flush)
                if pip_specs:
                    _run(log, [pip, "install", *pip_specs], str(dst), env, deadline, as_build, flush)
                try:
                    rec["runtime"]["python"] = subprocess.run([str(dst / ".venv" / "bin" / "python"), "-c", "import platform; print(platform.python_version())"],
                                                              capture_output=True, text=True, timeout=30, env=env, **as_build).stdout.strip()
                except (OSError, subprocess.TimeoutExpired):
                    pass
            if npm_specs or (dst / "package.json").is_file():
                stage("node packages")
                npm = shutil.which("npm", path=env.get("PATH")) or "npm"
                if (dst / "package.json").is_file():
                    _run(log, [npm, "ci" if (dst / "package-lock.json").is_file() else "install", "--no-audit", "--no-fund"],
                         str(dst), env, deadline, as_build, flush)
                if npm_specs:
                    if not (dst / "package.json").is_file():
                        (dst / "package.json").write_text(json.dumps({"name": slug or "environment", "version": "0.0.0", "private": True}, indent=2) + "\n")
                        if as_build:
                            os.chown(dst / "package.json", gid, gid)
                    _run(log, [npm, "install", "--no-audit", "--no-fund", "--save", *npm_specs], str(dst), env, deadline, as_build, flush)
                try:
                    rec["runtime"]["node"] = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=10, env=env).stdout.strip().lstrip("v")
                except (OSError, subprocess.TimeoutExpired):
                    pass
            if apt_specs:   # apt-get and dpkg -x run none of the packages' code; apt's lists need root
                stage("system packages")
                _apt_into_layer(log, dst, apt_specs, env, scratch, deadline, flush)
            if (dst / "setup.sh").is_file():
                stage("setup.sh")
                _run(log, ["bash", "setup.sh"], str(dst), {**env, "ENV_ROOT": str(dst)}, deadline, as_build, flush)
            stage("finishing")
            rec["packages"] = _packages(dst, env, as_build)
            if (dst / "apt").is_dir():
                rec["packages"] += _apt_packages(dst)
        _read_only(dst, gid)
        rec["files"], rec["bytes"] = _size(dst)
        rec["status"], rec["finished_at"], rec["stage"] = "ready", int(time.time()), ""
        log.append(f"ready: {rec['files']} files, {len(rec['packages'])} packages, {int(time.time()) - started}s")
        if activate:
            # The record is the build's last word, so what the build promised is in place before it
            # says ready. It used to be written first: a reader that waited for "ready" and started
            # a turn at once found no active version in between (issue #401; a CI run met it on a
            # slow disk, 2026-10-05). If the last steps fail, the active version is what it was.
            was = active_version(env_id)
            try:
                _point_active(env_id, n)
                ensure_mount(env_id, slug)
                _write_record(dst, rec)
            except Exception:
                _point_active(env_id, was)
                raise
        else:
            _write_record(dst, rec)
    except Exception as e:  # noqa: BLE001 — the record IS the report; nothing else sees this thread
        rec["status"], rec["finished_at"], rec["error"], rec["stage"] = "failed", int(time.time()), str(e)[:500], ""
        log.append(f"failed: {e}")
        try:
            _write_record(dst, rec)
        except OSError:
            pass
    finally:
        with _builds_lock:
            _builds.pop(f"{env_id}:{n}", None)


def start_build(env_id: str, n: int, slug: str, activate: bool = True, spec: dict | None = None) -> dict:
    if not source_dir(env_id).is_dir():
        raise HTTPException(409, "the environment has no files yet")
    key = f"{env_id}:{n}"
    with _builds_lock:
        if key in _builds and _builds[key].is_alive():
            raise HTTPException(409, "that version is already building")
        for k, t in _builds.items():
            if k.startswith(env_id + ":") and t.is_alive():
                raise HTTPException(409, "another version of this environment is building")
        t = threading.Thread(target=_build, args=(env_id, n, slug, activate, spec), daemon=True, name=f"env-build-{key}")
        _builds[key] = t
        t.start()
    return {"version": n, "status": "building"}


def _point_active(env_id: str, n: int | None) -> None:
    """Make version n the environment's active one; None leaves it with none."""
    link = active_link(env_id)
    if n is None:
        link.unlink(missing_ok=True)
        return
    tmp = link.with_name("active.tmp")
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    os.symlink(os.path.join("versions", str(n)), tmp)
    os.replace(tmp, link)                      # atomic: a session mid-turn sees the old or the new, never neither


def activate_version(env_id: str, n: int, slug: str) -> dict:
    dst = version_dir(env_id, n)
    rec = build_record(env_id, n)
    if not dst.is_dir() or not rec or rec.get("status") != "ready":
        raise HTTPException(409, f"version {n} is not a finished build")
    _point_active(env_id, n)
    ensure_mount(env_id, slug)
    return {"version": n, "status": "ready", "path": mount_path(slug)}


def ensure_mount(env_id: str, slug: str) -> str:
    """The path sessions are told, as a link to the environment's active version. Created on the
    container's rootfs, so it is remade after a restart; idempotent."""
    if not slug_ok(slug):
        raise HTTPException(400, "environment slug is not a path segment")
    if active_version(env_id) is None:
        raise HTTPException(409, "the environment has no built version")
    os.makedirs(ENV_MOUNT, mode=0o751, exist_ok=True)
    try:
        os.chmod(ENV_MOUNT, 0o751)
    except OSError:
        pass
    target = str(active_link(env_id))
    link = mount_path(slug)
    try:
        if os.readlink(link) == target:
            return link
    except OSError:
        pass
    tmp = link + ".tmp"
    if os.path.lexists(tmp):
        os.unlink(tmp)
    os.symlink(target, tmp)
    os.replace(tmp, link)
    return link


def drop_mount(slug: str) -> None:
    link = mount_path(slug)
    if os.path.islink(link):
        os.unlink(link)


def delete_environment(env_id: str, slug: str = "") -> dict:
    if slug:
        drop_mount(slug)
    d = env_dir(env_id)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    return {"id": env_id, "deleted": True}


# ── the turn ────────────────────────────────────────────────────────────────────────────────────
def resolve(spec: dict | None) -> dict | None:
    """What a turn's environment is on this box: the link at the path the agent is told (made if
    the container restarted), the version behind it, the entry the owner declared. None when the
    turn has no environment; 409 when the environment has nothing built."""
    if not spec:
        return None
    env_id, slug = _check_id(spec.get("id")), str(spec.get("slug") or "")
    link = ensure_mount(env_id, slug)
    if not pathlib.Path(link).resolve().is_dir():
        raise HTTPException(409, "the environment's active version is missing on disk")
    return {"id": env_id, "slug": slug, "path": link, "version": active_version(env_id),
            "entry": str(spec.get("entry") or "")}


def apply_env(env: dict, applied: dict | None) -> None:
    """The variables that make the layer's interpreter and packages the ones an agent runs:
    PROJECT_ROOT, the venv first on PATH (so `python3` is the venv's), the project on PYTHONPATH
    (so `from scripts.lib import x` works from anywhere), node_modules on NODE_PATH."""
    if not applied:
        return
    link = applied["path"]
    real = pathlib.Path(link).resolve()
    env["PROJECT_ROOT"] = link
    env["HR_ENVIRONMENT"] = link
    env["PYTHONPATH"] = link + (":" + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    path_add = []
    if (real / ".venv" / "bin").is_dir():
        path_add.append(os.path.join(link, ".venv", "bin"))
        env["VIRTUAL_ENV"] = os.path.join(link, ".venv")
    if (real / "node_modules" / ".bin").is_dir():
        path_add.append(os.path.join(link, "node_modules", ".bin"))
    if (real / "node_modules").is_dir():
        env["NODE_PATH"] = os.path.join(link, "node_modules") + (":" + env["NODE_PATH"] if env.get("NODE_PATH") else "")
    if (real / "apt").is_dir():
        apt = os.path.join(link, "apt")
        path_add += [os.path.join(apt, "usr", "bin"), os.path.join(apt, "usr", "local", "bin"), os.path.join(apt, "bin")]
        arch = _ARCH_DIRS.get({"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine(), ""), "")
        libs = [os.path.join(apt, "usr", "lib"), os.path.join(apt, "lib")] + ([os.path.join(apt, "usr", "lib", arch), os.path.join(apt, "lib", arch)] if arch else [])
        env["LD_LIBRARY_PATH"] = ":".join(libs + ([env["LD_LIBRARY_PATH"]] if env.get("LD_LIBRARY_PATH") else []))
    if path_add:
        env["PATH"] = ":".join(path_add + [env.get("PATH", "")])


def apply_to_turn(env: dict, spec: dict | None) -> dict | None:
    """resolve + apply_env in one call, for a caller that has no doc to write first."""
    applied = resolve(spec)
    apply_env(env, applied)
    return applied


def doc_section(applied: dict | None) -> list[str]:
    """The lines the agent's instruction file carries for its environment: where the project is,
    that it is read-only and shared, where to write, and how it is run when the owner said."""
    if not applied:
        return []
    path = applied["path"]
    lines = ["## Project environment", "",
             f"The project `{applied['slug']}` is at `{path}` (also `$PROJECT_ROOT`). It is READ-ONLY and shared "
             "with other sessions: its files are complete and its dependencies are already installed "
             "(its Python virtualenv and node_modules are on your PATH; `python3` and `node` from your "
             "shell use them), so do not install packages or copy the project to start. Do not try to "
             "write under it: write every output, log and scratch file to your working directory, and "
             "copy a project file there first if you need to change it. Run the project's scripts by "
             f"their absolute path (for example `python3 {path}/<script>.py`) with your working directory "
             "as the current directory, so relative outputs land where the user sees them."]
    if applied.get("entry"):
        lines += ["", f"How the project is run: `{applied['entry']}`"]
    lines.append("")
    return lines


# ── routes (internal: the gateway drives these; the write-wall middleware in server.py guards them) ──
@router.get("/environments/{env_id}/tree")
def r_tree(env_id: str) -> dict:
    return {"entries": tree(env_id), **source_stat(env_id)}


@router.get("/environments/{env_id}/source")
def r_read(env_id: str, path: str) -> Response:
    data, ctype = read_file(env_id, path)
    return Response(content=data, media_type=ctype)


@router.put("/environments/{env_id}/source")
async def r_write(env_id: str, path: str, request: Request) -> dict:
    return write_file(env_id, path, await request.body())


@router.post("/environments/{env_id}/mkdir")
def r_mkdir(env_id: str, path: str) -> dict:
    return make_dir(env_id, path)


@router.delete("/environments/{env_id}/source")
def r_delete(env_id: str, path: str) -> dict:
    return delete_path(env_id, path)


@router.post("/environments/{env_id}/import")
async def r_import(env_id: str, request: Request, replace: int = 0, git_url: str = "", git_ref: str = "") -> dict:
    if git_url:
        return import_git(env_id, git_url, git_ref, replace=bool(replace))
    fd, spool = tempfile.mkstemp(prefix="hr-env-import-")
    try:
        with os.fdopen(fd, "wb") as out:
            async for chunk in request.stream():
                if chunk:
                    out.write(chunk)
        return import_archive(env_id, spool, replace=bool(replace))
    finally:
        try:
            os.unlink(spool)
        except OSError:
            pass


@router.get("/environments/runtimes")
def r_runtimes() -> dict:
    return runtimes()


@router.get("/environments/packages/check")
def r_check_package(manager: str, spec: str) -> dict:
    return check_package(manager, spec)


@router.post("/environments/{env_id}/build")
async def r_build(env_id: str, version: int, slug: str, request: Request, activate: int = 1) -> dict:
    if not slug_ok(slug):
        raise HTTPException(400, "environment slug is not a path segment")
    raw = await request.body()
    try:
        spec = json.loads(raw) if raw else {}
    except ValueError:
        raise HTTPException(400, "the build body is not JSON")
    return start_build(env_id, int(version), slug, bool(activate), spec if isinstance(spec, dict) else {})


@router.get("/environments/{env_id}/build")
def r_build_status(env_id: str, version: int) -> dict:
    rec = build_record(env_id, int(version))
    if not rec:
        raise HTTPException(404, "no such build")
    return rec


@router.get("/environments/{env_id}/versions")
def r_versions(env_id: str) -> dict:
    return {"versions": versions(env_id), "active": active_version(env_id)}


@router.post("/environments/{env_id}/activate")
def r_activate(env_id: str, version: int, slug: str) -> dict:
    return activate_version(env_id, int(version), slug)


@router.delete("/environments/{env_id}")
def r_delete_env(env_id: str, slug: str = "") -> dict:
    return delete_environment(env_id, slug)


@router.get("/environments/{env_id}")
def r_get(env_id: str) -> JSONResponse:
    return JSONResponse({"id": env_id, "source": source_stat(env_id), "versions": versions(env_id),
                         "active": active_version(env_id), "root": ENV_ROOT})
