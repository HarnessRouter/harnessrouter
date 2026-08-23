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

import ast
import asyncio
import base64
import inspect
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

from fs_workspace import FsWorkspaceFiles

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
    app.BACKING.workspace = FsWorkspaceFiles(os.path.join(_DATA, "workspaces"))
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


@pytest.mark.parametrize("tree", ["inside the MediaError tree", "outside it"])
def test_v38f_an_exception_type_nobody_wrote_an_except_for_is_bounded_too(client500, client, kit,
                                                                         hostile, monkeypatch,
                                                                         tree):
    """THE STRUCTURAL ONE, and the reason round 3 existed.

    Every previous fix capped the `except` the finding named, so the next failure shape found the
    next uncapped branch. Here a failure type that did not exist when the cap was written is
    raised out of the submit. Nobody has written a branch for it and nobody ever will — the walk
    must still stop, and the agent must still get a sentence.

    ITS OWN BLIND SPOT, closed here: this used to raise a SUBCLASS of MediaError only, which is
    the one kind of surprise every handler in the media plane already catches. The failure that
    actually happens is a relay renaming a field, and that arrives as an AttributeError — outside
    the tree, past every `except MediaError`, out of the route as an HTTP 500. A test that only
    ever raises inside the tree proves the tree, not the boundary.
    """
    class _AFailureNobodyPlannedFor(media_plane.MediaError):
        pass

    def raising(cand, status, doc):
        if tree.startswith("inside"):
            raise _AFailureNobodyPlannedFor("a shape this code has never seen")
        raise AttributeError("'str' object has no attribute 'get'")

    monkeypatch.setattr(media_plane, "read_submit", raising)
    hid = _launch(client, kit)
    sid = _session(hid)
    submits = _count_submits(hostile)
    res = _call(client500, _cred(hid, sid), "generate_image", {"prompt": "a cat"})
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
                                    "::ffff:100.64.0.1",
                                    # fec0::/10, IPv6 site-local. Deprecated by RFC 3879 and
                                    # therefore neither is_private nor is_reserved in Python —
                                    # so it was the one whole IPv6 range this let through, on
                                    # exactly the reasoning that let CGNAT through.
                                    "fec0::1", "feff:ffff:ffff:ffff::1"])
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


# ══════════════════════════════════════════════════════════════════════════════════════════════
# ROUND 5 — THE CHOKE POINT: every outbound submit, and every answer to one
#
# Four rounds capped the branch the last finding named and the one beside it made the next submit:
# the poll path, then one branch of the submit walk, then the walk's loop. What every one of them
# missed is that a submit is not made by a walk — it is made by `_media_call`, which is the ONE
# place a socket is opened to a provider with this deployment's key on it. The tests here are
# written against that fact rather than against any walk, so a caller nobody has written yet is
# covered by them.
# ══════════════════════════════════════════════════════════════════════════════════════════════

@pytest.fixture()
def client500():
    """A client that does NOT re-raise a server exception, so a 500 is measurable AS a 500.

    The default TestClient re-raises, which turns "the agent got an HTTP error instead of a tool
    result" — the thing under test — into a crashed test whose message names a random provider
    field. The app is already started by the module-scoped client fixture; this one only skips
    the re-raise.
    """
    return TestClient(app.app, raise_server_exceptions=False)


def _payload_200(url: str) -> httpx.Response:
    """A 200 saying, in whatever shape this endpoint speaks, "your render is over there" — where
    over there is a file that will not land. The provider has billed by now: this is the
    synchronous shape's hand-off, and it is the step that let one tool call reach the resubmit."""
    if url.endswith("/images/generations"):
        return httpx.Response(200, json={"created": 1, "data": [
            {"url": "https://cdn.provider.example/gone.png"}]})
    if url.endswith("/chat/completions"):
        return httpx.Response(200, json={"choices": [{"message": {"content": None, "images": [
            {"image_url": {"url": "https://cdn.provider.example/gone.png"}}]}}]})
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [
        {"inlineData": {"mimeType": "image/png",
                        "data": base64.b64encode(b"not a picture").decode()}}]}}]})


def _is_submit(req: httpx.Request) -> bool:
    u = str(req.url)
    return req.method == "POST" and (u.endswith("/video/generations")
                                     or u.endswith("/images/generations")
                                     or u.endswith("/chat/completions")
                                     or ":generateContent" in u)


