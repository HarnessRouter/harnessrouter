"""Making media as an ORDINARY MCP server on a harness — the chain that picks a model and says
which one it picked, the jobs that outlive the turn, the canvas, the export, and the one rule that
matters more than any of them: the provider key never comes back out.

Every request in this file goes through the real app with local backing (SQLite + encrypted files
in a temp dir), so what is asserted is what a caller would actually receive. Every PROVIDER call
goes through an httpx MockTransport, so the five adapters are genuinely exercised — the URL, the
body, the parsing — and nothing is spent doing it.

THE CREDENTIAL CHECK IS NOT ONE TEST. `_seen` records every response body and every line the
gateway printed, and the last tests assert the provider key appears in none of them — so a route
added later that leaks it fails this file even if nobody writes a test for that route.

Tests that need a REAL generation are skipped unless HR_TEST_TOKENROUTER_KEY is set, and when it is
they use the shortest duration and the smallest size the model allows, one call each, reusing task
ids rather than resubmitting. No generation is ever looped.
"""
from __future__ import annotations

import ast
import asyncio
import base64
import copy
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Set BEFORE importing app: the backing, the internal key and the encryption passphrase are all
# read at import time, exactly as they are in a running container.
_DATA = tempfile.mkdtemp(prefix="hr-mediatest-")
os.environ.update({
    "HR_BACKING": "local", "HR_DATA_DIR": _DATA,
    # Self-hosted, a workspace is a live directory. The default is /data/workspaces, which does
    # not exist on a laptop — so the projection would silently not happen and this file would be
    # asserting nothing.
    "HARNESS_WORKSPACE": os.path.join(_DATA, "workspaces"),
    "HR_SECRET_KEY": "test-passphrase-not-a-real-one",
    "HARNESS_INTERNAL_KEY": "test-internal-key",
    "HARNESS_GLOBAL_TENANT": "global",
    # A base URL, so the MCP server is offered to a turn the way it would be in production — and
    # so it is an address this gateway recognises as its own.
    "HARNESS_PUBLIC_BASE_URL": "https://gateway.example",
    "HR_POOL_AUTH": "none",
    # Self-hosted: the one operator is the administrator, which is what lets this file connect the
    # provider integration the media server resolves its key from.
    "HR_IDENTITY_MODE": "off",
    # The sweeper must not race the assertions; every test drives _media_sweep itself.
    "HR_MEDIA_SWEEP_S": "3600",
})

import app  # noqa: E402
import media_plane  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

# The sentinel. Every assertion about "the key never comes out" is about this exact string.
PROVIDER_KEY = "sk-tr-SENTINEL-do-not-leak-4f7a9b21"
# The SECOND deployment credential. A separate sentinel on purpose: with one string for both
# providers, "the ElevenLabs key was not sent to TokenRouter" is unprovable, and that is precisely
# the mistake a second auth style makes possible.
ELEVEN_KEY = "sk_el-SENTINEL-do-not-leak-90c3ad12"

ORG = "testorg"
HEADERS = {"x-harness-internal": "test-internal-key", "x-harness-org": ORG,
           "x-harness-member": "tester@example.com"}

MCP_URL = "https://gateway.example/v1/mcp/media"
ENTRY_ID = "mcp.media"
TR = "https://api.tokenrouter.com/v1"
EL = "https://api.elevenlabs.io/v1"

# The kit that provisions the media server. Attaching it is something the kit that uses it drives,
# so every attach in this file goes through launch — there is no other way in.
_KIT = {"id": "media", "title": "Videos", "app": {"route": "/kits/media"},
        "harness": {"name": "Videos", "mcp_servers": [],
                    "launch": {"media": {"name": "media", "id": ENTRY_ID}},
                    "recommended": [{"base": "claude-code", "model": "claude-opus-5"}]}}

LIVE_KEY = os.environ.get("HR_TEST_TOKENROUTER_KEY", "").strip()
needs_live = pytest.mark.skipif(not LIVE_KEY,
                               reason="no HR_TEST_TOKENROUTER_KEY — a real generation costs money")
needs_ffmpeg = pytest.mark.skipif(not media_plane.have_ffmpeg(), reason="no ffmpeg on this box")

# Every response body and every printed line this file produced. See the module docstring.
_seen: list[str] = []
# Every provider request the mock transport saw, for the test currently running.
_calls: list[dict] = []
# The same, for the whole file and never cleared — so "the key DID reach the provider" is not an
# assertion about whichever test happened to run last.
_all_calls: list[dict] = []


# ── tiny real media, so verification is exercised on bytes and not on a stub ──────
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
WAV_SILENCE = (b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x40\x1f\x00\x00"
               b"\x80>\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00")
# One MPEG-1 Layer III frame header and its payload. ElevenLabs answers with mp3 BYTES and no JSON
# at all, so what the raw shapes are fed here has to be bytes that `sniff` genuinely identifies —
# a JSON stub would let the raw path pass a test the product fails on the first real call.
MP3_SILENCE = b"\xff\xfb\x90\x00" + bytes(414)


def _mp4(seconds: float = 1.0, size: str = "128x72") -> bytes:
    """A real, tiny mp4. ffprobe has to be able to read a duration out of it, because the gateway
    refuses a video it cannot measure — a stub of four bytes would pass a test the product fails."""
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "c.mp4")
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-f", "lavfi",
                        "-i", f"color=c=blue:s={size}:d={seconds}", "-f", "lavfi",
                        "-i", f"anullsrc=r=44100:cl=stereo:d={seconds}",
                        "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                        "-t", str(seconds), out], capture_output=True, check=True)
        return Path(out).read_bytes()


# ── the provider, mocked at the transport ────────────────────────────────────────
class Provider:
    """A stand-in for the two connected providers that answers per model, records every request,
    and can be told to fail a specific one. The adapters run for real against it.

    TokenRouter and ElevenLabs are both here because they are both connected in this deployment,
    and because the interesting failures are the ones that only exist once there are two: a key
    sent in the wrong header, or to the wrong host.
    """

    def __init__(self):
        self.fail: dict[str, tuple[int, dict]] = {}   # model -> (status, body)
        self.tasks: dict[str, dict] = {}              # task id -> poll record
        self.video_bytes = b""
        self.polls: dict[str, list] = {}              # task id -> queued poll answers
        # Where a finished render says it lives, and how that address answers. Both are the
        # PROVIDER's to choose, which is the whole reason they are knobs here.
        self.result_url = "https://cdn.provider.example/out.mp4"
        self.cdn_status = 200
        # What the raw shapes answer with, and how they label it. Both are knobs because the whole
        # point of those two adapters is that the SAME endpoint answers audio or JSON.
        self.audio_bytes = MP3_SILENCE
        self.audio_ctype = "audio/mpeg"

    def queue_poll(self, task_id: str, *answers) -> None:
        self.polls.setdefault(task_id, []).extend(answers)

    def handle(self, req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        # A JSON body where there is one. ElevenLabs is asked in JSON like everything else — it is
        # the ANSWER that is binary — but a request body is never assumed to parse.
        try:
            body = json.loads(req.content or b"{}") if req.content else {}
        except ValueError:
            body = {}
        call = {"method": req.method, "url": url, "body": body,
                "auth": req.headers.get("authorization", ""),
                "xi": req.headers.get("xi-api-key", "")}
        _calls.append(call)
        _all_calls.append(call)

        # ── ElevenLabs: raw audio out, JSON only when it goes wrong ──────────────
        if url.startswith(EL):
            model = ("elevenlabs/music-v1" if url.endswith("/music")
                     else str(body.get("model_id") or ""))
            if model in self.fail:
                st, b = self.fail[model]
                return httpx.Response(st, json=b)
            return httpx.Response(200, content=self.audio_bytes,
                                  headers={"content-type": self.audio_ctype})

        if url.endswith("/video/generations") and req.method == "POST":
            model = body.get("model") or ""
            if model in self.fail:
                st, b = self.fail[model]
                return httpx.Response(st, json=b)
            tid = f"task_{len(self.tasks) + 1}"
            self.tasks[tid] = {"model": model}
            return httpx.Response(200, json={"id": tid, "task_id": tid, "object": "video",
                                             "model": model, "status": "queued"})

        if "/video/generations/" in url and req.method == "GET":
            tid = url.rsplit("/", 1)[-1]
            queued = self.polls.get(tid)
            if queued:
                return queued.pop(0)
            return httpx.Response(200, json={"code": "success", "message": "", "data": {
                "id": tid, "task_id": tid, "platform": "mock", "status": "SUCCESS",
                "result_url": self.result_url}})

        if url.endswith("/images/generations"):
            model = body.get("model") or ""
            if model in self.fail:
                st, b = self.fail[model]
                return httpx.Response(st, json=b)
            return httpx.Response(200, json={"created": 1, "background": "opaque",
                                             "data": [{"b64_json": base64.b64encode(PNG_1PX).decode()}]})

        if ":generateContent" in url:
            model = url.split("/models/")[-1].split(":")[0]
            if model in self.fail:
                st, b = self.fail[model]
                return httpx.Response(st, json=b)
            if model == "google/gemini-3-pro-image-preview":
                # 200 OK, no parts, and it bills. Kept honest here because it is the exact shape
                # the "a 200 is not a success" rule exists for.
                return httpx.Response(200, json={"candidates": [{"content": {"parts": []},
                                                                 "finishReason": "STOP"}]})
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [
                {"thoughtSignature": "x" * 64},
                {"inlineData": {"mimeType": "image/png",
                                "data": base64.b64encode(PNG_1PX).decode()}}]}}]})

        if url.endswith("/chat/completions"):
            model = body.get("model") or ""
            if model in self.fail:
                st, b = self.fail[model]
                return httpx.Response(st, json=b)
            if body.get("modalities"):
                if body.get("stream"):
                    frames = [
                        'data: ' + json.dumps({"choices": [{"delta": {"audio": {
                            "data": base64.b64encode(WAV_SILENCE[:22]).decode(),
                            "transcript": "Hello "}}}]}),
                        'data: ' + json.dumps({"choices": [{"delta": {"audio": {
                            "data": base64.b64encode(WAV_SILENCE[22:]).decode(),
                            "transcript": "there."}}}]}),
                        "data: [DONE]"]
                    return httpx.Response(200, text="\n\n".join(frames) + "\n\n",
                                          headers={"content-type": "text/event-stream"})
                return httpx.Response(200, json={"choices": [{"message": {"audio": {
                    "data": base64.b64encode(WAV_SILENCE).decode(),
                    "transcript": "Hello! It's great to talk with you."}}}]})
            return httpx.Response(200, json={"choices": [{"message": {"content": None, "images": [
                {"image_url": {"url": "data:image/png;base64,"
                                      + base64.b64encode(PNG_1PX).decode()}}]}}],
                "usage": {"cost": 0.048188}})

        if url.startswith("https://cdn.provider.example/"):
            data = self.video_bytes or PNG_1PX
            ctype = "video/mp4" if url.endswith(".mp4") else "image/png"
            return httpx.Response(self.cdn_status, content=data,
                                  headers={"content-type": ctype})

        # ANY other host. A relay that names one has moved the gateway somewhere it chose, so
        # this answers rather than 404s — a refusal here would hide the fetch under a failure.
        return httpx.Response(200, content=b'{"SecretAccessKey":"AWSSECRET"}',
                              headers={"content-type": "application/json"})


@pytest.fixture(autouse=True)
def resolvable_cdn(monkeypatch):
    """The mock provider's CDN lives on a `.example` name, and `.example` resolves nowhere. This
    server will not fetch a finished render from an address it could not classify (see
    _provider_url_check), so the fake CDN has to resolve the way a real one does — otherwise every
    test that lands a file would quietly be asserting the refusal instead.

    Only `.example` is answered here, to a public address. Everything else falls through to the
    real resolver, so the SSRF assertions still mean what they say.
    """
    import socket
    real = socket.getaddrinfo

    def fake(host, port, *a, **kw):
        if str(host).endswith(".example"):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                     ("93.184.216.34", int(port or 443)))]
        return real(host, port, *a, **kw)

    monkeypatch.setattr(socket, "getaddrinfo", fake)


@pytest.fixture()
def provider(monkeypatch):
    p = Provider()
    _calls.clear()
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: p.handle(r)),
                               timeout=30)
    monkeypatch.setattr(app, "_media_client", lambda: client)
    app._media_quarantine.clear()
    yield p
    asyncio.run(client.aclose())


# ── the harness under test ───────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def client():
    with TestClient(app.app) as c:
        yield c


class Rec:
    """A client whose every response body is recorded before it is returned."""

    def __init__(self, c: TestClient):
        self.c = c

    def _do(self, method: str, path: str, **kw):
        r = getattr(self.c, method)(path, headers={**HEADERS, **(kw.pop("headers", None) or {})},
                                    **kw)
        _seen.append(r.text)
        return r

    def get(self, path, **kw):
        return self._do("get", path, **kw)

    def post(self, path, **kw):
        return self._do("post", path, **kw)

    def put(self, path, **kw):
        return self._do("put", path, **kw)

    def delete(self, path, **kw):
        return self._do("delete", path, **kw)


@pytest.fixture(scope="module")
def api(client):
    return Rec(client)


def _connect_provider(key: str = PROVIDER_KEY, eleven: str = ELEVEN_KEY) -> None:
    """The deployment's own credentials — one per provider, which is what every media call
    resolves and what nothing may ever return.

    TWO entries, because this deployment has two connected providers and the difference between
    them is the point: they are signed in different headers, and an integration document with one
    provider in it cannot show that the right key went to the right host.

    Written straight into the document the media server reads, rather than through the admin
    route: how a key got connected is another surface's business, and going through that route
    would make this file depend on the identity mode whichever test module imported `app` first
    happened to set."""
    doc = [{"name": "tr", "provider": "tokenrouter",
            "config": {"api_key": key, "base_url": TR}}]
    if eleven:
        doc.append({"name": "el", "provider": "elevenlabs",
                    "config": {"api_key": eleven, "base_url": EL}})
    asyncio.run(app._vault_put(app.GLOBAL_TENANT, app._INTEGRATIONS_KEY, json.dumps(doc)))


@pytest.fixture(scope="module", autouse=True)
def integration(api):
    _connect_provider()
    # Self-hosted, a workspace is a live directory, and its root is read at import time from
    # HARNESS_WORKSPACE. Bound here to THIS file's temp dir so the projection is real wherever the
    # process happened to start — a projection that silently lands nowhere asserts nothing.
    app.BACKING.workspace = app.backing.LocalWorkspaceFiles(os.path.join(_DATA, "workspaces"))
    return True


@pytest.fixture()
def kit(monkeypatch):
    """This kit, with a fresh id per test so launch's idempotence isn't a shared fixture."""
    kid = f"media{int(time.time() * 1e6) % 10_000_000}"
    monkeypatch.setattr(app, "_kits", lambda: {kid: {**_KIT, "id": kid}})
    return kid


def _launch(api, kit) -> dict:
    r = api.post(f"/v1/kits/{kit}/launch", json={})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture()
def harness(api, kit):
    return _launch(api, kit)["harnessId"]


@pytest.fixture()
def session(api, harness):
    """A session that belongs to this org AND to this harness, so both ownership checks on every
    app route are real.

    `harness_id` is the field the product's own session-create path stamps (_start_session), and
    therefore the field the media routes read. Writing anything else here would make the bind
    testable and absent.
    """
    return _session_of(harness)


def _session_of(hid: str, org: str = ORG) -> str:
    sid = "sess_" + os.urandom(6).hex()
    asyncio.run(app._vg_upsert("HarnessSession", sid,
                               {"tenant": org, "status": "idle", "turn_status": "idle",
                                "harness_id": hid}))
    return sid


def _due(jid: str) -> None:
    """Make a job due for its next poll right now.

    Without this every advance is a no-op — next_poll_at is 20 s out — and every assertion after
    it is vacuous. Real time is the only other way to get there.
    """
    job = asyncio.run(app._media_job_get(jid))
    job["next_poll_at"] = 0
    asyncio.run(app._media_job_save(job))


def _vertex(hid: str) -> dict:
    return asyncio.run(app.BACKING.graph.get(hid, label="Harness"))


def _stored(hid: str) -> list:
    return json.loads(_vertex(hid).get("mcp_servers") or "[]")


def _entry_of(hid: str) -> dict:
    return next(s for s in _stored(hid) if s.get("id") == ENTRY_ID)


def _key(hid: str) -> str:
    return app._vault_key(_entry_of(hid)["auth"])


def _cred(hid: str, sid: str = "") -> str:
    return app._mint_hosted_cred(hid, sid, _key(hid))


def _rpc(client, token, method, params=None, rid=1):
    body = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
    r = client.post("/v1/mcp/media", json=body,
                    headers={"authorization": f"Bearer {token}"} if token else {})
    _seen.append(r.text)
    return r


def _call(client, tok, name, args=None) -> dict:
    r = _rpc(client, tok, "tools/call", {"name": name, "arguments": args or {}})
    assert r.status_code == 200, r.text
    return r.json()["result"]


def _ok(res: dict) -> dict:
    assert res.get("isError") is not True, res["content"][0]["text"]
    return json.loads(res["content"][0]["text"])


def _err(res: dict) -> str:
    assert res.get("isError") is True, res
    return res["content"][0]["text"]


def _el(cap: str) -> dict:
    """The ElevenLabs candidate in a capability's chain, found by PROVIDER — so a test says what it
    means ("the one that is not TokenRouter's") instead of repeating a model id the catalog owns."""
    return next(c for c in media_plane.capability(cap)["candidates"]
                if c.get("provider") == "elevenlabs")


def _save_config(api, hid: str, servers: list, name="Videos"):
    return api.put(f"/v1/harnesses/{hid}",
                   json={"name": name, "base": "claude-code", "mcp_servers": servers})


# ══ the entry, and where the credential is not ═══════════════════════════════════

