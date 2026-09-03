'use client';
// The conversation controller: the state machine behind every agent chat surface in the console.
//
// It lives here, NOT in a page, because two surfaces now drive it: Tasks (one conversation at a
// time) and Arena (N conversations side by side, one shared composer fanning a message out to all
// of them). The pieces below are deliberately MODULE-LEVEL singletons: the conversation store, the
// bus-suppression set, the pending-card list and the turn telemetry. A second copy of any of them
// would give a second surface its own store, and the realtime bus would silently stop updating it.
//
// The split that makes sharing work: this module owns the turn lifecycle (send, stream, reconcile,
// stop, settle) and owns NO composer state. `send(text, files)` takes what to send as arguments, so
// one composer can drive one column or six.
import { useEffect, useId, useRef, useState } from 'react';
import { streamResponse, subscribeHarnessEvents, loadSessionTurns, cancelSession,
         type RespFile, type SessionTurn } from '@/lib/chat';
import { getCurrentWorkspaceRef } from '@/lib/workspace';
import { track } from '@/lib/analytics';
import { billing } from '@/app/(app)/billing/lib';
import { oobById } from '@/lib/harness';
import { withText, withReasoning, withStep, withResult } from 'reifyui';
import { createConversationStore } from 'reifyui';

/** Turn states the backend considers settled. One definition, used by every settle path. */
export const TERMINAL_TURN = new Set(['done', 'completed', 'failed', 'error', 'cancelled', 'incomplete', 'timeout', 'max_turns']);

/** A session card as the Recents/Arena lists see it (mirrors the gateway trace card). */
export interface TraceCard {
  session_id: string; title?: string; status?: string; finished_at?: number;
  model?: string; event_count?: number; elapsed?: number; credits?: number;
}

export interface ChatTarget { name: string; backend: string | null; model?: string; baseId?: string;
  /** The runtime this harness runs on and the model its settings default to (the footer names both). */
  runtime?: string; defaultModel?: string }
export interface UserMsg { role: 'user'; text: string; attachments?: { name: string; dataUri?: string }[] }
export interface ToolStep { name: string; args: string; result?: string; callId?: string }
// An assistant turn is an ORDERED list of blocks appended as events arrive, so tool activity is
// interleaved with prose in real time (not all tools hoisted to the top).
export type Block = { kind: 'text'; text: string } | { kind: 'tools'; reasoning: string; steps: ToolStep[] };
export interface AsstMsg { role: 'assistant'; blocks: Block[]; files: RespFile[]; status: 'running' | 'done' | 'failed' | 'cancelled' | 'incomplete';
  /** Why an incomplete turn is incomplete (max_steps | timeout | interrupted) — from the
   *  gateway's incomplete_details. Absent on records from before the field existed, which is
   *  why the badge itself must not assert a cause. */
  incompleteReason?: string;
  /** Seconds this turn took and the credits it cost, when the gateway kept them. */
  elapsed?: number; credits?: number }
// AGENTS.md / CLAUDE.md are harness-internal instruction files the runner seeds into the workspace
// (they surface installed skills to the agent). They are never user-facing outputs, so they must
// never render as output file cards, including on older sessions that captured them before the
// gateway started excluding them.
const _INTERNAL_OUT = new Set(['AGENTS.md', 'CLAUDE.md', 'QWEN.md']);
export const isInternalOutput = (name?: string) =>
  !!name && (_INTERNAL_OUT.has(name) || name.startsWith('.harness/') || name.includes('/.harness/'));
export type Msg = UserMsg | AsstMsg;

