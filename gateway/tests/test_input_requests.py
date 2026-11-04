"""A task can end by asking the person something (UHP Tasks §3.2, capability `input_requests`, #476).

The runner reports the question beside the reason `input_required`; the response ends `incomplete`
with the question as its last message and as an `input_request` item, and keeps what an answer is
checked against. The answer is an `input_response` item on the next request, chained on that
response: it is checked (409 / 410 / 422), claimed once, and becomes the turn's message with the
question carried back. A secret answer reaches the harness's environment and nothing a client
reads; any other input voids the question, and the response names it.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402  (environment: conftest.py)
import control_store  # noqa: E402

ORG = "org.ask"
QUESTION = {"kind": "choice", "prompt": "Which language?",
            "options": [{"id": "en", "label": "English"}, {"id": "zh", "label": "Chinese"}]}


def _tr(**kw) -> gw._RespTranslator:
    return gw._RespTranslator("resp_t", "m", "resp_prev", True, 0.0, sid="hsess1", **kw)


# ── the response: the question as a message and as the typed item ───────────────────────────────

def test_the_turn_ends_incomplete_with_the_question_as_text_and_as_an_item():
    tr = _tr()
    tr.feed({"type": "assistant", "message": {"content": [{"type": "text", "text": "Let me ask."}]}})
    tr.incomplete_reason = "input_required"
    tr.set_input_request(QUESTION)
    evs = tr.complete("incomplete")
    d = tr._response_obj("incomplete")
    assert d["status"] == "incomplete" and d["incomplete_details"]["reason"] == "input_required"
    kinds = [i["type"] for i in d["output"]]
    assert kinds == ["message", "message", "input_request"], kinds
    assert d["output"][1]["content"][0]["text"] == "Which language?\n- English (en)\n- Chinese (zh)"
    item = d["output"][-1]
    assert item["id"].startswith("inreq_") and item["status"] == "completed"
    assert item["kind"] == "choice" and item["prompt"] == "Which language?" and item["options"] == QUESTION["options"]
    assert "expires_at" not in item
    # streamed through the output-item events every client reads, before the terminal event
    added = [e for e in evs if e["type"] == "response.output_item.added" and e["item"]["type"] == "input_request"]
    done = [e for e in evs if e["type"] == "response.output_item.done" and e["item"]["type"] == "input_request"]
    assert len(added) == 1 and len(done) == 1 and done[0]["item"] == item
    assert evs[-1]["type"] == "response.incomplete" and evs[-1]["response"]["output"][-1] == item


def test_what_an_answer_is_checked_against_is_kept_with_the_record():
    tr = _tr()
    tr.set_input_request({**QUESTION, "expires_at": 1_900_000_000})
    p = tr.pending_input()
    assert p == {"id": tr.input_request["id"], "kind": "choice", "prompt": "Which language?",
                 "option_ids": ["en", "zh"], "expires_at": 1_900_000_000, "state": "pending"}
    assert tr._response_obj("incomplete")["output"] == []     # not on the response until complete()
    assert _tr().pending_input() is None


def test_a_completed_turn_carries_no_question():
    tr = _tr()
    tr.set_input_request(QUESTION)
    tr.complete("completed")
    assert all(i["type"] != "input_request" for i in tr.output)


def test_a_voided_question_is_named_in_metadata():
    tr = _tr()
    tr.voided_input_requests = ["inreq_1"]
    assert tr._response_obj("completed")["metadata"]["voided_input_requests"] == ["inreq_1"]
    assert "voided_input_requests" not in _tr()._response_obj("completed")["metadata"]


def test_the_runners_poll_body_sets_the_question():
    """The gateway's turn loop reads `input_request` beside `reason` on the runner's status body."""
    src = Path(gw.__file__).read_text()
    assert src.count('translator.set_input_request(s["input_request"])') == 2   # the turn loop and the adoption


# ── the answer: taken out of input, checked, claimed ───────────────────────────────────────────

def test_one_answer_is_split_out_of_the_input():
    a = {"type": "input_response", "input_request_id": "inreq_1", "answer": "en"}
    got, rest = gw._split_input_response([a, {"role": "user", "content": "and hurry"}])
    assert got is a and rest == [{"role": "user", "content": "and hurry"}]
    assert gw._split_input_response("plain") == (None, "plain")
    assert gw._split_input_response([{"role": "user", "content": "x"}])[0] is None
    with pytest.raises(HTTPException) as e:
        gw._split_input_response([a, a])
    assert e.value.status_code == 400 and e.value.detail["code"] == "invalid_input"
    with pytest.raises(HTTPException) as e:
        gw._split_input_response([{"type": "input_response", "answer": "en"}])
    assert e.value.status_code == 400 and e.value.detail["param"] == "input.input_request_id"


@pytest.fixture()
def blobs(monkeypatch):
    """The stored records, as the gateway writes them."""
    store: dict[str, dict] = {}

    async def put(key, body, **kw):
        store[key] = json.loads(body)
        return True
    monkeypatch.setattr(gw, "_blob_put", put)
    return store


def _prev(pend: dict | None, rid: str = "resp_q") -> dict:
    return {"id": rid, "status": "incomplete", "_org": ORG, "_session_id": "hsess1",
            **({"_pending_input": pend} if pend else {})}


def _pend(**over) -> dict:
    return {"id": "inreq_" + uuid.uuid4().hex[:8], "kind": "choice", "prompt": "Which language?",
            "option_ids": ["en", "zh"], "expires_at": None, "state": "pending", **over}


def _accept(prev, answer, rid="resp_q"):
    return asyncio.run(gw._input_response_accept(ORG, rid, prev, answer))


def _refused(prev, answer, rid="resp_q") -> HTTPException:
    with pytest.raises(HTTPException) as e:
        _accept(prev, answer, rid)
    return e.value


def test_an_answer_is_accepted_once_and_the_question_is_claimed(blobs):
    pend = _pend()
    prev = _prev(pend)
    acc = _accept(prev, {"type": "input_response", "input_request_id": pend["id"], "answer": "zh"})
    assert acc == {"id": pend["id"], "kind": "choice", "prompt": "Which language?", "answer": "zh"}
    assert prev["_pending_input"]["state"] == "answered"
    assert blobs["responses/resp_q.json"]["_pending_input"]["state"] == "answered"
    # the same answer again: the record says answered, so it is refused
    e = _refused(prev, {"type": "input_response", "input_request_id": pend["id"], "answer": "zh"})
    assert e.status_code == 409 and e.detail["code"] == "input_not_pending" and e.detail["detail"]["state"] == "answered"


def test_the_claim_is_decided_once_across_replicas(blobs):
    """Two replicas holding the same answer: each reads a record that says pending; the control
    store's compare-and-swap lets one through and refuses the other."""
    assert control_store.enabled()
    pend = _pend()
    one, two = _prev(pend), _prev(pend)      # two reads of the same record
    _accept(one, {"type": "input_response", "input_request_id": pend["id"], "answer": "en"})
    e = _refused(two, {"type": "input_response", "input_request_id": pend["id"], "answer": "en"})
    assert e.status_code == 409 and e.detail["code"] == "input_not_pending"
    # a claim undone (the turn never ran) is pending again, and an answer goes through
    assert asyncio.run(gw._input_request_settle(ORG, "resp_q", one, "pending"))
    _accept(_prev({**pend, "state": "pending"}), {"type": "input_response", "input_request_id": pend["id"], "answer": "en"})


