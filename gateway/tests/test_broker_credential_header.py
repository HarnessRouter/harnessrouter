"""The broker presents a connection's stored key in the one header its API reads, and in no other.

Anthropic's Messages API reads `x-api-key`; an OpenAI-shape API (chat/completions, responses) reads
`Authorization: Bearer`. Anthropic's own connection was already sent x-api-key alone. A custom
connection declared in the Anthropic format was sent a Bearer, which an Anthropic-compatible endpoint
that reads only x-api-key refuses (seen through the real claude binary on 0.41.3-rc.2). It now takes
the built-in provider's path. Never both: the caller's own credential headers (the relay's per-turn
credential, as Bearer and as x-api-key) are dropped first, and a connection's request headers, which
come after the key, may not name either.
"""
import asyncio
import http.server
import json
import sys
import threading
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402

KEY = "stored-key-SENTINEL"


class _Upstream(http.server.BaseHTTPRequestHandler):
    seen: list = []

    def do_POST(self):  # noqa: N802
        self.rfile.read(int(self.headers.get("content-length") or 0))
        _Upstream.seen.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()},
                               "raw": [(k.lower(), v) for k, v in self.headers.items()]})
        out = b'{"id":"x","type":"message","content":[]}'
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


@pytest.fixture
def upstream():
    _Upstream.seen = []
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Upstream)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _broker(monkeypatch, conn, path, client_headers=None):
    """One POST through /v1/llm/<path> on a turn credential for `conn`, carrying the credential the way the
    runner's relay sends it on a Messages call (Bearer AND x-api-key), plus `client_headers`."""
    monkeypatch.setattr(gw, "INTERNAL_KEY", "k-test-internal-key")

    async def resolve(name, org):
        return gw._with_provider_base(dict(conn))

    async def vertex_get(sid):
        return {}
    monkeypatch.setattr(gw, "_broker_resolve", resolve)
    monkeypatch.setattr(gw, "_vertex_get", vertex_get)
    monkeypatch.setattr(gw, "_relay_client", lambda: httpx.AsyncClient(timeout=10.0))
    cred = gw._mint_turn_cred("hsess-hdr", "integration:Proxy", "")

    async def run():
        transport = httpx.ASGITransport(app=gw.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://gw.test") as c:
            return await c.post(path, headers={"authorization": f"Bearer {cred}", "x-api-key": cred,
                                               **(client_headers or {})},
                                json={"model": "m", "max_tokens": 8, "messages": [{"role": "user", "content": "hi"}]})
    r = asyncio.run(run())
    assert r.status_code == 200, r.text
    assert len(_Upstream.seen) == 1
    got = _Upstream.seen[0]
    # the per-turn credential stops at the broker, in any header
    assert cred not in json.dumps(got["raw"])
    return got


def _custom(upstream, fmt, full, **extra):
    base = upstream + ("/gw/route/invoke" if full else "/gw/anthropic/v1")
    return {"name": "integration:Proxy", "provider": "custom", "api_key": KEY, "base_url": base,
            "api_format": fmt, "full_url": "1" if full else "", **extra}


def _one(got, name):
    return [v for k, v in got["raw"] if k == name]


# ── the Anthropic format: x-api-key, and only that ─────────────────────────────────────────────

@pytest.mark.parametrize("full", [True, False])
def test_a_custom_anthropic_connection_sends_the_key_as_x_api_key_alone(monkeypatch, upstream, full):
    got = _broker(monkeypatch, _custom(upstream, "anthropic", full), "/v1/llm/v1/messages?beta=true",
                  {"anthropic-version": "2023-06-01", "anthropic-beta": "fine-grained-tool-streaming-2025-05-14"})
    assert got["path"] == ("/gw/route/invoke?beta=true" if full else "/gw/anthropic/v1/messages?beta=true")
    assert _one(got, "x-api-key") == [KEY]
    assert "authorization" not in got["headers"]
    # the CLI's own Anthropic headers pass as they always did
    assert got["headers"]["anthropic-version"] == "2023-06-01"
    assert got["headers"]["anthropic-beta"] == "fine-grained-tool-streaming-2025-05-14"


def test_anthropics_own_connection_is_unchanged_and_is_the_same_rule(monkeypatch, upstream):
    conn = {"name": "integration:Anthropic", "provider": "anthropic", "api_key": KEY, "base_url": upstream + "/v1"}
    got = _broker(monkeypatch, conn, "/v1/llm/v1/messages", {"anthropic-version": "2023-06-01"})
    assert got["path"] == "/v1/messages"
    assert _one(got, "x-api-key") == [KEY] and "authorization" not in got["headers"]


# ── the OpenAI formats: Bearer, and only that ──────────────────────────────────────────────────

@pytest.mark.parametrize("full", [True, False])
@pytest.mark.parametrize("fmt,path,lands", [
    ("openai", "/v1/llm/v1/chat/completions", "/chat/completions"),
    ("responses", "/v1/llm/v1/responses", "/responses"),
])
def test_the_openai_formats_send_the_key_as_a_bearer_alone(monkeypatch, upstream, full, fmt, path, lands):
    conn = {**_custom(upstream, fmt, full), "base_url": upstream + ("/gw/route/invoke" if full else "/gw/v1")}
    got = _broker(monkeypatch, conn, path)
    assert got["path"] == ("/gw/route/invoke" if full else "/gw/v1" + lands)
    assert _one(got, "authorization") == [f"Bearer {KEY}"]
    assert "x-api-key" not in got["headers"]


def test_a_custom_connection_with_no_format_keeps_the_bearer(monkeypatch, upstream):
    """A custom connection stored before formats were required is the OpenAI format (the save path's default)."""
    conn = {"name": "integration:Proxy", "provider": "custom", "api_key": KEY, "base_url": upstream + "/gw/v1"}
    got = _broker(monkeypatch, conn, "/v1/llm/v1/chat/completions")
    assert _one(got, "authorization") == [f"Bearer {KEY}"] and "x-api-key" not in got["headers"]


# ── the connection's own headers come after the key and cannot add the other one ───────────────

@pytest.mark.parametrize("fmt,path,header,other", [
    ("anthropic", "/v1/llm/v1/messages", "x-api-key", "authorization"),
    ("openai", "/v1/llm/v1/chat/completions", "authorization", "x-api-key"),
])
def test_connection_headers_still_come_after_the_key(monkeypatch, upstream, fmt, path, header, other):
    conn = _custom(upstream, fmt, False, headers={"X-Project": "p1", "cf-aig-authorization": "Bearer cf-tok",
                                                  "Authorization": "Bearer attacker", "X-Api-Key": "attacker"})
    got = _broker(monkeypatch, conn, path)
    names = [k for k, _ in got["raw"]]
    assert _one(got, header) == ([KEY] if header == "x-api-key" else [f"Bearer {KEY}"])
    assert other not in got["headers"]
    assert "attacker" not in json.dumps(got["raw"])
    assert got["headers"]["x-project"] == "p1" and got["headers"]["cf-aig-authorization"] == "Bearer cf-tok"
    assert names.index("x-project") > names.index(header)


# ── owner trust brokers a custom Anthropic connection, so the rule above is the only one it meets ──

def _owner(monkeypatch):
    monkeypatch.setattr(gw, "SANDBOX_TRUST", "owner")
    monkeypatch.setattr(gw, "PUBLIC_BASE_URL", "")
    monkeypatch.setattr(gw, "INTERNAL_KEY", "k-test-internal-key")
    monkeypatch.setenv("HARNESS_GATEWAY_URL", "http://127.0.0.1:8080")
    monkeypatch.setattr(gw, "_pool_is_local", lambda: True)


def _turn_conn(backend, fmt, provider="tokenrouter", vendor="custom", base="https://llm.example/anthropic/v1"):
    """The connection as a turn's integration reaches _auth_from_conn (_mapped_integration_conn)."""
    return {"name": "integration:Proxy", "backend": backend, "provider": provider, "_vendor": vendor,
            "api_key": KEY, "base_url": base, "api_format": fmt, "full_url": ""}


@pytest.mark.parametrize("backend", ["claude", "pi", "omp", "opencode", "goose", "hermes", "openhands"])
def test_in_owner_trust_a_custom_anthropic_connection_with_only_a_base_url_is_brokered(monkeypatch, backend):
    _owner(monkeypatch)
    auth = gw._auth_from_conn(_turn_conn(backend, "anthropic"), "hsess1")
    assert auth["base_url"] == "http://127.0.0.1:8080/v1/llm"
    assert gw._verify_turn_cred(auth["api_key"]) == ("hsess1", "integration:Proxy")
    assert KEY not in json.dumps(auth)


def test_in_owner_trust_it_reaches_the_upstream_with_x_api_key_alone(monkeypatch, upstream):
    """End to end in the gateway: the auth owner trust now hands the runner is the broker's, and the call
    the runner's relay makes with it (Bearer and x-api-key both, as it does on /messages) reaches the
    connection's base with the stored key in x-api-key alone."""
    _owner(monkeypatch)
    conn = {"name": "integration:Proxy", "provider": "custom", "api_key": KEY,
            "base_url": upstream + "/gw/anthropic/v1", "api_format": "anthropic", "full_url": ""}
    auth = gw._auth_from_conn({**conn, "backend": "claude", "provider": "tokenrouter", "_vendor": "custom"}, "hsess1")
    assert auth["base_url"].endswith("/v1/llm"), auth.get("base_url")

    async def resolve(name, org):
        return gw._with_provider_base(dict(conn))

    async def vertex_get(sid):
        return {}
    monkeypatch.setattr(gw, "_broker_resolve", resolve)
    monkeypatch.setattr(gw, "_vertex_get", vertex_get)
    monkeypatch.setattr(gw, "_relay_client", lambda: httpx.AsyncClient(timeout=10.0))

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gw.app), base_url="http://gw.test") as c:
            return await c.post("/v1/llm/v1/messages?beta=true",
                                headers={"authorization": f"Bearer {auth['api_key']}", "x-api-key": auth["api_key"],
                                         "anthropic-version": "2023-06-01"},
                                json={"model": "m", "max_tokens": 8, "messages": [{"role": "user", "content": "hi"}]})
    r = asyncio.run(run())
    assert r.status_code == 200, r.text
    got = _Upstream.seen[-1]
    assert got["path"] == "/gw/anthropic/v1/messages?beta=true"
    assert _one(got, "x-api-key") == [KEY] and "authorization" not in got["headers"]
    assert auth["api_key"] not in json.dumps(got["raw"])


@pytest.mark.parametrize("conn", [
    _turn_conn("pi", "openai", base="https://llm.example/v1"),           # a custom OpenAI connection
    _turn_conn("codex", "responses", base="https://llm.example/v1"),     # a custom Responses connection
    # Anthropic's own connection: the runner's relay sends its key in x-api-key alone (api.anthropic.com)
    {"name": "integration:Anthropic", "backend": "claude", "provider": "anthropic", "api_key": KEY,
     "base_url": "https://api.anthropic.com/v1"},
    # an aggregator's Messages surface, outside this change
    _turn_conn("claude", "", provider="tokenrouter", vendor="openrouter", base="https://openrouter.ai/api/v1"),
])
def test_in_owner_trust_every_other_connection_is_handed_over_as_before(monkeypatch, conn):
    _owner(monkeypatch)
    auth = gw._auth_from_conn(conn, "hsess1")
    assert auth["api_key"] == KEY and auth["base_url"] == conn["base_url"]
