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


def _is_answer(node: ast.AST, helpers: set[str]) -> bool:
    """A call that hands back a Result: a client verb, or a helper of the module that returns one."""
    if not isinstance(node, ast.Call):
        return False
    parts = _dotted(node.func).split(".")
    if len(parts) >= 2 and parts[-1] in RESULT_VERBS and parts[-2] == "client":
        return True
    return isinstance(node.func, ast.Name) and node.func.id in helpers


def _bound(func: ast.AST, helpers: set[str]) -> set[str]:
    """The names one function gives an answer to. Gathered over the whole function before any read
    is looked at: an assignment three blocks deep comes later in a walk than a read one block deep,
    and a scan that binds as it goes walks past that read."""
    names = set()
    for node in ast.walk(func):
        targets = (node.targets if isinstance(node, ast.Assign)
                   else [node.target] if isinstance(node, (ast.AnnAssign, ast.NamedExpr)) else [])
        if targets and _is_answer(getattr(node, "value", None), helpers):
            names |= {t.id for t in targets if isinstance(t, ast.Name)}
    return names


def _functions(tree: ast.AST) -> list:
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _answer_helpers(tree: ast.AST) -> set[str]:
    """The module's functions that return a Result: one that returns a client call, a name bound
    to one, or another such helper's answer. Repeated until nothing is added, so a helper that
    wraps a helper counts."""
    helpers: set[str] = set()
    while True:
        found = set()
        for func in _functions(tree):
            if func.name in helpers:
                continue
            bound = _bound(func, helpers)
            for node in ast.walk(func):
                if isinstance(node, ast.Return) and node.value is not None and (
                        _is_answer(node.value, helpers)
                        or (isinstance(node.value, ast.Name) and node.value.id in bound)):
                    found.add(func.name)
        if not found:
            return helpers
        helpers |= found


def _scan(source: str) -> tuple[int, set[str]]:
    """How many answers the source reads, and every attribute it reads off one.

    Three ways the checks hold an answer, all of them looked at: a name assigned from a client
    call, a name assigned from a helper that returns one, and no name at all (`client.get(p).json`).
    Scoped per function on purpose: `e` is a Result in one and a dict in the next, and a
    module-wide name set would blame whichever pairing happens to be read later.
    """
    tree = ast.parse(source)
    helpers = _answer_helpers(tree)
    answers, read = 0, set()
    for func in _functions(tree):
        bound = _bound(func, helpers)
        answers += len(bound)
        for node in ast.walk(func):
            if not isinstance(node, ast.Attribute):
                continue
            if isinstance(node.value, ast.Name) and node.value.id in bound:
                read.add(node.attr)
            elif _is_answer(node.value, helpers):
                answers += 1
                read.add(node.attr)
    return answers, read


def _members() -> set[str]:
    return set(Result.__dataclass_fields__) | {n for n in dir(Result) if not n.startswith("__")}


def test_everything_the_checks_read_off_a_result_is_something_a_result_has():
    """A typo in a failure message waits until a server misbehaves to surface, so catch it here."""
    answers, read = _scan(inspect.getsource(checks))
    assert answers, "the scan found no client response anywhere, which means it stopped working"
    missing = read - _members()
    assert not missing, f"checks read {sorted(missing)} off a Result, which has only {sorted(_members())}"


@pytest.mark.parametrize("source", [
    # a name assigned from a client call, the read inside a message that never runs
    "def c(ctx):\n    r = ctx.client.get('/x')\n    assert r.status == 200, r.txt\n",
    # the assignment deeper in the function than the read: a scan that binds as it walks misses it
    "def c(ctx, ps):\n    if ps:\n        for p in ps:\n            r = ctx.client.get(p)\n    return r.txt\n",
    # the answer comes back from a helper of the module
    "def _h(ctx):\n    return ctx.client.post('/x')\n\ndef c(ctx):\n    r = _h(ctx)\n    assert r.status == 200, r.txt\n",
    # ...or from a helper that wraps that helper, or one that returns a name it bound
    "def _h(ctx):\n    r = ctx.client.post('/x')\n    return r\n\ndef _g(ctx):\n    return _h(ctx)\n\n"
    "def c(ctx):\n    done = _g(ctx)\n    assert done.status == 200, done.txt\n",
    # no name at all: the attribute is read straight off the call
    "def c(ctx):\n    return ctx.client.get('/x').txt\n",
    "def _h(ctx):\n    return ctx.client.post('/x')\n\ndef c(ctx):\n    return _h(ctx).txt\n",
    # an annotated assignment and an assignment expression bind like a plain one
    "def c(ctx):\n    r: object = ctx.client.get('/x')\n    return r.txt\n",
    "def c(ctx):\n    if (r := ctx.client.get('/x')).status:\n        return r.txt\n",
], ids=["assigned", "bound-deeper-than-read", "from-a-helper", "helper-of-a-helper", "straight-off-the-call",
        "straight-off-a-helper", "annotated", "assignment-expression"])
def test_the_scan_sees_every_way_a_check_holds_an_answer(source):
    """The scan is only worth its place if a wrong name cannot hide behind how the answer is held."""
    answers, read = _scan(source)
    assert answers and "txt" in read, (answers, read)
    assert "txt" not in _members()


def test_the_scan_blames_nothing_that_is_not_an_answer():
    """A dict's own `get`, and a name that is an answer in one function and a dict in the next."""
    source = ("def a(ctx):\n    e = ctx.client.get('/x')\n    return e.status\n\n"
              "def b(d):\n    e = d.get('k')\n    e.items()\n    return d.get('x').keys()\n")
    assert _scan(source) == (1, {"status"})


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
