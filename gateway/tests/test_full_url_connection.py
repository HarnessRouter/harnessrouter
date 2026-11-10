"""A custom connection whose address is the full request URL ("Use Full URL": the console's "Use as it
is", and the setup builder's `full_url`).

The address is used exactly as stored: no /chat/completions, /responses or /v1/messages is appended.
Each agent CLI appends its own resource to the base it is given, so the address can only be applied
where every base's model calls pass: the broker. A connection with a full URL is brokered under owner
trust too, as a connection with request headers is, and the broker sends the call for the
connection's own format to the stored URL and refuses every other path (a model list, a token count,
a compaction) without sending anything, since the stored URL is no address for them.
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


class _Upstream(http.server.BaseHTTPRequestHandler):
    seen: list = []

    def _answer(self):
        body = self.rfile.read(int(self.headers.get("content-length") or 0))
        _Upstream.seen.append({"method": self.command, "path": self.path,
                               "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
        out = json.dumps({"id": "c1", "object": "chat.completion", "model": "m",
                          "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"},
                                       "finish_reason": "stop"}]}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    do_POST = do_GET = _answer  # noqa: N815

    def log_message(self, *a):
        pass


@pytest.fixture
def upstream():
    _Upstream.seen = []
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Upstream)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _broker(monkeypatch, conn, method, path, body=None):
    """One call through /v1/llm/<path> on a turn credential for `conn`, as the runner's relay makes it
    for a brokered turn; → (status, what the upstream saw)."""
    monkeypatch.setattr(gw, "INTERNAL_KEY", "k-test-internal-key")

    async def resolve(name, org):
        return gw._with_provider_base(dict(conn))

    async def vertex_get(sid):
        return {}
    monkeypatch.setattr(gw, "_broker_resolve", resolve)
    monkeypatch.setattr(gw, "_vertex_get", vertex_get)
    monkeypatch.setattr(gw, "_relay_client", lambda: httpx.AsyncClient(timeout=10.0))
    cred = gw._mint_turn_cred("hsess-full", str(conn.get("name") or "integration:Proxy"), "")

    async def run():
        transport = httpx.ASGITransport(app=gw.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://gw.test") as c:
            return await c.request(method, path, headers={"authorization": f"Bearer {cred}"},
                                   json=body if method == "POST" else None)
    r = asyncio.run(run())
    return r.status_code, _Upstream.seen


def _custom(upstream, fmt, full, path="/deployments/team-a/invoke"):
    return {"name": "integration:Proxy", "provider": "custom", "api_key": "real-key-SENTINEL",
            "base_url": upstream + path, "api_format": fmt, "full_url": "1" if full else ""}


# ── the call for the connection's format lands on the stored URL, exactly ──────────────────────

@pytest.mark.parametrize("fmt,path", [
    ("openai", "/v1/llm/v1/chat/completions"),     # pi, hermes, qwen, opencode... as the relay forwards them
    ("openai", "/v1/llm/chat/completions"),
    ("responses", "/v1/llm/responses"),            # codex, pi, omp, dcode
    ("responses", "/v1/llm/v1/responses"),
    ("anthropic", "/v1/llm/v1/messages"),          # claude, pi's and omp's anthropic client
    ("anthropic", "/v1/llm/messages"),
])
def test_a_full_url_connections_call_lands_exactly_on_the_stored_url(monkeypatch, upstream, fmt, path):
    status, seen = _broker(monkeypatch, _custom(upstream, fmt, True), "POST", path,
                           {"model": "m", "input": "hi", "messages": [{"role": "user", "content": "hi"}]})
    assert status == 200, seen
    assert len(seen) == 1
    assert seen[0]["path"] == "/deployments/team-a/invoke"
    if fmt == "anthropic":   # the key in the header the format reads (test_broker_credential_header)
        assert seen[0]["headers"]["x-api-key"] == "real-key-SENTINEL" and "authorization" not in seen[0]["headers"]
    else:
        assert seen[0]["headers"]["authorization"] == "Bearer real-key-SENTINEL"


def test_the_clients_query_joins_the_stored_urls_own(monkeypatch, upstream):
    conn = _custom(upstream, "anthropic", True, path="/invoke?api-version=2026-01")
    status, seen = _broker(monkeypatch, conn, "POST", "/v1/llm/v1/messages?beta=true", {"model": "m"})
    assert status == 200
    assert seen[0]["path"] == "/invoke?api-version=2026-01&beta=true"
    status, seen = _broker(monkeypatch, _custom(upstream, "anthropic", True), "POST",
                           "/v1/llm/v1/messages?beta=true", {"model": "m"})
    assert seen[-1]["path"] == "/deployments/team-a/invoke?beta=true"


@pytest.mark.parametrize("fmt,method,path", [
    ("openai", "GET", "/v1/llm/v1/models"),                   # a model list: the stored URL is no list
    ("openai", "POST", "/v1/llm/v1/responses"),               # another format's resource
    ("openai", "POST", "/v1/llm/v1/embeddings"),
    ("responses", "POST", "/v1/llm/v1/responses/compact"),    # codex's compaction
    ("responses", "POST", "/v1/llm/v1/chat/completions"),
    ("anthropic", "POST", "/v1/llm/v1/messages/count_tokens"),
])
def test_any_other_path_is_refused_and_nothing_is_sent(monkeypatch, upstream, fmt, method, path):
    status, seen = _broker(monkeypatch, _custom(upstream, fmt, True), method, path, {"model": "m"})
    assert status == 404
    assert seen == []


# ── a connection without a full URL is forwarded as before ─────────────────────────────────────

@pytest.mark.parametrize("fmt,method,path,lands", [
    ("openai", "POST", "/v1/llm/v1/chat/completions", "/deployments/team-a/invoke/chat/completions"),
    ("responses", "POST", "/v1/llm/responses", "/deployments/team-a/invoke/responses"),
    ("anthropic", "POST", "/v1/llm/v1/messages?beta=true", "/deployments/team-a/invoke/messages?beta=true"),
    ("openai", "GET", "/v1/llm/v1/models", "/deployments/team-a/invoke/models"),
])
def test_a_connection_without_a_full_url_is_unchanged(monkeypatch, upstream, fmt, method, path, lands):
    status, seen = _broker(monkeypatch, _custom(upstream, fmt, False), method, path, {"model": "m"})
    assert status == 200
    assert seen[-1]["path"] == lands
    if fmt == "anthropic":
        assert seen[-1]["headers"]["x-api-key"] == "real-key-SENTINEL" and "authorization" not in seen[-1]["headers"]
    else:
        assert seen[-1]["headers"]["authorization"] == "Bearer real-key-SENTINEL"


def test_full_url_is_the_custom_providers_alone(monkeypatch, upstream):
    """The form offers it on a custom connection only; a vendor's connection that somehow carries it
    keeps the vendor's own paths."""
    conn = {**_custom(upstream, "openai", True), "provider": "openrouter"}
    status, seen = _broker(monkeypatch, conn, "POST", "/v1/llm/v1/chat/completions", {"model": "m"})
    assert status == 200 and seen[-1]["path"] == "/deployments/team-a/invoke/chat/completions"


