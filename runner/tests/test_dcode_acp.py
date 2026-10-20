"""deepagents-code over ACP: the argv, the record, and the two things the protocol does not carry.

WHY THIS FILE EXISTS. dcode was built once on its headless flag and left unoffered, because
`dcode -n "<task>"` always starts a fresh thread — its own source says so, and five turns passing
`-r <thread_id>` for a thread with 22 checkpoints produced five new threads and five "this thread
has no earlier message" answers. `dcode --acp` is the same agent behind the Agent Client Protocol,
whose server is built with `load_sessions=True`, and MEASURED on 0.1.84 (2026-10-19) a session
created by one process was continued by another: the second answered a recall question whose answer
existed ONLY in the conversation (the first turn was told to write nothing, and its updates carry no
tool call). The five-scenario run through the runner's own relay is in
docs/support-matrix-notes.md.

The fixture is real traffic: runner/tests/fixtures/batch4/dcode-six-tools.ndjson is every
`session/update` of one recorded turn that was asked to list, read, write, edit, search and run a
command. Two of its properties are the reason the driver is not a thinner translation:
  * ACP's tool_call has NO field for the tool's name — a title for a human and a kind from a fixed
    vocabulary — so the driver puts the id back (the server renames exactly four tools and passes
    `title = tool_name` for the rest).
  * One call never gets a completion: an edit_file with a full diff goes out through the server's
    `start_edit_tool_call` branch and nothing follows it. The record closes it by saying so.
"""
import json
import os
import pathlib
import sqlite3
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import dcode_driver as D  # noqa: E402
from server import (ALL_DCODE_TOOLS, BACKENDS, DCODE_PROVIDERS, Auth, _build_dcode,  # noqa: E402
                    _claude_passthrough, _dcode_session_present, _dcode_state_db, _dcode_threads)

FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "batch4" / "dcode-six-tools.ndjson"
# Every _build_dcode writes this CLI's config.toml under the cwd it is given (and an MCP config,
# when servers are declared), so the default cwd here is a scratch directory: a test that builds an
# argv must not leave a .harness/ tree in the repository's own fixtures.
_WS = tempfile.mkdtemp(prefix="dcode-argv-tests-")


def _job(**kw):
    ws = kw.pop("cwd", None) or _WS
    cmd = _build_dcode(kw.pop("provider", "openai-api"),
                       Auth(base_url="https://up.example/v1", api_key="k"),
                       kw.pop("model", "gpt-5.4"), kw.pop("prompt", "hi"), ws, kw.pop("env", {}),
                       **kw)
    assert cmd[1].endswith("dcode_driver.py"), cmd
    return json.loads(cmd[2])


# ── the argv ──────────────────────────────────────────────────────────────────────────────────
def test_the_turn_runs_the_acp_server_and_not_the_headless_flag():
    job = _job()
    assert "--acp" in job["argv"]
    # -n is the mode that cannot resume: it must not be how a turn runs here
    assert "-n" not in job["argv"] and "-q" not in job["argv"]
    # the task rides session/prompt, not the command line
    assert job["prompt"] == "hi"
    assert job["argv"][-1] != "hi"


def test_the_model_is_both_a_flag_and_a_spec_the_driver_can_ask_for():
    job = _job(model="claude-haiku-5.5")
    i = job["argv"].index("-M")
    assert job["argv"][i + 1] == "openai:claude-haiku-5.5"
    # the same string goes to the driver, which sets it ON THE SESSION: a loaded session brings
    # back the model it was created with, so a switch turn has to say so
    assert job["model_spec"] == "openai:claude-haiku-5.5"
    assert job["model"] == "claude-haiku-5.5"


def test_the_resume_id_is_asked_for_through_the_protocol_not_the_argv():
    job = _job(resume_session_id="deadbeef")
    assert job["resume"] == "deadbeef"
    assert "-r" not in job["argv"] and "deadbeef" not in job["argv"]


