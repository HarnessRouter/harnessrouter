'use client';
// Harness Studio (docs/uxuidesign/console-91, view `agents`: agentsView, cardHtml): the workspace's
// setups as brick towers or a list, under the workspace's header (its name, which opens the workspace
// menu under it, its facts, the view switch and New setup). Every number on it is read from the
// setups' own tasks (see setups.ts), the header's totals from the same rows as the cards: a setup
// whose tasks have not been read yet claims no health (a loading line) and no number (a dash), and the
// header then leaves out what it cannot total. A setup whose latest read failed keeps showing the
// last read that answered.
//
// It stays current while it shows, both views alike: each setup's health, its running dot, its latest
// task and its 24 h numbers. The workspace watch (lib/workspace-feed: the workspace's newest task cards
// read every few seconds) tells each task's start and end: a start shows on its setup at once, an end
// too, and that setup is read again for its numbers, as is a setup whose turn starts or ends on a
// setup's own feed this tab holds. Each time the watch comes up the rows are read once. While it
// cannot read, the page says its list may be out of date, with Try again (setups.ts useSetups live);
// nothing is read while the page is hidden.
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useWorkspace } from '@/lib/workspace';
import { WsBadge } from '@/components/hrui/ws';
import { isoSvg, ghostTower } from '@/components/hrui/tower';
import { Iso } from '@/components/hrui/Iso';
import { useSetups, ago, type SetupRow } from '@/components/hrui/setups';
import { HealthPill } from '@/components/hrui/setup/parts';
import { onFeedTurn } from '@/lib/feed-turns';
import { harnessLogoSrc } from '@/components/HarnessLogo';
import { NewSetup } from '@/components/hrui/NewSetup';
import { Skel, SkCards, SkRows, SkLine } from '@/components/hrui/Skel';
import { openWorkspaceMenu } from '@/components/hrui/WorkspaceSheets';

const CHEV = <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.4} aria-hidden="true"><path d="M6 9l6 6 6-6" /></svg>;
const PLUS = <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>;
const VM_KEY = 'hr.studio.view';
const setupHref = (id: string) => `/studio/${encodeURIComponent(id)}`;


function Logo({ base }: { base: string }) {
  const src = harnessLogoSrc(base);
  return src ? <img className="h-logo" src={src} alt="" /> : null;
}

// a setup's numbers, from its rows' last read that answered; a dash when there is none, or none to count
const pct = (r: SetupRow) => (!r.tasksKnown || r.day.succ == null ? '—' : (r.day.succ * 100).toFixed(1) + '%');
const count = (r: SetupRow) => (r.tasksKnown && r.day.n ? `${r.day.n}${r.dayCapped ? '+' : ''}` : '—');
const p95 = (r: SetupRow) => (r.tasksKnown && r.day.p95 ? r.day.p95 : '—');
// the card's line under its name: its latest task, or none yet; null while nothing is known
function lastLine(r: SetupRow): string | null {
  if (!r.tasksKnown) return null;
  return r.lastAny ? `Last task ${ago(r.lastAny)}` : 'No tasks yet';
}

function Card({ r }: { r: SetupRow }) {
  const line = lastLine(r);
  return (
    <Link className="card" href={setupHref(r.h.id)} data-agent={r.h.id}>
      <div className="card-tower">
        {r.running ? <span className="card-run"><span className="dot run" />Running</span> : null}
        <Iso svg={isoSvg(r.tower, 13, 'card')} />
      </div>
      <div className="card-body">
        <div className="card-h"><b>{r.h.name}</b><span className="card-st"><HealthPill r={r} /></span></div>
        <div className="card-sub" title={`Agent harness: ${r.baseName} · Model: ${r.h.defaultModel || 'harness default'}`}>
          <Logo base={r.h.base} />{r.baseName} · <span className="card-m">{r.h.defaultModel || 'harness default'}</span>
        </div>
        <div className="card-conn">{line ?? <SkLine w={110} h={11} />}</div>
        <dl className="card-stats">
          <div><dt>Tasks · 24 h</dt><dd>{count(r)}</dd></div>
          <div><dt>Success</dt><dd>{pct(r)}</dd></div>
          <div><dt>P95 · 24 h</dt><dd>{p95(r)}</dd></div>
        </dl>
      </div>
    </Link>
  );
}

