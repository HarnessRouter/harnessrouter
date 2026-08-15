"""Making a picture, a clip, a line of speech — and assembling them into one film.

Two callers, one engine, one place the provider key is resolved:

  * the `media` MCP server this gateway hosts, so an agent can ask for a CAPABILITY
    (text_to_video, text_to_image, …) and be told which model actually ran;
  * the routes a media app calls to read its canvas, poll its jobs and export a film.

WHAT NEVER LEAVES THIS PROCESS. The provider key is resolved from the integrations document
inside the gateway, at the moment of use. The runner never receives it (an agent gets a per-turn
capability, never a key), and neither does the browser. Same shape the database server already
uses, for the same reason: a sandbox runs a customer's agent with real bash and egress.

THE AGENT NEVER NAMES A MODEL. It names a capability; this module walks that capability's ordered
candidate list and returns the first one that can actually serve the request — provider connected,
parameters honourable, not watermarked unless asked, not quarantined by a recent billable failure —
and the caller reports which one it was. Four video models are listed and two of them are broken;
that is the whole reason this exists rather than a model id in a tool argument.

FIVE ENDPOINT SHAPES, all measured against the live account on 2026-08-15:

  video-generation   POST /video/generations -> task id; GET /video/generations/{id} to poll
  image-generation   POST /images/generations -> b64_json OR url (both occur)
  openai             POST /chat/completions -> choices[0].message.images[0].image_url.url
  gemini             POST /v1beta/models/{id}:generateContent -> inlineData parts
  audio-chat         POST /chat/completions with modalities -> message.audio.data (+ transcript)

"200 OK" IS NOT SUCCESS. A candidate has only run once its response carries an actual media
payload. google/gemini-3-pro-image-preview answers 200 with `parts: []` and bills ~1356 tokens;
it is excluded from every chain, and this rule exists so its siblings cannot do the same quietly.

NEVER FORWARD AN UNRECOGNISED PARAMETER. The relay ignores unknown fields and submits the job
anyway, so a typo costs a full-price generation. Each candidate declares `params`, and the request
builders emit nothing outside that set — see `build_submit`, which hands back exactly which
tunables it used so a test can assert the subset rather than trust the code.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import functools
import json
import math
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import time
import uuid

# ── errors ────────────────────────────────────────────────────────────────────────
class MediaError(Exception):
    """A failure with a sentence the agent can act on."""


class MediaRefused(MediaError):
    """The provider SAID NO: an HTTP error status at submit, or no answer at all. Retrying the
    candidate is free, so it is NOT quarantined — which is what lets the owner's preferred model
    sit at rank 1 through an outage and start working again the day the relay is fixed.

    A 200 IS NEVER THIS. It used to be, twice: a 200 whose body was not an object, and a 200 with
    no task id in it — whose own sentence read "the provider accepted the request but returned no
    task id". Both are the provider ANSWERING, which is the only evidence anyone has that it
    billed, and both were classified as free. One generate_video where every candidate answered
    that way walked the whole six-model chain, stood none of them down, and told the agent
    "nothing was charged". The line is the status code, because the status code is the only thing
    here that says whether the provider got as far as doing the work.
    """


class MediaEmpty(MediaError):
    """The provider answered 200 and returned no media. Billable, and therefore a failure that
    quarantines the candidate — this is the gemini-3-pro rule.

    "Returned no media" covers a body that is not the shape at all, not only an empty list in the
    right shape: `data: []` and a bare JSON array are the same event one container type apart, and
    charging one of them to the request and not the other is an accounting artefact.
    """


# ── the catalog ───────────────────────────────────────────────────────────────────
_CATALOG_PATH = os.environ.get("HR_MEDIA_CATALOG") or str(
    pathlib.Path(__file__).with_name("media_catalog.json"))

# How long a candidate that failed AFTER a task id existed is left out of the chain. A submit
# failure is free to retry and is never quarantined, which is exactly what lets the owner's
# preferred model sit permanently at rank 1 and start working the day the relay is fixed.
QUARANTINE_S = int(os.environ.get("HR_MEDIA_QUARANTINE_S", "1800"))
# The one blocking provider call. A synchronous shape renders inside it, so the ceiling is the
# slowest verified model (seedream-5.0-pro at 91 s) with room, not a round number.
SUBMIT_TIMEOUT_S = float(os.environ.get("HR_MEDIA_SUBMIT_TIMEOUT_S", "180"))
POLL_TIMEOUT_S = float(os.environ.get("HR_MEDIA_POLL_TIMEOUT_S", "30"))
# A body larger than this is not a clip anyone asked for; it is a memory incident.
MAX_BYTES = int(os.environ.get("HR_MEDIA_MAX_BYTES", str(128 * 1024 * 1024)))
# Nothing terminal after this and the job is failed with a sentence, rather than polled forever.
JOB_MAX_S = int(os.environ.get("HR_MEDIA_JOB_MAX_S", "1200"))
# Summed MEASURED spend per session. Exceeded, generate_* refuses and names both numbers.
SESSION_BUDGET_USD = float(os.environ.get("HR_MEDIA_SESSION_BUDGET_USD", "25"))

# What a caller may ask for on each shape, beyond the structural fields the shape itself needs.
# A candidate that declares none of its own is held to this — so "only whitelisted params are
# forwarded" is true for every entry in the file, including one added later without a `params`.
_SHAPE_TUNABLES = {
    "video-generation": ("prompt", "duration", "image", "mode", "size"),
    "image-generation": ("prompt", "n", "size", "image"),
    "openai": ("prompt", "image"),
    "gemini": ("prompt", "image"),
    "audio-chat": ("messages", "modalities", "audio", "stream"),
}


@functools.lru_cache(maxsize=1)
def catalog() -> dict:
    """The capability catalog, read from disk at first use.

    From disk rather than compiled in, for the same reason kits and skills are: a provider fixes
    a model or breaks one, and a table in source goes stale with nothing to say so.
    """
    try:
        doc = json.loads(pathlib.Path(_CATALOG_PATH).read_text())
    except Exception as e:  # noqa: BLE001
        print(f"[media] catalog at {_CATALOG_PATH} is unreadable ({e}) — no capability is "
              f"available until it is fixed", flush=True)
        return {"providers": {}, "capabilities": {}}
    caps = doc.get("capabilities") or {}
    n = sum(len(c.get("candidates") or []) for c in caps.values() if isinstance(c, dict))
    print(f"[media] catalog: {len(caps)} capabilities, {n} candidates", flush=True)
    return doc


def capability(name: str) -> dict:
    c = (catalog().get("capabilities") or {}).get(name)
    return c if isinstance(c, dict) else {}


def capability_names() -> list[str]:
    return [k for k in (catalog().get("capabilities") or {})]


def provider_meta(provider: str) -> dict:
    p = (catalog().get("providers") or {}).get(provider)
    return p if isinstance(p, dict) else {}


def declared_params(cand: dict) -> set[str]:
    """The tunables this candidate accepts. Its own list when it names one, the shape's otherwise —
    never "everything the caller sent"."""
    own = [str(p) for p in (cand.get("params") or [])]
    tunables = set(_SHAPE_TUNABLES.get(str(cand.get("shape") or ""), ()))
    return ({p for p in own if p in tunables} or tunables) if own else tunables


def estimated_usd(cand: dict) -> float | None:
    """What one unit costs, or None. Present ONLY where it was measured — a guessed price is
    worse than no price, because it is believed."""
    if not cand.get("quota_measured"):
        return None
    usd = cand.get("usd")
    return float(usd) if isinstance(usd, (int, float)) else None


def limits_of(cand: dict) -> dict:
    """What list_capabilities tells the agent about the model it would get. Only keys the
    candidate actually declares — an absent limit is absent, not a default someone invented."""
    out: dict = {}
    for k in ("durations_s", "duration_min_s", "duration_max_s", "durations_rejected_s",
              "duration_ignored", "duration_observed_s", "resolution", "min_pixels",
              "sizes_verified", "voices", "format", "latency_s", "output_mime"):
        if cand.get(k) is not None:
            out[k] = cand[k]
    if "accepts_input_image" in cand:
        out["accepts_input_image"] = bool(cand["accepts_input_image"])
    if cand.get("watermark"):
        out["watermark"] = True
    served = aspects_of(cand)
    if served:
        # Derived, never declared: the shapes fall out of the frame and the floor this entry
        # already records. A capability whose media has no shape at all (a line of speech) reports
        # no key, rather than an empty list that reads as "none of them".
        out["aspects"] = served
    return out


# ── chain selection ───────────────────────────────────────────────────────────────
def _fmt_s(x: float) -> str:
    return f"{int(x)}" if float(x).is_integer() else f"{x:g}"


_STOOD_DOWN = ("excluded", "unavailable")


def stood_down(cand: dict) -> str:
    """"" unless this candidate is stood down by something MEASURED about the model itself, in
    which case the sentence that says so.

    Asked before anything about this deployment — which providers are connected, what was asked
    for — because it is the more specific and more useful fact. "Background music needs a paid
    plan" names a fix; "nobody has connected that provider" does not, and it is the sentence the
    person reading it would have to get past first.

    TWO statuses stand a candidate down and only two. `broken` is deliberately NOT one of them: a
    model that fails at SUBMIT costs nothing to retry, and leaving it in the chain is precisely
    what let the owner's preferred video model start working again the day the relay's mapping was
    fixed — no code change, no cost, nobody watching. A rule that skipped everything marked broken
    would have made that recovery impossible and nobody would ever have known.
    """
    status = str(cand.get("status") or "")
    if status not in _STOOD_DOWN:
        return ""
    model = str(cand.get("model") or "?")
    reason = str(cand.get("reason") or cand.get("excluded_reason") or cand.get("error") or "")
    if status == "unavailable":
        return reason or f"{model} is not available in this deployment"
    return f"{model} is excluded: {reason or 'it fails silently'}"


def can_serve(cand: dict, params: dict) -> str:
    """"" when this candidate can honour the request, else the clause that says why not.

    PARAMETER FIT IS CHECKED BEFORE HEALTH, because a model that cannot render 8 seconds is not
    a fallback for one that can — it is a different film.
    """
    down = stood_down(cand)
    if down:
        return down
    model = str(cand.get("model") or "?")

    secs = params.get("seconds")
    if secs is not None:
        allowed = cand.get("durations_s")
        if isinstance(allowed, list) and allowed:
            if not any(abs(float(a) - float(secs)) < 1e-6 for a in allowed):
                return (f"{model} renders "
                        f"{' and '.join(_fmt_s(a) for a in allowed)} s only")
        # Durations this model was ASKED for and refused. A measured rejection, not a range
        # somebody inferred around it: the catalog claimed a 1 s floor and both kling models
        # answer 400 to a 1 s render, so the floor is gone and the measurement is here instead.
        rejected = cand.get("durations_rejected_s")
        if isinstance(rejected, list) and any(abs(float(a) - float(secs)) < 1e-6 for a in rejected):
            return f"{model} refuses a {_fmt_s(secs)} s render"
        lo, hi = cand.get("duration_min_s"), cand.get("duration_max_s")
        if lo is not None and float(secs) < float(lo):
            return f"{model} cannot render {_fmt_s(secs)} s (its shortest is {_fmt_s(lo)} s)"
        if hi is not None and float(secs) > float(hi):
            return f"{model} cannot render {_fmt_s(secs)} s (its longest is {_fmt_s(hi)} s)"

    if params.get("image") is not None and not cand.get("accepts_input_image"):
        # MiniMax and happyhorse IGNORE an input image and bill for a text-only clip. Skipping
        # them here is what stops image_to_video quietly becoming text_to_video.
        return f"{model} ignores an input image and would bill for a text-only render"

    size = params.get("size")
    if size and cand.get("min_pixels"):
        w, h = parse_size(str(size))
        if w and h and w * h < int(cand["min_pixels"]):
            return (f"{model} rejects anything under "
                    f"{int(cand['min_pixels']):,} px and {size} is smaller")

    aspect = params.get("aspect")
    if aspect and not aspect_size(cand, str(aspect)):
        # A CANDIDATE THAT CANNOT HOLD THE SHAPE IS SKIPPED LIKE ANY OTHER, and never quietly
        # substituted: returning a landscape clip for a 9:16 ask is the same class of defect as a
        # dashboard printing a number the database never returned. If the whole chain skips, the
        # tool refuses — see `refusal`, which is built out of these clauses.
        fixed = aspect_fixed(cand)
        if fixed != aspect:
            return (f"{model} only renders {fixed} ({cand.get('resolution')})" if fixed else
                    f"{model} cannot be told an aspect and what it returns was never measured")

    if cand.get("watermark") and not params.get("allow_watermark"):
        return f"{model} watermarks its output"

    voice = params.get("voice")
    if voice and cand.get("voices") and voice not in cand["voices"]:
        return f"{model} has no voice called {voice!r}"
    return ""


def resolve(cap_name: str, params: dict, connected: set[str],
            quarantined: dict[str, float] | None = None,
            exclude: frozenset[str] | set[str] = frozenset()) -> tuple[dict | None, list[str]]:
    """(candidate, skipped-clauses) — the first candidate that can actually serve this request.

    Declaration order, never re-sorted: the file is the preference, and a run-time sort would make
    "why did it pick that one" unanswerable. Nothing here issues a network call.

    `exclude` is what a chain that is already running passes back in: a candidate this job has
    ALREADY tried is not offered again, so advancing the chain is a loop over one function rather
    than a second, parallel walk of the same list.
    """
    cap = capability(cap_name)
    now = time.time()
    q = quarantined or {}
    skipped: list[str] = []
    for cand in cap.get("candidates") or []:
        if not isinstance(cand, dict):
            continue
        model = str(cand.get("model") or "?")
        if model in exclude:
            continue                       # already tried on this job; its error is in `attempts`
        down = stood_down(cand)
        if down:
            skipped.append(down)           # measured about the model; said before anything else
            continue
        provider = str(cand.get("provider") or "")
        if provider and provider not in connected:
            skipped.append(f"{model} needs a provider nobody has connected")
            continue
        why = can_serve(cand, params)
        if why:
            skipped.append(why)
            continue
        until = float(q.get(model) or 0)
        if until > now:
            mins = max(1, int((now - (until - QUARANTINE_S)) // 60) or 1)
            skipped.append(f"{model} failed {mins} minute{'s' if mins != 1 else ''} ago")
            continue
        return cand, skipped
    return None, skipped


def refusal(cap_name: str, skipped: list[str]) -> str:
    """The refusal, verbatim. The final clause is load-bearing: without it a model spends the
    rest of the turn trying to connect a provider itself.

    `instead` is the capability's own warning about the substitution a model would otherwise reach
    for — declared in the catalog beside the candidates, so the refusal is built from ONE place
    whatever the capability. It used to be a whole second refusal string that text_to_music alone
    was special-cased to return, which meant an empty candidate list and a hard-coded sentence
    could not disagree because only one of them was ever read.
    """
    cap = capability(cap_name)
    reason = ("; ".join(skipped) + "." if skipped
              else "No model is listed for it in this deployment.")
    out = (f"No model is available for {cap_name} right now. {reason}\n"
           f"Nothing was generated and nothing was charged.\n")
    if cap.get("instead"):
        out += f"{cap['instead']}\n"
    return out + ("Ask the person to connect a provider that can do this — you cannot connect one "
                  "yourself.")


_SIZE_RE = re.compile(r"^(\d{3,5})\s*[x*]\s*(\d{3,5})$", re.I)


def parse_size(size: str) -> tuple[int, int]:
    m = _SIZE_RE.match((size or "").strip())
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


# ── the aspect ────────────────────────────────────────────────────────────────────
# AN ASPECT IS A SIZE, everywhere in this catalog. Nothing here honours an `aspect_ratio` field —
# MiniMax is measured ignoring one and billing anyway — so the only lever any candidate has is the
# `size` parameter it already declares, and there is no new per-candidate key for aspects at all.
# Three facts already in the file answer the whole question:
#
#   `params` lists `size`   -> it can be TOLD a shape. That list is this file's statement of which
#                              tunables a model honours; MiniMax's deliberately omits `size` and
#                              says why in its note, so reading that list IS reading a measurement.
#   `resolution` and no     -> it IS one shape and cannot be told another. Its aspect is arithmetic
#   `size` in params           on a frame that was already measured, never a second hand-written
#                              field that could disagree with the first.
#   neither                 -> UNKNOWN. Skipped when an aspect is asked for, because "we did not
#                              measure it" and "it will be fine" are not the same sentence.
_ASPECTS = {"16:9": (16, 9), "9:16": (9, 16), "1:1": (1, 1)}

# How far a measured frame may sit from a label and still wear it. 1366x768 — MiniMax's measured
# output — is 1.7786 against 16:9's 1.7778, the standard near-16:9 panel, 0.05% out. Written as a
# number rather than left implicit because the alternative is either calling that frame something
# it is not, or refusing a request every display in the world would answer.
_ASPECT_TOL = 0.01

# Frame dimensions are built as a multiple of this. Every ratio in `_ASPECTS` then comes out even
# on both edges, which is what h.264 requires — a computed 1443x2565 would be refused by the
# encoder at export, one step away from where it was chosen.
_ASPECT_STEP = 8


def aspect_label(w: int, h: int) -> str:
    """The label a w×h frame wears, or "" when it wears none of them."""
    if not w or not h:
        return ""
    r = float(w) / float(h)
    for name, (rw, rh) in _ASPECTS.items():
        want = rw / rh
        if abs(r - want) <= _ASPECT_TOL * want:
            return name
    return ""


def aspect_fixed(cand: dict) -> str:
    """The one shape this candidate always produces, when it cannot be told another — "" if it can
    be told, or if nothing measured says what it returns.

    A candidate that takes a `size` gets "" even though it has a `resolution`: that number is its
    default, not a fixture, and reading a default as a limit would skip a model that can do the
    job.
    """
    if "size" in declared_params(cand):
        return ""
    return aspect_label(*parse_size(str(cand.get("resolution") or "")))


def aspect_size(cand: dict, aspect: str) -> str:
    """The size to ASK this candidate for so the frame comes back `aspect` — "" when it cannot be
    told a size at all, or when nothing in its entry says what size to ask for.

    Built out of that model's own numbers: a size it has been verified at when one is the right
    shape, otherwise the smallest frame of that shape clearing its own floor. The formula
    reproduces seedream-4.5's verified 1920x1920 at 1:1 and lands exactly on its 3,686,400 px
    minimum at 16:9 — which is the point. It is arithmetic on measurements, not a table typed by
    hand, so a model whose limits are corrected in the catalog is corrected here too.

    NOTHING IS INVENTED when there is no basis. A candidate that takes a size and records neither
    a floor, nor a verified size, nor a resolution gets "" and is skipped — a guessed frame is the
    same defect as a guessed price.
    """
    ratio = _ASPECTS.get(aspect)
    if not ratio or "size" not in declared_params(cand):
        return ""
    rw, rh = ratio
    target = int(cand.get("min_pixels") or 0)
    for s in cand.get("sizes_verified") or []:
        w, h = parse_size(str(s))
        if aspect_label(w, h) == aspect:
            return f"{w}x{h}"        # measured at this shape: ask for exactly what was verified
        target = max(target, w * h)  # wrong shape, but it still says what scale this model works at
    if not target:
        w, h = parse_size(str(cand.get("resolution") or ""))
        target = w * h
    if not target:
        return ""
    k = math.ceil(math.sqrt(target / float(rw * rh)))
    k = -(-k // _ASPECT_STEP) * _ASPECT_STEP
    return f"{rw * k}x{rh * k}"


def aspects_of(cand: dict) -> list[str]:
    """Every shape this candidate can actually deliver. What `list_capabilities` reports, so an
    agent planning a vertical film learns it cannot have one BEFORE it spends four minutes."""
    return [a for a in _ASPECTS if aspect_size(cand, a) or aspect_fixed(cand) == a]


def size_for(cand: dict, params: dict) -> str:
    """The size this candidate will be ASKED for — "" when it is told none at all.

    THE ONE PLACE that answer is computed, so what the submit carries and what the tool reports
    back afterwards cannot disagree. A tool that prints `size: 1024x1024` beside a model whose
    params are ["prompt"] is printing a number the provider never received.
    """
    if "size" not in declared_params(cand):
        return ""
    return str(params.get("size") or aspect_size(cand, str(params.get("aspect") or "")) or "")


# ── the five adapters: building a request ─────────────────────────────────────────
class Submit:
    """One outbound request, plus exactly which tunables it carried.

    `tunables` is not decoration: it is how "only whitelisted params are forwarded" is asserted
    rather than believed. Structural fields (model, messages, contents) are the shape's own and
    are not tunables — a caller cannot influence them.
    """

    __slots__ = ("method", "url", "body", "tunables", "stream", "timeout")

    def __init__(self, method: str, url: str, body: dict, tunables: dict,
                 stream: bool = False, timeout: float = SUBMIT_TIMEOUT_S):
        self.method, self.url, self.body = method, url, body
        self.tunables, self.stream, self.timeout = tunables, stream, timeout

    def __repr__(self) -> str:      # pragma: no cover - debugging aid
        return f"<Submit {self.method} {self.url} tunables={sorted(self.tunables)}>"


def _timeout_for(cand: dict) -> float:
    """A synchronous shape renders inside the submit, so its budget is its measured latency with
    room — not one number for a 4-second model and a 91-second one."""
    lat = cand.get("latency_s")
    if str(cand.get("shape")) == "video-generation" or not isinstance(lat, (int, float)):
        return min(SUBMIT_TIMEOUT_S, 120.0)
    return min(SUBMIT_TIMEOUT_S, max(60.0, float(lat) * 3.0))


def _api_root(base: str) -> str:
    """The provider's API root, for the one shape whose path is not `/v1` relative.

    The configured base carries the `/v1` every other shape needs, so it is right to keep it there
    and strip it HERE rather than store a second base_url that could drift out of step with it.
    """
    return base[:-3].rstrip("/") if base.endswith("/v1") else base


def build_submit(cand: dict, base_url: str, params: dict) -> Submit:
    """The request that starts this generation. Nothing outside `declared_params(cand)` is sent."""
    shape = str(cand.get("shape") or "")
    model = str(cand.get("model") or "")
    allow = declared_params(cand)
    base = (base_url or "").rstrip("/")
    tun: dict = {}

    def take(name: str, value):
        if value is None or name not in allow:
            return None
        tun[name] = value
        return value

    # The caller's own size, or the one that expresses the aspect it asked for — per candidate,
    # because the walk may end on a different model than it started at and each one is asked in
    # its own numbers. `None` where this candidate takes no size, so `take` drops it.
    asked_size = size_for(cand, params) or None

    if shape == "video-generation":
        body: dict = {"model": model, "extra_body": {}}
        prompt = take("prompt", params.get("prompt"))
        if prompt is not None:
            body["prompt"] = prompt
        secs = take("duration", params.get("seconds"))
        if secs is not None:
            # An integer where it is one: the relay round-trips 6.0 as "6.0" and one model reads
            # that as a float it does not offer.
            body["duration"] = int(secs) if float(secs).is_integer() else float(secs)
        img = take("image", params.get("image"))
        if img is not None:
            body[str(cand.get("input_image_param") or "image")] = img
        mode = take("mode", params.get("mode"))
        if mode is not None:
            body["mode"] = mode
        size = take("size", asked_size)
        if size is not None:
            body["size"] = (size.replace("x", "*") if cand.get("size_format") == "W*H"
                            else size)
        return Submit("POST", f"{base}/video/generations", body, tun, timeout=_timeout_for(cand))

    if shape == "image-generation":
        body = {"model": model}
        prompt = take("prompt", params.get("prompt"))
        if prompt is not None:
            body["prompt"] = prompt
        if "n" in allow:
            tun["n"] = 1
            body["n"] = 1
        size = take("size", asked_size)
        if size is not None:
            body["size"] = size
        img = take("image", params.get("image"))
        if img is not None:
            body["image"] = img
        return Submit("POST", f"{base}/images/generations", body, tun, timeout=_timeout_for(cand))

    if shape == "openai":
        content: list = []
        prompt = take("prompt", params.get("prompt"))
        if prompt is not None:
            content.append({"type": "text", "text": prompt})
        img = take("image", params.get("image"))
        if img is not None:
            content.append({"type": "image_url",
                            "image_url": {"url": _data_uri(img, params.get("image_mime"))}})
        body = {"model": model, "messages": [{"role": "user", "content": content}]}
        return Submit("POST", f"{base}/chat/completions", body, tun, timeout=_timeout_for(cand))

    if shape == "gemini":
        parts: list = []
        prompt = take("prompt", params.get("prompt"))
        if prompt is not None:
            parts.append({"text": prompt})
        img = take("image", params.get("image"))
        if img is not None:
            parts.append({"inlineData": {"mimeType": params.get("image_mime") or "image/png",
                                         "data": img}})
        body = {"contents": [{"parts": parts}]}
        # THE FULL ID, `google/` prefix and all: the bare name answers 503. Measured.
        # `/v1beta` hangs off the API ROOT, not off `/v1` — the other four shapes are `/v1`
        # relative, this one is not. Measured 2026-08-15 with a model id that does not exist, so
        # the difference is the ROUTE and not the model:
        #   …/v1/v1beta/models/{id}:generateContent -> 404 "Invalid URL"     (the path is wrong)
        #   …/v1beta/models/{id}:generateContent    -> 503 model_not_found   (the path is right)
        # Concatenating onto the configured base silently killed both Gemini image models, and the
        # chain fell through to a model 5x slower and priced per image — a failure that LOOKS like
        # success because a picture still comes back.
        return Submit("POST", f"{_api_root(base)}/v1beta/models/{model}:generateContent", body, tun,
                      timeout=_timeout_for(cand))

    if shape == "audio-chat":
        text = params.get("prompt") or ""
        body = {"model": model,
                "messages": [{"role": "user", "content": text}]}
        if "modalities" in allow:
            tun["modalities"] = ["text", "audio"]
            body["modalities"] = ["text", "audio"]
        if "audio" in allow:
            aud = {"voice": params.get("voice") or "alloy",
                   "format": str(cand.get("format") or "wav")}
            tun["audio"] = aud
            body["audio"] = aud
        stream = bool(cand.get("stream_required")) and "stream" in allow
        if stream:
            tun["stream"] = True
            body["stream"] = True
        tun["messages"] = body["messages"]
        return Submit("POST", f"{base}/chat/completions", body, tun, stream=stream,
                      timeout=_timeout_for(cand))

    raise MediaError(f"No adapter for endpoint shape {shape!r}.")


def build_poll(cand: dict, base_url: str, task_id: str) -> tuple[str, str]:
    if str(cand.get("shape")) != "video-generation":
        raise MediaError("Only the video shape is polled; every other shape answers inline.")
    return "GET", f"{(base_url or '').rstrip('/')}/video/generations/{task_id}"


# ── the five adapters: reading a response ─────────────────────────────────────────
class Payload:
    """Media that actually arrived: bytes in hand, or a URL to fetch them from."""

    __slots__ = ("data", "url", "mime", "transcript")

    def __init__(self, data: bytes | None = None, url: str = "", mime: str = "",
                 transcript: str = ""):
        self.data, self.url, self.mime, self.transcript = data, url, mime, transcript


def _b64(s: str) -> bytes:
    try:
        return base64.b64decode(s, validate=False)
    except (binascii.Error, ValueError) as e:
        raise MediaEmpty("the provider returned something that is not base64") from e


def _data_uri(b64_or_uri: str, mime: str | None) -> str:
    s = b64_or_uri or ""
    return s if s.startswith("data:") else f"data:{mime or 'image/png'};base64,{s}"


def _from_data_uri(uri: str) -> tuple[bytes, str]:
    head, _, tail = uri.partition(",")
    mime = head[5:].split(";")[0] if head.startswith("data:") else "application/octet-stream"
    return _b64(tail), mime


def read_submit(cand: dict, status: int, doc) -> tuple[str, Payload | None]:
    """(task_id, payload) for a submit response, with every credential the provider wrote into it
    removed. The reading is `_read_submit`; the removal is `_clean`, which is the same one rule
    every reader here is wrapped in."""
    return _clean(_read_submit(cand, status, doc))


def _read_submit(cand: dict, status: int, doc) -> tuple[str, Payload | None]:
    """(task_id, payload) for a submit response.

    A shape that answers with a task id returns ("task_…", None). A synchronous shape returns
    ("", payload). Anything else raises — and WHICH exception decides whether the candidate is
    quarantined, so the distinction is the point. ONE QUESTION DECIDES IT, asked once, here:
    DID THE PROVIDER ANSWER?
      MediaRefused  a status of 400 or worse: it said no, nothing ran, retry is free.
      MediaEmpty    a 200 that carried no media: it answered, so it billed — stand it down.
    Every shape below therefore raises MediaEmpty, whatever is wrong with the body: 200 is the
    line, and "which particular way the 200 was useless" is a sentence, not a policy.
    """
    if status >= 400:
        raise MediaRefused(provider_message(doc, status))
    if not isinstance(doc, dict):
        raise MediaEmpty("the provider answered with a body that is not an object")
    shape = str(cand.get("shape") or "")

    if shape == "video-generation":
        tid = str(doc.get("task_id") or doc.get("id") or "")
        if not tid:
            raise MediaEmpty(provider_message(doc, status) or
                             "the provider accepted the request but returned no task id")
        return tid, None

    if shape == "image-generation":
        items = doc.get("data")
        first = items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else {}
        if first.get("b64_json"):
            return "", Payload(data=_b64(str(first["b64_json"])), mime="image/png")
        if first.get("url"):
            return "", Payload(url=str(first["url"]))
        raise MediaEmpty("the provider answered with no image")

    if shape == "openai":
        msg = _first_message(doc)
        images = msg.get("images")
        if isinstance(images, list):
            for im in images:
                url = ((im or {}).get("image_url") or {}).get("url") if isinstance(im, dict) else ""
                if url and str(url).startswith("data:"):
                    data, mime = _from_data_uri(str(url))
                    return "", Payload(data=data, mime=mime)
                if url:
                    return "", Payload(url=str(url))
        raise MediaEmpty("the provider answered with text and no image")

    if shape == "gemini":
        cands = doc.get("candidates")
        parts = []
        if isinstance(cands, list) and cands and isinstance(cands[0], dict):
            parts = ((cands[0].get("content") or {}).get("parts")) or []
        for p in parts if isinstance(parts, list) else []:
            # The ~1 MB thoughtSignature part sits beside the picture and is not one.
            inline = (p or {}).get("inlineData") if isinstance(p, dict) else None
            if isinstance(inline, dict) and inline.get("data"):
                return "", Payload(data=_b64(str(inline["data"])),
                                   mime=str(inline.get("mimeType") or "image/png"))
        raise MediaEmpty("the provider answered 200 with no image part — it billed and returned "
                         "nothing")

    if shape == "audio-chat":
        msg = _first_message(doc)
        audio = msg.get("audio") if isinstance(msg, dict) else None
        if isinstance(audio, dict) and audio.get("data"):
            fmt = str(cand.get("format") or "wav")
            return "", Payload(data=_b64(str(audio["data"])), mime=f"audio/{fmt}",
                               transcript=str(audio.get("transcript") or ""))
        raise MediaEmpty("the provider answered with no audio")

    raise MediaError(f"No adapter for endpoint shape {shape!r}.")


def read_stream_audio(cand: dict, chunks: list[str]) -> Payload:
    """The streamed audio, scrubbed of credentials — see `_clean`."""
    return _clean(_read_stream_audio(cand, chunks))


def _read_stream_audio(cand: dict, chunks: list[str]) -> Payload:
    """gpt-audio refuses without stream:true, and then delivers its audio in deltas that have to
    be concatenated. Both halves are the model's, not ours."""
    b64_parts: list[str] = []
    transcript: list[str] = []
    for raw in chunks:
        line = raw.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            ev = json.loads(payload)
        except Exception:  # noqa: BLE001 — a keepalive or a partial frame is not an error
            continue
        for ch in (ev.get("choices") or []):
            delta = (ch or {}).get("delta") or {}
            aud = delta.get("audio") or {}
            if isinstance(aud, dict):
                if aud.get("data"):
                    b64_parts.append(str(aud["data"]))
                if aud.get("transcript"):
                    transcript.append(str(aud["transcript"]))
    if not b64_parts:
        raise MediaEmpty("the provider streamed no audio")
    fmt = str(cand.get("format") or "wav")
    return Payload(data=_b64("".join(b64_parts)), mime=f"audio/{fmt}",
                   transcript="".join(transcript))


