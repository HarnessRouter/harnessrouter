"""ADVERSARIAL REGRESSIONS for the media plane. Every test here is written so that PASSING means
the attack was repelled; a failure is a finding.

Three properties are held here, each of which was once false and each of which a narrow patch to
the function a finding NAMED left open in the function beside it:

  ONE TOOL CALL, AT MOST `_MEDIA_MAX_ADVANCES + 1` BILLABLE RENDERS. Two walks fall down the
  chain — the SUBMIT walk in `_media_chain` and the POLL walk in `_media_job_billable_failure` —
  and they share one budget, because "this request may buy one more render" is a fact about the
  request and not about which of the two happened to notice.

  A PROVIDER'S DOCUMENT IS SCRUBBED WHERE IT BECOMES OUR DATA. Not on the error channel only: the
  poll's `progress`, the provider-chosen task id and an audio transcript are the same document,
  one field over, and all three are persisted and relayed.

  THIS SERVER FETCHES ONLY AN ADDRESS IT HAS CLASSIFIED. A name it could not resolve — because it
  does not exist, or because the lookup did not answer — is not classified, and every poll is a
  fresh roll of that dice.

Zero generation endpoints are touched: every provider byte goes through httpx.MockTransport, the
same seam tests/test_media_mcp.py uses. Nothing here spends anything.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import socket
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
_DATA = tempfile.mkdtemp(prefix="hr-mediaattack-")
os.environ.update({
    "HR_BACKING": "local", "HR_DATA_DIR": _DATA,
    "HARNESS_WORKSPACE": os.path.join(_DATA, "workspaces"),
    "HR_SECRET_KEY": "test-passphrase-not-a-real-one",
    "HARNESS_INTERNAL_KEY": "test-internal-key",
    "HARNESS_GLOBAL_TENANT": "global",
    "HARNESS_PUBLIC_BASE_URL": "https://gateway.example",
    "HR_POOL_AUTH": "none",
    "HR_IDENTITY_MODE": "off",
    "HR_MEDIA_SWEEP_S": "3600",
})

import app  # noqa: E402
import media_plane  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

# The sweep interval is read when app is imported, and this file is not necessarily the module
# that imported it. Set it directly, so the background sweeper cannot race an assertion about how
# many renders one tool call bought.
app._MEDIA_SWEEP_EVERY_S = 3600

# The data root the app ACTUALLY writes to, which is the one `_disk_hits` has to walk. It is this
# module's temp dir only when this module imported app first; when another test module did, the
# env above arrived too late and a scan of it would find nothing and prove nothing.
_DATA_ROOT = str(Path(getattr(app.BACKING.graph, "_path", os.path.join(_DATA, "graph.db"))).parent)

# The sentinel. Every "the key never comes out" assertion is about this exact string.
PROVIDER_KEY = "sk-tr-SENTINEL-do-not-leak-4f7a9b21"
ORG = "testorg"
HEADERS = {"x-harness-internal": "test-internal-key", "x-harness-org": ORG,
           "x-harness-member": "tester@example.com"}
ENTRY_ID = "mcp.media"
TR = "https://api.tokenrouter.com/v1"

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

_KIT = {"id": "media", "title": "Videos", "app": {"route": "/kits/media"},
        "harness": {"name": "Videos", "mcp_servers": [],
                    "launch": {"media": {"name": "media", "id": ENTRY_ID}},
                    "recommended": [{"base": "claude-code", "model": "claude-opus-5"}]}}

needs_ffmpeg = pytest.mark.skipif(not media_plane.have_ffmpeg(), reason="no ffmpeg on this box")


def _mp4(seconds: float = 1.0, size: str = "128x72") -> bytes:
    """A real, tiny mp4: the gateway refuses a video it cannot measure, so a four-byte stub would
    pass a test the product fails."""
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "c.mp4")
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-f", "lavfi",
                        "-i", f"color=c=blue:s={size}:d={seconds}", "-f", "lavfi",
                        "-i", f"anullsrc=r=44100:cl=stereo:d={seconds}",
                        "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                        "-t", str(seconds), out], capture_output=True, check=True)
        return Path(out).read_bytes()


def _wav() -> bytes:
    return (b"RIFF" + (36 + 8).to_bytes(4, "little") + b"WAVEfmt "
            + (16).to_bytes(4, "little") + (1).to_bytes(2, "little") + (1).to_bytes(2, "little")
            + (8000).to_bytes(4, "little") + (16000).to_bytes(4, "little")
            + (2).to_bytes(2, "little") + (16).to_bytes(2, "little")
            + b"data" + (8).to_bytes(4, "little") + b"\x00" * 8)


# ── a hostile provider ────────────────────────────────────────────────────────────────────────
class Hostile:
    """A relay that behaves like a real one until told to misbehave. Records every outbound
    request INCLUDING its Authorization header, which is the thing under test."""

    def __init__(self):
        self.calls: list[dict] = []
        self.submit_error: tuple[int, dict] | None = None
        self.poll_answer = None
        self.task_id_override: str | None = None
        self.result_url = "https://cdn.provider.example/out.mp4"
        self.video_bytes = b""
        self.tasks: dict[str, str] = {}

    def handle(self, req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content or b"{}") if req.content else {}
        self.calls.append({"method": req.method, "url": str(req.url), "body": body,
                           "auth": req.headers.get("authorization", ""),
                           "host": req.url.host})
        url = str(req.url)

        if url.endswith("/video/generations") and req.method == "POST":
            if self.submit_error:
                return httpx.Response(self.submit_error[0], json=self.submit_error[1])
            tid = self.task_id_override or f"task_{len(self.tasks) + 1}"
            self.tasks[tid] = body.get("model") or ""
            return httpx.Response(200, json={"id": tid, "task_id": tid, "object": "video",
                                             "model": body.get("model"), "status": "queued"})

        if "/video/generations/" in url and req.method == "GET":
            if self.poll_answer is not None:
                return self.poll_answer
            tid = url.rsplit("/", 1)[-1]
            return httpx.Response(200, json={"code": "success", "message": "", "data": {
                "id": tid, "task_id": tid, "platform": "mock", "status": "SUCCESS",
                "result_url": self.result_url}})

        if url.endswith("/images/generations"):
            if self.submit_error:
                return httpx.Response(self.submit_error[0], json=self.submit_error[1])
            return httpx.Response(200, json={"created": 1, "data": [
                {"b64_json": base64.b64encode(PNG_1PX).decode()}]})

        if ":generateContent" in url:
            if self.submit_error:
                return httpx.Response(self.submit_error[0], json=self.submit_error[1])
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [
                {"inlineData": {"mimeType": "image/png",
                                "data": base64.b64encode(PNG_1PX).decode()}}]}}]})

        if url.endswith("/chat/completions"):
            if self.submit_error:
                return httpx.Response(self.submit_error[0], json=self.submit_error[1])
            return httpx.Response(200, json={"choices": [{"message": {"content": None, "images": [
                {"image_url": {"url": "data:image/png;base64,"
                                      + base64.b64encode(PNG_1PX).decode()}}]}}]})

        if url.startswith("https://cdn.provider.example/"):
            data = self.video_bytes or PNG_1PX
            return httpx.Response(200, content=data, headers={
                "content-type": "video/mp4" if url.endswith(".mp4") else "image/png"})

        # ANY other host — this is where an exfiltrated credential would land.
        return httpx.Response(200, content=PNG_1PX, headers={"content-type": "image/png"})


@pytest.fixture()
def hostile(monkeypatch):
    h = Hostile()
    cl = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: h.handle(r)), timeout=30)
    monkeypatch.setattr(app, "_media_client", lambda: cl)
    app._media_quarantine.clear()
    yield h
    asyncio.run(cl.aclose())


@pytest.fixture(autouse=True)
def resolvable_cdn(monkeypatch):
    """The mock provider's CDN lives on a `.example` name, and `.example` resolves nowhere. This
    server will not fetch a file from an address it could not classify, so the fake CDN has to
    resolve the way a real one does — otherwise every landing test would be quietly asserting the
    refusal instead of the thing it was written for.

    Only `.example` is answered. Everything else falls through to the real resolver, which is what
    lets the DNS tests below say "this name does not exist" and mean it.
    """
    real = socket.getaddrinfo

    def fake(host, port, *a, **kw):
        if str(host).endswith(".example"):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                     ("93.184.216.34", int(port or 443)))]
        return real(host, port, *a, **kw)

    monkeypatch.setattr(socket, "getaddrinfo", fake)


@pytest.fixture(scope="module")
def client():
    with TestClient(app.app) as c:
        yield c


def _connect_provider(key: str = PROVIDER_KEY) -> None:
    asyncio.run(app._vault_put(app.GLOBAL_TENANT, app._INTEGRATIONS_KEY, json.dumps(
        [{"name": "tr", "provider": "tokenrouter",
          "config": {"api_key": key, "base_url": TR}}])))


@pytest.fixture(scope="module", autouse=True)
def integration(client):
    _connect_provider()
    app.BACKING.workspace = app.backing.LocalWorkspaceFiles(os.path.join(_DATA, "workspaces"))
    return True


@pytest.fixture()
def kit(monkeypatch):
    kid = f"mediaatk{int(time.time() * 1e6) % 10_000_000}"
    monkeypatch.setattr(app, "_kits", lambda: {kid: {**_KIT, "id": kid}})
    return kid


# ── helpers ───────────────────────────────────────────────────────────────────────────────────
def _launch(client, kit) -> str:
    r = client.post(f"/v1/kits/{kit}/launch", json={}, headers=HEADERS)
    assert r.status_code == 200, r.text
    return r.json()["harnessId"]


def _session(hid: str, org: str = ORG) -> str:
    """A session vertex exactly as the session-create path writes one — `harness_id` and all. The
    field name matters: the whole harness/session bind keys on it."""
    sid = "sess_" + os.urandom(6).hex()
    asyncio.run(app._vg_upsert("HarnessSession", sid,
                               {"tenant": org, "status": "idle", "turn_status": "idle",
                                "harness_id": hid}))
    return sid


def _stored(hid: str) -> list:
    return json.loads(asyncio.run(
        app.BACKING.graph.get(hid, label="Harness")).get("mcp_servers") or "[]")


def _cred(hid: str, sid: str = "") -> str:
    key = app._vault_key(next(s for s in _stored(hid) if s.get("id") == ENTRY_ID)["auth"])
    return app._mint_hosted_cred(hid, sid, key)


def _call(client, tok, name, args=None) -> dict:
    r = client.post("/v1/mcp/media", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                           "params": {"name": name, "arguments": args or {}}},
                    headers={"authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text
    return r.json()["result"]


def _text(res: dict) -> str:
    return res["content"][0]["text"]


def _ok(res: dict) -> dict:
    assert res.get("isError") is not True, _text(res)
    return json.loads(_text(res))


def _due(jid: str) -> None:
    """Make a job due for the sweeper right now. Without this every _media_sweep() is a no-op
    (next_poll_at is 20 s out) and every assertion after it is vacuous."""
    job = asyncio.run(app._media_job_get(jid))
    job["next_poll_at"] = 0
    asyncio.run(app._media_job_save(job))


def _sweep(jid: str | None = None) -> int:
    if jid:
        _due(jid)
    return asyncio.run(app._media_sweep())


def _vertex(jid: str) -> dict:
    return asyncio.run(app.BACKING.graph.get(jid, label="MediaJob")) or {}


def _disk_hits(needle: str) -> list[str]:
    """Every file under the data root holding `needle` in the clear, minus the secret store (which
    is allowed to — that is where the credential legitimately lives)."""
    out = []
    for p in Path(_DATA_ROOT).rglob("*"):
        if not p.is_file() or p.stat().st_size > 8_000_000:
            continue
        try:
            if needle in p.read_text(errors="ignore"):
                if "/secrets/" in str(p) or "secret" in p.name:
                    continue
                out.append(str(p))
        except Exception:  # noqa: BLE001
            pass
    return out


def _assert_clean(needle, label, tool, vertex, browser):
    bad = []
    for where, hay in (("SANDBOX (tool result)", tool), ("VERTEX (durable)", vertex),
                       ("BROWSER (HTTP body)", browser)):
        if needle in hay:
            bad.append(f"{where}: …{hay[max(0, hay.find(needle) - 120):][:260]}")
    bad += [f"DISK: {f}" for f in _disk_hits(needle)]
    assert not bad, f"[{label}] the credential reached:\n" + "\n".join(bad)


def _count_submits(hostile) -> list[str]:
    """Every BILLABLE submit this test causes. Installed OUTSIDE any other handler override, so it
    sees the ones an override answers too."""
    submits: list[str] = []
    real = hostile.handle

    def counting(req):
        u = str(req.url)
        if req.method == "POST" and (u.endswith("/video/generations")
                                     or u.endswith("/images/generations")
                                     or u.endswith("/chat/completions")
                                     or ":generateContent" in u):
            try:
                body = json.loads(req.content or b"{}")
            except Exception:  # noqa: BLE001
                body = {}
            submits.append(str(body.get("model") or u.rsplit("/", 2)[-2]))
        return real(req)

    hostile.handle = counting
    return submits


def _drive_to_terminal(jid: str) -> dict:
    for _ in range(20):
        job = asyncio.run(app._media_job_get(jid))
        if job["status"] != "running":
            return job
        _sweep(jid)
    return asyncio.run(app._media_job_get(jid))


def _fetched_hosts(client, kit_id, hostile, url) -> list[str]:
    """Every host this server opened a socket to while landing a render the provider said lives
    at `url` — minus the provider's own submit/poll endpoint."""
    hid = _launch(client, kit_id)
    sid = _session(hid)
    hostile.result_url = url
    hostile.video_bytes = _mp4()
    jid = _ok(_call(client, _cred(hid, sid), "generate_video",
                    {"prompt": "r", "seconds": 6}))["job_id"]
    _due(jid)
    hostile.calls.clear()
    asyncio.run(app._media_sweep())
    return [c["host"] for c in hostile.calls if "/video/generations" not in c["url"]]


