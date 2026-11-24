# Controlled native approval tests

Run in an isolated Python 3.12+ environment:

```sh
python -m pip install -r runner/native_tests/requirements.txt
python -m pytest -q runner/native_tests runner/tests/test_langgraph_approval_boundary.py
```

This suite uses real LangChain HITL middleware, LangGraph, SQLite checkpoints,
Gateway's sealed invocation gate and journal, and a temporary file tool. Only the
model is scripted. Approve and deny journeys each restart three OS processes to capture,
resume and replay a stored decision. Denial delivery gets its own receipt while
the tool stays not_started; a subsequent tool proposal is interrupted anew. No provider, network tool or credentials are
needed. Dependencies are separate from the shared Runner installation and ordinary
`runner/tests`; missing native dependencies are collection errors, never skips.

`runner/langgraph_approval.py` is an **unregistered internal adapter**. It supports
only one root interrupt/action backed by persistent SQLite. Callers must own the
Runtime execution lease and supply current trusted policy, tool catalog and native
permission facts to Gateway's gate. The local adapter lock is not a process lease.
Bound adapters now also use the durable Runner registry execution pin: takeover
and release are blocked while native work is active or uncertain, even after TTL
expiry. Checkpoint-read expiry, post-effect lease loss, concurrent adapter objects,
cancel/error and the Gateway ownership coordinator's approve/deny journeys are
covered. The coordinator uses an independent heartbeat; it grants no tool permission.
Unknown pins need confirmation that the former Runtime and child work stopped
before future reconciliation; there is no force-clear HTTP endpoint.
Checkpoint parameter objects are authoritative; original model JSON whitespace is
not available. The native store must be trusted and inaccessible to untrusted tools.

Passing this suite does not establish dcode ACP integration, authenticated Runner
registration, response/SSE continuation, Hexa UI,
provider support or UHP conformance. `tool_approvals` remains unadvertised and
workflow approval policies remain blocked. See
[AC-44](../../docs/changes/CHG-task-centric-workflow/spec.md#langgraph-checkpoint-adapter-的受限验证边界).

`runner/native_session.py` now owns the optional adapter registration lifetime:
it verifies a persistent SQLite saver, records the installed LangGraph version,
maintains registration health/expiry, and invalidates retained adapters on exit.
It does not own or close the caller's graph/saver. Registration heartbeat is
separate from Gateway's owner lease heartbeat. Lost health or context cancellation
expires the registration and preserves unknown execution pins; it cannot stop a
native tool thread that has already started.

`test_native_session.py` covers this context with the real checkpoint/gate/journal.
`test_native_session_http.py` additionally requires the Linux Runner delivery image
and its FastAPI dependencies; it is skipped on Windows because the Runner imports
POSIX APIs. The Linux journey uses authenticated Runner HTTP and Gateway ownership
to approve/deny, then proves the closed session cannot be used again. Neither
module proves a production Provider factory, Responses/SSE or Hexa UI integration.
