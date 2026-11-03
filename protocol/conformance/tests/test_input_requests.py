"""T-13 and T-14 are shown to fail on servers that get a question for the person wrong (Tasks §3.2).

Nothing in the suite asked a question before this, so a server whose harness asked in prose and
reported `completed` scored as well as one that ended the turn on an `input_request` item. These
tests pin the ways it can go wrong — the question in prose, a reason with no item, an item with no
text, an answer outside the options accepted, a stale id answered 404, a question answered twice, a
secret read back — and the answers the checks have to accept: a server without the capability, and
a model that never asked, which measured nothing.
"""
from __future__ import annotations

import pathlib
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

from uhp_conformance import checks  # noqa: F401 — importing populates the registry
from uhp_conformance.client import Client
from uhp_conformance.context import Context
from uhp_conformance.registry import REGISTRY, Outcome

STUB = pathlib.Path(__file__).parent / "input_request_stub.py"
IDS = ("T-13", "T-14")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run(defect: str) -> dict[str, Outcome]:
    port = _free_port()
    srv = subprocess.Popen([sys.executable, str(STUB)],
                           env={"DEFECT": defect, "PORT": str(port), "PATH": "/usr/bin:/bin"},
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/uhp", timeout=1).read()
                break
            except (urllib.error.URLError, OSError):
                time.sleep(0.05)
        else:
            pytest.fail(f"the stub did not start for defect {defect!r}")
        ctx = Context(client=Client(f"http://127.0.0.1:{port}", "stub-key"), task_timeout=30.0)
        # the discovery document, as the suite's D-series leaves it for the capability-gated checks
        ctx.state["discovery"] = ctx.client.get("/v1/uhp").json
        return {c.id: c.run(ctx).outcome for c in REGISTRY if c.id in IDS}
    finally:
        srv.terminate()
        srv.wait(timeout=5)


def test_the_checks_are_registered_at_full():
    got = [c for c in REGISTRY if c.id in IDS]
    assert sorted(c.id for c in got) == list(IDS)
    assert {c.cls for c in got} == {"full"}


def test_a_conformant_server_passes():
    assert _run("none") == {"T-13": Outcome.PASS, "T-14": Outcome.PASS}


def test_a_server_without_the_capability_skips():
    assert _run("no_capability") == {"T-13": Outcome.SKIP, "T-14": Outcome.SKIP}


def test_a_model_that_never_asked_skips():
    """No question was put, so nothing about the rule was measured; a model that ignores the prompt
    must not fail the suite."""
    assert _run("never_asked") == {"T-13": Outcome.SKIP, "T-14": Outcome.SKIP}


def test_a_question_in_prose_fails():
    """The harness called ask_user and the server completed the task with the question in its
    text: a client cannot tell it from an answer, and cannot route an answer back."""
    assert _run("completed_in_prose")["T-13"] is Outcome.FAIL


def test_a_reason_with_no_item_fails():
    assert _run("no_item")["T-13"] is Outcome.FAIL


def test_a_reason_that_names_a_budget_fails():
    """`input_required` is how a client tells a question from a budget; `max_steps` on a question
    sends it to continue a task that is waiting on an answer."""
    assert _run("no_reason")["T-13"] is Outcome.FAIL


def test_an_item_with_no_text_fails():
    """A client that renders only message items is a valid client (§3.1); the question has to be
    in a message's text as well as in the item."""
    assert _run("no_text")["T-13"] is Outcome.FAIL


def test_an_answer_outside_the_options_accepted_fails():
    assert _run("accepts_any_option")["T-13"] is Outcome.FAIL


def test_a_stale_id_answered_404_fails():
    """The response exists; in this protocol a 404 says the addressed object does not."""
    assert _run("stale_is_404")["T-13"] is Outcome.FAIL


def test_a_question_answered_twice_fails():
    assert _run("answers_twice")["T-13"] is Outcome.FAIL


def test_a_continuation_that_failed_fails():
    assert _run("answer_fails")["T-13"] is Outcome.FAIL


def test_a_secret_repeated_by_the_harness_fails():
    """The turn after a secret answer carried the value in its text: the secret entered the
    conversation, and anyone reading the task back has it."""
    got = _run("secret_echoed")
    assert got["T-14"] is Outcome.FAIL and got["T-13"] is Outcome.PASS


def test_a_secret_kept_in_input_items_fails():
    assert _run("secret_in_input_items")["T-14"] is Outcome.FAIL


def test_no_check_errors_on_any_defect():
    for defect in ["none", "no_capability", "never_asked", "completed_in_prose", "no_item", "no_reason",
                   "no_text", "accepts_any_option", "stale_is_404", "answers_twice", "answer_fails",
                   "secret_echoed", "secret_in_input_items"]:
        got = _run(defect)
        assert set(got) == set(IDS), f"a check is not registered, so the defect {defect!r} was never run"
        assert Outcome.ERROR not in got.values(), defect