def _five_routes(hid, sid, jid=None, med=None):
    return [
        ("GET   scene", "get", f"/v1/harnesses/{hid}/servers/{ENTRY_ID}/sessions/{sid}/scene",
         None),
        ("PUT   scene", "put", f"/v1/harnesses/{hid}/servers/{ENTRY_ID}/sessions/{sid}/scene",
         {"scene": {"type": "excalidraw", "version": 2, "elements": [], "appState": {}}}),
        ("GET   jobs", "get", f"/v1/harnesses/{hid}/servers/{ENTRY_ID}/sessions/{sid}/jobs", None),
        ("POST  export", "post",
         f"/v1/harnesses/{hid}/servers/{ENTRY_ID}/sessions/{sid}/export", {}),
        ("GET   bytes", "get",
         f"/v1/harnesses/{hid}/servers/{ENTRY_ID}/sessions/{sid}/media/{med or 'med_x'}", None),
    ]


# ══════════════════════════════════════════════════════════════════════════════════════════════
# ONE TOOL CALL, ONE BUDGET — the submit walk, the poll walk, and the fact that they share it
# ══════════════════════════════════════════════════════════════════════════════════════════════

def test_v32_a_billable_empty_answer_does_not_walk_the_whole_image_chain(client, kit, hostile):
    """THE SUBMIT WALK. `_media_chain`, not `_media_job_billable_failure`.

    media_plane raises MediaEmpty for "200 with nothing in it", and the catalog's own words for
    that case are "it billed and returned nothing". The chain caught MediaEmpty and continued to
    the next candidate with no cap at all, so one generate_image where every candidate answers
    200-with-no-image paid for the whole eleven-model chain inside a single tool call — and
    `_MEDIA_MAX_ADVANCES`, which caps the poll walk, never saw it.
    """
    hid = _launch(client, kit)
    sid = _session(hid)
    real = hostile.handle

    def empty200(req):
        u = str(req.url)
        if u.endswith("/images/generations"):
            return httpx.Response(200, json={"created": 1, "data": []})
        if ":generateContent" in u:
            return httpx.Response(200, json={"candidates": [{"content": {"parts": []}}]})
        if u.endswith("/chat/completions"):
            return httpx.Response(200, json={"choices": [{"message": {"content": "sorry"}}]})
        return real(req)

    hostile.handle = empty200
    submits = _count_submits(hostile)
    res = _call(client, _cred(hid, sid), "generate_image", {"prompt": "a cat"})
    assert res.get("isError") is True, res
    assert len(submits) <= app._MEDIA_MAX_ADVANCES + 1, (
        f"ONE generate_image CALL BOUGHT {len(submits)} BILLABLE RENDERS: {submits}")
    # and the agent is TOLD what its one call bought, rather than being handed a bare "no model".
    assert "billed" in _text(res).lower(), _text(res)