def test_mcp_is_declared_or_switched_off_but_never_discovered():
    assert "--no-mcp" in _job()["argv"]
    job = _job(mcp_servers=[{"name": "x", "url": "https://mcp.example/sse", "transport": "sse"}])
    assert "--no-mcp" not in job["argv"]
    assert "--mcp-config" in job["argv"] and "--trust-project-mcp" in job["argv"]


def test_nothing_withheld_passes_no_allow_list_at_all():
    assert "--allow-fs-tools" not in _job()["argv"]


def test_a_withheld_tool_becomes_an_allow_list_that_still_holds_read_file():
    job = _job(tools_disabled=["execute", "delete"])
    kept = job["argv"][job["argv"].index("--allow-fs-tools") + 1].split(",")
    assert "execute" not in kept and "delete" not in kept
    # the flag's own parser rejects a list without read_file, so it is never withheld
    assert "read_file" in kept
    assert set(kept) == {"ls", "read_file", "write_file", "edit_file", "glob", "grep"}


def test_withholding_read_file_is_not_possible_and_does_not_break_the_flag():
    kept = _job(tools_disabled=["read_file"])["argv"]
    i = kept.index("--allow-fs-tools")
    assert "read_file" in kept[i + 1].split(",")


def test_every_offered_tool_is_one_the_allow_list_can_withhold():
    for tool in ALL_DCODE_TOOLS:
        job = _job(tools_disabled=[tool])
        kept = job["argv"][job["argv"].index("--allow-fs-tools") + 1].split(",")
        assert tool not in kept, tool


def test_the_step_budget_is_not_forwarded_because_this_surface_has_no_knob_for_it():
    # `--max-turns` "requires -n or piped stdin" and is rejected in ACP mode; --recursion-limit
    # counts graph steps, which is a different unit. The turn's wall clock is what bounds it.
    job = _job(max_turns=7)
    assert "--max-turns" not in job["argv"] and "--recursion-limit" not in job["argv"]
    assert job["timeout"] > 0


def test_the_relay_is_what_the_cli_is_pointed_at_and_not_the_connection():
    env = {}
    _build_dcode("openai-api", Auth(base_url="https://up.example/v1", api_key="secret-key"),
                 "gpt-5.4", "hi", _WS, env)
    assert env["OPENAI_API_KEY"] != "secret-key"
    assert "up.example" not in env["OPENAI_BASE_URL"]
    # and nothing of the CLI's own that would phone home or edit the user's files
    assert env["DEEPAGENTS_CODE_MEMORY_AUTO_SAVE"] == "0"
    assert env["DEEPAGENTS_CODE_OFFLINE"] == "1"
    assert env["LANGSMITH_TRACING"] == "false"


def test_an_anthropic_connection_is_not_a_provider_this_base_accepts():
    # it posts to /v1/responses through langchain-openai; a Messages endpoint has no such path
    assert "anthropic" not in DCODE_PROVIDERS
    assert BACKENDS["dcode"]["providers"] == sorted(DCODE_PROVIDERS)


# ── the store, which is where a session id exists ─────────────────────────────────────────────
def test_a_session_is_present_when_the_checkpointer_has_its_thread(tmp_path):
    db = _dcode_state_db(str(tmp_path))
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE checkpoints (thread_id TEXT, checkpoint_ns TEXT, checkpoint_id TEXT)")
    con.execute("INSERT INTO checkpoints VALUES ('abc', '', '1')")
    con.execute("INSERT INTO checkpoints VALUES ('abc', '', '2')")
    con.commit()
    con.close()
    assert _dcode_threads(str(tmp_path)) == ["abc"]
    assert _dcode_session_present(str(tmp_path), [], "abc") is True
    assert _dcode_session_present(str(tmp_path), [], "nope") is False
    assert _dcode_session_present(str(tmp_path), [], "") is False


def test_a_workspace_with_no_store_yet_has_no_sessions(tmp_path):
    assert _dcode_threads(str(tmp_path)) == []
    assert _dcode_session_present(str(tmp_path), [], "abc") is False


