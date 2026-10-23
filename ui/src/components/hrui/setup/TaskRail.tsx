'use client';
// A setup's task list, the left column of its Tasks tab (docs/uxuidesign/console-91: tasksBody, tkBar,
// tkRows, tkViewSeg, refreshTkList). Every task of the setup, whoever sent it (a test here, an app with
// an API key, a kit's page), most recent activity first: one row on top (New task; search and filter as
// two quiet icons, the filter holding what to show and the time range), a line naming a filter that is
// on, then the rows. Opening one shows it beside the list.
//
// Read live. A task a test has just sent shows at once, from the send itself (the conversation's
// optimistic entry, see lib/conversation addPendingCard), and gives way to the server's card as soon as
// the list carries it. The setup's own feed (useHarnessBus: GET /v1/harnesses/{id}/events) says when a
// task of it starts or ends, and the list's newest page is read then; the workspace watch (lib/use-
// workspace-feed: the workspace's task cards read every few seconds) says so too, and a start reads
// again at 1 s and 2 s while the task is not listed, an end while its card still says running. Each
// time the watch comes up (again), one catch-up read. While it is down the list says live updates are
// paused, with Try again, and a read that failed says so (the first: older tasks could not be read; a
// later one: could not refresh). A row's dot is the setup feed's word first (blue the moment a turn
// starts, finished the moment it ends), the card's after: a card read a moment before a start still
// says the turn before it (lib/conversation feedTurnOf, fmt liveStateOf).
//
// Every task has Delete on its row (Richard 10-18): a trash button at the row's right edge on hover or
// keyboard focus (on a touch screen, on the open task's row), asking first (the design's Delete task
// sheet), and not while it runs. The filter shows All or Failed.
//
// A setup saved from a demo's recorded run (start/replay.ts) has that run as its first task: the oldest
// row, always there, "Recorded" with when the setup was made, blue while it plays. It is no task of
// the server's, so it has no Delete; one that could not be read is said at the list's end, with Try
// again, never left out without a word.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { getSession } from '@/lib/auth';
import { harnessFetch } from '@/lib/hfetch';
import { feedTurnOf, livePending, useFeedTurns, useHarnessBus, type PendingCard } from '@/lib/conversation';
import { useWorkspaceFeed } from '@/lib/use-workspace-feed';
import { TASK_PAGE, type TraceCard } from '@/lib/revamp-data';
import { toast } from '../toast';
import { ago } from '../setups';
import { Skel, SkRows } from '../Skel';
import { createdMs, liveStateOf, stateOf } from './fmt';
import { DeleteTask, titleOf } from './TaskDetail';

const PLUS = <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>;
const SEARCH = <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="M20 20l-4-4" /></svg>;
const X = <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>;
const CHECK = <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.6} aria-hidden="true"><path d="M5 12l5 5L20 7" /></svg>;
const FILTER = <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" aria-hidden="true"><path d="M4 7h16M7 12h10M10 17h4" /></svg>;
const TRASH = <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth={1.9} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3" /></svg>;
const PER = 50;
/** The feed's frames that say a task ended. */
const END_TYPES = new Set(['response.completed', 'response.failed', 'response.incomplete']);
/** After a start or an end: read again at these times (ms) while the card lags the frame. */
const LAG_READS = [1000, 2000];

// ── the list's data ──────────────────────────────────────────────────────────────────────────────

/** One page of the setup's task cards, newest first; throws when the read fails or the answer is not
 *  the list (an edge answering a page of its own), so a failed read says so instead of reading as "no
 *  tasks". Every workspace's: the setup opens from any of them. */
async function readPage(id: string, cursor: string): Promise<{ sessions: TraceCard[]; cursor: string }> {
  const org = getSession()?.orgId;
  if (!org) throw new Error('signed out');
  const q = new URLSearchParams({ org, limit: String(TASK_PAGE), harness: id });
  if (cursor) q.set('cursor', cursor);
  const r = await harnessFetch(`/api/harness/v1/traces?${q.toString()}`);
  if (!r.ok) throw new Error(String(r.status));
  const d = await r.json() as { sessions?: unknown; cursor?: unknown } | null;
  if (!d || !Array.isArray(d.sessions)) throw new Error('not a list of tasks');
  return { sessions: d.sessions as TraceCard[], cursor: typeof d.cursor === 'string' ? d.cursor : '' };
}