# ── owner trust brokers a full URL, so the broker is where it applies for every base ───────────

def _owner(monkeypatch):
    monkeypatch.setattr(gw, "SANDBOX_TRUST", "owner")
    monkeypatch.setattr(gw, "PUBLIC_BASE_URL", "")
    monkeypatch.setattr(gw, "INTERNAL_KEY", "k-test-internal-key")
    monkeypatch.setenv("HARNESS_GATEWAY_URL", "http://127.0.0.1:8080")
    monkeypatch.setattr(gw, "_pool_is_local", lambda: True)


# The connection as a turn's integration reaches _auth_from_conn (_mapped_integration_conn: the runner's
# provider name, the vendor beside it, the integration's config), for the bases a custom one drives.
def _turn_conn(backend, full, fmt="openai"):
    return {"name": "integration:Proxy", "backend": backend, "provider": "tokenrouter", "_vendor": "custom",
            "api_key": "real-key-SENTINEL", "base_url": "https://llm.example/deployments/team-a/invoke",
            "api_format": fmt, **({"full_url": "1"} if full else {"full_url": ""})}


@pytest.mark.parametrize("backend,fmt", [("pi", "openai"), ("pi", "responses"), ("codex", "responses"),
                                         ("claude", "anthropic"), ("hermes", "openai"), ("qwen", "openai")])
def test_in_owner_trust_a_full_url_connection_is_brokered(monkeypatch, backend, fmt):
    _owner(monkeypatch)
    auth = gw._auth_from_conn(_turn_conn(backend, True, fmt), "hsess1")
    assert auth["base_url"] == "http://127.0.0.1:8080/v1/llm"
    assert gw._verify_turn_cred(auth["api_key"]) == ("hsess1", "integration:Proxy")
    assert "real-key-SENTINEL" not in json.dumps(auth) and "llm.example" not in json.dumps(auth)
    # the runner's base is the broker's, which is no full URL
    assert not auth.get("full_url")
    assert auth["api_format"] == fmt


def test_a_chain_connection_with_a_full_url_is_brokered_too(monkeypatch):
    _owner(monkeypatch)
    conn = gw._chain_wired({"name": "proxy", "provider": "custom", "api_key": "real-key-SENTINEL",
                            "base_url": "https://llm.example/invoke", "api_format": "openai", "full_url": "1"}, "pi")
    auth = gw._auth_from_conn(conn, "hsess1")
    assert auth["base_url"] == "http://127.0.0.1:8080/v1/llm" and "real-key-SENTINEL" not in json.dumps(auth)


def test_in_owner_trust_a_connection_without_a_full_url_is_handed_over_as_before(monkeypatch):
    _owner(monkeypatch)
    auth = gw._auth_from_conn(_turn_conn("pi", False), "hsess1")
    assert auth["api_key"] == "real-key-SENTINEL"
    assert auth["base_url"] == "https://llm.example/deployments/team-a/invoke"


def test_brokered_auth_never_carries_full_url(monkeypatch):
    monkeypatch.setattr(gw, "SANDBOX_TRUST", "")
    monkeypatch.setattr(gw, "INTERNAL_KEY", "k-test-internal-key")
    monkeypatch.setattr(gw, "PUBLIC_BASE_URL", "https://hr.example")
    monkeypatch.setattr(gw, "_pool_is_local", lambda: False)
    auth = gw._auth_from_conn(_turn_conn("pi", True), "hsess1")
    assert auth["base_url"] == "https://hr.example/v1/llm" and not auth.get("full_url")


def test_the_setup_builder_keeps_using_the_stored_url():
    w = gw._setup_build_wire("custom", {"api_key": "k", "base_url": "https://llm.example/invoke", "api_format": "openai",
                                        "full_url": "1"}, "m", "m")
    assert w["url"] == "https://llm.example/invoke"
    w = gw._setup_build_wire("custom", {"api_key": "k", "base_url": "https://llm.example/v1", "api_format": "openai"},
                             "m", "m")
    assert w["url"] == "https://llm.example/v1/chat/completions"
