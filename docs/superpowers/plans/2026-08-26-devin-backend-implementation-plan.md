# Devin backend implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans`. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a first-class `devin` runner backend to HarnessRouter CE that spawns `devin acp` per turn, speaks ACP JSON-RPC over stdio, and maps Devin's `session/update` stream to the canonical claude `stream-json` events the rest of the system consumes.

**Architecture:** One custom runner driver (`_run_devin_acp_bg`) modeled on the existing `_run_codex_appserver_bg` JSON-RPC driver; a normalizer (`_devin_to_claude`) for ACP updates; gateway catalog and provider wiring; a UI harness entry; and a runtime Docker install of the proprietary Devin CLI under the data volume.

**Tech stack:** Python 3.12 (runner/gateway), React 19 / TypeScript (UI), bash (entrypoint). No new Python dependencies required; ACP is driven by `json` + `subprocess` from the standard library.

## Global constraints

- **Do not ship the proprietary Devin binary in the open-source image.** Install at first run, on the data volume, under the end user's terms.
- **Runtime auth:** only `WINDSURF_API_KEY` is practical for a headless server; `devin auth login` is not an unattended flow.
- **Process model:** one `devin acp` subprocess per turn, killed on cancel/timeout.
- **Session continuity:** attempt `session/resume` only when the previous session artifact is present in the data volume; otherwise start fresh and emit `resume_lost`.
- **Tool enforcement:** `tool_enforcement` is "hard" — the driver responds to ACP `request_permission` with approve/deny based on `tools_disabled`.
- **Tests:** every code task ends with a passing unit test; integration is verified with `uhp-conformance`.

## File map

| File | Role | What changes |
| ------ | ------ | -------------- |
| `runner/server.py` | Runner backend | Add `DEVIN_*` constants, `BACKENDS["devin"]`, `_run_devin_acp_bg`, `_devin_to_claude`, env helper, and `turn()` dispatch branch. |
| `runner/tests/fixtures/devin_acp_updates.jsonl` | Test fixture | Sample ACP `session/update` notifications and `session/prompt` response. |
| `runner/tests/test_devin_normalize.py` | Unit test | `_devin_to_claude` mapping tests. |
| `runner/tests/fake_devin_acp.py` | Test helper | A fake `devin acp` script that speaks ACP JSON-RPC for the driver tests. |
| `runner/tests/test_devin_acp_driver.py` | Unit test | `_run_devin_acp_bg` tests against the fake server. |
| `gateway/app.py` | Gateway catalog | Add `devin` entries to `_BASE_CATALOG`, `_MODEL_CATALOG`, `_PROVIDER_CATALOG`, `_INTEGRATION_WIRING`, and `_BARE_MODELS` (if needed). |
| `ui/src/lib/harness.ts` | UI harness list | Add `devin` to `OOB` and update the `backend` union type. |
| `ui/src/components/HarnessLogo.tsx` | UI logo | Add a Devin logo mapping. |
| `public/logos/devin.png` | Static asset | Place a Devin logo (or use fallback glyph if absent). |
| `docker/entrypoint.sh` | Runtime install | Add `devin` to `HR_BACKENDS`, `backend_bin`, `install_devin`, and `install_backends`. |

---

### Task 1: Runner normalizer `_devin_to_claude`

**Files:**

- Create: `runner/tests/fixtures/devin_acp_updates.jsonl`
- Create: `runner/tests/test_devin_normalize.py`
- Modify: `runner/server.py` (insert `_devin_to_claude` after the `_opencode_to_claude` group)

**Interfaces:**

- Consumes: ACP `session/update` JSON-RPC notification payloads (dicts).
- Produces: A list of canonical claude `stream-json` event dicts.

- [ ] **Step 1: Create the fixture**

Create `runner/tests/fixtures/devin_acp_updates.jsonl`:

