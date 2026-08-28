"""What the model picker may offer.

A user picked a model the picker showed, the turn was accepted, and it failed after the point of
no return — TokenRouter serves no channel for it (_TOKENROUTER_NO_CHANNEL). _servable_models had
answered "no restriction" for any org with a policy chain, on the reasoning that a chain is
provider-level rather than per-model. The vendor tables ARE per-model and deliberately differ.

Both halves of the union below are load-bearing, and each was learned by breaking it:
  * chain only — greys out models an org runs daily through an explicit integration mapping.
  * map only   — the original bug: a chain-served org gets its entire catalog offered.

Measured on a real org (hosted, hermes, 2026-08-28), which is why the union is not theoretical:

    chain   -> 15 models (the gpt/claude families, from a direct provider table)
    map     -> 11 models (the frontier set the TokenRouter integration serves)
    neither ->  5 models (_TOKENROUTER_NO_CHANNEL)          = 31 total, 26 offered

The intermediate chain-only version greyed 16 — the whole frontier set, including kimi-k3,
glm-5.3 and the qwen and deepseek lines — while gpt and claude stayed available. The two routes
genuinely carry different halves there, so dropping either one hides a different set of working
models. These tests are the durable form of that observation; the production numbers will drift.

NOTE ON RUNNING THESE: gateway tests import app.py, which needs hashlib.scrypt. macOS system
python does not have it, so a local run here fails at COLLECTION with an AttributeError that has
nothing to do with the code under test. Run them in a container (docker exec <c> sh -lc 'cd
/app/gateway && python3 -m pytest') or let CI be the gate — CI pins the interpreter this tree
targets. A red local run is not evidence of a broken branch.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import app as A  # noqa: E402


def _patch(monkeypatch, *, chain=(), conn_provider=None, model_map=None, integrations=()):
    async def _chain(_org, _backend, _explicit):
        return list(chain)

    async def _conn(_org, _name):
        return ({"provider": conn_provider} if conn_provider else None), None

    async def _map():
        return dict(model_map or {})

    async def _docs():
        return list(integrations)

    monkeypatch.setattr(A, "_resolve_chain", _chain)
    monkeypatch.setattr(A, "_get_connection", _conn)
    monkeypatch.setattr(A, "_effective_model_map", _map)
    monkeypatch.setattr(A, "_integrations_doc", _docs)


@pytest.mark.asyncio
async def test_a_chain_restricts_to_what_that_vendor_actually_serves(monkeypatch):
    _patch(monkeypatch, chain=["tr"], conn_provider="tokenrouter")
    got = await A._servable_models("org", "hermes")
    assert got is not None, "a chain must no longer mean 'offer everything'"
    # the five with no channel are exactly what must not be offered
    assert got.isdisjoint(A._TOKENROUTER_NO_CHANNEL)
    assert "claude-sonnet-4.6" in got and "kimi-k3" in got


@pytest.mark.asyncio
async def test_an_explicitly_mapped_model_stays_available_alongside_a_chain(monkeypatch):
    """The regression the union prevents: answering from the chain alone greyed out models an
    org runs daily through its own integration mapping."""
    integ = {"name": "Router", "provider": "tokenrouter"}
    _patch(monkeypatch, chain=["tr"], conn_provider="tokenrouter",
           model_map={"minimax-m3": "Router"}, integrations=[integ])
    monkeypatch.setattr(A, "_integration_serves_backend", lambda _i, _b: True)
    got = await A._servable_models("org", "hermes")
    assert "minimax-m3" in got


@pytest.mark.asyncio
async def test_an_unknown_vendor_does_not_restrict(monkeypatch):
    """Not-in-our-tables is ignorance, not evidence a model cannot be served. Restricting on it
    would silently hide working models."""
    _patch(monkeypatch, chain=["mystery"], conn_provider="something-we-never-heard-of")
    assert await A._servable_models("org", "hermes") is None


@pytest.mark.asyncio
async def test_no_chain_still_answers_from_the_map(monkeypatch):
    integ = {"name": "Vercel", "provider": "vercel"}
    _patch(monkeypatch, chain=[], model_map={"gpt-5.4": "Vercel"}, integrations=[integ])
    monkeypatch.setattr(A, "_integration_serves_backend", lambda _i, _b: True)
    assert await A._servable_models("org", "codex") == {"gpt-5.4"}
