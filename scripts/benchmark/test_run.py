"""The rules a benchmark row is decided by, pinned.

Rule 3 exists because the first pilot's third task found its own ground truth online: the tool
calls the runner stores for a turn say whether it went out, and a run that did is a finding, not
a score. The usage convention exists because a cached read counted as input made one harness
read as 30x another on the same task (#209)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render import render  # noqa: E402
from run import lookup_use, network_use, prompt_matches, provider_failure, provider_streak, tool_outcomes, usage_of  # noqa: E402


def test_three_provider_failures_in_a_row_trip_the_halt_and_a_result_resets_it():
    """The first cut counted the streak under the same lock log() takes and deadlocked on the third
    failure (measured 2026-09-18: three threads in futex wait, the run silent for half an hour)."""
    bad = {"error": "provider failure, not a result: 402 Insufficient Balance"}
    good = {"resolved": True}
    assert not provider_streak(bad) and not provider_streak(bad) and provider_streak(bad)
    assert not provider_streak(good)
    assert not provider_streak(bad) and not provider_streak(bad)
    assert not provider_streak({"error": "request failed and no session found: 502"})   # not the provider's


def test_a_providers_refusal_is_the_runners_problem_not_the_harnesss():
    """Measured 2026-09-18: a key ran dry and 150 turns recorded '402 Insufficient Balance' in
    eleven minutes, each one a failed task in the table until this told them apart."""
    assert provider_failure({"type": "harness_error", "code": "turn_failed",
                             "message": 'The turn failed: 402: {"message":"Insufficient Balance"}'})
    assert provider_failure({"message": "The turn failed: Insufficient Balance"})
    assert provider_failure("429 rate limit exceeded") and provider_failure("503 Service Unavailable")
    assert provider_failure({"message": "Invalid API key"})
    # the agent's own failure to finish is the harness's, and stays a scored fail
    assert provider_failure({"message": "cline ended: max_iterations"}) == ""
    assert provider_failure({"message": "The turn failed: exit_code=1, no diagnostic output"}) == ""
    assert provider_failure(None) == ""


def test_a_truncated_stored_prompt_still_identifies_its_session():
    """The session list keeps 1500 characters of the prompt (measured); the first recovery matched
    on the prompt's tail and found nothing for a long instruction."""
    boiler = "You are working in a workspace. " * 20
    a = boiler + "### instruction\nSort column B by the helper column J " + "x" * 2000
    b = boiler + "### instruction\nCombine the RANGES sheet into LISTS " + "y" * 2000
    assert prompt_matches(a[:1500], a) and not prompt_matches(a[:1500], b)
    assert prompt_matches("[Attached files saved in your working directory: input.xlsx]\n\n" + a[:1400], a)
    assert not prompt_matches("", a)


def test_a_web_tool_or_a_shell_that_reaches_out_is_network_use():
    """The finding names what the tool was pointed at: the session is the evidence, and one run's
    was gone with only the tool's name kept (measured 2026-09-19)."""
    assert network_use([{"name": "webfetch", "arguments": '{"url": "https://x"}'}]) == ["webfetch: https://x"]
    assert network_use([{"name": "WebSearch", "arguments": "{}"}]) == ["WebSearch"]
    assert network_use([{"name": "fetch_web_content", "arguments": '{"query": "transpose rows"}'}]) == ["fetch_web_content: transpose rows"]
    hits = network_use([{"name": "bash", "arguments": json.dumps({"command": "curl -s https://example.com/answer.json"})}])
    assert hits and hits[0].startswith("bash: curl")
    assert network_use([{"name": "bash", "arguments": json.dumps({"command": "wget http://h/x"})}])


def test_pip_and_local_work_are_not_network_use():
    assert network_use([{"name": "bash", "arguments": json.dumps({"command": "pip install openpyxl pandas"})}]) == []
    assert network_use([{"name": "bash", "arguments": json.dumps({"command": "python3 -m pip install openpyxl && python3 solve.py"})}]) == []
    assert network_use([{"name": "bash", "arguments": json.dumps({"command": "ls -la && python3 solve.py"})}]) == []
    assert network_use([{"name": "read", "arguments": '{"filePath": "/workspace/input.xlsx"}'}]) == []
    assert network_use([]) == []


