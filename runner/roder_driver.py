#!/usr/bin/env python3
"""One app-server process per turn, as with Codex; native thread state rides the checkpoint."""
import asyncio
import json
import os
import pathlib
import sys

from roder_events import Events
from roder_mcp import Mcp


def emit(event):
    print(json.dumps(event), flush=True)


class RpcError(RuntimeError):
    def __init__(self, error):
        self.code = error.get("code")
        super().__init__(str(error.get("message") or "Roder RPC error"))


class Rpc:
    def __init__(self, process):
        self.process = process
        self.seq = 0
        self.pending = {}
        self.events = asyncio.Queue()

    async def read(self):
        error = RuntimeError("Roder app-server closed its output before turn/completed")
        try:
            while line := await self.process.stdout.readline():
                msg = json.loads(line)
                if "id" in msg and not msg.get("method"):
                    future = self.pending.pop(msg["id"], None)
                    if future and not future.done():
                        if msg.get("error"):
                            future.set_exception(RpcError(msg["error"]))
                        else:
                            future.set_result(msg.get("result") or {})
                else:
                    await self.events.put(msg)
        except Exception:
            error = RuntimeError("Roder app-server emitted an invalid JSON-RPC stream")
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(error)
            await self.events.put(None)

    async def request(self, method, params):
        self.seq += 1
        future = asyncio.get_running_loop().create_future()
        self.pending[self.seq] = future
        self.process.stdin.write((json.dumps({"jsonrpc": "2.0", "id": self.seq,
                                              "method": method, "params": params}) + "\n").encode())
        await self.process.stdin.drain()
        return await future


async def forward_stderr(process):
    # Roder's completion notification can be a bare terminal BEL. The runner merges this
    # driver's stderr into stdout; inheriting it would prefix our next JSON line with BEL and
    # make the runner drop turn/completed. Forward diagnostics only as complete, clean lines.
    while line := await process.stderr.readline():
        text = line.decode(errors="replace").replace("\x07", "").strip()
        if text:
            print(text, file=sys.stderr, flush=True)


async def configure_allowlist(job):
    """Discover built-ins without inference, then apply Roder's runtime allowlist before start.

    This also applies a changed policy to resumed threads. A non-matching sentinel denies every
    built-in when all are disabled: an empty Roder allowlist means unrestricted.
    """
    process = await asyncio.create_subprocess_exec(os.environ.get("HR_RODER_BIN", "roder"),
        "app-server", stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, limit=8 * 1024 * 1024)
    rpc = Rpc(process)
    reader = asyncio.create_task(rpc.read())
    diagnostics = asyncio.create_task(forward_stderr(process))
    try:
        tools = (await rpc.request("tools/list", {})).get("tools", [])
        disabled = set(job.get("tools_disabled") or [])
        allowed = [tool["name"] for tool in tools if tool["name"] not in disabled]
        config = pathlib.Path(os.environ["RODER_CONFIG_DIR"]) / "config.toml"
        # The builder rewrites this file every turn, so this is exactly one tools table.
        with config.open("a") as output:
            output.write("\n[tools]\nallowlist = " + json.dumps(allowed or ["hr_no_builtin_tools"]) + "\n")
    finally:
        if process.returncode is None:
            process.terminate()
        await process.wait()
        reader.cancel()
        await asyncio.gather(reader, diagnostics, return_exceptions=True)


async def run(job):
    await configure_allowlist(job)
    # No new process group: the runner's normal timeout/cancellation kills this driver AND the
    # app-server, its commands and attached stdio MCP processes together.
    process = await asyncio.create_subprocess_exec(os.environ.get("HR_RODER_BIN", "roder"),
        "app-server", stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, limit=8 * 1024 * 1024)
    rpc = Rpc(process)
    reader = asyncio.create_task(rpc.read())
    diagnostics = asyncio.create_task(forward_stderr(process))
    events = Events()
    try:
        await rpc.request("initialize", {})
        disabled = set(job.get("tools_disabled") or [])
        async with Mcp() as mcp:
            await mcp.connect(job.get("mcp_servers") or [], disabled, emit)
            sid = job.get("resume")
            if sid:
                try:
                    stored = await rpc.request("thread/read", {"threadId": sid})
                    if not stored.get("thread"):
                        emit({"type": "system", "subtype": "resume_lost", "requested_session_id": sid})
                        sid = None
                    elif (stored["thread"].get("externalTools") or []) != mcp.tools:
                        raise RuntimeError("MCP attachments changed; start a new Roder session")
                except RpcError as error:
                    # Do not mislabel an arbitrary read/storage error as lost conversation state.
                    if "not found" not in str(error).lower() and "unknown thread" not in str(error).lower():
                        raise
                    emit({"type": "system", "subtype": "resume_lost", "requested_session_id": sid})
                    sid = None
            if not sid:
                workspace = (await rpc.request("workspace/create", {"roots": [{"path": os.getcwd()}]}))["workspace"]
                thread = await rpc.request("thread/start", {"workspaceId": workspace["id"],
                    "model": job["model"], "modelProvider": "hr", "externalTools": mcp.tools})
                sid = thread["thread"]["id"]
            emit({"type": "system", "subtype": "init", "session_id": sid, "model": job["model"]})
            params = {"threadId": sid, "modelProvider": "hr", "model": job["model"],
                      "policyMode": "bypass", "input": [{"type": "text", "text": job["prompt"]}]}
            instructions = pathlib.Path("AGENTS.md")
            if instructions.is_file():
                params["developerContext"] = instructions.read_text()
            if job.get("reasoning"):
                params["reasoning"] = job["reasoning"]
            turn = await rpc.request("turn/start", params)
            turn_id = turn["turnId"]
            while not events.finished:
                msg = await rpc.events.get()
                if msg is None:
                    raise RuntimeError("Roder app-server exited before turn/completed")
                method, p = msg.get("method"), msg.get("params") or {}
                if p.get("threadId") != sid or (p.get("turnId") and p["turnId"] != turn_id):
                    continue
                if method == "thread/toolExecutionRequested":
                    try:
                        result = await mcp.call(p["call"])
                    except Exception:
                        result = {"output": "MCP tool call failed", "isError": True}
                    await rpc.request("tools/resolve", {"requestId": p["requestId"], **result})
                elif method in ("thread/userInputRequested", "thread/planExitRequested"):
                    raise RuntimeError("Roder requested interactive input in a non-interactive turn")
                else:
                    for event in events.notification(method, p):
                        emit(event)
    finally:
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        reader.cancel()
        await asyncio.gather(reader, diagnostics, return_exceptions=True)


def main():
    try:
        asyncio.run(run(json.loads(os.environ["HR_RODER_JOB"])))
        return 0
    except Exception as error:
        emit({"type": "result", "subtype": "error", "is_error": True, "result": str(error)})
        return 1


if __name__ == "__main__":
    sys.exit(main())
