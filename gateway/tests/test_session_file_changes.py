"""Delete, mkdir and move in a session workspace, on both backings, and what keeps them from coming back.

  * the hosted backing (CheckpointWorkspaceFiles): between turns the checkpoint tarball IS the
    workspace, so each change rewrites it, as `write` does
  * the self-hosted backing (RunnerWorkspaceFiles): the live directory through the runner, and then
    the checkpoint, because a sandbox that does not hold the last checkpoint is restored from it and
    a change made only live would be undone there
  * the durable copies: a delete leaves a tombstone, so the by-path read stops falling back to the
    agent's old capture and the restore stops re-applying the app's; a move carries the app's copy
    to the new name
  * the routes: the same ownership and busy rule as PUT, `..` and absolute paths refused, internal
    paths (.git, .harness) refused, and each backing's answer mapped to its failure
"""
import io
import json
import pathlib
import sys
import tarfile
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import app as A  # noqa: E402
import backing as B  # noqa: E402


def _tar(entries: dict) -> bytes:
    """name -> bytes (a file) or None (a directory entry)."""
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tf:
        for name, data in entries.items():
            info = tarfile.TarInfo(name)
            if data is None:
                info.type = tarfile.DIRTYPE
                tf.addfile(info)
            else:
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
    return out.getvalue()


def _files(raw: bytes) -> dict:
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:
        return {m.name: (tf.extractfile(m).read() if m.isfile() else None) for m in tf.getmembers()}


# ── the archive ────────────────────────────────────────────────────────────────────────────────
def test_delete_a_file_and_keep_the_rest():
    outcome, raw = B.tar_change(_tar({"./a.txt": b"a", "./b.txt": b"b"}), "delete", "a.txt")
    assert outcome == B.WS_OK and _files(raw) == {"./b.txt": b"b"}


def test_delete_a_directory_with_or_without_its_own_entry():
    for entries in ({"./d": None, "./d/x": b"x", "./dx": b"keep"}, {"d/x": b"x", "dx": b"keep"}):
        outcome, raw = B.tar_change(_tar(entries), "delete", "d")
        assert outcome == B.WS_OK
        assert [n for n in _files(raw)] == [n for n in entries if n.endswith("dx")]


def test_delete_nothing():
    assert B.tar_change(_tar({"a": b"a"}), "delete", "b") == (B.WS_NOT_FOUND, None)
    assert B.tar_change(None, "delete", "b") == (B.WS_NOT_FOUND, None)


def test_mkdir():
    outcome, raw = B.tar_change(_tar({"a": b"a"}), "mkdir", "d/e")
    assert outcome == B.WS_OK and _files(raw) == {"a": b"a", "d/e": None}
    assert B.tar_change(raw, "mkdir", "d/e") == (B.WS_OK, None)       # already there: unchanged
    assert B.tar_change(raw, "mkdir", "a") == (B.WS_EXISTS, None)      # a file is in the way
    outcome, raw = B.tar_change(None, "mkdir", "d")                     # no checkpoint yet
    assert outcome == B.WS_OK and _files(raw) == {"d": None}


def test_move_a_file_and_a_directory_keeping_the_bytes():
    raw = _tar({"./a.txt": b"A", "./d": None, "./d/x": b"X", "./d/y/z": b"Z"})
    outcome, raw = B.tar_change(raw, "move", "a.txt", "notes/a.txt")
    assert outcome == B.WS_OK
    outcome, raw = B.tar_change(raw, "move", "d", "e")
    assert outcome == B.WS_OK
    assert _files(raw) == {"./notes/a.txt": b"A", "./e": None, "./e/x": b"X", "./e/y/z": b"Z"}


def test_move_refusals():
    raw = _tar({"a": b"a", "b": b"b", "d/x": b"x"})
    assert B.tar_change(raw, "move", "a", "b") == (B.WS_EXISTS, None)
    assert B.tar_change(raw, "move", "d", "d/in") == (B.WS_BAD_PATH, None)
    assert B.tar_change(raw, "move", "nope", "c") == (B.WS_NOT_FOUND, None)