# The provider's own vocabulary for a video job, plus everything that is not terminal.
_VIDEO_RUNNING = {"NOT_START", "SUBMITTED", "IN_PROGRESS", "QUEUED", "PROCESSING", "RUNNING"}


def read_poll(cand: dict, status: int, doc) -> tuple[str, Payload | None, str, str]:
    """One poll, scrubbed of credentials — see `_clean`. `progress` is as much the provider's
    prose as `error` is, and it is written to the job vertex and served to the browser."""
    return _clean(_read_poll(cand, status, doc))


def _read_poll(cand: dict, status: int, doc) -> tuple[str, Payload | None, str, str]:
    """(status, payload, error, progress) for one poll.

    Four statuses and no more: running | succeeded | failed | unknown. `unknown` IS NEVER
    TERMINAL — an empty record is the known background-response race, and reading it as failure
    is how a finished render gets thrown away.
    """
    if status >= 500 or not isinstance(doc, dict) or not doc:
        return "unknown", None, "", ""
    data = doc.get("data")
    if not isinstance(data, dict) or not data:
        if status >= 400:
            return "failed", None, provider_message(doc, status), ""
        return "unknown", None, "", ""
    st = str(data.get("status") or "").upper()
    progress = str(data.get("progress") or "")
    if st == "SUCCESS":
        url = str(data.get("result_url") or data.get("video_url") or data.get("url") or "")
        if url:
            return "succeeded", Payload(url=url), "", progress
        # SUCCESS with nothing in it is a failure. Same rule as a 200 with no payload.
        return "failed", None, "the provider reported success and returned no video", progress
    if st == "FAILURE":
        return "failed", None, scrub(str(data.get("message") or data.get("error") or "")
                                     or "the render failed upstream"), progress
    if st in _VIDEO_RUNNING or not st:
        return "running", None, "", progress
    return "unknown", None, "", progress


