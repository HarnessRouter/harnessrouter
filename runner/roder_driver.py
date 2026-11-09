#!/usr/bin/env python3
"""One app-server process per turn, as with Codex; native thread state rides the checkpoint."""
import asyncio
import json
import os
import pathlib
import sys

from roder_events import Events
from roder_mcp import Mcp

# The longest stderr line forwarded whole; the rest of a longer line is dropped up to its newline.
STDERR_LINE_CAP = 8192


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
            buffer = bytearray()
            while chunk := await self.process.stdout.read(65536):
                buffer.extend(chunk)
                while (end := buffer.find(b"\n")) >= 0:
                    line = bytes(buffer[:end])
                    del buffer[:end + 1]
                    try:
                        msg = json.loads(line)
                    except (ValueError, UnicodeDecodeError):
                        continue
                    if not isinstance(msg, dict):
                        continue
                    self.dispatch(msg)
        except Exception:
            error = RuntimeError("Roder app-server emitted an invalid JSON-RPC stream")
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(error)
            await self.events.put(None)

    def dispatch(self, msg):
        if "id" in msg and not msg.get("method"):
            future = self.pending.pop(msg["id"], None)
            if future and not future.done():
                if msg.get("error"):
                    future.set_exception(RpcError(msg["error"]))
                else:
                    future.set_result(msg.get("result") or {})
        else:
            self.events.put_nowait(msg)

    async def request(self, method, params):
        self.seq += 1
        future = asyncio.get_running_loop().create_future()
        self.pending[self.seq] = future
        self.process.stdin.write((json.dumps({"jsonrpc": "2.0", "id": self.seq,
                                              "method": method, "params": params}) + "\n").encode())
        await self.process.stdin.drain()
        return await future


def _forward(line):
    text = line.decode(errors="replace").replace("\x07", "").strip()
    if text:
        print(text, file=sys.stderr, flush=True)


async def forward_stderr(stream):
    # Roder's completion notification can be a bare terminal BEL. The runner merges this
    # driver's stderr into stdout; inheriting it would prefix our next JSON line with BEL and
    # make the runner drop turn/completed. Forward diagnostics only as complete, clean lines.
    # Read in chunks, never by readline: a line past the stream's limit would end this task, and an
    # undrained stderr pipe would then stall the app-server on its next write. A long line keeps its
    # first STDERR_LINE_CAP bytes and the rest is dropped up to its newline.
    line, dropping = bytearray(), False
    while chunk := await stream.read(65536):
        while chunk:
            end = chunk.find(b"\n")
            part, chunk = (chunk, b"") if end < 0 else (chunk[:end], chunk[end + 1:])
            if not dropping:
                line.extend(part[:STDERR_LINE_CAP - len(line)])
                dropping = len(line) >= STDERR_LINE_CAP
            if end >= 0:
                _forward(bytes(line))
                line, dropping = bytearray(), False
    if line:
        _forward(bytes(line))


async def stop(process):
    """End the app-server: SIGTERM, then SIGKILL if it has not gone within five seconds."""
    if process.returncode is None:
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), 5)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()


async def run(job):
    # No new process group: the runner stops a turn by killing this driver's group AND every
    # descendant it finds by parent pid (server._kill_proc_tree), which reaches the app-server and
    # the commands it runs, and the stdio MCP servers too, which mcp 1.30.0 starts in a session of
    # their own (start_new_session) and so outside the group.
    process = await asyncio.create_subprocess_exec(os.environ.get("HR_RODER_BIN", "roder"),
        "app-server", stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, limit=8 * 1024 * 1024)
    rpc = Rpc(process)
    reader = asyncio.create_task(rpc.read())
    diagnostics = asyncio.create_task(forward_stderr(process.stderr))
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
                    else:
                        # Roder fixes a thread's external tools when it starts the thread and has no
                        # call to replace them, so the conversation keeps the ones it began with. A
                        # tool among them that is not attached now (its server is unreachable this
                        # turn, or the tool was switched off) answers its calls with an error
                        # (Mcp.call); one attached since cannot reach this thread, and the turn says so.
                        started = {tool.get("name") for tool in stored["thread"].get("externalTools") or []}
                        later = sorted({server for wire, server in mcp.servers.items() if wire not in started})
                        if later:
                            quoted = ", ".join(f'"{name}"' for name in later)
                            emit({"type": "system", "subtype": "notice", "text":
                                  f"This conversation keeps the MCP tools it started with, so tools added "
                                  f"since from {quoted} are not available in it. A new session has them."})
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
                elif method in ("thread/approvalRequested", "thread/userInputRequested", "thread/planExitRequested"):
                    raise RuntimeError("Roder requested approval or interactive input in a non-interactive turn")
                else:
                    for event in events.notification(method, p):
                        emit(event)
    finally:
        await stop(process)
        reader.cancel()
        await asyncio.gather(reader, diagnostics, return_exceptions=True)


def main():
    try:
        # Out of the environment before anything starts: the job carries MCP servers' bearer headers
        # and stdio servers' env, and the app-server, every command the agent runs and every stdio
        # MCP server would otherwise inherit it (server._driver_cmd; every driver pops it the same way).
        job = json.loads(os.environ.pop("HR_DRIVER_JOB"))
        asyncio.run(run(job))
        return 0
    except Exception as error:
        emit({"type": "result", "subtype": "error", "is_error": True, "result": str(error)})
        return 1


if __name__ == "__main__":
    sys.exit(main())
