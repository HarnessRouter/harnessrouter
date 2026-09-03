'use client';
// The full HarnessRouter API reference, rendered with the premiere apidoc components
// (method chips, param tables, syntax-highlighted code cards). Lives on the AGENTS.md
// page; the old per-harness workbench Integrate tab was merged into this and removed.
// Pass harnessId/additionalHeaders to scope the examples to one harness; omit them for
// the generic {harness_id} form.
import React, { useState } from 'react';
import { PrismAsync as SyntaxHL } from 'react-syntax-highlighter';
import oneLightTheme from 'react-syntax-highlighter/dist/esm/styles/prism/one-light';

export function CodeBlock({ code, lang = 'bash' }: { code: string; lang?: string }) {
  const [copied, setCopied] = useState(false);
  const label = lang === 'bash' || lang === 'sh' ? 'cURL' : lang === 'json' ? 'JSON'
    : lang === 'python' ? 'Python' : lang === 'javascript' || lang === 'js' ? 'Node' : lang.toUpperCase();
  return (
    <div className="apidoc-code">
      <div className="apidoc-code-head">
        <span className="apidoc-code-lang">{label}</span>
        <button className="apidoc-code-copy" onClick={() => { navigator.clipboard?.writeText(code); setCopied(true); setTimeout(() => setCopied(false), 1200); }}>{copied ? 'Copied' : 'Copy'}</button>
      </div>
      <SyntaxHL language={lang} style={oneLightTheme}
        customStyle={{ margin: 0, padding: '14px 16px', background: 'transparent', fontSize: 12.5, lineHeight: 1.6, whiteSpace: 'pre', overflowX: 'auto' }}
        codeTagProps={{ style: { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', color: '#383A42' } }}>{code}</SyntaxHL>
    </div>
  );
}

function Param({ name, type, req, children }: { name: string; type: string; req?: boolean; children: React.ReactNode }) {
  return (
    <tr>
      <td><code>{name}</code></td>
      <td className="apidoc-ty">{type}</td>
      <td>{req ? <span className="apidoc-req">required</span> : <span className="apidoc-opt">optional</span>}</td>
      <td>{children}</td>
    </tr>
  );
}
function ParamTable({ children }: { children: React.ReactNode }) {
  return (
    <table className="apidoc-tbl"><thead><tr><th>Field</th><th>Type</th><th></th><th>Description</th></tr></thead>
      <tbody>{children}</tbody></table>
  );
}
function Endpoint({ method, path, children }: { method: string; path: string; children: React.ReactNode }) {
  return (
    <section className="apidoc-ep">
      <div className="apidoc-ep-head"><span className={'apidoc-m apidoc-m-' + method.toLowerCase()}>{method}</span><code className="apidoc-path">{path}</code></div>
      {children}
    </section>
  );
}

export function ApiReference({ harnessId, additionalHeaders, model: modelIn }: {
  harnessId?: string; additionalHeaders?: string[]; model?: string;
}) {
  const addHdrs = (additionalHeaders || []).filter(Boolean);
  const hid = harnessId || '{harness_id}';
  const apiBase = `https://api.harnessrouter.ai/${hid}/v1`;   // task runs (per-agent)
  const mgmtBase = 'https://api.harnessrouter.ai/v1';         // everything else
  const model = modelIn || 'gpt-5.5';

  return (
    <div className="apidoc">
      <h2>API reference</h2>
      <p className="hr-meta" style={{ maxWidth: 760 }}>
        HarnessRouter speaks the <b>OpenAI Responses API</b>. Point any OpenAI SDK&apos;s base URL at your
        harness endpoint and it works unmodified, streaming, multi-turn chaining, and file in/out. The
        model field selects the paired LLM; the harness itself is the path.
      </p>

      <div className="apidoc-kv">
        <div><span className="apidoc-kv-k">Task base URL</span><code>{apiBase}</code></div>
        <div><span className="apidoc-kv-k">Management base URL</span><code>{mgmtBase}</code></div>
        <div><span className="apidoc-kv-k">Auth</span><code>Authorization: Bearer &lt;HARNESSROUTER_API_KEY&gt;</code></div>
        <div><span className="apidoc-kv-k">Content type</span><code>application/json</code></div>
      </div>

      <h3 className="apidoc-h3">Authentication</h3>
      <p className="hr-meta">Every request carries a per-org API key (mint one under API keys) as a Bearer
        token. Keys are scoped to your organization; the harness is chosen by the path, the LLM by the
        model field. Task runs use the per-agent form <code>/{'{harness_id}'}/v1/…</code>; management
        routes (harness CRUD, secrets, sessions) are plain <code>/v1/…</code>. Wire all of this behind a
        server route in your product so the key stays on the server, then surface the answer and file
        download links in your UI.</p>
      <CodeBlock lang="bash" code={`curl ${apiBase}/responses \\
  -H "Authorization: Bearer $HARNESSROUTER_API_KEY" \\
  -H "Content-Type: application/json" \\
${addHdrs.map((h) => `  -H "${h}: <value>" \\\n`).join('')}  -d '{ "model": "${model}", "input": "Summarize this contract." }'`} />

      <h3 className="apidoc-h3">Additional headers (app-level auth)</h3>
      <p className="hr-meta">
        A harness can declare custom request headers your product sends on every call, typically a
        per-user JWT. At task start their values are injected into the harness&apos;s tool connections
        (referenced in the MCP config as <code>$headers.&#123;Name&#125;</code>), so each task acts with
        your end user&apos;s authority. Values live for one turn only and are never stored. A request
        that omits a header referenced by an enabled tool connection fails fast with a 400 naming the
        missing header. Declare the names in the harness config (Config &amp; Preview, Additional
        Headers) or via <code>additional_headers</code> on the harness API.
      </p>
      {addHdrs.length > 0 && (
        <div className="apidoc-kv">
          {addHdrs.map((h) => (
            <div key={h}><span className="apidoc-kv-k">{h}</span><code>{'$headers.' + h}</code></div>
          ))}
        </div>
      )}

      {/* ── Run a task ──────────────────────────────────────────────────── */}
      <h3 className="apidoc-h3">Run a task</h3>
      <Endpoint method="POST" path="/{harness_id}/v1/responses">
        <p className="hr-meta">Run one turn of a harness. Returns a response object, or a stream of
          Server-Sent Events when stream is true. Chain turns with previous_response_id.</p>
        <div className="apidoc-sub">Request body</div>
        <ParamTable>
          <Param name="model" type="string" req>The underlying LLM to run this harness on (e.g. <code>{model}</code>, <code>claude-opus-4.8</code>). The harness itself is selected by the <code>{'{harness_id}'}</code> path segment, not here.</Param>
          <Param name="input" type="string | array" req>The user message, or an array of input items (<code>input_text</code>, <code>input_file</code>, <code>input_image</code>).</Param>
          <Param name="stream" type="boolean">Stream the answer as SSE events as they are produced (recommended for anything over a minute; keepalives flow every ~15s). Default <code>false</code>.</Param>
          <Param name="store" type="boolean">Persist the response so it can be retrieved / chained. Default <code>true</code>.</Param>
          <Param name="previous_response_id" type="string">Continue a prior turn, the server reconstructs the full context.</Param>
          <Param name="instructions" type="string">System/developer instructions prepended to this turn (first turn only).</Param>
          <Param name="metadata" type="object">Up to 16 key/value string pairs attached to the response. <code>metadata.session_id</code> doubles as a continuation fallback (send it together with <code>previous_response_id</code>).</Param>
          <Param name="max_step" type="integer">Per-request override of the agent&apos;s step budget (harness default, else 400).</Param>
          <Param name="timeout_seconds" type="integer">Per-request override of the per-task wall-clock cap (harness default, else 1800).</Param>
        </ParamTable>
        <div className="apidoc-sub">Response (200)</div>
        <CodeBlock lang="json" code={`{
  "id": "resp_8f1c…",
  "object": "response",
  "created_at": 1782154510,
  "status": "completed",
  "model": "${model}",
  "output": [
    { "type": "message", "role": "assistant",
      "content": [ { "type": "output_text", "text": "…" } ] }
  ],
  "usage": { "input_tokens": 412, "output_tokens": 88, "total_tokens": 500 },
  "metadata": { "session_id": "hsn_…" },
  "previous_response_id": null
}`} />
        <p className="hr-meta"><code>output[]</code> is the FULL transcript, tool items first, then the
          answer. Filter for <code>type === &quot;message&quot;</code> and read its <code>output_text</code> blocks;
          never render <code>output[0]</code> blindly. Files the agent produced appear on those text blocks
          as <code>container_file_citation</code> annotations, each with a ready-to-use
          <code> download_url</code>. Save <code>metadata.session_id</code>, it identifies the agent&apos;s
          working folder.</p>
        <div className="apidoc-sub">Streaming (SSE)</div>
        <p className="hr-meta">With stream enabled the body is a <span className="apidoc-tok">text/event-stream</span> in
          the OpenAI Responses style: <b><code>data:</code>-only frames, no <code>event:</code> lines</b>, the event name
          is the <code>type</code> field inside the JSON. Dispatch on <code>data.type</code> (a parser keyed on the SSE
          event name sees every frame as <code>message</code> and matches nothing), and ignore unknown types, the set is
          open. A real first frame:</p>
        <CodeBlock lang="text" code={`data: {"type": "response.created", "sequence_number": 0, "response": {"id": "resp_…", "status": "in_progress", "metadata": {"session_id": "hsess…"}, …}}`} />
        <p className="hr-meta">Recovery identifiers are <b>nested</b>: <code>data.response.id</code> and
          <code> data.response.metadata.session_id</code>, save both the moment <code>response.created</code> arrives.</p>
        <CodeBlock lang="text" code={`response.created                        # save response.id + response.metadata.session_id NOW
response.output_text.delta
response.reasoning_summary_text.delta
response.output_item.added
response.function_call_arguments.done
response.output_text.annotation.added   # container file citations
response.completed | response.failed | response.incomplete   # terminal`} />
        <p className="hr-meta">If the stream drops mid-run, the task is still running, recover instead
          of retrying: poll <code>GET /v1/sessions/&#123;session_id&#125;</code> until <code>status</code> is
          terminal, then read the answer from <code>/turns</code> and outputs from
          <code> /files?changed=true</code>. Only re-POST (same <code>Idempotency-Key</code>) if the run
          never emitted <code>response.created</code>. <code>incomplete</code> is not failure, the agent
          hit its step/time budget; offer a Continue action that sends a follow-up with
          <code> previous_response_id</code>. Vocabulary trap: the session object reports SUCCESS as
          <code> status: &quot;done&quot;</code>, not <code>completed</code> (failure-side names match), so poll until
          <code> status</code> leaves <code>running</code>/<code>starting</code> and treat <code>done</code> as success.</p>
        <div className="apidoc-sub">Timing</div>
        <p className="hr-meta">A brand-new session normally starts within a few seconds (a pool of warm
          sandboxes is kept ready). Under a burst that drains the warm pool, a fresh sandbox can take 1-2
          minutes to spin up; the request waits and then runs, it never times out from this. Keep
          streaming on and treat &quot;no first event yet&quot; as startup, not failure. Follow-up turns on an
          existing session skip startup entirely.</p>
        <div className="apidoc-sub">Idempotency</div>
        <p className="hr-meta">Send an <code>Idempotency-Key</code> header (any unique string per logical
          request) to make retries safe: if a request with the same key is retried, after a network
          drop or a timeout, the gateway returns the <em>first</em> request&apos;s response instead of
          starting a second run. Reuse the same key only for retries of the same request; use a fresh
          key for each new one.</p>
      </Endpoint>

      <Endpoint method="GET" path="/v1/responses/{response_id}">
        <p className="hr-meta">Retrieve a stored response by id.</p>
        <CodeBlock lang="bash" code={`curl ${mgmtBase}/responses/resp_8f1c… \\
  -H "Authorization: Bearer $HARNESSROUTER_API_KEY"`} />
      </Endpoint>

      <Endpoint method="DELETE" path="/v1/responses/{response_id}">
        <p className="hr-meta">Delete a stored response. Returns <code>{`{ "id": "…", "deleted": true }`}</code>.</p>
      </Endpoint>

      <Endpoint method="POST" path="/v1/sessions/{session_id}/cancel">
        <p className="hr-meta">Hard-cancel the running turn: the agent process is killed inside the
          sandbox immediately, the turn is marked <code>cancelled</code>, and a terminal
          <code> response.failed</code> event (reason <code>cancelled</code>) is emitted to any open
          stream. Idempotent: safe to call twice, or when no turn is running (returns
          <code> {`"cancelled": false`}</code>). The session itself survives, send a new message to
          continue from the last completed state of the workspace. Wire your Stop button to this.</p>
        <CodeBlock lang="bash" code={`curl -X POST ${mgmtBase}/sessions/{session_id}/cancel \\
  -H "Authorization: Bearer $HARNESSROUTER_API_KEY"
# -> { "session_id": "…", "status": "cancelled", "cancelled": true, "runner_killed": true }`} />
      </Endpoint>

      {/* ── Files ───────────────────────────────────────────────────────── */}
      <h3 className="apidoc-h3">Files</h3>
      <Endpoint method="POST" path="/v1/files">
        <p className="hr-meta">Upload a file (multipart/form-data) to reference from <code>input_file</code> in a later turn.
          The file lands in the agent&apos;s working folder with its original name before the run starts.
          Returns <code>{`{ "id": "file_…", "filename": "…", "bytes": 12345 }`}</code>.</p>
        <CodeBlock lang="bash" code={`curl ${mgmtBase}/files \\
  -H "Authorization: Bearer $HARNESSROUTER_API_KEY" \\
  -F purpose=input -F file=@contract.pdf`} />
      </Endpoint>

      <Endpoint method="GET" path="/v1/sessions/{session_id}/files">
        <p className="hr-meta">List the session workspace. Two views of the same working folder:
          the default is the FULL accumulated list (every user-visible file across all turns);
          <code> ?changed=true</code> returns only the files created or modified in the MOST RECENT turn
          (use it for &quot;what this run produced&quot;). Each entry carries <code>path</code>, <code>bytes</code>,
          <code> media_type</code>, <code>file_id</code>, <code>download_url</code>, snake_case, unlike harness
          records. <code>download_url</code> is an API-key-protected endpoint, <b>not</b> a pre-signed public
          link: fetch it server-side with the Bearer header and relay the bytes from your own authenticated
          route. <code>file_id</code> is opaque (<code>cfile_…</code>), the user-facing filename comes from
          <code> path</code> (sanitize to a basename for <code>Content-Disposition</code>).</p>
        <CodeBlock lang="bash" code={`curl ${mgmtBase}/sessions/{session_id}/files \\
  -H "Authorization: Bearer $HARNESSROUTER_API_KEY"
curl "${mgmtBase}/sessions/{session_id}/files?changed=true" \\
  -H "Authorization: Bearer $HARNESSROUTER_API_KEY"
# -> { "count": 2, "files": [ { "path": "report.docx", "bytes": 18244, "file_id": "…", "download_url": "…" } ] }`} />
      </Endpoint>

      <Endpoint method="GET" path="/v1/containers/{session_id}/files/{file_id}/content">
        <p className="hr-meta">Download any workspace file by <code>file_id</code>, from the files listing
          above, or from a <code>container_file_citation</code> annotation on a response. Returns the raw
          bytes with a <code>Content-Disposition</code> filename, so you can stream it straight to the
          user as a download.</p>
      </Endpoint>

      <Endpoint method="GET" path="/v1/sessions/{session_id}/files/archive">
        <p className="hr-meta">Every artifact as ONE zip, with the workspace folder hierarchy preserved —
          each zip entry&apos;s path is the file&apos;s relative path (<code>slide_png/deck.png</code> stays in its
          folder). Scopes: default = the whole workspace; <code>?changed=true</code> = only the most recent
          turn&apos;s outputs; <code>?files=fid1,fid2</code> = exactly those file ids (one specific turn&apos;s
          citations). Responds <code>application/zip</code> with a <code>Content-Disposition</code> filename —
          wire &quot;Download all&quot; buttons straight to it. Workspaces over 512&nbsp;MB return 413
          (download files individually).</p>
        <CodeBlock lang="bash" code={`curl -o files.zip "${mgmtBase}/sessions/{session_id}/files/archive?changed=true" \\
  -H "Authorization: Bearer $HARNESSROUTER_API_KEY"`} />
      </Endpoint>

      {/* ── Sessions ────────────────────────────────────────────────────── */}
      <h3 className="apidoc-h3">Sessions (task runs)</h3>
      <Endpoint method="GET" path="/v1/sessions?harness={id}&limit=20">
        <p className="hr-meta">Newest-first run cards: <code>session_id</code>, <code>title</code>,
          <code> status</code> (card vocabulary: <code>running</code> | <code>done</code> |
          <code> incomplete</code> | <code>failed</code> | <code>cancelled</code>, <code>done</code> here
          corresponds to <code>completed</code> on /responses), <code>model</code>, <code>elapsed</code>,
          <code> finished_at</code>, <code>last_response_id</code>. Build your &quot;recent tasks&quot; UI from
          this, no local storage needed. Ignore extra fields you don&apos;t recognize.</p>
      </Endpoint>

      <Endpoint method="GET" path="/v1/sessions/{session_id}">
        <p className="hr-meta">One run&apos;s full state: status, timestamps, harness, last ids.</p>
      </Endpoint>

      <Endpoint method="GET" path="/v1/sessions/{session_id}/turns">
        <p className="hr-meta">The full conversation (user + assistant per turn) for rendering history,
          plus <code>last_response_id</code> for continuation.</p>
      </Endpoint>

      {/* ── Manage agents ───────────────────────────────────────────────── */}
      <h3 className="apidoc-h3">Manage agents (harnesses)</h3>
      <Endpoint method="POST" path="/v1/harnesses">
        <p className="hr-meta">Create an agent. Returns the agent with its <code>id</code> (looks like
          <code> chrn_…</code>), that id is the task path segment.</p>
        <div className="apidoc-sub">Request body</div>
        <ParamTable>
          <Param name="name" type="string" req>Display name.</Param>
          <Param name="base" type="string" req><code>&quot;codex&quot;</code> | <code>&quot;claude-code&quot;</code>.</Param>
          <Param name="default_model" type="string">Model used when a run omits <code>model</code>.</Param>
          <Param name="system_prompt" type="string">The agent&apos;s instructions (written into its workspace as AGENTS.md / CLAUDE.md).</Param>
          <Param name="mcp_servers" type="array">Tool connections: <code>{`{name, url, auth?, enabled}`}</code>. For <code>auth</code>, pass a secrets ref (below) or a <code>$headers.&#123;Name&#125;</code> per-request reference.</Param>
          <Param name="skills" type="array"><code>{`{name, files:[{path, content|content_b64}]}`}</code>, a bundle MUST include a <code>SKILL.md</code>; invalid bundles are rejected with 400. Skills can be whole folders: <code>path</code> is the file&apos;s relative path inside the skill (nested layouts like <code>guides/SKILL.md</code> install as-is); the root <code>SKILL.md</code> needs YAML frontmatter (<code>name</code>, <code>description</code>). Bundles over ~48&nbsp;KB are offloaded server-side and the saved agent returns that skill as <code>{`{name, enabled, blob}`}</code> with no <code>files</code>, normal; the folder still mounts into every run. On later updates pass such entries back unchanged; only include <code>files</code> when changing content.</Param>
          <Param name="disabled_tools" type="array">Inherited/built-in tool names to disable.</Param>
          <Param name="additional_headers" type="array">Header NAMES your product passes per request for app-level auth (see Additional headers above).</Param>
          <Param name="max_step" type="integer">Default agent step budget (default 400).</Param>
          <Param name="timeout_seconds" type="integer">Default per-task wall-clock cap (default 1800).</Param>
        </ParamTable>
        <p className="hr-meta">Casing note: request bodies are snake_case (<code>default_model</code>,
          <code> mcp_servers</code>, <code>max_step</code>); responses come back camelCase
          (<code>defaultModel</code>, <code>mcpServers</code>, <code>maxStep</code>). A <code>null</code>
          <code> maxStep</code>/<code>timeoutSeconds</code> means unset, server defaults apply at run time.</p>
      </Endpoint>

      <Endpoint method="GET" path="/v1/harnesses">
        <p className="hr-meta">List every agent in the account.</p>
      </Endpoint>

      <Endpoint method="PUT" path="/v1/harnesses/{id}">
        <p className="hr-meta">Read (<code>GET</code>), update (<code>PUT</code>, same body as create), or
          delete (<code>DELETE</code>) one agent. PUT returns the stored canonical record.</p>
      </Endpoint>

      <Endpoint method="GET" path="/v1/harnesses/{id}/skills/{name}/files">
        <p className="hr-meta">Read one skill&apos;s full files back (resolves the server-side offload of
          large bundles), for verification or editing. <code>{`{name}`}</code> matches the skill&apos;s
          <code> id</code> or <code>name</code>; returns <code>{`{ id, name, files: [{path, content|content_b64}] }`}</code>.</p>
      </Endpoint>

      <Endpoint method="GET" path="/v1/models">
        <p className="hr-meta">The current model catalog per engine, each with its default. Build model
          pickers from this, don&apos;t hardcode model names. The map is keyed by <b>backend</b>, not
          base-harness name: base <code>claude-code</code> corresponds to the key <code>claude</code>. An
          empty-string <code>defaultModel</code> on a harness means the backend default applies.</p>
      </Endpoint>

      <Endpoint method="GET" path="/v1/harnesses/{id}/models">
        <p className="hr-meta">The models this agent may run, its default, and the fallback. A run
          requesting a model outside this set executes on the fallback, and the substitution is recorded
          in <code>response.metadata</code> (<code>requested_model</code>, <code>model_fallback</code>).</p>
      </Endpoint>

      {/* ── Rendering results ───────────────────────────────────────────── */}
      <h3 className="apidoc-h3">Render results in your product</h3>
      <p className="hr-meta">Don&apos;t stop at download buttons. <code>download_url</code> serves bytes with
        <code> Content-Disposition: attachment</code>, right for download links, wrong for inline display —
        so for inline rendering fetch the bytes through your server route and hand your UI a blob / text.
        Then by type: <b>markdown/text</b> → render as markdown; <b>images</b> → inline <code>&lt;img&gt;</code>;
        <b> PDF</b> → <code>&lt;iframe&gt;</code> on the blob; <b>DOCX/PPTX/XLSX</b> → download link, inline preview
        via the server-converted PDF (replace <code>/content</code> with <code>/pdf</code> in the same URL);
        <b> CSV</b> → table; <b>code</b> → monospace block with its <code>path</code>; <b>HTML app/game</b> →
        instruct the agent to emit one self-contained <code>index.html</code> and render it in a sandboxed
        <code> &lt;iframe srcdoc&gt;</code>; <b>multi-file project</b> → group by directory (paths keep folders) and
        offer &quot;Download all&quot; via the archive endpoint below; <b>anything else</b> → filename +
        size + download. Never render nothing.</p>

      <Endpoint method="PUT" path="/v1/mcp-secrets/{short-name}">
        <p className="hr-meta">Store a tool-connection access key: body <code>{`{ "token": "..." }`}</code>;
          returns <code>{`{ "ref": "..." }`}</code>, an opaque reference to use as the connection&apos;s
          <code> auth</code>. The raw key is never stored in config and never travels through
          conversation history.</p>
      </Endpoint>

      {/* ── SDKs ────────────────────────────────────────────────────────── */}
      <h3 className="apidoc-h3">SDKs</h3>
      <div className="apidoc-sub">Python (OpenAI SDK, drop-in)</div>
      <CodeBlock lang="python" code={`from openai import OpenAI
client = OpenAI(api_key="$HARNESSROUTER_API_KEY", base_url="${apiBase}")

r = client.responses.create(model="${model}", input="Summarize this contract.")
print(r.output_text)

# multi-turn (context is reconstructed server-side):
r2 = client.responses.create(model="${model}", previous_response_id=r.id,
                             input="Now list the risky clauses.")

# streaming:
with client.responses.stream(model="${model}", input="Draft an NDA.") as stream:
    for event in stream:
        if event.type == "response.output_text.delta":
            print(event.delta, end="")`} />
      <div className="apidoc-sub">Node (OpenAI SDK)</div>
      <CodeBlock lang="javascript" code={`import OpenAI from "openai";
const client = new OpenAI({ apiKey: process.env.HARNESSROUTER_API_KEY, baseURL: "${apiBase}" });

const r = await client.responses.create({ model: "${model}", input: "Summarize this contract." });
console.log(r.output_text);`} />

      {/* ── Errors ──────────────────────────────────────────────────────── */}
      <h3 className="apidoc-h3">Errors</h3>
      <p className="hr-meta">Errors use standard HTTP status codes with an OpenAI-style body. Streaming failures arrive as a terminal <code>response.failed</code> event.</p>
      <ParamTable>
        <Param name="401" type="error" >Missing or invalid API key.</Param>
        <Param name="404" type="error" >Unknown harness or response id.</Param>
        <Param name="400" type="error" >Malformed request, e.g. empty input, an invalid skill bundle, or a missing declared header referenced by a tool connection (the message names it).</Param>
        <Param name="429" type="error" >Rate limited, retry with backoff.</Param>
        <Param name="500" type="error" >Harness execution error (details in error.message).</Param>
      </ParamTable>
      <CodeBlock lang="json" code={`{ "error": { "type": "harness_error", "message": "…", "code": null } }`} />
    </div>
  );
}