def _first_message(doc: dict) -> dict:
    ch = doc.get("choices")
    if isinstance(ch, list) and ch and isinstance(ch[0], dict):
        m = ch[0].get("message")
        if isinstance(m, dict):
            return m
    return {}


# ── the provider's own words, minus the credential in them ────────────────────────
# A 401 is the one answer guaranteed to quote the key back at you: OpenAI's is literally
# `Incorrect API key provided: sk-…`. That sentence is relayed to a sandbox, written onto a job
# vertex and served to a browser, so it is scrubbed HERE — where a provider's words first become
# one of our strings — and not at those three exits. An exit added later gets it for free; a
# scrub at each exit is three places to remember and one to forget.
_SECRETS: set[str] = set()
_REDACTED = "[redacted]"


def remember_secret(value: str) -> None:
    """A credential this process sends out, and must therefore never relay back.

    Registered where the key is resolved (one place), so scrubbing is an exact replacement and not
    only a guess at what a credential looks like. Short strings are ignored: redacting those would
    blank ordinary words out of a diagnosis.
    """
    s = (value or "").strip()
    if len(s) >= 12:
        _SECRETS.add(s)


_SECRET_SHAPES = (
    # A token with a recognisable prefix and a separator: sk-…, sk_live_…, ghp_…, xoxb-….
    # The 8-character tail is what keeps "api-version", "key-value" and "secret-manager" intact.
    (re.compile(r"(?i)\b(?:sk|pk|rk|ak|api|apikey|key|token|tok|secret|ghp|gho|ghs|xox[abprs])"
                r"[-_][A-Za-z0-9][A-Za-z0-9\-_.]{7,}"), _REDACTED),
    (re.compile(r"(?i)\bAIza[0-9A-Za-z\-_]{20,}"), _REDACTED),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), _REDACTED),
    # A bearer the provider quoted back at us, in a sentence or in a curl line.
    (re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9\-._~+/=]{12,}"), r"\1" + _REDACTED),
    # Credentials in a URL: the userinfo, and the query parameters that carry a signature.
    (re.compile(r"(?<=://)[^\s/@:]+:[^\s/@]+(?=@)"), _REDACTED),
    (re.compile(r"(?i)([?&](?:api[-_]?key|key|token|access[-_]?token|sig|signature|password|"
                r"secret)=)[^&\s\"']+"), r"\1" + _REDACTED),
    # Not a credential, but it names the account being billed.
    (re.compile(r"(?i)\borg[-_][A-Za-z0-9]{6,}"), _REDACTED),
)