def test_a_url_spelled_in_code_is_not_network_use():
    """Measured: a turn that parsed the workbook with zipfile named the sheet XML's namespace,
    http://schemas.openxmlformats.org/spreadsheetml/2006/main, in a python heredoc and went
    nowhere; the first cut of this rule matched the string and called it a finding."""
    cmd = ("cd /data/workspaces/x && python3 << 'EOF'\nimport zipfile, xml.etree.ElementTree as ET\n"
           "ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}\nEOF")
    assert network_use([{"name": "bash", "arguments": json.dumps({"command": cmd})}]) == []
    assert network_use([{"name": "bash", "arguments": json.dumps({"command": "python3 -c 'import urllib.request; urllib.request.urlopen(\"http://x\")'"})}])
    assert network_use([{"name": "bash", "arguments": json.dumps({"command": "python3 -c 'import requests; requests.get(\"http://x\")'"})}])


def test_searching_the_machine_for_the_task_is_a_lookup():
    """Measured 2026-09-18: two turns recognised the suite and went looking for its data — a
    recursive grep of the whole filesystem for its vocabulary, a pip download by its name."""
    sh = lambda c: [{"name": "bash", "arguments": json.dumps({"command": c})}]
    assert lookup_use(sh('grep -rl "Sheet-Level Manipulation" / --include=*.json 2>/dev/null | head'))
    assert lookup_use(sh("grep -rl 'delete rows in an Excel worksheet' / 2>/dev/null | head -20"))
    assert lookup_use(sh("find / -name '*golden*.xlsx' 2>/dev/null"))
    assert lookup_use(sh("cd /tmp && timeout 60 pip download spreadsheetbench -d /tmp/sb --no-deps"))
    assert lookup_use(sh("rg 'answer_position' /data 2>/dev/null"))
    # the workspace is the agent's to search; pip for a library is not a lookup
    assert lookup_use(sh("grep -rn 'TOTAL' /data/workspaces/hsess1234/ | head")) == []
    assert lookup_use(sh("find /data/workspaces/hsess1234 -name '*.xlsx'")) == []
    assert lookup_use(sh("grep -r 'Sheet1' . && pip install openpyxl pandas")) == []
    assert lookup_use(sh("ls -la /data/workspaces/hsess1234")) == []


def test_usage_keeps_fresh_cached_and_output_apart():
    u = usage_of({"input_tokens": 14847, "output_tokens": 3623, "cache_read_tokens": 288000})
    assert u == {"fresh_input": 14847, "cached_input": 288000, "cache_write": 0, "output": 3623, "prompt_total": 302847}
    assert usage_of(None)["prompt_total"] == 0


def test_a_flagged_or_non_zero_tool_result_is_a_failed_call():
    """The result shapes as the trace stores them: opencode returns a shell that died as an
    ordinary result carrying "[exit code: 1]" with is_error false (measured 2026-09-18)."""
    ok = {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "1", "is_error": False,
                                                    "content": "sheets: ['Sheet1'] dims A1:D53706"}]}}
    died = {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "2", "is_error": False,
                                                      "content": "[stderr] Traceback (most recent call last):\n  ModuleNotFoundError: No module named 'openpyxl'\n[exit code: 1]"}]}}
    flagged = {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "3", "is_error": True, "content": "denied"}]}}
    use = lambda i: {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": i, "name": "bash", "input": {}}]}}
    trace = "\n".join(json.dumps(e) for e in [use("1"), ok, use("2"), died, use("3"), flagged,
                                              {"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": "..."}]}}])
    assert tool_outcomes(trace) == {"trace_tool_calls": 3, "tool_results": 3, "tool_failed": 2}
    # a result that merely mentions an exit code of zero, or none, is a success
    fine = {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "4", "is_error": False, "content": "done [exit code: 0]"}]}}
    assert tool_outcomes(json.dumps(use("4")) + "\n" + json.dumps(fine))["tool_failed"] == 0


