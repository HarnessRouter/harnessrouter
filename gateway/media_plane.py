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

SEVEN ENDPOINT SHAPES, all measured against the live accounts on 2026-08-15:

  video-generation   POST /video/generations -> task id; GET /video/generations/{id} to poll
  image-generation   POST /images/generations -> b64_json OR url (both occur)
  openai             POST /chat/completions -> choices[0].message.images[0].image_url.url
  gemini             POST /v1beta/models/{id}:generateContent -> inlineData parts
  audio-chat         POST /chat/completions with modalities -> message.audio.data (+ transcript)
  elevenlabs-music   POST /music -> RAW AUDIO BYTES
  elevenlabs-speech  POST /text-to-speech/{voice_id} -> RAW AUDIO BYTES

THE LAST TWO BREAK WHAT THE FIRST FIVE SHARE, and each break is a place a special case could have
gone. The auth header is not a bearer, and which header a provider wants is declared BESIDE ITS
BASE URL in the catalog — see `auth_of` — rather than branched on its name where the socket is.
The answer is not JSON, and the same endpoint answers audio when it worked and JSON when it did
not, so a response is CLASSIFIED before it is read — see `response_doc`. And the model is a PATH
SEGMENT, not a body field, which is why `voice_for` computes the answer in one place: what the URL
carries and what the tool reports afterwards cannot be allowed to disagree.

They are TWO shapes and not one because a shape IS an endpoint's identity here, and these are two
endpoints: different path, different body, different tunables. `_SHAPE_TUNABLES` is the whitelist a
candidate is held to when it declares no `params` of its own, and each of these lists is exactly
what its builder emits — merge them and the whitelist permits four fields where the endpoint has
two, which is a whitelist that has stopped describing what it guards. Merging would also need the
one branch to pick a path from some new catalog field, which is two shapes wearing one name. What
they genuinely share is shared rather than copied: one auth entry, one raw-response branch.

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
    "vercel-video": ("prompt", "duration", "image", "size"),
    "vercel-speech": ("prompt", "voice"),
    "image-generation": ("prompt", "n", "size", "image"),
    "openai": ("prompt", "image"),
    "gemini": ("prompt", "image"),
    "audio-chat": ("messages", "modalities", "audio", "stream"),
    # Two endpoints, two lists, neither a subset of the other — and each is EXACTLY what its
    # builder below emits. A permitted field the endpoint has no slot for is dead permission, and
    # the union of these two is four of them.
    "elevenlabs-music": ("prompt", "duration"),
    "elevenlabs-speech": ("prompt", "voice"),
}

# The shapes whose 200 IS THE MEDIA. Every other shape answers with a document that says where the
# media is or carries it base64'd inside; these answer with the file. See `response_doc`.
_RAW_SHAPES = frozenset({"elevenlabs-music", "elevenlabs-speech"})

# Vercel's media protocol version. Not a guess and not the model's `supported_specifications`:
# every other value tried answers 400 "Unsupported gateway protocol version".
_VERCEL_PROTOCOL = "0.0.1"
# Its video endpoint names resolutions rather than taking WxH. Asking for "480p" returned a
# 854x480 file, so the label is the request and the pixels are the provider's business.
_VERCEL_RES = {"854x480": "480p", "1280x720": "720p", "1920x1080": "1080p",
               "480x854": "480p", "720x1280": "720p", "1080x1920": "1080p"}


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


# ── the operator's preference, as a LAYER over the measured catalog ───────────────────────────
# THE CATALOG IS FACT AND THIS IS POLICY, and they are kept apart on purpose. The file records
# what each model DID when it was called — the duration it honoured, the frame it returned, what
# it cost. An operator saying "prefer this one, switch that one off" is a different kind of
# statement, and writing it into the catalog would overwrite a measurement with an opinion and
# lose the reason the ranking was what it was.
#
# It is applied in `capability()` — the ONE place candidates are read — so the chain that runs, the
# chain the console draws and the chain an agent is told about are the same list. Applying it at
# the two call sites instead is how a console comes to show an order the router does not use.
_policy: dict = {}


def set_policy(doc: dict | None) -> None:
    """Replace the operator's preference. Called at startup and after every write."""
    global _policy                                       # noqa: PLW0603 — one module-level cache
    _policy = doc if isinstance(doc, dict) else {}


def policy() -> dict:
    return _policy