def test_v32b_the_speech_chain_is_governed_by_the_same_cap(client, kit, hostile, monkeypatch):
    """Same walk, second capability — so this is a fact about `_media_chain` and not about one
    catalog entry.

    The speech chain is two candidates long, which the shipped cap already bounds at both of them;
    what would still be vacuous is "two is fewer than the whole chain". So the cap itself is moved
    to zero: the walk must be GOVERNED by it and not merely shorter than the chain. Before the
    fix, moving the cap changed nothing here, because the submit walk did not consult it.
    """
    monkeypatch.setattr(app, "_MEDIA_MAX_ADVANCES", 0)
    hid = _launch(client, kit)
    sid = _session(hid)
    real = hostile.handle

    def empty_audio(req):
        if str(req.url).endswith("/chat/completions"):
            return httpx.Response(200, json={"choices": [{"message": {"content": "sorry"}}]})
        return real(req)

    hostile.handle = empty_audio
    submits = _count_submits(hostile)
    res = _call(client, _cred(hid, sid), "generate_speech", {"text": "hello"})
    assert res.get("isError") is True, res
    assert len(submits) <= 1, (
        f"ONE generate_speech CALL BOUGHT {len(submits)} BILLABLE RENDERS with the advance "
        f"budget set to zero: {submits}")


def test_the_two_walks_share_one_budget(client, kit, hostile):
    """THE SIBLING PATH, which is how the last cap was reported closed while costing money.

    One tool call, both walks: candidate 1 answers 200-with-no-image (billable — the SUBMIT walk
    advances), candidate 2 hands back a URL that then 503s (billable — the POLL walk would
    advance). If each walk keeps its own count, one call buys four renders. The count belongs to
    the REQUEST, so it must buy two.
    """
    hid = _launch(client, kit)
    sid = _session(hid)
    real = hostile.handle

    def empty_then_dead_url(req):
        u = str(req.url)
        if ":generateContent" in u:                       # candidate 1: billed, gave nothing
            return httpx.Response(200, json={"candidates": [{"content": {"parts": []}}]})
        if u.endswith("/images/generations"):             # candidate 2: billed, url is dead
            return httpx.Response(200, json={"created": 1, "data": [
                {"url": "https://cdn.provider.example/gone.png"}]})
        if u.startswith("https://cdn.provider.example/gone.png"):
            return httpx.Response(503, content=b"upstream unavailable")
        if u.endswith("/chat/completions"):
            return httpx.Response(200, json={"choices": [{"message": {"content": "sorry"}}]})
        return real(req)

    hostile.handle = empty_then_dead_url
    submits = _count_submits(hostile)
    res = _call(client, _cred(hid, sid), "generate_image", {"prompt": "a cat"})
    if not res.get("isError"):
        _drive_to_terminal(_ok(res)["job_id"])
    assert len(submits) <= app._MEDIA_MAX_ADVANCES + 1, (
        f"ONE generate_image CALL BOUGHT {len(submits)} BILLABLE RENDERS ACROSS THE TWO WALKS: "
        f"{submits}")


def test_a_render_that_billed_at_submit_is_not_forgotten_by_the_job(client, kit, hostile):
    """The mechanism the test above rests on: what the submit walk spent is written ONTO the job,
    which is the only thing that outlives the tool call and the only place the poll walk can read
    it from."""
    hid = _launch(client, kit)
    sid = _session(hid)
    real = hostile.handle

    spent: list[str] = []

    def empty_first(req):
        """Only the FIRST candidate bills and returns nothing; the next one works. So the request
        succeeds — and the job it produced has to remember that one render was already bought."""
        u = str(req.url)
        if ":generateContent" in u and not spent:
            spent.append(u)
            return httpx.Response(200, json={"candidates": [{"content": {"parts": []}}]})
        return real(req)

    hostile.handle = empty_first
    job = _ok(_call(client, _cred(hid, sid), "generate_image", {"prompt": "a cat"}))
    v = _vertex(job["job_id"])
    assert int(float(v.get("advances") or 0)) >= 1, (
        f"a candidate billed inside the submit walk and the job records no advance: {v}")


