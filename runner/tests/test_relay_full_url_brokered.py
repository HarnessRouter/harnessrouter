"""A connection whose address is the full request URL reaches a turn brokered (the gateway's
_auth_from_conn), and the broker sends each call to that address (its _conn_request_url, tested in
gateway/tests/test_full_url_connection.py against exactly the paths below).

The runner's half: on the broker's base, a base's model call goes through the relay to
<broker>/<the format's resource>, joined exactly, with the broker's per-turn credential and nothing
else, whether or not the turn's auth still names `full_url` (a gateway before this one sent it beside
the broker's base). The runner never applies it, so the address is applied once, by the broker.
"""
import http.client
import http.server
import json
import pathlib
import sys
import threading

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server as rs  # noqa: E402

BROKER_CRED = "hrt.brokered-turn-credential"


class _Broker(http.server.BaseHTTPRequestHandler):
    seen: list = []

    def do_POST(self):  # noqa: N802
        self.rfile.read(int(self.headers.get("content-length") or 0))
        type(self).seen.append({"path": self.path, "auth": self.headers.get("authorization")})
        out = b'{"id":"x","object":"response","status":"completed","output":[]}'
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


@pytest.fixture
def broker():
    _Broker.seen = []
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Broker)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/v1/llm"
    srv.shutdown()


def _post(relay_base: str, token: str, resource: str) -> int:
    host, path = relay_base.removeprefix("http://").split("/", 1)
    conn = http.client.HTTPConnection(host, timeout=10)
    try:
        conn.request("POST", f"/{path}{resource}", body=json.dumps({"model": "m"}),
                     headers={"authorization": f"Bearer {token}", "content-type": "application/json"})
        r = conn.getresponse()
        r.read()
        return r.status
    finally:
        conn.close()


@pytest.mark.parametrize("full_url", ["", "1"])
@pytest.mark.parametrize("fmt,resource,lands", [
    ("openai", "/chat/completions", "/v1/llm/chat/completions"),
    ("responses", "/responses", "/v1/llm/responses"),
    # pi's anthropic client appends /v1/messages to a base stripped of its /v1 (_pi_relayed)
    ("anthropic", "/messages", "/v1/llm/v1/messages"),
])
def test_pi_on_a_brokered_turn_calls_the_broker_at_its_formats_resource(tmp_path, broker, full_url, fmt, resource,
                                                                      lands):
    home = tmp_path / "home"
    home.mkdir()
    rs._build_pi("tokenrouter", rs.Auth(api_key=BROKER_CRED, base_url=broker, api_format=fmt, full_url=full_url),
                 "m", "do it", str(tmp_path), {"HOME": str(home)})
    hr = json.loads((home / ".pi/agent/models.json").read_text())["providers"]["hr"]
    try:
        # the CLI's base and the resource its client appends to it (pi's anthropic base has no /v1)
        relay_base = hr["baseUrl"] if fmt != "anthropic" else hr["baseUrl"] + "/v1"
        assert _post(relay_base, hr["apiKey"], resource) == 200
        assert _Broker.seen == [{"path": lands, "auth": f"Bearer {BROKER_CRED}"}]
    finally:
        rs._HERMES_RELAY["routes"].pop(hr["apiKey"], None)


@pytest.mark.parametrize("full_url", ["", "1"])
def test_codex_on_a_brokered_turn_calls_the_broker_at_responses(tmp_path, broker, full_url):
    home = tmp_path / "home"
    home.mkdir()
    env = {"HOME": str(home)}
    cfg_dir = rs._codex_prepare_env("tokenrouter", rs.Auth(api_key=BROKER_CRED, base_url=broker,
                                                           api_format="responses", full_url=full_url),
                                    "m", str(tmp_path), env)
    cfg = (cfg_dir / "config.toml").read_text()
    tok = env["ROUTER_API_KEY"]
    try:
        relay_base = cfg.split('base_url = "', 1)[1].split('"', 1)[0]
        assert BROKER_CRED not in cfg and BROKER_CRED not in json.dumps(env)
        assert _post(relay_base, tok, "/responses") == 200     # Codex joins /responses onto its base
        assert _Broker.seen == [{"path": "/v1/llm/responses", "auth": f"Bearer {BROKER_CRED}"}]
    finally:
        rs._HERMES_RELAY["routes"].pop(tok, None)
