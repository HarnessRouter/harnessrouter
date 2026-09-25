"""The browser plug on the hosted gateway: a workspace connects it once (a Plug record of type
browser, platform auth, its site lists), a harness includes it like any plug, and the agent gets a
cloud browser over CDP as typed tools on the plugs server.

Every request goes through the real app with local backing; the plug registry and the vendor are
httpx MockTransports and the browser is a fake that answers the shapes the tools read and routes
every request through the same gate a real context would. What is asserted is what a caller
receives, what the vendor was sent, what was written down, and what was metered. The vendor key
and the CDP address are sentinels: the last test asserts they appear in no response the agent
could read.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import time
import urllib.parse
import zlib
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402
import browser_plane  # noqa: E402
import plugs_plane  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ORG = "browserorg"
WS = "browserorg__hrws1"
HEADERS = {"x-harness-internal": "test-internal-key", "x-harness-org": ORG,
           "x-harness-member": "m@browser", "x-harness-workspace": WS}
VENDOR_KEY = "bu_SENTINEL_never_returned_5e5e"
CDP = "wss://cdp.example/SENTINEL_never_returned_9d9d"
PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
TENANT = "browserorg-1a2b3c4d"
_seen: list[str] = []


def _png(w: int = 2, h: int = 2) -> bytes:
    """A real PNG, the smallest that verifies: the screenshot the fake page takes."""
    raw = b"".join(b"\x00" + b"\x10\x20\x30" * w for _ in range(h))

    def chunk(t: bytes, d: bytes) -> bytes:
        return len(d).to_bytes(4, "big") + t + d + zlib.crc32(t + d).to_bytes(4, "big")
    ihdr = w.to_bytes(4, "big") + h.to_bytes(4, "big") + b"\x08\x02\x00\x00\x00"
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def _record(status: str = "connected", allow=None, deny=None, version: int = 1) -> dict:
    """The engine's record for a workspace's browser plug: platform auth, nothing in the vault."""
    return {"id": "plug.browser1", "org_id": ORG, "workspace": WS, "type": "browser", "status": status,
            "effective_status": status, "source": "platform", "vault_tenant": TENANT, "key_refs": [],
            "config": {"allow_domains": allow or [], "deny_domains": deny or [], "proxy": False},
            "version": version, "expires_at": ""}


class Registry:
    """The engine's read door: the workspace's browser record, or 404."""

    def __init__(self):
        self.record: dict | None = None
        self.reads = 0
        self.any_workspace = False

    def handle(self, r: httpx.Request) -> httpx.Response:
        assert r.url.path == "/v1/plugs/by" and r.method == "GET", r.url
        assert r.headers.get("X-Internal-Key") == "test-internal-key"
        self.reads += 1
        if self.record and (self.any_workspace or r.url.params.get("workspace") == WS) and r.url.params.get("type") == "browser":
            ws = r.url.params.get("workspace")
            return httpx.Response(200, json={**self.record, "workspace": ws, "org_id": ws.split("__")[0]})
        return httpx.Response(404, json={"detail": "no such plug"})


class Vendor:
    """Browser Use Cloud's v4 browsers API: create, stop, read."""

    def __init__(self):
        self.calls: list[httpx.Request] = []
        self.created: list[dict] = []
        self.stopped: list[str] = []
        self.refuse: int | None = None          # 402 or 429 on the next create
        self.cost = 0.000667                     # what a stopped session reports

    def handle(self, r: httpx.Request) -> httpx.Response:
        self.calls.append(r)
        assert r.headers.get("X-Browser-Use-API-Key") == VENDOR_KEY, "the vendor key, never anything else"
        if r.url.path == "/api/v4/browsers" and r.method == "POST":
            if self.refuse:
                code, self.refuse = self.refuse, None
                return httpx.Response(code, json={"detail": "no"})
            body = json.loads(r.content)
            self.created.append(body)
            bid = f"bu_{len(self.created)}"
            return httpx.Response(201, json={"id": bid, "cdpUrl": CDP, "liveUrl": "https://live.example/x",
                                             "status": "active", "timeoutAt": "2026-09-24T22:00:00Z"})
        if r.url.path.startswith("/api/v4/browsers/") and r.method == "PATCH":
            bid = r.url.path.rsplit("/", 1)[1]
            assert json.loads(r.content) == {"action": "stop"}
            self.stopped.append(bid)
            return httpx.Response(200, json={"id": bid, "status": "stopped", "browserCost": self.cost,
                                             "proxyCost": 0, "proxyUsedMb": 0})
        return httpx.Response(404, json={"detail": f"no mock for {r.method} {r.url.path}"})


class Route:
    def __init__(self):
        self.aborted = None

    async def abort(self, why):
        self.aborted = why

    async def continue_(self):
        self.aborted = None


class Req:
    def __init__(self, url):
        self.url = url