export function msgsFromTurns(turns: SessionTurn[]): { msgs: Msg[]; running: boolean } {
  const m: Msg[] = [];
  let running = false;
  for (const t of turns) {
    if (t.user || (t.user_files || []).length) {
      m.push({ role: 'user', text: t.user,
        attachments: (t.user_files || []).map((f) => ({ name: f.name })) });
    }
    const steps = (t.tools || []).map((x) => ({ name: x.name, args: x.arguments, result: x.result }));
    const blocks: Block[] = [];
    if (steps.length) blocks.push({ kind: 'tools', reasoning: '', steps });
    if (t.assistant) blocks.push({ kind: 'text', text: t.assistant });
    const st: AsstMsg['status'] = t.status === 'failed' || t.status === 'error' ? 'failed'
      : t.status === 'cancelled' ? 'cancelled'
      : (t.status === 'incomplete' || t.status === 'max_turns' || t.status === 'timeout') ? 'incomplete'
        : (t.status === 'running' || t.status === 'starting' || t.status === 'in_progress') ? 'running' : 'done';
    if (st === 'running') running = true;
    m.push({ role: 'assistant', blocks, files: t.files || [], status: st,
      incompleteReason: (t as { incomplete_reason?: string }).incomplete_reason || undefined,
      elapsed: typeof t.elapsed === 'number' ? t.elapsed : undefined,
      credits: typeof t.credits === 'number' ? t.credits : undefined });
  }
  return { msgs: m, running };
}

// Optimistic Recents entries: a just-sent NEW task shows in the list INSTANTLY. The durable card
// only lands after session allocation + the first trace write (seconds on a cold start), so without
// this the list lags every new send. An entry drops the moment the server list contains its session
// (sid learned from response.created), or after a safety expiry if the send failed before a session
// existed. Module-level (like _runningSids) so it survives panel re-renders.
export type PendingCard = { tempId: string; harness: string; title: string; at: number; sid?: string };
let _pendingCards: PendingCard[] = [];
export function addPendingCard(harness: string, title: string): string {
  const tempId = 'pend_' + Math.random().toString(36).slice(2);
  _pendingCards.push({ tempId, harness, title, at: Date.now() });
  return tempId;
}
export function setPendingSid(tempId: string, sid: string) {
  const p = _pendingCards.find((x) => x.tempId === tempId);
  if (p) p.sid = sid;
}
export function dropPending(tempId: string) { _pendingCards = _pendingCards.filter((x) => x.tempId !== tempId); }
/** Pending entries still worth showing for this harness, given the server list; prunes the store. */
export function livePending(harness: string, cards: TraceCard[] | null): PendingCard[] {
  const now = Date.now();
  _pendingCards = _pendingCards.filter((p) =>
    now - p.at < 180_000 && !(p.sid && (cards || []).some((c) => c.session_id === p.sid)));
  return _pendingCards.filter((p) => p.harness === harness);
}

// ── Per-conversation store (module-level, survives panel remount + tab switches) ────────────────
// The Conversation component used to hold msgs/busy/stream in component-local state, so switching
// conversations destroyed the optimistic user message AND the in-flight stream, that's why a
// message "sent" to one conversation vanished when you came back, and why only the turn that had
// already finished (reloadable from the server) ever showed. Hoisting this state here keeps every
// conversation's messages + run status alive in the background; streams write to the store by key,
// so switching is just a re-view and N concurrent turns all keep streaming.
// The store mechanics live in UI Core (createConversationStore); these thin typed wrappers keep
// every call site unchanged.
export type ConvState = { msgs: Msg[]; busy: boolean; prevId: string | null; firstTurn: boolean; loaded: boolean };
export const convStore = createConversationStore();
export function getConvState(key: string): ConvState { return convStore.get(key) as ConvState; }
export function setConvState(key: string, patch: Partial<ConvState> | ((s: ConvState) => Partial<ConvState>)): void {
  convStore.set(key, patch);
}
export function useConvState(key: string): ConvState { return convStore.use(key) as ConvState; }

