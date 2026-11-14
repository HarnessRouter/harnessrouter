"""The antigravity backend: Google's managed Antigravity agent, reached over the Gemini API's
Interactions and Environments APIs. A remote runtime (qoder's shape, docs/harness-verification.md
"remote runtimes"), so what these pin is what that shape changes:

  the request: the agent, agent_config.model, the session's environment, the chain
      (previous_interaction_id on turn 2), the tools (a switched-off built-in left out, MCP servers),
      system_instruction carrying the harness's instructions, stream + background
  the stream: text, thoughts, tool calls and their results map to the canonical events; usage is
      Google's own (output with the thinking, reasoning a subset, cache reads apart)
  the status: completed, incomplete with the token budget's reason, failed with Google's words,
      requires_action, cancelled (SIGTERM posts :cancel)
  files: the workspace goes up as the checkpoint's archive (its exclusions, .harness and .git out,
      no link followed or sent), only when it changed, under a size cap checked before anything is
      made at Google; what the agent changed comes back, and a path from Google is input: `..`,
      absolute, .harness/.git and a path through a symlink never land
  the key: it stays in the relay; no event, state file, result or error carries it, and an error
      that echoes it is scrubbed; the route forwards this API's calls and nothing else
  purge: every interaction and environment the state recorded is deleted

A stub of Google's API (built here) answers the driver, run as the real subprocess it is; nothing
here reaches Google.
"""
import base64
import http.server
import io
import json
import os
import pathlib
import signal
import subprocess
import sys
import tarfile
import threading
import time
import urllib.parse
import urllib.request

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import antigravity_driver as drv  # noqa: E402
import server as rs  # noqa: E402

DRIVER = str(pathlib.Path(__file__).resolve().parents[1] / "antigravity_driver.py")
KEY = "AIzaDUMMY-not-a-key-0123456789"      # AIza and 25 more: the scrub's shape for a Google key, not a real key's length
# bsdtar on a developer's machine takes no --ignore-failed-read; the command's shape is pinned against
# the checkpoint's own in test_the_archive_is_the_checkpoints_command
TAR = {"argv": ["tar", "-czf"]}


# ── a stub of the Interactions and Environments APIs ─────────────────────────────────────────────
class Stub:
    """Environments hold files ({env: {path: bytes}}); an interaction create streams the scripted
    events of the next turn in `script` (a list of turns, each a list of (event, data) pairs and
    ("write", path, bytes) / ("delete", path) actions on the environment's files)."""

    def __init__(self):
        self.calls: list[dict] = []
        self.envs: dict[str, dict[str, bytes]] = {}
        self.env_status: dict[str, str] = {}
        self.interactions: dict[str, dict] = {}
        self.script: list[list] = []
        self.keys_seen: set[str] = set()
        self.bearers_seen: set[str] = set()
        self.hang = False
        self.fail_create: tuple[int, str] | None = None
        self.listing_extra: list[dict] = []
        self.n = 0
        self.lock = threading.Lock()
        stub = self

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):  # noqa: D102
                pass

            def _send(self, code: int, doc, ctype="application/json"):
                data = doc if isinstance(doc, (bytes, bytearray)) else json.dumps(doc).encode()
                self.send_response(code)
                self.send_header("content-type", ctype)
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _err(self, code: int, status: str, msg: str):
                self._send(code, {"error": {"code": code, "status": status, "message": msg}})

            def _body(self) -> bytes:
                n = int(self.headers.get("content-length") or 0)
                return self.rfile.read(n) if n else b""

            def _record(self, body: bytes):
                u = urllib.parse.urlsplit(self.path)
                with stub.lock:
                    stub.calls.append({"method": self.command, "path": u.path, "query": dict(urllib.parse.parse_qsl(u.query)),
                                       "headers": {k.lower(): v for k, v in self.headers.items()},
                                       "body": body})
                if self.headers.get("x-goog-api-key"):
                    stub.keys_seen.add(self.headers["x-goog-api-key"])
                if self.headers.get("authorization"):
                    stub.bearers_seen.add(self.headers["authorization"])
                return u

            def do_POST(self):  # noqa: N802
                body = self._body()
                u = self._record(body)
                p = u.path
                if p == "/v1beta/environments":
                    with stub.lock:
                        stub.n += 1
                        eid = f"env{stub.n}"
                    stub.envs[eid] = {}
                    stub.env_status[eid] = "active"
                    return self._send(200, {"id": eid, "status": "active"})
                if p == "/v1beta/interactions":
                    doc = json.loads(body)
                    if stub.fail_create:
                        code, msg = stub.fail_create
                        return self._err(code, "INVALID_ARGUMENT", msg)
                    return self._stream_new(doc)
                if p.endswith(":cancel") or p.endswith("/cancel"):
                    iid = p.split("/")[3].split(":")[0]
                    if iid not in stub.interactions:
                        return self._err(404, "NOT_FOUND", "no such interaction")
                    stub.interactions[iid]["status"] = "cancelled"
                    return self._send(200, {"id": iid, "status": "cancelled"})
                return self._err(404, "NOT_FOUND", p)

            def _stream_new(self, doc: dict):
                with stub.lock:
                    stub.n += 1
                    iid = f"v1_int{stub.n}"
                turn = stub.script.pop(0) if stub.script else []
                eid = doc.get("environment")
                stub.interactions[iid] = {"id": iid, "status": "in_progress", "body": doc, "environment": eid}
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.send_header("transfer-encoding", "chunked")
                self.end_headers()

                def out(event: str, data: dict):
                    raw = f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()
                    self.wfile.write(f"{len(raw):x}\r\n".encode() + raw + b"\r\n")
                    self.wfile.flush()

                out("interaction.created", {"interaction": {"id": iid, "status": "in_progress",
                                                            "agent": doc.get("agent"), "environment_id": eid},
                                            "event_type": "interaction.created"})
                for item in turn:
                    if item[0] == "write":
                        stub.envs[eid][item[1]] = item[2]
                        continue
                    if item[0] == "delete":
                        stub.envs[eid].pop(item[1], None)
                        continue
                    event, data = item
                    if event == "interaction.completed":
                        it = dict(data.get("interaction") or {})
                        it["id"] = iid
                        stub.interactions[iid].update(status=it.get("status"), usage=it.get("usage"))
                        data = {**data, "interaction": it}
                    out(event, {**data, "event_type": event})
                if stub.hang:
                    for _ in range(300):
                        if stub.interactions[iid]["status"] == "cancelled":
                            break
                        time.sleep(0.05)
                try:
                    self.wfile.write(b"0\r\n\r\n")
                except OSError:
                    pass

            def do_GET(self):  # noqa: N802
                u = self._record(b"")
                p = u.path
                q = dict(urllib.parse.parse_qsl(u.query))
                parts = p.split("/")
                if p.startswith("/v1beta/interactions/"):
                    iid = parts[3]
                    if iid not in stub.interactions:
                        return self._err(404, "NOT_FOUND", "no such interaction")
                    it = stub.interactions[iid]
                    return self._send(200, {k: v for k, v in it.items() if k != "body"})
                if p.startswith("/v1beta/environments/") and "/files" not in p:
                    eid = parts[3]
                    if eid not in stub.envs:
                        return self._err(404, "NOT_FOUND", "no such environment")
                    return self._send(200, {"id": eid, "status": stub.env_status.get(eid, "active")})
                if "/files" in p:
                    eid = parts[3]
                    rel = urllib.parse.unquote("/".join(parts[5:]))
                    files = stub.envs.get(eid)
                    if files is None:
                        return self._err(404, "NOT_FOUND", "no such environment")
                    if q.get("alt") == "media":
                        if rel not in files:
                            return self._err(404, "not_found", f"Path '{rel}' not found")
                        return self._send(200, files[rel], "application/octet-stream")
                    entries = [{"name": k.rsplit("/", 1)[-1], "path": k, "type": "FILE", "size_bytes": str(len(v)),
                                "modified": f"m{hash(v) & 0xffff}"} for k, v in sorted(files.items())
                               if k == rel or k.startswith(rel + "/")]
                    if not entries and not stub.listing_extra:
                        return self._err(404, "not_found", f"Path '{rel}' not found")
                    return self._send(200, {"files": entries + stub.listing_extra})
                return self._err(404, "NOT_FOUND", p)

            def do_PUT(self):  # noqa: N802
                body = self._body()
                u = self._record(body)
                parts = u.path.split("/")
                eid = parts[4]
                target = urllib.parse.unquote("/".join(parts[6:]))
                with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as tf:
                    for m in tf.getmembers():
                        if m.isfile():
                            name = m.name.removeprefix("./")
                            stub.envs[eid][f"{target}/{name}"] = tf.extractfile(m).read()
                        elif m.issym() or m.islnk():
                            stub.envs[eid][f"{target}/{m.name.removeprefix('./')}"] = b"<LINK>"
                return self._send(200, {"files": []})

            def do_DELETE(self):  # noqa: N802
                u = self._record(b"")
                parts = u.path.split("/")
                if u.path.startswith("/v1beta/interactions/"):
                    if stub.interactions.pop(parts[3], None) is None:
                        return self._err(404, "NOT_FOUND", "gone")
                    return self._send(200, {})
                if u.path.startswith("/v1beta/environments/"):
                    if stub.envs.pop(parts[3], None) is None:
                        return self._err(404, "NOT_FOUND", "gone")
                    return self._send(200, {})
                return self._err(404, "NOT_FOUND", u.path)

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def close(self):
        self.srv.shutdown()

    def creates(self) -> list[dict]:
        return [json.loads(c["body"]) for c in self.calls if c["method"] == "POST" and c["path"] == "/v1beta/interactions"]

    def uploads(self) -> list[dict]:
        return [c for c in self.calls if c["method"] == "PUT"]


