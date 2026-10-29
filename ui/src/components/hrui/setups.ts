'use client';
// The setups of the current workspace with what Studio says about each one, all read live: the setup
// records (custom harnesses) and each one's own task index.
//
// What a row claims is only ever what was read:
// - A read that failed, or did not answer within READ_TIMEOUT_MS, is not "no tasks". The row keeps the
//   last read that answered (in this tab, across Studio's mounts) and that setup alone is read again
//   with backoff. A setup with no answered read yet claims no health and no number (`tasksKnown`).
// - At most READS_IN_FLIGHT task reads are out at once, in the list's order: a workspace with dozens
//   of setups sent them all in one burst and the console's proxy dropped some.
//
// Every task of a setup counts, whoever sent it (a test here, an app with an API key, a kit's page):
// the gateway's cards do not say where a task came from. A setup's health is read from the tasks of
// the window (HEALTH_MIN finished ones or more, under HEALTH_OK of them done: needs a look).
//
// Studio keeps its rows current while it shows (useSetups({ live: true })) through the workspace watch
// (lib/workspace-feed: the workspace's newest task cards read every few seconds, each start and end
// told as a frame). A start marks its setup running at once; an end marks the task ended at once and
// reads that setup's newest tasks again for its numbers, again shortly while the card does not show
// the end yet. Each time the watch comes up, every setup's newest tasks are read once; a setup whose
// newest tasks read the same keeps its cards. While the watch is not up the rows stay as last read
// and heard, and once that has lasted a few seconds `paused` says so (the page says its list may be
// out of date, with Try again: lib/use-workspace-feed). Hidden, the watch stops and nothing is read.
import { useCallback, useEffect, useRef, useState } from 'react';
import type { FeedFrame } from '@/lib/workspace-feed';
import { useWorkspaceFeed } from '@/lib/use-workspace-feed';
import { getHarnessPlugs, listCustom, readCustom, loadBases, oobById, oobDefaultModel, type BaseInfo, type CustomHarness } from '@/lib/harness';
import { fetchHarnessTasks, p95Of, RUNNING, TERMINAL_BAD, TERMINAL_OK, type TraceCard } from '@/lib/revamp-data';
import { withDeadline } from '@/lib/settle';
import { towerOf, type Tower } from './tower';
import { madeHere, seededSetup } from './start/seed';
import {
  countOn, hasPlugsEntry, setupPlugins, setupSkills, setupTools, type PlugBinding, type SetupPlugin, type SetupSkill, type SetupTool,
} from './setup/setupParts';

/** A setup's tasks in the window: how many, how many have finished, the share of those that finished
 *  done (null with none finished), and the p95 of how long they ran (null with too few to say). */
export interface SetupStats { n: number; fin: number; succ: number | null; p95: string | null }
/** What a setup's tasks of the window say of it: none ran ('idle'), too many of the finished ones did
 *  not finish done ('failing'), or the rest ('healthy'). */
export type Health = 'healthy' | 'failing' | 'idle';

export interface SetupRow {
  h: CustomHarness;
  baseName: string;
  tower: Tower;
  day: SetupStats;           // its tasks in the last 24 h
  dayCapped: boolean;        // more tasks in the 24 h than were read; `day.n` is a floor
  lastAny: number | null;    // ms, its newest task
  running: boolean;
  /** its plugins binding as read: null when it has none, undefined when it could not be read */
  binding: PlugBinding | null | undefined;
  /** what a person added to it (setup/setupParts.ts, scope 'added'): the lists the Agent stack and
   *  Studio's card count, never a built-in skill or tool */
  added: { plugins: SetupPlugin[]; skills: SetupSkill[]; tools: SetupTool[] };
  /** a read of its tasks has answered in this tab. False: nothing is known of them yet, so no health
   *  and no number is claimed for it (never "Idle" or "No tasks yet") */
  tasksKnown: boolean;
  /** its latest read failed or had no answer in time: what it shows is the last read that answered */
  readFailed: boolean;
}

const DAY_MS = 86400_000;
/** Fired on window when the setups should be read again. */
export const SETUPS_EVENT = 'hrui:setups';
const MAX_PAGES = 6;   // 300 newest tasks per setup: a busier setup shows its count as a floor
/** Hidden longer than this, Studio reads its setups' records again too when it is shown (a coding
 *  agent may have saved a setup meanwhile). */
