"""AWS Bedrock and Google Vertex credentials stay in the runner's relay (2026-11-02).

claude and hermes used to get the AWS key pair or the Bedrock API key in their environment, and
claude on Vertex got the whole service account as <cwd>/.gcp-sa.json, where the agent could `cat` it.
The relay holds them now: it SigV4-signs each Bedrock call with the key pair (or sets the API key as
the bearer) and mints Vertex access tokens from the service account itself.

These tests pin the signer against botocore's SigV4Auth, the token minting against a stub token
endpoint, the relay end to end against stub upstreams, and a built turn's environment, argv and files.
Nothing here reaches AWS or Google: every upstream is local, and a signature is "valid" when botocore
computes the same one for the same request with the same (fake) credentials.
"""
import base64
import datetime
import hashlib
import http.client
import json
import os
import pathlib
import re
import sys
import threading
import urllib.parse
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server as rs  # noqa: E402
from server import Auth  # noqa: E402

# Recognisable fake credentials: any of these in a turn's environment, argv or files is a leak.
AKID = "AKIA_FAKE_ACCESS_KEY_01"
SECRET = "fake-secret-access-key-0123456789abcdef"
SESSION = "fake-session-token-FwoGZXIvYXdzEFAKE0123"
BEARER = "fake-bedrock-api-key-ABSKfakeFAKEfake0123"
AWS_SECRETS = (AKID, SECRET, SESSION, BEARER)
FROZEN = datetime.datetime(2026, 11, 2, 12, 34, 56, tzinfo=datetime.timezone.utc)
MODEL = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
TRACE_PARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"


# ── helpers ─────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def relay(monkeypatch):
    """A relay of this test's own: its own server and route table."""
    state = {"server": None, "port": 0, "routes": {}, "lock": threading.Lock(), "totals": threading.Lock()}
    monkeypatch.setattr(rs, "_HERMES_RELAY", state)
    yield state
    if state["server"] is not None:
        state["server"].shutdown()


class _Stub:
    """A local upstream: records every request it gets and answers it with `reply(handler, request)`."""

    def __init__(self, reply):
        self.requests: list[dict] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _any(self):
                n = int(self.headers.get("content-length") or 0)
                req = {"method": self.command, "path": self.path, "body": self.rfile.read(n) if n else b"",
                       "headers": {k.lower(): v for k, v in self.headers.items()}}
                stub.requests.append(req)
                reply(self, req)

            do_GET = do_POST = do_DELETE = _any

            def log_message(self, *a):
                pass

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def close(self):
        self.srv.shutdown()


def _json_reply(doc=None, status=200, headers=None):
    def reply(h, req):
        data = json.dumps({"ok": True} if doc is None else doc).encode()
        h.send_response(status)
        h.send_header("content-type", "application/json")
        for k, v in (headers or {}).items():
            h.send_header(k, v)
        h.send_header("content-length", str(len(data)))
        h.end_headers()
        h.wfile.write(data)
    return reply


def _upstream_to(relay_state, tok, base):
    """Point a registered route at a local stub instead of AWS or Google."""
    _old, cred, flags = relay_state["routes"][tok]
    relay_state["routes"][tok] = (base, cred, flags)


def _call(origin, path, body=b"", headers=None, method="POST"):
    u = urllib.parse.urlsplit(origin)
    conn = http.client.HTTPConnection(u.hostname, u.port, timeout=15)
    conn.request(method, path, body=body if method == "POST" else None, headers=headers or {})
    return conn, conn.getresponse()


def _botocore_sign(method, url, headers, body, *, akid, secret, token, region, when):
    """The headers botocore's SigV4Auth puts on this request at `when`."""
    import botocore.auth as ba
    from botocore.awsrequest import AWSRequest
    from botocore.credentials import Credentials
    if not hasattr(ba, "get_current_datetime"):
        pytest.skip("this botocore reads the clock some other way")
    req = AWSRequest(method=method, url=url, headers=dict(headers), data=body)
    signer = ba.SigV4Auth(Credentials(akid, secret, token or None), "bedrock", region)
    with mock.patch.object(ba, "get_current_datetime", lambda *a, **k: when.replace(tzinfo=None)):
        signer.add_auth(req)
    return req.headers


def _assert_signed_with_the_real_pair(seen, base, region, token):
    """The request the upstream received carries a SigV4 signature that botocore, given the real
    (fake) key pair, computes the same way for the same request: what AWS would accept."""
    auth = seen["headers"].get("authorization", "")
    assert auth.startswith(f"AWS4-HMAC-SHA256 Credential={AKID}/"), auth
    signed = re.search(r"SignedHeaders=([^,]+)", auth).group(1).split(";")
    assert {"host", "x-amz-date", "x-amz-content-sha256"} <= set(signed)
    assert seen["headers"]["x-amz-content-sha256"] == hashlib.sha256(seen["body"]).hexdigest()
    if token:
        assert "x-amz-security-token" in signed and seen["headers"]["x-amz-security-token"] == token
    else:
        assert "x-amz-security-token" not in seen["headers"]
    when = datetime.datetime.strptime(seen["headers"]["x-amz-date"], "%Y%m%dT%H%M%SZ").replace(
        tzinfo=datetime.timezone.utc)
    theirs = _botocore_sign(seen["method"], base + seen["path"], {n: seen["headers"][n] for n in signed},
                            seen["body"], akid=AKID, secret=SECRET, token=token, region=region, when=when)
    assert auth == theirs["Authorization"]


def _es_frame(headers: dict, payload: bytes) -> bytes:
    """One AWS eventstream frame (string headers only), CRCs included."""
    hb = b"".join(bytes([len(k)]) + k.encode() + b"\x07" + len(v.encode()).to_bytes(2, "big") + v.encode()
                  for k, v in headers.items())
    prelude = (16 + len(hb) + len(payload)).to_bytes(4, "big") + len(hb).to_bytes(4, "big")
    msg = prelude + zlib.crc32(prelude).to_bytes(4, "big") + hb + payload
    return msg + zlib.crc32(msg).to_bytes(4, "big")


