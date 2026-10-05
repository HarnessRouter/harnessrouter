"""Hermes's startup guard stops a turn that is hung, not one whose first answer is long.

hermes writes a message into its database only when the message is complete. A first answer that
streams for longer than the guard's limit therefore looked exactly like a provider call that never
answered, and was stopped mid-stream: on the hosted service, 2026-10-05, gpt-6-luna and gpt-5.4 asked
to write an 18,000 word file as their first step were both stopped at 90 s, and completed after 293 s
and 676 s of the same silence when a tool call came first. The relay sees that call's events as they
pass, so the guard also asks when a provider last sent one.
"""
import http.client
import http.server
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as rs  # noqa: E402

LIMIT = rs._HERMES_STARTUP_TIMEOUT_S


def test_a_first_answer_that_is_still_arriving_is_not_a_hung_call():
    now = 10_000.0
    started = now - LIMIT - 200                     # well past the limit, nothing written yet
    assert rs._hermes_startup_hung(False, started, last_data=now - 2, now=now) is False     # events 2 s ago
    assert rs._hermes_startup_hung(False, started, last_data=now - LIMIT - 1, now=now) is True
    # the case the guard was written for: the provider answered at once, then the CLI hung
    assert rs._hermes_startup_hung(False, started, last_data=started + 2.2, now=now) is True
    # no route at all (the calls do not pass the relay): the guard is what it was
    assert rs._hermes_startup_hung(False, started, last_data=0.0, now=now) is True
    assert rs._hermes_startup_hung(False, now - LIMIT + 5, last_data=0.0, now=now) is False
    assert rs._hermes_startup_hung(True, started, last_data=0.0, now=now) is False          # it has produced


def test_the_last_event_is_read_off_the_turns_own_routes():
    assert rs._routes_last_data({}) == 0.0 and rs._routes_last_data({"routes": [{}]}) == 0.0
    assert rs._routes_last_data({"routes": [{"last_data": 5.0}, {"last_data": 9.5}, {}]}) == 9.5


def test_the_relay_notes_each_event_of_a_stream_on_the_route():
    class Up(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["content-length"]))
            self.send_response(200); self.send_header("content-type", "text/event-stream"); self.end_headers()
            for chunk in (b': keep-alive\n\n', b'data: {"choices":[{"delta":{"content":"a"}}]}\n\n',
                          b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n', b'data: [DONE]\n\n'):
                self.wfile.write(chunk); self.wfile.flush()

        def log_message(self, *a):
            pass

    up = http.server.HTTPServer(("127.0.0.1", 0), Up)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    token = rs._TURN_THINKING.set({"asked": "", "applied": "", "routes": []})
    try:
        relay, tok = rs._hermes_relay_route(f"http://127.0.0.1:{up.server_port}/v1", "sk-real")
        routes = rs._TURN_THINKING.get()["routes"]
    finally:
        rs._TURN_THINKING.reset(token)
    conn = http.client.HTTPConnection(relay.removeprefix("http://").removesuffix("/v1"), timeout=10)
    try:
        before = time.time()
        conn.request("POST", "/v1/chat/completions", body=json.dumps({"model": "m", "stream": True, "messages": []}),
                     headers={"authorization": f"Bearer {tok}", "content-type": "application/json"})
        conn.getresponse().read()
        assert rs._routes_last_data({"routes": routes}) >= before
    finally:
        conn.close(); up.shutdown(); rs._HERMES_RELAY["routes"].pop(tok, None)
