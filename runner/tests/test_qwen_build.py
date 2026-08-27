"""The qwen backend, against facts measured on the shipped 0.22.1 binary."""
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from server import Auth, _agent_doc_path, _build_qwen, _claude_passthrough, BACKENDS  # noqa: E402


def _argv(**kw):
    d = tempfile.mkdtemp()
    env: dict = {}
    cmd = _build_qwen("openai-api", Auth(api_key="sk-t", base_url="https://relay.example/v1"),
                      "qwen3.7-max", "do it", d, env, **kw)
    return cmd, d, env


def test_argv_is_headless_stream_json_with_explicit_auth_type():
    """--auth-type is load bearing: without it every -r run on 0.22.1 dies
    'No auth type is selected' — verified live, both directions."""
    cmd, _, _ = _argv()
    assert cmd[:3] == ["qwen", "-p", "do it"]
    assert ["-o", "stream-json"] == cmd[3:5]
    assert "--auth-type" in cmd and "openai" in cmd


def test_yolo_is_present_or_the_agent_has_no_shell_at_all():
    """Verified on 0.22.1 both ways: without --yolo a headless run registers NO shell, write or
    edit tool (the agent literally says "I don't have a shell tool registered" and delegates);
    with it, perm mode is yolo and a real command wrote a file. Losing this flag is a silent
    capability amputation, not a permission tweak."""
    cmd, _, _ = _argv()
    assert "--yolo" in cmd


def test_resume_uses_dash_r():
    cmd, _, _ = _argv(resume_session_id="8e039a38-f91f")
    assert cmd[-2:] == ["-r", "8e039a38-f91f"]


def test_auth_is_environment_only_and_relayed():
    """qwen takes its credential ONLY via env, so every provider rides the loopback relay: the
    CLI's environment holds a per-route relay token — never the real key — and its base URL is
    the relay, which also repairs shapes strict endpoints refuse (LLMTR 400s the array-form
    tool content qwen sends). settings.json must carry neither."""
    _, d, env = _argv()
    assert env["OPENAI_API_KEY"].startswith("hr-relay-")
    assert "sk-t" not in env["OPENAI_API_KEY"]
    assert env["OPENAI_BASE_URL"].startswith("http://127.0.0.1:")
    st = pathlib.Path(d, ".harness", "home", ".qwen", "settings.json").read_text()
    assert "sk-t" not in st and "hr-relay-" not in st


def test_home_is_redirected_into_the_workspace():
    """Sessions live at ~/.qwen/projects/<cwd>/chats; HOME inside the workspace makes resume
    travel with the checkpoint."""
    _, d, env = _argv()
    assert env["HOME"] == f"{d}/.harness/home"


def test_mcp_settings_use_the_gemini_schema():
    d = tempfile.mkdtemp()
    env: dict = {}
    _build_qwen("openai-api", Auth(api_key="k", base_url="https://relay.example/v1"),
                "qwen3.7-max", "hi", d, env,
                mcp_servers=[{"name": "docs", "url": "https://mcp.example/sse",
                              "headers": {"Authorization": "Bearer t"}},
                             {"name": "fs", "command": "npx", "args": ["-y", "server-fs"]}])
    cfg = json.loads(pathlib.Path(d, ".harness", "home", ".qwen", "settings.json").read_text())
    assert cfg["mcpServers"]["docs"] == {"httpUrl": "https://mcp.example/sse",
                                         "headers": {"Authorization": "Bearer t"}}
    assert cfg["mcpServers"]["fs"] == {"command": "npx", "args": ["-y", "server-fs"]}


def test_normalizer_is_the_claude_passthrough():
    """qwen emits claude's stream-json natively (system/init, assistant, result with claude field
    names — captured from a live 0.22.1 turn), so the registry must wire the passthrough."""
    assert BACKENDS["qwen"]["normalize"] is _claude_passthrough


def test_instruction_file_is_qwen_md():
    assert _agent_doc_path("/ws", "qwen").name == "QWEN.md"
