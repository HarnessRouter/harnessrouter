"""The five bases added together: mimo, gajae, jcode, opensquilla, nanobot.

Everything asserted here was MEASURED against the pinned build named beside it, on 2026-10-02, not
read off documentation. Each test pins one thing that would otherwise fail SILENTLY — the class of
defect the last three harness PRs were taken over for:

  * a shared helper reused for a fork whose spelling differs by one flag (mimo)
  * a normaliser that treats a provider failure as an answer (gajae's agent_failed)
  * usage read from the field the CLI offers rather than the one that is true (jcode's done.usage,
    which holds only the LAST request's numbers)
  * a default that substitutes the model (opensquilla's router) or that cannot fit the prompt
    (its 8k assumption for a generic endpoint)
  * a tool policy applied at one tool source and not the other (nanobot's session policy)

Pinned builds: @mimo-ai/cli 0.1.15 · gjc 0.18.5 · jcode v0.90.0 · opensquilla 0.5.6 · nanobot-ai 0.3.5
"""
import json
import pathlib
import sys
import tempfile

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from server import (ALL_GAJAE_TOOLS, ALL_JCODE_TOOLS, ALL_NANOBOT_TOOLS,  # noqa: E402
                    Auth, BACKENDS, CHECKPOINT_EXCLUDE, _agent_doc_path, _build_gajae,
                    _build_jcode, _build_mimo, _build_nanobot, _build_opensquilla,
                    _BRIDGED_TRANSPORTS, _JCODE_SANDBOX_OFF, _gajae_to_claude, _jcode_eof, _jcode_to_claude,
                    _opencode_to_claude, _opensquilla_eof, _opensquilla_to_claude,
                    _opensquilla_transcript,
                    _jcode_session_model, _mcp_url_is_loopback, _opensquilla_usage,
                    _produced_visible, _resume_lost, _sse_bridges,
                    _visible_root,
                    _write_input_files, _write_skills)

UP = "https://up.example/v1"


def _ws():
    d = tempfile.mkdtemp()
    (pathlib.Path(d) / ".harness" / "home").mkdir(parents=True)
    return d


def _norm(fn, lines, model="gpt-5.4", cwd=""):
    state: dict = {"model": model, "final": "", "cwd": cwd}
    out = []
    for ln in lines:
        out += fn(ln, state)
    return out, state


# ── registration: the five places a missing row fails silently ────────────────────────────────

def test_every_base_is_registered():
    # gajae is in BACKENDS (the runner can execute it) but NOT in the gateway's catalogs, so the
    # product never asks it to — gateway/tests/test_gajae_not_offered.py pins that and says why.
    for b in ("mimo", "gajae", "jcode", "opensquilla", "nanobot"):
        assert b in BACKENDS, b
        assert BACKENDS[b]["providers"], b
        assert BACKENDS[b]["default_model"], b
        assert BACKENDS[b]["normalize"] is not None, b


def test_all_five_read_agents_md():
    # Measured per CLI (see _agent_doc_path's comment). Getting this wrong writes the file and the
    # agent never sees it, so the workspace contract never arrives and nothing says so.
    for b in ("mimo", "gajae", "jcode", "opensquilla", "nanobot"):
        assert _agent_doc_path("/w", b).name == "AGENTS.md", b


def test_skills_land_where_each_loader_looks():
    want = {
        "mimo": ".harness/skills",                        # named in mimo.json's skills.paths
        "gajae": ".harness/home/.gjc/agent/skills",        # gjc's canonical user root
        "jcode": ".harness/home/.jcode/skills",            # jcode's global root
        "opensquilla": ".harness/opensquilla/skills",      # its managed root = $OPENSQUILLA_STATE_DIR/skills
        "nanobot": "workspace/skills",                     # the ONE path its loader reads, inside
                                                           # the nested workspace (see _NANOBOT_WS)
    }
    for backend, rel in want.items():
        d = _ws()
        _write_skills(d, [{"name": "demo", "content": "# demo"}], backend=backend)
        assert (pathlib.Path(d) / rel / "demo" / "SKILL.md").is_file(), backend


# ── mimo: an opencode fork, and every difference is a parameter rather than a copy ────────────

def test_mimo_argv_is_opencodes_with_its_own_spellings():
    d, env = _ws(), {}
    cmd = _build_mimo("openai-api", Auth(api_key="sk-t", base_url=UP), "gpt-5.4", "do it", d, env)
    assert cmd[0] == "mimo" and cmd[1] == "run"
    assert "--format" in cmd and cmd[cmd.index("--format") + 1] == "json"
    # Nothing runs unattended without this: measured, the turn stops at the first write.
    assert "--dangerously-skip-permissions" in cmd
    assert "--pure" in cmd and "--thinking" in cmd
    # NOT opencode's --auto / --session: the fork renamed both.
    assert "--auto" not in cmd
    assert cmd[-1] == "do it"
    # Its own config env var and file name, so two backends in one workspace cannot collide.
    assert env["MIMOCODE_CONFIG"].endswith("/.harness/mimo.json")
    assert (pathlib.Path(d) / ".harness" / "mimo.json").is_file()
    assert not (pathlib.Path(d) / ".harness" / "opencode.json").exists()


def test_mimo_config_is_the_opencode_schema_with_the_key_named_not_written():
    d, env = _ws(), {}
    # deepseek-v4-pro rather than a gpt-5.x id: the fork kept _opencode_npm's per-model split, and
    # a gpt-5.x id would correctly pick @ai-sdk/openai (the Responses package) instead.
    _build_mimo("openai-api", Auth(api_key="sk-secret", base_url=UP), "deepseek-v4-pro", "hi", d, env,
                tools_disabled=["bash (Shell)"])
    cfg = json.loads((pathlib.Path(d) / ".harness" / "mimo.json").read_text())
    assert cfg["provider"]["hr"]["npm"] == "@ai-sdk/openai-compatible"
    assert cfg["provider"]["hr"]["options"]["apiKey"] == "{env:HR_MIMO_KEY}"
    # The real key never reaches the CLI at all: every OpenAI-shape turn rides the loopback relay,
    # so what the config names and what the environment carries is a per-turn PLACEHOLDER.
    assert "sk-secret" not in json.dumps(cfg)
    assert env["HR_MIMO_KEY"].startswith("hr-relay-") and env["HR_MIMO_KEY"] != "sk-secret"
    assert cfg["permission"] == {"bash": "deny"}
    # opencode's snapshot repo is a git repo of the workspace under $HOME; left on it reached
    # 699 MB in twenty turns (#193). The fork inherited it, so it is turned off here too.
    assert cfg["snapshot"] is False
    # The turn's connection and nothing else: mimo's built-in xiaomi provider is what a model's
    # `actor` subagent reached on rc.6, refused with "Invalid API Key", failing a finished turn.
    assert cfg["enabled_providers"] == ["hr"] and list(cfg["provider"]) == ["hr"]
    # mimo's own built-in skills off (pptx-official on python-pptx, which no sandbox here can get);
    # the harness's skills come through skills.paths and stay
    assert env["MIMOCODE_DISABLE_BUILTIN_SKILLS"] == "1"


def test_opencode_too_reaches_only_the_turns_connection():
    d, env = _ws(), {}
    from server import _build_opencode
    _build_opencode("openai-api", Auth(api_key="k", base_url=UP), "deepseek-v4-pro", "hi", d, env)
    cfg = json.loads((pathlib.Path(d) / ".harness" / "opencode.json").read_text())
    assert cfg["enabled_providers"] == ["hr"] and list(cfg["provider"]) == ["hr"]


def test_mimo_shares_opencodes_normaliser():
    # The stream is opencode's line for line, measured: {type,timestamp,sessionID,part}.
    assert BACKENDS["mimo"]["normalize"] is _opencode_to_claude
    evs, state = _norm(_opencode_to_claude, [
        {"type": "step_start", "sessionID": "ses_x", "part": {"type": "step-start"}},
        {"type": "text", "sessionID": "ses_x", "part": {"type": "text", "text": "OK"}},
        {"type": "step_finish", "sessionID": "ses_x",
         "part": {"type": "step-finish", "reason": "stop",
                  "tokens": {"total": 14450, "input": 14413, "output": 7, "reasoning": 30,
                             "cache": {"write": 0, "read": 0}}}},
    ])
    assert evs[0]["type"] == "system" and evs[0]["session_id"] == "ses_x"
    assert state["final"] == "OK"


def test_mimo_resume_is_not_claimed_for_a_session_this_workspace_does_not_hold():
    # Its SQLite store is opencode's under another name, $HOME/.local/share/mimocode/mimocode.db.
    # Naming a session it does not hold exits 1 before the first event, which would wedge every
    # later turn in the conversation rather than one.
    d = _ws()
    env = {"HOME": str(pathlib.Path(d) / ".harness" / "home")}
    cmd = _build_mimo("openai-api", Auth(api_key="k", base_url=UP), "gpt-5.4", "hi", d, env,
                      resume_session_id="ses_gone")
    assert "-s" not in cmd
    assert _resume_lost("mimo", cmd, "ses_gone", d) == "ses_gone"
    db = pathlib.Path(env["HOME"]) / ".local" / "share" / "mimocode"
    db.mkdir(parents=True, exist_ok=True)
    (db / "mimocode.db").write_bytes(b"...ses_here...")
    cmd = _build_mimo("openai-api", Auth(api_key="k", base_url=UP), "gpt-5.4", "hi", d, env,
                      resume_session_id="ses_here")
    assert cmd[cmd.index("-s") + 1] == "ses_here"
    assert _resume_lost("mimo", cmd, "ses_here", d) is None


# ── gajae: pi's stream, pi's normaliser, and the one event pi has no branch for ────────────────

def test_gajae_argv():
    d, env = _ws(), {"HOME": str(pathlib.Path(_ws()) / "h")}
    cmd = _build_gajae("openai-api", Auth(api_key="k", base_url=UP), "gpt-5.4", "do it", d, env)
    assert cmd[0] == "gjc" and "-p" in cmd
    assert cmd[cmd.index("--mode") + 1] == "json"
    # Fully qualified, because --model is a FUZZY pattern and a custom provider also gets
    # auto-enabled /v1/models discovery: a bare family name among hundreds of discovered ids is a
    # substitution waiting to happen.
    assert cmd[cmd.index("--model") + 1] == "hr/gpt-5.4"
    # Session storage AND lookup inside .harness/, so the transcript is checkpointed and is never
    # handed back as a produced file.
    assert cmd[cmd.index("--session-dir") + 1].endswith("/.harness/gajae-sessions")
    # The conventional MCP autoload includes a file IN the workspace (.gjc/mcp.json) that a task
    # could write and the next turn would execute — pi's --no-extensions hole, closed the same way.
    assert "--no-mcp" in cmd
    assert cmd[-1] == "do it"
    # A signed model-preset registry fetched at start-up can rewrite which model a preset names.
    assert env["GJC_MODEL_PRESET_REGISTRY_DISABLED"] == "1"


