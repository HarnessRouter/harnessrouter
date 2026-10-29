"""POST /v1/harnesses honours an Idempotency-Key (Harnesses §5.1).

The failure it prevents: the client creates a harness, the answer is lost on the way back (a
dropped connection, a timeout), and the client cannot tell whether the harness exists. Its retry
used to make a second one. The key is claimed before any prepare step writes a blob or a package,
so a retry replays the first harness and does not duplicate the side effects either.
"""
from __future__ import annotations

import asyncio
import sys
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402  (environment: conftest.py)

ORG = "org.a"
BASE = "hermes"


def _as(monkeypatch, principal: dict) -> TestClient:
    async def who(request):
        return dict(principal)
    monkeypatch.setattr(gw, "_principal", who)
    return TestClient(gw.app)


@pytest.fixture()
def api(monkeypatch):
    return _as(monkeypatch, {"org": ORG, "member": "me@local"})


def _name() -> str:
    return f"idem-{uuid.uuid4().hex[:8]}"


def _key() -> str:
    return f"k-{uuid.uuid4().hex}"


def _count(name: str, api) -> int:
    rows = api.get("/v1/harnesses").json()["harnesses"]
    return len([h for h in rows if h.get("name") == name])


def test_the_same_key_returns_the_first_harness_and_makes_only_one(api):
    key, body = _key(), {"name": _name(), "base": BASE}
    first = api.post("/v1/harnesses", json=body, headers={"Idempotency-Key": key})
    assert first.status_code == 200, first.text
    again = api.post("/v1/harnesses", json=body, headers={"Idempotency-Key": key})
    assert again.status_code == 200, again.text
    assert again.json()["id"] == first.json()["id"]
    assert _count(body["name"], api) == 1


def test_a_reused_key_with_a_different_body_is_refused(api):
    key, body = _key(), {"name": _name(), "base": BASE}
    assert api.post("/v1/harnesses", json=body, headers={"Idempotency-Key": key}).status_code == 200
    other = api.post("/v1/harnesses", json={**body, "name": body["name"] + "-other"},
                     headers={"Idempotency-Key": key})
    assert other.status_code == 409, other.text
    assert other.json()["error"]["code"] == "idempotency_key_reused"


def test_a_body_the_prepare_steps_rewrite_still_hashes_the_same(api):
    # _skills_prepare replaces a bundle over the inline cap with a blob handle and drops `files`.
    # Hashing the body after that would make a retry look like a different request: 409 instead of
    # a replay. The hash is taken before the prepares for exactly this case.
    key, name = _key(), _name()
    body = {"name": name, "base": BASE,
            "skills": [{"name": "idem-big", "enabled": True,
                        "files": [{"path": "SKILL.md",
                                   "content": "x" * (gw._SKILL_INLINE_MAX + 100)}]}]}
    first = api.post("/v1/harnesses", json=body, headers={"Idempotency-Key": key})
    assert first.status_code == 200, first.text
    again = api.post("/v1/harnesses", json=body, headers={"Idempotency-Key": key})
    assert again.status_code == 200, again.text
    assert again.json()["id"] == first.json()["id"]
    assert _count(name, api) == 1


def test_no_key_still_creates_one_per_request(api):
    # The header is optional: a client that sends none keeps the behaviour it had.
    body = {"name": _name(), "base": BASE}
    one = api.post("/v1/harnesses", json=body)
    two = api.post("/v1/harnesses", json=body)
    assert one.status_code == two.status_code == 200
    assert one.json()["id"] != two.json()["id"]
    assert _count(body["name"], api) == 2


def test_a_create_that_fails_before_the_record_does_not_poison_the_key(api, monkeypatch):
    # A claim whose request died before the vertex landed is released, or the retry would wait on a
    # harness that is never written.
    key, body = _key(), {"name": _name(), "base": BASE}
    real = gw._skills_prepare
    calls = {"n": 0}

    async def boom_once(skills):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("prepare failed")
        return await real(skills)

    monkeypatch.setattr(gw, "_skills_prepare", boom_once)
    with pytest.raises(RuntimeError):
        api.post("/v1/harnesses", json=body, headers={"Idempotency-Key": key})
    retried = api.post("/v1/harnesses", json=body, headers={"Idempotency-Key": key})
    assert retried.status_code == 200, retried.text
    assert _count(body["name"], api) == 1