def test_a_second_render_bought_by_the_same_request_is_also_stood_down(client, kit, hostile):
    """The sibling of the sibling. `_media_job_resubmit` is the one place a billable failure was
    recorded by hand rather than by the function that records billable failures: a candidate it
    reached that billed and gave nothing was neither written down, nor stood down, nor counted —
    so the very next request picked the same broken model and paid again."""
    hid = _launch(client, kit)
    sid = _session(hid)
    # Leave only the shape that hands back a URL, so BOTH candidates this request reaches are ones
    # that bill and then fail to deliver.
    for c in media_plane.capability("text_to_image")["candidates"]:
        if str(c.get("shape")) != "image-generation":
            app._media_quarantine[str(c["model"])] = time.time() + 9999
    real = hostile.handle

    def dead_url(req):
        u = str(req.url)
        if u.endswith("/images/generations"):
            return httpx.Response(200, json={"created": 1, "data": [
                {"url": "https://cdn.provider.example/gone.png"}]})
        if u.startswith("https://cdn.provider.example/gone.png"):
            return httpx.Response(503, content=b"upstream unavailable")
        return real(req)

    hostile.handle = dead_url
    jid = _ok(_call(client, _cred(hid, sid), "generate_image", {"prompt": "a cat"}))["job_id"]
    attempts = json.loads(_vertex(jid).get("attempts_json") or "[]")
    billed = [a for a in attempts if a.get("billed")]
    assert len(billed) == 2, f"a request bought two renders and wrote down {len(billed)}: {attempts}"
    for a in billed:
        assert app._media_quarantine.get(a["model"], 0) > time.time(), (
            f"{a['model']} billed for nothing and is still first in the chain")


# ══════════════════════════════════════════════════════════════════════════════════════════════
# A PROVIDER DOCUMENT IS SCRUBBED WHERE IT BECOMES OUR DATA — not on the error channel only
# ══════════════════════════════════════════════════════════════════════════════════════════════

@needs_ffmpeg
def test_v35_the_progress_string_is_a_provider_string_too(client, kit, hostile):
    """read_poll scrubbed the FAILURE branch and returned `progress` — from the SAME document —
    untouched. It is stored on the vertex, served to the browser and handed to the agent: the
    same three sinks the error text reaches, one field over."""
    hid = _launch(client, kit)
    sid = _session(hid)
    hostile.video_bytes = _mp4()
    jid = _ok(_call(client, _cred(hid, sid), "generate_video",
                    {"prompt": "r", "seconds": 6}))["job_id"]
    hostile.poll_answer = httpx.Response(200, json={"code": "success", "data": {
        "status": "IN_PROGRESS", "progress": f"30% (worker auth: {PROVIDER_KEY})"}})
    _due(jid)
    tool = _text(_call(client, _cred(hid, sid), "check_jobs", {"job_ids": [jid]}))
    vertex = json.dumps(_vertex(jid))
    browser = client.get(f"/v1/harnesses/{hid}/servers/{ENTRY_ID}/sessions/{sid}/jobs",
                         headers=HEADERS).text
    assert "30%" in tool or "30%" in browser, (tool[:300], browser[:300])   # not vacuous
    _assert_clean(PROVIDER_KEY, "poll `progress` field", tool, vertex, browser)


@needs_ffmpeg
def test_v36_a_provider_chosen_task_id_is_not_written_to_disk_in_the_clear(client, kit, hostile):
    """The provider also chooses the task id, and it is persisted verbatim on the job vertex."""
    hid = _launch(client, kit)
    sid = _session(hid)
    hostile.task_id_override = f"task_{PROVIDER_KEY}"
    hostile.video_bytes = _mp4()
    jid = _ok(_call(client, _cred(hid, sid), "generate_video",
                    {"prompt": "r", "seconds": 6}))["job_id"]
    _assert_clean(PROVIDER_KEY, "provider-chosen task id", "", json.dumps(_vertex(jid)), "")


def test_v37_a_provider_transcript_is_a_provider_string_too(client, kit, hostile):
    """gpt-audio's transcript arrives in the same body as the audio, is stored beside the bytes and
    is handed to the agent as `spoken_text`."""
    hid = _launch(client, kit)
    sid = _session(hid)
    real = hostile.handle

    def audio(req):
        if str(req.url).endswith("/chat/completions"):
            return httpx.Response(200, json={"choices": [{"message": {"audio": {
                "data": base64.b64encode(_wav()).decode(),
                "transcript": f"hello (billed to {PROVIDER_KEY})"}}}]})
        return real(req)

    hostile.handle = audio
    res = _call(client, _cred(hid, sid), "generate_speech", {"text": "hello"})
    body = _text(res)
    assert res.get("isError") is not True, body
    assert "hello" in body                                   # not vacuous
    _assert_clean(PROVIDER_KEY, "provider transcript", body, json.dumps(_vertex("")), "")


@needs_ffmpeg
def test_a_signed_result_url_is_still_fetched_verbatim(client, kit, hostile):
    """The other half, and the one an over-broad scrub fails: a result_url IS a credential-bearing
    string — every kling and seedream URL is signed — and it is the address of the file. Redacting
    the signature would repel nothing and lose every render."""
    hid = _launch(client, kit)
    sid = _session(hid)
    signed = "https://cdn.provider.example/out.mp4?signature=abcdef0123456789&key=zyxwvu987654321"
    hostile.result_url = signed
    hostile.video_bytes = _mp4()
    jid = _ok(_call(client, _cred(hid, sid), "generate_video",
                    {"prompt": "r", "seconds": 6}))["job_id"]
    _sweep(jid)
    fetched = [c["url"] for c in hostile.calls if c["host"] == "cdn.provider.example"]
    assert signed in fetched, f"the signed address was not fetched as given: {fetched}"
    assert asyncio.run(app._media_job_get(jid))["status"] == "succeeded"


def test_the_scrub_leaves_our_own_vocabulary_standing(client):
    """A redaction that eats model names, refusal sentences or a task id is a redaction nobody can
    diagnose against — and a mangled task id is a render that can never be polled."""
    for name in media_plane.capability_names():
        for cand in media_plane.capability(name).get("candidates") or []:
            model = str(cand.get("model") or "")
            assert media_plane.scrub(model) == model, model
            reason = str(cand.get("reason") or "")
            assert media_plane.scrub(reason) == reason, reason
    for tid in ("task_1", "cgt-2026081512345678", "9f8a7b6c-1234-4f5e-8a9b-0c1d2e3f4a5b",
                "7529431068442312704"):
        assert media_plane.scrub(tid) == tid, tid


# ══════════════════════════════════════════════════════════════════════════════════════════════
# THIS SERVER FETCHES ONLY AN ADDRESS IT HAS CLASSIFIED
# ══════════════════════════════════════════════════════════════════════════════════════════════

