'use client';
// One kit's page (docs/uxuidesign/console-79, view `kit`): the kit's own app, used the way a person would
// use it, running on the kit's setup in this workspace. A kit not set up here yet is set up first (what it
// runs on, and its database when it reads one); trying a kit is using it on its own setup. A self-hosted
// console shows no trace beside it: the trace view is the hosted product's (Richard 10-22). "Make it yours"
// sits under the app, and Launch to your users opens the design's starter sheet (Set up the app, starter:
// the coding agent takes the kit's app from the starter-kit repository, in that repository's own steps),
// as the design's launchKit does, rather than leaving the page.
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { useWorkspace } from '@/lib/workspace';
import { getCustom } from '@/lib/harness';
import { toast } from '../toast';
import { Skel, SkLine } from '../Skel';
import { rowOf, type SetupRow } from '../setups';
import { SetUpApp } from '../SetUpApp';
import { appHref, appPath, fetchKitBases, fetchKits, launchError, launchKit, partsOf, runtimeOf, type Base, type Kit, type Launched } from './kits';
import { HLogo, KitIc } from './parts';
import { LaunchSheet, type LaunchMode } from './LaunchSheet';
import { openNewSetup } from '../start/open';

/** "3.4 s", the design's ktSec */


const LOCK = <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></svg>;

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
    // the kit page, drawn while it loads: back link, the kit's identity, then the app
    return (
      <div className="scroll"><div className="list-wrap">
        <Skel label="Loading the kit">
          <SkLine w={64} h={12} />
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 18 }}>
            <SkLine w={36} h={36} r={10} /><div style={{ flex: 1 }}><SkLine w="36%" h={22} r={7} /><SkLine w="52%" h={11} style={{ marginTop: 9 }} /></div>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 20, marginTop: 28 }}>
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

  const next = (
    <div className={'kt-next' + (nextIn ? ' fresh' : '')}>
      <b>Make it yours</b>
      <button type="button" className="btn primary" disabled={busy} onClick={() => void launchToUsers()}>Launch to your users</button>
    </div>
  );
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
    // `done` shows the next step under the app; kt-solo lays the page out as the app alone (no trace)
    <div className="kt done kt-solo">
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
      <div className="kt-body">
        <section className="kt-app" aria-label={`${kit.title} app`}>
          <div className="kt-bar">
            <a className="kt-url" href={appHref(kit)} target="_blank" rel="noopener" title="Open in a new tab">{LOCK}<span className="kt-path">{appPath(kit)}</span></a>
            {kit.launched && kit.database ? <button type="button" className="link-q" onClick={() => setSheet('reconnect')}>Change database</button> : null}
          </div>
          <div className={'kt-frame' + (app === 'open' ? '' : ' kt-off')}>{frameIn}</div>
          <div className="kt-next-m">{next}</div>
        </section>
      </div>
      {sheet ? <LaunchSheet kit={kit} bases={bases} basesFailed={basesErr} onRetryBases={loadBases} mode={sheet} onClose={() => setSheet(null)} onDone={onLaunched} /> : null}
      {hand ? <SetUpApp r={hand} kit={kit.id} kitTitle={kit.title} onClose={() => setHand(null)} /> : null}
    </div>
  );
}
