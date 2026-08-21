"""A failed Response must validate against the spec's Error object.

The schema (protocol/schema/uhp-2026-08-11.schema.json, $defs.Error) requires `type` from a
closed enum plus `code` and `message`. The gateway used to emit {"code": "harness_error",
"message": ...} — the type in the code slot and no type at all — so EVERY failed turn produced
a spec-invalid Response. Nothing noticed until a conformance run actually failed a turn
(TokenRouter rejecting hermes's empty text block, LLMTR rejecting dsh's reasoning_effort,
both 2026-08-20): T-01/S-03/S-07 then flagged the envelope rather than just the failure.

This validates the envelope at the source, so the invariant holds without a live failing turn.
"""
from __future__ import annotations

import json
import os
import re
import sys

import jsonschema
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCHEMA = os.path.join(_ROOT, "protocol", "schema", "uhp-2026-08-11.schema.json")
_APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


def _error_schema() -> dict:
    s = json.load(open(_SCHEMA))
    return {"$defs": s["$defs"], **s["$defs"]["Error"]}


def _resp_translator():
    """Import lazily: app.py wants env + network at import time in some configurations."""
    from app import _RespTranslator
    return _RespTranslator


def test_failed_turn_error_validates_against_the_spec():
    tr = _resp_translator()("resp_test", "some-model", None, False, 0.0)
    tr.fail("provider said no")
    jsonschema.validate(tr.error, _error_schema())
    assert tr.error["type"] == "harness_error"
    assert tr.error["code"] == "turn_failed"


def test_failed_response_object_validates_end_to_end():
    s = json.load(open(_SCHEMA))
    tr = _resp_translator()("resp_test", "some-model", None, False, 0.0)
    tr.fail("provider said no")
    obj = tr._response_obj("failed")
    jsonschema.validate(obj, {"$defs": s["$defs"], **s["$defs"]["Response"]})


def test_every_error_assignment_in_source_carries_a_spec_type():
    """The other emission sites build their dicts inline with runtime values, so they are
    checked at the source: every `.error = {...}` literal must lead with a `type` from the
    spec's enum — the shape that was missing everywhere before this test existed."""
    src = open(_APP).read()
    enum = {"invalid_request_error", "authentication_error", "permission_error",
            "rate_limit_error", "harness_error", "server_error"}
    sites = re.findall(r'\.error = \{("(?:type|code)": "[a-z_]+")', src)
    assert sites, "no error assignments found — the pattern moved, update this test"
    for lead in sites:
        key, val = re.match(r'"(\w+)": "([a-z_]+)"', lead).groups()
        assert key == "type" and val in enum, f".error literal leads with {lead}, not a spec type"
