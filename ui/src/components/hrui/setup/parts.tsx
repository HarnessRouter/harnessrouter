'use client';
// The setup page's shared pieces (docs/uxuidesign/console-91, agentHead / towerHtml / sideTog): the
// one bar on top (back, name, what it runs, the setup's actions, Tasks · Settings at its right end) and
// the Agent stack column beside the work, its 56 px head on the same line as every other column's.
import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { isoSvg, LAYERS, PARTS, SUBS, type Drops } from '../tower';
import { partIcon } from '../bricks';
import { tabKeys } from '../tabKeys';
import { ago, healthOf, type SetupRow } from '../setups';
import { SkLine } from '../Skel';
import { harnessLogoSrc } from '@/components/HarnessLogo';
import { liveTower, runningNames } from './stackLive';
import { recordNames } from './setupParts';
import type { LayerKey } from './settingsModel';
import { OVERLAY_MAX, readFold, stackOff, STACK_KEY, toggled, writeFold, type Fold } from './stackFold';
import { DeployCloud } from './DeployCloud';

export type SetupTab = 'tasks' | 'settings';
const SETUP_TABS: readonly SetupTab[] = ['tasks', 'settings'];

// the tabs' icons (the hosted console's setup page redesign): Tasks a list, Settings a gear; the building page's bar draws
// the same (start/BuildPage: one bar for a setup, before it exists and after)
const TAB_SVG = { viewBox: '0 0 24 24', width: 16, height: 16, fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true } as const;
export const TASKS_IC = <svg {...TAB_SVG}><path d="M9 6h11M9 12h11M9 18h11" /><path d="M4 6h.01M4 12h.01M4 18h.01" /></svg>;
export const SETTINGS_IC = <svg {...TAB_SVG}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" /></svg>;
// the bar's action as an icon, on a phone: Connect your app (a plug)
const PLUG_IC = <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 22v-5M9 8V2M15 8V2M18 8v5a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8z" /></svg>;
/** The design's BACK_IC: a chevron pointing left (the bar's back, a task's back on a phone). */
export const BACK_IC = <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M15 6l-6 6 6 6" /></svg>;

/** A setup's health from its tasks of the last 24 h (setups.ts healthOf): Healthy, Failing (too many
 *  of its finished tasks failed) or Idle (none ran). Its tasks not read yet: nothing is claimed. */
export function HealthPill({ r }: { r: SetupRow }) {
  if (!r.tasksKnown) return <span className="pill-sk" aria-busy="true"><span className="sr">Health loading</span><SkLine w={84} h={22} r={999} /></span>;
  const h = healthOf(r.day);
  const tip = r.day.n ? `${r.day.n}${r.dayCapped ? '+' : ''} task${r.day.n === 1 && !r.dayCapped ? '' : 's'} in 24 h` : 'No tasks in 24 h';
  if (h === 'failing') return <span className="pill bad" title={tip}>Failing</span>;
  if (h === 'healthy') return <span className="pill ok" title={tip}><span className="dot ok" />Healthy</span>;
  return <span className="pill neutral" title={tip}>Idle</span>;
}

/** The setup page's one bar (agentHead, as the hosted console's setup page redesign draws it): back to
 *  Harness Studio; the name on the first line, its agent harness and model on the second (the Harness ID
 *  is the first row of Settings › Agent harness); the setup's two actions, Deploy to Cloud
 *  (DeployCloud.tsx) and Connect your app; and Tasks · Settings at the bar's right end, each with its
 *  icon, where the building page's bar draws them too. */
// A tab chosen with the keyboard keeps the keyboard on it. The page changes its address for the new tab and
// draws the bar again, often as a new tree, so the focus tabKeys gave the new tab was lost to the page body
// (audit, 10-21): the bar that draws next puts it back on the selected tab.
let refocusTab = false;