def _event(kind: str, doc: dict) -> bytes:
    return _es_frame({":event-type": kind, ":content-type": "application/json", ":message-type": "event"},
                     json.dumps(doc).encode())


def _streaming_reply(chunks: list[bytes], ctype: str, go_on: threading.Event, headers=None):
    """Send the first chunk, then the rest only once the test says the client has it: a relay that
    buffered the answer would never hand the client the first chunk, and the test would time out."""
    def reply(h, req):
        h.send_response(200)
        h.send_header("content-type", ctype)
        for k, v in (headers or {}).items():
            h.send_header(k, v)
        h.send_header("transfer-encoding", "chunked")
        h.end_headers()
        for i, c in enumerate(chunks):
            h.wfile.write(f"{len(c):x}\r\n".encode() + c + b"\r\n")
            h.wfile.flush()
            if i == 0:
                go_on.wait(10)
        h.wfile.write(b"0\r\n\r\n")
    return reply


def _service_account(token_uri: str, project: str = "fake-project-123"):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    sa = {"type": "service_account", "project_id": project, "private_key_id": "fakekeyid0123456789abcdef0123",
          "private_key": pem, "client_email": f"relay-test@{project}.iam.gserviceaccount.com",
          "client_id": "100000000000000000001", "token_uri": token_uri}
    return sa, key.public_key()


def _sa_secrets(sa: dict) -> tuple[str, ...]:
    """What of a service account must never leave the relay: the key (each line of its body) and its id."""
    body = [ln for ln in sa["private_key"].splitlines() if ln and not ln.startswith("-----")]
    return (sa["private_key_id"], *body)


def _token_endpoint(error: dict | None = None):
    """A stub OAuth2 token endpoint: it mints ya29.fake-access-token-<n>, or refuses with `error`."""
    def reply(h, req):
        form = urllib.parse.parse_qs(req["body"].decode())
        if error is not None:
            _json_reply(error, status=400)(h, req)
            return
        stub.minted.append(form)
        _json_reply({"access_token": f"ya29.fake-access-token-{len(stub.minted)}", "expires_in": 3600,
                     "token_type": "Bearer"})(h, req)
    stub = _Stub(reply)
    stub.minted = []
    return stub


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _leaks(secrets, env: dict, argv, *roots) -> list[str]:
    """Every place one of `secrets` turns up: an environment variable, an argument, a file."""
    found = []
    for k, v in env.items():
        found += [f"env {k}" for s in secrets if s in str(v)]
    for i, a in enumerate(argv or []):
        found += [f"argv[{i}]" for s in secrets if s in str(a)]
    for root in roots:
        for dirpath, _dirs, files in os.walk(root):
            for fn in files:
                p = os.path.join(dirpath, fn)
                if os.path.islink(p):
                    continue
                with open(p, "rb") as f:
                    data = f.read()
                found += [f"file {p}" for s in secrets if s.encode() in data]
    return found


# ── SigV4: the relay's signer is botocore's ─────────────────────────────────────────────────────
_BODY = json.dumps({"anthropic_version": "bedrock-2023-05-31", "max_tokens": 64,
                    "messages": [{"role": "user", "content": "héllo — say hi"}]}, ensure_ascii=False).encode()
SIGV4_CASES = [
    # Claude Code / the AWS SDKs: the model id one percent-encoded segment
    ("POST", f"https://bedrock-runtime.us-east-1.amazonaws.com/model/{urllib.parse.quote(MODEL, safe='')}/invoke",
     {"Content-Type": "application/json"}, _BODY, "", "us-east-1"),
    ("POST", f"https://bedrock-runtime.us-east-1.amazonaws.com/model/{urllib.parse.quote(MODEL, safe='')}/invoke",
     {"Content-Type": "application/json"}, _BODY, SESSION, "us-east-1"),
    # Anthropic's Python SDK leaves the colon raw (quote(model, safe=":"))
    ("POST", f"https://bedrock-runtime.us-west-2.amazonaws.com/model/{MODEL}/invoke-with-response-stream",
     {"content-type": "application/json", "accept": "application/vnd.amazon.eventstream"}, _BODY, SESSION,
     "us-west-2"),
    # an application inference profile ARN: colons and a slash, encoded
    ("POST", "https://bedrock-runtime.eu-west-1.amazonaws.com/model/"
     + urllib.parse.quote("arn:aws:bedrock:eu-west-1:123456789012:application-inference-profile/abc123def", safe="")
     + "/converse", {"Content-Type": "application/json"}, _BODY, "", "eu-west-1"),
    # a query string out of order, a repeated key, an empty body
    ("GET", "https://bedrock-runtime.us-east-1.amazonaws.com/async-invoke?maxResults=5&statusEquals=Completed&a=b&a=a",
     {}, b"", SESSION, "us-east-1"),
    # a port that is not the scheme's, dot segments, a space and a tilde, a header value to trim
    ("POST", "http://127.0.0.1:8443/model/m%2Fwith%20space~tilde/./x/../invoke",
     {"Content-Type": "application/json", "X-Amzn-Bedrock-Trace": "  ENABLED   now "}, _BODY, "", "ap-northeast-1"),
]


@pytest.mark.parametrize("method,url,headers,body,token,region", SIGV4_CASES)
def test_the_relay_signs_as_botocore_signs(method, url, headers, body, token, region):
    pytest.importorskip("botocore")
    mine = rs._sigv4_sign(method, url, headers, body, region=region, service="bedrock", access_key_id=AKID,
                          secret_access_key=SECRET, session_token=token, now=FROZEN)
    # botocore's SigV4Auth sends no x-amz-content-sha256 of its own (only S3's signer does); the relay
    # does, so botocore signs the same request with it
    theirs = _botocore_sign(method, url, {**headers, "X-Amz-Content-SHA256": hashlib.sha256(body).hexdigest()},
                            body, akid=AKID, secret=SECRET, token=token, region=region, when=FROZEN)
    assert mine["authorization"] == theirs["Authorization"]
    assert mine["x-amz-date"] == theirs["X-Amz-Date"] == "20261102T123456Z"
    assert mine["x-amz-content-sha256"] == hashlib.sha256(body).hexdigest()
    if token:
        assert mine["x-amz-security-token"] == theirs["X-Amz-Security-Token"] == token
    else:
        assert "x-amz-security-token" not in mine


