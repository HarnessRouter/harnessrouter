"""A harness create/update field is understood under both of its spellings, and the bases document
says what the runtime defaults are.

#199: a client that mirrored the shape GET returns sent `defaultModel`; the server stored nothing
and answered 200 with `"defaultModel": ""`, so every task had to carry a model and the conformance
suite waited out its timeout per task. The schema names the create shape in snake_case and the
object in camelCase; a field the server understands under one is not an unknown field under the
other."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402


def test_the_camel_case_spelling_lands_on_the_same_field():
    b = gw.HarnessBody.model_validate({"name": "smoke-codex", "base": "codex", "defaultModel": "codex-tools",
                                       "maxStep": 50, "timeoutSeconds": 600, "systemPrompt": "be brief",
                                       "disabledTools": ["web_search"], "mcpServers": [], "additionalHeaders": ["X-Trace"]})
    assert b.default_model == "codex-tools" and b.max_step == 50 and b.timeout_seconds == 600
    assert b.system_prompt == "be brief" and b.disabled_tools == ["web_search"] and b.additional_headers == ["X-Trace"]


def test_the_schema_spelling_still_lands_and_the_object_shape_carries_it_back():
    b = gw.HarnessBody.model_validate({"name": "x", "base": "codex", "default_model": "codex-tools", "max_step": 7})
    assert b.default_model == "codex-tools" and b.max_step == 7
    assert gw._harness_props(b)["default_model"] == "codex-tools"


def test_the_defaults_are_one_number_each_and_the_console_is_told():
    """The turn's fallback and the number the console shows must be the same value from the same
    place, or a person is shown a limit that is not the one that applies."""
    assert gw.DEFAULT_MAX_STEP > 0 and gw.DEFAULT_TIMEOUT_S > 0
    src = open(os.path.join(os.path.dirname(__file__), "..", "app.py")).read()
    assert "or DEFAULT_MAX_STEP)" in src and " or 400)" not in src
    i = src.index("async def list_bases(")
    body = src[i:src.index("\n\n\n", i)]
    assert '"runtimeDefaults": {"maxStep": DEFAULT_MAX_STEP, "timeoutSeconds": DEFAULT_TIMEOUT_S}' in body
