'use client';
// The task's browser in the redesigned task view (Richard 10-19: "Use Browser should open the
// browser's preview the way a file opens, the way we had it before"). It is the old console's live
// card as it is (BrowserPane: the stream, Take over and Hand back, full screen, the agent's glow and
// ghost cursor, the empty state) over the same store and routes (lib/conversation's browser state,
// fed by the feed's browser.opened/call/held/control/closed; GET /v1/sessions/{sid}/browser and
// POST .../browser/control), placed where a file's preview opens: docked beside the conversation from
// 1280 px with the preview's handle (PreviewGrip, the page's --pv-w), the preview's drawer from the
// right under that, a sheet from the bottom of a phone.
//
// What opens it: a browser step in the conversation (AgentTurns' TurnSteps), the Browser control in
// the task's bar (whenever the setup includes the browser plugin), and a browser opening during a run,
// which pops the card on its own unless it was closed for that very browser. A file opened later takes
// the place; the browser comes back from its step or from the bar. When the browser closes the card
// closes (Richard's rule); a past step opened after that shows what it recorded (its screenshot, else
// its own input and result), never a stream that has stopped.
//
// The live URL is a credential: BrowserPane reads it through the session's own route and keeps it in
// its own state. Nothing here logs it, puts it in the address bar or prints it.
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { browserActOf, browserElements, describeTool, parseToolArgs, toolKind, toolLine, type ToolDescription, type ToolItem } from 'reifyui/agent-chat';
import { BrowserPane, fetchBrowser } from '@/components/BrowserPane';
import { authHeaders } from '@/lib/chat';
import { harnessFetch } from '@/lib/hfetch';
import { getPaneState, seedBrowserState, setPaneState, useConvState, usePaneState, type BrowserState, type Msg, type PaneState } from '@/lib/conversation';
import { pairTurns, viewTurn } from './AgentTurns';
import './browser-slot.css';

/** One browser step of the conversation: what the card shows for it once its browser has closed. */
export interface BrowserStep {
  /** the turn it ran in (as pairTurns counts) and its call's id in that turn */
  turn: number; id: string;
  name: string; args: string; output?: string; status: string;
  /** what it did, in words ("Clicked the “About” link") */
  label: string;
}

export function stepOf(turn: number, item: ToolItem, d: ToolDescription): BrowserStep {
  return { turn, id: item.id, name: item.name, args: item.args, output: item.output, status: item.status,
    label: toolLine(d, item.status === 'running' ? 'running' : 'done') };
}

/** Every browser step of a conversation, oldest first. */
export function browserStepsOf(msgs: Msg[]): BrowserStep[] {
  const out: BrowserStep[] = [];
  for (const { asst, turn } of pairTurns(msgs)) {
    if (!asst) continue;
    const items = viewTurn(asst, null).items;
    const el = browserElements(items);
    for (const it of items) {
      if (it.kind !== 'tool' || toolKind(it.name) !== 'browser') continue;
      out.push(stepOf(turn, it, describeTool(it.name, it.args, { element: el[it.id] })));
    }
  }
  return out;
}

// the browser plug answers a screenshot with where it kept the picture, a path under this task's own
// harness and session ("Kept with the task's files as /v1/harnesses/…/media/med_…")
const MEDIA = /\/v1\/harnesses\/([^/\s]+)\/servers\/[^/\s]+\/sessions\/([^/\s]+)\/media\/(med_[A-Za-z0-9]+)/g;
const IMAGE_MIME = /^image\/(png|jpe?g|webp|gif)$/;