export function AgentHead({ r, tab, onTab, onSetUpApp, dirty }: {
  r: SetupRow; tab: SetupTab; onTab: (t: SetupTab) => void; onSetUpApp: () => void; dirty?: boolean;
}) {
  const logo = harnessLogoSrc(r.h.base);
  const tabsRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!refocusTab) return;
    refocusTab = false;
    tabsRef.current?.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]')?.focus();
  }, [tab]);
  const model = r.h.defaultModel || '';
  const tb = (k: SetupTab, icon: React.ReactNode, label: React.ReactNode) => (
    <button type="button" role="tab" aria-selected={tab === k} tabIndex={tab === k ? 0 : -1} className={tab === k ? 'on' : ''} onClick={() => onTab(k)}>{icon}{label}</button>
  );
  const act = (label: string, icon: React.ReactNode, onClick?: () => void, primary = false) => (
    <button type="button" className={`btn small ag-act${primary ? ' primary' : ''}`} aria-label={label} title={label}
      onClick={onClick}>{icon}<span className="ag-act-l">{label}</span></button>
  );
  return (
    <header className="ag-bar ag-rt">
      <div className="ag-lft">
        <Link className="ag-back" href="/studio" aria-label="Back to Harness Studio" title="Harness Studio">{BACK_IC}</Link>
        <div className="ag-ident">
          <div className="ag-l1">
            <h1 className="ag-name" title={r.h.name}>{r.h.name}</h1>
          </div>
          <div className={`ag-l2${logo ? ' has-logo' : ''}`}>
            {logo ? <img className="h-logo" src={logo} alt="" aria-hidden="true" title={r.baseName} /> : null}<span className="ag-h">{r.baseName}</span>
            {model ? <><span className="sep" aria-hidden="true">·</span><span className="mono ag-m" title={model}>{model}</span></> : null}
          </div>
        </div>
      </div>
      <div className="ag-right">
        {/* the setup's two actions: where it runs (Deploy to Cloud), and connecting your app to it
            (Connect your app, the primary one). They sit before the tabs, so Tasks · Settings keep the
            bar's right end. On a phone each folds to its icon (its words stay its name and tooltip),
            so the setup's name keeps the row */}
        <DeployCloud id={r.h.id} name={r.h.name} />
        {act('Connect your app', PLUG_IC, onSetUpApp, true)}
      </div>
      <div ref={tabsRef} className="tabs inline ag-tabs" role="tablist" onKeyDown={(e) => tabKeys(e, SETUP_TABS, tab, (k) => { refocusTab = true; onTab(k); })}>
        {tb('tasks', TASKS_IC, 'Tasks')}
        {tb('settings', SETTINGS_IC, <>Settings{dirty ? <i className="dirty-dot" role="img" aria-label="Unsaved changes" /> : null}</>)}
      </div>
    </header>
  );
}

/** A media query, read live (false until the page has a window). */
export function useMedia(q: string): boolean {
  const [on, setOn] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia(q);
    const set = () => setOn(mq.matches);
    set();
    mq.addEventListener('change', set);
    return () => mq.removeEventListener('change', set);
  }, [q]);
  return on;
}

/** Whether the Agent stack is folded (stackFold.ts): the viewer's own choice, kept in this browser
 *  and the same on Tasks, Settings and every setup; open the first time. Under 1280 px, where an
 *  open stack lies over the work, it starts folded and its toggle opens it for the visit without
 *  changing the kept choice. Another tab's choice is heard too. The design marks a folded stack on
 *  the page's root: its rules read the mark on #hrui itself (`#hrui:not(.side-off)`) and on a box
 *  inside it (`#hrui .side-off`), so it goes on #hrui and on its frame. */
export function useSideOff(): [boolean, () => void] {
  const narrow = useMedia(`(max-width: ${OVERLAY_MAX}px)`);
  const [kept, setKept] = useState<Fold | null>(null);
  const [openedNarrow, setOpenedNarrow] = useState(false);
  useEffect(() => {
    const store = () => { try { return window.localStorage; } catch { return null; } };
    setKept(readFold(store()));
    const heard = (e: StorageEvent) => { if (e.key === STACK_KEY) setKept(readFold(store())); };
    window.addEventListener('storage', heard);
    return () => window.removeEventListener('storage', heard);
  }, []);
  // back at desktop width the kept choice rules again; a visit's opening does not carry over
  useEffect(() => { if (!narrow) setOpenedNarrow(false); }, [narrow]);
  const off = stackOff(kept, narrow, openedNarrow);
  useEffect(() => {
    const els = [document.getElementById('hrui'), document.querySelector('#hrui > .app')];
    els.forEach((el) => el?.classList.toggle('side-off', off));
    return () => els.forEach((el) => el?.classList.remove('side-off'));
  }, [off]);
  const toggle = () => {
    const t = toggled(kept, narrow, openedNarrow);
    setOpenedNarrow(t.openedNarrow);
    if (t.keep) {
      setKept(t.keep);
      let store: Storage | null = null;
      try { store = window.localStorage; } catch { /* none */ }
      writeFold(store, t.keep);
    }
  };
  return [off, toggle];
}

const PART_FAM: Record<string, string> = { plugin: 'plugin', skill: 'skill', mcp: 'mcp', env: 'tool' };