def test_the_nesting_base_s_files_are_found_one_level_down():
    raw = _tar({".harness/agent-subdir": b"workspace\n", "workspace/deck.json": b"{}"})
    outcome, raw = B.tar_change(raw, "move", "deck.json", "old/deck.json")
    assert outcome == B.WS_OK and "workspace/old/deck.json" in _files(raw)
    outcome, raw = B.tar_change(raw, "delete", "old")
    assert outcome == B.WS_OK and set(_files(raw)) == {".harness/agent-subdir"}


# ── the hosted backing ────────────────────────────────────────────────────────────────────────
class _Blob:
    def __init__(self, objects=None):
        self.objects = dict(objects or {})

    async def get(self, kb, key):
        return self.objects.get((kb, key))

    async def put(self, kb, key, data):
        self.objects[(kb, key)] = data
        return True

    async def delete(self, kb, key):
        return self.objects.pop((kb, key), None) is not None


def _hosted(entries):
    blob = _Blob({("kb", "sessions/s/workspace.tgz"): _tar(entries)})
    return blob, B.CheckpointWorkspaceFiles(blob, "kb", lambda sid: f"sessions/{sid}/workspace.tgz")


@pytest.mark.asyncio
async def test_hosted_delete_mkdir_move_rewrite_the_checkpoint():
    blob, ws = _hosted({"a.txt": b"a", "d/x": b"x"})
    assert await ws.delete("s", "a.txt") == B.WS_OK
    assert await ws.mkdir("s", "new") == B.WS_OK
    assert await ws.move("s", "d", "e") == B.WS_OK
    assert _files(blob.objects[("kb", "sessions/s/workspace.tgz")]) == {"new": None, "e/x": b"x"}
    assert await ws.read("s", "e/x") == b"x" and await ws.read("s", "d/x") is None


@pytest.mark.asyncio
async def test_hosted_refusals_change_nothing():
    blob, ws = _hosted({"a.txt": b"a"})
    before = dict(blob.objects)
    assert await ws.delete("s", "../a.txt") == B.WS_BAD_PATH
    assert await ws.move("s", "a.txt", "../../b") == B.WS_BAD_PATH
    assert await ws.delete("s", "missing") == B.WS_NOT_FOUND
    assert blob.objects == before


# ── the self-hosted backing ───────────────────────────────────────────────────────────────────
class _Resp:
    def __init__(self, status, body=None):
        self.status_code, self._body = status, body or {}

    def json(self):
        return self._body


def _selfhosted(answer, entries=None):
    blob = _Blob({("ckpt", "sessions/s/workspace.tgz"): _tar(entries)} if entries is not None else {})
    ws = B.RunnerWorkspaceFiles("http://runner", "k", blob, "resp", "ckpt",
                                lambda sid: f"sessions/{sid}/workspace.tgz")
    calls = []

    class _Client:
        async def request(self, method, url, params=None, headers=None):
            calls.append((method, url, params))
            return answer

    ws._c = lambda: _Client()
    return blob, ws, calls


@pytest.mark.asyncio
async def test_selfhosted_changes_the_live_directory_and_then_the_checkpoint():
    blob, ws, calls = _selfhosted(_Resp(200, {"path": "d", "to": "e"}), {"d/x": b"x", "keep": b"k"})
    assert await ws.move("s", "d", "e") == B.WS_OK
    assert calls == [("POST", "http://runner/file/move", {"identifier": "s", "path": "d", "to": "e"})]
    assert _files(blob.objects[("ckpt", "sessions/s/workspace.tgz")]) == {"e/x": b"x", "keep": b"k"}


@pytest.mark.asyncio
async def test_selfhosted_uses_the_path_the_runner_found():
    """nanobot: the runner found deck.json one level down, which is where the checkpoint has it."""
    blob, ws, _calls = _selfhosted(_Resp(200, {"path": "workspace/deck.json"}),
                                   {"workspace/deck.json": b"{}", "deck.json.bak": b""})
    assert await ws.delete("s", "deck.json") == B.WS_OK
    assert set(_files(blob.objects[("ckpt", "sessions/s/workspace.tgz")])) == {"deck.json.bak"}


@pytest.mark.asyncio
async def test_selfhosted_a_file_made_since_the_checkpoint_leaves_it_alone():
    blob, ws, _ = _selfhosted(_Resp(200, {"path": "new.txt"}), {"old.txt": b"o"})
    before = dict(blob.objects)
    assert await ws.delete("s", "new.txt") == B.WS_OK
    assert blob.objects == before