@needs_ffmpeg
@pytest.mark.parametrize("url,host", [
    ("http://169.254.169.254/latest/meta-data/iam/security-credentials/", "169.254.169.254"),
    ("http://127.0.0.1:8080/admin", "127.0.0.1"),
    ("http://[::1]:9000/x.mp4", "::1"),
    ("http://10.1.2.3/internal.mp4", "10.1.2.3"),
    ("http://192.168.0.7/x.mp4", "192.168.0.7"),
    ("http://172.16.9.9/x.mp4", "172.16.9.9"),
    ("http://0.0.0.0/x.mp4", "0.0.0.0"),
    ("http://2130706433/x.mp4", "2130706433"),          # decimal 127.0.0.1
    ("http://127.1/x.mp4", "127.1"),
])
def test_v24_internal_addresses_are_refused(client, kit, hostile, url, host):
    assert host not in _fetched_hosts(client, kit, hostile, url), f"THE GATEWAY FETCHED {url}"


@needs_ffmpeg
@pytest.mark.parametrize("url", ["file:///etc/passwd", "gopher://127.0.0.1:11211/_x",
                                 "ftp://10.0.0.1/x", "//169.254.169.254/x"])
def test_v25_non_http_schemes_are_refused(client, kit, hostile, url):
    hosts = _fetched_hosts(client, kit, hostile, url)
    assert not hosts, f"{url} produced outbound calls to {hosts}"


@needs_ffmpeg
def test_v26_an_unresolvable_internal_name_is_refused(client, kit, hostile):
    """The finding named TWO addresses that were reached: 169.254.169.254 and
    http://internal.svc/admin. This is the second one, and it is the one an "it does not resolve,
    so it is not internal" rule lets straight through: our lookup failing says nothing about what
    the socket will do a millisecond later, in a cluster where `.svc` is a search domain.
    """
    hosts = _fetched_hosts(client, kit, hostile, "http://internal.svc/admin")
    assert "internal.svc" not in hosts, (
        f"THE GATEWAY STILL FETCHES http://internal.svc/admin. hosts touched = {hosts}")


@needs_ffmpeg
def test_v27_a_public_url_that_redirects_to_metadata_is_not_followed(client, kit, hostile):
    """A check on the URL the provider names is worthless if a 302 moves the socket afterwards."""
    hid = _launch(client, kit)
    sid = _session(hid)
    real = hostile.handle

    def redirecting(req):
        if req.url.host == "cdn.provider.example" and str(req.url).endswith("hop.mp4"):
            return httpx.Response(302, headers={
                "location": "http://169.254.169.254/latest/meta-data/"})
        return real(req)

    hostile.handle = redirecting
    hostile.result_url = "https://cdn.provider.example/hop.mp4"
    hostile.video_bytes = _mp4()
    jid = _ok(_call(client, _cred(hid, sid), "generate_video",
                    {"prompt": "r", "seconds": 6}))["job_id"]
    _due(jid)
    hostile.calls.clear()
    asyncio.run(app._media_sweep())
    hit = [c["url"] for c in hostile.calls if c["host"] == "169.254.169.254"]
    assert not hit, f"A REDIRECT MOVED THE FETCH TO LINK-LOCAL METADATA: {hit}"


def test_v28_the_shared_classifier_still_refuses_what_it_could_not_classify(client, monkeypatch):
    """One rule, one answer: a host that does not resolve is refused for the MCP and database
    callers too, and that is their whole contract."""
    bad_name = "this-name-does-not-exist-hr-test.invalid"
    assert asyncio.run(app._internal_target(bad_name, 443)) is not None
    monkeypatch.setattr(app, "_pool_is_local", lambda: False)
    assert asyncio.run(app._ssrf_check(f"https://{bad_name}/x")) is not None
    assert asyncio.run(app._ssrf_check("https://169.254.169.254/")) is not None
    assert asyncio.run(app._ssrf_check("https://10.0.0.9/mcp")) is not None


def test_v28b_a_transient_dns_failure_does_not_open_the_provider_url_check(client, monkeypatch):
    """`except Exception: return None` does not only mean NXDOMAIN. A resolver timeout, a
    momentarily unreachable resolver, an EAI_AGAIN under load — each one made the provider-URL
    check answer "fine" about an address it had NOT classified. The one caller whose URL is chosen
    by a remote party was the one caller that failed open, and every poll is a fresh roll.
    """
    real = socket.getaddrinfo

    def flaky(host, port, *a, **kw):
        if host == "rebind.attacker.example":
            raise socket.gaierror(socket.EAI_AGAIN, "Temporary failure in name resolution")
        return real(host, port, *a, **kw)

    monkeypatch.setattr(socket, "getaddrinfo", flaky)
    assert asyncio.run(app._provider_url_check("http://rebind.attacker.example/x.mp4")) is not None, (
        "a name whose lookup merely TIMED OUT was accepted as an address to fetch; the same name "
        "resolving to 10.0.0.5 on the next lookup is the whole SSRF")


def test_a_name_that_does_not_exist_and_one_we_could_not_look_up_are_told_apart(monkeypatch):
    """Both are refused — an address this server cannot classify is one it does not open a socket
    to — but they are DIFFERENT facts, and the operator reading the log is the one who needs them
    apart: one is a bad URL, the other is a broken resolver."""
    real = socket.getaddrinfo

    def flaky(host, port, *a, **kw):
        if host == "flaky.attacker.example":
            raise socket.gaierror(socket.EAI_AGAIN, "Temporary failure in name resolution")
        return real(host, port, *a, **kw)

    monkeypatch.setattr(socket, "getaddrinfo", flaky)
    gone = asyncio.run(app._internal_target("this-name-does-not-exist-hr-test.invalid", 443))
    unknown = asyncio.run(app._internal_target("flaky.attacker.example", 443))
    assert gone and unknown and gone != unknown, (gone, unknown)


# ══════════════════════════════════════════════════════════════════════════════════════════════
# THE CANARY — every rule above must leave the rightful owner working
# ══════════════════════════════════════════════════════════════════════════════════════════════

@needs_ffmpeg
def test_v12_the_rightful_harness_is_still_served_on_all_five_routes(client, kit, hostile):
    """The half an over-broad patch fails: a fix that 404s everything repels every attack in this
    file and ships a dead canvas."""
    hid = _launch(client, kit)
    sid = _session(hid)
    hostile.video_bytes = _mp4()
    jid = _ok(_call(client, _cred(hid, sid), "generate_video",
                    {"prompt": "r", "seconds": 6}))["job_id"]
    _call(client, _cred(hid, sid), "place", {"items": [{"job_id": jid}]})
    _sweep(jid)
    med = asyncio.run(app._media_job_get(jid))["media_id"]
    assert med, "the render never landed; this test would prove nothing"
    codes = {}
    for label, verb, path, body in _five_routes(hid, sid, jid, med):
        r = getattr(client, verb)(path, headers=HEADERS, **({"json": body} if body else {}))
        codes[label] = r.status_code
    assert codes["GET   scene"] == 200, codes
    assert codes["GET   jobs"] == 200, codes
    assert codes["GET   bytes"] == 200, codes
    # PUT scene may legitimately 412/422 (revision / media-element rules); it must NOT 404.
    assert codes["PUT   scene"] != 404, codes
    # export may legitimately 400 (nothing on the timeline); it must NOT 404.
    assert codes["POST  export"] != 404, codes


