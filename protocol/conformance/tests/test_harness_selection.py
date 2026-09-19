"""The suite says which harness its tasks run on and never falls back silently (#203), and an
installation without the schema is an error of the suite, never a skip that reads as the server's.
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from uhp_conformance import checks, context
from uhp_conformance.client import Client
from uhp_conformance.context import Context
from uhp_conformance.registry import Outcome, REGISTRY


HARNESSES = [{"id": "chrn_first", "name": "first", "defaultModel": "m1"},
             {"id": "chrn_second", "name": "second", "defaultModel": ""}]


class _Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/v1/harnesses":
            body, status = {"harnesses": HARNESSES}, 200
        elif path.startswith("/v1/harnesses/"):
            hid = path.rsplit("/", 1)[1]
            found = [h for h in HARNESSES if h["id"] == hid]
            body, status = (found[0], 200) if found else ({"error": {"code": "harness_not_found"}}, 404)
        else:
            body, status = {"object": "uhp.discovery", "versions": ["2026-09-12"]}, 200
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


@pytest.fixture(scope="module")
def stub():
    srv = HTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _cli(*args):
    return subprocess.run([sys.executable, "-m", "uhp_conformance.cli", *args],
                          capture_output=True, text=True, timeout=60)


def test_a_harness_id_that_matches_nothing_stops_the_run_before_the_first_task(stub):
    r = _cli("--base-url", stub, "--api-key", "k", "--harness-id", "smoke-hermes", "--class", "core")
    assert r.returncode == 2
    assert "no harness with id 'smoke-hermes'" in r.stderr and "not its name" in r.stderr


def test_a_named_harness_without_a_default_model_needs_a_model(stub):
    r = _cli("--base-url", stub, "--api-key", "k", "--harness-id", "chrn_second", "--class", "core")
    assert r.returncode == 2 and "has no default model" in r.stderr


def test_the_harness_the_tasks_run_on_is_announced(stub):
    r = _cli("--base-url", stub, "--api-key", "k", "--harness-id", "chrn_first", "--class", "core",
             "--only", "D-01", "--plain")
    assert "tasks run on harness chrn_first (first), model m1" in r.stderr


def test_the_checks_never_fall_back_to_another_harness(stub):
    ctx = Context(client=Client(stub, "k"), harness_id="chrn_gone")
    with pytest.raises(RuntimeError, match="no harness with id 'chrn_gone'"):
        checks._harness(ctx)
    ctx = Context(client=Client(stub, "k"), harness_id="chrn_second")
    assert checks._harness(ctx)["id"] == "chrn_second"
    ctx = Context(client=Client(stub, "k"))
    assert checks._harness(ctx)["id"] == "chrn_first"      # unnamed: the first listed


def test_a_missing_schema_is_an_error_of_the_suite_not_a_skip(monkeypatch, tmp_path):
    """Thirty checks once skipped on an install without the schema and the report read as a
    partial server (#203). The check reports ERROR: the suite could not run."""
    monkeypatch.setattr(context, "SCHEMA_RESOURCE", tmp_path / "absent.json")
    ctx = Context(client=Client("http://unused.invalid", ""))
    with pytest.raises(RuntimeError, match="schema is missing from this installation"):
        ctx.validate({"id": "x"}, "File")
    monkeypatch.setattr(context, "jsonschema", None)
    with pytest.raises(RuntimeError, match="jsonschema is not installed"):
        Context(client=Client("http://unused.invalid", "")).validate({}, "File")
    check = next(c for c in REGISTRY if c.id == "D-03")
    r = check.run(Context(client=Client("http://unused.invalid", "")))
    assert r.outcome is Outcome.ERROR and "jsonschema is not installed" in r.detail