def scrub(text: str) -> str:
    """A provider sentence with every credential in it removed, and the diagnosis left standing.

    Exact first — the keys this deployment actually sends — then by shape, because a provider also
    says other people's tokens, its own bearer and an org id out loud, and a redaction that only
    knows our own string only ever catches the leak we already found.

    WHAT THIS GUARANTEES, AND WHERE IT STOPS. The exact half is a guarantee: a credential THIS
    DEPLOYMENT sends is removed from anywhere in a provider document, error field or not. The
    shape half is a net, not a guarantee — `hf_`, `xai-`, `gsk_`, `r8_`, `nvapi-`, a bare hex
    string and a JWT are not in the list, so a THIRD PARTY's token quoted in a field nobody treats
    as an error (a progress string, a transcript) can survive. The list is deliberately not grown
    to cover every vendor's prefix: a provider's task id is made of the same characters, and this
    same function cleans the task id we poll with — a redaction that eats one is a render nobody
    can ever collect. Widening it means proving that first. See the test that pins both halves.
    """
    out = str(text or "")
    for secret in _SECRETS:
        if secret in out:
            out = out.replace(secret, _REDACTED)
    for pattern, replacement in _SECRET_SHAPES:
        out = pattern.sub(replacement, out)
    return out


# The two Payload fields that are NOT the provider talking. `data` is the media itself. `url` is
# the ADDRESS the media is fetched from, and a kling or seedream result_url is signed — its query
# string is a credential, so redacting it would lose every render and protect nobody: that URL is
# fetched once and is never persisted or relayed (see app._media_fetch, and the test that asserts
# the provider URL never reaches disk).
_PAYLOAD_VERBATIM = ("data", "url")