def test_a_signature_names_the_service_and_region_it_was_made_for():
    a = rs._sigv4_sign("POST", "https://bedrock-runtime.us-east-1.amazonaws.com/model/m/invoke", {}, b"{}",
                       region="us-east-1", service="bedrock", access_key_id=AKID, secret_access_key=SECRET,
                       now=FROZEN)
    b = rs._sigv4_sign("POST", "https://bedrock-runtime.us-east-1.amazonaws.com/model/m/invoke", {}, b"{}",
                       region="us-west-2", service="bedrock", access_key_id=AKID, secret_access_key=SECRET,
                       now=FROZEN)
    assert f"Credential={AKID}/20261102/us-east-1/bedrock/aws4_request" in a["authorization"]
    assert a["authorization"] != b["authorization"]
    assert SECRET not in json.dumps(a)


# ── Vertex: the relay mints the access token ────────────────────────────────────────────────────
def test_the_relay_mints_a_vertex_token_with_a_verifiable_jwt_and_caches_it(relay):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    tokens = _token_endpoint()
    try:
        sa, public = _service_account(tokens.base + "/token")
        _origin, tok = rs._vertex_relay_route(json.dumps(sa), "us-east5", "fake-project-123")
        cred = relay["routes"][tok][1]
        assert sa["private_key"] not in repr(relay["routes"][tok]) and "fake" not in repr(cred)

        t0 = 1_800_000_000.0
        assert cred.access_token(now=t0) == "ya29.fake-access-token-1"
        assert len(tokens.minted) == 1
        form = tokens.minted[0]
        assert form["grant_type"] == ["urn:ietf:params:oauth:grant-type:jwt-bearer"]
        h, c, s = form["assertion"][0].split(".")
        header, claims = json.loads(_b64d(h)), json.loads(_b64d(c))
        assert header == {"alg": "RS256", "typ": "JWT", "kid": sa["private_key_id"]}
        assert claims == {"iss": sa["client_email"], "scope": "https://www.googleapis.com/auth/cloud-platform",
                          "aud": tokens.base + "/token", "iat": int(t0), "exp": int(t0) + 3600}
        public.verify(_b64d(s), f"{h}.{c}".encode(), padding.PKCS1v15(), hashes.SHA256())   # raises if not

        # cached while it has more than five minutes left
        assert cred.access_token(now=t0 + 3000) == "ya29.fake-access-token-1"
        assert len(tokens.minted) == 1
        # minted afresh inside the last five minutes
        assert cred.access_token(now=t0 + 3600 - 299) == "ya29.fake-access-token-2"
        assert len(tokens.minted) == 2
        claims2 = json.loads(_b64d(tokens.minted[1]["assertion"][0].split(".")[1]))
        assert claims2["iat"] == int(t0 + 3600 - 299)
    finally:
        tokens.close()


def test_a_refused_token_request_says_why_and_shows_no_key(relay):
    tokens = _token_endpoint(error={"error": "invalid_grant", "error_description": "Invalid JWT Signature."})
    try:
        sa, _ = _service_account(tokens.base + "/token")
        _origin, tok = rs._vertex_relay_route(json.dumps(sa), "us-east5", "")
        with pytest.raises(rs._CloudAuthError) as e:
            relay["routes"][tok][1].access_token()
        msg = str(e.value)
        assert "HTTP 400" in msg and "invalid_grant" in msg and "Invalid JWT Signature." in msg
        assert not any(s in msg for s in _sa_secrets(sa)) and "eyJ" not in msg   # no key, no assertion
    finally:
        tokens.close()


@pytest.mark.parametrize("sa_json,why", [
    ("not json", "client_email and private_key"),
    (json.dumps({"client_email": "x@y.iam.gserviceaccount.com"}), "client_email and private_key"),
    (json.dumps({"client_email": "x@y.iam.gserviceaccount.com",
                 "private_key": "-----BEGIN " "PRIVATE KEY-----FAKEFAKEFAKE\n-----END PRIVATE KEY-----\n"}),
     "private key could not be read"),
    (json.dumps({"client_email": "x@y.iam.gserviceaccount.com", "private_key": "k",
                 "token_uri": "http://token.example/token"}), "not https"),
])
def test_a_service_account_that_cannot_be_used_fails_the_turn_with_a_reason(relay, sa_json, why):
    with pytest.raises(rs.HTTPException) as e:
        rs._vertex_relay_route(sa_json, "us-east5", "p")
    assert e.value.status_code == 400 and why in e.value.detail
    assert "FAKEFAKE" not in e.value.detail
    assert relay["routes"] == {}


# ── the relay, end to end ───────────────────────────────────────────────────────────────────────
def test_bedrock_with_a_key_pair_is_signed_with_the_real_pair_and_streams_byte_for_byte(relay):
    pytest.importorskip("botocore")
    go_on = threading.Event()
    frames = [_es_frame({":event-type": "chunk", ":message-type": "event"},
                        json.dumps({"bytes": base64.b64encode(f"part {i}".encode()).decode()}).encode())
              for i in range(3)]
    up = _Stub(_streaming_reply(frames, "application/vnd.amazon.eventstream", go_on,
                                headers={"x-amzn-requestid": "fake-request-id-1"}))
    try:
        origin, tok = rs._bedrock_relay_route("us-west-2", access_key_id=AKID, secret_access_key=SECRET,
                                              session_token=SESSION)
        _upstream_to(relay, tok, up.base)
        encoded = urllib.parse.quote(MODEL, safe="")
        # Claude Code under CLAUDE_CODE_SKIP_BEDROCK_AUTH: no credential, the token as the base's path
        conn, resp = _call(origin, f"/{tok}/model/{encoded}/invoke-with-response-stream", _BODY,
                           {"content-type": "application/json", "accept": "application/vnd.amazon.eventstream"})
        first = resp.read(len(frames[0]))      # here before the upstream sends the rest: streamed
        go_on.set()
        rest = resp.read()
        conn.close()
        assert resp.status == 200
        assert first + rest == b"".join(frames)
        assert resp.getheader("content-type") == "application/vnd.amazon.eventstream"
        assert resp.getheader("x-amzn-requestid") == "fake-request-id-1"

        seen = up.requests[0]
        assert seen["path"] == f"/model/{encoded}/invoke-with-response-stream"
        assert seen["body"] == _BODY
        _assert_signed_with_the_real_pair(seen, up.base, "us-west-2", SESSION)
        assert tok not in json.dumps(seen["headers"]) + seen["path"]
    finally:
        go_on.set()
        up.close()


