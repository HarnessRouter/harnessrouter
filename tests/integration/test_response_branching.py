"""Actual gateway → HTTP runner → subprocess → Git checkpoint → branch restore.

Only provider configuration and the paid Claude executable are synthetic. Gateway execution,
response storage, HTTP relays, runner lifecycle and Git restore are the production implementations.
No native-Claude or live-provider conformance claim is made.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import tempfile
import urllib.request
import uuid

import httpx
import pytest

_DATA = tempfile.mkdtemp(prefix="hr-branch-integration-")
os.environ.update({"HR_BACKING": "local", "HR_DATA_DIR": _DATA,
                   "HARNESS_WORKSPACE": str(Path(_DATA) / "workspaces"),
                   "HR_SECRET_KEY": "synthetic-test-passphrase", "HARNESS_INTERNAL_KEY": "synthetic-internal-key",
                   "HR_POOL_AUTH": "none", "HR_IDENTITY_MODE": "off", "HR_SANDBOX_TRUST": "owner",
                   "HARNESS_PUBLIC_BASE_URL": "https://gateway.example"})
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "gateway"))
import app as gw


class RunnerHTTP:
    """No connection pool survives a pytest event loop. Bytes here are tiny fixture files."""
    def build_request(self, method, url, **kwargs):
        return httpx.Request(method, url, **kwargs)

    async def send(self, request, **kwargs):
        async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
            return await client.send(request)

    async def request(self, method, url, **kwargs):
        async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
            return await client.request(method, url, **kwargs)

    async def get(self, url, **kwargs):
        return await self.request("GET", url, **kwargs)

    async def post(self, url, **kwargs):
        return await self.request("POST", url, **kwargs)

    async def put(self, url, **kwargs):
        return await self.request("PUT", url, **kwargs)


@pytest.fixture
def runner_url(tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    work = tmp_path / "workspaces"
    work.mkdir()
    spool = tmp_path / "spool"
    spool.mkdir()
    environment = {"PATH": os.environ["PATH"], "HOME": str(tmp_path),
                   "HARNESS_WORKSPACE": str(work), "HR_WS_MARKER_DIR": str(tmp_path / "markers"),
                   "PYTHONDONTWRITEBYTECODE": "1", "HARNESS_SPOOL_DIR": str(spool)}
    # SPOOL_DIR is configured directly in the fixture, before any real request.
    log = (tmp_path / "runner.log").open("wb")
    process = subprocess.Popen([sys.executable, str(Path(__file__).parent / "fixtures/branch_runner.py"), str(port)],
                               env=environment, stdout=log, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 15
        while True:
            if process.poll() is not None:
                raise AssertionError((tmp_path / "runner.log").read_text())
            try:
                urllib.request.urlopen(url + "/healthz", timeout=1).close()
                break
            except Exception:
                if time.monotonic() > deadline:
                    raise AssertionError((tmp_path / "runner.log").read_text())
                time.sleep(0.1)
        yield url
    finally:
        print("SYNTHETIC RUNNER LOG:\n" + (tmp_path / "runner.log").read_text())
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        log.close()


def assistant(response):
    text = "".join(part.get("text", "") for item in response["output"]
                   if item.get("type") == "message" for part in item.get("content", [])
                   if part.get("type") == "output_text")
    start = text.find('{"command":')
    assert start >= 0, text
    return json.loads(text[start:])


@pytest.mark.asyncio
async def test_three_real_turns_branch_from_one_and_continue_after_gateway_memory_reset(monkeypatch, runner_url):
    suffix = uuid.uuid4().hex
    org, hid = "org.e2e." + suffix, "chrn_" + suffix

    async def principal(_):
        return {"org": org, "member": "fixture@example.invalid"}

    async def chain(*_, **__):
        return ["fixture"]

    async def connection(*_, **__):
        return {"backend": "claude", "provider": "anthropic", "api_key": "synthetic-not-a-key",
                "model": "claude-sonnet-4-6"}, org

    async def model(name, *_, **__):
        return name or "sonnet-4.6"

    async def none(*_, **__):
        return None

    monkeypatch.setattr(gw, "POOL_ENDPOINT", runner_url)
    monkeypatch.setattr(gw, "RESP_POLL_S", 0.05)
    monkeypatch.setattr(gw, "_principal", principal)
    monkeypatch.setattr(gw, "_resolve_chain", chain)
    conn, _ = await connection()
    assert gw._conn_serves(conn, "sonnet-4.6"), "synthetic configuration must pass the real vendor model filter"
    assert gw._auth_from_conn(conn, "fixture-session") is not None, "synthetic owner-trust auth must be usable"
    monkeypatch.setattr(gw, "_get_connection", connection)
    monkeypatch.setattr(gw, "_resolve_model_policy", model)
    monkeypatch.setattr(gw, "_mapped_integration_conn", none)
    monkeypatch.setattr(gw, "_client", lambda: RunnerHTTP())
    monkeypatch.setattr(gw, "_relay_client", lambda: RunnerHTTP())
    await gw.BACKING.graph.upsert("Harness", hid, {"org": org, "name": hid, "base": "claude-code",
                                                  "custom": "1", "deleted": "0", "workspace": ""})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gw.app), base_url="http://gateway") as client:
        previous = None
        turns = []
        for command in ("one", "two", "three"):
            response = await client.post("/v1/responses", json={"input": "COMMAND:" + command,
                "previous_response_id": previous, "metadata": {"harness_id": hid}})
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["status"] == "completed", json.dumps(body, indent=2)
            turns.append(body)
            previous = body["id"]
        source = turns[0]["metadata"]["session_id"]
        before = (await client.get(f"/v1/sessions/{source}/turns")).json()
        response = await client.post("/v1/responses", json={"input": "COMMAND:branch", "branch": True,
            "previous_response_id": turns[0]["id"], "metadata": {"harness_id": hid}})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "completed", json.dumps(body, indent=2)
        target = body["metadata"]["session_id"]
        assert target != source, "branch must create a new session"
        assert body["metadata"]["branched_from"] == turns[0]["id"]
        observed = assistant(body)
        assert observed["before"] == "one"
        assert not observed["future"] and not observed["secret"]
        assert "COMMAND:one" in observed["prompt"] and "COMMAND:two" not in observed["prompt"]
        assert "COMMAND:three" not in observed["prompt"]
        assert (await client.get(f"/v1/sessions/{source}/turns")).json() == before
        assert (await client.get(f"/v1/sessions/{source}/files/user.txt")).text == "three"
        # Drop only gateway memory. Durable local backing and target checkpoint must suffice.
        gw._RESP_CACHE.clear()
        gw._session_trace.pop(target, None)
        async with httpx.AsyncClient(base_url=runner_url, trust_env=False) as runner_client:
            removed = await runner_client.delete("/workspace", params={"identifier": target})
            assert removed.status_code == 200 and removed.json()["removed"]
            probe = await runner_client.post("/hydrate", params={"identifier": target,
                "probe": (await gw._vertex_get(target))["ws_sha"]}, content=b"")
            assert probe.status_code == 200 and probe.json()["skipped"] is False
        continued = await client.post("/v1/responses", json={"input": "COMMAND:branch",
            "previous_response_id": body["id"], "metadata": {"harness_id": hid}})
        assert continued.status_code == 200, continued.text
        assert assistant(continued.json())["before"] == "one"
