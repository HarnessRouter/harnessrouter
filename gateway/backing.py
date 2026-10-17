"""Pluggable backing stores for the harness gateway.

The gateway needs three capabilities from the outside world, and nothing else:

  GraphStore   — session/harness/response/api-key records + ownership edges
  BlobStore    — traces, response records, workspace checkpoints, produced files
  SecretStore  — model-provider connections/policies ("bring your own keys")

Two implementations of each:

  local (this file)      — SQLite + filesystem + env/file, zero cloud dependencies. The whole
                           gateway runs on a laptop: HR_BACKING=local (or just leave
                           VG_GATEWAY_URL unset). Point POOL_MGMT_ENDPOINT at a single runner
                           process (the pool is only an identifier-routing proxy in front of
                           runner replicas — the routes are identical).
  vg (backing_vg.py)     — the production AgentStudio infra: vg-gateway (Cosmos graph + Azure
                           blob) and the vault service. Verbatim the code that always ran here.

Selection is one env var: HR_BACKING=vg|local; unset = vg when VG_GATEWAY_URL is set, local
otherwise. The interface is deliberately SEMANTIC (get/upsert/find/add_edge), not query-shaped:
call sites never build backend query strings, so an implementation is free to be a graph, a
relational table, or anything else that can look up records by label + property equality.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import secrets as secrets_mod
import io
import json
import mimetypes
import os
import posixpath
import re
import shutil
import sqlite3
import tarfile
import time
import uuid
from pathlib import Path
from typing import Protocol

import httpx


# ── interfaces ────────────────────────────────────────────────────────────────────
class GraphStore(Protocol):
    async def get(self, vid: str, label: str | None = None) -> dict | None: ...
    async def upsert(self, label: str, vid: str, props: dict, *, raise_on_fail: bool = False) -> None: ...
    async def add_edge(self, label: str, src: str, dst: str) -> None: ...
    async def find(self, label: str, eq: dict | None = None, neq: dict | None = None) -> list[dict]: ...
    async def delete(self, vid: str, label: str | None = None) -> bool:
        """Remove one vertex and its edges; False when there was none (or the label differs)."""
        ...
    async def probe(self) -> None:
        """Raise if the store is unreachable/misconfigured. Used by /readyz, which must FAIL on a
        broken plane — the normal read paths swallow errors and return empty."""
        ...


class BlobStore(Protocol):
    async def get(self, kb: str, file_id: str) -> bytes | None: ...
    async def put(self, kb: str, file_id: str, data: bytes) -> bool: ...
    async def delete(self, kb: str, file_id: str) -> bool: ...
    async def list(self, kb: str, prefix: str, limit: int = 20, cursor: str | None = None) -> dict: ...
    async def probe(self) -> None: ...


class SecretStore(Protocol):
    async def get(self, tenant: str, name: str) -> str | None: ...
    async def delete(self, tenant: str, name: str) -> None:
        """Forget a stored secret; nothing happens when there is none."""
        ...

    async def put(self, tenant: str, name: str, value: str, *,
                  require_encryption: bool = False) -> None:
        """`require_encryption=True` is the caller saying "this is a customer credential, not a
        provider key injected by the operator" — a database connection string, for instance. A
        store that cannot encrypt must raise SecretsNotConfigured rather than write it in the
        clear. Part of the interface, not of one implementation: a datasource must be refused
        the same way whichever backing is configured."""
        ...


class WorkspaceFiles(Protocol):
    """Reading and writing one file inside a session's workspace.

    Two environments, genuinely different storage, one interface:

    * **Self-hosted** — the runner shares this container and the workspace is a live directory on
      the data volume. A write is a write.
    * **Hosted** — sandboxes are ephemeral, so between turns a workspace exists ONLY as the
      checkpoint tarball in blob storage (`sessions/<sid>/workspace.tgz`). A write has to rewrite
      that archive, because there is no filesystem to write to until the next turn hydrates one.

    This exists so an app built on a Harness can own state the agent also edits — the slides kit
    keeps deck.json here — without either side needing to know which deployment it is running in.
    """
    async def read(self, sid: str, path: str) -> bytes | None: ...
    async def write(self, sid: str, path: str, data: bytes) -> bool: ...
    # The three below answer one of the WS_* outcomes rather than a bool: a route has to tell "nothing
    # there" (404) from "already there" (409) from a path it must refuse (400) from storage failing.
    async def delete(self, sid: str, path: str) -> str: ...
    async def mkdir(self, sid: str, path: str) -> str: ...
    async def move(self, sid: str, path: str, to: str) -> str: ...


WS_OK, WS_NOT_FOUND, WS_EXISTS, WS_BAD_PATH, WS_FAILED = "ok", "not_found", "exists", "bad_path", "failed"


class Backing:
    def __init__(self, graph: GraphStore, blob: BlobStore, secrets: SecretStore, mode: str,
                 workspace: "WorkspaceFiles"):
        self.graph, self.blob, self.secrets, self.mode = graph, blob, secrets, mode
        self.workspace = workspace


# ── local: SQLite graph ───────────────────────────────────────────────────────────
class SqliteGraphStore:
    """Vertices/edges in one SQLite file. VG upsert semantics preserved: property() sets the
    listed props and keeps the rest (merge, not replace); edge ids are the same uuid5(src|label|dst)
    so re-adds are idempotent. find() filters by property equality in Python — dev-scale data,
    no json_extract dialect games."""

    def __init__(self, path: str):
        self._path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS vertices (vid TEXT PRIMARY KEY, label TEXT NOT NULL, props TEXT NOT NULL)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_vertices_label ON vertices(label)")
            c.execute("CREATE TABLE IF NOT EXISTS edges (eid TEXT PRIMARY KEY, label TEXT NOT NULL, src TEXT NOT NULL, dst TEXT NOT NULL)")

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self._path, timeout=30)
        c.execute("PRAGMA journal_mode=WAL")
        return c

    async def get(self, vid: str, label: str | None = None) -> dict | None:
        def _do():
            with self._conn() as c:
                row = c.execute("SELECT vid, label, props FROM vertices WHERE vid=?", (vid,)).fetchone()
            if not row:
                return None
            if label is not None and row[1] != label:
                return None      # label filter is load-bearing where the id is caller-controlled
            return {"id": row[0], **json.loads(row[2])}
        return await asyncio.to_thread(_do)

    async def upsert(self, label: str, vid: str, props: dict, *, raise_on_fail: bool = False) -> None:
        clean = {k: str(v) for k, v in props.items()}   # VG stores string props; keep parity

        def _do():
            with self._conn() as c:
                row = c.execute("SELECT props FROM vertices WHERE vid=?", (vid,)).fetchone()
                merged = {**(json.loads(row[0]) if row else {}), **clean}
                c.execute("INSERT INTO vertices(vid,label,props) VALUES(?,?,?) "
                          "ON CONFLICT(vid) DO UPDATE SET props=excluded.props",
                          (vid, label, json.dumps(merged)))
        try:
            await asyncio.to_thread(_do)
        except Exception:
            if raise_on_fail:
                raise RuntimeError("graph write failed")

    async def add_edge(self, label: str, src: str, dst: str) -> None:
        if not (src and dst):
            return
        eid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{src}|{label}|{dst}"))

        def _do():
            with self._conn() as c:
                c.execute("INSERT OR IGNORE INTO edges(eid,label,src,dst) VALUES(?,?,?,?)",
                          (eid, label, src, dst))
        try:
            await asyncio.to_thread(_do)
        except Exception:  # noqa: BLE001 — best-effort, matches VG edge semantics
            pass

    async def delete(self, vid: str, label: str | None = None) -> bool:
        def _do():
            with self._conn() as c:
                row = c.execute("SELECT label FROM vertices WHERE vid=?", (vid,)).fetchone()
                if not row or (label is not None and row[0] != label):
                    return False
                c.execute("DELETE FROM vertices WHERE vid=?", (vid,))
                c.execute("DELETE FROM edges WHERE src=? OR dst=?", (vid, vid))
                return True
        try:
            return await asyncio.to_thread(_do)
        except Exception:  # noqa: BLE001
            return False

    async def find(self, label: str, eq: dict | None = None, neq: dict | None = None) -> list[dict]:
        def _do():
            with self._conn() as c:
                rows = c.execute("SELECT vid, props FROM vertices WHERE label=?", (label,)).fetchall()
            out = []
            for vid, props_json in rows:
                p = json.loads(props_json)
                if eq and any(str(p.get(k, "")) != str(v) for k, v in eq.items()):
                    continue
                if neq and any(str(p.get(k, "")) == str(v) for k, v in neq.items()):
                    continue
                out.append({"id": vid, **p})
            return out
        try:
            return await asyncio.to_thread(_do)
        except Exception:  # noqa: BLE001
            return []

    async def probe(self) -> None:
        def _do():
            with self._conn() as c:
                c.execute("SELECT 1 FROM vertices LIMIT 1").fetchone()
        await asyncio.to_thread(_do)


# ── local: filesystem blobs ───────────────────────────────────────────────────────
class FileBlobStore:
    """Objects as plain files under {root}/{kb}/{file_id}. Listing is ascending-lexical over the
    relative keys — the SAME ordering contract the trace machinery relies on from Azure blob
    listing (inverted-timestamp keys ⇒ newest-first)."""

    def __init__(self, root: str):
        self._root = Path(root)

    def _p(self, kb: str, file_id: str) -> Path:
        p = (self._root / kb / file_id).resolve()
        base = (self._root / kb).resolve()
        if not str(p).startswith(str(base)):        # refuse path escape
            raise ValueError(f"blob id escapes store: {file_id!r}")
        return p

    async def get(self, kb: str, file_id: str) -> bytes | None:
        def _do():
            try:
                return self._p(kb, file_id).read_bytes()
            except (OSError, ValueError):
                return None
        return await asyncio.to_thread(_do)

    async def put(self, kb: str, file_id: str, data: bytes) -> bool:
        if not data:
            return False

        def _do():
            try:
                p = self._p(kb, file_id)
                p.parent.mkdir(parents=True, exist_ok=True)
                tmp = p.with_suffix(p.suffix + ".tmp")
                tmp.write_bytes(data)
                tmp.replace(p)                      # atomic: a torn write never replaces a good blob
                return True
            except (OSError, ValueError):
                return False
        return await asyncio.to_thread(_do)

    async def delete(self, kb: str, file_id: str) -> bool:
        def _do():
            try:
                path = self._p(kb, file_id)
                path.unlink(missing_ok=True)
            except (OSError, ValueError):
                return False
            # The directories a key's slashes created go with the last object in them, up to the
            # store root. A blob store has no directories; this one only borrows them from the file
            # system, and left alone they outlive every object: hr-test held 3,696 empty
            # sessions/<sid>/ shells on 2026-09-16, one per session ever deleted. rmdir refuses a
            # directory that still holds anything, which is the whole check.
            base = (self._root / kb).resolve()
            for parent in path.parents:
                if parent == base or base not in parent.parents:
                    break
                try:
                    parent.rmdir()
                except OSError:
                    break
            return True
        return await asyncio.to_thread(_do)

    async def purge(self, kb: str, prefix: str) -> None:
        """Remove everything under a folder-shaped prefix ("sessions/<sid>/"), including the
        temporary files a torn write leaves and `list` does not show. A deleted session's folder
        held a lone `changed.json.tmp` after every listed object was gone (hr-test copy,
        2026-10-08)."""
        def _do():
            base = (self._root / kb).resolve()
            if not prefix.endswith("/") or prefix.strip("/") == "":
                return
            top = (base / prefix).resolve()
            if top == base or base not in top.parents or not top.is_dir():
                return
            shutil.rmtree(top, ignore_errors=True)
            for parent in top.parents:
                if parent == base or base not in parent.parents:
                    break
                try:
                    parent.rmdir()
                except OSError:
                    break
        await asyncio.to_thread(_do)

    async def list(self, kb: str, prefix: str, limit: int = 20, cursor: str | None = None) -> dict:
        # Walk only the subtree the prefix names: everything before its last "/" is a directory
        # under the store, the rest a name prefix inside it. Walking the whole store cost every
        # blob on every call, and a paged listing repeated the walk per page: with 15k blobs on a
        # self-hosted volume one turns read took 55 s and the gateway sat at 150% CPU (2026-09-06).
        def _do():
            base = (self._root / kb).resolve()
            dir_part, _, _ = prefix.rpartition("/")
            top = (base / dir_part).resolve() if dir_part else base
            if not str(top).startswith(str(base)) or not top.is_dir():   # escape or nothing there
                return {"items": [], "cursor": None}
            root_len = len(str(base)) + 1
            keys: list[str] = []
            for root, _dirs, files in os.walk(top):
                rel = root[root_len:].replace(os.sep, "/") if len(root) > root_len else ""
                for name in files:
                    if name.endswith(".tmp"):
                        continue
                    key = f"{rel}/{name}" if rel else name
                    if key.startswith(prefix) and (not cursor or key > cursor):
                        keys.append(key)
            keys.sort()
            page = keys[:limit]
            nxt = page[-1] if len(keys) > limit else None
            return {"items": [{"file_id": k} for k in page], "cursor": nxt}
        return await asyncio.to_thread(_do)

    async def probe(self) -> None:
        def _do():
            self._root.mkdir(parents=True, exist_ok=True)
            if not os.access(self._root, os.W_OK):
                raise RuntimeError(f"blob root not writable: {self._root}")
        await asyncio.to_thread(_do)


# ── local: env/file secrets ("bring your own provider keys") ──────────────────────
class SecretsNotConfigured(RuntimeError):
    """Raised when a secret must be written but there is nowhere safe to write it.

    Deliberately an error rather than a fallback. A provider key injected read-only through the
    environment is one risk; a customer's production database connection string written to a file
    in plaintext is another entirely, and the difference is not something to decide silently on
    the operator's behalf."""