def _apply_policy(cap_name: str, cands: list) -> list:
    """Candidates in the operator's order, with switched-off ones MARKED rather than removed.

    Marked, not filtered: a model that vanishes from the chain produces a refusal that cannot
    explain itself. `stood_down` turns the mark into a sentence, so an agent that finds nothing
    available is told "X is switched off on this instance" instead of "no model can do this".
    """
    p = (_policy.get(cap_name) or {}) if isinstance(_policy.get(cap_name), dict) else {}
    order = [str(m) for m in (p.get("order") or [])]
    off = {str(m) for m in (p.get("disabled") or [])}
    if not order and not off:
        return cands
    marked = [({**c, "policy_off": True} if str(c.get("model")) in off else c) for c in cands]
    if not order:
        return marked
    rank = {m: i for i, m in enumerate(order)}
    # A candidate the preference does not mention keeps its catalog position, AFTER the ones it
    # does: a model added by an upgrade must not silently outrank what an operator chose.
    return sorted(marked, key=lambda c: (rank.get(str(c.get("model")), len(order)),))


def capability(name: str) -> dict:
    c = (catalog().get("capabilities") or {}).get(name)
    if not isinstance(c, dict):
        return {}
    cands = c.get("candidates")
    if not isinstance(cands, list) or not _policy:
        return c
    return {**c, "candidates": _apply_policy(name, cands)}


def capability_names() -> list[str]:
    return [k for k in (catalog().get("capabilities") or {})]


def provider_meta(provider: str) -> dict:
    p = (catalog().get("providers") or {}).get(provider)
    return p if isinstance(p, dict) else {}


# ── how a provider is signed ──────────────────────────────────────────────────────
# TWO STYLES SO FAR, and which one a provider uses is that PROVIDER'S OWN FACT — declared in the
# catalog beside its base_url, because "where to send it" and "how to sign it" are the same kind of
# fact and are learnt in the same measurement. Five providers wanted `authorization: Bearer <key>`;
# ElevenLabs wants `xi-api-key: <key>` and answers 401 to a bearer.
#
# NOT A BRANCH ON THE PROVIDER'S NAME. `if provider == "elevenlabs"` at the socket would be a
# second place that has to know this provider exists — after the catalog, which is the place — and
# the next provider with its own header would make a third. A deployment can add one by editing
# the file, which is the whole reason the file is read from disk.
_AUTH_DEFAULT = ("authorization", "Bearer ")


def auth_of(pmeta: dict) -> tuple[str, str]:
    """(header, prefix) this provider signs with.

    The default is the bearer every OpenAI-shaped relay wants, so a provider entry that says
    nothing about auth keeps working — and a `prefix` of "" is a real answer, not an absent one:
    ElevenLabs wants the key bare.
    """
    a = pmeta.get("auth") if isinstance(pmeta, dict) else None
    if not isinstance(a, dict):
        return _AUTH_DEFAULT
    header = str(a.get("header") or _AUTH_DEFAULT[0]).strip().lower()
    prefix = _AUTH_DEFAULT[1] if a.get("prefix") is None else str(a.get("prefix"))
    return header, prefix


def auth_headers(prov: dict) -> dict:
    """The credential header for one outbound call, in this provider's own style. ONE header, so
    a key can never be sent in two places and only one of them noticed."""
    header, prefix = auth_of(prov)
    return {header: f"{prefix}{prov.get('api_key') or ''}"}


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


# ── voices ────────────────────────────────────────────────────────────────────────
# A VOICE HAS A NAME AND AN ID, and they belong to different halves of this. The NAME is what the
# agent asks for and what `can_serve` filters the chain on; the ID is what the request carries.
# One candidate holds both, as a {name: id} map, because two fields would be two things to keep in
# step. A candidate whose provider names its voices (`alloy`) declares a plain list instead, and
# both answer `in`.

def voice_names(cand: dict) -> list[str]:
    """The voices this candidate offers, by name, in its own declaration order — never the ids.
    An id is a routing detail; an agent picks a narrator."""
    v = cand.get("voices")
    return [str(k) for k in v] if isinstance(v, (dict, list)) else []


def default_voice(cand: dict) -> str:
    """The voice used when the caller names none: this candidate's declared default, or the first
    it lists.

    FROM THE CANDIDATE, never from the calling code. `alloy` used to be the tool's default for
    every model in the capability — one provider's voice name standing in for all of them — which
    meant every call that named no voice carried a voice only OpenAI has, and skipped anything
    else in the chain before it could run.
    """
    named = str(cand.get("default_voice") or "")
    return named or next(iter(voice_names(cand)), "")


