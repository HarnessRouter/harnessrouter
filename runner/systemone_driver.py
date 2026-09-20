"""One System One turn, as a runner subprocess.

Spawned per turn by server.py with the job as its one argument, the same one-process-per-turn
contract every other backend keeps: the runner reads NDJSON off stdout and cancel is a process-group
kill. Inside, the open-source System One Harness (github.com/HarnessRouter/SystemOneHarness) runs
its loop: observe the environment, compile the actions it offers right now into one request, ask
the model (TypeSafe's Jev, a decision function: typed answers with probabilities, no text), gate the
answer by the action's risk, execute, repeat, until a terminal state the loop can name.

The events are Claude Code's stream-json, so the runner's passthrough normaliser reads them as it
reads qwen's: one `tool_use` and one `tool_result` per executed action, a `thinking` block for a
step the gate refused or the model ended, one assistant text for the loop's closing sentence, and a
`result` whose `subtype` says how the loop ended. `incomplete` with a `reason` is this backend's
addition to the contract: a loop that stops because the model asked for help, or would not clear
the confidence a destructive action needs, has neither failed nor run out of steps, and the
task record must say which it was.

THE ENVIRONMENT IS THE HARNESS'S MCP SERVER. Its tools are compiled to actions once per turn (the
state definition convention: an `observe` tool, a `reset` tool, every other tool an action whose
parameters are enumerable; a tool that needs free text is listed in the trace as not offered). A
harness with no MCP server runs the harness's built-in order desk, one order to pick, pack and
ship, so the base works before anything is configured. A URL server keeps its own state between
turns; a stdio server is a new process each turn and must persist its own, and the order desk is
persisted here, under the workspace, keyed by the session.

THE MODEL IS REACHED THROUGH THE LOOPBACK RELAY like every other backend: the driver holds a
placeholder bearer, the relay holds the key, and the relay reads the served model and the usage
off the provider's answer. The route's base is the provider's API root rather than its /v1, because
OpenRouter serves decisions at /api/alpha/decisions and nowhere under /api/v1 (measured 2026-09-19,
404 on the versioned path).
"""
from __future__ import annotations

import dataclasses
import json
import pathlib
import sys
import uuid

_KEEP_ON_STEP = ("index", "started_at", "action", "params", "action_confidence", "weakest", "threshold",
                 "verdict", "result", "latency_ms", "served_model", "request_id", "note")


def _emit(ev: dict) -> None:
    print(json.dumps(ev, default=str), flush=True)


def _server_entry(s: dict) -> dict | None:
    """A harness MCP server entry (name, url|command, transport?, auth?, headers?) as the adapter takes it."""
    s = s or {}
    url = str(s.get("url") or "").strip()
    headers = {str(k): str(v) for k, v in (s.get("headers") or {}).items() if k and v is not None}
    auth = s.get("auth")
    if auth:
        headers["Authorization"] = auth if str(auth).lower().startswith("bearer ") else f"Bearer {auth}"
    if url:
        e: dict = {"url": url}
        if headers:
            e["headers"] = headers
        if str(s.get("transport") or "").lower() == "sse":
            e["transport"] = "sse"
        return e
    if s.get("command"):
        return {"command": str(s["command"]), "args": [str(a) for a in (s.get("args") or [])],
                "env": s.get("env") or None, "cwd": s.get("cwd")}
    return None


def _provider_path(provider: str) -> str:
    """Where the decisions endpoint sits under the route's base. OpenRouter: /api + /alpha/decisions.
    TypeSafe direct: host + /v1/systemone."""
    return "/systemone" if provider == "typesafe" else "/alpha/decisions"


