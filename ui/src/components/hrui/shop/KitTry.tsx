'use client';
// One kit's page (docs/uxuidesign/console-79, view `kit`: kitTryView, ktTraceInner, ktLiveInner):
// the kit's own app on the right, used the way a person would use it, and on the left the Trace,
// where every step its setup takes shows up as it happens. Narrow, the two sides are two tabs, the
// app first.
//
// Where the prototype simulates a run, this page shows a real one: the app is the kit's own app,
// running on the kit's setup in this workspace, and the Trace is that setup's task as its recorded
// trace says. A kit not set up here yet is set up first (what it runs on, and its database when it
// reads one). There is no separate free try: trying a kit is using it on its own setup.
//
// The Trace is the shared trace view (trace/TraceView): each event's time counts from its own
// turn's start (a kit's task runs turn after turn for hours), and a step's detail opens over the
// Trace panel. "Make it yours" stays at the foot of the panel, and Launch to your users opens the
// design's starter sheet (Set up the app, starter: the coding agent takes the kit's app from the
// starter-kit repository, in that repository's own steps), as the design's launchKit does, rather
// than leaving the page.
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { useWorkspace } from '@/lib/workspace';
import { getCustom } from '@/lib/harness';
import { isoSvg } from '../tower';
import { Iso } from '../Iso';
import { toast } from '../toast';
import { tabKeys } from '../tabKeys';
import { Skel, SkLine, SkRows } from '../Skel';
import { cutWords, durMs, preview, type TaskState } from '../setup/fmt';
import { rowOf, type SetupRow } from '../setups';
import { SetUpApp } from '../SetUpApp';
import { TraceView, dkind, ROLE, turnsOf, turnSpan, type DKind } from '../trace/TraceView';
import { appHref, appPath, fetchKitBases, fetchKits, kitTower, launchError, launchKit, partsOf, runtimeOf, type Base, type Kit, type Launched } from './kits';
import { HLogo, KitIc } from './parts';
import { LaunchSheet, type LaunchMode } from './LaunchSheet';
import { useKitRun, type FRow } from './useKitRun';
import { openNewSetup } from '../start/open';

/** "3.4 s", the design's ktSec */
/** a kit's two sides as tabs when narrow, in order (the arrow keys move through them) */
const KT_TABS = ['app', 'play'] as const;
const ktSec = (ms: number) => (Math.max(0, ms) / 1000).toFixed(1) + ' s';

/** A step's words, as the design writes them: a bold name and a muted detail. */
function RowText({ r, k }: { r: FRow; k: DKind }) {
  if (k === 'tool') return <><b>{r.label}</b> <span className="muted mono">{preview(r.param || '')}</span></>;
  if (k === 'step') return <><b>Thinking</b> <span className="muted">{preview(r.text || '')}</span></>;
  if (k === 'done' || k === 'error') return <><b>{k === 'done' ? 'Completed' : 'Failed'}</b> <span className="muted">{preview(r.text || '')}</span></>;
  return <>{cutWords(r.text || '', 240)}</>;
}

const LOCK = <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></svg>;
const TICK = <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>;

/** How the kit's app pane stands: not set up here yet, opening, open, or open in its own tab. */
type AppState = 'loading' | 'setup' | 'opening' | 'error' | 'open' | 'tab';