@pytest.mark.asyncio
async def test_selfhosted_with_no_checkpoint_yet():
    blob, ws, _ = _selfhosted(_Resp(200, {"path": "a"}))
    assert await ws.mkdir("s", "a") == B.WS_OK and blob.objects == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("status,outcome", [(404, B.WS_NOT_FOUND), (409, B.WS_EXISTS),
                                            (400, B.WS_BAD_PATH), (500, B.WS_FAILED)])
async def test_selfhosted_a_refusal_touches_no_checkpoint(status, outcome):
    blob, ws, _ = _selfhosted(_Resp(status), {"a": b"a"})
    before = dict(blob.objects)
    assert await ws.delete("s", "a") == outcome
    assert blob.objects == before


@pytest.mark.asyncio
async def test_selfhosted_a_bad_path_never_reaches_the_runner():
    _blob, ws, calls = _selfhosted(_Resp(200))
    assert await ws.delete("s", "../x") == B.WS_BAD_PATH
    assert await ws.move("s", "a", "/../b") == B.WS_BAD_PATH
    assert calls == []


# ── the durable copies ────────────────────────────────────────────────────────────────────────
@pytest.fixture
def captures(monkeypatch):
    """The response blob store, in memory: containers/<sid>/<cfile> and its .meta."""
    store: dict[str, bytes] = {}

    async def _list(prefix, **_k):
        return {"items": [{"file_id": k} for k in sorted(store) if k.startswith(prefix)]}

    async def _get(fid, **_k):
        return store.get(fid)

    async def _put(fid, data, **_k):
        store[fid] = data
        return True

    async def _delete(fid, **_k):
        return store.pop(fid, None) is not None

    async def _bytes(sid, cid):
        data = store.get(f"containers/{sid}/{cid}")
        return (data, "application/octet-stream", cid) if data is not None else None

    monkeypatch.setattr(A, "_blob_list", _list)
    monkeypatch.setattr(A, "_blob_get", _get)
    monkeypatch.setattr(A, "_blob_put", _put)
    monkeypatch.setattr(A, "_blob_delete", _delete)
    monkeypatch.setattr(A, "_container_file_bytes", _bytes)

    class _StoreBlob:
        async def put(self, _kb, key, data):
            store[key] = data
            return True

    monkeypatch.setattr(A.BACKING, "blob", _StoreBlob(), raising=False)

    def add(cid, name, data, ts, app=False):
        store[f"containers/s/{cid}"] = data
        store[f"containers/s/{cid}.meta"] = json.dumps(
            {"filename": name, "written_at": ts, **({"source": "app"} if app else {})}).encode()
    store_add = add
    store_add.store = store
    return store_add


@pytest.mark.asyncio
async def test_a_tombstone_hides_older_captures_of_the_path_and_under_it(captures):
    captures("cfile_agent1", "report.md", b"old", 100.0)
    captures("cfile_agent2", "d/x.md", b"x", 100.0)
    captures("cfile_agent3", "dx.md", b"keep", 100.0)
    await A._put_tombstone("s", "report.md")
    await A._put_tombstone("s", "d")
    assert set(await A._cfile_by_name("s")) == {"dx.md"}


@pytest.mark.asyncio
async def test_a_capture_newer_than_the_tombstone_is_back(captures):
    await A._put_tombstone("s", "report.md")
    captures("cfile_later", "report.md", b"new", time.time() + 10)
    assert (await A._cfile_by_name("s"))["report.md"] == "cfile_later"


@pytest.mark.asyncio
async def test_the_tombstone_replaces_the_app_s_own_copy(captures):
    await B.put_app_capture(A.BACKING.blob, "kb", "s", "sheet.json", b"rows")
    cid = B.app_capture_id("sheet.json")
    assert f"containers/s/{cid}" in captures.store
    await A._put_tombstone("s", "sheet.json")
    assert f"containers/s/{cid}" not in captures.store            # the bytes are gone
    assert json.loads(captures.store[f"containers/s/{cid}.meta"])["deleted"] is True