def test_v41_the_ceiling_holds_across_the_hand_off_from_the_walk_to_the_resubmit(client, kit,
                                                                                 hostile):
    """FIVE SUBMITS FROM ONE TOOL CALL, all inside the ceiling that says four.

    `_MEDIA_MAX_SUBMITS` says "whatever the provider answers", and it was claimed at the top of
    `_media_chain`'s loop — so it counted the walk and nothing else. `_media_job_resubmit` opens
    its own socket without asking, and one generate_image REACHES IT INSIDE THE SAME TOOL CALL:
    a synchronous shape answers 200, the file will not land, `_media_job_billable_failure` spends
    the job's one advance and resubmits. Measured: three 4xx then a 200 whose URL 504s bought
    submits from five different models, each carrying the key out of this process.

    Note what this test does NOT do: it names no branch. Whether the fifth submit comes from the
    resubmit, from a retry somebody adds next year or from a walk nobody has written, four is
    four — which is only true if the count is taken where the socket is opened.
    """
    hid = _launch(client, kit)
    sid = _session(hid)
    real = hostile.handle
    n = {"i": 0}

    def three_refusals_then_a_dead_file(req):
        if _is_submit(req):
            n["i"] += 1
            if n["i"] <= 3:
                return httpx.Response(429, json={"error": {"message": "rate limited"}})
            return _payload_200(str(req.url))
        if str(req.url).startswith("https://cdn.provider.example/gone.png"):
            return httpx.Response(504, content=b"gateway timeout")
        return real(req)

    hostile.handle = three_refusals_then_a_dead_file
    submits = _count_submits(hostile)
    _call(client, _cred(hid, sid), "generate_image", {"prompt": "a cat"})
    assert len(submits) <= app._MEDIA_MAX_SUBMITS, (
        f"ONE generate_image MADE {len(submits)} OUTBOUND SUBMITS against a ceiling of "
        f"{app._MEDIA_MAX_SUBMITS}: {submits}")


def test_v41b_the_budget_is_claimed_where_the_socket_is_opened_and_nowhere_else(client, kit,
                                                                                hostile):
    """THE STRUCTURAL ONE. Every round so far was closed by a check in the branch that had just
    been found, and every round after it arrived through the branch beside that one. The property
    that ends the series is not "these two callers are capped" — it is that a claim cannot be
    skipped, because there is exactly one place that can open an outbound submit and it claims
    before it opens.

    So: no function in app.py other than `_media_call` may touch the budget, and `_media_call`
    may not be reachable without one. A caller written next year by somebody who read none of
    this is then bounded whether or not they knew there was a budget.
    """
    src = Path(app.__file__).read_text()
    tree = ast.parse(src)
    owner = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for n in ast.walk(fn):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                    and n.func.attr in ("claim", "free"):
                owner.setdefault(n.func.attr, set()).add(fn.name)
    assert owner.get("claim") == {"_media_call"}, (
        f"the budget is claimed in {sorted(owner.get('claim') or [])} — a submit made by any of "
        f"the others is a submit outside the count, which is how the last four rounds survived")
    assert owner.get("free") == {"_media_call"}, (
        f"the budget is given back in {sorted(owner.get('free') or [])}; claim and free have to "
        f"be the same pair of hands or the money count drifts")

    for name in ("_media_call", "_media_job_resubmit", "_media_job_billable_failure",
                 "_media_job_advance", "_media_job_poll"):
        assert "budget" in inspect.signature(getattr(app, name)).parameters, (
            f"{name} takes no budget, so whatever it submits is outside the ceiling")

    # AND IT IS THE REQUEST'S BUDGET, which is the half the signature above cannot say. A caller
    # writing `_media_job_advance(job, _MediaBudget())` satisfies every assertion up to here and
    # is the original bug verbatim: a private ceiling per call bounds nothing, and that is exactly
    # what `_MediaBudget.for_job` used to hand the poll walk — one budget per JOB, `submits` back
    # at zero, so the number could not refuse a thing. A budget built with NO ARGUMENT starts a
    # new count, and a new count may only begin where a request does — an agent's turn, a sweep
    # pass, a browser tick, and nothing finer than one of those.
    fresh = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for n in ast.walk(fn):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) \
                    and n.func.id == "_MediaBudget" and not n.args and not n.keywords:
                fresh.add(fn.name)
    assert fresh == {"_media_budget_for", "_media_sweep", "get_media_jobs"}, (
        f"a fresh submit count is started in {sorted(fresh)}. Every name here claims to be the "
        f"start of a request — an agent's turn, a sweep pass, a browser tick: one budget per "
        f"anything smaller — per job, per call, per candidate — is a ceiling that counts only "
        f"itself, and no number binds it")


