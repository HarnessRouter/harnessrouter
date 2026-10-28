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


# A request in the shape Qwen Code 0.26.3 sent a real vLLM (captured 2026-10-28, #578): its own cap on
# every call, with the stream and its usage asked for.
def _captured(cap: int = 32768) -> dict:
    return {"model": "qwen3-4b", "max_tokens": cap, "stream": False,
            "stream_options": {"include_usage": True},
            "messages": [{"role": "system", "content": "You are Qwen Code."},
                         {"role": "user", "content": "Create hello.txt"}],
            "tools": [{"type": "function", "function": {"name": "write_file", "parameters": {"type": "object"}}}]}


def test_the_cap_the_cli_invents_never_reaches_the_provider():
    """0.26.3 puts max_tokens on every request, 32768 for qwen3-4b and 64000 for qwen3.5-9b (#578), a
    figure for the model's name, not for what the endpoint serves. The route is born dropping it, and
    every other field goes as the CLI wrote it."""
    from server import _HERMES_RELAY, _drop_top_level_field
    _, _, env = _argv()
    flags = _HERMES_RELAY["routes"][env["OPENAI_API_KEY"]][2]
    assert flags["drop_fields"] == ("max_tokens",)
    body = json.dumps(_captured(64000)).encode()
    for f in flags["drop_fields"]:
        body = _drop_top_level_field(body, f)
    want = _captured()
    del want["max_tokens"]
    assert json.loads(body) == want


def test_a_model_whose_window_is_smaller_than_the_cap_answers_through_the_route():
    """The report's setup through the real relay: a vLLM model served with max_model_len=8192 refuses
    any request whose cap does not fit ("max_tokens=64000 cannot be greater than max_model_len=
    max_total_tokens=8192"). Through the route _build_qwen registers, the call reaches the provider
    without the cap and is answered; the refusal is what the provider gave before this route dropped it."""
    import threading
    import urllib.request
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    got: list[dict] = []
    refusal = (b'{"object":"error","message":"max_tokens=64000cannot be greater than max_model_len='
               b'max_total_tokens=8192. Please request fewer output tokens.","type":"BadRequestError",'
               b'"param":"max_tokens","code":400}')

    class VLLM(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            got.append(body)
            if body.get("max_tokens", 0) > 8192:
                out, code = refusal, 400
            else:
                out, code = json.dumps({"object": "chat.completion", "model": body["model"], "choices": [
                    {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "DONE"}}]}).encode(), 200
            self.send_response(code)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    up = ThreadingHTTPServer(("127.0.0.1", 0), VLLM)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    try:
        env: dict = {}
        _build_qwen("openai-api", Auth(api_key="sk-local", base_url=f"http://127.0.0.1:{up.server_address[1]}/v1"),
                    "qwen3.5-9b", "hi", tempfile.mkdtemp(), env)
        req = urllib.request.Request(env["OPENAI_BASE_URL"] + "/chat/completions", method="POST",
                                     data=json.dumps(_captured(64000)).encode(),
                                     headers={"authorization": f"Bearer {env['OPENAI_API_KEY']}",
                                              "content-type": "application/json"})
        answer = json.loads(urllib.request.urlopen(req, timeout=10).read())
        assert answer["choices"][0]["message"]["content"] == "DONE"
        assert len(got) == 1 and "max_tokens" not in got[0]       # answered on the first call, without the cap
        want = _captured()
        del want["max_tokens"]
        assert got[0] == want                                      # and nothing else changed on the way
    finally:
        up.shutdown()