class Locator:
    def __init__(self, page, sel):
        self.page, self.sel, self.first = page, sel, self

    async def click(self, timeout=None):
        if self.sel not in self.page.dom:
            raise RuntimeError(f"Timeout 15000ms exceeded waiting for {self.sel}")
        target = self.page.dom[self.sel].get("href")
        self.page.clicks.append(self.sel)
        if target:
            await self.page.goto(target)

    async def fill(self, text, timeout=None):
        if self.sel not in self.page.dom:
            raise RuntimeError(f"Timeout 15000ms exceeded waiting for {self.sel}")
        self.page.dom[self.sel]["value"] = text

    async def press(self, key):
        self.page.pressed.append(key)

    async def inner_text(self):
        if self.sel == "body":
            return self.page.text
        if self.sel not in self.page.dom:
            raise RuntimeError(f"Timeout 30000ms exceeded waiting for {self.sel}")
        return self.page.dom[self.sel].get("name", "")

    async def wait_for(self, timeout=None):
        if self.sel != "body" and self.sel not in self.page.dom:
            raise RuntimeError("Timeout")


class Keyboard:
    def __init__(self, page):
        self.page = page

    async def press(self, key):
        self.page.pressed.append(key)


class Mouse:
    def __init__(self):
        self.wheels = []

    async def wheel(self, dx, dy):
        self.wheels.append((dx, dy))


class Page:
    """A page whose DOM is a dict of selector -> element; navigation goes through the context's
    route handler exactly as Chromium would put every request through it."""

    def __init__(self, ctx):
        self.ctx, self.url, self.dom, self.text = ctx, "about:blank", {}, ""
        self.clicks, self.pressed, self.history = [], [], []
        self.keyboard, self.mouse = Keyboard(self), Mouse()
        self.slow = 0.0

    def set_default_timeout(self, ms):
        pass

    async def goto(self, url, wait_until=None):
        if self.slow:
            await asyncio.sleep(self.slow)
        u = urllib.parse.urlsplit(url)
        url = urllib.parse.urlunsplit(u._replace(path=u.path or "/"))    # Chromium's own normalisation
        route = Route()
        await self.ctx.handler(route, Req(url))
        if route.aborted:
            raise RuntimeError(f"net::ERR_BLOCKED_BY_CLIENT at {url}")
        self.history.append(self.url)
        self.url = url
        self.dom = dict(SITES.get(url, {}).get("dom", {}))
        self.text = SITES.get(url, {}).get("text", "")

    async def go_back(self, wait_until=None):
        if not self.history:
            raise RuntimeError("no history")
        await self.goto(self.history.pop())

    async def title(self):
        return SITES.get(self.url, {}).get("title", "")

    async def evaluate(self, js, arg=None):
        rows = []
        for n, (sel, el) in enumerate(self.dom.items(), start=1):
            if n > arg:
                rows.append({"truncated": True})
                break
            rows.append({"ref": f"e{n}", "role": el.get("role", "link"), "name": el.get("name", ""),
                         **({"href": el["href"]} if el.get("href") else {}),
                         **({"value": el["value"]} if "value" in el else {})})
            el["ref"] = f"e{n}"
        return rows

    def locator(self, sel):
        ref = sel[len('[data-hr-ref="'):-2] if sel.startswith('[data-hr-ref="') else ""
        if ref:
            sel = next((s for s, el in self.dom.items() if el.get("ref") == ref), sel)
        return Locator(self, sel)

    def get_by_text(self, text):
        return Locator(self, "body" if text in self.text else "__absent__")

    async def wait_for_load_state(self, state):
        pass

    async def screenshot(self, type="png", full_page=False):
        return _png()


class Context:
    def __init__(self, browser, **kw):
        self.browser, self.kw, self.pages, self.handler, self.closed = browser, kw, [], None, False

    async def route(self, pattern, handler):
        self.handler = handler

    async def new_page(self):
        p = Page(self)
        self.pages.append(p)
        return p

    async def close(self):
        self.closed = True


class Browser:
    def __init__(self, cdp):
        self.cdp, self.contexts, self.closed = cdp, [], False

    async def new_context(self, **kw):
        c = Context(self, **kw)
        self.contexts.append(c)
        return c

    async def close(self):
        self.closed = True


SITES = {
    "https://example.com/": {"title": "Example Domain", "text": "Example Domain\nThis domain is for examples.\nMore information...",
                             "dom": {"a.more": {"role": "link", "name": "More information...", "href": "https://www.iana.org/domains/example"},
                                     "input#q": {"role": "textbox", "name": "Search", "value": ""}}},
    "https://www.iana.org/domains/example": {"title": "Example Domains", "text": "Example Domains\nAs described in RFC 2606.",
                                             "dom": {"a.home": {"role": "link", "name": "Home", "href": "https://www.iana.org/"}}},
    "https://public.example/leak": {"title": "Leak", "text": "", "dom": {"img": {"role": "img", "name": "", "href": "http://10.0.0.5/secret.png"}}},
}
browsers: list[Browser] = []


