"""One DeepSeek Harness turn, as a runner subprocess.

Spawned per turn by server.py (the same one-process-per-turn contract as every other backend:
the runner reads NDJSON off stdout, cancel is a process-group kill). Inside, the official
Python SDK (`deepseek-harness-sdk`, pinned) drives the bundled JSON-RPC runtime executable
(`deepseek-harness-runtime-bin`, same pinned version); every `session.event` notification is
re-emitted on stdout as one JSON line for server.py's normalizer.

THE RELAY, and why it exists. The dsh LLM adapter accumulates streamed tool calls the OpenAI
way — id from `call.id`, name from `call.function.name`, guarded by `!== undefined`. OpenAI
OMITS those fields on continuation deltas; aggregators like TokenRouter send them as EMPTY
STRINGS, so the second delta overwrites the real id/name with "" and every tool call dies as
UNKNOWN_TOOL (captured live 2026-08-20 against deepseek/deepseek-v4-flash). The relay sits on
loopback between the runtime and the endpoint and drops those empty fields from tool_call
deltas — nothing else is touched. It also means the REAL key lives only in this process: the
runtime is launched with DEEPSEEK_BASE_URL pointing at the relay and a placeholder key, so the
credential never enters the dsh process env, its session log, or anything it could checkpoint.
"""
from __future__ import annotations

import http.server
import json
import re
import os
import pathlib
import sys
import threading
import urllib.request

UPSTREAM_BASE = ""   # set in main() from HR_DSH_BASE_URL, then scrubbed from the env
UPSTREAM_KEY = ""


def _rewrite_sse_line(line: bytes) -> bytes:
    """Drop empty-string id/name from tool_call deltas in one `data:` SSE line."""
    if not line.startswith(b"data: {"):
        return line
    try:
        obj = json.loads(line[6:])
        for ch in obj.get("choices") or []:
            for tc in (ch.get("delta") or {}).get("tool_calls") or []:
                if tc.get("id") == "":
                    del tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name") == "":
                    del fn["name"]
        return b"data: " + json.dumps(obj, separators=(",", ":")).encode()
    except Exception:  # noqa: BLE001 — a line we cannot parse is a line we must not alter
        return line


# The deepseek-official adapter sends `reasoning_effort` on every request — DeepSeek's own API
# takes it, but aggregators serving deepseek/* over the OpenAI shape refuse the whole request
# (LLMTR: 'The "reasoning_effort" parameter is not supported by "deepseek/deepseek-v4-pro"',
# captured 2026-08-20 by conformance T-01). The relay retries such a rejection ONCE without the
# parameter and then strips it for the rest of the turn, so a provider that accepts it keeps it
# and one that refuses it costs one extra round trip, once. Flipped by _Relay, read per request.
_strip_reasoning_effort = False


_GOOGLE_UNKNOWN_RE = re.compile(r'Unknown name \\?"([A-Za-z_][A-Za-z0-9_]*)\\?"(?! at \')')
_drop_fields: list = []   # the top-level fields this upstream refused as unknown, dropped from then on
# Gemini 3 requires each replayed tool call's thought signature (400 "Function call is missing a
# thought_signature in functionCall parts", measured 2026-09-06); the relay reads them off the answer
# as it streams past and puts them back on the replay, Google's sentinel for a call it never saw.
_GOOGLE_SIG_SKIP = "skip_thought_signature_validator"
_GOOGLE_HOST = "generativelanguage.googleapis.com"
_google_sigs: dict = {}        # tool call id -> thought signature, this session's relay
_google_required = False       # a 400 naming thought_signature from an endpoint not recognised as Google


def _google_unknown_field(refused: bytes) -> str:
    """The top-level field Google's OpenAI-compatible endpoint refused ("Unknown name \"store\":
    Cannot find field."), or "" (a field named inside an object is not one to drop)."""
    text = refused.decode("utf-8", "replace") if isinstance(refused, (bytes, bytearray)) else str(refused)
    if "Cannot find field" not in text:
        return ""
    m = _GOOGLE_UNKNOWN_RE.search(text)
    return m.group(1) if m else ""