/** A task's own card, read by its link: null when there is no such task (the server's 404); throws on
 *  any other failure or an answer that is not a card, so a read that failed is never "not here". */
export async function readTaskCard(sid: string): Promise<TraceCard | null> {
  const r = await harnessFetch(`/api/harness/v1/traces/${encodeURIComponent(sid)}`);
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(String(r.status));
  const m = await r.json() as TraceCard | null;
  if (!m || typeof m.session_id !== 'string' || !m.session_id) throw new Error('not a task card');
  return m;
}

export interface TaskList {
  /** every task read so far, newest first */
  all: TraceCard[];
  byId: Map<string, TraceCard>;
  /** the first page has answered (or failed) */
  ready: boolean;
  /** the newest page has not been read: the list holds only what the page brought (or nothing), and
   *  is never complete */
  failed: boolean;
  /** the last read again failed: the list is as last read */
  stale: boolean;
  /** an older page is there to read */
  more: boolean;
  reading: boolean;
  older: () => void;
  refresh: () => void;
  /** live updates are down (lib/use-workspace-feed): the list may be out of date */
  paused: boolean;
  reconnect: () => void;
  /** a task deleted here: out of the list for good */
  drop: (sid: string) => void;
  /** a card read on its own (a task opened by its link): kept with the rest */
  add: (c: TraceCard) => void;
  /** the tasks just sent from here that the list does not carry yet */
  pending: PendingCard[];
}

/** The setup's tasks: the page's own cards (its last 24 h), the newest page read here, older pages
 *  on request, all kept current by the feeds. `nudge` changes when a test is sent. */