class FileSecretStore:
    """Reads HR_SECRET_{TENANT}_{NAME} from the environment first (read-only injection — the
    open-repo way to supply provider credentials without any vault), then falls back to files
    under {root}/{tenant}/{name}.

    Files are ENCRYPTED when HR_SECRET_KEY is set: AES-256-GCM under a key derived from it, with
    a random nonce per write, stored as `hrenc1:<b64 nonce||ciphertext>`. Reads accept both forms,
    so a store written before this existed keeps working and re-encrypts on its next write.

    Without HR_SECRET_KEY, `put(..., require_encryption=True)` REFUSES. That is the whole point:
    the caller that stores a database credential says so, and on an instance with no key it gets
    an error telling the operator what to set, instead of a plaintext file nobody knew about."""

    _MAGIC = "hrenc1:"

    def __init__(self, root: str):
        self._root = Path(root)
        self._key = self._derive(os.environ.get("HR_SECRET_KEY", ""))

    @property
    def encrypts(self) -> bool:
        return self._key is not None

    @staticmethod
    def _derive(passphrase: str) -> bytes | None:
        """A 32-byte key from the operator's passphrase. Scrypt with a fixed salt: the salt's job
        is to stop cross-deployment rainbow tables, and there is nowhere to keep a random one that
        would not sit beside the ciphertext anyway."""
        if not passphrase:
            return None
        return hashlib.scrypt(passphrase.encode(), salt=b"harnessrouter.secret.v1",
                              n=2 ** 14, r=8, p=1, dklen=32)

    def _seal(self, value: str) -> str:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        nonce = secrets_mod.token_bytes(12)
        blob = nonce + AESGCM(self._key).encrypt(nonce, value.encode(), None)
        return self._MAGIC + base64.b64encode(blob).decode()

    def _open(self, raw: str) -> str:
        if not raw.startswith(self._MAGIC):
            return raw                      # written before encryption existed
        if self._key is None:
            raise SecretsNotConfigured(
                "This secret is encrypted but HR_SECRET_KEY is not set. Set it to the passphrase "
                "used when the secret was stored.")
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        blob = base64.b64decode(raw[len(self._MAGIC):])
        return AESGCM(self._key).decrypt(blob[:12], blob[12:], None).decode()

    @staticmethod
    def _env_key(tenant: str, name: str) -> str:
        return "HR_SECRET_" + re.sub(r"[^A-Za-z0-9]", "_", f"{tenant}_{name}").upper()

    def _p(self, tenant: str, name: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", name)
        return self._root / re.sub(r"[^A-Za-z0-9._-]", "_", tenant) / safe

    async def get(self, tenant: str, name: str) -> str | None:
        v = os.environ.get(self._env_key(tenant, name))
        if v:
            return v

        def _do():
            try:
                return self._p(tenant, name).read_text()
            except OSError:
                return None
        raw = await asyncio.to_thread(_do)
        return self._open(raw) if raw is not None else None

    async def put(self, tenant: str, name: str, value: str, *, require_encryption: bool = False) -> None:
        if require_encryption and self._key is None:
            raise SecretsNotConfigured(
                "Refusing to store this credential: HR_SECRET_KEY is not set, so it could only be "
                "written to disk in plaintext. Set HR_SECRET_KEY to a passphrase and restart.")
        body = self._seal(value) if self._key is not None else value

        def _do():
            p = self._p(tenant, name)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body)
            with contextlib.suppress(OSError):
                p.chmod(0o600)              # belt to the encryption's braces
        await asyncio.to_thread(_do)

    async def delete(self, tenant: str, name: str) -> None:
        def _do():
            with contextlib.suppress(OSError):
                self._p(tenant, name).unlink()
        await asyncio.to_thread(_do)

    async def blank(self) -> list[tuple[str, str]]:
        """Every stored secret whose value is empty, as (tenant, name). Before 0.32.0 a removed
        credential was overwritten with nothing rather than deleted; the retention sweep removes
        those files. A value that cannot be opened (encrypted, and no key) is not reported."""
        def _do():
            out: list[tuple[str, str]] = []
            if not self._root.is_dir():
                return out
            for tdir in sorted(self._root.iterdir()):
                if not tdir.is_dir():
                    continue
                for f in sorted(tdir.iterdir()):
                    if not f.is_file():
                        continue
                    try:
                        if self._open(f.read_text()) == "":
                            out.append((tdir.name, f.name))
                    except Exception:  # noqa: BLE001 — unreadable is not empty
                        continue
            return out
        return await asyncio.to_thread(_do)