/** The Agent stack column (the design's full towerHtml): status, the tower with every brick named,
 *  the four optional parts by colour, and what each zone is (HarnessRouter, agent harness, model).
 *  Every brick, part and zone is a way into the Settings layer it is.
 *  `live`: the bricks a test's turn on this page is working through now (stackLive), so each layer
 *  lights as the turn reaches it; without one, a running task lights the layers it uses.
 *  `off` and `onToggle`: folded or open, as the page decides (sideTog); `focus`: beside Settings,
 *  the open layer, whose brick stays solid while the rest step back (setSide).
 *  While a new setup is being set up (start/build.ts): `now` is the status line the save says
 *  ("Saving · your setup"), and `drops` the bricks landing as each save answers. */
export function StackPanel({ r, live, off, onToggle, focus, now, drops }: {
  r: SetupRow; live?: string[] | null;
  off: boolean; onToggle: () => void; focus?: LayerKey;
  now?: React.ReactNode; drops?: Drops | null;
}) {
  const tower = live ? liveTower(r.tower, live) : r.tower;
  const st = tower.st;
  const built = LAYERS.filter((L) => st[L.key] === 'built' || st[L.key] === 'run').length;
  const running = runningNames(tower, !!live);
  // the parts HarnessRouter runs for it
  const subsOn = SUBS.filter(([k]) => st[k] === 'built' || st[k] === 'run').length;
  // what a part's slot names on hover: what a person added that is on (setupParts.ts), when every
  // one is named
  const names: Record<string, string[]> = {
    skill: r.added.skills.filter((x) => x.on).map((x) => x.name),
    plugin: recordNames(r.added.plugins) || [],
    mcp: r.added.tools.filter((x) => x.on).map((x) => x.name),
    env: [],
  };
  const logo = harnessLogoSrc(r.h.base);
  const zr = (z: string, kick: string, val: React.ReactNode, cls: string, tw: string) => (
    <div className="zr" data-zone={z}><button type="button" className="zr-b" data-tw={tw}><span className="zr-k">{kick}</span><span className={`zr-v${cls ? ` ${cls}` : ''}`}>{val}</span></button></div>
  );
  return (
    <aside className="agent-side" aria-label="Agent stack" data-focus={focus}>
      <div className="ins-h stack-h"><span>Agent stack</span><span className="stack-n">{built} of {LAYERS.length} layers</span>
        <button type="button" className="icon-btn side-tog" aria-expanded={!off} aria-label={`${off ? 'Show' : 'Hide'} agent stack`} title={`${off ? 'Show' : 'Hide'} agent stack`} onClick={onToggle}>
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={off ? 'M15 6l-6 6 6 6' : 'M9 6l6 6-6 6'} /></svg>
        </button>
      </div>
      {/* the status floats over the top of the illustration's room, so one line or two never moves it */}
      <div className="stack-art">
        <div className="now">
          {now ? <><span className="dot run" /><span>{now}</span></> : running.length ? <><span className="dot run" /><span><b>Running now</b> · {running.join(', ')}</span></>
            : <><span className="dot" /><span>Idle{r.lastAny ? ` · last task ${ago(r.lastAny)}` : ''}</span></>}
        </div>
        <div className="iso-wrap" aria-hidden="true" dangerouslySetInnerHTML={{ __html: isoSvg(tower, 24, true, false, drops || null) }} />
      </div>
      {/* the optional parts, as a person added them in Settings (setupParts.ts, scope 'added'): how
          many are on, never a built-in skill or tool; a part with none added says none yet */}
      <div className="parts" role="group" aria-label="Parts">
        {PARTS.map(([k, label]) => {
          const n = r.tower.parts[k];
          return n ? (
            <button key={k} type="button" className="part built" data-tw={k} title={names[k].length === n ? names[k].join(', ') : undefined}>
              <span className="part-ic" dangerouslySetInnerHTML={{ __html: partIcon('built', PART_FAM[k]) }} />
              <span className="part-n">{label}</span><small>{n} added</small>
            </button>
          ) : (
            <button key={k} type="button" className="part locked" data-partlock={k} title="Add it in Settings" aria-label={`${label}, none yet`}>
              <span className="part-ic" dangerouslySetInnerHTML={{ __html: partIcon('empty', '') }} />
              <span className="part-n">{label}</span>
            </button>
          );
        })}
      </div>
      <div className="zones">
        {zr('run', 'HarnessRouter', st.backend === 'run' ? 'Running a task' : `Included · ${subsOn} parts`, st.backend === 'run' ? 'run' : '', 'backend')}
        {zr('you', 'Agent harness', r.baseName ? <>{logo ? <img className="h-logo" src={logo} alt="" /> : null}{r.baseName}</> : 'Not chosen yet', '', 'b-runtime')}
        {zr('mdl', 'Model', r.h.defaultModel ? <span className="mono">{r.h.defaultModel}</span> : 'Harness default', '', 'model')}
      </div>
    </aside>
  );
}