@needs_ffmpeg
def test_an_ordinary_render_still_lands(client, kit, hostile):
    """The plainest thing the product does, asserted after every rule above — because each of them
    sits directly on this path."""
    hid = _launch(client, kit)
    sid = _session(hid)
    hostile.video_bytes = _mp4()
    jid = _ok(_call(client, _cred(hid, sid), "generate_video",
                    {"prompt": "r", "seconds": 6}))["job_id"]
    _sweep(jid)
    job = asyncio.run(app._media_job_get(jid))
    assert job["status"] == "succeeded", job
    assert job["media_id"], job


# ══════════════════════════════════════════════════════════════════════════════════════════════
# ROUND 3 — THE CEILING IS ON THE WALK, NOT ON THE EXITS
#
# The same finding was closed twice and found three times, each time in a sibling path, because
# each fix capped the `except` the finding NAMED. `MediaEmpty` was capped and `MediaError` was
# not; `_media_job_billable_failure` was capped and `_media_chain` was not. So the count moved to
# where the loop is: one gate, read before the socket is opened, so an exception type invented
# next year is bounded by it without anyone remembering that it should be.
# ══════════════════════════════════════════════════════════════════════════════════════════════

def test_v38_a_200_with_no_task_id_does_not_walk_the_whole_video_chain(client, kit, hostile):
    """THE MOST EXPENSIVE CHAIN IN THE CATALOG, bought whole by one tool call.

    Every candidate answers HTTP 200 with a body that carries no task id — which media_plane's own
    sentence calls "the provider accepted the request but returned no task id". That was raised as
    `MediaRefused`, whose docstring says "before any billable work started", so the cap that keyed
    on `MediaEmpty` never saw it: six submits, none of them stood down, and the agent was told
    "nothing was generated and nothing was charged".
    """
    hid = _launch(client, kit)
    sid = _session(hid)
    real = hostile.handle

    def no_task_id(req):
        if str(req.url).endswith("/video/generations") and req.method == "POST":
            return httpx.Response(200, json={"object": "video", "status": "queued"})
        return real(req)

    hostile.handle = no_task_id
    submits = _count_submits(hostile)
    res = _call(client, _cred(hid, sid), "generate_video", {"prompt": "a cat", "seconds": 6})
    assert res.get("isError") is True, res
    assert len(submits) <= app._MEDIA_MAX_ADVANCES + 1, (
        f"ONE generate_video CALL BOUGHT {len(submits)} 200-ANSWERS: {submits}")
    assert "charged" not in _text(res) or "billed" in _text(res).lower(), (
        f"models billed and the agent was told nothing was charged: {_text(res)}")


def test_v38b_a_200_whose_body_is_not_an_object_does_not_walk_the_image_chain(client, kit,
                                                                             hostile):
    """The same event as `data: []`, one JSON container type over. `data: []` was `MediaEmpty` and
    capped; a bare list was `MediaRefused` and uncapped — eight submits from one call."""
    hid = _launch(client, kit)
    sid = _session(hid)
    real = hostile.handle

    def not_an_object(req):
        u = str(req.url)
        if (u.endswith("/images/generations") or ":generateContent" in u
                or u.endswith("/chat/completions")):
            return httpx.Response(200, json=[{"b64_json": "not-where-we-look"}])
        return real(req)

    hostile.handle = not_an_object
    submits = _count_submits(hostile)
    res = _call(client, _cred(hid, sid), "generate_image", {"prompt": "a cat"})
    assert res.get("isError") is True, res
    assert len(submits) <= app._MEDIA_MAX_ADVANCES + 1, (
        f"ONE generate_image CALL BOUGHT {len(submits)} 200-ANSWERS: {submits}")


def test_v38c_free_failures_interleaved_with_billable_ones_still_cap_the_billable(client, kit,
                                                                                 hostile):
    """A 4xx costs nothing and IS walked past — that is the policy that keeps the owner's
    preferred model at rank 1 through an outage. Interleaving them with billable answers must not
    launder the billable ones past the cap."""
    hid = _launch(client, kit)
    sid = _session(hid)
    real = hostile.handle
    seen: list[str] = []

    def mixed(req):
        u = str(req.url)
        if (u.endswith("/images/generations") or ":generateContent" in u
                or u.endswith("/chat/completions")):
            seen.append(u)
            if len(seen) % 2 == 1:
                return httpx.Response(429, json={"error": {"message": "rate limited"}})
            if u.endswith("/images/generations"):
                return httpx.Response(200, json={"created": 1, "data": []})
            if ":generateContent" in u:
                return httpx.Response(200, json={"candidates": [{"content": {"parts": []}}]})
            return httpx.Response(200, json={"choices": [{"message": {"content": "sorry"}}]})
        return real(req)

    hostile.handle = mixed
    submits = _count_submits(hostile)
    res = _call(client, _cred(hid, sid), "generate_image", {"prompt": "a cat"})
    assert res.get("isError") is True, res
    billable = [s for i, s in enumerate(seen) if i % 2 == 1]
    assert len(billable) <= app._MEDIA_MAX_ADVANCES + 1, (
        f"ONE CALL BOUGHT {len(billable)} BILLABLE RENDERS among {len(submits)} submits")


def test_v38d_parallel_calls_in_one_turn_share_one_budget(client, kit, hostile, monkeypatch):
    """THE AGENT PARALLELISES. The whole rule is that a second render is the agent's decision made
    with the first one's cost in front of it — which is not true of a call that was already in
    flight when the first one billed. Four generate_image calls in flight at once, every candidate
    answering 200-with-no-image: four private budgets buy the entire chain in one turn.

    The four are held at the gateway door until all four have arrived, because "were they really
    concurrent" is thread-scheduling luck and this test is not about luck: it asserts that calls
    which ARE concurrent share one budget. What bounds the calls that do not overlap is the
    stand-down, asserted below — no model may be bought twice across the whole turn.
    """
    hid = _launch(client, kit)
    sid = _session(hid)
    real = hostile.handle

    def empty200(req):
        u = str(req.url)
        if u.endswith("/images/generations"):
            return httpx.Response(200, json={"created": 1, "data": []})
        if ":generateContent" in u:
            return httpx.Response(200, json={"candidates": [{"content": {"parts": []}}]})
        if u.endswith("/chat/completions"):
            return httpx.Response(200, json={"choices": [{"message": {"content": "sorry"}}]})
        return real(req)

    hostile.handle = empty200
    submits = _count_submits(hostile)
    tok = _cred(hid, sid)

    real_generate = app._media_generate
    arrived = {"n": 0}

    async def all_four_first(*a, **kw):
        """Every call is inside its budget by the time any of them submits — which is exactly the
        turn the agent issued, and not four turns that happened to be quick."""
        arrived["n"] += 1
        deadline = time.time() + 10
        while arrived["n"] < 4 and time.time() < deadline:
            await asyncio.sleep(0.005)
        assert arrived["n"] >= 4, "the four calls never overlapped; this test proved nothing"
        return await real_generate(*a, **kw)

    monkeypatch.setattr(app, "_media_generate", all_four_first)
    import concurrent.futures as cf
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(lambda _: _call(client, tok, "generate_image", {"prompt": "a cat"}), range(4)))
    assert len(submits) <= app._MEDIA_MAX_ADVANCES + 1, (
        f"ONE TURN (4 parallel tool calls) BOUGHT {len(submits)} BILLABLE RENDERS: {submits}")


