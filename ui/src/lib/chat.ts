// Live chat against the harness gateway's OpenAI Responses-compatible surface (via the
// /api/harness BFF). One POST /v1/responses with stream:true returns an SSE stream of native
// Responses events; we dispatch reasoning / tool-call / tool-output / text deltas + file
// citations to the caller. previous_response_id chains turns (server reconstructs context).
//
// Auth: the BFF injects the internal trust key; we pass the signed-in org/member as headers so
// the gateway resolves the principal (the browser never holds a key).
//
// SSE framing + native-Responses event dispatch live in the shared reifyui package; this file owns
// only the HR transport (BFF endpoints, auth headers, request body shape).
import { harnessFetch } from '@/lib/hfetch';
import { getSession } from '@/lib/auth';
import { workspaceHeaders } from '@/lib/workspace';
import { createResponsesDispatcher, readSSEStream } from 'reifyui';

const BASE = '/api/harness';

/** A file a turn produced, served from the turn's container. */
/** A file a turn produced. `url`: served as it is (a recorded run's own copy, start/replay.ts) rather
 *  than from the turn's container. */
export interface RespFile { container_id: string; file_id: string; filename: string; url?: string }

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
  /** Every event as it arrives, before the callbacks above: the conversation folds these into the
   *  turn's clock (when each call started and answered), which the callbacks do not carry. */
  onEvent?(ev: Record<string, unknown>): void;
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
  if (f.url) return f.url;
  return `${BASE}/v1/containers/${encodeURIComponent(f.container_id)}/files/${encodeURIComponent(f.file_id)}/content`;
}

/** Authenticated fetch of a container/archive file. Since LIVE-B the gateway verifies the login
 *  JWT on every file read, so bare <a href>/<iframe src>/fetch (headerless) 401, THE way to load
 *  artifact bytes is this helper; renderers turn the Blob into an object URL. */
export async function fetchFileBlob(url: string): Promise<Blob> {
  const r = await harnessFetch(url, { headers: authHeaders() });
  if (!r.ok) {
    let why = '';
    try { why = String(((await r.json()) || {}).detail || ''); } catch { /* no body */ }
    throw new Error(why || `${r.status}`);
  }
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
  elapsed?: number | null;
  user_files?: { name: string }[];   // caller-attached input files (names; bytes live in the workspace)
  tools: { name: string; arguments: string; result?: string; output?: string; is_error?: boolean }[]; files: RespFile[];
}

/** Load a past session's conversation (user + assistant per turn) to show its chat history.
 *  Bounded to the last 200 turns, far beyond any real session, but it keeps a pathological
 *  long-horizon history from fanning out hundreds of storage reads on every open.
 *
 *  `missing` is the one "there is nothing" answer: a 404, a task that no longer exists (deleted), and
 *  the caller must not keep a composer on it. Any other failure (a 5xx, the network, a body that is
 *  not the turns) THROWS: an empty list here would read as a task that holds nothing, and a caller
 *  would draw it empty, or settle a running turn from it. `signal` ends the read (a caller's deadline). */
export async function loadSessionTurns(sid: string, signal?: AbortSignal): Promise<{ turns: SessionTurn[]; lastResponseId: string | null; missing?: boolean }> {
  const res = await harnessFetch(`${BASE}/v1/sessions/${encodeURIComponent(sid)}/turns?limit=200`,
    { headers: authHeaders(), ...(signal ? { signal } : {}) });
  if (res.status === 404) return { turns: [], lastResponseId: null, missing: true };
  if (!res.ok) throw new TurnsReadError(res.status);
  const d = await res.json().catch(() => null) as { turns?: unknown; last_response_id?: unknown } | null;
  if (!d || typeof d !== 'object' || !Array.isArray(d.turns)) throw new TurnsReadError(res.status);
  return { turns: d.turns as SessionTurn[], lastResponseId: typeof d.last_response_id === 'string' && d.last_response_id ? d.last_response_id : null };
}

