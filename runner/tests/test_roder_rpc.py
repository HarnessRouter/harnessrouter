"""App-server framing must tolerate diagnostics and large native event payloads; the driver runs a
turn against a scripted app-server without leaking its job, and keeps a resumed thread whose MCP
attachments changed."""
import asyncio
import json
import os
import pathlib
import subprocess
import sys
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import roder_backend  # noqa: E402
import server  # noqa: E402
from roder_driver import Rpc, STDERR_LINE_CAP, forward_stderr  # noqa: E402

DRIVER = pathlib.Path(__file__).resolve().parents[1] / "roder_driver.py"

# A scripted `roder app-server`: answers the driver's requests, dumps its own environment (what every
# command the agent runs inherits) to FAKE_DUMP, logs every request to FAKE_LOG, serves FAKE_THREAD
# on thread/read, and on turn/start asks for FAKE_CALL (an external tool) when set, then completes.
FAKE_APP_SERVER = r'''
import json, os, sys
log = open(os.environ["FAKE_LOG"], "a")
json.dump(dict(os.environ), open(os.environ["FAKE_DUMP"], "w"))
stored = json.loads(os.environ.get("FAKE_THREAD") or "null")
call = os.environ.get("FAKE_CALL")
def send(msg):
    print(json.dumps(msg), flush=True)
def done():
    send({"method": "turn/completed", "params": {"threadId": "thread", "turnId": "turn",
          "turn": {"status": "completed", "usage": {"prompt_tokens": 1, "completion_tokens": 1}}}})
for line in sys.stdin:
    req = json.loads(line)
    log.write(line); log.flush()
    method = req.get("method")
    if method == "thread/read":
        send({"id": req["id"], "result": {"thread": stored}} if stored else
             {"id": req["id"], "error": {"code": -32602, "message": "thread not found"}})
        continue
    results = {"initialize": {}, "workspace/create": {"workspace": {"id": "ws"}},
               "thread/start": {"thread": {"id": "thread"}}, "turn/start": {"turnId": "turn"},
               "tools/resolve": {}}
    send({"id": req["id"], "result": results[method]})
    if method == "turn/start":
        if call:
            send({"method": "thread/toolExecutionRequested", "params": {"threadId": "thread",
                  "turnId": "turn", "requestId": "r1", "call": {"name": call, "arguments": {}}}})
        else:
            done()
    if method == "tools/resolve":
        done()
'''


def _fake(tmp_path):
    binary = tmp_path / "app-server"
    binary.write_text("#!" + sys.executable + "\n" + FAKE_APP_SERVER)
    binary.chmod(0o755)
    return binary


