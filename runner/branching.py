"""Restore a response's committed user files without importing its CLI or Git config."""
from __future__ import annotations

import contextlib
import fnmatch
import gzip
import zlib
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import tempfile

GIT_TIMEOUT_SECONDS = 120

COMMIT = re.compile(r"^[0-9a-f]{40}$")
# These are installations, not the user's committed work. Keep this list in sessions.md.
DEPENDENCY_DIRS = frozenset({"node_modules", ".venv", "venv", "__pycache__", ".cache"})


class BranchUnavailable(ValueError):
    """The point can't be a branch: its commit is missing, off the checkpoint's history, or not
    restorable as files. Final: the same checkpoint gives the same answer."""


class BranchRestoreFailed(RuntimeError):
    """The restore could not finish: a Git command ran past GIT_TIMEOUT_SECONDS, or the disk
    refused a write (full, out of descriptors). Not `BranchUnavailable`, since the point may be
    fine, and not retried either: the same checkpoint on the same box meets the same limit, and
    a resend repeats the whole upload and every Git command before it."""


def _git(repository: Path, *args: str, output=None, stdin=None):
    env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null",
               GIT_CONFIG_SYSTEM="/dev/null", GIT_NO_REPLACE_OBJECTS="1", GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0")
    # Inherited Git variables must not redirect this private repository elsewhere.
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY",
                "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG", "GIT_CONFIG_COUNT",
                "GIT_CONFIG_PARAMETERS", "GIT_TEMPLATE_DIR", "GIT_EXEC_PATH"):
        env.pop(key, None)
    return subprocess.run(["git", "--no-replace-objects", "--git-dir", str(repository),
                           "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
                           "-c", "core.alternateRefsCommand=", "-c", "core.commitGraph=false", *args],
                          env=env, stdin=stdin, stdout=output or subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=GIT_TIMEOUT_SECONDS, check=True)


def _verified_copy(repository: Path, selected: str, stage: Path) -> Path:
    """A second bare repository holding only `selected`'s commit, trees and blobs, each checked.

    The imported store is the source session's own `.git`, which its agent could write, and Git
    does not hash an object it reads: a loose object whose bytes are not what its name says is
    read as those bytes. `git fsck --strict` over the whole store checked every object every
    session ever made; this checks the ones the export reads. They are packed out of the imported
    store and indexed into an empty one with `index-pack --strict`, which names each object by
    hashing its content (an object with other bytes arrives under another name, and the commit or
    tree that names it then fails the link check, as does anything missing) and applies fsck's
    strict checks to each. The parents are outside the pack, so `selected` is entered in the new
    store's `shallow` file: its history is checked against the imported store's HEAD before this
    (merge-base), as policy, and none of it is exported."""
    listing = stage / "selected.objects"
    with listing.open("xb") as output:
        _git(repository, "rev-list", "--objects", "--no-walk", selected, output=output)
    pack = stage / "selected.pack"
    with listing.open("rb") as incoming, pack.open("xb") as output:
        _git(repository, "pack-objects", "--stdout", "--window=0", "--quiet", stdin=incoming, output=output)
    verified = stage / "verified.git"
    _git(verified, "init", "--bare", "--quiet", "--template=")
    (verified / "shallow").write_text(selected + "\n")
    with pack.open("rb") as incoming:
        _git(verified, "index-pack", "--strict", "--stdin", stdin=incoming)
    _git(verified, "cat-file", "-e", selected + "^{commit}")
    return verified


def _git_payload(name: str) -> bool:
    if name in {".git/HEAD", ".git/packed-refs"}:
        return True
    if name.startswith(".git/refs/"):
        return True
    return bool(re.fullmatch(r"\.git/objects/[0-9a-f]{2}/[0-9a-f]{38}", name)
                or re.fullmatch(r"\.git/objects/pack/pack-[0-9a-f]{40}\.(pack|idx)", name))


def excluded_path(path: PurePosixPath, patterns) -> bool:
    # Root configuration paths stay rooted; unanchored cache patterns match at any depth.
    if path.parts[0] == ".harness" or any(part == ".git" or part in DEPENDENCY_DIRS for part in path.parts):
        return True
    for pattern in patterns:
        rooted = pattern.startswith("./")
        pattern = pattern.removeprefix("./").rstrip("/")
        for index in (range(1) if rooted else range(len(path.parts))):
            tail = "/".join(path.parts[index:])
            if fnmatch.fnmatch(tail, pattern) or tail.startswith(pattern + "/"):
                return True
    return False


