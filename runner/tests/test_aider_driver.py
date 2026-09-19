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
import os
import pathlib
import sys
import tempfile
import types

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import aider_driver  # noqa: E402
from server import (Auth, BACKENDS, _AIDER_SESSION_NAME, _aider_eof,  # noqa: E402
                    _aider_mcp_block,
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
    assert g.mcp_calls_in("hr-mcp call deepwiki read_wiki_structure --params {}") == \
        [("deepwiki", "read_wiki_structure")]
    approved, tool, _ = g.decide("hr-mcp call deepwiki read_wiki_structure --params {}")
    assert approved is True and tool == "deepwiki.read_wiki_structure"


def test_disabling_an_mcp_tool_refuses_it_by_its_own_name():
    g = aider_driver._Gate(["read_wiki_structure"])
    approved, tool, reason = g.decide("hr-mcp call deepwiki read_wiki_structure --params {}")
    assert approved is False and tool == "deepwiki.read_wiki_structure"
    assert "read_wiki_structure" in reason


def test_a_disabled_tool_is_refused_wherever_the_call_stands_in_a_compound_command():
    """gpt-5.4, with probe_sse disabled, proposed `hr-mcp tools probe && hr-mcp call probe
    probe_sse` and a gate that read argv[0..3] saw a discovery and let the call through (hr-test,
    2026-09-18). The whole command is scanned; the bridge refuses the same name itself."""
    g = aider_driver._Gate(["probe_sse"])
    assert g.decide("hr-mcp tools probe && hr-mcp call probe probe_sse --params '{}'")[0] is False
    assert g.decide("cd x; .harness/bin/hr-mcp call probe probe_sse")[0] is False
    assert g.decide("echo | hr-mcp call probe probe_sse")[0] is False
    ok, name, _ = g.decide("hr-mcp call probe other_tool")
    assert ok and name == "probe.other_tool"
    # the bridge's own refusal, by bare name and by server.tool
    cfg = {"mcpServers": {"probe": {"url": "https://x/sse"}}, "disabledTools": ["probe_sse"]}
    assert aider_mcp_bridge._refused(cfg, "probe", "probe_sse").startswith("hr-mcp: the harness disabled")
    assert aider_mcp_bridge._refused({"disabledTools": ["probe.probe_sse"]}, "probe", "probe_sse")
    assert aider_mcp_bridge._refused(cfg, "probe", "other") == ""
    # and the runner writes the names beside the servers
    _, d, _, _ = _build(tools_disabled=["probe_sse"], mcp_servers=[{"name": "probe", "url": "https://x/sse", "transport": "sse"}])
    doc = json.loads(pathlib.Path(d, ".harness", "aider-mcp.json").read_text())
    assert doc["disabledTools"] == ["probe_sse"] and "probe" in doc["mcpServers"]


def test_a_command_that_merely_mentions_hr_mcp_is_not_an_mcp_call():
    """`hr-mcp` in prose, or a bare `hr-mcp tools <server>` discovery call, is a shell command —
    only the four-part `call` form names a tool, and treating anything else as one would invent an
    MCP call in the turn record."""
    g = aider_driver._Gate([])
    assert g.mcp_calls_in("echo hr-mcp call x y") == []
    assert g.mcp_calls_in("hr-mcp tools deepwiki") == []


def test_an_unparseable_command_does_not_crash_the_gate():
    g = aider_driver._Gate([])
    assert g.mcp_calls_in('hr-mcp call "unclosed') == []
    assert g.decide('hr-mcp call "unclosed')[1] == "Shell"


# ── the normalizer ───────────────────────────────────────────────────────────────
def _norm(events):
    state: dict = {}
    out = []
    for e in events:
        out += _aider_to_claude(e, state)
    return [e for e in out if e.get("subtype") != "init"], state


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


def test_aiders_advice_about_its_own_chat_commands_is_cut_from_the_reason():
    """show_exhausted_error ends with `- Use /tokens …`, `- Use /drop …`, `- Use /clear …`: in-chat
    commands this product never shows. Same rule kimi's resume hint earned."""
    state: dict = {"_aider_init": True}
    text = ("Model openai/gpt-5.4 has hit a token limit!\n\nInput tokens: ~300,000 of 272,000 "
            "-- possibly exhausted context window!\n\nTo reduce input tokens:\n"
            "- Use /tokens to see token usage.\n- Use /drop to remove unneeded files from the chat "
            "session.\n- Use /clear to clear the chat history.\n- Break your code into smaller source files.\n")
    _aider_to_claude({"m": "error", "p": {"text": text}}, state)
    reason = state["_aider_error"]
    assert "Use /" not in reason
    assert "hit a token limit" in reason and "Break your code into smaller source files." in reason
    ev = _aider_to_claude({"m": "result", "p": {"ok": False, "final": ""}}, state)[0]
    assert ev["is_error"] and "Use /" not in ev["result"]


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


def test_the_bridge_actually_reaches_the_model_and_is_runnable():
    """The defect this pins: the block was generated by a function nobody called, so the bridge
    existed and the model was never told it did — MCP was dead code that unit-testing the generator
    in isolation could not see. Assert the whole chain instead: config written, shim on PATH and
    executable, and the instructions appended to the doc the driver puts into the system message."""
    d = tempfile.mkdtemp()
    doc = pathlib.Path(d, "AGENTS.md")
    doc.write_text("# harness contract\n")
    env: dict = {}
    _build_aider("openai-api", Auth(api_key="sk-t", base_url="https://up.example/v1"),
                 "gpt-5.4", "do it", d, env,
                 mcp_servers=[{"name": "deepwiki", "url": "https://mcp.deepwiki.com/mcp"}])
    cfg = json.loads(pathlib.Path(d, ".harness", "aider-mcp.json").read_text())
    assert cfg == {"mcpServers": {"deepwiki": {"url": "https://mcp.deepwiki.com/mcp"}}, "disabledTools": []}
    shim = pathlib.Path(d, ".harness", "bin", "hr-mcp")
    assert shim.is_file() and shim.stat().st_mode & 0o111       # executable
    assert str(shim.parent) in env["PATH"].split(":")
    text = doc.read_text()
    assert "# harness contract" in text                          # appended, not overwritten
    assert "hr-mcp call" in text and "deepwiki" in text
    assert "```bash" in text        # the only surface aider can propose a tool through


def test_no_bridge_is_advertised_when_no_server_is_declared():
    d = tempfile.mkdtemp()
    doc = pathlib.Path(d, "AGENTS.md"); doc.write_text("# harness contract\n")
    _build_aider("openai-api", Auth(api_key="sk-t", base_url="https://up.example/v1"),
                 "gpt-5.4", "do it", d, {}, mcp_servers=[])
    text = doc.read_text()
    assert text.startswith("# harness contract\n")
    assert "hr-mcp" not in text and "## MCP servers" not in text
    assert _aider_mcp_block({}) == ""


def test_the_doc_tells_the_model_how_this_workspace_works_and_names_the_skills_by_relative_path():
    """aider's own prompt says the USER adds files and may run the suggested commands; here the
    driver does both, and a model that was not told behaved as aider's prompt says (guessed a
    skill's token, declared itself unable to run a tool, invented a result). The block names each
    SKILL.md as a `cat` the model can run on any turn; aider's own file-mention route adds only
    files git already tracks, which a first turn's skill files are not."""
    d = tempfile.mkdtemp()
    sk = pathlib.Path(d, ".harness", "skills", "plugin-probe"); sk.mkdir(parents=True)
    sk.joinpath("SKILL.md").write_text("---\nname: plugin-probe\n---\n")
    doc = pathlib.Path(d, "AGENTS.md"); doc.write_text("# harness contract\n")
    _build_aider("openai-api", Auth(api_key="sk-t", base_url="https://up.example/v1"),
                 "gpt-5.4", "do it", d, {}, mcp_servers=[])
    text = doc.read_text()
    assert "## How this workspace works for you" in text
    assert "- `cat .harness/skills/plugin-probe/SKILL.md`" in text
    assert "```bash" in text and "Report only output you were actually given" in text
    # written fresh each turn on top of the doc the turn wrote: no growth across turns
    doc.write_text("# harness contract\n")
    _build_aider("openai-api", Auth(api_key="sk-t", base_url="https://up.example/v1"),
                 "gpt-5.4", "do it", d, {}, mcp_servers=[])
    assert doc.read_text().count("## How this workspace works for you") == 1


def test_edit_blocks_are_stripped_from_the_answer_and_the_edits_render_as_cards():
    """The SEARCH/REPLACE markup is aider's wire format for an edit; the console showed it raw as
    the reply ("hello.py ```python <<<<<<< SEARCH ======= print(...) >>>>>>> REPLACE ```",
    hr-test 2026-09-18). The prose is the answer; each edited file is a card, as on every base."""
    text = ("I will create the file.\n\nhello.py\n```python\n<<<<<<< SEARCH\n=======\n"
            "print(\"aider\")\n>>>>>>> REPLACE\n```\n\nDONE-FILE")
    assert aider_driver.strip_edit_blocks(text) == "I will create the file.\n\n\nDONE-FILE"
    shell = "Run this:\n```bash\ncat SKILL.md\n```"
    assert aider_driver.strip_edit_blocks(shell) == "Run this:"  # the command renders as a card
    # a fence the model closed and kept writing on ("```An improved…") closes the block for aider
    # (editblock_coder.py:478) and the sentence is prose
    assert aider_driver.strip_edit_blocks("```bash\nofficecli view a.pptx\n```An improved style.\nDone.") == "An improved style.\nDone."
    state: dict = {"_aider_init": True}
    evs = _aider_to_claude({"m": "edits", "p": {"files": ["hello.py", "b.txt"]}}, state)
    calls = [c for e in evs for c in e["message"]["content"] if c["type"] == "tool_use"]
    results = [c for e in evs for c in e["message"]["content"] if c["type"] == "tool_result"]
    assert [c["name"] for c in calls] == ["Edit", "Edit"]
    assert [c["input"]["file_path"] for c in calls] == ["hello.py", "b.txt"]
    assert [r["tool_use_id"] for r in results] == [c["id"] for c in calls]
    # the result event's text is what the gateway stores as the answer: stripped there too, or
    # the markup comes back through the other door (measured: the text event was clean and the
    # stored answer still carried the block)
    src = pathlib.Path(__file__).resolve().parents[1].joinpath("aider_driver.py").read_text()
    assert '"final": strip_edit_blocks(coder.partial_response_content or "")' in src


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


# ── the MCP bridge itself ────────────────────────────────────────────────────────
# These run without the `mcp` SDK installed: the SDK is imported inside _run, and everything below
# is argument handling and the shapes the bridge puts in front of the agent. The live half — list,
# call, a failing call and an unknown server, against public servers — was measured separately and
# is recorded in docs/support-matrix-notes.md.
import aider_mcp_bridge  # noqa: E402


def test_an_unknown_server_names_the_ones_that_exist():
    """The agent reads stderr. "no such server" without the list is a dead end for it."""
    cfg = pathlib.Path(tempfile.mkdtemp(), "m.json")
    cfg.write_text(json.dumps({"mcpServers": {"deepwiki": {"url": "https://x/mcp"}}}))
    servers = aider_mcp_bridge._load(str(cfg))
    try:
        aider_mcp_bridge._target(servers, "nope")
    except SystemExit as e:
        assert e.code == 2
    else:
        raise AssertionError("an unknown server must not be silently accepted")


def test_a_url_server_resolves_to_its_url():
    """No transport and no headers: the plain string, which the SDK dials as streamable HTTP."""
    servers = {"deepwiki": {"url": "https://mcp.deepwiki.com/mcp"}}
    assert aider_mcp_bridge._target(servers, "deepwiki") == "https://mcp.deepwiki.com/mcp"


def _stub_mcp_sdk(monkeypatch):
    """The bridge runs under the aider venv's SDK (mcp 2.x with httpx2), not the runner's (1.x, no
    httpx2): the transports it builds do not import here. Stub the three modules by name so the
    test checks the bridge's choice of transport, which is what the declaration bug was about."""
    sse = types.ModuleType("mcp.client.sse")
    sse.sse_client = lambda url, headers=None: ("sse", url, headers)
    sh = types.ModuleType("mcp.client.streamable_http")
    sh.streamable_http_client = lambda url, http_client=None: ("http", url, http_client)
    hx = types.ModuleType("httpx2")
    hx.AsyncClient = lambda headers=None: ("client", headers)
    client = types.ModuleType("mcp.client")
    pkg = types.ModuleType("mcp")
    pkg.client = client
    for name, mod in (("mcp", pkg), ("mcp.client", client), ("mcp.client.sse", sse),
                      ("mcp.client.streamable_http", sh), ("httpx2", hx)):
        monkeypatch.setitem(sys.modules, name, mod)


def test_the_declared_transport_decides_and_not_the_urls_spelling(monkeypatch):
    _stub_mcp_sdk(monkeypatch)
    """MEASURED DEFECT this pins: `Client.__init__` sends a plain URL string to
    `streamable_http_client` unconditionally (mcp 2.2.0, client.py:393-394) — there is no inference
    and no SSE path — so a harness that declared `transport: sse` had its server dialled with the
    wrong protocol. Same rule the maintainer set for kimi: the declaration decides, never the url.
    A string result here would be that defect returning."""
    sse = aider_mcp_bridge._target(
        {"events": {"url": "https://example.test/events", "transport": "sse"}}, "events")
    assert sse == ("sse", "https://example.test/events", None)


def test_declared_headers_reach_the_server_rather_than_the_config_file(monkeypatch):
    """They were written into the config and never read: the streamable path takes headers on an
    httpx client, not on the call, so a plain URL string dropped every one of them."""
    _stub_mcp_sdk(monkeypatch)
    with_hdrs = aider_mcp_bridge._target(
        {"api": {"url": "https://example.test/mcp", "headers": {"X-K": "v"}}}, "api")
    assert with_hdrs == ("http", "https://example.test/mcp", ("client", {"X-K": "v"}))


def test_structured_content_wins_over_prose():
    """A tool that returns data should not be flattened into text for the agent to re-parse.

    NOTE the field name: the 2.2.0 SDK is snake_case (structured_content / is_error /
    input_schema), not the camelCase of older releases. The camelCase guess raised inside a
    TaskGroup and surfaced as an unreadable "unhandled errors in a TaskGroup" — measured."""
    class R:
        structured_content = {"answer": 42}
        content = []
    assert json.loads(aider_mcp_bridge._render(R())) == {"answer": 42}


def test_text_blocks_are_joined_when_there_is_no_structured_content():
    class Block:
        def __init__(self, t): self.text = t
    class R:
        structured_content = None
        content = [Block("one"), Block("two")]
    assert aider_mcp_bridge._render(R()) == "one\ntwo"


def test_bad_params_json_is_rejected_before_any_connection():
    rc = aider_mcp_bridge.main(["--config", "/nonexistent", "call", "s", "t",
                               "--params", "{not json"])
    assert rc == 2


# ── conversation continuity: the bug the support matrix found ────────────────────
def test_the_turn_announces_a_session_id_even_though_aider_has_none():
    """MEASURED FAILURE this pins: aider has no conversation id of any kind, so the gateway never
    recorded one, never treated a later turn as a follow-up, and every turn was a fresh thread. The
    support matrix's recycle scenario failed on every aider row while first/follow-up/switch
    passed — those three only check that a turn answers, never that it remembers."""
    state: dict = {}
    out = _aider_to_claude({"m": "text", "p": {"text": "hi"}}, state)
    assert out[0]["type"] == "system" and out[0]["subtype"] == "init"
    assert out[0]["session_id"] == _AIDER_SESSION_NAME
    # once per turn, not once per event
    again = _aider_to_claude({"m": "text", "p": {"text": "more"}}, state)
    assert not [e for e in again if e.get("subtype") == "init"]


def test_the_chat_history_is_restored_on_every_turn():
    """aider's only continuation mechanism. It travels in the checkpoint under .harness/, which is
    what lets a follow-up after a sandbox recycle still know what was said; on a first turn the file
    does not exist and aider starts fresh."""
    import json as _json
    _, _, _, job = _build()
    # the driver owns the argv; assert the flag it builds
    src = pathlib.Path(__file__).resolve().parents[1].joinpath("aider_driver.py").read_text()
    assert '"--restore-chat-history"' in src
    assert '"--chat-history-file", str(hist / "chat.history.md")' in src


# ── the Plugins sub-protocol (UHP 2026-09-12) ────────────────────────────────────
def test_a_plugins_stdio_server_reaches_the_bridge_as_command_and_args():
    """_plugin_launchers bakes env, cwd and the ${PLUGIN_ROOT}/${PLUGIN_DATA} placeholders into one
    launcher script, so every writer sees the same {name, command, args}. aider has no MCP client of
    its own, so "the writer" here is the bridge's server table plus the shim the turn builds."""
    d = tempfile.mkdtemp()
    pathlib.Path(d, "AGENTS.md").write_text("# contract\n")
    env: dict = {}
    _build_aider("openai-api", Auth(api_key="sk-t", base_url="https://up.example/v1"),
                 "gpt-5.4", "do it", d, env, mcp_servers=[
                     {"name": "probe", "command": "/ws/.harness/plugin-data/demo/.launch-probe.sh",
                      "args": ["--x", "1"]},
                     {"name": "vault", "url": "https://mcp.example.invalid/mcp"}])
    cfg = json.loads(pathlib.Path(d, ".harness", "aider-mcp.json").read_text())["mcpServers"]
    assert cfg["probe"] == {"command": "/ws/.harness/plugin-data/demo/.launch-probe.sh",
                            "args": ["--x", "1"]}
    assert cfg["vault"]["url"].startswith("https://")
    # both kinds are advertised to the model, and a stdio one is named as such
    doc = pathlib.Path(d, "AGENTS.md").read_text()
    assert "`probe` — stdio" in doc and "`vault` — streamable HTTP" in doc


def test_the_bridge_resolves_a_stdio_entry_to_stdio_server_parameters():
    """The half a config file cannot show. Verified live against a real stdio MCP server too: the
    bridge listed its tool and called it, exit 0.

    Skipped where the SDK is absent: `mcp` lives in AIDER's venv, not the runner's — deliberately,
    because installing it beside the runner bumps starlette past what FastAPI 0.115.6 accepts."""
    import pytest
    pytest.importorskip("mcp", reason="the MCP SDK lives in aider's own venv")
    servers = {"probe": {"command": "/bin/echo", "args": ["a", "b"], "env": {"K": "V"}}}
    target = aider_mcp_bridge._target(servers, "probe")
    assert target.command == "/bin/echo"
    assert target.args == ["a", "b"]
    assert target.env == {"K": "V"}


# The companion test that asserted membership of _STDIO_MCP_BACKENDS is gone with the set itself:
# upstream (#185) stopped declaring any transport missing, because the runner now hands every client
# one launcher shape and bridges SSE and streamable HTTP over stdio for the ones that cannot speak
# them. Nothing about aider changed — the bridge already resolved a stdio entry — so what is left to
# pin is the two tests above: the servers the turn writes, and the shape the bridge resolves them to.


def test_the_driver_bounds_every_api_call():
    """MEASURED FAILURE this pins: aider's --timeout defaults to None, so a provider that accepts
    the connection and never finishes the stream leaves the call waiting forever. aider's own retry
    loop cannot save it — that only fires on an exception, and is itself bounded at ~63s. In the
    vercel column single scenarios ran 3,621s, 6,040s, 16,071s and 27,360s against 7-30s healthy,
    and only the runner's 6-hour cap ended them."""
    src = pathlib.Path(__file__).resolve().parents[1].joinpath("aider_driver.py").read_text()
    assert '"--timeout", os.environ.get("HR_AIDER_TIMEOUT", "300")' in src


def test_the_operators_step_budget_reaches_the_driver():
    """aider has no CLI flag for it — its loop is Coder.max_reflections, a class attribute — so the
    budget travels in the job and the driver sets it on the object. Pinned here because the dispatch
    passes it and a builder that did not accept it would TypeError on the first aider turn, which no
    unit test exercises."""
    _, _, _, job = _build(max_turns=7)
    assert job["max_turns"] == 7
    src = pathlib.Path(__file__).resolve().parents[1].joinpath("aider_driver.py").read_text()
    assert "coder.max_reflections = max(1, int(budget))" in src
    # The dispatch is the link that was missing: the builder accepted the budget and turn() never
    # handed it over, so every aider turn ran on aider's own default no matter what the harness
    # said. Read off the source, since turn() needs a live workspace and a provider to run.
    server_src = pathlib.Path(__file__).resolve().parents[1].joinpath("server.py").read_text()
    dispatch = server_src[server_src.index('elif backend == "aider":'):]
    dispatch = dispatch[:dispatch.index("elif backend ==", 10)]
    assert "max_turns=req.max_turns" in dispatch


def test_only_the_agent_doc_rides_read_and_skills_are_reached_on_demand():
    """The PR passed every file of every installed skill bundle through --read on every turn:
    27 files and 264 KB for the three built-in bundles on hr-test, 45,030 input tokens for a
    one-line answer. The agent doc's skills block names the folders; the model reads a skill when
    a task calls for it, through the shell command the driver feeds back or a file mention aider
    adds itself."""
    server_src = pathlib.Path(__file__).resolve().parents[1].joinpath("server.py").read_text()
    dispatch = server_src[server_src.index('elif backend == "aider":'):]
    dispatch = dispatch[:dispatch.index("elif backend ==", 10)]
    assert "rglob" not in dispatch and "skills_read=aider_read" in dispatch


def _stub_aider_models(info):
    """`from aider.models import model_info_manager` without aider installed."""
    pkg = types.ModuleType("aider")
    mod = types.ModuleType("aider.models")
    mod.model_info_manager = types.SimpleNamespace(get_model_info=lambda name: info(name))
    pkg.models = mod
    return {"aider": pkg, "aider.models": mod}


def test_the_prefixed_id_is_given_back_the_record_the_prefix_hides():
    """MEASURED FAILURE this pins: litellm falls back from `openai/<id>` to the bare id ONLY when
    that id's own litellm_provider is openai (models.py:228-231). `openai/gpt-5.6-sol` keeps its
    66-key record; every gemini, claude, grok and qwen id resolved to an EMPTY dict, and aider then
    ran and REPORTED limits of 0 -- `Input tokens: ~45,356 of 0 -- possibly exhausted context
    window!` about a 1,048,576-token model (google|aider|gemini-3-flash-preview, 2026-09-16).
    The BARE id is what gets looked up, so aider's alias table is still never consulted."""
    asked = []
    stub = _stub_aider_models(lambda n: (asked.append(n), {"max_input_tokens": 1048576})[1])
    with tempfile.TemporaryDirectory() as d:
        pathlib.Path(d, ".harness", "aider").mkdir(parents=True)
        saved = {k: sys.modules.get(k) for k in stub}
        sys.modules.update(stub)
        try:
            out = aider_driver._write_model_metadata(d, "openai/gemini-3-flash-preview")
        finally:
            for k, v in saved.items():
                sys.modules.pop(k, None) if v is None else sys.modules.__setitem__(k, v)
        assert asked == ["gemini-3-flash-preview"]
        written = json.loads(pathlib.Path(out).read_text())
        # registered under the PREFIXED name: that is the key aider looks the running model up by
        assert written == {"openai/gemini-3-flash-preview": {"max_input_tokens": 1048576}}


def test_an_id_litellm_does_not_know_writes_nothing():
    """claude-opus-4.8, grok-4.6, qwen3.8-max and kimi-k3 are absent from litellm's database even
    bare, so there is nothing to hand over and the turn must run exactly as it does today."""
    stub = _stub_aider_models(lambda n: {})
    with tempfile.TemporaryDirectory() as d:
        pathlib.Path(d, ".harness", "aider").mkdir(parents=True)
        saved = {k: sys.modules.get(k) for k in stub}
        sys.modules.update(stub)
        try:
            assert aider_driver._write_model_metadata(d, "openai/grok-4.6") is None
        finally:
            for k, v in saved.items():
                sys.modules.pop(k, None) if v is None else sys.modules.__setitem__(k, v)
        assert not pathlib.Path(d, ".harness", "aider", "model-metadata.json").exists()


def test_the_record_is_handed_to_aider_on_the_command_line():
    """A file written and never passed is the defect the MCP block already taught this backend."""
    src = pathlib.Path(__file__).resolve().parents[1].joinpath("aider_driver.py").read_text()
    assert 'meta = _write_model_metadata(cwd, job["model"])' in src
    assert 'argv += ["--model-metadata-file", meta]' in src


def test_the_conversation_is_kept_verbatim_rather_than_summarised_at_aiders_cap():
    """aider keeps at most 8k tokens of history (1k for an id litellm does not know) and
    summarises the rest with a model call; after four short turns the fifth could not say what
    the first asked (console matrix, hr-test 2026-09-18). Half the window when known, else a
    budget that fits the catalog's smallest windows; and the flag reaches the command line."""
    d = tempfile.mkdtemp()
    meta = pathlib.Path(d, "meta.json")
    meta.write_text(json.dumps({"openai/gpt-5.4": {"max_input_tokens": 400000}}))
    assert aider_driver._history_budget(str(meta)) == 200000
    meta.write_text(json.dumps({"openai/x": {"max_input_tokens": 8000}}))
    assert aider_driver._history_budget(str(meta)) == 8192
    assert aider_driver._history_budget(None) == 96000
    meta.write_text("not json")
    assert aider_driver._history_budget(str(meta)) == 96000
    src = pathlib.Path(__file__).resolve().parents[1].joinpath("aider_driver.py").read_text()
    assert 'argv += ["--max-chat-history-tokens", str(_history_budget(meta))]' in src


def test_the_agent_doc_is_the_system_message_and_the_conversation_holds_only_the_users_turns():
    """--read sent the doc as a user message ("Here are some READ ONLY files, provided for your
    reference") ahead of the conversation, and aider's few-shot examples were user/assistant turns
    ahead of that: asked what the first message of the task said, gpt-5.4 answered "reference"
    and, before, "Change" (hr-test, 2026-09-18). The doc rides aider's own system_prompt_prefix
    hook and the examples fold into the system message; nothing of aider's precedes the user."""
    _, _, _, job = _build(skills_read=["/w/AGENTS.md"])
    assert job["system_files"] == ["/w/AGENTS.md"] and "read_files" not in job
    src = pathlib.Path(__file__).resolve().parents[1].joinpath("aider_driver.py").read_text()
    assert '"--read"' not in src
    assert "coder.main_model.system_prompt_prefix = (" in src
    assert "coder.main_model.examples_as_sys_msg = True" in src


def test_no_temperature_is_sent_since_a_provider_that_retired_the_field_refuses_the_turn():
    """claude-fable-5-1 on TokenRouter: "`temperature` is deprecated for this model", turn dead
    after 171 s of retries (console matrix, hr-test 2026-09-18). aider sends 0 for every id its
    settings do not know; no other base sets one; aider's own switch leaves it out."""
    src = pathlib.Path(__file__).resolve().parents[1].joinpath("aider_driver.py").read_text()
    assert "coder.main_model.use_temperature = False" in src


def test_the_harness_own_files_stay_out_of_the_repo_map():
    """.harness/ holds the skill bundles, aider's state and the MCP shim; summarised into the
    repo map they rode every request as the user's project. The driver hands aider an ignore
    file for them, so the map describes the task's files alone."""
    src = pathlib.Path(__file__).resolve().parents[1].joinpath("aider_driver.py").read_text()
    assert 'ignore.write_text(".harness/\\nAGENTS.md\\n.gitignore\\n")' in src
    assert '"--aiderignore", str(ignore),' in src


def test_a_binary_file_the_model_names_is_refused_at_aiders_add_prompt():
    """Asked to restyle hello.pptx (hr-test, 2026-09-19), the model named it, aider added it, the
    UTF-8 read failed ("Use --encoding…"), the file was dropped and added again on the next
    mention: an error and a reflection each time, twelve commands, fifteen minutes. A binary
    file is refused at aider's own "Add file to the chat?" prompt, which puts it on
    ignore_mentions; text files still go in."""
    d = tempfile.mkdtemp()
    pathlib.Path(d, "deck.pptx").write_bytes(b"PK\x03\x04\xf7\x00binary")
    pathlib.Path(d, "notes.md").write_text("# notes\n")
    assert aider_driver.is_text_file(os.path.join(d, "deck.pptx")) is False
    assert aider_driver.is_text_file(os.path.join(d, "notes.md")) is True
    asked = []
    io = types.SimpleNamespace(confirm_ask=lambda q, default="y", subject=None, explicit_yes_required=False, group=None, allow_never=False: asked.append(subject) or True,
                               assistant_output=lambda m, p=None: None, tool_error=lambda m="", strip=True: None,
                               tool_warning=lambda m="", strip=True: None)
    coder = types.SimpleNamespace(io=io, root=d, partial_response_content="", reasoning_tag_name="think",
                                  reflected_message=None)
    gate = aider_driver._Gate([])
    aider_driver._install(coder, gate)
    assert io.confirm_ask("Add file to the chat?", subject="deck.pptx") is False
    assert io.confirm_ask("Add file to the chat?", subject="notes.md") is True
    assert asked == ["notes.md"]                       # the binary never reached aider's prompt
    # nobody is at aider's prompt to say what to do instead, so the turn is told and goes on
    assert "`deck.pptx` is a binary file" in coder.reflected_message and "```bash" in coder.reflected_message


def test_the_turn_fails_only_when_an_error_was_the_last_thing_that_happened():
    """The restyled .pptx and the edited hello.md were reported FAILED for a decode error twelve
    commands earlier. An error followed by more of the model's work is a recovered error; an
    error with nothing after it (a provider refusal) is the failure."""
    io = types.SimpleNamespace(confirm_ask=lambda *a, **k: True, assistant_output=lambda m, p=None: None,
                               tool_error=lambda m="", strip=True: None, tool_warning=lambda m="", strip=True: None)
    coder = types.SimpleNamespace(io=io, root="/tmp", partial_response_content="", reasoning_tag_name="think",
                                  reflected_message=None)
    gate = aider_driver._Gate([])
    aider_driver._install(coder, gate)
    assert gate.error_after_output is False
    io.tool_error("x: 'utf-8' codec can't decode"); assert gate.error_after_output is True
    io.assistant_output("I restyled the deck."); assert gate.error_after_output is False
    io.tool_error("litellm.AuthenticationError"); assert gate.error_after_output is True
    src = pathlib.Path(__file__).resolve().parents[1].joinpath("aider_driver.py").read_text()
    assert "failed = coder.usage_report is None or gate.error_after_output" in src


def test_each_text_pass_ends_with_a_paragraph_break():
    """The console joins consecutive text blocks as they come; a closing fence ran straight into
    the next pass's first sentence and the rest of the turn rendered inside a code block."""
    state: dict = {"_aider_init": True}
    ev = _aider_to_claude({"m": "text", "p": {"text": "First pass.\n"}}, state)[0]
    assert ev["message"]["content"][0]["text"] == "First pass.\n\n"


def test_the_models_reasoning_is_not_rendered_as_its_answer():
    """MEASURED FAILURE this pins (vercel|aider|grok-4.20, 2026-09-18): the transcript showed the
    model's chain of thought -- "(wait, no, that's not how it works)... So my response should be:"
    -- because io.assistant_output receives aider's DISPLAY string, which base_coder.py:1882-1890
    builds by prepending the reasoning and rewriting its tags into `► **THINKING**`/`► **ANSWER**`
    furniture. The answer is partial_response_content, which is never decorated."""
    class _IO:
        def __init__(self):
            self.seen = []
        def assistant_output(self, message, pretty=None): self.seen.append(message)
        def confirm_ask(self, *a, **k): return True
        def tool_error(self, *a, **k): pass
        def tool_warning(self, *a, **k): pass
    class _Coder:
        def __init__(self):
            self.io = _IO()
            self.reasoning_tag_name = "thinking-content-7bbeb8e1441453ad999a0bbba8a46d4b"
            self.partial_response_content = "M1-grok-4.20"
            self.shell_commands = []
    coder = _Coder()
    emitted = []
    real_emit = aider_driver._emit
    aider_driver._emit = lambda m, p: emitted.append((m, p))
    # the driver asks aider to strip, so aider is where the tag semantics stay; the suite runs
    # without aider installed, so its helper stands in here
    import re as _re
    pkg = types.ModuleType("aider"); mod = types.ModuleType("aider.reasoning_tags")
    mod.remove_reasoning_content = lambda res, tag: (
        _re.sub(f"<{tag}>.*?</{tag}>", "", res, flags=_re.DOTALL).strip() if tag else res)
    pkg.reasoning_tags = mod
    saved = {k: sys.modules.get(k) for k in ("aider", "aider.reasoning_tags")}
    sys.modules.update({"aider": pkg, "aider.reasoning_tags": mod})
    try:
        aider_driver._install(coder, aider_driver._Gate([]))
        # what aider would hand it for a reasoning model
        coder.io.assistant_output(
            "--------------\n► **THINKING**\n\nwait, no, that is not how it works\n\n"
            "------------\n► **ANSWER**\n\nM1-grok-4.20")
    finally:
        aider_driver._emit = real_emit
        for k, v in saved.items():
            sys.modules.pop(k, None) if v is None else sys.modules.__setitem__(k, v)
    texts = [p["text"] for m, p in emitted if m == "text"]
    assert texts == ["M1-grok-4.20"], texts
    assert "THINKING" not in texts[0]

