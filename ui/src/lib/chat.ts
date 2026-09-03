// Live chat against the harness gateway's OpenAI Responses-compatible surface (via the
// /api/harness BFF). One POST /v1/responses with stream:true returns an SSE stream of native
// Responses events; we dispatch reasoning / tool-call / tool-output / text deltas + file
// citations to the caller. previous_response_id chains turns (server reconstructs context).
//
// Auth: the BFF injects the internal trust key; we pass the signed-in org/member as headers so
// the gateway resolves the principal (the browser never holds a key).
//
// SSE framing + native-Responses event dispatch live in the shared UI Core package
// (frontend-ui-core/src/stream/responses.js), this file owns only the HR transport
// (BFF endpoints, auth headers, request body shape).
import { harnessFetch } from '@/lib/hfetch';
import { getSession } from '@/lib/auth';
import { workspaceHeaders } from '@/lib/workspace';
import { pumpResponsesStream, readSSEStream } from 'reifyui';

const BASE = '/api/harness';

export interface RespFile { container_id: string; file_id: string; filename: string }

export interface StreamHandlers {
  onCreated?(responseId: string): void;
  onSession?(sessionId: string): void;   // the server-side session id (for Recents highlight + refresh)
  onReasoningDelta?(text: string): void;
  onToolCall?(name: string, args: string, callId: string): void;
  onToolResult?(callId: string, output: string): void;
  onTextDelta?(text: string): void;
  onFile?(f: RespFile): void;
  onDone?(status: string, response: unknown): void;
  onError?(message: string): void;
}

export interface StreamOpts {
  input: string | unknown[];
  model?: string;
  backend?: string | null;
  previousResponseId?: string | null;
  sessionHint?: string | null;  // known active session, fallback continuity signal so a
                                // follow-up never forks a new session when the response id
                                // was lost client-side (interrupted stream, tab switch)
  instructions?: string;
  harnessId?: string;       // tags the session/trace (per-harness Recents + Traces)
  harnessName?: string;
  extraHeaders?: Record<string, string>;  // Additional Headers (app-level auth) sent on this call
}

export function authHeaders(): Record<string, string> {
  const s = getSession();
  return {
    'content-type': 'application/json',
    'x-harness-org': s?.orgId || '',
    'x-harness-member': s?.member?.email || s?.member?.id || '',
    // Active workspace: new sessions/turns are stamped with it gateway-side.
    ...workspaceHeaders(),
  };
}

/** A file_data data-URI for an input_file content block. */
export function fileToDataUri(mediaType: string, base64: string): string {
  return `data:${mediaType || 'application/octet-stream'};base64,${base64}`;
}

/** Download URL for a turn-produced container file (served by the BFF -> gateway). */
export function containerFileUrl(f: RespFile): string {
  return `${BASE}/v1/containers/${encodeURIComponent(f.container_id)}/files/${encodeURIComponent(f.file_id)}/content`;
}

/** Authenticated fetch of a container/archive file. Since LIVE-B the gateway verifies the login
 *  JWT on every file read, so bare <a href>/<iframe src>/fetch (headerless) 401, THE way to load
 *  artifact bytes is this helper; renderers turn the Blob into an object URL. */
export async function fetchFileBlob(url: string): Promise<Blob> {
  const r = await harnessFetch(url, { headers: authHeaders() });
  if (!r.ok) throw new Error(`${r.status}`);
  return r.blob();
}

/** Authenticated download: fetch to a Blob, then trigger a client-side save. */
export async function downloadFile(url: string, filename: string): Promise<void> {
  const b = await fetchFileBlob(url);
  const obj = URL.createObjectURL(b);
  const a = document.createElement('a');
  a.href = obj;
  a.download = filename || 'download';
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(obj), 4000);
}

export interface SessionTurn {
  id: string; status: string; user: string; assistant: string;
  /** What this turn alone took and cost; absent on turns from before the gateway kept them. */
  elapsed?: number | null; credits?: number | null;
  user_files?: { name: string }[];   // caller-attached input files (names; bytes live in the workspace)
  tools: { name: string; arguments: string; result?: string }[]; files: RespFile[];
}

/** Load a past session's conversation (user + assistant per turn) to show its chat history.
 *  Bounded to the last 200 turns, far beyond any real session, but it keeps a pathological
 *  long-horizon history from fanning out hundreds of storage reads on every open. */
export async function loadSessionTurns(sid: string): Promise<{ turns: SessionTurn[]; lastResponseId: string | null }> {
  const res = await harnessFetch(`${BASE}/v1/sessions/${encodeURIComponent(sid)}/turns?limit=200`, { headers: authHeaders() });
  if (!res.ok) return { turns: [], lastResponseId: null };
  const d = await res.json();
  return { turns: d.turns || [], lastResponseId: d.last_response_id || null };
}