def test_an_unknown_or_voided_request_is_not_pending(blobs):
    e = _refused(_prev(_pend()), {"type": "input_response", "input_request_id": "inreq_nope", "answer": "en"})
    assert e.status_code == 409 and e.detail["code"] == "input_not_pending" and e.detail["detail"]["state"] is None
    pend = _pend(state="voided")
    e = _refused(_prev(pend), {"type": "input_response", "input_request_id": pend["id"], "answer": "en"})
    assert e.status_code == 409 and e.detail["detail"]["state"] == "voided"
    e = _refused(_prev(None), {"type": "input_response", "input_request_id": "inreq_x", "answer": "en"})
    assert e.status_code == 409
    e = _refused(None, {"type": "input_response", "input_request_id": "inreq_x", "answer": "en"})
    assert e.status_code == 409


def test_an_answer_after_expiry_is_gone(blobs):
    pend = _pend(expires_at=int(time.time()) - 5)
    prev = _prev(pend)
    e = _refused(prev, {"type": "input_response", "input_request_id": pend["id"], "answer": "en"})
    assert e.status_code == 410 and e.detail["code"] == "input_request_expired"
    assert e.detail["type"] == "invalid_request_error"
    assert prev["_pending_input"]["state"] == "expired"
    assert gw._UHP_STATUS_TYPE[410] == ("invalid_request_error", "gone")


