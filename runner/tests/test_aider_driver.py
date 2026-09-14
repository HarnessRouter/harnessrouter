"""The aider backend (Aider-AI/aider, Apache-2.0, pinned to 0.86.2).

aider is the only backend here driven IN PROCESS, and every test below pins one of the reasons why.
The reason that decided it: on stdout, model prose beginning `litellm.AuthenticationError:` is
BYTE-IDENTICAL to a real 401 — same stream, same exit code 0 — so a text-parsing normaliser would
turn ordinary answers into provider failures. In process the channels are separate at the source.

Source anchors (all 0.86.2):
  return_coder / forced yes_always   aider/main.py:451, 546-547
  the ONE explicit_yes_required site aider/coders/base_coder.py handle_shell_commands
  shell extraction, diff format only aider/coders/editblock_coder.py get_edits
  shell output is not reflected      aider/coders/base_coder.py:1609-1614
  MODEL_ALIASES (21 rewrites)        aider/models.py:87-111
  TAGS_CACHE_DIR, no CLI flag        aider/repomap.py:43
"""
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import aider_driver  # noqa: E402
from server import (Auth, BACKENDS, _aider_eof, _aider_mcp_block,  # noqa: E402
                    _aider_to_claude, _agent_doc_path, _build_aider, _resume_lost)


# ── the policy gate: what makes tool_enforcement "hard" true rather than asserted ──
def test_an_ordinary_command_is_approved_and_named_shell():
    g = aider_driver._Gate([])
    assert g.decide("python3 stamp.py") == (True, "Shell", "")


def test_disabling_shell_refuses_the_command_the_model_proposed():
    g = aider_driver._Gate(["Shell"])
    approved, tool, reason = g.decide("python3 stamp.py")
    assert approved is False and tool == "Shell"
    assert "disabled shell commands" in reason


def test_an_mcp_call_is_named_for_the_tool_it_invokes():
    """The bridge's call form. Naming the call after the MCP tool is what lets the support matrix
    measure `mcp_called` from a command that actually ran — aider itself has no MCP client at all
    (zero source hits across the 0.86.2 tree)."""
    g = aider_driver._Gate([])
    assert g.mcp_tool_of("mcptools call deepwiki read_wiki_structure --params {}") == \
        ("deepwiki", "read_wiki_structure")
    approved, tool, _ = g.decide("mcptools call deepwiki read_wiki_structure --params {}")
    assert approved is True and tool == "deepwiki.read_wiki_structure"


def test_disabling_an_mcp_tool_refuses_it_by_its_own_name():
    g = aider_driver._Gate(["read_wiki_structure"])
    approved, tool, reason = g.decide("mcptools call deepwiki read_wiki_structure --params {}")
    assert approved is False and tool == "deepwiki.read_wiki_structure"
    assert "read_wiki_structure" in reason


def test_a_command_that_merely_mentions_mcptools_is_not_an_mcp_call():
    """`mcptools` in prose, or a bare `mcptools tools <url>` discovery call, is a shell command —
    only the four-part `call` form names a tool, and treating anything else as one would invent an
    MCP call in the turn record."""
    g = aider_driver._Gate([])
    assert g.mcp_tool_of("echo mcptools call x y") == ("", "")
    assert g.mcp_tool_of("mcptools tools https://example/mcp") == ("", "")


def test_an_unparseable_command_does_not_crash_the_gate():
    g = aider_driver._Gate([])
    assert g.mcp_tool_of('mcptools call "unclosed') == ("", "")


# ── the normalizer ───────────────────────────────────────────────────────────────
def _norm(events):
    state: dict = {}
    out = []
    for e in events:
        out += _aider_to_claude(e, state)
    return out, state


def test_a_failure_on_the_error_channel_is_not_rendered_as_the_answer():
    """The whole point of the driver. io.tool_error is reachable only by aider itself; the model's
    prose cannot reach it. The text becomes the turn's reason and never its result."""
    out, state = _norm([
        {"m": "text", "p": {"text": "Here is what I found about the error handling."}},
        {"m": "error", "p": {"text": "litellm.AuthenticationError: Incorrect API key provided"}},
        {"m": "result", "p": {"ok": False, "final": ""}},
    ])
    rendered = [e for e in out if e.get("type") == "assistant"]
    assert len(rendered) == 1                      # the prose rendered
    res = out[-1]
    assert res["is_error"] is True
    assert "AuthenticationError" in res["result"]


