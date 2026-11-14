"""The Antigravity CLI (agy) on the gateway side: opt-in, wired to Google's own endpoint only, its models and
levels the runner's, its switches labelled for what they withhold, and what a person should know said in
their words."""
import asyncio
import os
import pathlib
import re
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as A  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "runner"))
import server as R  # noqa: E402


def test_agy_is_wired_to_googles_own_endpoint_and_nothing_else():
    assert A._INTEGRATION_WIRING[("google", "agy")] == "google"
    assert [p for (p, b) in A._INTEGRATION_WIRING if b == "agy"] == ["google"]
    assert "agy" in A._NATIVE_ONLY_BACKENDS
    for fmt, backends in A._CUSTOM_FORMAT_BACKENDS.items():
        assert "agy" not in backends, fmt
    assert A._backend_of_builtin("agy") == "agy"


def test_the_key_is_refused_to_a_brokered_sandbox_and_held_by_the_runner_in_owner_trust(monkeypatch):
    conn = {"name": "integration:Google AI Studio", "backend": "agy", "provider": "google", "api_key": "AIza-t"}
    monkeypatch.setattr(A, "SANDBOX_TRUST", "broker")
    monkeypatch.setattr(A, "PUBLIC_BASE_URL", "https://hr.example")
    assert A._auth_from_conn(conn, "sid1") is None
    monkeypatch.setattr(A, "SANDBOX_TRUST", "owner")
    assert A._auth_from_conn(conn, "sid1")["api_key"] == "AIza-t"      # to the runner, whose relay keeps it


AGY_ONLY = {"gemini-4-hydrogen", "gemini-4-carbon"}


def test_the_models_are_the_clis_on_a_gemini_key_and_each_is_served_as_itself():
    cat = A._MODEL_CATALOG["agy"]
    assert cat["default"] == R.AGY_DEFAULT_MODEL == "gemini-3.8-flash" and cat["default"] in cat["models"]
    # Google's table, plus the two the CLI names that only this base offers
    assert set(cat["models"]) <= set(A._VENDOR_MODELS["google"]) | A._CHANNEL_ALSO_SERVES[("google", "agy")]
    # every catalog id is one the CLI offers, under its own name where it differs
    assert {R.AGY_IDS.get(m, m) for m in cat["models"]} <= set(R.AGY_MODEL_LEVELS)
    # Google answers gemini-3.7-flash as gemini-3.8-flash: never offered as itself
    assert not set(cat["models"]) & A._GOOGLE_ANSWERS_AS_ANOTHER
    assert "agy" in A._STILL_QUALIFYING


def test_hydrogen_and_carbon_are_offered_on_this_base_under_the_clis_own_ids():
    cat = A._MODEL_CATALOG["agy"]
    assert AGY_ONLY <= set(cat["models"])
    assert AGY_ONLY <= set(R.AGY_MODEL_LEVELS)                          # the CLI's own ids, as `agy models` lists them
    assert not AGY_ONLY & set(R.AGY_IDS)                                # sent to the CLI as they are
    assert A._CHANNEL_ALSO_SERVES[("google", "agy")] == AGY_ONLY
    # the family stays together, Argon still leading it
    gem = [m for m in cat["models"] if m.startswith("gemini")]
    assert gem[:3] == ["gemini-4-argon", "gemini-4-carbon", "gemini-4-hydrogen"]
    # the shared table is untouched: no other base and no other connection is offered either
    assert not AGY_ONLY & set(A._VENDOR_MODELS["google"])
    for backend, c in A._MODEL_CATALOG.items():
        if backend != "agy":
            assert not AGY_ONLY & set(c["models"]), backend
    assert [k for k in A._CHANNEL_ALSO_SERVES if AGY_ONLY & A._CHANNEL_ALSO_SERVES[k]] == [("google", "agy")]


def _google(monkeypatch, *, chain=(), integration=True):
    """A Google AI Studio key as an integration, or (chain=["google"], integration=False) as a chain connection."""
    integ = {"name": "Google AI Studio", "provider": "google", "config": {"api_key": "AIza-t"}}

    async def docs():
        return [integ] if integration else []

    async def mm():
        return {m: integ["name"] for m in A._integration_models(integ)} if integration else {}

    async def resolve(_org, _backend, _explicit):
        return list(chain)

    async def get_conn(_org, _name):
        return {"provider": "google", "api_key": "AIza-t"}, None

    monkeypatch.setattr(A, "_integrations_doc", docs)
    monkeypatch.setattr(A, "_effective_model_map", mm)
    monkeypatch.setattr(A, "_resolve_chain", resolve)
    monkeypatch.setattr(A, "_get_connection", get_conn)


def test_a_google_integration_serves_the_two_on_this_base_and_on_no_other(monkeypatch):
    _google(monkeypatch)
    got = asyncio.run(A._servable_models("org", "agy"))
    assert AGY_ONLY <= got and {"gemini-4-argon", "gemini-3.8-flash"} <= got
    assert not AGY_ONLY & asyncio.run(A._servable_models("org", "gemini"))
    for m in sorted(AGY_ONLY):
        conn = asyncio.run(A._mapped_integration_conn("agy", m))
        assert conn and conn["name"] == "integration:Google AI Studio" and conn["provider"] == "google", m
        assert A._map_model(conn, m) == m                               # Google's id is the CLI's
        assert asyncio.run(A._mapped_integration_conn("gemini", m)) is None
    # a model nothing names is still refused
    assert asyncio.run(A._mapped_integration_conn("agy", "gemini-9-nope")) is None