@pytest.fixture
def stub():
    s = Stub()
    yield s
    s.close()


@pytest.fixture
def relay(stub):
    """The real relay route in front of the stub, holding the key; the driver gets the placeholder."""
    base, tok = rs._antigravity_relay_route(stub.base, KEY)
    yield base, tok
    rs._HERMES_RELAY["routes"].pop(tok, None)


def ev(event: str, **data):
    return (event, data)


def text_turn(*chunks: str, usage: dict | None = None, status: str = "completed", extra: list | None = None) -> list:
    t = [ev("interaction.status_update", status="in_progress"),
         ev("step.start", index=0, step={"type": "thought"}),
         ev("step.delta", index=0, delta={"type": "thought_summary", "content": {"type": "text", "text": "Planning."}}),
         ev("step.delta", index=0, delta={"type": "thought_signature", "signature": "sig"}),
         ev("step.stop", index=0)]
    t += list(extra or [])
    t += [ev("step.start", index=9, step={"type": "model_output"})]
    t += [ev("step.delta", index=9, delta={"type": "text", "text": c}) for c in chunks]
    t += [ev("step.stop", index=9),
          ev("interaction.completed", interaction={"status": status, "usage": usage or {
              "total_tokens": 1500, "total_input_tokens": 1000, "total_cached_tokens": 600,
              "total_output_tokens": 200, "total_thought_tokens": 300, "total_tool_use_tokens": 0}}),
          ev("done")]
    return t


def run_driver(job: dict, relay: tuple, timeout: float = 30.0):
    base, tok = relay
    job = {"base_url": base, "api_key": tok, "model": "gemini-4-hydrogen", "tar": TAR,
           "exclude": list(rs.CHECKPOINT_EXCLUDE), **job}
    proc = subprocess.run([sys.executable, DRIVER, json.dumps(job)], capture_output=True, text=True, timeout=timeout)
    lines = [json.loads(ln) for ln in proc.stdout.splitlines() if ln.strip().startswith("{")]
    return lines, proc


def normalise(lines: list[dict]) -> tuple[list[dict], dict]:
    state = {"model": "gemini-4-hydrogen", "final": ""}
    out: list[dict] = []
    for obj in lines:
        out += rs._antigravity_to_claude(obj, state)
    return out, state


