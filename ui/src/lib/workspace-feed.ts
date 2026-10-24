// The workspace's task activity: a frame each time a task of the current workspace starts or ends. It
// is how Studio's rows, a setup's task list and a task's trace hear of a task they did not start
// themselves (a task sent from an app with an API key, from another tab, from a kit's page).
//
// This gateway has no push for the workspace as a whole (a setup has its own live feed, GET
// /v1/harnesses/{id}/events, which a setup's page holds: lib/conversation useHarnessBus). So the
// workspace is WATCHED: while a page listens, the newest task cards of the current workspace are read
// (GET /v1/traces, WINDOW of them), every BUSY_MS while one of them runs and every IDLE_MS otherwise,
// and what changed between two reads goes to the listeners as frames: a card that is running and was
// not (or is new) is a start; a card that was running and is not, or a finished one that is new or
// was written again since, is an end. The first read of a watch says nothing of what it found: it is
// the watch coming up, and each listener reads what it shows once then (onUp), as it would after a
// push stream connected.
//
// ONE watch per tab, shared by every listener in it, for the workspace current when it began (a
// listener added after a switch begins a new one); it stops when the last listener leaves (a page
// hides it: lib/use-workspace-feed). A read that fails is 'down' (said once in the browser console)
// and is read again with backoff (about 2 s, doubling to 30 s); the next read that answers is 'up'
// again, with no frames for what passed meanwhile (the listeners read once more instead).
import { harnessFetch } from '@/lib/hfetch';
import { getSession } from '@/lib/auth';
import { appendWorkspaceQuery, workspaceHeaders } from '@/lib/workspace';
import { RUNNING, type TraceCard } from '@/lib/revamp-data';

export interface FeedFrame {
  session_id: string;
  harness_id: string;
  workspace: string;
  /** who started the task */
  member: string;
  /** 'harness.turn.started', or the ending: 'response.completed' | 'response.failed' | 'response.incomplete' */
  type: string;
  /** the task's state as its card says it ('running', 'completed', 'failed', 'cancelled', ...) */
  status: string;
  /** seconds: when the card that says it was written */
  at: number;
}

/** 'connecting' before the first read has answered, 'up' while reads answer, 'down' after one failed
 *  (it is read again with backoff). Only 'up' means current. */
export type FeedState = 'connecting' | 'up' | 'down';

type FrameFn = (f: FeedFrame) => void;
type StateFn = (s: FeedState) => void;

/** How many of the workspace's newest task cards each read takes. */
export const WINDOW = 50;
/** Between reads while one of the cards read runs (its end is what a page waits for). */
export const BUSY_MS = 3_000;
/** Between reads while none runs (a task from an app starts on its own). */
export const IDLE_MS = 10_000;
/** After a read that failed: about this long, doubling, at most FEED_BACKOFF_MAX_MS. */
export const FEED_BACKOFF_FIRST_MS = 2_000;
export const FEED_BACKOFF_MAX_MS = 30_000;

const END_OF: Record<string, string> = {
  completed: 'response.completed', done: 'response.completed',
  failed: 'response.failed', error: 'response.failed', cancelled: 'response.failed',
  incomplete: 'response.incomplete', timeout: 'response.incomplete', max_turns: 'response.incomplete', interrupted: 'response.incomplete',
};

function headers(): Record<string, string> {
  const s = getSession();
  return {
    'x-harness-org': s?.orgId || '',
    'x-harness-member': s?.member?.email || s?.member?.id || '',
    ...workspaceHeaders(),
  };
}

/** Which watch the headers ask for: a workspace switch (or another sign-in) needs a new one. */
const keyOf = (h: Record<string, string>) => JSON.stringify(h);

interface Conn { key: string; stop: () => void; now: () => void }
interface Seen { running: boolean; at: number }

const frameSubs = new Set<FrameFn>();
const stateSubs = new Set<StateFn>();
let state: FeedState = 'connecting';
let conn: Conn | null = null;

function setState(s: FeedState): void {
  if (s === state) return;
  state = s;
  stateSubs.forEach((f) => { try { f(s); } catch { /* one listener never stops the rest */ } });
}

function emit(f: FeedFrame): void {
  frameSubs.forEach((fn) => { try { fn(f); } catch { /* one listener never stops the rest */ } });
}

/** What changed between the cards `seen` held and the cards just read, as frames, oldest first.
 *  `since` (seconds): when the read `seen` came from began; a finished card new to the window is an
 *  end only when it was written after that (an older one has only come into view). */