def test_prose_that_merely_mentions_an_error_still_succeeds():
    """The case an anchored stdout regex cannot get right, and the driver gets right for free."""
    out, _ = _norm([
        {"m": "text", "p": {"text": "litellm.AuthenticationError: is raised when the key is bad."}},
        {"m": "result", "p": {"ok": True, "final": "litellm.AuthenticationError: is raised when the key is bad."}},
    ])
    assert out[-1]["is_error"] is False
    assert out[-1]["subtype"] == "success"


def test_an_approved_command_renders_as_a_call_and_its_real_result():
    out, _ = _norm([
        {"m": "shell_decision", "p": {"command": "python3 stamp.py", "tool": "Shell",
                                      "approved": True, "reason": ""}},
        {"m": "shell_result", "p": {"tool": "Shell", "command": "python3 stamp.py",
                                    "output": "STAMP-OK"}},
    ])
    call = out[0]["message"]["content"][0]
    res = out[1]["message"]["content"][0]
    assert call["type"] == "tool_use" and call["name"] == "Shell"
    assert call["input"] == {"command": "python3 stamp.py"}
    assert res["type"] == "tool_result" and res["tool_use_id"] == call["id"]
    assert res["is_error"] is False and res["content"] == "STAMP-OK"


def test_a_refused_command_is_a_complete_pair_with_the_policy_as_its_result():
    """Nothing ran, so the policy IS the result — and the reader sees the refusal rather than a
    call that silently never finished."""
    out, _ = _norm([{"m": "shell_decision", "p": {"command": "rm -rf /", "tool": "Shell",
                                                  "approved": False,
                                                  "reason": "the harness disabled shell commands"}}])
    assert len(out) == 2
    res = out[1]["message"]["content"][0]
    assert res["is_error"] is True and "disabled shell commands" in res["content"]


def test_usage_is_empty_rather_than_aiders_own_numbers():
    """aider fills the real field names with a tiktoken ESTIMATE when streaming (587 against a true
    595, measured) and reads cache under names an OpenAI response never carries. Per the 2026-09-13
    decision the relay supplies these, and no harness PR builds its own usage pipeline."""
    out, _ = _norm([{"m": "result", "p": {"ok": True, "final": "done"}}])
    assert out[0]["usage"] == {}


def test_eof_only_speaks_when_the_driver_never_reached_its_result():
    assert _aider_eof({"final": "x"}, 0)[0]["subtype"] == "success"
    assert _aider_eof({"_aider_error": "boom"}, 1)[0]["result"] == "boom"


def test_backend_is_registered_with_its_eof():
    assert BACKENDS["aider"]["normalize"] is _aider_to_claude
    assert getattr(BACKENDS["aider"]["normalize"], "eof", None) is _aider_eof


# ── argv, environment and the bridge ─────────────────────────────────────────────
def _build(**kw):
    d = tempfile.mkdtemp()
    env: dict = {}
    cmd = _build_aider("openai-api", Auth(api_key="sk-t", base_url="https://up.example/v1"),
                       "gemini-2.5-pro", "do it", d, env, **kw)
    return cmd, d, env, json.loads(cmd[-1])


def test_the_model_id_is_prefixed_so_aiders_alias_table_cannot_rewrite_it():
    """MODEL_ALIASES rewrites 21 BARE ids, `gemini-2.5-pro` among them — an id this catalog also
    serves. The openai/ prefix routes through litellm verbatim and skips that table, which is the
    same class of silent substitution that pruned the gemini catalog."""
    _, _, _, job = _build()
    assert job["model"] == "openai/gemini-2.5-pro"


def test_the_real_key_never_reaches_aider():
    _, _, env, _ = _build()
    assert env["OPENAI_API_KEY"].startswith("hr-relay-")
    assert env["OPENAI_API_BASE"] != "https://up.example/v1"


