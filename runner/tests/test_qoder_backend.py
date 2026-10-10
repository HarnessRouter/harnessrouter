"""The qoder backend: Qoder Cloud Agent, a hosted runtime reached over REST + SSE.

The first backend whose runtime is not a process the runner spawns, so what these pin is what the
remote shape changes (docs/harness-verification.md, "remote runtimes"):

  the relay route is a pass-through: a session object naming the configured model passes it and the
      turn's served model stays EMPTY; a DELETE goes up; a stalled stream is closed, not narrated
  a stop reaches the driver: SIGTERM, the grace, and the driver's own line about the remote cancel
      arrives in the record before the kill
  artifacts land in the workspace ROOT under a plain name, every declared one or the turn is
      `incomplete`; `../x` and `.harness/x` are refused and nothing is written for them; an existing
      file is never overwritten
  hard holds across turns: a tool disabled between two turns of one session is withheld on the
      second (the session's tools are replaced before the message goes)
  continuation: the session the caller names is continued; one that is gone reports resume_lost
  a pending confirmation is answered (allow, or deny for a disabled tool) rather than parked
  a purge reaches every remote id the state recorded, and a delete that fails is reported, not
      swallowed; `DELETE /workspace` runs it with the connection the gateway sends
  the credential never reaches the driver: it holds the relay's placeholder

A stub of the Managed API (runner/tests/fixtures-free, built here) answers the driver, run as the
real subprocess it is; nothing here reaches api.qoder.com.
"""
import http.server
import json
import pathlib
import signal
import subprocess
import sys
import threading
import time
import urllib.request

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import qoder_driver as drv  # noqa: E402
import server as rs  # noqa: E402

DRIVER = str(pathlib.Path(__file__).resolve().parents[1] / "qoder_driver.py")


