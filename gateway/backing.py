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
import json
import os
import re
import sqlite3
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


class Backing:
    def __init__(self, graph: GraphStore, blob: BlobStore, secrets: SecretStore, mode: str):
        self.graph, self.blob, self.secrets, self.mode = graph, blob, secrets, mode


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
class FileSecretStore:
    """Reads HR_SECRET_{TENANT}_{NAME} from the environment first (read-only injection — the
    open-repo way to supply provider credentials without any vault), then falls back to plain
    files under {root}/{tenant}/{name}. Writes (e.g. per-org MCP tokens) always go to files."""

    def __init__(self, root: str):
        self._root = Path(root)

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
        return await asyncio.to_thread(_do)

    async def put(self, tenant: str, name: str, value: str) -> None:
        def _do():
            p = self._p(tenant, name)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(value)
        await asyncio.to_thread(_do)


# ── selection ─────────────────────────────────────────────────────────────────────
def make_backing(*, client_getter, vg_url: str, vg_key: str, vg_tenant: str,
                 vault_url: str, vault_key: str) -> Backing:
    """Build the configured backing. HR_BACKING=vg|local; unset ⇒ vg when VG_GATEWAY_URL is
    configured (production), local otherwise (a laptop clone works with zero env)."""
    mode = os.environ.get("HR_BACKING", "").strip().lower() or ("vg" if vg_url else "local")
    if mode == "vg":
        from backing_vg import VgBlobStore, VgGraphStore, VaultSecretStore
        return Backing(
            graph=VgGraphStore(client_getter, vg_url, vg_key, vg_tenant),
            blob=VgBlobStore(client_getter, vg_url, vg_key),
            secrets=VaultSecretStore(client_getter, vault_url, vault_key),
            mode="vg")
    data = os.environ.get("HR_DATA_DIR", ".hr-data")
    return Backing(
        graph=SqliteGraphStore(os.path.join(data, "graph.db")),
        blob=FileBlobStore(os.path.join(data, "blobs")),
        secrets=FileSecretStore(os.path.join(data, "secrets")),
        mode="local")
