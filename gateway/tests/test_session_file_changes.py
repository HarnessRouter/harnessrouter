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
    assert B.tar_change(raw, "mkdir", "d/e") == (B.WS_UNCHANGED, None)  # already there
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
async def test_selfhosted_changes_the_nesting_base_s_checkpoint_where_its_files_are():
    """nanobot: the runner answers the session-relative path (workspace/deck.json); the checkpoint is
    changed by the caller's path, which tar_change looks for one level down itself. Passing the
    runner's spelling looked for workspace/workspace/deck.json, found nothing, and changed nothing."""
    marker = {".harness/agent-subdir": b"workspace"}
    blob, ws, _calls = _selfhosted(_Resp(200, {"path": "workspace/deck.json"}),
                                   {**marker, "workspace/deck.json": b"{}", "deck.json.bak": b""})
    assert await ws.delete("s", "deck.json") == B.WS_OK
    assert set(_files(blob.objects[("ckpt", "sessions/s/workspace.tgz")])) == {".harness/agent-subdir", "deck.json.bak"}
    blob, ws, _calls = _selfhosted(_Resp(200, {"path": "workspace/a.md", "to": "workspace/b/a.md"}),
                                   {**marker, "workspace/a.md": b"A"})
    assert await ws.move("s", "a.md", "b/a.md") == B.WS_OK
    assert _files(blob.objects[("ckpt", "sessions/s/workspace.tgz")])["workspace/b/a.md"] == b"A"


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
@pytest.mark.parametrize("status,outcome", [(409, B.WS_EXISTS), (400, B.WS_BAD_PATH), (500, B.WS_FAILED)])
async def test_selfhosted_a_refusal_touches_no_checkpoint(status, outcome):
    blob, ws, _ = _selfhosted(_Resp(status), {"a": b"a"})
    before = dict(blob.objects)
    assert await ws.delete("s", "a") == outcome
    assert blob.objects == before


@pytest.mark.asyncio
async def test_selfhosted_a_reaped_live_directory_leaves_the_change_to_the_checkpoint():
    """The live directory is reaped after HR_WORKSPACE_TTL_HOURS; the checkpoint still holds the file,
    and the next turn restores from it. The runner's 404 is not the answer then."""
    blob, ws, _ = _selfhosted(_Resp(404), {"notes.md": b"n", "keep": b"k"})
    assert await ws.delete("s", "notes.md") == B.WS_OK
    assert _files(blob.objects[("ckpt", "sessions/s/workspace.tgz")]) == {"keep": b"k"}
    assert await ws.move("s", "keep", "kept") == B.WS_OK
    assert _files(blob.objects[("ckpt", "sessions/s/workspace.tgz")]) == {"kept": b"k"}
    assert await ws.delete("s", "nowhere") == B.WS_NOT_FOUND
    _blob, ws, _ = _selfhosted(_Resp(404))                        # no checkpoint either
    assert await ws.delete("s", "x") == B.WS_NOT_FOUND


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
    assert f"containers/s/{cid}" not in captures.store and f"containers/s/{cid}.meta" not in captures.store
    assert json.loads(captures.store[A._tomb_key("s", "sheet.json")])["filename"] == "sheet.json"


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
async def test_a_move_carries_the_durable_copies_to_the_new_name(captures):
    """The app's (a restore re-applies it) and the agent's (a reaped workspace's by-path read is
    answered from the captures, and the new name would 404 until the next turn)."""
    await B.put_app_capture(A.BACKING.blob, "kb", "s", "d/sheet.json", b"typed since the checkpoint")
    captures("cfile_agent", "d/other.md", b"agent's", 100.0)
    await A._carry_captures("s", "d", "archive/d", await A._capture_state("s"))
    await A._put_tombstone("s", "d")
    by = await A._cfile_by_name("s")
    assert set(by) == {"archive/d/sheet.json", "archive/d/other.md"}
    assert captures.store[f"containers/s/{by['archive/d/sheet.json']}"] == b"typed since the checkpoint"
    assert captures.store[f"containers/s/{by['archive/d/other.md']}"] == b"agent's"


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
    assert await A.mkdir_session_file("s", "d", request=None) == \
        {"session_id": "s", "path": "d", "dir": True, "created": True}
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


# ── what the review of #478 found ─────────────────────────────────────────────────────────────
_NANOBOT = {".harness/agent-subdir": b"workspace\n",
            ".git/info/exclude": b"# runner\nworkspace/.nanobot/\nworkspace/skills/\nworkspace/memory/\n"
                                 b"workspace/AGENTS.md\n",
            "workspace/AGENTS.md": b"doc", "workspace/skills/s/SKILL.md": b"skill",
            "workspace/memory/m.md": b"mem", "workspace/deck.json": b"{}"}


