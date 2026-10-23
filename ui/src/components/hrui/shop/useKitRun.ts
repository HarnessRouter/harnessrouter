'use client';
// What the kit's app is doing, as its setup's own task trace says (the design's kit page Trace pane,
// which its prototype simulates). The kit app runs its work as tasks of the kit's setup; this
// follows the one running now, or the first one started after the page opened, and reads its
// recorded trace while it works. Nothing here is estimated: the rows, the times and the status are
// the task's own.
//
// Nothing pushes a task's start or end to this page, so the setup's newest tasks are read every
// POLL_MS while the page is visible (a read that fails is tried again, further apart, until one
// answers), and a running task's trace every TRACE_MS; its end, seen on the list, turns the card and
// makes the final trace read.
import { useEffect, useRef, useState } from 'react';
import { tracesApi } from '@/studio/traces/api';
import { flatten } from '@/studio/traces/flatten';
import type { TraceCard } from '@/lib/revamp-data';
import { newestTasks } from '../setups';
import { createdMs, stateOf, type TaskState } from '../setup/fmt';
import type { TRow } from '../trace/TraceView';

/** A trace event as the shared trace view reads it. */
export type FRow = TRow;
export interface KitRun {
  card: TraceCard | null;
  st: TaskState | null;
  rows: FRow[] | null;
  /** the trace could not be read (its last read failed) */
  failed: boolean;
  /** read the trace again (a person's Try again) */
  retry: () => void;
}

/** A running task's trace, read again this often (its steps have no push). */
export const TRACE_MS = 2500;
/** The setup's newest tasks, read this often while the page is visible: a task's start and end have no push. */
export const POLL_MS = 3000;
/** A tasks read that fails is tried again after 2 s, 4 s, ... at most this far apart, until one answers. */
const RETRY_MAX_MS = 30_000;

const visible = () => typeof document === 'undefined' || document.visibilityState === 'visible';
const running = (c: TraceCard | null) => !!c && stateOf(c) === 'running';

/** The task to follow, from the newest-first list and the one followed so far. */
function pick(list: TraceCard[], cur: TraceCard | null, openedAt: number): TraceCard | null {
  const top = list[0] || null;
  if (cur) {
    const fresh = list.find((x) => x.session_id === cur.session_id) || cur;
    if (running(fresh)) return fresh;
    if (top && top.session_id !== cur.session_id && createdMs(top) > createdMs(cur)) return top;
    return fresh;
  }
  // a task already running when the page opened is happening now; an older finished one is not
  if (top && (running(top) || createdMs(top) >= openedAt - 5000)) return top;
  return null;
}

export function useKitRun(harnessId: string | null): KitRun {
  const [card, setCard] = useState<TraceCard | null>(null);
  const [rows, setRows] = useState<FRow[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [again, setAgain] = useState(0);
  const openedAt = useRef(Date.now());
  const cur = useRef<TraceCard | null>(null);
  cur.current = card;

  // the setup's newest tasks: the task to follow, and how it stands
  const hid = useRef(harnessId);
  hid.current = harnessId;
  const readTasks = async (): Promise<void> => {
    const id = hid.current;
    if (!id) return;
    const page = await newestTasks(id);
    if (hid.current !== id) return;
    const next = pick(page.sessions, cur.current, openedAt.current);
    if (next && (next.session_id !== cur.current?.session_id || next.status !== cur.current?.status || next.elapsed !== cur.current?.elapsed)) {
      cur.current = next;
      setCard(next);
    }
  };
  // read as the page opens (a task already running is happening now), then every POLL_MS while the page
  // is visible; a read that fails is not "no task": it is read again, further apart, until one answers
  useEffect(() => {
    if (!harnessId) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let fails = 0;
    const step = async () => {
      if (visible()) {
        try { await readTasks(); fails = 0; } catch { fails += 1; }
      }
      if (alive) timer = setTimeout(() => void step(), fails ? Math.min(RETRY_MAX_MS, 2000 * 2 ** (fails - 1)) : POLL_MS);
    };
    void step();
    return () => { alive = false; if (timer) clearTimeout(timer); };
  // once per setup; `readTasks` reads the id it is given through `hid`
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [harnessId]);

  // its trace: read again while it works, and once more when it ends. A different task starts
  // empty, not with the last one's rows.
  const sid = card?.session_id || '';
  const going = running(card);
  const shownFor = useRef('');
  useEffect(() => { if (shownFor.current && shownFor.current !== sid) { setRows(null); setFailed(false); } shownFor.current = sid; }, [sid]);
  useEffect(() => {
    if (!sid) { setRows(null); return; }
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      if (visible()) {
        try {
          // the manifest says how the trace is kept; one that cannot be read is a trace that could not
          // be read, never an empty one
          const m = await tracesApi.manifest(sid);
          const evs = await tracesApi.events(sid, (m && m.chunks) || []);
          if (!alive) return;
          setRows(flatten(evs) as FRow[]); setFailed(false);
        } catch { if (alive) setFailed(true); }
      }
      if (alive && going) timer = setTimeout(() => void load(), TRACE_MS);
    };
    void load();
    return () => { alive = false; if (timer) clearTimeout(timer); };
  }, [sid, going, again]);

  return { card, st: card ? stateOf(card) : null, rows, failed, retry: () => setAgain((n) => n + 1) };
}
