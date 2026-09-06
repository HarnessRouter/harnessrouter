"""A Google AI Studio key is a provider: it serves the catalog's Gemini models on Gemini's
OpenAI-compatible surface for every backend that speaks that shape, and nothing else."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402


def test_google_serves_the_catalog_gemini_by_its_own_id():
    table = gw._vendor_models("google")
    # the Gemini chat family, each served by Google under its plain id (read from /v1beta/models 2026-09-06)
    assert set(table) == {"gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash",
                          "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.1-pro-preview",
                          "gemini-3-flash-preview", "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite"}
    assert all(k == v for k, v in table.items())
    assert gw._integration_models({"provider": "google"}) == gw._vendor_models("google")


def test_google_reaches_the_openai_shaped_backends_only():
    for backend in ("hermes", "pi", "dsh", "opencode", "qwen", "cline"):
        assert gw._INTEGRATION_WIRING[("google", backend)] == "openai-api", backend
    for backend in ("claude", "codex"):
        assert ("google", backend) not in gw._INTEGRATION_WIRING, backend


def test_google_is_listed_and_brokered_with_its_endpoint():
    assert "google" in {p for p, _ in gw._INTEGRATION_WIRING}
    assert "google" in gw._BROKERABLE_PROVIDERS
    conn = gw._with_provider_base({"provider": "google", "api_key": "k"})
    assert conn["base_url"] == "https://generativelanguage.googleapis.com/v1beta/openai"


# ── Gemini 3 thought signatures (2026-09-06) ──────────────────────────────────────────────
import json


def _delta(cid, sig=None):
    tc = {"id": cid, "type": "function", "function": {"name": "write_file", "arguments": "{}"}}
    if sig:
        tc["extra_content"] = {"google": {"thought_signature": sig}}
    return {"object": "chat.completion.chunk", "choices": [{"delta": {"tool_calls": [tc]}}]}


def test_signatures_are_read_off_a_chunk_and_a_whole_message():
    assert gw._google_signatures_in(_delta("call_1", "sigA")) == [("call_1", "sigA")]
    assert gw._google_signatures_in(_delta("call_1")) == []
    whole = {"object": "chat.completion", "choices": [{"message": {"tool_calls": [
        {"id": "call_2", "type": "function", "function": {"name": "f", "arguments": "{}"},
         "extra_content": {"google": {"thought_signature": "sigB"}}}]}}]}
    assert gw._google_signatures_in(whole) == [("call_2", "sigB")]


def test_the_tap_collects_signatures_as_the_stream_passes_and_off_a_whole_answer():
    tap = gw._GoogleSigTap("text/event-stream")
    line = b"data: " + json.dumps(_delta("call_9", "sigZ")).encode() + b"\n"
    tap.feed(line[:20]); tap.feed(line[20:])          # a signature split across two chunks
    assert tap.sigs == [("call_9", "sigZ")]
    tap.feed(b"data: [DONE]\n"); tap.finish()
    assert tap.sigs == [("call_9", "sigZ")]
    whole = gw._GoogleSigTap("application/json")
    body = json.dumps({"object": "chat.completion", "choices": [{"message": {"tool_calls": [
        {"id": "call_3", "type": "function", "function": {"name": "f", "arguments": "{}"},
         "extra_content": {"google": {"thought_signature": "sigC"}}}]}}]}).encode()
    whole.feed(body[:15]); whole.feed(body[15:])
    assert whole.sigs == []                             # a JSON answer is read once it has ended
    whole.finish()
    assert whole.sigs == [("call_3", "sigC")]


def test_the_replay_carries_the_seen_signature_or_the_sentinel():
    gw._GOOGLE_SIGS.clear()
    gw._google_remember("sidA", [("call_1", "sigA")])
    body = json.dumps({"model": "gemini-3.6-flash", "messages": [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "f", "arguments": "{}"}},
            {"id": "call_x", "type": "function", "function": {"name": "f", "arguments": "{}"}},
            {"id": "call_k", "type": "function", "function": {"name": "f", "arguments": "{}"},
             "extra_content": {"google": {"thought_signature": "kept"}}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "ok"}]}).encode()
    out = json.loads(gw._google_with_signatures(body, "sidA"))
    calls = out["messages"][1]["tool_calls"]
    assert calls[0]["extra_content"] == {"google": {"thought_signature": "sigA"}}
    assert calls[1]["extra_content"] == {"google": {"thought_signature": gw._GOOGLE_SIG_SKIP}}
    assert calls[2]["extra_content"] == {"google": {"thought_signature": "kept"}}
    assert out["messages"][2] == {"role": "tool", "tool_call_id": "call_1", "content": "ok"}
    # a signature seen under one session never serves another
    other = json.loads(gw._google_with_signatures(body, "sidB"))
    assert other["messages"][1]["tool_calls"][0]["extra_content"]["google"]["thought_signature"] == gw._GOOGLE_SIG_SKIP
    untouched = b'{"model": "gemini-3.6-flash", "messages": [{"role": "user", "content": "hi"}]}'
    assert gw._google_with_signatures(untouched, "sidA") is untouched


def test_the_table_is_bounded():
    gw._GOOGLE_SIGS.clear()
    gw._google_remember("s", [(f"c{i}", "x") for i in range(gw._GOOGLE_SIGS_MAX)])
    gw._google_remember("s", [("one-more", "y")])
    assert gw._GOOGLE_SIGS == {"s:one-more": "y"}


def test_llmtr_and_the_aggregators_carry_fable_5_1_and_llmtr_the_gemini_family():
    assert gw._VENDOR_MODELS["anthropic"]["claude-fable-5-1"] == "claude-fable-5-1"
    assert gw._VENDOR_MODELS["bedrock"]["claude-fable-5-1"] == "us.anthropic.claude-fable-5-1"
    for agg in ("tokenrouter", "openrouter", "vercel", "llmtr"):
        assert gw._VENDOR_MODELS[agg]["claude-fable-5-1"] == "anthropic/claude-fable-5.1", agg
    assert {m for m in gw._VENDOR_MODELS["llmtr"] if m.startswith("gemini")} == set(gw._VENDOR_MODELS["google"])
    for h, c in gw._MODEL_CATALOG.items():
        if "claude-fable-5" in c["models"]:
            assert "claude-fable-5-1" in c["models"], h


# ── Gemini function declarations through TokenRouter (2026-09-06) ─────────────────────────
def test_a_harness_tool_schema_is_normalised_to_googles_subset():
    cline_like = {"$schema": "http://json-schema.org/draft-07/schema#", "type": "object", "additionalProperties": False,
                  "properties": {"files": {"type": "array", "items": {"type": "object", "properties": {
                      "path": {"type": "string"}, "end_line": {"description": "line"},
                      "count": {"type": "integer", "exclusiveMinimum": 0},
                      "mode": {"oneOf": [{"const": "a"}, {"const": "b"}]},
                      "tag": {"type": ["string", "null"]}}, "required": ["path", "gone"]}},
                                 "opts": {"type": "object", "properties": {}}, "list": {"type": "array"}},
                  "required": ["files"]}
    out = gw._gemini_schema(cline_like)
    assert "$schema" not in out and "additionalProperties" not in out
    item = out["properties"]["files"]["items"]
    assert item["properties"]["end_line"] == {"description": "line", "type": "string"}
    assert item["properties"]["count"] == {"type": "integer", "minimum": 0}
    assert item["properties"]["mode"] == {"type": "string", "enum": ["a", "b"]}
    assert item["properties"]["tag"] == {"type": "string", "nullable": True}
    assert item["required"] == ["path"]
    assert out["properties"]["opts"] == {"type": "object"}
    assert out["properties"]["list"] == {"type": "array", "items": {"type": "string"}}


def test_only_tool_parameters_change_and_an_empty_declaration_is_dropped():
    body = json.dumps({"model": "google/gemini-3.8-flash", "messages": [{"role": "user", "content": "hi"}],
                       "tools": [{"type": "function", "function": {"name": "a", "parameters": {"$schema": "x", "type": "object", "properties": {"p": {"type": "string"}}}}},
                                 {"type": "function", "function": {"name": "b", "parameters": {"type": "object", "properties": {}}}}]}).encode()
    out = json.loads(gw._with_gemini_schemas(body))
    assert out["tools"][0]["function"]["parameters"] == {"type": "object", "properties": {"p": {"type": "string"}}}
    assert "parameters" not in out["tools"][1]["function"]
    assert out["messages"] == [{"role": "user", "content": "hi"}]
    plain = b'{"model": "google/gemini-3.8-flash", "messages": []}'
    assert gw._with_gemini_schemas(plain) is plain


def test_a_nullable_choice_gets_a_type():
    # zod's optional integer: anyOf [integer, null] with no type; the 3.5-flash channel refuses it without one
    assert gw._gemini_schema({"anyOf": [{"type": "integer"}, {"type": "null"}], "description": "line"}) == {"type": "integer", "nullable": True, "description": "line"}
    two = gw._gemini_schema({"anyOf": [{"type": "string"}, {"type": "integer"}, {"type": "null"}], "description": "either"})
    assert two == {"type": "string", "nullable": True, "description": "either"}      # no anyOf leaves the relay
    assert gw._gemini_schema({"anyOf": [{"type": "null"}]}) == {"type": "string", "nullable": True}
