"""The browser server's plane: a real browser in a vendor's cloud, driven from this gateway over
the Chrome DevTools Protocol, handed to the agent as a dozen typed tools and nothing else.

One browser session per harness session, made on the first call and stopped at the end of the
turn, after idle, or at the session cap. The vendor is behind one adapter (Browser Use Cloud
first; Browserbase has the same shape: a session id and a CDP address), so the tools, the guards
and the metering never learn a vendor's name.

What the agent is never given: a JavaScript evaluator, downloads, cookies, the vendor's key, the
CDP address. What every request is checked against, subresources and redirects included: the
harness's allow and deny lists and the private, loopback, link-local and metadata address ranges.

Money: the vendor's list price, no markup. A session is priced BEFORE it starts as the session cap
times the per-minute rate (that is what counts against the task's cost cap), and metered AFTER
from the vendor's own figures for the minutes it ran (rounded up, one-minute minimum). The prices
below are the estimate's; the meter reads what the vendor reports.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import math
import os
import socket
import time
import urllib.parse

import httpx

API_KEY = os.environ.get("BROWSER_USE_API_KEY", "")
# The key as a mounted secret file, read at every use: a rotated Key Vault secret reaches a
# mounted file without a new revision, where an environment variable holds the value the process
# started with.
API_KEY_FILE = os.environ.get("BROWSER_USE_API_KEY_FILE", "")
API_BASE = os.environ.get("BROWSER_USE_API_BASE", "https://api.browser-use.com/api/v4").rstrip("/")
SESSION_CAP_MIN = int(os.environ.get("HR_BROWSER_SESSION_MINUTES", "20"))      # per harness session
# Fair share of the vendor's concurrency (10 sessions until $1,000 lifetime spend, then 250):
# no org holds more than its share, and this process stops one below the vendor's ceiling so the
# refusal an agent reads is ours, in a sentence, not the vendor's 429. Per process: a second
# gateway replica has its own counts.
ORG_SESSIONS = int(os.environ.get("HR_BROWSER_ORG_SESSIONS", "3"))
MAX_SESSIONS = int(os.environ.get("HR_BROWSER_MAX_SESSIONS", "9"))
CALL_CAP_S = float(os.environ.get("HR_BROWSER_CALL_SECONDS", "60"))            # per tool call
IDLE_S = float(os.environ.get("HR_BROWSER_IDLE_SECONDS", "120"))               # no call for this long: stopped
TEXT_CAP = 20000                                                               # characters of extracted text
SNAPSHOT_CAP = 150                                                             # elements in a snapshot

# The vendor's list prices, no markup (browser-use.com/pricing and the v4 API docs, read
# 2026-09-24): browser time $0.02 per hour, rounded up to whole minutes, one-minute minimum;
# residential proxy $5 per GB (this slice runs with no proxy, so the unit never appears);
# screenshots are Playwright's and cost nothing. The meter posts dollars under one unit.
PRICES = {"browser.minute": 0.02 / 60, "browser.proxy_mb": 0.005, "browser.screenshot": 0.0}
UNIT = "browser.usd"
VENDOR = "browser-use"

transport: httpx.BaseTransport | None = None     # tests: the vendor's API
connector = None                                  # tests: async (cdp_url) -> a browser-like object


def api_key() -> str:
    if API_KEY_FILE:
        try:
            with open(API_KEY_FILE, encoding="utf-8") as f:
                key = f.read().strip()
            if key:
                return key
        except OSError:
            pass
    return API_KEY


def configured() -> bool:
    return bool(api_key())


def pricing() -> dict:
    """The browser's price line, for the page that shows it before a workspace turns it on."""
    return {"type": "browser", "unit": "browser hour", "usd_per_unit": round(PRICES["browser.minute"] * 60, 6),
            "markup": 0.0, "source": "vendor list price", "vendor": VENDOR, "billed_as": UNIT,
            "rounding": "up to the minute, one-minute minimum", "session_cap_minutes": SESSION_CAP_MIN,
            "session_estimate_usd": session_estimate_usd()}