def voice_for(cand: dict, params: dict) -> str:
    """The voice this candidate will be ASKED for — "" when it has no voices at all.

    THE ONE PLACE that answer is computed, for the same reason `size_for` is: what the submit
    carries and what the tool reports back afterwards cannot be allowed to disagree.
    """
    if not cand.get("voices"):
        return ""
    return str(params.get("voice") or default_voice(cand))


def voice_id(cand: dict, voice: str) -> str:
    """The provider's own id for a named voice, or "" when this candidate does not offer it. Only
    a candidate whose voices are addressed BY ID has a map to answer from."""
    voices = cand.get("voices")
    return str((voices or {}).get(voice) or "") if isinstance(voices, dict) else ""


# What a model that ANSWERS a prompt has to be told, to make it read one instead. A workaround for
# the wrong kind of model doing narration — measured: "Say: hello." came back as "Hello! It's great
# to talk with you." — so it is applied PER CANDIDATE, to the ones that need it.
#
# It used to be built by the tool, before any model had been chosen, which is a sentence about
# gpt-audio applied to whatever ran. A real reader would have READ IT OUT: "Read this aloud exactly
# as written, and say nothing else: the tide went out."
_READ_ALOUD = "Read this aloud exactly as written, and say nothing else: "


def spoken_prompt(cand: dict, text: str) -> str:
    """The line as this candidate must be given it."""
    return (_READ_ALOUD + text) if cand.get("answers_prompts") else text


def limits_of(cand: dict) -> dict:
    """What list_capabilities tells the agent about the model it would get. Only keys the
    candidate actually declares — an absent limit is absent, not a default someone invented."""
    out: dict = {}
    for k in ("durations_s", "duration_min_s", "duration_max_s", "durations_rejected_s",
              "duration_ignored", "duration_observed_s", "resolution", "min_pixels",
              "sizes_verified", "format", "latency_s", "output_mime"):
        if cand.get(k) is not None:
            out[k] = cand[k]
    if cand.get("voices"):
        # NAMES, whichever way this candidate stores them. The agent chooses by name and passes a
        # name back; an id in this dict would be a second spelling of the same choice.
        out["voices"] = voice_names(cand)
    if cand.get("answers_prompts"):
        # A measured property of the MODEL, and the one an agent planning narration most needs
        # before it spends: this one will answer the line instead of reading it.
        out["answers_prompts"] = True
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
    model_off = str(cand.get("model") or "?")
    if cand.get("policy_off"):
        # The operator's own decision, said in their terms: this is not a fault and not a limit.
        return f"{model_off} is switched off on this instance"
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

    __slots__ = ("method", "url", "body", "tunables", "stream", "timeout", "headers")

    def __init__(self, method: str, url: str, body: dict, tunables: dict,
                 stream: bool = False, timeout: float = SUBMIT_TIMEOUT_S,
                 headers: dict | None = None):
        self.method, self.url, self.body = method, url, body
        self.tunables, self.stream, self.timeout = tunables, stream, timeout
        # Non-credential headers a shape needs to be understood at all: Vercel's media endpoints
        # take the model and the protocol version there rather than in the body. NEVER the
        # credential — that is `auth_headers`, built once at the call site from the provider entry,
        # so there stays exactly one place a key can be written into a request.
        self.headers = headers or {}

    def __repr__(self) -> str:      # pragma: no cover - debugging aid
        return f"<Submit {self.method} {self.url} tunables={sorted(self.tunables)}>"


def _timeout_for(cand: dict) -> float:
    """A synchronous shape renders inside the submit, so its budget is its measured latency with
    room — not one number for a 4-second model and a 91-second one."""
    lat = cand.get("latency_s")
    # The video shapes SUBMIT a job and return in about a second; their `latency_s` is how long
    # the render takes afterwards, which is not a budget for this call. Reading it as one gave the
    # Vercel start a 348 s ceiling for a request that answers immediately.
    if str(cand.get("shape")) in ("video-generation", "vercel-video") \
            or not isinstance(lat, (int, float)):
        return min(SUBMIT_TIMEOUT_S, 120.0)
    return min(SUBMIT_TIMEOUT_S, max(60.0, float(lat) * 3.0))


