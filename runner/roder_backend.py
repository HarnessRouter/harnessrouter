"""Roder's native app-server backend. Provider traffic stays on the runner relay."""
import json
import pathlib
import sys

# dcode's providers: OpenRouter and a custom Responses endpoint are `openai-api`, the aggregators
# `tokenrouter` (gateway _INTEGRATION_WIRING).
PROVIDERS = {"openai", "azure", "openai-api", "tokenrouter"}
DEFAULT_MODEL = "gpt-6.1-sol"
DRIVER = str(pathlib.Path(__file__).with_name("roder_driver.py"))

# Roder 0.4.8's built-in tools, by the registry names its runtime `tools.allowlist` matches (what
# `tools/list` answers; the wire spells the dotted ones with underscores). Read off the pinned
# release's app-server for gpt-6.1-sol and for a claude id (the edit family differs by model: a gpt
# model gets apply_patch alone, others also get edit, multi_edit and write_file). Each console
# switch names EVERY tool that does the same job, so switching one off leaves no equivalent behind:
# the shell is four tools here, and a file is written by any of four. The gateway's catalog lists
# these ids (test_roder_catalog.py pins them equal); runner/tests/test_roder_process.py checks this
# table against the real binary, so a release that adds a tool fails there until it is placed.
TOOLS: dict[str, tuple[str, ...]] = {
    "exec_command": ("exec_command", "shell", "unified_exec", "write_stdin"),
    "read_file": ("read_file",),
    "apply_patch": ("apply_patch", "edit", "multi_edit", "write_file"),
    "grep": ("grep",),
    "glob": ("glob",),
    "list_files": ("list_files",),
    "view_image": ("view_image",),
    "update_plan": ("update_plan", "task_ledger.update"),
    "spawn_agent": ("spawn_agent", "followup_task", "send_message", "wait_agent", "list_agents",
                    "interrupt_agent"),
    "memory_save": ("memory_save", "memory_query", "memory_read", "memory_update", "memory_delete"),
    "knowledge_save": ("knowledge_save", "knowledge_search", "knowledge_list", "knowledge_read",
                       "knowledge_update", "knowledge_link", "knowledge_delete"),
    "create_goal": ("create_goal", "get_goal", "update_goal"),
    "subscribe_event": ("subscribe_event", "cancel_event_subscription", "list_event_subscriptions",
                        "publish_event"),
    "verification_review": ("verification_review",),
    "read_artifact": ("read_artifact", "grep_artifact", "tail_artifact"),
    "discovery.search": ("discovery.search", "discovery.list", "discovery.read"),
    "design_read": ("design_read", "design_batch_get", "design_patch", "design_get_variables",
                    "design_set_variables", "design_get_guidelines", "design_snapshot_layout",
                    "design_export_nodes", "design_spawn_agents"),
    # The provider's hosted search, not a registry tool: the allowlist does not reach it, Roder's
    # own `[web_search] mode` does (build).
    "web_search": (),
}

# Withheld on every turn and not offered, because they cannot run here or would stop a turn nobody
# is attending. MEASURED on 0.4.8 in a container, each called by a scripted model turn: chrome_*
# answered "Desktop integrated browser is not reachable", jev_browse "JEV_API_KEY is required",
# zerolang_check "failed to launch Zero binary zero"; webwright.* runs Playwright scripts with a
# browser the image does not carry; media_generate_image answered from a built-in FAKE provider
# ("generated 1 image artifact(s) with fake/fake-image") and media_generate_video says it is an
# offline test artifact, and media_attach/media_describe act only on what those produced; echo is a
# test tool. request_user_input and exit_plan_mode wait for a person, which the driver refuses.
WITHHELD: frozenset[str] = frozenset({
    *(f"chrome_{n}" for n in ("click", "console_read", "debug_attach", "debug_detach", "eval",
                              "highlight", "keypress", "navigate", "network_read", "page_snapshot",
                              "page_text", "recording_start", "recording_stop", "screenshot",
                              "scroll", "select", "tab_activate", "tab_close", "tab_open",
                              "tabs_group", "tabs_list", "type")),
    "jev_browse",
    *(f"jev_tab_{n}" for n in ("click", "drag", "hover", "key", "look", "navigate", "screenshot",
                               "scroll", "select", "type", "wait")),
    *(f"webwright.{n}" for n in ("allocate_run", "lint_script", "list_artifacts", "prepare_workspace",
                                 "read_log_tail", "run_script", "summarize_verification",
                                 "verify_run")),
    *(f"zerolang_{n}" for n in ("check", "edit", "fix_plan", "graph_dump", "graph_roundtrip",
                                "graph_view", "skills_get")),
    "media_generate_image", "media_generate_video", "media_attach", "media_describe",
    "echo", "request_user_input", "exit_plan_mode",
})