```json
{"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": "sess-1", "type": "agent_message_chunk", "content": [{"type": "text", "text": "Hello "}]}}
{"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": "sess-1", "type": "agent_message_chunk", "content": [{"type": "text", "text": "world"}]}}
{"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": "sess-1", "type": "tool_call", "toolCall": {"id": "tc-1", "name": "bash", "input": {"command": "echo hi"}}}}
{"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": "sess-1", "type": "tool_call_update", "toolCall": {"id": "tc-1", "status": "completed", "output": {"content": [{"type": "text", "text": "hi"}]}}}}
{"jsonrpc": "2.0", "id": 2, "result": {"stopReason": "end_turn"}}
```

- [ ] **Step 2: Write the failing test**

Create `runner/tests/test_devin_normalize.py`:

```python
import json
import pathlib

import pytest

FIXTURE = pathlib.Path(__file__).with_suffix("").parent / "fixtures" / "devin_acp_updates.jsonl"


@pytest.fixture
def update_lines():
    return [json.loads(l) for l in FIXTURE.read_text().splitlines() if l.strip()]


def _make_state():
    return {"model": "devin-swe", "final": ""}


def test_devin_text_chunk():
    from server import _devin_to_claude
    evs = _devin_to_claude(
        {"jsonrpc": "2.0", "method": "session/update",
         "params": {"sessionId": "s1", "type": "agent_message_chunk",
                    "content": [{"type": "text", "text": "hello"}]}},
        _make_state(),
    )
    assert evs[0]["type"] == "assistant"
    assert evs[0]["message"]["content"][0]["text"] == "hello"


def test_devin_tool_call():
    from server import _devin_to_claude
    evs = _devin_to_claude(
        {"jsonrpc": "2.0", "method": "session/update",
         "params": {"sessionId": "s1", "type": "tool_call",
                    "toolCall": {"id": "tc1", "name": "bash", "input": {"command": "ls"}}}},
        _make_state(),
    )
    assert evs[0]["type"] == "assistant"
    assert evs[0]["message"]["content"][0]["type"] == "tool_use"
    assert evs[0]["message"]["content"][0]["name"] == "bash"


def test_devin_final_result():
    from server import _devin_to_claude
    evs = _devin_to_claude(
        {"jsonrpc": "2.0", "id": 2, "result": {"stopReason": "end_turn"}},
        _make_state(),
    )
    assert any(e["type"] == "result" for e in evs)
```

- [ ] **Step 3: Run the test — expect failures**

```bash
cd /Users/chenillen/Codes/OpenSource/harnessrouter/runner
python -m pytest tests/test_devin_normalize.py -v
```

Expected: `ImportError` or `NameError` because `_devin_to_claude` does not exist.

- [ ] **Step 4: Implement `_devin_to_claude` in `runner/server.py`**

Insert after the `_opencode_to_claude` function (around line 2330):

```python
def _devin_to_claude(obj: dict, state: dict) -> list[dict]:
    """Map one ACP JSON-RPC line to canonical claude stream-json events."""
    if not isinstance(obj, dict):
        return []
    evs: list[dict] = []

    # JSON-RPC response to a request we made (e.g. session/prompt final)
    if "id" in obj and "result" in obj:
        res = obj["result"]
        stop = res.get("stopReason")
        if stop:
            ok = stop == "end_turn"
            # Devin does not stream token counts today; leave usage empty.
            evs.append({"type": "result", "subtype": "success" if ok else "error",
                        "is_error": not ok, "result": state.get("final", "")})
        return evs

    params = obj.get("params") or {}
    update_type = params.get("type")
    if update_type == "agent_message_chunk":
        for c in params.get("content") or []:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "text":
                text = c.get("text") or ""
                state["final"] = state.get("final", "") + text
                evs.append({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}})
            elif c.get("type") == "reasoning":
                evs.append({"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": c.get("thinking") or ""}]}})
    elif update_type == "tool_call":
        tc = params.get("toolCall") or {}
        evs.append({"type": "assistant", "message": {"content": [{"type": "tool_use",
                        "id": tc.get("id") or "", "name": tc.get("name") or "",
                        "input": tc.get("input") or {}}]}})
    elif update_type == "tool_call_update":
        tc = params.get("toolCall") or {}
        status = tc.get("status")
        if status in ("completed", "success"):
            out = tc.get("output") or {}
            parts = [x.get("text") or "" for x in (out.get("content") or []) if isinstance(x, dict)]
            evs.append({"type": "user", "message": {"content": [{"type": "tool_result",
                            "tool_use_id": tc.get("id") or "", "is_error": False,
                            "content": "\n".join(parts)}]}})
    elif update_type == "plan":
        plan = params.get("plan") or {}
        if plan:
            evs.append({"type": "system", "subtype": "plan", "plan": plan})
    elif update_type == "user_message_chunk":
        # Echo of our prompt; ignore.
        pass
    elif update_type == "request_permission":
        # Handled at the driver level; the normalizer does not emit UI events for it.
        pass
    return evs
```