export const BACK_FULL_MS = 60_000;
/** A setup's task read (its pages of the day) that has no answer by then has failed. */
export const READ_TIMEOUT_MS = 12_000;
/** How many setups' task reads are out at once; the rest wait their turn, in the list's order. */
export const READS_IN_FLIGHT = 6;
/** A setup whose read failed is read again after this, doubling up to RETRY_MAX_MS. */
export const RETRY_FIRST_MS = 2_000;
const RETRY_MAX_MS = 60_000;
/** The first load draws its rows by then even when some setups' reads are still out; those rows say
 *  nothing until their read lands. */
export const FIRST_DRAW_MS = 3_000;
const LIST_TIMEOUT_MS = 20_000;
/** Health: at least this many finished tasks, under this share done, needs a look. */
export const HEALTH_MIN = 3;
export const HEALTH_OK = 0.9;

/** When a task's card was last written (its latest settle, or its start while it runs), in ms. */
const atMs = (c: TraceCard) => (Number(c.finished_at) || 0) * 1000;

/** A setup's task cards back to `since` (every task of the setup, whichever workspace is current).
 *  `first`: its newest page, when the caller has just read it. A page that cannot be read rejects
 *  (TasksReadError), never reads as the end of the history. */
export async function tasksSince(id: string, since: number, first?: { sessions: TraceCard[]; cursor: string },
  signal?: AbortSignal): Promise<{ cards: TraceCard[]; capped: boolean }> {
  const cards: TraceCard[] = [];
  let cursor = '';
  for (let p = 0; p < MAX_PAGES; p++) {
    const page = p === 0 && first ? first : await fetchHarnessTasks(id, cursor, { anyWorkspace: true, signal });
    cards.push(...page.sessions);
    cursor = page.cursor;
    // a page can come back empty with history after it (the reach filter took every task on it): it
    // ends nothing; only the history's end, or a page reaching back past `since`, does
    if (!cursor) return { cards, capped: false };
    if (page.sessions.length && atMs(page.sessions[page.sessions.length - 1]) < since) return { cards, capped: false };
  }
  return { cards, capped: !!cursor };
}

/** A setup's newest tasks, as one page: the first page that holds any, passing over a page the reach
 *  filter emptied while the history goes on (up to MAX_PAGES). A page that cannot be read rejects;
 *  the caller decides what it keeps meanwhile. */
export async function newestTasks(id: string, opts: { anyWorkspace?: boolean } = {}): Promise<{ sessions: TraceCard[]; cursor: string }> {
  let cursor = '';
  for (let p = 0; p < MAX_PAGES; p++) {
    const page = await fetchHarnessTasks(id, cursor, opts);
    if (page.sessions.length || !page.cursor) return page;
    cursor = page.cursor;
  }
  return { sessions: [], cursor };
}

export function statsOf(cards: TraceCard[]): SetupStats {
  // finished: done, or failed (a task stopped or cut at a limit is neither a success nor a failure)
  const fin = cards.filter((c) => TERMINAL_OK.has(c.status || '') || TERMINAL_BAD.has(c.status || ''));
  const ok = fin.filter((c) => TERMINAL_OK.has(c.status || '')).length;
  return { n: cards.length, fin: fin.length, succ: fin.length ? ok / fin.length : null, p95: p95Of(fin) };
}

/** A setup's health from its tasks of the window (the old harness index's rule): none ran is idle;
 *  HEALTH_MIN or more finished with under HEALTH_OK of them done is failing; else healthy. */
export function healthOf(s: SetupStats): Health {
  if (!s.n) return 'idle';
  return s.succ != null && s.succ < HEALTH_OK && s.fin >= HEALTH_MIN ? 'failing' : 'healthy';
}

/** The plugins binding of a setup, read only when its record says it has one: null when it has none
 *  (or it is off), undefined when it could not be read. */
export async function plugsOf(h: CustomHarness): Promise<PlugBinding | null | undefined> {
  if (!hasPlugsEntry(h)) return null;
  try {
    const p = await getHarnessPlugs(h.id);
    return p && p.enabled !== false ? { plugs: p.plugs || [] } : null;
  } catch { return undefined; }
}

