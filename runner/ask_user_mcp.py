"""The `ask_user` tool, served to a base over stdio MCP (UHP Tasks §3.2, issue #476).

A harness that needs one answer from the person — a choice, a confirmation, a value it must not
guess, a secret it must not invent — calls this tool. The tool itself does nothing but say the
question was accepted: the runner, which reads every tool call and its result in the base's stream,
ends the turn at the result (`_run_turn_bg`, `_stop == "input_required"`), and the gateway reports
the turn `incomplete` with reason `input_required` and the question as an `input_request` item. The
answer arrives as the next turn's message, on the same conversation, through the base's own resume.

Nothing waits inside the tool, on purpose: a wait can last days, and a process held open that long
is a sandbox held open that long. The turn ends on the runner's decision, not on the model's
cooperation — a model that goes on working after the call is stopped all the same.

Stdlib only, with no MCP SDK: this runs as the session's own uid inside the sandbox, where the
runner's environment is not the agent's, and the protocol needed here is three methods.

    python3 ask_user_mcp.py        # speaks MCP over stdin/stdout (Claude Code: `--mcp-config`)
"""
from __future__ import annotations

import json
import math
import sys
import time

TOOL_NAME = "ask_user"
KINDS = ("choice", "confirm", "free_text", "secret")
# What the person is told about the tool: the model reads this, and it has to say when to ask and
# that the turn ends at the call, or the model asks in prose and goes on guessing.
DESCRIPTION = (
    "Ask the person one question and stop. Use it when the task cannot go on without their answer: "
    "a choice between alternatives, a confirmation before an action that cannot be undone, a value "
    "you must not guess, or a secret you must never invent or store. Your turn ends the moment you "
    "call it; do nothing after the call. The person's answer arrives as your next message.")
INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": list(KINDS),
                 "description": "choice: pick one of `options`. confirm: yes or no. free_text: any "
                                "text. secret: a credential, given to you without entering the "
                                "conversation."},
        "prompt": {"type": "string", "description": "The question, as the person will read it."},
        "options": {"type": "array", "description": "For `choice`: the alternatives.",
                    "items": {"type": "object",
                              "properties": {"id": {"type": "string"}, "label": {"type": "string"}},
                              "required": ["id", "label"]}},
        "expires_in_seconds": {"type": "integer", "minimum": 1,
                               "description": "Optional: how long the question stands."},
    },
    "required": ["kind", "prompt"],
}
_MAX_PROMPT = 4000
_MAX_OPTIONS = 32
_MAX_OPTION = 200


def validate_request(inp, now: float | None = None) -> tuple[dict | None, str]:
    """The model's arguments as the protocol's `input_request` fields, or why they cannot be.

    → ({kind, prompt, options?, expires_at?}, "") or (None, reason). The request a client reads
    is the gateway's (it adds the id); this is what the runner reports beside the turn's reason.
    A `confirm` with no options gets yes and no, and one with options needs at least two: a question
    with one answer asks nothing. A `choice` needs at least two, each with an id and a label, the ids
    distinct. An error goes back to the model as the tool's error, so it asks
    again properly; it does not end the turn."""
    if not isinstance(inp, dict):
        return None, "arguments must be an object"
    kind = str(inp.get("kind") or "").strip()
    if kind not in KINDS:
        return None, f"kind must be one of {', '.join(KINDS)}"
    prompt = inp.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return None, "prompt must be a non-empty string"
    prompt = prompt.strip()[:_MAX_PROMPT]
    req: dict = {"kind": kind, "prompt": prompt}
    raw = inp.get("options")
    options: list[dict] = []
    if raw is not None:
        if not isinstance(raw, list) or len(raw) > _MAX_OPTIONS:
            return None, f"options must be a list of at most {_MAX_OPTIONS}"
        for o in raw:
            if isinstance(o, str):
                o = {"id": o, "label": o}
            if not isinstance(o, dict):
                return None, "each option is an object with id and label"
            oid, label = str(o.get("id") or "").strip(), str(o.get("label") or "").strip()
            if not oid or not label:
                return None, "each option needs an id and a label"
            options.append({"id": oid[:_MAX_OPTION], "label": label[:_MAX_OPTION]})
        if len({o["id"] for o in options}) != len(options):
            return None, "option ids must be distinct"
    if kind == "choice":
        if len(options) < 2:
            return None, "a choice needs at least two options"
        req["options"] = options
    elif kind == "confirm":
        if len(options) == 1:
            return None, "a confirm offers both answers, or no options for yes and no"
        req["options"] = options or [{"id": "yes", "label": "Yes"}, {"id": "no", "label": "No"}]
    elif options:
        return None, f"a {kind} question takes no options"
    ttl = inp.get("expires_in_seconds")
    if ttl is not None:
        if not isinstance(ttl, (int, float)) or isinstance(ttl, bool) or not math.isfinite(ttl) or ttl < 1:
            return None, "expires_in_seconds must be a positive number"
        req["expires_at"] = int((now if now is not None else time.time()) + ttl)
    return req, ""


def _send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _tool_result(text: str, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def serve(stdin=None) -> None:
    """One MCP server over newline-delimited JSON-RPC: initialize, tools/list, tools/call."""
    for line in (stdin or sys.stdin):
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        mid, method = msg.get("id"), msg.get("method")
        if method == "initialize":
            _send({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                "serverInfo": {"name": "harnessrouter", "version": "1"}}})
        elif method == "tools/list":
            _send({"jsonrpc": "2.0", "id": mid, "result": {"tools": [
                {"name": TOOL_NAME, "description": DESCRIPTION, "inputSchema": INPUT_SCHEMA}]}})
        elif method == "tools/call":
            params = msg.get("params") or {}
            if params.get("name") != TOOL_NAME:
                _send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "unknown tool"}})
                continue
            req, why = validate_request(params.get("arguments"))
            if req is None:
                _send({"jsonrpc": "2.0", "id": mid, "result": _tool_result(f"ask_user: {why}", True)})
            else:
                # No prose for the model to interpret: the turn ends here, by the runner's hand.
                _send({"jsonrpc": "2.0", "id": mid,
                       "result": _tool_result(json.dumps({"status": "input_required"}))})
        elif mid is not None:        # a request this server does not serve (a notification is ignored)
            _send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found"}})


if __name__ == "__main__":
    serve()
