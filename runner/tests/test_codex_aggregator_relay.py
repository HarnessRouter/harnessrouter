"""Codex on an aggregator's connection rides the relay.

Codex groups a server's MCP tools in a namespace and adds an empty `properties` to each object node
of their schemas. Measured 2026-10-05 through a self-hosted instance, an MCP tool that reports what
it received, Codex with gpt-6-luna, two runs per connection:

    TokenRouter   OpenAI   Azure    OpenRouter   Vercel
    intact        intact   intact   intact       [{}], [{}, {}]

and the same on Vercel with gpt-6.1-sol. (gpt-5.4, gpt-5.4-mini, gpt-5.5, gpt-5.6-sol and gpt-6-astra
passed there; for gpt-5.4 Codex was seen to defer its tool definitions behind a tool search, and the
other four are assumed alike.) The repair lives in the relay, and Codex was the one base that never
passed through it: it was handed the connection's base and key.
"""
import http.client
import http.server
import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as rs  # noqa: E402


def _prepare(tmp_path, provider, auth, **kw):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {"HOME": str(home)}
    cfg_dir = rs._codex_prepare_env(provider, auth, "gpt-6-luna", str(tmp_path), env, **kw)
    return env, (cfg_dir / "config.toml").read_text()


def test_an_aggregator_connection_gets_a_route_and_the_key_stays_out_of_the_cli(tmp_path):
    env, cfg = _prepare(tmp_path, "tokenrouter",
                        rs.Auth(api_key="sk-agg-real", base_url="https://ai-gateway.example/v1"))
    tok = env["ROUTER_API_KEY"]
    try:
        assert tok.startswith("hr-relay-")
        assert "sk-agg-real" not in json.dumps(env) and "sk-agg-real" not in cfg
        assert "ai-gateway.example" not in cfg and 'base_url = "http://127.0.0.1:' in cfg
        upstream, key, _flags = rs._HERMES_RELAY["routes"][tok]
        assert upstream == "https://ai-gateway.example/v1" and key == "sk-agg-real"
    finally:
        rs._HERMES_RELAY["routes"].pop(tok, None)


def test_the_route_keeps_the_connection_base_exactly(tmp_path):
    """Codex called `<base>/responses` whatever the base looked like. A route that added a version
    segment, as other bases' routes do, would move a custom endpoint that has none."""
    env, _cfg = _prepare(tmp_path, "tokenrouter",
                         rs.Auth(api_key="k", base_url="https://llm.example/api/openai/", api_format="responses"))
    tok = env["ROUTER_API_KEY"]
    try:
        assert rs._HERMES_RELAY["routes"][tok][0] == "https://llm.example/api/openai"
    finally:
        rs._HERMES_RELAY["routes"].pop(tok, None)


def test_openai_and_azure_keep_their_direct_route(tmp_path):
    for provider, var, base in (("openai", "OPENAI_API_KEY", "https://api.openai.com/v1"),
                                ("azure", "AZURE_OPENAI_API_KEY", "https://res.openai.azure.com/openai/v1")):
        env, cfg = _prepare(tmp_path, provider, rs.Auth(api_key="sk-direct", base_url=base))
        assert env[var] == "sk-direct"
        assert f'base_url = "{base}"' in cfg and "127.0.0.1" not in cfg


def test_the_account_fingerprint_follows_the_connection_not_the_route(tmp_path):
    """A route is new on every turn. Were it part of the fingerprint, every resume would look like a
    change of account and the session's history would be replayed as content each time."""
    auth = rs.Auth(api_key="sk-agg-real", base_url="https://ai-gateway.example/v1")
    first, _ = _prepare(tmp_path, "tokenrouter", auth)
    second, _ = _prepare(tmp_path, "tokenrouter", auth)
    other, _ = _prepare(tmp_path, "tokenrouter", rs.Auth(api_key="sk-another", base_url="https://ai-gateway.example/v1"))
    try:
        assert first["ROUTER_API_KEY"] != second["ROUTER_API_KEY"]
        assert second["HR_CODEX_ACCOUNT_CHANGED"] == "0"
        assert other["HR_CODEX_ACCOUNT_CHANGED"] == "1"
    finally:
        for env in (first, second, other):
            rs._HERMES_RELAY["routes"].pop(env["ROUTER_API_KEY"], None)


def test_a_resumed_session_declares_its_earlier_provider_ids_at_the_route(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "_codex_session_provider_ids", lambda cfg_dir: ["hr-azure", "hr-tokenrouter"])
    env, cfg = _prepare(tmp_path, "tokenrouter",
                        rs.Auth(api_key="sk-agg-real", base_url="https://ai-gateway.example/v1"), resume=True)
    try:
        assert "[model_providers.hr-azure]" in cfg
        assert cfg.count('base_url = "http://127.0.0.1:') == 2 and "ai-gateway.example" not in cfg
    finally:
        rs._HERMES_RELAY["routes"].pop(env["ROUTER_API_KEY"], None)


def test_what_codex_sends_reaches_the_provider_at_the_same_url_with_the_objects_free_form(tmp_path):
    seen = {}

    class Up(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            seen["path"] = self.path
            seen["auth"] = self.headers.get("authorization")
            seen["body"] = json.loads(self.rfile.read(int(self.headers["content-length"])))
            out = b'{"id":"resp_1","object":"response","model":"m","status":"completed","output":[]}'
            self.send_response(200); self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(out))); self.end_headers(); self.wfile.write(out)

        def log_message(self, *a):
            pass

    up = http.server.HTTPServer(("127.0.0.1", 0), Up)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    # a base with no version segment: the route must not add one
    env, cfg = _prepare(tmp_path, "tokenrouter",
                        rs.Auth(api_key="sk-agg-real", base_url=f"http://127.0.0.1:{up.server_port}/api/llm"))
    tok = env["ROUTER_API_KEY"]
    relay = cfg.split('base_url = "', 1)[1].split('"', 1)[0]
    conn = http.client.HTTPConnection(relay.removeprefix("http://").split("/", 1)[0], timeout=10)
    try:
        # the request as Codex 0.154.0 builds it for a model it does not defer tools for
        conn.request("POST", "/" + relay.split("/", 3)[3] + "/responses",      # /v1/responses, as Codex joins it
                     body=json.dumps({"model": "openai/gpt-6-luna", "input": [], "stream": False, "tools": [
                         {"type": "namespace", "name": "mcp__probe", "description": "probe", "tools": [
                             {"type": "function", "name": "probe_rows", "strict": False, "parameters": {
                                 "type": "object", "properties": {"rows": {"type": "array", "items": {
                                     "type": "object", "properties": {}}}}, "required": ["rows"]}}]}]}),
                     headers={"authorization": f"Bearer {tok}", "content-type": "application/json"})
        resp = conn.getresponse(); resp.read()
        assert resp.status == 200
        assert seen["path"] == "/api/llm/responses" and seen["auth"] == "Bearer sk-agg-real"
        fn = seen["body"]["tools"][0]["tools"][0]
        assert fn["parameters"]["properties"]["rows"]["items"] == {"type": "object"}
        assert fn["parameters"]["required"] == ["rows"] and fn["strict"] is False
    finally:
        conn.close(); up.shutdown(); rs._HERMES_RELAY["routes"].pop(tok, None)