def run_turn(job: dict, provider=None, emit=_emit) -> dict:
    """Run one turn and emit its events; returns the result event. `provider` is injectable for tests."""
    from systemone_harness import Controller, DecisionProvider
    from systemone_harness.envs import McpEnvironment, OrderWorkflow
    from systemone_harness.trace import Step, reasoning_text

    cwd = pathlib.Path(job.get("cwd") or ".")
    model = str(job.get("model") or "")
    sid = str(job.get("resume_session_id") or "") or "s1_" + uuid.uuid4().hex[:16]
    resumed = bool(job.get("resume_session_id"))
    emit({"type": "system", "subtype": "init", "session_id": sid, "model": model})

    notes: list[str] = []
    servers = [e for e in (_server_entry(s) for s in (job.get("mcp_servers") or [])) if e]
    env = None
    try:
        if servers:
            if len(servers) > 1:
                notes.append(f"{len(servers)} MCP servers are configured; the first is the environment, "
                             "the others are not used by this base.")
            env = McpEnvironment(servers[0])
            cat = env.catalogue()
            space = cat.space
            for name, why in cat.unsupported.items():
                notes.append(f"Tool not offered, {name}: {why}.")
        else:
            env = OrderWorkflow("ship_cheapest")
            space = OrderWorkflow.action_space()
            notes.append("No MCP server is configured; the built-in order desk is the environment.")

        state_dir = cwd / ".harness" / "systemone" / sid
        prior: list[Step] = []
        if resumed and (state_dir / "steps.json").exists():
            try:
                prior = [Step(**{**_blank_step(), **d}) for d in json.loads((state_dir / "steps.json").read_text())]
            except (ValueError, TypeError):
                prior = []
        if resumed and isinstance(env, OrderWorkflow) and (state_dir / "environment.json").exists():
            try:
                env.restore(json.loads((state_dir / "environment.json").read_text()))
            except (ValueError, KeyError):
                pass

        if provider is None:
            provider = DecisionProvider(base_url=str(job["base_url"]).rstrip("/"),
                                        path=_provider_path(str(job.get("provider") or "openrouter")),
                                        api_key=str(job.get("api_key") or ""), model=model,
                                        headers={"X-Title": "HarnessRouter"})
        first = {"done": False}

        def on_step(step) -> None:
            n = step.index
            if not first["done"] and notes:
                emit({"type": "assistant", "message": {"content": [
                    {"type": "thinking", "thinking": " ".join(notes)}]}})
            first["done"] = True
            if step.verdict == "run":
                emit({"type": "assistant", "message": {"content": [
                    {"type": "tool_use", "id": f"call_{sid[-8:]}_{n}", "name": step.action,
                     "input": step.params or {}}]}})
                res = step.result or {}
                emit({"type": "user", "message": {"content": [
                    {"type": "tool_result", "tool_use_id": f"call_{sid[-8:]}_{n}",
                     "is_error": res.get("ok") is False, "content": str(res.get("text") or "")}]}})
            else:
                emit({"type": "assistant", "message": {"content": [
                    {"type": "thinking", "thinking": reasoning_text(step)}]}})

        ctl = Controller(space, env, provider, max_steps=int(job.get("max_turns") or 100),
                         timeout_seconds=job.get("timeout_seconds") or None,
                         disabled=set(job.get("tools_disabled") or []), on_step=on_step)
        run = ctl.run(str(job.get("prompt") or ""), reset=not resumed,
                      task_instructions=str(job.get("agent_doc") or ""), prior=prior)
        if not first["done"] and notes:
            emit({"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": " ".join(notes)}]}})

        state_dir.mkdir(parents=True, exist_ok=True)
        kept = [{k: v for k, v in dataclasses.asdict(s).items() if k in _KEEP_ON_STEP} for s in prior + run.steps]
        (state_dir / "steps.json").write_text(json.dumps(kept, default=str))
        if isinstance(env, OrderWorkflow):
            (state_dir / "environment.json").write_text(json.dumps(env.snapshot()))
        for art in run.artifacts:
            name, sep, content = str(art).partition(": ")
            if sep and name and "/" not in name and not name.startswith("."):
                (cwd / name).write_text(content)

        text = run.summary()
        emit({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}})
        if run.status == "completed":
            subtype, is_error = "success", False
        elif run.status == "incomplete" and run.reason in ("max_steps", "timeout"):
            subtype, is_error = "error_max_turns", False
        elif run.status == "incomplete":
            subtype, is_error = "incomplete", False
        else:
            subtype, is_error = "error", True
        result = {"type": "result", "subtype": subtype, "is_error": is_error,
                  "result": text if not is_error else (run.error or text), "reason": run.reason,
                  "session_id": sid, "model": run.served_model or model,
                  "usage": {"input_tokens": int(run.usage.get("input_tokens", 0)),
                            "output_tokens": int(run.usage.get("output_tokens", 0))} if run.steps else {}}
        emit(result)
        return result
    finally:
        if env is not None:
            try:
                env.close()
            except Exception:  # noqa: BLE001 - closing is best effort
                pass


def _blank_step() -> dict:
    return {"index": 0, "started_at": 0.0, "state": {}, "state_tokens": 0, "questions": {}, "answers": {},
            "action": "", "params": {}, "action_confidence": 0.0, "weakest": 0.0, "threshold": 0.0,
            "verdict": "run", "result": None, "latency_ms": 0, "usage": {}, "served_model": "",
            "request_id": "", "note": ""}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: systemone_driver.py '<job json>'", file=sys.stderr)
        return 2
    job = json.loads(argv[0])
    try:
        result = run_turn(job)
    except Exception as exc:  # noqa: BLE001 - a crash is a failed turn with its reason, never a silent exit
        _emit({"type": "result", "subtype": "error", "is_error": True,
               "result": f"{type(exc).__name__}: {exc}", "reason": "harness_error", "usage": {}})
        return 1
    return 0 if not result.get("is_error") else 1


if __name__ == "__main__":
    sys.exit(main())
