'use client';
// The conversation controller: the state machine behind every agent chat surface in the console.
//
// It lives here, NOT in a page, because a conversation outlives the view that shows it: a setup's
// task list, its open task and its trace all read the same one, and a turn keeps streaming while
// another task is open. The pieces below are deliberately MODULE-LEVEL singletons: the conversation
// store, the bus-suppression set, the pending-card list and the turn telemetry. A second copy of any
// of them would give a second view its own store, and the realtime bus would silently stop updating it.
//
// This module owns the turn lifecycle (send, stream, reconcile, stop, settle) and owns NO composer
// state: `send(text, files)` takes what to send as arguments.
import { useEffect, useId, useRef, useState, useSyncExternalStore } from 'react';
import { streamResponse, subscribeHarnessEvents, loadSessionTurns, cancelSession,
         type BusMsg, type RespFile, type SessionTurn } from '@/lib/chat';
import { subscribeWorkspaceFeed, type FeedFrame } from '@/lib/workspace-feed';
import { readSettled } from '@/lib/settle';
import { getCurrentWorkspaceRef } from '@/lib/workspace';
import { emitFeedTurn } from '@/lib/feed-turns';
import { track } from '@/lib/analytics';
import { oobById } from '@/lib/harness';
import { fillStep } from '@/lib/tool-steps';
import { withText, withReasoning, withStep, withResult, createConversationStore, createResponsesDispatcher } from 'reifyui';
import { newTurn, reduceTurn, finish, type Turn } from 'reifyui/agent-chat';

// The failure sentence is its own block, marked, and it stays LAST. It reaches a message on two
// paths, the turn's own stream and the settled read of the turns feed, and the second arrival must
// not print it twice (seen as "Error: X Error: X" under a refused turn). And a turn's text and tool
// steps can still arrive after the failed event (the trace chunk that carries them lands after
// the status): appended blindly they glued onto the error line and the feed then wrote the error
// again ("...from the provider20pt", a CheetahClaws turn on OSS, 2026-09-27; the same store here),
// so every append below goes in front of a trailing error block. Ported from OSS ec3c1b3.
const isErrorBlock = (b: Block | undefined): boolean => !!b && b.kind === 'text' && b.error === true;
function beforeError(blocks: Block[], apply: (rest: Block[]) => Block[]): Block[] {
  const last = blocks[blocks.length - 1];
  return isErrorBlock(last) ? [...apply(blocks.slice(0, -1)), last as Block] : apply(blocks);
}
const addText = (blocks: Block[], d: string): Block[] => beforeError(blocks, (r) => withText(r, d));
const addReasoning = (blocks: Block[], d: string): Block[] => beforeError(blocks, (r) => withReasoning(r, d));
const addStep = (blocks: Block[], step: ToolStep): Block[] =>
  fillStep(blocks, step) ?? beforeError(blocks, (r) => withStep(r, step));
const addResult = (blocks: Block[], callId: string, output: string): Block[] => beforeError(blocks, (r) => withResult(r, callId, output));
function errorBlock(blocks: Block[], msg: string): Block {
  return { kind: 'text', text: (blocks.length ? '\n\n' : '') + 'Error: ' + msg, error: true };
}
function withError(blocks: Block[], msg: string): Block[] {
  if (blocks.some((b) => isErrorBlock(b) && b.kind === 'text' && b.text.trimEnd().endsWith('Error: ' + msg))) return blocks;
  return [...blocks, errorBlock(blocks, msg)];
}


/** Turn states the backend considers settled. One definition, used by every settle path. */
export const TERMINAL_TURN = new Set(['done', 'completed', 'failed', 'error', 'cancelled', 'incomplete', 'timeout', 'max_turns']);
/** A record's turn state as a message shows it. A live state (the gateway's _TURN_LIVE: running,
 *  in_progress, queued, starting), or one this console does not know, is running: never drawn as
 *  done, so a read never ends a turn the server has not ended. */
export function turnStatus(status: unknown): AsstMsg['status'] {
  const s = String(status || '');
  if (s === 'failed' || s === 'error') return 'failed';
  if (s === 'cancelled') return 'cancelled';
  if (s === 'incomplete' || s === 'max_turns' || s === 'timeout') return 'incomplete';
  if (s === 'done' || s === 'completed') return 'done';
  return 'running';
}

/** A session card as a task list sees it (mirrors the gateway trace card). */
export interface TraceCard {
  session_id: string; title?: string; status?: string; finished_at?: number;
  model?: string; event_count?: number; elapsed?: number;
}

export interface ChatTarget { name: string; backend: string | null; model?: string; baseId?: string;
  /** The runtime this harness runs on and the model its settings default to (the footer names both). */
  runtime?: string; defaultModel?: string }
/** `imported`: part of an earlier turn brought with the task's first request (a recorded run carried
 *  into a task of your own, start/fork.ts), never the agent's own. */
export interface UserMsg { role: 'user'; text: string; attachments?: { name: string; dataUri?: string }[]; imported?: true }
export interface ToolStep { name: string; args: string; result?: string; callId?: string;
  /** the tool said this call failed (the record's is_error); absent when it worked */
  isError?: true }
// An assistant turn is an ORDERED list of blocks appended as events arrive, so tool activity is
// interleaved with prose in real time (not all tools hoisted to the top).
export type Block = { kind: 'text'; text: string; error?: true } | { kind: 'tools'; reasoning: string; steps: ToolStep[] };
export interface AsstMsg { role: 'assistant'; blocks: Block[]; files: RespFile[]; status: 'running' | 'done' | 'failed' | 'cancelled' | 'incomplete';
  /** Why an incomplete turn is incomplete (max_steps | timeout | interrupted) — from the
   *  gateway's incomplete_details. Absent on records from before the field existed, which is
   *  why the badge itself must not assert a cause. */
  incompleteReason?: string;
  /** the server's own sentence for a refusal, when it sent one (shown beside the reason) */
  incompleteDetail?: string;
  /** Seconds this turn took, when the gateway kept it. */
  elapsed?: number;
  /** an earlier turn brought with the task's first request (see UserMsg) */
  imported?: true;
  /** The turn's clock: the same events folded by reifyui's reduceTurn as they arrived, so a view can
   *  say when each call started and answered. Only a turn this browser watched live has one; a turn
   *  read from the record has none and shows no durations, never guessed ones. */
  clock?: Turn }