// What this tab knows of each setup, across Studio's mounts and the setup's own page: the last read of
// its tasks that answered (a read that fails never replaces it).
interface Known { cards: TraceCard[]; capped: boolean; sig: string }
const knownTasks = new Map<string, Known>();
/** Forget what this tab has read of its setups (a test's fresh start). */
export function forgetSetupReads(): void { knownTasks.clear(); }

/** A setup as Studio and its page read it. `binding`: its plugins binding (plugsOf); `base`: its agent
 *  harness in the bases document (one that takes no skills has none). */
export function rowOf(h: CustomHarness, baseName: string, cards: TraceCard[], capped: boolean,
  binding: PlugBinding | null | undefined = null, base: BaseInfo | null = null, now = Date.now()): SetupRow {
  const day = cards.filter((c) => atMs(c) >= now - DAY_MS);
  const running = cards.some((c) => RUNNING.has(c.status || ''));
  const tested = cards.some((c) => !RUNNING.has(c.status || ''));
  const added = { plugins: setupPlugins(h, binding, 'added'), skills: setupSkills(h, base, 'added'), tools: setupTools(h, base, 'added') };
  const tower = towerOf({
    // a setup with no model of its own runs on its harness's default, which is its model brick then
    harness: baseName, model: h.defaultModel || oobDefaultModel(oobById(h.base)), instructions: !!(h.systemPrompt || '').trim(), tested,
    // one brick per part a person added that is on; built-in skills and tools are never bricks
    parts: {
      skill: countOn(added.skills),
      plugin: countOn(added.plugins),
      mcp: countOn(added.tools),
      env: h.environment ? 1 : 0,
    },
    running,
  });
  const newest = cards.reduce((m, c) => Math.max(m, atMs(c)), 0);
  return {
    h, baseName, tower, day: statsOf(day), dayCapped: capped,
    lastAny: newest || null, running, binding, added,
    tasksKnown: true, readFailed: false,
  };
}

/** What a page of a setup's tasks says, compared between reads: a new task, a turn that started or
 *  ended, a follow-up. */
export function pageSig(page: { sessions: TraceCard[]; cursor: string }): string {
  return (page.cursor ? '+' : '') + page.sessions.map((c) =>
    [c.session_id, c.status, c.finished_at, c.last_response_id].join(':')).join('|');
}

/** The server's row for a setup's base, found by the base's id or by the backend a record made through the API may
 *  carry in its place (`claude` for claude-code). */
function serverBase(h: CustomHarness, bases: Record<string, BaseInfo> | null): BaseInfo | null {
  return bases?.[oobById(h.base)?.id || h.base] || null;
}

/** The agent harness's name as the catalog spells it ("Hermes"); a record made through the API may
 *  carry its id as its label ("hermes"), so the label only stands in when the catalog has no name. */
function nameOfBase(h: CustomHarness, bases: Record<string, BaseInfo> | null): string {
  return serverBase(h, bases)?.label || oobById(h.base)?.name || h.baseLabel || h.base;
}

/** A setup's tasks of the last day read again, from its newest page on: null when that page reads
 *  as it did when it had signature `sig` (nothing started, ended or arrived), so the cards stand. */
export async function dayIfMoved(id: string, since: number, sig: string | null, signal?: AbortSignal): Promise<{ cards: TraceCard[]; capped: boolean; sig: string } | null> {
  const head = await fetchHarnessTasks(id, '', { anyWorkspace: true, signal });
  const s = pageSig(head);
  if (sig !== null && s === sig) return null;
  return { ...(await tasksSince(id, since, head, signal)), sig: s };
}

// ── reads in turn, each with an end ─────────────────────────────────────────────────────────────────
const waitingReads: (() => void)[] = [];
let readsOut = 0;
/** Run a read when fewer than READS_IN_FLIGHT are out (one tab, every page's setups alike). `urgent`
 *  (a turn the watch says ended, a retry) goes ahead of a catch-up's queue. */
function inTurn<T>(run: () => Promise<T>, urgent = false): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const go = () => {
      readsOut += 1;
      Promise.resolve().then(run).then(resolve, reject).finally(() => {
        readsOut -= 1;
        waitingReads.shift()?.();
      });
    };
    if (readsOut < READS_IN_FLIGHT) go();
    else if (urgent) waitingReads.unshift(go);
    else waitingReads.push(go);
  });
}

