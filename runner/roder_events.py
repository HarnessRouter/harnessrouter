"""Translate Roder typed item envelopes into the runner's canonical stream-json."""


def assistant(block):
    return {"type": "assistant", "message": {"content": [block]}}


class Events:
    def __init__(self):
        self.text = {}
        self.final = ""
        self.calls = set()
        self.completed_calls = set()
        self.finished = False

    def notification(self, method, params):
        event = params.get("event") or {}
        item = event.get("item") or {}
        kind = item.get("type")
        if event.get("type") == "itemDelta":
            delta = event.get("delta") or {}
            ident = event.get("itemId")
            text = delta.get("delta") or ""
            if delta.get("type") == "agentMessageText":
                self.text[ident] = self.text.get(ident, "") + text
                self.final = self.text[ident]
                return [assistant({"type": "text", "text": text})] if text else []
            if delta.get("type") in ("reasoningText", "reasoningSummaryText"):
                return [assistant({"type": "thinking", "thinking": text})] if text else []
        if event.get("type") in ("itemStarted", "itemCompleted"):
            ident = item.get("id")
            if kind == "agentMessage" and event["type"] == "itemCompleted":
                text = item.get("text") or ""
                seen = self.text.get(ident, "")
                self.final = text or self.final
                self.text[ident] = text
                tail = text[len(seen):] if text.startswith(seen) else text
                return [assistant({"type": "text", "text": tail})] if tail else []
            if kind == "toolExecution":
                call = item.get("toolCallId") or ident
                out = []
                if call not in self.calls:
                    self.calls.add(call)
                    out.append(assistant({"type": "tool_use", "id": call,
                        "name": item.get("toolName"), "input": item.get("input") or {}}))
                if event["type"] == "itemCompleted" and call not in self.completed_calls:
                    self.completed_calls.add(call)
                    out.append({"type": "user", "message": {"content": [{"type": "tool_result",
                        "tool_use_id": call, "content": item.get("error") or item.get("output") or "",
                        "is_error": item.get("status") == "failed"}]}})
                return out
        if method == "turn/completed":
            self.finished = True
            turn = params.get("turn") or {}
            usage = turn.get("usage") or {}
            cached = usage.get("cached_prompt_tokens", 0)
            written = usage.get("cache_creation_prompt_tokens", 0)
            error = turn.get("error")
            if isinstance(error, dict):
                error = error.get("message") or str(error)
            failed = turn.get("status") != "completed" or bool(error)
            return [{"type": "result", "subtype": "error" if failed else "success", "is_error": failed,
                "result": str(error or turn.get("status")) if failed else self.final,
                "usage": {"input_tokens": max(0, usage.get("prompt_tokens", 0) - cached - written),
                          "output_tokens": usage.get("completion_tokens", 0),
                          "cache_read_tokens": cached, "cache_write_tokens": written}}]
        return []