// AGENTS.md / CLAUDE.md are harness-internal instruction files the runner seeds into the workspace
// (they surface installed skills to the agent). They are never user-facing outputs, so they must
// never render as output file cards, including on older sessions that captured them before the
// gateway started excluding them.
const _INTERNAL_OUT = new Set(['AGENTS.md', 'CLAUDE.md', 'QWEN.md', 'GEMINI.md']);
export const isInternalOutput = (name?: string) =>
  !!name && (_INTERNAL_OUT.has(name) || name.startsWith('.harness/') || name.includes('/.harness/'));
export type Msg = UserMsg | AsstMsg;

/** The server's turns, plus a local tail the server never recorded: a follow-up that was refused
 *  or never started keeps its bubble and its state instead of being reconciled away. */
export function keepUnrecordedTail(server: Msg[], local: Msg[]): Msg[] {
  const users = (ms: Msg[]) => ms.filter((m) => m.role === 'user').length;
  const n = users(server);
  if (users(local) <= n) return server;
  let seen = 0, cut = local.length;
  for (let i = 0; i < local.length; i++) { if (local[i].role === 'user') { seen++; if (seen > n) { cut = i; break; } } }
  const tail = local.slice(cut);
  const lastA = [...tail].reverse().find((x) => x.role === 'assistant') as AsstMsg | undefined;
  if (!lastA || lastA.status === 'running') return server;   // a live turn the server has not written yet: the caller decides
  return [...server, ...tail];
}

/** The record's messages, keeping the clocks the live ones had (matched answer by answer): a turn
 *  settled from its record after its stream dropped keeps the times it was seen working. */
export function carryClocks(server: Msg[], local: Msg[]): Msg[] {
  const clocks = local.filter((x): x is AsstMsg => x.role === 'assistant').map((a) => a.clock);
  let i = 0;
  return server.map((x) => {
    if (x.role !== 'assistant') return x;
    const c = clocks[i++];
    return c ? { ...x, clock: c } : x;
  });
}