def _drop_top_level_fields(body: bytes, fields) -> bytes:
    try:
        obj = json.loads(body)
    except Exception:  # noqa: BLE001 — a body we cannot parse is a body we must not alter
        return body
    if not isinstance(obj, dict) or not any(f in obj for f in fields):
        return body
    for f in fields:
        obj.pop(f, None)
    return json.dumps(obj).encode()


_STRICT_GEMINI_HOST = "api.tokenrouter.com"   # TokenRouter's channels, by the upstream host
# ── Gemini function declarations through a strict channel ────────────────────────────────
# Google's native API validates function declarations against its own Schema (type, format,
# description, nullable, enum, properties, required, items, min/max, anyOf and a few more) and
# refuses anything else: "Unknown name \"$schema\" at 'tools[0].function_declarations[0].parameters'",
# "Unknown name \"exclusiveMinimum\"", "schema didn't specify the schema type field". Google's own
# OpenAI-compatible endpoint, OpenRouter and Vercel normalise a harness's JSON-schema declarations
# before they reach it; TokenRouter's Gemini channels forward them as sent, so the first turn of a
# task on opencode ($schema) and cline (exclusiveMinimum, a property without type) failed on the
# ids those channels serve natively, gemini-3.8-flash for one (measured 2026-09-06, the platform
# column). Until TokenRouter normalises them itself, this relay does, for that channel only.
_GEMINI_SCHEMA_KEYS = {"type", "format", "title", "description", "nullable", "enum", "maxItems", "minItems",
                       "properties", "required", "minProperties", "maxProperties", "minLength", "maxLength",
                       "pattern", "example", "anyOf", "propertyOrdering", "default", "items", "minimum", "maximum"}


def _gemini_schema(node):
    """One JSON schema node as Google's function-declaration validator accepts it: only the keys it
    names, `oneOf` as `anyOf`, `const` as a one-value enum, an exclusive bound as the bound, a type
    list as one type plus nullable, a type on every node (inferred from its shape when left out),
    items on every array, and `required` limited to properties that exist."""
    if not isinstance(node, dict):
        return node
    out = {}
    for k, v in node.items():
        if k == "oneOf" and isinstance(v, list):
            out.setdefault("anyOf", [_gemini_schema(x) for x in v])
        elif k == "const":
            out["enum"] = [v]
        elif k == "exclusiveMinimum" and isinstance(v, (int, float)) and not isinstance(v, bool):
            out.setdefault("minimum", v)
        elif k == "exclusiveMaximum" and isinstance(v, (int, float)) and not isinstance(v, bool):
            out.setdefault("maximum", v)
        elif k not in _GEMINI_SCHEMA_KEYS:
            continue
        elif k == "properties" and isinstance(v, dict):
            out[k] = {pk: _gemini_schema(pv) for pk, pv in v.items()}
        elif k == "items":
            out[k] = _gemini_schema(v) if isinstance(v, dict) else (_gemini_schema(v[0]) if isinstance(v, list) and v else {"type": "string"})
        elif k == "anyOf" and isinstance(v, list):
            out[k] = [_gemini_schema(x) for x in v]
        else:
            out[k] = v
    t = out.get("type")
    if isinstance(t, list):
        non_null = [x for x in t if x != "null"]
        out["type"] = non_null[0] if non_null else "string"
        if "null" in t:
            out["nullable"] = True
    if isinstance(out.get("anyOf"), list):
        # No anyOf leaves this relay: one channel refuses an anyOf node without a type ("schema
        # didn't specify the schema type field", gemini-3.5-flash) and another refuses one with
        # anything beside it ("schema specified other fields alongside any_of", gemini-3.6-flash,
        # both measured 2026-09-06 on TokenRouter). The null member becomes `nullable`; a choice of
        # constants becomes one enum; any other choice becomes its first member under the node's
        # own description, which is what the model reads.
        members = [m for m in out.pop("anyOf") if isinstance(m, dict) and m.get("type") != "null"]
        if len(members) < len(node.get("anyOf") or []):
            out["nullable"] = True
        if members and all("enum" in m and "properties" not in m and "items" not in m for m in members):
            out = {**members[0], **out, "enum": [x for m in members for x in m["enum"]]}
            out.setdefault("type", "string")
        elif members:
            out = {**members[0], **out}
            out.setdefault("type", members[0].get("type") or "string")
    if "type" not in out and "anyOf" not in out:
        out["type"] = "object" if "properties" in out else ("array" if "items" in out else "string")
    if out.get("type") == "array" and "items" not in out:
        out["items"] = {"type": "string"}
    if out.get("type") == "object" and not out.get("properties"):
        out.pop("properties", None)                 # an empty properties object is refused too
        out.pop("required", None)
    elif isinstance(out.get("required"), list) and isinstance(out.get("properties"), dict):
        req = [r for r in out["required"] if r in out["properties"]]
        if req:
            out["required"] = req
        else:
            out.pop("required")
    return out


