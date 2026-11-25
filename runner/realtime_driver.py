"""One text turn on a realtime speech model, as a runner subprocess.

Spawned per turn by server.py with the job in its environment, the one-process-per-turn contract
every other backend keeps: the runner reads NDJSON off stdout and cancel is a process-group kill.
Inside, the open-source Realtime Harness (github.com/HarnessRouter/RealtimeHarness) runs the turn:
it opens the model's connection, gives it the harness's instructions and the tools of the
harness's MCP servers, replays what the session has said so far, asks, runs every tool call the
model makes and answers it, and stops when the model answers without calling a tool.

A realtime model also takes a text turn (Realtime Harness design §6.4), and that is all this
driver runs. A voice call is a connection held for minutes, which a process that lives for one
turn cannot hold: calls are the gateway's realtime plane, not this file.

THE MODEL IS REACHED OVER A WEBSOCKET, AND THE KEY STILL NEVER COMES HERE. The loopback relay
forwards HTTP and nothing else, so the driver cannot open the model's socket through it. What it
does through the relay is one HTTP call, the provider's own: `POST …/realtime/client_secrets`,
which mints a secret good for one session and bounded in time. The driver holds a placeholder for
that call and the relay holds the key, as for every backend; what comes back is the credential
the provider makes for exactly this, a client that must not hold the key. The driver then opens
the socket with it. Measured on Azure OpenAI gpt-realtime-2.1 (Realtime Harness design §1.7): a
client secret opens the WebSocket as a bearer, not only WebRTC.

So the relay's taps see no model call, and the driver reports what they would have: the model the
provider's own `session.created` names, and the usage its `response.done` events carry, summed
over the turn. A provider that reports no usage leaves it empty; nothing is counted here.

THE SESSION IS A FILE IN THE WORKSPACE: `.harness/realtime/<session>/items.json`, the items of
every earlier turn. Each turn replays them to a new connection, so a follow-up and a turn after a
sandbox recycle answer from the same history, and nothing of the session lives in a process.

The events are Claude Code's stream-json, so the runner's passthrough normaliser reads them: one
`tool_use` and one `tool_result` per tool call, the answer as assistant text (its deltas as
`stream_event`s when the turn asked for them), and a `result` with the usage and the model.

TOOLS ARE MCP SERVERS REACHED BY URL. The Realtime Harness speaks Streamable HTTP and SSE. A
stdio server is a process on this box that it has no way to start, so it is named in
`system/mcp_unavailable` and the turn runs without it, the remote-runtime precedent (qoder).
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.request
import uuid

SECRET_TTL_S = 120          # how long the minted secret may START a session; the turn opens it at once
MINT_TIMEOUT_S = 20
_SID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_SERVER_NAME_RE = re.compile(r"[^A-Za-z0-9_-]")


def _emit(ev: dict) -> None:
    print(json.dumps(ev, default=str), flush=True)


class MintError(RuntimeError):
    """The provider would not mint a session secret. The message is the provider's code, never its
    body: a body can quote the request, and the request carried the placeholder."""


def mint_secret(mint_url: str, token: str, model: str, *, ttl_s: int = SECRET_TTL_S) -> str:
    """One session secret for `model`, minted by the provider through the relay.

    `token` is the relay's placeholder; the relay replaces it with the connection's key. The body
    names the model and nothing else: the instructions and the tools are set on the connection
    itself, by this process, so nothing about the harness is fixed in a credential."""
    body = json.dumps({"expires_after": {"anchor": "created_at", "seconds": int(ttl_s)},
                       "session": {"type": "realtime", "model": model}}).encode()
    req = urllib.request.Request(mint_url, data=body, method="POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=MINT_TIMEOUT_S) as r:  # noqa: S310 - the relay, on loopback
            doc = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            code = str(((json.loads(e.read() or b"{}") or {}).get("error") or {}).get("code") or "")[:64]
        except (ValueError, AttributeError):
            code = ""
        raise MintError(f"The model's provider refused to start a session (HTTP {e.code}"
                        + (f", {code}" if code else "") + ").") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        raise MintError(f"The model's provider could not be reached ({type(e).__name__}).") from None
    secret = str((doc or {}).get("value") or "") if isinstance(doc, dict) else ""
    if not secret:
        raise MintError("The model's provider answered without a session secret.")
    return secret


def server_entries(mcp_servers: list | None) -> tuple[list[dict], list[dict]]:
    """The harness's MCP servers as the Realtime Harness takes them, and the ones it cannot reach.

    -> (entries with a url, [{"name": …}] for each stdio server). A bearer in `auth` becomes the
    Authorization header, as the other drivers read it. A name is made one the realtime APIs can
    put in a tool's name."""
    usable, dropped = [], []
    for i, s in enumerate(mcp_servers or []):
        if not isinstance(s, dict):
            continue
        name = _SERVER_NAME_RE.sub("_", str(s.get("name") or f"server{i + 1}"))[:40] or f"server{i + 1}"
        url = str(s.get("url") or "").strip()
        if not url:
            if s.get("command"):
                dropped.append({"name": name})
            continue
        headers = {str(k): str(v) for k, v in (s.get("headers") or {}).items() if k and v is not None}
        auth = s.get("auth")
        if auth:
            headers["Authorization"] = auth if str(auth).lower().startswith("bearer ") else f"Bearer {auth}"
        usable.append({"name": name, "url": url, "headers": headers,
                       "transport": "sse" if str(s.get("transport") or "").lower() == "sse" else "http",
                       "enabled": s.get("enabled", True) is not False,
                       "disabled_tools": [str(t) for t in (s.get("disabled_tools") or s.get("disabledTools") or [])]})
    return usable, dropped


