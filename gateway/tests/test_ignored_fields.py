"""A field the gateway did not act on is named on the response.

Tasks §1.4 makes `tools` and `include` reserved: accepted, never acted on. §1.1 makes ignoring
observable — the response MUST name them in `metadata.ignored_fields`. The gateway already did the
first half (it reads `tools` only for the idempotency hash and never for routing or execution) and
none of the second, so a client sending either field got a response indistinguishable from one
where the field had been honoured.

These test the metadata at the source, so the invariant holds without a live turn, and they check
both directions: a field that was sent is reported, and a field that was not sent is not.
"""
from __future__ import annotations

import json
import os
import sys

import jsonschema

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCHEMA = os.path.join(_ROOT, "protocol", "schema", "uhp-2026-08-11.schema.json")


def _response_schema() -> dict:
    s = json.load(open(_SCHEMA))
    return {"$defs": s["$defs"], **s["$defs"]["Response"]}


def _translator(**kw):
    from app import _RespTranslator
    return _RespTranslator("resp_test", "some-model", None, True, 0.0, **kw)


def test_a_reserved_field_that_was_sent_is_reported():
    tr = _translator(ignored=["tools", "include"])
    meta = tr._response_obj("completed")["metadata"]
    assert meta["ignored_fields"] == ["tools", "include"]


def test_a_request_that_sent_neither_is_not_told_one_was_ignored():
    """The opposite mistake, and just as misleading: a hardcoded list tells a caller their request
    was altered when it was not."""
    meta = _translator()._response_obj("completed")["metadata"]
    assert "ignored_fields" not in meta


def test_only_the_fields_actually_sent_are_named():
    meta = _translator(ignored=["include"])._response_obj("completed")["metadata"]
    assert meta["ignored_fields"] == ["include"]


def test_the_response_still_validates_against_the_spec():
    tr = _translator(ignored=["tools", "include"])
    jsonschema.validate(tr._response_obj("completed"), _response_schema())


def test_the_selection_matches_what_the_request_carried():
    """Mirrors the expression in the /v1/responses path: a field is ignored when it is present,
    and `None` means the client did not send it."""
    class Body:
        tools = [{"type": "function", "name": "x"}]
        include = None

    assert [f for f in ("tools", "include") if getattr(Body, f, None) is not None] == ["tools"]