async def _connect(cdp):
    b = Browser(cdp)
    browsers.append(b)
    return b


@pytest.fixture(scope="module")
def client():
    with TestClient(gw.app) as c:
        yield c


@pytest.fixture
def world(monkeypatch):
    reg, ven, posted = Registry(), Vendor(), []
    rc = httpx.AsyncClient(transport=httpx.MockTransport(reg.handle))
    monkeypatch.setattr(gw, "PLUGS_REGISTRY_URL", "https://registry.example")
    monkeypatch.setattr(gw, "_PLUGS_ORGS", {ORG})
    monkeypatch.setattr(gw, "_client", lambda: rc)
    monkeypatch.setattr(browser_plane, "API_KEY", VENDOR_KEY)
    monkeypatch.setattr(browser_plane, "transport", httpx.MockTransport(ven.handle))
    monkeypatch.setattr(browser_plane, "connector", _connect)
    # names resolve without the network: one internal name, the rest public
    monkeypatch.setattr(browser_plane, "resolves_private", _resolves)
    monkeypatch.setattr(gw, "_report_usage", lambda org, metric, amount, **kw: posted.append((org, metric, amount, kw)))
    browsers.clear()
    for s in list(browser_plane.sessions().values()):
        s.closed = True
    browser_plane.sessions().clear()
    yield reg, ven, posted
    asyncio.run(rc.aclose())


async def _resolves(host: str) -> bool:
    return host in ("intranet.example",) or browser_plane._ip_private(host)


def _post(client, path, body=None, headers=None):
    r = client.post(path, json=body, headers={**HEADERS, **(headers or {})})
    _seen.append(r.text)
    return r


def _get(client, path, headers=None):
    r = client.get(path, headers={**HEADERS, **(headers or {})})
    _seen.append(r.text)
    return r


def _harness(client, headers=None, **extra) -> str:
    return _post(client, "/v1/harnesses", {"name": "Browsing", "base": "claude-code", **extra}, headers).json()["id"]


def _key(hid: str) -> str:
    return gw._hosted_secret_key(hid, "mcp.plugs")


def _include(client, hid: str, plugs=("browser",)) -> dict:
    r = _post(client, f"/v1/harnesses/{hid}/servers/plugs", {"plugs": list(plugs)})
    assert r.status_code == 200, r.text
    return r.json()


