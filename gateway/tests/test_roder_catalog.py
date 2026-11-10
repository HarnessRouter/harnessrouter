"""Only Responses connections may be offered to the Roder native app-server adapter; its switches are
the runner's tool table; and a base this instance has not installed is not offered as ready."""
import asyncio
import inspect
import os
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as A

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "runner"))
import roder_backend  # noqa: E402


def test_roder_registration_is_responses_only():
    assert A._BASE_CATALOG["roder"]["backend"] == "roder"
    assert A._BASE_CATALOG["roder"]["tool_enforcement"] == "hard"
    assert "roder" in A._CUSTOM_FORMAT_BACKENDS["responses"]
    assert "roder" not in A._CUSTOM_FORMAT_BACKENDS["openai"]
    assert "roder" not in A._CUSTOM_FORMAT_BACKENDS["anthropic"]
    assert A._INTEGRATION_WIRING[("openai", "roder")] == "openai"
    assert A._INTEGRATION_WIRING[("azure-foundry", "roder")] == "azure"
    assert ("anthropic", "roder") not in A._INTEGRATION_WIRING
    assert ("google", "roder") not in A._INTEGRATION_WIRING
    assert A._backend_of_builtin("roder") == "roder"


def test_roder_offers_current_model_families_and_default():
    models = A._MODEL_CATALOG["roder"]["models"]
    assert A._MODEL_CATALOG["roder"]["default"] == roder_backend.DEFAULT_MODEL == "gpt-6.1-sol"
    assert models == ["gpt-6.1-sol"]
    assert "roder" in A._STILL_QUALIFYING


def test_roder_is_wired_as_dcode_is():
    """The same Responses endpoints dcode drives, by the same runner providers: OpenRouter and a
    custom endpoint on openai-api, the aggregators on tokenrouter."""
    for provider in ("openai", "azure-foundry", "openrouter", "custom", "tokenrouter", "vercel",
                     "llmtr", "harnessrouter"):
        assert A._INTEGRATION_WIRING[(provider, "roder")] == A._INTEGRATION_WIRING[(provider, "dcode")], provider
        assert A._INTEGRATION_WIRING[(provider, "roder")] in roder_backend.PROVIDERS, provider
    assert A._INTEGRATION_WIRING[("openrouter", "roder")] == "openai-api"
    assert A._INTEGRATION_WIRING[("custom", "roder")] == "openai-api"


def test_roder_inherits_responses_channel_refusals():
    for channel in ("tokenrouter", "harnessrouter"):
        assert A._CHANNEL_REFUSES[(channel, "roder")] == A._CHANNEL_REFUSES[(channel, "dcode")]


def test_the_switches_are_the_runners_tool_table():
    """A switch the console shows is one the runner maps to Roder's tool names, in the same order,
    and every name behind a switch is a tool the model is offered, never a withheld one."""
    ids = [name for name, _ in A._BASE_CATALOG["roder"]["tools"]]
    assert ids == list(roder_backend.TOOLS)
    labels = [label for _, label in A._BASE_CATALOG["roder"]["tools"]]
    assert len(set(labels)) == len(labels)
    behind = [n for names in roder_backend.TOOLS.values() for n in names]
    assert len(set(behind)) == len(behind)
    assert not set(behind) & roder_backend.WITHHELD
    # the shell and the file writers are each one switch, whatever the model's edit family
    assert set(roder_backend.TOOLS["exec_command"]) == {"exec_command", "shell", "unified_exec", "write_stdin"}
    assert set(roder_backend.TOOLS["apply_patch"]) == {"apply_patch", "edit", "multi_edit", "write_file"}


# ── a base this instance has not installed (HR_BACKENDS_INSTALLED, from docker/entrypoint.sh) ──────

def _bases(monkeypatch):
    async def org_member(_request):
        return "local", "owner"

    async def servable(_org, _backend):
        return None

    monkeypatch.setattr(A, "_pub_org_member", org_member)
    monkeypatch.setattr(A, "_servable_models", servable)
    return {b["id"]: b for b in asyncio.run(A.list_bases(None))["bases"]}


def test_without_the_installed_list_every_base_reads_as_the_catalog_says(monkeypatch):
    """Where nothing installs bases at start (no HR_BACKENDS_INSTALLED), nothing is withheld."""
    monkeypatch.delenv("HR_BACKENDS_INSTALLED", raising=False)
    bases = _bases(monkeypatch)
    assert bases["roder"]["status"] == "ready" and "statusReason" not in bases["roder"]
    assert A._backend_installed("roder")
    A._require_installed("roder")


def test_a_base_the_instance_did_not_install_reads_not_installed_with_the_reason(monkeypatch):
    monkeypatch.setenv("HR_BACKENDS_INSTALLED", "claude,codex,dcode")
    bases = _bases(monkeypatch)
    assert bases["roder"]["status"] == "not_installed"
    reason = bases["roder"]["statusReason"]
    assert reason.startswith("Roder is not installed on this instance.") and "HR_BACKENDS" in reason
    assert "—" not in reason
    assert bases["codex"]["status"] == "ready" and bases["claude-code"]["status"] == "ready"
    assert bases["dcode"]["status"] == "ready" and "statusReason" not in bases["dcode"]
    # any base, not only roder: one whose install failed reads the same
    assert bases["jcode"]["status"] == "not_installed"
    # and a turn on it is refused in words, with the same reason
    with pytest.raises(A.HTTPException) as refused:
        A._require_installed("roder")
    assert refused.value.status_code == 400 and refused.value.detail == reason
    A._require_installed("codex")
    # installed, it is ready
    monkeypatch.setenv("HR_BACKENDS_INSTALLED", "codex,roder")
    assert _bases(monkeypatch)["roder"]["status"] == "ready"


def test_new_setup_does_not_offer_a_base_the_instance_did_not_install(monkeypatch):
    async def servable(_org, _backend):
        return None

    monkeypatch.setattr(A, "_servable_models", servable)
    monkeypatch.setenv("HR_BACKENDS_INSTALLED", "codex,dcode")
    offered = asyncio.run(A._setup_bases("local"))
    assert "roder" not in offered and "hermes" not in offered
    assert "codex" in offered and "dcode" in offered
    monkeypatch.setenv("HR_BACKENDS_INSTALLED", "codex,dcode,roder")
    assert "roder" in asyncio.run(A._setup_bases("local"))


def test_a_turn_checks_the_base_is_installed_before_its_model_or_connections():
    src = inspect.getsource(A.create_response)
    check = src.index("_require_installed(backend)")
    assert src.index("backend = (_backend_of_harness(hv)") < check < src.index("_resolve_model_policy(")


def test_every_catalog_backend_is_one_the_entrypoint_can_report():
    """HR_BACKENDS_INSTALLED is built from the entrypoint's backend_bin table: a catalog backend
    missing there would always read not installed."""
    entry = (pathlib.Path(__file__).resolve().parents[2] / "docker" / "entrypoint.sh").read_text()
    table = entry[entry.index("backend_bin() {"):entry.index("\n}\n", entry.index("backend_bin() {"))]
    for b in {b["backend"] for b in A._BASE_CATALOG.values()}:
        assert f"\n    {b})" in table or f"\n    {b}) " in table, b
    assert 'export HR_BACKENDS_INSTALLED=' in entry
