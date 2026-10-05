"""How much a model thinks on a turn: which levels a model has, and what turns each one on.

A turn may ask for a level (none, minimal, low, medium, high, xhigh). Nothing here is a guess: every
entry below was measured on 2026-10-05 by sending one question at every level through each route and
reading the provider's own reasoning-token count (the table and the method are in
docs/support-matrix-notes.md, "How much a model thinks"). Three things the measurement taught:

- No field means the same thing everywhere. `reasoning_effort` is honoured for most families on most
  routes, but through Vercel a Gemini model takes `none` as "think more", through TokenRouter it
  ignores the field entirely, and what works instead differs per route (a `providerOptions` block on
  one, an `extra_body` block on the other).
- A level a model lacks is refused, not ignored: `minimal` on gpt-5.4, `none` on gpt-6.1-sol or on
  any Gemini through OpenRouter ("Reasoning is mandatory for this endpoint"), `low` on Mistral
  through Vercel. So a level is only ever sent where it was seen to be accepted, and a model that
  lacks the one asked for gets the nearest one it has.
- A model and route that were not measured get NOTHING sent, and the turn says so ("default").

Pure functions over bytes, no imports from the runner: the relay applies them (runner/server.py), the
DeepSeek Harness driver's own relay applies them (runner/dsh_driver.py), and the gateway reads
`levels_for` for what /v1/bases offers (gateway/app.py loads this file by path).
"""
from __future__ import annotations

import json
import re

LEVELS = ("none", "minimal", "low", "medium", "high", "xhigh")
# The providers that were measured. A route is one of these or "", and "" gets nothing sent.
ROUTES = ("vercel", "tokenrouter", "openrouter", "openai", "azure", "google", "anthropic")

# The levels a model has, by its bare id (the part after the vendor's prefix). First match wins.
# Only ids that were measured are named; a family's unmeasured members are left out on purpose.
_MODEL_LEVELS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # OpenAI. `minimal` is refused by half the line and by every route's Responses API, so it is
    # never sent; gpt-6.1-sol and gpt-6-astra cannot be turned off.
    (r"^gpt-6\.1-sol|^gpt-6-astra", ("low", "medium", "high", "xhigh")),
    (r"^gpt-(5\.[2-6]|6)(-|$)", ("none", "low", "medium", "high", "xhigh")),
    # Anthropic. fable-5.1 refuses both of the API's ways of turning thinking off (fable-5 is taken
    # to be the same; it was not measured).
    (r"^claude-fable-5", ("low", "medium", "high", "xhigh")),
    (r"^claude-(haiku-4[.-]5|sonnet-4[.-]6|opus-4[.-][78]|sonnet-5|opus-5)", ("none", "low", "medium", "high", "xhigh")),
    # Google. The pro model and the 3.7 and 3.8 flash models only work thinking, and refuse `minimal`.
    (r"^gemini-3\.1-pro|^gemini-3\.[78]-flash$", ("low", "medium", "high")),
    (r"^gemini-3(\.[156])?-flash(-lite|-preview)?$", ("none", "minimal", "low", "medium", "high")),
    (r"^grok-4\.[356]$", ("minimal", "low", "medium", "high", "xhigh")),          # cannot be turned off
    (r"^deepseek-v4(\.1)?-(flash|pro)$", ("none", "low", "medium", "high", "xhigh")),
    (r"^kimi-k3$", ("none", "low", "medium", "high")),
    (r"^qwen3\.7-max$|^qwen3\.8-flash$", ("none", "high")),                       # on or off
    (r"^mistral-medium-3[.-]5$", ("none", "high")),
    (r"^step-3\.7-flash$", ("minimal", "low", "medium", "high", "xhigh")),        # cannot be turned off
    (r"^muse-spark-1\.3$", ("low", "high")),
    (r"^minimax-m3$|^ling-3\.0-flash$|^nemotron-3\.5-lightning$", ("none", "high")),
    (r"^hy3$|^hunyuan-3$", ("none", "low", "high")),
)

# A provider's own name for a model where its bare id differs from the catalog's.
_ALIASES = {"gemini-3-flash": "gemini-3-flash-preview", "grok-4.20-reasoning": "grok-4.20"}

