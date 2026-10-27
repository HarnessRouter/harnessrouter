"""A Gemini thought signature (and OpenRouter's encrypted reasoning) goes back only to the model that made it
(2026-10-27). A fast-agent deck conversation moved from gemini-4-argon to gemini-3.6-flash, 3.5-flash, 3.5-flash-lite
and 3.1-pro-preview on the hosted service, and Google refused each with 400 "Corrupted thought signature.": the
harness keeps argon's signatures in its own history. The relay keeps which model made each call it saw a signature
for, beside the per-turn routes, and sends another model's as Google's sentinel."""
import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402

SKIP = server._GOOGLE_SIG_SKIP


@pytest.fixture(autouse=True)
def makers(monkeypatch):
    monkeypatch.setattr(server, "_SIG_MAKERS", {})
    return server._SIG_MAKERS


def _replay(model: str) -> bytes:
    return json.dumps({"model": model, "messages": [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c_argon", "type": "function", "function": {"name": "f", "arguments": "{}"},
             "extra_content": {"google": {"thought_signature": "sigArgon"}}},     # the harness kept it
            {"id": "c_flash", "type": "function", "function": {"name": "f", "arguments": "{}"}},
            {"id": "c_unseen", "type": "function", "function": {"name": "f", "arguments": "{}"},
             "extra_content": {"google": {"thought_signature": "own"}}}]}]}).encode()


def _sigs_of(body: bytes) -> list:
    return [(tc.get("extra_content") or {}).get("google", {}).get("thought_signature")
            for tc in json.loads(body)["messages"][1]["tool_calls"]]


def test_another_gemini_models_signatures_go_as_the_sentinel_on_a_switch():
    server._sig_makers_keep(["c_argon"], "gemini-4-argon")
    # the maker is the id the client asked for; the same model with or without a vendor prefix is the same
    server._sig_makers_keep(["c_flash"], "google/gemini-3.6-flash")
    sigs = {"c_argon": "sigArgon", "c_flash": "sigFlash"}
    assert _sigs_of(server._google_with_signatures(_replay("gemini-3.6-flash"), sigs)) == [SKIP, "sigFlash", "own"]
    assert _sigs_of(server._google_with_signatures(_replay("google/gemini-4-argon"), sigs)) == ["sigArgon", SKIP, "own"]


def test_a_route_not_known_as_googles_only_changes_what_the_harness_carried():
    server._sig_makers_keep(["c_argon"], "gemini-4-argon")
    out = server._google_with_signatures(_replay("google/gemini-3.6-flash"), {}, fill=False)
    assert _sigs_of(out) == [SKIP, None, "own"]                   # nothing added where nothing was carried
    same = _replay("google/gemini-4-argon")
    assert server._google_with_signatures(same, {}, fill=False) is same


def test_after_a_corrupted_refusal_a_signature_of_unknown_origin_goes_as_the_sentinel():
    server._sig_makers_keep(["c_flash"], "gemini-3.6-flash")
    out = server._google_with_signatures(_replay("gemini-3.6-flash"), {"c_flash": "sigFlash"}, distrust=True)
    assert _sigs_of(out) == [SKIP, "sigFlash", SKIP]              # its own call keeps its signature


def test_another_models_encrypted_reasoning_is_not_put_back():
    rd = {"type": "reasoning.encrypted", "data": "x", "id": "c1", "format": "google-gemini-v1"}
    server._sig_makers_keep(["c1"], "google/gemini-4-argon")
    body = lambda m: json.dumps({"model": m, "messages": [{"role": "assistant", "content": None, "tool_calls": [  # noqa: E731
        {"id": "c1", "type": "function", "function": {"name": "f", "arguments": "{}"}}]}]}).encode()
    same = json.loads(server._with_encrypted_reasoning(body("google/gemini-4-argon"), {"c1": rd}))
    assert same["messages"][0]["reasoning_details"] == [rd]
    other = server._with_encrypted_reasoning(body("google/gemini-3.6-flash"), {"c1": rd})
    assert "reasoning_details" not in json.loads(other)["messages"][0]