type DayRead = { ok: true; m: { cards: TraceCard[]; capped: boolean; sig: string } | null } | { ok: false };
/** A setup's tasks of the day (dayIfMoved), in its turn and within READ_TIMEOUT_MS: what it answered,
 *  or `ok: false` (failed, or no answer in time; the console says which, once). */
function readDay(id: string, since: number, sig: string | null, urgent = false): Promise<DayRead> {
  return inTurn(() => withDeadline((signal) => dayIfMoved(id, since, sig, signal), READ_TIMEOUT_MS).catch((e) => {
    if (e instanceof Error && e.name === 'ReadTimeout') console.warn(`Task list read failed: tasks of ${id}: no answer in ${READ_TIMEOUT_MS / 1000} s`);
    throw e;
  }), urgent).then((m): DayRead => ({ ok: true, m }), (): DayRead => ({ ok: false }));
}

// ── what the watch has said that no read shows yet ──────────────────────────────────────────────────
/** A task's start or end as the workspace watch told it. `at`: the card's time (server seconds);
 *  `seenAt`: when this tab heard it (ms), so only a read begun after it can settle it. */
export interface PushMark {
  sid: string; state: 'running' | 'ended'; status: string; at: number; since: number; seenAt: number;
}
/** A mark no read has shown a card for is dropped after this (a task this person's reads never carry). */
const PUSH_HOLD_MS = 5 * 60_000;
/** Reads again after an end the read does not show yet: 1 s, then 2 s. */
const END_RETRIES = 2;

/** A setup's cards as the watch says they stand now: a task whose start was told is running, and one
 *  whose end was told has ended, whatever an older read said. A card made from a frame carries what
 *  the frame says and no more (no title) until a read brings the task's own card. */
export function withPushed(cards: TraceCard[], marks: PushMark[], harness: string): TraceCard[] {
  if (!marks.length) return cards;
  const by = new Map(marks.map((m) => [m.sid, m]));
  const out = cards.map((c) => {
    const m = by.get(c.session_id);
    if (!m) return c;
    const run = RUNNING.has(c.status || '');
    if (m.state === 'running') return run ? c : { ...c, status: 'running' };
    return run ? { ...c, status: m.status, finished_at: m.at } : c;
  });
  const have = new Set(cards.map((c) => c.session_id));
  const add: TraceCard[] = marks.filter((m) => !have.has(m.sid)).sort((a, b) => b.since - a.since).map((m) => ({
    session_id: m.sid, harness_id: harness, status: m.status, finished_at: m.state === 'ended' ? m.at : m.since,
  }));
  return add.length ? [...add, ...out] : out;
}

/** The marks a read begun at `readAt` (ms) leaves standing, given the cards it shows: once the task's
 *  own card agrees with the watch (running, or ended after the start) it speaks for the task. */
export function settleMarks(marks: PushMark[], cards: TraceCard[], readAt: number, now = Date.now()): PushMark[] {
  return marks.filter((m) => {
    if (m.seenAt > readAt) return true;            // the read began before the watch said this
    const c = cards.find((x) => x.session_id === m.sid);
    if (!c) return now - m.seenAt < PUSH_HOLD_MS;
    const run = RUNNING.has(c.status || '');
    if (m.state === 'ended') return run;           // the card does not show the end yet
    return !run && (c.finished_at || 0) < m.at;    // a terminal card older than this start is the last turn's
  });
}

/** What a row is made from, kept so a later read makes it again: the setup's record and what does
 *  not move with its tasks, its cards with their newest page's signature, and when the read that
 *  gave them began (an older read never replaces a newer one). `known`: some read of its tasks has
 *  answered (this one or an earlier one in the tab); `failed`: the latest read did not. */
interface RowSrc {
  h: CustomHarness; baseName: string; base: BaseInfo | null; binding: PlugBinding | null | undefined;
  cards: TraceCard[]; capped: boolean; sig: string | null; at: number; known: boolean; failed: boolean;
}
const REFRESH_SOON_MS = 500;   // a turn's start or end, read a moment after: its card is written by then

/** A read's answer folded into a row: an answer over an older one, a failure only over an older answer
 *  (and it keeps the cards: it only marks the row). */
