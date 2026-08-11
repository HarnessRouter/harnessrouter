"""A deliberately thin HTTP client.

The suite tests a server, so it must not paper over anything a server does. This client therefore
does no retrying, no redirect chasing, and no error raising — every check sees the exact status,
headers and body the server sent, including the malformed ones.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field


@dataclass
class Result:
    status: int
    headers: dict
    body: bytes
    elapsed_s: float
    url: str
    method: str

    @property
    def json(self):
        """Parsed body, or None when it is not JSON. Never raises: a server returning HTML where
        JSON was promised is a finding to report, not an exception to crash the run."""
        try:
            return json.loads(self.body.decode("utf-8"))
        except Exception:  # noqa: BLE001
            return None

    def header(self, name: str) -> str:
        return self.headers.get(name.lower(), "")


@dataclass
class Client:
    base_url: str
    api_key: str = ""
    timeout: float = 300.0
    calls: list = field(default_factory=list)

    def _url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}{path}"

    def request(self, method: str, path: str, *, body=None, headers=None,
                auth: bool = True, raw: bytes | None = None, content_type: str | None = None) -> Result:
        url = self._url(path)
        h = {"accept": "application/json"}
        if auth and self.api_key:
            h["authorization"] = f"Bearer {self.api_key}"
        if body is not None:
            raw = json.dumps(body).encode()
            h["content-type"] = "application/json"
        if content_type:
            h["content-type"] = content_type
        h.update({k.lower(): v for k, v in (headers or {}).items()})

        req = urllib.request.Request(url, data=raw, method=method, headers=h)
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                res = Result(r.status, {k.lower(): v for k, v in r.headers.items()},
                             r.read(), time.time() - t0, url, method)
        except urllib.error.HTTPError as e:
            res = Result(e.code, {k.lower(): v for k, v in (e.headers or {}).items()},
                         e.read(), time.time() - t0, url, method)
        except Exception as e:  # noqa: BLE001 — a transport failure is a result, not a crash
            res = Result(0, {}, str(e).encode(), time.time() - t0, url, method)
        self.calls.append(res)
        return res

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, **kw):
        return self.request("POST", path, **kw)

    def put(self, path, **kw):
        return self.request("PUT", path, **kw)

    def delete(self, path, **kw):
        return self.request("DELETE", path, **kw)

    def stream(self, path: str, body: dict, *, headers=None, max_seconds: float = 300.0) -> list[dict]:
        """POST and read Server-Sent Events, returning the parsed `data:` objects in arrival order.

        Reads incrementally rather than buffering the whole body, so a server that only flushes at
        the end is measurable (see the streaming-progressiveness check) instead of indistinguishable
        from a fast one.
        """
        url = self._url(path)
        h = {"accept": "text/event-stream", "content-type": "application/json"}
        if self.api_key:
            h["authorization"] = f"Bearer {self.api_key}"
        h.update({k.lower(): v for k, v in (headers or {}).items()})
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers=h)

        events: list[dict] = []
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=max_seconds) as r:
                self.stream_headers = {k.lower(): v for k, v in r.headers.items()}
                self.stream_status = r.status
                buf = b""
                for chunk in r:
                    buf += chunk
                    while b"\n\n" in buf:
                        raw, _, buf = buf.partition(b"\n\n")
                        for line in raw.split(b"\n"):
                            if line.startswith(b"data:"):
                                try:
                                    ev = json.loads(line[5:].strip().decode("utf-8"))
                                except Exception:  # noqa: BLE001
                                    continue
                                ev["__t"] = time.time() - t0     # arrival time, for progressiveness
                                events.append(ev)
                    if time.time() - t0 > max_seconds:
                        break
        except urllib.error.HTTPError as e:
            self.stream_status = e.code
            self.stream_headers = {k.lower(): v for k, v in (e.headers or {}).items()}
            self.stream_error = e.read().decode("utf-8", "replace")[:500]
        except Exception as e:  # noqa: BLE001
            self.stream_status = 0
            self.stream_headers = {}
            self.stream_error = str(e)[:500]
        return events