def test_gajae_models_yml_names_the_key_rather_than_holding_it():
    d = _ws()
    env = {"HOME": str(pathlib.Path(d) / ".harness" / "home")}
    # deepseek-v4-pro, not a gpt-5.x id: pi's own api split sends the gpt-5 line to
    # openai-responses, which is correct and is asserted separately below.
    _build_gajae("openai-api", Auth(api_key="sk-secret", base_url=UP), "deepseek-v4-pro", "hi", d, env)
    mv = pathlib.Path(env["HOME"], ".gjc", "agent", "models.yml").read_text()
    assert "sk-secret" not in mv
    assert json.loads(mv)["providers"]["hr"]["apiKey"] == "HR_GAJAE_KEY"
    assert json.loads(mv)["providers"]["hr"]["api"] == "openai-completions"
    # What the variable holds is the relay's per-turn placeholder, never the provider key: the
    # file is in the checkpointed workspace, and the real key stays in the runner process.
    assert env["HR_GAJAE_KEY"].startswith("hr-relay-") and env["HR_GAJAE_KEY"] != "sk-secret"
    # The gpt-5 line goes to the Responses api instead — pi's split, inherited.
    d2 = _ws(); env2 = {"HOME": str(pathlib.Path(d2) / ".harness" / "home")}
    _build_gajae("openai-api", Auth(api_key="k", base_url=UP), "gpt-5.4", "hi", d2, env2)
    mv2 = json.loads(pathlib.Path(env2["HOME"], ".gjc", "agent", "models.yml").read_text())
    assert mv2["providers"]["hr"]["api"] == "openai-responses"
    # Excluded from the checkpoint anyway: a future build reading apiKey as a literal must not turn
    # this file into a leak.
    assert "./.harness/home/.gjc/agent/models.yml" in CHECKPOINT_EXCLUDE


def test_gajae_tool_allowlist_is_the_full_set_minus_the_disabled_one():
    d = _ws()
    env = {"HOME": str(pathlib.Path(d) / ".harness" / "home")}
    cmd = _build_gajae("openai-api", Auth(api_key="k", base_url=UP), "gpt-5.4", "hi", d, env,
                       tools_disabled=["write (File Write)"])
    allow = next(a for a in cmd if a.startswith("--tools="))[len("--tools="):].split(",")
    assert "write" not in allow
    assert set(allow) == ALL_GAJAE_TOOLS - {"write"}
    # A disable list naming nothing this runtime has is not a constraint, so nothing is sent — an
    # allowlist that removes nothing would only risk narrowing the set by accident.
    cmd = _build_gajae("openai-api", Auth(api_key="k", base_url=UP), "gpt-5.4", "hi", d, env,
                       tools_disabled=["WebSearch"])
    assert not any(a.startswith("--tools") for a in cmd)


def test_gajae_provider_failure_is_a_failed_turn_not_an_answer():
    # MEASURED against the pinned binary with a bad key: the turn ends on an assistant message_end
    # with stopReason "error" and the provider's sentence in errorMessage, and the CLI exits 1.
    evs, state = _norm(_gajae_to_claude, [
        {"type": "session", "id": "01a0", "version": 5},
        {"type": "message_end", "message": {
            "role": "assistant", "content": [], "model": "gpt-5.4", "stopReason": "error",
            "errorStatus": 401, "errorMessage": "401 Authentication failed.",
            "usage": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}}},
        {"type": "agent_end", "messages": []},
    ])
    res = evs[-1]
    assert res["type"] == "result" and res["is_error"] is True
    assert "401 Authentication failed." in res["result"]


def test_gajae_agent_failed_is_the_reason_and_never_the_answer():
    # print-mode.ts writes this when the terminal disposition is a failure no message_end reported.
    # pi's normaliser has no branch for it, so without this one the turn would complete with
    # whatever text came before as its answer.
    evs, state = _norm(_gajae_to_claude, [
        {"type": "session", "id": "01a0"},
        {"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "let me look"}},
        {"type": "agent_failed", "error": {"code": "empty_turn", "message": "the model returned nothing"}},
        {"type": "agent_end", "messages": []},
    ])
    res = evs[-1]
    assert res["is_error"] is True
    assert res["result"] == "the model returned nothing"


def test_gajae_answer_that_merely_mentions_an_error_still_passes():
    # The anchored-match rule: a coding agent writes about errors constantly, and an unanchored
    # match turns real answers into failures (the goose lesson). Nothing here sets the error state.
    evs, _ = _norm(_gajae_to_claude, [
        {"type": "session", "id": "01a0"},
        {"type": "message_end", "message": {
            "role": "assistant", "model": "gpt-5.4", "stopReason": "stop",
            "content": [{"type": "text", "text": "I fixed the error in parse(): it threw on empty input."}],
            "usage": {"input": 10, "output": 5}}},
        {"type": "agent_end", "messages": []},
    ])
    assert evs[-1]["is_error"] is False
    assert "I fixed the error" in evs[-1]["result"]


def test_gajae_resume_only_when_the_session_file_is_here():
    d = _ws()
    env = {"HOME": str(pathlib.Path(d) / ".harness" / "home")}
    cmd = _build_gajae("openai-api", Auth(api_key="k", base_url=UP), "gpt-5.4", "hi", d, env,
                       resume_session_id="01a0-gone")
    assert "-r" not in cmd and _resume_lost("gajae", cmd, "01a0-gone", d) == "01a0-gone"
    sd = pathlib.Path(d, ".harness", "gajae-sessions")
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "2026-10-02T22-43-45-033Z_01a0-here.jsonl").write_text("{}")
    cmd = _build_gajae("openai-api", Auth(api_key="k", base_url=UP), "gpt-5.4", "hi", d, env,
                       resume_session_id="01a0-here")
    assert cmd[cmd.index("-r") + 1] == "01a0-here"
    assert _resume_lost("gajae", cmd, "01a0-here", d) is None


# ── jcode: its own schema, and two measured facts a naive reading gets wrong ───────────────────

def test_jcode_argv_pins_the_version_under_the_measurement():
    d, env = _ws(), {"HOME": str(pathlib.Path(_ws()) / "h")}
    cmd = _build_jcode("openai-api", Auth(api_key="k", base_url=UP), "gpt-5.4", "do it", d, env)
    assert cmd[0] == "jcode"
    # MANDATORY: auto-update defaults to true, so without this the binary replaces itself midway
    # through a measurement — the Muse Code failure, written into the argv.
    assert "--no-update" in cmd
    assert cmd[cmd.index("--provider") + 1] == "openai-compatible"
    assert cmd[cmd.index("--model") + 1] == "gpt-5.4"
    assert cmd[-3:] == ["run", "--ndjson", "do it"]
    # The relay token rides the ENVIRONMENT, which is what _relay_served_model keys off: a backend
    # whose credential rides argv or a file leaves matrix rule 2 unevaluable (the openhands defect).
    assert env["JCODE_OPENAI_COMPAT_API_BASE"].startswith("http")
    assert env["OPENAI_COMPAT_API_KEY"]
    # Telemetry is on by default and prints a notice on every run.
    assert env["JCODE_NO_TELEMETRY"] == "1"


def test_jcode_disabled_tools_are_filtered_to_names_this_runtime_has():
    d, env = _ws(), {"HOME": str(pathlib.Path(_ws()) / "h")}
    cmd = _build_jcode("openai-api", Auth(api_key="k", base_url=UP), "gpt-5.4", "hi", d, env,
                       tools_disabled=["write (File Write)", "NotATool"])
    assert cmd[cmd.index("--disabled-tools") + 1].split(",") == sorted({"write"} | _JCODE_SANDBOX_OFF)
    assert "write" in ALL_JCODE_TOOLS and "notatool" not in ALL_JCODE_TOOLS


def test_jcode_tools_that_cannot_work_in_the_sandbox_are_off_on_every_turn():
    # rc.7: gpt-5.4-mini picked jcode's own Firefox-bridge `browser` over the browser plug and ran
    # 459 tool calls for two hours trying to connect it. Off whatever the harness asks for.
    d, env = _ws(), {"HOME": str(pathlib.Path(_ws()) / "h")}
    cmd = _build_jcode("openai-api", Auth(api_key="k", base_url=UP), "gpt-5.4", "hi", d, env)
    off = set(cmd[cmd.index("--disabled-tools") + 1].split(","))
    assert off == set(_JCODE_SANDBOX_OFF) and {"browser", "macos_computer_use", "gmail", "maintainer_feedback"} <= off
    assert _JCODE_SANDBOX_OFF <= ALL_JCODE_TOOLS and "bash" not in off and "webfetch" not in off


def test_jcode_usage_is_summed_across_requests_and_netted_of_both_caches():
    # The two facts: `done.usage` holds only the LAST request's numbers (NdjsonRunState.usage is
    # assigned, never accumulated), and `input` is GROSS — jcode's own OpenAI client says
    # "input_tokens is the total, including both cache-read and cache-write subsets".
    # Measured turn: tokens(10609/63, read 10431, write 175) then tokens(10748/5, read 10606,
    # write 139), with done.usage reporting only the second.
    evs, state = _norm(_jcode_to_claude, [
        {"type": "start", "session_id": "session_sloth_1", "model": "gpt-5.4"},
        {"type": "tokens", "input": 10609, "output": 63, "cache_read_input": 10431,
         "cache_creation_input": 175},
        {"type": "tokens", "input": 10748, "output": 5, "cache_read_input": 10606,
         "cache_creation_input": 139},
        {"type": "text_delta", "text": "DONE"},
        {"type": "done", "text": "DONE", "model": "gpt-5.4", "session_id": "session_sloth_1",
         "usage": {"input_tokens": 10748, "output_tokens": 5,
                   "cache_read_input_tokens": 10606, "cache_creation_input_tokens": 139}},
    ])
    res = evs[-1]
    assert res["type"] == "result" and res["is_error"] is False and res["result"] == "DONE"
    u = res["usage"]
    assert u["cache_read_tokens"] == 10431 + 10606
    assert u["cache_write_tokens"] == 175 + 139
    assert u["input_tokens"] == (10609 - 10431 - 175) + (10748 - 10606 - 139)
    assert u["output_tokens"] == 68
    # Not the number the CLI offers, which would under-report the turn by more than half.
    assert u["input_tokens"] != 10748