def test_a_repeat_while_the_first_is_still_creating_waits_for_it(api, monkeypatch):
    # The client timed out while the first create was still writing (a large skill upload) and sent
    # it again. Tasks §6: the repeat waits for the first and answers with its result; a not-found
    # here would tell the client its harness does not exist when it is about to.
    key, body = _key(), {"name": _name(), "base": BASE}
    first = api.post("/v1/harnesses", json=body, headers={"Idempotency-Key": key}).json()["id"]
    real, misses = gw._vertex_get, {"n": 2}

    async def not_landed_yet(vid):
        if vid == first and misses["n"]:
            misses["n"] -= 1
            return None
        return await real(vid)

    monkeypatch.setattr(gw, "_vertex_get", not_landed_yet)
    again = api.post("/v1/harnesses", json=body, headers={"Idempotency-Key": key})
    assert again.status_code == 200, again.text
    assert again.json()["id"] == first and misses["n"] == 0


def test_a_claim_left_by_a_create_that_died_is_taken_over(api, monkeypatch):
    # A process killed between the claim and the write never released it. Its claim names a harness
    # that will never land; past the stale age the repeat creates instead of waiting out the day.
    key, body = _key(), {"name": _name(), "base": BASE}
    sha = gw._idem_sha(f"harness\n\n{key}")
    req = gw._harness_req_hash(gw.HarnessBody(**body))
    assert asyncio.run(gw.control_store.idem_reserve(ORG, sha, "chrn_" + "d" * 32, req, 3600)) is None
    monkeypatch.setattr(gw, "_HARNESS_IDEM_STALE", 0.6)
    t0 = time.time()
    r = api.post("/v1/harnesses", json=body, headers={"Idempotency-Key": key})
    assert r.status_code == 200, r.text
    assert r.json()["id"] != "chrn_" + "d" * 32 and time.time() - t0 >= 0.6
    assert api.post("/v1/harnesses", json=body, headers={"Idempotency-Key": key}).json()["id"] == r.json()["id"]
    assert _count(body["name"], api) == 1


def test_once_the_keys_harness_is_deleted_the_key_creates_again(api):
    # Deploy to Cloud sends one key per harness and form. When the person deletes Cloud's copy and
    # deploys again, the key's harness is gone: the repeat makes a new one (and later repeats return
    # that one) instead of answering not-found until the key expires.
    key, body = _key(), {"name": _name(), "base": BASE}
    first = api.post("/v1/harnesses", json=body, headers={"Idempotency-Key": key}).json()["id"]
    assert api.delete(f"/v1/harnesses/{first}").status_code == 200
    again = api.post("/v1/harnesses", json=body, headers={"Idempotency-Key": key})
    assert again.status_code == 200, again.text
    second = again.json()["id"]
    assert second != first
    assert api.post("/v1/harnesses", json=body, headers={"Idempotency-Key": key}).json()["id"] == second
    assert _count(body["name"], api) == 1


def test_a_key_never_answers_with_another_workspaces_harness(monkeypatch):
    # Two workspaces of one organization, one key: each gets its own harness. A replay across them
    # would hand a workspace's key the other's harness, the read _scope_keeps exists to refuse.
    key, body = _key(), {"name": _name(), "base": BASE}
    a = _as(monkeypatch, {"org": ORG, "member": "a@x", "workspace": "space.a", "via": "api_key"})
    ha = a.post("/v1/harnesses", json=body, headers={"Idempotency-Key": key}).json()["id"]
    b = _as(monkeypatch, {"org": ORG, "member": "b@x", "workspace": "space.b", "via": "api_key"})
    rb = b.post("/v1/harnesses", json=body, headers={"Idempotency-Key": key})
    assert rb.status_code == 200, rb.text
    assert rb.json()["id"] != ha


def test_the_key_is_kept_apart_from_a_responses_key(api):
    # The same string sent as a task's key and as a create's names two different requests: neither
    # answers for the other (both claims live in one store).
    key = _key()
    assert asyncio.run(gw.control_store.idem_reserve(ORG, gw._idem_sha(key), "resp_x", "r", 3600)) is None
    r = api.post("/v1/harnesses", json={"name": _name(), "base": BASE}, headers={"Idempotency-Key": key})
    assert r.status_code == 200, r.text


def test_the_capability_is_advertised(api):
    # Declared, not inferred: a client asks before it relies on the header.
    caps = api.get("/v1/uhp").json()["capabilities"]
    assert caps["harness_idempotency"] is True