def test_v41c_a_renamed_provider_field_is_a_tool_result_and_not_an_http_error(client500, client,
                                                                              kit, hostile):
    """A RELAY CHANGED A FIELD'S SHAPE — the exact event this whole catalog is built around.

    `_read_submit`'s openai branch reads `im["image_url"]["url"]`. Hand it a string where the
    object was and it raises AttributeError, which is not in the MediaError tree — so
    `_media_chain`'s handler never sees it, `_media_walk_spend` never runs and the promise that
    every failure is a tool result and never an HTTP error is broken. Measured: HTTP 500, four
    submits, one of them billed $0.048, and the session's spend reading $0.0000.

    Two things are asserted, because either alone is half a fix: the agent gets a sentence, and
    the money that was spent getting it is where the session budget can see it.
    """
    hid = _launch(client, kit)
    sid = _session(hid)
    # Leave only the shape whose field was renamed, so this is a test about that field and not
    # about which candidate happened to be first.
    for c in media_plane.capability("text_to_image")["candidates"]:
        if str(c.get("shape")) != "openai":
            app._media_quarantine[str(c["model"])] = time.time() + 9999
    real = hostile.handle

    def renamed(req):
        if str(req.url).endswith("/chat/completions"):
            return httpx.Response(200, json={"choices": [{"message": {
                "content": None,
                "images": [{"image_url": "https://cdn.provider.example/x.png"}]}}]})
        return real(req)

    hostile.handle = renamed
    submits = _count_submits(hostile)
    res = _call(client500, _cred(hid, sid), "generate_image", {"prompt": "a cat"})
    assert res.get("isError") is True, res
    assert len(submits) <= app._MEDIA_MAX_SUBMITS, (
        f"a body-shape bug walked {len(submits)} submits: {submits}")
    # mai-image-2.5 is the one openai-shape candidate carrying a MEASURED price ($0.048188).
    assert asyncio.run(app._media_spend(sid)) > 0, (
        "a 200 billed, the body could not be read, and the session reports having spent nothing")


@pytest.mark.parametrize("exit_", ["age-out", "poll says FAILURE"])
def test_v41d_both_ways_a_render_ends_agree_that_it_was_bought(client, kit, hostile, monkeypatch,
                                                               exit_):
    """TWO EXITS, ONE EVENT. A submit that came back with a task id billed — a 200 is the provider
    answering, which is the only evidence there is either way.

    A poll that answers FAILURE goes through `_media_job_billable_failure`: banked, stood down,
    counted. A job that simply never finishes goes through the age-out in `_media_job_stalled`,
    which wrote `status: failed` and nothing else — no `billed_usd`, no quarantine. The same
    render, the same money, two different answers, and the one the age-out gave is the one that
    made the session read $0.00 and put the dead model back at rank 1 for the next call.
    """
    if exit_ == "age-out":
        monkeypatch.setattr(media_plane, "JOB_MAX_S", 0)
        answer = {"status": "IN_PROGRESS"}
    else:
        answer = {"status": "FAILURE", "message": "the render failed upstream"}
    hostile.poll_answer = httpx.Response(200, json={"code": "success", "data": answer})
    hid = _launch(client, kit)
    sid = _session(hid)
    # MiniMax-Hailuo-2.3 is the first video candidate with a measured price ($0.28).
    app._media_quarantine["dreamina-seedance-2-5-hc"] = time.time() + 9999
    jid = _ok(_call(client, _cred(hid, sid), "generate_video",
                    {"prompt": "a cat", "seconds": 6}))["job_id"]
    assert asyncio.run(app._media_job_get(jid))["model"] == "MiniMax-Hailuo-2.3"
    _sweep(jid)
    assert app._media_quarantine.get("MiniMax-Hailuo-2.3", 0) > time.time(), (
        f"[{exit_}] a render that was paid for and delivered nothing is still first in the chain")
    assert asyncio.run(app._media_spend(sid)) >= 0.28, (
        f"[{exit_}] $0.28 of render was bought and the session reports "
        f"${asyncio.run(app._media_spend(sid)):.2f}")


