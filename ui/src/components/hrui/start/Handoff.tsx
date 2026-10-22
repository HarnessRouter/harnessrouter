'use client';
// The coding-agent guides (docs/uxuidesign/console-79: handSheet / handHtml): "Start in your
// codebase" and "Migrate an existing agent". Five steps, each a brick that is built once its step is
// done: copy the prompt, tell it what to build (or to migrate), create an API key, it builds, it
// connects. Steps 2 and 4 happen in the coding agent, where the console cannot see; step 5 reads the
// workspace: a setup that appears after the prompt was copied is the one the coding agent saved, and
// it is checked once a task from the app (an API key) has run on it. Nothing here is simulated.
//
// How step 5 hears of it. A setup is connected once a task has ended on it: the setup is new (it was
// not in the workspace when the guide opened, and was saved after the prompt was copied), so its tasks
// are the app's. Nothing pushes a save or a task's end to this sheet, so while it waits it reads the
// workspace's setups and each new setup's newest tasks every POLL_MS, and stops once all are connected.
// The steps are the list every coding-agent sheet draws (start/Steps): step 1 the copy step every one
// has (PromptStep) and step 3 the key step every one has (start/KeyStep).
//
// The sheet picks up where it was left while this tab is open; once it is done, or the person has
// gone to Harness Studio from it, it opens fresh. The key step is the exception: each time the sheet
// opens it starts at the name row, and a key made before is never shown as done (Richard, 10-18).
// The build still counts from the first key made from this guide, while that key works.
import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react';
import { useRouter } from 'next/navigation';
import { listCustom, type CustomHarness } from '@/lib/harness';
import { RUNNING } from '@/lib/revamp-data';
import { track } from '@/lib/analytics';
import { Sheet } from '../Sheet';
import { newestTasks } from '../setups';
import { copyFrom, useCopyConfirm } from './copy';
import { useWsKeys } from './keys';
import { KEY_BASE, KeyStep, type MadeKey } from './KeyStep';
import { HxStep, PromptStep, type StepState } from './Steps';
import { HX_SAMPLES, MOVE_LINE, handPrompt, setupPrompt } from './prompts';
import { openNewSetup } from './open';

export type HandKind = 'new' | 'move';

const X = <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>;
const CHECK = <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.6} aria-hidden="true"><path d="M5 12l5 5L20 7" /></svg>;
const COPY = <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V5a2 2 0 0 1 2-2h8" /></svg>;
/** The workspace's setups, and each new setup's newest tasks, read this often while the sheet waits
 *  for the setup the coding agent saves and its first task: neither has a push. */
export const POLL_MS = 5000;

interface Hand {
  copied: boolean; copiedAt: number;
  /** the workspace's setups when the guide was opened: anything else that appears is new */
  baseline: string[] | null;
  /** the newest key made from this guide, and when the first was made (the build started then) */
  keyId: string; keyAt: number;
  done: boolean; left: boolean;
}
const fresh = (): Hand => ({ copied: false, copiedAt: 0, baseline: null, keyId: '', keyAt: 0, done: false, left: false });
// one guide of each kind per tab, so closing and reopening keeps its place
const store: Partial<Record<HandKind, Hand>> = {};

interface Made { h: CustomHarness; connected: boolean }

