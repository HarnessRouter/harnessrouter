"""What the agent can write must not steer what the runner does as root.

`.harness/agent-subdir` sits in the session's tree. An absolute path in it made every file route read outside the session, as root:
GET /file served /proc/self/environ and /etc/shadow. And a codex resume ran outside the turn's filesystem identity, so a rollout the
agent swapped for a link wrote its chosen lines anywhere on the box."""
import ast
import os
import pathlib

import pytest
from fastapi.testclient import TestClient

import server


@pytest.fixture
def ws(tmp_path, monkeypatch):
    root = tmp_path / "root"; root.mkdir()
    monkeypatch.setattr(server, "WORKSPACE_ROOT", str(root))
    monkeypatch.setattr(server, "_SANDBOX_PER_SESSION", False)
    d = root / "hsessmarker"; d.mkdir()
    return d


def _mark(d, value):
    (d / ".harness").mkdir(exist_ok=True)
    (d / ".harness" / "agent-subdir").write_text(value)


@pytest.mark.parametrize("value", ["/proc/self", "/etc", "//etc", "/", "..", "../..", "other", "workspace/../..", "./workspace", ""])
def test_any_value_but_the_runners_own_means_the_session_itself(ws, tmp_path, value):
    (ws / "workspace").mkdir(); (ws / "other").mkdir()
    _mark(ws, value)
    assert server._visible_root(str(ws)) == str(ws)


def test_the_value_the_runner_writes_still_works(ws):
    (ws / server._NANOBOT_WS).mkdir()
    server._agent_subdir_set(str(ws), server._NANOBOT_WS)
    assert server._visible_root(str(ws)) == os.path.join(str(ws), server._NANOBOT_WS)


def test_the_right_name_as_a_link_out_of_the_session_is_refused(ws, tmp_path):
    outside = tmp_path / "outside"; outside.mkdir()
    (ws / server._NANOBOT_WS).symlink_to(outside)
    server._agent_subdir_set(str(ws), server._NANOBOT_WS)
    assert server._visible_root(str(ws)) == str(ws)


def test_the_file_route_reads_nothing_through_a_planted_marker(ws, tmp_path):
    outside = tmp_path / "outside"; outside.mkdir(); (outside / "secret").write_text("CANARY")
    c = TestClient(server.app, raise_server_exceptions=False)
    assert c.get("/file", params={"identifier": ws.name, "path": "secret"}).status_code == 404
    _mark(ws, str(outside))
    r = c.get("/file", params={"identifier": ws.name, "path": "secret"})
    assert r.status_code == 404 and b"CANARY" not in r.content


def test_a_control_a_real_file_is_still_served(ws):
    (ws / "report.txt").write_text("hello")
    c = TestClient(server.app, raise_server_exceptions=False)
    assert c.get("/file", params={"identifier": ws.name, "path": "report.txt"}).content == b"hello"


def test_the_file_route_reads_as_the_session(ws, monkeypatch):
    (ws / "report.txt").write_text("hello")
    seen = []
    real = server._fs_as

    def spy(uid):
        seen.append(uid)
        return real(None)

    monkeypatch.setattr(server, "_fs_as", spy)
    monkeypatch.setattr(server, "_session_uid", lambda w: 20123)
    c = TestClient(server.app, raise_server_exceptions=False)
    assert c.get("/file", params={"identifier": ws.name, "path": "report.txt"}).status_code == 200
    assert seen == [20123]


def test_an_unreadable_file_is_not_found_rather_than_an_error(ws, monkeypatch):
    p = ws / "report.txt"; p.write_text("hello")
    real = pathlib.Path.read_bytes
    monkeypatch.setattr(pathlib.Path, "read_bytes", lambda self: (_ for _ in ()).throw(PermissionError()) if self.name == "report.txt" else real(self))
    c = TestClient(server.app, raise_server_exceptions=False)
    assert c.get("/file", params={"identifier": ws.name, "path": "report.txt"}).status_code == 404


@pytest.mark.parametrize("sid", [".", ".."])
def test_a_dot_is_not_a_session(ws, sid):
    c = TestClient(server.app, raise_server_exceptions=False)
    assert c.get("/file", params={"identifier": sid, "path": "x"}).status_code == 400
    assert c.delete("/workspace", params={"identifier": sid}).status_code == 400
    assert pathlib.Path(server.WORKSPACE_ROOT).is_dir() and ws.is_dir()


def test_every_rollout_rewrite_is_inside_the_sessions_identity():
    """Read off the source: a call outside `with _fs_as(...)` is a root write through whatever the agent left there."""
    src = pathlib.Path(server.__file__).read_text(); tree = ast.parse(src)
    parents = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_sanitize_codex_rollout"]
    assert len(calls) >= 2

    def in_scope(n):
        while n in parents:
            n = parents[n]
            if isinstance(n, ast.With) and any("_fs_as" in ast.get_source_segment(src, i.context_expr) for i in n.items):
                return True
            if isinstance(n, ast.FunctionDef) and n.name in ("_start_turn",):
                return True
        return False
    fns = {n.lineno: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    outside = [c.lineno for c in calls if not in_scope(c) and not _caller_holds_scope(tree, src, c)]
    assert not outside, f"outside the session's identity at lines {outside}"


def _caller_holds_scope(tree, src, call):
    """The exec path's helper runs only from _build_codex, called inside the turn's scope in _start_turn."""
    parents = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
    n = call
    while n in parents and not isinstance(n, ast.FunctionDef):
        n = parents[n]
    return getattr(n, "name", "") == "_build_codex"