def test_an_answer_outside_the_options_is_refused_and_the_question_stays(blobs):
    pend = _pend()
    prev = _prev(pend)
    e = _refused(prev, {"type": "input_response", "input_request_id": pend["id"], "answer": "fr"})
    assert e.status_code == 422 and e.detail["code"] == "input_response_invalid"
    assert e.detail["detail"] == {"input_request_id": pend["id"], "kind": "choice", "options": ["en", "zh"]}
    assert prev["_pending_input"]["state"] == "pending" and "responses/resp_q.json" not in blobs
    e = _refused(prev, {"type": "input_response", "input_request_id": pend["id"], "answer": ["en"]})
    assert e.status_code == 422
    # a free_text or secret answer is any non-empty string
    free = _pend(kind="free_text", option_ids=[])
    e = _refused(_prev(free), {"type": "input_response", "input_request_id": free["id"], "answer": "  "})
    assert e.status_code == 422 and e.detail["detail"]["kind"] == "free_text"
    assert _accept(_prev(free), {"type": "input_response", "input_request_id": free["id"], "answer": "Paris"})["answer"] == "Paris"


def test_the_answer_becomes_the_message_carrying_the_question_back():
    acc = {"id": "inreq_1", "kind": "choice", "prompt": "Which language?", "answer": "zh"}
    assert gw._answer_prompt(acc, None) == 'Answer to your question "Which language?": zh'
    line = gw._answer_prompt({**acc, "kind": "secret", "answer": "hunter2"}, "HR_INPUT_INREQ_1")
    assert "hunter2" not in line and "HR_INPUT_INREQ_1" in line


# ── the two turns, end to end through POST /v1/responses ─────────────────────────────────────────

@pytest.fixture()
def api(monkeypatch):
    async def who(request):
        return {"org": ORG, "member": "me@local"}
    monkeypatch.setattr(gw, "_principal", who)

    async def chain(org, backend, _):
        return ["c1"]
    monkeypatch.setattr(gw, "_resolve_chain", chain)
    return TestClient(gw.app)


class _FakeRunner:
    """Stands in for _resp_execute: the first turn ends on the question, the next one completes
    and records what it was handed."""

    def __init__(self):
        self.calls: list[dict] = []

    async def __call__(self, translator, **kw):
        self.calls.append(kw)
        if len(self.calls) == 1:
            translator.incomplete_reason = "input_required"
            translator.set_input_request(QUESTION if kw.get("prompt", "").startswith("ask") else
                                         {"kind": "secret", "prompt": "The API token?"})
            return "incomplete", [], {"status": "incomplete"}
        translator.feed({"type": "assistant", "message": {"content": [{"type": "text", "text": "DONE"}]}})
        return "completed", [], {"status": "done"}


