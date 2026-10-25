"""A fake ACP agent, so the driver's own conversation can be tested without a provider.

It answers the five methods dcode's server answers and records what it was asked in
$FAKE_ACP_LOG. FAKE_ACP_MODE picks the behaviour: `ok`, `silent_end_turn` (end_turn with no
message chunk at all, which a provider really did), `ask_user` (the free-form interrupt ACP
cannot carry, answered as deepagents' server answers it), `no_load` (an agent that does not
advertise loadSession at all), `load_fails` (it does, and the session is gone), `bad_model` (the
model this turn asks for is not in the session's list), `provider_401` (a refusal in `data.details`
with a traceback on stderr at the same time), `refusal` (a stopReason that is not end_turn),
`permission` (one tool call that asks the client), `slow_exit` (takes a second to go once its input
ends) or `no_exit` (catches SIGTERM and never goes). Its pid, and that it exited, are written to
$FAKE_ACP_LOG.life.
"""
import json
import os
import signal
import sys
import time

MODE = os.environ.get("FAKE_ACP_MODE", "ok")
LOG = open(os.environ["FAKE_ACP_LOG"], "w")
LIFE = open(os.environ["FAKE_ACP_LOG"] + ".life", "w")
LIFE.write(json.dumps({"pid": os.getpid()}) + "\n"); LIFE.flush()
if MODE == "no_exit":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def note(obj):
    LOG.write(json.dumps(obj) + "\n")
    LOG.flush()


def update(sid, upd):
    send({"jsonrpc": "2.0", "method": "session/update",
          "params": {"sessionId": sid, "update": upd}})


for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if method is None:
        continue                                        # our own answer coming back
    note({"method": method, "params": params})
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": 1,
            "agentCapabilities": {"loadSession": MODE != "no_load",
                                  "promptCapabilities": {"image": True}}}})
    elif method == "session/new":
        send({"jsonrpc": "2.0", "id": mid, "result": {"sessionId": "fake-session-1"}})
    elif method == "session/load":
        if MODE in ("no_load", "load_fails"):
            send({"jsonrpc": "2.0", "id": mid,
                  "error": {"code": -32602, "message": "resource_not_found"}})
        else:
            # a loaded session REPLAYS the conversation before the prompt is sent
            update(params.get("sessionId"), {"sessionUpdate": "user_message_chunk",
                                             "content": {"type": "text", "text": "an old prompt"}})
            update(params.get("sessionId"), {"sessionUpdate": "agent_message_chunk",
                                             "content": {"type": "text", "text": "AN OLD REPLY"}})
            send({"jsonrpc": "2.0", "id": mid, "result": {"configOptions": []}})
    elif method == "session/set_config_option":
        if MODE == "bad_model":
            send({"jsonrpc": "2.0", "id": mid,
                  "error": {"code": -32602, "message": "Invalid model: %s" % params.get("value")}})
        else:
            send({"jsonrpc": "2.0", "id": mid, "result": {"configOptions": []}})
    elif method == "session/prompt":
        sid = params.get("sessionId")
        if MODE == "provider_401":
            # what a refusal really looks like: the clean sentence in data.details, and the
            # agent's own traceback on stderr at the same time
            sys.stderr.write("Traceback (most recent call last):\n")
            sys.stderr.write("  raise OpenAIAuthenticationError(\n")
            sys.stderr.write("langchain_openai.chat_models.base.OpenAIAuthenticationError: 401\n")
            sys.stderr.flush()
            send({"jsonrpc": "2.0", "id": mid, "error": {
                "code": -32603, "message": "Internal error",
                "data": {"details": "Error code: 401 - {'error': {'message': "
                                    "'Authentication failed.', 'type': 'authentication_error'}}"}}})
            continue
        if MODE == "ask_user":
            send({"jsonrpc": "2.0", "id": mid, "error": {
                "code": -32600,
                "message": ("ACP limitation: this agent raised a free-form LangGraph interrupt(), "
                            "which ACP cannot display."),
                "data": {"interrupt_value": {"type": "ask_user"}}}})
            continue
        if MODE == "permission":
            update(sid, {"sessionUpdate": "tool_call", "toolCallId": "c1", "title": "echo hi",
                         "kind": "execute", "status": "pending", "rawInput": {"command": "echo hi"}})
            send({"jsonrpc": "2.0", "id": 9001, "method": "session/request_permission",
                  "params": {"sessionId": sid, "toolCall": {"toolCallId": "c1"},
                             "options": [{"optionId": "reject-once", "kind": "reject_once",
                                          "name": "No"},
                                         {"optionId": "allow-always", "kind": "allow_always",
                                          "name": "Yes"}]}})
            update(sid, {"sessionUpdate": "tool_call_update", "toolCallId": "c1",
                         "status": "completed",
                         "content": [{"type": "content",
                                      "content": {"type": "text", "text": "hi"}}]})
        if MODE != "silent_end_turn":
            update(sid, {"sessionUpdate": "agent_message_chunk",
                         "content": {"type": "text", "text": "THE NEW ANSWER"}})
        stop = "refusal" if MODE == "refusal" else "end_turn"
        send({"jsonrpc": "2.0", "id": mid, "result": {"stopReason": stop}})
    elif mid is not None:
        send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "no"}})

# input ended: the client is done with this agent
if MODE == "no_exit":
    while True:
        time.sleep(1)
if MODE == "slow_exit":
    time.sleep(1.0)
LIFE.write(json.dumps({"exited": True}) + "\n"); LIFE.flush()