def _with_gemini_schemas(body: bytes) -> bytes:
    """The chat request with every tool's parameters normalised for Google's validator; a tool
    that declares no parameter loses the empty declaration. A body without tools is untouched."""
    if b'"tools"' not in body:
        return body
    try:
        doc = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return body
    if not isinstance(doc, dict) or not isinstance(doc.get("tools"), list):
        return body
    changed = False
    for tool in doc["tools"]:
        fn = tool.get("function") if isinstance(tool, dict) else None
        if not isinstance(fn, dict) or not isinstance(fn.get("parameters"), dict):
            continue
        params = _gemini_schema(fn["parameters"])
        if params.get("type") == "object" and not params.get("properties"):
            fn.pop("parameters")
        else:
            fn["parameters"] = params
        changed = True
    return json.dumps(doc).encode() if changed else body


def _google_signatures_in(doc: dict) -> list:
    """The (tool call id, thought signature) pairs one answer (a chunk or a whole message) carries."""
    found = []
    for ch in doc.get("choices") or []:
        if not isinstance(ch, dict):
            continue
        holder = ch.get("delta") if isinstance(ch.get("delta"), dict) else ch.get("message")
        if not isinstance(holder, dict):
            continue
        for tc in holder.get("tool_calls") or []:
            if not isinstance(tc, dict):
                continue
            ec = tc.get("extra_content")
            sig = ((ec or {}).get("google") or {}).get("thought_signature") if isinstance(ec, dict) else None
            cid = tc.get("id")
            if isinstance(sig, str) and sig and isinstance(cid, str) and cid:
                found.append((cid, sig))
    return found


def _google_signatures_in_line(line: bytes) -> list:
    """The signatures one SSE line carries; a line without one costs a substring check."""
    if not line.startswith(b"data:") or b"thought_signature" not in line:
        return []
    try:
        doc = json.loads(line[5:].strip())
    except ValueError:
        return []
    return _google_signatures_in(doc) if isinstance(doc, dict) else []


def _google_with_signatures(body: bytes, sigs: dict) -> bytes:
    """The request with every replayed assistant tool call carrying a thought signature: the one
    this relay saw on the answer, else Google's sentinel. A body without tool calls is untouched."""
    if b"tool_calls" not in body:
        return body
    try:
        doc = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return body
    if not isinstance(doc, dict) or not isinstance(doc.get("messages"), list):
        return body
    changed = False
    for msg in doc["messages"]:
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls") or []:
            if not isinstance(tc, dict):
                continue
            ec = tc.get("extra_content")
            if isinstance(ec, dict) and isinstance(ec.get("google"), dict) and ec["google"].get("thought_signature"):
                continue
            cid = str(tc.get("id") or "")
            tc["extra_content"] = {"google": {"thought_signature": sigs.get(cid) or _GOOGLE_SIG_SKIP}}
            changed = True
    return json.dumps(doc).encode() if changed else body


