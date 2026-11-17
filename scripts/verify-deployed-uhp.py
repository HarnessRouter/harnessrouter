"""HTTP-level UHP verification for the local self-hosted Gateway.

The script starts a deterministic mock Runtime in this process, drives the deployed Gateway
through its native HTTP port, and removes the temporary connection in a finally block. It is
intended to run inside the Gateway container so the mock address is private without involving a
host service or any provider credential.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import httpx


MOCK_PORT = 18421
MOCK_KEY = "mock-runtime-secret"
MOCK_HARNESS = "browser/page-1"
GATEWAY = "http://127.0.0.1:8080"
RUNTIME_STATE = {"mode": "healthy", "task_posts": 0}


def _load_internal_key() -> str:
    value = os.environ.get("HARNESS_INTERNAL_KEY", "")
    if value:
        return value
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    try:
        with open(env_path, encoding="utf-8") as handle:
            for raw in handle:
                line = raw.strip()
                if line.startswith("HARNESS_INTERNAL_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    raise RuntimeError("HARNESS_INTERNAL_KEY is required; set it or provide a project .env file")


def response_payload(response_id: str, text: str, status: str = "completed") -> dict:
    return {
        "id": response_id,
        "status": status,
        "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
    }


class MockRuntime(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def authorized(self) -> bool:
        return self.headers.get("authorization") == f"Bearer {MOCK_KEY}"

    def send_json(self, code: int, value: dict | bytes, content_type: str = "application/json") -> None:
        raw = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlparse(self.path).path
        if path == "/v1/uhp":
            if RUNTIME_STATE["mode"] == "offline":
                self.send_json(503, {"error": "temporarily_unavailable"})
                return
            if RUNTIME_STATE["mode"] == "invalid":
                self.send_json(200, b"not-json")
                return
            self.send_json(200, {"version": "mock-1", "capabilities": {"streaming": True, "cancellation": True}})
            return
        if not self.authorized() or RUNTIME_STATE["mode"] == "unauthorized":
            self.send_json(401, {"error": "unauthorized"})
            return
        if path == "/v1/harnesses":
            self.send_json(200, {"data": [] if RUNTIME_STATE["mode"] == "missing" else
                                 [{"id": MOCK_HARNESS, "name": "Mock Browser"}]})
        elif path.startswith("/v1/responses/"):
            remote_id = path.rsplit("/", 1)[-1]
            self.send_json(200, response_payload(remote_id, "mock status"))
        else:
            self.send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if not self.authorized():
            self.send_json(401, {"error": "unauthorized"})
            return
        path = urlparse(self.path).path
        length = int(self.headers.get("content-length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw)
        except Exception:
            body = {}
        if path.endswith("/cancel") and path.startswith("/v1/responses/"):
            self.send_json(200, {"id": path.split("/")[-2], "status": "cancelled"})
            return
        if path == "/v1/responses":
            RUNTIME_STATE["task_posts"] += 1
            remote_id = "remote-" + uuid.uuid4().hex[:10]
            text = "mock output: " + str(body.get("input") or "")[:120]
            if body.get("stream"):
                events = [
                    {"type": "response.created", "response": {"id": remote_id, "status": "in_progress"}},
                    {"type": "response.completed", "response": response_payload(remote_id, text)},
                ]
                stream = b"".join(b"data: " + json.dumps(event, ensure_ascii=False).encode() + b"\n\n" for event in events)
                self.send_json(200, stream, "text/event-stream")
            else:
                self.send_json(200, response_payload(remote_id, text))
            return
        self.send_json(404, {"error": "not_found"})

    def log_message(self, *_args: object) -> None:
        return


async def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", MOCK_PORT), MockRuntime)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    internal = _load_internal_key()
    org = "verify-uhp-http"
    headers = {
        "x-harness-internal": internal,
        "x-harness-org": org,
        "x-harness-member": "verification@example.invalid",
        "x-harness-workspace": "",
    }
    connection_name = "verify-http-" + uuid.uuid4().hex[:8]
    base_url = f"http://127.0.0.1:{MOCK_PORT}"
    saved_ok = False
    async with httpx.AsyncClient(base_url=GATEWAY, timeout=20.0) as client:
        try:
            saved = await client.put(
                f"/v1/admin/uhp-connections/{connection_name}",
                headers=headers,
                json={"name": connection_name, "base_url": base_url, "api_key": MOCK_KEY},
            )
            assert saved.status_code == 200, saved.text
            saved_ok = True
            connection = saved.json()["connection"]
            assert connection["config"]["api_key"] == "__secret__"
            assert connection["health"]["status"] == "healthy"
            assert connection["health"]["fresh_until"] - connection["health"]["last_checked_at"] == 90
            harness_id = connection["harnesses"][0]["id"]
            detail = await client.get(f"/v1/harnesses/{harness_id}", headers=headers)
            assert detail.status_code == 200, detail.text
            assert detail.json()["available"] is True
            assert detail.json()["health"]["status"] == "healthy"

            harnesses = await client.get("/v1/harnesses", headers=headers)
            assert harnesses.status_code == 200, harnesses.text
            assert any(row["id"] == harness_id for row in harnesses.json()["harnesses"])

            created = await client.post(
                "/v1/responses",
                headers=headers,
                json={"input": "ordinary HTTP response", "metadata": {"harness_id": harness_id}},
            )
            assert created.status_code == 200, created.text
            local_id = created.json()["id"]
            assert local_id.startswith("resp_uhp_")

            fetched = await client.get(f"/v1/responses/{local_id}", headers=headers)
            assert fetched.status_code == 200, fetched.text
            assert fetched.json()["id"] == local_id

            cancelled = await client.post(f"/v1/responses/{local_id}/cancel", headers=headers)
            assert cancelled.status_code == 200, cancelled.text
            assert cancelled.json()["id"] == local_id
            continued = await client.post(
                "/v1/responses",
                headers=headers,
                json={"input": "continuation", "previous_response_id": local_id},
            )
            assert continued.status_code == 200, continued.text
            assert continued.json()["id"].startswith("resp_uhp_")

            stream_ids: list[str] = []
            async with client.stream(
                "POST",
                "/v1/responses",
                headers=headers,
                json={"input": "streamed", "stream": True, "metadata": {"harness_id": harness_id}},
            ) as stream:
                assert stream.status_code == 200
                async for line in stream.aiter_lines():
                    if line.startswith("data:"):
                        event = json.loads(line[5:].strip())
                        response = event.get("response") or {}
                        if response.get("id"):
                            stream_ids.append(response["id"])
            assert stream_ids and all(item.startswith("resp_uhp_") for item in stream_ids)

            snapshot = {
                "template_id": "verify-http",
                "template_version": 1,
                "title": "UHP HTTP workflow",
                "nodes": [{"id": "external", "name": "外部 Runtime", "agent_id": harness_id, "deps": [], "retry_limit": 0}],
            }
            task = await client.post(
                "/v1/workflow-tasks",
                headers=headers,
                json={"title": "UHP HTTP workflow", "input": "workflow external call", "snapshot": snapshot},
            )
            assert task.status_code == 200, task.text
            task_id = task.json()["id"]
            started = await client.post(f"/v1/workflow-tasks/{task_id}/run", headers=headers)
            assert started.status_code == 202, started.text
            for _ in range(40):
                current = await client.get(f"/v1/workflow-tasks/{task_id}", headers=headers)
                assert current.status_code == 200, current.text
                value = current.json()
                if value["status"] in ("completed", "failed"):
                    break
                await asyncio.sleep(0.25)
            assert value["status"] == "completed", value
            node = value["snapshot"]["nodes"][0]
            assert node["status"] == "done" and node["response_id"].startswith("resp_uhp_")
            assert "mock output" in node["output"]
            for mode, expected in (("offline", "unreachable"), ("unauthorized", "unauthorized"),
                                   ("invalid", "invalid"), ("missing", "harness_missing")):
                RUNTIME_STATE["mode"] = mode
                checked = await client.post(f"/v1/admin/uhp-connections/{connection_name}/check", headers=headers)
                assert checked.status_code == 200, checked.text
                observed = checked.json()["connection"]
                assert observed["health"]["status"] == expected, observed
                assert observed["harnesses"][0]["id"] == harness_id
                assert MOCK_KEY not in checked.text
                detail = await client.get(f"/v1/harnesses/{harness_id}", headers=headers)
                assert detail.status_code == 200, detail.text
                assert detail.json()["available"] is False
                assert detail.json()["health"]["status"] == expected
                assert MOCK_KEY not in detail.text
                before = RUNTIME_STATE["task_posts"]
                blocked = await client.post("/v1/responses", headers=headers,
                    json={"input": "must not dispatch", "metadata": {"harness_id": harness_id}})
                assert blocked.status_code == 503 and expected in blocked.text, blocked.text
                assert RUNTIME_STATE["task_posts"] == before
                assert MOCK_KEY not in blocked.text
                RUNTIME_STATE["mode"] = "healthy"
                recovered = await client.post("/v1/responses", headers=headers,
                    json={"input": "recovered", "metadata": {"harness_id": harness_id}})
                assert recovered.status_code == 200, recovered.text
                assert RUNTIME_STATE["task_posts"] == before + 1

            RUNTIME_STATE["mode"] = "offline"
            snapshot["nodes"][0]["retry_limit"] = 2
            failed_task = await client.post("/v1/workflow-tasks", headers=headers,
                json={"title": "UHP unhealthy retry", "input": "must not dispatch", "snapshot": snapshot})
            assert failed_task.status_code == 200, failed_task.text
            failed_id = failed_task.json()["id"]
            before = RUNTIME_STATE["task_posts"]
            assert (await client.post(f"/v1/workflow-tasks/{failed_id}/run", headers=headers)).status_code == 202
            for _ in range(80):
                current = await client.get(f"/v1/workflow-tasks/{failed_id}", headers=headers)
                assert current.status_code == 200, current.text
                failed_value = current.json()
                if failed_value["status"] in ("completed", "failed"):
                    break
                await asyncio.sleep(0.25)
            failed_node = failed_value["snapshot"]["nodes"][0]
            assert failed_value["status"] == "failed", failed_value
            assert failed_node["attempts"] == 3 and "unreachable" in failed_node["output"], failed_node
            assert failed_node["agent_id"] == harness_id
            assert RUNTIME_STATE["task_posts"] == before
            RUNTIME_STATE["mode"] = "healthy"
            listing = await client.get("/v1/admin/uhp-connections", headers=headers)
            assert listing.status_code == 200 and MOCK_KEY not in listing.text
            listed = next(row for row in listing.json()["connections"] if row["id"] == connection["id"])
            assert listed["health"]["status"] == "healthy", listed
            print(json.dumps({"connection": "saved+redacted", "harness": "discovered",
                "responses": "json+sse+continuation+cancel", "workflow": "completed",
                "health": "manual+offline+unauthorized+invalid+missing+recovery",
                "dispatch": "blocked without upstream task POST", "workflow_retry": "3 attempts; no agent switch"}))
        finally:
            if saved_ok:
                deleted = await client.delete(f"/v1/admin/uhp-connections/{connection_name}", headers=headers)
                assert deleted.status_code == 200, deleted.text
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    asyncio.run(main())