def session_estimate_usd() -> float:
    """What a session may cost at most, before it starts: the cap in minutes at the list price."""
    return round(SESSION_CAP_MIN * PRICES["browser.minute"], 6)


class BrowserRefused(RuntimeError):
    """A call that must not run, with the sentence the agent reads."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class BrowserToolError(RuntimeError):
    """A call that ran and failed in a way the agent can act on."""


# ── the vendor ───────────────────────────────────────────────────────────────────────────────
def _vendor_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=transport, timeout=60,
                             headers={"X-Browser-Use-API-Key": api_key(), "content-type": "application/json"})


async def vendor_create(timeout_min: int, metadata: dict) -> dict:
    """A browser in the vendor's cloud: no proxy, no CAPTCHA solving, no recording, so the only
    unit that can bill is time. 402 is the vendor's wallet, 429 its concurrency."""
    async with _vendor_client() as c:
        r = await c.post(f"{API_BASE}/browsers", json={
            "timeout": int(timeout_min), "proxyCountryCode": None, "solveCaptchas": False,
            "enableRecording": False, "metadata": {k: str(v)[:100] for k, v in metadata.items()}})
    if r.status_code == 402:
        raise BrowserRefused("vendor_credits", "The browser service has no credit left. Tell the person.")
    if r.status_code == 429:
        raise BrowserRefused("vendor_busy", "Every browser is in use right now. Try again in a minute.")
    if r.status_code >= 400:
        raise BrowserRefused("vendor_error", f"The browser service refused to start a browser ({r.status_code}).")
    d = r.json()
    if not d.get("id") or not d.get("cdpUrl"):
        raise BrowserRefused("vendor_error", "The browser service answered without a browser address.")
    return d


async def vendor_stop(vendor_id: str) -> dict:
    """Stop the browser and read what it cost: closing the CDP socket alone keeps the meter
    running on the vendor's side."""
    async with _vendor_client() as c:
        r = await c.patch(f"{API_BASE}/browsers/{vendor_id}", json={"action": "stop"})
        if r.status_code >= 400:
            r = await c.get(f"{API_BASE}/browsers/{vendor_id}")
    try:
        return r.json() if r.status_code < 400 else {}
    except ValueError:
        return {}


def vendor_cost(d: dict) -> float | None:
    """Dollars the vendor reports for a session: its browser time, plus proxy traffic when any.
    None when it reported no browser cost, which is the figure of record."""
    if d.get("browserCost") is None:
        return None
    total = 0.0
    for p in (d.get("browserCost"), d.get("proxyCost")):
        try:
            total += float(p or 0)
        except (TypeError, ValueError):
            pass
    return round(total, 6)


# ── the address guard ────────────────────────────────────────────────────────────────────────
_PRIVATE_NAMES = ("localhost", ".localhost", ".local", ".internal", ".home.arpa", ".lan", ".corp")


