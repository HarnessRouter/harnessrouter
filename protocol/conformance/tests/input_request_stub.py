"""A UHP server that gets a question for the person wrong, one way at a time (Tasks §3.2).

A task that asks ends `incomplete` with reason `input_required`, the question as an
`input_request` item and in the last message's text; the answer is an `input_response` on the
next task, checked (422 outside the options, 409 for a request the response does not hold, 409
again once answered) and run as a continuation; a `secret` answer appears nowhere a client reads.
Each defect below is one way of getting that wrong, and the last ones are the answers the checks
have to accept: a server without the capability, and a model that never asked.

The stub keeps its responses, so an answer is checked against the question that was asked, as a
real server checks it.

    DEFECT=no_item PORT=8943 python3 input_request_stub.py
"""
from __future__ import annotations

import json
import os
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

DEFECT = os.environ.get("DEFECT", "none")
PORT = int(os.environ.get("PORT", "8943"))
KEY = "stub-key"
BASE = "stub-base"

DEFECTS = {
    "none",                 # asks, checks, answers once; a secret stays out of what a client reads
    "no_capability",        # reports input_requests false: the checks skip
    "never_asked",          # the model answered without asking: nothing to measure, the checks skip
    "completed_in_prose",   # asked, then completed with the question in the text and no item
    "no_item",              # incomplete, reason input_required, no input_request item
    "no_reason",            # the item, but incomplete_details.reason names a budget
    "no_text",              # the item, but no message carries the question
    "accepts_any_option",   # an answer outside the options runs the turn (no 422)
    "stale_is_404",         # an unknown request id answers 404 instead of 409
    "answers_twice",        # the same request answered a second time runs again (no 409)
    "answer_fails",         # the continuation ends failed
    "secret_echoed",        # the turn after a secret answer repeats it in its text
    "secret_in_input_items",  # the stored input the task was created with holds the secret
}
assert DEFECT in DEFECTS, f"unknown defect {DEFECT!r}; one of {sorted(DEFECTS)}"

RESPONSES: dict[str, dict] = {}     # id -> {response, pending, input}


def _item(kind: str, prompt: str) -> dict:
    item = {"id": "inreq_" + uuid.uuid4().hex[:10], "type": "input_request", "status": "completed",
            "kind": kind, "prompt": prompt}
    if kind == "choice":
        item["options"] = [{"id": "red", "label": "Red"}, {"id": "blue", "label": "Blue"}]
    return item


def _message(text: str) -> dict:
    return {"id": "msg_" + uuid.uuid4().hex[:8], "type": "message", "role": "assistant",
            "status": "completed", "content": [{"type": "output_text", "text": text, "annotations": []}]}


def _call(name: str) -> list[dict]:
    return [{"id": "fc_1", "type": "function_call", "call_id": "call_1", "name": name,
             "arguments": "{}", "status": "completed"},
            {"id": "fco_1", "type": "function_call_output", "call_id": "call_1",
             "output": '{"status": "input_required"}', "status": "completed"}]


