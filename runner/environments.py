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

import json
import mimetypes
import platform
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
    src = source_dir(env_id)
    src.mkdir(parents=True, exist_ok=True)
    p = _safe_rel(src, rel)
    if p.is_dir():
        raise HTTPException(409, "a directory is at that path")
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".hr-tmp")
    tmp.write_bytes(data)
    os.replace(tmp, p)
    return {"path": rel.strip("/"), "bytes": len(data)}


def make_dir(env_id: str, rel: str) -> dict:
    src = source_dir(env_id)
    src.mkdir(parents=True, exist_ok=True)
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
    src.mkdir(parents=True, exist_ok=True)
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


def _run(log: list[str], cmd: list[str], cwd: str, env: dict, deadline: float) -> None:
    left = max(1, int(deadline - time.time()))
    log.append(f"$ {' '.join(cmd)}")
    try:
        r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=left)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{cmd[0]} did not finish within the build's {BUILD_TIMEOUT}s")
    if r.stdout.strip():
        log.append(r.stdout.rstrip()[-20000:])
    if r.stderr.strip():
        log.append(r.stderr.rstrip()[-20000:])
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} exited {r.returncode}")


def _packages(dst: pathlib.Path, env: dict) -> list[dict]:
    out: list[dict] = []
    pip = dst / ".venv" / "bin" / "pip"
    if pip.is_file():
        try:
            r = subprocess.run([str(pip), "list", "--format=json"], capture_output=True, text=True, timeout=120, env=env)
            for row in json.loads(r.stdout or "[]"):
                out.append({"manager": "pip", "name": str(row.get("name")), "version": str(row.get("version"))})
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    if (dst / "node_modules").is_dir():
        try:
            r = subprocess.run(["npm", "ls", "--json", "--depth=0"], cwd=str(dst), capture_output=True, text=True,
                               timeout=120, env=env)
            deps = (json.loads(r.stdout or "{}") or {}).get("dependencies") or {}
            for name, info in sorted(deps.items()):
                out.append({"manager": "npm", "name": name, "version": str((info or {}).get("version") or "")})
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    return out


def _apt_into_layer(log: list[str], dst: pathlib.Path, names: list[str], env: dict, scratch: str, deadline: float) -> None:
    """System packages, unpacked into the layer rather than installed into the box: apt resolves
    and downloads each named package with the dependencies the image lacks, and dpkg unpacks every
    archive under <version>/apt, which a turn puts on PATH and LD_LIBRARY_PATH. The image's own
    packages stay the image's; nothing here changes the container."""
    cache = pathlib.Path(scratch) / "apt-archives"
    cache.mkdir(parents=True, exist_ok=True)
    _run(log, ["apt-get", "update", "-qq"], str(dst), env, deadline)
    _run(log, ["apt-get", "install", "-y", "--download-only", "--reinstall", "-o", f"Dir::Cache::archives={cache}",
               "-o", "Debug::NoLocking=1", *[n.split("=", 1)[0] if "=" in n and not n.startswith("=") else n for n in names]],
         str(dst), env, deadline)
    debs = sorted(cache.glob("*.deb"))
    if not debs:
        raise RuntimeError("apt downloaded nothing for " + ", ".join(names))
    out = dst / "apt"
    out.mkdir(exist_ok=True)
    for deb in debs:
        _run(log, ["dpkg", "-x", str(deb), str(out)], str(dst), env, deadline)
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