export function KitTryPage({ kitId }: { kitId: string }) {
  const router = useRouter();
  const { current, loading } = useWorkspace();
  const [kit, setKit] = useState<Kit | null>(null);
  const [missing, setMissing] = useState(false);
  const [loadErr, setLoadErr] = useState(false);
  // what this organization can run, for choosing another pairing: null until read
  const [bases, setBases] = useState<Base[] | null>(null);
  const [basesErr, setBasesErr] = useState(false);
  const [app, setApp] = useState<AppState>('loading');
  const [frameKey, setFrameKey] = useState(0);
  const [sheet, setSheet] = useState<LaunchMode | null>(null);
  const [tab, setTab] = useState<'app' | 'play'>('app');
  const [busy, setBusy] = useState(false);

  // the kit, as the catalog says it for this workspace
  useEffect(() => {
    if (loading) return;
    let alive = true;
    fetchKits().then((ks) => {
      if (!alive) return;
      const k = ks.find((x) => x.id === kitId) || null;
      setKit(k); setMissing(!k); setLoadErr(false);
    }).catch(() => { if (alive) setLoadErr(true); });
    return () => { alive = false; };
  }, [loading, current.id, kitId]);
  // a read that fails is said where the choice is made (the launch sheet), with Try again; never
  // "nothing can run"
  const basesFor = useRef(0);
  const loadBases = useCallback(() => {
    const n = ++basesFor.current;
    setBasesErr(false);
    fetchKitBases().then((b) => { if (basesFor.current === n) setBases(b); })
      .catch(() => { if (basesFor.current === n) setBasesErr(true); });
  }, []);
  useEffect(() => {
    if (loading) return;
    loadBases();
    return () => { basesFor.current++; };
  }, [loading, current.id, loadBases]);

  // A kit set up here opens through launch: it is idempotent, and it is where a set-up kit picks
  // up what its kit definition has changed since (its package, its prompt, the tools it needs).
  const opened = useRef('');
  useEffect(() => {
    if (!kit) return;
    if (!kit.launched) { setApp('setup'); return; }
    if (opened.current === kit.id) return;
    opened.current = kit.id;
    setApp('opening');
    launchKit(kit.id).then(() => setApp('open')).catch((e) => { setApp('error'); toast(launchError(e, kit, false)); });
  }, [kit]);

  const run = useKitRun(kit?.launched ? kit.harnessId : null);
  const st: TaskState | null = run.st;
  const following = !!run.card;
  const isRun = st === 'running';
  const ended = following && !isRun;
  const ok = st === 'done';
  const rows = run.rows || [];
  // the turn now: a kit's task goes on turn after turn, so its clock counts from this turn's start
  const lastTurn = turnsOf(rows).slice(-1)[0] || [];
  const { t0, t1 } = turnSpan(lastTurn);

  // the running clock, from the task's own start
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!isRun) return;
    const t = setInterval(() => setNow(Date.now()), 200);
    return () => clearInterval(t);
  }, [isRun]);
  // A running turn's clock starts at its first event; until that event is read (the rows still end on
  // the last turn's result), at the moment this page saw the task start running.
  const runSince = useRef<number | null>(null);
  if (!isRun) runSince.current = null;
  else if (runSince.current == null) runSince.current = Date.now();
  const lastEnded = lastTurn.length > 0 && lastTurn[lastTurn.length - 1].kind === 'result';
  const startMs = isRun && (t0 == null || lastEnded) ? (runSince.current ?? now) : t0 != null ? t0 * 1000 : now;
  const tookMs = t0 != null && t1 != null ? (t1 - t0) * 1000 : run.card ? durMs(run.card) : 0;

  // each new step slides in once (marked until the next read changes the rows, not the next clock
  // tick); the list follows the newest one
  const anim = useRef<{ sid: string; rows: FRow[] | null; from: number }>({ sid: '', rows: null, from: 0 });
  if (anim.current.rows !== run.rows) {
    const sid = run.card?.session_id || '';
    anim.current = { sid, rows: run.rows, from: anim.current.sid === sid && anim.current.rows ? anim.current.rows.length : 0 };
  }
  const prevN = anim.current.from;
  const pb = useRef<HTMLDivElement | null>(null);
  useLayoutEffect(() => {
    const t = pb.current;
    if (t && t.scrollHeight > t.clientHeight + 2) t.scrollTop = t.scrollHeight;
  }, [rows.length, isRun]);
  // the Trace panel: a step's detail opens over it
  const [playEl, setPlayEl] = useState<HTMLElement | null>(null);
  // "Make it yours" stays put: it enters once with the page, then never re-mounts or toggles with
  // the task's running state (it flashed in and out while the agent worked)
  const [nextIn] = useState(true);
  // Launch to your users: the starter sheet for the kit's setup (read once it is asked for)
  const [hand, setHand] = useState<SetupRow | null>(null);

  // a refused frame (the browser will not show this page inside another) opens in its own tab
  const frame = useRef<HTMLIFrameElement | null>(null);
  const checked = useRef(false);
  const onFrameLoad = () => {
    if (checked.current || !kit) return;
    checked.current = true;
    try {
      const href = frame.current?.contentWindow?.location.href || '';
      if (!href || href === 'about:blank' || !href.includes(appHref(kit))) setApp('tab');
    } catch { setApp('tab'); }
  };

  /** The design's starter sheet for the kit's setup: how your coding agent takes the kit's app from
   *  the starter-kit repository and makes it yours. */
  async function openHand(hid: string) {
    if (!kit) return;
    const h = await getCustom(hid).catch(() => null);
    if (!h) { toast('The kit’s setup could not be read. Try again in a moment.'); return; }
    const rt = runtimeOf(kit, bases);
    setHand(rowOf(h, rt?.label || h.baseLabel || h.base, [], false));
  }
  async function launchToUsers() {
    if (!kit || busy) return;
    if (kit.launched && kit.harnessId) { setBusy(true); await openHand(kit.harnessId); setBusy(false); return; }
    setSheet('launch');
  }
  function onLaunched(r: Launched) {
    const mode = sheet;
    setSheet(null);
    if (!kit) return;
    // what it runs on now is the launch's own answer (the pairing chosen, or the one it already had);
    // without one the header names nothing rather than the suggestion
    setKit({ ...kit, launched: true, harnessId: r.harnessId || kit.harnessId, runningOn: r.runningOn });
    // launched to users: a setup just made, opened on its Tasks like every one (start/open.ts); its
    // header's Set up the app holds the kit's starter steps
    const hid = r.harnessId || kit.harnessId;
    if (mode === 'launch' && hid) { openNewSetup(router, { id: hid }); return; }
    if (mode === 'reconnect') { toast('Database connected.'); checked.current = false; setFrameKey((n) => n + 1); return; }
    // tried: it is set up and open now; nothing more to ask
    opened.current = kit.id;
    checked.current = false;
    setApp('open');
  }
  async function retryOpen() {
    if (!kit || busy) return;
    setBusy(true); setApp('opening');
    try { await launchKit(kit.id); checked.current = false; setApp('open'); }
    catch (e) { setApp('error'); toast(launchError(e, kit, false)); }
    setBusy(false);
  }

  if (missing || loadErr) {
    return (
      <div className="scroll"><div className="list-wrap">
        <p className="sub" role={loadErr ? 'alert' : undefined}>
          {loadErr ? 'This kit could not be read just now. Reload the page to try again.' : 'This kit is not in the Shop.'}{' '}
          <Link className="link-q inl" href="/shop">Back to the Shop</Link>
        </p>
      </div></div>
    );
  }
  if (!kit) {
    // the kit page, drawn while it loads: back link, the kit's identity, then the trace and the app
    return (
      <div className="scroll"><div className="list-wrap">
        <Skel label="Loading the kit">
          <SkLine w={64} h={12} />
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 18 }}>
            <SkLine w={36} h={36} r={10} /><div style={{ flex: 1 }}><SkLine w="36%" h={22} r={7} /><SkLine w="52%" h={11} style={{ marginTop: 9 }} /></div>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 20, marginTop: 28 }}>
            <div style={{ flex: '1 1 300px', minWidth: 0 }}><SkRows n={4} lead={false} /></div>
            <div style={{ flex: '2 1 360px', minWidth: 0 }}><SkLine h={320} r={14} /></div>
          </div>
        </Skel>
      </div></div>
    );
  }

  const rt = runtimeOf(kit, bases);
  const meta: ReactNode[] = [];
  if (rt) meta.push(<><HLogo base={rt.base} />{rt.label}</>);
  if (rt?.model) meta.push(<span className="mono">{rt.model}</span>);
  partsOf(kit).forEach((p) => meta.push(p[1]));

  const status = isRun ? <span className="kt-st run"><span className="dot run" /><span>{ktSec(now - startMs)}</span></span>
    : ended && tookMs ? <span className="kt-st">{ok ? 'Done in ' : st === 'cancelled' ? 'Cancelled after ' : 'Failed after '}{ktSec(tookMs)}</span> : null;
  const next = (
    <div className={'kt-next' + (nextIn ? ' fresh' : '')}>
      <b>Make it yours</b>
      <button type="button" className="btn primary" disabled={busy} onClick={() => void launchToUsers()}>Launch to your users</button>
    </div>
  );
  const taskHref = run.card && kit.harnessId
    ? `/studio/${encodeURIComponent(kit.harnessId)}?test=${encodeURIComponent(run.card.session_id)}` : '';

  // the trace pane
  let trace: ReactNode;
  if (!following) {
    trace = (
      <div className="kt-idle">
        <span className="kt-tower" aria-hidden="true"><Iso svg={isoSvg(kitTower(kit, rt), 7, false)} /></span>
        <p><b>Try it in the app.</b> Every step it takes shows up here, as it happens.</p>
      </div>
    );
  } else if (run.failed && !run.rows) {
    trace = <p className="fine" role="alert">The trace could not be read just now.{' '}<button type="button" className="link-q inl" onClick={run.retry}>Try again</button></p>;
  } else {
    trace = (
      <TraceView sid={run.card?.session_id || ''} rows={run.rows} failed={run.failed} running={isRun} overlayHost={playEl} enterFrom={prevN || undefined}
        foot={run.failed ? (
          // a read after the rows on screen failed: they may not be the latest
          <p className="fine" role="alert">The trace could not be read just now.{' '}<button type="button" className="link-q inl" onClick={run.retry}>Try again</button></p>
        ) : null} />
    );
  }

  // the one-line live step on the App tab (narrow screens)
  let live: ReactNode = null;
  if (following) {
    const lr = [...rows].reverse().find((r) => r.kind !== 'user') || null;
    const lk = lr ? dkind(lr) : null;
    live = isRun ? (
      <>
        <span className="dot run" />
        {lr && lk ? <><span className={`badge b-${lk}`}>{ROLE[lk]}</span><span className="kt-live-t"><RowText r={lr} k={lk} /></span></> : <span className="kt-live-t">Working</span>}
        <span className="kt-live-go">Trace</span>
      </>
    ) : (
      <>
        {ok ? <span className="kt-live-ok" aria-hidden="true">{TICK}</span> : <span className="dot bad" />}
        <span className="kt-live-t">{ok ? 'Done in ' : st === 'cancelled' ? 'Cancelled after ' : 'Failed after '}{ktSec(tookMs)} · {rows.length} steps</span>
        <span className="kt-live-go">See the trace</span>
      </>
    );
  }

  // the app pane
  let frameIn: ReactNode;
  if (app === 'open') {
    frameIn = <iframe key={frameKey} ref={frame} className="kt-appframe" src={appHref(kit)} title={`${kit.title} app`} onLoad={onFrameLoad} />;
  } else if (app === 'setup') {
    frameIn = (
      <div className="kt-idle">
        <KitIc kit={kit} as="span" />
        <p><b>Try {kit.title} here.</b></p>
        <button type="button" className="btn primary" onClick={() => setSheet('try')}>Try it</button>
      </div>
    );
  } else if (app === 'tab') {
    frameIn = (
      <div className="kt-idle">
        <KitIc kit={kit} as="span" />
        <p><b>{kit.title} opens in its own tab.</b></p>
        <a className="btn primary" href={appHref(kit)} target="_blank" rel="noopener">Open {kit.title}</a>
      </div>
    );
  } else if (app === 'error') {
    frameIn = (
      <div className="kt-idle">
        <p><b>{kit.title} did not open.</b></p>
        <button type="button" className="btn" disabled={busy} onClick={() => void retryOpen()}>Try again</button>
      </div>
    );
  } else {
    frameIn = <div className="kt-idle"><p role="status">{app === 'opening' ? `Opening ${kit.title}…` : ''}</p></div>;
  }

  return (
    // `done` is the design's mark for showing the next step on the app tab; it stays on
    <div className="kt done" data-tab={tab}>
      <header className="kt-h">
        <Link className="kt-back" href="/shop">‹ Shop</Link>
        <div className="kt-id">
          <KitIc kit={kit} as="span" />
          <div>
            <h1>{kit.title}</h1>
            <p className="kt-meta meta"><span className="meta-in">{meta.map((m, i) => <span key={i} className="meta-i">{m}</span>)}</span></p>
          </div>
        </div>
        <div className="kt-act">
          <button type="button" className="btn" onClick={() => void launchToUsers()}>Launch to your users</button>
        </div>
      </header>
      <div className="kt-tabs" role="tablist" onKeyDown={(e) => tabKeys(e, KT_TABS, tab, setTab)}>
        <button type="button" role="tab" aria-selected={tab === 'app'} tabIndex={tab === 'app' ? 0 : -1} className={tab === 'app' ? 'on' : ''} onClick={() => setTab('app')}>App</button>
        <button type="button" role="tab" aria-selected={tab === 'play'} tabIndex={tab === 'play' ? 0 : -1} className={tab === 'play' ? 'on' : ''} onClick={() => setTab('play')}>
          Trace{following && rows.length ? <> <span className="count">{rows.length}</span></> : null}
        </button>
      </div>
      <div className="kt-body">
        <section className="kt-play kt-play-trv" aria-label="Trace" ref={setPlayEl}>
          <div className="kt-ph">
            <span><b>Trace</b>{taskHref ? <small className="kt-proto"><Link className="link-q inl" href={taskHref}>Open the task</Link></small> : null}</span>
            {status}
          </div>
          <div className="kt-pb" ref={pb}>{trace}</div>
          {next}
        </section>
        <section className="kt-app" aria-label={`${kit.title} app`}>
          <div className="kt-bar">
            <a className="kt-url" href={appHref(kit)} target="_blank" rel="noopener" title="Open in a new tab">{LOCK}<span className="kt-path">{appPath(kit)}</span></a>
            {kit.launched && kit.database ? <button type="button" className="link-q" onClick={() => setSheet('reconnect')}>Change database</button> : null}
          </div>
          {following ? <button type="button" className="kt-live" aria-label="Open the trace" onClick={() => setTab('play')}>{live}</button> : null}
          <div className={'kt-frame' + (app === 'open' ? '' : ' kt-off')}>{frameIn}</div>
          <div className="kt-next-m">{next}</div>
        </section>
      </div>
      {sheet ? <LaunchSheet kit={kit} bases={bases} basesFailed={basesErr} onRetryBases={loadBases} mode={sheet} onClose={() => setSheet(null)} onDone={onLaunched} /> : null}
      {hand ? <SetUpApp r={hand} kit={kit.id} kitTitle={kit.title} onClose={() => setHand(null)} /> : null}
    </div>
  );
}