# A name no tool has: Roder reads an EMPTY allowlist as "every tool", so all switched off is this.
_NO_BUILTIN_TOOLS = "hr_no_builtin_tools"


def _switch_of(name: str) -> str | None:
    """The console switch a Roder tool name belongs to (a switch id is its own)."""
    if name in TOOLS:
        return name
    return next((switch for switch, names in TOOLS.items() if name in names), None)


def allowlist(tools_disabled) -> list[str]:
    """Roder's runtime allowlist for a turn: every offered tool whose switch is on. A disabled name
    is either a switch id or one of the Roder names behind it; either turns the whole switch off,
    because leaving an equivalent on would leave the job doable. Withheld tools are never listed."""
    off = {_switch_of(str(name)) for name in tools_disabled or []} - {None}
    allowed = sorted(name for switch, names in TOOLS.items() if switch not in off for name in names)
    return allowed or [_NO_BUILTIN_TOOLS]


def build(provider, auth, model, prompt, cwd, env, *, relay, driver_cmd, resume_session_id=None,
          mcp_servers=None, tools_disabled=None, thinking=None):
    from fastapi import HTTPException
    if provider not in PROVIDERS:
        raise HTTPException(400, f"unknown roder provider '{provider}'")
    if auth.api_format and auth.api_format != "responses":
        raise HTTPException(400, "roder requires a Responses-format endpoint")
    base = auth.base_url or {"openai": "https://api.openai.com/v1"}.get(provider)
    if not base or not auth.api_key:
        raise HTTPException(400, "roder needs a base_url and API key")
    # Roder's OpenAI profile asks for reasoning.encrypted_content with store:false and replays it on
    # every later turn, so after a model switch it sends what another model minted: dcode's case, and
    # its answer (_earlier_turns_as_content).
    base, token = relay(base, auth.api_key, turn_reasoning_only=True)
    root = pathlib.Path(cwd) / ".harness" / "roder"
    root.mkdir(parents=True, exist_ok=True)
    env.update(RODER_CONFIG_DIR=str(root), RODER_DATA_DIR=str(root), HR_RODER_KEY=token)
    # Roder custom providers speak Responses. The id is ours, never the built-in Codex provider
    # (which would use OAuth); the wire model id is preserved exactly, including vendor slashes.
    # The tool policy is written here, before the process starts: Roder reads `tools.allowlist`
    # once at boot and applies it to every thread, a resumed one included.
    config = (f'provider = "hr"\nmodel = {json.dumps(model)}\nruntime_profile = "non_interactive"\n'
              '[providers.hr]\napi_key_env = "HR_RODER_KEY"\n'
              f'base_url = {json.dumps(base)}\n'
              '[policy_modes]\ndefault = "bypass"\nwarn_on_bypass = false\n'
              f'[tools]\nallowlist = {json.dumps(allowlist(tools_disabled))}\n')
    if "web_search" in {_switch_of(str(n)) for n in tools_disabled or []}:
        config += '[web_search]\nmode = "disabled"\n'
    (root / "config.toml").write_text(config)
    job = {"model": model, "prompt": prompt, "resume": resume_session_id,
           "tools_disabled": tools_disabled or [], "mcp_servers": mcp_servers or [],
           "reasoning": (thinking or {}).get("asked")}
    # The job carries MCP servers' bearer headers and stdio servers' env, so it travels the way every
    # driver's does, through the runner's own _driver_cmd: in the environment, under the name the
    # driver removes from its own before it starts anything, never on the command line.
    return driver_cmd(sys.executable, DRIVER, job, env)


def normalize(obj, state):
    """The driver already emits the same canonical events as Codex's app-server path."""
    if obj.get("type") == "result" and not obj.get("is_error"):
        state["final"] = obj.get("result") or ""
    if obj.get("type") == "assistant":
        for block in obj.get("message", {}).get("content", []):
            if block.get("type") == "text":
                state["final"] = state.get("final", "") + block["text"]
    return [obj]


def eof(state, rc):
    # The runner stopped the turn itself (its step budget, or a question for the person): its own
    # result says so, the same one every other base gets (server._run_turn_bg), not a crash.
    if state.get("_stop"):
        return []
    # Unlike the generic runner's exit-zero fallback, a truncated app-server stream never passes.
    return [{"type": "result", "subtype": "error", "is_error": True,
             "result": f"Roder exited without turn/completed (exit {rc})"}]


normalize.eof = eof