# ── selection ─────────────────────────────────────────────────────────────────────

# ── workspace files ───────────────────────────────────────────────────────────────
def _safe_member(path: str) -> str | None:
    """A workspace-relative path, or None if it tries to leave the workspace.

    Rejected rather than sanitised: a path that needed cleaning was not the path the caller meant,
    and silently writing somewhere else is worse than refusing."""
    p = (path or "").strip().lstrip("/")
    if not p or p != posixpath.normpath(p) or p.startswith("../") or "\\" in p:
        return None
    return p


def app_capture_id(member: str) -> str:
    """The durable id of an APP's copy of one workspace path. Derived from the path, so saving the
    same file again replaces its one blob, and a delete's tombstone (see the gateway's
    _newest_captures) lands on the same id and replaces the app's copy rather than sitting beside it."""
    return "cfile_" + hashlib.sha256(f"app:{member}".encode()).hexdigest()[:32]


def _tar_name(m: tarfile.TarInfo) -> str:
    return m.name[2:] if m.name.startswith("./") else m.name.rstrip("/")


def _under(name: str, member: str) -> bool:
    return name == member or name.startswith(member + "/")


def tar_change(raw: bytes | None, op: str, member: str, to: str = "") -> tuple[str, bytes | None]:
    """Apply delete, mkdir or move to a checkpoint tarball → (WS_* outcome, the new archive or None
    when nothing changed).

    A path names a file or a directory, and a directory is everything under it: a tarball made by
    `tar -C ws .` lists the directory's own entry, but one rewritten by `write` may hold only the
    files, so both shapes count as the directory existing. The base that nests its workspace
    (`.harness/agent-subdir`, nanobot) keeps the user's files one level down, so a path is looked
    for there first and at the session root second, the order the runner's GET /file uses, and a
    move stays on the side its source was found."""
    # (entry, its path without "./", its bytes): the bytes travel WITH the entry, so a renamed
    # member keeps its own content
    entries: list[tuple[tarfile.TarInfo, str, bytes | None]] = []
    if raw:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as src:
            for m in src.getmembers():
                f = src.extractfile(m) if m.isfile() else None
                entries.append((m, _tar_name(m), f.read() if f else None))
    sub = next((d.decode(errors="replace").strip() for _m, n, d in entries
                if n == ".harness/agent-subdir" and d), "")
    if sub and (_safe_member(sub) != sub or "/" in sub):
        sub = ""

    def _exists(p: str) -> bool:
        return any(_under(n, p) for _m, n, _d in entries)

    found = next((c for c in ([f"{sub}/{member}"] if sub else []) + [member] if _exists(c)), "")
    if op == "delete":
        if not found:
            return WS_NOT_FOUND, None
        entries = [e for e in entries if not _under(e[1], found)]
    elif op == "mkdir":
        if found:
            is_file = any(n == found and m.isfile() for m, n, _d in entries)
            return (WS_EXISTS, None) if is_file else (WS_OK, None)
        d = tarfile.TarInfo(member)
        d.type, d.mode, d.mtime = tarfile.DIRTYPE, 0o755, int(time.time())
        entries.append((d, member, None))
    elif op == "move":
        if not found:
            return WS_NOT_FOUND, None
        dst = f"{sub}/{to}" if sub and found != member else to
        if _under(dst, found):
            return WS_BAD_PATH, None
        if _exists(dst):
            return WS_EXISTS, None
        for m, n, _d in entries:
            if _under(n, found):
                m.name = ("./" if m.name.startswith("./") else "") + dst + n[len(found):]
    else:
        raise ValueError(op)
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as dst_tar:
        for m, _n, data in entries:
            dst_tar.addfile(m, io.BytesIO(data or b"") if m.isfile() else None)
    return WS_OK, out.getvalue()


