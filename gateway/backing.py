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
import os
import pathlib
import posixpath
import re
import sqlite3
import tarfile
import time
import uuid
from pathlib import Path
from typing import Protocol


# ── interfaces ────────────────────────────────────────────────────────────────────
class GraphStore(Protocol):
    async def get(self, vid: str, label: str | None = None) -> dict | None: ...
    async def upsert(self, label: str, vid: str, props: dict, *, raise_on_fail: bool = False) -> None: ...
    async def add_edge(self, label: str, src: str, dst: str) -> None: ...
    async def find(self, label: str, eq: dict | None = None, neq: dict | None = None) -> list[dict]: ...
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
    async def put(self, tenant: str, name: str, value: str) -> None: ...


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
                self._p(kb, file_id).unlink(missing_ok=True)
                return True
            except (OSError, ValueError):
                return False
        return await asyncio.to_thread(_do)

    async def list(self, kb: str, prefix: str, limit: int = 20, cursor: str | None = None) -> dict:
        def _do():
            base = self._root / kb
            if not base.is_dir():
                return {"items": [], "cursor": None}
            keys = sorted(str(f.relative_to(base)) for f in base.rglob("*")
                          if f.is_file() and not f.name.endswith(".tmp")
                          and str(f.relative_to(base)).startswith(prefix))
            if cursor:
                keys = [k for k in keys if k > cursor]
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


class LocalWorkspaceFiles:
    """Self-hosted: the workspace is a live directory on the data volume, shared with the runner
    in this container. Writes land where the agent will read them on its next turn."""

    def __init__(self, root: str):
        self.root = root

    def _path(self, sid: str, path: str) -> str | None:
        member = _safe_member(path)
        if not member or not sid or "/" in sid or sid in (".", ".."):
            return None
        base = os.path.realpath(os.path.join(self.root, sid))
        full = os.path.realpath(os.path.join(base, member))
        # Resolve first, then prove containment: checking the input for '..' misses symlinks.
        return full if full == base or full.startswith(base + os.sep) else None

    async def read(self, sid: str, path: str) -> bytes | None:
        full = self._path(sid, path)
        if not full:
            return None
        try:
            return await asyncio.to_thread(pathlib.Path(full).read_bytes)
        except OSError:
            return None

    async def write(self, sid: str, path: str, data: bytes) -> bool:
        full = self._path(sid, path)
        if not full:
            return False

        def _put() -> bool:
            try:
                os.makedirs(os.path.dirname(full), exist_ok=True)
                # Write beside, then rename: a reader (the agent, mid-turn) sees either the old
                # file or the new one, never a half-written one.
                tmp = f"{full}.tmp-{uuid.uuid4().hex[:8]}"
                with open(tmp, "wb") as fh:
                    fh.write(data)
                os.replace(tmp, full)
                return True
            except OSError:
                return False
        return await asyncio.to_thread(_put)


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


def make_backing(*, client_getter, vg_url: str, vg_key: str, vg_tenant: str,
                 vault_url: str, vault_key: str) -> Backing:
    """Build the configured backing. HR_BACKING=vg|local; unset ⇒ vg when VG_GATEWAY_URL is
    configured (production), local otherwise (a laptop clone works with zero env)."""
    mode = os.environ.get("HR_BACKING", "").strip().lower() or ("vg" if vg_url else "local")
    # Where a session's workspace actually lives, which is the one thing that differs most between
    # the two deployments: a live directory this container shares with the runner, or a checkpoint
    # tarball that is the only copy between turns.
    ws_root = os.environ.get("HARNESS_WORKSPACE", "/data/workspaces")
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
    return Backing(
        graph=SqliteGraphStore(os.path.join(data, "graph.db")),
        blob=FileBlobStore(os.path.join(data, "blobs")),
        secrets=FileSecretStore(os.path.join(data, "secrets")),
        mode="local",
        workspace=LocalWorkspaceFiles(ws_root))