function withRead(x: RowSrc, r: DayRead, at: number): RowSrc {
  if (at < x.at) return x;
  if (!r.ok) return { ...x, failed: true };
  if (!r.m) return { ...x, at, failed: false };
  return { ...x, cards: r.m.cards, capped: r.m.capped, sig: r.m.sig, at, known: true, failed: false };
}

/** `live`: keep the rows current while the page shows (the workspace watch). `scope`: the current
 *  workspace's id, so a switch watches the new workspace. */
export function useSetups(opts: { live?: boolean; scope?: string } = {}): {
  rows: SetupRow[] | null; error: string; reload: () => void;
  /** read one setup's tasks again now (a turn of it started or ended) */
  refresh: (id: string) => void;
  /** live, and the watch has not been up for a few seconds: the rows may be behind */
  paused: boolean;
  /** read the workspace's tasks again now */
  reconnect: () => void;
} {
  const live = !!opts.live;
  const scope = opts.scope || '';
  const [rows, setRows] = useState<SetupRow[] | null>(null);
  const [error, setError] = useState('');
  const src = useRef<{ list: RowSrc[] } | null>(null);
  const gen = useRef(0);            // a full read makes every read begun before it moot
  const catching = useRef(false);   // one catch-up at a time
  const catchAgain = useRef(false); // one asked for while one ran: it runs once more after
  const loading = useRef(false);
  const upDuringLoad = useRef(false); // the watch came up while a full read ran: catch up after it
  const catchUpRef = useRef<() => Promise<void>>(async () => {});
  const loadRef = useRef<() => Promise<void>>(async () => {});
  const soon = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  const marks = useRef(new Map<string, PushMark[]>());           // per setup, newest first
  const retries = useRef(new Map<string, { n: number; t: ReturnType<typeof setTimeout> | null }>());
  const loadRetry = useRef<{ n: number; t: ReturnType<typeof setTimeout> | null }>({ n: 0, t: null });
  const readOneRef = useRef<(id: string, o?: { force?: boolean; urgent?: boolean }) => Promise<void>>(async () => {});

  // the rows from what was read and what the watch has said since, in the order the last full read
  // gave (a row never jumps under the pointer between reads), with the day's window and every "ago"
  // moved on
  const draw = useCallback(() => {
    const s = src.current;
    if (!s) return;
    const now = Date.now();
    setRows(s.list.map((x) => {
      const pm = marks.current.get(x.h.id);
      const cards = pm?.length ? withPushed(x.cards, pm, x.h.id) : x.cards;
      return { ...rowOf(x.h, x.baseName, cards, x.capped, x.binding, x.base, now), tasksKnown: x.known, readFailed: x.failed };
    }));
  }, []);

  const clearRetries = useCallback(() => {
    retries.current.forEach((r) => { if (r.t) clearTimeout(r.t); });
    retries.current.clear();
  }, []);
  // a setup whose read failed is read again on its own, 2 s, 4 s, ... up to a minute apart (while the
  // page is hidden the timer only waits on)
  const retry = useCallback((id: string) => {
    const r = retries.current.get(id) || { n: 0, t: null };
    retries.current.set(id, r);
    if (r.t) return;
    const ms = Math.min(RETRY_MAX_MS, RETRY_FIRST_MS * 2 ** r.n);
    r.n += 1;
    r.t = setTimeout(() => {
      r.t = null;
      if (document.visibilityState === 'hidden') { r.n -= 1; retry(id); return; }
      void readOneRef.current(id, { urgent: true });
    }, ms);
  }, []);

  // after a read of setup `id` begun at `at` was folded in: what this tab remembers, its retry, and the
  // watch's marks the read now speaks for
  const afterRead = useCallback((id: string, r: DayRead, at: number) => {
    const x = src.current?.list.find((y) => y.h.id === id);
    if (!x) return;
    if (!r.ok) { if (x.failed) retry(id); return; }
    const was = retries.current.get(id);
    if (was) { if (was.t) clearTimeout(was.t); retries.current.delete(id); }
    if (r.m && x.at === at) knownTasks.set(id, { cards: x.cards, capped: x.capped, sig: x.sig || '' });
    const pm = marks.current.get(id);
    if (pm?.length) {
      const left = settleMarks(pm, x.cards, at);
      if (left.length) marks.current.set(id, left); else marks.current.delete(id);
    }
  }, [retry]);

  // fold one setup's read in
  const apply = useCallback((id: string, r: DayRead, at: number) => {
    const s = src.current;
    if (!s) return;
    src.current = { ...s, list: s.list.map((x) => (x.h.id === id ? withRead(x, r, at) : x)) };
    afterRead(id, r, at);
  }, [afterRead]);

  const load = useCallback(async () => {
    const g = ++gen.current;
    loading.current = true;
    clearRetries();
    if (loadRetry.current.t) { clearTimeout(loadRetry.current.t); loadRetry.current.t = null; }
    const began = Date.now();
    let got: [CustomHarness[], Record<string, BaseInfo> | null];
    try {
      got = await Promise.all([withDeadline((signal) => listCustom(signal), LIST_TIMEOUT_MS), loadBases().catch(() => null)]);
    } catch (e) {
      if (g !== gen.current) return;
      loading.current = false;
      // the rows already drawn stay as they were read; with none, the page says it could not read them
      if (!src.current) {
        setError(e instanceof Error && e.name !== 'ReadTimeout' ? e.message : 'No answer in time.');
        setRows([]);
      }
      const L = loadRetry.current;
      const ms = Math.min(RETRY_MAX_MS, RETRY_FIRST_MS * 2 ** L.n);
      L.n += 1;
      L.t = setTimeout(() => { L.t = null; void loadRef.current(); }, ms);
      return;
    }
    if (g !== gen.current) return;
    loadRetry.current.n = 0;
    setError('');
    const [list, bases] = got;
    const since = Date.now() - DAY_MS;
    // each row starts from what this tab already knows of it: the rows drawn now, else an earlier mount
    const prev = new Map((src.current?.list || []).map((x) => [x.h.id, x]));
    const start: RowSrc[] = list.map((h) => {
      const was = prev.get(h.id), k = knownTasks.get(h.id);
      return {
        h, baseName: nameOfBase(h, bases), base: serverBase(h, bases),
        binding: was ? was.binding : hasPlugsEntry(h) ? undefined : null,
        cards: was?.cards ?? k?.cards ?? [], capped: was?.capped ?? k?.capped ?? false, sig: was?.sig ?? k?.sig ?? null,
        at: 0, known: !!(was?.known || k), failed: false,
      };
    });
    // every setup's day of tasks, READS_IN_FLIGHT at a time; the rows draw when all have answered or
    // after FIRST_DRAW_MS, and a read that lands after that fills its row in place
    let drawn = false;
    const early = new Map<string, { r: DayRead; binding: PlugBinding | null | undefined }>();
    const jobs = start.map((x) => Promise.all([
      readDay(x.h.id, since, null),
      hasPlugsEntry(x.h) ? withDeadline(() => plugsOf(x.h), READ_TIMEOUT_MS).catch(() => undefined) : Promise.resolve(null),
    ]).then(([r, binding]) => {
      if (g !== gen.current) return;
      if (!drawn) { early.set(x.h.id, { r, binding }); return; }
      const s = src.current;
      if (s) src.current = { ...s, list: s.list.map((y) => (y.h.id === x.h.id ? { ...y, binding } : y)) };
      apply(x.h.id, r, began);
      draw();
    }));
    const all = Promise.all(jobs);
    let firstDraw: ReturnType<typeof setTimeout> | undefined;
    await Promise.race([all, new Promise<void>((r) => { firstDraw = setTimeout(r, FIRST_DRAW_MS); })]);
    clearTimeout(firstDraw);
    if (g !== gen.current) return;
    const out = start.map((x) => { const e = early.get(x.h.id); return e ? withRead({ ...x, binding: e.binding }, e.r, began) : x; });
    const newest = (x: RowSrc) => x.cards.reduce((m, c) => Math.max(m, atMs(c)), 0) || x.h.createdAt || 0;
    out.sort((a, b) => newest(b) - newest(a));
    src.current = { list: out };
    drawn = true;
    early.forEach((e, id) => afterRead(id, e.r, began));
    draw();
    await all;
    if (g !== gen.current) return;
    loading.current = false;
    // the watch came up while this read ran: what it read may predate the watch, so read once more
    if (upDuringLoad.current) { upDuringLoad.current = false; void catchUpRef.current(); }
  }, [draw, apply, afterRead, clearRetries]);
  useEffect(() => { loadRef.current = load; }, [load]);

  // the catch-up when the watch comes up: every setup's newest page again, each folded in as it lands;
  // only a setup whose page moved is read further. A full read under way reads everything already.
  const catchUp = useCallback(async () => {
    const s = src.current;
    if (!s || loading.current) return;
    if (catching.current) { catchAgain.current = true; return; }
    catching.current = true;
    const g = gen.current, at = Date.now(), since = at - DAY_MS;
    try {
      await Promise.all(s.list.map((x) => readDay(x.h.id, since, x.known ? x.sig : null).then((r) => {
        if (g !== gen.current) return;
        apply(x.h.id, r, at);
        draw();
      })));
    } finally {
      catching.current = false;
      if (catchAgain.current) { catchAgain.current = false; void catchUpRef.current(); }
    }
  }, [draw, apply]);
  useEffect(() => { catchUpRef.current = catchUp; }, [catchUp]);

  // one setup's tasks read now: `force` reads the day again even when its newest page reads the same
  const readOne = useCallback(async (id: string, o: { force?: boolean; urgent?: boolean } = {}) => {
    const x = src.current?.list.find((y) => y.h.id === id);
    if (!x) return;
    const g = gen.current, at = Date.now();
    const r = await readDay(id, at - DAY_MS, o.force || !x.known ? null : x.sig, o.urgent);
    if (g !== gen.current) return;
    apply(id, r, at);
    draw();
  }, [apply, draw]);
  useEffect(() => { readOneRef.current = readOne; }, [readOne]);

  // a turn of setup `id` started or ended: read it a moment after, and again shortly while an end the
  // watch told of is not on its card yet
  const refreshAt = useCallback((id: string, attempt: number) => {
    if (!src.current?.list.some((x) => x.h.id === id)) return;
    const was = soon.current.get(id);
    if (was) clearTimeout(was);
    soon.current.set(id, setTimeout(() => {
      soon.current.delete(id);
      void readOneRef.current(id, { force: true, urgent: true }).then(() => {
        if (attempt < END_RETRIES && (marks.current.get(id) || []).some((m) => m.state === 'ended')) refreshAt(id, attempt + 1);
      });
    }, attempt ? 1000 * 2 ** (attempt - 1) : REFRESH_SOON_MS));
  }, []);
  const refresh = useCallback((id: string) => refreshAt(id, 0), [refreshAt]);

  // a frame of the watch, applied to its setup's row at once: a start marks the task running, an end
  // marks it ended and reads the setup again (its numbers, its card)
  const onFrame = useCallback((f: FeedFrame) => {
    const id = f.harness_id;
    // a frame during the first load is kept for its row; one for a setup not on the page is dropped
    if (!id || !f.session_id || (src.current && !src.current.list.some((x) => x.h.id === id))) return;
    const start = f.type === 'harness.turn.started';
    if (!start && !f.status) return;
    const at = f.at || Date.now() / 1000;
    const list = marks.current.get(id) || [];
    const prior = list.find((m) => m.sid === f.session_id);
    const m: PushMark = { sid: f.session_id, state: start ? 'running' : 'ended', status: start ? 'running' : f.status, at,
      since: start ? at : prior?.since ?? at, seenAt: Date.now() };
    marks.current.set(id, [m, ...list.filter((x) => x.sid !== f.session_id)]);
    draw();
    if (!start) refresh(id);
  }, [draw, refresh]);

  // read again when something else learns they changed (a setup made or deleted elsewhere in the tab)
  useEffect(() => {
    void load();
    const again = () => { void load(); };
    window.addEventListener(SETUPS_EVENT, again);
    const timers = soon.current;
    const L = loadRetry.current;
    return () => {
      gen.current += 1;               // reads still out land in no row
      window.removeEventListener(SETUPS_EVENT, again);
      timers.forEach((t) => clearTimeout(t));
      timers.clear();
      clearRetries();
      if (L.t) { clearTimeout(L.t); L.t = null; }
    };
  }, [load, clearRetries]);

  // live, while the page is visible: the workspace watch, each frame applied to its setup's row, and
  // one catch-up read each time the watch comes up; a full read when the page was hidden past
  // BACK_FULL_MS (a setup may have been made meanwhile), and after a full read under way when the
  // watch came up during it
  const { paused, reconnect } = useWorkspaceFeed({
    on: live, scope, onFrame,
    onUp: (away) => {
      if (away > BACK_FULL_MS) void loadRef.current();
      else if (loading.current) upDuringLoad.current = true;
      else void catchUpRef.current();
    },
  });

  return { rows, error, reload: load, refresh, paused, reconnect };
}