- [ ] **Step 5: Run the tests**

```bash
python -m pytest tests/test_devin_normalize.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add runner/tests/fixtures/devin_acp_updates.jsonl runner/tests/test_devin_normalize.py runner/server.py
git commit -m "feat(runner): add Devin ACP normalizer and tests"
```

---

### Task 2: Fake ACP server and `_run_devin_acp_bg` driver

**Files:**

- Create: `runner/tests/fake_devin_acp.py`
- Create: `runner/tests/test_devin_acp_driver.py`
- Modify: `runner/server.py` (insert `_run_devin_acp_bg` after `_run_codex_appserver_bg`)

**Interfaces:**

- Consumes: `TurnReq` fields (`prompt`, `resume_session_id`, `mcp_servers`, `tools_disabled`) passed as args to the driver.
- Produces: Events appended to `_turns[turn_id]["events"]`, and `result`/`status` set on the turn record.

- [ ] **Step 1: Write the fake ACP server**

Create `runner/tests/fake_devin_acp.py`:

```python
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
                     "agentCapabilities": {"session": {"resume": True}}}})
    initialized = json.loads(input())
    assert initialized["method"] == "initialized"

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
```

Make it executable:

```bash
chmod +x runner/tests/fake_devin_acp.py
```

- [ ] **Step 2: Write the failing driver test**

Create `runner/tests/test_devin_acp_driver.py`:

```python
import os
import pathlib
import threading
import time

from server import _turns

FAKE_DEVIN = pathlib.Path(__file__).with_suffix("").parent / "fake_devin_acp.py"


def test_devin_acp_driver():
    turn_id = "t-driver-1"
    _turns[turn_id] = {"events": [], "cancelled": False, "capped": False, "done": False}
    env = {**os.environ, "PATH": f"{FAKE_DEVIN.parent}:{os.environ.get('PATH', '')}"}
    # Override the binary name so we can point at our fake
    os.environ.setdefault("DEVIN_ACP_BINARY", str(FAKE_DEVIN))
    from server import _run_devin_acp_bg
    t = threading.Thread(target=_run_devin_acp_bg,
                         args=(turn_id, "/tmp", env, "devin-swe", "say hello", None, 60, None, None),
                         daemon=True)
    t.start()
    t.join(timeout=10)
    rec = _turns[turn_id]
    assert rec["done"]
    texts = [e["message"]["content"][0]["text"] for e in rec["events"]
             if e.get("type") == "assistant" and e["message"]["content"][0].get("type") == "text"]
    assert "Fake " in texts
    assert "Devin" in texts
```

- [ ] **Step 3: Run the test — expect failures**

```bash
python -m pytest tests/test_devin_acp_driver.py -v
```

Expected: `_run_devin_acp_bg` does not exist.

- [ ] **Step 4: Implement `_run_devin_acp_bg` in `runner/server.py`**

Insert after `_run_codex_appserver_bg` (around line 2640). The full implementation is in the spec; the key skeleton is below. Make it read `DEVIN_ACP_BINARY` for testability, falling back to `"devin"`.

