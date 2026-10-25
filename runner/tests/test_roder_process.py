"""Opt-in process qualification against the real release and a deterministic Responses server.

HR_RODER_TEST_BIN=/path/to/roder python -m pytest runner/tests/test_roder_process.py
No model keys or inference charges. This proves the wire contract, not model/provider quality.
"""
import http.server
import json
import os
import pathlib
import subprocess
import sys
import threading

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import roder_backend
from types import SimpleNamespace

BINARY = os.environ.get("HR_RODER_TEST_BIN")
pytestmark = pytest.mark.skipif(not BINARY, reason="set HR_RODER_TEST_BIN to qualify a real Roder binary")


@pytest.fixture
def endpoint():
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"data":[{"id":"gpt-6.1-sol"},{"id":"gpt-6-astra"}]}')

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.server.requests.append(body)
            if self.server.fail:
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":{"message":"qualification: invalid API key","type":"authentication_error"}}')
                return
            output = self.server.output(body)
            response = {"id": "resp_probe", "object": "response", "model": body["model"],
                "status": "completed", "output": output,
                "usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}}
            events = [{"type": "response.created", "response": {**response, "status": "in_progress", "output": []}}]
            for index, entry in enumerate(output):
                events.append({"type": "response.output_item.added", "output_index": index,
                               "item": {**entry, "arguments": ""} if entry["type"] == "function_call" else {**entry, "content": []}})
                if entry["type"] == "message":
                    events.append({"type": "response.output_text.delta", "item_id": entry["id"],
                        "output_index": index, "content_index": 0, "delta": entry["content"][0]["text"]})
                else:
                    events.append({"type": "response.function_call_arguments.delta", "item_id": entry["id"],
                        "output_index": index, "delta": entry["arguments"]})
                events.append({"type": "response.output_item.done", "output_index": index, "item": entry})
            events.append({"type": "response.completed", "response": response})
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for event in events:
                self.wfile.write(("event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n").encode())

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.requests, server.fail = [], False
    server.output = lambda body: message("PROBE-OK")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join()


def message(text):
    return [{"id": "msg_probe", "type": "message", "role": "assistant", "status": "completed",
             "content": [{"type": "output_text", "text": text, "annotations": []}]}]


def turn(endpoint, workspace, *, model="gpt-6.1-sol", resume=None, disabled=None, mcp=None, prompt="Remember NONCE-419", merged_stderr=False):
    env = {**os.environ, "HOME": str(workspace / ".harness/home"), "HR_RODER_BIN": BINARY}
    pathlib.Path(env["HOME"]).mkdir(parents=True, exist_ok=True)
    auth = SimpleNamespace(api_key="test-placeholder", base_url=f"http://127.0.0.1:{endpoint.server_port}/v1", api_format="responses")
    cmd = roder_backend.build("openai", auth, model, prompt, str(workspace), env,
        relay=lambda b,k: (b,k), resume_session_id=resume, tools_disabled=disabled, mcp_servers=mcp)
    result = subprocess.run(cmd, cwd=workspace, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT if merged_stderr else subprocess.PIPE, text=True, timeout=40)
    events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
    assert events, result.stderr
    return events


def test_first_turn_followup_and_model_switch_survive_a_process_restart(endpoint, tmp_path):
    first = turn(endpoint, tmp_path)
    assert first[-1]["subtype"] == "success", first
    sid = first[0]["session_id"]
    second = turn(endpoint, tmp_path, resume=sid, model="gpt-6-astra", prompt="What was the nonce?")
    assert second[0]["session_id"] == sid and second[-1]["subtype"] == "success", second
    assert endpoint.requests[-1]["model"] == "gpt-6-astra"
    assert "NONCE-419" in json.dumps(endpoint.requests[-1]["input"])
    third = turn(endpoint, tmp_path, resume=sid, model="gpt-6.1-sol")
    assert third[-1]["subtype"] == "success" and endpoint.requests[-1]["model"] == "gpt-6.1-sol"


def test_missing_thread_reports_resume_lost(endpoint, tmp_path):
    events = turn(endpoint, tmp_path, resume="missing-thread")
    assert any(e.get("subtype") == "resume_lost" for e in events), events
    assert events[-1]["subtype"] == "success", events


def test_disabled_tool_is_absent_after_resuming(endpoint, tmp_path):
    first = turn(endpoint, tmp_path)
    assert "update_plan" in [tool.get("name") for tool in endpoint.requests[-1]["tools"]]
    events = turn(endpoint, tmp_path, resume=first[0]["session_id"], disabled=["update_plan"])
    assert events[-1]["subtype"] == "success", events
    assert "update_plan" not in [tool.get("name") for tool in endpoint.requests[-1]["tools"]]


def test_provider_failure_preserves_its_reason(endpoint, tmp_path):
    endpoint.fail = True
    events = turn(endpoint, tmp_path)
    assert events[-1]["is_error"] and "invalid API key" in events[-1]["result"], events


def test_tool_writes_artifact_and_reports_complete_result(endpoint, tmp_path):
    def output(body):
        if any(entry.get("type") == "function_call_output" for entry in body["input"]):
            return message("ARTIFACT-OK")
        return [{"id": "fc_probe", "call_id": "call_probe", "type": "function_call", "name": "apply_patch",
                 "arguments": json.dumps({"patch": "*** Begin Patch\n*** Add File: artifact.txt\n+ARTIFACT-419\n*** End Patch"}), "status": "completed"}]
    endpoint.output = output
    events = turn(endpoint, tmp_path)
    assert events[-1]["subtype"] == "success", events
    assert (tmp_path / "artifact.txt").read_text().strip() == "ARTIFACT-419"
    assert any(block.get("type") == "tool_result" for e in events for block in e.get("message", {}).get("content", []))


def test_stdio_mcp_tool_is_executed(endpoint, tmp_path):
    script = tmp_path / "mcp_fixture.py"
    script.write_text('from mcp.server.fastmcp import FastMCP\nm = FastMCP("probe")\n@m.tool()\ndef echo(value: str) -> str:\n    return "MCP:" + value\nm.run(transport="stdio")\n')
    def output(body):
        if any(entry.get("type") == "function_call_output" for entry in body["input"]):
            assert "MCP:419" in json.dumps(body["input"])
            return message("MCP-OK")
        assert "mcp__probe__echo" in [tool.get("name") for tool in body["tools"]]
        return [{"id": "fc_mcp", "call_id": "call_mcp", "type": "function_call", "name": "mcp__probe__echo",
                 "arguments": '{"value":"419"}', "status": "completed"}]
    endpoint.output = output
    events = turn(endpoint, tmp_path, mcp=[{"name": "probe", "command": sys.executable, "args": [str(script)]}])
    assert events[-1]["subtype"] == "success", events


def test_native_skill_loader_and_agent_instructions_reach_the_model(endpoint, tmp_path):
    root = tmp_path / ".harness/home/.codex/skills/qualification"
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text("---\nname: qualification\ndescription: QUALIFICATION-SKILL-419\n---\nRun the bundled script.\n")
    (tmp_path / "AGENTS.md").write_text("AGENT-INSTRUCTION-419")
    events = turn(endpoint, tmp_path)
    assert events[-1]["subtype"] == "success", events
    body = json.dumps(endpoint.requests[-1])
    assert "QUALIFICATION-SKILL-419" in body
    assert "AGENT-INSTRUCTION-419" in body


def test_unavailable_mcp_is_reported_without_leaking_its_credentials(endpoint, tmp_path):
    events = turn(endpoint, tmp_path, mcp=[{"name": "unavailable", "url": "http://127.0.0.1:1/mcp",
                                         "headers": {"Authorization": "Bearer secret-419"}}])
    assert any(e.get("subtype") == "mcp_unavailable" for e in events), events
    assert "secret-419" not in json.dumps(events)
    assert events[-1]["subtype"] == "success", events


def test_native_terminal_bell_cannot_corrupt_the_runners_merged_stream(endpoint, tmp_path):
    events = turn(endpoint, tmp_path, merged_stderr=True)
    assert events[-1]["subtype"] == "success", events
    assert events[-1]["result"] == "PROBE-OK"


def test_real_binary_runs_through_the_runners_relay_and_result_collector(endpoint, tmp_path):
    import time
    import uuid
    import server

    env = {**os.environ, "HOME": str(tmp_path / ".harness/home"), "HR_RODER_BIN": BINARY}
    pathlib.Path(env["HOME"]).mkdir(parents=True)
    cmd = roder_backend.build("openai", server.Auth(api_key="provider-placeholder",
        base_url=f"http://127.0.0.1:{endpoint.server_port}/v1", api_format="responses"),
        "gpt-6.1-sol", "Reply PROBE-OK", str(tmp_path), env, relay=server._hermes_relay_route)
    turn_id = "roder-qualification-" + uuid.uuid4().hex
    server._turns[turn_id] = {"status": "running", "events": [], "result": "", "done": False,
                              "started": time.time(), "backend": "roder", "model": "gpt-6.1-sol"}
    try:
        server._run_turn_bg(turn_id, cmd, env, str(tmp_path), roder_backend.normalize,
                            "gpt-6.1-sol", timeout_seconds=30, max_turns=4, count_steps=True)
        record = server._turns[turn_id]
        assert record["status"] == "done", record
        assert record["result"] == "PROBE-OK"
        assert record["session_id"]
        assert record["events"][-1]["usage"]["input_tokens"] == 10
    finally:
        server._turns.pop(turn_id, None)


@pytest.mark.parametrize("model", ["gpt-6.1-sol", "gpt-6-astra", "claude-fable-5-1",
                                   "claude-opus-5.5", "gemini-4-argon", "grok-4.6",
                                   "deepseek-v4.1-flash", "kimi-k3", "qwen3.8-max"])
def test_current_model_ids_reach_the_responses_endpoint_unchanged(endpoint, tmp_path, model):
    events = turn(endpoint, tmp_path, model=model)
    assert events[-1]["subtype"] == "success", events
    assert endpoint.requests[-1]["model"] == model