def test_v41e_three_calls_that_all_age_out_do_not_buy_the_same_model_three_times(client, kit,
                                                                                 hostile,
                                                                                 monkeypatch):
    """The symptom the exit above produces in a session: measured, three sequential generate_video
    calls bought dreamina-seedance-2-5-hc three times, because ageing out stood nothing down."""
    monkeypatch.setattr(media_plane, "JOB_MAX_S", 0)
    hostile.poll_answer = httpx.Response(200, json={"code": "success",
                                                    "data": {"status": "IN_PROGRESS"}})
    hid = _launch(client, kit)
    sid = _session(hid)
    tok = _cred(hid, sid)
    picked = []
    for _ in range(3):
        jid = _ok(_call(client, tok, "generate_video",
                        {"prompt": "a cat", "seconds": 6}))["job_id"]
        picked.append(asyncio.run(app._media_job_get(jid))["model"])
        _sweep(jid)
        assert asyncio.run(app._media_job_get(jid))["status"] == "failed"
    assert len(set(picked)) == 3, (
        f"a model that was paid for and never delivered was bought again: {picked}")


def test_v41f_a_backing_store_blip_in_the_liveness_check_leaves_the_job_due_later(client, kit,
                                                                                  hostile,
                                                                                  monkeypatch):
    """The invariant is stated one call too narrowly. `_media_job_live` runs BEFORE the try that
    carries "a polled job comes out terminal or due later", and it catches only HTTPException —
    so a backing-store blip escapes, `next_poll_at` is never bumped, and the sweeper re-reads the
    same job every ten seconds for as long as the gateway runs. No provider call and no key on
    this path: this is graph churn and a placeholder that never resolves, not spend.
    """
    hid = _launch(client, kit)
    sid = _session(hid)
    jid = _ok(_call(client, _cred(hid, sid), "generate_video",
                    {"prompt": "a cat", "seconds": 6}))["job_id"]

    async def blip(_hid):
        raise RuntimeError("the backing store hiccuped")

    monkeypatch.setattr(app, "_vertex_get", blip)
    for _ in range(5):
        _sweep(jid)
    job = asyncio.run(app._media_job_get(jid))
    assert job["status"] != "running" or job["next_poll_at"] > time.time() * 1000, (
        f"five sweeps with a blipping store left the job due immediately for ever: {job}")


def test_v41g_no_test_in_this_suite_asserts_on_a_coroutine_nobody_awaited(client500):
    """A DEAD TEST IS WORSE THAN A MISSING ONE, and this is the way they die here.

    Half of what is under test is `async def`, and a coroutine object is truthy: the moment a
    checked function goes async, `assert app._provider_url_check(u)` stops calling anything and
    starts asserting that an object exists. It passes for ever, the warning scrolls past, and the
    property it was written for is unguarded. Found live: three such assertions, two of which
    were the only cover a rule had.

    `client500` is here so this file's app is imported the same way as everywhere else.
    """
    async_names = {}
    for mod in (app, media_plane):
        tree = ast.parse(Path(mod.__file__).read_text())
        async_names[Path(mod.__file__).stem] = {
            n.name for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)}
    alias = {"app": "app", "media_plane": "media_plane"}

    dead = []
    for path in sorted(Path(__file__).parent.glob("test_*.py")):
        tree = ast.parse(path.read_text())
        settled = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Await):
                settled.add(id(n.value))
            if isinstance(n, ast.Call):
                fn = n.func
                nm = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                if nm in ("run", "gather", "create_task", "run_until_complete", "wait_for",
                          "ensure_future"):
                    # Everything underneath one of these IS driven — including a comprehension
                    # inside a gather, which is how the concurrency tests here are written.
                    for arg in list(n.args) + [k.value for k in n.keywords]:
                        settled.update(id(x) for x in ast.walk(arg))
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and isinstance(n.func.value, ast.Name)):
                continue
            mod, name = alias.get(n.func.value.id), n.func.attr
            if not mod or name not in async_names.get(mod, ()) or id(n) in settled:
                continue
            dead.append(f"{path.name}:{n.lineno}: {mod}.{name}(…) is never awaited")
    assert not dead, (
        "these assertions are about a coroutine object and not about what it does:\n  "
        + "\n  ".join(dead))


