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
    # Sent on every request, before the per-call headers. For targets that need something a
    # stock UHP client never sends, such as a bring-your-own-key host that wants the caller's
    # model key in a header of its own: the suite measures the protocol, the header pays for it.
    headers: dict = field(default_factory=dict)

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
        h.update({k.lower(): v for k, v in self.headers.items()})
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
        h.update({k.lower(): v for k, v in self.headers.items()})
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
                    buf = _drain_sse(buf + chunk, events, t0)
                    if time.time() - t0 > max_seconds:
                        break
                else:
                    _drain_sse(buf, events, t0, final=True)
        except urllib.error.HTTPError as e:
            self.stream_status = e.code
            self.stream_headers = {k.lower(): v for k, v in (e.headers or {}).items()}
            self.stream_error = e.read().decode("utf-8", "replace")[:500]
        except Exception as e:  # noqa: BLE001
            self.stream_status = 0
            self.stream_headers = {}
            self.stream_error = str(e)[:500]
        return events


def _drain_sse(buf: bytes, events: list[dict], t0: float, *, final: bool = False) -> bytes:
    """Append every complete Server-Sent Event in `buf` to `events`; return the unparsed rest.

    Lines may end in CRLF, LF or CR (WHATWG HTML, "Parsing an event stream"); sse-starlette, for
    one, frames with CRLF by default. A trailing CR is held back unless `final`, since it may be
    the first half of a CRLF split across reads. An event's data is its `data:` lines joined by LF.
    """
    held = b""
    if buf.endswith(b"\r") and not final:
        buf, held = buf[:-1], b"\r"
    buf = buf.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    while b"\n\n" in buf:
        raw, _, buf = buf.partition(b"\n\n")
        data = [ln[5:].removeprefix(b" ") for ln in raw.split(b"\n") if ln.startswith(b"data:")]
        if not data:
            continue
        try:
            ev = json.loads(b"\n".join(data).decode("utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if isinstance(ev, dict):
            ev["__t"] = time.time() - t0     # arrival time, for progressiveness
            events.append(ev)
    return buf + held