def test_jcode_error_event_fails_the_turn_and_keeps_the_reason():
    evs, _ = _norm(_jcode_to_claude, [
        {"type": "start", "session_id": "s", "model": "gpt-5.4"},
        {"type": "error", "message": "OpenAI-compatible chat request failed\n  status: 401 Unauthorized"},
    ])
    assert evs[-1]["is_error"] is True and "401 Unauthorized" in evs[-1]["result"]


def test_jcode_eof_fails_a_stream_that_ended_with_neither_terminal_event():
    # Killed, cancelled, or dead before the emitter. An EMPTY result lets the run loop's stderr tail
    # be the reason instead of a sentence invented here.
    out = _jcode_eof({"model": "gpt-5.4", "final": "half an answer"}, 1)
    assert out[0]["is_error"] is True and out[0]["result"] == ""
    out = _jcode_eof({"model": "gpt-5.4", "final": "an answer"}, 0)
    assert out[0]["is_error"] is False and out[0]["result"] == "an answer"


def _tool_uses(evs):
    return [b for e in evs if e.get("type") == "assistant"
            for b in e["message"]["content"] if b.get("type") == "tool_use"]


def test_jcode_tool_call_carries_the_arguments_its_input_pieces_built():
    # Captured from jcode v0.90.0 against a stub endpoint that streamed one bash call in three
    # pieces (2026-10-12). The arguments arrive AFTER tool_start, as tool_input pieces with no id;
    # emitting the call at tool_start sent it with {} and the console row had nothing to open.
    evs, _ = _norm(_jcode_to_claude, [
        {"type": "start", "session_id": "s", "model": "stub-model"},
        {"id": "call_stub1", "name": "bash", "type": "tool_start"},
        {"delta": "{\"comm", "type": "tool_input"},
        {"delta": "and\": \"echo stub-", "type": "tool_input"},
        {"delta": "ok\"}", "type": "tool_input"},
        {"id": "call_stub1", "name": "bash", "type": "tool_exec"},
        {"stop_reason": "tool_calls", "type": "message_end"},
        {"error": None, "id": "call_stub1", "name": "bash", "type": "tool_done",
         "output": "stub-ok\n\n--- Command finished with exit code: 0 ---\n"},
        {"stop_reason": "stop", "type": "message_end"},
        {"type": "done", "text": "finished", "model": "stub-model", "session_id": "s"},
    ])
    uses = _tool_uses(evs)
    assert [(u["id"], u["name"], u["input"]) for u in uses] == [("call_stub1", "bash", {"command": "echo stub-ok"})]
    kinds = [e["type"] for e in evs]
    assert kinds.index("user") > kinds.index("assistant")   # the call before its result


def test_jcode_two_calls_in_one_message_keep_their_own_arguments_and_order():
    evs, _ = _norm(_jcode_to_claude, [
        {"type": "start", "session_id": "s", "model": "m"},
        {"id": "a", "name": "read", "type": "tool_start"}, {"delta": "{\"path\": \"x\"}", "type": "tool_input"},
        {"id": "b", "name": "bash", "type": "tool_start"}, {"delta": "{\"command\": \"ls\"}", "type": "tool_input"},
        {"id": "a", "name": "read", "type": "tool_exec"},
        {"id": "b", "name": "bash", "type": "tool_exec"},
        {"type": "message_end", "stop_reason": "tool_calls"},
        {"type": "done", "text": "ok"},
    ])
    assert [(u["id"], u["input"]) for u in _tool_uses(evs)] == [("a", {"path": "x"}), ("b", {"command": "ls"})]


def test_jcode_call_cut_off_by_a_kill_still_shows_what_had_arrived():
    state = {"model": "m"}
    for o in ({"type": "start", "session_id": "s"}, {"id": "c", "name": "bash", "type": "tool_start"},
              {"delta": "{\"command\": \"sleep", "type": "tool_input"}):
        assert _jcode_to_claude(o, state) in ([], [{"type": "system", "subtype": "init", "session_id": "s", "model": "m"}])
    out = _jcode_eof(state, 1)
    assert _tool_uses(out) == [{"type": "tool_use", "id": "c", "name": "bash",
                                "input": {"arguments": "{\"command\": \"sleep"}}]
    assert out[-1]["type"] == "result" and out[-1]["is_error"] is True


def test_jcode_bridges_remote_mcp_because_it_has_no_client_for_one():
    # "jcode currently supports stdio (command-based) servers only; HTTP/SSE entries are recognized
    # and skipped with a log line" — so without the bridge every remote server a harness declares is
    # dropped in silence and the agent simply never has those tools.
    assert set(_BRIDGED_TRANSPORTS["jcode"]) == {"http", "sse"}
    d, env = _ws(), {"HOME": str(pathlib.Path(_ws()) / "h")}
    pathlib.Path(env["HOME"]).mkdir(parents=True, exist_ok=True)
    _build_jcode("openai-api", Auth(api_key="k", base_url=UP), "gpt-5.4", "hi", d, env,
                 mcp_servers=[{"name": "deepwiki", "command": "/bin/sh", "args": ["/l.sh"]}])
    cfg = json.loads((pathlib.Path(env["HOME"]) / ".jcode" / "mcp.json").read_text())
    assert cfg["mcpServers"]["deepwiki"]["command"] == "/bin/sh"


# ── opensquilla: three defaults a harness must undo ────────────────────────────────────────────

def test_opensquilla_config_turns_the_router_off_and_declares_the_window():
    d, env = _ws(), {}
    _build_opensquilla("openai-api", Auth(api_key="k", base_url=UP), "gpt-5.4", "hi", d, env)
    cfg = pathlib.Path(d, ".harness", "opensquilla", "config.toml").read_text()
    # Its router scores each turn and routes it across four tiers to the cheapest capable model,
    # i.e. substitutes the model by design, and it is ON by default.
    assert "[squilla_router]" in cfg and "enabled = false" in cfg
    # A generic endpoint is assumed to hold 8192 tokens, and its own system block plus tool schemas
    # are ~43k characters: the first probe died with provider_request_too_large on three sentences.
    assert '[models.custom."gpt-5.4"]' in cfg
    assert "context_window = 200000" in cfg
    assert 'provider = "custom"' in cfg


def test_opensquilla_denies_cron_which_a_one_shot_turn_never_runs():
    # Its scheduler never runs under `opensquilla agent`, and its description was the only non-English
    # text in the request (Chinese examples); gpt-5.5 opened English answers in Chinese on rc.15.
    # Measured with the request captured at a stub: 26 tools with cron, 25 and no Chinese without.
    import tomllib
    d, env = _ws(), {}
    _build_opensquilla("openai-api", Auth(api_key="k", base_url=UP), "gpt-5.4", "hi", d, env)
    cfg = tomllib.loads(pathlib.Path(d, ".harness", "opensquilla", "config.toml").read_text())
    assert cfg["tools"]["deny"] == ["cron"]


def test_opensquilla_reply_language_rules_come_out_of_its_template(tmp_path, monkeypatch):
    # gpt-5.4 answered English prompts in Chinese (8 of 8) under these rules, in French without the
    # Chinese one, and in English (4 of 4) without all three, rc.16.
    import server
    t = tmp_path / "lib" / "python3.12" / "site-packages" / "opensquilla" / "identity" / "templates"
    t.mkdir(parents=True)
    body = ("## Reply Guidelines\n\n"
            "- Use the conversation's language for all user-visible replies, including progress notes, tables, and final answers.\n"
            "- If the user writes in Chinese, keep replying in Chinese unless they explicitly ask for another language.\n"
            "- Lead final answers with the result and a usable reference when relevant.\n"
            "## Tools\n- Write tool preambles in the same language as the user's current conversation.\n- Keep it short.\n")
    (t / "system_prompt.j2").write_text(body)
    monkeypatch.setattr(server, "_OPENSQUILLA_LANGUAGE_DONE", [])
    assert server._opensquilla_reply_language_fix(tmp_path) == "removed"
    out = (t / "system_prompt.j2").read_text()
    assert "language" not in out and "Chinese" not in out
    assert "- Lead final answers with the result" in out and "- Keep it short." in out
    monkeypatch.setattr(server, "_OPENSQUILLA_LANGUAGE_DONE", [])
    assert server._opensquilla_reply_language_fix(tmp_path) == "absent"      # idempotent
    assert server._opensquilla_reply_language_fix(tmp_path) == "done"        # once per runner


def test_opensquilla_argv_bounds_retries_and_keeps_a_session_db():
    d, env = _ws(), {}
    cmd = _build_opensquilla("openai-api", Auth(api_key="k", base_url=UP), "gpt-5.4", "hi", d, env,
                             resume_session_id="sess-1", max_turns=12)
    assert cmd[1] == "agent" and cmd[cmd.index("-m") + 1] == "hi"
    assert "--json" in cmd and "--event-stream-stderr" in cmd
    assert cmd[cmd.index("--permissions") + 1] == "bypass"
    # The default is `:memory:` — without an explicit file there is NO continuity between turns.
    assert cmd[cmd.index("--session-db-path") + 1].endswith("/.harness/opensquilla/sessions.sqlite")
    assert cmd[cmd.index("--session-id") + 1] == "sess-1"
    assert cmd[cmd.index("--max-iterations") + 1] == "12"
    # A provider answering the same 503 every time should not cost minutes before the reason lands.
    assert cmd[cmd.index("--max-provider-retries") + 1] == "2"
    assert env["OPENSQUILLA_STATE_DIR"].endswith("/.harness/opensquilla")
    # The relay's per-turn placeholder, not the provider key — and in the ENVIRONMENT, which is
    # where _relay_served_model looks for the route.
    assert env["CUSTOM_LLM_API_KEY"].startswith("hr-relay-")