def _rpc(client, tok: str, method: str, params: dict | None = None, rid=1):
    r = client.post("/v1/mcp/plugs", headers={"authorization": f"Bearer {tok}"},
                    json={"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
    _seen.append(r.text)
    return r.json().get("result") if r.status_code == 200 else r


def _call(client, tok, name, **args):
    return _rpc(client, tok, "tools/call", {"name": f"browser.{name}", "arguments": args})


def _rows(hid: str) -> list[dict]:
    rows = [r for r in asyncio.run(gw.BACKING.graph.find("PlugCall", {"harness": hid})) if r.get("plug") == "browser"]
    # by end time; on a same-millisecond tie the row that STARTED first (the session's) sorts last
    return sorted(rows, key=lambda r: (int(r["finished"]), -int(r["started"])))


def _session_of(hid: str, org: str = ORG) -> str:
    sid = "sess_" + os.urandom(6).hex()
    asyncio.run(gw._vg_upsert("HarnessSession", sid, {"tenant": org, "status": "idle", "turn_status": "idle", "harness_id": hid}))
    return sid


# ── the include and the workspace's record ───────────────────────────────────────────────────
def test_a_harness_includes_the_browser_like_any_plug_and_the_workspace_must_have_connected_it(client, world):
    reg, ven, _ = world
    hid = _harness(client)
    # no include: the plugs server lists nothing of the browser's
    other = _harness(client)
    _include(client, other, ("github",))
    tok_other = gw._mint_hosted_cred(other, "sess0", _key(other))
    assert not [t for t in _rpc(client, tok_other, "tools/list")["tools"] if t["name"].startswith("browser.")]
    # the include, with the workspace not yet connected: attached, status missing, a call refused
    d = _include(client, hid)
    assert d["plugs"] == ["browser"] and d["status"] == {"browser": "missing"}
    assert d["workspace"] == WS and d["id"] == "mcp.plugs"
    assert _get(client, f"/v1/harnesses/{hid}/servers/mcp.plugs").json()["status"] == {"browser": "missing"}
    tok = gw._mint_hosted_cred(hid, _session_of(hid), _key(hid))
    tools = _rpc(client, tok, "tools/list")["tools"]
    assert [t["name"] for t in tools] == ["browser.navigate", "browser.get_url", "browser.snapshot", "browser.extract_text",
                                          "browser.click", "browser.type", "browser.press_key", "browser.scroll", "browser.wait_for",
                                          "browser.screenshot", "browser.back", "browser.list_tabs", "browser.switch_tab"]
    assert next(t for t in tools if t["name"] == "browser.snapshot")["annotations"] == {"readOnlyHint": True, "destructiveHint": False}
    assert next(t for t in tools if t["name"] == "browser.click")["annotations"] == {"readOnlyHint": False, "destructiveHint": False}
    assert next(t for t in tools if t["name"] == "browser.navigate")["description"].startswith("[Browser, write]")
    out = _call(client, tok, "navigate", url="https://example.com/")
    assert out["isError"] and out["content"][0]["text"].startswith("The workspace has no Browser plugin connected")
    assert ven.created == [] and _rows(hid)[-1]["outcome"] == "refused" and _rows(hid)[-1]["error"] == "missing"
    # connected, then turned off by the workspace
    reg.record = _record()
    assert _get(client, f"/v1/harnesses/{hid}/servers/mcp.plugs").json()["status"] == {"browser": "connected"}
    reg.record = _record("disabled")
    out = _call(client, tok, "navigate", url="https://example.com/")
    assert out["isError"] and "turned off" in out["content"][0]["text"] and ven.created == []
    # a narrowed include lists only the named tools
    r = _post(client, f"/v1/harnesses/{hid}/servers/plugs", {"plugs": ["browser"], "tools": {"browser": ["navigate", "extract_text"]}})
    assert r.status_code == 200 and r.json()["tools"] == {"browser": ["navigate", "extract_text"]}
    assert [t["name"] for t in _rpc(client, tok, "tools/list")["tools"]] == ["browser.navigate", "browser.extract_text"]
    r = _post(client, f"/v1/harnesses/{hid}/servers/plugs", {"plugs": ["browser"], "tools": {"browser": ["evaluate"]}})
    assert r.status_code == 400 and "evaluate" in r.text


# ── the agent's session, priced, metered, stopped ────────────────────────────────────────────
def test_a_turn_browses_and_the_session_is_priced_metered_and_stopped(client, world):
    reg, ven, posted = world
    reg.record = _record()
    hid = _harness(client)
    _include(client, hid)
    sid = _session_of(hid)
    tok = gw._mint_hosted_cred(hid, sid, _key(hid))
    assert _rpc(client, tok, "initialize")["serverInfo"]["name"] == "plugs"

    # the first call opens the browser: the vendor is asked for a bare session, the estimate is reserved
    out = _call(client, tok, "navigate", url="example.com")
    assert out["isError"] is False, out
    text = out["content"][0]["text"]
    assert text.startswith("Opened https://example.com/ (Example Domain)") and 'e1 link "More information..." href=https://www.iana.org/domains/example' in text
    assert ven.created == [{"timeout": 20, "proxyCountryCode": None, "solveCaptchas": False, "enableRecording": False,
                            "metadata": {"harness": hid, "session": sid}}]
    assert browsers[-1].cdp == CDP and browsers[-1].contexts[0].kw == {"accept_downloads": False, "viewport": {"width": 1280, "height": 800}}

    assert _call(client, tok, "get_url")["content"][0]["text"] == "https://example.com/ (Example Domain)"
    snap = _call(client, tok, "snapshot")["content"][0]["text"]
    assert 'e2 textbox "Search" value=""' in snap
    out = _call(client, tok, "type", ref="e2", text="hello")
    assert out["content"][0]["text"] == "Typed 5 characters."
    assert 'value="hello"' in _call(client, tok, "snapshot")["content"][0]["text"]
    out = _call(client, tok, "click", ref="e1")
    assert out["content"][0]["text"] == "Clicked. Now at https://www.iana.org/domains/example (Example Domains)"
    assert _call(client, tok, "extract_text")["content"][0]["text"] == "Example Domains\nAs described in RFC 2606."
    assert _call(client, tok, "extract_text", max_chars=200, selector="a.home")["content"][0]["text"] == "Home"
    assert _call(client, tok, "back")["content"][0]["text"] == "Back at https://example.com/ (Example Domain)"
    assert _call(client, tok, "scroll", pixels=300)["content"][0]["text"] == "Scrolled down 300 pixels."
    assert _call(client, tok, "press_key", key="Escape")["content"][0]["text"].startswith("Pressed Escape.")
    assert _call(client, tok, "wait_for", text="examples")["content"][0]["text"] == '"examples" is on the page.'
    assert _call(client, tok, "wait_for", ms=10)["content"][0]["text"] == "Waited 10 ms."
    assert _call(client, tok, "list_tabs")["content"][0]["text"] == "0 * https://example.com/ (Example Domain)"
    out = _call(client, tok, "switch_tab", index=3)
    assert out["isError"] and "no tab 3" in out["content"][0]["text"]
    out = _call(client, tok, "click", selector="button.absent")
    assert out["isError"] and out["content"][0]["text"].startswith("The click did not land")

    # a screenshot: shown to the agent and kept as the session's media, served by the bytes route
    out = _call(client, tok, "screenshot")
    assert out["isError"] is False and out["content"][0]["type"] == "image" and out["content"][0]["mimeType"] == "image/png"
    assert base64.b64decode(out["content"][0]["data"]) == _png()
    note = out["content"][1]["text"]
    assert note.startswith("Screenshot of https://example.com/") and "/servers/mcp.plugs/sessions/" in note
    path = note.split("as ", 1)[1].strip()
    r = client.get(path, headers=HEADERS)
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/png") and r.content == _png()
    # the same bytes are not served through a media entry that is not on this harness
    assert client.get(path.replace("mcp.plugs", "mcp.media"), headers=HEADERS).status_code == 404

    # every call is written down as a plug call; the money has not been metered yet (the session runs)
    rows = _rows(hid)
    assert rows[0]["tool"] == "open" and rows[0]["unit"] == "call" and json.loads(rows[0]["detail"])["estimate_usd"] == 0.006667
    assert [r["tool"] for r in rows[1:6]] == ["navigate", "get_url", "snapshot", "type", "snapshot"]
    assert all(r["session"] == sid and r["org"] == ORG and r["workspace"] == WS and r["plug"] == "browser" for r in rows)
    shot = next(r for r in rows if r["tool"] == "screenshot")
    assert shot["unit"] == "screenshot" and shot["usd"] == "0.0" and shot["outcome"] == "ok"
    bad = next(r for r in rows if r["tool"] == "click" and r["outcome"] == "error")
    assert bad["error"].startswith("The click did not land")
    assert [p[1] for p in posted] == ["plug.call"] * 18 and ven.stopped == []

    # the turn ends: the vendor is told to stop, the session row carries its minutes and the
    # vendor's dollars, and that is what the meter posts
    asyncio.run(gw._browser_close(sid, "turn_end"))
    assert ven.stopped == ["bu_1"] and browsers[-1].closed and browsers[-1].contexts[0].closed
    end = _rows(hid)[-1]
    assert end["tool"] == "session" and end["unit"] == "browser.usd" and end["usd"] == "0.000667" and end["outcome"] == "ok"
    detail = json.loads(end["detail"])
    assert detail["reason"] == "turn_end" and detail["minutes"] == 1 and detail["usd_source"] == "vendor" and detail["calls"] == 17
    assert detail["vendor_session"] == "bu_1"
    # the estimate and what the vendor did not charge are on the row, for the record
    assert detail["reserved_usd"] == 0.006667 and detail["released_usd"] == 0.006
    assert posted[-1] == (ORG, "browser.usd", 0.000667, {"workspace": WS, "task_id": sid, "harness_id": hid, "title": "Browser", "harness_name": "Browser"})
    assert sid not in browser_plane.sessions()
    # closing again is nothing; a later call opens a new browser
    asyncio.run(gw._browser_close(sid, "turn_end"))
    assert len(ven.stopped) == 1
    assert _call(client, tok, "get_url")["isError"] is False and len(ven.created) == 2
    asyncio.run(gw._browser_close(sid, "turn_end"))


def test_the_vendor_figure_missing_bills_the_table(client, world):
    reg, ven, posted = world
    reg.record = _record()
    ven.cost = None
    hid = _harness(client)
    _include(client, hid)
    sid = _session_of(hid)
    tok = gw._mint_hosted_cred(hid, sid, _key(hid))
    assert _call(client, tok, "navigate", url="https://example.com/")["isError"] is False
    asyncio.run(gw._browser_close(sid, "turn_end"))
    end = _rows(hid)[-1]
    assert end["unit"] == "browser.usd" and end["usd"] == "0.000333" and json.loads(end["detail"])["usd_source"] == "table"
    assert posted[-1][1:3] == ("browser.usd", 0.000333)


# ── the guards ───────────────────────────────────────────────────────────────────────────────
def test_private_and_disallowed_addresses_are_refused_for_pages_and_their_requests(client, world):
    reg, ven, _ = world
    reg.record = _record(deny=["iana.org"])
    hid = _harness(client)
    _include(client, hid)
    sid = _session_of(hid)
    tok = gw._mint_hosted_cred(hid, sid, _key(hid))
    for url, why in [("http://127.0.0.1:8080/admin", "private or local"), ("http://169.254.169.254/latest/meta-data", "private or local"),
                     ("http://10.0.0.5/", "private or local"), ("http://localhost/", "private or local"),
                     ("http://vault.internal/", "private or local"), ("http://intranet.example/", "private or local"),
                     ("http://[::1]/", "private or local"), ("ftp://example.com/", "ftp address"),
                     ("https://www.iana.org/", "not allowed to visit")]:
        out = _call(client, tok, "navigate", url=url)
        assert out["isError"] and why in out["content"][0]["text"], (url, out)
    assert len(ven.created) == 1     # one browser opened, then every refusal happened here, before any request
    # a page's own request to a private address is aborted by the context gate
    assert _call(client, tok, "navigate", url="https://public.example/leak")["isError"] is False
    out = _call(client, tok, "click", ref="e1")           # the "image" link into 10.0.0.5
    assert out["isError"] and "ERR_BLOCKED_BY_CLIENT" in out["content"][0]["text"]
    ctx = browsers[-1].contexts[0]
    route = Route()
    asyncio.run(ctx.handler(route, Req("http://10.0.0.5/secret.png")))
    assert route.aborted == "blockedbyclient"
    route = Route()
    asyncio.run(ctx.handler(route, Req("https://cdn.public.example/a.css")))
    assert route.aborted is None
    # the workspace changes its lists: the next call sees them, on the same browser
    reg.record = _record(allow=["example.com"], version=2)
    out = _call(client, tok, "navigate", url="https://public.example/leak")
    assert out["isError"] and "outside the ones" in out["content"][0]["text"]
    assert _call(client, tok, "navigate", url="https://example.com/")["isError"] is False and len(ven.created) == 1
    asyncio.run(gw._browser_close(sid, "turn_end"))
    assert json.loads(_rows(hid)[-1]["detail"])["blocked"] == ["10.0.0.5"]


def test_caps_and_the_vendor_saying_no(client, world, monkeypatch):
    reg, ven, _ = world
    reg.record = _record()
    hid = _harness(client)
    _include(client, hid)
    sid = _session_of(hid)
    tok = gw._mint_hosted_cred(hid, sid, _key(hid))
    # the vendor's wallet and its concurrency, in the agent's words
    ven.refuse = 402
    out = _call(client, tok, "navigate", url="https://example.com/")
    assert out["isError"] and "no credit left" in out["content"][0]["text"]
    ven.refuse = 429
    out = _call(client, tok, "navigate", url="https://example.com/")
    assert out["isError"] and "Every browser is in use" in out["content"][0]["text"]
    assert [r["error"] for r in _rows(hid)[-2:]] == ["vendor_credits", "vendor_busy"]
    # the per-call cap
    monkeypatch.setattr(browser_plane, "CALL_CAP_S", 0.2)
    assert _call(client, tok, "navigate", url="https://example.com/")["isError"] is False
    browsers[-1].contexts[0].pages[0].slow = 1.0
    out = _call(client, tok, "navigate", url="https://example.com/")
    assert out["isError"] and "longer than" in out["content"][0]["text"]
    assert _rows(hid)[-1]["error"] == "timeout"
    monkeypatch.setattr(browser_plane, "CALL_CAP_S", 60.0)
    # idle and the session cap are found by the reaper, and each stop is in the trail
    s = browser_plane.sessions()[sid]
    s.last_used -= browser_plane.IDLE_S + 1
    assert [(x.sid, why) for x, why in browser_plane.expired_sessions()] == [(sid, "idle")]
    asyncio.run(gw._browser_close(sid, "idle"))
    assert ven.stopped == ["bu_1"] and json.loads(_rows(hid)[-1]["detail"])["reason"] == "idle"
    assert _call(client, tok, "navigate", url="https://example.com/")["isError"] is False
    s = browser_plane.sessions()[sid]
    s.created -= browser_plane.SESSION_CAP_MIN * 60 + 1
    assert [why for _, why in browser_plane.expired_sessions()] == ["session_cap"]
    asyncio.run(gw._browser_close(sid, "session_cap"))
    assert ven.stopped == ["bu_1", "bu_2"] and json.loads(_rows(hid)[-1]["detail"])["minutes"] == 21


def test_not_configured_a_stolen_credential_and_the_org_gate(client, world, monkeypatch):
    reg, ven, _ = world
    reg.record = _record()
    hid = _harness(client)
    _include(client, hid)
    sid = _session_of(hid)
    tok = gw._mint_hosted_cred(hid, sid, _key(hid))
    monkeypatch.setattr(browser_plane, "API_KEY", "")
    out = _call(client, tok, "navigate", url="https://example.com/")
    assert out["isError"] and "not set up on this deployment" in out["content"][0]["text"]
    monkeypatch.setattr(browser_plane, "API_KEY", VENDOR_KEY)
    # another harness's credential over this harness's record key
    thief = _harness(client)
    _include(client, thief)
    stolen = gw._mint_hosted_cred(thief, "sessX", _key(hid))
    out = _call(client, stolen, "navigate", url="https://example.com/")
    assert out["isError"] and "No plugins are connected" in out["content"][0]["text"] and ven.created == []
    # the org gate: the browser is open to every org; the held plugs are not, by name
    monkeypatch.setattr(gw, "_PLUGS_ORGS", set())
    sid2 = _session_of(thief)
    tok2 = gw._mint_hosted_cred(thief, sid2, _key(thief))
    out = _call(client, tok2, "navigate", url="https://example.com/")
    assert out["isError"] is False and len(ven.created) == 1
    asyncio.run(gw._browser_close(sid2, "turn_end"))
    r = _post(client, f"/v1/harnesses/{thief}/servers/plugs", {"plugs": ["browser", "github"]})
    assert r.status_code == 404 and r.json()["error"]["code"] == "plugs_unavailable" and "GitHub plug" in r.json()["error"]["message"]
    assert _post(client, f"/v1/harnesses/{thief}/servers/plugs", {"plugs": ["browser"]}).status_code == 200
    # a package that requires both gets the open one now and the held one when the org is let in
    manifest = {"$schema": PLUGIN_SCHEMA, "name": "needs-both", "version": "1.0.0", "requires": {"plugs": ["browser", "github"]}}
    r = _post(client, "/v1/harnesses", {"name": "Held", "base": "claude-code",
                                        "plugins": [{"files": [{"path": "plugin.json", "content": json.dumps(manifest)}]}]})
    assert r.status_code == 200 and _get(client, f"/v1/harnesses/{r.json()['id']}/servers/mcp.plugs").json()["plugs"] == ["browser"]


def test_a_package_that_requires_the_browser_includes_it_and_the_count_reads_the_bindings(client, world):
    reg, _, _ = world
    reg.record = _record()
    manifest = {"$schema": PLUGIN_SCHEMA, "name": "needs-browser", "version": "1.0.0", "requires": {"plugs": ["browser"]}}
    r = _post(client, "/v1/harnesses", {"name": "Packaged", "base": "claude-code",
                                        "plugins": [{"files": [{"path": "plugin.json", "content": json.dumps(manifest)}]}]})
    assert r.status_code == 200, r.text
    hid = r.json()["id"]
    assert [e["id"] for e in r.json()["mcpServers"]] == ["mcp.plugs"]
    assert _get(client, f"/v1/harnesses/{hid}/servers/mcp.plugs").json() == {
        "id": "mcp.plugs", "name": "plugs", "enabled": True, "workspace": WS, "plugs": ["browser"], "status": {"browser": "connected"}}
    # "attached N of M harnesses" for the Plugins page, from the bindings
    other = _harness(client)
    _include(client, other, ("github",))
    _harness(client)
    r = client.get("/internal/plugs/attachments", params={"workspace": WS, "type": "browser"}, headers={"x-harness-internal": "test-internal-key"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["type"] == "browser" and d["workspace"] == WS and hid in d["harness_ids"] and other not in d["harness_ids"]
    assert d["attached"] == len(d["harness_ids"]) and d["harnesses"] > d["attached"]
    assert client.get("/internal/plugs/attachments", params={"workspace": WS, "type": "browser"}).status_code == 401


def test_fair_share_of_the_vendors_concurrency(client, world, monkeypatch):
    reg, ven, _ = world
    reg.record = _record(); reg.any_workspace = True
    monkeypatch.setattr(browser_plane, "ORG_SESSIONS", 2)
    monkeypatch.setattr(browser_plane, "MAX_SESSIONS", 3)
    hid = _harness(client)
    _include(client, hid)
    toks = [(sid := _session_of(hid), gw._mint_hosted_cred(hid, sid, _key(hid))) for _ in range(3)]
    assert _call(client, toks[0][1], "get_url")["isError"] is False
    assert _call(client, toks[1][1], "get_url")["isError"] is False
    out = _call(client, toks[2][1], "get_url")
    assert out["isError"] and "already has 2 browsers open" in out["content"][0]["text"] and len(ven.created) == 2
    assert _rows(hid)[-1]["error"] == "org_busy"
    # another org takes the third and last seat; its second is the ceiling
    other = {**HEADERS, "x-harness-org": "otherorg", "x-harness-workspace": "otherorg__hrws"}
    oh = _post(client, "/v1/harnesses", {"name": "Other", "base": "claude-code"}, other).json()["id"]
    assert client.post(f"/v1/harnesses/{oh}/servers/plugs", json={"plugs": ["browser"]}, headers=other).status_code == 200
    s1, s2 = _session_of(oh, "otherorg"), _session_of(oh, "otherorg")
    out = _call(client, gw._mint_hosted_cred(oh, s1, _key(oh)), "get_url")
    assert out["isError"] is False, out
    out = _call(client, gw._mint_hosted_cred(oh, s2, _key(oh)), "get_url")
    assert out["isError"] and "Every browser is in use" in out["content"][0]["text"] and len(ven.created) == 3
    # a stop frees the seat
    asyncio.run(gw._browser_close(toks[0][0], "turn_end"))
    assert _call(client, toks[2][1], "get_url")["isError"] is False
    for sid_, _t in toks:
        asyncio.run(gw._browser_close(sid_, "turn_end"))
    asyncio.run(gw._browser_close(s1, "turn_end"))


def test_the_key_is_read_from_the_mounted_file_at_every_use(client, world, monkeypatch, tmp_path):
    reg, ven, _ = world
    reg.record = _record()
    f = tmp_path / "browser-use-api-key"
    monkeypatch.setattr(browser_plane, "API_KEY", "")
    monkeypatch.setattr(browser_plane, "API_KEY_FILE", str(f))
    assert browser_plane.configured() is False
    f.write_text(VENDOR_KEY + "\n")
    assert browser_plane.configured() is True
    hid = _harness(client)
    _include(client, hid)
    sid = _session_of(hid)
    tok = gw._mint_hosted_cred(hid, sid, _key(hid))
    assert _call(client, tok, "get_url")["isError"] is False and ven.calls[-1].headers["X-Browser-Use-API-Key"] == VENDOR_KEY
    asyncio.run(gw._browser_close(sid, "turn_end"))


def test_the_page_reads_the_price_and_the_tools_from_here(client, world):
    hdr = {"x-harness-internal": "test-internal-key"}
    r = client.get("/internal/plugs/pricing", params={"type": "browser"}, headers=hdr)
    assert r.status_code == 200 and r.json() == {"type": "browser", "unit": "browser hour", "usd_per_unit": 0.02, "markup": 0.0,
                                                 "source": "vendor list price", "vendor": "browser-use", "billed_as": "browser.usd",
                                                 "rounding": "up to the minute, one-minute minimum", "session_cap_minutes": 20,
                                                 "session_estimate_usd": 0.006667}
    rows = client.get("/internal/plugs/pricing", headers=hdr).json()["pricing"]
    assert [x["type"] for x in rows] == ["browser", "github", "vercel", "insforge"] and rows[1]["usd_per_unit"] == 0.0
    r = client.get("/internal/plugs/tools", params={"type": "browser"}, headers=hdr)
    assert r.status_code == 200 and r.json()["label"] == "Browser" and len(r.json()["tools"]) == 13
    assert r.json()["tools"][0] == {"name": "navigate", "description": "Open a web address in the current tab and read what is on the page.", "risk": "write"}
    assert client.get("/internal/plugs/tools", params={"type": "printer"}, headers=hdr).status_code == 404
    assert client.get("/internal/plugs/pricing").status_code == 401


def test_no_secret_ever_reached_a_caller():
    """Every response body every test above received: the vendor key and the browser address are
    in none of them."""
    assert _seen
    for body in _seen:
        assert VENDOR_KEY not in body and CDP not in body and "SENTINEL" not in body


def test_two_first_calls_at_once_open_one_browser(client, world, monkeypatch):
    """A CLI that issues tool calls in parallel (pi) sent navigate and screenshot together as a
    task's first browser calls; both found no session and both opened a browser at the vendor,
    and only the one registered last was ever stopped (hr-test, 2026-09-25: two open rows, one
    session row, one vendor session left running). The open is one per session now."""
    reg, ven, posted = world
    reg.record = _record()
    hid = _harness(client)
    _include(client, hid)
    sid = _session_of(hid)
    real = browser_plane.connector

    async def slow_connect(cdp):          # the vendor answered; the CDP connect takes a moment
        await asyncio.sleep(0.02)
        return await real(cdp)
    monkeypatch.setattr(browser_plane, "connector", slow_connect)
    cfg = {"allow_domains": [], "deny_domains": []}

    async def both():
        return await asyncio.gather(
            gw._browser_plug_call(1, hid, sid, ORG, WS, "navigate", plugs_plane.find("browser", "navigate"), {"url": "example.com"}, cfg, time.time()),
            gw._browser_plug_call(2, hid, sid, ORG, WS, "screenshot", plugs_plane.find("browser", "screenshot"), {}, cfg, time.time()))
    a, b = asyncio.run(both())
    assert json.loads(a.body)["result"]["isError"] is False and json.loads(b.body)["result"]["isError"] is False
    assert len(ven.created) == 1, ven.created          # one browser at the vendor, not two
    opens = [r for r in _rows(hid) if r["tool"] == "open"]
    assert len(opens) == 1
    asyncio.run(gw._browser_close(sid, "turn_end"))
    stops = [r for r in _rows(hid) if r["tool"] == "session"]
    assert len(stops) == 1 and json.loads(stops[0]["detail"])["vendor_session"] == "bu_1"
    assert sid not in gw._browser_open_locks