def test_bedrock_finds_the_route_by_the_placeholder_signature_and_signs_again(relay):
    """hermes's boto3 and AnthropicBedrock sign with placeholder keys whose access key id is the token."""
    pytest.importorskip("botocore")
    up = _Stub(_json_reply({"output": {}}))
    try:
        origin, tok = rs._bedrock_relay_route("us-west-2", access_key_id=AKID, secret_access_key=SECRET)
        _upstream_to(relay, tok, up.base)
        placeholder = rs._sigv4_sign("POST", f"{origin}/model/m/converse", {"content-type": "application/json"},
                                     b"{}", region="us-west-2", service="bedrock", access_key_id=tok,
                                     secret_access_key="hr-relay-placeholder",
                                     session_token="placeholder-session-token")
        conn, resp = _call(origin, "/model/m/converse", b"{}",
                           {"content-type": "application/json", **{k: v for k, v in placeholder.items()
                                                                   if k != "host"}})
        assert resp.status == 200 and json.loads(resp.read()) == {"output": {}}
        conn.close()
        seen = up.requests[0]
        assert seen["path"] == "/model/m/converse"
        _assert_signed_with_the_real_pair(seen, up.base, "us-west-2", "")
        assert "placeholder" not in json.dumps(seen["headers"]) and tok not in json.dumps(seen["headers"])
    finally:
        up.close()


def test_bedrock_with_an_api_key_sends_it_as_the_bearer(relay):
    up = _Stub(_json_reply({"content": [{"type": "text", "text": "hi"}]}))
    try:
        origin, tok = rs._bedrock_relay_route("us-east-1", bearer=BEARER)
        _upstream_to(relay, tok, up.base)
        # boto3 with AWS_BEARER_TOKEN_BEDROCK=<token>, on a base handed with /v1
        conn, resp = _call(origin, "/v1/model/m/invoke", b'{"x":1}',
                           {"authorization": f"Bearer {tok}", "content-type": "application/json",
                            "x-amz-date": "20200101T000000Z", "x-amz-security-token": "client-sent"})
        assert resp.status == 200 and json.loads(resp.read())["content"][0]["text"] == "hi"
        conn.close()
        seen = up.requests[0]
        assert seen["path"] == "/model/m/invoke" and seen["body"] == b'{"x":1}'
        assert seen["headers"]["authorization"] == f"Bearer {BEARER}"
        assert not [k for k in seen["headers"] if k.startswith("x-amz-")]
        assert tok not in json.dumps(seen["headers"])
    finally:
        up.close()


def test_vertex_gets_a_minted_token_and_its_sse_streams_byte_for_byte(relay):
    tokens = _token_endpoint()
    go_on = threading.Event()
    events = [b"event: message_start\ndata: {\"type\":\"message_start\"}\n\n",
              b"event: content_block_delta\ndata: {\"type\":\"content_block_delta\",\"delta\":{\"text\":\"hi\"}}\n\n",
              b"event: message_stop\ndata: {\"type\":\"message_stop\"}\n\n"]
    up = _Stub(_streaming_reply(events, "text/event-stream", go_on))
    try:
        sa, _ = _service_account(tokens.base + "/token")
        origin, tok = rs._vertex_relay_route(json.dumps(sa), "us-east5", "fake-project-123")
        _upstream_to(relay, tok, up.base)
        path = ("/v1/projects/fake-project-123/locations/us-east5/publishers/anthropic/models/"
                "claude-sonnet-4-5@20250929:streamRawPredict")
        body = json.dumps({"anthropic_version": "vertex-2023-10-16", "stream": True,
                           "messages": [{"role": "user", "content": "hi"}]}).encode()
        # Claude Code under CLAUDE_CODE_SKIP_VERTEX_AUTH sends no Authorization at all
        conn, resp = _call(origin, f"/{tok}{path}", body, {"content-type": "application/json"})
        first = resp.read(len(events[0]))
        go_on.set()
        rest = resp.read()
        conn.close()
        assert resp.status == 200 and resp.getheader("content-type") == "text/event-stream"
        assert first + rest == b"".join(events)
        seen = up.requests[0]
        assert seen["path"] == path and seen["body"] == body
        assert seen["headers"]["authorization"] == "Bearer ya29.fake-access-token-1"
        assert tok not in json.dumps(seen["headers"])

        # a second call rides the cached token
        conn, resp = _call(origin, f"/{tok}{path.replace(':streamRawPredict', ':rawPredict')}", body,
                           {"content-type": "application/json"})
        resp.read()
        conn.close()
        assert up.requests[1]["headers"]["authorization"] == "Bearer ya29.fake-access-token-1"
        assert len(tokens.minted) == 1
    finally:
        go_on.set()
        up.close()
        tokens.close()


