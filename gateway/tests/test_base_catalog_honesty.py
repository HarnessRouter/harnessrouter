"""What a base advertises must be what its runtime accepts.

Found by the custom-harness dimension: omp's entry listed "python" and "browser" as hard-enforced
switches, so the console offered toggles that put an unknown name on omp's --tools and killed
every turn. dsh's list is the sdk profile's request header, read off a 0.1.2rc1 turn.
"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as A  # noqa: E402

# Read by probing omp 18.1.13 itself: every name below is accepted on --tools, "python" and
# "browser" are refused with "Unknown tool". runner/server.py pins the same set as ALL_OMP_TOOLS.
OMP_ACCEPTED = {"bash", "read", "write", "edit", "glob", "grep", "lsp", "todo", "task", "web_search"}
# The tools the 0.1.2rc1 sdk profile put in front of the model (request/header, 2026-09-08).
DSH_OFFERED = {"bash", "create_goal", "edit", "exit_plan_mode", "get_goal", "glob", "grep", "interrupt_agent",
               "job_kill", "job_list", "job_output", "list_agents", "ralph", "read", "read_image", "send_message",
               "skill", "str_replace_editor", "subagent", "subagent_fork", "todo_write", "update_goal",
               "web_fetch", "web_search", "workflow", "write"}


def test_omp_advertises_only_the_tools_its_binary_accepts():
    names = {n for n, _ in A._BASE_CATALOG["omp"]["tools"]}
    assert names == OMP_ACCEPTED, f"a toggle for {sorted(names - OMP_ACCEPTED)} would put a refused name on --tools"
    assert A._BASE_CATALOG["omp"]["tool_enforcement"] == "hard"
    prompt = A._BASE_CATALOG["omp"]["system_prompt"].lower()
    assert "python" not in prompt and "browser" not in prompt, "the prompt promises a tool the agent does not have"


def test_dsh_advertises_tools_its_profile_offers():
    names = {n for n, _ in A._BASE_CATALOG["dsh"]["tools"]}
    assert names <= DSH_OFFERED, f"not offered by the sdk profile: {sorted(names - DSH_OFFERED)}"
    assert A._BASE_CATALOG["dsh"]["tool_enforcement"] == "instruction"