export function useTaskList(id: string, cards: TraceCard[], nudge: number, opts: { fresh?: boolean } = {}): TaskList {
  const [byId, setById] = useState<Map<string, TraceCard>>(() => new Map());
  // null: not read yet; '' the end. A setup this tab has just made has no task yet (`fresh`): its list
  // starts read, so it draws no loading lines in the hand-off from New setup; the first read follows
  const [cursor, setCursor] = useState<string | null>(() => (opts.fresh ? '' : null));
  const freshId = useRef(opts.fresh ? id : '');
  const [failed, setFailed] = useState(false);
  const [stale, setStale] = useState(false);
  const [reading, setReading] = useState(false);
  const gone = useRef(new Set<string>());
  const merge = useCallback((cs: TraceCard[]) => {
    if (!cs.length) return;
    setById((prev) => {
      const n = new Map(prev);
      for (const c of cs) if (c.session_id && !gone.current.has(c.session_id)) n.set(c.session_id, c);
      return n;
    });
  }, []);
  // the setup the reads below are for: an answer for the one before is dropped
  const idNow = useRef(id);
  idNow.current = id;
  useEffect(() => {
    let alive = true;
    // a fresh setup's empty list stays drawn while its first read is out
    setById(new Map()); setCursor(freshId.current === id ? '' : null); setFailed(false); setStale(false);
    // a failed first read leaves the list unfinished: it says older tasks could not be read, never
    // that it has them all (the page's own cards may be all it shows)
    readPage(id, '').then((p) => { if (alive) { merge(p.sessions); setCursor(p.cursor); } })
      .catch(() => { if (alive) setFailed(true); });
    return () => { alive = false; };
  }, [id, merge]);
  // after the reset above, so a setup's own cards are never cleared by it
  useEffect(() => { merge(cards); }, [cards, merge]);
  // the newest page again: one read at a time, and one more after it when asked meanwhile (a frame
  // that came while a read was out may not be in its answer)
  const busy = useRef(false);
  const again = useRef(false);
  const refresh = useCallback(async () => {
    if (busy.current) { again.current = true; return; }
    busy.current = true;
    const forId = id;
    try {
      const p = await readPage(forId, '');
      if (idNow.current !== forId) return;
      merge(p.sessions);
      setFailed(false); setStale(false);
      setCursor((c) => (c === null ? p.cursor : c));
    } catch {
      if (idNow.current === forId) setStale(true);
    } finally {
      busy.current = false;
    }
    if (again.current && idNow.current === forId) { again.current = false; void refreshRef.current(); }
  }, [id, merge]);
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;
  const older = useCallback(async () => {
    if (!cursor || reading) return;
    setReading(true);
    try {
      const p = await readPage(id, cursor);
      merge(p.sessions);
      setCursor(p.cursor);
    } catch { toast('Older tasks could not be read. Try again.'); }
    setReading(false);
  }, [id, cursor, reading, merge]);

  // the setup's own feed says when a task of it starts or ends, whichever workspace it ran in
  const soon = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useHarnessBus(id, () => { if (soon.current) clearTimeout(soon.current); soon.current = setTimeout(() => void refreshRef.current(), 500); });
  useEffect(() => () => { if (soon.current) clearTimeout(soon.current); }, []);

  // the workspace watch says when any task of this setup starts or ends (your app, another tab, this
  // page): read now, then again while the card lags the frame; each time it comes up, one catch-up read
  const byIdRef = useRef(byId);
  byIdRef.current = byId;
  const lagReads = useRef(new Set<ReturnType<typeof setTimeout>>());
  useEffect(() => {
    const ts = lagReads.current;
    return () => { ts.forEach(clearTimeout); ts.clear(); };
  }, [id]);
  const { paused, reconnect } = useWorkspaceFeed({
    on: !!id,
    onFrame: (f) => {
      if (f.harness_id !== id || !f.session_id) return;
      const sid = f.session_id, ended = END_TYPES.has(f.type);
      // still lagging: a start's task not listed yet, an end's card still running (or not listed)
      const lags = () => {
        if (gone.current.has(sid)) return false;
        const c = byIdRef.current.get(sid);
        return !c || (ended && stateOf(c) === 'running');
      };
      void refreshRef.current();
      for (const ms of LAG_READS) {
        const t = setTimeout(() => { lagReads.current.delete(t); if (lags()) void refreshRef.current(); }, ms);
        lagReads.current.add(t);
      }
    },
    onUp: () => { void refreshRef.current(); },
  });

  const all = useMemo(() => [...byId.values()].sort((a, b) => createdMs(b) - createdMs(a)), [byId]);
  // a test was just sent: read again now (the feed's start frame reads it again until it is listed)
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!nudge) return;
    setTick((t) => t + 1);
    void refreshRef.current();
  }, [nudge]);
  const pending = livePending(id, all);
  // times move on ("4 min ago")
  useEffect(() => { const t = setInterval(() => setTick((x) => x + 1), 30000); return () => clearInterval(t); }, []);

  const drop = useCallback((sid: string) => {
    gone.current.add(sid);
    setById((prev) => { if (!prev.has(sid)) return prev; const n = new Map(prev); n.delete(sid); return n; });
  }, []);
  const add = useCallback((c: TraceCard) => merge([c]), [merge]);
  return {
    all, byId, ready: cursor !== null || failed, failed, stale, more: !!cursor, reading,
    older: () => void older(), refresh: () => void refresh(), paused, reconnect, drop, add, pending,
  };
}

/** A task opened by its link (`sid`) that the list has not read (older than its pages, and not one
 *  sent from this page: `own`): its own card, read once the list's first read is in, and kept with the
 *  rest. Only the server's "no such task" (404) or a card of another setup calls `onGone` (the page
 *  lets go of the address); a read that failed is `failed` until `retry` reads it again. */
export function useLinkedTask(id: string, sid: string | null, list: TaskList, own: boolean, onGone: () => void): { failed: boolean; retry: () => void } {
  const asked = useRef('');
  const [failed, setFailed] = useState('');
  const [tries, setTries] = useState(0);
  const cb = useRef({ list, onGone });
  cb.current = { list, onGone };
  const listed = !!sid && list.byId.has(sid);
  useEffect(() => {
    if (!sid || !list.ready || listed || own || asked.current === sid) return;
    asked.current = sid;
    setFailed('');
    readTaskCard(sid).then((m) => {
      if (asked.current !== sid) return;
      if (m && (!m.harness_id || m.harness_id === id)) cb.current.list.add(m);
      else cb.current.onGone();
    }, () => { if (asked.current === sid) setFailed(sid); });
  }, [id, sid, list.ready, listed, own, tries]);
  const retry = useCallback(() => { asked.current = ''; setFailed(''); setTries((n) => n + 1); }, []);
  return { failed: !!sid && failed === sid, retry };
}

