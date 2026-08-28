"""An unpriced table must never look like a free run.

On the hosted deployment the price endpoint refused with 403 for months. The refusal was swallowed
as "keep the stale table", the table had never been populated, every _price_of() answered 0.0, and
the console showed 0 credits per session while the harvest billed the real amount. Nothing looked
broken anywhere. These pin the three states apart.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import app as A  # noqa: E402


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload


def _arrange(monkeypatch, resp=None, boom=None):
    monkeypatch.setattr(A, "ENGINE_URL", "https://engine.example", raising=False)
    monkeypatch.setattr(A, "BILLING_INTERNAL_KEY", "k", raising=False)
    monkeypatch.setattr(A, "_pricing_table", {}, raising=False)
    monkeypatch.setattr(A, "_pricing_fetched_at", 0.0, raising=False)
    monkeypatch.setattr(A, "_pricing_warned", False, raising=False)

    class _Client:
        async def get(self, *_a, **_k):
            if boom:
                raise boom
            return resp

    monkeypatch.setattr(A, "_client", lambda: _Client())


@pytest.mark.asyncio
async def test_a_refusal_is_reported_not_swallowed(monkeypatch, capsys):
    _arrange(monkeypatch, resp=_Resp(403))
    await A._refresh_pricing_table()
    out = capsys.readouterr().out
    assert "could not load the price table" in out and "403" in out
    assert "NOT a free run" in out


@pytest.mark.asyncio
async def test_a_200_with_no_table_counts_as_a_failure(monkeypatch, capsys):
    """Caching an empty table would hold emptiness for the whole TTL and make a broken
    deployment indistinguishable from a free one."""
    _arrange(monkeypatch, resp=_Resp(200, {"table": {}}))
    await A._refresh_pricing_table()
    assert "could not load the price table" in capsys.readouterr().out
    assert A._pricing_fetched_at == 0.0, "an empty table must not be cached as valid"


@pytest.mark.asyncio
async def test_it_warns_once_not_every_refresh(monkeypatch, capsys):
    _arrange(monkeypatch, resp=_Resp(403))
    await A._refresh_pricing_table()
    capsys.readouterr()
    await A._refresh_pricing_table()
    assert "could not load" not in capsys.readouterr().out


@pytest.mark.asyncio
async def test_billing_not_wired_stays_silent(monkeypatch, capsys):
    """A self-hosted instance with no billing configured is a normal state, not a fault."""
    monkeypatch.setattr(A, "ENGINE_URL", "", raising=False)
    monkeypatch.setattr(A, "BILLING_INTERNAL_KEY", "", raising=False)
    await A._refresh_pricing_table()
    assert capsys.readouterr().out == ""


@pytest.mark.asyncio
async def test_a_real_table_loads_and_recovery_is_announced(monkeypatch, capsys):
    _arrange(monkeypatch, resp=_Resp(200, {"table": {"system": {"tokens": 1.5}}}))
    monkeypatch.setattr(A, "_pricing_warned", True, raising=False)
    await A._refresh_pricing_table()
    assert A._price_of("tokens") == 1.5
    assert "real again" in capsys.readouterr().out