def _harness(api) -> str:
    r = api.post("/v1/harnesses", json={"name": f"ask-{uuid.uuid4().hex[:6]}", "base": "claude-code"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_a_question_and_its_answer_over_the_api(api, monkeypatch):
    fake = _FakeRunner()
    monkeypatch.setattr(gw, "_resp_execute", fake)
    hid = _harness(api)
    r = api.post("/v1/responses", json={"input": "ask me which language", "metadata": {"harness_id": hid}})
    assert r.status_code == 200, r.text
    first = r.json()
    assert first["status"] == "incomplete" and first["incomplete_details"]["reason"] == "input_required"
    item = first["output"][-1]
    assert item["type"] == "input_request" and item["kind"] == "choice"
    # the stored record reads back the same, and shows nothing internal
    got = api.get(f"/v1/responses/{first['id']}").json()
    assert got["status"] == "incomplete" and got["output"][-1] == item and "_pending_input" not in got
    # an option outside the question: refused, and the question stands
    r = api.post("/v1/responses", json={"previous_response_id": first["id"], "input": [
        {"type": "input_response", "input_request_id": item["id"], "answer": "fr"}]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "input_response_invalid"
    # an answer with no previous response to answer in
    r = api.post("/v1/responses", json={"metadata": {"harness_id": hid}, "input": [
        {"type": "input_response", "input_request_id": item["id"], "answer": "zh"}]})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_input"
    # the answer: a normal continuation, and the turn is handed the answer with the question
    r = api.post("/v1/responses", json={"previous_response_id": first["id"], "input": [
        {"type": "input_response", "input_request_id": item["id"], "answer": "zh"}]})
    assert r.status_code == 200, r.text
    second = r.json()
    assert second["status"] == "completed" and second["previous_response_id"] == first["id"]
    assert second["metadata"]["session_id"] == first["metadata"]["session_id"]
    assert fake.calls[1]["prompt"] == 'Answer to your question "Which language?": zh'
    assert fake.calls[1]["user_text"] == fake.calls[1]["prompt"]
    assert fake.calls[1]["extra_env"] == {} and fake.calls[1]["extra_secret"] == []
    assert fake.calls[1]["sid"] == fake.calls[0]["sid"]           # the same session, as any continuation
    # the input the turn was created with reads back the answer
    items = api.get(f"/v1/responses/{second['id']}/input_items").json()
    assert any(i.get("type") == "input_response" and i.get("answer") == "zh" for i in _items(items))
    # answered once: a second answer is refused
    r = api.post("/v1/responses", json={"previous_response_id": first["id"], "input": [
        {"type": "input_response", "input_request_id": item["id"], "answer": "en"}]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "input_not_pending"


def test_other_input_voids_the_question_and_the_response_says_so(api, monkeypatch):
    fake = _FakeRunner()
    monkeypatch.setattr(gw, "_resp_execute", fake)
    hid = _harness(api)
    first = api.post("/v1/responses", json={"input": "ask me which language", "metadata": {"harness_id": hid}}).json()
    item = first["output"][-1]
    r = api.post("/v1/responses", json={"previous_response_id": first["id"], "input": "never mind, use English"})
    assert r.status_code == 200, r.text
    assert r.json()["metadata"]["voided_input_requests"] == [item["id"]]
    assert fake.calls[1]["prompt"] == "never mind, use English"
    r = api.post("/v1/responses", json={"previous_response_id": first["id"], "input": [
        {"type": "input_response", "input_request_id": item["id"], "answer": "zh"}]})
    assert r.status_code == 409 and r.json()["error"]["detail"]["state"] == "voided"


def test_a_task_naming_only_the_session_passes_the_question_over(api, monkeypatch):
    """Tasks §3.2: a later task voids the question however it names the session. An answer that
    arrives after it is refused, and runs nothing: a stale `confirm` must not be acted on."""
    fake = _FakeRunner()
    monkeypatch.setattr(gw, "_resp_execute", fake)
    hid = _harness(api)
    first = api.post("/v1/responses", json={"input": "ask me which language", "metadata": {"harness_id": hid}}).json()
    item = first["output"][-1]
    sid = first.get("session_id") or first["metadata"]["session_id"]
    r = api.post("/v1/responses", json={"input": "something else", "metadata": {"harness_id": hid, "session_id": sid}})
    assert r.status_code == 200, r.text
    assert r.json()["metadata"]["voided_input_requests"] == [item["id"]]
    r = api.post("/v1/responses", json={"previous_response_id": first["id"], "input": [
        {"type": "input_response", "input_request_id": item["id"], "answer": "zh"}]})
    assert r.status_code == 409, r.text
    assert len(fake.calls) == 2, "the stale answer ran no turn"


def test_an_answer_is_not_in_the_stored_request_hash():
    def body(answer, rid="q1"):
        return gw.CreateResponseBody(input=[{"type": "input_response", "input_request_id": rid, "answer": answer}])
    assert gw._req_hash(body("123456")) == gw._req_hash(body("654321"))
    assert gw._req_hash(body("123456")) != gw._req_hash(body("123456", "q2"))


def test_a_secret_answer_reaches_the_harness_and_nothing_a_client_reads(api, monkeypatch):
    fake = _FakeRunner()
    monkeypatch.setattr(gw, "_resp_execute", fake)
    hid = _harness(api)
    first = api.post("/v1/responses", json={"input": "need the token", "metadata": {"harness_id": hid}}).json()
    item = first["output"][-1]
    assert item["kind"] == "secret"
    secret = "tok-" + uuid.uuid4().hex
    r = api.post("/v1/responses", json={"previous_response_id": first["id"], "input": [
        {"type": "input_response", "input_request_id": item["id"], "answer": secret}]})
    assert r.status_code == 200, r.text
    second = r.json()
    assert secret not in r.text
    name = "HR_INPUT_" + item["id"].upper()
    assert fake.calls[1]["extra_env"] == {name: secret} and fake.calls[1]["extra_secret"] == [name]
    assert secret not in fake.calls[1]["prompt"] and name in fake.calls[1]["prompt"]
    assert secret not in fake.calls[1]["user_text"]
    assert secret not in api.get(f"/v1/responses/{second['id']}").text
    assert secret not in api.get(f"/v1/responses/{second['id']}/input_items").text
    assert secret not in api.get(f"/v1/responses/{first['id']}").text


def _items(body):
    return body.get("data") if isinstance(body, dict) and isinstance(body.get("data"), list) else (
        body if isinstance(body, list) else body.get("input") or body.get("items") or [])


# ── what the server says it does ─────────────────────────────────────────────────────────────────

def test_the_capability_is_declared_and_the_base_that_has_it_is_named():
    assert gw.UHP_CAPABILITIES["input_requests"] is True
    assert gw._BASE_CATALOG["claude-code"]["input_requests"] is True
    assert gw._INPUT_REQUEST_BASES == {"claude"}
    assert all(not b.get("input_requests") for k, b in gw._BASE_CATALOG.items() if k != "claude-code")
