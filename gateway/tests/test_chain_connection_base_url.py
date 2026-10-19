"""A connection set from the ENVIRONMENT must reach the runner with its provider's endpoint.

THE BUG, measured while bringing up the support matrix for this batch (2026-10-19). A Vercel
connection written the way the self-hosting guide documents for a scripted deploy —

    HR_SECRET_GLOBAL_HARNESS_CONN_VERCEL={"name":"vercel","provider":"vercel","api_key":"…"}
    HR_SECRET_GLOBAL_HARNESS_POLICY_VIBE={"chain":["vercel"]}

— ran a turn that failed in the RUNNER's vocabulary: `The turn failed: vibe provider
'tokenrouter' needs a base_url (none configured)`. The integrations form supplies a known
provider's base_url on save ("A provider whose endpoint we know supplies its own base_url"), and
nothing did the same for a chain connection, so the operator was asked for nothing and given no
endpoint. Every backend whose provider type needs a base — which is most of them — failed on that
documented path, for vercel, tokenrouter, harnessrouter, google, openrouter and llmtr alike.

The rename is the trap in the fix: the runner's name for a Vercel connection is `tokenrouter`,
whose own endpoint is api.tokenrouter.com. The catalog has to be read under the connection's own
provider name, before the rename, or the turn goes to the wrong vendor with the right key.
"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as A  # noqa: E402


def test_a_vercel_connection_from_the_environment_carries_vercels_endpoint():
    out = A._chain_wired({"name": "vercel", "provider": "vercel", "api_key": "k"}, "vibe")
    assert out["provider"] == "tokenrouter"          # the runner's name for it
    assert out["base_url"] == "https://ai-gateway.vercel.sh/v1"
    assert out["api_key"] == "k"


def test_the_endpoint_is_the_connections_vendor_and_not_the_runners_provider_name():
    # tokenrouter is the runner's name for several aggregators; its own base must not be handed
    # to a connection that is not TokenRouter
    for provider, base in (("vercel", "https://ai-gateway.vercel.sh/v1"),
                           ("llmtr", "https://llmtr.com/v1"),
                           ("openrouter", "https://openrouter.ai/api/v1"),
                           ("tokenrouter", "https://api.tokenrouter.com/v1")):
        out = A._chain_wired({"name": provider, "provider": provider, "api_key": "k"}, "vibe")
        assert out["base_url"] == base, (provider, out["base_url"])


def test_every_catalog_provider_with_a_known_endpoint_gets_it_on_every_backend_it_drives():
    for (provider, backend), _runner in A._INTEGRATION_WIRING.items():
        known = (A._PROVIDER_CATALOG.get(provider) or {}).get("base_url")
        if not known:
            continue                                  # per-deployment (Azure, Bedrock): asked for
        out = A._chain_wired({"name": provider, "provider": provider, "api_key": "k"}, backend)
        assert out.get("base_url") == known, (provider, backend, out.get("base_url"))


def test_an_operators_own_base_url_is_never_overwritten():
    out = A._chain_wired({"name": "mine", "provider": "openai", "api_key": "k",
                          "base_url": "https://proxy.example/v1"}, "vibe")
    assert out["base_url"] == "https://proxy.example/v1"


def test_a_provider_the_catalog_does_not_know_is_left_exactly_as_written():
    # a runner-native name (openai-api, azure) stays the runner's to judge, as before
    conn = {"name": "raw", "provider": "openai-api", "api_key": "k"}
    assert A._chain_wired(dict(conn), "vibe") == conn


def test_a_provider_whose_endpoint_is_per_deployment_is_still_asked_for():
    conn = {"name": "az", "provider": "azure-foundry", "api_key": "k"}
    out = A._chain_wired(dict(conn), "vibe")
    assert "base_url" not in out or not out["base_url"]
    assert out["provider"] == "azure"


def test_the_fix_does_not_mutate_the_stored_connection():
    conn = {"name": "vercel", "provider": "vercel", "api_key": "k"}
    A._chain_wired(conn, "vibe")
    assert conn == {"name": "vercel", "provider": "vercel", "api_key": "k"}


def test_a_connection_with_nothing_to_change_is_the_same_object():
    # test_chain_pairing asks for identity here, and the fill must not quietly start copying
    conn = {"provider": "openai-api", "base_url": "http://h/v1"}
    assert A._chain_wired(conn, "codex") is conn