export function Handoff({ kind, onClose }: { kind: HandKind; onClose: () => void }) {
  const router = useRouter();
  const mv = kind === 'move';
  const [h, setH] = useState<Hand>(() => {
    const was = store[kind];
    return was && !was.done && !was.left ? was : (store[kind] = fresh());
  });
  // the store leads, so a read in flight sees the guide as it is now
  const put = useCallback((patch: Partial<Hand>) => { const next = { ...(store[kind] || fresh()), ...patch }; store[kind] = next; setH(next); }, [kind]);
  const k = useWsKeys();
  const { copy, failed } = useCopyConfirm();
  const src = useRef<HTMLPreElement | null>(null);
  const moveLine = useRef<HTMLSpanElement | null>(null);
  const keyEntry = useRef<HTMLElement | null>(null);
  const [made, setMade] = useState<Made[]>([]);
  const [, tick] = useState(0);
  const prompt = mv ? setupPrompt() : handPrompt();

  // what the coding agent has saved: setups that were not in the workspace when the guide opened. A
  // read that fails changes nothing (the next one tries again); once connected, a setup stays connected
  const madeRef = useRef<Made[]>([]);
  const putMade = (next: Made[]) => { madeRef.current = next; setMade(next); };
  const readList = async () => {
    const list = await listCustom();
    if (!store[kind]?.baseline) put({ baseline: list.map((x) => x.id) });
    const cur = store[kind] || fresh();
    if (!cur.copied || !cur.baseline) return;
    const base = new Set(cur.baseline);
    const now = list.filter((x) => !base.has(x.id) && (x.createdAt || 0) >= cur.copiedAt - 60_000)
      .sort((a, b) => (a.createdAt || 0) - (b.createdAt || 0));
    const prev = madeRef.current;
    putMade(now.map((x) => ({ h: x, connected: !!prev.find((p) => p.h.id === x.id)?.connected })));
  };
  // one new setup's newest tasks: connected once a task has ended on it
  const readTasks = async (id: string) => {
    const page = await newestTasks(id);
    if (page.sessions.some((c) => !RUNNING.has(c.status || ''))) putMade(madeRef.current.map((m) => (m.h.id === id ? { ...m, connected: true } : m)));
  };
  const conn = made.filter((m) => m.connected).length;
  const ok = made.length > 0 && conn === made.length;
  const waiting = !ok;
  // the list: once when the guide opens (what was there), then, while it waits, the list and each new
  // setup's tasks
  useEffect(() => {
    if (h.baseline && !(h.copied && waiting)) return;
    let alive = true, timer: ReturnType<typeof setTimeout> | undefined;
    const step = async () => {
      await readList().catch(() => { /* the next read tries again */ });
      await Promise.all(madeRef.current.filter((m) => !m.connected).map((m) => readTasks(m.h.id).catch(() => { /* the next read tries again */ })));
      if (alive && store[kind]?.copied) timer = setTimeout(step, POLL_MS);
    };
    void step();
    return () => { alive = false; if (timer) clearTimeout(timer); };
  // the reads follow the guide's own state through `store`
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, !!h.baseline, h.copied, waiting]);
  // "Started N min ago" moves on by itself
  useEffect(() => { const t = setInterval(() => tick((n) => n + 1), 30_000); return () => clearInterval(t); }, []);

  useEffect(() => { if (ok && !h.done) put({ done: true }); }, [ok, h.done, put]);
  const a = made[0]?.h || null;
  // the build started with a key made from this guide, and goes on while that key works
  const started = !!h.keyAt && (!h.keyId || k.keys === null || k.keys.some((x) => x.id === h.keyId && !x.revoked));
  const d1 = h.copied, d5 = ok, d4 = started || d5;
  // step 3, the key step, is built once a key made in this opening is copied
  const st2: StepState = d4 ? 'built' : d1 ? 'next' : 'empty';
  const st4: StepState = d5 ? 'built' : d4 ? 'next' : 'empty';
  const st5: StepState = d5 ? 'built' : d1 && d4 ? 'next' : 'empty';

  const doCopy = () => copy(prompt, src, 'Copied. Paste it into your coding agent.', () => {
    put(h.copied ? {} : { copied: true, copiedAt: Date.now() });
    track('agents_guide_copied', { surface: mv ? 'start_migrate' : 'start_codebase' });
  });
  // the build started when the first key was copied; another key does not restart it
  const onKey = (m: MadeKey | null) => { if (m) put({ keyId: m.id, keyAt: store[kind]?.keyAt || Date.now() }); };
  const toStudio = (href: string) => { put({ left: true }); onClose(); router.push(href); };
  const toList = () => toStudio('/studio');
  // the setup your coding agent saved opens on its Tasks, as every setup just made does (start/open.ts)
  const openMade = (id: string) => { put({ left: true }); onClose(); openNewSetup(router, { id }); };

  const since = h.keyAt ? Math.max(0, Math.round((Date.now() - h.keyAt) / 60e3)) : null;
  const s2 = mv ? (
    <div className="hx-bub me"><span id="moveLine" ref={moveLine}>{MOVE_LINE}</span>
      <button type="button" className="icon-btn xs" aria-label="Copy this line" title="Copy" onClick={() => void copyFrom(MOVE_LINE, moveLine.current)}>{COPY}</button>
    </div>
  ) : (
    <div className="hx-bub me hx-ex" aria-label={`For example: ${HX_SAMPLES[0]}`}>
      <span className="hx-eg" aria-hidden="true">e.g.</span>
      <span className="hx-exs">{HX_SAMPLES.map((t, i) => <span key={i} className="hx-exl" style={{ '--i': i } as CSSProperties} aria-hidden="true">{t}</span>)}</span>
    </div>
  );
  const s3 = since == null ? null : <span className="hx-live"><i className="dot run" />Started {since < 1 ? 'just now' : `${since} min ago`}</span>;
  const checks: [boolean, string, string][] = mv
    ? [[made.length > 0, 'Saves a setup per feature', made.length ? `${made.length} created` : ''], [ok, 'Checks each with a real task', made.length ? `${conn} of ${made.length} connected` : '']]
    : [[!!a, 'Saves the setup', a ? a.id : ''], [ok, 'Checks it with a real task', ok ? 'Connected' : '']];
  let cur = -1;
  if (h.copied) for (let i = 0; i < checks.length; i++) if (!checks[i][0]) { cur = i; break; }
  const s5 = (
    <>
      <div className="hand-steps">
        {checks.map((x, i) => (
          <div key={i} className={`hs${x[0] ? ' on' : i === cur ? ' busy' : ''}`}><i>{x[0] ? CHECK : null}</i><span>{x[1]}</span><small>{x[2]}</small></div>
        ))}
      </div>
      {ok || !(d1 && d4) ? null : <div className="hx-wait"><button type="button" className="btn small primary" onClick={toList}>Go to Harness Studio →</button></div>}
    </>
  );

  return (
    // the key step takes focus when it is the step at hand, as the design's sheets focus their first
    // live control; otherwise the sheet itself, so a phone keeps its keyboard down
    <Sheet onClose={onClose} labelledBy="hdh" className="hand-sheet use-sheet" initialFocus={h.copied ? keyEntry : 'dialog'}>
      <div className="sheet-top">
        <h3 id="hdh">{mv ? 'Migrate an existing agent' : 'Start in your codebase'}</h3>
        <button type="button" className="icon-btn" aria-label="Close" onClick={onClose}>{X}</button>
      </div>
      <div className="hand">
        <ol className="hx">
          <PromptStep state={d1 ? 'built' : 'next'} text={prompt} preId="handSrc" preRef={src} copied={h.copied} failed={failed} onCopy={doCopy} />
          <HxStep n={2} state={st2} title={mv ? 'When it is ready, tell it to migrate' : 'When it asks, tell it what to build'} sum="Sent">{s2}</HxStep>
          <KeyStep n={3} k={k} surface={mv ? 'start_migrate' : 'start_codebase'} base={KEY_BASE} state={d1 ? 'next' : 'empty'} onKey={onKey} entry={keyEntry} />
          <HxStep n={4} state={st4} title={mv ? 'It moves your agents' : 'It builds your app'} sum={mv ? 'Moved' : 'Built'}>{s3}</HxStep>
          <HxStep n={5} state={st5} title={mv ? 'They connect to HarnessRouter' : 'It connects to HarnessRouter'}>{s5}</HxStep>
        </ol>
        <div className="hand-foot">
          {ok ? (mv
            ? <><span className="grow ok-t">{CHECK}All {made.length} connected</span><button type="button" className="btn small primary" onClick={() => toStudio('/studio')}>Open Harness Studio</button></>
            : <><span className="grow ok-t">{CHECK}Connected</span><button type="button" className="btn small primary" onClick={() => a && openMade(a.id)}>Open {a?.name}</button></>)
            : <span className="grow" />}
          <button type="button" className="link-q" onClick={onClose}>{ok ? 'Done' : 'Close'}</button>
        </div>
      </div>
    </Sheet>
  );
}
