"""The realtime driver: one text turn on a realtime speech model, through the Realtime Harness.

What these pin:

  the events are claude's stream-json: init, the answer as assistant text, one tool_use and one
      tool_result per tool call, a result with the usage and the model
  the driver never holds the key: it posts the placeholder to the mint, and opens the model's
      socket with the secret the mint answered, which is the only credential the provider sees
  the served model is the one the provider's own session.created names, and is absent when it
      names none; the usage is the provider's, fresh input apart from cached, and empty when it
      reports none
  a session is a file in the workspace: a second turn replays the first to a new connection
  a disabled tool is never offered; a stdio server and an unreachable one are named in
      system/mcp_unavailable and the turn still runs
  a turn over its step budget ends error_max_turns, and the call it never answered is not kept
  a mint the provider refuses is a failed turn whose message carries no credential

They run on the Realtime Harness's own package (a venv of its own in the image: its MCP SDK is a
major version ahead of the runner's), against a scripted provider on the OpenAI realtime wire,
so no key is needed. This file imports nothing of the runner's but the driver.
"""
import asyncio
import http.server
import json
import os
import pathlib
import socket
import subprocess
import sys
import threading
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

pytest.importorskip("realtime_harness", reason="the Realtime Harness is installed on a venv of its own, not here")
websockets = pytest.importorskip("websockets")

import realtime_driver as drv  # noqa: E402
from realtime_harness.credentials import Connection  # noqa: E402
from realtime_harness.textturn import TurnResult  # noqa: E402

# Whether the installed Realtime Harness says which model ran a turn (TurnResult.model, its pull
# request 1). The image pins a commit, and on one before that change a turn names no model at all,
# which is the rule either way: what the provider said, or nothing, never the id that was asked for.
NAMES_MODEL = "model" in TurnResult.__dataclass_fields__

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "realtime" / "mcp_weather.py"
PLACEHOLDER = "hr-relay-00000000-test"
SECRET = "ek_test_session_secret"
USAGE = {"total_tokens": 130, "input_tokens": 100, "output_tokens": 30,
         "input_token_details": {"text_tokens": 100, "cached_tokens": 40}, "output_token_details": {"text_tokens": 30}}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeRealtime:
    """The OpenAI realtime wire, as much of it as a text turn uses, answering from a script.

    Each `response.create` takes the next entry: ("say", text) or ("call", tool, arguments), or a
    function of the connection's state that returns one. With the script used up it says "Hello."
    Every connection's state is kept: the headers it opened with, the instructions and tools it
    was given, and the items it was handed, in order."""

    def __init__(self, script=None, model="gpt-realtime-2.1-2026-07-07", usage=USAGE):
        self.script, self.model, self.usage = list(script or []), model, usage
        self.sessions: list[dict] = []
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._main, daemon=True)

    def __enter__(self):
        self._thread.start()
        assert self._ready.wait(10), "the scripted provider did not start"
        return self

    def __exit__(self, *exc):
        self._loop.call_soon_threadsafe(self._stop.set)
        self._thread.join(10)

    def _main(self):
        asyncio.set_event_loop(self._loop)
        self._stop = asyncio.Event()

        async def serve():
            async with websockets.serve(self._serve, "127.0.0.1", 0) as srv:
                self.url = f"ws://127.0.0.1:{srv.sockets[0].getsockname()[1]}/openai/v1/realtime"
                self._ready.set()
                await self._stop.wait()
        self._loop.run_until_complete(serve())

    async def _serve(self, ws):
        s = {"headers": dict(ws.request.headers), "items": [], "tools": [], "instructions": "", "modalities": None}
        self.sessions.append(s)

        async def send(ev):
            await ws.send(json.dumps(ev))

        await send({"type": "session.created", "session": {"type": "realtime", "id": "sess_1",
                                                           **({"model": self.model} if self.model else {})}})
        try:
            async for raw in ws:
                m = json.loads(raw)
                t = m.get("type")
                if t == "session.update":
                    sess = m.get("session") or {}
                    s["instructions"] = sess.get("instructions") or ""
                    s["tools"] = [x.get("name") for x in sess.get("tools") or []]
                    s["modalities"] = sess.get("output_modalities")
                    await send({"type": "session.updated", "session": {"type": "realtime"}})
                elif t == "conversation.item.create":
                    s["items"].append(m["item"])
                elif t == "response.create":
                    step = self.script.pop(0) if self.script else ("say", "Hello.")
                    if callable(step):
                        step = step(s)
                    if step[0] == "call":
                        await self._call(send, step[1], step[2])
                    else:
                        await self._say(send, step[1])
        except websockets.ConnectionClosed:
            return

    def _done(self, rid, item):
        return {"type": "response.done", "response": {"id": rid, "status": "completed", "output": [item],
                                                      **({"usage": self.usage} if self.usage else {})}}

    async def _say(self, send, text):
        await send({"type": "response.created", "response": {"id": "resp_1", "status": "in_progress"}})
        item = {"id": "item_m", "type": "message", "role": "assistant", "status": "in_progress", "content": []}
        await send({"type": "response.output_item.added", "response_id": "resp_1", "output_index": 0, "item": item})
        words = text.split(" ")
        for delta in [words[0]] + [" " + w for w in words[1:]]:        # the deltas add up to the text exactly
            await send({"type": "response.output_text.delta", "response_id": "resp_1", "item_id": "item_m",
                        "output_index": 0, "content_index": 0, "delta": delta})
        done = {**item, "status": "completed", "content": [{"type": "output_text", "text": text}]}
        await send({"type": "response.output_item.done", "response_id": "resp_1", "output_index": 0, "item": done})
        await send(self._done("resp_1", done))

    async def _call(self, send, name, args):
        self._n = getattr(self, "_n", 0) + 1
        iid, cid = f"item_c{self._n}", f"call_{self._n}"
        await send({"type": "response.created", "response": {"id": "resp_c", "status": "in_progress"}})
        item = {"id": iid, "type": "function_call", "status": "in_progress", "call_id": cid, "name": name, "arguments": ""}
        await send({"type": "response.output_item.added", "response_id": "resp_c", "output_index": 0, "item": item})
        arguments = json.dumps(args)
        await send({"type": "response.function_call_arguments.done", "response_id": "resp_c", "item_id": iid,
                    "output_index": 0, "call_id": cid, "arguments": arguments})
        done = {**item, "status": "completed", "arguments": arguments}
        await send({"type": "response.output_item.done", "response_id": "resp_c", "output_index": 0, "item": done})
        await send(self._done("resp_c", done))