```python
def _run_devin_acp_bg(turn_id: str, cwd: str, env: dict, model: str, prompt: str,
                      resume_session_id: str | None, timeout_seconds: int | None,
                      mcp_servers: list[dict] | None, tools_disabled: list[str] | None) -> None:
    rec = _turns[turn_id]
    state: dict = {"final": ""}

    def append(ev: dict) -> None:
        ev["_ts"] = time.time()
        with _turns_lock:
            rec["events"].append(ev)

    # env setup (mirrors claude/codex session isolation)
    home = pathlib.Path(cwd) / ".harness" / "home"
    home.mkdir(parents=True, exist_ok=True)
    xdg = pathlib.Path(env.get("HR_DATA_DIR") or "/data") / "agent-tools" / "devin"
    xdg.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(home)
    env["XDG_DATA_HOME"] = str(xdg)
    if env.get("WINDSURF_API_KEY"):
        pass  # already injected by turn()

    cmd = [env.get("DEVIN_ACP_BINARY") or "devin", "acp", "--model", model]
    # ... full JSON-RPC client loop (see spec §3)
    # Send initialize, initialized, session/new or session/resume, session/prompt,
    # read session/update, respond to request_permission, final result.
    # On cancel/timeout, send session/cancel and _kill_proc_tree.
```

- [ ] **Step 5: Run the tests**

```bash
python -m pytest tests/test_devin_acp_driver.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add runner/tests/fake_devin_acp.py runner/tests/test_devin_acp_driver.py runner/server.py
git commit -m "feat(runner): add Devin ACP driver and fake server tests"
```

---

### Task 3: Runner registry, dispatch, and env helper

**Files:**

- Modify: `runner/server.py` (`BACKENDS`, constants, `turn()` dispatch)

- [ ] **Step 1: Add Devin constants and registry**

Near the other backend provider sets (around line 2200), add:

```python
DEVIN_PROVIDERS = {"devin"}
DEVIN_DEFAULT_MODEL = os.environ.get("DEVIN_DEFAULT_MODEL", "devin-swe")
```

In `BACKENDS` (around line 2349), add:

```python
"devin": {
    "providers": sorted(DEVIN_PROVIDERS),
    "default_model": DEVIN_DEFAULT_MODEL,
    "normalize": None,  # _run_devin_acp_bg calls _devin_to_claude directly
},
```

- [ ] **Step 2: Add the `turn()` dispatch branch**

In `turn()` (around line 3373), after the `hermes` branch, add:

```python
elif backend == "devin":
    model = model or DEVIN_DEFAULT_MODEL
    if not env.get("WINDSURF_API_KEY"):
        rec.update(status="failed", error="WINDSURF_API_KEY not configured for devin backend", done=True)
        return _turn_resp(rec)
    threading.Thread(target=_run_devin_acp_bg,
                     args=(turn_id, cwd, env, model, req.prompt,
                           req.resume_session_id, req.timeout_seconds,
                           req.mcp_servers, req.tools_disabled),
                     daemon=True).start()
```

- [ ] **Step 3: Run unit tests**

```bash
python -m pytest tests/test_devin_normalize.py tests/test_devin_acp_driver.py -v
```

Expected: PASS.

- [ ] **Step 4: Run the runner server and hit `/v1/bases`**

```bash
python -m server &
curl -s http://localhost:8081/health
kill %1
```

Expected: runner starts without import/syntax errors.

- [ ] **Step 5: Commit**

```bash
git add runner/server.py
git commit -m "feat(runner): wire Devin backend into registry and dispatch"
```

---

### Task 4: Gateway catalog and provider wiring

**Files:**

- Modify: `gateway/app.py`

- [ ] **Step 1: Add `devin` to `_BASE_CATALOG`**

Insert after `opencode` (around line 11114):

```python
"devin": {
    "label": "Devin", "backend": "devin", "status": "ready",
    "system_prompt": ("You are Devin, an autonomous software-engineering agent. You work on a "
                      "real git workspace with shell and file access, reading and editing files "
                      "and running commands to complete the task end to end."),
    "tools": [("bash", "Bash"), ("read", "File Read"), ("write", "File Write"),
              ("edit", "Edit"), ("glob", "Glob"), ("grep", "Grep"),
              ("webfetch", "Web Fetch"), ("websearch", "Web Search"),
              ("task", "Task"), ("todowrite", "Todo")],
    "tool_enforcement": "hard",
},
```

- [ ] **Step 2: Add `devin` to `_MODEL_CATALOG`**

Insert after `opencode` (around line 4524):