def _response(status: str, output: list, prev: str | None, sid: str, details=None) -> dict:
    return {"id": f"resp_{uuid.uuid4().hex[:10]}", "object": "response", "status": status,
            "model": "stub-model", "usage": None, "created_at": int(time.time()), "error": None,
            "incomplete_details": details, "previous_response_id": prev, "store": True,
            "output": output, "metadata": {"session_id": sid, "harness_id": "h1"}}


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def send(self, status: int, payload=None):
        body = b"" if payload is None else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("uhp-version", "2026-10-19")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def refuse(self, status: int, code: str, message: str = "no"):
        return self.send(status, {"error": {"type": "invalid_request_error", "code": code,
                                            "message": message, "param": None, "detail": None}})

    def do_GET(self):
        p = [x for x in urlsplit(self.path).path.split("/") if x]
        if p == ["v1", "uhp"]:
            return self.send(200, {
                "object": "uhp.discovery", "protocol": "uhp", "versions": ["2026-10-19"],
                "default_version": "2026-10-19", "conformance_class": "full",
                "capabilities": {"streaming": True, "sessions": True, "cancellation": True,
                                 "files_input": True, "files_output": True, "session_listing": True,
                                 "harness_management": True,
                                 "input_requests": DEFECT != "no_capability"}})
        if (self.headers.get("authorization") or "").removeprefix("Bearer ").strip() != KEY:
            return self.refuse(401, "invalid_credential")
        if p == ["v1", "harnesses"]:
            return self.send(200, {"harnesses": [{"id": "h1", "name": "stub", "base": BASE,
                                                 "defaultModel": "stub-model"}]})
        if len(p) == 3 and p[:2] == ["v1", "responses"] and p[2] in RESPONSES:
            return self.send(200, RESPONSES[p[2]]["response"])
        if len(p) == 4 and p[:2] == ["v1", "responses"] and p[3] == "input_items" and p[2] in RESPONSES:
            return self.send(200, {"object": "list", "data": RESPONSES[p[2]]["input"]})
        return self.refuse(404, "not_found")

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        if (self.headers.get("authorization") or "").removeprefix("Bearer ").strip() != KEY:
            return self.refuse(401, "invalid_credential")
        p = [x for x in urlsplit(self.path).path.split("/") if x]
        try:
            body = json.loads(raw)
        except Exception:  # noqa: BLE001
            body = {}
        if p != ["v1", "responses"]:
            return self.refuse(404, "not_found")
        inp = body.get("input")
        answers = [i for i in inp if isinstance(i, dict) and i.get("type") == "input_response"] \
            if isinstance(inp, list) else []
        if answers:
            return self._answer(body, answers[0])
        return self._ask(body)

    def _ask(self, body: dict):
        prompt = str(body.get("input") or "")
        kind = "secret" if '"secret"' in prompt else "choice"
        question = "The deploy token?" if kind == "secret" else "Which colour?"
        sid = f"sess_{uuid.uuid4().hex[:10]}"
        if DEFECT == "never_asked":
            r = _response("completed", [_message("ANSWERED red")], None, sid)
        elif DEFECT == "completed_in_prose":
            r = _response("completed", _call("ask_user") + [_message(question)], None, sid)
        elif DEFECT == "no_item":
            r = _response("incomplete", _call("ask_user") + [_message(question)], None, sid,
                          {"reason": "input_required"})
        else:
            item = _item(kind, question)
            out = _call("mcp__harnessrouter__ask_user")
            if DEFECT != "no_text":
                out.append(_message(question))
            out.append(item)
            r = _response("incomplete", out, None, sid,
                          {"reason": "max_steps" if DEFECT == "no_reason" else "input_required"})
        pending = _input_request(r)
        RESPONSES[r["id"]] = {"response": r, "pending": pending, "input": [{"role": "user", "content": prompt}]}
        return self.send(200, r)

    def _answer(self, body: dict, a: dict):
        prev = RESPONSES.get(str(body.get("previous_response_id") or ""))
        if prev is None:
            return self.refuse(404, "response_not_found")
        pend = prev["pending"]
        rid = str(a.get("input_request_id") or "")
        if not pend or pend["id"] != rid:
            if DEFECT == "stale_is_404":
                return self.refuse(404, "not_found")
            if pend is None and DEFECT == "answers_twice" and prev.get("answered") == rid:
                pass        # runs again below
            else:
                return self.refuse(409, "input_not_pending")
        answer = str(a.get("answer") or "")
        if pend and pend["kind"] == "choice" and DEFECT != "accepts_any_option":
            if answer not in [o["id"] for o in pend.get("options") or []]:
                return self.refuse(422, "input_response_invalid")
        prev["pending"], prev["answered"] = None, rid
        sid = prev["response"]["metadata"]["session_id"]
        text = "RECEIVED" if (pend or {}).get("kind") == "secret" else f"ANSWERED {answer}"
        if DEFECT == "secret_echoed":
            text = f"RECEIVED {answer}"
        status = "failed" if DEFECT == "answer_fails" else "completed"
        r = _response(status, [_message(text)], prev["response"]["id"], sid)
        if status == "failed":
            r["error"] = {"type": "harness_error", "code": "harness_error", "message": "it broke"}
        stored_answer = answer if DEFECT == "secret_in_input_items" or (pend or {}).get("kind") != "secret" else "[redacted]"
        RESPONSES[r["id"]] = {"response": r, "pending": None,
                              "input": [{"type": "input_response", "input_request_id": rid, "answer": stored_answer}]}
        return self.send(200, r)


def _input_request(r: dict) -> dict | None:
    items = [i for i in r["output"] if i.get("type") == "input_request"]
    return items[-1] if items else None


if __name__ == "__main__":
    print(f"stub: defect={DEFECT} port={PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