def result_of(events: list[dict]) -> dict:
    return [e for e in events if e.get("type") == "result"][-1]


def hr_result(lines: list[dict]) -> dict:
    return [ln for ln in lines if ln["m"] == "__hr_result"][-1]["p"]


# ── the request ───────────────────────────────────────────────────────────────────────────────────
def test_a_first_turn_creates_the_environment_and_sends_the_request_this_base_builds(tmp_path, stub, relay):
    (tmp_path / "brief.md").write_text("the brief")
    stub.script = [text_turn("Done.")]
    lines, proc = run_driver({"cwd": str(tmp_path), "prompt": "Summarise the brief.", "agent_doc": "Be terse.",
                              "tools_disabled": ["google_search"], "input_files": ["brief.md"]}, relay)
    assert hr_result(lines)["status"] == "completed", proc.stderr
    [body] = stub.creates()
    assert body["agent"] == "antigravity-preview-09-2026"
    assert body["agent_config"] == {"type": "antigravity", "model": "gemini-4-hydrogen"}
    assert body["environment"] == "env1" and "previous_interaction_id" not in body
    assert body["stream"] is True and body["background"] is True and body["store"] is True
    # a switched-off built-in is left out; the list is always explicit, never the default set
    assert body["tools"] == [{"type": "code_execution"}, {"type": "url_context"}]
    assert body["system_instruction"].startswith("Be terse.") and "/workspace" in body["system_instruction"]
    # the message names the file it brought, which went up before the interaction
    assert body["input"][0]["type"] == "text" and "brief.md" in body["input"][0]["text"]
    assert "Summarise the brief." in body["input"][0]["text"]
    assert stub.envs["env1"]["workspace/brief.md"] == b"the brief"
    order = [(c["method"], c["path"]) for c in stub.calls]
    assert order.index(("POST", "/v1beta/environments")) < order.index(("PUT", "/upload/v1beta/environments/env1/files/workspace")) \
        < order.index(("POST", "/v1beta/interactions"))
    assert all(c["headers"].get("api-revision") == drv.API_REVISION for c in stub.calls)
    st = json.loads((tmp_path / rs.ANTIGRAVITY_STATE_REL).read_text())
    assert st["environment_id"] == "env1" and st["last_interaction_id"] == "v1_int2" and st["interactions"] == ["v1_int2"]


def test_turn_two_continues_the_environment_and_the_chain_and_sends_nothing_unchanged(tmp_path, stub, relay):
    (tmp_path / "a.txt").write_text("a")
    stub.script = [text_turn("one"), text_turn("two")]
    lines, _ = run_driver({"cwd": str(tmp_path), "prompt": "first"}, relay)
    sid = hr_result(lines)["session_id"]
    assert sid == "env1"
    uploads_after_first = len(stub.uploads())
    lines, proc = run_driver({"cwd": str(tmp_path), "prompt": "second", "resume_session_id": sid,
                              "model": "gemini-4-carbon"}, relay)
    assert hr_result(lines)["status"] == "completed", proc.stderr
    first, second = stub.creates()
    assert second["environment"] == "env1" and second["previous_interaction_id"] == "v1_int2"
    assert second["agent_config"]["model"] == "gemini-4-carbon"
    assert len(stub.uploads()) == uploads_after_first       # the workspace did not change: nothing went up
    assert not [ln for ln in lines if ln["m"] == "resume_lost"]
    assert len([c for c in stub.calls if c["path"] == "/v1beta/environments" and c["method"] == "POST"]) == 1


def test_a_session_whose_environment_is_gone_is_lost_and_starts_a_new_one(tmp_path, stub, relay):
    stub.script = [text_turn("one"), text_turn("two")]
    lines, _ = run_driver({"cwd": str(tmp_path), "prompt": "first"}, relay)
    del stub.envs["env1"]                                    # Google's TTL took it
    lines, _ = run_driver({"cwd": str(tmp_path), "prompt": "second", "resume_session_id": "env1"}, relay)
    assert [ln for ln in lines if ln["m"] == "resume_lost"][0]["p"]["requested_session_id"] == "env1"
    second = stub.creates()[1]
    assert second["environment"] == "env3" and "previous_interaction_id" not in second
    st = json.loads((tmp_path / rs.ANTIGRAVITY_STATE_REL).read_text())
    assert st["environments"] == ["env1", "env3"]            # both recorded, so a delete reaches both


def test_a_conversation_still_running_an_earlier_message_is_refused_not_sent_again(tmp_path, stub, relay):
    stub.script = [text_turn("one")]
    run_driver({"cwd": str(tmp_path), "prompt": "first"}, relay)
    stub.interactions["v1_int2"]["status"] = "in_progress"
    lines, _ = run_driver({"cwd": str(tmp_path), "prompt": "second", "resume_session_id": "env1"}, relay)
    res = hr_result(lines)
    assert res["status"] == "failed" and "still working on an earlier message" in res["reason"]
    assert len(stub.creates()) == 1