# ── a stub of the Managed API ──────────────────────────────────────────────────────────────────────
class Stub:
    """Scripted sessions: each session's stream serves one STAGE of events per connection, then
    closes; a `user.message` makes the session running, a `user.tool_confirmation` keeps it running
    for the next stage, and the stage that carries an end_turn idle makes it idle."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict | None, dict]] = []
        self.n = 0
        self.sessions: dict[str, dict] = {}
        self.agents: dict[str, dict] = {}
        self.blobs: dict[str, bytes] = {}
        self.vault_creds: dict[str, list[dict]] = {}    # vault id -> its credentials
        self.env_delete_409 = False
        self.fail_deletes = False       # every DELETE of a vault/skill/file answers 500
        self.hang_streams = False
        self.script: list[list[dict]] = [[]]          # the stages a NEW session gets
        self.token_seen: set[str] = set()
        self.lock = threading.Lock()
        stub = self

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):  # noqa: D102
                pass

            def _send(self, code: int, doc, ctype="application/json"):
                data = json.dumps(doc).encode() if not isinstance(doc, (bytes, bytearray)) else bytes(doc)
                self.send_response(code)
                self.send_header("content-type", ctype)
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _err(self, code: int, kind: str, msg: str):
                self._send(code, {"type": "error", "request_id": "r", "error": {"type": kind, "message": msg}})

            def _body(self):
                n = int(self.headers.get("content-length") or 0)
                raw = self.rfile.read(n) if n else b""
                ctype = self.headers.get("content-type") or ""
                if "json" in ctype and raw:
                    try:
                        return json.loads(raw)
                    except ValueError:
                        return {"_raw": raw.decode("utf-8", "replace")}
                if "multipart" in ctype:
                    return {"_multipart": raw.decode("utf-8", "replace")}
                return None

            def do_GET(self):  # noqa: N802
                self._handle("GET")

            def do_POST(self):  # noqa: N802
                self._handle("POST")

            def do_DELETE(self):  # noqa: N802
                self._handle("DELETE")

            def _handle(self, method: str):
                path, _, query = self.path.partition("?")
                body = self._body() if method != "GET" else None
                hdrs = {k.lower(): v for k, v in self.headers.items()}
                with stub.lock:
                    stub.calls.append((method, self.path, body, hdrs))
                if path.startswith("/blob/"):
                    fid = path.split("/blob/", 1)[1]
                    if "authorization" in hdrs:
                        return self._err(400, "test", "a presigned download must carry no credential")
                    data = stub.blobs.get(fid)
                    return self._send(200, data, "application/octet-stream") if data is not None else self._err(404, "not_found_error", "no blob")
                tok = hdrs.get("authorization", "").removeprefix("Bearer ")
                stub.token_seen.add(tok)
                parts = [p for p in path.split("/") if p]
                if method == "DELETE" and stub.fail_deletes and parts and parts[0] in ("vaults", "skills", "files"):
                    return self._err(500, "api_error", "storage unavailable")
                try:
                    return self._route(method, parts, query, body)
                except Exception as e:  # noqa: BLE001
                    return self._err(500, "api_error", f"{type(e).__name__}: {e}")

            def _new(self, prefix: str) -> str:
                with stub.lock:
                    stub.n += 1
                    return f"{prefix}_{stub.n}"

            def _route(self, method, parts, query, body):  # noqa: C901
                if parts == ["environments"] and method == "POST":
                    return self._send(200, {"id": self._new("env"), "type": "environment"})
                if len(parts) == 2 and parts[0] == "environments" and method == "DELETE":
                    if stub.env_delete_409:
                        return self._err(409, "invalid_request_error", "in use; archive instead")
                    return self._send(200, {"id": parts[1], "type": "environment_deleted"})
                if len(parts) == 3 and parts[0] == "environments" and parts[2] == "archive":
                    return self._send(200, {"id": parts[1], "archived_at": "now"})
                if parts == ["agents"] and method == "POST":
                    aid = self._new("agent")
                    stub.agents[aid] = {"id": aid, "version": 1, **(body or {})}
                    return self._send(200, stub.agents[aid])
                if len(parts) == 2 and parts[0] == "agents":
                    a = stub.agents.get(parts[1])
                    if not a:
                        return self._err(404, "not_found_error", "no agent")
                    if method == "GET":
                        return self._send(200, a)
                    if int((body or {}).get("version", -1)) != a["version"]:
                        return self._err(409, "conflict_error", "version")
                    a.update({k: v for k, v in (body or {}).items() if k != "version"})
                    a["version"] += 1
                    return self._send(200, a)
                if len(parts) == 3 and parts[0] == "agents" and parts[2] == "archive":
                    return self._send(200, {"id": parts[1], "archived_at": "now"})
                if parts == ["vaults"] and method == "POST":
                    return self._send(200, {"id": self._new("vault"), "credentials": []})
                if len(parts) == 3 and parts[0] == "vaults" and parts[2] == "credentials":
                    # as Qoder documents it: an mcp_server_url is unique among a vault's ACTIVE credentials
                    creds = stub.vault_creds.setdefault(parts[1], [])
                    if method == "GET":
                        return self._send(200, {"data": [dict(c) for c in creds], "has_more": False})
                    url = ((body or {}).get("auth") or {}).get("mcp_server_url")
                    if any(c["mcp_server_url"] == url and not c.get("archived_at") for c in creds):
                        return self._err(409, "invalid_request_error", "an active credential exists for this server")
                    cid = self._new("vcred")
                    creds.append({"id": cid, "mcp_server_url": url, "token": ((body or {}).get("auth") or {}).get("token")})
                    return self._send(200, {"id": cid, "type": "vault_credential"})
                if len(parts) == 5 and parts[0] == "vaults" and parts[2] == "credentials" and parts[4] == "archive":
                    for c in stub.vault_creds.get(parts[1], []):
                        if c["id"] == parts[3]:
                            c["archived_at"] = "now"
                            return self._send(200, {"id": c["id"], "archived_at": "now"})
                    return self._err(404, "not_found_error", "no credential")
                if len(parts) == 2 and parts[0] == "vaults" and method == "DELETE":
                    return self._send(200, {"id": parts[1], "type": "vault_deleted"})
                if parts == ["skills"] and method == "POST":
                    return self._send(201, {"id": self._new("skill"), "latest_version": "100"})
                if len(parts) == 3 and parts[0] == "skills" and parts[2] == "versions":
                    return self._send(201, {"skill_id": parts[1], "version": "200"})
                if len(parts) == 2 and parts[0] == "skills" and method == "DELETE":
                    return self._send(200, {"id": parts[1], "type": "skill_deleted"})
                if parts == ["files"] and method == "POST":
                    return self._send(200, {"id": self._new("file"), "type": "file", "downloadable": False})
                if len(parts) == 3 and parts[0] == "files" and parts[2] == "content":
                    if parts[1] not in stub.blobs:
                        return self._err(404, "not_found_error", "no file")
                    host = self.headers.get("host")
                    return self._send(200, {"url": f"http://{host}/blob/{parts[1]}", "expires_at": "2099-01-01T00:00:00Z"})
                if len(parts) == 2 and parts[0] == "files" and method == "DELETE":
                    return self._send(200, {"id": parts[1], "type": "file_deleted"})
                if parts == ["sessions"] and method == "POST":
                    sid = self._new("sess")
                    stub.sessions[sid] = {"id": sid, "type": "session", "status": "idle", "archived_at": None,
                                          "agent": {"id": (body or {}).get("agent", {}).get("id"), "model": {"id": "ultimate"}},
                                          "usage": {"model_credits": 1.5, "sandbox_runtime_credits": 0.5, "total_credits": 2.0},
                                          "stages": [list(s) for s in stub.script], "stage": 0, "events": [],
                                          "resources": list((body or {}).get("resources") or [])}
                    return self._send(200, stub.sessions[sid])
                if len(parts) >= 2 and parts[0] == "sessions":
                    s = stub.sessions.get(parts[1])
                    if not s:
                        return self._err(404, "not_found_error", f"Session '{parts[1]}' was not found.")
                    if len(parts) == 2:
                        if method == "DELETE":
                            return self._send(200, {"id": s["id"], "type": "session_deleted"})
                        if method == "POST":
                            s["updated"] = body
                            return self._send(200, {k: v for k, v in s.items() if k not in ("stages", "events")})
                        return self._send(200, {k: v for k, v in s.items() if k not in ("stages", "events")})
                    if parts[2] == "cancel":
                        s["status"] = "idle"
                        s["cancelled"] = True
                        return self._send(202, {"id": s["id"], "type": "session", "status": "canceling"})
                    if parts[2] == "resources":
                        s["resources"].append(body)
                        return self._send(200, {"id": self._new("sesr"), **(body or {})})
                    if parts[2] == "events" and len(parts) == 3 and method == "POST":
                        out = []
                        for e in (body or {}).get("events") or []:
                            eid = self._new("evt")
                            rec = {"id": eid, **e, "processed_at": "t"}
                            s["events"].append(rec)
                            out.append(rec)
                            if e.get("type") in ("user.message", "user.tool_confirmation"):
                                s["status"] = "running"
                        return self._send(200, {"data": out})
                    if parts[2] == "events" and len(parts) == 3:
                        return self._send(200, {"data": s["events"][-20:], "first_id": (s["events"][-1]["id"] if s["events"] else None),
                                                "last_id": None, "has_more": False, "next_page": None})
                    if parts[2] == "events" and parts[3] == "stream":
                        return self._stream(s)
                return self._err(404, "not_found_error", f"no route {method} {'/'.join(parts)}")

            def _stream(self, s: dict):
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.send_header("transfer-encoding", "chunked")
                self.end_headers()

                def frame(eid: str, ev: str, doc: dict):
                    raw = f"id: {eid}\nevent: {ev}\ndata: {json.dumps(doc)}\n\n".encode()
                    self.wfile.write(f"{len(raw):x}\r\n".encode() + raw + b"\r\n")
                    self.wfile.flush()

                if stub.hang_streams:
                    for _ in range(600):
                        raw = b"event: heartbeat\ndata: {}\n\n"
                        try:
                            self.wfile.write(f"{len(raw):x}\r\n".encode() + raw + b"\r\n")
                            self.wfile.flush()
                        except OSError:
                            return
                        time.sleep(0.1)
                    return
                stage = s["stages"][s["stage"]] if s["stage"] < len(s["stages"]) else []
                s["stage"] += 1
                for ev in stage:
                    doc = dict(ev)
                    if doc.get("type") in ("event_start", "event_delta"):
                        eid = doc.get("event_id") or doc.get("event", {}).get("id") or "evt_x"
                    else:
                        eid = doc.setdefault("id", self._new("evt"))
                        s["events"].append(doc)
                    if doc.get("type") == "session.status_idle" and (doc.get("stop_reason") or {}).get("type") == "end_turn":
                        s["status"] = "idle"
                    if doc.get("type") == "session.status_terminated":
                        s["status"] = "terminated"
                    frame(eid, doc["type"], doc)
                    time.sleep(0.01)
                self.wfile.write(b"0\r\n\r\n")

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def close(self):
        self.srv.shutdown()

    def posted(self, method: str, path: str) -> list[tuple]:
        return [c for c in self.calls if c[0] == method and c[1].split("?", 1)[0] == path]


@pytest.fixture
def stub():
    s = Stub()
    yield s
    s.close()


IDLE = {"type": "session.status_idle", "stop_reason": {"type": "end_turn"}}
RUNNING = {"type": "session.status_running"}


def run_driver(job: dict, stub: Stub, timeout: float = 30.0, base: str | None = None, token: str = "placeholder"):
    job = {"base_url": base or stub.base, "api_key": token, "model": "ultimate", **job}
    proc = subprocess.run([sys.executable, DRIVER, json.dumps(job)], capture_output=True, text=True, timeout=timeout)
    lines = [json.loads(ln) for ln in proc.stdout.splitlines() if ln.strip().startswith("{")]
    return lines, proc


def normalise(lines: list[dict]) -> tuple[list[dict], dict]:
    state = {"model": "ultimate", "final": ""}
    out: list[dict] = []
    for obj in lines:
        out += rs._qoder_to_claude(obj, state)
    return out, state


def result_of(events: list[dict]) -> dict:
    return [e for e in events if e.get("type") == "result"][-1]


# ── the turn, end to end against the stub ─────────────────────────────────────────────────────────
def test_a_turn_with_a_tool_call_and_an_artifact(tmp_path, stub):
    stub.blobs["file_art"] = b"hello report"
    stub.script = [[RUNNING,
                    {"type": "event_start", "event": {"id": "evt_m1", "type": "agent.message"}},
                    {"type": "event_delta", "event_id": "evt_m1", "delta": {"type": "content_delta", "index": 0, "content": {"type": "text", "text": "Writing "}}},
                    {"type": "agent.message", "id": "evt_m1", "content": [{"type": "text", "text": "Writing the report."}]},
                    {"type": "agent.tool_use", "id": "evt_t1", "name": "Write", "input": {"file_path": "/data/report.md"}, "evaluated_permission": "allow"},
                    {"type": "agent.tool_result", "id": "evt_r1", "tool_use_id": "evt_t1", "content": [{"type": "text", "text": "ok"}], "is_error": False},
                    {"type": "agent.artifact_delivered", "file_id": "file_art", "original_filename": "report.md", "size": 12, "content_type": "text/markdown"},
                    {"type": "session.usage", "model_credits": 1.5, "sandbox_runtime_credits": 0.5, "total_credits": 2.0},
                    IDLE]]
    lines, proc = run_driver({"cwd": str(tmp_path), "prompt": "write a report", "tools_disabled": ["Bash"],
                              "agent_doc": "Be terse."}, stub)
    assert proc.returncode == 0, proc.stderr
    events, state = normalise(lines)
    res = result_of(events)
    assert res["subtype"] == "success" and not res["is_error"], res
    assert res["charge"] == {"amount": 2.0, "unit": "qoder_credits", "basis": "snapshot",
                             "model_credits": 1.5, "sandbox_runtime_credits": 0.5, "session_total": 2.0}
    assert res["usage"] == {} and "model" not in res         # neither is reported by the API
    assert rs._status_from_result(res, 0) == "done"
    texts = [c["text"] for e in events if e.get("type") == "assistant" for c in e["message"]["content"] if c["type"] == "text"]
    assert "".join(texts) == "Writing the report."           # the delta, then only the remainder
    tools = [c for e in events if e.get("type") == "assistant" for c in e["message"]["content"] if c["type"] == "tool_use"]
    assert tools == [{"type": "tool_use", "id": "evt_t1", "name": "Write", "input": {"file_path": "/data/report.md"}}]
    results = [c for e in events if e.get("type") == "user" for c in e["message"]["content"]]
    assert results == [{"type": "tool_result", "tool_use_id": "evt_t1", "is_error": False, "content": "ok"}]
    # the artifact landed in the workspace ROOT, not under .harness/, with the declared bytes
    assert (tmp_path / "report.md").read_bytes() == b"hello report"
    assert not (tmp_path / ".harness" / "report.md").exists()
    # the Agent: the disabled tool is out of the whitelist AND named disallowed; the rest always_allow
    agent = stub.posted("POST", "/agents")[0][2]
    ts = agent["tools"][0]
    assert ts["type"] == "agent_toolset_20260401" and "Bash" not in ts["enabled_tools"] and ts["disallowed_tools"] == ["Bash"]
    assert all(c["permission_policy"]["type"] == "always_allow" for c in ts["configs"] if c.get("enabled"))
    assert {c["name"] for c in ts["configs"] if c.get("enabled") is False} == {"Bash"}
    assert agent["system"].startswith("Be terse.") and "DeliverArtifacts" in agent["system"]
    # the session pinned the Agent's version and the environment the turn created
    sess = stub.posted("POST", "/sessions")[0][2]
    assert sess["agent"] == {"id": agent_id(stub), "type": "agent", "version": 1} and sess["environment_id"].startswith("env_")
    # the message went once, then the stream was opened from its id
    msgs = [c for c in stub.calls if c[0] == "POST" and c[1].endswith("/events")]
    assert len(msgs) == 1 and msgs[0][2]["events"][0]["content"] == [{"type": "text", "text": "write a report"}]
    streams = [c for c in stub.calls if "/events/stream" in c[1]]
    assert streams and streams[0][3].get("last-event-id", "").startswith("evt_")
    # the state records every remote id for the next turn and for the purge
    st = json.loads((tmp_path / ".harness" / "qoder" / "state.json").read_text())
    assert st["session_id"].startswith("sess_") and st["agent_id"].startswith("agent_") and st["environment_id"].startswith("env_")
    assert st["artifacts"] == ["file_art"]


def agent_id(stub: Stub) -> str:
    return next(iter(stub.agents))


def test_a_declared_artifact_that_does_not_land_makes_the_turn_incomplete(tmp_path, stub):
    stub.script = [[RUNNING,
                    {"type": "agent.message", "content": [{"type": "text", "text": "done"}]},
                    {"type": "agent.artifact_delivered", "file_id": "file_missing", "original_filename": "out.txt", "size": 3, "content_type": "text/plain"},
                    IDLE]]
    lines, proc = run_driver({"cwd": str(tmp_path), "prompt": "x"}, stub)
    events, _ = normalise(lines)
    res = result_of(events)
    assert res["subtype"] == "incomplete" and not res["is_error"]
    assert "out.txt" in res["reason"] and rs._status_from_result(res, 0) == "incomplete"
    assert not (tmp_path / "out.txt").exists()


@pytest.mark.parametrize("bad", ["../x.txt", ".harness/x.txt", "sub/dir/x.txt", "..", ".env", "a\\b.txt"])
def test_an_artifact_name_that_is_not_a_plain_file_name_is_refused(tmp_path, stub, bad):
    stub.blobs["file_bad"] = b"evil"
    stub.script = [[RUNNING,
                    {"type": "agent.artifact_delivered", "file_id": "file_bad", "original_filename": bad, "size": 4, "content_type": "text/plain"},
                    IDLE]]
    lines, _ = run_driver({"cwd": str(tmp_path), "prompt": "x"}, stub)
    events, _ = normalise(lines)
    res = result_of(events)
    assert res["subtype"] == "incomplete" and repr(bad) in res["reason"]
    written = [p for p in tmp_path.rglob("*") if p.is_file() and "state.json" not in p.name]
    assert written == [], written
    assert not (tmp_path.parent / "x.txt").exists()
    # nothing was even fetched for a refused name
    assert not [c for c in stub.calls if c[1].startswith("/files/file_bad/content")]


def test_an_existing_file_is_never_overwritten_and_a_symlink_is_never_followed(tmp_path):
    (tmp_path / "report.md").write_text("mine")
    written, note = drv.land_artifact(str(tmp_path), "report.md", b"theirs")
    assert written == "report (2).md" and "already existed" in note
    assert (tmp_path / "report.md").read_text() == "mine" and (tmp_path / "report (2).md").read_bytes() == b"theirs"
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("keep")
    (tmp_path / "link.txt").symlink_to(outside)
    written, note = drv.land_artifact(str(tmp_path), "link.txt", b"x")
    assert written == "link (2).txt" and "symlink" in note and outside.read_text() == "keep"


def test_artifact_names_are_input():
    for bad in ("../x", ".harness/x", "a/b", "a\\b", "..", ".", ".git", "", "x\x00y", "evil\n.txt"):
        name, why = drv.artifact_name(bad)
        assert name == "" and why, bad
    assert drv.artifact_name("report.pdf") == ("report.pdf", "")
    assert drv.artifact_name("  spaced name.md ") == ("spaced name.md", "")


# ── continuation, and hard across turns ───────────────────────────────────────────────────────────
def test_a_tool_disabled_between_two_turns_is_withheld_on_the_second(tmp_path, stub):
    stub.script = [[RUNNING, {"type": "agent.message", "content": [{"type": "text", "text": "one"}]}, IDLE]]
    lines, _ = run_driver({"cwd": str(tmp_path), "prompt": "first"}, stub)
    sid = json.loads((tmp_path / ".harness" / "qoder" / "state.json").read_text())["session_id"]
    stub.sessions[sid]["stages"] = [[RUNNING, {"type": "agent.message", "content": [{"type": "text", "text": "two"}]}, IDLE]]
    stub.sessions[sid]["stage"] = 0
    lines, proc = run_driver({"cwd": str(tmp_path), "prompt": "second", "resume_session_id": sid,
                              "tools_disabled": ["Bash", "WebFetch"]}, stub)
    events, _ = normalise(lines)
    assert result_of(events)["subtype"] == "success"
    assert len(stub.posted("POST", "/sessions")) == 1, "the session was continued, not recreated"
    # the Agent got a new version AND the session's own tools were replaced before the message
    agent_posts = [c for c in stub.calls if c[0] == "POST" and c[1] == f"/agents/{agent_id(stub)}"]
    assert agent_posts and "Bash" not in agent_posts[-1][2]["tools"][0]["enabled_tools"]
    upd = stub.sessions[sid]["updated"]
    assert upd["agent"]["tools"][0]["disallowed_tools"] == ["Bash", "WebFetch"]
    order = [c for c in stub.calls if c[0] == "POST" and c[1] in (f"/sessions/{sid}", f"/sessions/{sid}/events")]
    assert [c[1] for c in order][-2:] == [f"/sessions/{sid}", f"/sessions/{sid}/events"]
    # the init event names the session the caller asked to continue
    assert [e for e in events if e.get("subtype") == "init"][0]["session_id"] == sid
    assert not [e for e in events if e.get("subtype") == "resume_lost"]


def test_a_session_that_is_gone_is_reported_as_lost_and_a_new_one_is_made(tmp_path, stub):
    stub.script = [[RUNNING, {"type": "agent.message", "content": [{"type": "text", "text": "one"}]}, IDLE]]
    run_driver({"cwd": str(tmp_path), "prompt": "first"}, stub)
    st = json.loads((tmp_path / ".harness" / "qoder" / "state.json").read_text())
    stub.sessions[st["session_id"]]["archived_at"] = "2026-01-01T00:00:00Z"      # archived at Qoder
    lines, _ = run_driver({"cwd": str(tmp_path), "prompt": "second", "resume_session_id": st["session_id"]}, stub)
    events, _ = normalise(lines)
    lost = [e for e in events if e.get("subtype") == "resume_lost"]
    assert lost == [{"type": "system", "subtype": "resume_lost", "requested_session_id": st["session_id"]}]
    assert len(stub.posted("POST", "/sessions")) == 2
    assert result_of(events)["subtype"] == "success"
    # an id the state never knew is lost too, without a network call
    stub.calls.clear()
    lines, _ = run_driver({"cwd": str(tmp_path), "prompt": "third", "resume_session_id": "sess_never"}, stub)
    events, _ = normalise(lines)
    assert [e for e in events if e.get("subtype") == "resume_lost"]
    assert not [c for c in stub.calls if c[1] == "/sessions/sess_never"]


def test_a_session_still_running_an_earlier_turn_is_a_conflict_not_a_retry(tmp_path, stub):
    stub.script = [[RUNNING, {"type": "agent.message", "content": [{"type": "text", "text": "one"}]}, IDLE]]
    run_driver({"cwd": str(tmp_path), "prompt": "first"}, stub)
    sid = json.loads((tmp_path / ".harness" / "qoder" / "state.json").read_text())["session_id"]
    stub.sessions[sid]["status"] = "running"
    stub.calls.clear()
    lines, _ = run_driver({"cwd": str(tmp_path), "prompt": "second", "resume_session_id": sid}, stub)
    events, _ = normalise(lines)
    res = result_of(events)
    assert res["subtype"] == "error" and "still processing" in res["result"]
    assert not [c for c in stub.calls if c[1] == f"/sessions/{sid}/events" and c[0] == "POST"]


# ── confirmations, status mapping ─────────────────────────────────────────────────────────────────
def test_a_pending_confirmation_is_answered_and_the_turn_goes_on(tmp_path, stub):
    stub.script = [[RUNNING,
                    {"type": "agent.mcp_tool_use", "id": "evt_ask1", "name": "query", "mcp_server_name": "docs", "input": {}, "evaluated_permission": "ask"},
                    {"type": "agent.mcp_tool_use", "id": "evt_ask2", "name": "delete_all", "mcp_server_name": "docs", "input": {}, "evaluated_permission": "ask"},
                    {"type": "session.status_idle", "stop_reason": {"type": "requires_action", "event_ids": ["evt_ask1", "evt_ask2"]}}],
                   [{"type": "agent.message", "content": [{"type": "text", "text": "done"}]}, IDLE]]
    lines, proc = run_driver({"cwd": str(tmp_path), "prompt": "x", "tools_disabled": ["mcp__docs__delete_all"]}, stub)
    events, _ = normalise(lines)
    assert result_of(events)["subtype"] == "success", lines
    confirms = [e for c in stub.calls if c[0] == "POST" and c[1].endswith("/events")
                for e in (c[2] or {}).get("events", []) if e["type"] == "user.tool_confirmation"]
    assert confirms == [{"type": "user.tool_confirmation", "tool_use_id": "evt_ask1", "result": "allow"},
                        {"type": "user.tool_confirmation", "tool_use_id": "evt_ask2", "result": "deny",
                         "deny_message": "This tool is disabled for this harness."}]
    names = [c["name"] for e in events if e.get("type") == "assistant" for c in e["message"]["content"] if c["type"] == "tool_use"]
    assert names == ["mcp__docs__query", "mcp__docs__delete_all"]


def test_every_stop_reason_but_end_turn_is_incomplete_with_the_raw_reason(tmp_path, stub):
    stub.script = [[RUNNING, {"type": "agent.message", "content": [{"type": "text", "text": "partial"}]},
                    {"type": "session.status_idle", "stop_reason": {"type": "max_steps"}}]]
    lines, _ = run_driver({"cwd": str(tmp_path), "prompt": "x"}, stub)
    events, _ = normalise(lines)
    res = result_of(events)
    assert res["subtype"] == "incomplete" and "max_steps" in res["reason"] and res["result"] == "partial"


def test_a_terminal_error_fails_the_turn_with_qoders_sentence_and_a_retrying_one_is_waited_on(tmp_path, stub):
    stub.script = [[RUNNING,
                    {"type": "session.error", "error": {"type": "model_error", "message": "upstream 503", "retry_status": {"type": "retrying"}}},
                    {"type": "session.status_rescheduled"},
                    {"type": "session.error", "error": {"type": "model_error", "message": "model unavailable", "retry_status": {"type": "exhausted"}}},
                    {"type": "session.status_idle", "stop_reason": {"type": "error"}}]]
    lines, _ = run_driver({"cwd": str(tmp_path), "prompt": "x"}, stub)
    events, _ = normalise(lines)
    res = result_of(events)
    assert res["subtype"] == "error" and res["result"] == "model unavailable" and rs._status_from_result(res, 0) == "failed"


def test_a_terminated_session_fails_the_turn(tmp_path, stub):
    stub.script = [[RUNNING, {"type": "session.status_terminated"}]]
    lines, _ = run_driver({"cwd": str(tmp_path), "prompt": "x"}, stub)
    res = result_of(normalise(lines)[0])
    assert res["subtype"] == "error" and "terminated" in res["result"]


def test_the_eof_names_a_driver_that_died_before_its_result():
    state = {"_qoder_notices": ["event stream dropped (TimeoutError); resuming from evt_9"]}
    ev = rs._qoder_eof(state, -9)[0]
    assert ev["type"] == "result" and ev["is_error"] and "may still be running" in ev["result"]
    assert "resuming from evt_9" in ev["result"]


# ── the live stream's shapes ──────────────────────────────────────────────────────────────────────
def test_the_recorded_live_session_maps_field_for_field(tmp_path, monkeypatch):
    """fixtures/qoder/live-session-events.json is the buffered event history of a real two-turn
    session on api.qoder.com (2026-10-09, model `efficient`, ids as Qoder issued them): a Write, a
    DeliverArtifacts, the delivered artifact, the answer, then a second turn after the Agent was
    updated. The driver's handler reads every field the normaliser depends on off these shapes."""
    events = json.loads((pathlib.Path(__file__).parent / "fixtures" / "qoder" / "live-session-events.json").read_text())
    emitted: list[dict] = []
    monkeypatch.setattr(drv, "_emit", lambda m, p: emitted.append({"m": m, "p": p}))
    turn = drv.Turn({"cwd": str(tmp_path), "base_url": "http://127.0.0.1:1", "api_key": "x", "prompt": "p"})
    turn.session_id = "sess_live"
    fetched: list[str] = []
    monkeypatch.setattr(drv.Turn, "artifact", lambda self, doc: fetched.append(doc["file_id"]) or self.declared.append(doc))
    first = [e for e in events[:events.index(next(e for e in events if e["type"] == "session.updated"))]]
    done = False
    for e in first:
        done = turn.handle(e["id"], e["type"], json.dumps(e), "", [True]) or done
    assert done, "the first turn's status_idle ends it"
    kinds = [x["m"] for x in emitted]
    assert kinds.count("tool_use") == 2 and kinds.count("tool_result") == 2 and "text" in kinds
    tools = [x["p"] for x in emitted if x["m"] == "tool_use"]
    assert tools[0]["name"] == "Write" and tools[0]["input"]["file_path"] == "/data/hello.md" and tools[0]["id"].startswith("evt_")
    assert tools[1]["name"] == "DeliverArtifacts" and tools[1]["input"]["files"] == [{"path": "/data/hello.md"}]
    results = [x["p"] for x in emitted if x["m"] == "tool_result"]
    assert results[0]["tool_use_id"] == tools[0]["id"] and "successfully" in results[0]["text"] and results[0]["is_error"] is False
    assert fetched == ["file_00rv4you3vw8wpwq624j"] and turn.declared[0]["original_filename"] == "hello.md" and turn.declared[0]["size"] == 36
    assert turn.final.startswith("Done") and turn.stop_reason == {"type": "end_turn"}
    # the stream's session.usage carried no sandbox charge yet (it settles after idle: GET /sessions
    # read 0.03 and 0.38 seconds later), which is why the driver re-reads the snapshot after idle
    # and the charge says basis: snapshot
    assert turn.usage == {"model_credits": 0.35, "sandbox_runtime_credits": 0, "total_credits": 0.35}
    events_, state = normalise(emitted + [{"m": "__hr_result", "p": {"status": "completed", "final": turn.final, "charge": turn.charge()}}])
    res = result_of(events_)
    assert res["subtype"] == "success" and res["charge"]["amount"] == 0.35 and res["charge"]["unit"] == "qoder_credits"
    assert res["charge"]["basis"] == "snapshot"


