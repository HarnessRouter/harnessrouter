"""The checkpoint spool directory must be one the runner can write to. On the hosted service an image
build imported server.py as root, which left /var/tmp/harness-spool root-owned at 755; its runner runs
as another user, so every checkpoint and every hydrate failed at mkstemp with EACCES for 18 hours
(2026-10-14). An existing directory it cannot write to now falls back to the OS tmpdir, as a missing
one did."""
import os
import pathlib
import sys
import tempfile

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server as rn  # noqa: E402


def test_a_writable_directory_is_kept_and_a_missing_one_is_created(tmp_path):
    assert rn._spool_dir(str(tmp_path)) == str(tmp_path)
    fresh = tmp_path / "spool"
    assert rn._spool_dir(str(fresh)) == str(fresh) and fresh.is_dir()


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes anywhere, so the case cannot be built")
def test_an_existing_directory_it_cannot_write_to_falls_back_to_the_tmpdir(tmp_path):
    locked = tmp_path / "harness-spool"
    locked.mkdir(mode=0o755)
    locked.chmod(0o555)                       # what a root-owned 755 directory is to another user
    try:
        assert rn._spool_dir(str(locked)) is None
        fd, p = tempfile.mkstemp(suffix=".tgz", dir=rn._spool_dir(str(locked)))   # what hydrate does
        os.close(fd); os.unlink(p)
    finally:
        locked.chmod(0o755)