def test_opensquilla_final_answer_comes_from_the_transcript_not_from_text():
    # MEASURED: asked to "reply with exactly DONE", its stdout object's `text` was
    # "I'll create `probe.txt` with the requested content and verify it.DONE" — the whole turn's
    # assistant output concatenated — while the transcript's LAST assistant message was "DONE".
    d = _ws()
    base = pathlib.Path(d, ".harness", "opensquilla")
    base.mkdir(parents=True)
    (base / "transcript.jsonl").write_text("\n".join(json.dumps(x) for x in [
        {"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": "go"}]}},
        {"type": "message", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "I’ll create probe.txt and verify it."},
            {"type": "toolCall", "name": "write_file", "id": "call_1", "arguments": {}}]}},
        {"type": "message", "message": {"role": "toolResult", "toolCallId": "call_1",
                                        "toolName": "write_file", "isError": False,
                                        "content": [{"type": "text", "text": "Written 6 bytes"}]}},
        {"type": "message", "message": {"role": "assistant",
                                        "content": [{"type": "text", "text": "DONE"}]}},
    ]))
    final_obj = {"status": "ok", "session_key": "s1", "text": "I’ll create probe.txt and verify it.DONE",
                 "usage": {"input_tokens": 25343, "output_tokens": 346, "cached_tokens": 16764,
                           "model_usage_breakdown": [{"cache_write_tokens": 8570}]}}
    evs, state = _norm(_opensquilla_to_claude, [
        {"_event": True, "schema_version": 1, "kind": "tool_use_start",
         "tool_use_id": "call_1", "tool_name": "write_file"},
        {"_event": True, "schema_version": 1, "kind": "tool_result",
         "tool_use_id": "call_1", "tool_name": "write_file", "is_error": False},
        final_obj,
    ], cwd=d)
    tail = _opensquilla_eof(state, 0)
    res = tail[-1]
    assert res["is_error"] is False
    assert res["result"] == "DONE"
    # the tool result's CONTENT, which the progress stream withholds by design, comes back here
    assert any(e.get("type") == "user" and "Written 6 bytes" in json.dumps(e) for e in tail)
    # usage netted: cached and cache_write are both SUBSETS of input_tokens (measured: 16764 + 8570
    # is within nine tokens of 25343).
    assert res["usage"]["input_tokens"] == 25343 - 16764 - 8570
    assert res["usage"]["cache_read_tokens"] == 16764
    assert res["usage"]["cache_write_tokens"] == 8570


def test_opensquilla_a_routed_model_fails_the_turn():
    # The router is off by configuration. If one of its decisions still arrives, the turn ran on a
    # model nobody asked for, and a substitution is a finding — never a pass.
    state = {"model": "gpt-5.4", "final": "an answer", "cwd": _ws()}
    _opensquilla_to_claude({"_event": True, "kind": "router_decision", "tier": "c1",
                            "model": "deepseek-v4-flash", "source": "router"}, state)
    _opensquilla_to_claude({"status": "ok", "session_key": "s", "usage": {}}, state)
    res = _opensquilla_eof(state, 0)[-1]
    assert res["is_error"] is True
    assert "deepseek-v4-flash" in res["result"] and "gpt-5.4" in res["result"]


def test_opensquilla_only_event_objects_are_read_as_events():
    # Its own warning: stderr also carries ordinary diagnostics, so only `_event: true` counts.
    state = {"model": "gpt-5.4", "final": "", "cwd": _ws()}
    assert _opensquilla_to_claude({"kind": "tool_use_start", "tool_name": "rm_rf"}, state) == []
    assert "_sq_final" not in state


def test_opensquilla_usage_of_nothing_is_nothing():
    assert _opensquilla_usage(None) == {}
    assert _opensquilla_usage({"input_tokens": 0, "output_tokens": 0}) == {}


# ── nanobot: the driver's contract with the runner ─────────────────────────────────────────────

def test_nanobot_job_puts_the_session_store_inside_the_checkpointed_tree():
    d, env = _ws(), {}
    cmd = _build_nanobot("openai-api", Auth(api_key="k", base_url=UP), "gpt-5.4", "hi", d, env,
                         resume_session_id="hr-1")
    assert cmd[1].endswith("nanobot_driver.py")
    job = json.loads(cmd[2])
    assert job["session_key"] == "hr-1"
    # Sessions live beside the CONFIG file (get_data_dir() is get_config_path().parent), so the
    # config goes in .harness/: checkpointed, and out of the produced-files list.
    assert job["config_path"].endswith("/.harness/nanobot/config.json")
    # And the agent's workspace is a directory INSIDE the session rather than the session itself,
    # because nanobot refuses a session store that sits inside the workspace the agent can write
    # ("session storage must be outside the agent workspace"). Measured against the real package:
    # with workspace == the session directory every turn dies before the first model call.
    assert job["workspace"] == str(pathlib.Path(d) / "workspace")
    assert pathlib.Path(job["workspace"]).is_dir()
    sessions = pathlib.Path(job["config_path"]).parent / "sessions"
    assert not sessions.resolve().is_relative_to(pathlib.Path(job["workspace"]).resolve())
    # …and still inside the session directory, which is what the checkpoint tars.
    assert sessions.resolve().is_relative_to(pathlib.Path(d).resolve())
    # The instruction file and the skills follow the workspace, or they are written and never read.
    assert _agent_doc_path(d, "nanobot") == pathlib.Path(d) / "workspace" / "AGENTS.md"


def test_nanobot_config_names_the_key_and_offers_no_fallback_model():
    d, env = _ws(), {}
    _build_nanobot("openai-api", Auth(api_key="sk-secret", base_url=UP), "gpt-5.4", "hi", d, env)
    cfg = json.loads(pathlib.Path(d, ".harness", "nanobot", "config.json").read_text())
    assert cfg["providers"]["custom"]["apiKey"] == "${HR_NANOBOT_RELAY_KEY}"
    assert "sk-secret" not in json.dumps(cfg)
    assert env["HR_NANOBOT_RELAY_KEY"].startswith("hr-relay-")
    assert env["HR_NANOBOT_RELAY_KEY"] != "sk-secret"
    # A fallback model is a substitution, and this product promises the model that was asked for.
    assert cfg["agents"]["defaults"]["fallbackModels"] == []
    # `apiType` is REFUSED on any provider but `openai` and the refusal rejects the WHOLE config,
    # so sending it would kill every turn over a field that was only ever decoration.
    assert "apiType" not in cfg["providers"]["custom"]
    # The config holds the relay placeholder today and must never ride a checkpoint tarball even if
    # a future build stops resolving ${VAR}. The sessions beside it MUST travel, so the exclusion
    # names the file, not the directory.
    assert "./.harness/nanobot/config.json" in CHECKPOINT_EXCLUDE
    assert not any(x.rstrip("/").endswith(".harness/nanobot") for x in CHECKPOINT_EXCLUDE)


def test_nanobot_session_lookup_uses_the_name_nanobot_itself_would_open():
    import base64 as _b64
    d = _ws()
    cmd = _build_nanobot("openai-api", Auth(api_key="k", base_url=UP), "gpt-5.4", "hi", d, {},
                         resume_session_id="hr:one")
    assert _resume_lost("nanobot", cmd, "hr:one", d) == "hr:one"
    ws_dir = pathlib.Path(d, ".harness", "nanobot", "sessions", "deadbeef")
    ws_dir.mkdir(parents=True)
    name = _b64.urlsafe_b64encode(b"hr:one").decode().rstrip("=") + ".jsonl"
    (ws_dir / name).write_text("{}")
    assert _resume_lost("nanobot", cmd, "hr:one", d) is None


def test_nanobot_tool_list_is_the_one_its_loop_registers():
    # 22, read off its own start-up line on 0.3.5. Writing has three doors and shell three, which is
    # why withholding one tool is not withholding a capability.
    assert len(ALL_NANOBOT_TOOLS) == 22
    for n in ("write_file", "edit_file", "apply_patch", "exec", "exec_session", "run_cli_app"):
        assert n in ALL_NANOBOT_TOOLS


# ── the real bytes ─────────────────────────────────────────────────────────────────────────────
# Everything above this line is a hand-written event, and a test written from the implementation
# can only prove the implementation is self-consistent. These replay CAPTURED streams — the actual
# stdout of the pinned binaries on 2026-10-02, against a live provider, trimmed and path-scrubbed
# but otherwise unaltered — through the shipped normaliser.

FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "batch3"


def _replay(fn, name, model, eof=None, rc=0):
    state = {"model": model, "final": "", "cwd": ""}
    evs = []
    for ln in (FIX / name).read_text().splitlines():
        if ln.strip().startswith("{"):
            evs += fn(json.loads(ln), state)
    res = next((e for e in evs if e.get("type") == "result"), None)
    if res is None and eof is not None:
        tail = eof(state, rc)
        evs += tail
        res = next((e for e in tail if e.get("type") == "result"), None)
    return evs, res


def test_real_gajae_turn_that_wrote_a_file():
    evs, res = _replay(_gajae_to_claude, "gajae-write-file.ndjson", "openai/gpt-6-luna")
    assert evs[0]["type"] == "system" and evs[0]["subtype"] == "init"
    assert any(e.get("type") == "assistant" and "tool_use" in json.dumps(e) for e in evs)
    assert any(e.get("type") == "user" and "Successfully wrote" in json.dumps(e) for e in evs)
    assert res["is_error"] is False and res["result"] == "DONE"
    # The served model comes off the CLI's own assistant messages, so rule 2 is answerable here
    # without the relay as well as with it.
    assert res["model"] == "openai/gpt-6-luna"
    assert res["usage"]["input_tokens"] > 0 and res["usage"]["output_tokens"] > 0


def test_real_gajae_turn_that_the_provider_refused():
    evs, res = _replay(_gajae_to_claude, "gajae-provider-401.ndjson", "openai/gpt-6-luna")
    assert res["is_error"] is True
    assert res["result"].startswith("401 Authentication failed")
    # and the failure is NOT rendered as the assistant's answer. Pinned by the event TYPES rather
    # than by "no assistant event": the second form also passes on an empty list, and a normaliser
    # that emitted nothing at all would then look correct here.
    assert [e.get("type") for e in evs] == ["system", "result"]


def test_real_jcode_turn_sums_the_usage_its_own_done_event_under_reports():
    evs, res = _replay(_jcode_to_claude, "jcode-write-file.ndjson", "openai/gpt-6-luna",
                       eof=_jcode_eof)
    assert res["is_error"] is False and res["result"] == "DONE"
    assert any("tool_use" in json.dumps(e) for e in evs)
    assert any("Created probe.txt" in json.dumps(e) for e in evs)
    u = res["usage"]
    # The capture's own `done.usage` says input_tokens 10748; the two `tokens` events say 10609 and
    # 10748, and both are gross. This is the turn, not the last request.
    assert u["cache_read_tokens"] == 21037
    assert u["cache_write_tokens"] == 314
    assert u["output_tokens"] == 68


def test_real_jcode_turn_that_the_provider_refused():
    _evs, res = _replay(_jcode_to_claude, "jcode-provider-401.ndjson", "openai/gpt-6-luna",
                        eof=_jcode_eof, rc=1)
    assert res["is_error"] is True
    assert "401 Unauthorized" in res["result"]
    # The message names the auth variable by NAME and never carries its value.
    assert "OPENAI_COMPAT_API_KEY" in res["result"] and "sk-" not in res["result"]


