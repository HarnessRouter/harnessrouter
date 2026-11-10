"""A response branch reads its real Git tree, not the latest files or native CLI home."""
from __future__ import annotations

import asyncio
import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import threading
import zlib

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
import branching
from branching import BranchRestoreFailed, BranchUnavailable, restore


def git(where, *args):
    return subprocess.run(["git", "-C", str(where), "-c", "core.hooksPath=/dev/null", *args],
                          check=True, capture_output=True, text=True,
                          env={**os.environ, "GIT_AUTHOR_NAME": "Fixture", "GIT_COMMITTER_NAME": "Fixture",
                               "GIT_AUTHOR_EMAIL": "fixture@example.invalid", "GIT_COMMITTER_EMAIL": "fixture@example.invalid"}).stdout.strip()


@pytest.fixture
def history(tmp_path):
    source = tmp_path / "original"
    source.mkdir()
    git(source, "init", "-q")
    (source / "answer.txt").write_text("turn one")
    (source / ".github").mkdir()
    (source / ".github/workflow.yml").write_text("user configuration")
    executable = source / "run.sh"
    executable.write_text("#!/bin/sh\necho user\n")
    executable.chmod(0o755)
    for name in (".harness/home/session.json", "node_modules/dependency.js", ".venv/bin/python"):
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not branch user files")
    git(source, "add", "-A")
    git(source, "commit", "-qm", "turn one")
    first = git(source, "rev-parse", "HEAD")
    for number in (2, 3):
        (source / "answer.txt").write_text(f"turn {number}")
        (source / f"future-{number}.txt").write_text("not yet written at turn one")
        git(source, "add", "-A")
        git(source, "commit", "-qm", f"turn {number}")
    latest = git(source, "rev-parse", "HEAD")
    return source, first, latest


def checkpoint(source, path):
    with tarfile.open(path, "w:gz") as archive:
        archive.add(source, arcname=".")
    return path


def test_branch_from_one_after_three_restores_user_files_and_leaves_original(history, tmp_path):
    source, first, latest = history
    before = (source / "answer.txt").read_bytes()
    target = tmp_path / "branch"
    restore(checkpoint(source, tmp_path / "checkpoint.tgz"), target, first, latest, tmp_path)
    assert (target / "answer.txt").read_text() == "turn one"
    assert (source / "answer.txt").read_bytes() == before
    assert git(source, "rev-parse", "HEAD") == latest
    assert not list(target.glob("future-*"))
    assert not (target / ".git").exists()
    assert not (target / ".harness").exists()
    assert not (target / "node_modules").exists()
    assert not (target / ".venv").exists()
    assert (target / ".github/workflow.yml").read_text() == "user configuration"
    assert (target / "run.sh").stat().st_mode & 0o111


def test_source_git_config_and_hooks_are_never_executed(history, tmp_path):
    source, first, latest = history
    marker = tmp_path / "hook-ran"
    hook = source / ".git/hooks/post-checkout"
    hook.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
    hook.chmod(0o755)
    with (source / ".git/config").open("a") as config:
        config.write(f'\n[core]\n hooksPath = {hook.parent}\n fsmonitor = touch "{marker}"\n')
    restore(checkpoint(source, tmp_path / "checkpoint.tgz"), tmp_path / "branch", first, latest, tmp_path)
    assert not marker.exists()


@pytest.mark.parametrize("selected,head", [("a" * 40, None), (None, "b" * 40), ("HEAD", None)])
def test_missing_nonfull_or_divergent_commits_fail_before_export(history, tmp_path, selected, head):
    source, first, latest = history
    target = tmp_path / "branch"
    with pytest.raises(BranchUnavailable):
        restore(checkpoint(source, tmp_path / "checkpoint.tgz"), target, selected or first, head or latest, tmp_path)
    assert not target.exists()