# What a route cannot do for a model that has the level elsewhere: (route, bare-id pattern, levels).
_ROUTE_LACKS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("openrouter", r"^claude-(opus|sonnet)-5[.-]5", ("none",)),   # "Reasoning is mandatory for this endpoint"
    ("openrouter", r"^gemini-", ("none",)),                       # the same refusal, every Gemini
    ("vercel", r"^claude-opus-5[.-]5", ("none",)),                # accepted and not honoured
    ("tokenrouter", r"^deepseek-v4-pro$", ("none",)),             # "must be one of: low, medium, high, xhigh, max"
    ("tokenrouter", r"^gemini-3\.1-pro", ("medium",)),            # low and high were measured, medium was not
    ("google", r"^gemini-.*-flash-lite", ("minimal",)),
)
# Gemini through TokenRouter's chat door: only these two answered to any setting.
_TOKENROUTER_GEMINI = re.compile(r"^gemini-3\.5-flash$|^gemini-3\.1-pro")

_BUDGET = {"low": 1024, "medium": 4096, "high": 16384, "xhigh": 32000}   # claude-haiku-4.5 takes a budget, not an effort


def bare(model: str) -> str:
    """A model id without its vendor prefix and without a dated suffix, lower case."""
    m = str(model or "").strip().lower().lstrip("~").rsplit("/", 1)[-1]
    m = re.sub(r"-20\d{6}$|-\d{4}-\d{2}-\d{2}$", "", m)
    return _ALIASES.get(m, m)


def levels_for(model: str) -> tuple[str, ...]:
    """The levels this model has, lowest first; () when none was measured for it."""
    b = bare(model)
    for pattern, levels in _MODEL_LEVELS:
        if re.search(pattern, b):
            return levels
    return ()


def route_of(base_url: str) -> str:
    """Which provider a base URL belongs to, as far as the measurements go; "" for any other."""
    host = re.sub(r"^[a-z]+://", "", str(base_url or "").lower()).split("/", 1)[0]
    if host.endswith("ai-gateway.vercel.sh"):
        return "vercel"
    if host.endswith("openrouter.ai"):
        return "openrouter"
    if "tokenrouter" in host:
        return "tokenrouter"
    if host.endswith("api.openai.com"):
        return "openai"
    if host.endswith((".openai.azure.com", ".cognitiveservices.azure.com", ".services.ai.azure.com")):
        return "azure"
    if host.endswith("generativelanguage.googleapis.com"):
        return "google"
    if host.endswith("api.anthropic.com"):
        return "anthropic"
    return ""


def nearest(asked: str, have: tuple[str, ...] | list[str]) -> str:
    """The level in `have` closest to the one asked for, "" when there is none to give.

    `none` is only ever given to a turn that asked for it. A model that cannot be turned off gets
    its lowest level for `none`; a turn that asked for some thinking is never answered with none.
    A tie goes to the lower level."""
    if asked not in LEVELS or not have:
        return ""
    if asked in have:
        return asked
    on = [lv for lv in have if lv != "none"]
    if not on:
        return ""
    want = LEVELS.index(asked)
    return min(on, key=lambda lv: (abs(LEVELS.index(lv) - want), LEVELS.index(lv)))


def level_on(route: str, model: str, asked: str) -> str:
    """The level a model gets on a route for the one asked; "" when nothing is to be sent."""
    b = bare(model)
    have = list(levels_for(b))
    for r, pattern, lacks in _ROUTE_LACKS:
        if r == route and re.search(pattern, b):
            have = [lv for lv in have if lv not in lacks]
    if route == "tokenrouter" and b.startswith("gemini-") and not _TOKENROUTER_GEMINI.search(b):
        return ""
    return nearest(asked, have)


def _family(b: str) -> str:
    return "gpt" if b.startswith("gpt-") else "claude" if b.startswith("claude-") else \
        "gemini" if b.startswith("gemini-") else "other"


def _chat(doc: dict, route: str, b: str, level: str) -> bool:
    if _family(b) != "gemini" or route in ("openrouter", "google"):
        if route == "google" and level == "none" and "flash-lite" in b:
            return True                    # this model does not think unless asked to; "none" is refused there
        doc["reasoning_effort"] = level
        return True
    # A Gemini model through an aggregator that does not honour the field takes Google's own setting,
    # each aggregator under its own key.
    cfg = {"thinkingBudget": 0} if level == "none" else {"thinkingLevel": level}
    doc.pop("reasoning_effort", None)
    if route == "vercel":
        key, inner, value = "providerOptions", "thinkingConfig", cfg
    elif route == "tokenrouter":
        key, inner = "extra_body", "thinking_config"
        value = {"thinking_budget": 0} if level == "none" else {"thinking_level": level}
    else:
        return False
    outer = dict(doc[key]) if isinstance(doc.get(key), dict) else {}
    google = dict(outer["google"]) if isinstance(outer.get("google"), dict) else {}
    google[inner] = value
    outer["google"] = google
    doc[key] = outer
    return True