def test_real_mimo_turn_through_opencodes_normaliser_unchanged():
    from server import _opencode_eof
    evs, res = _replay(_opencode_to_claude, "mimo-first-turn.ndjson", "openai/gpt-6-luna",
                       eof=_opencode_eof)
    assert evs[0]["subtype"] == "init"
    assert res["is_error"] is False and res["result"] == "OK"
    # step-finish's tokens, read by opencode's own accumulator: `input` is already cache-exclusive
    # in this fork as in opencode, and reasoning is added back into output.
    assert res["usage"]["input_tokens"] == 14413
    assert res["usage"]["output_tokens"] == 37


def test_opensquilla_warning_becomes_a_notice_the_gateway_renders_and_repeats_once():
    # Its compaction warning repeats once per retry; three identical notes on one reply is noise,
    # so the de-duplication happens here rather than in the gateway.
    state = {"model": "gpt-5.4", "final": "", "cwd": _ws()}
    w = {"_event": True, "schema_version": 1, "kind": "warning", "code": "***",
         "message": "Provider context limit reached; compacting older context before retrying."}
    first = _opensquilla_to_claude(dict(w), state)
    again = _opensquilla_to_claude(dict(w), state)
    assert len(first) == 1 and first[0]["subtype"] == "notice"
    assert first[0]["text"].startswith("Provider context limit reached")
    assert again == []
    # a DIFFERENT warning is still said
    other = _opensquilla_to_claude({**w, "message": "Search provider is not configured."}, state)
    assert len(other) == 1 and other[0]["subtype"] == "notice"
    # and an empty one is not
    assert _opensquilla_to_claude({**w, "message": ""}, state) == []


def test_opensquilla_channel_routing_directives_are_not_part_of_the_answer():
    # MEASURED on the first live turn through the product: asked to reply with exactly READY, the
    # record said "[[reply_to_current]]\nREADY". The directive is for OpenSquilla's channel
    # adapters; the project strips it in the channel layer and in BOTH of its terminal renderers,
    # but `opensquilla agent --json` strips neither. Left in, every scenario that recalls an exact
    # word fails for a reason that has nothing to do with the model.
    from server import _opensquilla_text
    assert _opensquilla_text("[[reply_to_current]]\nREADY") == "READY"
    assert _opensquilla_text("[reply_to: ops]\nhi there") == "hi there"      # the one-bracket spelling
    assert _opensquilla_text("READY [[reply_to_current]]") == "READY"
    assert _opensquilla_text("READY") == "READY"
    # and nothing else in double brackets is touched
    assert _opensquilla_text("see [[notes]] here") == "see [[notes]] here"


def test_opensquilla_calls_come_back_with_their_arguments_under_the_live_rows_name():
    # The progress stream announces a call with no input; its row read `{}` in the console and the
    # record. The transcript has the arguments, and the end-of-turn replay now sends each call again
    # under the same id and the name the live row was given, so the gateway fills that row in place.
    d = _ws()
    base = pathlib.Path(d, ".harness", "opensquilla"); base.mkdir(parents=True)
    (base / "transcript.jsonl").write_text("\n".join(json.dumps(x) for x in [
        {"type": "message", "message": {"role": "assistant", "content": [
            {"type": "toolCall", "name": "exec", "id": "call_1", "arguments": {"cmd": "echo one"}},
            {"type": "toolCall", "name": "exec", "id": "call_2", "arguments": "{\"cmd\": \"echo two\"}"},
            {"type": "toolCall", "name": "noop", "id": "call_3", "arguments": {}}]}},
        {"type": "message", "message": {"role": "toolResult", "toolCallId": "call_1", "isError": False,
                                        "content": [{"type": "text", "text": "one"}]}},
        {"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": "DONE"}]}},
    ]))
    evs, state = _norm(_opensquilla_to_claude, [
        {"_event": True, "schema_version": 1, "kind": "tool_use_start", "tool_use_id": "call_1", "tool_name": "exec_command"},
        {"_event": True, "schema_version": 1, "kind": "tool_use_start", "tool_use_id": "call_2", "tool_name": "exec_command"},
    ], cwd=d)
    live = [b for e in evs for b in e["message"]["content"] if b.get("type") == "tool_use"]
    assert [(u["id"], u["input"]) for u in live] == [("call_1", {}), ("call_2", {})]
    late = [b for e in _opensquilla_transcript(state) if e.get("type") == "assistant"
            for b in e["message"]["content"] if b.get("type") == "tool_use"]
    # each call once more, WITH its arguments (a JSON string parsed), named as the live row was; a
    # call with no arguments is not sent again (there is nothing to fill)
    assert [(u["id"], u["name"], u["input"]) for u in late] == [
        ("call_1", "exec_command", {"cmd": "echo one"}), ("call_2", "exec_command", {"cmd": "echo two"})]


def test_the_relay_assembles_a_tool_calls_arguments_from_the_models_stream():
    from server import _relay_tool_args, _tool_args_in_body, _tool_args_in_sse_line
    flags, st = {}, {}
    for piece in ({"index": 0, "id": "call_a", "function": {"name": "exec_command", "arguments": ""}},
                  {"index": 0, "function": {"arguments": "{\"cmd\": \"echo "}},
                  {"index": 0, "function": {"arguments": "one\"}"}},
                  {"index": 1, "id": "call_b", "function": {"name": "read", "arguments": "{\"path\": \"a\"}"}}):
        line = b"data: " + json.dumps({"choices": [{"index": 0, "delta": {"tool_calls": [piece]}}]}).encode()
        _tool_args_in_sse_line(line, flags, st)
    assert _relay_tool_args([flags], "call_a") == {"cmd": "echo one"}
    assert _relay_tool_args([flags], "call_b") == {"path": "a"}
    # Anthropic Messages: a tool_use block and its input_json_delta pieces
    fa, sa = {}, {}
    for ev in ({"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "toolu_1", "name": "bash", "input": {}}},
               {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": "{\"command\": "}},
               {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": "\"ls\"}"}}):
        _tool_args_in_sse_line(b"data: " + json.dumps(ev).encode(), fa, sa)
    assert _relay_tool_args([fa], "toolu_1") == {"command": "ls"}
    # a whole response, both shapes
    fb = {}
    _tool_args_in_body(json.dumps({"choices": [{"message": {"tool_calls": [
        {"id": "call_c", "function": {"name": "x", "arguments": "{\"k\": 1}"}}]}}]}).encode(), fb)
    _tool_args_in_body(json.dumps({"content": [{"type": "tool_use", "id": "toolu_2", "name": "y", "input": {"q": "z"}}]}).encode(), fb)
    assert _relay_tool_args([fb], "call_c") == {"k": 1} and _relay_tool_args([fb], "toolu_2") == {"q": "z"}
    # nothing seen, or not yet a whole object: no arguments rather than a wrong one
    assert _relay_tool_args([flags], "call_zzz") is None and _relay_tool_args(None, "call_a") is None
    _tool_args_note_half = {"tool_args": {"call_h": "{\"cmd\": \"ec"}}
    assert _relay_tool_args([_tool_args_note_half], "call_h") is None


def test_opensquilla_rows_have_their_arguments_while_the_turn_runs():
    # The live fix: the relay saw the model send call_1's arguments before opensquilla ran the tool,
    # so the row the progress event opens carries them, and the transcript does not add a second.
    d = _ws()
    base = pathlib.Path(d, ".harness", "opensquilla"); base.mkdir(parents=True)
    (base / "transcript.jsonl").write_text(json.dumps({"type": "message", "message": {"role": "assistant", "content": [
        {"type": "toolCall", "name": "exec", "id": "call_1", "arguments": {"cmd": "echo one"}}]}}))
    route = {"tool_args": {"call_1": "{\"cmd\": \"echo one\"}"}}
    state = {"model": "gpt-5.4", "final": "", "cwd": d, "routes": [route]}
    evs = _opensquilla_to_claude({"_event": True, "schema_version": 1, "kind": "tool_use_start",
                                  "tool_use_id": "call_1", "tool_name": "exec_command"}, state)
    assert evs[0]["message"]["content"][0]["input"] == {"cmd": "echo one"}
    late = [b for e in _opensquilla_transcript(state) if e.get("type") == "assistant"
            for b in e["message"]["content"] if b.get("type") == "tool_use"]
    assert late == []


def test_opensquilla_replays_only_this_turn_of_a_resumed_sessions_transcript():
    # A resumed session's transcript holds the whole conversation; replaying it all put the first
    # turn's answer in front of the sixth's and every earlier call into its trace (2026-10-13).
    d = _ws()
    base = pathlib.Path(d, ".harness", "opensquilla"); base.mkdir(parents=True)
    msgs = [
        {"role": "user", "content": [{"type": "text", "text": "[2026-10-13T04:51+00:00 Tue UTC]\nfollow instruction: hello"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "Hello! How can I help you today?"}]},
        {"role": "user", "content": [{"type": "text", "text": "[2026-10-13T04:53+00:00 Tue UTC]\nmake a pdf"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "Writing it."},
                                          {"type": "toolCall", "name": "write_file", "id": "call_old", "arguments": {"path": "a.pdf"}}]},
        {"role": "toolResult", "toolCallId": "call_old", "content": [{"type": "text", "text": "Written"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "Made a.pdf"}]},
        {"role": "user", "content": [{"type": "text", "text": "[2026-10-13T07:30+00:00 Tue UTC]\nchange to red"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "Recolouring."},
                                          {"type": "toolCall", "name": "edit_file", "id": "call_new", "arguments": {"color": "red"}}]},
        {"role": "toolResult", "toolCallId": "call_new", "content": [{"type": "text", "text": "Edited"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "It is red now."}]},
    ]
    (base / "transcript.jsonl").write_text("\n".join(json.dumps({"type": "message", "message": m}) for m in msgs))
    (base / "turn_prompt.txt").write_text("change to red")
    state = {"model": "gpt-5.4", "final": "", "cwd": d}
    evs = _opensquilla_transcript(state)
    blob = json.dumps(evs)
    assert "Hello! How can I help" not in blob and "Made a.pdf" not in blob and "call_old" not in blob
    assert "Recolouring." in blob and "call_new" in blob and "Edited" in blob
    assert state["final"] == "It is red now."
    # the prompt not on record (a turn built before this): after the last user message, the same turn
    (base / "turn_prompt.txt").unlink()
    state = {"model": "gpt-5.4", "final": "", "cwd": d}
    assert "Made a.pdf" not in json.dumps(_opensquilla_transcript(state)) and state["final"] == "It is red now."