def _clean(value):
    """A value we have just made our own out of a provider's document, with every credential the
    provider wrote into it removed — ONCE, here, rather than once per field.

    The first round of this scrubbed `provider_message` and the FAILURE branch of a poll. The very
    same document then walked out through `progress`, through the provider-chosen task id and
    through an audio transcript — each of them written to the job vertex, served to the browser and
    handed to the agent. Scrubbing a field at a time only ever covers the leak already found, so
    every reader in this file returns through here instead: a field added to Payload, or a fifth
    element added to a poll's tuple, is covered without anyone remembering.

    A scrubbed task id is a task id that cannot be polled, and that is the deliberate trade: an
    identifier shaped exactly like a credential is one we cannot tell from a credential, and a
    render that fails loudly is better than a key on disk.
    """
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, tuple):
        return tuple(_clean(v) for v in value)
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, Payload):
        for name in Payload.__slots__:
            if name not in _PAYLOAD_VERBATIM:
                setattr(value, name, _clean(getattr(value, name)))
    return value


def provider_message(doc, status: int) -> str:
    """The provider's own sentence, which is what the agent needs — never our paraphrase of it.
    Scrubbed of credentials, which is not a paraphrase: everything that diagnoses survives."""
    if isinstance(doc, dict):
        for key in ("message", "error", "detail", "msg"):
            v = doc.get(key)
            if isinstance(v, str) and v.strip():
                return scrub(v.strip())
            if isinstance(v, dict):
                for k2 in ("message", "detail", "msg"):
                    if isinstance(v.get(k2), str) and v[k2].strip():
                        return scrub(str(v[k2]).strip())
        if isinstance(doc.get("code"), str) and doc["code"] and doc["code"] != "success":
            return scrub(str(doc["code"]))
    return f"the provider answered HTTP {status}"


