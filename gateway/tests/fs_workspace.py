"""A workspace that IS a directory, for tests.

Production has two: the runner-backed one self-hosted (the session directory belongs to the
session's own uid, so only the runner may touch it) and the checkpoint-backed one on the hosted
side. Neither is a plain directory this process can write, and a media test wants to assert on
real bytes on real disk. So the double lives here rather than a third implementation living in
the product for tests to borrow."""
import asyncio
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from backing import _safe_member  # noqa: E402


class FsWorkspaceFiles:
    def __init__(self, root: str):
        self.root = root

    def _path(self, sid: str, path: str) -> str | None:
        member = _safe_member(path)
        if not member or not sid or "/" in sid or sid in (".", ".."):
            return None
        base = os.path.realpath(os.path.join(self.root, sid))
        full = os.path.realpath(os.path.join(base, member))
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
                tmp = f"{full}.tmp"
                with open(tmp, "wb") as fh:
                    fh.write(data)
                os.replace(tmp, full)
                return True
            except OSError:
                return False
        return await asyncio.to_thread(_put)