def test_opensquilla_transcript_answer_has_the_directive_removed():
    d = _ws()
    base = pathlib.Path(d, ".harness", "opensquilla"); base.mkdir(parents=True)
    (base / "transcript.jsonl").write_text(json.dumps(
        {"type": "message", "message": {"role": "assistant",
                                        "content": [{"type": "text", "text": "[[reply_to_current]]\nDONE"}]}}))
    state = {"model": "gpt-5.4", "final": "", "cwd": d}
    evs = _opensquilla_transcript(state)
    assert state["final"] == "DONE"
    assert "reply_to_current" not in json.dumps(evs)


def test_mimo_keeps_an_aggregators_claude_id_on_the_relay_so_rule_2_stays_answerable():
    # MEASURED WITH A CONTROL on the Vercel column (2026-10-06): mimo's claude-haiku-4.5 pair came
    # back unlabelled=4 — no served model on any of its four turns — while its seven other models
    # were labelled, and jcode's claude pair, which already keeps aggregator claude on
    # chat/completions, recorded anthropic/claude-haiku-4.5. Five scenarios "passed" on a rule with
    # no input. A Messages turn cannot ride the relay, and mimo names no served model itself.
    from server import _mimo_npm, _opencode_npm
    a = Auth(api_key="k", base_url=UP)
    # opencode's own choice is deliberately left alone; mimo's differs exactly here
    assert _opencode_npm(a, "claude-haiku-4.5", "tokenrouter") == "@ai-sdk/anthropic"
    assert _mimo_npm(a, "claude-haiku-4.5", "tokenrouter") == "@ai-sdk/openai-compatible"
    # a connection that IS Anthropic still speaks Messages, through the relay like every keyed turn
    assert _mimo_npm(a, "claude-haiku-4.5", "anthropic") == "@ai-sdk/anthropic"
    # and nothing else moved
    assert _mimo_npm(a, "gpt-5.4", "tokenrouter") == "@ai-sdk/openai"
    assert _mimo_npm(a, "deepseek-v4-flash", "tokenrouter") == "@ai-sdk/openai-compatible"

    # end to end: the claude row now rides the relay with a placeholder, which is what
    # _relay_served_model reads the served model off
    d, env = _ws(), {}
    _build_mimo("tokenrouter", Auth(api_key="sk-secret", base_url=UP), "claude-haiku-4.5", "hi", d, env)
    cfg = json.loads((pathlib.Path(d) / ".harness" / "mimo.json").read_text())
    assert cfg["provider"]["hr"]["npm"] == "@ai-sdk/openai-compatible"
    assert cfg["provider"]["hr"]["options"]["baseURL"].startswith("http://127.0.0.1:")
    assert env["HR_MIMO_KEY"].startswith("hr-relay-")


def test_nanobot_hides_its_own_machinery_from_the_produced_files_list():
    # MEASURED on the Vercel column (2026-10-06): without this, a turn that wrote NOTHING handed the
    # user 25 files — the three built-in skill bundles, the instruction file and nanobot's own
    # workspace id — and all eight nanobot pairs FAILED their first scenario, because the file cards
    # pushed the answer out of the transcript the judge reads. Re-measured after the fix: 0 files.
    d, env = _ws(), {}
    _build_nanobot("openai-api", Auth(api_key="k", base_url=UP), "gpt-5.4", "hi", d, env)
    ex = pathlib.Path(d, ".git", "info", "exclude")
    assert ex.is_file(), "/produced is git status, so git's own exclude is the door"
    lines = {l.strip() for l in ex.read_text().splitlines() if l.strip() and not l.startswith("#")}
    assert {"workspace/.nanobot/", "workspace/skills/", "workspace/memory/",
            "workspace/AGENTS.md"} <= lines
    # NOT a .gitignore: this is not a file in the agent's workspace, so the agent cannot read or
    # edit it and it is never itself a produced file; and _git_ensure rewrites only the root
    # .gitignore, so this survives every turn.
    assert not (pathlib.Path(d) / "workspace" / ".gitignore").exists()


def test_opensquilla_hides_the_files_it_seeds_into_every_workspace():
    # `ensure_agent_workspace` writes SOUL.md, IDENTITY.md, USER.md and MEMORY.md into the agent's
    # workspace unconditionally — its `seed_templates` flag has no caller that passes False and no
    # setting reads it, so there is nothing to turn off. Measured: a turn that wrote nothing handed
    # those four back, and the stale cards then failed rule 3 on the artifact scenario for all
    # eight models (five cards against a record of one).
    d, env = _ws(), {}
    _build_opensquilla("openai-api", Auth(api_key="k", base_url=UP), "gpt-5.4", "hi", d, env)
    lines = {l.strip() for l in pathlib.Path(d, ".git", "info", "exclude").read_text().splitlines()
             if l.strip() and not l.startswith("#")}
    assert {"SOUL.md", "IDENTITY.md", "USER.md", "MEMORY.md", "memory/"} <= lines


def test_opensquilla_memory_source_is_state_and_the_comment_says_what_it_actually_does():
    # It keeps the memory the agent ACCUMULATES out of the collected workspace (memory_tools.py
    # branches on exactly this value). It does NOT stop the bootstrap seeds — an earlier version of
    # this change claimed it did, and the column showed otherwise.
    d, env = _ws(), {}
    _build_opensquilla("openai-api", Auth(api_key="k", base_url=UP), "gpt-5.4", "hi", d, env)
    cfg = pathlib.Path(d, ".harness", "opensquilla", "config.toml").read_text()
    assert 'source = "state"' in cfg
    assert "does NOT stop the four bootstrap seeds" in cfg
    assert env["OPENSQUILLA_STATE_DIR"].endswith("/.harness/opensquilla")


# ── nanobot's nested workspace must not reach the user ───────────────────────────────────
# Found by running the product, not by reading it: a file written through
# PUT /v1/sessions/{sid}/files landed at the session root and the agent answered "there is no
# secret.txt in the working directory", while the same test on a flat-layout base read it back.
# The session's file root and the agent's cwd are two different directories for this one base.

def _nano(d, prompt="hi"):
    _build_nanobot("openai-api", Auth(api_key="k", base_url=UP), "gpt-5.4", prompt, d, {})


def test_the_visible_root_is_the_session_dir_for_a_flat_base():
    d, env = _ws(), {}
    _build_mimo("openai-api", Auth(api_key="k", base_url=UP), "gpt-5.4", "hi", d, env)
    assert _visible_root(d) == d
    assert {f["path"] for f in _produced_visible(d)} == {f["path"] for f in
                                                        __import__("server")._produced_list(d)}


def test_the_visible_root_is_the_agent_workspace_for_nanobot():
    d = _ws()
    _nano(d)
    assert _visible_root(d) == str(pathlib.Path(d, "workspace"))


def test_a_file_the_user_wrote_before_the_first_turn_reaches_the_agent():
    # the PUT route and attachments both land at the session root; they run before any backend is
    # built, so they cannot know a base nests. The turn adopts them.
    d = _ws()
    pathlib.Path(d, "deck.json").write_text('{"slides": 1}')
    _write_input_files(d, [{"filename": "notes.txt", "content_b64": "aGVsbG8="}])
    _nano(d)
    assert pathlib.Path(d, "workspace", "deck.json").read_text() == '{"slides": 1}'
    assert pathlib.Path(d, "workspace", "notes.txt").read_bytes() == b"hello"
    assert not pathlib.Path(d, "deck.json").exists()


def test_adoption_leaves_the_runners_own_entries_at_the_root():
    d = _ws()
    _nano(d)                                 # makes .harness/nanobot and workspace/
    pathlib.Path(d, "tmp").mkdir(exist_ok=True)
    _nano(d)
    for name in (".harness", "tmp", ".git", "workspace"):
        assert pathlib.Path(d, name).exists(), name
        assert not pathlib.Path(d, "workspace", name).exists(), name


def test_adoption_never_overwrites_what_the_agent_already_has():
    d = _ws()
    _nano(d)
    pathlib.Path(d, "workspace", "report.md").write_text("the agent's")
    pathlib.Path(d, "report.md").write_text("the uploader's")
    _nano(d)
    assert pathlib.Path(d, "workspace", "report.md").read_text() == "the agent's"


def test_a_produced_file_is_named_the_way_the_agent_named_it():
    # a card reading "workspace/report.md" names a directory the user never typed and no other base
    # shows. The prefix comes off where the cards and their download both resolve.
    d = _ws()
    _nano(d)
    pathlib.Path(d, "workspace", "report.md").write_text("done")
    import server
    assert {f["path"] for f in server._produced_list(d)} == {"workspace/report.md"}, (
        "the raw shape: git runs on the session dir")
    assert {f["path"] for f in _produced_visible(d)} == {"report.md"}


# ── nanobot's MCP config ────────────────────────────────────────────────────────────────
# Found by the custom-harness dimension on 2026-10-07, and it could not have been found anywhere
# else: nothing exercised this function's OUTPUT against nanobot's own schema, and the five routing
# scenarios never attach a server. Every turn on a harness carrying ANY MCP server died before the
# first model call — including the turn that was only supposed to report a build stamp, because the
# config is invalid as a whole.

def _nano_cfg(servers):
    d, env = _ws(), {}
    _build_nanobot("openai-api", Auth(api_key="k", base_url=UP), "gpt-5.4", "hi", d, env,
                   mcp_servers=servers)
    return json.loads(pathlib.Path(d, ".harness", "nanobot", "config.json").read_text())


# nanobot.config.Config's top level, read off the installed package (0.3.5), with extra="forbid":
# anything else is "Unknown setting." and the whole config is rejected.
NANOBOT_TOP = {"agents", "api", "channels", "gateway", "model_presets", "providers", "tools",
               "transcription"}


def test_the_config_uses_only_keys_nanobots_own_schema_declares():
    cfg = _nano_cfg([{"name": "deepwiki", "url": "https://mcp.deepwiki.com/mcp"}])
    assert set(cfg) <= NANOBOT_TOP, f"extra='forbid' rejects the whole file: {set(cfg) - NANOBOT_TOP}"
    assert "mcp" not in cfg, "this was the defect: a top-level mcp key, which nanobot forbids"


def test_a_remote_server_lands_at_tools_mcpServers_with_no_type():
    # the transport is nanobot's own inference: a url path ending in /sse is sse, anything else
    # streamable HTTP (agent/tools/mcp.py), which is why nanobot is in neither half of
    # _BRIDGED_TRANSPORTS and why no type is sent.
    cfg = _nano_cfg([{"name": "deepwiki", "url": "https://mcp.deepwiki.com/mcp"}])
    sv = cfg["tools"]["mcpServers"]["deepwiki"]
    assert sv == {"url": "https://mcp.deepwiki.com/mcp"}