def usage_usd(doc) -> float | None:
    """A cost the provider reported inline (mai-image-2.5 does). Measured, so it may be believed;
    absent otherwise, and never estimated."""
    if not isinstance(doc, dict):
        return None
    u = doc.get("usage")
    if isinstance(u, dict) and isinstance(u.get("cost"), (int, float)):
        return float(u["cost"])
    return None


# ── verifying what came back is media ─────────────────────────────────────────────
_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"GIF8", "image/gif", "gif"),
    (b"RIFF", "", ""),                    # wav or webp — decided below
    (b"OggS", "audio/ogg", "ogg"),
    (b"ID3", "audio/mpeg", "mp3"),
    (b"\xff\xfb", "audio/mpeg", "mp3"),   # a bare MPEG frame, no ID3 tag in front of it
    (b"\x1a\x45\xdf\xa3", "video/webm", "webm"),
)


def sniff(data: bytes) -> tuple[str, str]:
    """(mime, extension) FROM THE BYTES, or ("", "") when they identify nothing.

    The provider's content-type is a claim, not evidence, and it is never consulted here. That is
    the whole point: an HTML error page served as `image/png` is exactly what a hint-trusting
    sniffer stores as a picture, and the element then reads as ready and shows nothing.
    """
    head = data[:16]
    if head[4:8] == b"ftyp":
        brand = bytes(head[8:12])
        return ("video/quicktime", "mov") if brand.startswith(b"qt") else ("video/mp4", "mp4")
    for magic, mime, ext in _MAGIC:
        if not head.startswith(magic):
            continue
        if magic == b"RIFF":
            tag = data[8:12]
            if tag == b"WEBP":
                return "image/webp", "webp"
            if tag == b"WAVE":
                return "audio/wav", "wav"
            continue
        return mime, ext
    return "", ""


_KIND_FAMILY = {"video": "video", "image": "image", "audio": "audio", "film": "video"}


def verify(kind: str, data: bytes) -> dict:
    """{mime, ext, bytes, width, height, seconds} — or MediaEmpty when this is not that media.

    A body that fails verification is a FAILURE, not a success. A relay that answers 200 with an
    HTML error page is the case this catches, and storing it would make a broken element that
    reads as ready.
    """
    if not data:
        raise MediaEmpty("the provider returned an empty file")
    if len(data) > MAX_BYTES:
        raise MediaEmpty(f"the provider returned {len(data)} bytes, over the {MAX_BYTES} cap")
    mime, ext = sniff(data)
    want = _KIND_FAMILY.get(kind, kind)
    if not mime:
        raise MediaEmpty(f"the provider returned {len(data)} bytes this cannot identify as a "
                         f"{want}")
    if not mime.startswith(want + "/"):
        raise MediaEmpty(f"the provider returned {mime} where a {want} was expected")
    out = {"mime": mime, "ext": ext, "bytes": len(data), "width": 0, "height": 0, "seconds": 0.0}
    if want in ("video", "audio"):
        probed = probe(data, ext)
        if want == "video" and not probed.get("seconds"):
            # A video whose duration cannot be read cannot be cut, timed or summed. Refusing is
            # the honest answer; a zero-length shot in a timeline is not.
            if have_ffmpeg():
                raise MediaEmpty("the file came back unreadable — no duration in it")
        out.update({k: v for k, v in probed.items() if v})
    return out


# ── ffmpeg: probing, and assembling a film ────────────────────────────────────────
@functools.lru_cache(maxsize=1)
def have_ffmpeg() -> bool:
    """Both binaries or neither. Checked once at first use, so a deployment built without them
    reports export unavailable rather than failing at the end of a four-minute render."""
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _run(cmd: list[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)


def probe_file(path: str) -> dict:
    """{seconds, width, height, has_audio} for a file on disk, or {} when it cannot be read."""
    if not have_ffmpeg():
        return {}
    p = _run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
              path], timeout=60)
    if p.returncode != 0:
        return {}
    try:
        doc = json.loads(p.stdout or b"{}")
    except Exception:  # noqa: BLE001
        return {}
    streams = doc.get("streams") or []
    vid = next((s for s in streams if s.get("codec_type") == "video"), None)
    aud = next((s for s in streams if s.get("codec_type") == "audio"), None)
    dur = 0.0
    for src in ((doc.get("format") or {}).get("duration"), (vid or {}).get("duration"),
                (aud or {}).get("duration")):
        try:
            dur = float(src)
        except (TypeError, ValueError):
            continue
        if dur > 0:
            break
    return {"seconds": round(dur, 3), "width": int((vid or {}).get("width") or 0),
            "height": int((vid or {}).get("height") or 0), "has_audio": aud is not None}


def probe(data: bytes, ext: str = "bin") -> dict:
    with tempfile.NamedTemporaryFile(suffix=f".{ext or 'bin'}", delete=False) as f:
        f.write(data)
        path = f.name
    try:
        return probe_file(path)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(path)


class ExportRefused(MediaError):
    """The film cannot be assembled, and the sentence says what would fix it."""


