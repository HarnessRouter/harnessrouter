"""Tests for the Oh My Pi (OMP) runner backend."""
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from server import (  # noqa: E402
    _agent_doc_path,
    _build_omp,
    _omp_has_session,
    _omp_to_claude,
    _omp_write_mcp,
    _write_skills,
    Auth,
)


def _flat(chunks):
    return [e for evs in chunks for e in evs]


def _run_omp_events(events, model="gpt-5.4"):
    state = {"model": model, "final": ""}
    out = []
    for ev in events:
        out.append(_omp_to_claude(ev, state))
    return out, state


# ── argv construction and configuration ──────────────────────────────────────────


def test_omp_argv_native_provider():
    d = tempfile.mkdtemp()
    env = {"HOME": d}
    auth = Auth(api_key="sk-ant-test")
    cmd = _build_omp("anthropic", auth, "claude-sonnet-4.6", "hello world", d, env)

    assert cmd[:3] == ["omp", "-p", "--mode"]
    assert cmd[3] == "json"
    assert "--model" in cmd and "claude-sonnet-4.6" in cmd
    assert "--auto-approve" in cmd
    assert "--no-extensions" in cmd
    assert cmd[-1] == "hello world"
    assert env.get("ANTHROPIC_API_KEY") == "sk-ant-test"
    assert env.get("PI_CODING_AGENT_DIR") == str(pathlib.Path(d) / ".omp" / "agent")


def test_omp_argv_custom_provider_writes_models_json():
    d = tempfile.mkdtemp()
    env = {"HOME": d}
    auth = Auth(api_key="sk-test", base_url="https://relay.example/v1", api_format="openai")
    cmd = _build_omp("openai-api", auth, "gpt-5.4", "do work", d, env)

    assert "--model" in cmd
    idx = cmd.index("--model")
    assert cmd[idx + 1] == "hr/gpt-5.4"

    cfg_path = pathlib.Path(d) / ".omp" / "agent" / "models.json"
    assert cfg_path.exists()
    cfg = json.loads(cfg_path.read_text())
    assert "hr" in cfg["providers"]
    assert cfg["providers"]["hr"]["baseUrl"] == "https://relay.example/v1"
    assert cfg["providers"]["hr"]["api"] == "openai-completions"
    assert cfg["providers"]["hr"]["models"][0]["id"] == "gpt-5.4"


def test_omp_resume_skipped_when_session_missing():
    d = tempfile.mkdtemp()
    env = {"HOME": d}
    auth = Auth(api_key="sk-test")
    cmd = _build_omp("openai", auth, "gpt-5.4", "continue", d, env, resume_session_id="missing_sid")
    assert "--resume" not in cmd


def test_omp_resume_included_when_session_file_exists():
    d = tempfile.mkdtemp()
    env = {"HOME": d}
    sess_dir = pathlib.Path(d) / ".omp" / "agent" / "sessions" / "proj"
    sess_dir.mkdir(parents=True, exist_ok=True)
    (sess_dir / "2026-09-05_present_sid_123.jsonl").write_text('{"type":"session"}\n')

    auth = Auth(api_key="sk-test")
    cmd = _build_omp("openai", auth, "gpt-5.4", "continue", d, env, resume_session_id="present_sid_123")
    assert "--resume" in cmd
    idx = cmd.index("--resume")
    assert cmd[idx + 1] == "present_sid_123"


def test_omp_disabled_tools_generates_tools_flag():
    d = tempfile.mkdtemp()
    env = {"HOME": d}
    auth = Auth(api_key="sk-test")
    cmd = _build_omp("openai", auth, "gpt-5.4", "do task", d, env, tools_disabled=["bash", "browser"])

    tools_flags = [x for x in cmd if x.startswith("--tools=")]
    assert len(tools_flags) == 1
    enabled = tools_flags[0].split("=")[1].split(",")
    assert "bash" not in enabled
    assert "browser" not in enabled
    assert "read" in enabled
    assert "edit" in enabled


def test_omp_all_tools_disabled_passes_no_tools():
    d = tempfile.mkdtemp()
    env = {"HOME": d}
    auth = Auth(api_key="sk-test")
    all_tools = ["bash", "read", "write", "edit", "glob", "grep", "lsp", "python", "todo", "task", "browser", "web_search"]
    cmd = _build_omp("openai", auth, "gpt-5.4", "do task", d, env, tools_disabled=all_tools)
    assert "--no-tools" in cmd