def test_a_stdio_server_keeps_command_args_env():
    cfg = _nano_cfg([{"name": "probe", "command": ["python3", "-u", "s.py"], "args": ["--x"],
                      "env": {"K": "v"}}])
    assert cfg["tools"]["mcpServers"]["probe"] == {
        "command": "python3", "args": ["-u", "s.py", "--x"], "env": {"K": "v"}}


def test_no_servers_means_no_tools_section_at_all():
    cfg = _nano_cfg([])
    assert "tools" not in cfg and "mcp" not in cfg


# ── jcode: the model a resumed turn asked for ───────────────────────────────────────────
# jcode's --model and --provider are its session's INITIAL ones, and `jcode run` has no model flag,
# so on --resume the stored model wins and the person's pick is ignored in silence. MEASURED with a
# control in the same run: two turns in one session, haiku then gemini — jcode served haiku twice,
# mimo served each as asked. The family tour served all TWELVE of jcode's families with
# openai/gpt-5.4; the five-scenario column held the same evidence (one `served` entry per pair where
# mimo had two) and passed it, because its switch target is the subset's first id.

def _jcode_store(d, env, sid, model, provider="openai-compatible"):
    # the runner points HOME inside the checkpointed workspace before the builder runs, and that is
    # where jcode keeps its sessions; the builder itself does not set it.
    env.setdefault("HOME", str(pathlib.Path(d, ".harness", "home")))
    home = pathlib.Path(env["HOME"], ".jcode", "sessions")
    home.mkdir(parents=True, exist_ok=True)
    f = home / f"{sid}.json"
    f.write_text(json.dumps({"id": sid, "model": model, "provider_key": provider,
                             "messages": [{"role": "user", "content": "hi"}]}))
    return f


def test_resuming_points_the_store_at_the_model_this_turn_asked_for():
    d, env = _ws(), {}
    _build_jcode("openai-api", Auth(api_key="k", base_url=UP), "gpt-5.4", "hi", d, env)
    f = _jcode_store(d, env, "sess-1", "anthropic/claude-haiku-4.5")
    argv = _build_jcode("openai-api", Auth(api_key="k", base_url=UP),
                        "google/gemini-3.6-flash", "next", d, env, resume_session_id="sess-1")
    assert "--resume" in argv and argv[argv.index("--resume") + 1] == "sess-1"
    doc = json.loads(f.read_text())
    assert doc["model"] == "google/gemini-3.6-flash"
    # the conversation is jcode's to keep; the provider key follows this turn's provider
    assert doc["provider_key"] == "openai-compatible" and doc["messages"]


def test_a_switch_between_connection_kinds_carries_the_provider_key_with_the_model():
    """jcode joins the stored provider key onto the model when it restores a session: after a turn
    on the Messages path (`claude-api`) an OpenAI-compatible turn asked for
    `claude-api:openai/gpt-6.1-sol` and got a 404 (the column's switch row, 2026-10-12)."""
    d, env = _ws(), {}
    _build_jcode("openai-api", Auth(api_key="k", base_url=UP), "gpt-5.4", "hi", d, env)
    f = _jcode_store(d, env, "sess-5", "claude-haiku-4-5-20251001")
    doc = json.loads(f.read_text()); doc["provider_key"] = "claude-api"; f.write_text(json.dumps(doc))
    _build_jcode("openai-api", Auth(api_key="k", base_url=UP), "openai/gpt-6.1-sol", "next", d, env,
                 resume_session_id="sess-5")
    doc = json.loads(f.read_text())
    assert (doc["provider_key"], doc["model"]) == ("openai-compatible", "openai/gpt-6.1-sol")
    # and back: an Anthropic connection's turn on a session an OpenAI-compatible turn wrote
    _build_jcode("anthropic", Auth(api_key="k", base_url="https://api.anthropic.com/v1"),
                 "claude-haiku-4-5-20251001", "again", d, env, resume_session_id="sess-5")
    doc = json.loads(f.read_text())
    assert (doc["provider_key"], doc["model"]) == ("claude-api", "claude-haiku-4-5-20251001")


def test_a_turn_on_the_same_model_leaves_the_store_untouched():
    d, env = _ws(), {}
    _build_jcode("openai-api", Auth(api_key="k", base_url=UP), "gpt-5.4", "hi", d, env)
    f = _jcode_store(d, env, "sess-2", "openai/gpt-5.4")
    before = f.read_text()
    _build_jcode("openai-api", Auth(api_key="k", base_url=UP), "openai/gpt-5.4", "next", d, env,
                 resume_session_id="sess-2")
    assert f.read_text() == before


def test_a_store_that_is_not_there_or_not_json_does_not_fail_the_turn():
    d, env = _ws(), {}
    _build_jcode("openai-api", Auth(api_key="k", base_url=UP), "gpt-5.4", "hi", d, env)
    # no file at all: _jcode_has_session already declines to resume, and this must not raise either
    assert _jcode_session_model(env, "missing", "gpt-5.4") == ""
    f = _jcode_store(d, env, "sess-3", "openai/gpt-5.4")
    f.write_text("{not json")
    assert _jcode_session_model(env, "sess-3", "google/gemini-3.6-flash") == ""
    assert f.read_text() == "{not json", "a store it cannot parse is left exactly as it was"


def test_no_model_asked_for_means_no_rewrite():
    d, env = _ws(), {}
    _build_jcode("openai-api", Auth(api_key="k", base_url=UP), "gpt-5.4", "hi", d, env)
    f = _jcode_store(d, env, "sess-4", "openai/gpt-5.4")
    assert _jcode_session_model(env, "sess-4", "") == ""
    assert json.loads(f.read_text())["model"] == "openai/gpt-5.4"


# ── nanobot refuses a loopback MCP url, and the product injects one ──────────────────────
# Found by the browser column (2026-10-10): the `plugs` server is how EVERY base gets the browser
# tools and it is injected at http://127.0.0.1:8080/v1/mcp/plugs. nanobot was the one base of four
# that made no browser call at all, twice, and said it had no browser toolset — while its config
# held the server correctly. Its MCP client runs `validate_url_target` over every url and drops a
# loopback one with a log line of its own, so nothing reaches the turn record as a refusal.

def test_a_loopback_server_is_bridged_for_nanobot():
    d = _ws()
    out = _sse_bridges(d, [{"name": "plugs", "url": "http://127.0.0.1:8080/v1/mcp/plugs",
                            "headers": {"Authorization": "Bearer t"}}], "nanobot")
    assert out[0].get("command"), "it has to arrive as a stdio command, with no url to validate"
    assert "url" not in out[0] and "headers" not in out[0]
    launcher = pathlib.Path(out[0]["command"]).read_text()
    assert "HR_MCP_URL" in launcher and "127.0.0.1:8080" in launcher
    assert "Bearer t" not in pathlib.Path(out[0]["command"]).name, "never on the command line"


def test_a_public_server_still_goes_to_nanobots_own_client():
    # measured in both the custom-harness and the plugin columns: its remote client handles a public
    # streamable-HTTP and SSE server, so bridging those would add a hop for nothing.
    d = _ws()
    out = _sse_bridges(d, [{"name": "deepwiki", "url": "https://mcp.deepwiki.com/mcp"}], "nanobot")
    assert out[0].get("url") == "https://mcp.deepwiki.com/mcp" and "command" not in out[0]


def test_which_hosts_count_as_loopback():
    for u in ("http://127.0.0.1:8080/x", "http://localhost:3000/x", "http://[::1]:9/x",
              "http://10.1.2.3/x", "http://192.168.0.5/x", "http://172.16.4.4/x",
              "http://169.254.169.254/latest", "http://api.localhost/x"):
        assert _mcp_url_is_loopback(u), u
    for u in ("https://mcp.deepwiki.com/mcp", "https://example.com/x", "http://172.32.0.1/x",
              "http://1.2.3.4/x"):
        assert not _mcp_url_is_loopback(u), u


def test_a_flat_base_is_untouched_by_this_rule():
    # the rule is nanobot's; mimo reaches a loopback server itself and must keep doing so
    d = _ws()
    out = _sse_bridges(d, [{"name": "plugs", "url": "http://127.0.0.1:8080/v1/mcp/plugs"}], "mimo")
    assert out[0].get("url") == "http://127.0.0.1:8080/v1/mcp/plugs"


# ── nanobot's shell does not inherit the environment layer ───────────────────────────────
# Its own `_build_env` says so: "Build a minimal environment for subprocess execution. On Unix, only
# HOME/LANG/TERM are passed by default." MEASURED by the environments column (2026-10-10): three of
# four bases used the layer's pip, npm and apt packages without installing anything and nanobot
# failed all three with ModuleNotFoundError. The layer reached the driver process and stopped there.

LAYER = {"HR_ENVIRONMENT": "/env/x", "PROJECT_ROOT": "/env/x", "PYTHONPATH": "/env/x",
         "VIRTUAL_ENV": "/env/x/.venv", "NODE_PATH": "/env/x/node_modules",
         "LD_LIBRARY_PATH": "/env/x/apt/usr/lib",
         "PATH": "/env/x/.venv/bin:/env/x/node_modules/.bin:/env/x/apt/usr/bin:/usr/bin:/bin"}


def test_the_layers_variables_and_path_are_handed_to_the_exec_tool():
    d, env = _ws(), dict(LAYER)
    _build_nanobot("openai-api", Auth(api_key="k", base_url=UP), "gpt-5.4", "hi", d, env)
    ex = json.loads(pathlib.Path(d, ".harness", "nanobot", "config.json").read_text())["tools"]["exec"]
    assert set(ex["allowedEnvKeys"]) == set(LAYER) - {"PATH"}
    # only the layer's own PATH entries, and in the order the turn had them
    assert ex["pathPrepend"] == "/env/x/.venv/bin:/env/x/node_modules/.bin:/env/x/apt/usr/bin"
    # by ENTRY, not by substring: /env/x/apt/usr/bin legitimately contains "/usr/bin", and the
    # first version of this assertion failed the implementation for that
    assert all(e.startswith("/env/x/") for e in ex["pathPrepend"].split(":")), \
        "the image's own PATH entries are nanobot's to decide"


def test_no_environment_means_no_exec_section():
    d, env = _ws(), {"PATH": "/usr/bin:/bin"}
    _build_nanobot("openai-api", Auth(api_key="k", base_url=UP), "gpt-5.4", "hi", d, env)
    cfg = json.loads(pathlib.Path(d, ".harness", "nanobot", "config.json").read_text())
    assert "exec" not in (cfg.get("tools") or {})