@pytest.mark.asyncio
async def test_a_restore_does_not_bring_back_what_the_app_deleted(captures, monkeypatch):
    await B.put_app_capture(A.BACKING.blob, "kb", "s", "sheet.json", b"rows")
    await B.put_app_capture(A.BACKING.blob, "kb", "s", "d/x.json", b"x")
    await A._put_tombstone("s", "sheet.json")
    await A._put_tombstone("s", "d")
    written = {}

    class _Ws:
        async def write(self, _sid, name, data):
            written[name] = data
            return True

    monkeypatch.setattr(A.BACKING, "workspace", _Ws(), raising=False)
    assert await A._reapply_app_writes("s") == 0 and written == {}


@pytest.mark.asyncio
async def test_a_removed_path_does_not_come_back_by_its_bare_name(captures, monkeypatch):
    """The read falls back to a capture named by the bare filename (captures from before paths
    were kept). After `notes/a.md` is deleted, a capture called `a.md` is some other file."""
    captures("cfile_legacy", "a.md", b"legacy", 50.0)

    class _Gone:
        async def read(self, *_a, **_k):
            return None

    async def _owned(*_a, **_k):
        return ("org", {})

    monkeypatch.setattr(A.BACKING, "workspace", _Gone(), raising=False)
    monkeypatch.setattr(A, "_owned_session", _owned)
    r = await A.read_session_file("s", "notes/a.md", request=None)
    assert r.body == b"legacy"                                    # before: the old fallback stands
    await A._put_tombstone("s", "notes/a.md")
    with pytest.raises(Exception) as e:
        await A.read_session_file("s", "notes/a.md", request=None)
    assert getattr(e.value, "status_code", None) == 404


@pytest.mark.asyncio
async def test_a_move_carries_the_app_s_copy_to_the_new_name(captures):
    await B.put_app_capture(A.BACKING.blob, "kb", "s", "d/sheet.json", b"typed since the checkpoint")
    captures("cfile_agent", "d/other.md", b"agent's", 100.0)
    await A._carry_app_captures("s", "d", "archive/d")
    await A._put_tombstone("s", "d")
    by = await A._cfile_by_name("s")
    assert set(by) == {"archive/d/sheet.json"}
    assert captures.store[f"containers/s/{by['archive/d/sheet.json']}"] == b"typed since the checkpoint"


# ── the routes ────────────────────────────────────────────────────────────────────────────────
class _Fake:
    def __init__(self, outcome=B.WS_OK):
        self.outcome, self.calls = outcome, []

    async def delete(self, sid, path):
        self.calls.append(("delete", path))
        return self.outcome

    async def mkdir(self, sid, path):
        self.calls.append(("mkdir", path))
        return self.outcome

    async def move(self, sid, path, to):
        self.calls.append(("move", path, to))
        return self.outcome


@pytest.fixture
def routes(monkeypatch, captures):
    state = {"v": {}}

    async def _owned(_r, _sid):
        return ("org", state["v"])

    fake = _Fake()
    monkeypatch.setattr(A, "_owned_session", _owned)
    monkeypatch.setattr(A.BACKING, "workspace", fake, raising=False)
    monkeypatch.setattr(A, "_ws_changed", lambda sid: state.setdefault("changed", []).append(sid))
    state["fake"] = fake
    return state


@pytest.mark.asyncio
async def test_routes_do_the_change_and_answer(routes):
    assert await A.delete_session_file("s", "a.txt", request=None) == \
        {"session_id": "s", "path": "a.txt", "deleted": True}
    assert await A.mkdir_session_file("s", "d", request=None) == {"session_id": "s", "path": "d", "dir": True}
    assert await A.move_session_file("s", "d", A.WorkspaceMove(to="e"), request=None) == \
        {"session_id": "s", "path": "d", "to": "e", "moved": True}
    assert routes["fake"].calls == [("delete", "a.txt"), ("mkdir", "d"), ("move", "d", "e")]
    assert routes["changed"] == ["s", "s", "s"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["running", "starting"])