def _ip_private(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return (a.is_private or a.is_loopback or a.is_link_local or a.is_multicast or a.is_reserved
            or a.is_unspecified or (a.version == 6 and a.ipv4_mapped is not None and _ip_private(str(a.ipv4_mapped))))


def _suffix_match(host: str, patterns: list[str]) -> bool:
    for p in patterns:
        p = (p or "").strip().lower().lstrip("*").lstrip(".")
        if p and (host == p or host.endswith("." + p)):
            return True
    return False


def host_policy(host: str, allow: list[str], deny: list[str]) -> str | None:
    """Why this host may not be reached, or None. Name rules only; the address rule follows."""
    h = (host or "").strip().lower().rstrip(".")
    if not h:
        return "no host"
    if h.startswith("[") and h.endswith("]"):
        h = h[1:-1]
    if _ip_private(h):
        return "a private or local address"
    if h == "localhost" or any(h.endswith(s) for s in _PRIVATE_NAMES[1:]):
        return "a private or local address"
    if deny and _suffix_match(h, deny):
        return "a site this agent is not allowed to visit"
    if allow and not _suffix_match(h, allow):
        return "a site outside the ones this agent is allowed to visit"
    return None


async def resolves_private(host: str) -> bool:
    """Whether any address the name resolves to is private. A name that does not resolve counts
    as private: this is an address a page chose, and it is asked again on every request."""
    h = (host or "").strip().lower().rstrip(".").strip("[]")
    if _ip_private(h):
        return True
    try:
        ipaddress.ip_address(h)
        return False
    except ValueError:
        pass
    try:
        infos = await asyncio.wait_for(asyncio.to_thread(socket.getaddrinfo, h, None), 4)
    except Exception:  # noqa: BLE001
        return True
    return any(_ip_private(str(i[4][0])) for i in infos) or not infos


# ── the session ──────────────────────────────────────────────────────────────────────────────
# One browser per harness session, wherever the call lands. The RECORD of it (the vendor's id,
# the CDP address, when it opened and was last used, its counts, its lists) is kept once for every
# gateway process by the registry below; the ATTACHMENT (the CDP connection, the context, the
# page) is this process's own, made by the first call that reaches it and dropped when the record
# goes. A CLI's tool calls are load-balanced over every replica, and a per-process record let one
# turn open a browser on each replica it reached (four for one turn on 2026-09-25, three of them
# stopped only by the idle reaper, none of them the page the agent had opened).
class Session:
    """This process's attachment to a session's browser, built from its record."""

    def __init__(self, rec: dict):
        self.sid, self.hid, self.org, self.workspace = str(rec["sid"]), str(rec["hid"]), str(rec["org"]), str(rec["workspace"])
        self.allow, self.deny = list(rec.get("allow") or []), list(rec.get("deny") or [])
        self.vendor_id = str(rec.get("vendor_id") or "")
        self.cdp_url = str(rec.get("cdp_url") or "")
        self.live_url = str(rec.get("live_url") or "")
        self.created = float(rec.get("created") or time.time())
        self.reserved = float(rec.get("reserved") or 0.0)   # what was counted against the task before the browser opened
        self.browser = None
        self.context = None
        self.page = None
        self.blocked: list[str] = []            # hosts this attachment refused, so each is recorded once
        self.host_cache: dict[str, bool] = {}
        self.lock = asyncio.Lock()
        self.closed = False
        self.opened = False                     # this call made the browser at the vendor: the caller writes the open row once


def minutes(rec: dict) -> int:
    return max(1, math.ceil((time.time() - float(rec.get("created") or time.time())) / 60))


def expired(rec: dict, now: float | None = None) -> str | None:
    now = now or time.time()
    if now - float(rec.get("created") or now) > SESSION_CAP_MIN * 60:
        return "session_cap"
    if now - float(rec.get("last_used") or now) > IDLE_S:
        return "idle"
    return None


# ── the registry ─────────────────────────────────────────────────────────────────────────────
# Where the records live. In this process by default, which is right for one gateway process (a
# self-hosted instance); a deployment that runs several installs one over its shared store, so
# the same session reads the same browser from every replica. `bump` increments the counters
# named in COUNTERS, appends to the lists named in LISTS and sets anything else.
COUNTERS = ("calls", "screenshots")
LISTS = ("blocked",)


class LocalRegistry:
    def __init__(self):
        self._recs: dict[str, dict] = {}

    async def get(self, sid: str) -> dict | None:
        return self._recs.get(sid)

    async def create(self, sid: str, rec: dict) -> bool:
        """True iff this call made the record; False when one is there already."""
        if sid in self._recs:
            return False
        self._recs[sid] = rec
        return True

    async def bump(self, sid: str, **fields) -> None:
        rec = self._recs.get(sid)
        if rec is None:
            return
        for k, v in fields.items():
            if k in COUNTERS:
                rec[k] = int(rec.get(k) or 0) + int(v)
            elif k in LISTS:
                rec.setdefault(k, []).append(v)
            else:
                rec[k] = v

    async def delete(self, sid: str) -> bool:
        """True iff this call removed the record: the remover stops the browser and writes its row."""
        return self._recs.pop(sid, None) is not None

    async def all(self) -> list[dict]:
        return list(self._recs.values())

    async def lock(self, sid: str, ttl_s: int) -> bool:
        return True                             # one process: the caller's own lock serialises its opens

    async def unlock(self, sid: str) -> None:
        pass


registry = LocalRegistry()
_SESSIONS: dict[str, Session] = {}            # this process's attachments, by session
_pw = None


def sessions() -> dict[str, Session]:
    return _SESSIONS


def _record(sid: str, hid: str, org: str, workspace: str, allow: list[str], deny: list[str], d: dict,
            reserved: float) -> dict:
    now = time.time()
    return {"sid": sid, "hid": hid, "org": org, "workspace": workspace, "allow": list(allow), "deny": list(deny),
            "vendor_id": str(d["id"]), "cdp_url": str(d["cdpUrl"]), "live_url": str(d.get("liveUrl") or ""),
            "created": now, "last_used": now, "calls": 0, "screenshots": 0, "blocked": [],
            "reserved": float(reserved)}


async def _connect(cdp_url: str):
    global _pw
    if connector is not None:
        return await connector(cdp_url)
    from playwright.async_api import async_playwright
    if _pw is None:
        _pw = await async_playwright().start()
    return await _pw.chromium.connect_over_cdp(cdp_url, timeout=30000)


async def _allowed(s: Session, url: str) -> str | None:
    """Why this URL may not be requested from this session, or None; resolved once per host."""
    try:
        u = urllib.parse.urlsplit(url)
    except ValueError:
        return "not a valid address"
    if u.scheme not in ("http", "https"):
        return f"a {u.scheme or 'non-web'} address" if u.scheme not in ("about", "data", "blob") else None
    host = u.hostname or ""
    why = host_policy(host, s.allow, s.deny)
    if why:
        return why
    if host not in s.host_cache:
        s.host_cache[host] = await resolves_private(host)
    return "a private or local address" if s.host_cache[host] else None


async def open_session(sid: str, hid: str, org: str, workspace: str, allow: list[str], deny: list[str],
                       reserved: float = 0.0) -> Session:
    """The session's browser, attached here: the recorded one when there is one, else a new one at
    the vendor, recorded for every process first. One opener at a time across processes: the
    others wait for its record. `opened` on the result says this call made the browser."""
    if not configured():
        raise BrowserRefused("not_configured", "The browser service is not set up on this deployment. Tell the person.")
    rec = await registry.get(sid)
    locked = False
    if rec is None:
        for _ in range(60):
            if await registry.lock(sid, 30):
                locked = True
                break
            await asyncio.sleep(0.5)
            rec = await registry.get(sid)
            if rec is not None:
                break
        else:
            raise BrowserRefused("busy", "The browser is still being started. Try again in a moment.")
    opened = False
    try:
        if rec is None:
            live = await registry.all()
            if sum(1 for x in live if x.get("org") == org) >= ORG_SESSIONS:
                raise BrowserRefused("org_busy", f"This account already has {ORG_SESSIONS} browsers open. Try again when one of them finishes.")
            if len(live) >= MAX_SESSIONS:
                raise BrowserRefused("busy", "Every browser is in use right now. Try again in a minute.")
            d = await vendor_create(SESSION_CAP_MIN, {"harness": hid, "session": sid})
            rec = _record(sid, hid, org, workspace, allow, deny, d, reserved)
            if await registry.create(sid, rec):
                opened = True
            else:
                # Made elsewhere between the lock and here (a lock the store could not keep): theirs stands.
                try:
                    await vendor_stop(rec["vendor_id"])
                except Exception:  # noqa: BLE001
                    pass
                rec = await registry.get(sid)
                if rec is None:
                    raise BrowserRefused("busy", "The browser could not be started. Try again.")
    finally:
        if locked:
            await registry.unlock(sid)
    try:
        s = await attach(rec)
    except Exception:
        if opened:                              # a browser nobody can reach: not left for the reaper
            await registry.delete(sid)
            try:
                await vendor_stop(rec["vendor_id"])
            except Exception:  # noqa: BLE001
                pass
        raise
    s.opened = opened
    return s


async def attach(rec: dict) -> Session:
    """This process's attachment to the recorded browser, made on first use and kept. Every process
    uses the browser's own default context and its first tab, so the page is the same page from
    every replica; the request gate is installed per attachment and reads the record's lists."""
    sid = str(rec["sid"])
    s = _SESSIONS.get(sid)
    if s is not None and not s.closed and s.vendor_id == str(rec.get("vendor_id") or ""):
        return s
    if s is not None:
        await detach(s)                         # the record names another browser: this one is gone
    s = Session(rec)
    s.browser = await _connect(s.cdp_url)
    try:
        contexts = list(getattr(s.browser, "contexts", None) or [])
        s.context = contexts[0] if contexts else await s.browser.new_context(accept_downloads=False, viewport={"width": 1280, "height": 800})

        async def gate(route, request):
            why = await _allowed(s, request.url)
            if why:
                host = urllib.parse.urlsplit(request.url).hostname or request.url[:60]
                if host not in s.blocked:
                    s.blocked.append(host)
                    await registry.bump(sid, blocked=host)
                await route.abort("blockedbyclient")
            else:
                await route.continue_()

        await s.context.route("**/*", gate)
        pages = list(getattr(s.context, "pages", None) or [])
        s.page = pages[0] if pages else await s.context.new_page()
        s.page.set_default_timeout(30000)
    except Exception:
        await detach(s)
        raise
    _SESSIONS[sid] = s
    return s


async def detach(s: Session) -> None:
    """Drop this process's attachment; the browser itself stays as it is (a connected browser's
    close disconnects it and closes only the contexts this attachment made)."""
    s.closed = True
    if _SESSIONS.get(s.sid) is s:
        _SESSIONS.pop(s.sid, None)
    closer = getattr(s.browser, "close", None)
    if closer:
        try:
            await asyncio.wait_for(closer(), 10)
        except Exception:  # noqa: BLE001
            pass


async def close_session_browser(rec: dict, s: Session | None) -> dict:
    """Stop the recorded browser and read the vendor's figures, dropping this process's attachment
    when it has one. Every step is best effort: a browser that would not close must not keep its
    minutes from being metered."""
    if s is not None:
        s.closed = True
        if _SESSIONS.get(s.sid) is s:
            _SESSIONS.pop(s.sid, None)
        for closer in (getattr(s.context, "close", None), getattr(s.browser, "close", None)):
            if closer:
                try:
                    await asyncio.wait_for(closer(), 10)
                except Exception:  # noqa: BLE001
                    pass
    figures: dict = {}
    if rec.get("vendor_id"):
        try:
            figures = await vendor_stop(str(rec["vendor_id"]))
        except Exception:  # noqa: BLE001
            figures = {}
    usd = vendor_cost(figures)
    source = "vendor"
    if usd is None:
        usd, source = round(minutes(rec) * PRICES["browser.minute"], 6), "table"
    return {"minutes": minutes(rec), "usd": usd, "usd_source": source, "calls": int(rec.get("calls") or 0),
            "screenshots": int(rec.get("screenshots") or 0), "blocked": list(rec.get("blocked") or [])[:20],
            "proxy_mb": figures.get("proxyUsedMb") or 0}


async def expired_sessions(now: float | None = None) -> list[tuple[dict, str]]:
    """Every recorded browser past its cap or idle, from any process."""
    now = now or time.time()
    return [(rec, why) for rec in await registry.all() if (why := expired(rec, now))]


async def sweep_attachments() -> None:
    """Drop the attachments whose browser was stopped from another process."""
    for s in list(_SESSIONS.values()):
        if await registry.get(s.sid) is None:
            await detach(s)


# ── the tools ────────────────────────────────────────────────────────────────────────────────
_TOOLS: list[dict] = []


def _tool(name: str, risk: str, description: str, schema: dict):
    _TOOLS.append({"name": name, "risk": risk, "description": description,
                   "inputSchema": {"type": "object", "properties": schema.get("properties", {}),
                                   "required": schema.get("required", []), "additionalProperties": False}})


_REF = {"ref": {"type": "string", "description": "An element ref from the last snapshot, like e12."},
        "selector": {"type": "string", "description": "A CSS selector, when there is no ref for the element."}}

_tool("navigate", "act", "Open a web address in the current tab and read what is on the page.",
      {"properties": {"url": {"type": "string", "description": "An http or https address."}}, "required": ["url"]})
_tool("get_url", "read", "The current tab's address and title.", {})
_tool("snapshot", "read", "What is on the page: headings, links, buttons and fields, each with a ref to act on.",
      {"properties": {"max_elements": {"type": "integer", "description": f"At most this many elements (default {SNAPSHOT_CAP})."}}})
_tool("extract_text", "read", "The readable text of the page, or of one element.",
      {"properties": {"selector": {"type": "string", "description": "A CSS selector; the whole page when absent."},
                      "max_chars": {"type": "integer", "description": f"At most this many characters (default {TEXT_CAP})."}}})
_tool("click", "act", "Click an element, by ref or selector.", {"properties": dict(_REF)})
_tool("type", "act", "Type text into a field, by ref or selector, replacing what is there.",
      {"properties": {**_REF, "text": {"type": "string"}, "submit": {"type": "boolean", "description": "Press Enter afterwards."}},
       "required": ["text"]})
_tool("press_key", "act", "Press a key, like Enter, Tab, Escape or ArrowDown.",
      {"properties": {"key": {"type": "string"}}, "required": ["key"]})
_tool("scroll", "act", "Scroll the page.",
      {"properties": {"direction": {"type": "string", "enum": ["down", "up"]},
                      "pixels": {"type": "integer", "description": "How far (default 600)."}}})
_tool("wait_for", "read", "Wait until text or an element appears, or for a number of milliseconds.",
      {"properties": {"text": {"type": "string"}, "selector": {"type": "string"},
                      "ms": {"type": "integer", "description": f"Milliseconds, at most {int(CALL_CAP_S * 1000)}."}}})
_tool("screenshot", "read", "A picture of the current tab, kept with the task's files and shown to you.",
      {"properties": {"full_page": {"type": "boolean", "description": "The whole page, not only the visible part."}}})
_tool("back", "act", "Go back one page in the current tab.", {})
_tool("list_tabs", "read", "The open tabs, with their index, address and title.", {})
_tool("switch_tab", "act", "Make one of the open tabs the current tab.",
      {"properties": {"index": {"type": "integer"}}, "required": ["index"]})


def tool_list() -> list[dict]:
    return [{"name": f"browser.{t['name']}", "description": f"[browser, {t['risk']}] {t['description']}",
             "inputSchema": t["inputSchema"],
             "annotations": {"readOnlyHint": t["risk"] == "read", "destructiveHint": False}} for t in _TOOLS]


def find(name: str) -> dict | None:
    return next((t for t in _TOOLS if t["name"] == name), None)


_SNAPSHOT_JS = """
(max) => {
  const out = []; let n = 0;
  const seen = new Set();
  const vis = (el) => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none'; };
  const nameOf = (el) => (el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('placeholder')
    || (el.labels && el.labels[0] && el.labels[0].innerText) || el.getAttribute('alt') || el.innerText || el.value || '').trim().replace(/\\s+/g, ' ').slice(0, 80);
  const sel = 'h1,h2,h3,a[href],button,input,select,textarea,[role=button],[role=link],[role=tab],[role=menuitem],[role=checkbox],[role=radio],[role=textbox],[contenteditable=true],summary';
  for (const el of document.querySelectorAll(sel)) {
    if (n >= max) { out.push({truncated: true}); break; }
    if (!vis(el) || seen.has(el)) continue;
    seen.add(el);
    const tag = el.tagName.toLowerCase();
    const role = el.getAttribute('role') || (tag === 'a' ? 'link' : tag === 'button' || tag === 'summary' ? 'button'
      : tag === 'select' ? 'combobox' : tag === 'textarea' ? 'textbox' : tag === 'input' ? ((el.type === 'checkbox' || el.type === 'radio' || el.type === 'submit' || el.type === 'button') ? el.type : 'textbox')
      : /^h[1-3]$/.test(tag) ? 'heading' : tag);
    const row = {role, name: nameOf(el)};
    if (role !== 'heading') { const ref = 'e' + (++n); el.setAttribute('data-hr-ref', ref); row.ref = ref; }
    else row.level = Number(tag[1]);
    if (tag === 'a') row.href = (el.getAttribute('href') || '').slice(0, 120);
    if (tag === 'input' || tag === 'textarea') { if (el.value && el.type !== 'password') row.value = String(el.value).slice(0, 60); if (el.disabled) row.disabled = true; }
    if (el.type === 'checkbox' || el.type === 'radio') row.checked = !!el.checked;
    out.push(row);
  }
  return out;
}
"""


def _fmt_snapshot(rows: list[dict]) -> str:
    lines = []
    for r in rows:
        if r.get("truncated"):
            lines.append("… more elements below; scroll or ask for a larger snapshot")
            continue
        if r.get("role") == "heading":
            lines.append(f"h{r.get('level', 2)} \"{r.get('name', '')}\"")
            continue
        extra = ""
        if r.get("href"):
            extra += f" href={r['href']}"
        if "value" in r:
            extra += f" value=\"{r['value']}\""
        if "checked" in r:
            extra += " checked" if r["checked"] else " unchecked"
        if r.get("disabled"):
            extra += " disabled"
        lines.append(f"{r.get('ref')} {r.get('role')} \"{r.get('name', '')}\"{extra}")
    return "\n".join(lines) if lines else "(nothing interactive is visible on this page)"


async def _snapshot(s: Session, max_elements: int) -> str:
    rows = await s.page.evaluate(_SNAPSHOT_JS, max(1, min(int(max_elements or SNAPSHOT_CAP), 500)))
    return _fmt_snapshot(rows or [])


def _target(s: Session, args: dict):
    ref, selector = str(args.get("ref") or "").strip(), str(args.get("selector") or "").strip()
    if ref:
        return s.page.locator(f'[data-hr-ref="{ref}"]').first
    if selector:
        return s.page.locator(selector).first
    raise BrowserToolError("Say which element: a ref from the snapshot or a selector.")


async def _where(s: Session) -> str:
    try:
        title = await s.page.title()
    except Exception:  # noqa: BLE001
        title = ""
    return f"{s.page.url}" + (f" ({title})" if title else "")


async def _settled(s: Session) -> None:
    with_timeout = getattr(s.page, "wait_for_load_state", None)
    if with_timeout:
        try:
            await asyncio.wait_for(s.page.wait_for_load_state("domcontentloaded"), 8)
        except Exception:  # noqa: BLE001
            pass


async def call(s: Session, name: str, args: dict):
    """Run one tool on this session. Returns text, or ("image", png bytes, caption) for a
    screenshot the caller stores. Raises BrowserToolError with a sentence the agent can act on."""
    await registry.bump(s.sid, last_used=time.time(), calls=1)
    page = s.page
    if name == "navigate":
        url = str(args.get("url") or "").strip()
        if not url:
            raise BrowserToolError("Give a web address to open.")
        if "://" not in url:
            url = "https://" + url
        why = await _allowed(s, url)
        if why:
            raise BrowserToolError(f"That address is {why}, so it cannot be opened.")
        try:
            await page.goto(url, wait_until="domcontentloaded")
        except Exception as e:  # noqa: BLE001
            raise BrowserToolError(f"The page did not open: {str(e).splitlines()[0][:200]}") from None
        return f"Opened {await _where(s)}\n\n{await _snapshot(s, 80)}"
    if name == "get_url":
        return await _where(s)
    if name == "snapshot":
        return f"{await _where(s)}\n\n{await _snapshot(s, args.get('max_elements') or SNAPSHOT_CAP)}"
    if name == "extract_text":
        selector = str(args.get("selector") or "").strip() or "body"
        cap = max(200, min(int(args.get("max_chars") or TEXT_CAP), TEXT_CAP))
        try:
            text = await page.locator(selector).first.inner_text()
        except Exception as e:  # noqa: BLE001
            raise BrowserToolError(f"No readable text at {selector!r}: {str(e).splitlines()[0][:160]}") from None
        text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        return text[:cap] + (f"\n… {len(text) - cap} more characters" if len(text) > cap else "")
    if name == "click":
        loc = _target(s, args)
        try:
            await loc.click(timeout=15000)
        except Exception as e:  # noqa: BLE001
            raise BrowserToolError(f"The click did not land: {str(e).splitlines()[0][:160]}") from None
        await _settled(s)
        return f"Clicked. Now at {await _where(s)}"
    if name == "type":
        loc = _target(s, args)
        text = str(args.get("text") or "")
        try:
            await loc.fill(text, timeout=15000)
            if args.get("submit"):
                await loc.press("Enter")
                await _settled(s)
        except Exception as e:  # noqa: BLE001
            raise BrowserToolError(f"Typing failed: {str(e).splitlines()[0][:160]}") from None
        return f"Typed {len(text)} characters." + (f" Now at {await _where(s)}" if args.get("submit") else "")
    if name == "press_key":
        key = str(args.get("key") or "").strip()
        if not key:
            raise BrowserToolError("Say which key.")
        await page.keyboard.press(key)
        await _settled(s)
        return f"Pressed {key}. Now at {await _where(s)}"
    if name == "scroll":
        px = max(50, min(int(args.get("pixels") or 600), 5000))
        dy = -px if str(args.get("direction") or "down") == "up" else px
        await page.mouse.wheel(0, dy)
        return f"Scrolled {'up' if dy < 0 else 'down'} {abs(dy)} pixels."
    if name == "wait_for":
        text, selector = str(args.get("text") or "").strip(), str(args.get("selector") or "").strip()
        ms = int(args.get("ms") or 0)
        budget = int(CALL_CAP_S * 1000) - 2000
        try:
            if text:
                await page.get_by_text(text).first.wait_for(timeout=budget)
                return f"\"{text}\" is on the page."
            if selector:
                await page.locator(selector).first.wait_for(timeout=budget)
                return f"{selector} is on the page."
        except Exception:  # noqa: BLE001
            raise BrowserToolError("It did not appear within the wait.") from None
        if ms > 0:
            await asyncio.sleep(min(ms, budget) / 1000)
            return f"Waited {min(ms, budget)} ms."
        raise BrowserToolError("Say what to wait for: text, a selector or a number of milliseconds.")
    if name == "screenshot":
        try:
            png = await page.screenshot(type="png", full_page=bool(args.get("full_page")))
        except Exception as e:  # noqa: BLE001
            raise BrowserToolError(f"The screenshot failed: {str(e).splitlines()[0][:160]}") from None
        await registry.bump(s.sid, screenshots=1)
        return ("image", png, f"Screenshot of {await _where(s)}")
    if name == "back":
        try:
            await page.go_back(wait_until="domcontentloaded")
        except Exception as e:  # noqa: BLE001
            raise BrowserToolError(f"Could not go back: {str(e).splitlines()[0][:160]}") from None
        return f"Back at {await _where(s)}"
    if name == "list_tabs":
        rows = []
        for i, p in enumerate(s.context.pages):
            try:
                t = await p.title()
            except Exception:  # noqa: BLE001
                t = ""
            rows.append(f"{i}{' *' if p is s.page else ''} {p.url}" + (f" ({t})" if t else ""))
        return "\n".join(rows) or "(no tabs)"
    if name == "switch_tab":
        pages = s.context.pages
        i = int(args.get("index") or 0)
        if i < 0 or i >= len(pages):
            raise BrowserToolError(f"There is no tab {i}; there are {len(pages)}.")
        s.page = pages[i]
        s.page.set_default_timeout(30000)
        return f"Current tab is now {i}: {await _where(s)}"
    raise BrowserToolError(f"No tool named browser.{name}.")


def audit_line(d: dict) -> str:
    """The record's one-line shape, for the trace and the log."""
    return json.dumps(d, separators=(",", ":"))