def test_each_turn_is_charged_what_it_added_to_the_sessions_running_total(tmp_path, monkeypatch):
    """Qoder's session usage is the session's running total, not the turn's: the recorded live
    session read 0.35 credits after its first turn and 0.61 after its second (model 0.35 + 0.23,
    sandbox 0.03 settled by then). Charging the snapshot as it stands billed the first turn again on
    the second; each turn now carries what it added, and the total beside it."""
    events = json.loads((pathlib.Path(__file__).parent / "fixtures" / "qoder" / "live-session-events.json").read_text())
    cut = events.index(next(e for e in events if e["type"] == "session.updated"))
    monkeypatch.setattr(drv, "_emit", lambda m, p: emitted.append({"m": m, "p": p}))
    monkeypatch.setattr(drv.Turn, "artifact", lambda self, doc: None)
    charges = []
    for part in (events[:cut], events[cut:]):
        emitted: list[dict] = []
        turn = drv.Turn({"cwd": str(tmp_path), "base_url": "http://127.0.0.1:1", "api_key": "x", "prompt": "p"})
        turn.session_id = "sess_live"
        for e in part:
            turn.handle(e["id"], e["type"], json.dumps(e), "", [True])
        turn.result("completed", "")
        charges.append([x["p"]["charge"] for x in emitted if x["m"] == "__hr_result"][0])
    assert [c["amount"] for c in charges] == [0.35, 0.26]
    assert [c["model_credits"] for c in charges] == [0.35, 0.23]
    assert [c["sandbox_runtime_credits"] for c in charges] == [0, 0.03]
    assert [c["session_total"] for c in charges] == [0.35, 0.61]
    # a continuation that lost its session starts a new running total: nothing is subtracted from it
    turn = drv.Turn({"cwd": str(tmp_path), "base_url": "http://127.0.0.1:1", "api_key": "x", "prompt": "p"})
    turn.session_id, turn.usage = "sess_new", {"model_credits": 0.1, "sandbox_runtime_credits": 0, "total_credits": 0.1}
    assert turn.charge()["amount"] == 0.1