export function msgsFromTurns(turns: SessionTurn[]): { msgs: Msg[]; running: boolean } {
  const m: Msg[] = [];
  let running = false;
  for (const t of turns) {
    if (t.user || (t.user_files || []).length) {
      m.push({ role: 'user', text: t.user,
        attachments: (t.user_files || []).map((f) => ({ name: f.name })) });
    }
    // the gateway's turns name a tool's result `output` (its first 4,000 characters); `result` is the older name
    const steps: ToolStep[] = (t.tools || []).map((x) => ({ name: x.name, args: x.arguments, result: x.result ?? x.output,
      ...(x.is_error ? { isError: true as const } : {}) }));
    const blocks: Block[] = [];
    if (steps.length) blocks.push({ kind: 'tools', reasoning: '', steps });
    if (t.assistant) blocks.push({ kind: 'text', text: t.assistant });
    // a failed turn's reason, the line the live stream appended as its error event
    const why = (t as { error?: string }).error;
    if (why && (t.status === 'failed' || t.status === 'error')) blocks.push(errorBlock(blocks, why));
    const st = turnStatus(t.status);
    if (st === 'running') running = true;
    m.push({ role: 'assistant', blocks, files: t.files || [], status: st,
      incompleteReason: (t as { incomplete_reason?: string }).incomplete_reason || undefined,
      incompleteDetail: (t as { incomplete_detail?: string }).incomplete_detail || undefined,
      elapsed: typeof t.elapsed === 'number' ? t.elapsed : undefined });
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
/** The browser a task is using, as the harness feed reports it: open or not, who has it, when the
 *  agent last acted. `epoch` counts openings, so a pane the person closed stays closed for THAT
 *  browser and comes back on its own for the next one. The live URL is not here: the pane reads it
 *  through the session's own route, because whoever holds it controls the browser. */
export type BrowserState = { open: boolean; control: 'agent' | 'user'; lastCallAt: number; lastTool: string; held: boolean; epoch: number;
  /** where the agent last acted on the page (the element's centre) and the page's viewport, for the ghost cursor */
  point?: { x: number; y: number } | null; viewport?: { w: number; h: number } };
export type ConvState = { msgs: Msg[]; busy: boolean; prevId: string | null; firstTurn: boolean; loaded: boolean; browser?: BrowserState };
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
// A turn settles on whichever path wins: the SSE terminal event, or the read of its record
// (settleFromRecord). Reporting only the fast path would systematically under-count failures,
// because dropped terminal events are exactly what that read exists to repair.
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
/** What the harness's feed last said of a session's turn: running or ended, that turn's response ID
 *  when the feed named it, and when the feed said it. A task list draws its dots from this first: a
 *  card read a moment before a start or an end still says the state before it. */
export interface FeedTurn { on: boolean; rid: string; at: number }
const _feedTurns = new Map<string, FeedTurn>();
const _feedSubs = new Set<() => void>();
let _feedVer = 0;
function feedTurn(sid: string, rid: string, on: boolean, harness = ''): void {
  if (!sid) return;
  const was = _feedTurns.get(sid);
  // an end names the turn it ends; without its ID it is the turn the feed saw start
  const id = rid || (!on && was ? was.rid : '');
  if (was && was.on === on && was.rid === id) return;      // every subscriber of the feed reports it
  _feedTurns.set(sid, { on, rid: id, at: Date.now() });
  if (on) _runningSids.add(sid); else _runningSids.delete(sid);
  _feedVer += 1;
  _feedSubs.forEach((f) => f());
  emitFeedTurn(sid, harness, on);      // Studio reads that setup's row again (lib/feed-turns)
}
export function feedTurnOf(sid: string): FeedTurn | undefined { return sid ? _feedTurns.get(sid) : undefined; }
/** The sessions the feed says are running now, each with when it said so. */
export function feedRunning(): [string, number][] {
  return [..._feedTurns].filter(([, t]) => t.on).map(([sid, t]) => [sid, t.at]);
}
/** Draws again on every turn start and end the feed reports (read them with feedTurnOf). */
export function useFeedTurns(): number {
  return useSyncExternalStore((f) => { _feedSubs.add(f); return () => { _feedSubs.delete(f); }; }, () => _feedVer, () => 0);
}
const _busFn: Record<string, { name: string; callId: string }> = {};
// A produced file reaches a tab through TWO channels by design: the tab's own POST stream renders
// the citation as it arrives (onFile), and the broadcast bus delivers the same event a moment after
// the stream ends and _busSuppress is lifted. The bus drops history replays, but this frame is
// live-forward and simply lands late, so both paths appended and one file rendered as two cards
// while the record held one (2026-09-07). With two delivery channels, applying the same event twice
// has to be a no-op: the answer's file list is a set keyed by file identity.
function withFile(files: RespFile[], f: RespFile): RespFile[] {
  const same = (x: RespFile) => (f.file_id ? x.file_id === f.file_id && x.container_id === f.container_id : x.filename === f.filename);
  return files.some(same) ? files : [...files, f];
}

function busUpdateLast(sid: string, fn: (a: AsstMsg) => void) {
  setConvState(sid, (s) => {
    const out = s.msgs.slice();
    for (let i = out.length - 1; i >= 0; i--) {
      if (out[i].role === 'assistant') { const a = { ...(out[i] as AsstMsg) }; fn(a); out[i] = a; break; }
    }
    return { msgs: out };
  });
}
// A turn's content from the feed goes to the answer still being drawn only. An answer already settled
// holds its record's whole text: the feed is a second channel and can run behind the record (a feed
// on another server tails the trace), and its tail written onto a settled answer printed it twice.
function busAppend(sid: string, fn: (a: AsstMsg) => void) {
  busUpdateLast(sid, (a) => { if (a.status === 'running') fn(a); });
}
function applyBusEvent(sid: string, responseId: string, ev: Record<string, unknown>, replay = false) {
  if (!sid) return;
  const t = ev.type as string;
  // The tab that runs the turn ignores the feed's copy of its own deltas (its POST stream owns
  // them), but the browser notices travel on the feed alone: they pass, they are state, not deltas.
  if (_busSuppress.has(sid) && !t.startsWith('browser.')) return;        // initiating tab's POST stream owns this one
  // History catch-up frames are dropped: an in-flight turn's progress-so-far is loaded from the
  // authoritative durable trace via GET /v1/sessions/{sid}/turns (msgsFromTurns). Re-applying the
  // same events off the bus would double-render (append the same text/tools twice). The bus is the
  // live-FORWARD channel only; the trace snapshot + the read of the record (settleFromRecord) own
  // history + repair.
  if (replay) return;
  // the clock first: every live-forward event, at the moment it arrived (a start opens a new one)
  if (t !== 'harness.turn.started' && !t.startsWith('browser.')) {
    busUpdateLast(sid, (a) => { if (a.status === 'running' || a.clock) a.clock = reduceTurn(a.clock || newTurn(), ev as { type: string }, Date.now()); });
  }
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
        add.push({ role: 'assistant', blocks: [], files: [], status: 'running', clock: newTurn({ startedAt: Date.now() }) });
        return { msgs: [...s.msgs, ...add], busy: true, loaded: true };
      });
      break;
    }
    case 'response.reasoning_summary_text.delta':
      busAppend(sid, (a) => { a.blocks = addReasoning(a.blocks, ev.delta as string); }); break;
    case 'response.output_item.added': {
      const item = ev.item as Record<string, unknown>;
      if (item?.type === 'function_call') _busFn[`${sid}:${ev.output_index}`] = { name: item.name as string, callId: (item.call_id as string) || '' };
      else if (item?.type === 'function_call_output') busAppend(sid, (a) => { a.blocks = addResult(a.blocks, (item.call_id as string) || '', String(item.output ?? '')); });
      break;
    }
    case 'response.function_call_arguments.done': {
      const fn = _busFn[`${sid}:${ev.output_index}`] || { name: 'tool', callId: '' };
      busAppend(sid, (a) => { a.blocks = addStep(a.blocks, { name: fn.name, args: (ev.arguments as string) || '', callId: fn.callId }); }); break;
    }
    case 'response.output_text.delta':
      busAppend(sid, (a) => { a.blocks = addText(a.blocks, ev.delta as string); }); break;
    case 'response.output_text.annotation.added': {
      const a = ev.annotation as Record<string, unknown>;
      if (a?.type === 'container_file_citation') busUpdateLast(sid, (m) => { m.files = withFile(m.files, { container_id: a.container_id as string, file_id: a.file_id as string, filename: a.filename as string }); });
      break;
    }
    case 'response.completed':
      busUpdateLast(sid, (a) => { a.status = 'done'; }); setConvState(sid, { busy: false, prevId: responseId, firstTurn: false }); break;
    case 'response.incomplete': {
      // the event carries why (max_steps | timeout | interrupted) and the server's sentence when it
      // sent one; the stored record has the same fields, so a reload agrees with what the live turn
      // showed
      const inc = (ev.response as { incomplete_details?: { reason?: string; detail?: string } } | undefined)?.incomplete_details;
      busUpdateLast(sid, (a) => { a.status = 'incomplete'; if (inc?.reason) a.incompleteReason = inc.reason; if (inc?.detail) a.incompleteDetail = inc.detail; });
      setConvState(sid, { busy: false, prevId: responseId, firstTurn: false }); break;
    }
    case 'response.failed': {
      // A user Stop arrives as response.failed with reason/status "cancelled", show it as
      // Cancelled, not Failed (the session card + turn record already say cancelled).
      const wasCancelled = ev.reason === 'cancelled'
        || (ev.response as Record<string, unknown> | undefined)?.status === 'cancelled';
      busUpdateLast(sid, (a) => { a.status = wasCancelled ? 'cancelled' : 'failed'; });
      setConvState(sid, { busy: false, prevId: responseId, firstTurn: false }); break;
    }
    case 'error':
      busUpdateLast(sid, (a) => { a.blocks = withError(a.blocks, (ev.message as string) || 'stream error'); }); break;
    // ── the task's browser (the browser plug's live view) ──
    case 'browser.opened':
      setConvState(sid, (st) => ({ browser: { open: true, control: 'agent', lastCallAt: Number(ev.at) * 1000 || Date.now(), lastTool: '', held: false,
                                              epoch: (st.browser?.epoch ?? 0) + 1 } })); break;
    case 'browser.call':
    case 'browser.held':
      setConvState(sid, (st) => ({ browser: { ...(st.browser ?? { control: 'agent', epoch: 1 }), open: true,
                                              lastCallAt: Number(ev.at) * 1000 || Date.now(), lastTool: String(ev.tool || ''), held: t === 'browser.held',
                                              ...(ev.point && typeof ev.point === 'object' ? { point: ev.point as { x: number; y: number } } : {}),
                                              ...(ev.viewport && typeof ev.viewport === 'object' ? { viewport: ev.viewport as { w: number; h: number } } : {}) } as BrowserState })); break;
    case 'browser.control':
      setConvState(sid, (st) => (st.browser ? { browser: { ...st.browser, control: ev.control === 'user' ? 'user' : 'agent', held: false } } : {})); break;
    case 'browser.closed':
      setConvState(sid, (st) => (st.browser ? { browser: { ...st.browser, open: false, held: false } } : {})); break;
  }
}
/** The browser pane on a harness page: whether it is showing, how (docked beside the conversation
 *  or full screen), and which browsers the person closed (by session and epoch) so a closed pane stays closed for that browser and comes
 *  back for the next. The page header's Browser control and the conversation share this state. */
