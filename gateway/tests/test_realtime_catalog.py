"""The realtime base: what the catalog promises is what the router and the runner can run.

A realtime speech model is reached over a WebSocket and answers no chat call, so its id lives in
the one vendor table whose provider the base is wired to, and only the realtime base lists it.
The base has nothing built in: no tools of its own, no skills, no environment layer. Its
connection's key stays on the runner's relay, which the broker cannot stand in for, so a brokered
connection is refused in words.
"""
import asyncio
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "runner"))
import realtime_backend  # noqa: E402

MODEL = "gpt-realtime-2.1"


def test_the_model_is_on_the_one_provider_the_base_is_wired_to_and_nowhere_else():
    assert gw._VENDOR_MODELS["azure-foundry"][MODEL] == MODEL
    assert gw._provider_model_id("azure-foundry", MODEL) == MODEL
    assert gw._provider_model_id("azure", MODEL) == MODEL        # the runner's name for the same vendor
    for vendor, table in gw._VENDOR_MODELS.items():
        if vendor != "azure-foundry":
            assert MODEL not in table, f"{vendor} lists a realtime model nothing reaches through it"


def test_only_the_realtime_base_offers_it_and_it_offers_nothing_else():
    assert gw._MODEL_CATALOG["realtime"] == {"default": MODEL, "models": [MODEL]}
    for backend, cat in gw._MODEL_CATALOG.items():
        if backend != "realtime":
            assert MODEL not in cat.get("models", []), f"{backend} offers a model that answers no chat call"
    # still qualifying: this instance's own provider column has not run
    assert "realtime" in gw._STILL_QUALIFYING


def test_the_gateway_and_the_runner_name_the_same_default_and_the_same_providers():
    assert gw._MODEL_CATALOG["realtime"]["default"] == realtime_backend.DEFAULT_MODEL
    wired = {k[0]: v for k, v in gw._INTEGRATION_WIRING.items() if k[1] == "realtime"}
    assert wired == {"azure-foundry": "azure"}
    # what the runner is told the provider is, for every wiring row, is a provider it builds a turn for
    for wire in wired.values():
        assert gw._RUNNER_VENDOR.get(wire, wire) in realtime_backend.PROVIDERS
    # and every provider the runner builds for has a row, so none is unreachable
    assert {gw._RUNNER_VENDOR.get(w, w) for w in wired.values()} == realtime_backend.PROVIDERS


def test_an_azure_connection_drives_the_base_and_no_other_provider_claims_to():
    assert gw._integration_serves_backend({"provider": "azure-foundry"}, "realtime")
    for provider in ("openai", "openrouter", "tokenrouter", "vercel", "llmtr", "anthropic", "google",
                     "harnessrouter", "typesafe", "qoder"):
        assert not gw._integration_serves_backend({"provider": provider}, "realtime"), provider
    # no custom format speaks the realtime socket
    for fmt in gw._CUSTOM_FORMAT_BACKENDS:
        assert "realtime" not in gw._CUSTOM_FORMAT_BACKENDS[fmt]
        assert not gw._integration_serves_backend({"provider": "custom", "config": {"api_format": fmt}}, "realtime")


def test_the_base_is_in_the_catalog_with_nothing_built_in():
    b = gw._BASE_CATALOG["realtime"]
    assert b["backend"] == "realtime" and b["status"] == "ready" and b["label"] == "Realtime Harness"
    assert b["tools"] == []                     # its tools are its MCP servers'; nothing is built in
    assert b["tool_enforcement"] == "hard"      # a disabled tool is left out of the session's tool list
    assert b["system_prompt"].strip()
    assert gw._backend_of_builtin("realtime") == "realtime"
    assert "realtime" in gw._SUPPORTED_BASES
    assert not b.get("remote")                  # one process per turn on this box


def test_the_base_takes_no_skills_and_none_are_mounted_for_a_turn(monkeypatch):
    assert gw._BASE_CATALOG["realtime"]["skills"] is False
    assert not gw._base_takes_skills("realtime")
    monkeypatch.setattr(gw, "_builtin_skills", lambda: {"pdf": {"title": "PDF", "description": "", "default_enabled": True,
                                                                  "origin": "image", "files": [{"path": "SKILL.md", "content": "x"}]}})
    _, skills, _, _, _ = asyncio.run(gw._harness_plugins("realtime", "local", None, hv=None))
    assert skills == []