def _api_root(base: str) -> str:
    """The provider's API root: the configured base with a trailing `/v1` taken off it.

    Two shapes need this, for opposite reasons, and both reasons are the same fact — a base_url is
    typed by a person and the version segment is the part they disagree about.

      gemini            posts under `/v1beta`, which hangs off the ROOT. TokenRouter's base carries
                        `/v1` for the four shapes that need it, so it is stripped here rather than
                        stored twice where the two copies could drift.
      the two elevenlabs
                        shapes build their own `/v1/…` on top of what this returns, so the SAME
                        url is produced whether the connected integration was saved as
                        `https://api.elevenlabs.io` or `https://api.elevenlabs.io/v1`. Measured:
                        the live integration is stored the first way and the catalog's default is
                        too; a shape that simply concatenated would 404 on the other spelling, and
                        a 404 here reads as "the provider is down".
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

    # Vercel's AI Gateway puts media on `/v4/ai/<kind>-model`, and takes the model and the
    # protocol version as HEADERS rather than in the body. Both are required: without
    # `ai-gateway-protocol-version` every call answers 400 "Unsupported gateway protocol
    # version", whatever else is right, and that is the whole body of the response.
    #
    # Measured against the live gateway on 2026-08-16 (Future HR key). The version that works is
    # `0.0.1`; v2/v3/v4 and bare 1/2/3 are all rejected, so it is a protocol version and NOT the
    # model's `supported_specifications`, which say v2/v3/v4 for the very models these calls land
    # on. Pinned here because a wrong guess is indistinguishable from an outage.
    if shape in ("vercel-video", "vercel-speech"):
        hdr = {"ai-model-id": model, "ai-gateway-protocol-version": _VERCEL_PROTOCOL}
        root = _api_root(base)                     # the /v4 lives on the root, not under /v1

        if shape == "vercel-video":
            body = {}
            prompt = take("prompt", params.get("prompt"))
            if prompt is not None:
                body["prompt"] = prompt
            secs = take("duration", params.get("seconds"))
            if secs is not None:
                body["duration"] = int(secs) if float(secs).is_integer() else float(secs)
            # The tier is this candidate's OWN verified resolution, not the caller's frame. This
            # endpoint accepts named tiers ("480p") and refuses a WxH, and each model publishes
            # only some of them — so a size computed for an aspect arrives as a frame the provider
            # has never heard of. A candidate that takes no `size` tunable therefore renders at
            # exactly the tier it was measured at, and one asked for a shape it cannot hold is
            # skipped upstream by can_serve rather than reframed here.
            tier = _VERCEL_RES.get(str(cand.get("resolution") or ""))
            asked = take("size", asked_size)          # only when the entry declares `size`
            if asked is not None:
                tier = _VERCEL_RES.get(asked, tier)
            if tier:
                body["resolution"] = tier
            img = take("image", params.get("image"))
            if img is not None:
                body["image"] = img
            # `/start`, NOT the plain endpoint. The plain one renders inside the request and a
            # seedance render is ~116 s, which is longer than a tool call will wait: the first run
            # through the kit reached this model and then timed out at the transport with no job
            # id, leaving a render that may have been running and could not be polled or claimed.
            # The start/status pair is what every other video candidate here already does.
            # `callbackUrl` is deliberately not sent — the SDK's own source says async video jobs
            # are polling-first, and a webhook would need a public address this instance may not
            # have.
            return Submit("POST", f"{root}/v4/ai/video-model/start", body, tun,
                          timeout=_timeout_for(cand), headers=hdr)

        body = {}
        prompt = take("prompt", params.get("prompt"))
        if prompt is not None:
            body["text"] = spoken_prompt(cand, prompt)
        voice = take("voice", voice_for(cand, params))
        if voice:
            # This endpoint addresses voices BY NAME ("alloy"), so the name is what goes on the
            # wire. `voice_id` only answers for a candidate that declares a name -> id map, and
            # sending its "" for a list-style candidate put an empty voice in every request.
            body["voice"] = voice_id(cand, voice) or voice
        body["outputFormat"] = str(cand.get("format") or "mp3")
        return Submit("POST", f"{root}/v4/ai/speech-model", body, tun,
                      timeout=_timeout_for(cand), headers=hdr)

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
        # The read-aloud instruction is THIS candidate's, not the tool's — see `spoken_prompt`.
        text = spoken_prompt(cand, str(params.get("prompt") or ""))
        body = {"model": model,
                "messages": [{"role": "user", "content": text}]}
        if "modalities" in allow:
            tun["modalities"] = ["text", "audio"]
            body["modalities"] = ["text", "audio"]
        if "audio" in allow:
            aud = {"voice": voice_for(cand, params) or "alloy",
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

    if shape == "elevenlabs-music":
        body = {}
        prompt = take("prompt", params.get("prompt"))
        if prompt is not None:
            body["prompt"] = prompt
        secs = take("duration", params.get("seconds"))
        if secs is not None:
            # MILLISECONDS, where every other duration in this catalog is seconds. Measured: 10000
            # returned a 10.031 s track.
            body["music_length_ms"] = int(round(float(secs) * 1000))
        # NO MODEL FIELD ANYWHERE: this endpoint takes none. `elevenlabs/music-v1` is our name for
        # the candidate — what the chain reports, quarantines and prices on — and it stays here.
        return Submit("POST", f"{_api_root(base)}/v1/music", body, tun,
                      timeout=_timeout_for(cand))

    if shape == "elevenlabs-speech":
        # THE MODEL THIS ADDRESSES IS A PATH SEGMENT. A voice id in the body would be accepted,
        # ignored, and billed as a default voice — the same class of failure as MiniMax ignoring an
        # input image, one layer up, and just as invisible in a 200.
        name = take("voice", voice_for(cand, params))
        vid = voice_id(cand, str(name or ""))
        if not vid:
            raise MediaError(f"{model} has no voice called {name!r}.")
        # Through `spoken_prompt` like the other speech shape, and not around it: "how must this
        # candidate be given the line" is ONE question, and a shape that answers it by not asking
        # is a shape that will be given the wrong answer the day a reader is added to the other
        # branch. This candidate does not declare `answers_prompts`, so the line comes back
        # untouched — which is the whole point, and is now asserted rather than arranged.
        line = take("prompt", spoken_prompt(cand, str(params.get("prompt") or "")))
        body = {"text": line or "", "model_id": model}
        return Submit("POST", f"{_api_root(base)}/v1/text-to-speech/{vid}", body, tun,
                      timeout=_timeout_for(cand))

    raise MediaError(f"No adapter for endpoint shape {shape!r}.")


class Poll:
    """One status check. A body and headers as well as a url, because not every provider answers
    a GET: Vercel's video status is a POST carrying back the opaque handle its start returned."""

    __slots__ = ("method", "url", "headers", "body")

    def __init__(self, method: str, url: str, headers: dict | None = None,
                 body: dict | None = None):
        self.method, self.url = method, url
        self.headers, self.body = headers or {}, body