def test_the_nesting_base_s_own_directory_is_not_a_user_path():
    """DELETE …/files/workspace on nanobot would have removed the agent's whole working directory."""
    raw = _tar(_NANOBOT)
    assert B.tar_change(raw, "delete", "workspace") == (B.WS_NOT_FOUND, None)
    assert B.tar_change(raw, "move", "workspace", "w2") == (B.WS_NOT_FOUND, None)


@pytest.mark.parametrize("op,path,to", [("delete", "skills", ""), ("delete", "AGENTS.md", ""),
                                        ("delete", "memory/m.md", ""), ("move", "skills", "s2"),
                                        ("move", "deck.json", "skills/deck.json"),
                                        ("mkdir", "memory/new", "")])
def test_the_base_s_excluded_machinery_is_refused(op, path, to):
    assert B.tar_change(_tar(_NANOBOT), op, path, to) == (B.WS_BAD_PATH, None)


def test_a_flat_base_s_excluded_files_are_refused_too():
    """opensquilla seeds SOUL.md and memory/ at the session root and excludes them."""
    raw = _tar({".git/info/exclude": b"SOUL.md\nmemory/\n", "SOUL.md": b"s", "memory/x": b"x",
                "notes.md": b"n"})
    assert B.tar_change(raw, "delete", "SOUL.md") == (B.WS_BAD_PATH, None)
    assert B.tar_change(raw, "delete", "memory") == (B.WS_BAD_PATH, None)
    assert B.tar_change(raw, "delete", "notes.md")[0] == B.WS_OK


def test_a_file_written_at_the_root_between_turns_is_still_reachable_on_the_nesting_base():
    """An app's PUT lands at the session root until the next turn adopts it."""
    outcome, raw = B.tar_change(_tar({**_NANOBOT, "sheet.json": b"rows"}), "move", "sheet.json", "kept.json")
    assert outcome == B.WS_OK and _files(raw)["kept.json"] == b"rows"


@pytest.mark.parametrize("op,path,to", [("move", "a.md", "notes.txt/a.md"), ("mkdir", "notes.txt/sub", ""),
                                        ("move", "a.md", "notes.txt/deeper/a.md")])
def test_nothing_goes_under_a_file(op, path, to):
    """Such an archive holds `notes.txt` and `notes.txt/a.md`, and no restore can unpack it."""
    assert B.tar_change(_tar({"notes.txt": b"n", "a.md": b"a"}), op, path, to) == (B.WS_EXISTS, None)


def test_a_rewritten_archive_unpacks(tmp_path):
    _o, raw = B.tar_change(_tar({"./d": None, "./d/x": b"X", "./y": b"Y"}), "move", "d", "e/d")
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:
        tf.extractall(tmp_path, filter="data")
    assert (tmp_path / "e" / "d" / "x").read_bytes() == b"X" and (tmp_path / "y").read_bytes() == b"Y"


@pytest.mark.asyncio
async def test_a_hosted_rewrite_records_the_new_checkpoint_sha():
    """A sandbox kept warm with the old workspace passes the hydrate probe on the old sha, and its next
    checkpoint writes the deleted files back. The new sha matches no sandbox."""
    import hashlib
    blob, ws = _hosted({"a.txt": b"a", "b.txt": b"b"})
    seen = []

    async def _rewritten(sid, sha):
        seen.append((sid, sha))
    ws.on_rewrite = _rewritten
    assert await ws.delete("s", "a.txt") == B.WS_OK
    assert await ws.write("s", "c.txt", b"c")
    assert await ws.delete("s", "missing") == B.WS_NOT_FOUND
    assert len(seen) == 2
    assert seen[-1] == ("s", hashlib.sha256(blob.objects[("kb", "sessions/s/workspace.tgz")]).hexdigest())


@pytest.mark.asyncio
async def test_two_changes_at_once_both_land():
    import asyncio

    class _Slow(_Blob):
        async def get(self, kb, key):
            await asyncio.sleep(0.01)
            return await super().get(kb, key)

    blob = _Slow({("kb", "sessions/s/workspace.tgz"): _tar({"a": b"a", "b": b"b", "c": b"c"})})
    ws = B.CheckpointWorkspaceFiles(blob, "kb", lambda sid: f"sessions/{sid}/workspace.tgz")
    assert await asyncio.gather(ws.delete("s", "a"), ws.delete("s", "b")) == [B.WS_OK, B.WS_OK]
    assert _files(blob.objects[("kb", "sessions/s/workspace.tgz")]) == {"c": b"c"}


@pytest.mark.asyncio
async def test_selfhosted_mkdir_says_when_the_directory_was_there():
    _blob, ws, _ = _selfhosted(_Resp(200, {"path": "d", "created": False}))
    assert await ws.mkdir("s", "d") == B.WS_UNCHANGED