def test_a_google_chain_connection_serves_the_two_on_this_base_and_on_no_other(monkeypatch):
    _google(monkeypatch, chain=["google"], integration=False)
    got = asyncio.run(A._servable_models("org", "agy"))
    assert AGY_ONLY <= got
    assert not AGY_ONLY & asyncio.run(A._servable_models("org", "gemini"))
    conn = {"provider": "google"}
    assert A._conn_serves(conn, "gemini-4-hydrogen", "agy") and A._conn_serves(conn, "gemini-4-carbon", "agy")
    assert not A._conn_serves(conn, "gemini-4-hydrogen", "gemini") and not A._conn_serves(conn, "gemini-4-carbon")
    assert not A._conn_serves({"provider": "openrouter"}, "gemini-4-hydrogen", "agy")


def test_the_bases_document_offers_both_with_the_levels_the_cli_lists(monkeypatch):
    monkeypatch.delenv("HR_BACKENDS_INSTALLED", raising=False)
    agy = _bases(monkeypatch)["agy"]
    models = {m["id"]: m for m in agy["models"]}
    assert models["gemini-4-hydrogen"]["available"] and models["gemini-4-carbon"]["available"]
    assert models["gemini-4-hydrogen"]["reasoning"] == ["low", "medium", "high", "xhigh"]
    assert models["gemini-4-carbon"]["reasoning"] == ["low", "medium", "high"]
    # and a task may name them
    assert A._model_authorized("gemini-4-hydrogen", "agy") and A._model_authorized("gemini-4-carbon", "agy")
    assert not A._model_authorized("gemini-4-hydrogen", "gemini")


def test_each_models_levels_are_the_ones_the_cli_takes():
    levels = A._BASE_CATALOG["agy"]["model_levels"]
    assert set(levels) == set(A._MODEL_CATALOG["agy"]["models"])
    for m, lv in levels.items():
        assert tuple(lv) == R.AGY_MODEL_LEVELS[R.AGY_IDS.get(m, m)], m


def test_the_switches_are_the_clis_tools_and_only_the_shell_is_withheld():
    b = A._BASE_CATALOG["agy"]
    names = [n for n, _ in b["tools"]]
    assert set(names) <= set(R.AGY_TOOLS)
    assert b["tool_enforcement"] == "instruction"
    assert set(b["hard_tools"]) == set(R.AGY_WITHHELD_BY_ANSWER)
    assert A._tool_enforcement(b, "run_command") == "hard" and A._tool_enforcement(b, "write_file") == "instruction"
    assert "agy" in R._TOOLS_OFF_BY_REQUEST                             # the rest are asked off in the instructions


def _bases(monkeypatch):
    async def org_member(_request):
        return "local", "owner"

    async def servable(_org, _backend):
        return None

    monkeypatch.setattr(A, "_pub_org_member", org_member)
    monkeypatch.setattr(A, "_servable_models", servable)
    return {x["id"]: x for x in asyncio.run(A.list_bases(None))["bases"]}


def test_the_bases_document_carries_the_clis_own_levels_and_what_a_person_should_know(monkeypatch):
    monkeypatch.delenv("HR_BACKENDS_INSTALLED", raising=False)
    agy = _bases(monkeypatch)["agy"]
    assert agy["label"] == "Antigravity CLI" and agy["backend"] == "agy"
    lv = {m["id"]: m["reasoning"] for m in agy["models"]}
    assert lv["gemini-4-argon"] == ["low", "medium", "high"]            # not the "none" another base's channel takes
    assert lv["gemini-3.1-pro-preview"] == ["low", "high"]
    notes = " ".join(agy["notes"])
    assert "does not update itself" in notes and "sends Google none" in notes
    assert "never given to the agent" in notes
    # in the person's words: no implementation names
    for word in ("relay", "runner", "broker", "sandbox", "ACP", "telemetry flag", "gateway", "HR_"):
        assert word not in notes, word
    # another base's document is unchanged: no notes, and the shared table's levels
    other = _bases(monkeypatch)["gemini"]
    assert "notes" not in other
    assert {m["id"]: m["reasoning"] for m in other["models"]}["gemini-4-argon"] == ["none", "low", "medium", "high"]


def test_agy_is_opt_in_and_reads_not_installed_where_the_instance_does_not_hold_it(monkeypatch):
    monkeypatch.setenv("HR_BACKENDS_INSTALLED", "claude,codex,gemini")
    agy = _bases(monkeypatch)["agy"]
    assert agy["status"] == "not_installed"
    assert agy["statusReason"].startswith("Antigravity CLI is not installed on this instance.")
    assert "HR_BACKENDS" in agy["statusReason"]
    with pytest.raises(A.HTTPException):
        A._require_installed("agy")
    monkeypatch.setenv("HR_BACKENDS_INSTALLED", "claude,agy")
    assert _bases(monkeypatch)["agy"]["status"] == "ready"
    entry = (pathlib.Path(__file__).resolve().parents[2] / "docker" / "entrypoint.sh").read_text()
    default = re.search(r'export HR_BACKENDS="\$\{HR_BACKENDS:-([^}]*)\}"', entry).group(1).split(",")
    assert "agy" not in default