def test_a_gitlink_is_not_silently_dropped(history, tmp_path):
    source, first, latest = history
    git(source, "update-index", "--add", "--cacheinfo", f"160000,{first},submodule")
    git(source, "commit", "-qm", "gitlink")
    current = git(source, "rev-parse", "HEAD")
    with pytest.raises(BranchUnavailable):
        restore(checkpoint(source, tmp_path / "checkpoint.tgz"), tmp_path / "branch", current, current, tmp_path)


def test_escaping_committed_symlink_fails_without_writing_outside(history, tmp_path):
    source, first, latest = history
    (source / "escape").symlink_to("../outside")
    git(source, "add", "escape")
    git(source, "commit", "-qm", "unsafe link")
    current = git(source, "rev-parse", "HEAD")
    with pytest.raises(BranchUnavailable):
        restore(checkpoint(source, tmp_path / "checkpoint.tgz"), tmp_path / "branch", current, current, tmp_path)
    assert not (tmp_path / "outside").exists()


@pytest.fixture
def runner(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    monkeypatch.setattr(server, "_WS_MARKER_DIR", str(tmp_path / "markers"))
    monkeypatch.setattr(server, "SPOOL_DIR", str(tmp_path))
    monkeypatch.setattr(server, "_SANDBOX_PER_SESSION", False)
    monkeypatch.setattr(server, "_SESSION_UIDS", False)
    monkeypatch.setattr(server, "_INTERNAL_KEY", "")
    (tmp_path / "workspaces").mkdir()
    client = TestClient(server.app)
    try:
        yield client
    finally:
        client.close()


def test_real_runner_branch_is_idempotent_and_its_checkpoint_has_full_commit(runner, history, tmp_path):
    source, first, latest = history
    body = checkpoint(source, tmp_path / "source.tgz").read_bytes()
    url = f"/hydrate?identifier=branch&branch_commit={first}&branch_head={latest}"
    assert runner.post(url, content=body).status_code == 200
    target = Path(server._ws("branch"))
    assert (target / "answer.txt").read_text() == "turn one"
    assert runner.post(url, content=body).status_code == 200
    result = runner.get("/checkpoint?identifier=branch")
    assert result.status_code == 200
    assert len(result.headers["X-Git-Commit"]) == 40
    assert result.headers["X-Git-Commit"].startswith(result.headers["X-Git-Head"])
    # A checkpoint has advanced the marker: a delayed branch-restore retry cannot wipe it.
    assert runner.post(url, content=body).status_code == 409


def test_empty_branch_never_becomes_a_fresh_workspace(runner):
    assert runner.post("/hydrate?identifier=empty&branch_commit=" + "a" * 40, content=b"").status_code == 409
    assert not Path(server._ws("empty")).exists()


def test_incomplete_branch_body_preserves_original(runner, history, tmp_path):
    source, first, latest = history
    body = checkpoint(source, tmp_path / "source.tgz").read_bytes()
    result = runner.post(f"/hydrate?identifier=bad&branch_commit={first}&branch_head={latest}", content=body[:100])
    assert result.status_code == 409
    assert not Path(server._ws("bad")).exists()
    assert git(source, "rev-parse", "HEAD") == latest
    assert (source / "answer.txt").read_text() == "turn 3"


def test_export_attributes_cannot_drop_or_substitute_committed_bytes(history, tmp_path):
    source, first, latest = history
    (source / ".gitattributes").write_text("answer.txt export-ignore\nsubstitution.txt export-subst\n")
    (source / "substitution.txt").write_text("$Format:%H$")
    git(source, "add", ".gitattributes", "substitution.txt")
    git(source, "commit", "-qm", "attributes")
    current = git(source, "rev-parse", "HEAD")
    target = tmp_path / "branch"
    restore(checkpoint(source, tmp_path / "source.tgz"), target, current, current, tmp_path)
    assert (target / "answer.txt").read_text() == "turn 3"
    assert (target / "substitution.txt").read_text() == "$Format:%H$"


def test_a_present_but_divergent_commit_is_not_a_branch_point(history, tmp_path):
    source, first, latest = history
    original = git(source, "branch", "--show-current")
    git(source, "checkout", "--orphan", "divergent")
    git(source, "commit", "-qm", "unrelated root")
    divergent = git(source, "rev-parse", "HEAD")
    git(source, "checkout", original)
    assert git(source, "cat-file", "-t", divergent) == "commit"
    with pytest.raises(BranchUnavailable):
        restore(checkpoint(source, tmp_path / "source.tgz"), tmp_path / "branch", divergent, latest, tmp_path)


def test_actual_cli_home_history_shed_makes_old_point_unavailable(history, tmp_path):
    source, first, latest = history
    server._git_shed_cli_home_history(str(source))
    rewritten = git(source, "rev-parse", "HEAD")
    assert rewritten != latest
    with pytest.raises(BranchUnavailable):
        restore(checkpoint(source, tmp_path / "source.tgz"), tmp_path / "branch", first, rewritten, tmp_path)


@pytest.mark.parametrize("pattern", server.CHECKPOINT_EXCLUDE)
def test_every_checkpoint_exclusion_hides_old_tracked_root_and_nested_files(history, tmp_path, pattern):
    source, first, latest = history
    sample = pattern.removeprefix("./").replace("*", "probe").rstrip("/")
    names = []
    for prefix in ("", "nested/"):
        name = prefix + sample
        path = source / name
        if path.is_dir() or pattern.endswith("/"):
            name += "/probe.txt"
            path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic credential or scratch")
        names.append(name)
    git(source, "add", "--force", "--", *names)
    git(source, "commit", "-qm", "legacy tracked files")
    current = git(source, "rev-parse", "HEAD")
    target = tmp_path / "branch"
    restore(checkpoint(source, tmp_path / "source.tgz"), target, current, current, tmp_path,
            excluded=(*server.CHECKPOINT_EXCLUDE, *("./" + p for p in (*server._PER_TURN_CONFIG, *server._STATE_DIRS))))
    assert not (target / names[0]).exists()
    if pattern.startswith("./") and not any(
            part in {"node_modules", ".venv", "venv", "__pycache__", ".cache"}
            for part in Path(names[1]).parts):
        assert (target / names[1]).read_text() == "synthetic credential or scratch"
    else:
        assert not (target / names[1]).exists()


def crafted_checkpoint(source, path, name, kind="file", data=b"bad"):
    original = checkpoint(source, path.with_suffix(".original.tgz"))
    with tarfile.open(original, "r:gz") as old, tarfile.open(path, "w:gz") as new:
        for member in old:
            new.addfile(member, old.extractfile(member) if member.isfile() else None)
        member = tarfile.TarInfo(name)
        if kind in ("symlink", "hardlink"):
            member.type = tarfile.SYMTYPE if kind == "symlink" else tarfile.LNKTYPE
            member.linkname = "../../outside"
            new.addfile(member)
        else:
            member.size = len(data)
            new.addfile(member, io.BytesIO(data))
    return path


@pytest.mark.parametrize("name,kind", [
    ("../outside", "file"), ("/outside", "file"), (".git/objects", "symlink"),
    (".git/objects/aa/" + "a" * 38, "hardlink"), (".git/objects/info/alternates", "file"),
    (".git/shallow", "file"), (".git/objects/pack/pack-" + "a" * 40 + ".promisor", "file"),
    (".git/HEAD", "file"),
])
def test_crafted_checkpoint_is_refused_before_target_export(history, tmp_path, name, kind):
    source, first, latest = history
    body = crafted_checkpoint(source, tmp_path / "crafted.tgz", name, kind)
    target = tmp_path / "branch"
    with pytest.raises(BranchUnavailable):
        restore(body, target, first, latest, tmp_path)
    assert not target.exists()


@pytest.mark.parametrize("name", [".git/objects/info/commit-graph", ".git/objects/pack/multi-pack-index"])
def test_derived_graph_metadata_is_not_imported_or_consulted(history, tmp_path, name):
    source, first, latest = history
    body = crafted_checkpoint(source, tmp_path / "crafted.tgz", name)
    target = tmp_path / "branch"
    restore(body, target, first, latest, tmp_path)
    assert (target / "answer.txt").read_text() == "turn one"


@pytest.mark.parametrize("failure", ["empty", "raise", "bytes"])
def test_checkpoint_git_metadata_failure_keeps_user_files(runner, monkeypatch, failure):
    work = Path(server._ws("nohead"))
    work.mkdir()
    (work / "user.txt").write_text("must survive")
    original_git = server._git

    def fail_head(where, *args, **kwargs):
        if args[0] == "commit":
            return subprocess.CompletedProcess([], 1, "", "synthetic failure")
        if args in (("rev-parse", "HEAD"), ("rev-parse", "--short", "HEAD")):
            if failure == "raise":
                raise subprocess.CalledProcessError(1, ["git", *args])
            return subprocess.CompletedProcess([], 1, b"" if failure == "bytes" else "", "synthetic failure")
        return original_git(where, *args, **kwargs)

    monkeypatch.setattr(server, "_git", fail_head)
    result = runner.get("/checkpoint?identifier=nohead")
    assert result.status_code == 200
    assert result.headers["X-Git-Commit"] == ""
    with tarfile.open(fileobj=io.BytesIO(result.content), mode="r:gz") as archive:
        assert archive.extractfile("./user.txt").read() == b"must survive"


def test_an_unexpected_restore_error_is_retryable_and_leaves_no_partial_target(runner, monkeypatch, history, tmp_path):
    source, first, latest = history

    def unexpected(*args, **kwargs):
        raise LookupError("synthetic unexpected failure")

    monkeypatch.setattr(branching, "restore", unexpected)
    result = runner.post(f"/hydrate?identifier=transient&branch_commit={first}&branch_head={latest}",
                         content=checkpoint(source, tmp_path / "source.tgz").read_bytes())
    assert result.status_code == 503
    assert not Path(server._ws("transient")).exists()
    assert not server._ws_marker_path("transient").exists()


@pytest.mark.parametrize("failure", [subprocess.TimeoutExpired(["git"], 120), FileNotFoundError("git"),
                                     OSError(28, "No space left on device")])
def test_a_git_timeout_or_disk_error_is_final_not_a_retried_503(history, tmp_path, monkeypatch, failure):
    """A timeout used to escape restore() as itself, the runner answered 503, and the gateway's
    _HYDRATE_PAUSES sent the whole checkpoint again seven times, each running every Git command
    up to its 120 s limit again. It is BranchRestoreFailed now: not branch_unavailable (the point
    may be fine) and not retried."""
    source, first, latest = history
    real = branching._git

    def failing(repository, *args, **kwargs):
        if args[0] == "index-pack":
            raise failure
        return real(repository, *args, **kwargs)

    monkeypatch.setattr(branching, "_git", failing)
    target = tmp_path / "branch"
    with pytest.raises(BranchRestoreFailed):
        restore(checkpoint(source, tmp_path / "checkpoint.tgz"), target, first, latest, tmp_path)
    assert not target.exists()


def test_the_runner_answers_a_restore_failure_with_a_status_the_gateway_does_not_resend(runner, monkeypatch, history, tmp_path):
    source, first, latest = history

    def timed_out(*args, **kwargs):
        raise BranchRestoreFailed("branch restore did not finish: TimeoutExpired")

    monkeypatch.setattr(branching, "restore", timed_out)
    result = runner.post(f"/hydrate?identifier=slow&branch_commit={first}",
                         content=checkpoint(source, tmp_path / "source.tgz").read_bytes())
    assert result.status_code == 500 and result.json()["detail"] == "branch_restore_failed"
    assert not Path(server._ws("slow")).exists()
    assert not server._ws_marker_path("slow").exists()


def _forge(repository: Path, oid: str, kind: bytes, body: bytes) -> None:
    """Overwrite a loose object with other, well-formed bytes under its original name."""
    path = repository / ".git/objects" / oid[:2] / oid[2:]
    path.chmod(0o644)
    path.write_bytes(zlib.compress(kind + b" " + str(len(body)).encode() + b"\0" + body))


def test_a_forged_object_in_the_chosen_commit_is_refused(history, tmp_path):
    """Git does not hash what it reads: a loose object holding other bytes than its name says is
    read as those bytes. The chosen commit's objects are re-hashed (index-pack), so the branch is
    refused rather than restoring bytes the commit never named."""
    source, first, latest = history
    blob = git(source, "rev-parse", f"{first}:answer.txt")
    _forge(source, blob, b"blob", b"forged")
    assert git(source, "cat-file", "-p", blob) == "forged"     # what an unchecked read returns
    target = tmp_path / "branch"
    with pytest.raises(BranchUnavailable):
        restore(checkpoint(source, tmp_path / "checkpoint.tgz"), target, first, latest, tmp_path)
    assert not target.exists()


def test_a_forged_tree_in_the_chosen_commit_is_refused(history, tmp_path):
    source, first, latest = history
    tree = git(source, "rev-parse", f"{first}^{{tree}}")
    other = git(source, "rev-parse", f"{latest}^{{tree}}")
    raw = (source / ".git/objects" / other[:2] / other[2:]).read_bytes()
    path = source / ".git/objects" / tree[:2] / tree[2:]
    path.chmod(0o644)
    path.write_bytes(raw)             # the latest tree's bytes, under turn one's tree's name
    with pytest.raises(BranchUnavailable):
        restore(checkpoint(source, tmp_path / "checkpoint.tgz"), tmp_path / "branch", first, latest, tmp_path)


def test_a_missing_blob_in_the_chosen_commit_is_refused(history, tmp_path):
    source, first, latest = history
    blob = git(source, "rev-parse", f"{first}:run.sh")
    (source / ".git/objects" / blob[:2] / blob[2:]).unlink()
    with pytest.raises(BranchUnavailable):
        restore(checkpoint(source, tmp_path / "checkpoint.tgz"), tmp_path / "branch", first, latest, tmp_path)


def test_integrity_is_checked_for_the_chosen_commit_only(history, tmp_path):
    """A damaged object the chosen commit does not name (here a later turn's file) is not read,
    so it no longer refuses the branch: `git fsck --strict` over the whole store did."""
    source, first, latest = history
    later = git(source, "rev-parse", f"{latest}:future-3.txt")
    _forge(source, later, b"blob", b"damaged later bytes")
    target = tmp_path / "branch"
    restore(checkpoint(source, tmp_path / "checkpoint.tgz"), target, first, latest, tmp_path)
    assert (target / "answer.txt").read_text() == "turn one"


def test_restore_runs_off_the_event_loop_and_its_write_identity_stays_on_its_thread(runner, monkeypatch, history, tmp_path):
    """restore() runs in a worker thread (asyncio.to_thread). _fs_as sets the filesystem uid of
    the calling thread only (setfsuid), so it has to be entered and left on the thread that
    writes: it is, inside restore(), and the event loop's thread never takes it."""
    source, first, latest = history
    real_restore, real_fs_as = branching.restore, server._fs_as
    seen = {"fs_as": []}

    def spy(*args, **kwargs):
        seen["thread"] = threading.get_ident()
        try:
            asyncio.get_running_loop()
            seen["on_loop"] = True
        except RuntimeError:
            seen["on_loop"] = False
        return real_restore(*args, **kwargs)

    @contextlib.contextmanager
    def fs_as(uid):
        seen["fs_as"].append(("enter", threading.get_ident()))
        with real_fs_as(uid):
            yield
        seen["fs_as"].append(("leave", threading.get_ident()))

    monkeypatch.setattr(branching, "restore", spy)
    monkeypatch.setattr(server, "_fs_as", fs_as)
    result = runner.post(f"/hydrate?identifier=offloop&branch_commit={first}",
                         content=checkpoint(source, tmp_path / "source.tgz").read_bytes())
    assert result.status_code == 200, result.text
    assert seen["on_loop"] is False
    # restore()'s write wall, entered and left on its own thread; the setup after it (_git_ensure)
    # takes its own on the loop's thread, as /hydrate does
    on_restore_thread = [kind for kind, thread in seen["fs_as"] if thread == seen["thread"]]
    assert on_restore_thread == ["enter", "leave"]
    for thread in {thread for _, thread in seen["fs_as"]}:
        kinds = [kind for kind, other in seen["fs_as"] if other == thread]
        assert kinds.count("enter") == kinds.count("leave")
    assert (Path(server._ws("offloop")) / "answer.txt").read_text() == "turn one"


@pytest.fixture
def pooled(runner, monkeypatch):
    """A sandbox per session (HR_SANDBOX_PER_SESSION): the workspace is the root itself, and a
    pooled sandbox is reused, so the root can hold what the last session left."""
    monkeypatch.setattr(server, "_SANDBOX_PER_SESSION", True)
    root = Path(server.WORKSPACE_ROOT)
    assert Path(server._ws("any")) == root
    (root / "leftover.txt").write_text("a prior session's file")
    (root / "project").mkdir()
    (root / "project/old.txt").write_text("a prior session's folder")
    (root / ".git").mkdir()
    return root


def test_a_branch_on_a_reused_per_session_root_wipes_it_like_hydrate(runner, pooled, history, tmp_path):
    """It used to be refused 409 (the target was not empty): every branch on a reused sandbox."""
    source, first, latest = history
    result = runner.post(f"/hydrate?identifier=pooled&branch_commit={first}",
                         content=checkpoint(source, tmp_path / "source.tgz").read_bytes())
    assert result.status_code == 200, result.text
    assert result.json()["branched"] is True
    assert (pooled / "answer.txt").read_text() == "turn one"
    assert not (pooled / "leftover.txt").exists() and not (pooled / "project").exists()
    assert not list(pooled.glob("future-*"))


def test_a_failed_branch_on_a_per_session_root_empties_it_and_keeps_it(runner, pooled, history, tmp_path):
    source, first, latest = history
    result = runner.post(f"/hydrate?identifier=pooled-bad&branch_commit={'a' * 40}",
                         content=checkpoint(source, tmp_path / "source.tgz").read_bytes())
    assert result.status_code == 409
    assert pooled.is_dir(), "the workspace root must never be removed"
    assert not any(pooled.iterdir())
    assert not server._ws_marker_path("pooled-bad").exists()


def test_a_per_session_folder_with_leftovers_and_no_receipt_is_wiped_too(runner, history, tmp_path):
    """Shared deployments: a folder under the branch's new id that holds files but no receipt is
    not this branch's restore, and is wiped as /hydrate would."""
    source, first, latest = history
    folder = Path(server._ws("stale"))
    folder.mkdir()
    (folder / "leftover.txt").write_text("not this branch's")
    result = runner.post(f"/hydrate?identifier=stale&branch_commit={first}",
                         content=checkpoint(source, tmp_path / "source.tgz").read_bytes())
    assert result.status_code == 200, result.text
    assert (folder / "answer.txt").read_text() == "turn one"
    assert not (folder / "leftover.txt").exists()


@pytest.mark.asyncio
async def test_disconnected_upload_does_not_create_target(runner, history, tmp_path):
    import httpx
    source, first, latest = history
    body = checkpoint(source, tmp_path / "source.tgz").read_bytes()

    async def disconnected():
        yield body[:100]
        raise RuntimeError("synthetic client disconnect")

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://runner") as client:
        result = await client.post(f"/hydrate?identifier=disconnected&branch_commit={first}&branch_head={latest}",
                                   content=disconnected())
    assert result.status_code == 400
    assert not Path(server._ws("disconnected")).exists()


def test_subdirectory_base_file_root_is_regenerated_without_cli_state(runner, history, tmp_path):
    source, first, latest = history
    path = source / "workspace/user.txt"
    path.parent.mkdir()
    path.write_text("selected user bytes")
    git(source, "add", "workspace/user.txt")
    git(source, "commit", "-qm", "subdirectory workspace")
    current = git(source, "rev-parse", "HEAD")
    body = checkpoint(source, tmp_path / "source.tgz").read_bytes()
    result = runner.post(f"/hydrate?identifier=subdir&branch_commit={current}&branch_head={current}&branch_backend=nanobot", content=body)
    assert result.status_code == 200, result.text
    result = runner.get("/file?identifier=subdir&path=user.txt")
    assert result.status_code == 200 and result.content == b"selected user bytes"
    target = Path(server._ws("subdir"))
    assert (target / ".harness/agent-subdir").read_text() == "workspace"
    assert not (target / ".harness/home").exists()


# The gateway sends no `branch_head` (app.py _checkpoint): the point is checked against the HEAD of
# the checkpoint it is restored from. A copy of the session's latest commit kept beside the tarball
# fell out of step with it (a failed write, a branch racing a new turn's checkpoint), and every
# point of that session was then 409 until the session's next turn.

def test_a_checkpoint_newer_than_the_point_still_branches_from_it(history, tmp_path):
    source, first, latest = history
    # a fourth turn after the point was recorded, and after any copy of "latest" anyone kept
    (source / "answer.txt").write_text("turn 4")
    git(source, "add", "-A")
    git(source, "commit", "-qm", "turn 4")
    target = tmp_path / "branch"
    restore(checkpoint(source, tmp_path / "checkpoint.tgz"), target, first, "", tmp_path)
    assert (target / "answer.txt").read_text() == "turn one"
    assert not list(target.glob("future-*"))


@pytest.mark.parametrize("which", ["unknown", "divergent", "shed"])
def test_without_a_named_head_a_point_off_the_checkpoints_history_is_still_refused(history, tmp_path, which):
    """The same refusals as test_missing_nonfull_or_divergent_commits_fail_before_export,
    test_a_present_but_divergent_commit_is_not_a_branch_point and
    test_actual_cli_home_history_shed_makes_old_point_unavailable, with the HEAD taken from the
    checkpoint rather than named by the caller."""
    source, first, latest = history
    selected = "a" * 40
    if which == "divergent":
        original = git(source, "branch", "--show-current")
        git(source, "checkout", "--orphan", "divergent")
        git(source, "commit", "-qm", "unrelated root")
        selected = git(source, "rev-parse", "HEAD")
        git(source, "checkout", original)
    elif which == "shed":
        server._git_shed_cli_home_history(str(source))
        selected = first
    target = tmp_path / "branch"
    with pytest.raises(BranchUnavailable):
        restore(checkpoint(source, tmp_path / "checkpoint.tgz"), target, selected, "", tmp_path)
    assert not target.exists()


def test_real_runner_branches_with_no_head_named(runner, history, tmp_path):
    source, first, latest = history
    body = checkpoint(source, tmp_path / "source.tgz").read_bytes()
    result = runner.post(f"/hydrate?identifier=nohead&branch_commit={first}", content=body)
    assert result.status_code == 200, result.text
    assert (Path(server._ws("nohead")) / "answer.txt").read_text() == "turn one"
    result = runner.post(f"/hydrate?identifier=nohead-bad&branch_commit={'a' * 40}", content=body)
    assert result.status_code == 409
    assert not Path(server._ws("nohead-bad")).exists()