@pytest.mark.asyncio
async def test_mkdir_route_answers_created(routes):
    routes["fake"].outcome = B.WS_UNCHANGED
    assert (await A.mkdir_session_file("s", "d", request=None))["created"] is False


@pytest.mark.asyncio
async def test_a_move_clash_names_the_destination(routes):
    routes["fake"].outcome = B.WS_EXISTS
    with pytest.raises(Exception) as e:
        await A.move_session_file("s", "a.md", A.WorkspaceMove(to="b.md"), request=None)
    assert e.value.status_code == 409 and e.value.detail["param"] == "to"
    assert "'b.md'" in e.value.detail["message"]


@pytest.mark.asyncio
async def test_a_tombstone_the_store_refused_is_reported_and_keeps_the_copy(routes, captures, monkeypatch):
    await B.put_app_capture(A.BACKING.blob, "kb", "s", "sheet.json", b"rows")
    cid = B.app_capture_id("sheet.json")

    async def _refuse(fid, data, **_k):
        return False
    monkeypatch.setattr(A, "_blob_put", _refuse)
    with pytest.raises(Exception) as e:
        await A.delete_session_file("s", "sheet.json", request=None)
    assert e.value.status_code == 502
    assert routes.get("changed") == ["s"]                    # the change itself was made
    assert f"containers/s/{cid}" in captures.store           # the copy was not dropped unrecorded
    assert "Repeat the delete" in e.value.detail["message"]


@pytest.mark.asyncio
async def test_a_delete_of_what_is_already_gone_still_records_it(routes, captures):
    """The repeat a refused tombstone asks for: the workspace answers 404, the removal is recorded."""
    captures("cfile_agent", "old.md", b"agent's", 100.0)
    routes["fake"].outcome = B.WS_NOT_FOUND
    assert (await A.delete_session_file("s", "old.md", request=None))["deleted"] is True
    assert "old.md" not in await A._cfile_by_name("s")


@pytest.mark.asyncio
async def test_the_gateway_records_a_rewritten_checkpoint_s_sha_on_the_session(monkeypatch):
    seen = []

    class _Graph:
        async def upsert(self, label, vid, props, *, raise_on_fail=False):
            seen.append((label, vid, props, raise_on_fail))
    monkeypatch.setattr(A.BACKING, "graph", _Graph(), raising=False)
    await A._checkpoint_rewritten("s", "abc")
    assert seen == [("HarnessSession", "s", {"ws_sha": "abc"}, True)]


@pytest.mark.asyncio
async def test_a_removed_directory_compacts_what_it_hides(captures):
    for name in ("d/a.json", "d/b.json", "keep.json"):
        await B.put_app_capture(A.BACKING.blob, "kb", "s", name, b"x")
    await A._put_tombstone("s", "d/old", await A._capture_state("s"))
    await A._put_tombstone("s", "d", await A._capture_state("s"))
    metas = {json.loads(v)["filename"] for k, v in captures.store.items() if k.endswith(".meta")}
    tombs = {json.loads(v)["filename"] for k, v in captures.store.items() if k.startswith("ws-removed/")}
    assert metas == {"keep.json"} and tombs == {"d"}


@pytest.mark.asyncio
async def test_every_tombstone_is_read_beside_the_capture_window(captures):
    """The captures stay a first page of 200 metas; the tombstones live apart and are read in full,
    so none can fall out of a window and let the file it hid come back."""
    for i in range(250):
        captures(f"cfile_{i:04d}", f"f{i}.md", b"x", 100.0)
    for i in range(30):
        await A._put_tombstone("s", f"gone{i}.md")
    await A._put_tombstone("s", "f0.md")
    caps, tombs = await A._capture_state("s")
    assert len(tombs) == 31 and "f0.md" not in caps and len(caps) == 199


@pytest.mark.asyncio
async def test_a_delete_of_a_path_that_never_existed_stores_nothing(routes, captures):
    routes["fake"].outcome = B.WS_NOT_FOUND
    for i in range(5):
        with pytest.raises(Exception):
            await A.delete_session_file("s", f"never{i}.md", request=None)
    assert not [k for k in captures.store if k.startswith("ws-removed/")]


@pytest.mark.asyncio
async def test_the_read_fallback_scans_the_captures_once(captures, monkeypatch):
    captures("cfile_legacy", "a.md", b"legacy", 50.0)
    calls = []
    real = A._capture_state

    async def _counted(sid):
        calls.append(sid)
        return await real(sid)

    class _Gone:
        async def read(self, *_a, **_k):
            return None

    async def _owned(*_a, **_k):
        return ("org", {})

    monkeypatch.setattr(A, "_capture_state", _counted)
    monkeypatch.setattr(A.BACKING, "workspace", _Gone(), raising=False)
    monkeypatch.setattr(A, "_owned_session", _owned)
    assert (await A.read_session_file("s", "notes/a.md", request=None)).body == b"legacy"
    assert calls == ["s"]


