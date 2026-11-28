"""Realtime voice sessions on a harness: a speech-to-speech call that keeps the harness's own
instructions and its plug tools, spoken directly between the caller's browser and the provider.

THE GATEWAY'S HALF IS THIN ON PURPOSE. It mints a short-lived client secret for one call, bridges the
call's tool calls to the plugs server as the harness, and meters the call as a session of the harness.
Audio never passes through here: the browser speaks WebRTC to the provider with the client secret, and
the provider key never leaves this process.

THREE PIECES, so a second provider or a realtime harness takes one of them over without a rewrite:

  Provider     mint(spec) -> Minted, end(ref), usage(ref) -> Usage | None. The one place a vendor's
               API is spoken. AzureRealtime is the first: Azure OpenAI's GA realtime surface on the
               instance's Azure OpenAI connection.
  Ports        what the gateway lends the service: its plugs server (one MCP call, made as the
               agent's CLI makes it), its session record and card, its usage meter and a one-holder
               lock. app.py builds them from functions it already has and wires three routes.
  Service      the contract: create, tool_call, end; settle, for a call whose session is deleted
               while open; and the sweep that meters a call nobody ended.

Money: a call is metered by the clock, elapsed minutes times HR_REALTIME_USD_PER_MIN (the list
price, below), capped by the call's max_cost_usd, posted once as `media.usd` (dollars at the
provider's price, which the ledger counts as model usage) and written on the session record as its
spend_usd. A provider that can say what a call used (a server sideband on the call, a realtime
harness) answers `usage()` and is billed by that instead.

OFF BY DEFAULT. HR_REALTIME=1 turns the three routes on; without it each answers 403
`realtime_not_enabled` and no call is minted. A call that started is always ended and metered,
whatever the switch says by then.

TWO PROVIDERS. AzureRealtime hands the caller's browser a client secret and the browser talks to Azure
itself: nothing sits on the call, so the browser can change its own call's instructions and tools, and
nothing here can hang up. HarnessRealtime (HR_REALTIME_PROVIDER=harness) places the call on a Realtime
Harness instead, which relays it: the device talks to the harness, the harness to Azure. The harness
keeps the configuration the gateway handed it, runs the call's tools itself against the plugs server,
hangs up when told, and knows what each turn said and used. So a relayed call is ended for real, billed
by its tokens and leaves a transcript. The provider key still never leaves this process: the harness
asks for a short-lived credential per connection, with a token good for its one call.
"""
from __future__ import annotations

import asyncio
import dataclasses
import datetime
import json
import os
import re
import time
import typing
import urllib.parse
import uuid

import httpx
from fastapi import HTTPException
from pydantic import BaseModel

# ── settings ─────────────────────────────────────────────────────────────────────────────────────
# The switch: voice calls are served only where HR_REALTIME is set. Unset by default: nobody.
ENABLED = os.environ.get("HR_REALTIME", "").strip().lower() in ("1", "true", "yes", "on")
# The instance's Azure OpenAI connection by its name; empty: the first enabled Azure OpenAI
# connection that has a credential (a key, or a Microsoft Entra sign-in) and an Azure endpoint.
INTEGRATION = os.environ.get("HR_REALTIME_INTEGRATION", "").strip()
MODEL = os.environ.get("HR_REALTIME_MODEL", "gpt-realtime-2.1").strip()
# A deployment is named by whoever made the resource. Its name is read, in this order, from the
# connection's own model row for MODEL (the row every other base reads), from this setting, and
# last from MODEL itself.
DEPLOYMENT = os.environ.get("HR_REALTIME_DEPLOYMENT", "").strip()
# Azure takes the input transcription model as the name of a transcription DEPLOYMENT on the same
# resource (its documented deviation from OpenAI's reference), gpt-4o-transcribe for one. Empty:
# the caller's speech is not transcribed by the provider (the model's own spoken answers still are).
#
# What a call is set to here is its start, not a lock: the browser holds the client secret and may send
# session.update (instructions, tools) for its own call, and neither Azure nor OpenAI's client-secret
# mint has a setting that forbids it. What the gateway runs does not move with it: the tool calls route
# runs only the harness's plug tools recorded at the mint, under the same consent gate. Measured on Azure
# gpt-realtime-2.1 (2026-10-27): a client's session.update replaced the tools (with none) and the
# instructions, both confirmed by session.updated; a model change was confirmed and ignored.
TRANSCRIBE = os.environ.get("HR_REALTIME_TRANSCRIBE_DEPLOYMENT", "").strip()


def _env_float(name: str, default: float) -> float:
    try:
        v = float(os.environ.get(name, "") or default)
        return v if v > 0 else default
    except ValueError:
        return default


# The list price per minute of call (OpenAI's published price for gpt-realtime-2.1, read 2026-10-26:
# audio in $32 and audio out $64 per million tokens, text in $4, cached input $0.40). A minute of the
# caller's speech is about 600 audio tokens ($0.0192) and a minute of the model's about 1,200 ($0.0768):
# both directions full is $0.096, rounded up to cover the instructions and tools each answer re-reads.
USD_PER_MIN = _env_float("HR_REALTIME_USD_PER_MIN", 0.10)
DEFAULT_MINUTES = 10
MAX_MINUTES = 30
# How long the client secret may be used to START the call (Azure: 10 to 7200 s). The call itself then
# lasts until it is hung up or reaches max_minutes; this bounds only how long a minted secret is worth
# stealing.
# The secret's lifetime bounds starting a call only loosely: one minted with expires_after 120 s still opened a
# session at 135 s (Azure, 2026-10-27). Nothing may treat it as a hard window, a revocation among them.
SECRET_TTL_S = int(min(max(_env_float("HR_REALTIME_SECRET_TTL_S", 120), 10), 7200))
VOICES = ("alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse", "marin", "cedar")
DEFAULT_VOICE = os.environ.get("HR_REALTIME_VOICE", "marin").strip() or "marin"
MAX_TOOLS = 128                  # the provider's ceiling on a session's tools
MAX_CLIENT_TOOLS = 8             # page tools a call may carry beside the harness's
CLIENT_PARAMS_MAX = 8000         # characters of one page tool's parameters, as JSON
DESC_MAX = 1024                  # characters of a tool's description handed to a speech model
OUTPUT_MAX = 16000               # characters of a tool's answer handed back for the model to speak from
SWEEP_EVERY_S = 60               # a call nobody hung up on the gateway's side ends within this of its max_minutes
END_CLAIM_S = 30 * 86400         # how long the claim that one replica meters a call is kept
KIND = "realtime"
METRIC = "media.usd"
LIVE, ENDED = "live", "done"
SID_PREFIX = "hrrt_"