def test_a_download_link_that_is_not_a_web_address_lands_nothing(tmp_path, monkeypatch):
    """urllib opens file:, ftp: and data: URLs as readily as https:. The link comes from Qoder's
    answer; one that is not a web address would land a file of this box as the artifact."""
    secret = tmp_path / "secret.txt"
    secret.write_text("not for the workspace")
    turn = drv.Turn({"cwd": str(tmp_path / "ws"), "base_url": "http://127.0.0.1:1", "api_key": "x", "prompt": "p"})
    monkeypatch.setattr(turn.api, "request", lambda *a, **k: {"url": secret.as_uri()})
    got, why = turn._download("file_x", "secret.txt", tmp_path / "ws" / "part")
    assert got is None and "not a web address" in why and not (tmp_path / "ws" / "part").exists()


# ── input files ───────────────────────────────────────────────────────────────────────────────────
def test_input_files_are_uploaded_and_mounted_and_a_binary_one_fails_the_turn_up_front(tmp_path, stub):
    (tmp_path / "spec.md").write_text("# spec")
    stub.script = [[RUNNING, {"type": "agent.message", "content": [{"type": "text", "text": "read"}]}, IDLE]]
    lines, _ = run_driver({"cwd": str(tmp_path), "prompt": "x", "input_files": ["spec.md"]}, stub)
    assert result_of(normalise(lines)[0])["subtype"] == "success"
    up = stub.posted("POST", "/files")
    assert len(up) == 1 and 'filename="spec.md"' in up[0][2]["_multipart"] and "# spec" in up[0][2]["_multipart"]
    sess = stub.posted("POST", "/sessions")[0][2]
    assert sess["resources"] == [{"type": "file", "file_id": "file_" + sess["resources"][0]["file_id"].split("_")[1],
                                  "mount_path": "/mnt/session/uploads/spec.md"}]
    msg = stub.posted("POST", f"/sessions/{sess_id(stub)}/events")[0][2]["events"][0]["content"][0]["text"]
    assert "/mnt/session/uploads/spec.md" in msg and msg.endswith("x")
    # a second turn does not upload the same bytes again
    stub.calls.clear()
    sid = sess_id(stub)
    stub.sessions[sid]["stages"], stub.sessions[sid]["stage"] = [[RUNNING, IDLE]], 0
    run_driver({"cwd": str(tmp_path), "prompt": "y", "input_files": ["spec.md"], "resume_session_id": sid}, stub)
    assert not stub.posted("POST", "/files")
    # a file attached on a LATER turn: the session keeps the Agent version (and the system prompt) it
    # was created with, so the model learns of the file from the message that brought it
    (tmp_path / "notes.txt").write_text("later")
    stub.calls.clear()
    stub.sessions[sid]["stages"], stub.sessions[sid]["stage"] = [[RUNNING, IDLE]], 0
    run_driver({"cwd": str(tmp_path), "prompt": "z", "input_files": ["notes.txt"], "resume_session_id": sid}, stub)
    mounted = [c[2] for c in stub.calls if c[0] == "POST" and c[1] == f"/sessions/{sid}/resources"]
    assert mounted and mounted[0]["mount_path"] == "/mnt/session/uploads/notes.txt"
    msg = stub.posted("POST", f"/sessions/{sid}/events")[0][2]["events"][0]["content"][0]["text"]
    assert "/mnt/session/uploads/notes.txt" in msg and msg.endswith("z")
    # a binary file: refused here, before anything is created, naming the file
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    (fresh / "photo.png").write_bytes(b"\x89PNG")
    stub.calls.clear()
    lines, _ = run_driver({"cwd": str(fresh), "prompt": "x", "input_files": ["photo.png"]}, stub)
    res = result_of(normalise(lines)[0])
    assert res["subtype"] == "error" and "photo.png" in res["result"] and "text-type" in res["result"]
    assert not stub.posted("POST", "/environments")