def test_the_tui_table_is_not_what_is_asked(tmp_path):
    # ACP turns never write dcode_thread_workspaces; a reader that wanted it would find nothing
    db = _dcode_state_db(str(tmp_path))
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE checkpoints (thread_id TEXT)")
    con.execute("INSERT INTO checkpoints VALUES ('t1')")
    con.commit(); con.close()
    assert _dcode_threads(str(tmp_path)) == ["t1"]


# ── the record, over real recorded traffic ────────────────────────────────────────────────────
def _fixture_updates():
    return [json.loads(l) for l in FIX.read_text().splitlines() if l.strip()]


def test_the_six_tools_of_the_recorded_turn_come_back_under_their_own_names():
    evs, answer = D.translate(_fixture_updates())
    names = [c["name"] for e in evs if e.get("type") == "assistant"
             for c in e["message"]["content"] if c.get("type") == "tool_use"]
    assert names == ["ls", "read_file", "write_file", "edit_file", "grep", "execute"]
    assert answer


def test_every_call_in_the_record_is_closed_by_a_result():
    evs, _ = D.translate(_fixture_updates())
    calls = [c["id"] for e in evs if e.get("type") == "assistant"
             for c in e["message"]["content"] if c.get("type") == "tool_use"]
    results = [c["tool_use_id"] for e in evs if e.get("type") == "user"
               for c in e["message"]["content"] if c.get("type") == "tool_result"]
    assert sorted(calls) == sorted(results)
    # the one the protocol never completed says exactly that, instead of claiming an outcome
    unreported = [c["content"] for e in evs if e.get("type") == "user"
                  for c in e["message"]["content"]
                  if c.get("type") == "tool_result" and "no completion" in str(c.get("content"))]
    assert len(unreported) == 1 and "edit_file" in unreported[0]


def test_a_tool_call_carries_the_arguments_the_agent_sent():
    evs, _ = D.translate(_fixture_updates())
    write = next(c for e in evs if e.get("type") == "assistant"
                 for c in e["message"]["content"]
                 if c.get("type") == "tool_use" and c["name"] == "write_file")
    assert "file_path" in write["input"]


def test_the_tool_name_mapping_covers_every_shape_the_server_sends():
    assert D._tool_name("ls", "search") == "ls"
    assert D._tool_name("grep", "search") == "grep"
    assert D._tool_name("Read `/ws/a.txt`", "read") == "read_file"
    assert D._tool_name("Write `/ws/a.txt`", "edit") == "write_file"
    assert D._tool_name("Edit `/ws/a.txt`", "edit") == "edit_file"
    assert D._tool_name("echo hi", "execute") == "execute"
    # an MCP tool's title IS its name (the server renames only its own four)
    assert D._tool_name("deepwiki__read_wiki_structure", "other") == "deepwiki__read_wiki_structure"
    # and a shape nobody has seen still produces something rather than crashing
    assert D._tool_name("", "") == "tool"


def test_text_and_tool_calls_keep_the_order_the_reader_saw():
    evs, _ = D.translate([
        {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "first "}},
        {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "part"}},
        {"sessionUpdate": "tool_call", "toolCallId": "c1", "title": "ls", "kind": "search",
         "rawInput": {"path": "."}},
        {"sessionUpdate": "tool_call_update", "toolCallId": "c1", "status": "completed",
         "content": [{"type": "content", "content": {"type": "text", "text": "a.txt"}}]},
        {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "then more"}},
    ])
    kinds = [(e["type"], e["message"]["content"][0]["type"]) for e in evs]
    assert kinds == [("assistant", "text"), ("assistant", "tool_use"),
                     ("user", "tool_result"), ("assistant", "text")]


def test_a_failed_call_is_recorded_as_an_error_not_as_a_result():
    evs, _ = D.translate([
        {"sessionUpdate": "tool_call", "toolCallId": "c1", "title": "echo no", "kind": "execute",
         "rawInput": {"command": "echo no"}},
        {"sessionUpdate": "tool_call_update", "toolCallId": "c1", "status": "failed",
         "content": [{"type": "content", "content": {"type": "text", "text": "denied"}}]},
    ])
    res = [c for e in evs if e.get("type") == "user" for c in e["message"]["content"]]
    assert res[0]["is_error"] is True and "denied" in res[0]["content"]