def _rec(**kw):
    base = {"provider": "deepseek", "pack": "spreadsheetbench", "harness": "opencode", "model": "m", "task": "t",
            "resolved": True, "reward": 1.0, "wall_s": 10.0, "tool_calls": 3, "connection": "integration:deepseek",
            "served": "deepseek-flash", "usage": {"fresh_input": 100, "cached_input": 1000, "output": 10},
            "tool_results": 3, "tool_failed": 1}
    base.update(kw)
    return base


def test_a_finding_is_listed_and_left_out_of_the_score():
    md = render([_rec(task="a"), _rec(task="b", network=["webfetch"], resolved=True),
                 _rec(task="c", foreign="integration:other"), _rec(task="d", substituted=True, served="gpt-5.5")])
    row = next(line for line in md.splitlines() if line.startswith("| opencode |"))
    assert "| 1 | 1 (100%) |" in row, row            # one counted run of four
    assert "3 runs are findings, not counted" in row
    assert "reached the network: webfetch" in md and "served by integration:other" in md and "served as gpt-5.5" in md
    md = render([_rec(task="e", lookup=["bash: grep -rl x /"])])
    assert "looked for the task outside the workspace: bash: grep -rl x /" in md


def test_a_capped_run_is_a_failure_and_the_row_says_how_many():
    md = render([_rec(task="a"), _rec(task="b", resolved=False, reward=0.0, capped=900, detail="time cap 900 s; no workbook produced")])
    row = next(line for line in md.splitlines() if line.startswith("| opencode |"))
    assert "| 2 | 1 (50%) |" in row and "1 runs hit the time cap (counted as failures)" in row, row


def test_a_task_the_grader_cannot_decide_is_left_out_not_failed():
    """Two of the first fifty SpreadsheetBench tasks fail their own grader (a sheet name with
    commas, a whole-column range); every harness lost both until they were told apart."""
    md = render([_rec(task="a"), _rec(task="b", resolved=None, reward=None, detail="ungradable: the grader raises on the golden workbook: ValueError('b2b is not a valid coordinate or range')")])
    row = next(line for line in md.splitlines() if line.startswith("| opencode |"))
    assert "| 1 | 1 (100%) |" in row, row
    assert "1 runs the pack could not grade (the task fails its own grader), left out" in row and "findings" not in row


def test_an_unreported_served_model_is_noted_not_scored_against():
    md = render([_rec(served="", served_unreported=True)])
    row = next(line for line in md.splitlines() if line.startswith("| opencode |"))
    assert "| 1 | 1 (100%) |" in row
    assert "served model unreported on 1 of 1 runs" in row


def test_tokens_are_reported_apart_never_summed():
    md = render([_rec(usage={"fresh_input": 1500, "cached_input": 2_000_000, "output": 700})])
    row = next(line for line in md.splitlines() if line.startswith("| opencode |"))
    assert "| 2k | 2.00M | 1k |" in row, row


def test_wall_is_summed_and_failed_calls_are_a_rate():
    md = render([_rec(task="a", wall_s=10.0, tool_calls=3, tool_results=3, tool_failed=1),
                 _rec(task="b", wall_s=30.0, tool_calls=5, tool_results=5, tool_failed=1)])
    row = next(line for line in md.splitlines() if line.startswith("| opencode |"))
    assert "| 40 s | 20 s | 8 | 2 (25%) |" in row, row
    md = render([_rec(task="a", tool_results=3, tool_failed=1), {**_rec(task="b"), "tool_results": None, "tool_failed": None}])
    row = next(line for line in md.splitlines() if line.startswith("| opencode |"))
    assert "tool outcomes read on 1 of 2 runs" in row, row


def test_a_runner_error_is_listed_as_an_error_not_a_fail():
    md = render([_rec(task="a"), {"provider": "deepseek", "pack": "spreadsheetbench", "harness": "opencode", "model": "m",
                                  "task": "b", "error": "request failed and no session found: 502"}])
    assert "Runner errors" in md and "opencode x m b: request failed" in md
    row = next(line for line in md.splitlines() if line.startswith("| opencode |"))
    assert "| 1 | 1 (100%) |" in row