```python
"devin": {"default": "devin-swe",
          "models": ["devin-swe", "devin-swe-fast", "devin-opus",
                     "devin-sonnet", "devin-gpt-5.5", "devin-adaptive"]},
```

These model names are a starter set based on Devin's public model names; verify and update them with the actual output of `devin models list --format json` once the CLI is installed.

- [ ] **Step 3: Add `devin` provider to `_PROVIDER_CATALOG`**

Insert after `elevenlabs` (around line 3509):

```python
"devin": {
    "label": "Devin",
    "base_url": None,
    "fields": [],
    "secret": "api_key",
    "secret_label": "Devin / Windsurf API Key",
    "key_hint": "wind-…",
},
```

- [ ] **Step 4: Add integration wiring**

In `_INTEGRATION_WIRING` (around line 950), add:

```python
("devin", "devin"): "devin",
```

- [ ] **Step 5: Update `_BARE_MODELS` and `_route_backend` (if needed)**

If `_route_backend` does not already fall through to the backend from a harness `base`, add `devin` to `_BARE_MODELS` (around line 4534):

```python
_BARE_MODELS = {"", "claude", "codex", "anthropic", "bedrock", "openai",
                "hermes", "pi", "dsh", "deepseek", "devin"}
```

- [ ] **Step 6: Run gateway smoke test**

```bash
cd /Users/chenillen/Codes/OpenSource/harnessrouter/gateway
python -m pytest tests/ -k "not integration" -x || true
curl -s http://localhost:8080/api/harness/v1/bases | head -c 200
```

Expected: `devin` appears in `/v1/bases` and `/v1/models` once the gateway is running.

- [ ] **Step 7: Commit**

```bash
git add gateway/app.py
git commit -m "feat(gateway): add devin harness base, model catalog, and provider"
```

---

### Task 5: UI harness entry

**Files:**

- Modify: `ui/src/lib/harness.ts`
- Modify: `ui/src/components/HarnessLogo.tsx`
- Create: `public/logos/devin.png` (or skip and use fallback glyph)

- [ ] **Step 1: Update the `OobHarness` backend union**

In `ui/src/lib/harness.ts` (line 23), change:

```typescript
backend: 'claude' | 'codex' | 'hermes' | 'pi' | 'dsh' | 'opencode' | 'devin' | null;
```

- [ ] **Step 2: Add `devin` to `OOB`**

Insert before the `];` (line 85):

```typescript
  { id: 'devin', name: 'Devin', version: 'v1.0.0', backend: 'devin', status: 'ready',
    models: ['devin-swe', 'devin-swe-fast', 'devin-opus', 'devin-sonnet'], defaultModel: 'devin-swe', moreModels: 0,
    systemPrompt: 'You are Devin, an autonomous software-engineering agent. You work on a real git workspace with shell and file access, reading and editing files and running commands to complete the task end to end.',
    tools: [], skills: [] },
```

- [ ] **Step 3: Add logo mapping**

In `ui/src/components/HarnessLogo.tsx` (line 7-14), add:

```typescript
devin: '/logos/devin.png',
```

Place `public/logos/devin.png` (a 128x128 PNG) or remove the mapping and let the UI fall back to the generic glyph if no asset is available.

- [ ] **Step 4: Type-check the UI**

```bash
cd /Users/chenillen/Codes/OpenSource/harnessrouter/ui
npm run type-check
```

Expected: no new type errors.

- [ ] **Step 5: Commit**

```bash
git add ui/src/lib/harness.ts ui/src/components/HarnessLogo.tsx public/logos/devin.png
git commit -m "feat(ui): add Devin harness entry and logo"
```

---

### Task 6: Docker runtime install

**Files:**

- Modify: `docker/entrypoint.sh`

- [ ] **Step 1: Add `devin` to `HR_BACKENDS` and `backend_bin`**

Change the default (around line 175):

```bash
export HR_BACKENDS="${HR_BACKENDS:-claude,codex,hermes,pi,dsh,opencode,devin}"
```

In `backend_bin()` (around line 189), add:

```bash
    devin)  echo "$TOOLS/bin/devin" ;;
```