# ══════════════════════════════════════════════════════════════════════════════════════════════
# ROUND 6 — THE CEILING BELONGS TO THE REQUEST, AND A BAD ARGUMENT IS STILL A SENTENCE
#
# Round 5 moved the claim to the socket, which made `_MEDIA_MAX_SUBMITS` true of the SUBMIT walk
# for a caller that had never heard of it. It left the number DECORATIVE on the three POLL
# entries: each built one budget per JOB out of what that job had already spent, so `submits`
# started at zero every time and the walk ceiling could not refuse anything. Measured: one
# check_jobs over six failing jobs made six outbound submits against a ceiling of four, and moving
# the ceiling did not move the count.
#
# NOT AN OVERSPEND, and these tests must not be read as claiming one. Per job the money rule held
# — `advances` still capped each job at `_MEDIA_MAX_ADVANCES + 1` renders — and the total across
# all sweeps was unchanged. It is a BURST, not extra money. What was wrong is that the constant
# says "how many outbound submits ONE REQUEST may make AT ALL" and that sentence was false on all
# three poll entries. A ceiling that claims more than it counts is how four rounds survived.
# ══════════════════════════════════════════════════════════════════════════════════════════════

def _running_video_jobs(client, hid, sid, n: int) -> list[str]:
    """`n` jobs that a provider has accepted and is rendering. Every one on the first candidate,
    so they all fail the same way and the count below is about the ceiling and not about which
    model happened to answer."""
    return [_ok(_call(client, _cred(hid, sid), "generate_video",
                      {"prompt": f"shot {i}", "seconds": 6}))["job_id"] for i in range(n)]


@pytest.mark.parametrize("entry", ["check_jobs", "the sweeper", "the app's jobs route"])
def test_v42_one_poll_pass_makes_no_more_submits_than_the_ceiling_it_names(client, kit, hostile,
                                                                          entry):
    """SIX SUBMITS FROM ONE READ. `_MEDIA_MAX_SUBMITS` is four.

    A poll that answers FAILURE advances the chain, and advancing the chain opens a socket with
    this deployment's key on it. The budget that submit is claimed against was built by
    `_MediaBudget.for_job`, which seeds only `billed` — so on a poll pass the walk counter was
    always zero and `claim()` always said yes. What actually bounded the path was the `advances`
    check one branch over in `_media_job_billable_failure`: a guard beside the socket, which is
    the exact construction round 5 set out to delete.

    All three poll entries are driven, because a cap on one of them is a cap on one of them: an
    agent's check_jobs, the background sweep and the browser's own tick each walk the same
    `_media_job_advance` and each used to walk it with a private ceiling per job.
    """
    hid = _launch(client, kit)
    sid = _session(hid)
    jids = _running_video_jobs(client, hid, sid, 6)
    hostile.poll_answer = httpx.Response(200, json={"code": "success", "data": {
        "status": "FAILURE", "message": "the render failed upstream"}})
    for jid in jids:
        _due(jid)
    submits = _count_submits(hostile)          # installed AFTER the six starting submits

    if entry == "check_jobs":
        _call(client, _cred(hid, sid), "check_jobs", {"job_ids": jids})
    elif entry == "the sweeper":
        asyncio.run(app._media_sweep())
    else:
        r = client.get(f"/v1/harnesses/{hid}/servers/{ENTRY_ID}/sessions/{sid}/jobs",
                       headers=HEADERS)
        assert r.status_code == 200, r.text

    assert submits, f"[{entry}] no job was advanced at all — this test proves nothing"
    assert len(submits) <= app._MEDIA_MAX_SUBMITS, (
        f"[{entry}] ONE PASS MADE {len(submits)} OUTBOUND SUBMITS against a ceiling of "
        f"{app._MEDIA_MAX_SUBMITS}: {submits}")