def build_poll(cand: dict, base_url: str, task_id: str) -> Poll:
    shape = str(cand.get("shape"))
    base = (base_url or "").rstrip("/")
    if shape == "video-generation":
        return Poll("GET", f"{base}/video/generations/{task_id}")
    if shape == "vercel-video":
        # `task_id` here is the whole `operation` the start returned, carried as text because that
        # is what a job vertex can hold. It is the provider's handle and nothing is read out of it:
        # it goes back exactly as it came, which is the contract the SDK's doStatus implements.
        try:
            operation = json.loads(task_id)
        except Exception as e:  # noqa: BLE001
            raise MediaError("the stored video job handle is not readable") from e
        return Poll("POST", f"{_api_root(base)}/v4/ai/video-model/status",
                    headers={"ai-model-id": str(cand.get("model") or ""),
                             "ai-gateway-protocol-version": _VERCEL_PROTOCOL},
                    body={"operation": operation})
    raise MediaError("Only the video shapes are polled; every other shape answers inline.")


# ── the five adapters: reading a response ─────────────────────────────────────────
class Raw:
    """A response body that IS the media, rather than a document describing where it is."""

    __slots__ = ("data", "mime")

    def __init__(self, data: bytes, mime: str):
        self.data, self.mime = data, mime


# What a provider CLAIMS it sent, when the claim is that it sent media. Used for exactly one
# decision — parse or do not parse — and for nothing else.
_MEDIA_CT = re.compile(r"^\s*(?:audio|image|video)/", re.I)