export function ago(ts: number): string {
  const d = (Date.now() - ts) / 1000;
  if (d < 45) return 'just now';
  if (d < 3600) return Math.round(d / 60) + ' min ago';
  if (d < 86400) return Math.round(d / 3600) + ' h ago';
  return Math.round(d / 86400) + ' d ago';
}

/** One setup, by id, with the same reading as Studio's rows; `reload` reads it again. `missing` only
 *  when the server says the setup is not in this workspace (or does not exist); `failed` when it could
 *  not be read after a few tries (a console restart, a slow gateway), which the page says as such. */
export function useSetup(id: string): { row: SetupRow | null; cards: TraceCard[]; missing: boolean; failed: boolean; reload: () => void } {
  // a setup this tab has just made opens with its record already here (start/seed.ts): no loading
  // lines between the page it was made on and this one; the server's read follows behind it
  const [row, setRow] = useState<SetupRow | null>(() => {
    const s = seededSetup(id);
    return s ? rowOf(s.h, nameOfBase(s.h, null), [], false) : null;
  });
  const [cards, setCards] = useState<TraceCard[]>([]);
  const [missing, setMissing] = useState(false);
  const [failed, setFailed] = useState(false);
  // a task read that failed is tried again on its own, 2 s, 4 s, ... up to a minute apart
  const again = useRef<{ n: number; t: ReturnType<typeof setTimeout> | null }>({ n: 0, t: null });
  const loadRef = useRef<() => Promise<void>>(async () => {});
  useEffect(() => () => { if (again.current.t) clearTimeout(again.current.t); }, [id]);
  const load = useCallback(async () => {
    if (again.current.t) { clearTimeout(again.current.t); again.current.t = null; }
    const side = loadBases().catch(() => null);
    let h: CustomHarness | null = null;
    for (let i = 0; ; i++) {
      try { h = await readCustom(id); break; }
      catch { if (i >= 2) { setFailed(true); return; } await new Promise((r) => setTimeout(r, 800 * 2 ** i)); }
    }
    // a setup this tab has just made is not missing while the server catches up with its create
    for (let n = 0; !h && n < 4 && madeHere(id); n++) {
      await new Promise((r) => setTimeout(r, 1000 * (n + 1)));
      h = await readCustom(id).catch(() => null);
    }
    setFailed(false);
    const bases = await side;
    if (!h) { setMissing(true); return; }
    setMissing(false);
    const [day, plugs] = await Promise.all([readDay(id, Date.now() - DAY_MS, null, true), plugsOf(h)]);
    const baseName = nameOfBase(h, bases);
    if (day.ok && day.m) {
      again.current.n = 0;
      knownTasks.set(id, { cards: day.m.cards, capped: day.m.capped, sig: day.m.sig });
      setCards(day.m.cards);
      setRow(rowOf(h, baseName, day.m.cards, day.m.capped, plugs, serverBase(h, bases)));
      return;
    }
    // the read failed: the last one that answered in this tab stands (none: nothing is claimed), and
    // the setup is read again shortly
    const k = knownTasks.get(id);
    if (k) setCards(k.cards);
    setRow({ ...rowOf(h, baseName, k?.cards || [], k?.capped || false, plugs, serverBase(h, bases)), tasksKnown: !!k, readFailed: true });
    const A = again.current;
    const ms = Math.min(RETRY_MAX_MS, RETRY_FIRST_MS * 2 ** A.n);
    A.n += 1;
    A.t = setTimeout(() => { A.t = null; void loadRef.current(); }, ms);
  }, [id]);
  useEffect(() => { loadRef.current = load; }, [load]);
  useEffect(() => { void load(); }, [load]);
  return { row, cards, missing, failed, reload: load };
}