async def test_routes_refuse_while_a_turn_runs(routes, status):
    routes["v"] = {"turn_status": status}
    for call in (lambda: A.delete_session_file("s", "a", request=None),
                 lambda: A.mkdir_session_file("s", "a", request=None),
                 lambda: A.move_session_file("s", "a", A.WorkspaceMove(to="b"), request=None)):
        with pytest.raises(Exception) as e:
            await call()
        assert e.value.status_code == 409 and e.value.detail["code"] == "session_busy"
    assert routes["fake"].calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["../a", "a/../../b", ".git", ".git/config", ".harness/agent-subdir",
                                  "x/.git/HEAD", ".gitignore", "a\\b"])
async def test_routes_refuse_escapes_and_internal_paths(routes, path):
    for call in (lambda: A.delete_session_file("s", path, request=None),
                 lambda: A.mkdir_session_file("s", path, request=None),
                 lambda: A.move_session_file("s", path, A.WorkspaceMove(to="ok"), request=None),
                 lambda: A.move_session_file("s", "ok", A.WorkspaceMove(to=path), request=None)):
        with pytest.raises(Exception) as e:
            await call()
        assert e.value.status_code == 400 and e.value.detail["code"] == "invalid_input"
    assert routes["fake"].calls == []


@pytest.mark.asyncio
async def test_a_leading_slash_names_the_same_workspace_path(routes):
    """The PUT next door treats `/a.txt` as `a.txt` (_safe_member strips it); these do the same."""
    await A.delete_session_file("s", "/a.txt", request=None)
    assert routes["fake"].calls == [("delete", "a.txt")]


@pytest.mark.asyncio
async def test_move_into_itself_is_refused_before_the_backing(routes):
    with pytest.raises(Exception) as e:
        await A.move_session_file("s", "d", A.WorkspaceMove(to="d/in"), request=None)
    assert e.value.status_code == 400 and routes["fake"].calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome,status,code", [(B.WS_NOT_FOUND, 404, "file_not_found"),
                                                 (B.WS_EXISTS, 409, "file_exists"),
                                                 (B.WS_BAD_PATH, 400, "invalid_input"),
                                                 (B.WS_FAILED, 502, "internal_error")])
async def test_routes_map_the_backing_s_answer(routes, outcome, status, code):
    routes["fake"].outcome = outcome
    with pytest.raises(Exception) as e:
        await A.delete_session_file("s", "a", request=None)
    assert e.value.status_code == status and e.value.detail["code"] == code
    assert "changed" not in routes                     # a refused change evicts nothing


def test_the_action_suffix_routes_a_path_with_slashes():
    from starlette.routing import Match

    def _match(method, path):
        scope = {"type": "http", "method": method, "path": path, "root_path": "", "query_string": b"",
                 "headers": []}
        for r in A.app.router.routes:
            m, child = r.matches(scope)
            if m == Match.FULL:
                return r.endpoint.__name__, child["path_params"]
        return None

    assert _match("POST", "/v1/sessions/s/files/notes/2026/a.md:move") == \
        ("move_session_file", {"sid": "s", "path": "notes/2026/a.md"})
    assert _match("POST", "/v1/sessions/s/files/a/b:mkdir") == \
        ("mkdir_session_file", {"sid": "s", "path": "a/b"})
    assert _match("DELETE", "/v1/sessions/s/files/a/b.txt") == \
        ("delete_session_file", {"sid": "s", "path": "a/b.txt"})
    # the routes beside them are untouched
    assert _match("GET", "/v1/sessions/s/files/a/b.txt")[0] == "read_session_file"
    assert _match("PUT", "/v1/sessions/s/files/a/b.txt")[0] == "write_session_file"


@pytest.mark.asyncio
async def test_a_capture_that_cannot_be_carried_does_not_stop_the_move(routes, monkeypatch):
    """The backing has already moved the file; the tombstone on the source must still land, or the
    next restore writes the app's old copy back under the old name."""
    await B.put_app_capture(A.BACKING.blob, "kb", "s", "sheet.json", b"rows")

    async def _boom(*_a, **_k):
        raise RuntimeError("blob store flaked")

    monkeypatch.setattr(A, "_container_file_bytes", _boom)
    assert (await A.move_session_file("s", "sheet.json", A.WorkspaceMove(to="kept.json"), request=None))["moved"]
    assert "sheet.json" not in await A._cfile_by_name("s")