@pytest.mark.parametrize("kind", ["bedrock-keys", "bedrock-bearer", "vertex"])
def test_a_redirect_from_upstream_is_not_followed(relay, kind):
    elsewhere = _Stub(_json_reply())

    def redirect(h, req):
        h.send_response(307)
        h.send_header("location", elsewhere.base + "/collect")
        h.send_header("content-length", "0")
        h.end_headers()
    up = _Stub(redirect)
    tokens = _token_endpoint()
    try:
        if kind == "vertex":
            sa, _ = _service_account(tokens.base + "/token")
            origin, tok = rs._vertex_relay_route(json.dumps(sa), "us-east5", "p")
            path = f"/{tok}/v1/projects/p/locations/us-east5/publishers/anthropic/models/m:rawPredict"
        else:
            origin, tok = (rs._bedrock_relay_route("us-east-1", access_key_id=AKID, secret_access_key=SECRET)
                           if kind == "bedrock-keys" else rs._bedrock_relay_route("us-east-1", bearer=BEARER))
            path = f"/{tok}/model/m/invoke"
        _upstream_to(relay, tok, up.base)
        conn, resp = _call(origin, path, b"{}", {"content-type": "application/json"})
        resp.read()
        conn.close()
        assert resp.status == 307
        assert resp.getheader("location") is None       # not handed on for the client to follow either
        assert len(up.requests) == 1
        assert elsewhere.requests == []                  # the credential went nowhere else
    finally:
        up.close()
        elsewhere.close()
        tokens.close()


def test_only_model_calls_are_forwarded(relay):
    up = _Stub(_json_reply())
    tokens = _token_endpoint()
    try:
        origin, btok = rs._bedrock_relay_route("us-east-1", access_key_id=AKID, secret_access_key=SECRET)
        sa, _ = _service_account(tokens.base + "/token")
        _o, vtok = rs._vertex_relay_route(json.dumps(sa), "us-east5", "p")
        _upstream_to(relay, btok, up.base)
        _upstream_to(relay, vtok, up.base)
        vroot = f"/{vtok}/v1/projects/p/locations/us-east5"
        for method, path, kind in [
            ("GET", f"/{btok}/foundation-models", "bedrock"),
            ("GET", f"/{btok}/inference-profiles?typeEquals=SYSTEM_DEFINED", "bedrock"),
            ("GET", f"/{btok}/model/m/invoke", "bedrock"),
            ("DELETE", f"/{btok}/model/m/invoke", "bedrock"),
            ("POST", f"/{btok}/async-invoke", "bedrock"),
            ("POST", f"/{btok}/guardrail/g/version/1/apply", "bedrock"),
            ("POST", f"/{btok}/model/../invoke", "bedrock"),
            ("POST", f"/{btok}/model/m/invoke/../../async-invoke", "bedrock"),
            ("POST", f"{vroot}/customJobs", "vertex"),
            ("GET", f"{vroot}/endpoints", "vertex"),
            ("POST", f"{vroot}/publishers/anthropic/models/m:deploy", "vertex"),
            ("GET", f"{vroot}/publishers/anthropic/models/m:rawPredict", "vertex"),
            ("POST", f"/{vtok}/v1/projects/p/locations/us-east5/endpoints/e:predict", "vertex"),
        ]:
            conn, resp = _call(origin, path, b"{}", {"content-type": "application/json"}, method=method)
            data = resp.read()
            conn.close()
            assert resp.status == 404, (method, path, resp.status)
            if kind == "bedrock":
                assert resp.getheader("x-amzn-errortype") == "UnknownOperationException"
            else:
                assert json.loads(data)["error"]["status"] == "NOT_FOUND"
        assert up.requests == [] and tokens.minted == []
    finally:
        up.close()
        tokens.close()


def test_a_route_is_found_by_its_path_or_signature_only_when_it_is_a_cloud_route(relay):
    up = _Stub(_json_reply())
    try:
        base, htok = rs._hermes_relay_route(up.base + "/v1", "sk-fake-provider-key")
        origin = rs._relay_origin(base)
        # an ordinary route's token in the path, with no credential: not this route
        conn, resp = _call(origin, f"/{htok}/chat/completions", b"{}", {"content-type": "application/json"})
        resp.read()
        conn.close()
        assert resp.status == 401
        # nor as the access key id of a signature
        conn, resp = _call(origin, "/chat/completions", b"{}",
                           {"authorization": f"AWS4-HMAC-SHA256 Credential={htok}/20261102/us-east-1/bedrock/"
                                             "aws4_request, SignedHeaders=host, Signature=00"})
        resp.read()
        conn.close()
        assert resp.status == 401
        # an unknown token in the path
        conn, resp = _call(origin, f"/hr-relay-{'0' * 32}/model/m/invoke", b"{}")
        resp.read()
        conn.close()
        assert resp.status == 401
        assert up.requests == []
    finally:
        up.close()


def test_a_cloud_call_carries_the_turns_trace_context(relay):
    up = _Stub(_json_reply())
    token = rs._TURN_TRACE.set({"traceparent": TRACE_PARENT, "tracestate": "vendor=1"})
    try:
        origin, tok = rs._bedrock_relay_route("us-east-1", access_key_id=AKID, secret_access_key=SECRET)
    finally:
        rs._TURN_TRACE.reset(token)
    try:
        assert relay["routes"][tok][2]["traceparent"] == TRACE_PARENT
        _upstream_to(relay, tok, up.base)
        conn, resp = _call(origin, f"/{tok}/model/m/invoke", b"{}", {"content-type": "application/json"})
        resp.read()
        conn.close()
        got = up.requests[0]["headers"]["traceparent"]
        assert got.split("-")[1] == TRACE_PARENT.split("-")[1] and got != TRACE_PARENT
        assert up.requests[0]["headers"]["tracestate"] == "vendor=1"
    finally:
        up.close()


