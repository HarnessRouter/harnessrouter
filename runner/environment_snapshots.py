"""Internal environment transfer between runners with identical images and data paths."""
import asyncio
import contextlib
import hashlib
import os
import pathlib
import shutil
import tarfile
import tempfile

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

import environments as E


def snapshot(env_id: str) -> str:
    with E._source_lock(env_id), E._builds_lock:
        if any(k.startswith(env_id + ":") and t.is_alive() for k, t in E._builds.items()):
            raise HTTPException(409, "environment build is still running")
        root = E.env_dir(env_id)
        if not root.is_dir():
            raise HTTPException(404, "environment does not exist")
        fd, path = tempfile.mkstemp(suffix=".tar.gz")
        os.close(fd)
        try:
            with tarfile.open(path, "w:gz", dereference=False) as archive:
                archive.add(root, arcname="environment")
        except BaseException:
            os.unlink(path)
            raise
        return path


def restore(env_id: str, path: str) -> dict:
    root = E.env_dir(env_id)
    with open(path, "rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    root.parent.mkdir(parents=True, exist_ok=True)
    with E._source_lock(env_id), E._builds_lock:
        if root.exists():
            marker = root / ".hr-restored-snapshot"
            if marker.is_file() and not marker.is_symlink() and marker.read_text() == digest:
                return {"id": env_id, "restored": True, "active": E.active_version(env_id)}
            raise HTTPException(409, "environment already exists on this runner")
        with tempfile.TemporaryDirectory(prefix=".restore-", dir=root.parent) as scratch:
            staging = pathlib.Path(scratch)
            with tarfile.open(path, "r:gz") as archive:
                members = archive.getmembers()
                names = set()
                for member in members:
                    name = pathlib.PurePosixPath(member.name)
                    if (name.is_absolute() or ".." in name.parts or not name.parts
                            or name.parts[0] != "environment" or "\\" in member.name):
                        raise HTTPException(400, "snapshot path escapes the environment")
                    normalized = str(name)
                    if normalized in names or not (member.isdir() or member.isreg() or member.issym() or member.islnk()):
                        raise HTTPException(400, "unsupported snapshot entry")
                    names.add(normalized)
                # Files are extracted before links. Archive ownership and special modes are
                # discarded, and no extraction can follow a link into another root path.
                for member in members:
                    target = staging / member.name
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                    elif member.isreg():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with archive.extractfile(member) as source, target.open("xb") as dest:
                            shutil.copyfileobj(source, dest)
                        target.chmod(member.mode & 0o777)
                for member in members:
                    if member.islnk():
                        source = staging / member.linkname
                        if not source.resolve().is_relative_to(staging) or not source.is_file() or source.is_symlink():
                            raise HTTPException(400, "invalid snapshot hardlink")
                        target = staging / member.name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        os.link(source, target)
                for member in members:
                    if member.issym():
                        target = staging / member.name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        os.symlink(member.linkname, target)
            captured = staging / "environment"
            active = captured / "active"
            if active.is_symlink():
                value = pathlib.PurePosixPath(os.readlink(active))
                if (len(value.parts) != 2 or value.parts[0] != "versions"
                        or not value.parts[1].isdigit()):
                    raise HTTPException(400, "invalid active version in snapshot")
            elif active.exists():
                raise HTTPException(400, "active version must be a link")
            for name in ("source", "versions"):
                directory = captured / name
                if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
                    raise HTTPException(400, f"{name} must be a directory")
            # Claim a local identity before publishing the captured tree. A restore is
            # admitted only after all layers regain their local read-only permissions.
            E._claim(env_id)
            try:
                gid = E.env_gid(env_id)
                if gid is not None:
                    os.chown(captured, 0, gid)
                    os.chmod(captured, 0o750)
                source = captured / "source"
                if source.is_symlink():
                    raise HTTPException(400, "source must be a directory")
                if source.exists():
                    os.chmod(source, 0o700)
                versions = captured / "versions"
                if versions.is_symlink():
                    raise HTTPException(400, "versions must be a directory")
                if versions.exists():
                    if gid is not None:
                        os.chown(versions, 0, gid)
                    os.chmod(versions, 0o750)
                    for version in versions.iterdir():
                        if version.is_symlink() or not version.is_dir() or not version.name.isdigit():
                            raise HTTPException(400, "invalid version directory")
                        E._read_only(version, gid)
                marker = captured / ".hr-restored-snapshot"
                if marker.exists() or marker.is_symlink():
                    marker.unlink()
                marker.write_text(digest)
                marker.chmod(0o600)
                os.replace(captured, root)
            except BaseException:
                root.rmdir()
                raise
        return {"id": env_id, "restored": True, "active": E.active_version(env_id)}


@E.router.get("/environments/{env_id}/snapshot")
def download(env_id: str):
    path = snapshot(env_id)
    return FileResponse(path, media_type="application/gzip", background=BackgroundTask(os.unlink, path))


@E.router.post("/environments/{env_id}/restore")
async def upload(env_id: str, request: Request):
    fd, path = tempfile.mkstemp()
    try:
        with os.fdopen(fd, "wb") as dest:
            async for chunk in request.stream():
                dest.write(chunk)
        return await asyncio.to_thread(restore, env_id, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(path)