export type PaneMode = 'docked' | 'full';
export type PaneState = { open: boolean; mode: PaneMode; dismissed: Record<string, number> };
const _pane = new Map<string, PaneState>();
const _paneSubs = new Set<() => void>();
const _paneDefault: PaneState = { open: false, mode: 'docked', dismissed: {} };
export function getPaneState(h: string): PaneState { return _pane.get(h) ?? _paneDefault; }
export function setPaneState(h: string, patch: Partial<PaneState>): void {
  _pane.set(h, { ...getPaneState(h), ...patch }); _paneSubs.forEach((f) => f());
}
export function usePaneState(h: string): PaneState {
  return useSyncExternalStore((f) => { _paneSubs.add(f); return () => { _paneSubs.delete(f); }; }, () => getPaneState(h), () => _paneDefault);
}
/** What the session's route says about its browser, folded into the store (the feed keeps it fresh
 *  from there). Called when a task is opened, so a browser that was already running shows. */
export function seedBrowserState(sid: string, info: { open: boolean; control?: string; last_call_at?: number | null; last_tool?: string;
                                                       viewport?: { w: number; h: number } | null } | null): void {
  if (!sid || !info) return;
  setConvState(sid, (st) => {
    if (!info.open) return st.browser ? { browser: { ...st.browser, open: false } } : {};
    return { browser: { open: true, control: info.control === 'user' ? 'user' : 'agent', lastCallAt: (Number(info.last_call_at) || 0) * 1000,
                        lastTool: String(info.last_tool || ''), held: false, epoch: st.browser?.epoch || 1,
                        ...(info.viewport && info.viewport.w > 0 ? { viewport: info.viewport } : {}) } };
  });
}
// ── settling a busy conversation from its record ────────────────────────────────────────────────
// A turn's live text arrives on its own stream or the setup's live feed; its END must not depend on
// either of them arriving. Each busy conversation on screen is listed here and reads its record once
// (settleFromRecord) whenever something says the end may have passed unseen: the setup's live feed
// came up again (whatever ended while it was down went to no one), the workspace watch (its task
// cards read every few seconds while one runs: lib/workspace-feed) reported the end of its task, or
// its own stream ended before the turn did.
interface Settler { harness: string; sid: () => string | null; settle: (waits: readonly number[]) => void }
const _settlers = new Set<Settler>();
/** The re-reads of one settle, ms from its start: the record can trail the end it reports by seconds. */
export const SETTLE_NOW = [0, 1000, 2000, 4000] as const;
/** After the workspace watch's end frame: the setup's own feed first gets a beat to deliver the end. */
export const SETTLE_AFTER_FEED = [1000, 2000, 4000] as const;
const FEED_ENDS = new Set(['response.completed', 'response.failed', 'response.incomplete']);
/** The open's read of a task's record: one quiet second try, and an end (lib/settle). */
const LOAD_READ = { within: 30_000, firstTry: 20_000 };
// Turns whose own stream ended before the turn did. The feed drew the rest, but what was said
// between the stream's last byte and the feed taking over reached no one (the feed's copy was
// suppressed for this tab meanwhile), so the settled read puts the record's whole answer in place.
const _gapped = new Set<string>();
let _wsFeedOff: (() => void) | null = null;
function onWorkspaceFrame(f: FeedFrame): void {
  if (!FEED_ENDS.has(f.type)) return;
  _settlers.forEach((s) => { if (s.sid() === f.session_id) s.settle(SETTLE_AFTER_FEED); });
}
function addSettler(s: Settler): () => void {
  _settlers.add(s);
  // one listener for the page, on the tab's one workspace watch (lib/workspace-feed), while any waits
  if (!_wsFeedOff) _wsFeedOff = subscribeWorkspaceFeed(onWorkspaceFrame);
  return () => {
    _settlers.delete(s);
    if (!_settlers.size && _wsFeedOff) { _wsFeedOff(); _wsFeedOff = null; }
  };
}

