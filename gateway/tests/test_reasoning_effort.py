"""How much a model thinks on a turn, on the gateway side: the request's `reasoning.effort`, the
harness's `reasoning_effort`, what /v1/bases offers per model, and the turn's record of what was
asked and what was applied. A turn and a harness that set neither read exactly as they did before."""
import asyncio
import os
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402


def test_a_level_is_one_of_six_and_anything_else_is_refused_where_it_was_sent():
    assert [gw._reasoning_level(v, "reasoning.effort") for v in ("low", " High ", "", None)] == ["low", "high", "", ""]
    with pytest.raises(HTTPException) as e:
        gw._reasoning_level("maximum", "reasoning.effort")
    assert e.value.status_code == 400 and "none, minimal, low, medium, high, xhigh" in e.value.detail
    assert gw._reasoning_level("maximum") == ""        # a stored value that is not a level asks for nothing


def test_the_request_takes_the_responses_apis_own_field_and_it_is_part_of_what_the_request_is():
    plain = gw.CreateResponseBody(model="gpt-5.4", input="hi")
    low = gw.CreateResponseBody(model="gpt-5.4", input="hi", reasoning={"effort": "low"})
    high = gw.CreateResponseBody(model="gpt-5.4", input="hi", reasoning={"effort": "high"})
    assert low.reasoning == {"effort": "low"}
    # an Idempotency-Key reused with another level is another request...
    assert len({gw._req_hash(plain), gw._req_hash(low), gw._req_hash(high)}) == 3
    # ...and a request without a level hashes as it did before the field existed
    src = open(os.path.join(os.path.dirname(__file__), "..", "app.py")).read()
    assert '**({"reasoning": body.reasoning} if body.reasoning else {})' in src


def test_a_harness_keeps_a_default_level_under_either_spelling():
    body = gw.HarnessBody(name="h", base="codex", reasoning_effort="low")
    assert gw._harness_props(body)["reasoning_effort"] == "low"
    assert gw._harness_props(gw.HarnessBody(name="h", base="codex", reasoningEffort="High"))["reasoning_effort"] == "high"
    assert gw._harness_props(gw.HarnessBody(name="h", base="codex"))["reasoning_effort"] == ""
    with pytest.raises(HTTPException) as e:
        gw._harness_props(gw.HarnessBody(name="h", base="codex", reasoning_effort="lots"))
    assert e.value.status_code == 400 and "reasoning_effort must be one of" in e.value.detail
    assert gw._harness_out({"id": "hrn_1", "name": "h", "base": "codex", "reasoning_effort": "low"})["reasoningEffort"] == "low"
    assert gw._harness_out({"id": "hrn_1", "name": "h", "base": "codex"})["reasoningEffort"] == ""


def test_the_turns_own_level_wins_over_the_harnesss_and_neither_asks_nothing():
    src = open(os.path.join(os.path.dirname(__file__), "..", "app.py")).read()
    i = src.index("effort = (_reasoning_level((body.reasoning or {}).get(\"effort\")")
    rule = src[i:src.index("\n", src.index("or _reasoning_level((hv or {}).get(\"reasoning_effort\")))", i))]
    assert rule.index("body.reasoning") < rule.index('(hv or {}).get("reasoning_effort")')
    # the runner is told a level or nothing: None leaves its request as it was
    assert '"reasoning_effort": effort or None,' in src
    # ...and which measured provider the connection is, read off the connection's own base, since
    # in broker trust the base the runner is handed is this gateway's
    assert '"reasoning_route": (reasoning.route_of(str((_with_provider_base(conn) or {}).get("base_url") or ""))' in src
    assert gw.reasoning.route_of(gw._with_provider_base({"provider": "google"})["base_url"]) == "google"
    assert gw.reasoning.route_of(gw._with_provider_base({"provider": "openai"})["base_url"]) == "openai"


def test_the_record_says_what_was_asked_at_once_and_what_was_applied_when_the_result_comes():
    tr = gw._RespTranslator("resp_1", "gpt-5.4", None, True, 0.0)
    assert tr._response_obj("in_progress")["reasoning"] is None          # a turn that asked for no level
    tr.reasoning = {"effort": "minimal", "applied": None}                # set when the turn is created
    assert tr._response_obj("in_progress")["reasoning"] == {"effort": "minimal", "applied": None}
    tr.feed({"type": "result", "result": "ok", "reasoning": {"effort": "minimal", "applied": "low"},
             "usage": {"input_tokens": 5, "output_tokens": 9, "reasoning_tokens": 7}})
    done = tr._response_obj("completed")
    assert done["reasoning"] == {"effort": "minimal", "applied": "low"}
    # the provider's own count of thinking tokens, where the Responses API keeps it
    assert done["usage"]["output_tokens_details"] == {"reasoning_tokens": 7}
    assert done["usage"]["output_tokens"] == 9


def test_a_turn_that_asked_for_no_level_reads_as_it_did_before():
    ev = {"type": "result", "result": "PONG", "usage": {"input_tokens": 1, "output_tokens": 1}}
    kinds = gw._blocks_from_canonical(ev)
    assert kinds and all("reasoning" not in payload for _, payload in kinds)
    tr = gw._RespTranslator("resp_2", "gpt-5.4", None, True, 0.0)
    tr.feed(ev)
    done = tr._response_obj("completed")
    assert done["reasoning"] is None and "output_tokens_details" not in done["usage"]


def test_bases_say_which_levels_each_model_has_and_none_where_none_was_measured(monkeypatch):
    async def servable(org, backend):
        return set(gw._MODEL_CATALOG.get(backend, {}).get("models") or [])

    async def who(request):
        return "org1", "m1"

    monkeypatch.setattr(gw, "_servable_models", servable)
    monkeypatch.setattr(gw, "_pub_org_member", who)
    out = asyncio.run(gw.list_bases(None))
    by_base = {b["id"]: {m["id"]: m["reasoning"] for m in b["models"]} for b in out["bases"]}
    codex = by_base["codex"]
    assert codex["gpt-5.4"] == ["none", "low", "medium", "high", "xhigh"]
    assert codex["gpt-6.1-sol"] == ["low", "medium", "high", "xhigh"]          # cannot be turned off
    listed = {m: lv for models in by_base.values() for m, lv in models.items()}
    assert listed["claude-haiku-4.5"][0] == "none" and listed["gemini-3.8-flash"] == ["low", "medium", "high"]
    assert listed["llama-3.3-70b"] == [] and listed["glm-5.3"] == []
    for model, levels in listed.items():
        assert all(lv in gw.reasoning.LEVELS for lv in levels), model


def test_the_levels_come_from_the_runners_table_not_a_second_one():
    assert gw.reasoning.__file__.replace(os.sep, "/").endswith("runner/reasoning.py")
    assert gw.reasoning.levels_for("openai/gpt-5.4") == ("none", "low", "medium", "high", "xhigh")
