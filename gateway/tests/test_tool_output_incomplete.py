"""A tool output the runner could not back with a complete record is marked incomplete.

The runner reads a codex command's output from codex's own record of what the model was given
(openai/codex#28207: codex's command item drops the output printed first). When no complete
record is found, its tool_result says `incomplete`, and the response's function_call_output item
carries status "incomplete" instead of "completed", so it is never passed off as the whole output.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402


def _outputs(*results: dict) -> list[dict]:
    tr = gw._RespTranslator("resp_t", "m", None, False, 0.0)
    tr.feed({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": r["tool_use_id"], "name": "Bash", "input": {"command": "x"}} for r in results]}})
    tr.feed({"type": "user", "message": {"content": list(results)}})
    return [o for o in tr.output if o.get("type") == "function_call_output"]


def test_an_output_without_a_complete_record_is_an_incomplete_item():
    out = _outputs({"type": "tool_result", "tool_use_id": "call_A", "content": "LAST\n", "incomplete": True},
                   {"type": "tool_result", "tool_use_id": "call_B", "content": "FIRST\nLAST\n"})
    assert [(o["call_id"], o["status"], o["output"]) for o in out] == [
        ("call_A", "incomplete", "LAST\n"), ("call_B", "completed", "FIRST\nLAST\n")]
