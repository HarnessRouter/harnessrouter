"""The files checks, tested by being shown to fail.

X-05 sends its file inline and X-09 uploads it through `POST /v1/files`. A server whose upload
endpoint fails outright must fail X-09 and still pass X-05 — that pair is the gap HarnessRouter
CE 0.17.3 shipped through (#198: every upload answered 500, the inline form worked, the suite was
green). Each defect in files_stub.py is caught by X-09, by no other files check, and a clean stub
passes both. No real agent runs: the stub echoes the file it was handed.
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

STUB = pathlib.Path(__file__).parent / "files_stub.py"
FILE_CHECKS = ("X-05", "X-09")
DEFECTS = ("upload_500", "upload_no_id", "upload_truncates")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run(defect: str) -> dict[str, tuple[Outcome, str]]:
    port = _free_port()
    srv = subprocess.Popen([sys.executable, str(STUB)],
                           env={"DEFECT": defect, "PORT": str(port), "PATH": "/usr/bin:/bin"})
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
        out = {}
        for c in REGISTRY:
            if c.id in FILE_CHECKS:
                r = c.run(ctx)
                out[c.id] = (r.outcome, r.detail)
        return out
    finally:
        srv.terminate()
        srv.wait(timeout=5)


def test_x09_is_registered_at_extended_after_x08():
    ids = [c.id for c in REGISTRY if c.id.startswith("X-")]
    assert ids == [f"X-{i:02d}" for i in range(1, 10)]
    assert next(c for c in REGISTRY if c.id == "X-09").cls == "extended"


def test_a_conformant_server_passes_both_and_the_stub_echoes_the_token():
    out = _run("none")
    assert out["X-05"][0] is Outcome.PASS and out["X-09"][0] is Outcome.PASS, out
    assert "echoed the token" in out["X-09"][1], out["X-09"]


def test_an_upload_endpoint_that_fails_outright_fails_x09_and_passes_x05():
    """The #198 shape: the inline form works, the upload form answers 500, and before X-09 the
    files chapter was green."""
    out = _run("upload_500")
    assert out["X-05"][0] is Outcome.PASS, out["X-05"]
    assert out["X-09"][0] is Outcome.FAIL, out["X-09"]
    assert "HTTP 500" in out["X-09"][1] and "X-05" in out["X-09"][1], out["X-09"]


@pytest.mark.parametrize("defect", DEFECTS)
def test_each_defect_is_caught_by_x09_and_by_no_other_files_check(defect):
    out = _run(defect)
    assert out["X-09"][0] is Outcome.FAIL, f"{defect!r} was not caught: {out}"
    assert out["X-05"][0] is Outcome.PASS, f"{defect!r} also failed X-05, which diagnoses one bug twice"


def test_no_check_errors_on_any_defect():
    for defect in ("none", *DEFECTS):
        out = _run(defect)
        assert Outcome.ERROR not in {o for o, _ in out.values()}, f"{defect}: {out}"