def test_progress_updates_are_not_the_turns_answer():
    # thoughts and plans are progress; a record that read them as the answer would hand the user
    # the agent's thinking as its reply
    evs, answer = D.translate([
        {"sessionUpdate": "agent_thought_chunk", "content": {"type": "text", "text": "hmm"}},
        {"sessionUpdate": "plan", "entries": [{"content": "do it", "status": "pending"}]},
        {"sessionUpdate": "user_message_chunk", "content": {"type": "text", "text": "the prompt"}},
        {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "the answer"}},
    ])
    assert answer == "the answer"
    assert len(evs) == 1


def test_an_empty_turn_produces_no_events_and_no_answer():
    assert D.translate([]) == ([], "")


# ── what the runner does with the driver's own stream ─────────────────────────────────────────
def test_the_normaliser_for_this_backend_is_the_passthrough():
    assert BACKENDS["dcode"]["normalize"] is _claude_passthrough


def test_the_drivers_events_survive_the_passthrough():
    state = {"model": "gpt-5.4", "final": "", "cwd": "/ws"}
    out = []
    for ev in [{"type": "system", "subtype": "init", "session_id": "s1", "model": "gpt-5.4"},
               {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}},
               {"type": "result", "subtype": "success", "is_error": False, "result": "hi",
                "usage": {}}]:
        out += _claude_passthrough(ev, state)
    assert [e.get("type") for e in out] == ["system", "assistant", "result"]
    assert out[0]["session_id"] == "s1"


# ── the driver's own conversation, against a fake agent ───────────────────────────────────────
# The fixture agent answers the five methods dcode's server answers, so the parts that only exist
# at run time — the load, the model the session has to be told about, the permission the agent asks
# the client for, the replay a load sends before the prompt — are tested without a provider.
def _drive(tmp_path, mode, resume="", model_spec="openai:gpt-5.4", prompt="do it"):
    import subprocess
    agent = pathlib.Path(__file__).resolve().parent / "fixtures" / "batch4" / "fake_acp_agent.py"
    log = tmp_path / "asked.ndjson"
    job = {"argv": [sys.executable, str(agent)], "cwd": str(tmp_path), "prompt": prompt,
           "model": "gpt-5.4", "model_spec": model_spec, "resume": resume, "timeout": 60,
           "env": {"FAKE_ACP_MODE": mode, "FAKE_ACP_LOG": str(log)}}
    proc = subprocess.run([sys.executable, str(pathlib.Path(D.__file__)), json.dumps(job)],
                          cwd=str(tmp_path), text=True, capture_output=True,
                          stdin=subprocess.DEVNULL, timeout=120,
                          env={**os.environ, "FAKE_ACP_MODE": mode, "FAKE_ACP_LOG": str(log)})
    evs = [json.loads(l) for l in proc.stdout.splitlines() if l.strip().startswith("{")]
    asked = [json.loads(l) for l in log.read_text().splitlines() if l.strip()]
    return evs, asked, proc


def test_a_first_turn_opens_a_session_and_answers(tmp_path):
    evs, asked, proc = _drive(tmp_path, "ok")
    assert proc.returncode == 0, proc.stderr
    assert [a["method"] for a in asked][:2] == ["initialize", "session/new"]
    init = next(e for e in evs if e.get("subtype") == "init")
    assert init["session_id"] == "fake-session-1"
    res = evs[-1]
    assert res["subtype"] == "success" and res["is_error"] is False
    assert res["result"] == "THE NEW ANSWER"


def test_a_resumed_turn_loads_instead_of_opening_a_new_one(tmp_path):
    evs, asked, _ = _drive(tmp_path, "ok", resume="fake-session-1")
    methods = [a["method"] for a in asked]
    assert "session/load" in methods and "session/new" not in methods
    loaded = next(a for a in asked if a["method"] == "session/load")
    # the same cwd the session was created with, which the agent requires
    assert loaded["params"]["cwd"] == str(tmp_path)
    assert next(e for e in evs if e.get("subtype") == "init")["session_id"] == "fake-session-1"