def sess_id(stub: Stub) -> str:
    return next(iter(stub.sessions))


def test_the_upload_rule_is_qoders():
    assert drv.upload_ok("notes.md", 10) == ""
    assert drv.upload_ok("Makefile", 10) == ""
    assert drv.upload_ok("deck.pptx", 10) and "text-type" in drv.upload_ok("deck.pptx", 10)
    assert "5 MB" in drv.upload_ok("big.txt", 6 * 1024 * 1024)


# ── skills and MCP ────────────────────────────────────────────────────────────────────────────────
def test_skills_are_published_once_by_content_and_a_stdio_server_is_declared_unavailable(tmp_path, stub):
    sk = tmp_path / ".harness" / "skills" / "deck-maker"
    sk.mkdir(parents=True)
    (sk / "SKILL.md").write_text("---\nname: deck-maker\ndescription: makes decks\n---\n# Deck\n")
    (sk / "scripts").mkdir()
    (sk / "scripts" / "run.sh").write_text("echo hi\n")
    bad = tmp_path / ".harness" / "skills" / "Bad Name"
    bad.mkdir()
    (bad / "SKILL.md").write_text("---\nname: Bad Name\ndescription: x\n---\n")
    stub.script = [[RUNNING, {"type": "agent.message", "content": [{"type": "text", "text": "ok"}]}, IDLE]]
    job = {"cwd": str(tmp_path), "prompt": "x",
           "skills": [{"name": "deck-maker", "dir": str(sk)}, {"name": "Bad Name", "dir": str(bad)}],
           "mcp_servers": [{"name": "docs", "url": "https://mcp.example/mcp", "auth": "Bearer s3cret"},
                           {"name": "local", "command": "/x/launch.sh"}]}
    lines, _ = run_driver(job, stub)
    events, _ = normalise(lines)
    assert result_of(events)["subtype"] == "success"
    pub = stub.posted("POST", "/skills")
    assert len(pub) == 1 and 'filename="deck-maker/SKILL.md"' in pub[0][2]["_multipart"] and 'filename="deck-maker/scripts/run.sh"' in pub[0][2]["_multipart"]
    agent = stub.posted("POST", "/agents")[0][2]
    assert agent["skills"] == [{"type": "custom", "skill_id": "skill_" + agent["skills"][0]["skill_id"].split("_")[1], "version": "100"}]
    assert agent["mcp_servers"] == [{"name": "docs", "type": "url", "url": "https://mcp.example/mcp"}]
    # the bearer went into a Vault credential and the session names the vault; the token never in the Agent
    cred = [c for c in stub.calls if c[0] == "POST" and "/credentials" in c[1]][0][2]
    assert cred["auth"] == {"type": "static_bearer", "mcp_server_url": "https://mcp.example/mcp", "token": "s3cret"}
    assert "s3cret" not in json.dumps(agent)
    assert stub.posted("POST", "/sessions")[0][2]["vault_ids"]
    unavailable = [e for e in events if e.get("subtype") == "mcp_unavailable"]
    assert unavailable == [{"type": "system", "subtype": "mcp_unavailable", "servers": [{"name": "local"}]}]
    # the second turn: same bytes, no new skill version; changed bytes, a new version of the same skill
    stub.calls.clear()
    sid = sess_id(stub)
    stub.sessions[sid]["stages"], stub.sessions[sid]["stage"] = [[RUNNING, IDLE]], 0
    run_driver({**job, "prompt": "y", "resume_session_id": sid}, stub)
    assert not stub.posted("POST", "/skills")
    (sk / "SKILL.md").write_text("---\nname: deck-maker\ndescription: makes better decks\n---\n")
    stub.calls.clear()
    stub.sessions[sid]["stages"], stub.sessions[sid]["stage"] = [[RUNNING, IDLE]], 0
    run_driver({**job, "prompt": "z", "resume_session_id": sid}, stub)
    versions = [c for c in stub.calls if c[0] == "POST" and c[1].endswith("/versions")]
    assert len(versions) == 1 and not stub.posted("POST", "/skills")