def restore(source: Path, target: Path, selected: str, latest: str, spool: Path,
            write_context=contextlib.nullcontext, excluded=()) -> str:
    """Read only Git objects/refs from the completed checkpoint. Never extract its worktree.

    The fresh bare repository supplies its own config. The source's config, hooks, CLI state,
    alternates and worktree files cannot influence the export. All intermediate files are under
    the runner's private spool, not under either session's workspace.

    `latest` empty means the checkpoint's own HEAD, which is what the gateway sends: `selected`
    names its files by hash, so any later checkpoint whose history still holds it restores the
    same bytes. A caller that does name `latest` still has it checked against that HEAD.
    """
    if not COMMIT.fullmatch(selected) or (latest and not COMMIT.fullmatch(latest)):
        raise BranchUnavailable("missing full checkpoint commit")
    if target.exists() and any(target.iterdir()):
        raise BranchUnavailable("branch target is not empty")
    try:
        with tempfile.TemporaryDirectory(prefix="branch-", dir=spool) as temporary:
            stage = Path(temporary)
            repository = stage / "objects.git"
            _git(repository, "init", "--bare", "--quiet", "--template=")
            with tarfile.open(source, "r:gz") as archive:
                seen = set()
                for member in archive:
                    name = str(PurePosixPath(member.name))
                    parts = PurePosixPath(member.name).parts
                    if PurePosixPath(member.name).is_absolute() or ".." in parts:
                        raise BranchUnavailable("unsafe checkpoint path")
                    if not parts or parts[0] != ".git":
                        continue  # Do not materialize source user files or CLI state.
                    if name in {".git/objects/info/alternates", ".git/objects/info/http-alternates",
                                ".git/commondir", ".git/gitdir", ".git/shallow"} or name.endswith(".promisor"):
                        raise BranchUnavailable("external or incomplete Git history")
                    if member.issym() or member.islnk():
                        raise BranchUnavailable("linked Git payload")
                    if not _git_payload(name):
                        continue  # Config and hooks are never imported, even when ordinary files.
                    if not member.isfile() and not member.isdir():
                        raise BranchUnavailable("linked Git payload")
                    if name in seen:
                        raise BranchUnavailable("duplicate Git payload")
                    seen.add(name)
                    dest = repository.joinpath(*parts[1:])
                    if member.isdir():
                        dest.mkdir(parents=True, exist_ok=True)
                    else:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        # init creates HEAD; only the checkpoint's HEAD may replace it.
                        mode = "wb" if name == ".git/HEAD" else "xb"
                        with archive.extractfile(member) as incoming, dest.open(mode) as output:
                            while chunk := incoming.read(1024 * 1024):
                                output.write(chunk)
            # Policy, on the imported store: the point is a commit on the history of the HEAD this
            # checkpoint was taken at. Integrity is the verified copy's, below.
            head = _git(repository, "rev-parse", "--verify", "HEAD").stdout.decode().strip()
            if latest and head != latest:
                raise BranchUnavailable("checkpoint HEAD differs from its acknowledged commit")
            latest = head
            _git(repository, "cat-file", "-e", selected + "^{commit}")
            _git(repository, "merge-base", "--is-ancestor", selected, latest)
            # Integrity: the chosen commit and its whole tree, present and well-formed, and
            # nothing else read from the imported store from here on.
            verified = _verified_copy(repository, selected, stage)
            tree = _git(verified, "ls-tree", "-r", "-z", selected).stdout
            for row in tree.split(b"\0"):
                if row and row.split(b" ", 1)[0] == b"160000":
                    raise BranchUnavailable("submodule worktrees are not checkpointed user files")
            # Export committed bytes, not .gitattributes' export-ignore/export-subst projection.
            (verified / "info").mkdir(exist_ok=True)
            (verified / "info/attributes").write_text("* -export-ignore -export-subst\n")
            exported = stage / "user-files.tar"
            with exported.open("xb") as output:
                _git(verified, "archive", "--format=tar", selected, output=output)
            h = hashlib.sha256()
            with exported.open("rb") as data:
                while chunk := data.read(1024 * 1024):
                    h.update(chunk)
            with tarfile.open(exported, "r:") as archive:
                members = []
                for member in archive:
                    path = PurePosixPath(member.name)
                    if path.is_absolute() or ".." in path.parts:
                        raise BranchUnavailable("unsafe committed path")
                    if excluded_path(path, excluded):
                        continue
                    if not (member.isdir() or member.isfile() or member.issym()):
                        raise BranchUnavailable("unsupported committed file")
                    # Validate every selected member before making the target visible to extraction.
                    tarfile.data_filter(member, str(target))
                    members.append(member)
                with write_context():
                    target.mkdir(parents=True, exist_ok=True)
                    archive.extractall(target, members=members, filter="data")
            return h.hexdigest()
    except (subprocess.CalledProcessError, tarfile.TarError, EOFError, gzip.BadGzipFile, zlib.error, RuntimeError) as error:
        raise BranchUnavailable("checkpoint history could not be restored") from error
    except (subprocess.TimeoutExpired, OSError) as error:
        # After the clause above: gzip.BadGzipFile is an OSError, and a corrupt archive is the
        # checkpoint's fault, not the box's.
        raise BranchRestoreFailed(f"branch restore did not finish: {type(error).__name__}") from error