export default function StudioPage() {
  const router = useRouter();
  const { current } = useWorkspace();
  const { rows, error, refresh, paused, reconnect } = useSetups({ live: true, scope: current.id });
  // a turn of a setup starting or ending, on any feed this tab holds: that setup's row is read again
  useEffect(() => onFeedTurn((_sid, harness) => { if (harness) refresh(harness); }), [refresh]);
  const [vm, setVm] = useState<'cards' | 'list'>('cards');
  useEffect(() => { try { if (localStorage.getItem(VM_KEY) === 'list') setVm('list'); } catch { /* none */ } }, []);
  const pick = (v: 'cards' | 'list') => { setVm(v); try { localStorage.setItem(VM_KEY, v); } catch { /* none */ } };

  const list = rows || [];
  const own = list.length;
  // the header totals the same rows the cards show, and only when every row's read is in: a total
  // over some of them would read as the whole
  const whole = list.every((r) => r.tasksKnown && !r.readFailed);
  const runningN = list.filter((r) => r.running).length;
  const tot = list.reduce((s, r) => s + r.day.n, 0);
  const capped = list.some((r) => r.dayCapped);
  const meta = [
    rows === null || error ? '' : own ? `${own} setup${own === 1 ? '' : 's'}` : 'No setups yet',
    whole && runningN ? `${runningN} running` : '',
    whole && tot ? `${tot}${capped ? '+' : ''} task${tot === 1 ? '' : 's'} in 24 h` : '',
  ].filter(Boolean);
  const openWs = (e: React.MouseEvent<HTMLElement>) => openWorkspaceMenu(e.currentTarget);
  // New setup opens the design's dialog here; /studio?new=1 (a link from elsewhere) opens it too
  const [nw, setNw] = useState(false);
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get('new') !== '1') return;
    setNw(true); router.replace('/studio', { scroll: false });
  }, [router]);
  const newSetup = () => setNw(true);

  return (
    <div className="scroll">
      <div className="list-wrap">
        <div className="list-top">
          <div>
            <button type="button" className="ws-switch" aria-haspopup="menu" aria-label="Switch workspace" onClick={openWs}>
              <WsBadge name={current.name} size={34} /><h1>{current.name}</h1><span className="ws-chev">{CHEV}</span>
            </button>
            <p className="sub meta"><span className="meta-in">{meta.map((m) => <span key={m} className="meta-i">{m}</span>)}</span></p>
          </div>
          <div className="top-actions">
            <div className="seg vm-seg" role="group" aria-label="View">
              <button type="button" className={vm === 'cards' ? 'on' : ''} aria-pressed={vm === 'cards'} onClick={() => pick('cards')}>
                <svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" strokeWidth={1.6} aria-hidden="true"><rect x="2" y="2" width="5" height="5" rx="1.2" /><rect x="9" y="2" width="5" height="5" rx="1.2" /><rect x="2" y="9" width="5" height="5" rx="1.2" /><rect x="9" y="9" width="5" height="5" rx="1.2" /></svg>Cards
              </button>
              <button type="button" className={vm === 'list' ? 'on' : ''} aria-pressed={vm === 'list'} onClick={() => pick('list')}>
                <svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" aria-hidden="true"><path d="M2.5 4h11M2.5 8h11M2.5 12h11" /></svg>List
              </button>
            </div>
            <button type="button" className={`btn primary${own || rows === null || error ? '' : ' pulse'}`} onClick={newSetup}>{PLUS}New setup</button>
          </div>
        </div>

        {error ? <p className="sub" role="alert">Your setups could not be read just now. {error}</p> : null}
        {paused && !error && rows !== null ? (
          <p className="sub live-off" role="status">
            Live updates paused. This list may be out of date.{' '}
            <button type="button" className="link-q inl" onClick={reconnect}>Try again</button>
          </p>
        ) : null}

        {vm === 'cards' ? (
          <div className="cards">
            {rows === null ? <Skel label="Loading your setups" className="hrui-skel-contents"><SkCards n={3} /></Skel> : null}
            {list.map((r) => <Card key={r.h.id} r={r} />)}
            <button type="button" className={`card new-card${own || rows === null || error ? '' : ' hi'}`} onClick={newSetup}>
              <div className="card-tower" aria-hidden="true"><Iso svg={isoSvg(ghostTower(), 13, false)} /></div>
              <div className="nc-b">{PLUS}<span>New setup</span></div>
            </button>
          </div>
        ) : (
          <>
            <div className="rows-head agents-g"><span>Name</span><span>Health</span><span className="r">Tasks · 24 h</span><span className="r">Success</span><span className="r">P95 · 24 h</span><span className="r">Last active</span></div>
            <div className="rows">
              {list.map((r) => (
                <Link key={r.h.id} className="row agents-g" href={setupHref(r.h.id)} data-agent={r.h.id}>
                  <span className="t with-mini">
                    <Iso className="mini-iso" svg={isoSvg(r.tower, 5, false)} />
                    <span><b>{r.h.name}</b>{r.running ? <span className="dot run ag-run" role="img" aria-label="Running" title="Running" /> : null}<small className="sub2 ag-sub"><Logo base={r.h.base} />{r.baseName} · {r.h.defaultModel || 'harness default'}</small></span>
                  </span>
                  <span><HealthPill r={r} /></span>
                  <span className="r">{count(r)}</span>
                  <span className="r">{pct(r)}</span>
                  <span className="r">{p95(r)}</span>
                  <span className="r">{r.tasksKnown && r.lastAny ? ago(r.lastAny) : '—'}</span>
                </Link>
              ))}
              {rows === null ? <Skel label="Loading your setups"><SkRows n={4} cols={4} /></Skel> : null}
              {rows !== null && !list.length && !error ? <div className="empty-list">No setups yet.</div> : null}
            </div>
          </>
        )}
      </div>
      {nw ? <NewSetup onClose={() => setNw(false)} /> : null}
    </div>
  );
}