def test_the_record_is_bounded():
    for i in range(server._SIG_MAKERS_MAX + 5):
        server._sig_makers_keep([f"c{i}"], "m")
    assert len(server._SIG_MAKERS) == server._SIG_MAKERS_MAX and "c0" not in server._SIG_MAKERS


# ── through the relay: one turn per route, as the runner gives each turn its own ──────────────────────────

@pytest.fixture
def google_like():
    """An upstream that answers argon with a signed tool call, and refuses a request whose replay carries a
    signature another model made, as Google did on 10-27."""
    got: list[bytes] = []
    made = {"sigArgon": "gemini-4-argon"}

    class Upstream(BaseHTTPRequestHandler):
        def do_POST(self):
            raw = self.rfile.read(int(self.headers["content-length"]))
            got.append(raw)
            doc = json.loads(raw)
            carried = [((tc.get("extra_content") or {}).get("google") or {}).get("thought_signature")
                       for m in doc["messages"] if m.get("role") == "assistant" for tc in m.get("tool_calls") or []]
            if any(s and s != SKIP and made.get(s, "unknown") != doc["model"] for s in carried):
                code, out = 400, json.dumps({"error": {"code": 400, "message": "Corrupted thought signature.",
                                                       "status": "INVALID_ARGUMENT"}}).encode()
            elif doc["model"] == "gemini-4-argon" and len(doc["messages"]) == 1:
                code, out = 200, json.dumps({"object": "chat.completion", "model": doc["model"], "choices": [
                    {"index": 0, "finish_reason": "tool_calls", "message": {"role": "assistant", "content": None, "tool_calls": [
                        {"id": "c_argon", "type": "function", "function": {"name": "f", "arguments": "{}"},
                         "extra_content": {"google": {"thought_signature": "sigArgon"}}}]}}]}).encode()
            else:
                code, out = 200, json.dumps({"object": "chat.completion", "model": doc["model"], "choices": [
                    {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "DONE"}}]}).encode()
            self.send_response(code)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    up = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=up.serve_forever, daemon=True).start()

    def turn(body: dict) -> int:
        base, tok = server._hermes_relay_route(f"http://127.0.0.1:{up.server_address[1]}/v1", "sk-key")
        req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(), method="POST",
                                     headers={"authorization": f"Bearer {tok}", "content-type": "application/json"})
        try:
            return urllib.request.urlopen(req, timeout=10).status
        except urllib.error.HTTPError as e:
            return e.code
    yield turn, got
    up.shutdown()


ASK = {"role": "user", "content": "make the deck"}
ARGON_CALL = {"role": "assistant", "content": None, "tool_calls": [
    {"id": "c_argon", "type": "function", "function": {"name": "f", "arguments": "{}"},
     "extra_content": {"google": {"thought_signature": "sigArgon"}}}]}
RESULT = {"role": "tool", "tool_call_id": "c_argon", "content": "ok"}


def test_a_switch_in_the_next_turn_sends_the_sentinel_for_the_first_models_call(google_like):
    turn, got = google_like
    assert turn({"model": "gemini-4-argon", "messages": [ASK]}) == 200            # argon's turn signs c_argon
    assert server._SIG_MAKERS.get("c_argon") == "gemini-4-argon"
    # the next turn, its own route, on flash: the harness replays argon's call with argon's signature
    assert turn({"model": "gemini-3.6-flash", "messages": [ASK, ARGON_CALL, RESULT]}) == 200
    assert len(got) == 2 and _sigs_of(got[1]) == [SKIP]                          # fitted before it went
    # back on argon, its own signature goes back
    assert turn({"model": "gemini-4-argon", "messages": [ASK, ARGON_CALL, RESULT]}) == 200
    assert _sigs_of(got[2]) == ["sigArgon"]


def test_a_runner_that_never_saw_the_call_learns_from_the_refusal(google_like, makers):
    turn, got = google_like
    makers.clear()                                                                 # a runner started since
    assert turn({"model": "gemini-3.6-flash", "messages": [ASK, ARGON_CALL, RESULT]}) == 200
    assert len(got) == 2 and _sigs_of(got[0]) == ["sigArgon"] and _sigs_of(got[1]) == [SKIP]
