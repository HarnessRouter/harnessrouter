"""A chain connection is held to the rule an integration is held to, before the runner is called.

The runner knows no provider called "custom": an integration maps it through the wiring to the
runner's own name (tokenrouter, openai-api) with api_format beside it, but a chain connection from
HR_SECRET_GLOBAL_HARNESS_CONN_* was sent verbatim, so a custom connector reached the runner as a
provider no backend has and its refusal came back in the runner's vocabulary (#201, reported by
master5d). The refusal is decided here, in the operator's words, and the provider is mapped as
an integration's is."""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402


def test_a_custom_chat_endpoint_cannot_drive_codex_and_the_reason_is_in_the_operators_words():
    conn = {"name": "x", "provider": "custom", "api_format": "openai", "base_url": "http://h:4000/v1", "api_key": "k"}
    why = gw._chain_refusal(conn, "codex")
    assert why == "a custom endpoint in the openai format cannot drive codex, which speaks the responses format"
    assert gw._chain_refusal({**conn, "api_format": "responses"}, "codex") == ""


def test_a_custom_endpoint_without_a_format_is_told_what_it_needs():
    assert gw._chain_refusal({"provider": "custom", "base_url": "http://h/v1"}, "pi").startswith("a custom endpoint needs api_format")


def test_a_custom_endpoint_reaches_the_runner_under_the_runners_name_with_its_format():
    conn = {"name": "x", "provider": "custom", "api_format": "openai", "base_url": "http://h/v1", "api_key": "k"}
    for backend in ("pi", "hermes", "aider", "codex"):
        assert gw._chain_refusal({**conn, "api_format": "openai" if backend != "codex" else "responses"}, backend) == ""
        wired = gw._chain_wired({**conn, "api_format": "openai" if backend != "codex" else "responses"}, backend)
        assert wired["provider"] == gw._INTEGRATION_WIRING[("custom", backend)] and wired["api_format"]
        assert wired["api_key"] == "k" and wired["base_url"] == "http://h/v1"


def test_a_catalog_provider_is_refused_where_the_wiring_has_no_row_and_named_where_it_has_one():
    assert gw._chain_refusal({"provider": "openai"}, "codex") == "" and gw._chain_wired({"provider": "openai"}, "codex")["provider"] == "openai"
    assert gw._chain_wired({"provider": "openai"}, "hermes")["provider"] == "openai-api"
    why = gw._chain_refusal({"provider": "typesafe"}, "codex")
    assert why.startswith("provider typesafe cannot drive codex; providers that can:") and "openai" in why


def test_a_runner_native_name_passes_untouched_and_the_runner_stays_its_judge():
    for conn in ({"provider": "openai-api", "base_url": "http://h/v1"}, {"provider": "azure"}, {"provider": "made-up"}):
        assert gw._chain_refusal(conn, "codex") == ""
        assert gw._chain_wired(conn, "codex") is conn