def _drop_reasoning_effort(body: bytes) -> bytes:
    try:
        obj = json.loads(body)
        if isinstance(obj, dict) and "reasoning_effort" in obj:
            del obj["reasoning_effort"]
            return json.dumps(obj, separators=(",", ":")).encode()
    except Exception:  # noqa: BLE001 — a body we cannot parse is a body we must not alter
        pass
    return body


class _Relay(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):  # noqa: N802
        global _strip_reasoning_effort, _google_required
        body = self.rfile.read(int(self.headers.get("content-length") or 0))
        # The adapters' base URLs point at this relay and they append their own API paths
        # (/v1/chat/completions, /v1/responses, /v1/messages); the upstream base ends in /v1 —
        # join without doubling.
        tail = self.path.removeprefix("/v1") if self.path.startswith("/v1/") else self.path
        # Forward protocol headers (anthropic-version et al) verbatim; strip hop/auth/length.
        drop = {"host", "content-length", "authorization", "x-api-key", "connection",
                "accept-encoding", "transfer-encoding"}
        headers = {k: v for k, v in self.headers.items() if k.lower() not in drop}
        headers["authorization"] = f"Bearer {UPSTREAM_KEY}"
        headers["x-api-key"] = UPSTREAM_KEY   # the anthropic-messages spelling; harmless elsewhere
        headers.setdefault("accept", "*/*")
        if _strip_reasoning_effort:
            body = _drop_reasoning_effort(body)
        if _drop_fields:
            body = _drop_top_level_fields(body, _drop_fields)
        google = _GOOGLE_HOST in UPSTREAM_BASE or _google_required
        if google and tail.endswith("/chat/completions"):
            body = _google_with_signatures(body, _google_sigs)
        if _STRICT_GEMINI_HOST in UPSTREAM_BASE and tail.endswith("/chat/completions") and b"gemini" in body:
            try:
                _model = str((json.loads(body) or {}).get("model") or "")
            except (ValueError, AttributeError):
                _model = ""
            if "gemini" in _model.lower():
                body = _with_gemini_schemas(body)   # TokenRouter's Gemini channels forward tool schemas to Google's validator as sent
        resp = None
        for attempt in (0, 1, 2):
            req = urllib.request.Request(UPSTREAM_BASE.rstrip("/") + tail,
                                         data=body, method="POST", headers=headers)
            try:
                resp = urllib.request.urlopen(req, timeout=600)
                break
            except urllib.error.HTTPError as e:
                data = e.read()
                stripped = _drop_reasoning_effort(body)
                if attempt < 2 and b"reasoning_effort" in data and stripped != body:
                    _strip_reasoning_effort = True
                    body = stripped
                    continue
                if google and e.code == 400:
                    # the harness shows this as "400 (no body)"; the refusal is here
                    print(f"[dsh relay] google refused {tail}: {data[:300]!r}", flush=True)
                if attempt < 2 and e.code == 400 and b"thought_signature" in data and not _google_required:
                    # a Gemini 3 endpoint this relay did not recognise as Google names the need itself
                    _google_required = True
                    google = True
                    body = _google_with_signatures(body, _google_sigs)
                    continue
                unknown = _google_unknown_field(data) if e.code == 400 else ""
                if attempt < 2 and unknown and unknown not in _drop_fields:
                    # Google's OpenAI-compatible endpoint refuses any field it does not know (dsh
                    # sends OpenAI's optional store and seed; measured 2026-09-06). The refusal
                    # names the field: drop it, remember it, send again.
                    _drop_fields.append(unknown)
                    body = _drop_top_level_fields(body, _drop_fields)
                    continue
                # pass provider errors through verbatim
                self.send_response(e.code)
                self.send_header("content-type", e.headers.get("content-type") or "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
        ctype = resp.headers.get("content-type") or ""
        # The empty-string id/name quirk is a chat-completions stream shape; other protocols
        # (anthropic-messages, openai-responses) pass through byte-faithful.
        rewrite = self.path.endswith("/chat/completions")
        self.send_response(resp.status)
        self.send_header("content-type", ctype)
        if "text/event-stream" in ctype:
            self.send_header("transfer-encoding", "chunked")
            self.end_headers()
            buf = b""
            while True:
                chunk = resp.read(4096)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if google:
                        for cid, sig in _google_signatures_in_line(line.strip()):
                            _google_sigs[cid] = sig
                    out = (_rewrite_sse_line(line.rstrip(b"\r")) if rewrite else line.rstrip(b"\r")) + b"\n"
                    self.wfile.write(f"{len(out):x}\r\n".encode() + out + b"\r\n")
                self.wfile.flush()
            if buf:
                out = _rewrite_sse_line(buf) if rewrite else buf
                self.wfile.write(f"{len(out):x}\r\n".encode() + out + b"\r\n")
            self.wfile.write(b"0\r\n\r\n")
        else:
            data = resp.read()
            if google and b"thought_signature" in data:
                try:
                    doc = json.loads(data)
                except ValueError:
                    doc = None
                if isinstance(doc, dict):
                    _google_sigs.update(_google_signatures_in(doc))
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    def log_message(self, *a):  # diagnostics belong on stderr, never stdout
        pass


def _emit(method: str, payload) -> None:
    sys.stdout.write(json.dumps({"m": method, "p": payload}, default=str) + "\n")
    sys.stdout.flush()


# Whether the PINNED runtime wheel bundles @deepseek-ai/dsh-mcp-client. rc7 does NOT — the
# upstream sdk-runtime README already documents the plugin as bundled, but the wheel predates
# it: naming the entry makes the plugin tree fail, and a failed tree leaves the runtime alive
# with a mute stdout, which reads as a hang (measured: the initialize response simply never
# comes). Flip this when the wheel pin moves to a build that ships the plugin — and re-verify.
DSH_RUNTIME_HAS_MCP = False


def _compose_cordis(home: pathlib.Path, servers: list[dict], llm: dict | None = None,
                    relay_port: int = 0, model: str = "") -> str:
    """Our runtime composition: the wheel's bundled default, with the SDK server entry swapped
    for the resume-or-create subclass (see hr_dsh_server.cjs — packaged-bin loads
    configuration-relative plugins), plus one dsh-mcp-client entry per enabled MCP server."""
    import deepseek_harness_runtime as runtime
    base = pathlib.Path(runtime.bundled_default_config_path()).read_text()
    needle = "name: '@deepseek-ai/dsh-sdk-jsonrpc-server'"
    if base.count(needle) != 1:
        raise SystemExit("dsh bundled cordis no longer names the sdk server exactly once — "
                         "re-verify hr_dsh_server.cjs against this runtime before shipping")
    base = base.replace(needle, "name: './hr_dsh_server.cjs'")
    blocks = []
    for i, s in enumerate(servers):
        url = (s or {}).get("url")
        if not url:
            continue
        name = "".join(c for c in str((s or {}).get("name") or f"mcp{i}") if c.isalnum() or c in "_-")[:32] or f"mcp{i}"
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
        blocks.append(entry)
    if llm:
        # Non-deepseek families ride dsh's OWN multi-provider layer, dsh-llm-pi-ai — which is
        # pi's unified LLM library wrapped as a Cordis plugin, so the api-by-family choices are
        # literally the ones the pi backend already proved. The route points at the loopback
        # relay; apiKeyEnv resolves a placeholder, and the relay injects the real credential
        # upstream — same isolation as the deepseek path.
        api = llm.get("api") or "openai-completions"
        # The same /v1 lesson the pi backend already paid for: the anthropic-messages client
        # appends /v1/messages to its base itself, the openai clients want /v1 present. Getting
        # it wrong here produced /v1/v1/messages against the relay — measured, not guessed.
        base_url = (f"http://127.0.0.1:{relay_port}" if api == "anthropic-messages"
                    else f"http://127.0.0.1:{relay_port}/v1")
        blocks.append({"id": "hr-llm", "name": "@deepseek-ai/dsh-llm-pi-ai", "config": {
            "providers": {"hr": {
                "displayName": "HR Gateway",
                "apiKeyEnv": "HR_RELAY_TOKEN",
                "api": api,
                "baseURL": base_url,
                "models": [{"id": model, "contextWindow": 200000, "maxTokens": 32000,
                            "input": (["text", "image"] if llm.get("vision", True) else ["text"])}],
            }}}})
    path = home / ".dsh" / "cordis.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copy(pathlib.Path(__file__).with_name("hr_dsh_server.cjs"), path.parent / "hr_dsh_server.cjs")
    extra = ""
    if blocks:
        import yaml
        extra = "\n" + yaml.safe_dump(blocks, sort_keys=False)
    path.write_text(base + extra)
    return str(path)


def main() -> int:
    global UPSTREAM_BASE, UPSTREAM_KEY
    job = json.loads(sys.argv[1])
    UPSTREAM_BASE = os.environ.pop("HR_DSH_BASE_URL", "")
    UPSTREAM_KEY = os.environ.pop("HR_DSH_API_KEY", "")
    home = pathlib.Path(os.environ.get("HOME") or ".")
    cwd = job.get("cwd") or os.getcwd()
    sessions = home / ".dsh" / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Relay)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    os.environ["DEEPSEEK_BASE_URL"] = f"http://127.0.0.1:{srv.server_address[1]}/v1"
    os.environ["DEEPSEEK_API_KEY"] = "hr-relay"   # the real key never reaches the runtime

    from deepseek_harness import DeepSeekHarness

    os.environ["HR_RELAY_TOKEN"] = "hr-relay"   # the placeholder the pi-ai route resolves
    mcp = job.get("mcp_servers") or []
    if mcp and not DSH_RUNTIME_HAS_MCP:
        # The pi precedent: a capability the harness asked for but this build cannot provide is
        # SAID, and the turn still runs — a loud line beats a task wedged on a mute runtime.
        print("[dsh] MCP servers are configured on this harness, but the pinned DeepSeek Harness "
              "runtime (0.1.0rc7) does not bundle its MCP client yet — this turn runs without "
              "them. The next runtime pin restores them.", flush=True)
        mcp = []
    llm = job.get("llm")   # None => the verified deepseek-official path
    kwargs = dict(provider=("hr" if llm else "deepseek-official"), model=job["model"],
                  cwd=cwd, session_root=str(sessions),
                  cordis=_compose_cordis(home, mcp, llm=llm,
                                         relay_port=srv.server_address[1], model=job["model"]),
                  # A runtime whose plugin tree failed stays alive with a mute stdout; without a
                  # bound the initialize request waits forever and the turn reads as a hang.
                  request_timeout_seconds=180.0)
    sid = job.get("session_id") or None
    _emit("__hr_init", {"session_id": sid or "", "relay_port": srv.server_address[1]})
    with DeepSeekHarness(**kwargs) as h:
        r = h.run(job["prompt"], session_id=sid,
                  on_notification=lambda n: _emit(getattr(n, "method", ""), getattr(n, "payload", None)))
        _emit("__hr_result", {"final": r.final_response or "", "reason": r.finish_reason,
                              "session_id": r.session_id})
    return 0


if __name__ == "__main__":
    sys.exit(main())
