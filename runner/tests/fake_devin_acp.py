#!/usr/bin/env python3
import json
import sys


def send(obj):
    print(json.dumps(obj), flush=True)


def main():
    init = json.loads(input())
    assert init["method"] == "initialize"
    send({"jsonrpc": "2.0", "id": init["id"],
          "result": {"protocolVersion": 1,
                     "agentCapabilities": {"session": {"resume": True}},
                     "authMethods": [{"id": "fake-auth", "name": "Fake", "description": ""}]}})
    initialized = json.loads(input())
    assert initialized["method"] == "initialized"

    auth_req = json.loads(input())
    assert auth_req["method"] == "authenticate"
    send({"jsonrpc": "2.0", "id": auth_req["id"], "result": {}})

    session_req = json.loads(input())
    session_id = "sess-fake-123"
    if session_req["method"] == "session/resume":
        session_id = session_req["params"]["sessionId"]
    else:
        send({"jsonrpc": "2.0", "id": session_req["id"],
              "result": {"sessionId": session_id}})

    prompt_req = json.loads(input())
    assert prompt_req["method"] == "session/prompt"
    # Stream a couple of updates
    send({"jsonrpc": "2.0", "method": "session/update",
          "params": {"sessionId": session_id, "type": "agent_message_chunk",
                     "content": [{"type": "text", "text": "Fake "}]}})
    send({"jsonrpc": "2.0", "method": "session/update",
          "params": {"sessionId": session_id, "type": "agent_message_chunk",
                     "content": [{"type": "text", "text": "Devin"}]}})
    send({"jsonrpc": "2.0", "id": prompt_req["id"],
          "result": {"stopReason": "end_turn"}})


if __name__ == "__main__":
    main()