# The one line every call adds to the harness's own instructions.
CALL_NOTE = ("This is a spoken call. Keep your answers short. Say so when you use a tool, and when an "
             "action waits for a person's approval.")
NOT_OPEN = "Voice calls are not turned on for this instance. Its operator sets HR_REALTIME=1 to serve them."
NOT_SET_UP = ("Voice calls need an Azure OpenAI connection with a realtime deployment, and this instance "
              "has none.")
ENDED_DETAIL = "This call has ended."

# Which provider carries a call: "azure" (the browser and Azure, directly) or "harness" (a Realtime Harness
# relays it). The harness is reached by this gateway at HARNESS_URL and by the caller's device at
# HARNESS_PUBLIC_URL, a ws:// or wss:// address: a device connects to the harness itself, and the console's
# own port carries no WebSocket.
PROVIDER = os.environ.get("HR_REALTIME_PROVIDER", "azure").strip().lower() or "azure"
HARNESS_URL = os.environ.get("HR_REALTIME_HARNESS_URL", "").strip().rstrip("/")
HARNESS_PUBLIC_URL = os.environ.get("HR_REALTIME_HARNESS_PUBLIC_URL", "").strip().rstrip("/")
HARNESS_NOT_SET_UP = ("Voice calls are set to run on a Realtime Harness, and this instance does not say where it "
                      "is: HR_REALTIME_HARNESS_URL, HR_REALTIME_HARNESS_PUBLIC_URL and HR_REALTIME_HARNESS_KEY.")
# How many provider credentials one relayed call may be given: its first connection, and the harness's
# replacements when the provider drops (it makes at most two), with one to spare.
MAX_UPSTREAM_MINTS = 4
# Dollars per million tokens, OpenAI's published prices for gpt-realtime-2.1 (read 2026-11-27): what a
# relayed call is billed by, from the usage the provider reports for each turn. Azure's own page listed no
# figure that day. A cached token costs the same whether it was text or audio.
USD_PER_M = {"text_in": 4.00, "audio_in": 32.00, "cached_in": 0.40, "text_out": 24.00, "audio_out": 64.00}

clock = time.time                                     # tests move it
transport: httpx.AsyncBaseTransport | None = None     # tests: the provider's API

_SID_RE = re.compile(r"^hrrt_[0-9a-f]{32}$")
_TOOL_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_CLIENT_TOOL_NAME = re.compile(r"^page_[A-Za-z0-9_-]{1,59}$")
_AZURE_HOSTS = (".openai.azure.com", ".cognitiveservices.azure.com", ".services.ai.azure.com")


def enabled() -> bool:
    """Whether this instance serves voice calls (the switch)."""
    return ENABLED


def _plain_error(status: int, code: str, message: str, param: str | None = None) -> HTTPException:
    return HTTPException(status, message)


# The gateway's protocol error (app.uhp_error), installed by the app; a plain HTTPException without it.
error: typing.Callable[..., HTTPException] = _plain_error


def _err(status: int, code: str, message: str, param: str | None = None) -> HTTPException:
    return error(status, code, message, param)


# ── the request bodies ───────────────────────────────────────────────────────────────────────────
class SessionBody(BaseModel):
    voice: str | None = None
    max_minutes: int | None = None
    max_cost_usd: float | None = None
    metadata: dict | None = None
    # function tools the caller's own page runs (creating a company by voice): put in the call's tools at the
    # mint, beside the harness's, and never run here (client_tools_of)
    client_tools: list | None = None


class ToolCallBody(BaseModel):
    call_id: str
    name: str
    arguments: str | dict = "{}"


# ── the provider interface ───────────────────────────────────────────────────────────────────────
@dataclasses.dataclass(frozen=True)
class CallSpec:
    """What a call is: the harness's instructions, its tools as function definitions, the voice, and
    how long it may last. Provider-neutral: every adapter takes the same one."""
    instructions: str
    tools: list[dict]
    voice: str
    max_minutes: int
    # for a provider that carries the call itself (runs_tools): the gateway's own ids for it, and the MCP
    # servers it reaches the call's tools at, each {name, url, headers}
    session_id: str = ""
    harness_id: str = ""
    harness_name: str = ""
    servers: tuple = ()


@dataclasses.dataclass(frozen=True)
class Minted:
    client_secret: str               # handed to the caller once, never stored or logged
    expires_at: float                # epoch seconds: the secret starts no call after this
    webrtc_url: str                  # where the device connects: its SDP offer (webrtc), or its socket (websocket)
    deployment: str
    model: str
    voice: str
    ref: dict = dataclasses.field(default_factory=dict)   # the provider's own ids for end/usage; no secret
    transport: str = "webrtc"        # how the device connects there


@dataclasses.dataclass(frozen=True)
class Usage:
    usd: float                       # what the call cost at the provider's price
    detail: dict = dataclasses.field(default_factory=dict)


class ProviderError(Exception):
    def __init__(self, status: int, text: str):
        super().__init__(text)
        self.status, self.text = status, text


class Provider(typing.Protocol):
    name: str
    # True: the provider carries the call and runs its tools itself, at the servers in the CallSpec. The tool
    # calls route then runs nothing for the call, and a caller's page tools cannot join it.
    runs_tools: bool

    async def mint(self, spec: CallSpec) -> Minted: ...

    async def end(self, ref: dict) -> None: ...

    async def usage(self, ref: dict) -> Usage | None: ...

    async def transcript(self, ref: dict) -> list[dict] | None:
        """The call's turns once it has ended, as response objects (input: what the person said, output: the
        model's tool calls and what it said); None from a provider that does not know."""