# ── cancellation: the stop reaches the driver and the remote turn ─────────────────────────────────
def test_sigterm_cancels_the_remote_turn_and_the_record_says_so(tmp_path, stub):
    stub.hang_streams = True
    job = {"base_url": stub.base, "api_key": "placeholder", "model": "ultimate", "cwd": str(tmp_path), "prompt": "long"}
    proc = subprocess.Popen([sys.executable, DRIVER, json.dumps(job)], stdout=subprocess.PIPE, text=True)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and not [c for c in stub.calls if "/events/stream" in c[1]]:
        time.sleep(0.05)
    time.sleep(0.3)
    proc.send_signal(signal.SIGTERM)
    out, _ = proc.communicate(timeout=15)
    lines = [json.loads(ln) for ln in out.splitlines() if ln.startswith("{")]
    sid = sess_id(stub)
    assert stub.sessions[sid].get("cancelled") is True
    notices = [l["p"]["text"] for l in lines if l["m"] == "notice"]
    assert any(f"cancel accepted by Qoder for session {sid}" in n for n in notices)
    res = [l for l in lines if l["m"] == "__hr_result"][-1]["p"]
    assert res["status"] == "cancelled" and sid in res["reason"]
    assert proc.returncode == 0


def test_a_remote_backends_stop_is_a_sigterm_with_a_grace_before_the_kill(tmp_path, monkeypatch):
    """The runner's own path: _stop_proc on a `remote` backend sends SIGTERM first and keeps reading
    stdout through the grace, so the driver's last line is in the record; a local backend is killed
    at once. The child here stands in for the driver: it prints a line on SIGTERM and exits."""
    child = ("import signal, sys, time, json\n"
             "def h(*a):\n"
             "    print(json.dumps({'m': 'notice', 'p': {'text': 'cancel accepted by Qoder for session sess_1'}}), flush=True)\n"
             "    print(json.dumps({'m': '__hr_result', 'p': {'status': 'cancelled', 'reason': 'cancel accepted', 'final': ''}}), flush=True)\n"
             "    sys.exit(0)\n"
             "signal.signal(signal.SIGTERM, h)\n"
             "print(json.dumps({'m': 'session', 'p': {'session_id': 'sess_1'}}), flush=True)\n"
             "time.sleep(30)\n")
    rec = {"status": "running", "events": [], "result": "", "done": False, "started": time.time(),
           "backend": "qoder", "model": "ultimate"}
    monkeypatch.setitem(rs._turns, "tq", rec)
    t = threading.Thread(target=rs._run_turn_bg, args=("tq", [sys.executable, "-c", child], {}, str(tmp_path),
                                                       rs._qoder_to_claude, "ultimate", 60))
    t.start()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not rec.get("proc"):
        time.sleep(0.02)
    while time.monotonic() < deadline and not rec["events"]:
        time.sleep(0.02)
    out = rs.cancel_turn("tq")
    assert out["cancelled"] is True
    t.join(timeout=15)
    assert rec["done"] and rec["status"] == "cancelled"
    res = [e for e in rec["events"] if e.get("type") == "result"]
    assert res and res[-1]["result"] == "cancel accepted", rec["events"]   # the handler's line reached the record
    assert rec["exit_code"] == 0                                            # SIGTERM, handled; not SIGKILL's -9
    # a local backend's stop is the kill it always was
    local = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
    rs._stop_proc(local, {"backend": "claude", "turn_id": ""})
    assert local.wait(timeout=5) == -signal.SIGKILL