class RunnerWorkspaceFiles:
    """Self-hosted: a session's workspace is a live directory on the data volume, and the RUNNER is
    the only principal that touches it. Behind the write-wall each session directory belongs to that
    session's own uid and the product deliberately cannot read or write there (see _isolate_session
    in the runner), so a live read or write goes through the runner, which acts as the session,
    rather than through this process's own filesystem access. One door, whether the wall is up or
    not: the runner is beside the gateway in every self-hosted deployment.

    Live, unlike the checkpoint the listing route reads: an app sees a file the moment a tool call
    creates it, rather than when the turn ends."""

    def __init__(self, endpoint: str, key: str, blob=None, kb: str = "", ckpt_kb: str = "", key_for=None):
        self.endpoint = (endpoint or "").rstrip("/")
        self.key = key
        self.blob, self.kb = blob, kb
        self.ckpt_kb, self.key_for = ckpt_kb, key_for
        self._client: httpx.AsyncClient | None = None

    def _c(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=5.0))
        return self._client

    def _headers(self) -> dict:
        return {"X-Harness-Internal": self.key} if self.key else {}

    async def read(self, sid: str, path: str) -> bytes | None:
        member = _safe_member(path)
        if not member or not self.endpoint:
            return None
        try:
            r = await self._c().get(f"{self.endpoint}/file", params={"identifier": sid, "path": member},
                                    headers=self._headers())
        except Exception:      # noqa: BLE001 — a runner that is down reads as "no file", never a 500
            return None
        return r.content if r.status_code == 200 else None

    async def write(self, sid: str, path: str, data: bytes) -> bool:
        member = _safe_member(path)
        if not member or not self.endpoint:
            return False
        try:
            r = await self._c().put(f"{self.endpoint}/file", params={"identifier": sid, "path": member},
                                    headers={**self._headers(), "content-type": "application/octet-stream"},
                                    content=data)
        except Exception:      # noqa: BLE001
            return False
        if r.status_code != 200:
            return False
        await self._capture(sid, member, data)
        return True

    async def delete(self, sid: str, path: str) -> str:
        return await self._change(sid, "delete", path)

    async def mkdir(self, sid: str, path: str) -> str:
        return await self._change(sid, "mkdir", path)

    async def move(self, sid: str, path: str, to: str) -> str:
        return await self._change(sid, "move", path, to)

    async def _change(self, sid: str, op: str, path: str, to: str = "") -> str:
        """The live directory first, through the runner (which acts as the session), then the
        checkpoint tarball.

        The checkpoint is the second half because the live directory is not the only copy: it is
        reaped after HR_WORKSPACE_TTL_HOURS, and a sandbox that does not hold the last checkpoint
        is wiped and restored from that tarball. A delete made only in the live directory would
        come back on that restore, and a move would come back as two copies. `write` closes the
        same hole with a per-file capture; a delete, a directory or a rename has no file to
        capture, so the archive itself is changed, as the hosted backing does."""
        member = _safe_member(path)
        dest = _safe_member(to) if op == "move" else ""
        if not member or (op == "move" and not dest) or not self.endpoint:
            return WS_BAD_PATH
        params = {"identifier": sid, "path": member, **({"to": dest} if op == "move" else {})}
        url = f"{self.endpoint}/file" + ("" if op == "delete" else f"/{op}")
        try:
            r = await self._c().request("DELETE" if op == "delete" else "POST", url, params=params,
                                        headers=self._headers())
        except Exception:      # noqa: BLE001
            return WS_FAILED
        outcome = {200: WS_OK, 404: WS_NOT_FOUND, 409: WS_EXISTS, 400: WS_BAD_PATH}.get(r.status_code, WS_FAILED)
        if outcome != WS_OK:
            return outcome
        # The runner answers where it found the path (the nesting base's user files live one level
        # down), which is also where the path sits in the archive.
        try:
            got = r.json()
        except ValueError:
            got = {}
        await self._change_checkpoint(sid, op, str(got.get("path") or member), str(got.get("to") or dest))
        return WS_OK

    async def _change_checkpoint(self, sid: str, op: str, member: str, to: str) -> None:
        if not self.blob or not self.ckpt_kb or not self.key_for:
            return
        key = self.key_for(sid)
        try:
            raw = await self.blob.get(self.ckpt_kb, key)
            if not raw:
                return            # no turn has ended yet: the live directory is the only copy
            outcome, tar = await asyncio.to_thread(tar_change, raw, op, member, to)
            if outcome == WS_NOT_FOUND or (outcome == WS_OK and tar is None):
                return            # not in the checkpoint (made since it was taken), or already so
            if outcome == WS_OK and await self.blob.put(self.ckpt_kb, key, tar):
                return
            why = outcome if outcome != WS_OK else "store refused"
        except Exception as e:   # noqa: BLE001
            why = f"{type(e).__name__}: {e}"
        # The live change stands, but a restore from this checkpoint would undo it. Say so.
        print(f"[workspace] checkpoint {op} not applied sid={sid} path={member}: {why}", flush=True)

    async def _capture(self, sid: str, member: str, data: bytes) -> None:
        """Persist the app's copy of this file so it outlives the live directory.

        THIS is why the class takes a blob store. The live workspace is reaped after
        HR_WORKSPACE_TTL_HOURS and is only ever refreshed by a TURN's checkpoint, so a file an app
        wrote BETWEEN turns lived in exactly one place and was deleted with it: a sheet somebody
        typed into and never asked the agent about again came back empty, and so did every agent
        column they had bound by hand. The hosted sibling writes straight into the durable tarball
        and never had the hole, which is the tell — one Protocol, two meanings for `write`.

        The id is derived from the path, so a sheet saved a thousand times keeps ONE blob instead
        of leaking one per save. `written_at` is what makes the read side deterministic: the
        agent's own capture of the same filename carries one too, and the newer of the two wins
        rather than whichever the blob listing happened to return last."""
        if not self.blob or not self.kb:
            return
        await put_app_capture(self.blob, self.kb, sid, member, data)


