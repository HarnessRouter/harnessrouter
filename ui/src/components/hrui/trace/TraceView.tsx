'use client';
// A task's trace, laid out as the console's earlier trace viewer laid it out (studio/traces/
// TracesMain: a compact line of figures, a thin timeline, then one line per event, its detail on
// click), drawn in the redesign's own classes (badges, event rows, the detail panel). Richard,
// 2026-10-18: the cost card took the room; the events come first.
//
// One view for every trace: a setup's Tasks › Trace and a kit page's Trace panel. Events are grouped
// by turn, and each event's time is counted from its own turn's start (h:mm:ss), so a task that runs
// over days never reads "43455.7 s". On a wide trace the detail sits beside the events; on a narrow
// one (a kit's side panel, a phone) it covers the trace panel, with Close at its top right and
// Escape. Nothing here is estimated: rows, times and tokens are the recorded trace's own.
//
// A setup's trace (useTrace) is read when it opens, again when the task starts or stops running (its
// card says so), and while it runs on push: each event of the task the setup's own feed carries (lib/
// chat subscribeHarnessEvents, at most a read a second; its end among them), and each time that feed
// connects again. A read that fails says so: the trace could not be read, or, with rows already shown,
// that they could not be refreshed; each with Try again.
import { createContext, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { tracesApi } from '@/studio/traces/api';
import { flatten } from '@/studio/traces/flatten';
import { subscribeHarnessEvents } from '@/lib/chat';
import { Md, prettyJson } from '../setup/TaskThread';
import { clock, idle, ktok, preview, sec } from '../setup/fmt';
import { Skel, SkLine, SkRows } from '../Skel';
import './trace.css';

export interface TTool { name: string; input: Record<string, unknown>; result?: string; is_error?: boolean; id?: string }
export interface TRow {
  i: number; kind: string; label: string; text?: string; param?: string; tools?: TTool[]; is_error?: boolean;
  tokens?: { in?: number; out?: number } | null; ts?: number; sub?: string | null; clipped?: boolean; limited?: boolean;
  md?: boolean; dur?: number | null;
}
export type DKind = 'user' | 'agent' | 'step' | 'tool' | 'done' | 'error';
export const ROLE: Record<DKind, string> = { user: 'User', agent: 'Agent', step: 'Thinking', tool: 'Tool', done: 'Result', error: 'Error' };

export function dkind(r: TRow): DKind {
  if (r.kind === 'user') return 'user';
  if (r.kind === 'thinking') return 'step';
  if (r.kind === 'tool') return 'tool';
  if (r.kind === 'result') return r.is_error ? 'error' : 'done';
  return 'agent';
}
const rowName = (r: TRow, k: DKind) => (k === 'user' || k === 'agent' ? 'Message' : k === 'step' ? 'Thinking'
  : k === 'tool' ? r.label : k === 'done' ? 'Completed' : 'Failed');

/** Rows grouped by turn: a turn opens with the person's message, or after the last turn's result. */
export function turnsOf<T extends TRow>(rows: T[]): T[][] {
  const out: T[][] = [];
  let cur: T[] = [];
  for (const r of rows) {
    const last = cur[cur.length - 1];
    const opens = !r.sub && last && ((r.kind === 'user' && last.kind !== 'user') || last.kind === 'result');
    if (opens) { out.push(cur); cur = []; }
    cur.push(r);
  }
  if (cur.length) out.push(cur);
  return out;
}
const tsOf = (r: TRow | undefined) => (r && typeof r.ts === 'number' ? r.ts : null);
/** A turn's own first and last event times (s), when the events carry them. */
export function turnSpan(t: TRow[]): { t0: number | null; t1: number | null } {
  const xs = t.map(tsOf).filter((x): x is number => x != null);
  return { t0: xs.length ? Math.min(...xs) : null, t1: xs.length ? Math.max(...xs) : null };
}
/** What a turn read and wrote: its result's figures, the turn's own total. */
function turnTokens(t: TRow[]): { tin: number; tout: number } | null {
  for (let i = t.length - 1; i >= 0; i--) {
    const k = t[i].tokens;
    if (t[i].kind === 'result' && k && (k.in != null || k.out != null)) return { tin: k.in || 0, tout: k.out || 0 };
  }
  return null;
}
/** When a turn started, as a clock: today "9:41 PM", earlier "Oct 17, 9:41 PM". */
function startedAt(s: number): string {
  const d = new Date(s * 1000), today = new Date().toDateString() === d.toDateString();
  return d.toLocaleString('en-US', today ? { hour: 'numeric', minute: '2-digit' } : { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}
/** The totals the head line names. */
export function traceTotals(rows: TRow[] | null): { events: number; tin: number; tout: number } {
  const ts = turnsOf(rows || []).map(turnTokens);
  return { events: (rows || []).length, tin: ts.reduce((a, t) => a + (t ? t.tin : 0), 0), tout: ts.reduce((a, t) => a + (t ? t.tout : 0), 0) };
}

/** At most one read of a running trace a second, however many events arrive. */
export const TRACE_READ_GAP_MS = 1000;
/** Each open trace's read, by task: its view's Try again reads it now. */
const traceReads = new Map<string, () => void>();

/** A task's recorded trace: read when it opens and whenever it starts or stops running, then on push
 *  (see the head of this file). `failed`: the last read failed (with rows, they are as last read);
 *  `retry` reads it again now. */
export function useTrace(sid: string, live: boolean): { rows: TRow[] | null; failed: boolean; retry: () => void } {
  const [rows, setRows] = useState<TRow[] | null>(null);
  const [failed, setFailed] = useState(false);
  // the setup the task is of, as its manifest says: whose feed carries its events
  const [harness, setHarness] = useState('');
  const ask = useRef<{ soon: () => void; now: () => void }>({ soon: () => undefined, now: () => undefined });
  useEffect(() => {
    let alive = true, busy = false, again = false, last = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async (): Promise<void> => {
      if (busy) { again = true; return; }
      busy = true; last = Date.now();
      try {
        const m = await tracesApi.manifest(sid).catch(() => null);
        const evs = await tracesApi.events(sid, (m && m.chunks) || []);
        if (!alive) return;
        if (m && typeof m.harness_id === 'string' && m.harness_id) setHarness(m.harness_id);
        setRows(flatten(evs) as TRow[]); setFailed(false);
      } catch { if (alive) setFailed(true); }
      finally { busy = false; }
      if (alive && again) { again = false; soon(); }
    };
    // a read asked for while one is out follows it; reads come at most TRACE_READ_GAP_MS apart
    const soon = () => {
      if (!alive || timer) return;
      if (busy) { again = true; return; }
      timer = setTimeout(() => { timer = undefined; void load(); }, Math.max(0, last + TRACE_READ_GAP_MS - Date.now()));
    };
    const now = () => { if (timer) { clearTimeout(timer); timer = undefined; } void load(); };
    ask.current = { soon, now };
    traceReads.set(sid, now);
    void load();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
      if (traceReads.get(sid) === now) traceReads.delete(sid);
    };
  }, [sid, live]);
  // while it runs: each of its events on the setup's own feed (never a replay of what was read), and
  // once each time that feed connects again (what happened while it was down went to no one)
  useEffect(() => {
    if (!live || !harness) return undefined;
    let ups = 0;
    return subscribeHarnessEvents(harness, (m) => { if (m.session_id === sid && !m.replay) ask.current.soon(); },
      (st) => { if (st === 'up' && ups++ > 0) ask.current.soon(); });
  }, [sid, live, harness]);
  const retry = useRef(() => ask.current.now()).current;
  return { rows, failed, retry };
}

const X = <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>;
const IDLE_GAP = 20;        // seconds: a longer gap is drawn as a short idle mark on the timeline
// px: a trace narrower than this shows a step's detail over itself (or its host); beside the events,
// the detail takes up to 420 px and leaves them at least 400
const NARROW = 820;

/** Where a narrow trace's step detail opens when the trace names no overlayHost: a setup's page puts
 *  it in its right column, over the Agent stack or a file's preview (studio/[id], .tk-trv-host). */
export const TraceDetailHost = createContext<HTMLElement | null>(null);

/** The thin timeline (the earlier viewer's strip): one mark per event in its kind's colour, a tool's
 *  as wide as it ran; gaps over 20 s are drawn short, so a task that waited hours stays readable. */
function Strip({ rows, onJump }: { rows: TRow[]; onJump: (i: number) => void }) {
  const marks = useMemo(() => {
    let at = 0, prev: number | null = null;
    const out: { r: TRow; at: number; w: number; gap: boolean }[] = [];
    for (const r of rows) {
      const t = tsOf(r);
      let gap = false;
      if (t != null && prev != null) { const g = t - prev; gap = g > IDLE_GAP; at += Math.min(Math.max(0, g), IDLE_GAP); }
      if (t != null) prev = t;
      out.push({ r, at, w: r.kind === 'tool' && r.dur ? Math.min(r.dur, IDLE_GAP) : 0, gap });
    }
    return out;
  }, [rows]);
  const span = Math.max(1, ...marks.map((m) => m.at + m.w));
  if (!rows.length) return null;
  return (
    <div className="trv-strip" aria-hidden="true">
      {marks.map(({ r, at, w, gap }) => (
        <span key={r.i}>
          {gap ? <i className="trv-gap" style={{ left: `${Math.max(0, (at - IDLE_GAP) / span * 100)}%`, width: `${IDLE_GAP / span * 100}%` }} /> : null}
          <i className={`trv-seg s-${dkind(r)}`} style={{ left: `${at / span * 100}%`, width: `max(3px, ${w / span * 100}%)` }} onClick={() => onJump(r.i)} />
        </span>
      ))}
    </div>
  );
}

/** One step's whole content (the same view wide or narrow). */
function Detail({ r, turn, at, full, loadingFull, fullFailed, onFullRetry, onClose, closeRef }: {
  r: TRow; turn: number; at: number; full: TRow | null; loadingFull: boolean;
  /** the whole content could not be read: the clipped words show, said to be clipped */
  fullFailed: boolean; onFullRetry: () => void;
  onClose: () => void; closeRef: React.RefObject<HTMLButtonElement | null>;
}) {
  const x = full || r, k = dkind(r);
  const tok = x.tokens && (x.tokens.in != null || x.tokens.out != null) ? x.tokens : null;
  const sub = [`Turn ${turn}`, clock(at), x.dur != null ? sec(x.dur * 1000) : ''].filter(Boolean).join(' · ');
  return (
    <div className="trv-detail" role="dialog" aria-label={`${ROLE[k]}: ${rowName(x, k)}`}>
      <div className="dr-top"><span className={`badge b-${k}`}>{ROLE[k]}</span><b>{rowName(x, k)}</b>
        <button ref={closeRef} type="button" className="icon-btn" aria-label="Close" onClick={onClose}>{X}</button>
      </div>
      <div className="dr-sub mono">{sub}</div>
      {loadingFull ? <Skel label="Reading the full content"><SkLine w="90%" h={11} /><SkLine w="70%" h={11} style={{ marginTop: 8 }} /></Skel> : null}
      {fullFailed ? (
        <p className="fine" role="alert">The rest of this step could not be read.{' '}
          <button type="button" className="link-q inl" onClick={onFullRetry}>Try again</button></p>
      ) : null}
      {k === 'user' ? <><div className="dr-h">Input</div><div className="prose dr-p"><Md text={x.text || ''} /></div></> : null}
      {k === 'agent' ? <><div className="dr-h">Content</div><div className="prose dr-p"><Md text={x.text || ''} /></div></> : null}
      {k === 'step' ? <><div className="dr-h">Content</div><p className="dr-p trv-think">{x.text}</p></> : null}
      {k === 'done' || k === 'error' ? <><div className="dr-h">{k === 'error' ? 'Error' : 'Result'}</div><div className="prose dr-p"><Md text={x.text || ''} /></div></> : null}
      {k === 'tool' ? (x.tools || []).map((t, j) => {
        const res = t.result != null ? String(t.result) : null;
        const clip = res && res.length > 20000 ? res.slice(0, 20000) + '…' : res;
        return (
          <div key={j}>
            {(x.tools || []).length > 1 ? <div className="trv-tsep">{t.name}</div> : null}
            <div className="dr-h">Tool use</div>
            <pre className="json">{JSON.stringify(t.input || {}, null, 2)}</pre>
            {clip != null ? <><div className="dr-h">Tool result</div><pre className={`json${t.is_error ? ' trv-err' : ''}`}>{prettyJson(clip) ?? clip}</pre></> : null}
          </div>
        );
      }) : null}
      {k !== 'user' && tok ? (
        <><div className="dr-h">Tokens</div>
          <dl className="cost">
            {tok.in != null ? <div><dt>Input</dt><dd>{tok.in.toLocaleString('en-US')}</dd></div> : null}
            {tok.out != null ? <div><dt>Output</dt><dd>{tok.out.toLocaleString('en-US')}</dd></div> : null}
          </dl></>
      ) : null}
    </div>
  );
}

export function TraceView({ sid, rows, failed, onRetry, running, head, foot, openError, overlayHost, enterFrom, empty, whole }: {
  sid: string;
  rows: TRow[] | null;
  /** the last read failed: with no rows the trace could not be read, with rows they are as last read */
  failed: boolean;
  /** read the trace again (a setup's trace, useTrace, needs none: its read is found by `sid`) */
  onRetry?: () => void;
  running: boolean;
  /** the head line's figures the caller adds (cost, the key it ran on) */
  head?: ReactNode;
  /** under the events: a note */
  foot?: ReactNode;
  /** select the last error once the events are in */
  openError?: boolean;
  /** a narrow trace's detail covers this element (the panel the trace sits in); else the window */
  overlayHost?: HTMLElement | null;
  /** rows from this index slide in (new since the last read) */
  enterFrom?: number;
  /** what an empty trace says */
  empty?: ReactNode;
  /** the rows are all there is (a recorded trace): an event's whole content is never read again */
  whole?: boolean;
}) {
  const root = useRef<HTMLDivElement | null>(null);
  const pageHost = useContext(TraceDetailHost);
  const host = overlayHost ?? pageHost;
  const [narrow, setNarrow] = useState(false);
  useLayoutEffect(() => {
    const el = root.current;
    if (!el) return;
    const fit = () => setNarrow(el.getBoundingClientRect().width < NARROW);
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const [sel, setSel] = useState<number | null>(null);
  const [full, setFull] = useState<TRow[] | null>(null);
  const [loadingFull, setLoadingFull] = useState(false);
  // the whole content's last read failed; a Try again (or another step opened) reads it again
  const [fullFailed, setFullFailed] = useState(false);
  const [fullTry, setFullTry] = useState(0);
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const wantErr = useRef(!!openError);
  const turns = useMemo(() => turnsOf(rows || []), [rows]);
  const where = useMemo(() => {
    const m = new Map<number, { turn: number; at: number }>();
    turns.forEach((t, ti) => { const { t0 } = turnSpan(t); t.forEach((r) => m.set(r.i, { turn: ti + 1, at: t0 != null && r.ts != null ? (r.ts - t0) * 1000 : 0 })); });
    return m;
  }, [turns]);
  useEffect(() => {
    if (!wantErr.current || !rows) return;
    wantErr.current = false;
    for (let i = rows.length - 1; i >= 0; i--) if (dkind(rows[i]) === 'error') { setSel(rows[i].i); break; }
  }, [rows]);
  // another task's trace starts with nothing open
  const sidNow = useRef(sid);
  sidNow.current = sid;
  useEffect(() => { setSel(null); setFull(null); setLoadingFull(false); setFullFailed(false); }, [sid]);
  const selRow = sel != null && rows ? rows.find((r) => r.i === sel) || null : null;
  const selClipped = !!selRow?.clipped;
  const covered = sel != null && !!full && !!full[sel];
  // A clipped event's whole content is read when it is opened and the last full read does not hold
  // it (the first one opened, or a running task's newer event). The read answers this task's trace
  // whatever renders meanwhile: its own loading flag or a running task's re-read of the rows never
  // drops it, so the loading line above the content always ends. A failed read keeps the clipped
  // words and says the rest could not be read, with Try again; it is asked again when an event is
  // opened again too.
  useEffect(() => {
    if (sel == null || !selClipped || covered || whole) return;
    const forSid = sid;
    setLoadingFull(true); setFullFailed(false);
    tracesApi.fullEvents(forSid).then((evs: unknown[]) => { if (sidNow.current === forSid) setFull(flatten(evs) as TRow[]); })
      .catch(() => { if (sidNow.current === forSid) setFullFailed(true); })
      .finally(() => { if (sidNow.current === forSid) setLoadingFull(false); });
  }, [sel, selClipped, covered, sid, whole, fullTry]);
  useEffect(() => { if (sel != null) requestAnimationFrame(() => closeRef.current?.focus()); }, [sel]);
  const close = () => {
    const was = sel;
    setSel(null);
    if (was != null) requestAnimationFrame(() => root.current?.querySelector<HTMLElement>(`[data-ev="${was}"]`)?.focus());
  };
  const closeNow = useRef(close);
  closeNow.current = close;
  useEffect(() => {
    if (sel == null) return;
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape' && !document.querySelector('#hrui .scrim')) { e.stopPropagation(); closeNow.current(); } };
    document.addEventListener('keydown', key);
    return () => document.removeEventListener('keydown', key);
  }, [sel]);
  const jump = (i: number) => root.current?.querySelector<HTMLElement>(`[data-ev="${i}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });

  const tot = traceTotals(rows);
  const tok = turns.map(turnTokens);
  // Try again after a failed read: the caller's, else the setup's own read of this trace (useTrace)
  const again = onRetry || (failed && traceReads.has(sid) ? () => traceReads.get(sid)?.() : null);
  const retry = again ? <button type="button" className="link-q inl" onClick={again}>Try again</button> : null;
  let prevIn = 0;
  const detail = selRow ? (
    <Detail r={selRow} turn={where.get(selRow.i)?.turn || 1} at={where.get(selRow.i)?.at || 0} onClose={close} closeRef={closeRef}
      full={selRow.clipped && full ? full[selRow.i] || null : null} loadingFull={selClipped && !covered && loadingFull}
      fullFailed={selClipped && !covered && !loadingFull && fullFailed} onFullRetry={() => setFullTry((n) => n + 1)} />
  ) : null;
  // narrow: the detail covers the panel the trace sits in; the window when there is none, or when the
  // panel runs taller than the window (a phone, where the page scrolls as one and the panel's top may
  // be above the screen)
  const hostFits = !!host && host.getBoundingClientRect().height <= window.innerHeight + 1;
  const over = detail && narrow ? (host && hostFits ? createPortal(<div className="trv-over">{detail}</div>, host)
    : createPortal(<div className="trv-over trv-over-fixed">{detail}</div>, document.getElementById('hrui') || document.body)) : null;

  return (
    <div ref={root} className={`trv${detail && !narrow ? ' with-detail' : ''}`}>
      <div className="trv-main">
        <div className="trv-head">
          {rows ? <span className="chip">{tot.events} event{tot.events === 1 ? '' : 's'}</span> : null}
          {tot.tin || tot.tout ? <span className="chip mono">in {ktok(tot.tin)} · out {ktok(tot.tout)}</span> : null}
          {head}
        </div>
        {rows && failed ? <p className="fine" role="status">Could not refresh the trace.{retry ? <>{' '}{retry}</> : null}</p> : null}
        {rows && rows.length ? <Strip rows={rows} onJump={jump} /> : null}
        {!rows ? (failed ? <p className="fine" role="alert">The trace could not be read.{retry ? <>{' '}{retry}</> : null}</p> : <Skel label="Loading the trace"><SkRows n={6} lead={false} cols={1} /></Skel>) : null}
        {rows && !rows.length && !running ? (empty || <p className="fine">No events recorded.</p>) : null}
        {turns.map((t, ti) => {
          const { t0, t1 } = turnSpan(t);
          const prevEnd = ti > 0 ? turnSpan(turns[ti - 1]).t1 : null;
          const tt = tok[ti];
          const grew = ti > 0 && prevIn > 0 && !!tt && tt.tin > prevIn * 1.3;
          const from = prevIn;
          if (tt) prevIn = tt.tin;
          return (
            <div key={ti} className="trv-turn">
              {ti > 0 && t0 != null && prevEnd != null ? <div className="idle trv-idle">Idle · {idle(Math.max(0, t0 - prevEnd) * 1000)}</div> : null}
              {turns.length > 1 ? (
                <div className="turn-h">Turn {ti + 1}{t0 != null ? ` · ${startedAt(t0)}` : ''}{t0 != null && t1 != null ? ` · ${sec((t1 - t0) * 1000)}` : ''}{tt ? ` · in ${ktok(tt.tin)} · out ${ktok(tt.tout)}` : ''}</div>
              ) : null}
              {turns.length > 1 && grew && tt ? (
                <div className="ctx-hint">This turn sent the earlier conversation again: input grew from {ktok(from)} to {ktok(tt.tin)} tokens. Start a new task for unrelated work.</div>
              ) : null}
              <ol className="ev-list trv-list">
                {t.map((r) => {
                  const k = dkind(r), w = where.get(r.i);
                  const text = r.limited ? null
                    : k === 'tool' ? <><b>{r.label}</b> <span className="muted mono">{preview(r.param || '')}</span></>
                      : k === 'step' || k === 'done' || k === 'error' ? <><b>{rowName(r, k)}</b> <span className="muted">{preview(r.text || '')}</span></>
                        : preview(r.text || '');
                  const stats = [
                    r.tokens && (r.tokens.in != null || r.tokens.out != null) ? `${ktok(r.tokens.in || 0)} / ${ktok(r.tokens.out || 0)}` : '',
                    r.dur != null && r.kind === 'tool' ? sec(r.dur * 1000) : '',
                  ].filter(Boolean).join(' · ');
                  const inner = <><span className={`badge b-${k}`}>{ROLE[k]}</span><span className="ev-text">{text}</span><span className="trv-stat">{stats}</span><span className="ev-t">{clock(w ? w.at : 0)}</span></>;
                  const cls = `ev-row trv-r k-${k}${r.sub ? ' trv-sub' : ''}${enterFrom != null && r.i >= enterFrom ? ' trv-in' : ''}`;
                  return (
                    <li key={r.i}>
                      {r.limited ? <div className={cls}>{inner}</div> : (
                        <button type="button" className={cls + (sel === r.i ? ' on' : '')} data-ev={r.i}
                          aria-expanded={sel === r.i} onClick={() => setSel(sel === r.i ? null : r.i)}>{inner}</button>
                      )}
                    </li>
                  );
                })}
              </ol>
            </div>
          );
        })}
        {running ? <div className="trv-wait"><span className="dot run" />Working</div> : null}
        {foot}
      </div>
      {detail && !narrow ? <aside className="trv-side">{detail}</aside> : null}
      {over}
    </div>
  );
}