# ── the stream ────────────────────────────────────────────────────────────────────────────────────
def test_the_stream_maps_to_the_canonical_events(tmp_path, stub, relay):
    calls = [ev("step.start", index=1, step={"type": "code_execution_call", "id": "c1"}),
             ev("step.delta", index=1, delta={"type": "code_execution_call", "arguments": {"code": "print(1)", "language": "python"}}),
             ev("step.stop", index=1),
             ev("step.start", index=2, step={"type": "code_execution_result", "call_id": "c1"}),
             ev("step.delta", index=2, delta={"type": "code_execution_result", "result": "1\n", "is_error": False}),
             ev("step.stop", index=2, usage={"total_tokens": 10}),
             ev("step.start", index=3, step={"type": "mcp_server_tool_call", "id": "m1", "name": "lookup", "server_name": "crm", "arguments": {}}),
             ev("step.delta", index=3, delta={"type": "arguments_delta", "arguments": "{\"q\": \"ac"}),
             ev("step.delta", index=3, delta={"type": "arguments_delta", "arguments": "me\"}"}),
             ev("step.stop", index=3),
             ev("step.start", index=4, step={"type": "mcp_server_tool_result", "call_id": "m1"}),
             ev("step.delta", index=4, delta={"type": "mcp_server_tool_result", "result": [{"type": "text", "text": "found"}]}),
             ev("step.stop", index=4),
             ev("some.future_event", whatever=True)]          # an event this driver does not know: skipped
    stub.script = [text_turn("Hello ", "world.", extra=calls)]
    lines, proc = run_driver({"cwd": str(tmp_path), "prompt": "go"}, relay)
    events, state = normalise(lines)
    blocks = [c for e in events if e["type"] in ("assistant", "user") for c in e["message"]["content"]]
    assert {"type": "thinking", "thinking": "Planning."} in blocks
    uses = [b for b in blocks if b["type"] == "tool_use"]
    assert uses[0] == {"type": "tool_use", "id": "c1", "name": "code_execution", "input": {"code": "print(1)", "language": "python"}}
    assert uses[1] == {"type": "tool_use", "id": "m1", "name": "mcp__crm__lookup", "input": {"q": "acme"}}
    results = [b for b in blocks if b["type"] == "tool_result"]
    assert results[0]["tool_use_id"] == "c1" and results[0]["content"] == "1\n" and results[0]["is_error"] is False
    assert results[1]["tool_use_id"] == "m1" and results[1]["content"] == "found"
    assert "".join(b["text"] for b in blocks if b["type"] == "text") == "Hello world."
    init = [e for e in events if e.get("subtype") == "init"]
    assert len(init) == 1 and init[0]["session_id"] == "env1"
    res = result_of(events)
    assert res["subtype"] == "success" and res["result"] == "Hello world."
    # Google's own count: fresh input, output with the thinking in it, reasoning a subset, cache reads apart
    assert res["usage"] == {"input_tokens": 400, "output_tokens": 500, "cache_read_tokens": 600, "reasoning_tokens": 300}
    assert "model" not in res                                # the configured model is not the one that served


def test_usage_counts_tool_prompts_with_the_input_and_reasoning_never_exceeds_output():
    u = drv.usage_of({"total_input_tokens": 50, "total_cached_tokens": 20, "total_tool_use_tokens": 5,
                      "total_output_tokens": 7, "total_thought_tokens": 11, "total_tokens": 73})
    assert u == {"input_tokens": 35, "output_tokens": 18, "cache_read_tokens": 20, "reasoning_tokens": 11}
    assert u["reasoning_tokens"] <= u["output_tokens"]
    assert drv.usage_of(None) == {} and drv.usage_of({}) == {}
    assert drv.usage_of({"total_output_tokens": "9"})["output_tokens"] == 9


def test_a_dropped_stream_resumes_from_the_last_event_id_without_writing_text_twice(tmp_path, stub, relay):
    """The stream ends before the interaction does; the driver asks where it stands and, still in
    progress, reconnects with the last event id; the end comes from the interaction's document."""
    stub.script = [[ev("step.start", index=0, step={"type": "model_output"}),
                    ev("step.delta", index=0, delta={"type": "text", "text": "Hal"}, event_id="e5")]]
    def finish_later():
        time.sleep(1.0)
        it = stub.interactions.get("v1_int2")
        if it:
            it.update(status="completed", usage={"total_input_tokens": 3, "total_output_tokens": 2},
                      steps=[{"type": "user_input", "content": [{"type": "text", "text": "go"}]},
                             {"type": "model_output", "content": [{"type": "text", "text": "Halfway there."}]}])
    threading.Thread(target=finish_later, daemon=True).start()
    lines, proc = run_driver({"cwd": str(tmp_path), "prompt": "go"}, relay)
    res = hr_result(lines)
    assert res["status"] == "completed", proc.stderr
    streams = [c for c in stub.calls if c["method"] == "GET" and c["query"].get("stream") == "true"]
    assert not streams or streams[0]["query"].get("last_event_id") == "e5"
    texts = [ln["p"]["text"] for ln in lines if ln["m"] == "text"]
    assert texts[0] == "Hal" and "".join(texts) == "Halfway there."    # what was streamed is not written again
    assert res["final"] == "Halfway there." and res["usage"]["output_tokens"] == 2


# ── the status ────────────────────────────────────────────────────────────────────────────────────
def test_a_token_budget_ends_the_turn_incomplete_with_that_reason(tmp_path, stub, relay):
    stub.script = [text_turn("Partial", status="incomplete")]
    lines, _ = run_driver({"cwd": str(tmp_path), "prompt": "go", "max_total_tokens": 50000}, relay)
    assert stub.creates()[0]["agent_config"]["max_total_tokens"] == 50000
    res = result_of(normalise(lines)[0])
    assert res["subtype"] == "incomplete" and "token budget" in res["reason"] and "50000" in res["reason"]


@pytest.mark.parametrize("status,want", [("failed", "error"), ("requires_action", "incomplete"), ("cancelled", "error")])
def test_every_other_end_is_mapped(tmp_path, stub, relay, status, want):
    stub.script = [[ev("error", error={"message": "Deadline expired before operation could complete.", "code": "gateway_timeout"}),
                    ev("interaction.completed", interaction={"status": status}), ev("done")]]
    lines, _ = run_driver({"cwd": str(tmp_path), "prompt": "go"}, relay)
    res = result_of(normalise(lines)[0])
    assert res["subtype"] == want
    if status == "failed":
        assert "Deadline expired" in res["reason"]
    if status == "requires_action":
        assert "requires_action" in res["reason"]


def test_google_refusing_the_request_fails_the_turn_in_words_with_no_key_in_them(tmp_path, stub, relay):
    stub.fail_create = (403, f"API key not valid for this project: key={KEY}; x-goog-api-key: {KEY}")
    lines, proc = run_driver({"cwd": str(tmp_path), "prompt": "go"}, relay)
    res = hr_result(lines)
    assert res["status"] == "failed" and res["reason"].startswith("Google refused the key of the Google AI Studio connection")
    assert KEY not in proc.stdout and KEY not in proc.stderr