// ONE connection per setup in a tab, however many surfaces listen (a setup page's task list and its
// conversation both do): two connections applied every delta of a turn drawn from the feed twice.
interface Bus { stop: () => void; listeners: Set<{ current?: () => void }> }
const _buses = new Map<string, Bus>();
const TURN_EDGES = new Set(['harness.turn.started', 'response.completed', 'response.failed', 'response.incomplete']);
function onBusMsg(harnessId: string, m: BusMsg): void {
  const t = (m.event as Record<string, unknown>)?.type as string;
  // track in-flight sessions (authoritative for the Recents dot) regardless of suppress/replay:
  // a replayed start still tells us the session is live (its terminal event clears it).
  if (t === 'harness.turn.started') feedTurn(m.session_id, m.response_id || '', true, harnessId);
  else if (t === 'response.completed' || t === 'response.failed' || t === 'response.incomplete') feedTurn(m.session_id, m.response_id || '', false, harnessId);
  applyBusEvent(m.session_id, m.response_id, m.event || {}, Boolean(m.replay));
  if (TURN_EDGES.has(t)) _buses.get(harnessId)?.listeners.forEach((l) => { try { l.current?.(); } catch { /* one listener never stops the rest */ } });
}
function onBusState(harnessId: string, s: 'up' | 'down'): void {
  if (s !== 'up') return;
  // connected, or connected again: each busy conversation of this setup reads its record once
  _settlers.forEach((x) => { if (x.harness === harnessId) x.settle([0]); });
}
export function useHarnessBus(harnessId: string, onActivity?: () => void) {
  const cb = useRef(onActivity);
  cb.current = onActivity;
  useEffect(() => {
    if (!harnessId) return;
    let bus = _buses.get(harnessId);
    if (!bus) {
      const b: Bus = { stop: () => {}, listeners: new Set() };
      _buses.set(harnessId, b);
      b.stop = subscribeHarnessEvents(harnessId, (m) => onBusMsg(harnessId, m), (s) => onBusState(harnessId, s));
      bus = b;
    }
    const mine = bus;
    mine.listeners.add(cb);
    return () => {
      mine.listeners.delete(cb);
      if (!mine.listeners.size && _buses.get(harnessId) === mine) { mine.stop(); _buses.delete(harnessId); }
    };
  }, [harnessId]);
}


// ── the turn controller ────────────────────────────────────────────────────────────────────────
/**
 * One conversation's lifecycle: bind to the store, load history, run turns, settle them.
 *
 * Owns NO composer state on purpose. `send(text, files)` is given what to send, so the composer that
 * drives it keeps its own text.
 */
