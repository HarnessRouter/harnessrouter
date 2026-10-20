"""W3C trace context (https://www.w3.org/TR/trace-context/) for a turn: the caller's `traceparent`
and `tracestate`, checked, and the child `traceparent` the relay sends on a model call.

A caller with distributed tracing sends these on POST /v1/responses. The gateway keeps the pair on
the turn and hands it to the runner's /turn; the runner puts it in the CLI's environment
(TRACEPARENT, TRACESTATE, the names OpenTelemetry-aware tools read) and on each model call its relay
forwards, as a child: the same trace id, a new span id, the sampled flag kept. Only these two
headers ever leave: `baggage` and any other context can carry the caller's data to a model
provider, so nothing else is read.

A value that is not W3C syntax is dropped, never refused: tracing is the caller's, and a turn does
not fail over it. No header in means nothing out.

Pure functions, no imports from the runner: the runner applies them (runner/server.py), and the
gateway loads this file by path (gateway/app.py), as it does runner/reasoning.py.
"""
from __future__ import annotations

import re
import secrets

# version-traceid-parentid-flags, lowercase hex. A version above 00 may carry more fields after a
# dash; only the four known ones are read, and only version 00 is ever written.
_TRACEPARENT = re.compile(r"([0-9a-f]{2})-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})(-.*)?")
# One list-member: a key (simple, or tenant@system) and a value of printable ASCII without ',' or '='.
_TRACESTATE_MEMBER = re.compile(
    r"(?:[a-z][a-z0-9_\-*/]{0,255}|[a-z0-9][a-z0-9_\-*/]{0,240}@[a-z][a-z0-9_\-*/]{0,13})"
    r"=[\x20-\x2b\x2d-\x3c\x3e-\x7e]{0,255}[\x21-\x2b\x2d-\x3c\x3e-\x7e]")
_TRACESTATE_MAX = 512


def _traceparent(value) -> str:
    """The traceparent when it is valid W3C syntax, else ""."""
    v = str(value or "").strip()
    m = _TRACEPARENT.fullmatch(v)
    if not m:
        return ""
    version, trace_id, parent_id, _flags, rest = m.groups()
    if version == "ff" or (version == "00" and rest):
        return ""
    if trace_id == "0" * 32 or parent_id == "0" * 16:
        return ""
    return v


def _tracestate(value) -> str:
    """The tracestate when it is valid W3C syntax, else "". Empty members are allowed and dropped."""
    v = str(value or "").strip()
    if not v or len(v) > _TRACESTATE_MAX:
        return ""
    members = [p.strip() for p in v.split(",")]
    members = [p for p in members if p]
    if not members or len(members) > 32:
        return ""
    if not all(_TRACESTATE_MEMBER.fullmatch(p) for p in members):
        return ""
    return ",".join(members)


def parse(traceparent, tracestate=None) -> dict:
    """{"traceparent": ..., "tracestate": ...} with only what is valid; {} when the traceparent is
    missing or invalid, since a tracestate means nothing without one."""
    tp = _traceparent(traceparent)
    if not tp:
        return {}
    ts = _tracestate(tracestate)
    return {"traceparent": tp, **({"tracestate": ts} if ts else {})}


def child(traceparent: str) -> str:
    """A child of `traceparent`: the same trace id, a new span id, the sampled flag kept. "" when the
    parent is not valid."""
    tp = _traceparent(traceparent)
    if not tp:
        return ""
    _version, trace_id, _parent, flags = tp.split("-")[:4]
    span = secrets.token_hex(8)
    while span == "0" * 16:
        span = secrets.token_hex(8)
    return f"00-{trace_id}-{span}-{int(flags, 16) & 0x01:02x}"


def trace_id(traceparent: str) -> str:
    """The trace id of a valid traceparent, "" otherwise."""
    tp = _traceparent(traceparent)
    return tp.split("-")[1] if tp else ""