/** An image block the record kept whole (an MCP result's {type: image, data, mimeType}), as a data URI. */
function imageIn(out: string): string | null {
  const x = out.trim();
  if (!/^[[{]/.test(x)) return null;
  let v: unknown;
  try { v = JSON.parse(x); } catch { return null; }
  const find = (n: unknown, depth: number): string | null => {
    if (!n || typeof n !== 'object' || depth > 3) return null;
    if (Array.isArray(n)) { for (const e of n) { const r = find(e, depth + 1); if (r) return r; } return null; }
    const o = n as Record<string, unknown>;
    const mime = String(o.mimeType || o.mime_type || o.media_type || '');
    if (o.type === 'image' && typeof o.data === 'string' && IMAGE_MIME.test(mime) && /^[A-Za-z0-9+/=\s]+$/.test(o.data)) return `data:${mime};base64,${o.data.replace(/\s+/g, '')}`;
    for (const k of ['content', 'output', 'result', 'source']) { const r = find(o[k], depth + 1); if (r) return r; }
    return null;
  };
  return find(v, 0);
}

/** The picture a screenshot step kept: the record's own image, or the plug's path for it (only one of
 *  this task's own, under this harness and session); null for any other step. */
export function shotOf(step: Pick<BrowserStep, 'name' | 'args' | 'output'>, harnessId: string, sid: string): { path?: string; dataUri?: string } | null {
  const act = browserActOf(step.name) || String(parseToolArgs(step.args).action || '');
  if (!/screenshot|capture/i.test(act)) return null;
  const out = String(step.output || '');
  const data = imageIn(out);
  if (data) return { dataUri: data };
  const all = [...out.matchAll(MEDIA)];
  const last = all[all.length - 1];
  if (!last || !sid) return null;
  const dec = (s: string) => { try { return decodeURIComponent(s); } catch { return s; } };
  return dec(last[1]) === harnessId && dec(last[2]) === sid ? { path: last[0] } : null;
}

/** A step's result as a person reads it: the plug's note about where the picture went is the picture. */
export function resultText(output?: string): string {
  const t = String(output ?? '').replace(/\u001b\[[0-9;?]*[A-Za-z]/g, '').replace(/\r\n?/g, '\n')
    .split('\n').filter((l) => !/^Kept with the task's files as /.test(l)).join('\n').trim();
  return t.length > 8000 ? `${t.slice(0, 8000)}\n…` : t;
}

/** The screenshot's picture, read with the sign-in (a bare src would be refused) into an object URL. */
function useShot(shot: { path?: string; dataUri?: string } | null): { src: string; state: 'none' | 'loading' | 'ready' | 'failed' } {
  const [got, setGot] = useState<{ key: string; src: string; failed: boolean } | null>(null);
  const key = shot?.path || '';
  useEffect(() => {
    if (!key) return undefined;
    let alive = true, obj = '';
    harnessFetch(`/api/harness${key}`, { headers: authHeaders() })
      .then(async (r) => {
        if (!r.ok) throw new Error(String(r.status));
        const b = await r.blob();
        if (!alive) return;
        obj = URL.createObjectURL(b);
        setGot({ key, src: obj, failed: false });
      })
      .catch(() => { if (alive) setGot({ key, src: '', failed: true }); });
    return () => { alive = false; if (obj) URL.revokeObjectURL(obj); };
  }, [key]);
  if (shot?.dataUri) return { src: shot.dataUri, state: 'ready' };
  if (!key) return { src: '', state: 'none' };
  if (!got || got.key !== key) return { src: '', state: 'loading' };
  return got.failed ? { src: '', state: 'failed' } : { src: got.src, state: 'ready' };
}

/** What a past step recorded, in the screen's place once its browser has closed. */
export function StepRecord({ step, harnessId, sid, closed }: { step: BrowserStep; harnessId: string; sid: string;
  /** this page saw the task's browser and it has closed since (else nothing is said about it) */
  closed: boolean }) {
  const shot = useShot(useMemo(() => shotOf(step, harnessId, sid), [step, harnessId, sid]));
  const args = useMemo(() => {
    const a = parseToolArgs(step.args);
    return Object.keys(a).filter((k) => a[k] != null && a[k] !== '' && k !== '_raw')
      .map((k) => `${k}: ${typeof a[k] === 'object' ? JSON.stringify(a[k]) : String(a[k])}`).join('\n') || String(a._raw || '');
  }, [step.args]);
  const result = resultText(step.output);
  return (
    <div className="tk-brec">
      {closed ? <p className="tk-brec-note">This browser has closed.</p> : null}
      {shot.state === 'ready' ? <img className="tk-brec-shot" src={shot.src} alt={`Screenshot from this step: ${step.label}`} />
        : shot.state === 'loading' ? <div className="tk-brec-shot is-loading" role="img" aria-label="Loading the screenshot" />
          : shot.state === 'failed' ? <p className="tk-brec-none">The screenshot could not be loaded.</p> : null}
      <h3 className="tk-brec-t">{step.label}</h3>
      {args ? (<section className="tk-brec-sec"><h4>Input</h4><pre>{args}</pre></section>) : null}
      {result ? (<section className={'tk-brec-sec' + (step.status === 'failed' ? ' is-failed' : '')}><h4>{step.status === 'failed' ? 'Error' : 'Result'}</h4><pre>{result}</pre></section>)
        : shot.state === 'none' ? <p className="tk-brec-none">This step kept no screenshot and no result.</p> : null}
    </div>
  );
}

export interface TaskBrowser {
  /** the open task's browser as the feed and its route report it (undefined: none seen) */
  live: BrowserState | undefined;
  /** the task's turn is running here (the card's glow follows the work) */
  busy: boolean;
  pane: PaneState;
  /** the past step the card was opened from, or null (the live browser, or the empty state) */
  step: BrowserStep | null;
  /** the card opened on its own (a browser opening), not at the person's word: it takes no focus */
  popped: boolean;
  /** open the card: on a step, or on the live browser (null) */
  show: (step: BrowserStep | null) => void;
  /** close it; `dismiss` (the person closed it) keeps it closed for this browser */
  close: (dismiss?: boolean) => void;
}

/** The open task's browser and the card's state: seeded from the route when a task opens, popped when a
 *  browser opens (unless the person closed it for that browser), closed when the browser closes or the
 *  task changes. `onPop`: the card is taking the place (the page lets go of a file's preview). */
export function useTaskBrowser(harnessId: string, sid: string | null, onPop: () => void): TaskBrowser {
  const st = useConvState(sid || '');
  const live = sid ? st.browser : undefined;
  const busy = !!sid && st.busy;
  const pane = usePaneState(harnessId);
  const [step, setStep] = useState<BrowserStep | null>(null);
  const [popped, setPopped] = useState(false);
  // a task opened: what its route says (a browser already running shows at once)
  useEffect(() => {
    if (!sid) return undefined;
    let alive = true;
    fetchBrowser(sid).then((i) => { if (alive) seedBrowserState(sid, i); });
    return () => { alive = false; };
  }, [sid]);
  // another task (or New task) takes the page: the card closes, as the preview does; a new task that
  // has just got its session keeps it
  const prevSid = useRef(sid);
  useEffect(() => {
    const was = prevSid.current;
    prevSid.current = sid;
    if (was && was !== sid) { setStep(null); setPaneState(harnessId, { open: false, mode: 'docked' }); }
  }, [sid, harnessId]);
  // a browser opening pops the card, unless the person closed it for that very browser
  const epoch = live?.open ? live.epoch : 0;
  const popRef = useRef(onPop);
  popRef.current = onPop;
  useEffect(() => {
    if (!sid || !epoch || getPaneState(harnessId).dismissed[sid] === epoch) return;
    setStep(null);
    setPopped(true);
    setPaneState(harnessId, { open: true });
    popRef.current();
  }, [sid, epoch, harnessId]);
  // the browser closing closes the card (no stopped stream left standing)
  const wasOpen = useRef(false);
  useEffect(() => {
    const open = !!live?.open;
    if (wasOpen.current && !open) { setStep(null); setPaneState(harnessId, { open: false, mode: 'docked' }); }
    wasOpen.current = open;
  }, [live?.open, harnessId]);
  // the feed is open only while a turn runs here: a browser still open after it (its close comes when
  // the turn's end or the idle timer stops it) is asked about now and then, so the card never holds a
  // stream that has stopped
  useEffect(() => {
    if (!sid || !live?.open || busy) return undefined;
    let alive = true;
    const ask = () => fetchBrowser(sid).then((i) => { if (alive && i) seedBrowserState(sid, i); });
    const first = window.setTimeout(ask, 1500);
    const every = window.setInterval(ask, 5000);
    return () => { alive = false; window.clearTimeout(first); window.clearInterval(every); };
  }, [sid, live?.open, busy]);
  const show = (s: BrowserStep | null) => { setStep(s); setPopped(false); setPaneState(harnessId, { open: true }); };
  const close = (dismiss = true) => {
    setStep(null);
    const d = getPaneState(harnessId).dismissed;
    setPaneState(harnessId, { open: false, mode: 'docked', dismissed: dismiss && sid && live?.open ? { ...d, [sid]: live.epoch } : d });
  };
  return { live, busy, pane, step, popped, show, close };
}

/** A drawer from the right (a sheet from the bottom on a phone): Escape and the scrim close it. Opened
 *  by the person, the focus goes into it and comes back to where it was; popped by a browser opening,
 *  it leaves the focus where it is (the person may be writing). */
function Drawer({ onClose, focus, children }: { onClose: () => void; focus: boolean; children: ReactNode }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const back = focus ? document.activeElement as HTMLElement | null : null;
    if (focus) ref.current?.focus();
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape' && !e.defaultPrevented) { e.stopPropagation(); closeRef.current(); } };
    document.addEventListener('keydown', key);
    return () => { document.removeEventListener('keydown', key); back?.focus?.(); };
  // once, as it opens
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <>
      <div className="tk-bscrim" aria-hidden="true" onClick={onClose} />
      <div ref={ref} tabIndex={-1} className="tk-bdrawer hrui-legacy tk-bhost" role="dialog" aria-modal="true" aria-label="Browser">{children}</div>
    </>
  );
}

/** The card in the preview's place: docked (the page's third column) or, under 1280 px, a drawer. */
export function BrowserSlot({ harnessId, sid, tb, overlay }: { harnessId: string; sid: string | null; tb: TaskBrowser; overlay: boolean }) {
  const open = !!tb.live?.open;
  const closedView = !open && tb.step
    ? { status: tb.step.label, body: <StepRecord step={tb.step} harnessId={harnessId} sid={sid || ''} closed={!!tb.live} /> } : null;
  const card = <BrowserPane harnessId={harnessId} sessionId={sid || ''} live={tb.live} busy={tb.busy} mode={tb.pane.mode}
    onClose={() => tb.close()} closedView={closedView} />;
  if (overlay) return <Drawer onClose={() => tb.close()} focus={!tb.popped}>{card}</Drawer>;
  return (
    <aside className="tk-preview tk-bslot" aria-label="Browser">
      <div className="hrui-legacy tk-bhost">{card}</div>
    </aside>
  );
}

const BROWSER_IC = <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth={1.9} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="3.5" y="4.5" width="17" height="15" rx="2.5" /><path d="M3.5 9h17M7 6.8h.01M9.6 6.8h.01" /></svg>;

/** The task bar's Browser control: shows or hides the card, its dot lit while a browser is open (green
 *  while the person has it). */
export function BrowserControl({ shown, live, onToggle }: { shown: boolean; live: BrowserState | undefined; onToggle: () => void }) {
  const on = !!live?.open;
  return (
    <button type="button" className={'icon-btn tk-ib tk-bctl' + (shown ? ' on' : '')} aria-pressed={shown} aria-label="Browser"
      title={shown ? 'Hide the browser' : on ? 'Show the browser the agent is using' : 'Show the browser'} onClick={onToggle}>
      {BROWSER_IC}
      {on ? <span className={'tk-bdot' + (live?.control === 'user' ? ' is-user' : '')} aria-hidden="true" /> : null}
    </button>
  );
}