def test_the_exec_section_and_the_mcp_servers_share_the_one_tools_block():
    d, env = _ws(), dict(LAYER)
    _build_nanobot("openai-api", Auth(api_key="k", base_url=UP), "gpt-5.4", "hi", d, env,
                   mcp_servers=[{"name": "deepwiki", "url": "https://mcp.deepwiki.com/mcp"}])
    t = json.loads(pathlib.Path(d, ".harness", "nanobot", "config.json").read_text())["tools"]
    assert set(t) == {"mcpServers", "exec"}, "one tools block, or the second overwrites the first"


def test_a_layer_with_only_some_of_the_variables_passes_only_those():
    d, env = _ws(), {"HR_ENVIRONMENT": "/env/y", "PROJECT_ROOT": "/env/y",
                     "PATH": "/env/y/.venv/bin:/usr/bin"}
    _build_nanobot("openai-api", Auth(api_key="k", base_url=UP), "gpt-5.4", "hi", d, env)
    ex = json.loads(pathlib.Path(d, ".harness", "nanobot", "config.json").read_text())["tools"]["exec"]
    assert set(ex["allowedEnvKeys"]) == {"HR_ENVIRONMENT", "PROJECT_ROOT"}
    assert ex["pathPrepend"] == "/env/y/.venv/bin"


@pytest.mark.parametrize("build", ["_build_mimo", "_build_jcode", "_build_opensquilla", "_build_nanobot"])
def test_the_provider_key_never_reaches_the_cli_whatever_the_connection_shape(build):
    """The CLI's environment is the agent's shell's, and its config files ride the workspace
    checkpoint: the real key belongs in neither, on any connection a base is offered. A direct
    Anthropic connection and a custom endpoint left the relay on jcode, opensquilla and mimo (and a
    custom endpoint on nanobot) and handed the CLI the key itself; the relay reads its placeholder
    from a bearer or x-api-key and sends the provider the key the way it takes it."""
    import server
    key = "sk-real-provider-secret-0123456789"
    shapes = [("openai-api", Auth(api_key=key, base_url=UP)),
              ("anthropic", Auth(api_key=key, base_url="https://api.anthropic.com/v1")),
              ("openai-api", Auth(api_key=key, base_url=UP, api_format="openai"))]
    if build == "_build_mimo":
        shapes.append(("openai-api", Auth(api_key=key, base_url="https://proxy.example/v1", api_format="anthropic")))
    for provider, auth in shapes:
        d, env = _ws(), {}
        cmd = getattr(server, build)(provider, auth, "claude-haiku-4.5", "hi", d, env)
        assert key not in json.dumps(env), (build, provider, auth.api_format, "environment")
        assert key not in json.dumps(cmd or []), (build, provider, auth.api_format, "argv")
        for f in pathlib.Path(d).rglob("*"):
            if f.is_file():
                assert key.encode() not in f.read_bytes(), (build, provider, auth.api_format, str(f))
        assert any(str(v).startswith("hr-relay-") for v in env.values()), (build, provider, "no relay placeholder")


def test_jcode_runs_on_an_anthropic_connection_only_a_model_its_catalog_lists(monkeypatch):
    """jcode's Anthropic provider replaces any id its catalog does not list with claude-opus-5-5 and
    says so only in its own log: a claude-haiku-4.5 turn whose wire id was the dated
    claude-haiku-4-5-20251001 was answered and billed by Opus (2026-10-12)."""
    import server
    monkeypatch.setattr(server, "_JCODE_ANTHROPIC_LISTED", ["claude-opus-5-5", "claude-sonnet-4-6", "claude-haiku-4-5"])
    a = Auth(api_key="k", base_url="https://api.anthropic.com/v1")
    # the dated id is the same model under jcode's undated name
    argv = _build_jcode("anthropic", a, "claude-haiku-4-5-20251001", "hi", _ws(), {})
    assert argv[argv.index("--model") + 1] == "claude-haiku-4-5"
    argv = _build_jcode("anthropic", a, "claude-sonnet-4-6", "hi", _ws(), {})
    assert argv[argv.index("--model") + 1] == "claude-sonnet-4-6"
    # an id it does not list is refused, never answered by Opus
    with pytest.raises(server.HTTPException) as e:
        _build_jcode("anthropic", a, "claude-sonnet-5-5", "hi", _ws(), {})
    assert "claude-sonnet-5-5" in e.value.detail and "claude-opus-5-5" in e.value.detail
    # an OpenAI-compatible connection takes any id, as before
    argv = _build_jcode("openai-api", Auth(api_key="k", base_url=UP), "anthropic/claude-sonnet-5.5", "hi", _ws(), {})
    assert argv[argv.index("--model") + 1] == "anthropic/claude-sonnet-5.5"


def test_opensquillas_route_asks_openai_for_a_stream_without_padding():
    """OpenAI and Azure pad every streamed chunk with `obfuscation`, the usage trailer included, and
    opensquilla 0.5.6 fails a turn that has already answered on a trailer key it does not know."""
    import server
    from server import _without_stream_obfuscation
    asked = json.dumps({"model": "gpt-5.4-mini", "stream": True, "stream_options": {"include_usage": True}}).encode()
    for base in ("https://api.openai.com/v1", "https://agentstudio-oai-e2.openai.azure.com/openai/v1"):
        out = json.loads(_without_stream_obfuscation(asked, base))
        assert out["stream_options"] == {"include_usage": True, "include_obfuscation": False}, base
    # an aggregator's stream, a body that does not stream, and one that already chose are left alone
    assert _without_stream_obfuscation(asked, "https://ai-gateway.vercel.sh/v1") == asked
    still = json.dumps({"model": "m", "stream": False}).encode()
    assert _without_stream_obfuscation(still, "https://api.openai.com/v1") == still
    chose = json.dumps({"stream": True, "stream_options": {"include_obfuscation": True}}).encode()
    assert _without_stream_obfuscation(chose, "https://api.openai.com/v1") == chose
    # only opensquilla's route asks for it
    d, env = _ws(), {}
    _build_opensquilla("openai-api", Auth(api_key="k", base_url="https://api.openai.com/v1"), "gpt-5.4-mini", "hi", d, env)
    tok = next(v for v in env.values() if str(v).startswith("hr-relay-"))
    assert server._HERMES_RELAY["routes"][tok][2]["plain_stream"] is True
    d2, env2 = _ws(), {}
    _build_jcode("openai-api", Auth(api_key="k", base_url="https://api.openai.com/v1"), "gpt-5.4-mini", "hi", d2, env2)
    tok2 = next(v for v in env2.values() if str(v).startswith("hr-relay-"))
    assert not server._HERMES_RELAY["routes"][tok2][2].get("plain_stream")


def test_after_a_finished_choice_opensquilla_reads_only_a_bare_usage_chunk():
    """Every provider ends a stream its own way, and opensquilla 0.5.6 fails a turn that has already
    answered on anything after a finished choice but a bare usage chunk (2026-10-12)."""
    from server import _plain_trailer_line, _rewrite_stream_line
    def run(lines, flags={"plain_stream": True}):
        st = {}
        return [_rewrite_stream_line(ln, flags, st) for ln in lines]
    answer = b'data: {"id":"c","choices":[{"index":0,"delta":{"content":"OK"},"finish_reason":null}]}'
    finish = b'data: {"id":"c","choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"usage":null}'
    usage = '"usage":{"prompt_tokens":9,"completion_tokens":2,"total_tokens":11}'
    trailers = {
        "openai": f'data: {{"id":"c","object":"chat.completion.chunk","choices":[],"obfuscation":"xyz",{usage}}}'.encode(),
        "azure": f'data: {{"choices":[],"id":"c","latency_checkpoint":{{"t":1}},"routing":{{"r":"x"}},{usage}}}'.encode(),
        "openrouter": f'data: {{"id":"c","provider":"Fireworks","choices":[{{"index":0,"delta":{{"content":"","role":"assistant"}},"finish_reason":null}}],{usage}}}'.encode(),
    }
    for name, trailer in trailers.items():
        out = run([answer, finish, trailer, b"data: [DONE]"])
        assert out[0] == answer and out[1] == finish and out[3] == b"data: [DONE]", name
        got = json.loads(out[2][5:])
        assert got["choices"] == [] and got["usage"]["total_tokens"] == 11, name
        assert set(got) <= {"id", "object", "created", "model", "system_fingerprint", "service_tier", "usage", "choices"}, name
    # a post-finish chunk with no usage at all is dropped; before the finish nothing changes
    assert run([finish, b'data: {"id":"c","choices":[{"index":0,"delta":{}}]}'])[1] == b""
    assert run([answer, b'data: {"choices":[],"prompt_filter_results":[]}'])[1] == b'data: {"choices":[],"prompt_filter_results":[]}'
    # another route's stream is untouched
    assert run([finish, trailers["openai"]], flags={})[1] == trailers["openai"]
    assert _plain_trailer_line(b": keep-alive", {"finished": True}) == b": keep-alive"


def test_a_field_anthropic_calls_deprecated_for_the_model_is_one_the_relay_drops():
    """nanobot sends temperature, and claude-sonnet-5.5 on Anthropic's OpenAI-compatible surface
    refused every turn: "`temperature` is deprecated for this model." (2026-10-12)."""
    from server import _refused_top_level_field
    body = b'{"type":"error","error":{"type":"invalid_request_error","message":"`temperature` is deprecated for this model."}}'
    assert _refused_top_level_field(body) == "temperature"
    assert _refused_top_level_field(b'{"error":{"message":"Invalid JSON payload received. Unknown name \\"store\\": Cannot find field."}}') == "store"
    assert _refused_top_level_field(b'{"error":{"message":"max_tokens: must be positive"}}') == ""


def test_nanobots_shell_gets_the_harnesss_own_variables_by_name():
    """Every other base's shell inherits the harness's variables; nanobot's passes only what it is
    named. The custom-harness dimension's script ran without its STAMP_NONCE (2026-10-12)."""
    d, env = _ws(), {"STAMP_NONCE": "n-123", "HR_API_URL": "http://127.0.0.1:8080"}
    _build_nanobot("openai-api", Auth(api_key="k", base_url=UP), "gpt-5.4", "hi", d, env,
                   caller_keys=["STAMP_NONCE", "HR_API_URL", "NOT_SET"])
    cfg_path = pathlib.Path(d, ".harness", "nanobot", "config.json")
    text = cfg_path.read_text()
    ex = json.loads(text)["tools"]["exec"]
    assert ex["allowedEnvKeys"] == ["STAMP_NONCE", "HR_API_URL"]     # names only, none that is unset
    assert "n-123" not in text                                     # the value stays in the environment
    assert "pathPrepend" not in ex                                 # no environment layer, no PATH entry