// ── what the list shows (tkFiltered, RANGES) ─────────────────────────────────────────────────────

export type TaskView = 'all' | 'failed';
/** The filter's kinds of task, in the menu's order, and what the line under the bar calls each. */
const VIEWS: [TaskView, string][] = [['all', 'All'], ['failed', 'Failed']];
const viewName = (v: TaskView) => (v === 'all' ? '' : VIEWS.find((x) => x[0] === v)?.[1] || '');
export type TaskRange = '1h' | '24h' | '7d' | '30d' | 'all';
/** The design's time ranges, and Any time: the list reaches every task the setup has (older pages
 *  are read on request), so it is the default here. */
const RANGES: [TaskRange, string, number][] = [['1h', '1 h', 3600e3], ['24h', '24 h', 86400e3], ['7d', '7 d', 7 * 86400e3], ['30d', '30 d', 30 * 86400e3], ['all', 'Any time', 0]];
export interface TaskFilter { view: TaskView; range: TaskRange; q: string }
export const NO_FILTER: TaskFilter = { view: 'all', range: 'all', q: '' };

const rangeMs = (r: TaskRange) => RANGES.find((x) => x[0] === r)?.[2] || 0;
const rangeName = (r: TaskRange) => RANGES.find((x) => x[0] === r)?.[1] || '';

function inRange(c: TraceCard, since: number): boolean {
  return !since || createdMs(c) >= since;
}
function passes(c: TraceCard, f: TaskFilter, since: number, needle: string): boolean {
  if (!inRange(c, since)) return false;
  if (f.view === 'failed' && stateOf(c) !== 'failed') return false;
  if (!needle) return true;
  if (titleOf(c).toLowerCase().includes(needle)) return true;
  // a response ID finds its task (each task's newest response is on its card)
  return needle.startsWith('resp_') && String(c.last_response_id || '').toLowerCase().startsWith(needle);
}

/** The tasks the list shows, newest first; how many of each kind the time range holds among the tasks
 *  read; and whether what was read covers the whole range (an older page could still hold some, and a
 *  list whose newest page could not be read holds only what the page brought: a count is only said
 *  when it is complete). */
export function filterTasks(list: TaskList, f: TaskFilter): { shown: TraceCard[]; failedN: number; counts: Record<TaskView, number>; complete: boolean } {
  const since = rangeMs(f.range) ? Date.now() - rangeMs(f.range) : 0;
  const needle = f.q.trim().toLowerCase();
  const shown = list.all.filter((c) => passes(c, f, since, needle));
  const counts: Record<TaskView, number> = { all: 0, failed: 0 };
  for (const c of list.all) {
    if (!inRange(c, since)) continue;
    counts.all += 1;
    if (stateOf(c) === 'failed') counts.failed += 1;
  }
  const oldest = list.all.length ? createdMs(list.all[list.all.length - 1]) : 0;
  const complete = !list.failed && (!list.more || (!!since && !!oldest && oldest < since));
  return { shown, failedN: counts.failed, counts, complete };
}

const STATE_WORD: Record<string, string> = { failed: 'Failed', cancelled: 'Cancelled', incomplete: 'Incomplete' };
const DOT: Record<string, string> = { running: ' run', failed: ' bad', done: ' ok' };

// ── the column ───────────────────────────────────────────────────────────────────────────────────

/** The setup's recorded first task, as its row shows it: its title (the recorded request), when the
 *  setup was made (ms), whether it is the one open, whether it is playing, and opening it. */
export interface RecordedRow { title: string; at: number; on: boolean; running?: boolean; onOpen?: () => void }

