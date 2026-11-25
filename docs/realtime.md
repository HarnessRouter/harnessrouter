# Realtime Harness

The `realtime` base runs a **text turn on a realtime speech model**, through the
[Realtime Harness](https://github.com/HarnessRouter/RealtimeHarness) (Apache-2.0, built on
Pipecat). A realtime model is the kind a voice call talks to. This base lets the same harness
that takes calls also answer a typed task, with the same instructions and the same tools, and
lets the verification suites drive it the way they drive every other base.

It is not a coding agent. The model has no shell and no file tools. What it can do is answer,
and call the tools of the MCP servers the harness configures.

Voice calls themselves are not part of this base. They are a separate piece of work.

## How a turn runs

Each turn starts one process, `runner/realtime_driver.py`, in the base's own Python
environment. It reads the harness's MCP servers, opens one connection to the model, runs the
turn, and exits. It prints the same event stream Claude Code prints, so nothing downstream is
special to this base.

A realtime model is reached over a WebSocket, which the runner's relay does not forward. The
connection's key still never reaches the turn's process:

1. The turn is given a relay placeholder (`HR_REALTIME_KEY`) and the relay's address.
2. The driver posts the placeholder to the relay. The relay puts the real key on that one
   request and forwards it to the provider's client-secret endpoint
   (`POST …/realtime/client_secrets`).
3. The provider answers with a short-lived secret for one session (120 seconds to start it).
4. The driver opens the provider's WebSocket with that secret.

The turn's relay route forwards that one request and nothing else. Any other path or method
sent with the placeholder is answered 403 by the relay and never reaches the provider.

## Connections

An **Azure OpenAI / Azure AI Foundry** connection **with an API key**. The model id is the
name of the deployment. The catalog holds one model, `gpt-realtime-2.1`, the one the Realtime
Harness was measured on.

A deployment is named by whoever made the resource. Where yours is not named
`gpt-realtime-2.1`, add a model row to the connection (**Keys**, the connection, **Add
model**): the model `gpt-realtime-2.1`, and your deployment's name as its id. The row applies
to a connection saved in the console or through the API. A connection set from the environment
(`HR_SECRET_GLOBAL_HARNESS_CONN_…`) has no rows, so its deployment must carry the model's name.

Not supported yet:

- **A connection that signs in with Microsoft Entra.** Such a connection is always sent
  through the gateway's model broker, and the broker carries neither the client-secret
  request nor a WebSocket. A turn on one is refused with that reason before it starts.
- **An instance that is not in owner trust** (`HR_SANDBOX_TRUST` other than `owner`), for the
  same reason.
- **Any other provider.** OpenAI speaks the same wire and is added when it has a measured
  column. No aggregator carries the realtime socket, and no custom endpoint format names it.

## Installation

`realtime` is opt-in: it is not in the default `HR_BACKENDS`. Add it to install it.

```sh
docker run -e HR_BACKENDS=claude,codex,realtime ...
```

The installer builds a virtual environment of its own at
`/data/agent-tools/realtime-venv` from `docker/locks/realtime.lock.txt`: 70 distributions,
each pinned by version and by the SHA-256 of its files (about 540 MB on arm64, measured
2026-11-25). The environment is separate because
the Realtime Harness's MCP SDK is a major version ahead of the runner's.

The Realtime Harness has no release yet, so the pin is a commit of its main branch, fetched
as a source archive whose digest the lock holds. Two distributions are built from source at
install time, by the unprivileged install user: that archive, and `docopt` (a dependency of
Pipecat's `num2words`), which publishes no wheel.

Set `HR_REALTIME_SPEC` to install the package from somewhere else (a fork, a mirror). Such an
install is not covered by the lock, and the start log says it is not verified.

A base the catalog lists and this instance has not installed is reported as not installed:
the console does not offer it, and a turn on it is refused with that reason.

`HR_REALTIME_PYTHON` selects an existing interpreter for development.

### Licences in the dependency tree

The Realtime Harness is Apache-2.0 and Pipecat is BSD-2-Clause. Two of Pipecat's
dependencies are LGPL: `num2words` (LGPL) and `soxr` (LGPL-2.1-or-later). They are
installed unchanged from PyPI into the base's own environment at first start, like every
other base's dependencies, and are not redistributed in the image.

## Sessions, instructions, tools

- **Sessions.** A provider's realtime session ends with its connection, so the conversation
  is kept in the workspace: `.harness/realtime/<session id>/items.json`. A follow-up turn
  replays it to a new connection. It rides the normal checkpoint. A turn that names a session
  whose file is gone emits `system/resume_lost` and starts a new one.
- **Instructions.** The harness's instructions travel in the turn's job and become the
  session's instructions. This base reads no instruction file from the workspace, so the
  settings page calls the box "Instructions".
- **Tools.** Nothing is built in. The tools are those of the harness's MCP servers, read from
  the servers at the start of every turn and offered as `mcp__<server>__<tool>`.
- **A disabled tool** is left out of the session's tool list, so the model is never offered
  it. This holds on every turn of a session, because the list is rebuilt each turn.
- **MCP servers are reached by URL** (streamable HTTP or SSE). A stdio server, such as one a
  plugin declares, cannot be started by this base. It is named in `system/mcp_unavailable`,
  and so is a server that cannot be reached; the turn still runs with the rest.
- **Skills** are not offered. A skill is prose an agent reads and scripts it runs from a
  shell, and this base has neither.
- **Environments** are not mounted. A turn that names one is refused.
- **Step budget.** `max_turns` is the number of model steps the turn may take. A turn that
  reaches it ends incomplete at its budget, and a tool call it never answered is not kept in
  the session.
- **Usage and the served model** come from the provider's own session events, because the
  relay sees no model call on this base. When the provider reports no usage the turn carries
  none, rather than an estimate.

## Verification

The unit and registration tests need no provider key:

```sh
python -m pytest runner/tests/test_realtime_backend.py runner/tests/test_realtime_route.py
python -m pytest gateway/tests/test_realtime_catalog.py gateway/tests/test_instruction_file_label.py
```

The driver's tests run in an environment that has the Realtime Harness installed (they skip
anywhere else), against a scripted provider on the OpenAI realtime wire:

```sh
/data/agent-tools/realtime-venv/bin/python -m pip install pytest
/data/agent-tools/realtime-venv/bin/python -m pytest runner/tests/test_realtime_driver.py
```

These tests check the event stream, that the key never reaches the turn, the one-request
relay route, session replay, tool policy, unavailable servers, the step budget and a refused
mint. They do **not** establish a live provider column. No support-matrix result exists for
this base yet, and none has been copied from another base.
