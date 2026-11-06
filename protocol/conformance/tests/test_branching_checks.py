"""Positive and defective servers prove each branch check enforces its claimed behavior."""
import io
import json
import zipfile

import pytest

from uhp_conformance import checks
from uhp_conformance.client import Result
from uhp_conformance.context import Context
from uhp_conformance.registry import REGISTRY, Outcome


def answer(body, status=200, raw=None):
    return Result(status, {}, json.dumps(body).encode() if raw is None else raw, 0, "fixture", "GET")


class BranchServer:
    def __init__(self, defect=""):
        self.defect = defect
        self.number = 0
        self.filename = self.future = self.token = ""
        self.source = {}
        self.first = {}
        self.target = {}
        self.pending = False
        self.extra = []

    def post(self, path, *, body=None):
        if path.endswith("/cancel"):
            return answer({})
        if body.get("background"):
            self.pending = True
            return answer({"id": "running", "status": "in_progress", "metadata": {"session_id": "pending"}})
        if body.get("branch") and not body.get("previous_response_id"):
            if self.defect != "runs_unbranched":
                return answer({"error": {"code": "invalid_input", "param": "branch"}}, 400)
            self.extra.append("unbranched")
            return answer({"id": "unbranched", "metadata": {"session_id": "source", "ignored_fields": ["branch"]}})
        if body.get("previous_response_id") == "branch":
            return answer({"id": "branch-2", "metadata": {"session_id": "target",
                **({"branched_from": "r1"} if self.defect == "origin_every_turn" else {})}})
        if body.get("previous_response_id") == "running":
            return answer({"error": {"code": "session_busy" if self.defect == "wrong_error" else "branch_unavailable"}}, 409)
        if body.get("branch"):
            if self.defect == "unavailable":
                return answer({"error": {"code": "branch_unavailable"}}, 409)
            self.target = dict(self.source if self.defect == "latest" else self.first)
            if self.defect == "mutates_source":
                self.source = dict(self.first)
            return answer({"id": "branch", "metadata": {"session_id": "source" if self.defect == "same_session" else "target",
                **({} if self.defect == "no_origin" else {"branched_from": "r1"})}})
        self.number += 1
        if self.number == 1:
            self.filename = body["input"].split()[1]
            self.token = self.filename.removeprefix("branch-").removesuffix(".txt")
            self.future = "future-" + self.token + ".txt"
            self.source = {self.filename: (self.token + "-one").encode()}
            self.first = dict(self.source)
        else:
            self.source[self.filename] = (self.token + "-" + str(self.number)).encode()
            self.source[self.future] = b"later"
        return answer({"id": "r" + str(self.number), "metadata": {"session_id": "source"}})

    def get(self, path):
        if path.endswith("/files/archive"):
            stream = io.BytesIO()
            data = self.target if "/target/" in path else self.source
            with zipfile.ZipFile(stream, "w") as archive:
                for name, body in data.items():
                    archive.writestr(name, body)
            return answer({}, raw=stream.getvalue())
        if path.endswith("/turns"):
            return answer({"turns": ["r1", "r2", "r3"] + self.extra})
        if path.endswith("/target"):
            origin = {"response_id": "r1", "session_id": "source"}
            if self.defect == "with_turn":
                origin["turn"] = 1
            elif self.defect == "bad_turn":
                origin["turn"] = 3
            return answer({"branched_from": {} if self.defect == "detail" else origin})
        if path.endswith("/running"):
            return answer({"status": "in_progress"})
        raise AssertionError(path)


def run(check, defect=""):
    ctx = Context(BranchServer(defect), state={"harness": {"id": "fixture"}})
    item = next(item for item in REGISTRY if item.id == check)
    return item.run(ctx)


@pytest.mark.parametrize("check", ["B-01", "B-02", "B-03", "B-04", "B-05", "B-06"])
def test_correct_branch_server_passes(check):
    result = run(check)
    assert result.outcome is Outcome.PASS, result.detail


def test_a_session_detail_with_the_right_turn_passes():
    assert run("B-03", "with_turn").outcome is Outcome.PASS


@pytest.mark.parametrize("check,defect", [("B-01", "latest"), ("B-01", "same_session"),
    ("B-01", "no_origin"), ("B-02", "mutates_source"), ("B-03", "detail"), ("B-03", "bad_turn"),
    ("B-04", "wrong_error"), ("B-05", "runs_unbranched"), ("B-06", "origin_every_turn")])
def test_specific_defects_fail(check, defect):
    result = run(check, defect)
    assert result.outcome is Outcome.FAIL, result.detail


def test_fresh_fixture_unavailable_checkpoint_fails_full_conformance():
    assert run("B-01", "unavailable").outcome is Outcome.FAIL