def test_a_hard_link_to_a_removed_file_keeps_its_bytes(tmp_path):
    """tar stores a second hard link as a pointer to the first member's name. Removing or renaming that
    member left a pointer to nothing, and an archive no restore can unpack."""
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tf:
        info = tarfile.TarInfo("./a.txt"); info.size = 1
        tf.addfile(info, io.BytesIO(b"A"))
        for n in ("./b.txt", "./c.txt"):
            ln = tarfile.TarInfo(n); ln.type, ln.linkname = tarfile.LNKTYPE, "./a.txt"
            tf.addfile(ln)
    outcome, raw = B.tar_change(out.getvalue(), "delete", "a.txt")
    assert outcome == B.WS_OK
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:
        tf.extractall(tmp_path / "del", filter="data")
    assert (tmp_path / "del" / "b.txt").read_bytes() == b"A" and (tmp_path / "del" / "c.txt").read_bytes() == b"A"
    outcome, raw = B.tar_change(out.getvalue(), "move", "a.txt", "d/a.txt")
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:
        tf.extractall(tmp_path / "mv", filter="data")
    assert (tmp_path / "mv" / "d" / "a.txt").read_bytes() == b"A" and (tmp_path / "mv" / "b.txt").read_bytes() == b"A"


def test_a_new_folder_on_the_nesting_base_goes_in_the_agent_s_directory():
    """Where the runner now makes it, so the live directory and the checkpoint agree."""
    outcome, raw = B.tar_change(_tar(_NANOBOT), "mkdir", "slides/old")
    assert outcome == B.WS_OK and "workspace/slides/old" in _files(raw)
    raw = _tar({**_NANOBOT, "workspace/notes": b"a file"})
    assert B.tar_change(raw, "mkdir", "notes/x") == (B.WS_EXISTS, None)


@pytest.mark.asyncio
async def test_a_sha_that_cannot_be_recorded_leaves_the_archive_as_it_was():
    """Rewriting under a sha that still matches the warm sandbox would be undone by its next checkpoint."""
    blob, ws = _hosted({"a.txt": b"a"})
    before = dict(blob.objects)

    async def _down(_sid, _sha):
        raise RuntimeError("graph store down")
    ws.on_rewrite = _down
    assert await ws.delete("s", "a.txt") == B.WS_FAILED
    assert not await ws.write("s", "b.txt", b"b")
    assert blob.objects == before


def test_a_delete_on_the_nesting_base_removes_every_copy():
    """A file at the root beside the agent's copy (an app's PUT from before writes went where the file
    is) would be adopted back next turn if only the agent's copy went."""
    outcome, raw = B.tar_change(_tar({**_NANOBOT, "notes.md": b"app", "workspace/notes.md": b"agent"}),
                                "delete", "notes.md")
    assert outcome == B.WS_OK and not {"notes.md", "workspace/notes.md"} & set(_files(raw))


@pytest.mark.asyncio
async def test_a_hosted_put_replaces_the_nesting_base_s_file_where_it_is():
    blob, ws = _hosted({**_NANOBOT})
    assert await ws.write("s", "deck.json", b'{"v":2}')
    files = _files(blob.objects[("kb", "sessions/s/workspace.tgz")])
    assert files["workspace/deck.json"] == b'{"v":2}' and "deck.json" not in files
    assert await ws.read("s", "deck.json") == b'{"v":2}'
    assert await ws.write("s", "new.json", b"n")                 # a new file: the root, adopted next turn
    assert _files(blob.objects[("kb", "sessions/s/workspace.tgz")])["new.json"] == b"n"
    assert await ws.read("s", "new.json") == b"n"


@pytest.mark.asyncio
async def test_a_put_waits_for_a_change_of_the_same_session(routes, monkeypatch):
    """Under the same lock as delete, mkdir and move: a PUT racing a delete of its path would have
    its fresh copy dropped by the delete's tombstone."""
    import asyncio
    order = []

    class _Ws(_Fake):
        async def delete(self, sid, path):
            order.append("delete start")
            await asyncio.sleep(0.02)
            order.append("delete end")
            return B.WS_OK

        async def write(self, sid, path, data):
            order.append("put")
            return True

    monkeypatch.setattr(A.BACKING, "workspace", _Ws(), raising=False)
    await asyncio.gather(A.delete_session_file("s", "n.md", request=None),
                         A.write_session_file("s", "n.md", A.WorkspaceWrite(content="x"), request=None))
    assert order == ["delete start", "delete end", "put"]