# ── boto3, configured the way hermes's environment configures it ────────────────────────────────
@pytest.fixture
def aws_sandbox(monkeypatch, tmp_path):
    """An environment with no AWS configuration of its own (no profile files, no instance metadata)."""
    for n in (*rs._AWS_CREDENTIAL_ENV, "AWS_ENDPOINT_URL", "AWS_ENDPOINT_URL_BEDROCK_RUNTIME", "AWS_REGION",
              "AWS_DEFAULT_REGION", "ANTHROPIC_BEDROCK_BASE_URL"):
        monkeypatch.delenv(n, raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "no-aws-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "no-aws-credentials"))
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    return monkeypatch


def _hermes_bedrock_env(tmp_path, auth) -> dict:
    env: dict = {}
    rs._hermes_prepare_env("bedrock", auth, str(tmp_path), env, model=MODEL)
    return env


@pytest.mark.parametrize("mode", ["keys", "bearer"])
def test_boto3_with_hermes_environment_converses_through_the_relay(relay, aws_sandbox, tmp_path, mode):
    boto3 = pytest.importorskip("boto3")
    up = _Stub(_json_reply({"output": {"message": {"role": "assistant", "content": [{"text": "hello from the stub"}]}},
                            "stopReason": "end_turn", "usage": {"inputTokens": 3, "outputTokens": 4, "totalTokens": 7},
                            "metrics": {"latencyMs": 1}}))
    try:
        auth = (Auth(aws_region="us-west-2", aws_access_key_id=AKID, aws_secret_access_key=SECRET,
                     aws_session_token=SESSION) if mode == "keys"
                else Auth(aws_region="us-west-2", aws_bearer_token=BEARER))
        env = _hermes_bedrock_env(tmp_path, auth)
        tok = env.get("AWS_ACCESS_KEY_ID") if mode == "keys" else env.get("AWS_BEARER_TOKEN_BEDROCK")
        _upstream_to(relay, tok, up.base)
        for k in ("AWS_REGION", "AWS_DEFAULT_REGION", "AWS_ENDPOINT_URL_BEDROCK_RUNTIME", "AWS_ACCESS_KEY_ID",
                  "AWS_SECRET_ACCESS_KEY", "AWS_BEARER_TOKEN_BEDROCK"):
            if k in env:
                aws_sandbox.setenv(k, env[k])
        client = boto3.session.Session().client("bedrock-runtime")
        out = client.converse(modelId=MODEL, messages=[{"role": "user", "content": [{"text": "hi"}]}])
        assert out["output"]["message"]["content"][0]["text"] == "hello from the stub"
        seen = up.requests[0]
        assert seen["path"] == f"/model/{urllib.parse.quote(MODEL, safe='')}/converse"
        if mode == "keys":
            _assert_signed_with_the_real_pair(seen, up.base, "us-west-2", SESSION)
        else:
            assert seen["headers"]["authorization"] == f"Bearer {BEARER}"
        assert tok not in json.dumps(seen["headers"]) and "hr-relay-placeholder" not in json.dumps(seen["headers"])
    finally:
        up.close()


def test_boto3_converse_stream_parses_the_relayed_eventstream(relay, aws_sandbox, tmp_path):
    boto3 = pytest.importorskip("boto3")
    frames = [_event("messageStart", {"role": "assistant"}),
              _event("contentBlockDelta", {"contentBlockIndex": 0, "delta": {"text": "hello "}}),
              _event("contentBlockDelta", {"contentBlockIndex": 0, "delta": {"text": "through the relay"}}),
              _event("contentBlockStop", {"contentBlockIndex": 0}),
              _event("messageStop", {"stopReason": "end_turn"}),
              _event("metadata", {"usage": {"inputTokens": 3, "outputTokens": 4, "totalTokens": 7},
                                  "metrics": {"latencyMs": 1}})]
    assert [h[":event-type"] for h, _ in rs._aws_eventstream_frames(_Chunks(frames))] == [
        "messageStart", "contentBlockDelta", "contentBlockDelta", "contentBlockStop", "messageStop", "metadata"]
    go_on = threading.Event()
    go_on.set()
    up = _Stub(_streaming_reply(frames, "application/vnd.amazon.eventstream", go_on))
    try:
        env = _hermes_bedrock_env(tmp_path, Auth(aws_region="us-west-2", aws_access_key_id=AKID,
                                                 aws_secret_access_key=SECRET))
        _upstream_to(relay, env["AWS_ACCESS_KEY_ID"], up.base)
        for k in ("AWS_REGION", "AWS_DEFAULT_REGION", "AWS_ENDPOINT_URL_BEDROCK_RUNTIME", "AWS_ACCESS_KEY_ID",
                  "AWS_SECRET_ACCESS_KEY"):
            aws_sandbox.setenv(k, env[k])     # botocore reads AWS_DEFAULT_REGION; hermes's env has both
        client = boto3.session.Session().client("bedrock-runtime")
        out = client.converse_stream(modelId=MODEL, messages=[{"role": "user", "content": [{"text": "hi"}]}])
        text = "".join(e["contentBlockDelta"]["delta"]["text"] for e in out["stream"] if "contentBlockDelta" in e)
        assert text == "hello through the relay"
        assert up.requests[0]["path"] == f"/model/{urllib.parse.quote(MODEL, safe='')}/converse-stream"
        _assert_signed_with_the_real_pair(up.requests[0], up.base, "us-west-2", "")
    finally:
        up.close()


class _Chunks:
    """A response-like object over fixed chunks, for the relay's own eventstream reader."""

    def __init__(self, chunks):
        self._chunks = list(chunks)

    def read1(self, _n):
        return self._chunks.pop(0) if self._chunks else b""


# ── the turn: no AWS or GCP secret in its environment, argv or files ────────────────────────────
def _launch(monkeypatch, tmp_path, backend, provider, auth, model):
    launched: dict = {}
    started = threading.Event()

    def fake_turn(turn_id, cmd, env, cwd, *a, **k):
        launched.update(argv=list(cmd), env=dict(env), cwd=cwd)
        started.set()

    def fake_hermes(turn_id, cwd, env, model, provider, prompt, *a):
        # the hermes command line is built from these alone (see _run_hermes_bg)
        launched.update(argv=["hermes", "-z", prompt, "--provider", provider, "--model", model,
                              *[str(x) for x in a]], env=dict(env), cwd=cwd)
        started.set()
    monkeypatch.setattr(rs, "_run_turn_bg", fake_turn)
    monkeypatch.setattr(rs, "_run_hermes_bg", fake_hermes)
    cwd = tmp_path / "w"
    cwd.mkdir(exist_ok=True)
    rs.turn(rs.TurnReq(backend=backend, provider=provider, model=model, prompt="say hi", auth=auth, cwd=str(cwd)))
    assert started.wait(10), "the turn was never launched"
    return launched


_RELAY_ORIGIN = r"http://127\.0\.0\.1:\d+"
_TOKEN = r"hr-relay-[0-9a-f]{32}"
_AWS_NAMES = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_BEARER_TOKEN_BEDROCK")


@pytest.mark.parametrize("auth", [
    Auth(aws_region="us-west-2", aws_access_key_id=AKID, aws_secret_access_key=SECRET, aws_session_token=SESSION),
    Auth(aws_region="us-west-2", aws_bearer_token=BEARER),
], ids=["key-pair", "api-key"])
def test_a_claude_bedrock_turn_carries_no_aws_secret(relay, monkeypatch, tmp_path, auth):
    got = _launch(monkeypatch, tmp_path, "claude", "bedrock", auth, MODEL)
    env = got["env"]
    assert _leaks(AWS_SECRETS, env, got["argv"], str(tmp_path)) == []
    assert not [n for n in _AWS_NAMES if n in env]
    assert env["CLAUDE_CODE_USE_BEDROCK"] == "1" and env["CLAUDE_CODE_SKIP_BEDROCK_AUTH"] == "1"
    assert env["AWS_REGION"] == "us-west-2"
    m = re.fullmatch(rf"({_RELAY_ORIGIN})/({_TOKEN})", env["ANTHROPIC_BEDROCK_BASE_URL"])
    assert m, env["ANTHROPIC_BEDROCK_BASE_URL"]
    upstream, cred, flags = relay["routes"][m.group(2)]
    assert upstream == "https://bedrock-runtime.us-west-2.amazonaws.com"
    assert flags["cloud"] == "bedrock" and flags["region"] == "us-west-2"
    assert (cred.bearer == BEARER) if auth.aws_bearer_token else (cred.secret_access_key == SECRET)
    assert "--model" in got["argv"] and MODEL in got["argv"]


def test_a_claude_vertex_turn_carries_no_service_account(relay, monkeypatch, tmp_path):
    sa, _ = _service_account("https://oauth2.googleapis.com/token", project="fake-project-123")
    auth = Auth(gcp_region="europe-west1", gcp_sa_json=json.dumps(sa))     # the project from the account
    got = _launch(monkeypatch, tmp_path, "claude", "vertex", auth, "claude-sonnet-4-5@20250929")
    env = got["env"]
    assert _leaks(_sa_secrets(sa), env, got["argv"], str(tmp_path)) == []
    assert list(tmp_path.rglob(".gcp-sa.json")) == []
    assert "GOOGLE_APPLICATION_CREDENTIALS" not in env
    assert env["CLAUDE_CODE_USE_VERTEX"] == "1" and env["CLAUDE_CODE_SKIP_VERTEX_AUTH"] == "1"
    assert env["ANTHROPIC_VERTEX_PROJECT_ID"] == "fake-project-123" and env["CLOUD_ML_REGION"] == "europe-west1"
    m = re.fullmatch(rf"({_RELAY_ORIGIN})/({_TOKEN})/v1", env["ANTHROPIC_VERTEX_BASE_URL"])
    assert m, env["ANTHROPIC_VERTEX_BASE_URL"]
    upstream, _cred, flags = relay["routes"][m.group(2)]
    assert upstream == "https://europe-west1-aiplatform.googleapis.com"
    assert flags["cloud"] == "vertex" and flags["project"] == "fake-project-123"


@pytest.mark.parametrize("auth", [
    Auth(aws_region="us-west-2", aws_access_key_id=AKID, aws_secret_access_key=SECRET, aws_session_token=SESSION),
    Auth(aws_region="us-west-2", aws_bearer_token=BEARER),
], ids=["key-pair", "api-key"])
def test_a_hermes_bedrock_turn_carries_no_aws_secret(relay, monkeypatch, tmp_path, auth):
    got = _launch(monkeypatch, tmp_path, "hermes", "bedrock", auth, MODEL)
    env = got["env"]
    assert _leaks(AWS_SECRETS, env, got["argv"], str(tmp_path)) == []
    origin = env["AWS_ENDPOINT_URL_BEDROCK_RUNTIME"]
    assert re.fullmatch(_RELAY_ORIGIN, origin) and env["ANTHROPIC_BEDROCK_BASE_URL"] == origin
    assert env["AWS_REGION"] == env["AWS_DEFAULT_REGION"] == "us-west-2"
    if auth.aws_bearer_token:
        tok = env["AWS_BEARER_TOKEN_BEDROCK"]
        assert "AWS_ACCESS_KEY_ID" not in env and "AWS_SECRET_ACCESS_KEY" not in env
    else:
        tok = env["AWS_ACCESS_KEY_ID"]
        assert env["AWS_SECRET_ACCESS_KEY"] == "hr-relay-placeholder"
        assert "AWS_BEARER_TOKEN_BEDROCK" not in env
    assert "AWS_SESSION_TOKEN" not in env
    assert re.fullmatch(_TOKEN, tok) and relay["routes"][tok][2]["cloud"] == "bedrock"


def test_the_runners_own_cloud_credentials_never_reach_a_turn(relay, monkeypatch, tmp_path):
    ambient = {"AWS_BEARER_TOKEN_BEDROCK": "fake-ambient-bedrock-key-0123456789",
               "AWS_ACCESS_KEY_ID": "AKIA_FAKE_AMBIENT_KEY_01",
               "AWS_SECRET_ACCESS_KEY": "fake-ambient-secret-0123456789",
               "AWS_SESSION_TOKEN": "fake-ambient-session-0123456789",
               "GOOGLE_APPLICATION_CREDENTIALS": "/fake/ambient/service-account.json"}
    for k, v in ambient.items():
        monkeypatch.setenv(k, v)
    for k in ("AWS_BEARER_TOKEN_BEDROCK", "GOOGLE_APPLICATION_CREDENTIALS", "AWS_SECRET_ACCESS_KEY",
              "AWS_SESSION_TOKEN"):
        assert k not in rs._child_env()
    keys = Auth(aws_region="us-west-2", aws_access_key_id=AKID, aws_secret_access_key=SECRET)
    for backend in ("claude", "hermes"):
        got = _launch(monkeypatch, tmp_path, backend, "bedrock", keys, MODEL)
        assert _leaks((*ambient.values(), *AWS_SECRETS), got["env"], got["argv"]) == [], backend
    sa, _ = _service_account("https://oauth2.googleapis.com/token")
    got = _launch(monkeypatch, tmp_path, "claude", "vertex", Auth(gcp_sa_json=json.dumps(sa)), "claude-haiku-4-5@20251001")
    # an access key id alone is an identifier, not a secret, and a vertex turn leaves AWS names alone
    secret_ambient = [v for k, v in ambient.items() if k != "AWS_ACCESS_KEY_ID"]
    assert _leaks((*secret_ambient, *_sa_secrets(sa)), got["env"], got["argv"]) == []


def test_a_bedrock_turn_without_a_credential_of_its_own_keeps_the_aws_chain(relay, monkeypatch, tmp_path):
    """No key in the connection (an instance role): nothing to keep from the agent, no route."""
    got = _launch(monkeypatch, tmp_path, "claude", "bedrock", Auth(aws_region="eu-central-1"), MODEL)
    assert got["env"]["AWS_REGION"] == "eu-central-1" and "ANTHROPIC_BEDROCK_BASE_URL" not in got["env"]
    env: dict = {}
    rs._hermes_prepare_env("bedrock", Auth(), str(tmp_path), env, model=MODEL)
    assert env["AWS_REGION"] == "us-east-1" and "AWS_ENDPOINT_URL_BEDROCK_RUNTIME" not in env
    assert relay["routes"] == {}


def test_a_stale_service_account_file_is_removed_when_a_turn_starts(relay, monkeypatch, tmp_path):
    cwd = tmp_path / "w"
    cwd.mkdir()
    (cwd / ".gcp-sa.json").write_text('{"private_key": "-----BEGIN " "PRIVATE KEY-----FAKESTALE"}')
    got = _launch(monkeypatch, tmp_path, "claude", "anthropic", Auth(api_key="sk-fake-anthropic"), "claude-haiku-4-5")
    assert not (cwd / ".gcp-sa.json").exists()
    assert _leaks(("FAKESTALE",), got["env"], got["argv"], str(cwd)) == []
    # a link is removed itself, never followed
    outside = tmp_path / "outside.json"
    outside.write_text("keep me")
    os.symlink(outside, cwd / ".gcp-sa.json")
    _launch(monkeypatch, tmp_path, "hermes", "bedrock", Auth(aws_region="us-east-1"), MODEL)
    assert not os.path.lexists(cwd / ".gcp-sa.json") and outside.read_text() == "keep me"


def test_a_vertex_turn_with_an_unreadable_key_writes_nothing(relay, monkeypatch, tmp_path):
    cwd = tmp_path / "w"
    cwd.mkdir()
    env: dict = {"HOME": str(cwd / ".harness" / "home")}
    bad = json.dumps({"client_email": "x@y.iam.gserviceaccount.com",
                      "private_key": "-----BEGIN " "PRIVATE KEY-----FAKEFAKE\n-----END PRIVATE KEY-----\n"})
    with pytest.raises(rs.HTTPException) as e:
        rs._build_claude("vertex", Auth(gcp_sa_json=bad, gcp_project="p"), "m", "hi", 5, str(cwd), env)
    assert e.value.status_code == 400 and "FAKEFAKE" not in e.value.detail
    assert _leaks(("FAKEFAKE",), env, [], str(cwd)) == []
    assert list(cwd.rglob(".gcp-sa.json")) == []


def test_a_provider_refusal_on_a_cloud_route_is_the_turns_reason(relay):
    """A refused cloud call kept nothing on the route, so a hermes turn that AWS refused said "gave no reason"
    (measured on real AWS 2026-11-03). The next call starts clean: an earlier refusal is not its reason."""
    words = "User: arn:aws:iam::123456789012:user/x is not authorized to perform: bedrock:InvokeModel"
    refuse, fine = _json_reply({"message": words}, status=403), _json_reply({"ok": 1})
    answers = [refuse, fine]
    up = _Stub(lambda h, req: answers.pop(0)(h, req))
    try:
        origin, tok = rs._bedrock_relay_route("us-east-1", bearer=BEARER)
        _upstream_to(relay, tok, up.base)
        flags = relay["routes"][tok][2]
        conn, resp = _call(origin, f"/{tok}/model/m/invoke", b"{}", {"content-type": "application/json"})
        assert resp.status == 403 and words in resp.read().decode()      # byte for byte to the client, as before
        conn.close()
        assert flags["last_refusal"] == "403: " + words
        # the turn finds it from the base address Claude Code was handed, and from hermes's placeholder
        assert rs._turn_relay_flags({"ANTHROPIC_BEDROCK_BASE_URL": f"{origin}/{tok}"}) is flags
        assert rs._turn_relay_flags({"AWS_BEARER_TOKEN_BEDROCK": tok}) is flags
        assert rs._turn_relay_flags({"ANTHROPIC_VERTEX_BASE_URL": f"{origin}/{tok}/v1"}) is flags
        assert rs._turn_relay_flags({"PATH": "/usr/bin", "X": "https://example.com/not-a-route"}) == {}
        conn, resp = _call(origin, f"/{tok}/model/m/invoke", b"{}", {"content-type": "application/json"})
        assert resp.status == 200
        resp.read(); conn.close()
        assert "last_refusal" not in flags
    finally:
        up.close()