async def put_app_capture(blob, kb: str, sid: str, member: str, data: bytes) -> bool:
    """Store an app's durable copy of one workspace file (RunnerWorkspaceFiles._capture says why).
    Also how a move carries an app's copy to the file's new name."""
    cfile = app_capture_id(member)
    meta = json.dumps({"filename": member,
                       "media_type": mimetypes.guess_type(member)[0] or "application/octet-stream",
                       "written_at": time.time(),
                       "source": "app"}).encode()
    try:
        if await blob.put(kb, f"containers/{sid}/{cfile}", data):
            await blob.put(kb, f"containers/{sid}/{cfile}.meta", meta)
            return True
    except Exception as e:   # noqa: BLE001
        print(f"[workspace] durable capture failed sid={sid} path={member}: {e}", flush=True)
        return False
    # A live write that was not captured is the old silent-loss shape. Say so rather than
    # letting it look like a clean save.
    print(f"[workspace] durable capture rejected sid={sid} path={member}", flush=True)
    return False


class CheckpointWorkspaceFiles:
    """Hosted: between turns the workspace is only the checkpoint tarball, so a write rewrites
    that archive — copy every member across, substituting the one being written.

    Rewriting rather than appending is deliberate: tar allows duplicate names and readers take the
    LAST one, so appending would work until something read the archive differently, and the bug
    would be a stale file appearing at random."""

    def __init__(self, blob, kb: str, key_for):
        self.blob, self.kb, self.key_for = blob, kb, key_for

    async def read(self, sid: str, path: str) -> bytes | None:
        member = _safe_member(path)
        if not member:
            return None
        raw = await self.blob.get(self.kb, self.key_for(sid))
        if not raw:
            return None

        def _extract() -> bytes | None:
            with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:
                for name in (member, f"./{member}"):
                    try:
                        f = tf.extractfile(name)
                    except KeyError:
                        continue
                    if f:
                        return f.read()
            return None
        try:
            return await asyncio.to_thread(_extract)
        except Exception:      # noqa: BLE001 — a corrupt archive reads as "not there"
            return None

    async def write(self, sid: str, path: str, data: bytes) -> bool:
        member = _safe_member(path)
        if not member:
            return False
        key = self.key_for(sid)
        raw = await self.blob.get(self.kb, key)

        def _rewrite() -> bytes:
            out = io.BytesIO()
            wrote = False
            with tarfile.open(fileobj=out, mode="w:gz") as dst:
                if raw:
                    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as src:
                        for m in src.getmembers():
                            name = m.name[2:] if m.name.startswith("./") else m.name
                            if name == member:
                                continue          # replaced below
                            f = src.extractfile(m) if m.isfile() else None
                            dst.addfile(m, f)
                info = tarfile.TarInfo(member)
                info.size = len(data)
                info.mtime = int(time.time())
                info.mode = 0o644
                dst.addfile(info, io.BytesIO(data))
                wrote = True
            return out.getvalue() if wrote else b""

        try:
            tar = await asyncio.to_thread(_rewrite)
        except Exception:      # noqa: BLE001
            return False
        return bool(tar) and await self.blob.put(self.kb, key, tar)

    async def delete(self, sid: str, path: str) -> str:
        return await self._change(sid, "delete", path)

    async def mkdir(self, sid: str, path: str) -> str:
        return await self._change(sid, "mkdir", path)

    async def move(self, sid: str, path: str, to: str) -> str:
        return await self._change(sid, "move", path, to)

    async def _change(self, sid: str, op: str, path: str, to: str = "") -> str:
        """Rewrite the archive with the change applied, as `write` does: between turns the archive
        IS the workspace."""
        member = _safe_member(path)
        dest = _safe_member(to) if op == "move" else ""
        if not member or (op == "move" and not dest):
            return WS_BAD_PATH
        key = self.key_for(sid)
        try:
            raw = await self.blob.get(self.kb, key)
            outcome, tar = await asyncio.to_thread(tar_change, raw, op, member, dest)
        except Exception:      # noqa: BLE001
            return WS_FAILED
        if outcome != WS_OK or tar is None:
            return outcome
        return WS_OK if await self.blob.put(self.kb, key, tar) else WS_FAILED