class Mint:
    """The provider's client-secret endpoint, as the relay forwards to it: it knows one bearer."""

    def __init__(self, status=200):
        self.status, self.requests = status, []
        mint = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
                mint.requests.append({"path": self.path, "auth": self.headers.get("authorization"), "body": body})
                if mint.status != 200 or self.headers.get("authorization") != f"Bearer {PLACEHOLDER}":
                    # a provider's refusal quotes what it was sent: the driver must not repeat it
                    out, code = {"error": {"code": "invalid_api_key",
                                           "message": f"Incorrect key provided: {self.headers.get('authorization')}"}}, 401
                else:
                    out, code = {"value": SECRET, "expires_at": int(time.time()) + 120,
                                 "session": {"type": "realtime", "model": body.get("session", {}).get("model")}}, 200
                raw = json.dumps(out).encode()
                self.send_response(code)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *a):
                pass
        self._srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self._srv.server_address[1]}/openai/v1/realtime/client_secrets"
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()

    def close(self):
        self._srv.shutdown()


@pytest.fixture(scope="module")
def mcp_url():
    port = free_port()
    proc = subprocess.Popen([sys.executable, str(FIXTURE), str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 20
    while time.time() < deadline:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                break
        time.sleep(0.1)
    else:
        proc.kill()
        pytest.skip("the test tool server did not start")
    yield f"http://127.0.0.1:{port}/mcp"
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture
def mint():
    m = Mint()
    yield m
    m.close()


def turn(tmp_path, fake, mint, **job):
    """One turn through the driver's own path (the mint, then the socket), and every event it emitted."""
    events: list[dict] = []
    base = {"cwd": str(tmp_path), "model": "gpt-realtime-2-1", "prompt": "Say hello.", "provider": "azure-foundry",
            "mint_url": mint.url, "api_key": PLACEHOLDER, "ws_url": fake.url + "?model=gpt-realtime-2-1"}
    result = drv.run_turn({**base, **job}, emit=events.append)
    return events, result


def kinds(events):
    out = []
    for e in events:
        if e["type"] in ("assistant", "user"):
            out += [c["type"] for c in e["message"]["content"]]
        else:
            out.append(e["type"] if e["type"] != "system" else f"system/{e['subtype']}")
    return out


# ── the events, and what the provider saw ──
def test_a_turn_is_claudes_stream_json_with_the_providers_usage_and_model(tmp_path, mint):
    with FakeRealtime([("say", "Hello there.")]) as fake:
        events, result = turn(tmp_path, fake, mint, agent_doc="Be brief.")
    assert kinds(events) == ["system/init", "text", "result"]
    assert events[0]["session_id"].startswith("rt_") and events[0]["model"] == "gpt-realtime-2-1"
    assert events[1]["message"]["content"][0]["text"] == "Hello there."
    assert result["subtype"] == "success" and result["is_error"] is False and result["result"] == "Hello there."
    assert result["session_id"] == events[0]["session_id"]
    # the provider's own name for what it ran, not the deployment that was asked for
    if NAMES_MODEL:
        assert result["model"] == "gpt-realtime-2.1-2026-07-07"
    else:
        assert "model" not in result
    # input is fresh input only: the provider's 100 includes the 40 it read from its cache
    assert result["usage"] == {"input_tokens": 60, "output_tokens": 30, "cache_read_input_tokens": 40}
    s = fake.sessions[0]
    assert s["instructions"] == "Be brief." and s["modalities"] == ["text"]
    assert s["items"][-1] == {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Say hello."}]}


def test_the_key_never_comes_here_the_mint_gets_the_placeholder_and_the_socket_the_secret(tmp_path, mint):
    with FakeRealtime() as fake:
        turn(tmp_path, fake, mint)
    assert len(mint.requests) == 1
    req = mint.requests[0]
    assert req["path"] == "/openai/v1/realtime/client_secrets" and req["auth"] == f"Bearer {PLACEHOLDER}"
    # the mint fixes the model and nothing of the harness: instructions and tools go on the connection
    assert req["body"]["session"] == {"type": "realtime", "model": "gpt-realtime-2-1"}
    assert req["body"]["expires_after"] == {"anchor": "created_at", "seconds": drv.SECRET_TTL_S}
    headers = {k.lower(): v for k, v in fake.sessions[0]["headers"].items()}
    assert headers["authorization"] == f"Bearer {SECRET}"
    assert PLACEHOLDER not in json.dumps(headers)


def test_a_provider_that_names_no_model_and_no_usage_gets_neither_made_up(tmp_path, mint):
    with FakeRealtime(model="", usage=None) as fake:
        _events, result = turn(tmp_path, fake, mint)
    assert "model" not in result and result["usage"] == {} and result["subtype"] == "success"


def test_text_deltas_are_stream_events_only_when_the_turn_asked_for_them(tmp_path, mint):
    with FakeRealtime([("say", "one two three")]) as fake:
        quiet, _ = turn(tmp_path, fake, mint)
    with FakeRealtime([("say", "one two three")]) as fake:
        loud, _ = turn(tmp_path, fake, mint, partial=True)
    assert not [e for e in quiet if e["type"] == "stream_event"]
    deltas = [e["event"]["delta"]["text"] for e in loud if e["type"] == "stream_event"]
    assert deltas == ["one", " two", " three"]
    assert all(e["event"] == {"type": "content_block_delta", "delta": {"type": "text_delta", "text": d}}
               for e, d in zip([e for e in loud if e["type"] == "stream_event"], deltas))
    # the whole answer still follows, for the passthrough to keep the non-text blocks of
    assert [e for e in loud if e["type"] == "assistant"][-1]["message"]["content"][0]["text"] == "one two three"


# ── the session is a file ──
def test_a_second_turn_replays_the_first_to_a_new_connection_from_the_workspace(tmp_path, mint):
    with FakeRealtime([("say", "Paris is clear.")]) as fake:
        _e, first = turn(tmp_path, fake, mint, prompt="What is the weather in Paris?")
    sid = first["session_id"]
    stored = json.loads((tmp_path / ".harness" / "realtime" / sid / "items.json").read_text(encoding="utf-8"))
    assert [(i["type"], i.get("role")) for i in stored] == [("message", "user"), ("message", "assistant")]

    def which(s):          # answers from what the connection was handed, so the test sees whether it arrived
        said = " ".join(p.get("text", "") for it in s["items"][:-1] for p in it.get("content") or [])
        return ("say", "You asked about Paris." if "Paris" in said else "I do not know.")

    with FakeRealtime([which]) as fake:
        events, second = turn(tmp_path, fake, mint, prompt="Which city did I ask about?", resume_session_id=sid)
        handed = fake.sessions[0]["items"]
    assert second["result"] == "You asked about Paris." and second["session_id"] == sid == events[0]["session_id"]
    assert [(i["type"], i["role"]) for i in handed] == [("message", "user"), ("message", "assistant"), ("message", "user")]
    assert handed[1]["content"] == [{"type": "output_text", "text": "Paris is clear."}]
    assert len(json.loads((tmp_path / ".harness" / "realtime" / sid / "items.json").read_text(encoding="utf-8"))) == 4


def test_a_session_whose_file_is_gone_starts_from_nothing_under_the_same_id(tmp_path, mint):
    with FakeRealtime() as fake:
        events, result = turn(tmp_path, fake, mint, resume_session_id="rt_0123456789abcdef")
        assert len(fake.sessions[0]["items"]) == 1          # only this turn's question: nothing to replay
    assert result["session_id"] == "rt_0123456789abcdef" and result["subtype"] == "success"


def test_a_session_id_that_is_not_one_is_not_used_as_a_path(tmp_path, mint):
    with FakeRealtime() as fake:
        _events, result = turn(tmp_path, fake, mint, resume_session_id="../../etc")
    assert result["session_id"].startswith("rt_") and not (tmp_path.parent / "etc").exists()
    assert [p.name for p in (tmp_path / ".harness" / "realtime").iterdir()] == [result["session_id"]]


# ── tools ──
def test_a_tool_call_is_run_answered_and_shown_with_its_server(tmp_path, mint, mcp_url):
    script = [("call", "weather", {"city": "Paris"}),
              lambda s: ("say", "Paris is clear, 18 degrees." if "celsius" in s["items"][-1].get("output", "") else "No answer.")]
    with FakeRealtime(script) as fake:
        events, result = turn(tmp_path, fake, mint, prompt="Weather in Paris?",
                              mcp_servers=[{"name": "weather desk", "url": mcp_url, "auth": "tok"}])
        offered, handed = fake.sessions[0]["tools"], fake.sessions[0]["items"]
    assert kinds(events) == ["system/init", "tool_use", "tool_result", "text", "result"]
    use = events[1]["message"]["content"][0]
    assert use["name"] == "mcp__weather_desk__weather" and use["input"] == {"city": "Paris"}
    res = events[2]["message"]["content"][0]
    assert res["tool_use_id"] == use["id"] and res["is_error"] is False and '"celsius": 18' in res["content"]
    assert result["result"] == "Paris is clear, 18 degrees."
    assert "weather" in offered and "step" in offered
    assert [i["type"] for i in handed] == ["message", "function_call_output"]
    # two model responses in one turn: the usage is their sum
    assert result["usage"] == {"input_tokens": 120, "output_tokens": 60, "cache_read_input_tokens": 80}
    kept = json.loads((tmp_path / ".harness" / "realtime" / result["session_id"] / "items.json").read_text(encoding="utf-8"))
    assert [i["type"] for i in kept] == ["message", "function_call", "function_call_output", "message"]


def test_a_disabled_tool_is_not_offered_and_a_call_to_it_is_refused_not_run(tmp_path, mint, mcp_url):
    script = [("call", "delete_account", {"user": "ada"}), ("say", "I cannot do that.")]
    with FakeRealtime(script) as fake:
        events, result = turn(tmp_path, fake, mint, mcp_servers=[{"name": "desk", "url": mcp_url}],
                              tools_disabled=["delete_account"])
        offered = fake.sessions[0]["tools"]
    assert "delete_account" not in offered and "weather" in offered
    res = next(c for e in events if e["type"] == "user" for c in e["message"]["content"])
    assert res["is_error"] is True and "refused" in res["content"] and "disabled" in res["content"]
    assert result["subtype"] == "success"


def test_a_stdio_server_and_an_unreachable_one_are_named_and_the_turn_still_runs(tmp_path, mint, mcp_url):
    with FakeRealtime() as fake:
        events, result = turn(tmp_path, fake, mint, mcp_servers=[
            {"name": "local", "command": "node", "args": ["server.js"]},
            {"name": "gone", "url": f"http://127.0.0.1:{free_port()}/mcp"},
            {"name": "desk", "url": mcp_url}])
        offered = fake.sessions[0]["tools"]
    down = [e["servers"] for e in events if e["type"] == "system" and e["subtype"] == "mcp_unavailable"]
    assert down == [[{"name": "local"}], [{"name": "gone"}]]
    assert "weather" in offered and result["subtype"] == "success"


def test_a_turn_over_its_step_budget_ends_error_max_turns_and_keeps_no_unanswered_call(tmp_path, mint, mcp_url):
    script = [("call", "step", {"n": 1}), ("call", "step", {"n": 2}), ("say", "DONE")]
    with FakeRealtime(script) as fake:
        events, result = turn(tmp_path, fake, mint, mcp_servers=[{"name": "desk", "url": mcp_url}], max_turns=1)
    assert result["subtype"] == "error_max_turns" and result["is_error"] is False and result["reason"] == "max_steps"
    assert [c["name"] for e in events if e["type"] == "assistant" for c in e["message"]["content"]
            if c["type"] == "tool_use"] == ["mcp__desk__step"]
    kept = json.loads((tmp_path / ".harness" / "realtime" / result["session_id"] / "items.json").read_text(encoding="utf-8"))
    # the call the budget cut off was never answered, and a replayed call with no answer stalls a provider
    assert [i["type"] for i in kept] == ["message"]


# ── failures ──
def test_a_refused_mint_is_a_failed_turn_whose_message_carries_no_credential(tmp_path):
    m = Mint(status=401)
    try:
        with FakeRealtime() as fake:
            events, result = turn(tmp_path, fake, m)
            assert fake.sessions == []                      # no socket was opened on a refusal
    finally:
        m.close()
    assert result["subtype"] == "error" and result["is_error"] is True and result["reason"] == "provider"
    assert "HTTP 401" in result["result"] and "invalid_api_key" in result["result"]
    assert PLACEHOLDER not in json.dumps(events) and "Incorrect key" not in json.dumps(events)


def test_a_provider_that_cannot_be_reached_is_a_failed_turn_not_a_crash(tmp_path, mint):
    events: list[dict] = []
    result = drv.run_turn({"cwd": str(tmp_path), "model": "gpt-realtime-2-1", "prompt": "hi", "mint_url": mint.url,
                           "api_key": PLACEHOLDER, "ws_url": f"ws://127.0.0.1:{free_port()}/openai/v1/realtime"},
                          emit=events.append)
    assert result["subtype"] == "error" and result["is_error"] is True
    assert "could not be reached" in result["result"] and SECRET not in json.dumps(events)


# ── the process ──
def test_the_job_comes_from_the_environment_and_is_removed_from_it(tmp_path, mint, monkeypatch, capsys):
    with FakeRealtime([("say", "ok")]) as fake:
        monkeypatch.setenv("HR_DRIVER_JOB", json.dumps({
            "cwd": str(tmp_path), "model": "gpt-realtime-2-1", "prompt": "Reply ok.", "mint_url": mint.url,
            "api_key": PLACEHOLDER, "ws_url": fake.url}))
        assert drv.main([]) == 0
    assert "HR_DRIVER_JOB" not in os.environ
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    assert [e["type"] for e in lines] == ["system", "assistant", "result"] and lines[-1]["result"] == "ok"


def test_an_injected_connection_skips_the_mint(tmp_path):
    with FakeRealtime() as fake:
        events: list[dict] = []
        result = drv.run_turn({"cwd": str(tmp_path), "model": "m", "prompt": "hi"}, emit=events.append,
                              connect=lambda model: Connection(url=fake.url, headers={}, model=model, ref={}))
    assert result["subtype"] == "success" and result["result"] == "Hello."