def response_doc(content_type: str, body: bytes):
    """What the readers below are handed for one response: the parsed document, or the BYTES
    THEMSELVES when the provider answered with media instead of with a description of one.

    THE CONTENT TYPE DECIDES, because nothing else can. ElevenLabs answers the SAME endpoint with
    audio when it worked and with JSON when it did not, and those two answers mean opposite things
    about money — a 4xx is free and stays in the chain, a 200 billed. "Parse it and see" reads a
    402 as a corrupt track and pushes 160 KB of mp3 through `json.loads` on every call that
    succeeded. A parser is not a classifier.

    THIS IS NOT THE SNIFFING RULE BEING RELAXED. What the provider claims decides only whether to
    parse. What the bytes ARE still decides whether they are media, in `sniff`/`verify`, which
    every payload goes through before it is stored — an HTML error page labelled `audio/mpeg` gets
    this far and is refused there, exactly as it always was. The two questions are different and
    only one of them is answerable from a header.

    Anything not claimed as media is a document, INCLUDING a body with no content type at all: the
    five older shapes answer JSON and some relays say so and some do not, and defaulting the other
    way would break every one of them on a header nobody sends.
    """
    if _MEDIA_CT.match(content_type or ""):
        return Raw(bytes(body or b""), str(content_type).split(";")[0].strip().lower())
    try:
        return json.loads(body or b"{}")
    except Exception:  # noqa: BLE001
        return None


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
    shape = str(cand.get("shape") or "")

    if shape in _RAW_SHAPES:
        # A 200 from these IS the audio. Asked BEFORE the object check below, which would
        # otherwise read the track itself as "not an object" and stand the model down for
        # delivering.
        if isinstance(doc, Raw):
            if doc.data:
                return "", Payload(data=doc.data, mime=doc.mime)
            raise MediaEmpty("the provider answered 200 with an empty audio file")
        # A DOCUMENT where the audio should be: this provider talking, in a body that parsed. It
        # answered, so it billed, and it gets what every other 200 with no media in it gets — with
        # its own sentence, which is the only one that says what actually went wrong.
        raise MediaEmpty(provider_message(doc, status))

    if not isinstance(doc, dict):
        raise MediaEmpty("the provider answered with a body that is not an object")

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

    # Both Vercel media shapes are SYNCHRONOUS: the render happens inside the submit and the 200
    # carries the finished thing. There is no task id to poll, so `_read_submit` returns the
    # payload and the job never enters the polling walk at all.
    if shape == "vercel-video":
        # The start answers with an opaque `operation` and nothing else — no url, no id we could
        # shorten. It is stored whole, as text, and posted back verbatim on every poll.
        op = doc.get("operation")
        if op is not None:
            return json.dumps(op, separators=(",", ":")), None
        raise MediaEmpty(provider_message(doc, status) or
                         "the provider accepted the request but returned no job handle")

    if shape == "vercel-speech":
        if doc.get("audio"):
            fmt = str(cand.get("format") or "mp3")
            return "", Payload(data=_b64(str(doc["audio"])), mime=f"audio/{fmt}")
        raise MediaEmpty(provider_message(doc, status) or
                         "the provider answered with no audio")

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

    if str(cand.get("shape")) == "vercel-video":
        # A discriminated union on `status`, per the SDK's own schema: pending | completed, plus
        # the terminal states a job can end in. The shape is flat — `videos` sits beside `status`,
        # not under a `data` envelope like the relay's.
        st = str(doc.get("status") or "").lower()
        if st == "completed":
            vids = doc.get("videos")
            first = (vids[0] if isinstance(vids, list) and vids and isinstance(vids[0], dict)
                     else {})
            if first.get("url"):
                return "succeeded", Payload(url=str(first["url"]),
                                            mime=str(first.get("mediaType") or "video/mp4")), "", ""
            if first.get("base64") or first.get("data"):
                return "succeeded", Payload(
                    data=_b64(str(first.get("base64") or first.get("data"))),
                    mime=str(first.get("mediaType") or "video/mp4")), "", ""
            # Completed with nothing in it billed and delivered nothing. Same rule as everywhere.
            return "failed", None, "the provider reported completed and returned no video", ""
        if st in ("failed", "cancelled", "canceled"):
            return "failed", None, scrub(provider_message(doc, status)
                                         or f"the render ended as {st}"), ""
        if st == "pending" or not st:
            return "running", None, "", ""
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


def grab_frame(path: str, seconds: float | None = None) -> bytes:
    """One frame of a clip, as jpeg bytes. `seconds` defaults to the LAST frame.

    This is how one shot continues into the next: the frame a clip ends on becomes the frame the
    next shot starts from, so the cut lands on the same picture instead of on a second guess at
    the same scene. Nothing else can produce that frame — the still that seeded a shot is where
    it BEGAN, and five seconds of movement later the world has moved on.
    """
    if not have_ffmpeg():
        raise ExportRefused("This deployment cannot read a frame out of a clip — ffmpeg is not "
                            "installed.")
    dur = float(probe_file(path).get("seconds") or 0.0)
    if seconds is None:
        # Not the very last presentation timestamp: seeking exactly to the end lands past the
        # final frame on some files and decodes nothing at all.
        seconds = max(0.0, dur - 0.08) if dur else 0.0
    out = path + ".frame.jpg"
    p = _run(["ffmpeg", "-nostdin", "-y", "-ss", f"{max(0.0, seconds):.3f}", "-i", path,
              "-frames:v", "1", "-q:v", "2", out], timeout=120)
    if p.returncode != 0 or not os.path.exists(out) or not os.path.getsize(out):
        raise ExportRefused("That clip's frame could not be read.")
    try:
        return pathlib.Path(out).read_bytes()
    finally:
        try:
            os.unlink(out)
        except OSError:
            pass


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