def test_a_tool_that_ran_although_switched_off_makes_the_turn_say_so(tmp_path, stub, relay):
    extra = [ev("step.start", index=1, step={"type": "google_search_call", "id": "g1"}),
             ev("step.delta", index=1, delta={"type": "google_search_call", "arguments": {"queries": ["x"]}}),
             ev("step.stop", index=1)]
    stub.script = [text_turn("ok", extra=extra)]
    lines, _ = run_driver({"cwd": str(tmp_path), "prompt": "go", "tools_disabled": ["google_search"]}, relay)
    res = hr_result(lines)
    assert res["status"] == "incomplete" and "google_search although switched off" in res["reason"]


def test_sigterm_cancels_the_interaction_at_google_and_the_record_says_so(tmp_path, stub, relay):
    stub.hang = True
    stub.script = [[ev("step.start", index=0, step={"type": "model_output"}),
                    ev("step.delta", index=0, delta={"type": "text", "text": "working"})]]
    base, tok = relay
    job = {"base_url": base, "api_key": tok, "model": "gemini-4-hydrogen", "cwd": str(tmp_path), "prompt": "long",
           "tar": TAR, "exclude": []}
    proc = subprocess.Popen([sys.executable, DRIVER, json.dumps(job)], stdout=subprocess.PIPE, text=True)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and not stub.interactions:
        time.sleep(0.05)
    time.sleep(0.5)
    proc.send_signal(signal.SIGTERM)
    out, _ = proc.communicate(timeout=20)
    lines = [json.loads(ln) for ln in out.splitlines() if ln.startswith("{")]
    assert stub.interactions["v1_int2"]["status"] == "cancelled"
    assert [c for c in stub.calls if c["path"] == "/v1beta/interactions/v1_int2:cancel"]
    res = hr_result(lines)
    assert res["status"] == "cancelled" and "cancel accepted by Google for interaction v1_int2" in res["reason"]
    assert proc.returncode == 0


def test_the_eof_says_googles_interaction_may_still_be_running():
    out = rs._antigravity_to_claude.eof({"_ag_notices": ["the event stream dropped"]}, 1)
    assert out[0]["is_error"] and "may still be running" in out[0]["result"]


# ── files ────────────────────────────────────────────────────────────────────────────────────────
def test_the_workspace_goes_up_as_the_checkpoint_keeps_it_and_no_link_is_sent(tmp_path, stub, relay):
    ws = tmp_path
    (ws / "keep.txt").write_text("keep")
    (ws / "sub").mkdir()
    (ws / "sub" / "code.py").write_text("print(1)")
    for d in ("tmp", "node_modules/pkg", "sub/node_modules", ".harness/home", ".git"):
        (ws / d).mkdir(parents=True, exist_ok=True)
    (ws / "tmp" / "scratch").write_text("s")
    (ws / "node_modules" / "pkg" / "i.js").write_text("x")
    (ws / "sub" / "node_modules" / "j.js").write_text("y")
    (ws / ".harness" / "home" / "secret").write_text("runner's")
    (ws / ".git" / "HEAD").write_text("ref")
    (ws / "outside").symlink_to("/etc/hosts")
    (ws / "outdir").symlink_to("/etc")
    stub.script = [text_turn("ok")]
    lines, proc = run_driver({"cwd": str(ws), "prompt": "go"}, relay)
    assert hr_result(lines)["status"] == "completed", proc.stderr
    sent = sorted(k for k in stub.envs["env1"])
    assert sent == ["workspace/keep.txt", "workspace/sub/code.py"]
    # a link is never read through either: what the driver recorded as sent is the two plain files
    st = json.loads((ws / rs.ANTIGRAVITY_STATE_REL).read_text())
    assert sorted(st["synced"]) == ["keep.txt", "sub/code.py"]


def test_a_workspace_over_the_cap_is_refused_before_anything_is_made_at_google(tmp_path, stub, relay):
    (tmp_path / "big.bin").write_bytes(b"x" * 4096)
    lines, _ = run_driver({"cwd": str(tmp_path), "prompt": "go", "upload_max_bytes": 1024}, relay)
    res = hr_result(lines)
    assert res["status"] == "failed" and "over the 1024-byte limit" in res["reason"]
    assert stub.calls == []                                  # not even an environment


def test_what_the_agent_changes_comes_back_and_what_it_removes_goes(tmp_path, stub, relay):
    (tmp_path / "old.md").write_text("old")
    (tmp_path / "edit.md").write_text("v1")
    stub.script = [text_turn("ok", extra=[("write", "workspace/report.pdf", b"%PDF-1"),
                                          ("write", "workspace/edit.md", b"v2"),
                                          ("write", "workspace/deep/dir/out.csv", b"a,b"),
                                          ("write", "workspace/tmp/scratch.txt", b"scratch"),
                                          ("delete", "workspace/old.md")])]
    lines, proc = run_driver({"cwd": str(tmp_path), "prompt": "go"}, relay)
    assert hr_result(lines)["status"] == "completed", proc.stderr
    assert (tmp_path / "report.pdf").read_bytes() == b"%PDF-1"
    assert (tmp_path / "edit.md").read_text() == "v2"
    assert (tmp_path / "deep" / "dir" / "out.csv").read_text() == "a,b"
    assert not (tmp_path / "tmp" / "scratch.txt").exists()   # scratch, as the checkpoint keeps it out
    assert not (tmp_path / "old.md").exists()
    assert set(hr_result(lines)["files"]) >= {"report.pdf", "edit.md", "deep/dir/out.csv", "old.md"}
    # next turn, nothing changed on either side: nothing comes back again, nothing goes up again
    ups, downs = len(stub.uploads()), len([c for c in stub.calls if c["query"].get("alt") == "media"])
    stub.script = [text_turn("again")]
    lines, _ = run_driver({"cwd": str(tmp_path), "prompt": "again", "resume_session_id": "env1"}, relay)
    assert len(stub.uploads()) == ups and len([c for c in stub.calls if c["query"].get("alt") == "media"]) == downs