def test_v42b_moving_the_ceiling_moves_the_count_on_the_poll_walk_too(client, kit, hostile,
                                                                     monkeypatch):
    """THE TEST THAT WOULD HAVE CAUGHT IT. A number that is real answers when you turn it.

    With `_MEDIA_MAX_SUBMITS` set to 1, one check_jobs over six failing jobs made six submits and
    zero refusals — identical to the count at four. That is what a decorative ceiling looks like
    from outside, and it is measurable without knowing a thing about which branch does the work.
    """
    monkeypatch.setattr(app, "_MEDIA_MAX_SUBMITS", 1)
    hid = _launch(client, kit)
    sid = _session(hid)
    jids = _running_video_jobs(client, hid, sid, 6)
    hostile.poll_answer = httpx.Response(200, json={"code": "success", "data": {
        "status": "FAILURE", "message": "the render failed upstream"}})
    for jid in jids:
        _due(jid)
    submits = _count_submits(hostile)
    _call(client, _cred(hid, sid), "check_jobs", {"job_ids": jids})
    assert len(submits) <= 1, (
        f"the ceiling was moved to 1 and the pass still made {len(submits)} submits: {submits} — "
        f"whatever bounds this path, it is not the number that claims to")


@pytest.mark.parametrize("tool,args,what", [
    ("generate_video", {"prompt": "a cat", "seconds": "six"}, "a number written as a word"),
    ("generate_video", {"prompt": "a cat", "seconds": {"n": 6}}, "an object where a number goes"),
    ("generate_video", {"prompt": "a cat", "seconds": 6, "aspect": "square"}, "a value not in the"
                                                                             " enum"),
    ("generate_image", {"prompt": ["a", "cat"]}, "a list where the string goes"),
    ("arrange", {"columns": "four"}, "a count written as a word"),
    ("check_jobs", {"job_ids": 5}, "a bare number where the list of ids goes"),
    ("check_jobs", {"job_id": "mjob_1"}, "the singular of the argument's name"),
    ("place", {"items": "mjob_1"}, "a string where the array goes"),
    ("set_timeline", {"shots": [{"element_id": "e1", "in_s": "start"}]}, "a word inside an item"),
])
def test_v43_an_argument_the_schema_refuses_is_a_tool_result_and_never_an_http_error(
        client500, client, kit, hostile, tool, args, what):
    """A MODEL WROTE "six" WHERE THE SCHEMA SAYS {"type": "number"}. That is a Tuesday, not an
    attack, and it was an HTTP 500.

    Nothing validates arguments against the declared schema before `_media_tool_call` runs, and
    the tool bodies coerce by hand: `float(args.get("seconds") or 0)` raises ValueError on "six"
    and TypeError on {"n": 6}; `for j in (args.get("job_ids") or [])` raises TypeError on a bare
    number. None of those are in the MediaError tree and none are HTTPException, so they went past
    both handlers at the route and left the agent with a status code it cannot read — the same
    promise this catalog is built around, broken one level away from where round 5 fixed it.

    No money is at stake on any of these. What is at stake is that the agent gets a sentence and
    can correct itself, instead of a 500 it will read as "the tool is broken" and route around.
    """
    hid = _launch(client, kit)
    sid = _session(hid)
    r = client500.post("/v1/mcp/media",
                       json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                             "params": {"name": tool, "arguments": args}},
                       headers={"authorization": f"Bearer {_cred(hid, sid)}"})
    assert r.status_code == 200, (
        f"{tool} with {what} answered HTTP {r.status_code} instead of a tool result: "
        f"{r.text[:400]}")
    res = r.json()["result"]
    assert res.get("isError") is True, (
        f"{tool} with {what} was accepted rather than refused: {res}")