def test_the_mcp_bridge_block_names_the_servers_and_the_call_form():
    block = _aider_mcp_block([{"name": "deepwiki", "url": "https://mcp.deepwiki.com/mcp"}])
    assert "deepwiki" in block and "https://mcp.deepwiki.com/mcp" in block
    assert "mcptools call" in block          # the exact form the gate recognises
    assert "```bash" in block                # the only surface aider can propose a tool through


def test_no_mcp_block_without_servers():
    assert _aider_mcp_block([]) == ""
    assert _aider_mcp_block(None) == ""


def test_agent_doc_is_written_as_agents_md_even_though_aider_reads_it_via_read():
    assert _agent_doc_path("/ws", "aider").name == "AGENTS.md"


# ── a lost conversation must not answer from an empty history ────────────────────
def test_resume_lost_reads_the_history_file_because_there_is_no_session_id():
    """aider has no session id at all, and a missing history file resumes silently with no output
    difference whatsoever. The store question is "does the history hold a message?"."""
    d = tempfile.mkdtemp()
    assert _resume_lost("aider", ["aider"], "s1", d) == "s1"
    hist = pathlib.Path(d, ".harness", "aider", "chat.history.md")
    hist.parent.mkdir(parents=True)
    hist.write_text("# aider chat started at 2026-09-13\n\n")   # a file, but no exchange
    assert _resume_lost("aider", ["aider"], "s1", d) == "s1"
    hist.write_text("# aider chat started\n\n#### do the thing\n\nok\n")
    assert _resume_lost("aider", ["aider"], "s1", d) is None


# ── the in-turn loop the maintainer asked to be measured ─────────────────────────
class _FakeCoder:
    """Enough Coder to exercise the shell-reporting wrapper without aider installed."""
    def __init__(self, output="STAMP-OK"):
        self.shell_commands = ["python3 stamp.py"]
        self.reflected_message = None
        self.runs = 0
        self._output = output

    def run_shell_commands(self):
        self.runs += 1
        return "\n".join(f"Output from {c}\n{self._output}" for c in self.shell_commands)


def test_shell_output_is_fed_back_so_the_model_sees_it_in_the_same_turn():
    """aider stashes shell output for the NEXT user message and sets no reflection of its own
    (base_coder.py:1609-1614), unlike its lint and test paths. Without this the model can never
    report what its command printed, and every other backend here can. Measured against a stub with
    the reflection on: two provider round trips and the answer carries the script's output; with it
    off, one round trip and the answer is the ```bash block itself."""
    c = _FakeCoder()
    g = aider_driver._Gate([])
    g.calls.append({"command": "python3 stamp.py", "tool": "Shell", "approved": True, "reason": ""})
    aider_driver._run_shell_commands_reporting(c, g, reflect=True)
    c.run_shell_commands()
    assert c.reflected_message and "STAMP-OK" in c.reflected_message


def test_a_reflection_does_not_re_run_the_command_it_reported():
    """The bug this wrapper introduced and this test pins: init_before_message() empties
    shell_commands once per TURN, not per reflection, so with a reflection set the next pass
    re-ran every command already executed. Measured before the fix: one proposed command ran four
    times and the turn made four round trips instead of two, side effects repeated each time."""
    c = _FakeCoder()
    g = aider_driver._Gate([])
    aider_driver._run_shell_commands_reporting(c, g, reflect=True)
    c.run_shell_commands()
    assert c.shell_commands == []          # cleared, so a reflection cannot replay it
    c.reflected_message = None             # _run_turn clears this at the top of every pass
    c.run_shell_commands()                 # the reflection's pass
    # nothing left to run, so no output, so no second reflection: the loop ends after one.
    assert c.runs == 2 and c.reflected_message is None


def test_reflection_can_be_turned_off_and_then_aider_behaves_as_shipped():
    c = _FakeCoder()
    g = aider_driver._Gate([])
    aider_driver._run_shell_commands_reporting(c, g, reflect=False)
    c.run_shell_commands()
    assert c.reflected_message is None