/** A task's turns could not be read (not a 404): the caller shows that, never an empty task. */
export class TurnsReadError extends Error {
  constructor(public status: number) { super('This task could not be read just now.'); this.name = 'TurnsReadError'; }
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

/** Nothing at all on a stream for this long, not even the server's keepalive comment (it writes one
 *  every 15 s on a turn's own stream and on a setup's live feed): the stream died without a close. */
export const STREAM_IDLE_MS = 45_000;
/** The live feed's reconnect backoff: about 1 s, doubling, at most this. */
export const BUS_BACKOFF_MAX_MS = 30_000;
/** A feed that stayed up this long was healthy: the next drop starts the backoff over. */
const BUS_HEALTHY_MS = 60_000;

/** `body` as readSSEStream reads it, ended (a read that answers done) when nothing at all arrives for
 *  `ms`; `stalled()` then says so. `onBytes` hears every chunk, the comments between frames too. */
export function readUntilIdle(body: ReadableStream<Uint8Array>, ms: number, onBytes?: (b: Uint8Array) => void) {
  const reader = body.getReader();
  let stalled = false;
  return {
    stalled: () => stalled,
    body: {
      getReader: () => ({
        read: () => new Promise<ReadableStreamReadResult<Uint8Array>>((resolve, reject) => {
          const t = setTimeout(() => {
            stalled = true;
            reader.cancel().catch(() => { /* already ended */ });
            resolve({ done: true, value: undefined });
          }, ms);
          reader.read().then((r) => {
            clearTimeout(t);
            if (!r.done && r.value) { try { onBytes?.(r.value); } catch { /* a listener never ends the read */ } }
            resolve(r);
          }, (e) => { clearTimeout(t); reject(e); });
        }),
      }),
    },
  };
}

/** What a setup's live feed is doing: 'up' once the server's ": connected" comment arrives (it
 *  registers the listener before it writes that, so nothing after it is missed), 'down' when an open
 *  feed ended. Each 'up' after the first is a reconnect: whatever happened while it was down went to
 *  no one, and a listener reads what it follows once. */
export type BusState = 'up' | 'down';

/**
 * Subscribe to a harness's realtime broadcast bus: every event of every one of this harness's
 * sessions (per-user filtered server-side), tagged with session_id. This is the UI's source of
 * truth for live updates, independent of which tab/POST started the turn, so switching
 * conversations, opening a session started elsewhere, or reconnecting never misses an update.
 * Connects again with backoff (about 1 s, doubling to 30 s) whenever it fails or ends, and drops a
 * feed on which nothing at all arrived for STREAM_IDLE_MS (it died without a close). `onState`
 * hears each 'up' and 'down'. Returns an unsubscribe fn.
 */
export function subscribeHarnessEvents(harnessId: string, onMsg: (m: BusMsg) => void, onState?: (s: BusState) => void): () => void {
  let stopped = false;
  let ctrl: AbortController | null = null;
  let wake: (() => void) | null = null;
  const sleep = (ms: number) => new Promise<void>((r) => {
    const t = setTimeout(() => { wake = null; r(); }, ms);
    wake = () => { clearTimeout(t); wake = null; r(); };
  });
  const tell = (s: BusState) => { if (!stopped) { try { onState?.(s); } catch { /* a listener never stops the feed */ } } };
  (async () => {
    let attempt = 0;
    while (!stopped) {
      const c = new AbortController();
      ctrl = c;
      let opened = 0;
      // no answer at all is a failed connect too, not a feed that waits forever
      const noAnswer = setTimeout(() => c.abort(), STREAM_IDLE_MS);
      try {
        const res = await harnessFetch(`${BASE}/v1/harnesses/${encodeURIComponent(harnessId)}/events`, {
          headers: authHeaders(), cache: 'no-store', signal: c.signal,
        });
        clearTimeout(noAnswer);
        if (res.ok && res.body) {
          const dec = new TextDecoder();
          let head = '';
          const r = readUntilIdle(res.body, STREAM_IDLE_MS, (b) => {
            if (opened) return;
            head += dec.decode(b, { stream: true });
            if (/(^|\n):\s?connected\r?\n/.test(head)) { opened = Date.now(); head = ''; tell('up'); }
            else if (head.length > 8192) head = head.slice(-64);
          });
          await readSSEStream(r.body as unknown as ReadableStream<Uint8Array>, (data: string) => {
            try { onMsg(JSON.parse(data) as BusMsg); } catch { /* ignore malformed frame */ }
          });
        } else {
          res.body?.cancel().catch(() => { /* nothing to read */ });
        }
      } catch { /* network drop / abort, fall through to reconnect */ }
      clearTimeout(noAnswer);
      if (stopped) break;
      if (opened) tell('down');
      if (opened && Date.now() - opened >= BUS_HEALTHY_MS) attempt = 0;
      const wait = Math.min(BUS_BACKOFF_MAX_MS, 1000 * 2 ** attempt * (0.75 + Math.random() * 0.5));
      attempt += 1;
      await sleep(wait);
    }
  })();
  return () => { stopped = true; ctrl?.abort(); wake?.(); };
}

/**
 * Run one turn, streaming native Responses events to `h`. Returns the new response id (for
 * chaining the next turn via previousResponseId). Throws only on transport/HTTP failure; agent
 * failures arrive as onError + a final onDone('failed', ...). A stream on which nothing at all
 * arrives for STREAM_IDLE_MS (the server writes a keepalive every 15 s while the turn runs) is ended
 * here and returns without a terminal event, as a dropped stream does: the turn may still be
 * running server-side, and the caller settles it from the record.
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
    // Surface the server's own message when it sent one instead of raw status + JSON: the user sees
    // the actionable sentence, not a transport artifact.
    // the protocol's error shape: {error: {code, message}, detail}. `detail` is the sentence for
    // people; `error.code` is the stable class a caller can act on (one turn at a time, a cap)
    let detail = '', code = '';
    try {
      const j = JSON.parse(t) as { detail?: unknown; error?: { code?: unknown; message?: unknown } };
      detail = String(j?.detail || j?.error?.message || '');
      code = String(j?.error?.code || '');
    } catch { /* not JSON */ }
    // Carry the status alongside the human sentence: once `detail` replaces the status text,
    // the only way for a caller to tell a refusal from a blip is to pattern-match
    // an arbitrary server string. The code is the stable signal.
    throw Object.assign(new Error(detail || `responses failed: ${res.status} ${t.slice(0, 200)}`),
                        { status: res.status, code });
  }

  // Shared parser: SSE framing + native-Responses dispatch (tool-call pairing by output_index)
  // live in UI Core; resolves to the response id for previousResponseId chaining. Each event also
  // goes to onEvent first, whole, at the moment it arrived.
  const d = createResponsesDispatcher(h);
  await readSSEStream(readUntilIdle(res.body, STREAM_IDLE_MS).body as unknown as ReadableStream<Uint8Array>, (data: string) => {
    let ev: Record<string, unknown>;
    try { ev = JSON.parse(data); } catch { return; }   // a malformed frame
    try { h.onEvent?.(ev); } catch { /* the clock must never break the stream */ }
    d.dispatch(ev as Parameters<typeof d.dispatch>[0]);
  });
  return d.responseId;
}
