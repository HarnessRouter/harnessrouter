"""A fake `agy acp`, answering the way agy 1.5.8's ACP server answered on a Gemini API key (2026-11-13).

The shapes are the recorded ones (tool_call with `name`, `args`, `kind`, `title`, `rawInput`; the
completed update's `rawOutput` and `content`; a permission request with string id and the options
"allow"/allow_once and "deny"/reject_once; the prompt's result with `usage`), so the driver is tested
against what the CLI really sends. It records what it was asked in $FAKE_AGY_LOG, its own environment
in $FAKE_AGY_LOG.env, and its argv in $FAKE_AGY_LOG.argv. FAKE_AGY_MODE: `ok` (a write, a shell command
that asks first, an MCP call, then the answer), `thinking` (an answer that thought; `apart` reports the
thinking beside the output instead of inside it), `bad_model` (set_model refused), `load_fails` (the
stored session will not load), `silent` (end_turn with nothing said).
"""
import json
import os
import sys

MODE = os.environ.get("FAKE_AGY_MODE", "ok")
LOG = open(os.environ["FAKE_AGY_LOG"], "w")
with open(os.environ["FAKE_AGY_LOG"] + ".env", "w") as fh:
    json.dump(dict(os.environ), fh)
with open(os.environ["FAKE_AGY_LOG"] + ".argv", "w") as fh:
    json.dump(sys.argv, fh)
SID = "45233099-b000-438c-90c0-c5896a1c8f6d"


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def note(obj):
    LOG.write(json.dumps(obj) + "\n")
    LOG.flush()


def update(upd):
    send({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": SID, "update": upd}})


def ask_permission(call):
    """agy's own request, with a STRING id, answered before anything else is read."""
    send({"jsonrpc": "2.0", "id": "1", "method": "session/request_permission",
          "params": {"sessionId": SID, "toolCall": {**call, "status": "pending"},
                     "options": [{"optionId": "allow", "name": "Allow", "kind": "allow_once"},
                                 {"optionId": "deny", "name": "Deny", "kind": "reject_once"}]}})
    for raw in sys.stdin:
        reply = json.loads(raw)
        if reply.get("id") == "1" and reply.get("method") is None:
            note({"asked_client": "session/request_permission", "reply": reply})
            return ((reply.get("result") or {}).get("outcome") or {}).get("optionId") == "allow"
    return False


def tool(cid, name, args, kind, title, output=None, raw_output=None, ask=False, diff=None):
    call = {"sessionUpdate": "tool_call", "toolCallId": cid, "name": name, "args": args, "status": "in_progress",
            "kind": kind, "title": title, "rawInput": args}
    update(call)
    if ask and not ask_permission(call):
        update({**call, "sessionUpdate": "tool_call_update", "status": "failed", "rawOutput": {"output": ""},
                "content": [{"type": "content", "content": {"type": "text", "text": ""}}]})
        return False
    done = {**call, "sessionUpdate": "tool_call_update", "status": "completed",
            "rawOutput": raw_output if raw_output is not None else {}}
    if output is not None:
        done["content"] = [{"type": "content", "content": {"type": "text", "text": output}}]
    if diff is not None:
        done["content"] = [{"type": "diff", "path": args.get("Path"), "newText": diff}]   # a write reports its diff
    update(done)
    return True


for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if method is None:
        continue
    note({"method": method, "params": params})
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": 1,
            "agentCapabilities": {"loadSession": True, "promptCapabilities": {"image": True, "audio": False,
                                                                             "embeddedContext": True}},
            "agentInfo": {"name": "Antigravity ACP Server", "version": "1.5.8"}}})
    elif method == "session/new":
        send({"jsonrpc": "2.0", "id": mid, "result": {"sessionId": SID, "models": {
            "currentModelId": "gemini-3.1-pro-low",
            "availableModels": [{"modelId": "gemini-3.8-flash-low", "name": "Gemini 3.8 Flash (Low)"}]}}})
    elif method == "session/load":
        if MODE == "load_fails":
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "conversation not found"}})
            continue
        # a loaded conversation is replayed as updates before the prompt is sent
        update({"sessionUpdate": "user_message_chunk", "content": {"type": "text", "text": "an old prompt"}})
        update({"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "AN OLD REPLY"}})
        send({"jsonrpc": "2.0", "id": mid, "result": {}})
    elif method == "session/set_model":
        if MODE == "bad_model":
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32602,
                                                         "message": "model %s is not recognized" % params.get("modelId")}})
        else:
            send({"jsonrpc": "2.0", "id": mid, "result": {}})
    elif method == "session/prompt":
        update({"sessionUpdate": "usage_update", "used": 0, "size": 1048576})
        update({"sessionUpdate": "session_info_update", "title": "A Title"})
        if MODE == "silent":
            send({"jsonrpc": "2.0", "id": mid, "result": {"stopReason": "end_turn", "usage": {
                "inputTokens": 10, "outputTokens": 0, "cachedReadTokens": 0, "cachedWriteTokens": 0,
                "thoughtTokens": 0, "totalTokens": 10}}})
            continue
        if MODE in ("thinking", "apart"):
            update({"sessionUpdate": "agent_thought_chunk", "content": {"type": "text", "text": "counting"}})
            update({"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "21"}})
            usage = ({"inputTokens": 8254, "outputTokens": 2973, "cachedReadTokens": 0, "cachedWriteTokens": 0,
                      "thoughtTokens": 2825, "totalTokens": 11227} if MODE == "thinking" else
                     {"inputTokens": 8254, "outputTokens": 148, "cachedReadTokens": 0, "cachedWriteTokens": 0,
                      "thoughtTokens": 2825, "totalTokens": 11227})
            send({"jsonrpc": "2.0", "id": mid, "result": {"stopReason": "end_turn", "usage": usage}})
            continue
        tool("call_1", "write_file", {"Content": "alpha", "Path": os.path.join(params.get("cwd") or os.getcwd(), "a.txt")},
             "edit", "File a.txt", diff="alpha\n")
        ran = tool("call_2", "run_command", {"CommandLine": "cat a.txt", "WaitMsBeforeAsync": 5000},
                   "execute", "cat a.txt", output="Command exited with code 0.\n\nCommand output:\nalpha",
                   raw_output={"output": "Command output:\nalpha", "exit_code": 0}, ask=True)
        if not ran:
            # agy ends the turn at a refused command: the rest of the batch fails and nothing is said
            update({"sessionUpdate": "tool_call", "toolCallId": "call_3", "name": "search_web",
                    "args": {"query": "x"}, "status": "failed", "kind": "search", "title": '"x" on Web'})
            send({"jsonrpc": "2.0", "id": mid, "result": {"stopReason": "end_turn", "usage": {
                "inputTokens": 8743, "outputTokens": 144, "cachedReadTokens": 0, "cachedWriteTokens": 0,
                "thoughtTokens": 0, "totalTokens": 8887}}})
            continue
        tool("call_4", "call_mcp_tool", {"Arguments": {}, "ServerName": "probe_http", "ToolName": "lucky_number"},
             "execute", "MCP Tool lucky_number", output="4711", raw_output="4711")
        update({"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "alpha and "}})
        update({"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "4711"}})
        send({"jsonrpc": "2.0", "id": mid, "result": {"stopReason": "end_turn", "usage": {
            "inputTokens": 13579, "outputTokens": 306, "cachedReadTokens": 13949, "cachedWriteTokens": 0,
            "thoughtTokens": 0, "totalTokens": 27834}}})
    else:
        send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found"}})