def session_dir(cwd: pathlib.Path, sid: str) -> pathlib.Path:
    return cwd / ".harness" / "realtime" / sid


def load_items(cwd: pathlib.Path, sid: str) -> list[dict]:
    """What the session has said so far; [] for a new one, or one whose file is gone or unreadable
    (the runner's own probe says so to the person: _SESSION_PRESENT)."""
    try:
        doc = json.loads((session_dir(cwd, sid) / "items.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [it for it in doc if isinstance(it, dict)] if isinstance(doc, list) else []


def save_items(cwd: pathlib.Path, sid: str, items: list[dict]) -> None:
    d = session_dir(cwd, sid)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "items.json.tmp"
    tmp.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, d / "items.json")           # a turn killed mid-write leaves the last whole file


def claude_usage(usage: dict | None) -> dict:
    """The provider's usage in the names the runner reads. Its input count includes what it read
    from its cache, and the contract's `input_tokens` is fresh input only. {} when the provider
    reported none: a zero here would read as a free turn."""
    if not isinstance(usage, dict):
        return {}
    cached = int(usage.get("cache_read_tokens") or 0)
    out = {"input_tokens": max(int(usage.get("input_tokens") or 0) - cached, 0),
           "output_tokens": int(usage.get("output_tokens") or 0)}
    if cached:
        out["cache_read_input_tokens"] = cached
    return out


def _text_of(item: dict) -> str:
    return "".join(str(p.get("text") or "") for p in item.get("content") or [] if isinstance(p, dict))


def _tool_output(item: dict) -> tuple[str, bool]:
    """A tool call's answer as the trace shows it: its text, and whether it was a refusal or a failure."""
    raw = str(item.get("output") or "")
    try:
        doc = json.loads(raw)
    except ValueError:
        return raw, False
    if not isinstance(doc, dict):
        return raw, False
    if doc.get("error"):
        return f"{doc.get('error')}: {doc.get('detail') or ''}".strip(": "), True
    return str(doc.get("output") if doc.get("output") is not None else raw), False


async def _run(job: dict, emit, connect=None) -> dict:
    from realtime_harness.config import HarnessConfig, McpServer
    from realtime_harness.credentials import Connection
    from realtime_harness.textturn import Listener, TurnResult, run_text_turn
    from realtime_harness.tools import ToolExecutor

    cwd = pathlib.Path(job.get("cwd") or ".")
    model = str(job.get("model") or "")
    resume = str(job.get("resume_session_id") or "")
    sid = resume if _SID_RE.match(resume) else "rt_" + uuid.uuid4().hex[:16]
    partial = bool(job.get("partial"))
    emit({"type": "system", "subtype": "init", "session_id": sid, "model": model})

    usable, dropped = server_entries(job.get("mcp_servers"))
    if dropped:
        emit({"type": "system", "subtype": "mcp_unavailable", "servers": dropped})
    harness = HarnessConfig(
        id="turn", name="turn", instructions=str(job.get("agent_doc") or ""),
        mcp_servers=[McpServer(name=s["name"], url=s["url"], transport=s["transport"], headers=s["headers"],
                               enabled=s["enabled"], disabled_tools=s["disabled_tools"]) for s in usable],
        disabled_tools=[str(t) for t in (job.get("tools_disabled") or [])],
        **({"tool_timeout_seconds": float(job["tool_timeout_seconds"])} if job.get("tool_timeout_seconds") else {}))
    history = load_items(cwd, sid) if resume and sid == resume else []
    text = str(job.get("prompt") or "")
    executor = ToolExecutor(harness)
    server_of: dict[str, str] = {}          # the name the model sees -> its server, for the trace

    seen: list[dict] = []                   # every item as it finished, for a turn its own time cut short

    class Trace(Listener):
        async def text_delta(self, item: dict, delta: str) -> None:
            if partial and delta:
                emit({"type": "stream_event", "event": {"type": "content_block_delta",
                                                         "delta": {"type": "text_delta", "text": delta}}})

        async def item_done(self, item: dict) -> None:
            seen.append(item)
            kind = item.get("type")
            if kind == "message":
                said = _text_of(item)
                if said:
                    emit({"type": "assistant", "message": {"content": [{"type": "text", "text": said}]}})
            elif kind == "function_call":
                name = str(item.get("name") or "")
                try:
                    args = json.loads(item.get("arguments") or "{}")
                except ValueError:
                    args = {"arguments": item.get("arguments")}
                # Claude Code's own name for an MCP tool, so the trace says which server ran it.
                shown = f"mcp__{server_of[name]}__{name}" if name in server_of else name
                emit({"type": "assistant", "message": {"content": [
                    {"type": "tool_use", "id": str(item.get("call_id") or item.get("id") or ""), "name": shown,
                     "input": args if isinstance(args, dict) else {"arguments": args}}]}})
            elif kind == "function_call_output":
                out, is_error = _tool_output(item)
                emit({"type": "user", "message": {"content": [
                    {"type": "tool_result", "tool_use_id": str(item.get("call_id") or ""), "is_error": is_error,
                     "content": out}]}})

    result = TurnResult(status="failed", error={"code": "harness_error", "message": "The turn did not run."})
    reason = ""
    try:
        await executor.open()
        server_of.update({name: tool.server for name, tool in executor.tools.items()})
        unreachable = [{"name": k.split(":", 1)[1]} for k, why in executor.left_out.items()
                       if k.startswith("server:") and str(why).startswith("unreachable")]
        if unreachable:        # UHP Harnesses §4.1: an unreachable server does not fail the task, and it is said
            emit({"type": "system", "subtype": "mcp_unavailable", "servers": unreachable})
        if connect is not None:
            conn = connect(model)
        else:
            secret = await asyncio.to_thread(mint_secret, str(job.get("mint_url") or ""),
                                             str(job.get("api_key") or ""), model)
            conn = Connection(url=str(job.get("ws_url") or ""), headers={"Authorization": f"Bearer {secret}"},
                              model=model, ref={})
        max_step = int(job["max_turns"]) if job.get("max_turns") else None
        turn = run_text_turn(conn, instructions=harness.instructions, executor=executor, history=history,
                             text=text, listener=Trace(), cancelled=asyncio.Event(), max_step=max_step)
        timeout = float(job["timeout_seconds"]) if job.get("timeout_seconds") else None
        if timeout:
            try:
                result = await asyncio.wait_for(turn, timeout)
            except asyncio.TimeoutError:
                result, reason = TurnResult(status="incomplete", output=list(seen)), "timeout"
        else:
            result = await turn
        if result.status == "incomplete" and not reason:
            reason = "max_steps"
    except MintError as e:
        result, reason = TurnResult(status="failed", error={"code": "provider_unavailable", "message": str(e)}), "provider"
    finally:
        await executor.close()

    # The record: what this turn added, after what was there. Only whole items are kept, so a
    # connection that later replays them is never handed a call without its answer.
    user_item = {"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}
    done = [it for it in (result.output or []) if it.get("status") in (None, "completed")]
    answered = {it.get("call_id") for it in done if it.get("type") == "function_call_output"}
    done = [it for it in done if it.get("type") != "function_call" or it.get("call_id") in answered]
    save_items(cwd, sid, history + [user_item] + done)

    final = next((_text_of(it) for it in reversed(result.output or []) if it.get("type") == "message"), "")
    served = str(getattr(result, "model", "") or "")
    out = {"type": "result", "session_id": sid, "usage": claude_usage(result.usage),
           # the model the provider named; absent when it named none, so a row reads "served model
           # unreported" and never repeats the id that was asked for as if it had been checked
           **({"model": served} if served else {})}
    if result.status == "completed":
        out.update(subtype="success", is_error=False, result=final)
    elif result.status == "incomplete":
        # a step budget or the turn's own time ran out: the runner's max_turns, which the gateway
        # reports as `incomplete` naming the budget
        out.update(subtype="error_max_turns", is_error=False, result=final, reason=reason)
    else:
        err = result.error or {}
        out.update(subtype="error", is_error=True, reason=reason or str(err.get("code") or "provider_error"),
                   result=str(err.get("message") or "The turn failed."))
    emit(out)
    return out


def run_turn(job: dict, emit=_emit, connect=None) -> dict:
    """Run one turn and emit its events; returns the result event. `connect(model) -> Connection`
    is injectable for tests, in place of the mint and the provider's address."""
    return asyncio.run(_run(job, emit, connect))


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    raw = argv[0] if len(argv) == 1 else os.environ.pop("HR_DRIVER_JOB", "") if not argv else ""
    if not raw:
        print("usage: realtime_driver.py '<job json>' (or the job in HR_DRIVER_JOB)", file=sys.stderr)
        return 2
    job = json.loads(raw)
    try:
        result = run_turn(job)
    except Exception as exc:  # noqa: BLE001 - a crash is a failed turn with its reason, never a silent exit
        _emit({"type": "result", "subtype": "error", "is_error": True,
               "result": f"The turn failed ({type(exc).__name__}).", "reason": "harness_error", "usage": {}})
        return 1
    return 0 if not result.get("is_error") else 1


if __name__ == "__main__":
    sys.exit(main())