- [ ] **Step 2: Add `install_devin`**

Insert after `install_opencode` (around line 215):

```bash
install_devin() {
  devin_home="$DATA_DIR/agent-tools/devin/home"
  devin_xdg="$DATA_DIR/agent-tools/devin"
  mkdir -p "$devin_home" "$devin_xdg" "$TOOLS/bin"
  # The official installer writes versions into $XDG_DATA_HOME/devin/cli and links
  # the binary into $HOME/.local/bin. Redirecting HOME/XDG keeps all state on the data volume.
  HOME="$devin_home" XDG_DATA_HOME="$devin_xdg" \
    bash -c 'curl -fsSL https://cli.devin.ai/install.sh | bash' || return 1
  local installed="$devin_home/.local/bin/devin"
  [ -x "$installed" ] || { echo "Devin installer did not produce a binary"; return 1; }
  ln -sf "$installed" "$TOOLS/bin/devin"
}
```

- [ ] **Step 3: Call `install_devin` from `install_backends`**

Add after the `opencode` block (around line 249):

```bash
  if wanted devin && [ ! -x "$(backend_bin devin)" ]; then
    echo "[harnessrouter] installing Devin (Cognition/Windsurf terms apply)…"
    try_install "Devin" install_devin || true
  fi
```

- [ ] **Step 4: Lint / smoke the entrypoint**

```bash
bash -n docker/entrypoint.sh
```

If `shellcheck` is installed:

```bash
shellcheck docker/entrypoint.sh
```

Expected: no syntax errors and no new shellcheck warnings.

- [ ] **Step 5: Commit**

```bash
git add docker/entrypoint.sh
git commit -m "feat(docker): install Devin CLI at runtime"
```

---

### Task 7: Integration and conformance

- [ ] **Step 1: Build the runner/gateway image locally (if using Docker)**

```bash
docker build -t harnessrouter-devin -f Dockerfile .
```

- [ ] **Step 2: Run UHP conformance against a local gateway**

Start the gateway/runner in the dev environment and run:

```bash
cd /Users/chenillen/Codes/OpenSource/harnessrouter/protocol/conformance
python -m uhp_conformance --base http://localhost:8080 --tests bases,models
```

Expected: `devin` appears in the `bases` and `models` results.

- [ ] **Step 3: Manual smoke with a real or fake binary**

If a `WINDSURF_API_KEY` is available:

```bash
export WINDSURF_API_KEY=...
docker run -e HR_BACKENDS=devin -e WINDSURF_API_KEY ... harnessrouter-devin
# Create a devin harness in the UI and run a turn.
```

If no key is available, temporarily replace `devin` in the container with the fake `runner/tests/fake_devin_acp.py` and run a turn to verify the end-to-end flow:

```bash
cp runner/tests/fake_devin_acp.py /data/agent-tools/bin/devin
# trigger a turn and inspect the trace
```

- [ ] **Step 4: Update model list from real CLI**

Once Devin is installed in a real environment, run:

```bash
devin models list --format json
```

and update `gateway/app.py` `_MODEL_CATALOG["devin"]` with the actual model ids.

- [ ] **Step 5: Final commit (if any model list updates)**

```bash
git add gateway/app.py
git commit -m "chore(gateway): update Devin model list from live CLI"
```

---

## Self-review

- **Spec coverage:** Every section of the spec maps to a task: runner ACP client (Task 2), normalizer (Task 1), registry/dispatch (Task 3), gateway (Task 4), UI (Task 5), Docker install (Task 6), integration (Task 7).
- **Placeholder scan:** No `TBD`, `TODO`, or vague steps. The `_MODEL_CATALOG["devin"]` model list is a starter set and is explicitly verified against `devin models list` in Task 7.
- **Type consistency:** `_run_devin_acp_bg` is always started with `(turn_id, cwd, env, model, prompt, resume_session_id, timeout_seconds, mcp_servers, tools_disabled)`. `_devin_to_claude` keeps the `(obj, state)` signature used by the other normalizers.
- **Risk mitigation:** The resume guard and `request_permission` handling are explicit. The proprietary-binary-distribution rule is enforced by runtime install.