def assemble(shots: list[dict], audio: list[dict], *, fps: int, resolution: str,
             out_path: str, on_progress=None) -> dict:
    """Cut the shots together into one file. Returns {seconds, width, height, bytes}.

    LETTERBOX, NEVER STRETCH. Every shot is scaled to fit inside the timeline's own declared
    resolution and padded to it — not resized to whatever the first clip happened to be, which
    distorts an entire film because one shot was shot in portrait.

    THEN THE OUTPUT IS PROBED AND ITS DURATION COMPARED WITH THE PLAN. A mismatch fails the job
    and reports both numbers. An assembled duration nobody checks is an assembled duration nobody
    notices is wrong.
    """
    if not have_ffmpeg():
        raise ExportRefused("This deployment cannot assemble video — ffmpeg is not installed. "
                            "The clips are all still here to download individually.")
    if not shots:
        raise ExportRefused("There is nothing in the timeline to export.")
    W, H = parse_size(resolution)
    if not W or not H:
        raise ExportRefused(f"{resolution!r} is not a resolution this can render.")

    inputs: list[str] = []
    filters: list[str] = []
    concat_in = ""
    planned = 0.0
    for i, shot in enumerate(shots):
        path = shot["path"]
        info = probe_file(path)
        dur = float(info.get("seconds") or 0.0)
        start = max(0.0, float(shot.get("in_s") or 0.0))
        end = float(shot.get("out_s") or dur or 0.0) or dur
        end = min(end, dur) if dur else end
        if end <= start:
            raise ExportRefused(f"Shot {i + 1} has no length between {start}s and {end}s.")
        planned += end - start
        if start:
            inputs += ["-ss", f"{start:.3f}"]
        inputs += ["-to", f"{end:.3f}", "-i", path]
        filters.append(
            f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,fps={fps},setsar=1,format=yuv420p[v{i}]")
        if info.get("has_audio"):
            filters.append(f"[{i}:a]aresample=async=1:first_pts=0,asetpts=PTS-STARTPTS[a{i}]")
        else:
            # A shot with no audio contributes silence of its exact length, so the concat's audio
            # and video streams stay the same length and nothing drifts.
            filters.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{end - start:.3f},"
                           f"asetpts=PTS-STARTPTS[a{i}]")
        concat_in += f"[v{i}][a{i}]"
        if on_progress:
            on_progress(i, len(shots))

    filters.append(f"{concat_in}concat=n={len(shots)}:v=1:a=1[vout][acat]")
    last_audio = "acat"
    if audio:
        mix_in = "[acat]"
        for j, tr in enumerate(audio):
            k = len(shots) + j
            inputs += ["-i", tr["path"]]
            delay = int(max(0.0, float(tr.get("start_s") or 0.0)) * 1000)
            gain = float(tr.get("gain_db") or 0.0)
            filters.append(f"[{k}:a]adelay={delay}|{delay},volume={gain}dB[m{j}]")
            mix_in += f"[m{j}]"
        filters.append(f"{mix_in}amix=inputs={len(audio) + 1}:duration=first:"
                       f"dropout_transition=0,alimiter=limit=0.95[aout]")
        last_audio = "aout"

    cmd = (["ffmpeg", "-nostdin", "-y"] + inputs +
           ["-filter_complex", ";".join(filters), "-map", "[vout]", "-map", f"[{last_audio}]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out_path])
    p = _run(cmd, timeout=float(os.environ.get("HR_MEDIA_EXPORT_TIMEOUT_S", "1800")))
    if p.returncode != 0 or not os.path.exists(out_path) or not os.path.getsize(out_path):
        tail = (p.stderr or b"").decode("utf-8", "replace").strip().splitlines()[-3:]
        raise ExportRefused("The assembly failed: " + (" ".join(tail) or "ffmpeg produced nothing"))

    got = probe_file(out_path)
    actual = float(got.get("seconds") or 0.0)
    if abs(actual - planned) > 0.5:
        raise ExportRefused(
            f"The assembled film is {actual:.2f}s but the timeline plans {planned:.2f}s. "
            f"Nothing was delivered — a film that is not the length it was cut to is not the film.")
    return {"seconds": round(actual, 3), "width": int(got.get("width") or W),
            "height": int(got.get("height") or H), "bytes": os.path.getsize(out_path),
            "planned_seconds": round(planned, 3)}


# ── the canvas: an Excalidraw scene we construct, never one an agent writes ───────
# The agent gets narrow tools (place, move, arrange, remove) and those produce valid elements.
# A large schema an agent writes freehand is a schema an agent gets wrong.
SCENE_SOURCE = "harnessrouter/kits/media"

# Default tile geometry. A 16:9 card wide enough to read a caption under.
TILE_W, TILE_H, GUTTER = 480, 270, 24
CAPTION_H = 24


def new_scene(title: str = "") -> dict:
    return {"type": "excalidraw", "version": 2, "source": SCENE_SOURCE,
            "elements": [], "appState": {"viewBackgroundColor": "#ffffff", "gridSize": None},
            "files": {},
            "timeline": {"v": 1, "fps": 30, "resolution": "1920x1080", "shots": [], "audio": [],
                         "updatedAt": int(time.time() * 1000)},
            "meta": {"title": title, "rev": 0}}


def _eid() -> str:
    return "el_" + uuid.uuid4().hex[:16]


def _seed() -> int:
    return int(uuid.uuid4().int % 2_000_000_000) + 1


def _base_element(kind: str, x: float, y: float, w: float, h: float) -> dict:
    now = int(time.time() * 1000)
    return {"id": _eid(), "type": kind, "x": float(x), "y": float(y),
            "width": float(w), "height": float(h), "angle": 0,
            "strokeColor": "#1e1e1e", "backgroundColor": "transparent", "fillStyle": "solid",
            "strokeWidth": 1, "strokeStyle": "solid", "roughness": 0, "opacity": 100,
            "groupIds": [], "frameId": None, "roundness": None, "seed": _seed(),
            "version": 1, "versionNonce": _seed(), "isDeleted": False,
            "boundElements": None, "updated": now, "link": None, "locked": False}


def media_element(kind: str, *, x: float, y: float, w: float = TILE_W, h: float = TILE_H,
                  media_id: str = "", job_id: str = "", status: str = "running",
                  model: str = "", cap: str = "", seconds: float = 0.0,
                  width: int = 0, height: int = 0, prompt: str = "", label: str = "",
                  media_url: str = "") -> dict:
    """One element per clip, and one only.

    Two elements per clip — a backing rectangle plus a captured frame with a hand-drawn play
    triangle — doubles every move, every remove and every selection, and the two halves
    desynchronise. A video is an `embeddable` the app renders itself; an image is an `image`
    element whose file entry points at the same media.

    NO PROVIDER URL IS EVER STORED. It expires; our copy does not. `link` is this gateway's own
    media path, derived from the media id, so moving the deployment does not strand a scene.
    """
    el = _base_element("image" if kind == "image" else "embeddable", x, y, w, h)
    el["customData"] = {"media": {
        "v": 1, "kind": kind, "status": status, "jobId": job_id or None,
        "mediaId": media_id or None, "posterMediaId": None,
        "model": model or None, "capability": cap or None,
        "seconds": float(seconds) or None, "width": int(width) or None,
        "height": int(height) or None, "prompt": prompt or None, "label": label or None,
        "createdAt": int(time.time() * 1000)}}
    if kind == "image":
        el.update({"status": "saved" if media_id else "pending",
                   "fileId": media_id or None, "scale": [1, 1], "crop": None})
    else:
        el["link"] = media_url or None
    return el


def text_element(text: str, *, x: float, y: float, w: float = TILE_W,
                 h: float = CAPTION_H) -> dict:
    el = _base_element("text", x, y, w, h)
    el.update({"text": text, "originalText": text, "fontSize": 16, "fontFamily": 5,
               "textAlign": "left", "verticalAlign": "top", "containerId": None,
               "lineHeight": 1.25, "autoResize": True, "strokeColor": "#1e1e1e"})
    return el


def file_entry(media_id: str, mime: str, url: str) -> dict:
    """An Excalidraw files[] entry whose dataURL is a same-origin PATH rather than a data URI.

    Verified: Excalidraw accepts a plain URL there. That is what keeps a ten-image board a few
    kilobytes of document instead of forty megabytes of base64.
    """
    return {"id": media_id, "mimeType": mime or "image/png", "dataURL": url,
            "created": int(time.time() * 1000), "lastRetrieved": int(time.time() * 1000)}


def is_media(el: dict) -> bool:
    return bool(((el or {}).get("customData") or {}).get("media"))


def media_of(el: dict) -> dict:
    return ((el or {}).get("customData") or {}).get("media") or {}


def element_summary(el: dict) -> dict:
    """What describe_canvas says about one element. Never raw scene JSON — the agent has no use
    for `versionNonce` and every use for "Shot 2 is still rendering"."""
    m = media_of(el)
    kind = str(m.get("kind") or ("text" if el.get("type") == "text"
                                 else "frame" if el.get("type") == "frame" else "shape"))
    out = {"id": el.get("id"), "kind": kind,
           "x": round(float(el.get("x") or 0), 1), "y": round(float(el.get("y") or 0), 1),
           "w": round(float(el.get("width") or 0), 1), "h": round(float(el.get("height") or 0), 1)}
    if el.get("type") == "text":
        out["label"] = el.get("text") or ""
    if m:
        out["status"] = m.get("status")
        for src, dst in (("label", "label"), ("seconds", "seconds"), ("model", "model"),
                         ("jobId", "job_id"), ("mediaId", "media_id")):
            if m.get(src):
                out[dst] = m[src]
    if el.get("type") == "frame":
        # Nothing here builds a frame; a person drawing one in the app is why this branch exists.
        out["label"] = el.get("name") or ""
    return out


def next_free(elements: list[dict], columns: int = 4) -> tuple[float, float]:
    """Where the next `place` with no coordinates lands. Returned by describe_canvas so the agent
    can reason about layout without doing arithmetic and without guessing.

    Packing is driven by the MEDIA TILES and nothing else. A caption sits under its clip, so
    counting it as an occupant puts the next clip level with the caption instead of level with the
    clip — a board that drifts down and to the right one shot at a time.
    """
    tiles = [e for e in elements if not e.get("isDeleted") and is_media(e)]
    if not tiles:
        return 40.0, 40.0
    row_y = max(float(e.get("y") or 0) for e in tiles)
    same_row = [e for e in tiles if abs(float(e.get("y") or 0) - row_y) < 1.0]
    if len(same_row) >= columns:
        # The row is full: drop below everything on the canvas, captions included, so the new row
        # does not land on top of the last row's text.
        live = [e for e in elements if not e.get("isDeleted")]
        bottom = max(float(e.get("y") or 0) + float(e.get("height") or 0) for e in live)
        return 40.0, bottom + GUTTER * 2
    right = max(float(e.get("x") or 0) + float(e.get("width") or 0) for e in same_row)
    return right + GUTTER, row_y


def storyboard_items(els: list[dict], chosen: list[dict]) -> list[dict]:
    """Group a flat element list into shots: each media element, then the elements PLACED WITH IT.

    A media element's companions are the ones that follow it in document order until the next
    media element, sharing its shot — because `place` appends a caption directly after the media
    it captions, so document order already binds them and no new field is needed.

    Selecting "every element with the same shot name" instead makes each element a child of every
    clip in that shot, so a shot holding a still AND a clip emits every element twice and the
    board is laid out on top of itself.
    """
    index = {id(e): i for i, e in enumerate(els)}
    items: list[dict] = []
    for e in chosen:
        item = {"id": e.get("id"), "w": float(e.get("width") or TILE_W),
                "h": float(e.get("height") or TILE_H)}
        shot = (e.get("customData") or {}).get("shot")
        kids: list[dict] = []
        start = index.get(id(e))
        if start is not None and shot:
            for c in els[start + 1:]:
                if is_media(c) or (c.get("customData") or {}).get("shot") != shot:
                    break                              # the next clip owns what follows it
                kids.append({"id": c.get("id"), "w": float(c.get("width") or TILE_W),
                             "h": float(c.get("height") or CAPTION_H)})
        item["children"] = kids
        items.append(item)
    return items


def layout_positions(items: list[dict], layout: str, *, columns: int = 4, gutter: int = GUTTER,
                     origin: tuple[float, float] = (40.0, 40.0)) -> list[dict]:
    """The row-packing every storyboard wants, on the server where the agent can ask for it.

    `storyboard` is one row per shot — clip, then its caption, then its audio chip — because that
    is what a person reads down a page, and computing it in a browser strands it there.
    """
    ox, oy = origin
    out: list[dict] = []
    if layout == "row":
        x = ox
        for it in items:
            out.append({"element_id": it["id"], "x": x, "y": oy,
                        "w": it["w"], "h": it["h"]})
            x += it["w"] + gutter
        return out
    if layout == "column":
        y = oy
        for it in items:
            out.append({"element_id": it["id"], "x": ox, "y": y, "w": it["w"], "h": it["h"]})
            y += it["h"] + gutter
        return out
    if layout == "storyboard":
        y = oy
        for it in items:
            for band in [it] + list(it.get("children") or []):
                out.append({"element_id": band["id"], "x": ox, "y": y,
                            "w": band["w"], "h": band["h"]})
                y += band["h"] + gutter // 3
            y += gutter * 2                      # the gap between one shot and the next
        return out
    cols = max(1, int(columns))
    col_w = max((it["w"] for it in items), default=TILE_W)
    row_h = max((it["h"] for it in items), default=TILE_H)
    for i, it in enumerate(items):
        out.append({"element_id": it["id"],
                    "x": ox + (i % cols) * (col_w + gutter),
                    "y": oy + (i // cols) * (row_h + gutter),
                    "w": it["w"], "h": it["h"]})
    return out


def scene_bounds(elements: list[dict]) -> dict:
    live = [e for e in elements if not e.get("isDeleted")]
    if not live:
        return {"x": 0, "y": 0, "w": 0, "h": 0}
    xs = [float(e.get("x") or 0) for e in live]
    ys = [float(e.get("y") or 0) for e in live]
    x2 = [float(e.get("x") or 0) + float(e.get("width") or 0) for e in live]
    y2 = [float(e.get("y") or 0) + float(e.get("height") or 0) for e in live]
    return {"x": round(min(xs), 1), "y": round(min(ys), 1),
            "w": round(max(x2) - min(xs), 1), "h": round(max(y2) - min(ys), 1)}


def sanitize_scene(doc) -> dict:
    """A document we will store, whatever a client sent.

    `appState.collaborators` is a Map in the component and `{}` after a JSON round trip, and
    Excalidraw crashes calling `.forEach` on it. Stripping it is not tidiness; it is the
    difference between a canvas that opens and one that does not.
    """
    if not isinstance(doc, dict):
        return new_scene()
    out = dict(doc)
    out.setdefault("type", "excalidraw")
    out.setdefault("version", 2)
    out.setdefault("source", SCENE_SOURCE)
    els = out.get("elements")
    out["elements"] = [e for e in els if isinstance(e, dict)] if isinstance(els, list) else []
    st = out.get("appState")
    st = dict(st) if isinstance(st, dict) else {}
    st.pop("collaborators", None)
    out["appState"] = st
    out["files"] = out.get("files") if isinstance(out.get("files"), dict) else {}
    tl = out.get("timeline")
    out["timeline"] = tl if isinstance(tl, dict) else {"v": 1, "fps": 30,
                                                       "resolution": "1920x1080",
                                                       "shots": [], "audio": []}
    meta = out.get("meta")
    out["meta"] = meta if isinstance(meta, dict) else {"title": "", "rev": 0}
    return out


def timeline_total(scene: dict, ready_only: bool = False) -> float:
    """Summed from the clips' REAL measured durations, never from the seconds someone asked for."""
    by_id = {e.get("id"): e for e in scene.get("elements") or []}
    total = 0.0
    for shot in (scene.get("timeline") or {}).get("shots") or []:
        el = by_id.get(shot.get("elementId")) or {}
        m = media_of(el)
        if ready_only and m.get("status") != "ready":
            continue
        dur = float(m.get("seconds") or 0.0)
        a = float(shot.get("inS") or 0.0)
        b = float(shot.get("outS") or dur or 0.0) or dur
        total += max(0.0, min(b, dur or b) - a)
    return round(total, 3)


def levenshtein_ratio(a: str, b: str) -> float:
    """How close what the model SAID is to what it was asked to say. Real data both sides — the
    provider returns its own transcript, so `verbatim` is measured rather than assumed."""
    a, b = re.sub(r"\W+", " ", (a or "").lower()).strip(), re.sub(r"\W+", " ", (b or "").lower()).strip()
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return 1.0 - prev[-1] / max(len(a), len(b))


async def to_thread(fn, *a, **kw):
    """Run a blocking ffmpeg/ffprobe call off the event loop. One helper, so no call site has to
    remember that assembling a film blocks for minutes."""
    return await asyncio.get_running_loop().run_in_executor(None, functools.partial(fn, *a, **kw))