def _read_only(dst: pathlib.Path) -> None:
    """Root's, readable by everyone, writable by nobody else: directories 755, files keep their
    execute bits and lose group/other write."""
    for dirpath, dirnames, filenames in os.walk(dst):
        try:
            os.chmod(dirpath, 0o755)
        except OSError:
            pass
        for f in filenames:
            p = os.path.join(dirpath, f)
            try:
                st = os.lstat(p)
                if stat.S_ISLNK(st.st_mode):
                    continue
                os.chmod(p, 0o755 if st.st_mode & 0o111 else 0o644)
            except OSError:
                continue


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
           "packages": [], "files": 0, "bytes": 0, "log": log, "runtime": {},
           "declared": {"pip": pip_specs, "npm": npm_specs, "apt": apt_specs}}
    try:
        if dst.exists():
            shutil.rmtree(dst)
        _write_record(dst, rec)
        deadline = time.time() + BUILD_TIMEOUT
        env = _tool_env()
        log.append(f"copying the project ({source_stat(env_id)['count']} files)")
        shutil.copytree(src, dst, symlinks=False, dirs_exist_ok=True,
                        ignore=lambda d, names: [x for x in names if x in NOT_COPIED])
        with tempfile.TemporaryDirectory(prefix="hr-env-build-") as scratch:
            env["HOME"] = env["TMPDIR"] = scratch
            env["npm_config_cache"] = os.path.join(scratch, "npm-cache")
            if pip_specs or (dst / "requirements.txt").is_file() or (dst / "pyproject.toml").is_file():
                # The interpreter the owner chose, when the box has it; the image's python3 otherwise.
                python = (shutil.which(f"python{want_py}", path=env.get("PATH")) if want_py else None) \
                    or shutil.which("python3", path=env.get("PATH")) or "python3"
                _run(log, [python, "-m", "venv", ".venv"], str(dst), env, deadline)
                pip = str(dst / ".venv" / "bin" / "pip")
                if (dst / "requirements.txt").is_file():
                    _run(log, [pip, "install", "-r", "requirements.txt"], str(dst), env, deadline)
                if (dst / "pyproject.toml").is_file():
                    _run(log, [pip, "install", "."], str(dst), env, deadline)
                if pip_specs:
                    _run(log, [pip, "install", *pip_specs], str(dst), env, deadline)
                try:
                    rec["runtime"]["python"] = subprocess.run([str(dst / ".venv" / "bin" / "python"), "-c", "import platform; print(platform.python_version())"],
                                                              capture_output=True, text=True, timeout=30, env=env).stdout.strip()
                except (OSError, subprocess.TimeoutExpired):
                    pass
            if npm_specs or (dst / "package.json").is_file():
                npm = shutil.which("npm", path=env.get("PATH")) or "npm"
                if (dst / "package.json").is_file():
                    _run(log, [npm, "ci" if (dst / "package-lock.json").is_file() else "install", "--no-audit", "--no-fund"],
                         str(dst), env, deadline)
                if npm_specs:
                    if not (dst / "package.json").is_file():
                        (dst / "package.json").write_text(json.dumps({"name": slug or "environment", "version": "0.0.0", "private": True}, indent=2) + "\n")
                    _run(log, [npm, "install", "--no-audit", "--no-fund", "--save", *npm_specs], str(dst), env, deadline)
                try:
                    rec["runtime"]["node"] = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=10, env=env).stdout.strip().lstrip("v")
                except (OSError, subprocess.TimeoutExpired):
                    pass
            if apt_specs:
                _apt_into_layer(log, dst, apt_specs, env, scratch, deadline)
            if (dst / "setup.sh").is_file():
                _run(log, ["bash", "setup.sh"], str(dst), {**env, "ENV_ROOT": str(dst)}, deadline)
            rec["packages"] = _packages(dst, env)
            if (dst / "apt").is_dir():
                rec["packages"] += _apt_packages(dst)
        _read_only(dst)
        rec["files"], rec["bytes"] = _size(dst)
        rec["status"], rec["finished_at"] = "ready", int(time.time())
        log.append(f"ready: {rec['files']} files, {len(rec['packages'])} packages, {int(time.time()) - started}s")
        _write_record(dst, rec)
        if activate:
            activate_version(env_id, n, slug)
    except Exception as e:  # noqa: BLE001 — the record IS the report; nothing else sees this thread
        rec["status"], rec["finished_at"], rec["error"] = "failed", int(time.time()), str(e)[:500]
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


def activate_version(env_id: str, n: int, slug: str) -> dict:
    dst = version_dir(env_id, n)
    rec = build_record(env_id, n)
    if not dst.is_dir() or not rec or rec.get("status") != "ready":
        raise HTTPException(409, f"version {n} is not a finished build")
    link = active_link(env_id)
    tmp = link.with_name("active.tmp")
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    os.symlink(os.path.join("versions", str(n)), tmp)
    os.replace(tmp, link)                      # atomic: a session mid-turn sees the old or the new, never neither
    ensure_mount(env_id, slug)
    return {"version": n, "status": "ready", "path": mount_path(slug)}


def ensure_mount(env_id: str, slug: str) -> str:
    """The path sessions are told, as a link to the environment's active version. Created on the
    container's rootfs, so it is remade after a restart; idempotent."""
    if not slug_ok(slug):
        raise HTTPException(400, "environment slug is not a path segment")
    if active_version(env_id) is None:
        raise HTTPException(409, "the environment has no built version")
    os.makedirs(ENV_MOUNT, mode=0o755, exist_ok=True)
    try:
        os.chmod(ENV_MOUNT, 0o755)
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