// ── realtime broadcast bus → conv store ──────────────────────────────────────────────────────────
// The gateway broadcasts every event of every session of a harness. We apply each event to the
// conv store keyed by the REAL session id, so any conversation renders live regardless of which tab
// (or none) started the turn, fixing "open a running session and see nothing until a hard refresh".
// `_busSuppress` holds session ids whose turn THIS tab is already rendering via its own POST stream
// (convKey === sid), so we don't double-apply deltas for those.
export const _busSuppress = new Set<string>();
// ── task_started / task_finished bookkeeping ────────────────────────────────────────────────
// Both live at module scope for the same reason the conversation store does: a turn outlives
// the component that started it (switch away, come back, reload).
// Wall-clock turn start, keyed by conv key then re-keyed to the real session id once allocated.
// Absent means "not observed by this browser" — duration is then omitted, never guessed.
const _turnStart = new Map<string, number>();
// A turn settles on whichever path wins: the SSE terminal event, or the 4s reconcile poll.
// Reporting only the fast path would systematically under-count failures, because dropped
// terminal events are exactly what the poll exists to repair.
const _finished = new Set<string>();
export function trackTaskFinished(sid: string, turnIndex: number, props: Record<string, string | number | boolean | null | undefined>): void {
  const key = `${sid}#${turnIndex}`;
  if (_finished.has(key)) return;
  _finished.add(key);
  const started = _turnStart.get(sid);
  if (started) _turnStart.delete(sid);
  track('task_finished', { ...props, turn_index: turnIndex,
                           duration_ms: started ? Math.round(performance.now() - started) : undefined });
}
/** Turn index = assistant messages so far - 1. One definition, used by both settle paths. */
export function turnIndexOf(msgs: Msg[]): number {
  return Math.max(0, msgs.filter((m) => m.role === 'assistant').length - 1);
}

// Sessions with a turn currently in flight, maintained from the bus (authoritative, no trace-card
// lag) so the Recents "working" dot is accurate the instant a turn starts/ends.
export const _runningSids = new Set<string>();
const _busFn: Record<string, { name: string; callId: string }> = {};
function busUpdateLast(sid: string, fn: (a: AsstMsg) => void) {
  setConvState(sid, (s) => {
    const out = s.msgs.slice();
    for (let i = out.length - 1; i >= 0; i--) {
      if (out[i].role === 'assistant') { const a = { ...(out[i] as AsstMsg) }; fn(a); out[i] = a; break; }
    }
    return { msgs: out };
  });
}
function applyBusEvent(sid: string, responseId: string, ev: Record<string, unknown>, replay = false) {
  if (!sid || _busSuppress.has(sid)) return;        // initiating tab's POST stream owns this one
  // History catch-up frames are dropped: an in-flight turn's progress-so-far is loaded from the
  // authoritative durable trace via GET /v1/sessions/{sid}/turns (msgsFromTurns). Re-applying the
  // same events off the bus would double-render (append the same text/tools twice). The bus is the
  // live-FORWARD channel only; the trace snapshot + the reconcile poll own history + repair.
  if (replay) return;
  const t = ev.type as string;
  switch (t) {
    case 'harness.turn.started': {
      // Ignore a REPLAYED start of a turn we've already finished (its response_id is our last prevId):
      // a stale/duplicate start would otherwise append a phantom "Working…" turn that never completes.
      if (responseId && getConvState(sid).prevId === responseId) return;
      setConvState(sid, (s) => {
        const last = s.msgs[s.msgs.length - 1];
        if (last && last.role === 'assistant' && (last as AsstMsg).status === 'running') return {}; // already showing it
        const user = String((ev.user_text as string) || '');
        const add: Msg[] = [];
        if (user) add.push({ role: 'user', text: user });
        add.push({ role: 'assistant', blocks: [], files: [], status: 'running' });
        return { msgs: [...s.msgs, ...add], busy: true, loaded: true };
      });
      break;
    }
    case 'response.reasoning_summary_text.delta':
      busUpdateLast(sid, (a) => { a.blocks = withReasoning(a.blocks, ev.delta as string); }); break;
    case 'response.output_item.added': {
      const item = ev.item as Record<string, unknown>;
      if (item?.type === 'function_call') _busFn[`${sid}:${ev.output_index}`] = { name: item.name as string, callId: (item.call_id as string) || '' };
      else if (item?.type === 'function_call_output') busUpdateLast(sid, (a) => { a.blocks = withResult(a.blocks, (item.call_id as string) || '', String(item.output ?? '')); });
      break;
    }
    case 'response.function_call_arguments.done': {
      const fn = _busFn[`${sid}:${ev.output_index}`] || { name: 'tool', callId: '' };
      busUpdateLast(sid, (a) => { a.blocks = withStep(a.blocks, { name: fn.name, args: (ev.arguments as string) || '', callId: fn.callId }); }); break;
    }
    case 'response.output_text.delta':
      busUpdateLast(sid, (a) => { a.blocks = withText(a.blocks, ev.delta as string); }); break;
    case 'response.output_text.annotation.added': {
      const a = ev.annotation as Record<string, unknown>;
      if (a?.type === 'container_file_citation') busUpdateLast(sid, (m) => { m.files = [...m.files, { container_id: a.container_id as string, file_id: a.file_id as string, filename: a.filename as string }]; });
      break;
    }
    case 'response.completed':
      busUpdateLast(sid, (a) => { a.status = 'done'; }); setConvState(sid, { busy: false, prevId: responseId, firstTurn: false }); break;
    case 'response.incomplete':
      busUpdateLast(sid, (a) => { a.status = 'incomplete'; }); setConvState(sid, { busy: false, prevId: responseId, firstTurn: false }); break;
    case 'response.failed': {
      // A user Stop arrives as response.failed with reason/status "cancelled", show it as
      // Cancelled, not Failed (the session card + turn record already say cancelled).
      const wasCancelled = ev.reason === 'cancelled'
        || (ev.response as Record<string, unknown> | undefined)?.status === 'cancelled';
      busUpdateLast(sid, (a) => { a.status = wasCancelled ? 'cancelled' : 'failed'; });
      setConvState(sid, { busy: false, prevId: responseId, firstTurn: false }); break;
    }
    case 'error':
      busUpdateLast(sid, (a) => { a.blocks = withText(a.blocks, '\n\nError: ' + ((ev.message as string) || 'stream error')); }); break;
  }
}
export function useHarnessBus(harnessId: string, onActivity?: () => void) {
  useEffect(() => {
    if (!harnessId) return;
    const unsub = subscribeHarnessEvents(harnessId, (m) => {
      const t = (m.event as Record<string, unknown>)?.type as string;
      // track in-flight sessions (authoritative for the Recents dot) regardless of suppress/replay:
      // a replayed start still tells us the session is live (its terminal event clears it).
      if (t === 'harness.turn.started') _runningSids.add(m.session_id);
      else if (t === 'response.completed' || t === 'response.failed' || t === 'response.incomplete') _runningSids.delete(m.session_id);
      applyBusEvent(m.session_id, m.response_id, m.event || {}, Boolean(m.replay));
      if (t === 'harness.turn.started' || t === 'response.completed' || t === 'response.failed' || t === 'response.incomplete') onActivity?.();
    });
    return unsub;
  }, [harnessId]); // eslint-disable-line react-hooks/exhaustive-deps
}