@pytest.mark.parametrize("bad", ["workspace/../escape.txt", "/etc/passwd", "workspace/.harness/antigravity/state.json",
                                 "workspace/.git/config", "elsewhere/x.txt", "workspace/a\\b.txt", "workspace//x",
                                 "workspace/./x"])
def test_a_path_from_google_that_is_not_plain_never_lands(tmp_path, stub, relay, bad):
    stub.listing_extra = [{"name": "x", "path": bad, "type": "FILE", "size_bytes": "3", "modified": "m"}]
    stub.script = [text_turn("ok")]
    lines, _ = run_driver({"cwd": str(tmp_path), "prompt": "go"}, relay)
    res = hr_result(lines)
    assert res["status"] == "incomplete" and "not brought back" in res["reason"]
    assert not (tmp_path.parent / "escape.txt").exists()
    assert not [c for c in stub.calls if c["query"].get("alt") == "media"]      # never even fetched


def test_a_file_is_never_written_through_a_symlink(tmp_path, stub, relay):
    target = tmp_path / "victim"
    target.mkdir()
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "out").symlink_to(target)
    (ws / "link.txt").symlink_to(target / "f")
    stub.script = [text_turn("ok", extra=[("write", "workspace/out/f.txt", b"through"),
                                          ("write", "workspace/link.txt", b"over")])]
    lines, _ = run_driver({"cwd": str(ws), "prompt": "go"}, relay)
    res = hr_result(lines)
    assert res["status"] == "incomplete" and "out/f.txt" in res["reason"] and "link.txt" in res["reason"]
    assert list(target.iterdir()) == [] and (ws / "link.txt").is_symlink()


def test_safe_rel_and_excluded():
    assert drv.safe_rel("workspace/a/b.txt") == ("a/b.txt", "")
    for bad in ("workspace/..", "workspace/../x", "/workspace/x", "workspace/.git/x", "workspace/.harness",
                "x/y", "workspace/", "workspace/a\x00b"):
        assert drv.safe_rel(bad)[1], bad
    ex = list(rs.CHECKPOINT_EXCLUDE)
    assert drv.excluded("tmp/x", ex) and drv.excluded("a/node_modules/b", ex) and drv.excluded(".git/HEAD", ex)
    assert drv.excluded(".harness/home/.codex/auth.json", ex) and drv.excluded("x/.cache/pip/y", ex)
    assert not drv.excluded("a/tmp/x", ex) and not drv.excluded("src/main.py", ex) and not drv.excluded("cache/pip", ex)


def test_the_archive_is_the_checkpoints_command(tmp_path):
    """The driver's archive command is the checkpoint's: the same tar and flags, the same exclusions,
    the runner's tree and the git history out besides."""
    env: dict = {}
    cmd = rs._build_antigravity("google", rs.Auth(api_key=KEY), "gemini-4-hydrogen", "hi", str(tmp_path), env)
    job = json.loads(env["HR_DRIVER_JOB"])
    try:
        made = drv.tar_command(job, "/spool/a.tgz", str(tmp_path), job["exclude"] + ["./.harness", "./.git"])
        assert made == rs._workspace_tar_argv(str(tmp_path), "/spool/a.tgz", rs._ANTIGRAVITY_NOT_SENT)
        assert job["tar"]["argv"] == list(rs._WORKSPACE_TAR) and job["exclude"] == list(rs.CHECKPOINT_EXCLUDE)
        assert cmd == [rs.ANTIGRAVITY_PYTHON, rs.ANTIGRAVITY_DRIVER]
    finally:
        rs._HERMES_RELAY["routes"].pop(job["api_key"], None)


def test_skills_go_into_the_agents_skills_folder_once_and_a_removed_one_is_switched_off(tmp_path, stub, relay):
    rs._write_skills(str(tmp_path), [{"name": "deck", "files": [{"path": "SKILL.md", "content": "---\nname: deck\ndescription: d\n---\nbody"}]}],
                     "antigravity")
    skill = {"name": "deck", "dir": str(tmp_path / ".harness" / "skills" / "deck")}
    stub.script = [text_turn("one"), text_turn("two"), text_turn("three")]
    run_driver({"cwd": str(tmp_path), "prompt": "a", "skills": [skill]}, relay)
    assert b"body" in stub.envs["env1"][".agents/skills/deck/SKILL.md"]
    assert not any(k.startswith("workspace/.harness") for k in stub.envs["env1"])
    n = len(stub.uploads())
    run_driver({"cwd": str(tmp_path), "prompt": "b", "resume_session_id": "env1", "skills": [skill]}, relay)
    assert len(stub.uploads()) == n                          # unchanged: not sent again
    run_driver({"cwd": str(tmp_path), "prompt": "c", "resume_session_id": "env1", "skills": []}, relay)
    assert b"Switched off" in stub.envs["env1"][".agents/skills/deck/SKILL.md"]


def test_an_attached_image_also_goes_inline_with_the_message(tmp_path, stub, relay):
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    (tmp_path / "chart.png").write_bytes(png)
    stub.script = [text_turn("ok")]
    run_driver({"cwd": str(tmp_path), "prompt": "read it", "input_files": ["chart.png"]}, relay)
    parts = stub.creates()[0]["input"]
    assert parts[1] == {"type": "image", "mime_type": "image/png", "data": base64.b64encode(png).decode()}


