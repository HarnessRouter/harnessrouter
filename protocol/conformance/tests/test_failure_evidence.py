"""A check that quotes the server's answer has to be able to read it as text.

Eighteen failure messages across ten checks and three shared helpers are built from
`r.text[:200]`, but `Result` carries `body` as bytes and offers `json` and `header()` — there is no
`text`. An assert's message is evaluated only when the assertion fails, so against a conformant
server the missing attribute is invisible. Against a server that really does refuse the call the
assert raises `AttributeError` rather than `AssertionError`, and the registry files that as ERROR —
"the check itself broke — a bug in the suite" (README) — so a genuine non-conformance is reported as
a defect in the suite, and the server's own sentence about why it refused never reaches the report.

The first test below is the reason this is a rule rather than a one-off patch: an attribute name in
a message that never runs cannot be caught by running the suite, but it can be caught by reading it.
"""
from __future__ import annotations

import ast
import contextlib
import inspect
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from uhp_conformance import checks  # noqa: F401 — importing populates the registry
from uhp_conformance.client import Client, Result
from uhp_conformance.context import Context
from uhp_conformance.registry import REGISTRY, Outcome

# The client verbs that hand back a Result; `stream` returns parsed events, not one.
RESULT_VERBS = {"get", "post", "put", "delete", "request"}
REFUSAL = "the storage backend is mounted read-only"
UNDECODABLE = b"\xff\xfe\x00what the server actually sent"


def _dotted(node: ast.AST) -> str:
    """`ctx.client.post(...)` reads back as "ctx.client.post", so the verb cannot be told apart
    from a dict's own `get` until you can see whose method it is."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _reads_in_scope(func: ast.AST) -> tuple[set[str], set[str]]:
    """One function's own answer variables and the attributes read straight off them.

    Scoped per function on purpose: `e` is a Result in one and a dict in the next, and a
    module-wide name set would blame whichever pairing happens to be read later.
    """
    bound, read = set(), set()
    for node in ast.walk(func):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            parts = _dotted(node.value.func).split(".")
            if len(parts) >= 2 and parts[-1] in RESULT_VERBS and parts[-2] == "client":
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        bound.add(target.id)
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id in bound:
                read.add(node.attr)
    return bound, read


def test_everything_the_checks_read_off_a_result_is_something_a_result_has():
    """A typo in a failure message waits until a server misbehaves to surface, so catch it here."""
    tree = ast.parse(inspect.getsource(checks))
    members = set(Result.__dataclass_fields__) | {n for n in dir(Result) if not n.startswith("__")}
    total, missing = 0, set()
    for func in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        bound, read = _reads_in_scope(func)
        total += len(bound)
        missing |= read - members
    assert total, "the scan bound no client response anywhere, which means it stopped working"
    assert not missing, f"checks read {sorted(missing)} off a Result, which has only {sorted(members)}"


def _run(check_id: str, base: str):
    ctx = Context(client=Client(base, "stub-key"), task_timeout=10.0)
    result = next(c for c in REGISTRY if c.id == check_id).run(ctx)
    return result.outcome, result.detail


@contextlib.contextmanager
def _refusing_server(body: bytes):
    """A server that declares environments, then refuses to create one in these bytes."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self._reply(200, "application/json",
                        json.dumps({"capabilities": {"environments": True}}).encode())

        def do_POST(self):
            self.rfile.read(int(self.headers.get("content-length", 0)))
            self._reply(500, "text/plain", body)

        def _reply(self, status: int, content_type: str, payload: bytes):
            self.send_response(status)
            self.send_header("content-type", content_type)
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.mark.parametrize("body", [REFUSAL.encode(), UNDECODABLE], ids=["plain", "undecodable"])
def test_a_refused_environment_creation_is_a_finding_not_a_suite_error(body):
    """EN-01's symptom: HTTP 500 must reach the report as FAIL, whatever the body holds."""
    with _refusing_server(body) as base:
        outcome, detail = _run("EN-01", base)
    assert outcome is Outcome.FAIL, f"the suite reported {outcome}: {detail}"
    assert "HTTP 500" in detail, detail


def test_the_servers_own_reason_survives_into_the_report():
    """The point of the message: whoever reads the report learns why the call was refused."""
    with _refusing_server(REFUSAL.encode()) as base:
        outcome, detail = _run("EN-01", base)
    assert outcome is Outcome.FAIL, f"the suite reported {outcome}: {detail}"
    assert REFUSAL in detail, detail


def test_text_is_the_body_decoded_and_never_raises():
    assert Result(500, {}, REFUSAL.encode(), 0.1, "u", "POST").text == REFUSAL
    assert Result(500, {}, b"", 0.1, "u", "POST").text == ""
    assert Result(500, {}, UNDECODABLE, 0.1, "u", "POST").text  # replacement, not an exception
