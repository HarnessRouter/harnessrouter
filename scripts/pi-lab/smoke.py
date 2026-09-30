"""Exercise the installed Pi Lab CLI against a local scripted provider, without API spend.

Set HR_PI_LAB_BIN and HR_PI_LAB_SOL_PI_ENTRY to the pinned runtime and upstream entrypoint.
Run with the runner's Python dependencies installed. This validates integration, not quality.
"""
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runner"))
from server import Auth, CHECKPOINT_EXCLUDE, _build_pi, _pi_lab_to_claude, _pi_lab_eof
from pi_lab import FEATURES, build

requests = []
mode = "full"


class Provider(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        requests.append(body)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        first = len(requests) == 1
        if first:
            args = {"path": "artifact.txt", "content": "artifact evidence"}
            if mode == "full":
                args["then_run"] = {"command": "printf fused > fused.txt"}
            tool = "write"
            if mode == "reducer":
                tool = "bash"
                args = {"command": "python3 -m unittest missing_test_module; python3 -c \"print('ERROR_MARKER ' * 800)\""}
            delta = {"role": "assistant", "tool_calls": [{"index": 0, "id": "call_write",
                     "type": "function", "function": {"name": tool, "arguments": json.dumps(args)}}]}
            finish = "tool_calls"
        else:
            delta, finish = {"role": "assistant", "content": "SMOKE_OK"}, "stop"
        for part, reason in [(delta, None), ({}, finish)]:
            chunk = {"id": "chatcmpl-smoke", "object": "chat.completion.chunk", "created": 1,
                     "model": body["model"], "choices": [{"index": 0, "delta": part, "finish_reason": reason}]}
            if reason:
                chunk["usage"] = {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25}
            self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
        self.wfile.write(b"data: [DONE]\n\n")


def main():
    global mode
    service = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    threading.Thread(target=service.serve_forever, daemon=True).start()
    auth = Auth(api_key="local-test", base_url=f"http://127.0.0.1:{service.server_port}/v1", api_format="openai")
    reports = []
    try:
        for mode in ("full", "off", "reducer"):
            requests.clear()
            with tempfile.TemporaryDirectory(prefix="hr-pilab-smoke-") as temp:
                root = Path(temp)
                # A conflicting task config must not override the managed switches.
                (root / ".pi").mkdir()
                (root / ".pi/sol-pi.json").write_text(json.dumps({"version": 1, **{k: mode == "off" for k in FEATURES}}))
                config = {k: mode == "full" for k in FEATURES}
                if mode == "reducer":
                    config["evidencePreservingReducer"] = True
                    config["reducerModel"] = "small-model"
                env = {**os.environ, "HOME": str(root / ".harness/home")}
                cmd = build(_build_pi, "openai-api", auth, "test-model", "Create an artifact.", temp, env, config=config)
                proc = subprocess.run(cmd, cwd=temp, env=env, stdin=subprocess.DEVNULL,
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=90)
                events = [json.loads(line) for line in proc.stdout.splitlines() if line.startswith("{")]
                assert requests, f"No provider request: {proc.stdout}\n{proc.stderr}"
                tools = {t["function"]["name"]: t["function"] for t in requests[0]["tools"]}
                assert ("then_run" in tools["write"]["parameters"]["properties"]) == (mode == "full"), proc.stderr
                assert ("obs_recall" in tools) == (mode == "full"), tools.keys()
                assert ("update_plan" in tools) == (mode == "full"), tools.keys()
                if mode != "reducer":
                    assert (root / "artifact.txt").read_text() == "artifact evidence", proc.stdout
                assert (root / "fused.txt").exists() == (mode == "full"), proc.stdout
                state = {"model": "test-model", "final": ""}
                normalized = [out for event in events for out in _pi_lab_to_claude(event, state)]
                assert not any(e["type"] == "result" for e in normalized)
                result, = _pi_lab_eof(state, proc.returncode)
                assert not result["is_error"] and result["result"] == "SMOKE_OK", (result, proc.stderr)
                if mode == "reducer":
                    assert any(r["model"] == "small-model" for r in requests)
                    assert result["pi_lab"]["auxiliary_usage"]["hr/small-model"]["input"] == 20
                    assert any(e.get("type") == "pi_lab_event" and e.get("kind") == "fallback" for e in events)
                    assert "ERROR_MARKER" in json.dumps(requests[-1]["messages"]), "Fallback lost source evidence"
                sid = next(e["id"] for e in events if e.get("type") == "session")
                # A fresh CLI process after deleting/restoring the workspace must recover history.
                with tempfile.TemporaryDirectory(prefix="hr-pilab-checkpoint-") as backup:
                    archive = str(Path(backup) / "workspace.tgz")
                    subprocess.run(["tar", "-czf", archive, *[f"--exclude={p}" for p in CHECKPOINT_EXCLUDE],
                                    "-C", temp, "."], check=True)
                    shutil.rmtree(root)
                    root.mkdir()
                    subprocess.run(["tar", "-xzf", archive, "-C", temp], check=True)
                assert not (root / ".harness/home/.pi-lab/agent/models.json").exists()
                for model in ("test-model", "other-model", "test-model"):
                    before = len(requests)
                    cmd = build(_build_pi, "openai-api", auth, model, "Continue our conversation.", temp, env,
                                config=config, resume_session_id=sid)
                    follow = subprocess.run(cmd, cwd=temp, env=env, stdin=subprocess.DEVNULL,
                                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=90)
                    assert follow.returncode == 0, follow.stderr
                    assert len(requests) > before, follow.stdout + follow.stderr
                    assert "SMOKE_OK" in json.dumps(requests[before]["messages"]), "History was lost"
                    assert requests[before]["model"] == model
                reports.append({"configuration": mode, "tools": sorted(tools), "artifact": mode != "reducer", "reducer_fallback_and_usage": mode == "reducer",
                                "fusion": mode == "full", "resume_and_model_switch": True,
                                "checkpoint_restore": True})
    finally:
        service.shutdown()
    print(json.dumps({"passed": reports}, indent=2))


if __name__ == "__main__":
    main()