def test_launching_provisions_an_entry_indistinguishable_from_a_third_party_one(api, kit):
    out = _launch(api, kit)
    hid = out["harnessId"]
    entry = _entry_of(hid)
    assert entry["url"] == MCP_URL and entry["transport"] == "http"
    assert entry["auth"].startswith("vault:" + app._HOSTED_SECRET_PREFIX)
    # THE WHOLE POINT: its key set is a third-party entry's key set. Nothing stored distinguishes
    # them, so nothing can branch on the difference.
    assert set(entry) == {"id", "name", "url", "transport", "auth", "enabled"}
    assert PROVIDER_KEY not in json.dumps(_vertex(hid))


def test_the_record_holds_a_binding_and_no_secret_at_all(api, kit):
    """A database record holds a customer's connection string. This one holds who it is for and
    nothing else — the provider credential is the deployment's, and must never become a
    per-harness secret."""
    hid = _launch(api, kit)["harnessId"]
    rec = asyncio.run(app._hosted_record(ORG, _key(hid)))
    assert rec["server"] == "media" and rec["harness"] == hid
    assert set(rec) == {"server", "harness", "updated_at"}
    assert PROVIDER_KEY not in json.dumps(rec)


def test_launching_needs_no_encryption_passphrase(api, kit, monkeypatch):
    """The database's record holds a customer's connection string, so an instance that cannot
    encrypt must refuse it. This record holds a binding and no credential at all, and refusing
    would block a feature with nothing to protect."""
    real = app.BACKING.secrets.put

    async def no_passphrase(tenant, name, value, *, require_encryption=False):
        if require_encryption:
            raise app.backing.SecretsNotConfigured("set HR_SECRET_KEY")
        return await real(tenant, name, value)

    monkeypatch.setattr(app.BACKING.secrets, "put", no_passphrase)
    out = _launch(api, kit)
    assert out["created"] is True
    rec = asyncio.run(app._hosted_record(ORG, _key(out["harnessId"])))
    assert rec == {"server": "media", "harness": out["harnessId"],
                   "updated_at": rec["updated_at"]}


def test_launch_is_idempotent(api, kit):
    first = _launch(api, kit)
    key_before = _key(first["harnessId"])
    again = _launch(api, kit)
    assert again["harnessId"] == first["harnessId"] and again["created"] is False
    assert len([e for e in _stored(first["harnessId"]) if e.get("id") == ENTRY_ID]) == 1
    assert _key(first["harnessId"]) == key_before


def test_a_turn_is_handed_a_capability_and_never_the_provider_key(harness):
    """Invariant 1, at the funnel every plugin passes through: grep the WHOLE resolved plugin list
    for the sentinel and find nothing, then confirm what the sandbox actually got."""
    v = asyncio.run(app._harness_vertex(harness))
    mcp, *_ = asyncio.run(app._harness_plugins(harness, ORG, hv=v, sid="sess-42"))
    entry = next(m for m in mcp if m["name"] == "media")
    assert entry["url"] == MCP_URL
    assert entry["auth"].startswith("hrs_")
    assert app._verify_hosted_cred(entry["auth"]) == (harness, "sess-42", _key(harness))
    assert PROVIDER_KEY not in json.dumps(mcp)


def test_the_hosted_namespace_never_resolves_as_a_bearer_token(harness, capsys):
    """The refusal at the funnel every outbound credential passes through, so it holds for callers
    that do not exist yet."""
    capsys.readouterr()
    assert asyncio.run(app._resolve_mcp_auth(ORG, f"vault:{_key(harness)}")) == ""
    assert "refusing to resolve" in capsys.readouterr().out


def test_an_entry_here_that_names_no_record_is_not_offered(api, kit):
    """A url of ours with a third-party auth is not a server we can serve: minting for it would
    hand out a capability to a record this harness does not have."""
    hid = api.post("/v1/harnesses", json={"name": "Bare", "base": "claude-code"}).json()["id"]
    assert _save_config(api, hid, [{"id": "mcp.fake", "name": "media", "url": MCP_URL,
                                    "transport": "http", "auth": "vault:harness-mcp-theirs",
                                    "enabled": True}]).status_code == 200
    v = asyncio.run(app._harness_vertex(hid))
    mcp, *_ = asyncio.run(app._harness_plugins(hid, ORG, hv=v, sid="s"))
    assert mcp == []


def test_one_harness_cannot_read_anothers_canvas(client, api, kit, harness):
    """The binding: `auth` is a client-writable field on an ordinary entry and harness ids are
    public, so a caller can write someone else's ref onto their own entry."""
    thief = api.post("/v1/harnesses", json={"name": "Thief", "base": "claude-code"}).json()["id"]
    stolen = _key(harness)
    assert _save_config(api, thief, [{"id": ENTRY_ID, "name": "media", "url": MCP_URL,
                                      "transport": "http", "auth": f"vault:{stolen}",
                                      "enabled": True}], name="Thief").status_code == 200
    tok = app._mint_hosted_cred(thief, "sess1", stolen)
    assert "no media tools are connected" in _err(_call(client, tok, "describe_canvas")).lower()


def test_the_session_comes_from_the_credential_and_never_from_arguments():
    """Invariant 5: no tool has a `session` property and every schema is closed, so a call naming
    another session is rejected by the schema rather than by a check someone has to remember."""
    for tool in app._MEDIA_MCP_TOOLS:
        schema = tool["inputSchema"]
        assert schema.get("additionalProperties") is False, tool["name"]
        assert "session" not in (schema.get("properties") or {}), tool["name"]
        assert "harness" not in (schema.get("properties") or {}), tool["name"]


def test_a_credential_with_no_session_is_told_so_rather_than_generating(client, harness,
                                                                        provider):
    res = _call(client, _cred(harness, ""), "generate_video",
                {"prompt": "rain on a window", "seconds": 6})
    assert "no workspace" in _err(res)
    assert _calls == [], "a generation was submitted for a session that does not exist"


def test_the_endpoint_refuses_without_a_valid_credential(client, harness):
    assert _rpc(client, None, "tools/list").status_code == 401
    assert _rpc(client, "hrs_not-a-real-token", "tools/list").status_code == 401
    good = _cred(harness, "s1")
    forged = good[:-1] + ("a" if good[-1] != "a" else "b")
    assert _rpc(client, forged, "tools/list").status_code == 401


def test_a_deleted_harness_stops_answering_its_own_credential(client, api, kit):
    hid = _launch(api, kit)["harnessId"]
    tok = _cred(hid, "s1")
    api.delete(f"/v1/harnesses/{hid}")
    assert "cannot make media" in _err(_call(client, tok, "describe_canvas"))


def test_a_disabled_entry_is_not_handed_to_a_turn_and_its_endpoint_refuses(client, api, kit):
    """A token minted before the switch is valid for hours, so the refusal has to be at the
    endpoint too and not only where turns are built."""
    hid = _launch(api, kit)["harnessId"]
    tok = _cred(hid, "s1")
    assert _save_config(api, hid, [{**_entry_of(hid), "enabled": False}]).status_code == 200
    v = asyncio.run(app._harness_vertex(hid))
    mcp, *_ = asyncio.run(app._harness_plugins(hid, ORG, hv=v, sid="s1"))
    assert [m for m in mcp if m["name"] == "media"] == []
    assert "cannot make media" in _err(_call(client, tok, "describe_canvas"))


# ══ the protocol ═════════════════════════════════════════════════════════════════

