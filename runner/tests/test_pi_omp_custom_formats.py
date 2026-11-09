"""pi and omp on a custom connection, by the format the connection declares (#640).

Both CLIs take a provider's `api` from the config the runner writes (pi 1.5.0: ~/.pi/agent/models.json;
omp 18.1.13: <agent dir>/models.yml), and both list `openai-responses` among the values it takes (pi's
docs/models-configuration.md, omp's docs/models.md "Allowed provider/model `api` values"). Each
posts a Responses call to `<baseUrl>/responses` (pi through the OpenAI SDK's `responses.create`,
omp as `${baseUrl}/responses`).

What these tests hold:
  - a custom connection's declared format decides the API, whatever the model id would suggest, so a
    Responses connection gets `openai-responses` and a Chat one keeps `openai-completions`, even for
    an id of the family the runner would otherwise send to Responses;
  - the config the CLI reads holds the loopback relay and a placeholder, never the connection's key;
  - what the CLI sends to the relay reaches the connection's own URL, joined exactly, with the key
    the route holds, and the placeholder goes no further.
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

CFG = {"pi": ".pi/agent/models.json", "omp": ".omp/agent/models.yml"}


def _build(base: str, tmp_path, fmt: str, model: str, key: str = "sk-conn-SENTINEL",
           url: str = "https://gw.example/api/llm"):
    """One build as a custom connection reaches the runner: the gateway wires a custom connection to
    pi and omp as the runner's `tokenrouter` provider, with the connection's api_format beside it."""
    home = tmp_path / f"{base}-{fmt}"
    home.mkdir()
    env = {"HOME": str(home)}
    builder = rs._build_pi if base == "pi" else rs._build_omp
    cmd = builder("tokenrouter", rs.Auth(api_key=key, base_url=url, api_format=fmt), model, "do it",
                  str(home), env)
    text = (home / CFG[base]).read_text()
    return cmd, env, text, json.loads(text)["providers"]["hr"]


@pytest.mark.parametrize("base", ["pi", "omp"])
@pytest.mark.parametrize("fmt,model,api", [
    # the Responses format, on ids of every family: the format decides, not the id
    ("responses", "gpt-6.1-sol", "openai-responses"),
    ("responses", "vendor-model", "openai-responses"),
    ("responses", "claude-sonnet-4.6", "openai-responses"),
    # Chat connections are unchanged: an id of the Responses family stays on Chat Completions when the
    # connection says so, which is what a Chat-only endpoint needs
    ("openai", "gpt-6.1-sol", "openai-completions"),
    ("openai", "vendor-model", "openai-completions"),
    ("anthropic", "claude-sonnet-4.6", "anthropic-messages"),
    ("anthropic", "vendor-model", "anthropic-messages"),
])
def test_the_declared_format_decides_the_api(tmp_path, base, fmt, model, api):
    _cmd, _env, _text, hr = _build(base, tmp_path, fmt, model)
    try:
        assert hr["api"] == api
        assert [m["id"] for m in hr["models"]] == [model]
    finally:
        rs._HERMES_RELAY["routes"].pop(hr["apiKey"], None)


@pytest.mark.parametrize("base", ["pi", "omp"])
def test_a_responses_connection_writes_the_relay_and_a_placeholder(tmp_path, base):
    cmd, env, text, hr = _build(base, tmp_path, "responses", "gpt-6.1-sol")
    try:
        assert hr["api"] == "openai-responses"
        # the relay's own /v1 base, which the CLI joins /responses onto
        assert hr["baseUrl"].startswith("http://127.0.0.1:") and hr["baseUrl"].endswith("/v1")
        assert hr["apiKey"].startswith("hr-relay-")
        # the key is in none of what the CLI is given: its config, its environment, its arguments
        assert "sk-conn-SENTINEL" not in text
        assert "sk-conn-SENTINEL" not in json.dumps(env)
        assert "sk-conn-SENTINEL" not in json.dumps(cmd)
        assert "gw.example" not in text
        # the route holds the connection's own base, exactly as stored (no /v1 added to a base that
        # names no version), and its key
        assert rs._HERMES_RELAY["routes"][hr["apiKey"]][:2] == ("https://gw.example/api/llm", "sk-conn-SENTINEL")
        if base == "omp":
            # omp reads models.yml; models.json beside it is the same document
            home = tmp_path / f"{base}-responses"
            assert (home / ".omp/agent/models.json").read_text() == text
            assert cmd[cmd.index("--model") + 1] == "hr/gpt-6.1-sol"
        else:
            assert cmd[cmd.index("--provider") + 1] == "hr"
    finally:
        rs._HERMES_RELAY["routes"].pop(hr["apiKey"], None)


class _Upstream(http.server.BaseHTTPRequestHandler):
    seen: list = []

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("content-length") or 0))
        type(self).seen.append({"path": self.path, "auth": self.headers.get("authorization"),
                                "x-api-key": self.headers.get("x-api-key"), "body": body})
        out = b'{"id":"resp_1","object":"response","model":"m","status":"completed","output":[]}'
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


@pytest.mark.parametrize("base", ["pi", "omp"])
@pytest.mark.parametrize("fmt,resource", [("responses", "/responses"), ("openai", "/chat/completions")])
def test_what_the_cli_sends_reaches_the_connection_with_its_key(tmp_path, base, fmt, resource):
    """The request as the CLI makes it: its config's baseUrl plus the API's resource, with its
    config's apiKey as the bearer. The connection's base names no version, and the route adds none;
    the key is added at the relay, and the placeholder stops there."""
    _Upstream.seen = []
    up = http.server.HTTPServer(("127.0.0.1", 0), _Upstream)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    _cmd, _env, _text, hr = _build(base, tmp_path, fmt, "gpt-6.1-sol",
                                   url=f"http://127.0.0.1:{up.server_port}/api/llm/")
    relay = hr["baseUrl"]
    host, path = relay.removeprefix("http://").split("/", 1)
    conn = http.client.HTTPConnection(host, timeout=10)
    body = ({"model": "gpt-6.1-sol", "input": [{"role": "user", "content": "hi"}], "stream": False,
             "store": False} if fmt == "responses" else
            {"model": "gpt-6.1-sol", "messages": [{"role": "user", "content": "hi"}], "stream": False})
    try:
        conn.request("POST", f"/{path}{resource}", body=json.dumps(body),
                     headers={"authorization": f"Bearer {hr['apiKey']}", "content-type": "application/json"})
        resp = conn.getresponse()
        resp.read()
        assert resp.status == 200
        assert len(_Upstream.seen) == 1
        got = _Upstream.seen[0]
        assert got["path"] == "/api/llm" + resource
        assert got["auth"] == "Bearer sk-conn-SENTINEL"
        assert hr["apiKey"].encode() not in got["body"] and hr["apiKey"] not in str(got["x-api-key"])
        if fmt == "responses":
            sent = json.loads(got["body"])
            assert sent["input"] == body["input"] and sent["store"] is False
    finally:
        conn.close()
        up.shutdown()
        rs._HERMES_RELAY["routes"].pop(hr["apiKey"], None)
