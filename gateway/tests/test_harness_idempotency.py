"""POST /v1/harnesses honours an Idempotency-Key (Harnesses §5.1).

The failure it prevents: the client creates a harness, the answer is lost on the way back (a
dropped connection, a timeout), and the client cannot tell whether the harness exists. Its retry
used to make a second one. The reservation is taken before any prepare step writes a blob or a
package, so a retry replays the first harness and does not duplicate the side effects either.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402  (environment: conftest.py)

ORG = "org.a"
BASE = "hermes"


@pytest.fixture()
def api(monkeypatch):
    async def principal(request):
        return {"org": ORG, "member": "me@local"}
    monkeypatch.setattr(gw, "_principal", principal)
    return TestClient(gw.app)


def _name() -> str:
    return f"idem-{uuid.uuid4().hex[:8]}"


def _count(name: str, api) -> int:
    rows = api.get("/v1/harnesses").json()["harnesses"]
    return len([h for h in rows if h.get("name") == name])


def test_the_same_key_returns_the_first_harness_and_makes_only_one(api):
    key, body = f"k-{uuid.uuid4().hex}", {"name": _name(), "base": BASE}
    first = api.post("/v1/harnesses", json=body, headers={"Idempotency-Key": key})
    assert first.status_code == 200, first.text
    again = api.post("/v1/harnesses", json=body, headers={"Idempotency-Key": key})
    assert again.status_code == 200, again.text
    assert again.json()["id"] == first.json()["id"]
    assert _count(body["name"], api) == 1


def test_a_reused_key_with_a_different_body_is_refused(api):
    key, body = f"k-{uuid.uuid4().hex}", {"name": _name(), "base": BASE}
    assert api.post("/v1/harnesses", json=body, headers={"Idempotency-Key": key}).status_code == 200
    other = api.post("/v1/harnesses", json={**body, "name": body["name"] + "-other"},
                     headers={"Idempotency-Key": key})
    assert other.status_code == 409, other.text
    assert other.json()["error"]["code"] == "idempotency_key_reused"


def test_a_body_the_prepare_steps_rewrite_still_hashes_the_same(api):
    # _skills_prepare replaces a bundle over the inline cap with a blob handle and drops `files`.
    # Hashing the body after that would make a retry look like a different request: 409 instead of
    # a replay. The hash is taken before the prepares for exactly this case.
    key, name = f"k-{uuid.uuid4().hex}", _name()
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
    # A reservation whose request died before the vertex landed must be released, or the retry
    # would replay a harness that never existed.
    key, body = f"k-{uuid.uuid4().hex}", {"name": _name(), "base": BASE}
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


def test_the_capability_is_advertised(api):
    # Declared, not inferred: a client asks before it relies on the header.
    caps = api.get("/v1/uhp").json()["capabilities"]
    assert caps["harness_idempotency"] is True