def test_v38e_a_200_that_delivered_nothing_stands_the_model_down_too(client, kit, hostile):
    """What stops a loop across CALLS is the stand-down, not the per-request cap. A failure mode
    that bills and does not quarantine buys the same models again on the very next call — three
    sequential generate_video calls bought eighteen renders."""
    hid = _launch(client, kit)
    sid = _session(hid)
    real = hostile.handle

    def no_task_id(req):
        if str(req.url).endswith("/video/generations") and req.method == "POST":
            return httpx.Response(200, json={"object": "video", "status": "queued"})
        return real(req)

    hostile.handle = no_task_id
    submits = _count_submits(hostile)
    tok = _cred(hid, sid)
    for _ in range(3):
        _call(client, tok, "generate_video", {"prompt": "a cat", "seconds": 6})
    assert len(submits) <= 3 * (app._MEDIA_MAX_ADVANCES + 1), (
        f"THREE generate_video CALLS BOUGHT {len(submits)} 200-ANSWERS: {submits}")
    assert len(set(submits)) == len(submits), (
        f"a model that billed for nothing was picked twice: {submits}")


def test_v38f_an_exception_type_nobody_wrote_an_except_for_is_bounded_too(client, kit, hostile,
                                                                         monkeypatch):
    """THE STRUCTURAL ONE, and the reason this round exists.

    Every previous fix capped the `except` the finding named, so the next failure shape found the
    next uncapped branch. Here a failure type that did not exist when the cap was written is
    raised out of the submit. Nobody has written a branch for it and nobody ever will — the walk
    must still stop, because the count is taken where the loop is and not where the exits are.
    """
    class _AFailureNobodyPlannedFor(media_plane.MediaError):
        pass

    def raising(cand, status, doc):
        raise _AFailureNobodyPlannedFor("a shape this code has never seen")

    monkeypatch.setattr(media_plane, "read_submit", raising)
    hid = _launch(client, kit)
    sid = _session(hid)
    submits = _count_submits(hostile)
    res = _call(client, _cred(hid, sid), "generate_image", {"prompt": "a cat"})
    assert res.get("isError") is True, res
    assert len(submits) <= app._MEDIA_MAX_SUBMITS, (
        f"AN UNPLANNED FAILURE TYPE WALKED {len(submits)} SUBMITS OF THE CHAIN: {submits}")


def test_v38g_a_walk_that_billed_and_delivered_nothing_is_in_the_session_spend(client, kit,
                                                                              hostile):
    """An untraceable charge is worse than a visible failure — the rule the job store already
    states about a fetch that fails after a synchronous render. A submit walk that bought two
    renders and delivered none left NO record at all, so the session read $0.00 and the budget
    that is supposed to stop a runaway session never saw a cent of it."""
    hid = _launch(client, kit)
    sid = _session(hid)
    real = hostile.handle

    def no_task_id(req):
        if str(req.url).endswith("/video/generations") and req.method == "POST":
            return httpx.Response(200, json={"object": "video", "status": "queued"})
        return real(req)

    hostile.handle = no_task_id
    res = _call(client, _cred(hid, sid), "generate_video", {"prompt": "a cat", "seconds": 6})
    assert res.get("isError") is True, res
    # MiniMax-Hailuo-2.3 is the one candidate this walk reaches with a MEASURED price ($0.28).
    assert asyncio.run(app._media_spend(sid)) >= 0.28, (
        "two renders billed inside one submit walk and the session reports none of it")


# ══════════════════════════════════════════════════════════════════════════════════════════════
# ROUND 3 — A POLL THAT RAISES MUST STILL LEAVE THE JOB SOMEWHERE
# ══════════════════════════════════════════════════════════════════════════════════════════════

@needs_ffmpeg
def test_v39_a_dead_socket_on_a_resolvable_cdn_does_not_poll_for_ever(client, kit, hostile):
    """THE FETCH, not the resolver. Only the resolver-failure INPUT was closed last round; the
    mechanism was never touched. `_media_fetch` is wrapped in `except media_plane.MediaError` and
    httpx raises its own class, so any CDN host that resolves and then refuses the socket escapes
    the poll BEFORE next_poll_at is bumped and before the age check — and every caller swallows
    it. Production polls every ten seconds: one provider poll CARRYING THE KEY plus one CDN fetch,
    for ever, presenting to the person as a placeholder that never resolves and never errors.
    """
    hid = _launch(client, kit)
    sid = _session(hid)
    hostile.video_bytes = _mp4()
    jid = _ok(_call(client, _cred(hid, sid), "generate_video",
                    {"prompt": "r", "seconds": 6}))["job_id"]
    real = hostile.handle

    def dead_socket(req):
        if req.url.host == "cdn.provider.example":
            raise httpx.ConnectError("connection refused", request=req)
        return real(req)

    hostile.handle = dead_socket
    fetches: list[int] = []
    for _ in range(5):
        before = len([c for c in hostile.calls if c["host"] == "cdn.provider.example"])
        _sweep(jid)
        fetches.append(len([c for c in hostile.calls if c["host"] == "cdn.provider.example"])
                       - before)
    job = asyncio.run(app._media_job_get(jid))
    assert job["status"] != "running", (
        f"five sweeps and the job is still running; fetches per sweep {fetches}, "
        f"next_poll_at {job['next_poll_at']}, backoff {job['poll_backoff_s']}")
    assert job.get("error"), "the job ended with no sentence for the person"


@needs_ffmpeg
def test_v39b_a_poll_that_raises_anything_still_leaves_the_job_due_later(client, kit, hostile,
                                                                        monkeypatch):
    """The general shape of the one above. Whatever a poll raises — including a bug of ours — the
    job it was polling is left either terminal or due later. Otherwise `next_poll_at` stays where
    it was, the age check never runs, and the sweeper re-polls the same job every ten seconds for
    ever while every caller's blanket `except` says nothing."""
    hid = _launch(client, kit)
    sid = _session(hid)
    hostile.video_bytes = _mp4()
    jid = _ok(_call(client, _cred(hid, sid), "generate_video",
                    {"prompt": "r", "seconds": 6}))["job_id"]

    async def boom(job):
        raise RuntimeError("a bug nobody has found yet")

    monkeypatch.setattr(app, "_media_job_poll", boom)
    _sweep(jid)
    job = asyncio.run(app._media_job_get(jid))
    assert job["status"] != "running" or job["next_poll_at"] > time.time() * 1000, (
        f"the poll raised and left the job due immediately for ever: {job}")