export function useConversationTurn({ harnessId, sessionId, target, onRan, onSession, onSendStart, onRefused, onMissing, extraHeaders }: {
  harnessId: string;
  sessionId: string | null;
  target: ChatTarget;
  onRan: () => void;
  onSession?: (sid: string) => void;
  /** a first message the server refused or never took: the composer keeps it */
  onRefused?: (text: string, files: { name: string; dataUri: string }[]) => void;
  /** the task no longer exists (its feed answers 404, it was deleted): the thread must let go of it */
  onMissing?: (sid: string) => void;
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
  // The send latch is released when the send's own stream ends (its finally). A turn can also
  // settle off that stream, through the broadcast bus or the read of its record (settleFromRecord)
  // finding the terminal status: busy then goes false and the composer re-enables while the latch stays set,
  // and every later message is dropped at the guard, silently (OSS Playwright, 2026-09-07: a task
  // took three turns and then none). Idle releases the latch; the double-click guard is unaffected
  // because the clicks it collapses land before any render.
  useEffect(() => { if (!busy) sendingRef.current = false; }, [busy]);
  const setPrevId = (id: string | null) => setConvState(convKeyRef.current, { prevId: id });
  const setFirstTurn = (b: boolean) => setConvState(convKeyRef.current, { firstTurn: b });
  const [loading, setLoading] = useState(false);
  // The task's record could not be read on open (not a 404: a 5xx, the network, a body that is not
  // its turns). Nothing was written from it: the store keeps what it held, and the page says the
  // read failed, with Try again (`reload`). Until a read succeeds, a message is not sent from here,
  // since the conversation it would follow is not known.
  const [loadFailed, setLoadFailed] = useState(false);
  const loadFailedRef = useRef(false);
  loadFailedRef.current = loadFailed;
  const [loadTry, setLoadTry] = useState(0);
  const loadSeq = useRef(0);
  const sessionIdRef = useRef(sessionId);
  sessionIdRef.current = sessionId;
  const onMissingRef = useRef(onMissing);
  onMissingRef.current = onMissing;
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
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
  // A read that fails (one quiet second try, then an end: lib/settle) writes nothing: an empty answer
  // here would open the task empty, or wipe a live turn and end it.
  useEffect(() => {
    const seq = ++loadSeq.current;
    const current = () => seq === loadSeq.current;
    setLoadFailed(false);
    const existing = getConvState(convKey);
    if (!sessionId) { setLoading(false); if (!existing.loaded) setConvState(convKey, { loaded: true }); return; }
    // Already loaded, idle, and has content → trust it (no refetch on every open).
    if (existing.loaded && !existing.busy && existing.msgs.length) { setLoading(false); return; }
    setLoading(true);
    readSettled((signal) => loadSessionTurns(sessionId, signal), LOAD_READ).then(({ turns, lastResponseId, missing }) => {
      if (missing) {
        // a deleted task: nothing to show and nothing to send to (a follow-up typed into one ran on
        // the deleted session and billed, 2026-09-07); the page lets go of it
        if (current()) setLoading(false);
        onMissing?.(sessionId); return;
      }
      const { msgs: m, running } = msgsFromTurns(turns);
      const cur = getConvState(convKey);
      if (!running) {
        // Backend is terminal → authoritative for what it holds; a refused or unsent tail stays.
        setConvState(convKey, { msgs: keepUnrecordedTail(m, cur.msgs), prevId: lastResponseId, firstTurn: false, loaded: true, busy: false });
      } else if (!cur.msgs.length) {
        // In-flight with nothing local yet → load the turn's progress-so-far (the backend
        // reconstructs a running turn's partial output from its durable trace) and let the bus
        // stream new events on top. If the trace was still empty this is just the placeholder.
        setConvState(convKey, { msgs: m, prevId: lastResponseId, firstTurn: false, loaded: true, busy: true });
      } else {
        // In-flight and we already hold live msgs (switched away/back mid-turn) → keep them.
        setConvState(convKey, { loaded: true });
      }
      if (current()) setLoading(false);
    }).catch(() => {
      if (!current()) return;
      setLoading(false);
      setLoadFailed(true);
    });
  }, [convKey, sessionId, loadTry]); // eslint-disable-line react-hooks/exhaustive-deps

  /**
   * ONE read of the record, settling the turn when the record says it has ended: the repair for a
   * turn whose end no stream delivered (a dropped or stalled stream, a feed that was down, a
   * terminal frame dropped on a full queue). 'running' and 'behind' (the record does not hold this
   * turn yet) change nothing; 'skip': not this read's to settle (the send's own stream owns its
   * turn, or the conversation moved to another task). Throws when the record cannot be read.
   */
  async function settleFromRecord(sid: string): Promise<'settled' | 'running' | 'behind' | 'skip'> {
    const here = () => (sessionIdRef.current ?? sidRef.current) === sid;
    if (sendingRef.current || !here()) return 'skip';     // the send's own stream owns its turn
    const { turns, lastResponseId, missing } = await loadSessionTurns(sid);
    if (!mounted.current || sendingRef.current || !here()) return 'skip';
    if (missing) { onMissingRef.current?.(sid); return 'skip'; }
    // only settle on the turn being waited for: while the server still lists one turn fewer than
    // this thread holds, the new turn has no record yet (a slow accept), so this is not its end
    if (!turns.length || turns.length < getConvState(convKeyRef.current).msgs.filter((x) => x.role === 'assistant').length) return 'behind';
    const last = turns[turns.length - 1];
    if (!TERMINAL_TURN.has(String(last.status || ''))) return 'running';
    const { msgs: m } = msgsFromTurns(turns);
    // The OTHER settle path. SSE is best-effort; a dropped terminal event lands here instead, and
    // instrumenting only the fast path would bias the success rate — the one metric this event
    // exists to measure — upward.
    const lastAsst = [...m].reverse().find((x) => x.role === 'assistant') as AsstMsg | undefined;
    trackTaskFinished(sid, turnIndexOf(m), {
      ...factsRef.current(),
      status: lastAsst?.status === 'done' ? 'completed' : (lastAsst?.status || 'failed'),
      produced_files: !!lastAsst?.files?.length,
      file_count: lastAsst?.files?.length ?? 0,
    });
    _busSuppress.delete(sid);
    _gapped.delete(sid);                                   // the record's whole answer is in place now
    setConvState(convKeyRef.current, (cur) => ({ msgs: keepUnrecordedTail(carryClocks(m, cur.msgs), cur.msgs), prevId: lastResponseId, firstTurn: false, loaded: true, busy: false }));
    return 'settled';
  }
  const settleRef = useRef(settleFromRecord);
  settleRef.current = settleFromRecord;
  /** settleFromRecord at each of `waits` (ms from now) until one settles, while the turn is still
   *  busy here; a failed read is the next one's to try. Then it is the feeds' again. */
  function settleSoon(waits: readonly number[]): void {
    const sid = sessionIdRef.current ?? sidRef.current;
    if (!sid) return;
    void (async () => {
      let at = 0;
      for (const w of waits) {
        if (w > at) { await new Promise((r) => setTimeout(r, w - at)); at = w; }
        if (!mounted.current || !getConvState(convKeyRef.current).busy) return;
        try {
          const r = await settleRef.current(sid);
          if (r === 'settled' || r === 'skip') return;
        } catch { /* the record could not be read: the next read, or the next word from a feed */ }
      }
    })();
  }
  const settleSoonRef = useRef(settleSoon);
  settleSoonRef.current = settleSoon;
  // While busy, this conversation is one the feeds settle (see _settlers): a reconnect of the
  // setup's feed, or the workspace feed's end frame for its task, has it read its record.
  useEffect(() => {
    if (!busy) return;
    return addSettler({ harness: harnessId, sid: () => sessionIdRef.current ?? sidRef.current, settle: (w) => settleSoonRef.current(w) });
  }, [busy, harnessId]);

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
    if (!last || last.status === 'running') return;
    const key = `${sid}#${idx}`;
    if (settledRead.current.has(key)) return;
    settledRead.current.add(key);
    let stop = false;
    const attempt = async (left: number) => {
      if (stop) return;
      try {
        const { turns } = await loadSessionTurns(sid);
        const t = turns[turns.length - 1];
        if (t && typeof t.elapsed === 'number') {
          // a turn whose own stream ended before it did (_gapped): the record's whole answer, when the
          // record holds just the turns this thread does (nothing unrecorded after it)
          const whole = _gapped.has(sid) ? msgsFromTurns(turns).msgs : null;
          _gapped.delete(sid);

          setConvState(convKeyRef.current, (st) => {
            const answers = (ms: Msg[]) => ms.filter((x) => x.role === 'assistant').length;
            if (whole && answers(whole) === answers(st.msgs)) {
              const merged = carryClocks(whole, st.msgs);
              const localAnswers = st.msgs.filter(
                (x): x is AsstMsg => x.role === 'assistant',
              );
              let answerIndex = 0;

              return {
                msgs: merged.map((x) => {
                  if (x.role !== 'assistant') return x;

                  const local = localAnswers[answerIndex++];
                  if (!local) return x;

                  const files = (local.files || []).reduce(
                    (acc: RespFile[], f) => withFile(acc, f),
                    x.files || [],
                  );

                  return { ...x, files };
                }),
              };
            }

            const out = st.msgs.slice();

            for (let i = out.length - 1; i >= 0; i--) {
              if (out[i].role === 'assistant') {
                // The record's files may arrive after elapsed is recorded.
                const a = out[i] as AsstMsg;
                const files = (t.files || []).reduce(
                  (acc: RespFile[], f) => withFile(acc, f),
                  a.files || [],
                );

                out[i] = {
                  ...a,
                  files,
                  elapsed: t.elapsed,
                };
                break;
              }
            }

            return { msgs: out };
          });

          // Keep retrying while files have not arrived.
          if ((t.files || []).length > 0 || left === 0) return;
        }
      } catch { /* transient; the retry below */ }
      // Growing gaps, about 85s in all: the persist trails the terminal event by seconds when the
      // settle collects produced files, and by much longer when the gateway is busy (an arena
      // finishing six columns at once). Stops on the first read that carries the figures.
      if (left > 0) setTimeout(() => void attempt(left - 1), Math.min(30000, Math.round(4000 * Math.pow(1.5, 6 - left))));
    };
    const t0 = setTimeout(() => void attempt(6), 2500);
    return () => { stop = true; clearTimeout(t0); };
  }, [busy, sessionId, boundSid]); // eslint-disable-line react-hooks/exhaustive-deps
  /**
   * Resolves as soon as the server has taken the turn (true), or when it refused or never took
   * it (false). The answer keeps streaming after that: `busy` holds until it lands. A view that
   * waited for the whole stream here held its composer text and its title for a minute or more.
   */
  /** `opts.input`: the request's whole input, when the caller builds it (a recorded demo's fork,
   *  start/fork.ts: the recorded turn as earlier messages, then this message); the thread shows the
   *  text and attachments as usual. */
  async function send(rawText: string, attach: { name: string; dataUri: string }[] = [], opts: { input?: unknown[] } = {}): Promise<boolean> {
    const text = (rawText || '').trim();
    // `busy` is React state, so three clicks landing in one tick all read it as false and all
    // three stream into the same assistant message: the server runs the turn once, but the
    // reader watches the answer arrive three times over. The latch is a ref because it has to
    // flip now, not at the next render.
    if ((!text && attach.length === 0) || busy || sendingRef.current || !target.backend) return false;
    // a task whose record could not be read: what this message would follow is not known (Try again)
    if (loadFailedRef.current && sessionId) return false;
    sendingRef.current = true;
    const sent = attach;
    // OpenAI Responses input: a string, or a user MESSAGE whose content is text + file parts.
    // (The gateway parses {role,content:[…]}, a bare content-part array reads as empty input.)
    const input_payload: string | unknown[] = opts.input ? opts.input : sent.length
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
    setMsgs((m) => [...m, { role: 'user', text, attachments: sent.map((f) => ({ name: f.name, dataUri: f.dataUri })) },
      { role: 'assistant', blocks: [], files: [], status: 'running', clock: newTurn({ startedAt: Date.now() }) }]);
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
    let started = false;                        // the server accepted the turn (its first event arrived)
    let settle: (took: boolean) => void = () => {};
    const accepted = new Promise<boolean>((r) => { settle = r; });
    const run = async () => {
    try {
      const id = await streamResponse(
        // No `instructions`: the harness's configured Agent Instructions are written into the
        // workspace as AGENTS.md/CLAUDE.md (server-side, from the saved harness), so the model keeps
        // its default system prompt rather than having instructions prepended to the first message.
        // sessionHint: continuity fallback, the gateway continues this session even if prevId was
        // lost client-side (interrupted stream), instead of forking a new one.
        { input: input_payload, backend: target.backend, model: target.model || undefined, previousResponseId: prevId,
          sessionHint: knownSid, harnessId, harnessName: target.name, extraHeaders: extraHeaders?.() || {} },
        { onEvent: (ev) => updateLast((a) => { a.clock = reduceTurn(a.clock || newTurn(), ev as { type: string }, Date.now()); }),
          onCreated: (rid) => { settle(true); setPrevId(rid); },
          onSession: (sid) => {
            started = true;
            settle(true);
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
          onReasoningDelta: (d) => updateLast((a) => { a.blocks = addReasoning(a.blocks, d); }),
          onToolCall: (name, args, callId) => updateLast((a) => { a.blocks = addStep(a.blocks, { name, args, callId }); }),
          onToolResult: (callId, output) => updateLast((a) => { a.blocks = addResult(a.blocks, callId, output); }),
          onTextDelta: (d) => updateLast((a) => { a.blocks = addText(a.blocks, d); }),
          onFile: (f) => updateLast((a) => { a.files = withFile(a.files, f); }),
          onError: (msg) => updateLast((a) => { a.blocks = withError(a.blocks, msg); }),
          onDone: (status, response) => {
            // why an incomplete turn stopped (max_steps | timeout | interrupted) and the server's
            // sentence ride on the terminal event's response object, the same fields the stored
            // record carries
            const inc = (response as { incomplete_details?: { reason?: string; detail?: string } } | undefined)?.incomplete_details;
            updateLast((a) => {
              a.status = status === 'completed' ? 'done'
                : (['failed', 'cancelled', 'incomplete'].includes(status) ? status as AsstMsg['status'] : 'failed');
              if (status === 'incomplete' && inc?.reason) a.incompleteReason = inc.reason;
              if (status === 'incomplete' && inc?.detail) a.incompleteDetail = inc.detail;
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
      // The server answered with a status (a refusal, a cap, an error), or the turn never started:
      // the message stays on screen with what happened. Only a stream that dropped AFTER the turn
      // started is left running for the auto-reconnecting bus, because the turn is still live
      // server-side and painting it failed would strand the user. A refused follow-up used to be
      // mistaken for a dropped stream, left "running", and then reconciled away by the server's
      // turns, which never held it: the message vanished without a word.
      const st = (e as { status?: unknown })?.status;
      const code = String((e as { code?: unknown })?.code || '');
      const answered = typeof st === 'number';
      settle(false);
      if (answered || !started) {
        track('task_blocked', {
          reason: code === 'one_at_a_time' || st === 429 ? 'rate_limited'
            : answered ? 'other' : 'transport',
          ...taskFacts(),
        });
        if (pendId) dropPending(pendId);
        const detail = e instanceof Error ? e.message : String(e);
        if (!(sessionId ?? sidRef.current)) onRefused?.(text, sent.map((f) => ({ name: f.name, dataUri: f.dataUri })));
        updateLast((a) => { a.blocks = withText(a.blocks, answered ? `\n\nError: ${detail}` : '\n\nNot sent. Check your connection and try again.'); a.status = 'failed'; });
      }
    } finally {
      sendingRef.current = false;
      const sk = sessionId ?? sidRef.current;
      // If the stream ended (returned, threw, or went silent past its deadline) but no terminal event
      // set the assistant status, the turn may still be live server-side (transport drop OR a clean
      // drain-close mid-turn), or it ended and its end was lost with the stream. Hand it to the
      // broadcast bus, which reconnects, by releasing suppression, KEEP the working state, and read
      // the record now (and again at 1, 2 and 4 s while it has not caught up): an ended turn settles
      // from it at once; a running one is the feeds' to end (their end frames, or a reconnect, read
      // it again).
      const ms = getConvState(convKeyRef.current).msgs;
      const lastA = ms[ms.length - 1];
      const stillRunning = !!lastA && lastA.role === 'assistant' && (lastA as AsstMsg).status === 'running';
      if (sk && stillRunning) {
        _busSuppress.delete(sk);            // bus renders the remainder; keep busy=true (composer stays disabled)
        _gapped.add(sk);
        settleSoon(SETTLE_NOW);
      } else {
        if (sk) _busSuppress.delete(sk);
        setBusy(false);
      }
      onRan();
      settle(started);
    }
    };
    void run();
    return accepted;
  }

  /** Cancel the running turn, settling from the server verdict as well as the bus event. */
  function stop() {
    const sid = sessionId ?? sidRef.current;
    if (!sid || stopping) return;
    setStopping(true);
    void cancelSession(sid).then((r) => {
      const terminal = ['cancelled', 'failed', 'error', 'done', 'completed', 'incomplete', 'max_turns', 'timeout'];
      if (r.cancelled || terminal.includes(r.status)) {
        updateLast((a) => { a.status = 'cancelled'; if (a.clock && a.clock.status === 'running') a.clock = finish(a.clock, 'cancelled', Date.now()); });
        setBusy(false);
      } else {
        setStopping(false);   // cancel did not land, let the user retry
      }
    }).catch(() => setStopping(false));
  }

  /** A recorded run played into this conversation as if it streamed now (start/replay.ts): the
   *  request, then each recorded event at its own offset from it, folded by the same handlers a live
   *  turn's stream goes through, so it reads the same. Nothing is sent: no task is made and nothing
   *  is spent. The run's own response and task are not taken (they belong to the recording), and
   *  each file it made is shown as `fileOf` maps it (the recording's own copy; null leaves it out).
   *  Ends at its terminal event, or at `endAt` ms when the recording has none. Answers a cancel. */
  function replay(text: string, events: { t: number; ev: Record<string, unknown> }[], fileOf: (f: RespFile) => RespFile | null, endAt = 0): () => void {
    if (busy || sendingRef.current) return () => {};
    const timers: ReturnType<typeof setTimeout>[] = [];
    let over = false;
    const t0 = Date.now();
    setBusy(true);
    onSendStart?.();
    setMsgs((m) => [...m, { role: 'user', text }, { role: 'assistant', blocks: [], files: [], status: 'running', clock: newTurn({ startedAt: t0 }) }]);
    const end = (status: AsstMsg['status']) => {
      if (over) return;
      over = true;
      updateLast((a) => { if (a.status === 'running') a.status = status; if (a.clock && a.clock.status === 'running') a.clock = finish(a.clock, status === 'done' ? 'completed' : status, Date.now()); });
      setBusy(false);
    };
    const d = createResponsesDispatcher({
      onReasoningDelta: (x: string) => updateLast((a) => { a.blocks = addReasoning(a.blocks, x); }),
      onToolCall: (name: string, args: string, callId: string) => updateLast((a) => { a.blocks = addStep(a.blocks, { name, args, callId }); }),
      onToolResult: (callId: string, output: string) => updateLast((a) => { a.blocks = addResult(a.blocks, callId, output); }),
      onTextDelta: (x: string) => updateLast((a) => { a.blocks = addText(a.blocks, x); }),
      onFile: (f: RespFile) => { const g = fileOf(f); if (g) updateLast((a) => { a.files = withFile(a.files, g); }); },
      onError: (msg: string) => updateLast((a) => { a.blocks = withError(a.blocks, msg); }),
      onDone: (status: string) => end(status === 'completed' ? 'done' : (['failed', 'cancelled', 'incomplete'].includes(status) ? status as AsstMsg['status'] : 'failed')),
    });
    // the events due at the same moment fold together, in their order (one render for them)
    const at = new Map<number, Record<string, unknown>[]>();
    for (const { t, ev } of events) { const k = Math.max(0, Math.round(t)); at.set(k, [...(at.get(k) || []), ev]); }
    let last = 0;
    for (const [t, evs] of [...at.entries()].sort((a, b) => a[0] - b[0])) {
      last = Math.max(last, t);
      timers.push(setTimeout(() => {
        if (over) return;
        for (const ev of evs) {
          if (over) return;
          updateLast((a) => { a.clock = reduceTurn(a.clock || newTurn(), ev as { type: string }, Date.now()); });
          d.dispatch(ev as Parameters<typeof d.dispatch>[0]);
        }
      }, t));
    }
    timers.push(setTimeout(() => end('done'), Math.max(endAt, last) + 400));
    return () => { timers.forEach(clearTimeout); if (!over) end('cancelled'); };
  }

  return { msgs, busy, loading, stopping, prevId, firstTurn,
           /** the task's record could not be read on open; `reload` reads it again */
           loadFailed, reload: () => setLoadTry((n) => n + 1),

           liveSessionId: sessionId ?? sidRef.current, convKey,
           send, stop, replay, setMsgs, updateLast };
}
