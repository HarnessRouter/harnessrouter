"""The Hermes patch: a tool's own error answer is not a strike against its MCP server.

Exercised on the exact hermes-agent 0.19.0 source when it is at hand (HR_HERMES_MCP_TOOL names the
file). Hermes is installed on an instance's first start, so the entrypoint applies the patch there.
"""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runner" / "patches"))
import hermes_mcp_breaker as P  # noqa: E402

SRC = "header\n" + P.TOOL_ERROR + "middle\n" + P.AFTER_CALL + "footer = 1\n"


def test_the_patch_marks_a_tool_refusal_and_the_breaker_lets_it_pass():
    out = P.patch(SRC)
    assert P.TOOL_ERROR_NEW in out and P.AFTER_CALL_NEW in out
    # run the patched post-call check on the two kinds of error answer
    ns = {"json": json}
    strikes = {"n": 0}
    ns["_bump_server_error"] = lambda s: strikes.__setitem__("n", strikes["n"] + 1)
    ns["_reset_server_error"] = lambda s: strikes.__setitem__("n", 0)
    body = "def after(result, server_name):\n" + "\n".join(line[8:] for line in P.AFTER_CALL_NEW.splitlines())
    exec(body, ns)
    refused = json.dumps({"error": "no such item: x", P.MARK: True})
    for _ in range(5):
        shown = ns["after"](refused, "company")
    assert strikes["n"] == 0 and json.loads(shown) == {"error": "no such item: x"}     # the model reads the same words
    for n in (1, 2, 3):
        ns["after"](json.dumps({"error": "MCP server 'company' is not connected"}), "company")
        assert strikes["n"] == n                                                  # a failure to reach it still counts
    ns["after"](json.dumps({"result": "ok"}), "company")
    assert strikes["n"] == 0


def test_a_source_that_moved_is_refused_and_nothing_is_written(tmp_path):
    with pytest.raises(P.Moved):
        P.patch("nothing like hermes")
    f = tmp_path / "mcp_tool.py"
    f.write_text("nothing like hermes\n")
    with pytest.raises(P.Moved):
        P.apply(str(f))
    assert f.read_text() == "nothing like hermes\n"


def test_applying_twice_changes_nothing_the_second_time(tmp_path):
    # the stand-in has to compile, as the real file does: the two blocks sit inside a function
    f = tmp_path / "mcp_tool.py"
    f.write_text("import json\n\n\ndef call(result, server_name, error_text, _sanitize_error, _bump_server_error, _reset_server_error):\n"
                 "    if True:\n        if True:\n            if error_text:\n" + P.TOOL_ERROR + P.AFTER_CALL)
    assert P.apply(str(f)) == "applied"
    once = f.read_text()
    assert once.count(P.MARK) == 2
    assert P.apply(str(f)) == "already applied" and f.read_text() == once


def test_a_result_that_does_not_compile_is_not_written(tmp_path):
    f = tmp_path / "mcp_tool.py"
    broken = "def call(:\n" + P.TOOL_ERROR + P.AFTER_CALL
    f.write_text(broken)
    with pytest.raises(SyntaxError):
        P.apply(str(f))
    assert f.read_text() == broken
    import subprocess
    r = subprocess.run([sys.executable, str(ROOT / "runner" / "patches" / "hermes_mcp_breaker.py"), str(f)], capture_output=True, text=True)
    assert r.returncode == 4 and "NOT applied" in r.stdout and "Traceback" not in r.stderr and f.read_text() == broken
    f.write_text("x = 1\n")
    r = subprocess.run([sys.executable, str(ROOT / "runner" / "patches" / "hermes_mcp_breaker.py"), str(f)], capture_output=True, text=True)
    assert r.returncode == 3 and "NOT applied" in r.stdout and f.read_text() == "x = 1\n"


def test_the_entrypoint_applies_it_on_every_start_and_can_never_stop_the_start():
    sh = (ROOT / "docker" / "entrypoint.sh").read_text()
    assert "if wanted hermes; then verify_hermes_mcp; verify_hermes_breaker; fi" in sh
    body = sh[sh.index("verify_hermes_breaker() {"):]
    body = body[:body.index("\n}\n")]
    assert "/app/runner/patches/hermes_mcp_breaker.py" in body and body.rstrip().endswith("return 0")
    assert "|| true" in body                       # the patch's own exit status is read from its words, not trusted to `set -e`


@pytest.mark.skipif(not os.environ.get("HR_HERMES_MCP_TOOL"), reason="the hermes source is not at hand")
def test_the_real_file_takes_the_patch(tmp_path):
    src = Path(os.environ["HR_HERMES_MCP_TOOL"]).read_text()
    out = P.patch(src)
    assert out.count(P.MARK) == 2
    compile(out, str(tmp_path / "mcp_tool.py"), "exec")