def test_initialize_echoes_the_protocol_version_and_a_notification_is_a_202(client, harness):
    tok = _cred(harness, "s1")
    res = _rpc(client, tok, "initialize", {"protocolVersion": "2025-06-18"}).json()["result"]
    assert res["protocolVersion"] == "2025-06-18" and res["capabilities"]["tools"] == {}
    assert res["serverInfo"]["name"] == "media"
    n = client.post("/v1/mcp/media", headers={"authorization": f"Bearer {tok}"},
                    json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert n.status_code == 202


def test_the_tool_list_is_thirteen_tools(client, harness):
    tools = _rpc(client, _cred(harness, "s1"), "tools/list").json()["result"]["tools"]
    assert [t["name"] for t in tools] == [
        "list_capabilities", "generate_video", "generate_image", "generate_speech",
        "generate_music", "check_jobs", "describe_canvas", "place", "move", "arrange",
        "remove", "set_timeline", "export_timeline"]
    assert all(t["inputSchema"]["type"] == "object" for t in tools)


def test_an_unknown_tool_and_an_unknown_method_are_answered_not_crashed(client, harness):
    tok = _cred(harness, "s1")
    assert "No tool named" in _err(_call(client, tok, "make_a_feature_film"))
    assert _rpc(client, tok, "resources/list").json()["error"]["code"] == -32601


# ══ the chain ════════════════════════════════════════════════════════════════════

def test_the_chain_reports_the_model_that_actually_ran(client, harness, session, provider):
    """The owner's preferred model is rank 1 and broken. It is tried, it fails at submit, and the
    model reported is the one that took the job."""
    provider.fail["dreamina-seedance-2-5-hc"] = (400, {"message": "unknown model 'eva-video-2.5'"})
    out = _ok(_call(client, _cred(harness, session), "generate_video",
                    {"prompt": "rain on a window at night", "seconds": 6}))
    assert out["model"] == "MiniMax-Hailuo-2.3"
    assert out["capability"] == "text_to_video" and out["status"] == "running"
    assert out["attempts"][0]["model"] == "dreamina-seedance-2-5-hc"
    assert "eva-video-2.5" in out["attempts"][0]["error"]
    assert out["estimated_usd"] == 0.28


def test_a_submit_failure_is_never_quarantined_so_the_broken_model_self_heals(
        client, harness, session, provider):
    """A candidate that fails BEFORE a task id exists costs nothing to retry, which is exactly what
    lets rank 1 sit there permanently and start working the day the relay is fixed."""
    provider.fail["dreamina-seedance-2-5-hc"] = (400, {"message": "unknown model 'eva-video-2.5'"})
    tok = _cred(harness, session)
    _ok(_call(client, tok, "generate_video", {"prompt": "a", "seconds": 6}))
    assert "dreamina-seedance-2-5-hc" not in app._media_quarantine

    provider.fail.clear()                     # the relay is fixed
    out = _ok(_call(client, tok, "generate_video", {"prompt": "b", "seconds": 6}))
    assert out["model"] == "dreamina-seedance-2-5-hc", "the preferred model did not self-heal"


def test_a_two_hundred_with_no_media_is_a_failure_and_the_model_is_stood_down(
        client, harness, session, provider):
    """Invariant 7, with gemini-3-pro's exact response. It is excluded from the chain, so the
    assertion is that a candidate behaving that way is treated as failed AND quarantined."""
    empty = (200, {"candidates": [{"content": {"parts": []}, "finishReason": "STOP"}]})
    provider.fail["google/gemini-3.1-flash-lite-image"] = empty
    out = _ok(_call(client, _cred(harness, session), "generate_image", {"prompt": "a frame"}))
    assert out["model"] != "google/gemini-3.1-flash-lite-image"
    assert app._media_quarantine.get("google/gemini-3.1-flash-lite-image", 0) > time.time()
    assert "returned nothing" in out["attempts"][0]["error"]


def test_the_excluded_model_can_never_be_selected(client, harness, session, provider):
    """It is in the file so nobody re-adds it, and it must be unreachable from every chain."""
    for cand in media_plane.capability("text_to_image")["candidates"]:
        if cand["model"] == "google/gemini-3-pro-image-preview":
            assert cand["status"] == "excluded"
    assert media_plane.can_serve({"model": "x", "status": "excluded"}, {})
    for _ in range(3):
        out = _ok(_call(client, _cred(harness, session), "generate_image", {"prompt": "a"}))
        assert out["model"] != "google/gemini-3-pro-image-preview"


def test_image_to_video_never_degrades_to_text_to_video(client, harness, session, provider):
    """Invariant 9. MiniMax and happyhorse IGNORE an input image and bill for a text-only clip, so
    if no image-capable model works this capability has NO substitute and must refuse."""
    img = _ok(_call(client, _cred(harness, session), "generate_image", {"prompt": "a face"}))
    _calls.clear()
    for m in ("dreamina-seedance-2-5-hc", "kling-v3", "kling-v2-6"):
        app._media_quarantine[m] = time.time() + 900
    res = _call(client, _cred(harness, session), "generate_video",
                {"prompt": "the face turns", "seconds": 6, "from_image": img["job_id"]})
    text = _err(res)
    assert "No model is available for image_to_video" in text
    assert "you cannot connect one yourself" in text
    assert [c for c in _calls if "generations" in c["url"]] == [], "it submitted anyway"


def test_an_input_frame_is_sent_to_the_provider_and_never_written_onto_the_job(
        client, harness, session, provider):
    """Continuity is `from_image`, so this path carries a base64 frame on every call. A graph
    property has a size cap and a frame is megabytes, so what is WRITTEN DOWN is the media id and
    the bytes are re-read from our own store if the chain has to advance."""
    tok = _cred(harness, session)
    face = _ok(_call(client, tok, "generate_image", {"prompt": "a face"}))
    out = _ok(_call(client, tok, "generate_image",
                    {"prompt": "the same face, smiling", "from_image": face["media_id"]}))
    assert out["capability"] == "image_to_image"

    sent = _calls[-1]["body"]
    assert "inlineData" in json.dumps(sent), "the frame never reached the provider"

    raw = asyncio.run(app.BACKING.graph.get(out["job_id"], label="MediaJob"))
    stored = json.loads(raw["params_json"])
    assert "image" not in stored and "image_mime" not in stored
    assert stored["from_media"] == face["media_id"]
    assert len(raw["params_json"]) < 2000, "a frame was written onto the vertex"
    # And a job read back off the vertex can still advance, because the frame is re-readable.
    job = asyncio.run(app._media_job_get(out["job_id"]))
    assert job["params"]["from_media"] == face["media_id"]
    assert asyncio.run(app._media_read_image(session, face["media_id"]))[1]


def test_a_missing_input_frame_is_named_rather_than_generated_around(client, harness, session,
                                                                     provider):
    tok = _cred(harness, session)
    assert "No job with the id mjob_nope" in _err(
        _call(client, tok, "generate_video", {"prompt": "a", "seconds": 6,
                                              "from_image": "mjob_nope"}))
    assert "no media with the id med_nope" in _err(
        _call(client, tok, "generate_image", {"prompt": "a", "from_image": "med_nope"})).lower()


def test_the_watermarked_model_is_never_chosen_by_default(client, harness, session, provider):
    """Invariant 13: every other video candidate down, allow_watermark unset → the refusal, not
    a stamped clip nobody asked for."""
    for c in media_plane.capability("text_to_video")["candidates"]:
        if c["model"] != "happyhorse-1.0-t2v":
            app._media_quarantine[c["model"]] = time.time() + 900
    res = _call(client, _cred(harness, session), "generate_video", {"prompt": "a", "seconds": 6})
    assert "watermarks its output" in _err(res)

    out = _ok(_call(client, _cred(harness, session), "generate_video",
                    {"prompt": "a", "seconds": 6, "allow_watermark": True}))
    assert out["model"] == "happyhorse-1.0-t2v"


def test_parameter_fit_is_checked_before_health(client, harness, session, provider):
    """A model that cannot render 8 seconds is not a fallback for one that can — it is a different
    film. MiniMax does 6 and 10 only, so 8 must go past it rather than be rounded onto it."""
    provider.fail["dreamina-seedance-2-5-hc"] = (400, {"message": "unknown model"})
    out = _ok(_call(client, _cred(harness, session), "generate_video",
                    {"prompt": "a", "seconds": 8}))
    assert out["model"] == "kling-v3", "8 s was silently rounded onto a 6/10 s model"
    body = next(c["body"] for c in _calls
                if c["url"].endswith("/video/generations") and c["body"].get("model") == "kling-v3")
    assert body["duration"] == 8


def test_a_video_submit_without_a_duration_is_impossible(client, harness, session, provider):
    """Invariant 11: kling's own default is 15.041 s at ~$1.68, six times a 6 s MiniMax clip. The
    schema requires it, and every builder emits it."""
    assert app._MEDIA_MCP_TOOLS[1]["name"] == "generate_video"
    assert app._MEDIA_MCP_TOOLS[1]["inputSchema"]["required"] == ["prompt", "seconds"]
    _ok(_call(client, _cred(harness, session), "generate_video", {"prompt": "a", "seconds": 6}))
    for c in _calls:
        if c["url"].endswith("/video/generations"):
            assert c["body"].get("duration"), f"a clip was submitted with no duration: {c['body']}"


@pytest.mark.parametrize("cap,args,shape", [
    ("text_to_video", {"prompt": "p", "seconds": 6}, "video-generation"),
    ("text_to_image", {"prompt": "p", "size": "1920x1920"}, "image-generation"),
    ("text_to_image", {"prompt": "p"}, "gemini"),
    ("text_to_image", {"prompt": "p"}, "openai"),
    ("text_to_speech", {"prompt": "p", "voice": "alloy"}, "audio-chat"),
])
def test_only_whitelisted_params_are_forwarded(cap, args, shape):
    """Invariant 12, one case per shape. The relay silently ignores unknown params and submits the
    job anyway, so a typo would cost a full-price generation."""
    cand = next(c for c in media_plane.capability(cap)["candidates"]
                if c.get("shape") == shape and c.get("status") != "excluded")
    sub = media_plane.build_submit(cand, TR, {**args, "not_a_real_param": "boom",
                                              "resolution": "4k"})
    assert set(sub.tunables) <= media_plane.declared_params(cand), sub.tunables
    assert "not_a_real_param" not in json.dumps(sub.body)
    assert "4k" not in json.dumps(sub.body)


def test_the_gemini_shape_keeps_the_google_prefix():
    """The bare name answers 503. Measured, and the kind of thing a tidy-up would break."""
    cand = next(c for c in media_plane.capability("text_to_image")["candidates"]
                if c["shape"] == "gemini")
    sub = media_plane.build_submit(cand, TR, {"prompt": "p"})
    assert "google/" in sub.url


def test_the_gemini_shape_posts_to_the_api_root_not_under_v1():
    """`/v1beta` hangs off the ROOT. Measured live 2026-08-15 against a model id that does not
    exist, so the two answers differ by ROUTE and not by model:

        …/v1/v1beta/models/{id}:generateContent -> 404 "Invalid URL"
        …/v1beta/models/{id}:generateContent    -> 503 model_not_found

    This assertion used to read `f"{TR}/v1beta/..."`, which is the bug written down as the
    expectation: every Gemini call 404'd, the chain fell through to a slower per-image model, and
    a picture still came back — so the suite stayed green while the two fastest models in the
    chain were dead in every deployment. Pin the negative too; that is the half that was wrong.
    """
    for cap in ("text_to_image", "image_to_image"):
        for cand in media_plane.capability(cap)["candidates"]:
            if cand.get("shape") != "gemini":
                continue
            for base in (TR, TR.rstrip("/") + "/", "https://api.tokenrouter.com"):
                url = media_plane.build_submit(cand, base, {"prompt": "p"}).url
                assert "/v1/v1beta/" not in url, url
                assert url == (f"https://api.tokenrouter.com/v1beta/models/"
                               f"{cand['model']}:generateContent"), url


def test_arrange_positions_every_element_exactly_once():
    """A shot holding a still AND a clip laid the board out on top of itself.

    Each media element's companions were "everything sharing the shot name", which includes the
    OTHER media in that shot and its caption — so four elements produced eight positions, the
    second pass overwrote the first, and the clip landed under its own caption. The agent noticed
    before any test did: "the arrange returned duplicate positions… arrange lumped all four into
    one shot group and stacked them."
    """
    def media(eid, shot):
        return {"id": eid, "width": 480, "height": 270,
                "customData": {"shot": shot, "media": {"v": 1, "kind": "video",
                                                       "status": "ready"}}}

    def caption(eid, shot):
        return {"id": eid, "type": "text", "width": 480, "height": 24,
                "customData": {"shot": shot}}

    els = [media("A", "Shot 1"), caption("a", "Shot 1"),
           media("B", "Shot 1"), caption("b", "Shot 1"),
           media("C", "Shot 2"), caption("c", "Shot 2")]
    chosen = [e for e in els if media_plane.is_media(e)]
    pos = media_plane.layout_positions(media_plane.storyboard_items(els, chosen), "storyboard")
    ids = [p["element_id"] for p in pos]
    assert sorted(ids) == sorted(e["id"] for e in els), ids
    assert len(ids) == len(set(ids)), f"an element was positioned twice: {ids}"
    # And nothing overlaps anything else.
    boxes = {p["element_id"]: p for p in pos}
    for i, p in enumerate(pos):
        for q in pos[i + 1:]:
            apart = (p["y"] + p["h"] <= q["y"] or q["y"] + q["h"] <= p["y"]
                     or p["x"] + p["w"] <= q["x"] or q["x"] + q["w"] <= p["x"])
            assert apart, f"{p['element_id']} overlaps {q['element_id']}"
    # A caption sits directly under the media it was placed with, not under the other clip's.
    assert boxes["a"]["y"] > boxes["A"]["y"] and boxes["a"]["y"] < boxes["B"]["y"]
    assert boxes["b"]["y"] > boxes["B"]["y"]


def test_every_refusal_ends_with_you_cannot_connect_it_yourself(client, harness, session,
                                                                provider):
    """Invariant 25, over every no-model path there is."""
    for m in [c["model"] for c in media_plane.capability("text_to_video")["candidates"]]:
        app._media_quarantine[m] = time.time() + 900
    for cap in ("text_to_speech", "text_to_music"):
        for m in [c["model"] for c in media_plane.capability(cap)["candidates"]]:
            app._media_quarantine[m] = time.time() + 900
    tok = _cred(harness, session)
    for name, args in (("generate_video", {"prompt": "a", "seconds": 6}),
                       ("generate_speech", {"text": "hello"}),
                       ("generate_music", {"prompt": "a warm score"})):
        assert "you cannot connect" in _err(_call(client, tok, name, args)).lower(), name


def test_music_never_becomes_speech(client, harness, session, provider, monkeypatch):
    """Invariant 10: when no music model can run, generate_music REFUSES and reaches for no speech
    model on the way — and the refusal names the fix rather than leaving the reader nowhere.

    Driven here by standing the music model down, because the capability is available in this
    deployment now. The invariant was never about the model being broken; it is about what happens
    when it is, and a chain that could fall through to `text_to_speech` would be a silent
    substitution of conversation for a score.
    """
    _calls.clear()
    app._media_quarantine["elevenlabs/music-v1"] = time.time() + 900
    text = _err(_call(client, _cred(harness, session), "generate_music",
                      {"prompt": "a warm orchestral score", "seconds": 10}))
    assert "not music" in text, text
    assert "you cannot connect" in text.lower()
    assert _calls == []
    # And speech is genuinely available right now, so this is not passing on an empty deployment.
    assert _ok(_call(client, _cred(harness, session), "generate_speech",
                     {"text": "hello"}))["status"] == "succeeded"


def test_list_capabilities_is_free_and_names_what_is_broken(client, harness, session, provider):
    _calls.clear()
    out = _ok(_call(client, _cred(harness, session), "list_capabilities"))
    by = {c["name"]: c for c in out["capabilities"]}
    assert _calls == [], "list_capabilities issued a provider call"
    assert by["text_to_video"]["available"] is True
    assert by["text_to_video"]["model"] == "dreamina-seedance-2-5-hc"
    # Every limit reported is one that was MEASURED on this model, and nothing else is reported.
    # It ignores the duration it is sent — asked 1 s, returned 6.08 s — so the agent is told that
    # rather than left to believe the number it asked for.
    #
    # `aspects` is in this dict for the same reason and by the same standard: it is arithmetic on
    # the 1280x720 frame two lines above, not a new claim about the model. It takes no `size`
    # parameter, so 16:9 is the only shape it can produce and the only one it can be asked for.
    assert by["text_to_video"]["limits"] == {"duration_ignored": True,
                                             "duration_observed_s": 6.08,
                                             "resolution": "1280x720",
                                             "accepts_input_image": False,
                                             "aspects": ["16:9"]}
    assert by["text_to_music"]["available"] is True
    assert by["text_to_music"]["model"] == "elevenlabs/music-v1"
    assert by["export"]["available"] is media_plane.have_ffmpeg()
    # A cost is present only where it was measured.
    assert "estimated_usd_per_unit" not in by["text_to_video"]
    for m in ("dreamina-seedance-2-5-hc",):
        app._media_quarantine[m] = time.time() + 900
    again = {c["name"]: c for c in _ok(_call(client, _cred(harness, session),
                                             "list_capabilities"))["capabilities"]}
    assert again["text_to_video"]["model"] == "MiniMax-Hailuo-2.3"
    assert again["text_to_video"]["estimated_usd_per_unit"] == 0.28
    assert again["text_to_video"]["limits"]["durations_s"] == [6, 10]


def test_the_session_budget_stops_generation_rather_than_throttling_it(
        client, harness, session, provider, monkeypatch):
    monkeypatch.setattr(media_plane, "SESSION_BUDGET_USD", 0.10)
    provider.video_bytes = b""
    tok = _cred(harness, session)
    provider.fail["dreamina-seedance-2-5-hc"] = (400, {"message": "unknown model"})
    first = _ok(_call(client, tok, "generate_video", {"prompt": "a", "seconds": 6}))
    job = asyncio.run(app._media_job_get(first["job_id"]))
    job["status"] = "succeeded"
    asyncio.run(app._media_job_save(job))
    text = _err(_call(client, tok, "generate_video", {"prompt": "b", "seconds": 6}))
    assert "$0.28" in text and "$0.10" in text and "cannot raise the limit" in text


# ══ jobs ═════════════════════════════════════════════════════════════════════════

def test_a_video_job_polls_then_lands_as_our_own_file(client, harness, session, provider):
    provider.video_bytes = _mp4(1.0)
    tok = _cred(harness, session)
    provider.fail["dreamina-seedance-2-5-hc"] = (400, {"message": "no"})
    out = _ok(_call(client, tok, "generate_video", {"prompt": "rain", "seconds": 6}))
    jid = out["job_id"]

    tid = next(t for t in provider.tasks)
    provider.queue_poll(tid, httpx.Response(200, json={"code": "success", "message": "", "data": {
        "id": tid, "task_id": tid, "status": "IN_PROGRESS", "progress": "40%"}}))
    # Poll #1 — still rendering. The job must not be advanced past its own next_poll_at, so drop
    # the gate the way real time would.
    _due(jid)
    running = _ok(_call(client, tok, "check_jobs", {"job_ids": [jid]}))["jobs"][0]
    assert running["status"] == "running" and running["progress"] == "40%"

    _due(jid)
    done = _ok(_call(client, tok, "check_jobs", {"job_ids": [jid]}))["jobs"][0]
    assert done["status"] == "succeeded" and done["kind"] == "video"
    assert done["media_id"].startswith("med_")
    assert done["seconds"] > 0 and done["bytes"] > 0
    assert done["model"] == "MiniMax-Hailuo-2.3" and done["usd"] == 0.28


def test_an_empty_poll_is_never_terminal(client, harness, session, provider):
    """Invariant 8. An empty record is the known background-response race; reading it as failure
    is how a finished render gets thrown away."""
    provider.video_bytes = _mp4(1.0)
    tok = _cred(harness, session)
    provider.fail["dreamina-seedance-2-5-hc"] = (400, {"message": "no"})
    jid = _ok(_call(client, tok, "generate_video", {"prompt": "a", "seconds": 6}))["job_id"]
    tid = next(iter(provider.tasks))
    provider.queue_poll(tid, httpx.Response(200, json={}))

    rows = []
    for _ in range(2):
        _due(jid)
        rows.append(_ok(_call(client, tok, "check_jobs", {"job_ids": [jid]}))["jobs"][0])
    assert [r["status"] for r in rows] == ["unknown", "succeeded"], rows
    assert "ask again" in rows[0]["note"]
    # And `unknown` is never what the job IS — only what one answer was.
    assert asyncio.run(app._media_job_get(jid))["status"] == "succeeded"


def test_an_unknown_job_id_is_a_row_and_never_an_omission(client, harness, session, provider):
    """A missing row reads as 'still running', which is the worst possible answer."""
    rows = _ok(_call(client, _cred(harness, session), "check_jobs",
                     {"job_ids": ["mjob_nope", "mjob_also_nope"]}))["jobs"]
    assert [r["job_id"] for r in rows] == ["mjob_nope", "mjob_also_nope"]
    assert all(r["status"] == "failed" and "No job with that id" in r["error"] for r in rows)


def test_a_failed_render_advances_the_chain_exactly_once(client, harness, session, provider):
    """The render was billable, so the chain advances once — not in a loop."""
    provider.video_bytes = _mp4(1.0)
    tok = _cred(harness, session)
    provider.fail["dreamina-seedance-2-5-hc"] = (400, {"message": "no"})
    jid = _ok(_call(client, tok, "generate_video", {"prompt": "a", "seconds": 6}))["job_id"]
    tid = next(iter(provider.tasks))
    provider.queue_poll(tid, httpx.Response(200, json={"code": "success", "data": {
        "id": tid, "task_id": tid, "status": "FAILURE", "message": "the render failed upstream"}}))
    _due(jid)
    row = _ok(_call(client, tok, "check_jobs", {"job_ids": [jid]}))["jobs"][0]
    assert row["status"] == "running", "a billable failure did not advance the chain"
    assert row["model"] == "kling-v3"
    assert app._media_quarantine["MiniMax-Hailuo-2.3"] > time.time()


def test_one_finished_render_is_downloaded_and_stored_exactly_once(client, harness, session,
                                                                   provider):
    """The sweeper, check_jobs and the app's poll route advance jobs CONCURRENTLY by design.

    Without a per-job lock each of them saw the same SUCCESS, each fetched the same clip and each
    stored it under a fresh media id. Measured live on the VM: one 6 s clip landed three times,
    3,974,388 bytes apiece (byte-identical, md5 2aeae1f1…), two orphaned the instant the third
    won the vertex. The `next_poll_at` gate does not help — every racer reads the same past value.
    """
    provider.video_bytes = _mp4(1.0)
    tok = _cred(harness, session)
    provider.fail["dreamina-seedance-2-5-hc"] = (400, {"message": "no"})
    jid = _ok(_call(client, tok, "generate_video", {"prompt": "a", "seconds": 6}))["job_id"]

    async def race():
        job = await app._media_job_get(jid)
        job["next_poll_at"] = 0
        await app._media_job_save(job)
        fresh = await app._media_job_get(jid)
        # Five callers, all holding the same pre-landing snapshot — the real shape of the race.
        # A budget each, because that is what five racers ARE: five requests. Sharing one here
        # would let the submit ceiling settle the race and the per-job lock would go untested.
        return await asyncio.gather(*[app._media_job_advance(dict(fresh), app._MediaBudget())
                                      for _ in range(5)])

    out = asyncio.run(race())
    assert all(j["status"] == "succeeded" for j in out), [j["status"] for j in out]
    ids = {j["media_id"] for j in out}
    assert len(ids) == 1, f"the same render landed under {len(ids)} media ids: {ids}"

    stored = [c for c in _calls if "cdn.provider.example" in c["url"]]
    assert len(stored) == 1, f"the clip was downloaded {len(stored)} times"
    assert asyncio.run(app._media_job_get(jid))["media_id"] == ids.pop()


def test_a_job_outlives_its_turn(client, harness, session, provider):
    """Invariant 21. The sweeper is not an optimisation: without it a job whose turn ended and
    whose tab is closed never completes, and its provider URL expires."""
    provider.video_bytes = _mp4(1.0)
    tok = _cred(harness, session)
    provider.fail["dreamina-seedance-2-5-hc"] = (400, {"message": "no"})
    jid = _ok(_call(client, tok, "generate_video", {"prompt": "a", "seconds": 6}))["job_id"]
    place = _ok(_call(client, tok, "place", {"items": [{"job_id": jid, "shot": "Shot 1"}]}))
    eid = place["placed"][0]["element_id"]
    rev_before = place["scene_rev"]

    _due(jid)
    assert asyncio.run(app._media_sweep()) >= 1               # no turn, no agent, no tab

    scene = asyncio.run(app._media_scene_read(session))
    el = next(e for e in scene["elements"] if e["id"] == eid)
    assert el["customData"]["media"]["status"] == "ready"
    assert el["customData"]["media"]["mediaId"].startswith("med_")
    assert int(scene["meta"]["rev"]) > rev_before


def test_a_job_that_never_finishes_is_failed_with_a_sentence(client, harness, session, provider,
                                                             monkeypatch):
    monkeypatch.setattr(media_plane, "JOB_MAX_S", 0)
    tok = _cred(harness, session)
    provider.fail["dreamina-seedance-2-5-hc"] = (400, {"message": "no"})
    jid = _ok(_call(client, tok, "generate_video", {"prompt": "a", "seconds": 6}))["job_id"]
    tid = next(iter(provider.tasks))
    provider.queue_poll(tid, httpx.Response(200, json={"code": "success", "data": {
        "id": tid, "task_id": tid, "status": "IN_PROGRESS"}}))
    _due(jid)
    row = _ok(_call(client, tok, "check_jobs", {"job_ids": [jid]}))["jobs"][0]
    assert row["status"] == "failed" and "never finished" in row["error"]


def test_the_provider_url_is_never_persisted(client, harness, session, provider):
    """Invariant 14. Every provider URL is signed or short-lived — happyhorse's lasts a day — so a
    scene holding one is a scene that stops working tomorrow."""
    provider.video_bytes = _mp4(1.0)
    tok = _cred(harness, session)
    provider.fail["dreamina-seedance-2-5-hc"] = (400, {"message": "no"})
    jid = _ok(_call(client, tok, "generate_video", {"prompt": "a", "seconds": 6}))["job_id"]
    _ok(_call(client, tok, "place", {"items": [{"job_id": jid}]}))
    _due(jid)
    asyncio.run(app._media_sweep())

    med = asyncio.run(app._media_job_get(jid))["media_id"]
    scene = json.dumps(asyncio.run(app._media_scene_read(session)))
    vertex = json.dumps(asyncio.run(app._media_job_get(jid)))
    meta = json.dumps(asyncio.run(app._media_meta(session, med)))
    for blob in (scene, vertex, meta):
        assert "cdn.provider.example" not in blob
    assert med in scene, "the scene does not point at our own copy either"


# ══ the synchronous shapes ═══════════════════════════════════════════════════════

def test_an_image_lands_inline_and_says_so(client, harness, session, provider):
    """A synchronous shape renders inside the submit. Reporting it as 'running' would be a lie the
    very next call exposes.

    This test used to end `assert out["size"] == "1024x1024"` and that assertion pinned a lie: the
    model it names has params ["prompt"], is never sent a size, and the 1024x1024 came straight
    back out of the request. What is asserted now is that the size key is absent — see
    test_a_size_the_model_cannot_be_told_is_not_reported_as_though_it_were, which pins the reason.
    """
    out = _ok(_call(client, _cred(harness, session), "generate_image",
                    {"prompt": "a rainy window", "size": "1024x1024"}))
    assert out["status"] == "succeeded" and out["media_id"].startswith("med_")
    assert out["model"] == "google/gemini-3.1-flash-lite-image"
    assert "size" not in out


def test_a_size_below_a_models_floor_skips_it(client, harness, session, provider):
    """seedream-4.5 rejects anything under 3,686,400 px with a 400. Skipping it is cheaper than
    finding out."""
    for c in media_plane.capability("text_to_image")["candidates"]:
        if c["shape"] == "gemini":
            app._media_quarantine[c["model"]] = time.time() + 900
    out = _ok(_call(client, _cred(harness, session), "generate_image",
                    {"prompt": "a", "size": "1024x1024"}))
    assert out["model"] != "bytedance-seed/seedream-4.5"
    big = _ok(_call(client, _cred(harness, session), "generate_image",
                    {"prompt": "a", "size": "1920x1920"}))
    assert big["model"] == "bytedance-seed/seedream-4.5"


def test_speech_reports_what_the_model_actually_said(client, harness, session, provider):
    """These models ANSWER the prompt rather than reading it, and the transcript the provider
    returns is real data — so `verbatim` is measured, not assumed.

    The reader that now outranks them is stood down first, which is the only way to reach them:
    they are the FALLBACK for this capability, and the warning below is the reason they are.
    """
    app._media_quarantine[_el("text_to_speech")["model"]] = time.time() + 900
    out = _ok(_call(client, _cred(harness, session), "generate_speech", {"text": "Say: hello."}))
    assert out["model"] == "openai/gpt-audio-mini"
    assert "answers prompts rather than reading them" in out["warning"]
    assert out["spoken_text"] == "Hello! It's great to talk with you."
    assert out["verbatim"] is False


def test_the_streaming_audio_model_is_driven_the_way_it_demands(client, harness, session,
                                                                provider):
    """gpt-audio answers 400 without stream:true and then delivers audio in deltas that have to be
    concatenated."""
    app._media_quarantine[_el("text_to_speech")["model"]] = time.time() + 900
    app._media_quarantine["openai/gpt-audio-mini"] = time.time() + 900
    out = _ok(_call(client, _cred(harness, session), "generate_speech", {"text": "hello"}))
    assert out["model"] == "openai/gpt-audio" and out["status"] == "succeeded"
    body = next(c["body"] for c in _calls if c["body"].get("model") == "openai/gpt-audio")
    assert body["stream"] is True and body["modalities"] == ["text", "audio"]
    assert out["spoken_text"] == "Hello there."


def test_the_openai_shape_reads_the_image_out_of_a_message_with_no_content(client, harness,
                                                                          session, provider):
    """`message.content` is null on image turns; the picture is in `message.images`."""
    for c in media_plane.capability("text_to_image")["candidates"]:
        if c["shape"] in ("gemini", "image-generation"):
            app._media_quarantine[c["model"]] = time.time() + 900
    out = _ok(_call(client, _cred(harness, session), "generate_image", {"prompt": "a"}))
    assert out["model"] == "microsoft/mai-image-2.5" and out["status"] == "succeeded"
    # And a cost the provider reported INLINE is used, because it was measured.
    assert out["estimated_usd"] == 0.0482


def test_a_body_that_is_not_media_is_a_failure_and_not_a_success(client, harness, session,
                                                                  provider):
    """A relay answering 200 with an HTML error page is the case this catches. Storing it would
    make an element that reads as ready and plays nothing."""
    provider.fail["google/gemini-3.1-flash-lite-image"] = (
        200, {"candidates": [{"content": {"parts": [
            {"inlineData": {"mimeType": "image/png",
                            "data": base64.b64encode(b"<html>gateway timeout</html>").decode()}}]}}]})
    out = _ok(_call(client, _cred(harness, session), "generate_image", {"prompt": "a"}))
    # It answered, and it billed, so the chain advances exactly once — and the reason is recorded
    # rather than an HTML page being stored as a picture.
    assert out["model"] != "google/gemini-3.1-flash-lite-image"
    assert "cannot identify as a image" in json.dumps(out["attempts"])
    assert app._media_quarantine["google/gemini-3.1-flash-lite-image"] > time.time()
    assert media_plane.sniff(b"<html>gateway timeout</html>") == ("", "")


def test_a_billable_render_that_cannot_be_fetched_leaves_a_visible_failure(client, harness,
                                                                          session, provider):
    """It already billed by the time the fetch is attempted, so an untraceable charge is worse
    than a job that says what went wrong. With no candidate left to advance to, the job is failed
    and readable — not absent."""
    only = "openai/gpt-5.4-image-2"
    for c in media_plane.capability("text_to_image")["candidates"]:
        if c["model"] != only:
            app._media_quarantine[c["model"]] = time.time() + 900
    provider.fail[only] = (200, {"data": [{"url": "https://cdn.provider.example/gone.png"}]})
    inner = provider.handle

    def gone(req):
        return (httpx.Response(404, text="expired") if req.url.path.endswith("gone.png")
                else inner(req))

    provider.handle = gone
    out = _ok(_call(client, _cred(harness, session), "generate_image",
                    {"prompt": "a", "size": "1024x1024"}))
    assert out["status"] == "failed" and out["model"] == only
    job = asyncio.run(app._media_job_get(out["job_id"]))
    assert job is not None and job["status"] == "failed"
    assert "could not be fetched" in job["error"]
    assert job["attempts"][-1]["model"] == only


def test_a_poll_that_reports_success_with_no_video_is_a_failure():
    """The same rule the submit side holds, on the poll side: SUCCESS with nothing in it is not a
    success — it is the shape that lets a job sit 'done' with no file."""
    cand = {"shape": "video-generation", "model": "x"}
    status, payload, err, _p = media_plane.read_poll(cand, 200, {"code": "success", "data": {
        "id": "t", "status": "SUCCESS", "result_url": ""}})
    assert status == "failed" and payload is None and "returned no video" in err


def test_the_gemini_reader_walks_past_the_thought_signature_part(client, harness, session,
                                                                 provider):
    """The ~1 MB thoughtSignature part sits beside the picture and is not one."""
    out = _ok(_call(client, _cred(harness, session), "generate_image", {"prompt": "a"}))
    assert out["model"] == "google/gemini-3.1-flash-lite-image"
    meta = asyncio.run(app._media_meta(session, out["media_id"]))
    assert meta["mime"] == "image/png" and meta["bytes"] == len(PNG_1PX)


def test_the_catalog_is_read_from_disk_and_not_compiled_in(tmp_path, monkeypatch):
    """A table in source goes stale the moment a provider fixes a model or breaks one, and nothing
    says so. Same rule as kits and skills."""
    assert Path(media_plane._CATALOG_PATH).name == "media_catalog.json"
    doc = json.loads(Path(media_plane._CATALOG_PATH).read_text())
    # The owner's preference moved to the Vercel gateway on 2026-08-16, deliberately: it is the
    # connection with the credits on it, and its seedance HONOURS a requested duration where the
    # relay's ignores it. The relay's entry is still in the chain, one rank down, because it
    # renders well and a second route is the point of a chain.
    t2v = [c["model"] for c in doc["capabilities"]["text_to_video"]["candidates"]]
    assert t2v[0] == "bytedance/seedance-2.5", "the owner's preferred model is no longer rank 1"
    assert "dreamina-seedance-2-5-hc" in t2v, "the previous rank 1 was deleted rather than demoted"
    swapped = tmp_path / "cat.json"
    swapped.write_text(json.dumps({"providers": {}, "capabilities": {}}))
    monkeypatch.setattr(media_plane, "_CATALOG_PATH", str(swapped))
    media_plane.catalog.cache_clear()
    try:
        assert media_plane.capability_names() == []
    finally:
        monkeypatch.undo()
        media_plane.catalog.cache_clear()


# ══ the catalog is measurement, and corrections are measurement too ══════════════
# Four things were measured AFTER the sweep that wrote this file, and each is a fact the code has
# to keep honouring. They are asserted here rather than trusted to a comment.

def test_nothing_is_skipped_for_being_marked_broken(client, harness, session, provider):
    """The rule that must never be added.

    `dreamina-seedance-2-5-hc` was marked broken for the whole outage and stayed at rank 1,
    because a candidate that fails at SUBMIT costs nothing to retry. That is the only reason it
    started working again the day the relay's mapping was fixed — no code change, nobody watching.
    A tidy-up that skipped everything marked `status: broken` would have made the recovery
    impossible and left the file looking correct.
    """
    broken = [c for c in media_plane.capability("text_to_video")["candidates"]
              if str(c.get("status") or "") == "broken"]
    assert broken, "nothing is marked broken any more — this test is asserting against nothing"
    for cand in broken:
        assert media_plane.can_serve(cand, {"seconds": 6}) == "", cand["model"]
    # and the corrected rank 1 is now selected and really renders
    out = _ok(_call(client, _cred(harness, session), "generate_video",
                    {"prompt": "rain", "seconds": 6}))
    assert out["model"] == "dreamina-seedance-2-5-hc"


def _catalog_with_first(cap_name: str, cand: dict) -> dict:
    """The real catalog with one candidate lifted to rank 1.

    For a test whose subject is a model that is deliberately NOT the default choice. Reordering
    here rather than editing the catalog keeps the test about the model's behaviour instead of
    about which model the owner currently prefers, which is a decision that will move again.
    """
    doc = copy.deepcopy(json.loads(Path(media_plane._CATALOG_PATH).read_text()))
    c = doc["capabilities"][cap_name]["candidates"]
    doc["capabilities"][cap_name]["candidates"] = (
        [x for x in c if x["model"] == cand["model"]] +
        [x for x in c if x["model"] != cand["model"]])
    return doc


def test_the_model_that_ignores_a_duration_says_so_rather_than_being_believed(client, harness,
                                                                              session, provider,
                                                                              monkeypatch):
    """Measured: 1 s was asked for and a 6.08 s clip came back. It is no longer rank 1 — the Vercel
    seedance took that slot and HONOURS a duration — but it is still in the chain, so the rule it
    exists for is still live: nothing downstream may assume the length it was asked for.

    Found BY NAME rather than by rank. Asserting a quirk of one model through whatever happens to
    sit at position 0 is how a re-ranking silently stops testing the quirk.
    """
    cands = media_plane.capability("text_to_video")["candidates"]
    cand = next(c for c in cands if c["model"] == "dreamina-seedance-2-5-hc")
    assert cand["duration_ignored"] is True
    # The model that displaced it must NOT claim the same quirk, or the note below is wrong for it.
    assert not cands[0].get("duration_ignored"), \
        f"{cands[0]['model']} is rank 1 and ignores duration — the honest-note path needs revisiting"
    # Drive the chain to THIS candidate for the end-to-end half, since rank 1 is now another model.
    monkeypatch.setattr(media_plane, "catalog", lambda: _catalog_with_first("text_to_video", cand))
    assert "duration_min_s" not in cand and "durations_s" not in cand, (
        "an ignored duration must not be written down as a limit — that would skip the model")
    out = _ok(_call(client, _cred(harness, session), "generate_video",
                    {"prompt": "rain", "seconds": 1}))
    assert out["model"] == cand["model"], "a 1 s ask must still reach it, not skip it"
    assert "does not honour a requested duration" in out["note"]
    assert "6.08" in out["note"], "the note quotes what was measured, not a guess"
    # And the duration is still SENT: a video submit that carries none lets the model choose.
    body = next(c["body"] for c in _calls if c["url"].endswith("/video/generations"))
    assert body["duration"] == 1


# ══ the aspect ═══════════════════════════════════════════════════════════════════
# `aspect` was declared on generate_video, described as a thing the tool does, and occurred
# EXACTLY ONCE in the whole gateway: in the schema. The generate branch built
# {prompt, seconds, allow_watermark} and the argument fell on the floor — so an agent asked for a
# vertical film, was ACCEPTED, and got whatever the model defaults to. Round 5 made it worse in
# one way: enum validation refuses an INVALID aspect while a VALID one is still ignored, which
# reads to a model as proof the argument works.
#
# Nothing here spends anything. What is asserted is OUR OUTBOUND BODY and OUR REFUSAL — whether a
# model then obeys is the provider's business and is not what was broken.

def test_a_requested_aspect_reaches_the_provider_request_body(client, harness, session, provider):
    """THE BUG, stated as the assertion that would have caught it: ask for 9:16 and read what left
    this process.

    happyhorse is the only text_to_video candidate that lists `size` among the params it honours,
    so it is the only one that can be TOLD a shape — and it watermarks, so this asks for that too.
    1080*1920 is arithmetic on its own measured 1920*1080 frame, in its own W*H format.
    """
    out = _ok(_call(client, _cred(harness, session), "generate_video",
                    {"prompt": "a lift door closing", "seconds": 6, "aspect": "9:16",
                     "allow_watermark": True}))
    assert out["model"] == "happyhorse-1.0-t2v"
    body = next(c["body"] for c in _calls if c["url"].endswith("/video/generations"))
    assert body.get("size") == "1080*1920", (
        f"9:16 was accepted and the submit carried {body.get('size')!r} — the argument is still "
        f"decorative")
    assert out["aspect"] == "9:16", "the tool must report the shape it actually secured"


def test_an_aspect_nobody_in_the_chain_can_honour_is_refused_and_names_why(client, harness,
                                                                          session, provider):
    """Never landscape for a 9:16 request. Without allow_watermark the one model that can be told
    a shape is stood down, and there is no substitute — so this refuses, and the refusal is built
    out of each candidate's own reason rather than one flat sentence."""
    text = _err(_call(client, _cred(harness, session), "generate_video",
                      {"prompt": "a lift door closing", "seconds": 6, "aspect": "9:16"}))
    assert "Nothing was generated" in text
    assert "only renders 16:9" in text, (
        f"the fixed-shape models must say what they DO render: {text}")
    assert "1280x720" in text, "and it names the frame that fact comes from"
    assert "never measured" in text, "kling can be told nothing and nobody measured it — say so"
    assert "watermarks its output" in text
    assert not [c for c in _calls if c["url"].endswith("/video/generations")], (
        "a refusal for a shape nobody can render must not open a socket")


def test_a_model_that_is_already_the_requested_shape_is_asked_for_nothing(client, harness,
                                                                         session, provider):
    """16:9 is what dreamina renders and it takes no size parameter at all. Honouring the request
    is therefore selecting it — inventing a `size` field for a model whose params do not list one
    would be the same silent invention one direction over."""
    out = _ok(_call(client, _cred(harness, session), "generate_video",
                    {"prompt": "rain", "seconds": 6, "aspect": "16:9"}))
    assert out["model"] == "dreamina-seedance-2-5-hc" and out["aspect"] == "16:9"
    body = next(c["body"] for c in _calls if c["url"].endswith("/video/generations"))
    assert "size" not in body, f"a size was invented for a model that declares none: {body}"


def test_animating_a_frame_at_a_shape_nobody_measured_refuses_rather_than_guessing(
        client, harness, session, provider):
    """image_to_video is the capability with NO substitute, and both its candidates take no size
    and have no measured output frame. So a request to animate a still AT a shape cannot be
    honoured by anything, and the only two honest answers are a refusal or a landscape clip
    handed back as though it were vertical. This asserts the refusal, and that nothing was spent
    finding out."""
    img = _ok(_call(client, _cred(harness, session), "generate_image", {"prompt": "a face"}))
    _calls.clear()
    text = _err(_call(client, _cred(harness, session), "generate_video",
                      {"prompt": "the face turns", "seconds": 6, "from_image": img["job_id"],
                       "aspect": "9:16"}))
    assert "No model is available for image_to_video" in text
    assert "kling-v3 cannot be told an aspect and what it returns was never measured" in text
    assert [c for c in _calls if "generations" in c["url"]] == [], "it submitted anyway"


def test_an_aspect_survives_the_chain_advancing(client, harness, session, provider):
    """A walk that falls off its first candidate may not land on one that cannot hold the shape.

    The advance is the path four rounds of this file's bugs lived on, and `resolve` is what makes
    it safe here: the aspect is in the job's params, so the second candidate is filtered by the
    same rule as the first — and when nothing else can hold it, this refuses rather than
    substituting a landscape clip.
    """
    provider.fail["happyhorse-1.0-t2v"] = (400, {"message": "unknown model"})
    text = _err(_call(client, _cred(harness, session), "generate_video",
                      {"prompt": "a lift door closing", "seconds": 6, "aspect": "9:16",
                       "allow_watermark": True}))
    assert "Nothing was generated" in text
    submitted = [c["body"].get("model") for c in _calls if c["url"].endswith("/video/generations")]
    assert submitted == ["happyhorse-1.0-t2v"], (
        f"the walk tried a model that cannot hold 9:16: {submitted}")


@pytest.mark.parametrize("model,aspect,want", [
    # Arithmetic on each model's OWN measured floor, not a table someone typed. 2560x1440 is
    # exactly seedream's 3,686,400 px minimum, and 1:1 lands on the size the file records as
    # verified — which is how the formula is checked against a measurement.
    ("bytedance-seed/seedream-4.5", "16:9", "2560x1440"),
    ("bytedance-seed/seedream-4.5", "9:16", "1440x2560"),
    ("bytedance-seed/seedream-4.5", "1:1", "1920x1920"),
    ("openai/gpt-5.4-image-2", "1:1", "1024x1024"),
    # Neither shape takes a size parameter, and nothing measured says what frame they return.
    ("google/gemini-3.1-flash-lite-image", "16:9", ""),
    ("microsoft/mai-image-2.5", "16:9", ""),
])
def test_the_aspect_is_translated_per_model_out_of_that_models_own_numbers(model, aspect, want):
    cand = next(c for c in media_plane.capability("text_to_image")["candidates"]
                if c["model"] == model)
    assert media_plane.aspect_size(cand, aspect) == want


def test_a_capability_says_which_shapes_it_can_actually_render(client, harness, session, provider):
    """list_capabilities is the free pre-flight, and an agent planning a vertical film must be able
    to learn before it spends that this deployment cannot render one."""
    by = {c["name"]: c for c in _ok(_call(client, _cred(harness, session),
                                          "list_capabilities"))["capabilities"]}
    assert by["text_to_video"]["limits"]["aspects"] == ["16:9"]
    assert "aspects" not in by["text_to_speech"]["limits"], "a line of speech has no shape"


def test_a_size_the_model_cannot_be_told_is_not_reported_as_though_it_were(client, harness,
                                                                          session, provider):
    """THE SIBLING, found by auditing the same question one argument over.

    generate_image echoed `size` back beside `model` on every call — including the rank-1 gemini
    models, whose params list is ["prompt"] and which are never sent a size at all. A number the
    provider never received, printed next to the model that did not receive it, is the same defect
    as an aspect that is accepted and ignored.
    """
    out = _ok(_call(client, _cred(harness, session), "generate_image",
                    {"prompt": "a rainy window", "size": "1024x1024"}))
    assert out["model"] == "google/gemini-3.1-flash-lite-image"
    assert "size" not in out, f"a size nothing was told was reported anyway: {out}"
    assert "cannot be told a frame size" in out.get("note", "")
    body = next(c["body"] for c in _calls if ":generateContent" in c["url"])
    assert "size" not in json.dumps(body)
    # And where it IS told one, it says so — the same key, earned.
    for c in media_plane.capability("text_to_image")["candidates"]:
        if c["shape"] == "gemini":
            app._media_quarantine[c["model"]] = time.time() + 900
    told = _ok(_call(client, _cred(harness, session), "generate_image",
                     {"prompt": "a", "size": "1920x1920"}))
    assert told["model"] == "bytedance-seed/seedream-4.5" and told["size"] == "1920x1920"
    sent = next(c["body"] for c in _calls if c["url"].endswith("/images/generations"))
    assert sent["size"] == told["size"], (
        "the size reported and the size submitted are two readings of one fact and must come "
        "from one place — see media_plane.size_for")


def test_the_model_that_rejects_an_input_image_is_not_in_the_image_chain():
    """They reject an input image url outright. Listing one in image_to_video would spend the
    rank-1 slot of a capability with NO substitute on a model that cannot do it at all.

    Both seedance entries are checked, not just the top one: the Vercel model that now leads
    text_to_video is text-only too, so the rule has two subjects rather than one.
    """
    assert [c["model"] for c in media_plane.capability("image_to_video")["candidates"]] == [
        "kling-v3", "kling-v2-6"]
    t2v = media_plane.capability("text_to_video")["candidates"]
    textonly = [c for c in t2v if c["model"] in ("dreamina-seedance-2-5-hc",
                                                 "bytedance/seedance-2.5")]
    assert len(textonly) == 2, "a seedance entry vanished from the text chain"
    for cand in textonly:
        assert cand["accepts_input_image"] is False
        assert media_plane.can_serve(cand, {"image": "…"}), \
            f"{cand['model']} would have taken an image job"


@pytest.mark.parametrize("cap", ["text_to_video", "image_to_video"])
def test_a_duration_a_model_measurably_refuses_is_not_offered_to_it(cap):
    """Both kling models answer 400 to a 1 s render, and this file used to claim 1 s was their
    floor. The claim is gone; what replaced it is the measurement and nothing wider — the shortest
    duration they DO accept was never measured, and a number nobody measured is worse than none.
    """
    klings = [c for c in media_plane.capability(cap)["candidates"]
              if c["model"] in ("kling-v3", "kling-v2-6")]
    assert len(klings) == 2
    for cand in klings:
        assert "duration_min_s" not in cand, f"{cand['model']} still claims a floor nobody measured"
        assert cand["durations_rejected_s"] == [1]
        assert media_plane.can_serve(cand, {"seconds": 1}) == f"{cand['model']} refuses a 1 s render"
        assert media_plane.can_serve(cand, {"seconds": 6}) == ""


def test_music_is_one_candidate_that_holds_no_credential_to_be_one():
    """The music chain is ONE candidate — the model the owner chose — and the key that reaches it
    is not in this file. It never was: when this candidate was stood down for a free-tier plan the
    same assertion held, and it is the one that must survive the candidate becoming available."""
    cap = media_plane.capability("text_to_music")
    assert len(cap["candidates"]) == 1
    only = cap["candidates"][0]
    assert only["model"] == "elevenlabs/music-v1" and only["provider"] == "elevenlabs"
    assert not only.get("status"), "the music candidate is stood down again"
    # Nothing that looks like a credential, for EITHER provider's key shape.
    blob = json.dumps(media_plane.catalog()).lower()
    assert "sk_" not in blob and "sk-" not in blob, \
        "a key was written into the catalog; it belongs in the integration document"
    # And with the provider not connected, the refusal is the ordinary one and still names the fix.
    _, skipped = media_plane.resolve("text_to_music", {}, {"tokenrouter"}, {})
    assert "you cannot connect one yourself" in media_plane.refusal("text_to_music", skipped)


# ══ a sixth provider, shaped like none of the five ═══════════════════════════════
# ElevenLabs breaks all three assumptions the five TokenRouter shapes share: it is signed in its
# own header, it answers a submit with RAW AUDIO instead of a document, and its model is a PATH
# SEGMENT. Each of those is a place a special case could have gone; these pin that none of them
# did.

def test_the_two_elevenlabs_shapes_are_two_because_their_whitelists_differ():
    """One shape or two is a real choice, and this is the fact that decides it.

    Music takes a length and no voice; speech takes a voice and no length. A single shape's
    whitelist would have to be the UNION of those, which would forward `voice` to the music
    endpoint and `music_length_ms` to the speech one — the exact defect "never forward an
    unrecognised parameter" exists to stop, reintroduced by tidying two adapters into one.

    What the two DO share — the auth header and the raw-audio answer — is expressed once each and
    outside the shape branch, so two shapes cost nothing in duplication.
    """
    music, speech = _el("text_to_music"), _el("text_to_speech")
    assert music["shape"] != speech["shape"]
    assert media_plane.declared_params(music) == {"prompt", "duration"}
    assert media_plane.declared_params(speech) == {"prompt", "voice"}
    # Asserted on the SHAPE and not only on these two entries, because the shape's list is what a
    # candidate added later WITHOUT its own `params` is held to — and because a whitelist is only
    # a whitelist while it still describes its endpoint. Each of these shapes permits EXACTLY what
    # its builder emits when it is offered everything: a permitted field the endpoint has no slot
    # for is dead permission, and the union of the two is four of them.
    bare = {"model": "x", "provider": "elevenlabs"}
    loose = {"prompt": "p", "seconds": 10, "voice": "George"}
    for cand, extra, want in (
            (music, {}, {"prompt", "duration"}),
            (speech, {"voices": speech["voices"]}, {"prompt", "voice"})):
        shape = cand["shape"]
        sent = media_plane.build_submit({**bare, "shape": shape, **extra}, EL, loose)
        assert set(sent.tunables) == set(media_plane._SHAPE_TUNABLES[shape]) == want, (
            shape, sorted(sent.tunables), sorted(media_plane._SHAPE_TUNABLES[shape]))
    # And nothing crossed over: no voice in a music body, no length in a speech one.
    assert "George" not in json.dumps(media_plane.build_submit(music, EL, loose).body)
    assert "10000" not in json.dumps(media_plane.build_submit(speech, EL, loose).body)
    # The shared halves are shared, not copied.
    assert media_plane.provider_meta("elevenlabs")["auth"]["header"] == "xi-api-key"
    for cand in (music, speech):
        _, payload = media_plane.read_submit(
            cand, 200, media_plane.response_doc("audio/mpeg", MP3_SILENCE))
        assert payload.data == MP3_SILENCE and payload.mime == "audio/mpeg"


def test_the_music_request_is_the_one_that_was_measured():
    """POST /v1/music {prompt, music_length_ms} — measured 2026-08-15, and the length is in
    MILLISECONDS while every other duration in this catalog is in seconds."""
    sub = media_plane.build_submit(_el("text_to_music"), EL,
                                   {"prompt": "a warm score", "seconds": 10,
                                    "voice": "Sarah", "not_a_real_param": "boom"})
    assert sub.url == f"{EL}/music"
    assert sub.body == {"prompt": "a warm score", "music_length_ms": 10000}
    assert set(sub.tunables) <= media_plane.declared_params(_el("text_to_music"))
    assert "Sarah" not in json.dumps(sub.body) and "boom" not in json.dumps(sub.body)


def test_the_voice_is_a_path_segment_and_never_a_body_field():
    """The third broken assumption: the model this shape addresses is chosen by the URL.

    A voice id in the body would be silently ignored and a default voice would be billed for —
    the same class of failure as MiniMax ignoring an input image, one layer up.
    """
    cand = _el("text_to_speech")
    sub = media_plane.build_submit(cand, EL, {"prompt": "Hello there.", "voice": "Sarah"})
    vid = cand["voices"]["Sarah"]
    assert sub.url == f"{EL}/text-to-speech/{vid}"
    assert sub.body == {"text": "Hello there.", "model_id": cand["model"]}
    assert vid not in json.dumps(sub.body)


def test_a_model_that_reads_the_line_is_not_told_to_read_it_aloud():
    """The wrapper is a WORKAROUND for a conversational model doing narration, so it belongs to
    the models that need it and to nothing else.

    Measured: gpt-audio answers "Say: hello." with "Hello! It's great to talk with you." — so it
    is sent an instruction. ElevenLabs reads what it is given, so sending it the same instruction
    would make it SAY "Read this aloud exactly as written" out loud. The tool used to build that
    sentence itself, before any model was chosen, which is why it reached both.
    """
    line = "The tide went out and never came back."
    speech = media_plane.build_submit(_el("text_to_speech"), EL, {"prompt": line})
    assert speech.body["text"] == line, "a real reader was handed the workaround"

    chat = next(c for c in media_plane.capability("text_to_speech")["candidates"]
                if c.get("shape") == "audio-chat")
    said = media_plane.build_submit(chat, TR, {"prompt": line})
    assert said.body["messages"][0]["content"].endswith(line)
    assert said.body["messages"][0]["content"] != line, "the model that answers lost its wrapper"
    assert chat["answers_prompts"] is True


def test_audio_and_an_error_arrive_at_the_same_endpoint_and_are_told_apart_by_content_type():
    """The second broken assumption. ONE endpoint answers either, so the code cannot decide by
    hoping — and the two answers mean opposite things about money.

      audio/mpeg + 200  -> the track, and nothing is stood down
      application/json  -> the provider talking. 4xx is a refusal (free, stays in the chain);
                           a 200 that carried a document billed and delivered nothing.
    """
    cand = _el("text_to_music")
    doc = media_plane.response_doc("audio/mpeg", MP3_SILENCE)
    assert media_plane.read_submit(cand, 200, doc)[1].data == MP3_SILENCE

    err = media_plane.response_doc(
        "application/json", b'{"detail":{"message":"Music API is not available for free users."}}')
    with pytest.raises(media_plane.MediaRefused) as refused:
        media_plane.read_submit(cand, 402, err)
    assert "not available for free users" in str(refused.value)
    # The same document at 200 is the expensive one: it answered, so it billed.
    with pytest.raises(media_plane.MediaEmpty):
        media_plane.read_submit(cand, 200, err)
    # And an empty body labelled as audio is not a track either.
    with pytest.raises(media_plane.MediaEmpty):
        media_plane.read_submit(cand, 200, media_plane.response_doc("audio/mpeg", b""))


def test_no_binary_body_is_ever_handed_to_a_json_parser(monkeypatch):
    """160 KB of mp3 through json.loads is waste on every successful call, and the exception it
    raises is indistinguishable from a relay renaming a field. The classification happens first."""
    seen: list[bytes] = []
    real = json.loads

    def watched(s, *a, **kw):
        seen.append(s if isinstance(s, bytes) else str(s).encode())
        return real(s, *a, **kw)

    monkeypatch.setattr(media_plane.json, "loads", watched)
    doc = media_plane.response_doc("audio/mpeg", MP3_SILENCE)
    assert isinstance(doc, media_plane.Raw)
    assert seen == [], f"a binary body reached a JSON parser: {seen}"
    # A document still parses — this is a classifier, not a blanket refusal to read anything.
    assert media_plane.response_doc("application/json; charset=utf-8", b'{"a":1}') == {"a": 1}
    assert seen, "nothing was parsed at all; the classifier swallowed the JSON path too"


def test_the_content_type_only_chooses_the_parser_and_never_vouches_for_the_bytes():
    """`sniff` deliberately never trusts a provider's label. Routing on it here does not soften
    that: an HTML error page labelled audio/mpeg gets through the reader and is refused by
    `verify`, exactly as it always was."""
    lie = b"<!doctype html><html><body>502 Bad Gateway</body></html>"
    _, payload = media_plane.read_submit(_el("text_to_music"), 200,
                                         media_plane.response_doc("audio/mpeg", lie))
    assert payload.data == lie
    with pytest.raises(media_plane.MediaEmpty):
        media_plane.verify("audio", payload.data)


def test_the_auth_style_is_declared_in_the_catalog_and_not_branched_on_a_provider_name():
    """Invariant: the catalog is where a provider's facts live, and "how it is signed" is one.

    A `if provider == "elevenlabs"` beside the socket would be a second place that has to know
    this provider exists, and the next provider would add a third.
    """
    assert media_plane.auth_headers({"api_key": "K", **media_plane.provider_meta("elevenlabs")}) \
        == {"xi-api-key": "K"}
    assert media_plane.auth_headers({"api_key": "K", **media_plane.provider_meta("tokenrouter")}) \
        == {"authorization": "Bearer K"}
    # A provider entry that says nothing about auth still gets the bearer every relay wants.
    assert media_plane.auth_headers({"api_key": "K"}) == {"authorization": "Bearer K"}

    # And no PROVIDER NAME is compared against anywhere in either module. Read out of the syntax
    # tree rather than grepped for, so the rule survives being explained in a comment that has to
    # spell the thing it forbids — and so it catches every spelling instead of the six somebody
    # thought of.
    names = set((media_plane.catalog().get("providers") or {}))
    assert names, "no providers in the catalog; this would pass on an empty file"
    for mod in (app, media_plane):
        for node in ast.walk(ast.parse(Path(mod.__file__).read_text())):
            if not isinstance(node, ast.Compare):
                continue
            for side in [node.left, *node.comparators]:
                assert not (isinstance(side, ast.Constant) and side.value in names), (
                    f"{Path(mod.__file__).name}:{node.lineno} branches on the provider name "
                    f"{side.value!r}; that fact belongs in the catalog")


def test_each_provider_is_signed_in_its_own_header_and_never_in_the_others(client, harness,
                                                                          session, provider):
    """The one that matters once there are two keys: the wrong key in the right header is a
    credential handed to a third party."""
    _calls.clear()
    tok = _cred(harness, session)
    assert _ok(_call(client, tok, "generate_image", {"prompt": "a"}))["media_id"]
    assert _ok(_call(client, tok, "generate_music", {"prompt": "a warm score", "seconds": 10}))
    tr = [c for c in _calls if c["url"].startswith(TR)]
    el = [c for c in _calls if c["url"].startswith(EL)]
    assert tr and el, f"one of the two providers was never called: {[c['url'] for c in _calls]}"
    for c in tr:
        assert c["auth"] == f"Bearer {PROVIDER_KEY}" and c["xi"] == ""
    for c in el:
        assert c["xi"] == ELEVEN_KEY and c["auth"] == ""
    assert ELEVEN_KEY not in json.dumps(tr) and PROVIDER_KEY not in json.dumps(el)


def test_music_is_made_by_a_music_model_and_never_by_a_speech_one(client, harness, session,
                                                                  provider):
    """Invariant 10, now that the capability is available rather than refused: generate_music
    reaches the music endpoint, and no speech model is touched on the way."""
    _calls.clear()
    out = _ok(_call(client, _cred(harness, session), "generate_music",
                    {"prompt": "a warm orchestral score", "seconds": 10}))
    assert out["model"] == "elevenlabs/music-v1" and out["status"] == "succeeded"
    assert [c["url"] for c in _calls] == [f"{EL}/music"]
    assert media_plane.capability("text_to_music")["instead"], \
        "the substitution warning was deleted with the refusal it used to be attached to"


def test_speech_reads_the_line_it_was_given_and_says_so(client, harness, session, provider):
    """The upgrade, end to end: a real reader outranks the two conversational models, the line
    reaches it verbatim, and the tool stops warning about a limitation the model that ran does not
    have."""
    _calls.clear()
    line = "Say: hello."
    out = _ok(_call(client, _cred(harness, session), "generate_speech", {"text": line}))
    assert out["model"] == _el("text_to_speech")["model"]
    assert out["status"] == "succeeded"
    assert "warning" not in out, out.get("warning")
    assert "spoken_text" not in out, "a reader was asked what it said"
    assert out["voice"] == _el("text_to_speech")["default_voice"]
    body = next(c["body"] for c in _calls if "/text-to-speech/" in c["url"])
    assert body["text"] == line


def test_a_voice_a_model_does_not_have_picks_the_model_that_does(client, harness, session,
                                                                 provider):
    """A voice is the caller's, and the chain is filtered by it — so naming `alloy` still reaches
    the model that has one. This is why the tool no longer defaults to `alloy` itself: a default
    written into the tool is a default written for ONE provider, and it skipped the other on every
    call that named no voice."""
    tok = _cred(harness, session)
    assert _ok(_call(client, tok, "generate_speech",
                     {"text": "hello", "voice": "alloy"}))["model"] == "openai/gpt-audio-mini"
    named = _el("text_to_speech")["default_voice"]
    assert _ok(_call(client, tok, "generate_speech",
                     {"text": "hello", "voice": named}))["model"] == _el("text_to_speech")["model"]
    tool = next(t for t in app._MEDIA_MCP_TOOLS if t["name"] == "generate_speech")
    assert "default" not in tool["inputSchema"]["properties"]["voice"], \
        "the tool names one provider's voice as the default for every provider"


def test_the_elevenlabs_key_never_comes_back_out_of_its_own_401(client, harness, session,
                                                                provider):
    """A 401 is the answer guaranteed to quote the key back at you, and this provider's key is a
    different string in a different header — so the scrub has to have been told about it."""
    provider.fail[_el("text_to_speech")["model"]] = (
        401, {"detail": {"message": f"Invalid API key provided: {ELEVEN_KEY}"}})
    provider.fail["elevenlabs/music-v1"] = (
        401, {"detail": {"message": f"Invalid API key provided: {ELEVEN_KEY}"}})
    tok = _cred(harness, session)
    out = _ok(_call(client, tok, "generate_speech", {"text": "hello"}))
    assert out["model"].startswith("openai/gpt-audio"), "the chain did not fall through a 401"
    assert ELEVEN_KEY not in json.dumps(out)
    assert ELEVEN_KEY not in _err(_call(client, tok, "generate_music", {"prompt": "a"}))


def test_a_raw_shape_that_answers_200_with_a_document_is_billed_and_stood_down(client, harness,
                                                                               session, provider):
    """The gemini-3-pro rule, on a shape that has no JSON in it when it works. A 200 carrying a
    document is the provider ANSWERING, which is the only evidence there is that it billed."""
    provider.audio_ctype, provider.audio_bytes = "application/json", b'{"detail":"nope"}'
    tok = _cred(harness, session)
    assert "nothing was charged" not in _err(_call(client, tok, "generate_music",
                                                   {"prompt": "a", "seconds": 10})).lower()
    assert app._media_quarantine.get("elevenlabs/music-v1", 0) > time.time()


def test_the_submit_ceiling_still_holds_when_the_answer_is_binary(client, harness, session,
                                                                  provider, monkeypatch):
    """The auth style and the response mode are new; the ceiling in `_media_call` is not, and
    adding a second of either must not have moved it off the socket."""
    monkeypatch.setattr(app, "_MEDIA_MAX_ADVANCES", 0)
    provider.audio_ctype, provider.audio_bytes = "application/json", b'{"detail":"nope"}'
    _calls.clear()
    _call(client, _cred(harness, session), "generate_speech", {"text": "hello"})
    submits = [c for c in _calls if c["method"] == "POST"]
    assert len(submits) <= 1, f"one generate_speech bought {len(submits)} renders: {submits}"


@pytest.mark.parametrize("base", ["https://api.elevenlabs.io", "https://api.elevenlabs.io/v1"])
def test_both_spellings_of_the_base_url_reach_the_same_endpoint(base):
    """MEASURED, and it cost a round: the connected integration stores this base WITHOUT `/v1`,
    the catalog's default matches it, and both adapters build `/v1/…` on top — so a shape that
    concatenated onto whatever was stored would 404 on one of the two spellings. A 404 from a
    provider reads as "it is down", which is the worst kind of wrong answer to have here.

    Pinned both ways round, because the bug is only visible from the spelling nobody used.
    """
    assert media_plane.build_submit(_el("text_to_music"), base,
                                    {"prompt": "p", "seconds": 10}).url == f"{EL}/music"
    cand = _el("text_to_speech")
    assert media_plane.build_submit(cand, base, {"prompt": "p"}).url \
        == f"{EL}/text-to-speech/{cand['voices'][cand['default_voice']]}"


def test_a_capability_reports_voice_names_and_not_voice_ids(client, harness, session, provider):
    """`list_capabilities` is how an agent learns what to pass to `voice`, so it has to report the
    thing that is passable. An id is a routing detail and a second spelling of the same choice."""
    by = {c["name"]: c for c in _ok(_call(client, _cred(harness, session),
                                          "list_capabilities"))["capabilities"]}
    limits = by["text_to_speech"]["limits"]
    cand = _el("text_to_speech")
    assert limits["voices"] == list(cand["voices"]), limits["voices"]
    assert "answers_prompts" not in limits, "the reader was described as a model that answers"
    assert not any(vid in json.dumps(limits) for vid in cand["voices"].values())
    # And the fallback's own row says the thing an agent most needs before it spends.
    app._media_quarantine[cand["model"]] = time.time() + 900
    again = {c["name"]: c for c in _ok(_call(client, _cred(harness, session),
                                             "list_capabilities"))["capabilities"]}
    assert again["text_to_speech"]["limits"]["answers_prompts"] is True
    assert again["text_to_speech"]["limits"]["voices"] == ["alloy"]


def test_a_model_that_answers_the_prompt_is_never_the_first_choice_for_speech():
    """Declaration order is the preference, and the preference is a MEASURED one — so it is
    asserted against the MEASUREMENT rather than against the entry that happens to be first.

    "The top entry is the ElevenLabs one" would be satisfied by any entry with that name on it,
    including the same conversational model moved up. What actually matters is the property: the
    model this capability reaches for first must be one that READS the line it is given, and the
    ones that answer it are a fallback.
    """
    cands = media_plane.capability("text_to_speech")["candidates"]
    assert not cands[0].get("answers_prompts"), \
        f"{cands[0]['model']} answers prompts and is ranked first for narration"
    assert any(c.get("answers_prompts") for c in cands[1:]), \
        "the conversational models were deleted rather than demoted; they are a real fallback"
    # And the reason they are a fallback and not a substitute is written down where an agent reads
    # it, not only in a comment here.
    assert "answers_prompts" in media_plane.limits_of(cands[-1])


# ══ the canvas ═══════════════════════════════════════════════════════════════════

def test_placing_a_running_job_is_the_intended_path(client, harness, session, provider):
    provider.fail["dreamina-seedance-2-5-hc"] = (400, {"message": "no"})
    tok = _cred(harness, session)
    jid = _ok(_call(client, tok, "generate_video", {"prompt": "rain", "seconds": 6}))["job_id"]
    out = _ok(_call(client, tok, "place",
                    {"items": [{"job_id": jid, "shot": "Shot 1", "caption": "Rain on the window"}]}))
    assert out["placed"][0]["status"] == "running"
    seen = _ok(_call(client, tok, "describe_canvas"))
    kinds = [e["kind"] for e in seen["elements"]]
    assert kinds == ["video", "text"]
    assert seen["elements"][0]["status"] == "running"
    assert seen["shots"] == [{"name": "Shot 1", "element_ids": [e["id"] for e in seen["elements"]]}]
    assert seen["free_space"]["x"] > 0
    # And the job knows its element, so the agent can move it without another read.
    assert _ok(_call(client, tok, "check_jobs", {"job_ids": [jid]}))["jobs"][0]["element_id"]


def test_a_shot_label_given_at_generate_is_the_one_the_canvas_groups_by(client, harness, session,
                                                                       provider):
    """`shot` is declared on all three generate tools and described as "Groups the clip with its
    caption on the canvas". Nothing recorded it: only place and arrange ever read customData.shot,
    so the grouping the description promises happened only if the agent typed the same label again
    by hand — and an agent that believed the description did not.

    Recorded on the JOB, because the job is the only thing that survives between the submit and
    the place call that puts it on the board.
    """
    tok = _cred(harness, session)
    out = _ok(_call(client, tok, "generate_image", {"prompt": "a lift door", "shot": "Shot 3"}))
    assert asyncio.run(app._media_job_get(out["job_id"]))["shot"] == "Shot 3"
    _ok(_call(client, tok, "place",
              {"items": [{"job_id": out["job_id"], "caption": "the doors close"}]}))
    seen = _ok(_call(client, tok, "describe_canvas"))
    assert seen["shots"] == [{"name": "Shot 3",
                              "element_ids": [e["id"] for e in seen["elements"]]}]


def test_a_height_given_for_a_caption_is_the_height_it_gets(client, harness, session, provider):
    """A third sibling of the same shape, found by the same audit: `h` is declared on every place
    item and was read only on the media branch — a text item's height went to the caption default
    however tall the caller said to make it. An unasked-for height still gets that default."""
    tok = _cred(harness, session)
    _ok(_call(client, tok, "place", {"items": [{"text": "a long note", "h": 240},
                                               {"text": "an ordinary caption"}]}))
    els = _ok(_call(client, tok, "describe_canvas"))["elements"]
    assert [e["h"] for e in els] == [240, media_plane.CAPTION_H]


def test_a_shot_named_at_place_still_wins_over_the_one_on_the_job(client, harness, session,
                                                                 provider):
    """The job's label is a default, not an override: an agent that renames a shot while placing
    it means the rename."""
    tok = _cred(harness, session)
    out = _ok(_call(client, tok, "generate_image", {"prompt": "a lift door", "shot": "Shot 3"}))
    _ok(_call(client, tok, "place", {"items": [{"job_id": out["job_id"], "shot": "Shot 9"}]}))
    seen = _ok(_call(client, tok, "describe_canvas"))
    assert [s["name"] for s in seen["shots"]] == ["Shot 9"]


def test_packing_is_driven_by_the_tiles_and_not_by_the_captions(client, harness, session,
                                                                provider):
    """A caption sits under its clip. Counting it as an occupant puts the next clip level with the
    caption instead of level with the clip, and a board drifts down and right one shot at a time."""
    tok = _cred(harness, session)
    ids = [_ok(_call(client, tok, "generate_image", {"prompt": f"f{i}"}))["media_id"]
           for i in range(2)]
    first = _ok(_call(client, tok, "place",
                      {"items": [{"media_id": ids[0], "caption": "under it"}]}))["placed"]
    assert (first[0]["x"], first[0]["y"]) == (40.0, 40.0)
    assert first[1]["y"] > first[0]["y"], "the caption is not under the clip"
    second = _ok(_call(client, tok, "place",
                       {"items": [{"media_id": ids[1]}]}))["placed"][0]
    assert second["y"] == 40.0, "the second tile drifted down past a caption"
    assert second["x"] == first[0]["x"] + first[0]["w"] + 24


def test_the_arrange_flag_on_place_has_two_different_behaviours(client, harness, session,
                                                                provider):
    """A parameter whose two values behave identically is a lie in a schema."""
    tok = _cred(harness, session)
    a = _ok(_call(client, tok, "generate_image", {"prompt": "a"}))
    b = _ok(_call(client, tok, "generate_image", {"prompt": "b"}))
    packed = _ok(_call(client, tok, "place", {"items": [{"media_id": a["media_id"]}]}))
    assert (packed["placed"][0]["x"], packed["placed"][0]["y"]) == (40.0, 40.0)
    loose = _ok(_call(client, tok, "place", {"items": [{"media_id": b["media_id"]}],
                                             "arrange": "none"}))
    assert (loose["placed"][0]["x"], loose["placed"][0]["y"]) == (0.0, 0.0)


def test_describe_canvas_never_returns_raw_scene_json(client, harness, session, provider):
    tok = _cred(harness, session)
    img = _ok(_call(client, tok, "generate_image", {"prompt": "a"}))
    _ok(_call(client, tok, "place", {"items": [{"media_id": img["media_id"]}]}))
    out = _ok(_call(client, tok, "describe_canvas"))
    el = out["elements"][0]
    assert set(el) <= {"id", "kind", "x", "y", "w", "h", "label", "status", "seconds", "model",
                       "job_id", "media_id"}
    assert "versionNonce" not in json.dumps(out) and "seed" not in json.dumps(out)


def test_an_item_must_name_exactly_one_thing(client, harness, session, provider):
    tok = _cred(harness, session)
    img = _ok(_call(client, tok, "generate_image", {"prompt": "a"}))
    both = _err(_call(client, tok, "place",
                      {"items": [{"text": "hi"}, {"media_id": img["media_id"], "text": "also"}]}))
    assert "item 2 named both" in both
    assert "item 1 named neither" in _err(_call(client, tok, "place", {"items": [{"x": 0}]}))


def test_moving_one_element_of_a_shot_moves_the_shot(client, harness, session, provider):
    tok = _cred(harness, session)
    img = _ok(_call(client, tok, "generate_image", {"prompt": "a"}))
    placed = _ok(_call(client, tok, "place", {"items": [{"media_id": img["media_id"],
                                                         "shot": "Shot 1", "caption": "under it",
                                                         "x": 0, "y": 0}]}))
    clip, cap = placed["placed"][0]["element_id"], placed["placed"][1]["element_id"]
    before = {e["id"]: e for e in _ok(_call(client, tok, "describe_canvas"))["elements"]}
    out = _ok(_call(client, tok, "move", {"moves": [{"element_id": clip, "x": 500, "y": 300}]}))
    assert out["moved"] == [clip] and out["not_found"] == []
    after = {e["id"]: e for e in _ok(_call(client, tok, "describe_canvas"))["elements"]}
    assert after[clip]["x"] == 500
    assert after[cap]["x"] == before[cap]["x"] + 500
    assert after[cap]["y"] == before[cap]["y"] + 300


def test_arrange_packs_a_grid_and_a_storyboard(client, harness, session, provider):
    tok = _cred(harness, session)
    for i in range(3):
        img = _ok(_call(client, tok, "generate_image", {"prompt": f"frame {i}"}))
        _ok(_call(client, tok, "place", {"items": [{"media_id": img["media_id"],
                                                    "shot": f"Shot {i + 1}",
                                                    "caption": f"caption {i}"}]}))
    grid = _ok(_call(client, tok, "arrange", {"layout": "grid", "columns": 2}))
    xs = {p["x"] for p in grid["positions"]}
    assert len(grid["positions"]) == 3 and len(xs) == 2

    story = _ok(_call(client, tok, "arrange", {"layout": "storyboard"}))
    ys = [p["y"] for p in story["positions"]]
    assert ys == sorted(ys) and len(story["positions"]) == 6, "captions are not in the rows"


def test_remove_never_deletes_media(client, harness, session, provider):
    tok = _cred(harness, session)
    img = _ok(_call(client, tok, "generate_image", {"prompt": "a"}))
    eid = _ok(_call(client, tok, "place",
                    {"items": [{"media_id": img["media_id"]}]}))["placed"][0]["element_id"]
    out = _ok(_call(client, tok, "remove", {"element_ids": [eid, "el_nope"]}))
    assert out["removed"] == [eid] and out["not_found"] == ["el_nope"]
    assert out["media_kept"] is True
    # And it can be placed again, which is the whole reason to say so.
    again = _ok(_call(client, tok, "place", {"items": [{"media_id": img["media_id"]}]}))
    assert again["placed"][0]["element_id"] != eid


def test_a_finished_image_gets_a_new_file_id_equal_to_its_media_id(client, harness, session,
                                                                   provider):
    """Excalidraw's addFiles will not update a fileId that already exists, so a placeholder swapped
    onto the same id stays a placeholder forever."""
    tok = _cred(harness, session)
    img = _ok(_call(client, tok, "generate_image", {"prompt": "a"}))
    _ok(_call(client, tok, "place", {"items": [{"media_id": img["media_id"]}]}))
    scene = asyncio.run(app._media_scene_read(session))
    el = next(e for e in scene["elements"] if e["type"] == "image")
    assert el["fileId"] == img["media_id"]
    assert scene["files"][img["media_id"]]["id"] == img["media_id"]
    assert scene["files"][img["media_id"]]["dataURL"].endswith(img["media_id"])


def test_the_scene_stays_a_valid_excalidraw_scene(client, harness, session, provider):
    """Invariant 15, as far as Python can assert it: the top-level shape Excalidraw's restore()
    reads, plus our two additions surviving a round trip."""
    tok = _cred(harness, session)
    img = _ok(_call(client, tok, "generate_image", {"prompt": "a"}))
    _ok(_call(client, tok, "place", {"items": [{"media_id": img["media_id"], "shot": "Shot 1"}]}))
    scene = asyncio.run(app._media_scene_read(session))
    assert scene["type"] == "excalidraw" and scene["version"] == 2
    assert set(scene) >= {"type", "version", "source", "elements", "appState", "files",
                          "timeline", "meta"}
    el = scene["elements"][0]
    for k in ("id", "type", "x", "y", "width", "height", "angle", "strokeColor",
              "backgroundColor", "seed", "version", "versionNonce", "isDeleted", "groupIds"):
        assert k in el, k
    # The Map that becomes {} on a round trip and crashes .forEach is never stored.
    assert "collaborators" not in scene["appState"]
    round_tripped = media_plane.sanitize_scene(json.loads(json.dumps(scene)))
    assert round_tripped["timeline"] == scene["timeline"]
    assert round_tripped["elements"][0]["customData"] == el["customData"]


# ══ the timeline and the export ══════════════════════════════════════════════════

def _two_ready_clips(client, tok, provider, session) -> list[str]:
    provider.fail["dreamina-seedance-2-5-hc"] = (400, {"message": "no"})
    ids = []
    for i, (secs, size) in enumerate(((1.0, "128x72"), (1.0, "72x128"))):
        provider.video_bytes = _mp4(secs, size)
        jid = _ok(_call(client, tok, "generate_video",
                        {"prompt": f"shot {i}", "seconds": 6}))["job_id"]
        eid = _ok(_call(client, tok, "place",
                        {"items": [{"job_id": jid, "shot": f"Shot {i + 1}"}]}
                        ))["placed"][0]["element_id"]
        _due(jid)
        asyncio.run(app._media_sweep())
        ids.append(eid)
    return ids


@needs_ffmpeg
def test_the_timeline_is_explicit_order_and_warns_honestly(client, harness, session, provider):
    tok = _cred(harness, session)
    a, b = _two_ready_clips(client, tok, provider, session)
    out = _ok(_call(client, tok, "set_timeline",
                    {"shots": [{"element_id": b}, {"element_id": a}], "fps": 30,
                     "resolution": "1920x1080"}))
    assert out["ready"] is True and out["timeline"]["shots"] == 2
    assert out["total_seconds"] > 0
    assert any("letterboxed" in w for w in out["warnings"]), out
    scene = asyncio.run(app._media_scene_read(session))
    # ARRAY ORDER IS THE CUT ORDER — never re-derived from where things sit on the canvas.
    assert [s["elementId"] for s in scene["timeline"]["shots"]] == [b, a]


@needs_ffmpeg
def test_export_letterboxes_and_validates_its_own_duration(client, harness, session, provider):
    """Invariants 22 and 23. One 9:16 shot in position 1 must not distort the film, and an
    assembled duration nobody checks is one nobody notices is wrong."""
    tok = _cred(harness, session)
    a, b = _two_ready_clips(client, tok, provider, session)
    _ok(_call(client, tok, "set_timeline", {"shots": [{"element_id": a}, {"element_id": b}],
                                            "resolution": "1920x1080", "fps": 24}))
    out = _ok(_call(client, tok, "export_timeline", {}))
    assert out["shots"] == 2 and out["status"] == "running"
    assert "eta" not in json.dumps(out).lower()

    for _ in range(120):
        job = asyncio.run(app._media_job_get(out["job_id"]))
        if job["status"] != "running":
            break
        time.sleep(0.5)
    assert job["status"] == "succeeded", job.get("error")
    assert job["width"] == 1920 and job["height"] == 1080
    assert abs(job["seconds"] - 2.0) < 0.5

    # LETTERBOXED, NOT STRETCHED — read off the actual pixels. Shot 2 is 72x128 (portrait); in a
    # 1920x1080 frame its picture is a centred column with black either side. A film that resized
    # every clip to the first one's shape would paint the whole row blue.
    film = asyncio.run(app._blob_get(app._media_blob(session, job["media_id"], "mp4"),
                                     kb=app.BLOB_KB))
    frame = _frame_at(film, 1.5)
    def px(x, y):
        i = (y * 1920 + x) * 3
        return frame[i], frame[i + 1], frame[i + 2]
    assert max(px(10, 540)) < 40, "the padding is not black — the shot was stretched"
    assert px(960, 540)[2] > 120, "the middle of the frame is not the shot"
    # And shot 1 is 16:9, so it fills the frame edge to edge with no bars.
    first = _frame_at(film, 0.5)
    assert first[(540 * 1920 + 10) * 3 + 2] > 120, "a 16:9 shot was letterboxed anyway"


def _frame_at(mp4: bytes, t: float) -> bytes:
    """One decoded RGB frame of a film, so 'letterboxed, never stretched' is read off pixels
    rather than off a duration nobody looked at."""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "film.mp4")
        Path(src).write_bytes(mp4)
        out = subprocess.run(["ffmpeg", "-nostdin", "-ss", str(t), "-i", src, "-frames:v", "1",
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                             capture_output=True, check=True)
        return out.stdout


@needs_ffmpeg
def test_export_fails_when_the_assembled_length_is_not_the_planned_length(monkeypatch):
    """Invariant 23, at the guard itself. An assembled duration nobody checks is an assembled
    duration nobody notices is wrong — which is exactly how a two-second-short film ships."""
    real = media_plane.probe_file
    with tempfile.TemporaryDirectory() as d:
        clip = os.path.join(d, "a.mp4")
        Path(clip).write_bytes(_mp4(2.0))
        out = os.path.join(d, "out.mp4")

        def short(path):
            got = real(path)
            return {**got, "seconds": 0.2} if path == out else got

        monkeypatch.setattr(media_plane, "probe_file", short)
        with pytest.raises(media_plane.ExportRefused) as e:
            media_plane.assemble([{"path": clip, "in_s": 0.0, "out_s": 2.0}], [], fps=24,
                                 resolution="1920x1080", out_path=out)
    msg = str(e.value)
    assert "0.20s" in msg and "2.00s" in msg, msg
    assert "Nothing was delivered" in msg


@needs_ffmpeg
def test_export_refuses_while_a_shot_is_still_rendering(client, harness, session, provider):
    tok = _cred(harness, session)
    a, _b = _two_ready_clips(client, tok, provider, session)
    provider.fail["dreamina-seedance-2-5-hc"] = (400, {"message": "no"})
    pending = _ok(_call(client, tok, "generate_video", {"prompt": "c", "seconds": 6}))["job_id"]
    eid = _ok(_call(client, tok, "place",
                    {"items": [{"job_id": pending}]}))["placed"][0]["element_id"]
    tl = _ok(_call(client, tok, "set_timeline",
                   {"shots": [{"element_id": a}, {"element_id": eid}]}))
    assert tl["ready"] is False
    assert any("still rendering" in w for w in tl["warnings"])
    assert "still rendering" in _err(_call(client, tok, "export_timeline", {}))


def test_export_refuses_honestly_without_ffmpeg(client, harness, session, provider, monkeypatch):
    """Invariant 24. No silent degradation and no partial file."""
    monkeypatch.setattr(media_plane, "have_ffmpeg", lambda: False)
    tok = _cred(harness, session)
    text = _err(_call(client, tok, "export_timeline", {}))
    assert "ffmpeg is not installed" in text and "still here to download" in text
    caps = {c["name"]: c for c in _ok(_call(client, tok, "list_capabilities"))["capabilities"]}
    assert caps["export"]["available"] is False
    assert "ffmpeg is not installed" in caps["export"]["reason"]


def test_export_with_an_empty_timeline_refuses(client, harness, session, provider):
    assert "nothing in the timeline" in _err(
        _call(client, _cred(harness, session), "export_timeline", {})).lower()


# ══ the app's data plane ═════════════════════════════════════════════════════════

def test_the_app_reads_the_scene_and_the_server_describes_itself(api, harness, session, client,
                                                                 provider):
    tok = _cred(harness, session)
    img = _ok(_call(client, tok, "generate_image", {"prompt": "a"}))
    _ok(_call(client, tok, "place", {"items": [{"media_id": img["media_id"]}]}))

    got = api.get(f"/v1/harnesses/{harness}/servers/{ENTRY_ID}/sessions/{session}/scene").json()
    assert got["rev"] >= 1 and got["scene"]["type"] == "excalidraw"

    desc = api.get(f"/v1/harnesses/{harness}/servers/{ENTRY_ID}").json()
    assert desc["id"] == ENTRY_ID and desc["name"] == "media"
    by = {c["name"]: c for c in desc["capabilities"]}
    assert by["text_to_video"]["available"] is True
    assert by["text_to_music"]["available"] is True
    assert desc["export"]["available"] is media_plane.have_ffmpeg()
    assert "connection" not in desc


def test_the_app_cannot_add_or_delete_a_media_element(api, harness, session, client, provider):
    """Invariant 17: a browser bug must not be able to orphan a rendered clip or resurrect a
    deleted one."""
    tok = _cred(harness, session)
    img = _ok(_call(client, tok, "generate_image", {"prompt": "a"}))
    _ok(_call(client, tok, "place", {"items": [{"media_id": img["media_id"], "caption": "hi"}]}))
    base = f"/v1/harnesses/{harness}/servers/{ENTRY_ID}/sessions/{session}/scene"
    got = api.get(base).json()
    scene = got["scene"]

    stripped = {**scene, "elements": [e for e in scene["elements"]
                                      if not media_plane.is_media(e)]}
    r = api.put(base, json={"scene": stripped}, headers={"if-match": str(got["rev"])})
    assert r.status_code == 422 and r.json()["error"]["code"] == "media_elements_are_the_agents"
    assert api.get(base).json()["rev"] == got["rev"], "the store moved on a refused write"

    # Moving what the person drew, and what they may move, is fine.
    moved = {**scene, "elements": [{**e, "x": 999} for e in scene["elements"]]}
    ok = api.put(base, json={"scene": moved}, headers={"if-match": str(got["rev"])})
    assert ok.status_code == 200 and ok.json()["rev"] == got["rev"] + 1


def test_the_app_write_is_409_while_a_turn_runs_and_412_when_the_revision_moved(
        api, harness, session, client, provider):
    tok = _cred(harness, session)
    img = _ok(_call(client, tok, "generate_image", {"prompt": "a"}))
    _ok(_call(client, tok, "place", {"items": [{"media_id": img["media_id"]}]}))
    base = f"/v1/harnesses/{harness}/servers/{ENTRY_ID}/sessions/{session}/scene"
    got = api.get(base).json()

    stale = api.put(base, json={"scene": got["scene"]}, headers={"if-match": "0"})
    assert stale.status_code == 412 and stale.json()["error"]["code"] == "scene_moved"
    assert stale.json()["error"]["detail"]["rev"] == got["rev"]

    asyncio.run(app._vg_upsert("HarnessSession", session, {"turn_status": "running"}))
    busy = api.put(base, json={"scene": got["scene"]}, headers={"if-match": str(got["rev"])})
    assert busy.status_code == 409 and busy.json()["error"]["code"] == "session_busy"
    asyncio.run(app._vg_upsert("HarnessSession", session, {"turn_status": "idle"}))


def test_the_media_route_serves_ranges(api, harness, session, client, provider):
    """Without Range, Safari refuses to play at all and a timeline cannot scrub."""
    tok = _cred(harness, session)
    img = _ok(_call(client, tok, "generate_image", {"prompt": "a"}))
    url = (f"/v1/harnesses/{harness}/servers/{ENTRY_ID}/sessions/{session}"
           f"/media/{img['media_id']}")
    whole = api.get(url)
    assert whole.status_code == 200 and whole.headers["accept-ranges"] == "bytes"
    assert whole.headers["etag"] == f'"{img["media_id"]}"'
    assert "immutable" in whole.headers["cache-control"]
    assert whole.content == PNG_1PX

    part = api.get(url, headers={"range": "bytes=0-9"})
    assert part.status_code == 206 and len(part.content) == 10
    assert part.headers["content-range"] == f"bytes 0-9/{len(PNG_1PX)}"
    tail = api.get(url, headers={"range": "bytes=-4"})
    assert tail.status_code == 206 and tail.content == PNG_1PX[-4:]
    assert api.get(url, headers={"range": "bytes=999999-"}).status_code == 416


def test_the_apps_job_poll_is_the_same_path_the_agent_takes(api, harness, session, client,
                                                            provider):
    provider.video_bytes = _mp4(1.0)
    tok = _cred(harness, session)
    provider.fail["dreamina-seedance-2-5-hc"] = (400, {"message": "no"})
    jid = _ok(_call(client, tok, "generate_video", {"prompt": "a", "seconds": 6}))["job_id"]
    _due(jid)
    out = api.get(f"/v1/harnesses/{harness}/servers/{ENTRY_ID}/sessions/{session}/jobs"
                  f"?ids={jid}").json()
    assert out["jobs"][0]["job_id"] == jid and out["jobs"][0]["status"] == "succeeded"
    assert out["spend_usd"] == 0.28


def test_the_spend_figure_is_measured_and_absent_when_it_is_not(api, harness, session, client,
                                                                provider):
    """Invariant 30: a session whose jobs reported no cost shows nothing at all, not $0.00."""
    tok = _cred(harness, session)
    _ok(_call(client, tok, "generate_image", {"prompt": "a"}))   # gemini reports no cost
    out = api.get(f"/v1/harnesses/{harness}/servers/{ENTRY_ID}/sessions/{session}/jobs").json()
    assert out["spend_usd"] == 0
    assert out["jobs"][0].get("usd") is None, "a cost nobody measured was reported"


def test_another_org_cannot_reach_any_of_it(client, api, harness, session, provider):
    other = {**HEADERS, "x-harness-org": "someone-else"}
    base = f"/v1/harnesses/{harness}/servers/{ENTRY_ID}/sessions/{session}"
    for r in (client.get(f"/v1/harnesses/{harness}/servers/{ENTRY_ID}", headers=other),
              client.get(f"{base}/scene", headers=other),
              client.get(f"{base}/jobs", headers=other),
              client.get(f"{base}/media/med_anything", headers=other),
              client.post(f"{base}/export", headers=other)):
        _seen.append(r.text)
        assert r.status_code == 404, r.text


def test_deleting_the_session_takes_its_media_with_it(api, harness, session, client, provider):
    tok = _cred(harness, session)
    img = _ok(_call(client, tok, "generate_image", {"prompt": "a"}))
    assert asyncio.run(app._media_meta(session, img["media_id"]))
    api.delete(f"/v1/traces/{session}")
    assert asyncio.run(app._media_meta(session, img["media_id"])) is None
    assert asyncio.run(app._media_jobs_of(session)) == []


# ══ the workspace projection ═════════════════════════════════════════════════════

def test_the_scene_is_projected_into_the_workspace_as_an_ordinary_artifact(client, harness,
                                                                           session, provider):
    """The canvas lives in the store because the gateway cannot durably write a live sandbox's
    workspace mid-turn — but `scene.excalidraw` still has to be a file the console can list."""
    tok = _cred(harness, session)
    img = _ok(_call(client, tok, "generate_image", {"prompt": "a"}))
    _ok(_call(client, tok, "place", {"items": [{"media_id": img["media_id"]}]}))
    raw = asyncio.run(app.BACKING.workspace.read(session, "scene.excalidraw"))
    assert raw, "nothing was projected"
    doc = json.loads(raw)
    assert doc["type"] == "excalidraw" and doc["elements"]
    assert doc["meta"]["rev"] == asyncio.run(app._media_scene_read(session))["meta"]["rev"]


# ══ attacked ═════════════════════════════════════════════════════════════════════
# Findings from an adversarial pass, each written so that PASSING means the attack was repelled.
# They are here rather than in a scratch file because a hole closed once and left untested is a
# hole that comes back the next time someone tidies the code that closed it.

_KEY_IN_A_401 = (f"Incorrect API key provided: {PROVIDER_KEY}. You can find your API key at "
                 f"https://tokenrouter.example/keys")


def _fail_every_candidate(provider, cap: str, status: int, body: dict) -> None:
    """Every model this capability could reach answers the same way — which is what turns one
    provider sentence into the refusal that enumerates all of them."""
    for cand in media_plane.capability(cap)["candidates"]:
        provider.fail[str(cand["model"])] = (status, body)


def test_a_provider_sentence_that_names_the_key_never_reaches_the_agent(client, harness, session,
                                                                        provider):
    """Every major provider echoes the offending credential in its 401 — OpenAI's is literally
    `Incorrect API key provided: sk-…`. The refusal names every candidate it skipped, so one
    un-redacted sentence is the key handed to the sandbox once per candidate in a single tool
    result. The sandbox runs a customer's agent with real bash and real egress."""
    _fail_every_candidate(provider, "text_to_image", 401, {"message": _KEY_IN_A_401})
    body = _err(_call(client, _cred(harness, session), "generate_image", {"prompt": "a cat"}))
    assert PROVIDER_KEY not in body, body[:500]
    # Redacted, not swallowed: the diagnosis is the whole point of relaying the sentence at all.
    assert "Incorrect API key provided" in body


def test_a_credential_shaped_string_is_redacted_even_when_it_is_not_our_key(client, harness,
                                                                            session, provider):
    """A provider says more than our own key out loud: the account it bills, a token it wants us
    to use instead, a signed URL. Matching only the string we configured catches only the leak we
    already knew about."""
    other = "sk-live-9f2b7c41d0e8a35b6c7d8e9f0a1b"
    _fail_every_candidate(provider, "text_to_image", 401, {"message":
        f"key {other} for org-9f2b7c41d0 is revoked; retry as "
        f"https://api.example/v1/x?api_key={other} with Bearer {other}"})
    body = _err(_call(client, _cred(harness, session), "generate_image", {"prompt": "a cat"}))
    for secret in (other, "org-9f2b7c41d0"):
        assert secret not in body, body[:500]
    assert "is revoked" in body


@pytest.mark.parametrize("sentence", [
    "400 unknown model 'eva-video-2.5' (relay maps it to a name the upstream rejects)",
    "Audio output requires stream: true",
    "InvalidParameter: image size must be at least 3686400 pixels, got 1024x1024",
    "fail_to_fetch_task — upstream 'model is not supported'",
    "api_panic: assignment to entry in nil map",
    "code 1201: the image is not valid base64",
    "Your account does not have access to gpt-5-image-mini; api-version 2026-01-01 is required",
    "the render failed upstream after 240s",
])
def test_redaction_leaves_the_diagnosis_completely_intact(sentence):
    """The point of relaying a provider's own sentence is that it diagnoses. A scrubber that eats
    model ids, parameter names, error codes or version strings turns every failure into 'something
    went wrong' — which is the paraphrase this deliberately does not do."""
    assert media_plane.scrub(sentence) == sentence


def _a_job_that_fails_naming_the_key(client, tok, provider) -> str:
    """One video job whose render fails upstream with the key in the failure message, and whose
    fallback is refused the same way. Returns the job id, failed."""
    jid = _ok(_call(client, tok, "generate_video", {"prompt": "rain", "seconds": 6}))["job_id"]
    tid = next(iter(provider.tasks))
    provider.queue_poll(tid, httpx.Response(200, json={"code": "success", "data": {
        "id": tid, "task_id": tid, "status": "FAILURE",
        "message": f"auth rejected for key {PROVIDER_KEY}"}}))
    _fail_every_candidate(provider, "text_to_video", 500,
                          {"message": f"auth rejected for key {PROVIDER_KEY}"})
    _due(jid)
    return jid


def test_a_provider_sentence_that_names_the_key_is_not_written_onto_the_job(client, harness,
                                                                            session, provider):
    """Worse than a transient echo: a billable failure writes the sentence into `attempts` on a
    vertex, where it outlives the turn, the tab and a restart."""
    tok = _cred(harness, session)
    jid = _a_job_that_fails_naming_the_key(client, tok, provider)
    row = _ok(_call(client, tok, "check_jobs", {"job_ids": [jid]}))["jobs"][0]
    assert row["status"] == "failed", row          # the advance really ran
    vertex = asyncio.run(app.BACKING.graph.get(jid, label="MediaJob"))
    assert PROVIDER_KEY not in json.dumps(vertex), json.dumps(vertex.get("attempts_json"))[:500]
    assert PROVIDER_KEY not in json.dumps(row)
    assert "auth rejected" in json.dumps(row)      # and the diagnosis survived


def test_a_provider_sentence_that_names_the_key_is_not_served_to_the_browser(api, client, harness,
                                                                             session, provider):
    """The app's jobs route returns `error`, straight from the same string."""
    tok = _cred(harness, session)
    _a_job_that_fails_naming_the_key(client, tok, provider)
    r = api.get(f"/v1/harnesses/{harness}/servers/{ENTRY_ID}/sessions/{session}/jobs")
    assert '"failed"' in r.text, r.text[:300]      # the advance really ran
    assert PROVIDER_KEY not in r.text, r.text[:500]


def test_a_provider_chosen_task_id_cannot_move_the_poll_to_another_host(client, harness, session,
                                                                         provider):
    """`build_poll` interpolates the provider's OWN task id into a URL, and that poll carries this
    deployment's key. A relay that answers a submit with a task id containing `@` or `../` would
    otherwise choose where the key goes."""
    cand = next(c for c in media_plane.capability("text_to_video")["candidates"]
                if c.get("shape") == "video-generation")
    for hostile in ("x@evil.example", "../../../../evil.example/x", "..%2f..%2fevil.example",
                    "x#@evil.example", "x?@evil.example"):
        poll = media_plane.build_poll(cand, TR, hostile)
        assert httpx.URL(poll.url).host == "api.tokenrouter.com", poll.url

    # The Vercel shape cannot be steered this way at all: its handle never reaches the url. It is
    # posted in the BODY, so a hostile handle is data the provider gets back, not an address.
    vc = next(c for c in media_plane.capability("text_to_video")["candidates"]
              if c.get("shape") == "vercel-video")
    poll = media_plane.build_poll(vc, "https://ai-gateway.vercel.sh/v1", '{"id":"x@evil.example"}')
    assert httpx.URL(poll.url).host == "ai-gateway.vercel.sh", poll.url
    assert poll.method == "POST" and poll.body == {"operation": {"id": "x@evil.example"}}


def test_the_finished_file_is_fetched_without_the_credential(client, harness, session, provider):
    """A result_url is an address the PROVIDER chose. Fetching it must not carry our key."""
    provider.video_bytes = _mp4(1.0)
    jid = _ok(_call(client, _cred(harness, session), "generate_video",
                    {"prompt": "a", "seconds": 6}))["job_id"]
    _due(jid)
    asyncio.run(app._media_sweep())
    fetches = [c for c in _calls if "cdn.provider.example" in c["url"]]
    assert fetches, "the fetch never happened — the assertion below would be vacuous"
    assert all(not c["auth"] for c in fetches), fetches


def test_a_result_url_inside_our_own_network_is_not_fetched(client, harness, session, provider):
    """A result_url is attacker-influenced, and nothing checked it: the gateway reached
    169.254.169.254 — where cloud metadata lives — because a relay named it."""
    provider.video_bytes = _mp4(1.0)
    provider.result_url = "http://169.254.169.254/latest/meta-data/iam/security-credentials/"
    tok = _cred(harness, session)
    jid = _ok(_call(client, tok, "generate_video", {"prompt": "a", "seconds": 6}))["job_id"]
    for _ in range(4):
        if asyncio.run(app._media_job_get(jid))["status"] != "running":
            break
        _due(jid)
        asyncio.run(app._media_sweep())
    inside = [c for c in _calls if "169.254.169.254" in c["url"]]
    assert not inside, [c["url"] for c in inside]
    row = _ok(_call(client, tok, "check_jobs", {"job_ids": [jid]}))["jobs"][0]
    assert row["status"] == "failed" and "AWSSECRET" not in json.dumps(row)


# ── the job model ────────────────────────────────────────────────────────────────

def test_another_agent_cannot_read_this_agents_session_through_the_app(api, client, kit, harness,
                                                                       session, provider,
                                                                       monkeypatch):
    """The app's data plane binds the ENTRY to the harness and the SESSION to the org — and, until
    this, never the session to the harness. So a second agent's own media entry plus this
    session's id read its jobs, its canvas, and the BYTES of its render."""
    provider.video_bytes = _mp4(1.0)
    tok = _cred(harness, session)
    jid = _ok(_call(client, tok, "generate_video",
                    {"prompt": "secret storyboard", "seconds": 6}))["job_id"]
    _ok(_call(client, tok, "place", {"items": [{"text": "CONFIDENTIAL SHOT LIST"}]}))
    _due(jid)
    asyncio.run(app._media_sweep())
    med = asyncio.run(app._media_job_get(jid))["media_id"]
    assert med, "nothing landed — the assertions below would be vacuous"

    kid_b = f"mediab{int(time.time() * 1e6) % 10_000_000}"
    monkeypatch.setattr(app, "_kits", lambda: {kid_b: {**_KIT, "id": kid_b}})
    hid_b = _launch(api, kid_b)["harnessId"]
    base = f"/v1/harnesses/{hid_b}/servers/{ENTRY_ID}/sessions/{session}"
    for path in (f"{base}/jobs", f"{base}/scene", f"{base}/media/{med}"):
        r = api.get(path)
        assert r.status_code >= 400, f"{path} served another agent's session: {r.text[:200]}"
        assert jid not in r.text and "CONFIDENTIAL" not in r.text
    assert api.put(f"{base}/scene", json={"scene": {}}).status_code >= 400
    # and the same session on its OWN agent still works, so this is not passing by refusing
    # everything.
    assert api.get(f"/v1/harnesses/{harness}/servers/{ENTRY_ID}/sessions/{session}"
                   f"/media/{med}").status_code == 200


def test_a_session_that_names_no_agent_is_refused_rather_than_assumed(api, harness):
    """A session that names no agent cannot be proved to belong to this one. Fail closed."""
    sid = "sess_" + os.urandom(6).hex()
    asyncio.run(app._vg_upsert("HarnessSession", sid, {"tenant": ORG, "status": "idle"}))
    r = api.get(f"/v1/harnesses/{harness}/servers/{ENTRY_ID}/sessions/{sid}/scene")
    assert r.status_code == 404, r.text[:200]


def test_deleting_the_agent_stops_and_buries_its_jobs(api, client, kit, provider):
    """DELETE returned 200 and the sweeper carried on: two more provider calls carrying the key,
    and a finished file written into the store — for an agent the owner had deleted."""
    hid = _launch(api, kit)["harnessId"]
    sid = _session_of(hid)
    provider.video_bytes = _mp4(1.0)
    jid = _ok(_call(client, _cred(hid, sid), "generate_video",
                    {"prompt": "a", "seconds": 6}))["job_id"]
    assert api.delete(f"/v1/harnesses/{hid}").status_code == 200

    _due(jid)
    _calls.clear()
    asyncio.run(app._media_sweep())
    assert [c["url"] for c in _calls if "/video/generations/" in c["url"]] == []
    job = asyncio.run(app._media_job_get(jid))
    assert job["status"] != "succeeded" and not job.get("media_id")
    assert asyncio.run(app._blob_list_all(f"media/{sid}/", kb=app.BLOB_KB)) == []
    # Nothing addressed to a deleted agent is still readable, by either door.
    assert _call(client, _cred(hid, sid), "check_jobs",
                 {"job_ids": [jid]}).get("isError") is True
    assert api.get(f"/v1/harnesses/{hid}/servers/{ENTRY_ID}/sessions/{sid}/jobs").status_code >= 400


def test_switching_the_media_server_off_stops_its_jobs_and_switching_it_on_resumes_them(
        api, client, kit, provider):
    """`check_enabled` refuses a TURN; the sweeper never asked, so a server the owner had switched
    off carried on spending. Off is a pause, not a death — the same job finishes when it is back
    on, which is what makes this different from deleting the agent."""
    hid = _launch(api, kit)["harnessId"]
    sid = _session_of(hid)
    provider.video_bytes = _mp4(1.0)
    jid = _ok(_call(client, _cred(hid, sid), "generate_video",
                    {"prompt": "a", "seconds": 6}))["job_id"]

    assert _save_config(api, hid, [{**_entry_of(hid), "enabled": False}]).status_code == 200
    _due(jid)
    _calls.clear()
    asyncio.run(app._media_sweep())
    assert [c["url"] for c in _calls if "/video/generations/" in c["url"]] == []
    assert asyncio.run(app._media_job_get(jid))["status"] == "running"

    assert _save_config(api, hid, [{**_entry_of(hid), "enabled": True}]).status_code == 200
    _due(jid)
    asyncio.run(app._media_sweep())
    assert asyncio.run(app._media_job_get(jid))["status"] == "succeeded"


def test_one_tool_call_buys_at_most_one_fallback_render(client, harness, session, provider):
    """A transient failure fetching the FINISHED file is not a reason to render the whole chain.

    `_media_job_billable_failure` promised to advance EXACTLY ONCE; it advanced once per POLL, and
    there is a poll after every advance. Measured with the CDN 503ing on an otherwise-fine render:
    one generate_video walked all six models, $1.96 of list price, and the agent was told nothing.
    """
    provider.video_bytes = _mp4(1.0)
    provider.cdn_status = 503
    tok = _cred(harness, session)
    jid = _ok(_call(client, tok, "generate_video", {"prompt": "one shot", "seconds": 6}))["job_id"]
    for _ in range(10):
        if asyncio.run(app._media_job_get(jid))["status"] != "running":
            break
        _due(jid)
        asyncio.run(app._media_sweep())
    submits = [c for c in _calls if c["url"].endswith("/video/generations")]
    assert len(submits) <= 2, ("one call bought "
                               f"{len(submits)} renders: {[c['body'].get('model') for c in submits]}")
    job = asyncio.run(app._media_job_get(jid))
    assert job["status"] == "failed"
    # And the money is counted. The budget guard summed only SUCCEEDED jobs, so a session that
    # burned the whole chain read as $0.00 and the cap never fired.
    assert asyncio.run(app._media_spend(session)) >= 0.28


def test_a_media_id_cannot_walk_out_of_its_session(api, client, harness, provider):
    """`med` is agent- and URL-supplied and is interpolated straight into a storage key."""
    sid_a, sid_b = _session_of(harness), _session_of(harness)
    _ok(_call(client, _cred(harness, sid_b), "place",
              {"items": [{"text": "OTHER SESSION SECRET"}]}))
    ref = f"../../sessions/{sid_b}/scene"
    r = api.get(f"/v1/harnesses/{harness}/servers/{ENTRY_ID}/sessions/{sid_a}/media/{ref}")
    assert "OTHER SESSION SECRET" not in r.text
    res = _call(client, _cred(harness, sid_a), "generate_image", {"prompt": "x",
                                                                  "from_image": ref})
    assert "OTHER SESSION" not in json.dumps(res)


# ══ a real generation, only when a key is configured ═════════════════════════════

@needs_live
def test_one_real_image_end_to_end(api, kit, client):
    """The cheapest, fastest verified model, one call, the smallest size it takes. Skipped
    entirely unless HR_TEST_TOKENROUTER_KEY is set."""
    _connect_provider(LIVE_KEY)
    try:
        hid = _launch(api, kit)["harnessId"]
        sid = "sess_" + os.urandom(6).hex()
        asyncio.run(app._vg_upsert("HarnessSession", sid, {"tenant": ORG, "status": "idle"}))
        out = _ok(_call(client, _cred(hid, sid), "generate_image",
                        {"prompt": "a single grey square", "size": "1024x1024"}))
        assert out["status"] == "succeeded", out
        meta = asyncio.run(app._media_meta(sid, out["media_id"]))
        assert meta["bytes"] > 0 and meta["mime"].startswith("image/")
        print(f"[live] {out['model']} produced {meta['bytes']}B", flush=True)
    finally:
        _connect_provider()


@needs_live
def test_the_two_untested_video_models_are_probed_once_each(api, kit, client):
    """MiniMax-Hailuo-2.3 and happyhorse-1.0-t2v were never submitted. ONE submit each, at the
    shortest duration each allows, and the task id is NOT polled to completion — a submit that
    returns a task id is the fact under test.

    A TASK ID, not a status code. `google/gemini-3-pro-image-preview` answers 200 with an empty
    parts list and bills ~1356 tokens for it, so a probe that reads HTTP < 500 as "this model
    works" would record that model as available on every call, for as long as it kept charging.
    Availability is a media payload — read_submit is the one place that decides, and this probe
    goes through it rather than around it.
    """
    _connect_provider(LIVE_KEY)
    try:
        results = {}
        for model, secs in (("MiniMax-Hailuo-2.3", 6), ("happyhorse-1.0-t2v", 3)):
            cand = next(c for c in media_plane.capability("text_to_video")["candidates"]
                        if c["model"] == model)
            sub = media_plane.build_submit(cand, TR, {"prompt": "a grey wall", "seconds": secs})
            r = httpx.post(sub.url, json=sub.body,
                           headers={"authorization": f"Bearer {LIVE_KEY}"}, timeout=60)
            doc = r.json() if r.content else {}
            print(f"[live] {model}: HTTP {r.status_code} {json.dumps(doc)[:200]}", flush=True)
            results[model] = media_plane.read_submit(cand, r.status_code, doc)
        for model, (task_id, payload) in results.items():
            assert task_id or payload is not None, f"{model} answered with no task and no media"
    finally:
        _connect_provider()


# ══ the whole file, checked at once ═══════════════════════════════════════════════

def test_the_provider_key_appears_in_no_response_this_file_produced():
    """Every body recorded above, in one assertion. A new route that leaks the key fails here even
    if nobody thought to test that route."""
    assert _seen, "nothing was recorded — the recording client stopped being used"
    leaked = [t for t in _seen if PROVIDER_KEY in t or ELEVEN_KEY in t]
    assert not leaked, f"{len(leaked)} response(s) contained a provider key: {leaked[:1]}"


def test_each_provider_key_reaches_its_own_provider_and_nothing_else():
    """The other half: they DID go out on the wire, so this is not passing because nothing was
    ever called — and each went to ONE host, in ONE header, over the whole file.

    Two keys is what makes this worth asserting globally. A single sentinel could not tell "signed
    correctly" from "signed with whatever key was lying around", and a second auth style is
    exactly the change that makes the second thing possible.
    """
    assert _all_calls, "no provider call was made — this file would pass on an empty mock"
    outbound = [c for c in _all_calls if "cdn.provider.example" not in c["url"]]
    tr = [c for c in outbound if c["url"].startswith(TR)]
    el = [c for c in outbound if c["url"].startswith(EL)]
    assert tr and el, "one of the two providers was never called"
    assert len(tr) + len(el) == len(outbound), "a call went somewhere unexpected"
    assert all(c["auth"] == f"Bearer {PROVIDER_KEY}" and not c["xi"] for c in tr)
    assert all(c["xi"] == ELEVEN_KEY and not c["auth"] for c in el)


def test_the_provider_key_appears_in_nothing_the_gateway_printed(api, kit, client, provider,
                                                                 capsys):
    """Launch, generate, fail, sweep, delete — then read the logs the container would have written."""
    capsys.readouterr()
    hid = _launch(api, kit)["harnessId"]
    sid = "sess_" + os.urandom(6).hex()
    asyncio.run(app._vg_upsert("HarnessSession", sid, {"tenant": ORG, "status": "idle"}))
    tok = _cred(hid, sid)
    provider.fail["dreamina-seedance-2-5-hc"] = (400, {"message": "unknown model"})
    _call(client, tok, "generate_image", {"prompt": "a"})
    _call(client, tok, "generate_video", {"prompt": "a", "seconds": 6})
    _call(client, tok, "generate_music", {"prompt": "a"})
    asyncio.run(app._media_sweep())
    api.delete(f"/v1/traces/{sid}")
    out = capsys.readouterr()
    for key in (PROVIDER_KEY, ELEVEN_KEY):
        assert key not in out.out and key not in out.err
    # And it did log something identifying, so this is not passing on an empty string.
    assert "[media]" in out.out


def test_the_provider_key_is_on_no_vertex_and_in_no_scene(api, kit, client, provider, session):
    hid = _launch(api, kit)["harnessId"]
    tok = _cred(hid, session)
    _ok(_call(client, tok, "generate_image", {"prompt": "a"}))
    dump = json.dumps(_vertex(hid)) + json.dumps(asyncio.run(app._media_jobs_of(session)))
    dump += json.dumps(asyncio.run(app._media_scene_read(session)))
    assert PROVIDER_KEY not in dump and ELEVEN_KEY not in dump
    # The secret store holds the integration document, and only the integration document.
    root = Path(app.BACKING.secrets._root)
    hits = [p for p in root.rglob("*")
            if p.is_file() and app._INTEGRATIONS_KEY not in p.name
            and any(k in p.read_text(errors="ignore") for k in (PROVIDER_KEY, ELEVEN_KEY))]
    assert hits == [], f"the key was written somewhere it should not be: {hits}"


def test_the_provider_key_is_in_nothing_this_file_wrote_down():
    """The other half of the recording client, and the half a response-only sweep cannot see.

    `_seen` covers what was RETURNED. This covers what was KEPT: every vertex, every job, every
    scene, every stored file and every projected workspace this file produced — the whole data
    directory, which is the entire durable state of a deployment. A key that never appears in a
    response but sits on a graph vertex is the same leak with a much longer half-life, and it is
    exactly the one that shipped.

    Written as a walk of the storage root rather than a list of places to look, so a NEW place to
    write things down is covered on the day it is added rather than on the day someone remembers.
    """
    # This deployment really is holding the sentinel as its credential — otherwise the walk below
    # would pass on a store that never had a key in it.
    doc = json.dumps(asyncio.run(app._integrations_doc()))
    assert PROVIDER_KEY in doc, "the integration is gone — this test is asserting against nothing"

    leaked = []
    for p in Path(_DATA).rglob("*"):
        if not p.is_file() or p.stat().st_size > 64_000_000:
            continue
        try:
            if PROVIDER_KEY in p.read_text(errors="ignore"):
                leaked.append(str(p))
        except OSError:
            continue
    # Nowhere, not even the secret store: the one place it is allowed to live keeps it encrypted.
    assert leaked == [], f"the provider key was written to disk in the clear: {leaked}"