@needs_ffmpeg
def test_v39c_a_credential_in_the_exempt_result_url_reaches_no_sink(client, kit, hostile):
    """`Payload.url` is deliberately not scrubbed, because a signed result_url IS its query
    string. The claim that makes that safe is that it is fetched once and never persisted or
    relayed — so put this deployment's own key in it and check every sink."""
    hid = _launch(client, kit)
    sid = _session(hid)
    hostile.result_url = f"https://cdn.provider.example/out.mp4?api_key={PROVIDER_KEY}"
    hostile.video_bytes = _mp4()
    jid = _ok(_call(client, _cred(hid, sid), "generate_video",
                    {"prompt": "r", "seconds": 6}))["job_id"]
    _sweep(jid)
    tool = _text(_call(client, _cred(hid, sid), "check_jobs", {"job_ids": [jid]}))
    vertex = json.dumps(_vertex(jid))
    browser = client.get(f"/v1/harnesses/{hid}/servers/{ENTRY_ID}/sessions/{sid}/jobs",
                         headers=HEADERS).text
    _assert_clean(PROVIDER_KEY, "the exempt result_url", tool, vertex, browser)


@needs_ffmpeg
def test_v39d_the_scrub_removes_our_keys_and_names_the_shape_it_cannot(client, kit, hostile):
    """THE STATED LIMIT, pinned so the next reader finds it as a fact rather than as a surprise.

    Our own credentials are exact-matched and are removed from anywhere in a provider document.
    A THIRD PARTY's token, in a field that is not an error, survives unless its shape happens to
    be in the pattern list — and the list is deliberately not grown to catch every vendor prefix,
    because the same characters are what a provider's task ids are made of and a redacted task id
    is a render nobody can poll. This test holds both halves: the guarantee, and its edge.
    """
    hid = _launch(client, kit)
    sid = _session(hid)
    hostile.video_bytes = _mp4()
    jid = _ok(_call(client, _cred(hid, sid), "generate_video",
                    {"prompt": "r", "seconds": 6}))["job_id"]
    foreign = "hf_QeRtYuIoPaSdFgHjKlZxCvBnM1234567890"
    hostile.poll_answer = httpx.Response(200, json={"code": "success", "data": {
        "status": "IN_PROGRESS",
        "progress": f"30% for {PROVIDER_KEY} (worker {foreign})"}})
    _due(jid)
    tool = _text(_call(client, _cred(hid, sid), "check_jobs", {"job_ids": [jid]}))
    assert PROVIDER_KEY not in tool and PROVIDER_KEY not in json.dumps(_vertex(jid)), (
        f"OUR OWN key survived a non-error field: {tool[:300]}")
    assert media_plane.scrub(foreign) == foreign, (
        "the pattern list grew to cover third-party prefixes — check it cannot eat a task id, "
        "then update the note in media_plane.scrub that says it does not")


# ══════════════════════════════════════════════════════════════════════════════════════════════
# ROUND 3 — THE RESOLVER: what it classifies, what it costs, and what it does NOT promise
# ══════════════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("mapped", ["::ffff:127.0.0.1", "::ffff:10.0.0.5",
                                    "::ffff:169.254.169.254", "64:ff9b::7f00:1", "fd00::1",
                                    "::ffff:100.64.0.1"])
def test_v40_ipv6_forms_of_an_internal_address_are_classified(monkeypatch, mapped):
    real = socket.getaddrinfo

    def fake(host, port, *a, **kw):
        if host == "v6.attacker.example":
            return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", (mapped, int(port or 443), 0, 0))]
        return real(host, port, *a, **kw)

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    assert asyncio.run(app._internal_target("v6.attacker.example", 443)) is not None, mapped
    assert asyncio.run(app._provider_url_check("http://v6.attacker.example/x.mp4")) is not None, (
        mapped)


@pytest.mark.parametrize("addr", ["100.64.0.1", "100.127.255.254", "100.64.99.7"])
def test_v40b_carrier_grade_nat_is_internal(monkeypatch, addr):
    """100.64.0.0/10 is what a managed Kubernetes cluster hands its pods and nodes. Python's
    ipaddress does not call it private, so it was the one whole range this classifier allowed —
    a provider naming a pod address would have had this server fetching from inside the cluster.
    """
    real = socket.getaddrinfo

    def fake(host, port, *a, **kw):
        if host == "cgnat.attacker.example":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, int(port or 443)))]
        return real(host, port, *a, **kw)

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    assert asyncio.run(app._internal_target("cgnat.attacker.example", 443)) is not None, addr


def test_v40c_a_slow_lookup_does_not_stall_the_event_loop():
    """Every provider URL is resolved on every poll. Resolving on the event loop stalls the whole
    process for the resolver's timeout: measured, a 1.01 s lookup produced ZERO heartbeat ticks,
    so one relay naming a slow-resolving host froze every other request in the gateway."""
    real = socket.getaddrinfo

    def slow(host, port, *a, **kw):
        if host == "slow.attacker.test":
            time.sleep(1.0)
            raise socket.gaierror(socket.EAI_NONAME, "nope")
        return real(host, port, *a, **kw)

    async def drive():
        ticks = {"n": 0}

        async def heartbeat():
            while True:
                ticks["n"] += 1
                await asyncio.sleep(0.02)

        hb = asyncio.create_task(heartbeat())
        await asyncio.sleep(0.1)
        base = ticks["n"]
        await asyncio.to_thread(lambda: None)          # warm the pool
        t0 = time.time()
        await app._provider_url_check("http://slow.attacker.test/x.mp4")
        wall = time.time() - t0
        gained = ticks["n"] - base
        hb.cancel()
        return wall, gained

    saved = socket.getaddrinfo
    socket.getaddrinfo = slow
    try:
        wall, gained = asyncio.run(drive())
    finally:
        socket.getaddrinfo = saved
    assert gained > wall * 20, (
        f"the event loop made {gained} ticks while a {wall:.2f}s DNS lookup ran; it was blocked")


def test_v40d_the_classifier_does_not_promise_to_stop_a_dns_rebind(monkeypatch):
    """WHAT IT DOES NOT DO, pinned because a comment claiming otherwise is worse than no comment.

    Resolving every answer defeats a multi-A record whose second address is internal. It does NOT
    defeat a TTL-0 rebind: httpx opens the socket with its OWN lookup, so a name that answers
    public here can answer 10.0.0.5 a millisecond later. Two halves are held: the classifier still
    catches what it claims to catch (a name whose FIRST answer is internal), and the docstring no
    longer tells the next reader that the connection is pinned to what was checked.
    """
    real = socket.getaddrinfo
    n = {"i": 0}

    def rebinding(host, port, *a, **kw):
        if host == "rebind.attacker.test":
            n["i"] += 1
            ip = "93.184.216.34" if n["i"] == 1 else "10.0.0.5"
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, int(port or 443)))]
        return real(host, port, *a, **kw)

    monkeypatch.setattr(socket, "getaddrinfo", rebinding)
    assert asyncio.run(app._provider_url_check("http://rebind.attacker.test/x.mp4")) is None
    assert asyncio.run(app._internal_target("rebind.attacker.test", 80)) is not None
    doc = (app._internal_target.__doc__ or "").lower()
    assert "cannot rebind" not in doc, (
        "the docstring still promises the check survives a rebind between the check and the "
        "connection; it does not, and the next reader will build on the promise")
    assert "rebind" in doc, "the limit is not written down where the next reader will find it"
