"""A field a harness does not have is refused by name, and a model its base does not run is refused
when the harness is saved (2026-10-10, the same rule as the hosted service). The camelCase names were
already taken (#212); an unknown name or a typo was dropped in silence behind a 200, and a harness
saved on a model its base does not run answered 200 and then refused every task. An agent driving
the API learns nothing from either, and makes the same harness again and again."""
import asyncio
import os
import re
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app  # noqa: E402

H = {"x-harness-internal": "test-internal-key", "x-harness-org": "org.fields", "x-harness-member": "tester@example.com"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app.app) as c:
        yield c


def _model(base):
    return app._MODEL_CATALOG[app._backend_of_harness({"base": base})]["models"][0]


def _count(client):
    return len(client.get("/v1/harnesses", headers=H).json()["harnesses"])


def test_the_names_a_harness_comes_back_with_are_taken_on_the_way_in(client):
    m = _model("pi")
    r = client.post("/v1/harnesses", json={"name": "story", "base": "pi", "systemPrompt": "Write stories.",
                                           "defaultModel": m, "maxStep": 7, "disabledTools": ["bash"]}, headers=H)
    assert r.status_code == 200, r.text
    h = r.json()
    assert h["systemPrompt"] == "Write stories." and h["defaultModel"] == m and h["maxStep"] == 7
    assert h["disabledTools"] == ["bash"]


def test_a_harness_read_back_and_sent_again_saves(client):
    m = _model("pi")
    h = client.post("/v1/harnesses", json={"name": "story", "base": "pi", "system_prompt": "v1", "default_model": m}, headers=H).json()
    got = client.get(f"/v1/harnesses/{h['id']}", headers=H).json()
    # the whole object, id, createdAt, member, kit, notLoaded and all, and the protocol's `object`
    got.update(systemPrompt="v2", object="harness")
    r = client.put(f"/v1/harnesses/{h['id']}", json=got, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["systemPrompt"] == "v2" and r.json()["defaultModel"] == m and r.json()["id"] == h["id"]


def test_the_snake_case_name_wins_when_a_body_carries_both(client):
    r = client.post("/v1/harnesses", json={"name": "x", "base": "pi", "system_prompt": "mine", "systemPrompt": "copied"}, headers=H)
    assert r.status_code == 200 and r.json()["systemPrompt"] == "mine"


def test_a_field_the_harness_does_not_have_is_refused_by_name_with_the_nearest_one(client):
    before = _count(client)
    r = client.post("/v1/harnesses", json={"name": "x", "base": "pi", "system_promt": "a typo's value"}, headers=H)
    assert r.status_code == 422
    msg = r.json()["error"]["message"]
    assert "system_promt" in msg and "did you mean 'system_prompt'" in msg and "default_model" in msg
    assert "typo's value" not in r.text                     # the value is never echoed
    r = client.post("/v1/harnesses", json={"name": "x", "base": "pi", "instructions": "do it"}, headers=H)
    assert r.status_code == 422 and "'instructions'" in r.json()["error"]["message"]
    assert _count(client) == before                         # nothing was written
    # an update is held to the same rule
    h = client.post("/v1/harnesses", json={"name": "y", "base": "pi"}, headers=H).json()
    r = client.put(f"/v1/harnesses/{h['id']}", json={"name": "y", "base": "pi", "model": _model("pi")}, headers=H)
    assert r.status_code == 422 and "'model'" in r.json()["error"]["message"]


def test_the_servers_own_builders_still_build():
    """Kit launch and plugin install build the body from keywords, which are all fields."""
    b = app.HarnessBody(name="k", base="pi", default_model=_model("pi"), plugins=[], max_step=None)
    assert b.default_model == _model("pi")


def test_a_model_the_base_does_not_run_is_refused_when_saved(client):
    before = _count(client)
    r = client.post("/v1/harnesses", json={"name": "story", "base": "pi", "default_model": "gemini-2.5-flash"}, headers=H)
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "model_not_available" and err["param"] == "default_model"
    assert "gemini-2.5-flash" in err["message"] and _model("pi") in err["message"]
    assert _model("pi") in err["detail"]["offered"]
    assert _count(client) == before
    # no model at all is the base's default, and is fine
    assert client.post("/v1/harnesses", json={"name": "story", "base": "pi"}, headers=H).status_code == 200
    # an unknown base is said as that, not as its model
    r = client.post("/v1/harnesses", json={"name": "s", "base": "nope", "default_model": "x"}, headers=H)
    assert r.status_code == 422 and r.json()["error"]["code"] == "unsupported_base"


def test_an_edit_that_leaves_a_retired_model_as_it_was_still_saves(client):
    h = client.post("/v1/harnesses", json={"name": "old", "base": "pi", "default_model": _model("pi")}, headers=H).json()
    # a harness saved before the model was retired (or before this check)
    asyncio.run(app._vg_upsert("Harness", h["id"], {"default_model": "gemini-2.5-flash"}))
    r = client.put(f"/v1/harnesses/{h['id']}", json={"name": "renamed", "base": "pi", "default_model": "gemini-2.5-flash"}, headers=H)
    assert r.status_code == 200, r.text
    r = client.put(f"/v1/harnesses/{h['id']}", json={"name": "renamed", "base": "pi", "default_model": "gemini-2.0-pro"}, headers=H)
    assert r.status_code == 422 and r.json()["error"]["code"] == "model_not_available"
    r = client.put(f"/v1/harnesses/{h['id']}", json={"name": "renamed", "base": "pi", "default_model": _model("pi")}, headers=H)
    assert r.status_code == 200 and r.json()["defaultModel"] == _model("pi")


def test_a_model_an_integration_that_drives_the_base_was_given_is_taken(client, monkeypatch):
    """The rule a task naming the model is held to: a custom endpoint's own model id is in no catalog."""
    async def integrations():
        return [{"name": "Mine", "provider": "custom", "config": {"api_format": "openai"}}]

    async def model_map():
        return {"my-own-model": "Mine"}
    monkeypatch.setattr(app, "_integrations_doc", integrations)
    monkeypatch.setattr(app, "_effective_model_map", model_map)
    r = client.post("/v1/harnesses", json={"name": "own", "base": "pi", "default_model": "my-own-model"}, headers=H)
    assert r.status_code == 200 and r.json()["defaultModel"] == "my-own-model"
    # the same model on a base its format does not drive is refused
    r = client.post("/v1/harnesses", json={"name": "own", "base": "claude-code", "default_model": "my-own-model"}, headers=H)
    assert r.status_code == 422 and r.json()["error"]["code"] == "model_not_available"


def test_every_model_the_console_offers_on_a_base_is_one_the_gateway_saves():
    """The console fills a new harness's model from its own per-base lists; one the gateway would
    refuse makes a harness the console cannot save."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "..", "ui", "src", "lib", "harness.ts")).read()
    oob = src[src.index("export const OOB"):]
    oob = oob[:oob.index("\n];")]
    blocks = re.split(r"\n  \{ id: ", oob)[1:]
    assert len(blocks) == len(app._BASE_CATALOG)
    refused = []
    for blk in blocks:
        base = re.match(r"'([^']+)'", blk).group(1)
        models = re.findall(r"'([^']+)'", re.search(r"models: \[([^\]]*)\]", blk).group(1))
        default = re.search(r"defaultModel: '([^']*)'", blk).group(1)
        backend = app._backend_of_harness({"base": base})
        refused += [(base, m) for m in models + [default] if not app._model_authorized(m, backend)]
    assert not refused, refused