def test_omp_mcp_config_written():
    d = tempfile.mkdtemp()
    env = {"HOME": d}
    auth = Auth(api_key="sk-test")
    mcp_servers = [
        {"name": "fetcher", "url": "https://mcp.example/sse", "auth": "bearer token123"},
        {"name": "db", "url": "https://db.example/mcp", "headers": {"X-Custom": "val"}},
    ]
    _build_omp("openai", auth, "gpt-5.4", "task", d, env, mcp_servers=mcp_servers)

    mcp_path = pathlib.Path(d) / ".omp" / "agent" / "mcp.json"
    assert mcp_path.exists()
    mcp_data = json.loads(mcp_path.read_text())
    assert "fetcher" in mcp_data["mcpServers"]
    assert mcp_data["mcpServers"]["fetcher"]["url"] == "https://mcp.example/sse"
    assert mcp_data["mcpServers"]["fetcher"]["headers"]["Authorization"] == "bearer token123"
    assert mcp_data["mcpServers"]["db"]["headers"]["X-Custom"] == "val"


def test_omp_doc_and_skills_paths():
    assert _agent_doc_path("/workspace", "omp").name == "AGENTS.md"

    d = tempfile.mkdtemp()
    skills = [{"name": "test-skill", "content": "# Test Skill"}]
    installed = _write_skills(d, skills, backend="omp")
    assert len(installed) == 1
    assert installed[0]["entry"] == ".harness/home/.omp/agent/skills/test-skill/SKILL.md"
    assert (pathlib.Path(d) / ".harness" / "home" / ".omp" / "agent" / "skills" / "test-skill" / "SKILL.md").exists()


# ── event stream normalization ───────────────────────────────────────────────────


def test_omp_normalizer_session_init():
    stream = [
        {"type": "session", "version": 3, "id": "omp_sess_999", "timestamp": "2026-09-05T08:00:00.000Z", "cwd": "/ws"},
        {"type": "agent_end", "messages": [], "isTerminal": True},
    ]
    chunks, _ = _run_omp_events(stream, model="gpt-5.4")
    evs = _flat(chunks)
    assert evs[0]["type"] == "system"
    assert evs[0]["subtype"] == "init"
    assert evs[0]["session_id"] == "omp_sess_999"
    assert evs[0]["model"] == "gpt-5.4"


def test_omp_normalizer_streaming_text_and_usage():
    stream = [
        {"type": "session", "version": 3, "id": "s1", "cwd": "/ws"},
        {"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "Hello"}},
        {"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": " world!"}},
        {"type": "message_end", "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "Hello world!"}],
            "usage": {"input": 1500, "output": 25, "cacheRead": 300, "cacheWrite": 0},
            "stopReason": "stop",
        }},
        {"type": "agent_end", "messages": [], "isTerminal": True},
    ]
    chunks, state = _run_omp_events(stream)
    evs = _flat(chunks)

    deltas = [e for e in evs if e.get("type") == "assistant"]
    assert len(deltas) == 2
    assert deltas[0]["message"]["content"][0]["text"] == "Hello"
    assert deltas[1]["message"]["content"][0]["text"] == " world!"

    results = [e for e in evs if e.get("type") == "result"]
    assert len(results) == 1
    assert results[0]["subtype"] == "success"
    assert results[0]["is_error"] is False
    assert results[0]["result"] == "Hello world!"
    assert results[0]["usage"]["input_tokens"] == 1500
    assert results[0]["usage"]["output_tokens"] == 25
    assert results[0]["usage"]["cache_read_tokens"] == 300


