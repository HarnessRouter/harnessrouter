#!/usr/bin/env python3
"""Interactive client for an xred-bc UHP Harness through HarnessRouter.

The script uses only the Python standard library. It never asks for or stores the
xred runtime key: Gateway owns that key after the UHP connection is configured.

Examples:
  python scripts/xred_interactive.py
  python scripts/xred_interactive.py --base-url http://127.0.0.1:3000/api/harness
  python scripts/xred_interactive.py --harness-id chrn_xred_9222_default-t1 --stream

Environment:
  HARNESSROUTER_API_KEY  Gateway API key created in the Gateway /keys page
  HARNESSROUTER_BASE_URL Defaults to http://127.0.0.1:3000/api/harness
  HARNESS_ID              Optional stable Gateway Harness ID
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterator


DEFAULT_BASE_URL = "http://127.0.0.1:3000/api/harness"


class ApiError(RuntimeError):
    def __init__(self, status: int, payload: Any):
        self.status = status
        self.payload = payload
        message = payload.get("error", {}).get("message") if isinstance(payload, dict) else None
        super().__init__(f"HTTP {status}: {message or payload}")


@dataclass(frozen=True)
class Harness:
    id: str
    name: str
    base: str = ""
    url: str = ""
    status: str = ""

    @classmethod
    def from_json(cls, row: dict[str, Any]) -> "Harness":
        return cls(
            id=str(row.get("id") or ""),
            name=str(row.get("name") or row.get("id") or ""),
            base=str(row.get("base") or ""),
            url=str(row.get("url") or row.get("metadata", {}).get("url") or ""),
            status=str(row.get("status") or row.get("state") or ""),
        )


class GatewayClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 300.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                **({"Content-Type": "application/json"} if data is not None else {}),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            raw = error.read()
            try:
                payload = json.loads(raw.decode("utf-8", "replace"))
            except json.JSONDecodeError:
                payload = raw.decode("utf-8", "replace")
            raise ApiError(error.code, payload) from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"无法连接 Gateway {self.base_url}: {error.reason}") from error
        return json.loads(raw.decode("utf-8")) if raw else {}

    def harnesses(self) -> list[Harness]:
        payload = self._request("GET", "/v1/harnesses")
        return [Harness.from_json(row) for row in payload.get("harnesses", []) if isinstance(row, dict)]

    def create_response(self, prompt: str, harness_id: str, *, stream: bool, background: bool,
                        previous_response_id: str | None) -> dict[str, Any]:
        metadata = {"harness_id": harness_id} if harness_id else {}
        body: dict[str, Any] = {"input": prompt, "metadata": metadata}
        if stream:
            body["stream"] = True
        if background:
            body["background"] = True
        if previous_response_id:
            body["previous_response_id"] = previous_response_id
        return self._request("POST", "/v1/responses", body)

    def stream_response(self, prompt: str, harness_id: str, *, background: bool,
                        previous_response_id: str | None) -> Iterator[dict[str, Any]]:
        metadata = {"harness_id": harness_id} if harness_id else {}
        body: dict[str, Any] = {"input": prompt, "stream": True, "metadata": metadata}
        if background:
            body["background"] = True
        if previous_response_id:
            body["previous_response_id"] = previous_response_id
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + "/v1/responses", data=data, method="POST",
            headers={"Authorization": f"Bearer {self.api_key}", "Accept": "text/event-stream",
                     "Content-Type": "application/json"},
        )
        try:
            response = urllib.request.urlopen(request, timeout=self.timeout)
        except urllib.error.HTTPError as error:
            raw = error.read()
            try:
                payload = json.loads(raw.decode("utf-8", "replace"))
            except json.JSONDecodeError:
                payload = raw.decode("utf-8", "replace")
            raise ApiError(error.code, payload) from error
        try:
            for raw_line in response:
                line = raw_line.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                value = line[5:].strip()
                if value == "[DONE]":
                    return
                try:
                    event = json.loads(value)
                except json.JSONDecodeError:
                    print(f"[无法解析 SSE] {value}", file=sys.stderr)
                    continue
                if isinstance(event, dict):
                    yield event
        finally:
            response.close()

    def get_response(self, response_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/responses/{response_id}")

    def cancel(self, response_id: str) -> dict[str, Any]:
        return self._request("POST", f"/v1/responses/{response_id}/cancel")


def output_text(response: dict[str, Any]) -> str:
    chunks: list[str] = []
    for item in response.get("output", []) or []:
        for content in item.get("content", []) if isinstance(item, dict) else []:
            if isinstance(content, dict) and content.get("type") in ("output_text", "text"):
                chunks.append(str(content.get("text") or ""))
    return "".join(chunks)


def choose_harness(harnesses: list[Harness], requested: str | None) -> str:
    if requested:
        if any(row.id == requested for row in harnesses):
            return requested
        raise RuntimeError(f"找不到 Harness: {requested}")
    if not harnesses:
        raise RuntimeError("Gateway 没有发现在线 Harness；请先启动 xred-bc 并在 Gateway 的 UHP 页面保存连接。")
    if len(harnesses) == 1:
        return harnesses[0].id
    print("发现多个 Harness，请选择：")
    for index, row in enumerate(harnesses, 1):
        print(f"  {index}. {row.id} | {row.name} | {row.url or row.base}")
    while True:
        answer = input("Harness 编号（q 退出）> ").strip()
        if answer.lower() == "q":
            raise KeyboardInterrupt
        try:
            row = harnesses[int(answer) - 1]
        except (ValueError, IndexError):
            print("请输入列表中的编号。")
            continue
        return row.id


def print_event(event: dict[str, Any]) -> str | None:
    response = event.get("response") if isinstance(event.get("response"), dict) else {}
    status = response.get("status") or event.get("type") or "event"
    text = output_text(response)
    if text:
        print(text, end="", flush=True)
    elif status not in ("response.in_progress", "in_progress"):
        print(f"\n[{status}]", flush=True)
    return str(response.get("id")) if response.get("id") else None


def interactive(client: GatewayClient, harness_id: str, stream: bool, background: bool) -> None:
    previous: str | None = None
    print("已连接。命令：/harness 切换 Harness，/list 列表，/get 查询，/cancel 取消，/new 开新会话，/quit 退出。")
    while True:
        try:
            line = input("\nxred> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        if line in ("/quit", "/exit", ":q"):
            return
        try:
            if line == "/new":
                previous = None
                print("已开始新会话。")
                continue
            if line == "/list":
                for row in client.harnesses():
                    print(f"{row.id} | {row.name} | {row.url or row.base}")
                continue
            if line.startswith("/harness"):
                requested = line.partition(" ")[2].strip()
                harness_id = choose_harness(client.harnesses(), requested or None)
                print(f"当前 Harness：{harness_id}")
                continue
            if line.startswith("/get "):
                print(json.dumps(client.get_response(line[5:].strip()), ensure_ascii=False, indent=2))
                continue
            if line.startswith("/cancel "):
                print(json.dumps(client.cancel(line[8:].strip()), ensure_ascii=False, indent=2))
                continue
            if line == "/stream":
                stream = not stream
                print(f"流式输出：{'开' if stream else '关'}")
                continue
            if stream:
                response_id = None
                print("assistant> ", end="", flush=True)
                for event in client.stream_response(line, harness_id, background=background,
                                                    previous_response_id=previous):
                    response_id = print_event(event) or response_id
                print()
                if response_id:
                    previous = response_id
            else:
                response = client.create_response(line, harness_id, stream=False, background=background,
                                                  previous_response_id=previous)
                previous = str(response.get("id") or previous or "") or None
                print(output_text(response) or json.dumps(response, ensure_ascii=False, indent=2))
                print(f"[response_id={previous} status={response.get('status', 'unknown')}]")
        except ApiError as error:
            print(f"请求失败：{error}", file=sys.stderr)
        except RuntimeError as error:
            print(f"错误：{error}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="通过 HarnessRouter 交互调用 xred-bc UHP Harness")
    parser.add_argument("--base-url", default=os.environ.get("HARNESSROUTER_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--api-key", default=os.environ.get("HARNESSROUTER_API_KEY"), help="Gateway API key；也可用 HARNESSROUTER_API_KEY")
    parser.add_argument("--harness-id", default=os.environ.get("HARNESS_ID"))
    parser.add_argument("--stream", action="store_true", help="默认使用 SSE 流式输出")
    parser.add_argument("--background", action="store_true", help="后台受理任务")
    args = parser.parse_args()
    if not args.api_key:
        parser.error("请设置 HARNESSROUTER_API_KEY，或使用 --api-key")
    client = GatewayClient(args.base_url, args.api_key)
    try:
        harness_id = choose_harness(client.harnesses(), args.harness_id)
        print(f"Gateway: {client.base_url}\nHarness: {harness_id}")
        interactive(client, harness_id, args.stream, args.background)
    except KeyboardInterrupt:
        print()
    except (ApiError, RuntimeError) as error:
        print(f"启动失败：{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
