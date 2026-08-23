"""The session write-wall (HR_SESSION_UIDS): what it changes when declared, and that it changes
nothing when it is not. The uid switch itself needs root and is exercised live on a self-hosted
box; these pin the parts a test process can reach."""
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402


def test_wall_off_changes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_SESSION_UIDS", False)
    ws = tmp_path / "s1"
    ws.mkdir()
    assert server._session_uid(str(ws)) is None
    assert server._as_session(str(ws)) == {}
    server._isolate_session(str(ws))          # a no-op, not an error, on a non-root test process
    assert (ws.stat().st_mode & 0o777) == 0o755 or (ws.stat().st_mode & 0o777) == 0o775


def test_session_uid_reads_the_directory_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_SESSION_UIDS", True)
    ws = tmp_path / "s2"
    ws.mkdir()
    # Owned by the test user: outside the session range, so "not isolated yet".
    assert server._session_uid(str(ws)) is None
    assert server._as_session(str(ws)) == {}
    fake = server._SESSION_UID_BASE + 7
    real_stat = os.stat

    class St:
        st_uid = fake

    monkeypatch.setattr(server.os, "stat", lambda p, *a, **k: St() if str(p) == str(ws) else real_stat(p, *a, **k))
    assert server._session_uid(str(ws)) == fake
    assert server._as_session(str(ws)) == {"user": fake, "group": fake, "extra_groups": []}


@pytest.mark.parametrize("name,stripped", [
    ("HARNESS_INTERNAL_KEY", True), ("HR_AUTH_PASSWORD", True), ("HR_AUTH_USER", True),
    ("HR_SECRET_KEY", True), ("HR_SESSION_KEY", True), ("OPENAI_API_KEY", True),
    ("AWS_SECRET_ACCESS_KEY", True), ("GITHUB_TOKEN", True), ("DB_PASSWORD", True),
    ("PATH", False), ("HOME", False), ("HR_DSH_PYTHON", False), ("HR_PI_MCP_EXT", False),
    ("NODE_PATH", False), ("HERMES_DISABLE_LAZY_INSTALLS", False), ("OFFICECLI_RESIDENT_FLUSH", False),
    ("HARNESS_WORKSPACE", False), ("HR_BACKENDS", False),
])
def test_child_env_strips_secrets_and_keeps_the_runtime(monkeypatch, name, stripped):
    monkeypatch.setenv(name, "v")
    assert (name not in server._child_env()) is stripped


def test_own_tree_only_reowns_the_listed_owners_and_never_hard_links(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    (root / "sub").mkdir(parents=True)
    (root / "a.txt").write_text("a")
    (root / "sub" / "b.txt").write_text("b")
    (root / "planted").write_text("x")
    os.link(root / "planted", root / "link2")            # nlink == 2 on both names
    os.symlink("/etc/hostname", root / "sym")
    calls: list[tuple[str, int, int]] = []
    monkeypatch.setattr(server.os, "lchown", lambda p, u, g: calls.append((os.path.basename(p), u, g)))
    me = os.getuid()
    server._own_tree(str(root), 31337, {me})
    names = {c[0] for c in calls}
    assert {"sub", "a.txt", "b.txt", "sym"} <= names
    assert "planted" not in names and "link2" not in names
    assert all(u == 31337 and g == 31337 for _, u, g in calls)
    calls.clear()
    server._own_tree(str(root), 31337, {0})               # nothing here is root's: nothing moves
    assert calls == []


def test_runner_api_requires_the_internal_key_behind_the_wall(monkeypatch):
    monkeypatch.setattr(server, "_SESSION_UIDS", True)
    monkeypatch.setattr(server, "_INTERNAL_KEY", "k-test")
    c = TestClient(server.app)
    assert c.get("/healthz").status_code == 200
    assert c.get("/backends").status_code == 401
    assert c.get("/backends", headers={"x-harness-internal": "wrong"}).status_code == 401
    assert c.get("/backends", headers={"x-harness-internal": "k-test"}).status_code == 200


def test_runner_api_is_open_when_the_wall_is_off(monkeypatch):
    monkeypatch.setattr(server, "_SESSION_UIDS", False)
    monkeypatch.setattr(server, "_INTERNAL_KEY", "k-test")
    assert TestClient(server.app).get("/backends").status_code == 200


def test_turn_refuses_a_caller_chosen_cwd_behind_the_wall(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "_SESSION_UIDS", True)
    monkeypatch.setattr(server, "_INTERNAL_KEY", "")
    c = TestClient(server.app)
    r = c.post("/turn?identifier=sA", json={"prompt": "x", "backend": "claude", "cwd": str(tmp_path)})
    assert r.status_code == 400
    assert "identifier" in r.text


def test_hermes_vision_auth_is_its_own_route(tmp_path, monkeypatch):
    """The model hermes asks about images is the one the gateway resolved, never the writing
    model; the credential rides the loopback relay (OpenAI-compatible) and the environment, and
    is not written into config.yaml (which is checkpointed with the workspace)."""
    import yaml
    env = {"HOME": str(tmp_path)}
    monkeypatch.setattr(server, "_hermes_relay_route",
                        lambda base, key: ("http://127.0.0.1:1/v1", "hr-relay-placeholder"))
    server._hermes_prepare_env("openai-api", server.Auth(api_key="k-chat", base_url="https://x/v1"),
                               str(tmp_path), env, model="qwen/qwen3.8-max",
                               vision_auth={"provider": "openai-api", "model": "gpt-5.4-mini",
                                            "base_url": "https://vision.example/v1", "api_key": "k-vision"})
    cfg = yaml.safe_load((tmp_path / ".hermes" / "config.yaml").read_text())
    assert cfg["model"]["default"] == "qwen/qwen3.8-max"            # writing model untouched
    v = cfg["auxiliary"]["vision"]
    assert v["model"] == "gpt-5.4-mini" and v["provider"] == "openai-api"
    assert v["base_url"] == "http://127.0.0.1:1/v1"                 # relay, not the endpoint
    assert v["key_env"] == "HR_VISION_API_KEY" and "api_key" not in v
    assert env["HR_VISION_API_KEY"] == "hr-relay-placeholder"       # placeholder, never the key
    assert "k-vision" not in (tmp_path / ".hermes" / "config.yaml").read_text()


def test_hermes_without_vision_auth_keeps_its_default(tmp_path):
    import yaml
    env = {"HOME": str(tmp_path)}
    server._hermes_prepare_env("anthropic", server.Auth(api_key="k"), str(tmp_path), env,
                               model="claude-sonnet-5", vision_auth=None)
    cfg = yaml.safe_load((tmp_path / ".hermes" / "config.yaml").read_text())
    assert "auxiliary" not in cfg
