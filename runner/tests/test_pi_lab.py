import json
import pathlib
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from server import Auth, BACKENDS, _build_pi, _pi_lab_to_claude, _pi_lab_eof
from pi_lab import FEATURES, build


def test_checkpoint_excludes_credentials_but_restores_conversation(tmp_path, monkeypatch):
    import io
    import tarfile
    import server
    from fastapi.testclient import TestClient
    monkeypatch.setattr(server, "WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    monkeypatch.setattr(server, "SPOOL_DIR", str(tmp_path))
    monkeypatch.setattr(server, "_WS_MARKER_DIR", str(tmp_path / "markers"))
    monkeypatch.setattr(server, "_SESSION_UIDS", False)
    monkeypatch.setattr(server, "_SANDBOX_PER_SESSION", False)
    monkeypatch.setattr(server, "_INTERNAL_KEY", "")
    root = pathlib.Path(server._ws("pilab-test"))
    agent = root / ".harness/home/.pi-lab/agent"
    slug = "--" + str(root).lstrip("/").replace("/", "-") + "--"
    history = agent / "sessions" / slug / "history.jsonl"
    history.parent.mkdir(parents=True)
    history.write_text(json.dumps({"type": "session", "id": "known-session", "cwd": str(root)}) + "\n")
    for name in ("auth.json", "models.json", "mcp.json"):
        (agent / name).write_text('{"key": "SECRET_SENTINEL"}')
    with TestClient(server.app) as client:
        response = client.get("/checkpoint?identifier=pilab-test")
        assert response.status_code == 200, response.text
        with tarfile.open(fileobj=io.BytesIO(response.content), mode="r:gz") as archive:
            names = archive.getnames()
            assert any(n.endswith("history.jsonl") for n in names)
            for member in archive.getmembers():
                if member.isfile():
                    assert b"SECRET_SENTINEL" not in archive.extractfile(member).read(), member.name
        assert client.delete("/workspace?identifier=pilab-test").status_code == 200
        assert not history.exists()
        assert client.post("/hydrate?identifier=pilab-test", content=response.content).status_code == 200
    assert history.exists()
    assert not (agent / "models.json").exists()


def test_turn_hands_the_harness_switches_to_pi_lab(tmp_path, monkeypatch):
    import pi_lab
    import server
    from fastapi.testclient import TestClient
    monkeypatch.setattr(server, "_SESSION_UIDS", False)
    monkeypatch.setattr(server, "_INTERNAL_KEY", "")
    seen = {}

    def build(*args, config=None, **kw):
        seen["config"] = config
        raise HTTPException(418, "stop before spawning")
    monkeypatch.setattr(pi_lab, "build", build)
    with TestClient(server.app) as client:
        r = client.post("/turn", json={"backend": "pi-lab", "prompt": "hi", "cwd": str(tmp_path),
                                       "pi_lab": {"actionFusion": False}})
    assert r.status_code == 418, r.text
    assert seen["config"] == {"actionFusion": False}


def test_provider_failure_and_model_substitution_are_not_success():
    for message, expected in [
        ({"model": "main", "stopReason": "error", "errorMessage": "401 invalid key"}, "401 invalid key"),
        ({"model": "substituted", "content": [{"type": "text", "text": "hello"}]}, "instead of"),
    ]:
        state = {"model": "main"}
        _pi_lab_to_claude({"type": "pi_lab_ready", "config": {}, "revision": "test"}, state)
        _pi_lab_to_claude({"type": "message_end", "message": {"role": "assistant", **message}}, state)
        _pi_lab_to_claude({"type": "agent_end"}, state)
        result, = _pi_lab_eof(state, 0)
        assert result["is_error"] and expected in result["result"]


@pytest.fixture
def installed(tmp_path, monkeypatch):
    monkeypatch.setenv("HR_PI_LAB_BIN", str(tmp_path / "pi"))
    monkeypatch.setenv("HR_PI_LAB_SOL_PI_ENTRY", str(tmp_path / "upstream.ts"))
    return tmp_path, {"HOME": str(tmp_path / ".harness/home")}


def launch(installed, **kw):
    root, env = installed
    return build(_build_pi, "openai-api", Auth(api_key="test", base_url="http://localhost/v1", api_format="openai"),
                 "main-model", "hello", str(root), env, **kw)


def test_independent_identity_and_storage(installed):
    root, env = installed
    cmd = launch(installed, resume_session_id="session-123")
    assert cmd[0] == str(root / "pi")
    assert BACKENDS["pi-lab"]["normalize"] is not BACKENDS["pi"]["normalize"]
    assert pathlib.Path(env["PI_CODING_AGENT_DIR"]).parts[-2:] == (".pi-lab", "agent")
    assert not (root / ".harness/home/.pi").exists()
    assert cmd[cmd.index("--session-id") + 1] == "session-123"
    cfg = json.loads((root / ".harness/pi-lab/effective-config.json").read_text())
    assert all(cfg[k] for k in FEATURES)
    assert cfg["evidencePreservingReducerProvider"] == "hr"
    assert cfg["evidencePreservingReducerModel"] == "main-model"


@pytest.mark.parametrize("mask", range(16))
def test_all_switch_combinations_reach_upstream_factory(installed, mask):
    flags = {k: bool(mask & (1 << i)) for i, k in enumerate(FEATURES)}
    launch(installed, config=flags)
    wrapper = (installed[0] / ".harness/pi-lab/extension.ts").read_text()
    cfg = json.loads((installed[0] / ".harness/pi-lab/effective-config.json").read_text())
    assert {k: cfg[k] for k in FEATURES} == flags
    assert "registerConfiguredFeatures(observed, config)" in wrapper


def test_reducer_registered_on_same_connection(installed):
    launch(installed, config={"reducerModel": "small-model", "cacheWriteReadRatio": 0})
    models = json.loads((pathlib.Path(installed[1]["PI_CODING_AGENT_DIR"]) / "models.json").read_text())
    assert [m["id"] for m in models["providers"]["hr"]["models"]] == ["main-model", "small-model"]


@pytest.mark.parametrize("tool", ["bash", "write", "edit", "obs_recall", "update_plan"])
def test_switches_cannot_bypass_tool_policy(installed, tool):
    with pytest.raises(HTTPException) as exc:
        launch(installed, tools_disabled=[tool])
    assert exc.value.status_code == 400


def test_original_pi_loads_no_pi_lab(installed):
    root, env = installed
    cmd = _build_pi("openai", Auth(api_key="test"), "main", "hi", str(root), env)
    assert cmd[0] == "pi" and "--extension" not in cmd
    assert pathlib.Path(env["PI_CODING_AGENT_DIR"]).parts[-2:] == (".pi", "agent")


def test_compaction_continuation_has_one_terminal_event_and_aux_usage():
    state = {"model": "main", "final": "", "_pi_lab_ready": {"revision": "test"}}
    for text in ["first phase", "final answer"]:
        _pi_lab_to_claude({"type": "message_end", "message": {"role": "assistant", "model": "main",
                           "content": [{"type": "text", "text": text}], "usage": {"input": 10, "output": 2}}}, state)
        assert _pi_lab_to_claude({"type": "agent_end"}, state) == []
    _pi_lab_to_claude({"type": "pi_lab_event", "kind": "provider_response", "provider": "hr",
                       "model": "small", "usage": {"input": 100, "output": 5}}, state)
    _pi_lab_to_claude({"type": "pi_lab_event", "kind": "applied", "usage": {"input": 100}}, state)
    result, = _pi_lab_eof(state, 0)
    assert result["result"] == "final answer"
    assert result["usage"]["input_tokens"] == 20
    assert result["pi_lab"]["auxiliary_usage"]["hr/small"]["input"] == 100


def test_premature_exit_is_not_success():
    result, = _pi_lab_eof({"model": "main"}, 0)
    assert result["is_error"]


def test_a_retried_attempt_does_not_fail_the_turn():
    """pi's own retry after a cut reply stream (verbatim capture, see test_pi_normalize): Pi Lab
    waits for EOF, and the attempt's error must not outlive the retry that succeeded."""
    events = [json.loads(line) for line in
              (pathlib.Path(__file__).parent / "fixtures" / "pi_retry_after_stream_cut.jsonl").read_text().splitlines()]
    state = {"model": "test-model", "final": ""}
    for event in [{"type": "pi_lab_ready", "config": {}, "revision": "test"}, *events]:
        _pi_lab_to_claude(event, state)
    result, = _pi_lab_eof(state, 0)
    assert not result["is_error"] and result["result"] == "The file is saved as Report.pdf"