# ── the relay route ───────────────────────────────────────────────────────────────────────────────
def test_the_qoder_route_passes_through_and_records_no_served_model(stub):
    stub.script = []
    base, tok = rs._qoder_relay_route(stub.base, "real-pat")
    try:
        assert tok.startswith("hr-relay-") and base.endswith("/v1")
        # create a session through the relay: its object names the configured model
        req = urllib.request.Request(base + "/sessions", data=json.dumps({"agent": {"id": "agent_x"}, "environment_id": "env_x"}).encode(),
                                     method="POST", headers={"authorization": f"Bearer {tok}", "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            doc = json.loads(r.read())
        assert doc["agent"]["model"] == {"id": "ultimate"}
        req = urllib.request.Request(base + f"/sessions/{doc['id']}", headers={"authorization": f"Bearer {tok}"})
        with urllib.request.urlopen(req, timeout=10) as r:
            assert b'"model"' in r.read()
        assert rs._relay_served_model({"QODER_API_KEY": tok}) == ""          # the tap is off on this route
        assert rs._relay_usage({"QODER_API_KEY": tok}) == {} and rs._relay_last_finish({"QODER_API_KEY": tok}) == ""
        # the stub saw the real credential; the client only ever held the placeholder
        assert "real-pat" in stub.token_seen and tok not in stub.token_seen
        # DELETE goes up
        req = urllib.request.Request(base + f"/sessions/{doc['id']}", method="DELETE", headers={"authorization": f"Bearer {tok}"})
        with urllib.request.urlopen(req, timeout=10) as r:
            assert json.loads(r.read())["type"] == "session_deleted"
        assert [c for c in stub.calls if c[0] == "DELETE"]
        # a 4xx comes down as the API wrote it
        req = urllib.request.Request(base + "/sessions/sess_nope", headers={"authorization": f"Bearer {tok}"})
        try:
            urllib.request.urlopen(req, timeout=10)
            assert False, "a 404 must come through"
        except urllib.error.HTTPError as e:
            assert e.code == 404 and json.loads(e.read())["error"]["type"] == "not_found_error"
    finally:
        rs._HERMES_RELAY["routes"].pop(tok, None)


def test_a_stalled_passthrough_stream_is_closed_not_narrated(monkeypatch):
    """A long remote tool step can be silent past the relay's wait. On a model route the relay
    writes an error event into the stream; on this one the connection simply closes, so the
    driver resumes from its last event id instead of reading an error the API never sent."""
    class H(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):  # noqa: D102
            pass

        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("transfer-encoding", "chunked")
            self.end_headers()
            raw = b'id: evt_1\nevent: agent.message\ndata: {"type":"agent.message","id":"evt_1","content":[]}\n\n'
            self.wfile.write(f"{len(raw):x}\r\n".encode() + raw + b"\r\n")
            self.wfile.flush()
            time.sleep(3)
            try:
                self.wfile.write(b"0\r\n\r\n")
            except OSError:
                pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(rs, "HR_RELAY_UPSTREAM_TIMEOUT_S", 1.0)
    base, tok = rs._qoder_relay_route(f"http://127.0.0.1:{srv.server_address[1]}", "k")
    try:
        req = urllib.request.Request(base + "/sessions/s/events/stream", headers={"authorization": f"Bearer {tok}"})
        got = b""
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                while True:
                    chunk = r.read1(4096)
                    if not chunk:
                        break
                    got += chunk
        except (http.client.HTTPException, OSError):
            pass        # the close is the point
        assert b"evt_1" in got
        assert b"upstream_unavailable" not in got and b"error" not in got.lower().replace(b"agent.message", b"")
    finally:
        rs._HERMES_RELAY["routes"].pop(tok, None)
        srv.shutdown()


# ── the builder ───────────────────────────────────────────────────────────────────────────────────
def test_the_builder_hands_the_driver_the_relay_and_a_placeholder_never_the_key(tmp_path):
    env: dict = {}
    auth = rs.Auth(api_key="pat-secret")
    cmd = rs._build_qoder("qoder", auth, "ultimate", "hi", str(tmp_path), env, resume_session_id="sess_9",
                          tools_disabled=["Bash"], agent_doc="Rules.", input_files=["a.md"],
                          skills=[{"name": "s", "dir": "/x/s"}])
    tok = None
    try:
        assert cmd[0] == rs.QODER_PYTHON and cmd[1] == rs.QODER_DRIVER
        job = json.loads(cmd[2])
        tok = job["api_key"]
        assert tok.startswith("hr-relay-") and "pat-secret" not in cmd[2] and "pat-secret" not in json.dumps(env)
        assert job["base_url"].startswith("http://127.0.0.1:") and job["base_url"].endswith("/v1")
        assert rs._HERMES_RELAY["routes"][tok][0] == rs.QODER_DEFAULT_BASE and rs._HERMES_RELAY["routes"][tok][1] == "pat-secret"
        assert rs._HERMES_RELAY["routes"][tok][2].get("passthrough") is True
        assert job["resume_session_id"] == "sess_9" and job["tools_disabled"] == ["Bash"] and job["agent_doc"] == "Rules."
        assert job["input_files"] == ["a.md"] and job["skills"] == [{"name": "s", "dir": "/x/s"}]
        assert env["QODER_API_KEY"] == tok
    finally:
        if tok:
            rs._HERMES_RELAY["routes"].pop(tok, None)
    with pytest.raises(rs.HTTPException):
        rs._build_qoder("qoder", rs.Auth(), "ultimate", "hi", str(tmp_path), {})        # no PAT
    with pytest.raises(rs.HTTPException):
        rs._build_qoder("openai", auth, "ultimate", "hi", str(tmp_path), {})           # not a provider of this base


def test_the_registration_points():
    assert rs.BACKENDS["qoder"]["remote"] is True and rs.BACKENDS["qoder"]["normalize"] is rs._qoder_to_claude
    assert rs.BACKENDS["qoder"]["providers"] == ["qoder"]
    assert rs.QODER_TOOLS == drv.TOOLS
    assert rs.QODER_EFFORTS == drv.EFFORTS
    assert rs._SESSION_PRESENT.get("qoder") is None     # the driver itself reports a lost session
    assert not any(b.get("remote") for k, b in rs.BACKENDS.items() if k != "qoder")


def test_no_agent_doc_is_written_and_skills_are_staged_under_harness(tmp_path):
    rs._write_agent_doc(str(tmp_path), "qoder", "Rules.", [])
    assert not list(tmp_path.iterdir()), "this backend reads no workspace file"
    installed = rs._write_skills(str(tmp_path), [{"name": "deck", "files": [{"path": "SKILL.md", "content": "---\nname: deck\ndescription: d\n---\n"}]}], "qoder")
    assert installed and installed[0]["entry"].startswith(".harness/skills/deck/")
    assert (tmp_path / ".harness" / "skills" / "deck" / "SKILL.md").is_file()


# ── the purge ─────────────────────────────────────────────────────────────────────────────────────
def write_state(ws: pathlib.Path, **extra) -> dict:
    st = {"environment_id": "env_1", "agent_id": "agent_1", "agent_version": 2, "session_id": "sess_1",
          "sessions": ["sess_1"], "vault_id": "vault_1", "skills": {"deck": {"id": "skill_1", "sha": "x", "version": "1"}},
          "files": {"spec.md": {"id": "file_in", "sha": "y", "mounted": ["sess_1"]}}, "artifacts": ["file_art"], **extra}
    (ws / ".harness" / "qoder").mkdir(parents=True, exist_ok=True)
    (ws / ".harness" / "qoder" / "state.json").write_text(json.dumps(st))
    return st


def test_the_purge_reaches_every_recorded_id_and_reports_what_it_could_not(tmp_path, stub):
    stub.sessions["sess_1"] = {"id": "sess_1", "status": "idle", "archived_at": None, "stages": [], "stage": 0, "events": [], "resources": []}
    stub.agents["agent_1"] = {"id": "agent_1", "version": 2}
    write_state(tmp_path)
    lines, proc = run_driver({"purge": True, "cwd": str(tmp_path)}, stub)
    assert proc.returncode == 0
    report = [l for l in lines if l["m"] == "purge"][-1]["p"]
    assert report["failed"] == []
    seen = [(c[0], c[1]) for c in stub.calls]
    for want in (("POST", "/sessions/sess_1/cancel"), ("DELETE", "/sessions/sess_1"), ("DELETE", "/files/file_art"),
                 ("DELETE", "/files/file_in"), ("POST", "/agents/agent_1/archive"), ("DELETE", "/vaults/vault_1"),
                 ("DELETE", "/skills/skill_1"), ("DELETE", "/environments/env_1")):
        assert want in seen, want
    assert seen.index(("DELETE", "/sessions/sess_1")) < seen.index(("DELETE", "/files/file_in"))   # the session first
    # an environment still referenced is archived, as the API says to
    stub.calls.clear()
    stub.env_delete_409 = True
    lines, proc = run_driver({"purge": True, "cwd": str(tmp_path)}, stub)
    assert ("POST", "/environments/env_1/archive") in [(c[0], c[1]) for c in stub.calls]
    assert [l for l in lines if l["m"] == "purge"][-1]["p"]["failed"] == []
    # an object already gone is not a failure; a delete the API refuses is reported with its id,
    # and the exit says so
    stub.env_delete_409 = False
    stub.sessions.pop("sess_1")
    stub.agents.pop("agent_1")
    stub.fail_deletes = True
    stub.calls.clear()
    lines, proc = run_driver({"purge": True, "cwd": str(tmp_path)}, stub)
    report = [l for l in lines if l["m"] == "purge"][-1]["p"]
    assert proc.returncode == 1 and report["failed"]
    assert any(f["what"] == "delete vault vault_1" and "500" in f["error"] for f in report["failed"]), report
    assert "delete session sess_1 (already gone)" in report["done"]


def test_delete_workspace_purges_at_qoder_with_the_connection_it_is_sent(tmp_path, stub, monkeypatch):
    import asyncio
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(rs, "WORKSPACE_ROOT", str(root))
    monkeypatch.setattr(rs, "_SANDBOX_PER_SESSION", False)
    sid = "hsessqoder0123456789abcdef0123456789"
    ws = pathlib.Path(rs._ws(sid))
    ws.mkdir(parents=True)
    stub.sessions["sess_1"] = {"id": "sess_1", "status": "idle", "archived_at": None, "stages": [], "stage": 0, "events": [], "resources": []}
    stub.agents["agent_1"] = {"id": "agent_1", "version": 2}
    write_state(ws)
    out = asyncio.run(rs.delete_workspace(sid, rs.WorkspaceDelete(auth=rs.Auth(api_key="real-pat", base_url=stub.base))))
    assert out["removed"] is True and out["remote"]["purged"] is True and not ws.exists()
    assert ("DELETE", "/sessions/sess_1") in [(c[0], c[1]) for c in stub.calls]
    assert "real-pat" in stub.token_seen            # through the relay: the credential stayed in the runner
    # without a credential the folder still goes, and the answer says what was left at Qoder
    ws.mkdir(parents=True)
    write_state(ws)
    out = asyncio.run(rs.delete_workspace(sid))
    assert out["removed"] is True and out["remote"] == {"backend": "qoder", "purged": False, "reason": "no credential",
                                                         "state": rs.QODER_STATE_REL}
    # a session with no remote state answers as before
    ws.mkdir(parents=True)
    out = asyncio.run(rs.delete_workspace(sid))
    assert out["removed"] is True and "remote" not in out


# ── review fixes (2026-10-09) ─────────────────────────────────────────────────────────────────────
def test_a_changed_mcp_token_replaces_the_vault_credential_and_no_token_is_kept(tmp_path, stub):
    """The gateway mints a per-turn credential for a server it hosts, and keys rotate: a vault that
    kept the first turn's token failed that server on every later turn. An unchanged token is not
    sent again; a changed one archives the old credential and creates the new one."""
    stub.script = [[RUNNING, IDLE]]
    job = {"cwd": str(tmp_path), "prompt": "x",
           "mcp_servers": [{"name": "db", "url": "https://hr.example/v1/mcp/database", "auth": "tok-1"}]}
    run_driver(job, stub)
    sid = sess_id(stub)
    vid = stub.posted("POST", "/sessions")[0][2]["vault_ids"][0]

    def again(token):
        stub.calls.clear()
        stub.sessions[sid]["stages"], stub.sessions[sid]["stage"] = [[RUNNING, IDLE]], 0
        lines, _ = run_driver({**job, "prompt": "y", "resume_session_id": sid,
                               "mcp_servers": [{**job["mcp_servers"][0], "auth": token}]}, stub)
        return result_of(normalise(lines)[0])

    assert again("tok-1")["subtype"] == "success"
    assert not [c for c in stub.calls if "/credentials" in c[1]]            # same token: nothing sent
    assert again("tok-2")["subtype"] == "success"
    active = [c for c in stub.vault_creds[vid] if not c.get("archived_at")]
    assert [c["token"] for c in active] == ["tok-2"] and len(stub.vault_creds[vid]) == 2
    state = (tmp_path / ".harness" / "qoder" / "state.json").read_text()
    assert "tok-1" not in state and "tok-2" not in state                      # a hash, never the token


def test_an_active_credential_the_state_does_not_know_is_archived_and_made_anew(tmp_path, stub):
    stub.script = [[RUNNING, IDLE]]
    job = {"cwd": str(tmp_path), "prompt": "x", "mcp_servers": [{"name": "docs", "url": "https://mcp.example/mcp", "auth": "a"}]}
    run_driver(job, stub)
    sid = sess_id(stub)
    st_path = tmp_path / ".harness" / "qoder" / "state.json"
    st = json.loads(st_path.read_text())
    st.pop("vault_creds")                     # e.g. a driver killed between the create and the save
    st_path.write_text(json.dumps(st))
    stub.sessions[sid]["stages"], stub.sessions[sid]["stage"] = [[RUNNING, IDLE]], 0
    lines, _ = run_driver({**job, "prompt": "y", "resume_session_id": sid,
                           "mcp_servers": [{**job["mcp_servers"][0], "auth": "b"}]}, stub)
    assert result_of(normalise(lines)[0])["subtype"] == "success"
    vid = st["vault_id"]
    assert [c["token"] for c in stub.vault_creds[vid] if not c.get("archived_at")] == ["b"]


def test_a_model_route_does_not_forward_delete(stub):
    """DELETE through the relay is a remote runtime's alone: a sandbox must not delete what an org's
    provider key owns (files, fine-tunes) through the relay that holds the key."""
    base, tok = rs._hermes_relay_route(stub.base + "/v1", "sk-real")
    try:
        req = urllib.request.Request(base + "/files/file_1", method="DELETE", headers={"authorization": f"Bearer {tok}"})
        try:
            urllib.request.urlopen(req, timeout=10)
            assert False, "a DELETE on a model route must be refused"
        except urllib.error.HTTPError as e:
            assert e.code == 405
        assert not [c for c in stub.calls if c[0] == "DELETE"]
    finally:
        rs._HERMES_RELAY["routes"].pop(tok, None)


def test_an_artifact_over_the_limit_or_unwritable_fails_with_its_reason(tmp_path, stub, monkeypatch):
    monkeypatch.setenv("HR_QODER_ARTIFACT_MAX_BYTES", "8")
    stub.blobs["file_big"] = b"0123456789"
    stub.blobs["file_ok"] = b"tiny"
    stub.script = [[RUNNING,
                    {"type": "agent.artifact_delivered", "file_id": "file_big", "original_filename": "big.bin", "size": 10},
                    {"type": "agent.artifact_delivered", "file_id": "file_ok", "original_filename": "ok.txt", "size": 4},
                    IDLE]]
    lines, _ = run_driver({"cwd": str(tmp_path), "prompt": "x"}, stub)
    res = result_of(normalise(lines)[0])
    assert res["subtype"] == "incomplete" and "big.bin" in res["reason"] and "limit" in res["reason"]
    assert (tmp_path / "ok.txt").read_bytes() == b"tiny" and not (tmp_path / "big.bin").exists()
    assert not list((tmp_path / ".harness" / "qoder").glob("*.part"))       # no download left behind
    # a workspace the file cannot be written to: that artifact fails with the reason; the turn goes on
    monkeypatch.delenv("HR_QODER_ARTIFACT_MAX_BYTES")
    ro = tmp_path / "ro"
    (ro / ".harness" / "qoder").mkdir(parents=True)
    ro.chmod(0o555)
    try:
        stub.script = [[RUNNING, {"type": "agent.artifact_delivered", "file_id": "file_ok", "original_filename": "ok.txt", "size": 4},
                        {"type": "agent.message", "content": [{"type": "text", "text": "done"}]}, IDLE]]
        lines, _ = run_driver({"cwd": str(ro), "prompt": "x"}, stub)
        res = result_of(normalise(lines)[0])
        assert res["subtype"] == "incomplete" and "could not be written" in res["reason"], res
        assert not [ln for ln in lines if ln.get("m") == "notice" and "dropped" in str(ln.get("p"))]
    finally:
        ro.chmod(0o755)


def test_a_long_artifact_name_is_cut_by_bytes_keeping_its_extension():
    name, why = drv.artifact_name("é" * 200 + ".pdf")
    assert not why and name.endswith(".pdf") and len(name.encode("utf-8")) <= 240