def test_the_base_mounts_no_environment_layer(monkeypatch):
    assert gw._BASE_CATALOG["realtime"]["environments"] is False
    assert not gw._backend_takes_environments("realtime")
    assert gw._backend_takes_environments("codex")

    # and the console is told so, with the rest of what the base does not take
    async def org_member(_request):
        return "local", "owner"

    async def servable(_org, _backend):
        return set()

    monkeypatch.setattr(gw, "_pub_org_member", org_member)
    monkeypatch.setattr(gw, "_servable_models", servable)
    base = {b["id"]: b for b in asyncio.run(gw.list_bases(None))["bases"]}["realtime"]
    assert base["takesEnvironments"] is False and base["takesSkills"] is False
    assert base["tools"] == [] and base["builtinSkills"] == []


def test_a_brokered_connection_is_refused_rather_than_dialled_at_the_broker(monkeypatch):
    """The driver mints a client secret through the runner's relay and opens the provider's socket
    itself. The broker carries neither, and the base a brokered turn is handed is the broker's
    address, where no realtime socket answers. So the turn's connection is refused before a
    process starts: with a key in owner trust it is handed over; brokered (an Entra sign-in, or
    any connection outside owner trust) it is not built at all."""
    assert "realtime" in gw._NATIVE_ONLY_BACKENDS
    key = {"name": "az", "backend": "realtime", "provider": "azure-foundry", "api_key": "k-0123456789",
           "base_url": "https://res.openai.azure.com"}
    monkeypatch.setattr(gw, "SANDBOX_TRUST", "owner")
    out = gw._auth_from_conn(key, "sess_1")
    assert out["api_key"] == "k-0123456789"
    assert out["base_url"] == "https://res.openai.azure.com/openai/v1"      # the base the socket is derived from
    assert realtime_backend.socket_url(out["base_url"], MODEL) == \
        "wss://res.openai.azure.com/openai/v1/realtime?model=gpt-realtime-2.1"
    entra = {"name": "az", "backend": "realtime", "provider": "azure-foundry", "auth": "entra",
             "tenant_id": "t", "client_id": "c", "client_secret": "s", "base_url": "https://res.openai.azure.com"}
    assert gw._auth_from_conn(entra, "sess_1") is None
    monkeypatch.setattr(gw, "SANDBOX_TRUST", "")
    assert gw._auth_from_conn(key, "sess_1") is None


def test_a_deployment_named_otherwise_is_reached_by_the_connections_own_row(monkeypatch):
    """On Azure the id on the wire is the deployment's name, which whoever made the resource chose.
    The table sends the model id itself; a connection whose deployment has another name says so in
    a model row, and that name is what the turn is given and what the socket asks for."""
    integ = {"name": "az", "provider": "azure-foundry", "rows_v": 2,
             "config": {"api_key": "k-0123456789", "base_url": "https://res.openai.azure.com"},
             "models": [{"canonical": MODEL, "provider_id": "gpt-realtime-2-1"}]}

    async def docs(*_a, **_k):
        return [integ]

    async def model_map():
        return {MODEL: "az"}

    monkeypatch.setattr(gw, "_integrations_doc", docs)
    monkeypatch.setattr(gw, "_effective_model_map", model_map)
    monkeypatch.setattr(gw, "SANDBOX_TRUST", "owner")
    conn = asyncio.run(gw._mapped_integration_conn("realtime", MODEL))
    assert conn["provider"] == "azure" and conn["model"] == "gpt-realtime-2-1" and conn["_model_resolved"] is True
    base = gw._auth_from_conn(conn, "sess_1")["base_url"]
    assert realtime_backend.socket_url(base, conn["model"]) ==         "wss://res.openai.azure.com/openai/v1/realtime?model=gpt-realtime-2-1"
    # without a row, the model id is the deployment's name
    integ["models"] = []
    assert asyncio.run(gw._mapped_integration_conn("realtime", MODEL))["model"] == MODEL


def test_setup_never_picks_it_automatically(monkeypatch):
    """Auto builds an agent that reads skills from a workspace; this base takes none."""
    async def servable(_org, _backend):
        return None

    monkeypatch.setattr(gw, "_servable_models", servable)
    bases = asyncio.run(gw._setup_bases("local"))
    if "realtime" in bases:                     # absent where the instance did not install it
        assert bases["realtime"]["auto"] is False and bases["realtime"]["skills"] is False
        assert bases["realtime"]["default"] == MODEL