/** Stop a running session's turn (kills the CLI in the sandbox; terminal event follows on the bus).
 *  Returns the server's verdict so the caller can settle its UI even if the bus event is missed:
 *  cancelled=true means the turn was stopped NOW; a terminal status with cancelled=false means
 *  there was no running turn to stop (already settled, treat as terminal too). */
export async function cancelSession(sid: string): Promise<{ cancelled: boolean; status: string }> {
  const res = await harnessFetch(`${BASE}/v1/sessions/${encodeURIComponent(sid)}/cancel`, {
    method: 'POST', headers: authHeaders(), cache: 'no-store',
  });
  if (!res.ok) return { cancelled: false, status: '' };
  const d = await res.json().catch(() => ({} as Record<string, unknown>));
  return { cancelled: Boolean(d.cancelled), status: String(d.status || '') };
}

export interface BusMsg { session_id: string; response_id: string; member?: string; event: Record<string, unknown>; replay?: boolean }

/**
 * Subscribe to a harness's realtime broadcast bus: every event of every one of this harness's
 * sessions (per-user filtered server-side), tagged with session_id. This is the UI's source of
 * truth for live updates, independent of which tab/POST started the turn, so switching
 * conversations, opening a session started elsewhere, or reconnecting never misses an update.
 * Auto-reconnects with backoff. Returns an unsubscribe fn.
 */
export function subscribeHarnessEvents(harnessId: string, onMsg: (m: BusMsg) => void): () => void {
  let stopped = false;
  let ctrl: AbortController | null = null;
  const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
  (async () => {
    while (!stopped) {
      ctrl = new AbortController();
      try {
        const res = await harnessFetch(`${BASE}/v1/harnesses/${encodeURIComponent(harnessId)}/events`, {
          headers: authHeaders(), cache: 'no-store', signal: ctrl.signal,
        });
        if (!res.ok || !res.body) { await sleep(2000); continue; }
        await readSSEStream(res.body, (data: string) => {
          try { onMsg(JSON.parse(data) as BusMsg); } catch { /* ignore malformed frame */ }
        });
      } catch { /* network drop / abort, fall through to reconnect */ }
      if (!stopped) await sleep(1500);
    }
  })();
  return () => { stopped = true; ctrl?.abort(); };
}

/**
 * Run one turn, streaming native Responses events to `h`. Returns the new response id (for
 * chaining the next turn via previousResponseId). Throws only on transport/HTTP failure; agent
 * failures arrive as onError + a final onDone('failed', ...).
 */
export async function streamResponse(
  opts: StreamOpts, h: StreamHandlers, signal?: AbortSignal,
): Promise<string | null> {
  const body: Record<string, unknown> = {
    input: opts.input,
    stream: true,
    store: true,
  };
  // Send a real model only, NEVER the bare backend name ("claude"/"codex"), which isn't a valid
  // provider model id and 400s on e.g. Bedrock. Routing still works via `backend`; when no model is
  // set the gateway inherits the previous round's model / harness default.
  if (opts.model) body.model = opts.model;
  if (opts.backend) body.backend = opts.backend;
  if (opts.previousResponseId) body.previous_response_id = opts.previousResponseId;
  if (opts.instructions) body.instructions = opts.instructions;
  const metadata: Record<string, string> = {};
  if (opts.harnessId) metadata.harness_id = opts.harnessId;
  if (opts.harnessName) metadata.harness_name = opts.harnessName;
  if (opts.sessionHint) metadata.session_id = opts.sessionHint;
  if (opts.model) metadata.model = opts.model;       // gateway honors this real model over the connection default
  if (Object.keys(metadata).length) body.metadata = metadata;

  const res = await harnessFetch(`${BASE}/v1/responses`, {
    method: 'POST', headers: { ...authHeaders(), ...(opts.extraHeaders || {}) },
    body: JSON.stringify(body), signal, cache: 'no-store',
  });
  if (!res.ok || !res.body) {
    const t = await res.text().catch(() => '');
    // Surface the server's own message when it sent one (e.g. the out-of-credits 402) instead of
    // raw status + JSON, the user sees the actionable sentence, not a transport artifact.
    let detail = '';
    try { detail = String((JSON.parse(t) as { detail?: unknown })?.detail || ''); } catch { /* not JSON */ }
    throw new Error(detail || `responses failed: ${res.status} ${t.slice(0, 200)}`);
  }

  // Shared parser: SSE framing + native-Responses dispatch (tool-call pairing by output_index)
  // live in UI Core; resolves to the response id for previousResponseId chaining.
  const responseId: string | null = await pumpResponsesStream(res.body, h);
  return responseId;
}