def test_the_replay_a_load_sends_is_not_this_turns_record(tmp_path):
    # THE defect this driver was written around: a loaded session replays the whole conversation
    # as updates, so a turn that recorded from the start would open with every earlier reply.
    evs, _, _ = _drive(tmp_path, "ok", resume="fake-session-1")
    text = json.dumps(evs)
    assert "AN OLD REPLY" not in text
    assert "an old prompt" not in text
    assert evs[-1]["result"] == "THE NEW ANSWER"


def test_an_agent_that_cannot_load_a_session_is_not_asked_to(tmp_path):
    evs, asked, _ = _drive(tmp_path, "no_load", resume="gone-forever")
    # loadSession is false in this mode, so the driver does not even try — and the turn still runs
    assert "session/load" not in [a["method"] for a in asked]
    assert "session/new" in [a["method"] for a in asked]
    assert evs[-1]["subtype"] == "success"


def test_a_session_the_agent_no_longer_has_runs_as_a_new_conversation(tmp_path):
    # The store was asked before this process started (_resume_lost), so a load that fails here is
    # not the place to tell the user: the turn runs as a new conversation and reports its new id.
    evs, asked, _ = _drive(tmp_path, "load_fails", resume="gone-forever")
    methods = [a["method"] for a in asked]
    assert methods.count("session/load") == 1 and "session/new" in methods
    assert next(e for e in evs if e.get("subtype") == "init")["session_id"] == "fake-session-1"
    assert evs[-1]["subtype"] == "success"


def test_this_turns_model_is_set_on_the_session_every_time(tmp_path):
    _, asked, _ = _drive(tmp_path, "ok", resume="fake-session-1", model_spec="openai:other-model")
    opt = next(a for a in asked if a["method"] == "session/set_config_option")
    assert opt["params"] == {"sessionId": "fake-session-1", "configId": "model",
                            "value": "openai:other-model"}


def test_a_model_the_session_refuses_is_said_out_loud_and_does_not_fail_the_turn(tmp_path):
    evs, _, _ = _drive(tmp_path, "bad_model")
    notices = [e for e in evs if e.get("subtype") == "notice"]
    assert notices, evs
    assert "could not be set" in notices[0]["text"]
    assert "openai:gpt-5.4" in notices[0]["text"]        # which model, so the record says what ran
    assert evs[-1]["subtype"] == "success"


def test_the_permission_the_agent_asks_for_is_answered_with_an_allow(tmp_path):
    evs, _, proc = _drive(tmp_path, "permission")
    assert proc.returncode == 0, proc.stderr
    names = [c["name"] for e in evs if e.get("type") == "assistant"
             for c in e["message"]["content"] if c.get("type") == "tool_use"]
    assert names == ["execute"]
    assert evs[-1]["subtype"] == "success"


def test_a_question_for_the_user_is_reported_as_what_it_is(tmp_path):
    # ask_user is declared on this surface, cannot be withheld, and raises a free-form interrupt
    # the protocol has no shape for: the server answers -32600 and the turn ends here.
    evs, _, proc = _drive(tmp_path, "ask_user")
    assert proc.returncode == 0, proc.stderr
    res = evs[-1]
    assert res["subtype"] == "error" and res["is_error"] is True
    assert "ask the user" in res["result"]
    assert "-32600" not in res["result"] and "LangGraph" not in res["result"]


def test_a_stop_reason_that_is_not_an_answer_is_an_error_with_a_reason(tmp_path):
    evs, _, _ = _drive(tmp_path, "refusal")
    res = evs[-1]
    assert res["is_error"] is True
    assert "refused" in res["result"]