# ── Azure OpenAI ─────────────────────────────────────────────────────────────────────────────────
def azure_host(url: str) -> str:
    """The resource's host when `url` is one of Azure's AI endpoints over https, else ""."""
    try:
        u = urllib.parse.urlsplit((url or "").strip())
    except ValueError:
        return ""
    host = (u.hostname or "").lower()
    ok = u.scheme == "https" and any(host.endswith(h) and len(host) > len(h) for h in _AZURE_HOSTS)
    return host if ok else ""


_ENTRA_FIELDS = ("tenant_id", "client_id", "client_secret")


def signs_in_with_entra(cfg: dict) -> bool:
    return str((cfg or {}).get("auth") or "").strip().lower() == "entra"


def has_credential(cfg: dict) -> bool:
    """A key, or for a connection that signs in with Microsoft Entra its three sign-in fields."""
    if signs_in_with_entra(cfg):
        return all(str(cfg.get(f) or "").strip() for f in _ENTRA_FIELDS)
    return bool(str((cfg or {}).get("api_key") or "").strip())


def deployment_of(integ: dict, model: str, fallback: str = "") -> str:
    """The name of the deployment that serves `model` on this connection: the connection's own model
    row for it, else `fallback`, else the model's name."""
    for row in integ.get("models") or []:
        if isinstance(row, dict) and str(row.get("canonical") or "").strip() == model:
            pid = str(row.get("provider_id") or "").strip()
            if pid:
                return pid
    return fallback or model


def pick_integration(integrations: list[dict], name: str = "") -> dict | None:
    """The Azure OpenAI connection a call is minted on: the one named, else the first enabled Azure
    connection (`azure` or `azure-foundry`) with a credential and an Azure endpoint."""
    for integ in integrations or []:
        if not isinstance(integ, dict) or integ.get("enabled") is False:
            continue
        if name and str(integ.get("name") or "") != name:
            continue
        provider = str(integ.get("provider") or "").strip().lower()
        if provider not in ("azure", "azure-foundry"):
            continue
        cfg = integ.get("config") or {}
        if not has_credential(cfg):
            continue
        if azure_host(str(cfg.get("base_url") or "")):
            return integ
    return None


def session_body(spec: CallSpec, deployment: str, transcribe: str, ttl_s: int) -> dict:
    """The client-secret request (POST /openai/v1/realtime/client_secrets, GA, no api-version): the
    session the browser's call will run, fixed here so the browser cannot choose its own."""
    audio_in: dict = {"turn_detection": {"type": "server_vad", "create_response": True, "interrupt_response": True}}
    if transcribe:
        audio_in["transcription"] = {"model": transcribe}
    session: dict = {"type": "realtime", "model": deployment, "instructions": spec.instructions,
                     "output_modalities": ["audio"],
                     "audio": {"input": audio_in, "output": {"voice": spec.voice}}}
    if spec.tools:
        session["tools"] = spec.tools
        session["tool_choice"] = "auto"
    return {"expires_after": {"anchor": "created_at", "seconds": int(ttl_s)}, "session": session}


class AzureRealtime:
    """Azure OpenAI's realtime API on the instance's Azure OpenAI connection, read from the
    instance's connections at every mint (a rotated key is used at once). The key is sent to Azure's
    own hosts only, in the `api-key` header, and appears in no answer, record or line.

    A connection that signs in with Microsoft Entra holds no key. `sign_in` (the gateway's own, which
    keeps a token until it ages) turns the connection into a token, sent as a Bearer in the key's
    place. Without `sign_in` such a connection cannot be used and the mint says so."""

    name = "azure"
    runs_tools = False

    def __init__(self, integrations: typing.Callable[[], typing.Awaitable[list[dict]]], *, integration: str = "",
                 deployment: str = "", model: str = "", transcribe: str | None = None, ttl_s: int = 0,
                 sign_in: typing.Callable[[dict], typing.Awaitable[str]] | None = None):
        self._integrations = integrations
        self._sign_in = sign_in
        self.integration = integration or INTEGRATION
        self.deployment = deployment or DEPLOYMENT
        self.model = model or MODEL
        self.transcribe = TRANSCRIBE if transcribe is None else transcribe
        self.ttl_s = ttl_s or SECRET_TTL_S

    async def _conn(self) -> tuple[str, dict, str]:
        """The resource's host, the one credential header, and the deployment's name."""
        integ = pick_integration(await self._integrations(), self.integration)
        if not integ:
            raise ProviderError(503, NOT_SET_UP)
        cfg = integ.get("config") or {}
        host = azure_host(str(cfg.get("base_url") or ""))
        deployment = deployment_of(integ, self.model, self.deployment)
        if not signs_in_with_entra(cfg):
            return host, {"api-key": str(cfg.get("api_key") or "").strip()}, deployment
        if not self._sign_in:
            raise ProviderError(503, NOT_SET_UP)
        try:
            token = await self._sign_in({**cfg, "provider": integ.get("provider")})
        except HTTPException as e:
            # the gateway's sign-in words its own refusals for the person who fixes the connection,
            # and none of them carries the secret or a token
            raise ProviderError(503 if e.status_code == 401 else 502, str(e.detail)) from None
        return host, {"authorization": f"Bearer {token}"}, deployment

    async def mint(self, spec: CallSpec) -> Minted:
        host, credential, deployment = await self._conn()
        url = f"https://{host}/openai/v1/realtime/client_secrets"
        body = session_body(spec, deployment, self.transcribe, self.ttl_s)
        try:
            async with httpx.AsyncClient(transport=transport, timeout=15.0) as c:
                r = await c.post(url, json=body, headers={**credential, "content-type": "application/json"})
        except httpx.HTTPError as e:
            raise ProviderError(502, f"The voice service could not be reached ({type(e).__name__}).") from None
        if r.status_code >= 400:
            # Azure's own error code, never its body: a message can quote the request, never our key, but
            # what a caller needs is whether to try again
            try:
                code = str(((r.json() or {}).get("error") or {}).get("code") or "")[:64]
            except ValueError:
                code = ""
            raise ProviderError(502 if r.status_code >= 500 or r.status_code == 429 else 503,
                                f"The voice service refused to start the call (HTTP {r.status_code}"
                                + (f", {code}" if code else "") + ").")
        try:
            doc = r.json()
        except ValueError:
            doc = {}
        secret = str((doc or {}).get("value") or "")
        if not secret:
            raise ProviderError(502, "The voice service answered without a client secret.")
        try:
            expires = float(doc.get("expires_at") or 0) or clock() + self.ttl_s
        except (TypeError, ValueError):
            expires = clock() + self.ttl_s
        sess = doc.get("session") if isinstance(doc.get("session"), dict) else {}
        voice = str(((sess.get("audio") or {}).get("output") or {}).get("voice") or spec.voice)
        return Minted(client_secret=secret, expires_at=expires,
                      webrtc_url=f"https://{host}/openai/v1/realtime/calls",
                      deployment=deployment, model=self.model, voice=voice,
                      ref={"provider": self.name, "session": str(sess.get("id") or "")[:80]})

    async def end(self, ref: dict) -> None:
        # The call is addressed by the call id Azure gives the browser's SDP answer (its Location
        # header), which this gateway never sees: there is nothing here to hang up. The caller hangs up;
        # the record and the meter stop at max_minutes whatever it does.
        return None

    async def usage(self, ref: dict) -> Usage | None:
        # Azure reports a call's tokens in its `response.done` events, on the call's own channels; a server
        # reads them only through a sideband on the call id (above). Until then the clock meters.
        return None

    async def transcript(self, ref: dict) -> list[dict] | None:
        return None                      # what was said went between the browser and Azure