def _turn(tmp_path, *, resume=None, mcp=None, disabled=None, thread=None, call=None):
    """One turn through roder_backend.build and the real driver, against the scripted app-server."""
    env = {**os.environ, "HOME": str(tmp_path / "home"), "HR_RODER_BIN": str(_fake(tmp_path)),
           "FAKE_DUMP": str(tmp_path / "app-server-env.json"), "FAKE_LOG": str(tmp_path / "requests.log"),
           "FAKE_THREAD": json.dumps(thread), "FAKE_CALL": call or ""}
    auth = SimpleNamespace(api_key="provider-key", base_url="http://127.0.0.1:9/v1", api_format="responses")
    cmd = roder_backend.build("openai", auth, "gpt-6.1-sol", "test", str(tmp_path), env,
                              relay=lambda b, k, **_: (b, "hr-relay-token-419"), driver_cmd=server._driver_cmd,
                              resume_session_id=resume,
                              mcp_servers=mcp, tools_disabled=disabled)
    result = subprocess.run(cmd, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
    requests = [json.loads(line) for line in (tmp_path / "requests.log").read_text().splitlines()]
    return result, events, requests


def test_rpc_skips_noise_and_reads_items_larger_than_stream_limit():
    async def check():
        stream = asyncio.StreamReader(limit=64)
        rpc = Rpc(SimpleNamespace(stdout=stream))
        payload = {"method": "large", "params": {"text": "x" * (8 * 1024 * 1024 + 1)}}
        reader = asyncio.create_task(rpc.read())
        raw = b'diagnostic line\n[]\n' + json.dumps(payload).encode() + b'\n'
        for offset in range(0, len(raw), 65536):
            stream.feed_data(raw[offset:offset + 65536])
            await asyncio.sleep(0)
        stream.feed_eof()
        await reader
        assert await rpc.events.get() == payload
        assert await rpc.events.get() is None
    asyncio.run(check())


def test_a_stderr_line_past_any_limit_is_capped_and_the_stream_still_drains(capsys):
    """readline at an 8 MiB limit ended the task on one long line, and an undrained stderr would
    then stall the app-server. Chunked, the long line keeps its head and the next line still comes."""
    async def check():
        stream = asyncio.StreamReader(limit=64)
        task = asyncio.create_task(forward_stderr(stream))
        raw = b"\x07head " + b"y" * (9 * 1024 * 1024) + b"\nnext line\n" + b"tail without newline"
        for offset in range(0, len(raw), 65536):
            stream.feed_data(raw[offset:offset + 65536])
            await asyncio.sleep(0)
        stream.feed_eof()
        await asyncio.wait_for(task, 10)
    asyncio.run(check())
    lines = capsys.readouterr().err.splitlines()
    assert lines[0].startswith("head yyy") and len(lines[0]) <= STDERR_LINE_CAP
    assert lines[1:] == ["next line", "tail without newline"]


def test_approval_request_ends_noninteractive_turn(tmp_path):
    binary = tmp_path / "app-server"
    binary.write_text("#!" + sys.executable + '\n' + '''
import json, sys
for line in sys.stdin:
    req = json.loads(line)
    method = req['method']
    results = {'initialize': {}, 'workspace/create': {'workspace': {'id': 'ws'}},
               'thread/start': {'thread': {'id': 'thread'}},
               'turn/start': {'turnId': 'turn'}}
    print(json.dumps({'id': req['id'], 'result': results[method]}), flush=True)
    if method == 'turn/start':
        print(json.dumps({'method': 'thread/approvalRequested', 'params': {
            'threadId': 'thread', 'turnId': 'turn', 'approvalId': 'approval'}}), flush=True)
''')
    binary.chmod(0o755)
    (tmp_path / 'config.toml').write_text('')
    result = subprocess.run([sys.executable, str(DRIVER)],
        cwd=tmp_path, env={**os.environ, 'HR_RODER_BIN': str(binary),
            'RODER_CONFIG_DIR': str(tmp_path), 'HR_DRIVER_JOB': json.dumps({'model': 'gpt-6.1-sol', 'prompt': 'test'})},
        capture_output=True, text=True, timeout=10)
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert result.returncode == 1
    assert events[-1]['is_error']
    assert 'approval' in events[-1]['result']


def test_one_app_server_per_turn(tmp_path):
    """The tool policy is in the config before the process starts, so nothing boots twice."""
    result, events, requests = _turn(tmp_path)
    assert events[-1]["subtype"] == "success", (events, result.stderr)
    assert [r["method"] for r in requests].count("initialize") == 1
    assert "tools/list" not in [r["method"] for r in requests]


def test_the_job_and_mcp_credentials_never_reach_the_agents_environment(tmp_path):
    """The job carries every MCP server's bearer and every stdio server's env. The app-server (whose
    environment every command the agent runs inherits) and each stdio server get neither: the
    driver pops the job first, and a stdio server starts from the turn's env without HR_ names."""
    dump = tmp_path / "stdio-env.json"
    server_script = tmp_path / "stdio_server.py"
    server_script.write_text(
        "import json, os, sys\n"
        "json.dump(dict(os.environ), open(os.environ['DUMP_TO'], 'w'))\n"
        "from mcp.server.fastmcp import FastMCP\n"
        "m = FastMCP('probe')\n"
        "@m.tool()\n"
        "def echo(value: str) -> str:\n"
        "    return value\n"
        "m.run(transport='stdio')\n")
    mcp = [{"name": "probe", "command": sys.executable, "args": [str(server_script)],
            "env": {"DUMP_TO": str(dump), "PROBE_OWN_SETTING": "kept"}},
           {"name": "remote", "url": "http://127.0.0.1:1/mcp",
            "headers": {"Authorization": "Bearer secret-bearer-419"}}]
    result, events, requests = _turn(tmp_path, mcp=mcp)
    assert events[-1]["subtype"] == "success", (events, result.stderr)
    assert any(e.get("subtype") == "mcp_unavailable" for e in events)
    start = next(r for r in requests if r["method"] == "thread/start")
    assert [t["name"] for t in start["params"]["externalTools"]] == ["mcp__probe__echo"]
    app_env = json.loads((tmp_path / "app-server-env.json").read_text())
    stdio_env = json.loads(dump.read_text())
    for env in (app_env, stdio_env):
        assert "HR_DRIVER_JOB" not in env and "HR_RODER_JOB" not in env
        assert "secret-bearer-419" not in json.dumps(env)
    # the app-server keeps the one HR_ name it needs, the relay token its config names
    assert app_env["HR_RODER_KEY"] == "hr-relay-token-419"
    assert not [k for k in stdio_env if k.upper().startswith("HR_")]
    assert stdio_env["PROBE_OWN_SETTING"] == "kept"
    assert "secret-bearer-419" not in result.stdout + result.stderr


def test_a_resumed_thread_whose_tool_is_detached_keeps_going(tmp_path):
    """The thread was started with mcp__gone__lookup; this turn its server is unreachable. The
    follow-up continues the same thread, says the server is unavailable, and a call to the tool is
    answered with an error rather than failing the turn."""
    thread = {"id": "thread", "externalTools": [{"name": "mcp__gone__lookup", "description": "",
                                                 "parameters": {"type": "object"}}]}
    mcp = [{"name": "gone", "url": "http://127.0.0.1:1/mcp"}]
    result, events, requests = _turn(tmp_path, resume="thread", mcp=mcp, thread=thread,
                                     call="mcp__gone__lookup")
    assert events[-1]["subtype"] == "success", (events, result.stderr)
    assert events[[e.get("subtype") for e in events].index("init")]["session_id"] == "thread"
    assert any(e.get("subtype") == "mcp_unavailable" and e["servers"] == [{"name": "gone"}] for e in events)
    methods = [r["method"] for r in requests]
    assert "thread/start" not in methods and "workspace/create" not in methods
    resolve = next(r for r in requests if r["method"] == "tools/resolve")["params"]
    assert resolve["requestId"] == "r1" and resolve["isError"] is True
    assert "not available" in resolve["output"]


def test_a_tool_switched_off_since_the_thread_started_is_refused_not_fatal(tmp_path):
    thread = {"id": "thread", "externalTools": [{"name": "mcp__probe__echo", "description": "",
                                                 "parameters": {"type": "object"}}]}
    script = tmp_path / "stdio_server.py"
    script.write_text("from mcp.server.fastmcp import FastMCP\nm = FastMCP('probe')\n"
                      "@m.tool()\ndef echo(value: str) -> str:\n    return value\nm.run(transport='stdio')\n")
    mcp = [{"name": "probe", "command": sys.executable, "args": [str(script)]}]
    result, events, requests = _turn(tmp_path, resume="thread", mcp=mcp, thread=thread,
                                     disabled=["mcp__probe__echo"], call="mcp__probe__echo")
    assert events[-1]["subtype"] == "success", (events, result.stderr)
    resolve = next(r for r in requests if r["method"] == "tools/resolve")["params"]
    assert resolve["isError"] is True and "switched off" in resolve["output"]


def test_tools_attached_after_the_thread_started_are_named_in_a_note(tmp_path):
    script = tmp_path / "stdio_server.py"
    script.write_text("from mcp.server.fastmcp import FastMCP\nm = FastMCP('probe')\n"
                      "@m.tool()\ndef echo(value: str) -> str:\n    return value\nm.run(transport='stdio')\n")
    mcp = [{"name": "probe", "command": sys.executable, "args": [str(script)]}]
    result, events, _ = _turn(tmp_path, resume="thread", mcp=mcp, thread={"id": "thread"})
    assert events[-1]["subtype"] == "success", (events, result.stderr)
    note = next(e for e in events if e.get("subtype") == "notice")["text"]
    assert '"probe"' in note and "new session" in note.lower() and "—" not in note


def test_a_runner_turn_starts_roder_through_its_relay_and_driver(tmp_path, monkeypatch):
    """The runner's own /turn path for roder: the provider key reaches neither the app-server nor
    the command line, the job is out of the app-server's environment, and the turn completes."""
    import time
    monkeypatch.setattr(server, "WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.setenv("HR_RODER_BIN", str(_fake(tmp_path)))
    monkeypatch.setenv("FAKE_DUMP", str(tmp_path / "app-server-env.json"))
    monkeypatch.setenv("FAKE_LOG", str(tmp_path / "requests.log"))
    req = server.TurnReq(backend="roder", provider="openai", model="gpt-6.1-sol", prompt="hi",
                         auth=server.Auth(api_key="provider-key-419", base_url="http://127.0.0.1:9/v1",
                                          api_format="responses"))
    started = server._start_turn(req, "sess-roder")
    try:
        deadline = time.time() + 30
        while not server._turns[started["turn_id"]].get("done") and time.time() < deadline:
            time.sleep(0.1)
        rec = server._turns[started["turn_id"]]
        assert rec["status"] == "done", rec
        app_env = json.loads((tmp_path / "app-server-env.json").read_text())
        assert "HR_DRIVER_JOB" not in app_env
        assert "provider-key-419" not in json.dumps(app_env)
        assert app_env["HR_RODER_KEY"].startswith("hr-relay-")
    finally:
        server._turns.pop(started["turn_id"], None)