# ── MCP servers ──────────────────────────────────────────────────────────────────────────────────
def test_only_public_https_streamable_servers_go_and_the_rest_are_reported(tmp_path, stub, relay):
    servers = [{"name": "CRM Tools", "url": "https://mcp.example.com/mcp", "auth": "tok-from-request-1234",
                "headers": {"X-Tenant": "acme-request-value"}},
               {"name": "local", "url": "http://127.0.0.1:9000/mcp"},
               {"name": "private", "url": "https://10.0.0.5/mcp"},
               {"name": "sse", "url": "https://mcp.example.com/sse", "transport": "sse"},
               {"name": "proc", "command": "npx", "args": ["x"], "transport": "stdio"}]
    withheld = [{"name": "vaulted", "reason": "its access key is stored on this instance"}]
    stub.script = [text_turn("ok")]
    lines, _ = run_driver({"cwd": str(tmp_path), "prompt": "go", "mcp_servers": servers, "mcp_withheld": withheld}, relay)
    tools = stub.creates()[0]["tools"]
    mcp = [t for t in tools if t["type"] == "mcp_server"]
    assert mcp == [{"type": "mcp_server", "name": "crm-tools", "url": "https://mcp.example.com/mcp",
                    "headers": {"Authorization": "Bearer tok-from-request-1234", "X-Tenant": "acme-request-value"}}]
    unavailable = [ln["p"]["servers"] for ln in lines if ln["m"] == "mcp_unavailable"][0]
    assert {u["name"] for u in unavailable} == {"vaulted", "local", "private", "sse", "proc"}
    events, _ = normalise(lines)
    sys_ev = [e for e in events if e.get("subtype") == "mcp_unavailable"][0]
    assert {s["name"] for s in sys_ev["servers"]} == {"vaulted", "local", "private", "sse", "proc"}
    assert all(s.get("reason") for s in sys_ev["servers"])
    # the values handed to Google for its servers are in no line this driver wrote
    out = json.dumps(lines)
    assert "tok-from-request-1234" not in out and "acme-request-value" not in out


# ── the key ──────────────────────────────────────────────────────────────────────────────────────
def test_the_key_stays_in_the_relay_and_reaches_google_only_as_x_goog_api_key(tmp_path, stub, relay):
    (tmp_path / "a.txt").write_text("a")
    stub.script = [text_turn("ok", extra=[("write", "workspace/b.txt", b"b")])]
    lines, proc = run_driver({"cwd": str(tmp_path), "prompt": "go"}, relay)
    assert hr_result(lines)["status"] == "completed", proc.stderr
    assert stub.keys_seen == {KEY}                           # every call carried the real key, and only it
    assert not stub.bearers_seen                             # never a bearer beside it (Google reads it as OAuth)
    _base, tok = relay
    for blob in (proc.stdout, proc.stderr, (tmp_path / rs.ANTIGRAVITY_STATE_REL).read_text()):
        assert KEY not in blob and tok not in blob
    assert all(KEY not in json.dumps(ln) for ln in lines)