# ── a Realtime Harness ───────────────────────────────────────────────────────────────────────────
def tokens_usd(responses: list[dict]) -> tuple[float, dict] | None:
    """What a call's turns cost at USD_PER_M, and the tokens counted; None when no turn reported usage (the
    clock meters then: a figure is never made up from nothing).

    A turn's usage says how many input tokens were audio and how many were cached, not how many of the
    cached ones were audio. The cached ones are counted against the text first, the cheaper kind to lose,
    so the figure is never under what the provider charges for the same tokens."""
    seen = False
    t = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "input_audio_tokens": 0, "output_audio_tokens": 0}
    for r in responses or []:
        u = r.get("usage") if isinstance(r, dict) else None
        if not isinstance(u, dict):
            continue
        seen = True
        for k in t:
            try:
                t[k] += max(0, int(u.get(k) or 0))
            except (TypeError, ValueError):
                pass
    if not seen:
        return None
    audio_in = min(t["input_audio_tokens"], t["input_tokens"])
    text_in = t["input_tokens"] - audio_in
    cached = min(t["cache_read_tokens"], t["input_tokens"])
    cached_text = min(cached, text_in)
    cached_audio = cached - cached_text
    audio_out = min(t["output_audio_tokens"], t["output_tokens"])
    usd = ((text_in - cached_text) * USD_PER_M["text_in"] + (audio_in - cached_audio) * USD_PER_M["audio_in"]
           + cached * USD_PER_M["cached_in"] + (t["output_tokens"] - audio_out) * USD_PER_M["text_out"]
           + audio_out * USD_PER_M["audio_out"]) / 1_000_000
    return round(usd, 6), t


