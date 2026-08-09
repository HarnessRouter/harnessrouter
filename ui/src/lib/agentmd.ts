// The interactive AGENTS.md a vibe coder drops into their own coding agent (Claude Code / Codex).
// Key-Tool-Gate revision (2026-07-18 candidate, adopted): the API-key setup is Step 0, a state
// machine (KEY_SETUP_STATUS / KEY_SOURCE) executed as the FIRST tool call, before product planning:
// 0.1 resolve server env / secret file, 0.2 secret-input tool or wrapped OS-native password dialog
// (osascript hidden answer / PowerShell / zenity), 0.3 open-the-env-file fallback, 0.4 verify with
// classified statuses only. Steps renumbered (understand=1, agent=2, build=3, test=4); Step 1 adds
// the feature-key inventory + Workspace mapping. Retains the trace-audit fixes (data:-only frames,
// done≠completed, verbatim schemas) and the workspace-scoped-key note.
// NOTE: the /agents page renders this markdown in two prose slices around a rich React
// API reference: it splits on the literal anchors '\n## Runtime integration reference' and
// '\n## Done conditions'. Keep those headings verbatim (or update agents/page.tsx) when editing.
export function agentMd(apiBase = 'https://api.harnessrouter.ai'): string {
  return `# HarnessRouter, Add an AI agent feature to a product

You are a coding agent helping the user build or modify a product that uses HarnessRouter for
runtime agent capabilities.

HarnessRouter runs configured agents. The user's product keeps its own UI, authentication,
authorization, product data, and user experience.

## Step 0, Execute the API-key setup

Complete this step before product planning or implementation. The first tool call for this guide
must execute the Key setup flow. Track its result as \`KEY_SETUP_STATUS\`.

### 0.1 Prepare the secret destination and resolve the current state

Use a Coding Agent execution tool to perform this sequence before any input tool can save a Key.
Track the selected source as \`KEY_SOURCE\`:

1. Resolve the project root.
2. Check trusted server environment sources already available to the product server, including its
   process environment, deployment environment, or configured secret manager, only for whether
   \`HR_API_KEY\` is present and non-empty. If present, set \`KEY_SOURCE=SERVER_ENV\`, set
   \`KEY_SETUP_STATUS=READY\`, and immediately execute Step 0.4 without creating a local secret file.
3. Otherwise resolve one server-only secret file as \`KEY_ENV_FILE\`. Use \`.env\` when it is not tracked by Git.
   When \`.env\` is already tracked, preserve it unchanged and use a project-supported ignored secret
   file, preferring \`.env.local\`; verify or configure the product server to load that file.
4. Add \`KEY_ENV_FILE\` to \`.gitignore\` if it is not already covered, then create the file if it does
   not exist.
5. Add \`HR_API_KEY=\` if that variable is not already present, preserving all other content.
6. Create or update the committed \`.env.example\` with an empty \`HR_API_KEY=\` entry while
   preserving its other content.
7. Set \`KEY_ENV_FILE\` to owner read/write permissions where the platform supports it.
8. Check only whether \`HR_API_KEY\` is present and non-empty in \`KEY_ENV_FILE\`. Return a Boolean
   status, not the value.

- If present, set \`KEY_SOURCE=FILE\`, set \`KEY_SETUP_STATUS=READY\`, and continue to Step 0.4.
- If absent, immediately continue to Step 0.2 in the same setup flow.

### 0.2 Collect the Key with a tool

Select and execute the first available tool path automatically:

1. Use a Coding Agent secret-input tool when it masks the value, excludes it from the transcript,
   and writes it directly to a trusted local secret destination.
2. Otherwise, use the Coding Agent execution tool to run a wrapper around an OS-native password
   dialog. The wrapper captures the submitted value inside the process, writes it directly to the
   prepared \`KEY_ENV_FILE\`, suppresses the dialog's stdout and stderr from the execution transcript, clears
   the in-process value, and emits only one status. On macOS, wrap \`osascript\` with a hidden answer;
   on Windows, wrap the native PowerShell password input; on Linux desktop, wrap
   \`zenity --password\` or the available native equivalent.
3. If neither path is available or succeeds, immediately execute Step 0.3.

Label the input \`HarnessRouter API key\` and mention that it starts with \`sk-hr-\`. The tool
handler writes the submitted value directly to the project's \`KEY_ENV_FILE\` as
\`HR_API_KEY\`. Its result contains exactly one status:

- \`KEY_SAVED\`
- \`KEY_CANCELLED\`
- \`KEY_INPUT_UNAVAILABLE\`

When the result is \`KEY_SAVED\`, verify only that \`HR_API_KEY\` is present and non-empty, set
\`KEY_SOURCE=FILE\`, set \`KEY_SETUP_STATUS=READY\`, and immediately execute Step 0.4.

When the result is \`KEY_CANCELLED\`, set \`KEY_SETUP_STATUS=CANCELLED\` and continue only with work
that does not require authenticated HarnessRouter requests.

When the result is \`KEY_INPUT_UNAVAILABLE\`, immediately execute Step 0.3.

### 0.3 Open the local \`.env\` fallback

Use the Coding Agent's file or execution tool to open the \`KEY_ENV_FILE\` prepared in Step 0.1 in the
user's trusted local editor. Place the cursor after \`HR_API_KEY=\` when the editor integration
supports it.

Then tell the user:

> The local server environment file is open. Paste your HarnessRouter API key after
> \`HR_API_KEY=\`, save the
> file, then reply \`ready\`.

Set \`KEY_SETUP_STATUS=WAITING_FOR_ENV\` and wait for the user's response.

When the user replies \`ready\`, verify only whether \`HR_API_KEY\` is present and non-empty.

- If present, set \`KEY_SOURCE=FILE\`, set \`KEY_SETUP_STATUS=READY\`, and immediately execute Step 0.4.
- If absent, reopen the same \`KEY_ENV_FILE\` and keep \`KEY_SETUP_STATUS=WAITING_FOR_ENV\`.

If the local editor cannot be opened automatically, report the resolved absolute \`KEY_ENV_FILE\` path,
keep \`KEY_SETUP_STATUS=WAITING_FOR_ENV\`, and ask the user to open that exact file, paste the Key
after \`HR_API_KEY=\`, save it, and reply \`ready\`.

### 0.4 Verify the connection

Authenticated HarnessRouter operations may begin only when \`KEY_SETUP_STATUS=READY\`.

Use an execution wrapper in the server context selected by \`KEY_SOURCE\`. For \`SERVER_ENV\`, read the
existing trusted environment value in the context that already has access to it. For \`FILE\`, read
\`HR_API_KEY\` from \`KEY_ENV_FILE\` directly into the request process. Send the header without placing
the Key in command arguments or tool output, suppress response headers and bodies from the
transcript, clear the in-process value, and emit only the classified status for this server-side
request:

\`\`\`http
GET ${apiBase}/v1/models
Authorization: Bearer $HR_API_KEY
\`\`\`

Apply the result as follows:

- HTTP 200: report \`HarnessRouter connection verified\`, keep \`KEY_SETUP_STATUS=READY\`, and
  continue to Step 1.
- HTTP 401 or 403: report \`HarnessRouter rejected the Key\` and set \`KEY_SETUP_STATUS=REJECTED\`.
  For \`KEY_SOURCE=FILE\`, replace only the \`HR_API_KEY\` value in \`KEY_ENV_FILE\` with an empty value
  and execute Step 0.2 again. For \`KEY_SOURCE=SERVER_ENV\`, ask the user to update that same trusted
  server environment source and wait for \`ready\` before retrying Step 0.4.
- HTTP 429: report \`HarnessRouter rate limited verification\`, set \`KEY_SETUP_STATUS=RATE_LIMITED\`,
  wait for \`Retry-After\` when supplied, and retry Step 0.4.
- HTTP 500–599: report \`HarnessRouter service is unavailable\`, set
  \`KEY_SETUP_STATUS=SERVICE_UNAVAILABLE\`, and wait or retry Step 0.4.
- Any other HTTP response: report only its status code as a configuration failure, set
  \`KEY_SETUP_STATUS=CONFIGURATION_ERROR\`, and wait for the configuration to be corrected before
  retrying Step 0.4.
- Network failure: report \`HarnessRouter could not be reached\`, set
  \`KEY_SETUP_STATUS=CONNECTION_UNAVAILABLE\`, and wait without making another authenticated call.
  Retry Step 0.4 only after the user explicitly requests it or confirms that network access changed.

The Key remains in the server-side secret destination. Verification and later tool results expose
only status. Every server-side HarnessRouter request uses:

\`\`\`http
Authorization: Bearer $HR_API_KEY
\`\`\`

HarnessRouter base URL:

\`\`\`text
${apiBase}
\`\`\`

Third-party access tokens use the same tool-selection flow and are stored through the HarnessRouter
secrets endpoint.
The Key also carries its scope: a key created inside a HarnessRouter Workspace sees and creates
agents and sessions in that Workspace only. That is normal, one product integration lives in one
Workspace. If an expected agent is missing from \`GET /v1/harnesses\`, the Key likely belongs to a
different Workspace; ask the user to create the Key from the intended Workspace in the dashboard.

---

## The most important boundary

There are two different jobs. Never collapse them into one.

1. **Build-time product work** is done by you, the current coding agent, in the user's project.
   Examples: create the app, build its UI, add server routes, implement authentication, connect
   HarnessRouter, render results, and add tests.
2. **Runtime end-user work** is done by a configured HarnessRouter agent after the product
   integration exists. Examples: generate one game from a game brief, review one uploaded contract,
   fix one submitted codebase, or create one slide deck.

When the user asks you to build an app or product feature whose end users will use AI to perform a
task, implement the host product in the user's project. Configure HarnessRouter to perform the
future end-user task at runtime.

Do not send the host-product request itself to the HarnessRouter agent. Only send representative
end-user tasks after the host product and its server-side integration exist.

### Example

User request:

> Build an app that lets users generate playable games.

Build-time responsibility:

- Build the game-generation product, UI, server routes, authentication, result renderer, and
  HarnessRouter integration.

Runtime-agent responsibility:

- Receive a specific end-user game brief and return playable game files.

Incorrect runtime input:

> Build an app that generates games.

Correct runtime input:

> Create a playable two-player space rescue game with scoring, win/loss states, and restart.

## Request classification gate

Before calling HarnessRouter, classify the current request:

- **Host-product request:** asks to build, add, integrate, design, or modify an app or product.
  Implement it locally in the user's project. Extract the future runtime capability as the
  HarnessRouter agent's purpose, but do not forward the host-product request as runtime input.
- **Runtime task:** asks the already-integrated product agent to perform one end-user job. Send it
  through the product's authenticated server route to the configured HarnessRouter agent.
- **Harness administration:** asks to create, update, inspect, or test agent configuration. Use the
  HarnessRouter management API, but do not treat configuration work as an end-user task.
- **Unclear request:** ask one short question: "Should I build the product feature, or run one task
  with an agent that is already connected?" Suggest the likely answer.

Do not call \`POST /{harness_id}/v1/responses\` until this classification is complete.

## Standing rule, runtime agent capability goes through HarnessRouter

For product features that perform multi-step reasoning, tool use, code execution, file reading or
generation, browsing, or other autonomous work, use a purpose-configured HarnessRouter agent.

- Do not hand-roll an agent loop, tool dispatcher, planner/executor, sandbox, retry manager, or
  separate agent orchestration framework.
- One product can use many purpose-configured agents. Reuse an existing agent when its purpose and
  permissions genuinely match; otherwise create a new one.
- HarnessRouter owns runtime execution, tools, sandboxing, files, retries, and session continuity.
- The product owns UI, authentication, tenant authorization, product records, policy, and rendering.
- A plain single-shot text transformation with no tools, files, or multi-step work may use a raw
  model call if that matches the user's existing architecture.

This rule governs runtime implementation. It does not authorize replacing unrelated existing
architecture or ignoring a later explicit user instruction.

## Vocabulary

- **Host app:** the user's product being built or modified.
- **Coding agent:** you, working on the host app at build time.
- **Base harness:** the execution engine, currently \`codex\`, \`claude-code\`, or \`hermes\`.
- **Configured agent:** a HarnessRouter harness record with a purpose, instructions, tools, skills,
  model policy, and limits. Its ID is the \`harness_id\` used to run tasks.
- **Runtime task:** one end-user request executed by the configured agent.
- **Session:** the persistent conversation and working folder used across related runtime turns.
- **Response:** one runtime turn inside a session.

Use user-friendly language in the product UI. Use the exact API terms in code and technical notes.

## How to work with the user

- Keep explanations short and use plain language unless the user asks for technical detail.
- Ask one question at a time only when the answer is required.
- Make reversible implementation choices yourself. Explain choices that affect cost, permissions,
  data access, security, or long-term product architecture.
- Never claim the integration works because a direct API call succeeded. The generated host app
  must be started and tested as an end user.

---

## Step 1, Understand the product feature

If the request is already clear, proceed without repeating these questions. Otherwise ask, one at
a time:

1. What should the host app let its end users accomplish?
2. Should the feature appear as a conversation, a button/action, or a background job? Suggest the
   natural default.
3. What product data or external tools may the runtime agent use?
4. What rules, permissions, output formats, or prohibited actions apply?
5. Which agent-powered feature keys exist, and which Workspace and configured agent should serve
   each one?

Write down two separate statements:

- **Host-app goal:** what you will build in the user's project.
- **Runtime-agent purpose:** what the configured HarnessRouter agent will do for an end user.

Example:

\`\`\`text
Host-app goal: Build a responsive game-generation app with an idea form, progress stream,
playable preview, saved sessions, downloads, and Continue/Revise.

Runtime-agent purpose: Turn one end-user game brief into verified, playable browser-game files.
\`\`\`

Never use the host-app goal as the runtime task.

Create a feature inventory before configuring agents:

| Feature key | Runtime job | Inputs | Outputs | Data/Tools | Permission boundary |
|---|---|---|---|---|---|

Group feature keys into one configured agent only when their runtime purpose, data access, tools,
permissions, and output contract all match. Use separate configured agents when any of those
boundaries differ. Select or create the project Workspace through the deployed API or official
HarnessRouter product surface, then record every approved \`feature_key → harness_id\` mapping in
the authenticated product server configuration.

---

## Step 2, Find, create, or update the configured agent

For each feature group from Step 1, first call \`GET /v1/harnesses\` in the selected Workspace and
look for an existing agent whose purpose, tool permissions, skills, model policy, and output
contract match the group.

- Reuse it only when those boundaries match.
- Update it when it is the canonical agent for this feature and the requested change is compatible.
- Otherwise create a new agent with \`POST /v1/harnesses\`.
- Do not create duplicate agents merely because this guide is run twice.

Get the current model catalog from \`GET /v1/models\` and the allowed models for an existing agent
from \`GET /v1/harnesses/{id}/models\`. Do not hardcode a model name as permanent policy.

\`GET /v1/models\` returns a map keyed by **backend**, not by base-harness name:

\`\`\`json
{
  "backends": {
    "codex":  { "default": "<id>", "models": [ { "id": "...", "label": "...", "backend": "codex",  "available": true, "default": true } ] },
    "claude": { "default": "<id>", "models": [ { "id": "...", "label": "...", "backend": "claude", "available": true, "default": false } ] },
    "hermes": { "default": "<id>", "models": [ { "id": "...", "label": "...", "backend": "hermes", "available": true, "default": false } ] }
  }
}
\`\`\`

Note the naming mismatch: the base harness \`claude-code\` corresponds to the backend key
\`claude\` (\`codex\` and \`hermes\` match their backend keys). A harness record with
\`defaultModel: ""\` (empty string) means "use the backend's default model", treat empty and
null alike.

Choose a sensible default when the product has no model-selection requirement. If the product lets
users select a model, fetch the allowed set server-side, apply product or tenant policy, validate
the selection on the server, and record the requested and actual model.

Create example:

\`\`\`bash
curl -sS ${apiBase}/v1/harnesses \\
  -H "Authorization: Bearer $HR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "name": "Playable Game Generator",
    "base": "codex",
    "default_model": "<allowed model from the models API>",
    "system_prompt": "<runtime-agent instructions, not the host-app request>",
    "mcp_servers": [],
    "skills": []
  }'
\`\`\`

The configured agent's instructions must:

1. Define the runtime job and reject host-product or HarnessRouter-integration work as a role
   mismatch when the agent is purpose-limited.
2. Save every deliverable as a real file in the working directory.
3. Define the expected output and Artifact structure, including the primary file, supporting files,
   entry point, relationships, and verification result when applicable.
4. Never return \`localhost\` or \`127.0.0.1\` as a user-facing link.
5. Avoid secrets, private services, and actions outside the configured permissions.

For a game generator, include a boundary such as:

\`\`\`text
You generate one playable game from an end-user game brief. You do not build the host
game-generation product, integrate HarnessRouter, create API routes, or redesign the caller's app.
If asked to do host-product or integration work, return role_mismatch with a short explanation.
\`\`\`

**Verify a skill actually landed** after configuring custom skills: run one narrow diagnostic that
lists the installed skill files and reads the first line of every root \`SKILL.md\`. Every configured
skill must appear before the host app relies on it.

---

## Step 3, Build the host app before running a task

Implement the product feature in the user's project. At minimum:

1. Build the native product UI for the requested experience.
2. Add an authenticated server route that accepts a trusted \`feature_key\`, resolves the
   allowlisted \`harness_id\` from the current user's or tenant's server-side mapping, and calls
   HarnessRouter. The browser sends the feature key and product input; the server selects the
   configured agent and keeps the HarnessRouter call server-side.
3. Map every created \`session_id\` and response/run identifier to the authenticated product user or
   tenant. Authorize list, detail, continue, cancel, file, preview, and download operations.
4. Generate a fresh \`Idempotency-Key\` for every new runtime request (a UUID is fine). Reuse the
   same key only when retrying that exact request.
5. Stream long tasks. As soon as the \`response.created\` event arrives, save the two recovery
   identifiers from its payload, exact JSON paths: \`response.id\` and
   \`response.metadata.session_id\` (the metadata object is **nested inside \`response\`**, not at
   the frame's top level).
6. If a stream drops after \`response.created\`, recover from the saved session. Do not start a
   second runtime task. Closing or losing the SSE connection does **not** stop the run, the
   agent keeps working server-side; stopping it requires an explicit
   \`POST /v1/sessions/{session_id}/cancel\`.
7. Support terminal states explicitly: completed, incomplete, failed, and cancelled. Offer
   Continue for incomplete work when appropriate.
8. Proxy file download and inline preview through an authenticated product server route. The
   browser must never receive the HarnessRouter API key, this includes \`download_url\` values
   from the files API, which point at the HarnessRouter API and require the Bearer key.
9. Render outputs according to trusted media type plus Artifact metadata. Safely handle Markdown,
   structured JSON, code, Diff/Patch, directory trees, HTML previews, images, PDF, Office files,
   CSV/XLSX, multi-file projects, and unknown types.
10. Isolate untrusted HTML and code previews. Do not give generated content access to the parent
    page, product credentials, or privileged browser APIs.

The host app must retain its own product-level ownership and authorization records even when
HarnessRouter provides session history. Do not expose account-wide session listings directly to
end users.

---

## Step 4, Test through the host app

Only after Step 3 is complete, run a representative end-user task.

The preferred path is:

\`\`\`text
Test user
  → host app UI
  → authenticated host-app server route
  → configured HarnessRouter agent
  → streamed status, response, and files
  → host app renderer
\`\`\`

A direct \`POST /{harness_id}/v1/responses\` call may be used only as a narrow diagnostic to isolate
an integration failure. It does not prove the host app works and cannot satisfy completion.

For the game-generation example:

- Incorrect test input: "Build an app that generates games."
- Correct runtime test input: "Create a playable two-player space rescue game with keyboard
  controls, scoring, win/loss states, and restart."

The test passes only if:

- the host app itself is present and starts successfully;
- the runtime request originates through the host app;
- the expected configured agent receives the end-user task;
- streaming, recovery identifiers, and terminal status are handled;
- returned files are rendered or downloaded through authorized product routes;
- the main Artifact is usable, not just described;
- Session Recall and Continue/Revise work;
- a second product user cannot see, download, cancel, or continue the first user's task.

---

## Runtime integration reference

### Run a task

Use the configured agent ID as the first path segment:

\`\`\`http
POST /{harness_id}/v1/responses
\`\`\`

Send \`Idempotency-Key\` on the initial request, not only on retries. Prefer streaming for agent work.

\`\`\`json
{
  "input": "Create a playable two-player space rescue game.",
  "stream": true
}
\`\`\`

### Stream wire format, read this before writing a parser

The stream is Server-Sent Events, but in the **OpenAI Responses style: \`data:\`-only frames.
There are no \`event:\` lines.** The event name is the \`type\` field *inside* the JSON payload.
A parser that dispatches on the SSE event name will see every frame as \`message\` and match
nothing, dispatch on \`data.type\` instead.

A real first frame (one \`data:\` line, frames separated by a blank line):

\`\`\`text
data: {"type": "response.created", "sequence_number": 0, "response": {"id": "resp_…", "object": "response", "created_at": 1784410449, "status": "in_progress", "error": null, "incomplete_details": null, "previous_response_id": null, "model": "…", "output": [], "store": true, "usage": null, "metadata": {"session_id": "hsess…"}}}
\`\`\`

- Recovery identifiers live at \`data.response.id\` and \`data.response.metadata.session_id\`.
- Frames carry a \`sequence_number\` you can use for ordering/debugging.
- Lifecycle frames not listed in the table below also appear (for example
  \`response.in_progress\`, roughly one heartbeat-style frame per step). **Ignore unknown
  \`type\` values instead of erroring**, the set is open.
- Payloads for the delta/item events follow the OpenAI Responses streaming schema for that
  \`type\`.

Important stream events:

| \`data.type\` | Product behavior |
|---|---|
| \`response.created\` | Save \`response.id\` and \`response.metadata.session_id\` immediately |
| \`response.in_progress\` | Liveness signal; no UI change needed |
| \`response.output_text.delta\` | Append visible answer text |
| \`response.reasoning_summary_text.delta\` | Optional progress summary |
| \`response.output_item.added\` | Show sanitized tool/activity status |
| \`response.output_text.annotation.added\` | Record returned file metadata |
| \`response.completed\` | Finalize successful UI state |
| \`response.incomplete\` | Show partial result and Continue action |
| \`response.failed\` | Show the classified failure or cancellation state |

If the stream drops after \`response.created\`, poll \`GET /v1/sessions/{session_id}\` until terminal,
then recover the final answer from \`/turns\` and recent files from \`/files?changed=true\`.

**The session record's SUCCESS status differs from the stream's event name.** A successfully
finished turn reports \`status: "done"\` (plus \`turn_status: "done"\`), **not** \`completed\`;
failure-side states (\`failed\`, \`cancelled\`, \`incomplete\`) match the stream's names. Code that
polls for the literal string \`completed\` will never see success terminate. Poll until \`status\`
leaves \`running\`/\`starting\`, treat \`"done"\` as success-side terminal, and read the actual answer
text from \`/turns\`. Useful fields on the session object: \`status\`, \`turn_status\`,
\`last_response_id\`, \`harness_id\`, \`harness_name\`, \`model\`, \`backend\`, \`user_prompt\`, \`title\`,
\`elapsed\`, \`finished_at\`, \`event_count\`.

A brand-new session normally starts within seconds (warm sandbox pool); under a burst a fresh
sandbox can take 1-2 minutes, the request waits and then runs, so treat "no first event yet" as
startup, not failure. Errors are JSON \`{ "detail": "..." }\` with standard HTTP codes (400 invalid
body, the detail says what, 401 bad key, 404 not yours or missing).

### Continue

\`\`\`json
{
  "input": "Continue where you left off and finish the remaining work.",
  "previous_response_id": "<response id>",
  "metadata": { "session_id": "<session id>" }
}
\`\`\`

### Upload a file

Upload with \`POST /v1/files\`, then reference the returned \`file_id\` in an \`input_file\` content
block. The upload, runtime request, Session, and returned files must all remain associated with the
same authorized product user or tenant.

### Sessions and files

- \`GET /v1/sessions?harness={id}&limit=20\`
- \`GET /v1/sessions/{session_id}\`
- \`GET /v1/sessions/{session_id}/turns\`
- \`POST /v1/sessions/{session_id}/cancel\`
- \`GET /v1/sessions/{session_id}/files\`
- \`GET /v1/sessions/{session_id}/files?changed=true\`
- \`GET /v1/containers/{session_id}/files/{file_id}/content\`
- \`GET /v1/sessions/{session_id}/files/archive\`, every artifact as ONE zip, folder hierarchy
  preserved (each zip entry's path is the file's relative path). Scopes: default = the whole
  workspace; \`?changed=true\` = only the most recent turn's outputs; \`?files=fid1,fid2\` = exactly
  those file ids (one specific turn's citations). Same auth rule as \`download_url\`: fetch it
  server-side and relay the bytes from your own authenticated route. Wire "Download all" to this.

Call these only from authenticated product server routes after verifying product-level ownership.

\`GET /v1/sessions/{session_id}/files\` returns:

\`\`\`json
{
  "session_id": "hsess…",
  "count": 1,
  "files": [
    {
      "path": "index.html",
      "bytes": 12117,
      "media_type": "text/html",
      "file_id": "cfile_…",
      "download_url": "${apiBase}/v1/containers/hsess…/files/cfile_…/content"
    }
  ]
}
\`\`\`

- Field names are snake_case here (\`file_id\`, \`media_type\`), the same convention as request
  bodies, unlike harness records which come back camelCase.
- \`download_url\` is simply the \`/containers/…/content\` URL for that file. It is an
  **API-key-protected endpoint, not a pre-signed public link**, it must be fetched
  server-side with the Bearer header and must never be handed to the browser. Serve the bytes
  from your own authenticated product route with \`Content-Disposition: attachment\` for
  downloads or \`inline\` for previews.
- \`file_id\` values (\`cfile_…\`) are opaque, use \`path\` for the user-facing filename
  (sanitize it to a basename before putting it in a \`Content-Disposition\` header).
- Use \`media_type\` to pick the renderer for inline display.
- Office files (DOCX/PPTX/XLSX) have a server-converted PDF preview: replace \`/content\` with
  \`/pdf\` on the same URL.

### Agent configuration and models

- \`GET /v1/harnesses\`
- \`POST /v1/harnesses\`
- \`GET | PUT | DELETE /v1/harnesses/{id}\`
- \`GET /v1/models\`
- \`GET /v1/harnesses/{id}/models\`
- \`PUT /v1/mcp-secrets/{short-name}\`
- \`GET /v1/harnesses/{id}/skills/{name}/files\`

Facts the schema will not tell you:

- Request bodies are snake_case (\`default_model\`, \`max_step\`); harness records in responses
  return camelCase (\`defaultModel\`, \`maxStep\`), but session and file objects return
  snake_case (\`session_id\`, \`file_id\`). Check each payload rather than assuming one
  convention. A \`null\` \`maxStep\`/\`timeoutSeconds\` (or an empty-string \`defaultModel\`) means
  the server defaults apply at run time (400 steps / 1800 s / backend default model).
- Skills install as folders: \`skills[]\` entries are \`{name, files:[{path, content|content_b64}]}\`;
  \`path\` keeps relative directories and the root \`SKILL.md\` needs YAML frontmatter (\`name\`,
  \`description\`). Bundles over ~48 KB round-trip as \`{name, enabled, blob}\` with no \`files\` —
  this is normal; pass such entries back unchanged on update, and read the real files back with
  \`GET /v1/harnesses/{id}/skills/{name}/files\`.
- Every base agent already includes document skills (docx, pdf, pptx, xlsx), Office
  deliverables need no custom skill.
- \`additional_headers[]\` declares header NAMES the product forwards on each run for app-level
  auth (for example a per-user JWT): declare \`"X-App-JWT"\`, send that header on each
  \`/responses\` call, and reference it in an MCP server's \`auth\` as \`"$headers.X-App-JWT"\` —
  injected per request, never stored. This is the supported path for per-tenant downstream
  identity.

Treat the deployed API schema as the source of truth for exact fields and capability metadata;
do not invent unsupported behavior.

---

## Done conditions

Before finishing, confirm all of these conditions:

- The request was classified as host-product work, runtime work, or Harness administration.
- The host-app goal and runtime-agent purpose are written separately.
- No host-product request was forwarded to the runtime agent.
- When the task required an authenticated HarnessRouter operation, \`KEY_SETUP_STATUS\` reached
  \`READY\` through Step 0 before the first authenticated request. Otherwise, the non-ready status
  was recorded and no authenticated request was made.
- An appropriate configured agent was reused, updated, or created without duplication.
- The host app contains authenticated, tenant-authorized server routes for run, recovery,
  Continue, cancel, files, previews, and downloads as required by the feature.
- Every initial runtime request includes a unique \`Idempotency-Key\`.
- The stream parser dispatches on \`data.type\` rather than the SSE event name and accepts unknown
  types.
- The host app was started and a representative end-user task was submitted through it.
- Streaming, terminal state, files, rendering, Recall, and Continue/Revise were verified.
- Cross-user access to Session and files was rejected.
- The final result is a working product integration, not merely a successful direct Harness run.
`;
}
