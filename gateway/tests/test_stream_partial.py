"""Token-level streaming: a streamed grok turn gave its answer only when the turn settled.

The gate that asks the runner for partial messages admitted claude and codex only, so a grok turn
streamed nothing until it ended and the whole answer arrived as ONE response.output_text.delta.
The runner already carried grok's half of the path (--include-partial-messages on the grok argv,
and the claude passthrough that reads grok's `stream_event` framing); what was missing was the
gate, so none of it was reachable.

The default is unchanged: the gate is opt-in, through HARNESS_STREAM_PARTIAL=1 or
metadata.stream_partial, so a rollback is flipping the env with no redeploy.
"""
import os
import pathlib
import sys

import pytest
from fastapi.testclient import TestClient  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as A  # noqa: E402

ORG = "org_e"


@pytest.fixture()
def api(monkeypatch):
    async def principal(request):
        return {"org": ORG, "member": "me@local"}
    monkeypatch.setattr(A, "_principal", principal)
    monkeypatch.setattr(A, "_response_in_reach", lambda p, rec: _true())
    monkeypatch.setattr(A, "_harness_in_reach", lambda p: _true())
    return TestClient(A.app)


async def _true():
    return True


def _run(api, monkeypatch, backend: str, body: dict) -> dict:
    """The body the turn handed the runner's /turn, with the world's edges stubbed out.

    The request goes through the real endpoint, so the gate that decides whether a turn asks for
    partial messages is the one under test, not a helper called directly.
    """
    monkeypatch.setattr(A, "_base_catalog_get", lambda h: {"id": h, "base": backend}, raising=False)

    async def _chain(org, backend, model):
        return [{"backend": backend}]
    monkeypatch.setattr(A, "_resolve_chain", _chain)

    seen: dict = {}

    async def _exec(tr, **kw):
        seen["kwargs"] = kw
        return "completed", [], {}

    monkeypatch.setattr(A, "_resp_execute", _exec)

    # The harness is named in metadata, which is where create_response reads it from
    # (`meta.get("harness_id")`), so the turn really runs on the backend under test.
    r = api.post("/v1/responses", json={"input": "hi", "metadata": {"harness_id": backend}, **body})
    assert r.status_code == 200, r.text
    return seen.get("kwargs") or {}


def test_a_grok_turn_asks_the_runner_for_partial_messages(api, monkeypatch):
    """The seam the change opens: a grok turn whose gate is open must reach the runner carrying
    `partial_messages`, because that is the only thing that makes the runner add
    `--include-partial-messages` to the grok argv. Without the gate the flag never reaches the
    runner, and none of the runner's existing support helps."""
    monkeypatch.setenv("HARNESS_STREAM_PARTIAL", "1")
    kw = _run(api, monkeypatch, "grok", {})
    assert kw.get("partial_messages") is True, (
        f"the executor was handed {kw.get('partial_messages')!r} instead of the request for "
        "partial messages")


def test_a_grok_turn_asks_for_no_partial_messages_by_default(api, monkeypatch):
    """The default is unchanged: a turn that asked for nothing gets the batch path, so a server
    that never sets the flag is unaffected by this change."""
    monkeypatch.delenv("HARNESS_STREAM_PARTIAL", raising=False)
    kw = _run(api, monkeypatch, "grok", {})
    assert kw.get("partial_messages") is False, (
        f"the executor was handed {kw.get('partial_messages')!r} with no request for partial "
        "messages")


def test_a_backend_with_no_partial_path_is_not_asked_for_partial_messages(api, monkeypatch):
    """A backend whose CLI cannot stream partials is not asked to. The gate names the backends
    that can, and a backend outside it stays on the batch path however the request is made."""
    monkeypatch.setenv("HARNESS_STREAM_PARTIAL", "1")
    monkeypatch.setattr(A, "_backend_of_builtin", lambda harness_id: "qwen")
    kw = _run(api, monkeypatch, "qwen", {})
    assert kw.get("partial_messages") is False, (
        f"the executor was handed {kw.get('partial_messages')!r} for a backend that cannot stream "
        "partials")