class HarnessRealtime:
    """A Realtime Harness (github.com/HarnessRouter/RealtimeHarness) that relays the call: the device talks to
    the harness, the harness to the provider. This gateway is the harness's operator: it creates each call
    there with the call's own configuration (the gateway harness's instructions and voice, the MCP servers
    the call's tools are reached at, how long it may last) and the call's own way to the provider (`upstream`:
    a URL on this gateway and a token good for that one call).

    `inner` is the provider that holds the key (AzureRealtime): the harness never does. `key` answers the
    operator key this gateway calls the harness with, read when asked and sent to the harness's own address
    only. `upstream` answers (url, token) for one call's id."""

    name = "harness"
    runs_tools = True

    def __init__(self, inner, *, key: typing.Callable[[], str],
                 upstream: typing.Callable[[str], tuple[str, str]], base: str = "", public: str = "", model: str = ""):
        self._inner, self._key, self._upstream = inner, key, upstream
        self.base = (base or HARNESS_URL).rstrip("/")
        self.public = (public or HARNESS_PUBLIC_URL).rstrip("/")
        self.model = model or MODEL

    async def _ask(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        key = (self._key() or "").strip()
        if not (self.base and self.public and key):
            raise ProviderError(503, HARNESS_NOT_SET_UP)
        try:
            async with httpx.AsyncClient(transport=transport, timeout=30.0) as c:
                r = await c.request(method, self.base + path, json=body,
                                    headers={"authorization": f"Bearer {key}", "content-type": "application/json"})
        except httpx.HTTPError as e:
            raise ProviderError(502, f"The voice service could not be reached ({type(e).__name__}).") from None
        try:
            doc = r.json()
        except ValueError:
            doc = {}
        return r.status_code, doc if isinstance(doc, dict) else {}

    async def mint(self, spec: CallSpec) -> Minted:
        url, token = self._upstream(spec.session_id)
        harness = {"id": spec.harness_id, "name": spec.harness_name or spec.harness_id,
                   "instructions": spec.instructions, "voice": spec.voice, "max_call_minutes": spec.max_minutes,
                   "mcp_servers": [dict(s) for s in spec.servers]}
        if TRANSCRIBE:
            harness["transcription_model"] = TRANSCRIBE
        status, doc = await self._ask("POST", "/v1/realtime/sessions", {
            "transport": "websocket", "model": self.model, "harness": harness, "upstream": {"url": url, "token": token}})
        connect = doc.get("connect") if isinstance(doc.get("connect"), dict) else {}
        secret, rid = str(connect.get("token") or ""), str(doc.get("id") or "")
        if status != 201 or not secret or not rid:
            # the harness's own error code, never its message: a message may quote the request
            code = str((doc.get("error") or {}).get("code") or "")[:64] if isinstance(doc.get("error"), dict) else ""
            raise ProviderError(502 if status >= 500 or status == 201 else 503,
                                f"The voice service refused to start the call (HTTP {status}" + (f", {code}" if code else "") + ").")
        try:
            expires = datetime.datetime.fromisoformat(str(connect.get("expires_at") or "").replace("Z", "+00:00")).timestamp()
        except ValueError:
            expires = clock() + 60
        return Minted(client_secret=secret, expires_at=expires, webrtc_url=f"{self.public}/v1/realtime/connect",
                      deployment=self.model, model=self.model, voice=spec.voice, transport="websocket",
                      ref={"provider": self.name, "session": rid[:80]})

    async def credential(self, voice: str) -> dict:
        """A provider credential for one connection of a relayed call, in the mint answer's shape. The session it
        is minted with says nothing: the harness sets the call's instructions and tools on the connection."""
        m = await self._inner.mint(CallSpec("", [], voice or DEFAULT_VOICE, 1))
        return {"client_secret": m.client_secret, "webrtc_url": m.webrtc_url, "deployment": m.deployment}

    async def _session(self, ref: dict) -> dict | None:
        rid = str((ref or {}).get("session") or "")
        if not rid:
            return None
        status, doc = await self._ask("GET", f"/v1/sessions/{urllib.parse.quote(rid)}")
        return doc if status == 200 else None

    async def end(self, ref: dict) -> None:
        rid = str((ref or {}).get("session") or "")
        if rid:
            await self._ask("POST", f"/v1/sessions/{urllib.parse.quote(rid)}/cancel")      # hangs up: the device's socket closes

    async def usage(self, ref: dict) -> Usage | None:
        """What the call's turns used. Three cases, told apart on purpose:

        - the harness's record of the call cannot be read: None, and the clock meters, so a call is never
          free because a read failed;
        - the record is read and holds no turn: nothing was said, the model generated nothing, and the call
          is billed nothing. (The clock billed such a call its whole length, more than one in which people
          talked: measured 2026-11-27, a silent minute $0.10 against a nine second exchange $0.0044.);
        - the record holds turns: their tokens, or None when not one of them reported usage."""
        doc = await self._session(ref)
        if doc is None:
            return None
        turns = [r for r in doc.get("responses") or [] if isinstance(r, dict)]
        if not turns and isinstance(doc.get("responses"), list):
            return Usage(0.0, {"tokens": {}, "turns": 0})
        priced = tokens_usd(turns)
        return Usage(priced[0], {"tokens": priced[1]}) if priced else None

    async def transcript(self, ref: dict) -> list[dict] | None:
        doc = await self._session(ref)
        if doc is None:
            return None
        return [r for r in doc.get("responses") or [] if isinstance(r, dict)]


# ── what a call is made of ───────────────────────────────────────────────────────────────────────
def instructions(system_prompt: str) -> str:
    base = (system_prompt or "").strip()
    return f"{base}\n\n{CALL_NOTE}" if base else CALL_NOTE


def function_tools(mcp_tools: list[dict]) -> list[dict]:
    """The plugs server's tools as the realtime API's function definitions, in its order: a name the API
    cannot take is left out, a long description is cut, at most MAX_TOOLS."""
    out: list[dict] = []
    for t in mcp_tools or []:
        if not isinstance(t, dict):
            continue
        name = str(t.get("name") or "")
        if not _TOOL_NAME.match(name) or any(f["name"] == name for f in out):
            continue
        params = t.get("inputSchema") if isinstance(t.get("inputSchema"), dict) else {}
        params = {k: v for k, v in params.items() if k != "$schema"} or {"type": "object", "properties": {}}
        params.setdefault("type", "object")
        out.append({"type": "function", "name": name,
                    "description": str(t.get("description") or "")[:DESC_MAX], "parameters": params})
        if len(out) >= MAX_TOOLS:
            break
    return out


def client_tools_of(raw: list | None) -> list[dict]:
    """The caller's page tools as function definitions: at most MAX_CLIENT_TOOLS, each named page_<name>, its
    parameters a JSON schema object. They are the caller's page's to run: the call's tool calls route never runs
    one (only the harness's plug tools are recorded as the call's). A session.update of `tools` from the browser
    replaces the whole list, the harness's tools with it, which is why they are put in at the mint."""
    if not raw:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_CLIENT_TOOLS:
        raise _err(422, "invalid_input", f"client_tools is a list of at most {MAX_CLIENT_TOOLS} function tools.",
                   "client_tools")
    out: list[dict] = []
    for t in raw:
        name = str((t or {}).get("name") or "") if isinstance(t, dict) else ""
        if not _CLIENT_TOOL_NAME.match(name) or any(f["name"] == name for f in out):
            raise _err(422, "invalid_input", "Each client tool has its own name, starting page_ (letters, digits, "
                                             "_ and -, at most 64).", "client_tools")
        if str(t.get("type") or "function") != "function":
            raise _err(422, "invalid_input", "A client tool is a function tool.", "client_tools")
        params = t.get("parameters") if t.get("parameters") is not None else {"type": "object", "properties": {}}
        if not isinstance(params, dict) or str(params.get("type") or "object") != "object" \
                or len(json.dumps(params)) > CLIENT_PARAMS_MAX:
            raise _err(422, "invalid_input", f"A client tool's parameters are a JSON schema object of at most "
                                             f"{CLIENT_PARAMS_MAX} characters.", "client_tools")
        out.append({"type": "function", "name": name, "description": str(t.get("description") or "")[:DESC_MAX],
                    "parameters": {"type": "object", **params}})
    return out


def voice_of(asked: str | None) -> str:
    v = (asked or "").strip().lower() or DEFAULT_VOICE
    if v not in VOICES:
        raise _err(422, "invalid_input", "voice is one of: " + ", ".join(VOICES) + ".", "voice")
    return v


def minutes_of(asked: int | None) -> int:
    if asked is None:
        return DEFAULT_MINUTES
    if asked < 1:
        raise _err(422, "invalid_input", "max_minutes is at least 1.", "max_minutes")
    return min(int(asked), MAX_MINUTES)


def cap_of(asked: float | None) -> float | None:
    if asked is None:
        return None
    if not asked > 0:
        raise _err(422, "invalid_input", "max_cost_usd is a positive dollar figure.", "max_cost_usd")
    return float(asked)


def meter(started: float, ended: float, max_minutes: float, rate: float, cap: float | None) -> tuple[float, float]:
    """(minutes, dollars) for a call: the minutes it was open, never more than its max_minutes, at the
    rate it was minted with, never more than its cap."""
    minutes = max(0.0, min(ended - started, max_minutes * 60.0)) / 60.0
    usd = minutes * rate
    if cap is not None:
        usd = min(usd, cap)
    return round(minutes, 3), round(usd, 6)


def parse_arguments(raw) -> dict | None:
    if isinstance(raw, dict):
        return raw
    try:
        doc = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def result_text(result: dict) -> str:
    parts = []
    for c in (result or {}).get("content") or []:
        if isinstance(c, dict) and c.get("type") == "text":
            parts.append(str(c.get("text") or ""))
        elif isinstance(c, dict):
            parts.append(f"[{c.get('type') or 'content'}]")
    return "\n".join(parts)[:OUTPUT_MAX]


def tool_answer(result: dict, parked: dict | None) -> dict:
    """The plugs server's answer to one call, in the contract's three words."""
    text = result_text(result)
    if parked:
        return {"status": "held", "approval_id": str(parked.get("run") or ""), "says": text}
    if (result or {}).get("isError"):
        return {"status": "refused", "detail": text or "The tool refused this call."}
    return {"status": "done", "output": text}


def _iso(t: float) -> str:
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _f(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def card_of(sid: str, rec: dict) -> dict:
    """The session's card in the harness's and the organization's session lists, from its record."""
    status = str(rec.get("status") or LIVE)
    minutes = rec.get("rt_minutes")
    return {"session_id": sid, "org_id": rec.get("tenant"), "tenant": rec.get("tenant"), "kind": KIND,
            "member_id": rec.get("member_id") or "", "started_by": rec.get("member_id") or "",
            "harness_id": rec.get("harness_id") or "", "harness_name": rec.get("harness_name") or "",
            "workspace": rec.get("workspace") or "", "task_ref": rec.get("task_ref") or "",
            "source": rec.get("source") or "", "backend": KIND, "model": rec.get("model") or "",
            "title": "Voice call", "user_prompt": "", "status": status, "trace_blob": rec.get("trace_blob"),
            "chunks": [], "finished_at": _f(rec.get("rt_ended_at")) or _f(rec.get("created_at")),
            "schema_version": 1, "usage": {}, "spend_usd": _f(rec.get("spend_usd")),
            "elapsed": round(_f(minutes) * 60.0, 1) if minutes not in (None, "") else None,
            "result": (f"Voice call, {_f(minutes):.1f} min" if status == ENDED else "")}




# ── what the gateway lends ───────────────────────────────────────────────────────────────────────
@dataclasses.dataclass
class Ports:
    # one MCP call on the harness's plugs server as the harness, for this session: (result, parked), where
    # parked is {"run": the consent run} when the call waits for a person's approval, else None
    plugs: typing.Callable[[str, str, str, dict], typing.Awaitable[tuple[dict, dict | None]]]
    put: typing.Callable[[str, dict], typing.Awaitable[bool]]          # session record fields (`tenant`: the create)
    get: typing.Callable[[str], typing.Awaitable[dict | None]]         # the record, or None; raises when unread
    card: typing.Callable[[str, dict], typing.Awaitable[None]]         # the card (card_of) in the session lists
    prefix: typing.Callable[[str, str, float], str]                    # the session's trace prefix, '{org}/{inv}_{sid}'
    reach: typing.Callable[[dict, dict], typing.Awaitable[bool]]       # the caller may use this session
    usage: typing.Callable[..., None]                                  # post usage, fire and forget
    lock: typing.Callable[[str, int], typing.Awaitable[bool]]          # one holder across replicas, for ttl seconds
    unlock: typing.Callable[[str], typing.Awaitable[None]]
    live: typing.Callable[[], typing.Awaitable[list[dict]]]            # every realtime record not yet metered (rt_open)
    # for a provider that carries the call (runs_tools). servers(harness, session): the MCP servers the call's
    # tools are reached at, [{name, url, headers}], with a credential for this harness and this call.
    # turns(session, record, responses): the ended call's turns, kept in the session's conversation.
    servers: typing.Callable[[str, str], typing.Awaitable[list[dict]]] | None = None
    turns: typing.Callable[[str, dict, list[dict]], typing.Awaitable[None]] | None = None


class Service:
    def __init__(self, provider: Provider, ports: Ports):
        self.provider, self.ports = provider, ports
        self._answers: dict[tuple[str, str], dict] = {}     # (session, call id): a retried call's answer

    # ── create ──
    async def create(self, p: dict, hid: str, hv: dict, body: SessionBody, acting_for: str = "") -> dict:
        org = str(p.get("org") or "")
        voice, minutes, cap = voice_of(body.voice), minutes_of(body.max_minutes), cap_of(body.max_cost_usd)
        page = client_tools_of(body.client_tools)
        relayed = bool(getattr(self.provider, "runs_tools", False))
        if page and relayed:
            raise _err(422, "invalid_input", "client_tools are not offered on this instance: its calls run on a "
                                             "harness, which runs a call's tools itself.", "client_tools")
        meta = body.metadata or {}
        sid = SID_PREFIX + uuid.uuid4().hex
        created = clock()
        member = str(p.get("member") or "")
        person = member if p.get("via") == "person" and member else ""
        prefix = self.ports.prefix(org, sid, created)
        rec = {"tenant": org, "kind": KIND, "status": "minting", "backend": KIND, "model": MODEL,
               "member_id": member, "person": person, "acting_for": acting_for,
               "source": "person" if person else "api" if p.get("via") == "api_key" else "",
               "harness_id": hid, "harness_name": str(hv.get("name") or ""),
               "workspace": str(hv.get("workspace") or ""), "task_ref": str(meta.get("task_ref") or "")[:120],
               # the harness's owner pays, as for a turn (and a harness runs only for its own organization)
               "billing_org": str(hv.get("org") or "") or org,
               "created_at": str(created), "created_at_inv": prefix.rsplit("/", 1)[-1].split("_", 1)[0],
               "trace_blob": prefix, "rt_max_minutes": str(minutes), "rt_deadline": str(created + minutes * 60),
               "rt_usd_per_min": repr(USD_PER_MIN), "rt_voice": voice, "spend_usd": "0.0",
               # "1" until the call is metered: what the sweep looks for, a deleted session's call included
               "rt_open": "1", "rt_provider": str(getattr(self.provider, "name", "")), "rt_relayed": "1" if relayed else "0",
               **({"rt_max_cost_usd": repr(cap)} if cap is not None else {})}
        # the record first: no call is minted that nothing would meter
        if not await self.ports.put(sid, rec):
            raise _err(503, "server_error", "The call could not be recorded just now, so it was not started.")
        try:
            listed, _ = await self.ports.plugs(hid, sid, "tools/list", {})
            tools = function_tools((listed or {}).get("tools") or [])[:MAX_TOOLS - len(page)]
            if any(t["name"] == c["name"] for t in tools for c in page):
                raise _err(422, "invalid_input", "A client tool has the name of one of the harness's tools.",
                           "client_tools")
            servers = await self.ports.servers(hid, sid) if relayed and self.ports.servers else []
            minted = await self.provider.mint(CallSpec(instructions(str(hv.get("system_prompt") or "")), tools + page,
                                                       voice, minutes, session_id=sid, harness_id=hid,
                                                       harness_name=str(hv.get("name") or ""), servers=tuple(servers)))
        except ProviderError as e:
            await self.ports.put(sid, {"status": "failed", "rt_open": "0", "rt_end_reason": "not started"})
            raise _err(e.status, "provider_error", e.text) from None
        except BaseException:
            await self.ports.put(sid, {"status": "failed", "rt_open": "0", "rt_end_reason": "not started"})
            raise
        names = [t["name"] for t in tools]
        # rt_tools: the tools the tool calls route may run, the harness's alone; page tools are only listed.
        # None for a relayed call: the harness runs them, at the plugs server, and that route runs nothing.
        live = {"status": LIVE, "rt_deployment": minted.deployment, "rt_voice": minted.voice,
                "rt_expires_at": str(minted.expires_at), "rt_tools": json.dumps([] if relayed else names),
                "rt_client_tools": json.dumps([c["name"] for c in page]),
                "rt_ref": json.dumps(minted.ref)}
        await self.ports.put(sid, live)
        rec.update(live)
        await self.ports.card(sid, rec)
        print(f"[realtime] started sid={sid} harness={hid} provider={self.provider.name} tools={len(names)} "
              f"max_minutes={minutes}", flush=True)
        return {"session_id": sid, "client_secret": minted.client_secret, "expires_at": _iso(minted.expires_at),
                "transport": minted.transport, "connect_url": minted.webrtc_url,
                **({"webrtc_url": minted.webrtc_url} if minted.transport == "webrtc" else {}),
                "deployment": minted.deployment, "voice": minted.voice,
                "tools": names, "client_tools": [c["name"] for c in page], "max_minutes": minutes}

    # ── a session the caller may use ──
    async def _own(self, p: dict, sid: str) -> dict:
        if not _SID_RE.match(sid or ""):
            raise _err(404, "session_not_found", "No session with that id.", "session_id")
        try:
            v = await self.ports.get(sid)
        except Exception:  # noqa: BLE001 — unread is not absent
            raise _err(503, "server_error", "The call could not be read just now. Try again.") from None
        if (not v or str(v.get("kind") or "") != KIND or str(v.get("tenant") or "") != str(p.get("org") or "")
                or str(v.get("status") or "") == "deleted" or not await self.ports.reach(p, v)):
            raise _err(404, "session_not_found", "No session with that id.", "session_id")
        return {**v, "id": sid}

    # ── tool calls ──
    async def tool_call(self, p: dict, sid: str, body: ToolCallBody) -> dict:
        v = await self._own(p, sid)
        if str(v.get("status")) != LIVE:
            return {"status": "refused", "detail": ENDED_DETAIL}
        if clock() >= _f(v.get("rt_deadline")):
            await self._finish(v, "max_minutes")
            return {"status": "refused", "detail": ENDED_DETAIL}
        if str(v.get("rt_relayed")) == "1":
            return {"status": "refused", "detail": "This call's tools are run by the harness that carries it."}
        try:
            offered = json.loads(v.get("rt_tools") or "[]")
        except ValueError:
            offered = []
        if body.name not in offered:
            return {"status": "refused", "detail": f"No tool named {body.name!r} in this call."}
        args = parse_arguments(body.arguments)
        if args is None:
            return {"status": "refused", "detail": "The arguments are not a JSON object."}
        key = (sid, str(body.call_id or "")[:200])
        if key[1] and key in self._answers:
            return self._answers[key]                    # a retried call on this replica: answered, never run again
        result, parked = await self.ports.plugs(str(v.get("harness_id") or ""), sid, "tools/call",
                                                {"name": body.name, "arguments": args})
        answer = tool_answer(result, parked)
        if key[1]:
            if len(self._answers) > 5000:
                self._answers.clear()
            self._answers[key] = answer
        return answer

    # ── a relayed call's way to the provider ──
    async def upstream(self, sid: str) -> dict:
        """A provider credential for one connection of a relayed call. The caller is the harness that carries
        the call, already checked by the route against the token made for this one call; this checks the call:
        relayed, live, within its time, and not asking more often than a call's connections can need."""
        credential = getattr(self.provider, "credential", None)
        try:
            v = await self.ports.get(sid) if _SID_RE.match(sid or "") else None
        except Exception:  # noqa: BLE001 — unread is not absent
            raise _err(503, "server_error", "The call could not be read just now. Try again.") from None
        if (credential is None or not v or str(v.get("kind") or "") != KIND or str(v.get("rt_relayed")) != "1"
                or str(v.get("status")) != LIVE or clock() >= _f(v.get("rt_deadline"))):
            raise _err(403, "call_ended", ENDED_DETAIL)
        asked = int(_f(v.get("rt_upstream")))
        if asked >= MAX_UPSTREAM_MINTS:
            raise _err(429, "rate_limited", "This call has been given every provider credential a call can need.")
        if not await self.ports.put(sid, {"rt_upstream": str(asked + 1)}):
            raise _err(503, "server_error", "The call could not be recorded just now. Try again.")
        try:
            return await credential(str(v.get("rt_voice") or ""))
        except ProviderError as e:
            raise _err(e.status, "provider_error", e.text) from None

    # ── the end ──
    async def end(self, p: dict, sid: str) -> dict:
        v = await self._own(p, sid)
        if str(v.get("status")) == ENDED:
            return {"minutes": _f(v.get("rt_minutes")), "spend_usd": _f(v.get("spend_usd"))}
        if str(v.get("status")) != LIVE:
            return {"minutes": 0.0, "spend_usd": 0.0}       # never started: nothing to meter
        return await self._finish(v, "max_minutes" if clock() >= _f(v.get("rt_deadline")) else "ended")

    async def _finish(self, v: dict, reason: str) -> dict:
        """End a live call once, whoever asks first (its caller, a tool call past its time, the sweep), on any
        replica: the claim decides who meters, and everyone else reads the figures it wrote."""
        sid = str(v["id"])
        claim = f"realtime-end::{sid}"
        try:
            mine = await self.ports.lock(claim, END_CLAIM_S)
        except Exception:  # noqa: BLE001 — the claim's store did not answer: nothing is metered twice, so nothing now
            raise _err(503, "server_error", "The call could not be ended just now. Try again.") from None
        if not mine:
            done = await self.ports.get(sid) or {}
            if str(done.get("status")) == ENDED:
                return {"minutes": _f(done.get("rt_minutes")), "spend_usd": _f(done.get("spend_usd"))}
            raise _err(409, "session_ending", "This call is being ended. Ask again in a moment.", "session_id")
        try:
            now = clock()
            cap = _f(v.get("rt_max_cost_usd")) if v.get("rt_max_cost_usd") not in (None, "") else None
            minutes, usd = meter(_f(v.get("created_at")), now, _f(v.get("rt_max_minutes"), DEFAULT_MINUTES),
                                 _f(v.get("rt_usd_per_min"), USD_PER_MIN), cap)
            try:
                ref = json.loads(v.get("rt_ref") or "{}")
            except ValueError:
                ref = {}
            turns: list[dict] | None = None
            billed = "clock"
            try:
                # the hang-up first: a provider that carries the call knows its last turn only once it is over
                await self.provider.end(ref)
            except Exception as e:  # noqa: BLE001 — the record and the meter stop whatever the provider does
                print(f"[realtime] provider end failed sid={sid}: {type(e).__name__}", flush=True)
            try:
                said = await self.provider.usage(ref)
                if said is not None:
                    usd = round(min(said.usd, cap) if cap is not None else said.usd, 6)
                    billed = "tokens"
                turns = await self.provider.transcript(ref)
            except Exception as e:  # noqa: BLE001 — the clock still meters
                print(f"[realtime] provider usage or transcript failed sid={sid}: {type(e).__name__}", flush=True)
            ended = {"status": ENDED, "rt_open": "0", "rt_ended_at": str(now), "rt_minutes": repr(minutes),
                     "spend_usd": repr(usd), "rt_end_reason": reason, "rt_billed_by": billed,
                     **({"rt_turns": str(len(turns))} if turns is not None else {})}
            if str(v.get("status")) != LIVE:
                ended.pop("status")                       # a session deleted or retired keeps its status; its call is billed
            await self.ports.put(sid, ended)
        except BaseException:
            await self.ports.unlock(claim)                # nothing was metered: the next asker ends it
            raise
        org = str(v.get("billing_org") or v.get("tenant") or "")
        self.ports.usage(org, METRIC, usd, workspace=str(v.get("workspace") or ""), task_id=sid,
                         harness_id=str(v.get("harness_id") or ""), title="Voice call",
                         harness_name=str(v.get("harness_name") or ""))
        try:
            await self.ports.card(sid, {**v, **ended})
        except Exception as e:  # noqa: BLE001 — the record is the truth; the list takes the next write
            print(f"[realtime] card not written sid={sid}: {type(e).__name__}", flush=True)
        # what was said, kept in the session's conversation: not for a session that is being deleted
        if turns and self.ports.turns and str(v.get("status")) == LIVE and reason != "deleted":
            try:
                await self.ports.turns(sid, {**v, **ended}, turns)
            except Exception as e:  # noqa: BLE001 — the call is ended and metered; its words are the loss
                print(f"[realtime] transcript not kept sid={sid}: {type(e).__name__}", flush=True)
        print(f"[realtime] ended sid={sid} reason={reason} minutes={minutes} usd={usd} billed_by={billed}"
              + (f" turns={len(turns)}" if turns is not None else ""), flush=True)
        return {"minutes": minutes, "spend_usd": usd}

    # ── calls nobody ended ──
    async def settle(self, sid: str, v: dict | None, reason: str) -> dict | None:
        """Meter a call that is still open now, for a reason other than its caller's end: its session is being
        deleted (the delete keeps only a marker, so this is the last moment its record can be read), or the
        sweep found it. A mint that never finished is closed with nothing to bill: its secret reached nobody.
        None when there was nothing to meter."""
        if not v or str(v.get("kind")) != KIND or str(v.get("rt_open")) != "1":
            return None
        status = str(v.get("status"))
        if status in ("minting", "failed"):
            await self.ports.put(sid, {"status": "failed", "rt_open": "0", "rt_end_reason": "not started"})
            return None
        past = clock() >= _f(v.get("rt_deadline"))
        return await self._finish({**v, "id": sid}, "max_minutes" if past else reason)

    async def sweep(self) -> int:
        """Meter every open call its caller will not end: one past its max_minutes (metered as max_minutes, the
        most it could have run on our side), one whose session left `live` some other way, and close a mint
        that never finished once its time is up."""
        n = 0
        for v in await self.ports.live():
            sid = str(v.get("id") or "")
            if not _SID_RE.match(sid):
                continue
            status, past = str(v.get("status")), clock() >= _f(v.get("rt_deadline"))
            if status in (LIVE, "minting") and not past:
                continue
            try:
                if await self.settle(sid, v, status or "closed"):
                    n += 1
            except HTTPException:
                pass                                       # another replica is ending it
        return n

    async def sweep_forever(self) -> None:
        while True:
            await asyncio.sleep(SWEEP_EVERY_S)
            try:
                if await self.ports.lock("realtime-sweep", SWEEP_EVERY_S - 5):
                    await self.sweep()
            except Exception as e:  # noqa: BLE001
                print(f"[realtime] sweep failed: {type(e).__name__}", flush=True)
