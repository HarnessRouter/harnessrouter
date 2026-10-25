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
    # the ids with no channel are exactly what must not be offered
    assert got.isdisjoint(A._TOKENROUTER_NO_CHANNEL)
    # kimi-k3 was this test's served example until TokenRouter served it as another model (2026-10-25)
    # and it joined the table above; deepseek-v4.1-flash is served as itself
    assert "claude-sonnet-4.6" in got and "deepseek-v4.1-flash" in got and "kimi-k3" not in got


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


@pytest.mark.asyncio
async def test_a_connection_the_router_would_refuse_offers_none_of_its_models(monkeypatch):
    """MEASURED on the support matrix (2026-10-20), and the same class of broken promise this
    file opens with: an instance whose only connection was google offered docker-agent the whole
    gemini family as available — eight ids — and every turn came back "No connection on this
    account serves gemini-4-argon", because the router refuses a chain connection whose
    (provider, base) pair has no wiring row and this function never asked. docker-agent has a
    google row now (probed, same commit), which is why this test asks about a base that does not.

    The picker now asks the router's own question, so the two cannot drift: whatever
    _chain_refusal says about a connection, the picker says about its models."""
    # goose is the DOCUMENTED case of a deliberately absent row ("No ("google", "goose") row:
    # unprobed is unlisted", in the wiring table itself), and its catalog carries nine gemini ids
    # — so the picker had nine promises to break. fast-agent and dcode are in the same position.
    assert not A._INTEGRATION_WIRING.get(("google", "goose")), \
        "this test needs a base google cannot drive; pick another if that changes"
    assert [m for m in A._MODEL_CATALOG["goose"]["models"] if "gemini" in str(m)]
    _patch(monkeypatch, chain=["g"], conn_provider="google")
    got = await A._servable_models("org", "goose")
    assert got == set(), got
    # and a base google CAN drive still gets google's table
    assert A._INTEGRATION_WIRING.get(("google", "vibe"))
    _patch(monkeypatch, chain=["g"], conn_provider="google")
    vibe = await A._servable_models("org", "vibe")
    assert vibe and "gemini-3.8-flash" in vibe


@pytest.mark.asyncio
async def test_the_refused_connection_does_not_turn_into_no_restriction(monkeypatch):
    """The failure mode to avoid while fixing it: a skipped connection must not fall through to
    `return None`, which means "offer everything" — the original bug this file records."""
    _patch(monkeypatch, chain=["g"], conn_provider="google")
    assert await A._servable_models("org", "goose") is not None
