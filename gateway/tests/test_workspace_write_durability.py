"""A workspace write made through the API must outlive the live workspace.

Self-hosted, a session's workspace is a live directory the runner owns, and it is reaped after
HR_WORKSPACE_TTL_HOURS. Only a TURN's checkpoint ever refreshed the durable copy, so a file an APP
wrote between turns existed in exactly one place and was deleted with it. The sheets kit keeps the
whole spreadsheet in sheet.json, so a sheet somebody typed rows into and never asked the agent
about again came back with the agent's original empty structure, and every agent column they had
bound by hand came back unbound. The hosted sibling (CheckpointWorkspaceFiles) writes into the
durable tarball and never had the hole, which is the tell: one Protocol, two meanings for `write`.

Unlike the app-level tests next door, these import only backing.py, so they run anywhere.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import backing as B  # noqa: E402


class _Blob:
    """The durable side, reduced to what the capture actually needs."""

    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}

    async def put(self, kb, key, data):
        self.objects[(kb, key)] = data
        return True


class _OK:
    status_code = 200


def _runner(blob):
    ws = B.RunnerWorkspaceFiles("http://runner", "k", blob, "harness-responses")

    class _Client:
        async def put(self, *_a, **_k):
            return _OK()

    ws._c = lambda: _Client()          # the live write always succeeds here
    return ws


@pytest.mark.asyncio
async def test_a_write_is_captured_durably():
    blob = _Blob()
    assert await _runner(blob).write("hsess1", "sheet.json", b'{"rows":[1]}') is True

    metas = [k for k in blob.objects if k[1].endswith(".meta")]
    assert len(metas) == 1, "the write must leave exactly one durable copy plus its meta"
    meta = __import__("json").loads(blob.objects[metas[0]])
    assert meta["filename"] == "sheet.json"
    assert meta["written_at"] > 0, "without a stamp the read side cannot tell which copy is newer"

    body = [k for k in blob.objects if not k[1].endswith(".meta")][0]
    assert blob.objects[body] == b'{"rows":[1]}'
    assert body[1].startswith("containers/hsess1/cfile_")


@pytest.mark.asyncio
async def test_saving_the_same_file_again_does_not_leak_a_blob_per_save():
    """A spreadsheet autosaves. One blob per keystroke would be a storage leak, so the id is
    derived from the path rather than minted fresh."""
    blob = _Blob()
    ws = _runner(blob)
    for i in range(5):
        assert await ws.write("hsess1", "sheet.json", f'{{"n":{i}}}'.encode()) is True

    assert len(blob.objects) == 2, "five saves, one blob and one meta"
    body = [k for k in blob.objects if not k[1].endswith(".meta")][0]
    assert blob.objects[body] == b'{"n":4}', "the newest save must be the one kept"


@pytest.mark.asyncio
async def test_two_files_keep_two_blobs():
    blob = _Blob()
    ws = _runner(blob)
    await ws.write("hsess1", "sheet.json", b"a")
    await ws.write("hsess1", "notes.md", b"b")
    assert len({k for k in blob.objects if not k[1].endswith(".meta")}) == 2


@pytest.mark.asyncio
async def test_a_refused_live_write_captures_nothing():
    """Durability must not invent a file the workspace itself rejected."""
    blob = _Blob()
    ws = _runner(blob)

    class _Refused:
        status_code = 409

    class _Client:
        async def put(self, *_a, **_k):
            return _Refused()

    ws._c = lambda: _Client()
    assert await ws.write("hsess1", "sheet.json", b"x") is False
    assert blob.objects == {}


@pytest.mark.asyncio
async def test_a_path_that_escapes_the_workspace_captures_nothing():
    blob = _Blob()
    assert await _runner(blob).write("hsess1", "../../etc/passwd", b"x") is False
    assert blob.objects == {}