export function TaskList({ setupName, list, f, setF, current, isNew, newOpen = isNew, recorded = null, recordedRetry, onOpen, onNew, onGone }: {
  setupName: string;
  list: TaskList;
  f: TaskFilter;
  setF: (f: TaskFilter) => void;
  /** the task open beside the list, when one is */
  current: string | null;
  /** the New task pane is open, nothing sent from it yet */
  isNew: boolean;
  /** a new task is open, sent or not (a sent one is its list's running row until it has its task) */
  newOpen?: boolean;
  /** the setup's recorded first task (start/replay.ts), read from the setup's own record: no task of
   *  the server's, the oldest row, always there */
  recorded?: RecordedRow | null;
  /** the setup's recorded first task could not be read: Try again reads it again */
  recordedRetry?: () => void;
  onOpen: (sid: string, card: TraceCard | null) => void;
  onNew: () => void;
  /** a task deleted from its row */
  onGone: (sid: string) => void;
}) {
  useFeedTurns();      // a row's dot follows the feed (a turn's start and end) the moment it says so
  const [searching, setSearching] = useState(false);
  const [pop, setPop] = useState(false);
  const [shownN, setShownN] = useState(PER);
  useEffect(() => { setShownN(PER); }, [f.view, f.range, f.q]);
  const qRef = useRef<HTMLInputElement | null>(null);
  const searchBtn = useRef<HTMLButtonElement | null>(null);
  const fltBtn = useRef<HTMLButtonElement | null>(null);
  const popRef = useRef<HTMLSpanElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  // the task being deleted from its row
  const [del, setDel] = useState<TraceCard | null>(null);

  // the filter menu: closes on a click outside it or Esc (focus back on its button)
  useEffect(() => {
    if (!pop) return undefined;
    requestAnimationFrame(() => popRef.current?.querySelector<HTMLElement>('[aria-checked="true"]')?.focus());
    const down = (e: MouseEvent) => { const t = e.target as Node; if (!popRef.current?.contains(t) && !fltBtn.current?.contains(t)) setPop(false); };
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopPropagation(); setPop(false); fltBtn.current?.focus(); } };
    document.addEventListener('mousedown', down); document.addEventListener('keydown', key, true);
    return () => { document.removeEventListener('mousedown', down); document.removeEventListener('keydown', key, true); };
  }, [pop]);
  // ↑ ↓ (and j k) move through the list from anywhere on the page but a field or an open sheet
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || !/^(ArrowDown|ArrowUp|j|k)$/.test(e.key)) return;
      const t = e.target as HTMLElement | null;
      if (t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable)) return;
      if (document.querySelector('#hrui .scrim') || popRef.current) return;
      const rows = Array.from(listRef.current?.querySelectorAll<HTMLButtonElement>('button.tk-r') || []);
      if (!rows.length || !listRef.current?.offsetParent) return;
      e.preventDefault();
      const cur = rows.findIndex((r) => r.classList.contains('on'));
      const next = Math.max(0, Math.min(rows.length - 1, cur + (e.key === 'ArrowDown' || e.key === 'j' ? 1 : -1)));
      if (next !== cur) { rows[next].click(); rows[next].focus({ preventScroll: true }); rows[next].scrollIntoView({ block: 'nearest' }); }
    };
    document.addEventListener('keydown', key);
    return () => document.removeEventListener('keydown', key);
  }, []);

  const { shown, failedN, counts, complete } = filterTasks(list, f);
  const listed = shown.slice(0, shownN);
  const needle = f.q.trim().toLowerCase();
  // a test sent from here that the list does not carry yet: shown at once, as running
  const pend = f.view === 'all' ? list.pending.filter((p) => !needle || p.title.toLowerCase().includes(needle)) : [];
  const on = f.view !== 'all' || f.range !== 'all';
  const openSearch = (v: boolean) => {
    setSearching(v); setPop(false);
    if (v) requestAnimationFrame(() => qRef.current?.focus());
    else { setF({ ...f, q: '' }); requestAnimationFrame(() => searchBtn.current?.focus()); }
  };
  const it = (val: string, cur: string, label: React.ReactNode, pick: () => void) => (
    <button key={val} type="button" role="menuitemradio" aria-checked={val === cur} onClick={() => { pick(); setPop(false); fltBtn.current?.focus(); }}>
      {val === cur ? CHECK : <i />}{label}
    </button>
  );
  const wider = RANGES.findIndex((x) => x[0] === f.range);
  const next = f.range !== 'all' && wider >= 0 ? RANGES[wider + 1] : null;

  const bar = searching || f.q ? (
    <div className="tk-bar">
      <label className="search tk-sq">{SEARCH}<span className="sr">Search tasks</span>
        <input ref={qRef} id="q" type="search" placeholder="Search tasks" value={f.q} autoComplete="off" spellCheck={false}
          onChange={(e) => setF({ ...f, q: e.target.value })}
          onKeyDown={(e) => { if (e.key === 'Escape') { e.preventDefault(); openSearch(false); } }} />
      </label>
      <button type="button" className="icon-btn tk-ib" aria-label="Close search" title="Close search" onClick={() => openSearch(false)}>{X}</button>
    </div>
  ) : (
    <div className="tk-bar">
      <button type="button" className={`btn tk-newb${isNew ? ' on' : ''}`} aria-pressed={isNew} onClick={onNew}>{PLUS}New task</button>
      <span className="grow" />
      <button ref={searchBtn} type="button" className="icon-btn tk-ib" aria-label="Search tasks" title="Search tasks" onClick={() => openSearch(true)}>{SEARCH}</button>
      <span className="flt-w">
        <button ref={fltBtn} type="button" className={`icon-btn tk-ib${on ? ' on' : ''}`} aria-haspopup="menu" aria-expanded={pop}
          aria-label={`Filter tasks${failedN && complete ? `, ${failedN} failed` : ''}`} title="Filter" onClick={() => setPop(!pop)}>
          {FILTER}{failedN && f.view !== 'failed' ? <i className="flt-dot" aria-hidden="true" /> : null}
        </button>
        {pop ? (
          <span ref={popRef} className="rng-pop flt-pop" role="menu" aria-label="Filter tasks">
            {VIEWS.map(([k, label]) => it(k, f.view,
              <>{label}{k !== 'all' && counts[k] && complete ? <span className="flt-n">{counts[k].toLocaleString('en-US')}</span> : null}</>,
              () => setF({ ...f, view: k })))}
            <span className="flt-hr" role="separator" />
            {RANGES.map(([k, label]) => it(k, f.range, label, () => setF({ ...f, range: k })))}
          </span>
        ) : null}
      </span>
    </div>
  );

  // the recorded first task: the oldest row, once the list reaches its end, under the same filters
  // (it did not fail; its search is its title)
  const since = rangeMs(f.range) ? Date.now() - rangeMs(f.range) : 0;
  const rec = recorded && f.view === 'all' && (!since || recorded.at >= since) && (!needle || recorded.title.toLowerCase().includes(needle)) ? recorded : null;
  const atEnd = !list.failed && shown.length <= listed.length && (!list.more || complete);
  const loading = !list.ready && !list.all.length;
  const none = list.ready && !list.failed && !list.all.length && !list.pending.length && !recorded && !recordedRetry;
  const empty = list.ready && !shown.length && !pend.length && !rec && !recordedRetry;
  // one quiet line on top when what the list shows may be behind: a read again failed, or live
  // updates are down (a list that was never read says so at its end instead)
  const behind = list.failed ? null
    : list.stale ? <div className="tk-empty" role="status">Could not refresh.<button type="button" className="link-q inl" onClick={list.refresh}>Try again</button></div>
      : list.paused ? <div className="tk-empty" role="status">Live updates paused. This list may be out of date.<button type="button" className="link-q inl" onClick={list.reconnect}>Try again</button></div>
        : null;
  return (
    <div className="tk-l">
      {bar}
      {on ? (
        <div className="tk-fsum">
          <span>{[viewName(f.view), f.range !== 'all' ? `Last ${rangeName(f.range)}` : ''].filter(Boolean).join(' · ')}</span>
          <button type="button" className="link-q" onClick={() => setF({ ...NO_FILTER, q: f.q })}>Clear</button>
        </div>
      ) : null}
      <div ref={listRef} className="tk-list" id="tkList" role="list" aria-label={`Tasks of ${setupName}`}>
        {behind}
        {loading ? <Skel label="Loading the tasks"><SkRows n={6} lead={false} /></Skel> : null}
        {pend.map((p) => {
          const sel = p.sid ? p.sid === current : !current && newOpen;
          return (
            <div key={p.tempId} className="tk-rw" role="listitem">
              <button type="button" className={`tk-r${sel ? ' on' : ''}`} aria-current={sel ? 'true' : undefined} onClick={() => { if (p.sid) onOpen(p.sid, null); }}>
                <span className="dot run" aria-hidden="true" />
                <span className="tk-rt"><b>{p.title || 'New task'}</b><small>Just now<span className="sr"> · Running</span></small></span>
              </button>
            </div>
          );
        })}
        {listed.map((c) => {
          const sid = c.session_id, st = liveStateOf(c, feedTurnOf(sid)), sel = !isNew && sid === current, made = createdMs(c);
          const word = STATE_WORD[st] || '';
          const title = titleOf(c);
          // a task not running (a running one is stopped first) can be deleted from its row
          const canDel = st !== 'running';
          return (
            <div key={sid} className="tk-rw" role="listitem">
              <button type="button" className={`tk-r${sel ? ' on' : ''}`} data-tkpick={sid} aria-current={sel ? 'true' : undefined} onClick={() => onOpen(sid, c)}>
                <span className={`dot${DOT[st] || ''}`} aria-hidden="true" />
                <span className="tk-rt"><b>{title}</b>
                  <small>{made ? ago(made) : ''}
                    {st === 'running' ? <span className="sr"> · Running</span> : null}
                    {word ? (st === 'failed' ? <span className="tk-fr"> · {word}</span> : <> · {word}</>) : null}
                  </small>
                </span>
              </button>
              {canDel ? (
                // the sheet gives focus back to what opened it: this button, focused on a click too
                <button type="button" className="tk-mb tk-rdel" aria-label={`Delete task ${title}`} title="Delete task"
                  onClick={(e) => { e.currentTarget.focus(); setDel(c); }}>{TRASH}</button>
              ) : null}
            </div>
          );
        })}
        {rec && list.ready && atEnd ? (
          <div className="tk-rw" role="listitem">
            <button type="button" className={`tk-r${rec.on ? ' on' : ''}`} aria-current={rec.on ? 'true' : undefined} onClick={rec.onOpen}>
              {/* blue while it plays, as a live run's dot is while it runs */}
              <span className={`dot${rec.running ? ' run' : ' ok'}`} aria-hidden="true" />
              <span className="tk-rt"><b>{rec.title}</b><small>Recorded{rec.at ? ` · ${ago(rec.at)}` : ''}{rec.running ? <span className="sr"> · Running</span> : null}</small></span>
            </button>
          </div>
        ) : null}
        {recordedRetry && list.ready && atEnd ? (
          <div className="tk-empty" role="alert">The recorded first task could not be read.
            <button type="button" className="link-q inl" onClick={recordedRetry}>Try again</button></div>
        ) : null}
        {shown.length > listed.length ? (
          <button type="button" className="tk-more" onClick={() => setShownN((n) => n + PER)}>
            Show more · {(shown.length - listed.length).toLocaleString('en-US')} left
          </button>
        ) : list.more && !complete ? (list.reading
          ? <Skel label="Reading older tasks"><SkRows n={2} lead={false} /></Skel>
          : <button type="button" className="tk-more" onClick={list.older}>Show older tasks</button>
        ) : null}
        {list.failed ? (
          <div className="tk-empty" role="alert">{list.all.length ? 'Older tasks could not be read.' : 'Tasks could not be read.'}
            <button type="button" className="link-q inl" onClick={list.refresh}>Try again</button></div>
        ) : none ? <div className="tk-empty">No tasks yet.</div>
          : empty ? (
            <div className="tk-empty">{f.range !== 'all' ? `No tasks match in the last ${rangeName(f.range)}.` : 'No tasks match.'}
              {next ? <button type="button" className="link-q inl" onClick={() => setF({ ...f, range: next[0] })}>{next[0] === 'all' ? 'Show any time' : `Try ${next[1]}`}</button> : null}
            </div>
          ) : null}
      </div>
      {del ? (
        <DeleteTask card={del} onClose={() => setDel(null)}
          onGone={(sid) => {
            onGone(sid);
            // focus to the task open now (the next one, when it was the open one), once it is drawn
            requestAnimationFrame(() => requestAnimationFrame(() => {
              const q = (sel: string) => listRef.current?.querySelector<HTMLButtonElement>(sel);
              (q('button.tk-r.on') || q('button.tk-r'))?.focus({ preventScroll: true });
            }));
          }} />
      ) : null}
    </div>
  );
}