def test_omp_normalizer_tool_calls():
    stream = [
        {"type": "session", "version": 3, "id": "s2", "cwd": "/ws"},
        {"type": "tool_execution_start", "toolCallId": "call_123", "toolName": "bash", "args": {"command": "ls -la"}},
        {"type": "tool_execution_end", "toolCallId": "call_123", "toolName": "bash",
         "result": {"content": [{"type": "text", "text": "total 0\n"}]}, "isError": False},
        {"type": "message_end", "message": {
            "role": "assistant", "content": [{"type": "text", "text": "Listed files."}],
            "usage": {"input": 50, "output": 10}, "stopReason": "stop"}},
        {"type": "agent_end", "messages": [], "isTerminal": True},
    ]
    chunks, _ = _run_omp_events(stream)
    evs = _flat(chunks)

    tool_use = [e for e in evs if e.get("type") == "assistant" and e["message"]["content"][0].get("type") == "tool_use"]
    assert len(tool_use) == 1
    assert tool_use[0]["message"]["content"][0]["id"] == "call_123"
    assert tool_use[0]["message"]["content"][0]["name"] == "bash"
    assert tool_use[0]["message"]["content"][0]["input"] == {"command": "ls -la"}

    tool_res = [e for e in evs if e.get("type") == "user" and e["message"]["content"][0].get("type") == "tool_result"]
    assert len(tool_res) == 1
    assert tool_res[0]["message"]["content"][0]["tool_use_id"] == "call_123"
    assert tool_res[0]["message"]["content"][0]["is_error"] is False
    assert "total 0" in tool_res[0]["message"]["content"][0]["content"]


def test_omp_normalizer_error_propagation():
    stream = [
        {"type": "session", "version": 3, "id": "s_err", "cwd": "/ws"},
        {"type": "message_end", "message": {
            "role": "assistant",
            "content": [],
            "usage": {"input": 0, "output": 0},
            "stopReason": "error",
            "errorMessage": "401 Invalid API key for provider",
        }},
        {"type": "agent_end", "messages": [], "isTerminal": True},
    ]
    chunks, _ = _run_omp_events(stream)
    evs = _flat(chunks)

    results = [e for e in evs if e.get("type") == "result"]
    assert len(results) == 1
    assert results[0]["subtype"] == "error"
    assert results[0]["is_error"] is True
    assert "401 Invalid API key" in results[0]["result"]


# ── live end-to-end turn test with mock LLM (skipped if omp not installed) ─────
import http.server
import shutil
import threading
import time
import pytest
from fastapi.testclient import TestClient
import server


class _MockLLM(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("content-length", 0))
        self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        chunk1 = {
            "id": "chatcmpl-e2e", "object": "chat.completion.chunk", "created": int(time.time()),
            "model": "gpt-4o", "choices": [{"index": 0, "delta": {"role": "assistant", "content": "OMP "}, "finish_reason": None}],
        }
        self.wfile.write(f"data: {json.dumps(chunk1)}\n\n".encode("utf-8"))
        self.wfile.flush()

        chunk2 = {
            "id": "chatcmpl-e2e", "object": "chat.completion.chunk", "created": int(time.time()),
            "model": "gpt-4o", "choices": [{"index": 0, "delta": {"content": "works!"}, "finish_reason": None}],
        }
        self.wfile.write(f"data: {json.dumps(chunk2)}\n\n".encode("utf-8"))
        self.wfile.flush()

        chunk3 = {
            "id": "chatcmpl-e2e", "object": "chat.completion.chunk", "created": int(time.time()),
            "model": "gpt-4o", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
        }
        self.wfile.write(f"data: {json.dumps(chunk3)}\n\n".encode("utf-8"))
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def log_message(self, *args):
        pass


@pytest.mark.skipif(shutil.which("omp") is None, reason="omp binary not installed on host")
def test_omp_turn_e2e_with_mock_llm():
    mock_server = http.server.HTTPServer(("127.0.0.1", 0), _MockLLM)
    port = mock_server.server_address[1]
    t = threading.Thread(target=mock_server.serve_forever, daemon=True)
    t.start()

    client = TestClient(server.app)
    d = tempfile.mkdtemp()
    req_body = {
        "provider": "openai-api",
        "backend": "omp",
        "model": "gpt-5.4",
        "prompt": "Say OMP works",
        "cwd": d,
        "auth": {
            "api_key": "sk-mock",
            "base_url": f"http://127.0.0.1:{port}/v1",
            "api_format": "openai",
        },
    }

    resp = client.post("/turn", json=req_body)
    assert resp.status_code == 200
    turn_id = resp.json()["turn_id"]

    data = {}
    for _ in range(60):
        time.sleep(0.3)
        t_resp = client.get(f"/turn/{turn_id}")
        data = t_resp.json()
        if data.get("done"):
            break

    mock_server.shutdown()
    assert data.get("done") is True
    assert data.get("status") == "done"
    assert "OMP works!" in data.get("result", "")