// ── the turn controller ────────────────────────────────────────────────────────────────────────
/**
 * One conversation's lifecycle: bind to the store, load history, run turns, settle them.
 *
 * Owns NO composer state on purpose. `send(text, files)` is given what to send, which is what lets
 * Tasks drive one of these from its own composer and Arena drive six from one shared composer.
 */
export function useConversationTurn({ harnessId, sessionId, target, onRan, onSession, onSendStart, extraHeaders }: {
  harnessId: string;
  sessionId: string | null;
  target: ChatTarget;
  onRan: () => void;
  onSession?: (sid: string) => void;
  /** Fired the instant a send is accepted, so a view can clear its composer. */
  onSendStart?: () => void;
  /** App-auth pass-through header values for this harness. */
  extraHeaders?: () => Record<string, string>;
}) {
  const genId = useId();
  const [boundSid, setBoundSid] = useState<string | null>(null);
  const sidRef = useRef<string | null>(sessionId);
  // Synchronous send latch — see the comment in send(). React state cannot gate two calls that
  // land in the same tick, because neither has re-rendered yet.
  const sendingRef = useRef(false);
  useEffect(() => { if (sessionId) sidRef.current = sessionId; }, [sessionId]);
  const convKey = sessionId ?? boundSid ?? `new-${genId}`;
  const convKeyRef = useRef(convKey);
  convKeyRef.current = convKey;
  const conv = useConvState(convKey);
  const msgs = conv.msgs;
  const busy = conv.busy;
  const prevId = conv.prevId;
  const firstTurn = conv.firstTurn;
  const setMsgs = (u: Msg[] | ((m: Msg[]) => Msg[])) =>
    setConvState(convKeyRef.current, (s) => ({ msgs: typeof u === 'function' ? (u as (m: Msg[]) => Msg[])(s.msgs) : u }));
  const setBusy = (b: boolean) => setConvState(convKeyRef.current, { busy: b });
  const setPrevId = (id: string | null) => setConvState(convKeyRef.current, { prevId: id });
  const setFirstTurn = (b: boolean) => setConvState(convKeyRef.current, { firstTurn: b });
  const [loading, setLoading] = useState(false);
  const [outOfCredits, setOutOfCredits] = useState<{ balance: number | null } | null>(null);
  // Stop is one-shot: disabled the moment it is clicked so a slow cancel cannot be spammed.
  const [stopping, setStopping] = useState(false);
  useEffect(() => { setStopping(false); }, [busy]);

  // The shape of a task, never its content. No prompt, no file name, no title.
  const taskFacts = () => ({
    harness_kind: oobById(harnessId) ? 'builtin' : 'custom',
    base: target.baseId || null,
    model: target.model || null,
    workspace_id: getCurrentWorkspaceRef()?.id || null,
  });
  const factsRef = useRef(taskFacts);
  factsRef.current = taskFacts;

  const updateLast = (fn: (a: AsstMsg) => void) =>
    setMsgs((m) => { const out = m.slice(); for (let i = out.length - 1; i >= 0; i--) { if (out[i].role === 'assistant') { const a = { ...(out[i] as AsstMsg) }; fn(a); out[i] = a; break; } } return out; });


  // Load a session's chat history into the store, reconciling against the AUTHORITATIVE backend.
  // Opening a session always checks the real turn status: a session the backend reports terminal is
  // shown done with its content even if the store was left stuck at busy:true (e.g. a terminal bus
  // event was dropped on a full queue / reconnect race), which previously stranded it at "Working…"
  // until a hard refresh. A genuinely in-flight turn keeps its live placeholder for the bus to stream.
  useEffect(() => {
    const existing = getConvState(convKey);
    if (!sessionId) { if (!existing.loaded) setConvState(convKey, { loaded: true }); return; }
    // Already loaded, idle, and has content → trust it (no refetch on every open).
    if (existing.loaded && !existing.busy && existing.msgs.length) return;
    setLoading(true);
    loadSessionTurns(sessionId).then(({ turns, lastResponseId }) => {
      const { msgs: m, running } = msgsFromTurns(turns);
      const cur = getConvState(convKey);
      if (!running) {
        // Backend is terminal → authoritative. Show its content and clear any stale busy flag.
        setConvState(convKey, { msgs: m, prevId: lastResponseId, firstTurn: false, loaded: true, busy: false });
      } else if (!cur.msgs.length) {
        // In-flight with nothing local yet → load the turn's progress-so-far (the backend
        // reconstructs a running turn's partial output from its durable trace) and let the bus
        // stream new events on top. If the trace was still empty this is just the placeholder.
        setConvState(convKey, { msgs: m, prevId: lastResponseId, firstTurn: false, loaded: true, busy: true });
      } else {
        // In-flight and we already hold live msgs (switched away/back mid-turn) → keep them.
        setConvState(convKey, { loaded: true });
      }
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [convKey, sessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  // RECONCILIATION: SSE (POST stream or bus) is best-effort delivery, a reconnect gap, a
  // replica switch, or a dropped terminal event must NEVER strand the conversation at
  // "Working…". While busy, poll the authoritative turn state; the moment the backend says
  // the turn is over, rebuild from /turns and settle. This is the load-bearing guarantee;
  // streaming is just the fast path on top of it.
  useEffect(() => {
    if (!busy) return;
    const sid = sessionId ?? sidRef.current;
    if (!sid) return;
    let stop = false;
    const iv = setInterval(async () => {
      if (stop) return;
      try {
        const { turns, lastResponseId } = await loadSessionTurns(sid);
        if (stop || !turns.length) return;
        const last = turns[turns.length - 1];
        if (!TERMINAL_TURN.has(String(last.status || ''))) return;
        const { msgs: m } = msgsFromTurns(turns);
        // The OTHER settle path. SSE is best-effort (see the comment above); a dropped terminal
        // event lands here instead, and instrumenting only the fast path would bias the success
        // rate — the one metric this event exists to measure — upward.
        const lastAsst = [...m].reverse().find((x) => x.role === 'assistant') as AsstMsg | undefined;
        trackTaskFinished(sid, turnIndexOf(m), {
          ...factsRef.current(),
          status: lastAsst?.status === 'done' ? 'completed' : (lastAsst?.status || 'failed'),
          produced_files: !!lastAsst?.files?.length,
          file_count: lastAsst?.files?.length ?? 0,
        });
        _busSuppress.delete(sid);
        setConvState(convKeyRef.current, { msgs: m, prevId: lastResponseId, firstTurn: false, loaded: true, busy: false });
      } catch { /* transient, next tick */ }
    }, 4000);
    return () => { stop = true; clearInterval(iv); };
  }, [busy, sessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  // The settled read. A turn that settled on the SSE path holds only what was streamed; what it
  // took and cost is written by the gateway at settle, a moment after the terminal event. One
  // read (and one retry, since the persist can trail the event by a couple of seconds) folds
  // those figures into the last answer, so the per-turn line appears without a reload.
  const settledRead = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (busy) return;
    const sid = sessionId ?? sidRef.current;
    if (!sid) return;
    const cur = getConvState(convKeyRef.current);
    const idx = turnIndexOf(cur.msgs);
    const last = [...cur.msgs].reverse().find((x) => x.role === 'assistant') as AsstMsg | undefined;
    if (!last || last.status === 'running' || last.elapsed != null) return;
    const key = `${sid}#${idx}`;
    if (settledRead.current.has(key)) return;
    settledRead.current.add(key);
    let stop = false;
    const attempt = async (left: number) => {
      if (stop) return;
      try {
        const { turns } = await loadSessionTurns(sid);
        const t = turns[turns.length - 1];
        if (t && (typeof t.elapsed === 'number' || typeof t.credits === 'number')) {
          setConvState(convKeyRef.current, (st) => {
            const out = st.msgs.slice();
            for (let i = out.length - 1; i >= 0; i--) {
              if (out[i].role === 'assistant') {
                out[i] = { ...(out[i] as AsstMsg),
                  elapsed: typeof t.elapsed === 'number' ? t.elapsed : undefined,
                  credits: typeof t.credits === 'number' ? t.credits : undefined };
                break;
              }
            }
            return { msgs: out };
          });
          return;
        }
      } catch { /* transient; the retry below */ }
      if (left > 0) setTimeout(() => void attempt(left - 1), 4000);
    };
    // Up to four reads over ~15s: the persist can trail the terminal event by several seconds
    // when the settle is collecting produced files.
    const t0 = setTimeout(() => void attempt(3), 2500);
    return () => { stop = true; clearTimeout(t0); };
  }, [busy, sessionId]); // eslint-disable-line react-hooks/exhaustive-deps
  async function send(rawText: string, attach: { name: string; dataUri: string }[] = []) {
    const text = (rawText || '').trim();
    // `busy` is React state, so three clicks landing in one tick all read it as false and all
    // three stream into the same assistant message: the server runs the turn once, but the
    // reader watches the answer arrive three times over. The latch is a ref because it has to
    // flip now, not at the next render.
    if ((!text && attach.length === 0) || busy || sendingRef.current || !target.backend) return;
    sendingRef.current = true;
    const sent = attach;
    // OpenAI Responses input: a string, or a user MESSAGE whose content is text + file parts.
    // (The gateway parses {role,content:[…]}, a bare content-part array reads as empty input.)
    const input_payload: string | unknown[] = sent.length
      ? [{ role: 'user', content: [
          ...(text ? [{ type: 'input_text', text }] : []),
          ...sent.map((f) => ({ type: 'input_file', filename: f.name, file_data: f.dataUri })),
        ] }]
      : text;
    const wasFirstTurn = firstTurn;
    const startedAt = performance.now();
    let reported = false;                       // task_started fires on the FIRST session id only
    setBusy(true);
    onSendStart?.();
    setMsgs((m) => [...m, { role: 'user', text, attachments: sent.map((f) => ({ name: f.name, dataUri: f.dataUri })) }, { role: 'assistant', blocks: [], files: [], status: 'running' }]);
    // NEW task (no session yet): surface it in Recents IMMEDIATELY via an optimistic entry, the
    // durable card takes seconds (session allocation + first trace write). onRan() re-renders the
    // panel now; the entry swaps for the real card as soon as the server list carries this session.
    const pendId = !sessionId ? addPendingCard(harnessId, (text || sent[0]?.name || 'New task').split('\n')[0].slice(0, 120)) : null;
    // A follow-up has a card already; its record turns "running" as the turn starts, so the
    // panel re-reads now too and the task rises to the top of its harness while it runs.
    onRan();
    // This tab renders the turn via its own POST stream below; tell the broadcast bus to NOT also
    // apply deltas to this same session (convKey === sid) to avoid double-rendering. Other tabs /
    // other conversations still get it live from the bus.
    const knownSid = sessionId ?? sidRef.current;
    if (knownSid) _busSuppress.add(knownSid);
    try {
      const id = await streamResponse(
        // No `instructions`: the harness's configured Agent Instructions are written into the
        // workspace as AGENTS.md/CLAUDE.md (server-side, from the saved harness), so the model keeps
        // its default system prompt rather than having instructions prepended to the first message.
        // sessionHint: continuity fallback, the gateway continues this session even if prevId was
        // lost client-side (interrupted stream), instead of forking a new one.
        { input: input_payload, backend: target.backend, model: target.model || undefined, previousResponseId: prevId,
          sessionHint: knownSid, harnessId, harnessName: target.name, extraHeaders: extraHeaders?.() || {} },
        { onCreated: (rid) => setPrevId(rid),
          onSession: (sid) => {
            if (!reported && sid) {
              reported = true;
              _turnStart.set(sid, startedAt);
              // Fired on session allocation, not on POST dispatch: a request that dies before it
              // gets a session never became a task.
              track('task_started', { ...taskFacts(), is_first_turn: wasFirstTurn,
                                      has_attachments: sent.length > 0, attachment_count: sent.length });
            }
            if (pendId) setPendingSid(pendId, sid);
            // First turn of a new conversation: rebind the conv store to the real session id so all
            // future writes (this stream, the bus, follow-up turns) land on ONE key.
            if (!sessionId && !sidRef.current && sid) {
              convStore.seed(sid, { ...getConvState(convKeyRef.current) });
              _busSuppress.add(sid);
              sidRef.current = sid;
              setBoundSid(sid);
            }
            onSession?.(sid);
          },
          onReasoningDelta: (d) => updateLast((a) => { a.blocks = withReasoning(a.blocks, d); }),
          onToolCall: (name, args, callId) => updateLast((a) => { a.blocks = withStep(a.blocks, { name, args, callId }); }),
          onToolResult: (callId, output) => updateLast((a) => { a.blocks = withResult(a.blocks, callId, output); }),
          onTextDelta: (d) => updateLast((a) => { a.blocks = withText(a.blocks, d); }),
          onFile: (f) => updateLast((a) => { a.files = [...a.files, f]; }),
          onError: (msg) => updateLast((a) => { a.blocks = withText(a.blocks, '\n\nError: ' + msg); }),
          onDone: (status) => {
            updateLast((a) => {
              a.status = status === 'completed' ? 'done'
                : (['failed', 'cancelled', 'incomplete'].includes(status) ? status as AsstMsg['status'] : 'failed');
            });
            const sk = sessionId ?? sidRef.current;
            const ms = getConvState(convKeyRef.current).msgs;
            const lastA = [...ms].reverse().find((x) => x.role === 'assistant') as AsstMsg | undefined;
            if (sk) trackTaskFinished(sk, turnIndexOf(ms), {
              ...taskFacts(),
              status: ['completed', 'failed', 'cancelled', 'incomplete'].includes(status) ? status : 'failed',
              produced_files: !!lastA?.files?.length,
              file_count: lastA?.files?.length ?? 0,
            });
          } },
      );
      if (id) setPrevId(id); setFirstTurn(false);
    } catch (e) {
      // A throw here is a TRANSPORT failure (the POST stream dropped), never an agent failure, which
      // arrives via onError + onDone('failed'). If the turn already reached a session it is STILL
      // running server-side (a gateway redeploy rolling the SSE, a network blip), so painting it
      // "failed" is a lie that strands the user. Leave it running and let the finally hand rendering
      // to the auto-reconnecting broadcast bus. Only a start failure (no session yet) is a real error.
      const sk = sessionId ?? sidRef.current;
      if (!sk) {
        // The loop broke before it started. Report the CLASS, never the message: the server's
        // raw `detail` string is arbitrary text and must not leave the browser. The 402 credit
        // wall and a gateway blip look identical to the user and completely different to the
        // business, which is the whole point of the enum.
        const st = (e as { status?: unknown })?.status;
        track('task_blocked', {
          reason: st === 402 ? 'out_of_credits' : st === 429 ? 'rate_limited'
            : typeof st === 'number' ? 'other' : 'transport',
          ...taskFacts(),
        });
        // Out of credits is a decision, not a defect: name it and hand over the door, instead of
        // leaving a red line in the transcript the user cannot act on. The balance is fetched
        // rather than assumed — a wrong number on a money dialog is worse than no number.
        if (st === 402) {
          setOutOfCredits({ balance: null });
          billing.balance()
            .then((b) => setOutOfCredits({ balance: Math.round(Number(b?.balance ?? 0)) }))
            .catch(() => { /* keep the dialog, just without a figure */ });
        }
        if (pendId) dropPending(pendId);
        updateLast((a) => { a.blocks = withText(a.blocks, '\n\nError: ' + (e instanceof Error ? e.message : String(e))); a.status = 'failed'; });
      }
    } finally {
      sendingRef.current = false;
      const sk = sessionId ?? sidRef.current;
      // If the stream ended (returned or threw) but no terminal event set the assistant status, the
      // turn is still live server-side (transport drop OR a clean drain-close mid-turn). Hand it to the
      // broadcast bus, which auto-reconnects, by releasing suppression, and KEEP the working state so
      // the indicator stands until the bus (or the on-focus reconcile) lands the true terminal status.
      const ms = getConvState(convKeyRef.current).msgs;
      const lastA = ms[ms.length - 1];
      const stillRunning = !!lastA && lastA.role === 'assistant' && (lastA as AsstMsg).status === 'running';
      if (sk && stillRunning) {
        _busSuppress.delete(sk);            // bus renders the remainder; keep busy=true (composer stays disabled)
      } else {
        if (sk) _busSuppress.delete(sk);
        setBusy(false);
      }
      onRan();
    }
  }

  /** Cancel the running turn, settling from the server verdict as well as the bus event. */
  function stop() {
    const sid = sessionId ?? sidRef.current;
    if (!sid || stopping) return;
    setStopping(true);
    void cancelSession(sid).then((r) => {
      const terminal = ['cancelled', 'failed', 'error', 'done', 'completed', 'incomplete', 'max_turns', 'timeout'];
      if (r.cancelled || terminal.includes(r.status)) {
        updateLast((a) => { a.status = 'cancelled'; });
        setBusy(false);
      } else {
        setStopping(false);   // cancel did not land, let the user retry
      }
    }).catch(() => setStopping(false));
  }

  return { msgs, busy, loading, stopping, prevId, firstTurn, outOfCredits,
           clearOutOfCredits: () => setOutOfCredits(null),
           liveSessionId: sessionId ?? sidRef.current, convKey,
           send, stop, setMsgs, updateLast };
}