# Where an overlay sits when it is not filling the frame, as a fraction of the frame, and the
# inset that keeps a corner off the very edge. Five places, because five is what a menu can offer
# and what the preview can draw exactly — a free-form x/y belongs to a canvas with drag handles,
# and building the field before the handles is building a promise.
OVERLAY_POS = {"full": None, "tl": (0.0, 0.0), "tr": (1.0, 0.0), "bl": (0.0, 1.0),
               "br": (1.0, 1.0), "center": (0.5, 0.5)}
OVERLAY_INSET = 0.03


def _overlay_xy(pos: str, scale: float) -> tuple[str, str]:
    """ffmpeg x:y for an overlay of `scale` of the frame, in one of the named places."""
    at = OVERLAY_POS.get(pos) or OVERLAY_POS["center"]
    fx, fy = at
    pad = f"{OVERLAY_INSET}*W"
    x = "(W-w)/2" if fx == 0.5 else (pad if fx == 0.0 else f"W-w-{pad}")
    y = "(H-h)/2" if fy == 0.5 else (pad if fy == 0.0 else f"H-h-{pad}")
    return x, y


def assemble(shots: list[dict], audio: list[dict], *, fps: int, resolution: str,
             out_path: str, overlays: list[dict] | None = None, on_progress=None) -> dict:
    """Cut the shots together into one file. Returns {seconds, width, height, bytes}.

    LETTERBOX, NEVER STRETCH. Every shot is scaled to fit inside the timeline's own declared
    resolution and padded to it — not resized to whatever the first clip happened to be, which
    distorts an entire film because one shot was shot in portrait.

    THE SHOTS ARE THE FILM'S SPINE AND THE OVERLAYS SIT ON TOP OF IT. An overlay is placed at a
    time rather than queued in an order, so adding one never moves anything underneath it — that
    is the whole difference between a second layer and another shot. The film is as long as its
    spine: an overlay hanging off the end is trimmed, because a layer above cannot lengthen what
    it is layered over.

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

        # A STILL HAS NO DURATION OF ITS OWN, so the CUT decides how long it is shown, and
        # `-loop 1 -t` is what turns one frame into a segment. WHETHER a shot is a still is the
        # caller's to state — see shot_window(). This asked ffprobe once, and a jpeg (which
        # reports 0.04s) was clamped to a single frame while the identical png was held for 3s.
        still = bool(shot.get("still")) or (dur <= 0 and not info.get("has_audio"))
        if still:
            hold = float(shot.get("out_s") or 0.0) - start
            if hold <= 0:
                raise ExportRefused(
                    f"Shot {i + 1} is a still and nothing says how long to hold it. Give it a "
                    f"duration on the timeline.")
            planned += hold
            inputs += ["-loop", "1", "-t", f"{hold:.3f}", "-i", path]
            filters.append(
                f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=decrease,"
                f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,fps={fps},setsar=1,"
                f"format=yuv420p[v{i}]")
            filters.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{hold:.3f},"
                           f"asetpts=PTS-STARTPTS[a{i}]")
            concat_in += f"[v{i}][a{i}]"
            if on_progress:
                on_progress(i, len(shots))
            continue

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

    filters.append(f"{concat_in}concat=n={len(shots)}:v=1:a=1[vcat][acat]")

    # ── the layers above the spine ───────────────────────────────────────────────
    # Composited in `layer` order, so what the timeline draws on top is what ends up on top.
    # Each one is seeked to its own in-point and then shifted to the moment on the FILM'S clock
    # where the cut places it; `enable` keeps it off screen the rest of the time.
    last_video, over_audio, n_in = "vcat", [], len(shots)
    ordered = sorted(enumerate(overlays or []), key=lambda p: (int(p[1].get("layer") or 1), p[0]))
    for j, (_, ov) in enumerate(ordered):
        o_in = max(0.0, float(ov.get("in_s") or 0.0))
        o_out = float(ov.get("out_s") or 0.0)
        at = max(0.0, float(ov.get("start_s") or 0.0))
        span = o_out - o_in
        if span <= 0 or at >= planned:
            continue                      # nothing to draw, or entirely past the end of the film
        span = min(span, planned - at)    # the spine is the film; a layer cannot extend it
        k, n_in = n_in, n_in + 1
        if ov.get("still"):
            inputs += ["-loop", "1", "-t", f"{span:.3f}", "-i", ov["path"]]
        else:
            inputs += ["-ss", f"{o_in:.3f}", "-to", f"{o_in + span:.3f}", "-i", ov["path"]]
        scale = min(1.0, max(0.05, float(ov.get("scale") or 1.0)))
        pos = str(ov.get("pos") or "full")
        box = f"{int(W * scale)}:{int(H * scale)}"
        filters.append(f"[{k}:v]scale={box}:force_original_aspect_ratio=decrease,setsar=1,"
                       f"fps={fps},format=yuva420p,setpts=PTS-STARTPTS+{at:.3f}/TB[ov{j}]")
        x, y = _overlay_xy(pos if scale < 1.0 else "center", scale)
        filters.append(f"[{last_video}][ov{j}]overlay={x}:{y}:eof_action=pass:"
                       f"enable='between(t,{at:.3f},{at + span:.3f})'[vov{j}]")
        last_video = f"vov{j}"
        if ov.get("has_audio"):
            over_audio.append({"input": k, "start_s": at, "gain_db": ov.get("gain_db") or 0.0})
    filters.append(f"[{last_video}]null[vout]")

    last_audio = "acat"
    beds = list(audio or [])
    if beds or over_audio:
        mix_in = "[acat]"
        for j, tr in enumerate(beds):
            k, n_in = n_in, n_in + 1
            inputs += ["-i", tr["path"]]
            delay = int(max(0.0, float(tr.get("start_s") or 0.0)) * 1000)
            gain = float(tr.get("gain_db") or 0.0)
            filters.append(f"[{k}:a]adelay={delay}|{delay},volume={gain}dB[m{j}]")
            mix_in += f"[m{j}]"
        # An overlay's own sound comes with it. A talking head dropped onto a layer that plays
        # silent is a layer that lost half of what was dropped on it.
        for j, tr in enumerate(over_audio):
            delay = int(tr["start_s"] * 1000)
            filters.append(f"[{tr['input']}:a]adelay={delay}|{delay},"
                           f"volume={float(tr['gain_db'])}dB[mo{j}]")
            mix_in += f"[mo{j}]"
        filters.append(f"{mix_in}amix=inputs={len(beds) + len(over_audio) + 1}:duration=first:"
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
                         "overlays": [], "updatedAt": int(time.time() * 1000)},
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


# How long a still is held when the cut doesn't say. The kit has the same number in
# src/lib/timeline.js — a preview that disagrees with the film is the bug this whole module
# exists to prevent, so the two constants are one decision written twice, and neither moves alone.
STILL_HOLD_S = 3.0


def shot_window(shot: dict, media: dict) -> tuple[float, float, bool]:
    """What part of a clip a shot shows: (in_s, out_s, is_still). THE answer to that question.

    It used to be answered in five places that disagreed. A 13-second cut exported as a 10-second
    film and every guard passed, because the planner said a still lasts STILL_HOLD_S, the total
    said an unbounded still lasts 0s, and the assembler asked ffprobe — which reports no duration
    for a png and 0.04s (one frame at 25fps) for a jpeg. Same picture, three answers, and the
    jpeg was cut down to a single frame.

    A STILL IS A STILL BECAUSE THE DOCUMENT SAYS IT IS AN IMAGE. Not because a file failed to
    report a duration. It has no length of its own, so the cut decides; if the cut is silent it
    is held for STILL_HOLD_S. A video is bounded by the length it was actually measured to be.
    """
    dur = float(media.get("seconds") or 0.0)
    still = media.get("kind") == "image" or (dur <= 0 and media.get("kind") != "video")
    in_s = max(0.0, float(shot.get("inS") or 0.0))
    raw = shot.get("outS")
    out_s = float(raw) if raw not in (None, "") else 0.0
    if still:
        # 0 gets here from writers that fell back to `seconds` a still does not have.
        if out_s <= in_s:
            out_s = in_s + STILL_HOLD_S
        return in_s, out_s, True
    if out_s <= 0 or out_s > dur:
        out_s = dur
    return min(in_s, out_s), out_s, False


def timeline_total(scene: dict, ready_only: bool = False) -> float:
    """Summed from the clips' REAL measured durations, never from the seconds someone asked for."""
    by_id = {e.get("id"): e for e in scene.get("elements") or []}
    total = 0.0
    for shot in (scene.get("timeline") or {}).get("shots") or []:
        el = by_id.get(shot.get("elementId")) or {}
        m = media_of(el)
        if ready_only and m.get("status") != "ready":
            continue
        a, b, _ = shot_window(shot, m)
        total += max(0.0, b - a)
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