def test_the_route_forwards_this_agents_calls_and_nothing_else_the_key_can_do(stub, relay):
    base, tok = relay

    def call(method: str, path: str, body: bytes | None = None):
        req = urllib.request.Request(base + path, data=body, method=method,
                                     headers={"x-goog-api-key": tok, "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    before = len(stub.calls)
    for method, path in (("POST", "/v1beta/models/gemini-4-hydrogen:generateContent"),
                         ("GET", "/v1beta/files"),
                         ("GET", "/v1beta/environments/env1/files/workspace/%2e%2e/%2e%2e/x?alt=media"),
                         ("GET", "/v1beta/environments/env1/files/workspace/..%252fx"),
                         ("GET", "/v1beta/interactions/abc?key=other"),
                         ("PUT", "/v1beta/interactions"),
                         ("DELETE", "/v1beta/corpora/x")):
        code, data = call(method, path, b"{}" if method in ("POST", "PUT") else None)
        assert code == 403, (method, path, code)
        assert json.loads(data)["error"]["status"] == "PERMISSION_DENIED"
    assert len(stub.calls) == before                         # none reached Google
    code, _ = call("POST", "/v1beta/environments", b"{}")
    assert code == 200 and stub.calls[-1]["headers"]["x-goog-api-key"] == KEY


def test_a_model_route_still_refuses_put_and_delete(stub):
    base, tok = rs._hermes_relay_route(stub.base, "k")
    try:
        for method in ("PUT", "DELETE"):
            req = urllib.request.Request(base + "/x", data=b"{}" if method == "PUT" else None, method=method,
                                         headers={"authorization": f"Bearer {tok}"})
            with pytest.raises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(req, timeout=10)
            assert e.value.code == 405
    finally:
        rs._HERMES_RELAY["routes"].pop(tok, None)


def test_the_scrub_takes_out_the_placeholder_googles_key_shape_and_header_values():
    s = drv.Scrub()
    s.add("hr-relay-0123456789abcdef")
    s.add("Bearer mcp-secret-value-123")
    said = s.error(f"x-goog-api-key: {KEY} placeholder hr-relay-0123456789abcdef url ?key={KEY}&a=1 "
                   "Bearer mcp-secret-value-123 authorization: Bearer abcdefgh")
    for leaked in (KEY, "hr-relay-0123456789abcdef", "mcp-secret-value-123", "abcdefgh"):
        assert leaked not in said, leaked
    # the agent's own prose about authorization is not mangled
    assert s.text("Send an Authorization: Bearer header") == "Send an Authorization: Bearer header"


# ── the builder, the registration points ─────────────────────────────────────────────────────────
def test_the_builder_hands_the_driver_the_relay_and_a_placeholder_never_the_key(tmp_path):
    env: dict = {}
    cmd = rs._build_antigravity("google", rs.Auth(api_key=KEY, base_url="https://generativelanguage.googleapis.com/v1beta/openai"),
                                "gemini-4-argon", "hi", str(tmp_path), env, resume_session_id="env9",
                                tools_disabled=["url_context"], agent_doc="Rules.", input_files=["a.md"],
                                mcp_withheld=[{"name": "v", "reason": "r"}], skills=[{"name": "s", "dir": "/x/s"}])
    job = json.loads(env["HR_DRIVER_JOB"])
    tok = job["api_key"]
    try:
        assert len(cmd) == 2                                 # the job rides the env: argv is every uid's to read
        assert tok.startswith("hr-relay-") and KEY not in json.dumps(cmd) and KEY not in json.dumps(env)
        route = rs._HERMES_RELAY["routes"][tok]
        assert route[0] == rs.ANTIGRAVITY_BASE and route[1] == KEY
        assert route[2].get("passthrough") is True and route[2].get("google_key") is True
        assert job["base_url"].startswith("http://127.0.0.1:") and job["resume_session_id"] == "env9"
        assert job["tools_disabled"] == ["url_context"] and job["agent_doc"] == "Rules." and job["model"] == "gemini-4-argon"
        assert job["mcp_withheld"] == [{"name": "v", "reason": "r"}] and job["input_files"] == ["a.md"]
    finally:
        rs._HERMES_RELAY["routes"].pop(tok, None)
    with pytest.raises(rs.HTTPException):
        rs._build_antigravity("google", rs.Auth(), "m", "hi", str(tmp_path), {})              # no key
    with pytest.raises(rs.HTTPException):
        rs._build_antigravity("openai", rs.Auth(api_key="k"), "m", "hi", str(tmp_path), {})   # not this base's provider
    with pytest.raises(rs.HTTPException) as e:
        rs._build_antigravity("google", rs.Auth(api_key="k", base_url="https://proxy.example.com/v1"), "m", "hi",
                              str(tmp_path), {})
    assert "not Google's" in e.value.detail


def test_the_registration_points():
    assert rs.BACKENDS["antigravity"]["remote"] is True
    assert rs.BACKENDS["antigravity"]["normalize"] is rs._antigravity_to_claude
    assert rs.BACKENDS["antigravity"]["providers"] == ["google"]
    assert rs.ANTIGRAVITY_TOOLS == drv.TOOLS and rs.ANTIGRAVITY_MODELS == drv.MODELS
    assert rs.ANTIGRAVITY_DEFAULT_MODEL == drv.DEFAULT_MODEL == "gemini-4-hydrogen"
    assert "antigravity" in rs._MCP_AGENT_RUNS_ELSEWHERE and "antigravity" in rs._GENERIC_STEP_BUDGET
    assert rs._SESSION_PRESENT.get("antigravity") is None   # the driver itself reports a lost session
    assert rs._compose_agent_doc("/w", "antigravity", "Rules.", []) == ""


def test_no_agent_doc_is_written_and_skills_are_staged_under_harness(tmp_path):
    rs._write_agent_doc(str(tmp_path), "antigravity", "Rules.", [])
    assert not list(tmp_path.iterdir()), "this backend reads no workspace file"
    installed = rs._write_skills(str(tmp_path), [{"name": "deck", "files": [{"path": "SKILL.md", "content": "---\nname: deck\ndescription: d\n---\n"}]}], "antigravity")
    assert installed and installed[0]["entry"].startswith(".harness/skills/deck/")


def test_an_environment_is_refused_on_this_base_before_anything_starts():
    assert rs.BACKENDS["antigravity"].get("remote")         # turn() refuses an environment for every remote base


# ── purge ────────────────────────────────────────────────────────────────────────────────────────
def test_the_purge_deletes_every_interaction_and_environment_and_reports_what_it_could_not(tmp_path, stub, relay):
    stub.script = [text_turn("one")]
    run_driver({"cwd": str(tmp_path), "prompt": "first"}, relay)
    st = json.loads((tmp_path / rs.ANTIGRAVITY_STATE_REL).read_text())
    st["environments"].append("env_gone")
    st["interactions"].append("v1_gone")
    (tmp_path / rs.ANTIGRAVITY_STATE_REL).write_text(json.dumps(st))
    base, tok = relay
    proc = subprocess.run([sys.executable, DRIVER, json.dumps({"purge": True, "cwd": str(tmp_path), "base_url": base,
                                                               "api_key": tok})], capture_output=True, text=True, timeout=30)
    report = [json.loads(ln) for ln in proc.stdout.splitlines() if ln.startswith("{")][-1]["p"]
    assert proc.returncode == 0 and report["failed"] == []
    assert "delete environment env1" in report["done"] and "delete interaction v1_int2" in report["done"]
    assert "delete environment env_gone (already gone)" in report["done"]
    assert "env1" not in stub.envs and "v1_int2" not in stub.interactions


def test_delete_workspace_purges_at_google_with_the_connection_it_is_sent(tmp_path, stub, monkeypatch):
    import asyncio
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(rs, "WORKSPACE_ROOT", str(root))
    monkeypatch.setattr(rs, "_SANDBOX_PER_SESSION", False)
    monkeypatch.setattr(rs, "ANTIGRAVITY_BASE", stub.base)
    sid = "hsessantigravity0123456789abcdef012345"
    ws = pathlib.Path(rs._ws(sid))
    (ws / ".harness" / "antigravity").mkdir(parents=True)
    stub.envs["env7"] = {}
    stub.interactions["v1_x"] = {"id": "v1_x", "status": "completed"}
    (ws / rs.ANTIGRAVITY_STATE_REL).write_text(json.dumps({"environment_id": "env7", "environments": ["env7"],
                                                           "interactions": ["v1_x"]}))
    auth = rs.Auth(api_key=KEY, base_url="https://generativelanguage.googleapis.com/v1beta/openai")
    out = asyncio.run(rs.delete_workspace(sid, rs.WorkspaceDelete(auth=auth, backend="antigravity")))
    assert out["removed"] is True and out["remote"]["purged"] is True and out["remote"]["backend"] == "antigravity"
    assert "env7" not in stub.envs and "v1_x" not in stub.interactions and stub.keys_seen == {KEY}
    # without a credential the folder still goes, and the answer says what was left at Google
    (ws / ".harness" / "antigravity").mkdir(parents=True)
    (ws / rs.ANTIGRAVITY_STATE_REL).write_text(json.dumps({"environment_id": "env8"}))
    out = asyncio.run(rs.delete_workspace(sid))
    assert out["removed"] is True and out["remote"] == {"backend": "antigravity", "purged": False,
                                                         "reason": "no credential", "state": rs.ANTIGRAVITY_STATE_REL}