def make_backing(*, client_getter, vg_url: str, vg_key: str, vg_tenant: str,
                 vault_url: str, vault_key: str) -> Backing:
    """Build the configured backing. HR_BACKING=vg|local; unset ⇒ vg when VG_GATEWAY_URL is
    configured (production), local otherwise (a laptop clone works with zero env)."""
    mode = os.environ.get("HR_BACKING", "").strip().lower() or ("vg" if vg_url else "local")
    # Where a session's workspace actually lives, which is the one thing that differs most between
    # the two deployments: a live directory the runner owns and serves, or a checkpoint tarball
    # that is the only copy between turns.
    ws_key = lambda sid: f"sessions/{sid}/workspace.tgz"   # noqa: E731 — matches gateway._ws_blob
    if mode == "vg":
        from backing_vg import VgBlobStore, VgGraphStore, VaultSecretStore
        blob = VgBlobStore(client_getter, vg_url, vg_key)
        return Backing(
            graph=VgGraphStore(client_getter, vg_url, vg_key, vg_tenant),
            blob=blob,
            secrets=VaultSecretStore(client_getter, vault_url, vault_key),
            mode="vg",
            workspace=CheckpointWorkspaceFiles(blob, os.environ.get("HARNESS_BLOB_KB", "harness-sessions"), ws_key))
    data = os.environ.get("HR_DATA_DIR", ".hr-data")
    local_blob = FileBlobStore(os.path.join(data, "blobs"))
    return Backing(
        graph=SqliteGraphStore(os.path.join(data, "graph.db")),
        blob=local_blob,
        secrets=FileSecretStore(os.path.join(data, "secrets")),
        mode="local",
        workspace=RunnerWorkspaceFiles(os.environ.get("POOL_MGMT_ENDPOINT", "http://127.0.0.1:8081"),
                                       os.environ.get("HARNESS_INTERNAL_KEY", ""),
                                       local_blob,
                                       os.environ.get("HARNESS_RESP_BLOB_KB", "harness-responses"),
                                       os.environ.get("HARNESS_BLOB_KB", "harness-sessions"), ws_key))