def test_end_turn_with_nothing_said_is_not_an_answer(tmp_path):
    """MEASURED in this base's first column (2026-10-20): grok-4.5 through Vercel ended a turn
    with `output: []` — no content and no tool call — 18 output tokens billed and all of them
    reasoning, while the ACP server reported stopReason `end_turn`. Twice in three runs of that
    pair, a different scenario each time. The first was recorded as a completed turn whose answer
    was "", which the console shows as a done pill over a blank reply; with this branch the second
    was recorded as failed and the console showed the reason. What the provider did is the model's
    behaviour on this route and is a row-level finding in the notes; this test is about what the
    record says when it happens."""
    evs, _, proc = _drive(tmp_path, "silent_end_turn")
    assert proc.returncode == 0, proc.stderr
    res = evs[-1]
    assert res["subtype"] == "error" and res["is_error"] is True
    assert "without answering" in res["result"]
    assert res["result"] != ""


def test_end_turn_with_an_answer_is_still_a_success(tmp_path):
    evs, _, proc = _drive(tmp_path, "ok")
    res = evs[-1]
    assert res["subtype"] == "success" and res["is_error"] is False
    assert res["result"].strip()


def test_an_agent_that_does_not_start_is_reported_rather_than_crashing(tmp_path):
    import subprocess
    job = {"argv": [str(tmp_path / "there-is-no-such-binary")], "cwd": str(tmp_path),
           "prompt": "x", "model": "m", "model_spec": "openai:m", "resume": "", "timeout": 5}
    proc = subprocess.run([sys.executable, str(pathlib.Path(D.__file__)), json.dumps(job)],
                          text=True, capture_output=True, stdin=subprocess.DEVNULL, timeout=60)
    evs = [json.loads(l) for l in proc.stdout.splitlines() if l.strip().startswith("{")]
    assert proc.returncode == 0
    assert evs[-1]["is_error"] is True and "did not start" in evs[-1]["result"]


# ── a provider failure, in the shape one really arrives in ────────────────────────────────────
# RECORDED through the runner's own relay with a bad key (2026-10-19): the agent answers the
# prompt with -32603 "Internal error" and puts its own traceback in `data.details`, frames joined
# by " / ". The turn must FAIL — several CLIs narrate a provider refusal as ordinary assistant text
# and end the run normally, which is how a 401 becomes a turn's answer — and the reason must be
# the provider's sentence rather than the agent's internals.
_REAL_401 = {
    "code": -32603, "message": "Internal error",
    "data": {"details": (
        "Error code: 401 - {'error': {'message': 'Authentication failed. Create an API key and "
        "set in AI_GATEWAY_API_KEY environment variable', 'type': 'authentication_error'}} / "
        "raise OpenAIAuthenticationError( / langchain_openai.chat_models.base."
        "OpenAIAuthenticationError: Error code: 401 / During task with name 'model' and id "
        "aa320639-2379-c8bd-8c57-e2a7b78fe534")}}


def test_a_provider_refusal_reads_as_the_providers_own_sentence():
    text = D.error_text(_REAL_401)
    assert "401" in text and "Authentication failed" in text
    assert "Internal error" not in text          # the JSON-RPC envelope is not the reason
    assert "raise OpenAIAuthenticationError" not in text   # nor is the traceback
    assert "During task with name" not in text
    assert len(text) <= 600


def test_an_error_with_nothing_in_it_still_has_a_reason():
    assert D.error_text({}) == "the agent reported an error"
    assert D.error_text({"message": "boom"}) == "boom"
    assert D.error_text(None) == "the agent reported an error"


def test_a_provider_refusal_fails_the_turn_without_the_agents_traceback(tmp_path):
    # The CLI writes a full Python traceback to stderr at the same time as the refusal. A reason
    # that already names the refusal is worse off with three frames of langchain_openai glued to
    # it, so the stderr tail is kept for the failures that have no reason of their own.
    evs, _, proc = _drive(tmp_path, "provider_401")
    assert proc.returncode == 0, proc.stderr
    res = evs[-1]
    assert res["subtype"] == "error" and res["is_error"] is True
    assert "401" in res["result"] and "Authentication failed" in res["result"]
    assert "Traceback" not in res["result"]
    assert "langchain_openai" not in res["result"]
    # and the gateway's own framing is not repeated here: it says "The turn failed: <reason>"
    # around whatever this hands up, and the family tour showed that twice over (2026-10-20).
    assert "turn failed" not in res["result"].lower(), res["result"]