@pytest.mark.parametrize("where,mod,name,exc,tool", [
    ("build_submit", "media_plane", "build_submit", KeyError("shape"), "generate_image"),
    ("_media_providers", "app", "_media_providers", RuntimeError("blip"), "generate_image"),
    ("_media_job_save", "app", "_media_job_save", RuntimeError("blip"), "generate_image"),
    ("_media_job_land", "app", "_media_job_land", ValueError("not a frame"), "generate_image"),
    ("_media_store", "app", "_media_store", OSError("no space left"), "generate_image"),
    ("_media_scene_read", "app", "_media_scene_read", RuntimeError("blip"), "describe_canvas"),
    ("_media_scene_write", "app", "_media_scene_write", RuntimeError("blip"), "arrange"),
])
def test_v44_a_failure_nobody_wrote_an_except_for_is_a_tool_result_and_never_an_http_error(
        client500, client, kit, hostile, monkeypatch, where, mod, name, exc, tool):
    """THE STRUCTURAL HALF OF THE SAME PROMISE. "Every failure is a tool result and never an HTTP
    error" is enforced by an EXCEPTION-TYPE LIST — `except MediaError`, `except HTTPException` —
    so it holds for the failures somebody thought of and for no others.

    Round 5 made this structural INSIDE `_media_call`, which is why a renamed provider field is a
    sentence now. Everywhere else it is still a list: `build_submit` sits outside that try (the
    claim is the line after it), and the store, the scene and the file writer are not in it at
    all. Each row here raises a type no handler names, from a real place, on the ordinary path.

    This test names no branch on purpose. It asserts what the promise says: whatever fails, the
    agent gets a sentence.
    """
    hid = _launch(client, kit)
    sid = _session(hid)
    target = app if mod == "app" else media_plane

    def boom(*_a, **_kw):
        raise exc

    monkeypatch.setattr(target, name, boom)
    args = {"prompt": "a cat"} if tool == "generate_image" else {}
    r = client500.post("/v1/mcp/media",
                       json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                             "params": {"name": tool, "arguments": args}},
                       headers={"authorization": f"Bearer {_cred(hid, sid)}"})
    assert r.status_code == 200, (
        f"{where} raising {type(exc).__name__} answered HTTP {r.status_code}, not a tool result: "
        f"{r.text[:400]}")
    res = r.json()["result"]
    assert res.get("isError") is True, f"{where} raising {type(exc).__name__} read as success: {res}"
    assert _text(res).strip(), f"{where} raising {type(exc).__name__} produced an empty sentence"


def test_v42c_a_ceiling_that_refuses_an_advance_does_not_let_a_later_pass_buy_it_twice(
        client, kit, hostile):
    """THE MONEY RULE, ACROSS THE PASSES THE CEILING NOW SPLITS THE WORK INTO.

    The count is per request, so a pass that hits four refuses the rest — and the obvious way to
    soften that is to leave the refused jobs running so the next pass picks them up. Done without
    care that is a re-buy: `_media_job_billable_failure` has already banked the render and stood
    the model down by the time the submit is refused, so a second visit banks it again and the
    session's spend climbs for renders nobody bought.

    So this asserts what the finding this all came from was careful to say: the burst is gone and
    the TOTAL is not larger. Six failing jobs, swept to quiescence — every job terminal, every one
    of them with at most `_MEDIA_MAX_ADVANCES` advances on it, and no more outbound submits in
    total than one advance each.
    """
    hid = _launch(client, kit)
    sid = _session(hid)
    jids = _running_video_jobs(client, hid, sid, 6)
    hostile.poll_answer = httpx.Response(200, json={"code": "success", "data": {
        "status": "FAILURE", "message": "the render failed upstream"}})
    submits = _count_submits(hostile)
    for _ in range(6):
        for jid in jids:
            job = asyncio.run(app._media_job_get(jid))
            if job["status"] == "running":
                _due(jid)
        asyncio.run(app._media_sweep())

    jobs = [asyncio.run(app._media_job_get(j)) for j in jids]
    assert not [j for j in jobs if j["status"] == "running"], (
        f"six sweeps left {len([j for j in jobs if j['status'] == 'running'])} jobs running — the "
        f"ceiling stranded them instead of refusing them, and they will be re-read for ever")
    over = [(j["id"], j.get("advances")) for j in jobs
            if int(j.get("advances") or 0) > app._MEDIA_MAX_ADVANCES]
    assert not over, f"jobs advanced past the money rule once the passes were split: {over}"
    assert len(submits) <= len(jids) * app._MEDIA_MAX_ADVANCES, (
        f"{len(submits)} submits across six passes for {len(jids)} jobs allowed "
        f"{app._MEDIA_MAX_ADVANCES} advance each: {submits} — the per-request count has become a "
        f"per-pass allowance, which is the same money spent again")