def _responses(doc: dict, b: str, level: str) -> bool:
    if _family(b) != "gpt":
        return False
    cur = doc.get("reasoning")
    doc["reasoning"] = {**(cur if isinstance(cur, dict) else {}), "effort": level}
    return True


def _messages(doc: dict, b: str, level: str) -> bool:
    """Anthropic's Messages API, as the API itself answered through a pass-through door: the older
    model takes a budget and refuses an effort, the newer ones the reverse, and the 5.5 line names
    its own way of turning thinking off."""
    if _family(b) != "claude":
        return False
    if level == "none":
        doc["thinking"] = {"type": "between_tools" if re.search(r"-5[.-]5", b) else "disabled"}
        return True
    if re.search(r"^claude-haiku-4", b):
        cap = doc.get("max_tokens")
        budget = _BUDGET.get(level, 1024)
        if isinstance(cap, int):
            budget = min(budget, cap // 2)      # the budget comes out of max_tokens; half is left to answer with
        if budget < 1024:                       # the API's floor
            return False
        doc["thinking"] = {"type": "enabled", "budget_tokens": budget}
        return True
    doc["thinking"] = {"type": "adaptive"}
    cur = doc.get("output_config")
    doc["output_config"] = {**(cur if isinstance(cur, dict) else {}), "effort": "max" if level == "xhigh" else level}
    return True


def _google(doc: dict, level: str) -> bool:
    """Google's own generateContent body: a level, or a budget of zero for off, never both."""
    gen = doc.setdefault("generationConfig", {})
    if not isinstance(gen, dict):
        return False
    cfg = gen.get("thinkingConfig")
    cfg = dict(cfg) if isinstance(cfg, dict) else {}
    cfg.pop("thinkingBudget", None)
    cfg.pop("thinkingLevel", None)
    if level == "none":
        cfg["thinkingBudget"] = 0
    else:
        cfg["thinkingLevel"] = level
    gen["thinkingConfig"] = cfg
    return True


def apply(body: bytes, shape: str, base_url: str, asked: str, model: str = "", route: str = "") -> tuple[bytes, str]:
    """One request body with the level a turn asked for → (the body to send, the level applied).

    `shape` is the API the body is written for: "chat" (Chat Completions), "responses", "messages"
    (Anthropic) or "google" (generateContent, whose model is in the URL and comes as `model`). The
    level applied is "" when nothing was sent: the model or the route was not measured, or the shape
    has no setting for the family. The body comes back as the same object in that case.

    `route` names the provider when the caller knows it and the base does not say: behind a broker
    every base is the broker's, and the gateway, which knows the connection, names the route. A
    name that is not one of ROUTES is no route."""
    if asked not in LEVELS or not body:
        return body, ""
    try:
        doc = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return body, ""
    if not isinstance(doc, dict):
        return body, ""
    b = bare(model or doc.get("model") or "")
    route = route if route in ROUTES else route_of(base_url)
    if not route:
        return body, ""
    if shape == "messages" and route not in ("anthropic", "tokenrouter", "vercel", "openrouter"):
        return body, ""
    level = level_on(route, b, asked)
    if not level:
        return body, ""
    if shape == "chat":
        done = _chat(doc, route, b, level)
    elif shape == "responses":
        done = _responses(doc, b, level)
    elif shape == "messages":
        done = _messages(doc, b, level)
    elif shape == "google":
        done = _family(b) == "gemini" and route in ("google", "tokenrouter") and _google(doc, level)
    else:
        done = False
    if not done:
        return body, ""
    return json.dumps(doc, separators=(",", ":")).encode(), level


def shape_of(path: str) -> str:
    """The API a request path belongs to; "" for anything that carries no model call."""
    p = str(path or "").split("?", 1)[0]
    if p.endswith("/chat/completions"):
        return "chat"
    if p.endswith("/responses"):
        return "responses"
    if p.endswith("/messages"):
        return "messages"
    if p.endswith((":generateContent", ":streamGenerateContent")):
        return "google"
    return ""