export function framesBetween(seen: Map<string, Seen>, cards: TraceCard[], since: number): FeedFrame[] {
  const out: FeedFrame[] = [];
  for (const c of cards) {
    const sid = c.session_id, harness = c.harness_id || '';
    if (!sid || !harness) continue;
    const status = String(c.status || '');
    const running = RUNNING.has(status);
    const at = Number(c.finished_at) || 0;
    const was = seen.get(sid);
    const base = { session_id: sid, harness_id: harness, workspace: String(c.workspace || ''), member: String(c.member_id || ''), status, at };
    if (running) {
      if (!was || !was.running) out.push({ ...base, type: 'harness.turn.started' });
    } else if (END_OF[status] && (was ? was.running || at > was.at : at >= since)) {
      out.push({ ...base, type: END_OF[status] });
    }
  }
  return out.sort((a, b) => a.at - b.at);
}

async function readCards(h: Record<string, string>, signal: AbortSignal): Promise<TraceCard[]> {
  const q = new URLSearchParams({ org: h['x-harness-org'], limit: String(WINDOW) });
  appendWorkspaceQuery(q);
  const r = await harnessFetch(`/api/harness/v1/traces?${q.toString()}`, { headers: h, cache: 'no-store', signal });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const d = await r.json().catch(() => null) as { sessions?: unknown } | null;
  if (!d || !Array.isArray(d.sessions)) throw new Error(`HTTP ${r.status}, not a task list`);
  return d.sessions as TraceCard[];
}

function connect(h: Record<string, string>): Conn {
  let stopped = false;
  let ctrl: AbortController | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let reading = false;
  let seen: Map<string, Seen> | null = null;
  let seenSince = 0;                               // seconds: when the read `seen` came from began
  let failures = 0;
  let said = '';                                   // the last failure the console was told of
  const schedule = (ms: number) => {
    if (stopped) return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => { timer = null; void read(); }, ms);
  };
  const read = async () => {
    if (stopped || reading) return;
    reading = true;
    ctrl = new AbortController();
    let next = IDLE_MS;
    const began = Date.now() / 1000;
    try {
      const cards = await readCards(h, ctrl.signal);
      if (stopped) return;
      failures = 0; said = '';
      const frames = seen ? framesBetween(seen, cards, seenSince) : [];
      // the server's clock may run ahead of or behind this one: half a minute either way
      seenSince = began - 30;
      seen = new Map(cards.map((c) => [c.session_id, { running: RUNNING.has(String(c.status || '')), at: Number(c.finished_at) || 0 }]));
      // up first: a listener that hears it reads what is there now, the frames then add to that
      setState('up');
      frames.forEach(emit);
      if (cards.some((c) => RUNNING.has(String(c.status || '')))) next = BUSY_MS;
    } catch (e) {
      if (stopped) return;
      const why = e instanceof Error ? e.message : String(e);
      if (why !== said) { console.warn(`Task updates could not be read: ${why}; trying again`); said = why; }
      // what passed while down is not known: the next read that answers starts afresh
      seen = null;
      setState('down');
      next = Math.min(FEED_BACKOFF_MAX_MS, FEED_BACKOFF_FIRST_MS * 2 ** failures);
      failures += 1;
    } finally {
      reading = false;
    }
    schedule(next);
  };
  void read();
  return {
    key: keyOf(h),
    stop: () => { stopped = true; ctrl?.abort(); if (timer) clearTimeout(timer); timer = null; },
    now: () => { if (!stopped && !reading) { if (timer) clearTimeout(timer); timer = null; void read(); } },
  };
}

function ensure(): void {
  const h = headers();
  if (!h['x-harness-org']) return;                  // not signed in: nothing to watch
  if (conn && conn.key === keyOf(h)) return;
  conn?.stop();
  state = 'connecting';
  stateSubs.forEach((f) => { try { f('connecting'); } catch { /* none */ } });
  conn = connect(h);
}

/** Listen to the workspace's task activity: `onFrame` for each task start or end, `onState` now and
 *  on every change of the watch's state. One watch per tab, begun by the first listener, for the
 *  workspace current then (a listener added after a switch begins a new one), and stopped when the
 *  last one leaves. Returns the unsubscribe. */
export function subscribeWorkspaceFeed(onFrame: FrameFn, onState?: StateFn): () => void {
  frameSubs.add(onFrame);
  ensure();
  if (onState) {
    stateSubs.add(onState);
    try { onState(conn ? state : 'down'); } catch { /* none */ }
  }
  return () => {
    frameSubs.delete(onFrame);
    if (onState) stateSubs.delete(onState);
    if (!frameSubs.size && conn) {
      conn.stop();
      conn = null;
      state = 'connecting';
    }
  };
}

/** Read again now instead of at the end of the wait (a person's Try again). */
export function reconnectWorkspaceFeed(): void {
  conn?.now();
}
