"""One DeepSeek Harness turn, as a runner subprocess.

Spawned per turn by server.py (the same one-process-per-turn contract as every other backend:
the runner reads NDJSON off stdout, cancel is a process-group kill). Inside, the official
Python SDK (`deepseek-harness-sdk`, pinned) drives the bundled JSON-RPC runtime executable
(`deepseek-harness-runtime-bin`, same pinned version); every `session.event` notification is
re-emitted on stdout as one JSON line for server.py's normalizer.

THE RELAY. The runtime's model calls ride the runner's relay (server.py, _HermesRelayHandler), as
every other base's do. _build_dsh registers this turn's route there, holding the connection's
key, and hands this process only the relay's base and the route's placeholder (HR_DSH_RELAY_BASE,
HR_DSH_RELAY_TOKEN). The runtime is launched with DEEPSEEK_BASE_URL at that base and the
placeholder as its key, so the credential never enters this process, the runtime's env, its
session log, or anything it could checkpoint.

The route carries the one repair this base needs of its own (tool_call_deltas_no_empty). The dsh
LLM adapter accumulates streamed tool calls the OpenAI way: id from `call.id`, name from
`call.function.name`, guarded by `!== undefined`. OpenAI OMITS those fields on continuation
deltas; aggregators like TokenRouter send them as EMPTY STRINGS, so the second delta overwrites
the real id/name with "" and every tool call dies as UNKNOWN_TOOL (captured live 2026-08-20
against deepseek/deepseek-v4-flash). Until #382 this driver ran a loopback relay of its own for
that, and every relay fix (the stream rules, the Gemini repairs, an answer when the provider does
not answer) had to be made twice; most were made once.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys


def _emit(method: str, payload) -> None:
    sys.stdout.write(json.dumps({"m": method, "p": payload}, default=str) + "\n")
    sys.stdout.flush()


def _compose_patch(home: pathlib.Path, servers: list[dict], llm: dict | None = None,
                   relay_base: str = "", model: str = "", cwd: str = "") -> str:
    """Our overlay on the runtime's stock `sdk` profile, in the loader's own patch grammar: a row
    named by id is merged, `disabled: true` stops one, and `insert` appends new rows.

    The stock JSON-RPC server row is disabled and ours inserted in its place (see
    hr_dsh_server.mjs: resume-or-create), one dsh-mcp-client row is inserted per enabled MCP
    server, and a non-deepseek family gets its route merged into the stock dsh-llm-pi-ai row.
    A patch cannot rename a row, which is why the server is disable-plus-insert rather than the
    name swap the previous runtime's bundled cordis.yml allowed.

    The sdk profile's sandboxing executor rows are disabled and the local executors inserted, the
    composition rc7 shipped (dsh-bash-local, dsh-fs-local). This is the state upstream itself
    names, "sandbox_permissions is not available in this composition (no sandboxing executor to
    escalate)": with a sandboxing executor mounted, every file tool advertises the escalation
    fields `sandbox_permissions` and `justification`, meant for a one-shot retry after a denial.
    GPT models fill them on every write regardless, and under danger-full-access each such call is
    refused as "not strictly wider than this call's current mode": twenty refused writes in one
    turn, the file never created, on gpt-5.2 through gpt-6-astra (the dsh matrix column through
    Vercel, 2026-09-08); DeepSeek and Claude leave the fields alone. A field that does not exist
    cannot be filled. The workspace and the container are the boundary here, as for every other
    backend. `permission` goes with them: it throws over an unconfined executor."""
    entries: list = [{"id": "sdk-jsonrpc-server", "disabled": True}]
    entries += [{"id": rid, "disabled": True}
                for rid in ("sandbox", "sandbox-policy", "bash-sandbox", "fs-sandbox", "permission")]
    # The stock web_search provider calls DeepSeek's own API (https://api.deepseek.com/anthropic/v1/messages) with
    # the relay's placeholder key: every search answered 401 "Authentication Fails" (measured on the test instance,
    # 2026-10-27, and on the hosted service), and it would send a turn's queries to a provider the turn's
    # connection never named. The provider row is off, and the tool itself is not registered: with the row off
    # alone the model was still offered web_search, and every call failed "the configured web provider is not
    # registered" (measured on the test instance). `search: false` is the web tool's own switch (its config:
    # search, fetch, both default true), merged into the stock `tool-web` row; web_fetch (plain HTTP) stays, and a
    # setup's own search plug is how an agent searches.
    entries.append({"id": "web-search-deepseek", "disabled": True})
    entries.append({"id": "tool-web", "config": {"search": False}})
    cjs = home / ".dsh" / "hr_dsh_server.mjs"
    inserted: list = [{"id": "hr-sdk-jsonrpc-server", "name": str(cjs),
                       "inject": ["sdkAppStartup", "loader"],
                       # the stock row's default: a turn that stops on max tokens is a finished turn
                       "config": {"maxTokensAsSuccess": True}},
                      {"id": "hr-bash-local", "name": "@deepseek-ai/dsh-bash-local", "config": {"cwd": cwd}},
                      {"id": "hr-fs-local", "name": "@deepseek-ai/dsh-fs-local", "config": {"cwd": cwd}}]
    for i, s in enumerate(servers):
        url = (s or {}).get("url")
        name = "".join(c for c in str((s or {}).get("name") or f"mcp{i}") if c.isalnum() or c in "_-")[:32] or f"mcp{i}"
        if not url:
            # A plugin's stdio server: dsh-mcp-client's own stdio transport spawns the command
            # (StdioClientTransport); the launcher the runner wrote carries env and cwd. The row
            # names the workspace as cwd because the client's schema defaults it to "" and spawns
            # with that, which never starts (hosted, 2026-09-15); the launcher cd's on its own.
            if (s or {}).get("command"):
                inserted.append({"id": f"hr-mcp-{i}", "name": "@deepseek-ai/dsh-mcp-client",
                                 "config": {"transport": "stdio", "serverName": name, "cwd": cwd,
                                            "command": str(s["command"]), "args": [str(a) for a in (s.get("args") or [])]}})
            continue
        entry = {"id": f"hr-mcp-{i}", "name": "@deepseek-ai/dsh-mcp-client",
                 "config": {"transport": "streamable-http", "serverName": name, "url": url}}
        hdrs: dict = {}
        auth = (s or {}).get("auth")
        if auth:
            hdrs["Authorization"] = auth if str(auth).lower().startswith("bearer ") else f"Bearer {auth}"
        if isinstance((s or {}).get("headers"), dict):
            hdrs.update({str(k): str(v) for k, v in s["headers"].items() if k and v is not None})
        if hdrs:
            entry["config"]["headers"] = hdrs
        inserted.append(entry)
    entries.append({"insert": inserted})
    if llm:
        # Non-deepseek families ride dsh's OWN multi-provider layer, dsh-llm-pi-ai — which is
        # pi's unified LLM library wrapped as a Cordis plugin, so the api-by-family choices are
        # literally the ones the pi backend already proved. The route points at the runner's
        # relay; apiKeyEnv resolves the route's placeholder, and the relay injects the real
        # credential upstream — same isolation as the deepseek path.
        api = llm.get("api") or "openai-completions"
        # The same /v1 lesson the pi backend already paid for: the anthropic-messages client
        # appends /v1/messages to its base itself, the openai clients want /v1 present. Getting
        # it wrong here produced /v1/v1/messages against the relay — measured, not guessed.
        base = relay_base.rstrip("/").removesuffix("/v1")   # the runner's relay names its base with /v1
        base_url = base if api == "anthropic-messages" else f"{base}/v1"
        entries.append({"id": "llm-pi-ai", "config": {
            "providers": {"hr": {
                "displayName": "HR Gateway",
                "apiKeyEnv": "HR_RELAY_TOKEN",
                "api": api,
                "baseURL": base_url,
                "models": [{"id": model, "contextWindow": 200000, "maxTokens": 32000,
                            "input": (["text", "image"] if llm.get("vision", True) else ["text"])}],
            }}}})
    path = home / ".dsh" / "hr.patch.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copy(pathlib.Path(__file__).with_name("hr_dsh_server.mjs"), cjs)
    import yaml
    path.write_text(yaml.safe_dump(entries, sort_keys=False))
    return str(path)


# dsh's skill tool loads only what its skill-filesystem provider found (the runtime's own docs: project roots
# <projectRoot>/.dsh/skills and .agents/skills, Config.customSkillDirs, then <dshHome>/skills and <agentsHome>/skills;
# a root's direct children only, <name>/SKILL.md or <name>.md). The runner writes a setup's skills to .harness/skills
# and a plugin package's to .harness/plugins/<package>/skills, neither of them a root, so every `skill` call answered
# 'Error: skill "<name>" is unknown or no longer available' while AGENTS.md listed the names (measured on the test
# instance, 2026-10-27, 2 of 2 for the built-in officecli; the hosted service saw 29 of 29). Each one is copied
# into <dshHome>/skills, the user root: inside this session's own home under .harness/, so never a produced file,
# and rewritten each turn. A setup's own skill wins a name a package also uses; packages in name order after it.
def _install_skills(home: pathlib.Path, cwd: str) -> list[str]:
    import shutil
    dest = home / ".dsh" / "skills"
    root = pathlib.Path(cwd) / ".harness"
    sources = [root / "skills"] + sorted(p / "skills" for p in (root / "plugins").glob("*") if (p / "skills").is_dir())
    shutil.rmtree(dest, ignore_errors=True)
    installed: list[str] = []
    for src in sources:
        if not src.is_dir():
            continue
        for d in sorted(src.iterdir()):
            if not (d.is_dir() and (d / "SKILL.md").is_file()) or d.name in installed or d.name.startswith("."):
                continue
            shutil.copytree(d, dest / d.name, symlinks=False)
            installed.append(d.name)
    return installed


def main() -> int:
    job = json.loads(sys.argv[1])
    # The runner's relay and this turn's route on it (server.py, _build_dsh). Neither is a
    # credential: the key stays in the runner, and the placeholder opens only this turn's route.
    relay_base = os.environ.pop("HR_DSH_RELAY_BASE", "")
    relay_tok = os.environ.pop("HR_DSH_RELAY_TOKEN", "")
    if not (relay_base and relay_tok):
        print("[dsh driver] no relay route was handed over (HR_DSH_RELAY_BASE, HR_DSH_RELAY_TOKEN)",
              file=sys.stderr, flush=True)
        return 2
    home = pathlib.Path(os.environ.get("HOME") or ".")
    cwd = job.get("cwd") or os.getcwd()
    try:
        _install_skills(home, cwd)
    except OSError as e:   # a turn without its skills still runs, and says why on the runner's log
        print(f"[dsh] skills not installed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)

    os.environ["DEEPSEEK_BASE_URL"] = relay_base
    os.environ["DEEPSEEK_API_KEY"] = relay_tok   # the real key never reaches the runtime

    from deepseek_harness import DeepSeekHarness

    os.environ["HR_RELAY_TOKEN"] = relay_tok   # the placeholder the pi-ai route resolves
    # The sdk profile's approval policy reads this ('never' only under danger-full-access, 'ask'
    # otherwise), and a headless turn has no one to ask. The sandbox policy read it too before the
    # sandboxing executor rows were taken out of the composition (see _compose_patch): its default
    # refused EVERY command on a host with no bubblewrap and no Landlock, which is this product's
    # container ("no sandbox backend is usable on this host; refusing to run the command
    # unconfined", measured 2026-09-08 on 0.1.2rc1: the skill's script never ran and the agent
    # quoted its source instead).
    os.environ["DSH_PERMISSION_MODE"] = "danger-full-access"
    llm = job.get("llm")   # None => the verified deepseek-official path
    # The SDK launches `dsh --profile sdk --patch <ours>` against an explicit home; the profile
    # keeps sessions under $DSH_HOME/sessions, so ~/.dsh/sessions is where every earlier
    # runtime already put them.
    kwargs = dict(provider=("hr" if llm else "deepseek-official"), model=job["model"],
                  cwd=cwd, dsh_home=str(home / ".dsh"),
                  patches=(_compose_patch(home, job.get("mcp_servers") or [], llm=llm,
                                          relay_base=relay_base, model=job["model"], cwd=cwd),),
                  # A runtime whose plugin tree failed stays alive with a mute stdout; without a
                  # bound the initialize request waits forever and the turn reads as a hang.
                  request_timeout_seconds=180.0)
    sid = job.get("session_id") or None
    _emit("__hr_init", {"session_id": sid or ""})
    with DeepSeekHarness(**kwargs) as h:
        r = h.run(job["prompt"], session_id=sid,
                  on_notification=lambda n: _emit(getattr(n, "method", ""), getattr(n, "payload", None)))
        _emit("__hr_result", {"final": r.final_response or "", "reason": r.finish_reason,
                              "session_id": r.session_id})
    return 0


if __name__ == "__main__":
    sys.exit(main())
