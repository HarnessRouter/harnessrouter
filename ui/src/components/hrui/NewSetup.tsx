'use client';
// "Set up an agent harness" (docs/uxuidesign/console-91: openNewAgent / newAgentHtml in its one-step
// form, nwPickHtml, placeDD, nwArt, nwMsg, then buildAgent and the save card, backendShow / buildSeq).
// Say what the setup does for your users in one sentence; the agent harness and the model start on
// Auto and can be chosen. Sending sets up a harness CONFIGURATION, never a task (Richard, 2026-10-18):
//
//   1. the sheet closes and the setup's page opens at once (Richard, 2026-10-19: the build plays in
//      the chat, not in the popup). The work goes on there (start/build.ts): the server builds the
//      setup under the tab's key for it (start/compose.ts, /v1/harnesses/builds): its builder, run on
//      one of the person's own models, turns the sentence into a configuration (a name, standing
//      instructions written for serving each end user's request, the harness and model where they
//      were left on Auto, the skills, plugins and tools the job needs from the workspace, and one
//      request as an end user would send it) and saves it, while one live line says which step it is
//      on; the save card then shows it at the top of the first task, and the example request waits in
//      its box, ready to send (Richard, 2026-10-19: nothing runs until the person sends it). An
//      unchanged demo with a recorded first run is preset from its template and plays that run back
//      when its request is sent (start/replay.ts), which reaches no server and spends nothing.
//
// The sentence is never sent to the setup, nor saved as its instructions. When the server's build
// fails, nothing was saved and nothing is saved in its place: the page says why with Try again, which
// opens this sheet again with the sentence as it was written (a new build, under a new key).
//
// The builder and every setup run on this instance's own model keys: with no key that runs a model,
// the line under the box says to connect one, and Save waits (the hosted console's request check and
// free requests are not part of this edition).
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { useRouter } from 'next/navigation';
import { offeredOob, oobById, oobDefaultModel, useBasesRead, useModelCatalogRead } from '@/lib/harness';
import { providerById, useModelProviders } from '@/lib/providers';
import { harnessLogoSrc } from '@/components/HarnessLogo';
import { Sheet } from './Sheet';
import { SkLine } from './Skel';
import { toast } from './toast';
import { nwArt } from './start/art';
import { startBuild } from './start/build';
import { openNewSetup } from './start/open';
import { AUTO } from './start/compose';
import { DEMOS, baseName, demoPick, runnableModels } from './start/demos';
import { Handoff } from './start/Handoff';
import { tooShort } from './start/names';

export interface NewSetupPre { job?: string; demo?: number }

const X = <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>;
const CHEV = <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.4} aria-hidden="true"><path d="M6 9l6 6 6-6" /></svg>;
const CHECK = <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.6} aria-hidden="true"><path d="M5 12l5 5L20 7" /></svg>;
const UP = <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.4} aria-hidden="true"><path d="M12 19V5M5 12l7-7 7 7" /></svg>;
const LOCK = <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} aria-hidden="true"><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></svg>;
const NW_SAMPLES = ['Answer support emails: look up the order, then draft a reply in our tone.', 'Review a contract and flag the risky clauses.', 'Turn a product brief into a studio product image.'];
const SENTENCE = 'Write it as a sentence, e.g. Answer support emails in our tone.';
// Auto picks among the general agent harnesses the platform can pay a first test on: not one that
// takes no skills (a decision model), nor one that runs on the organization's own token alone
// (setup_check.NO_FREE_BASES on the server, which makes the same choice).
const OWN_TOKEN_ONLY = ['qoder'];

/** Reads like a change to the person's own code: say once where that belongs, without blocking. */
function codeAsk(t: string): boolean {
  const x = String(t || '');
  if (/\bagent\b/i.test(x)) return false;
  return /\b(add|build|implement|refactor|set up|integrate|scaffold|create|make|fix)\b[^.]{0,40}\b(to|in|into)\s+(my|our)\s+(next\.?js|react|vue|svelte|rails|django|flask|laravel|ios|android|app|codebase|repo|repository|website|site|frontend|backend|project|code)\b/i.test(x)
    || /\b(build|make|create)\s+(me\s+)?(a|an)\s+[a-z\- ]{0,24}\b(app|website|landing page|site)\b/i.test(x);
}

type Pick = 'h' | 'm' | null;

export function NewSetup({ pre, onClose }: { pre?: NewSetupPre; onClose: () => void }) {
  const router = useRouter();
  // the page Save opens is fetched while the sheet is open, so pressing Save needs nothing more from
  // the server to get there (a page load on the way is still picked up there: start/build.ts)
  useEffect(() => { router.prefetch('/studio/new'); }, [router]);
  const basesRead = useBasesRead();
  const catalogRead = useModelCatalogRead();
  const bases = basesRead.value;
  const catalog = catalogRead.value;
  const providers = useModelProviders();
  const offered = offeredOob(bases);
  const demo = pre?.demo != null && DEMOS[pre.demo] ? pre.demo : null;
  const [job, setJob] = useState(() => (demo != null ? DEMOS[demo].instr : pre?.job || ''));
  // Auto unless a demo names its pair; a demo's model lands with the catalog
  // a demo opens on its own harness when the server offers it; else on Auto (the page says the demo's
  // harness is not available), never another harness in its place
  const [h, setH] = useState(() => (demo != null ? demoPick(demo, bases).base || AUTO : AUTO));
  const [m, setM] = useState(() => (demo != null ? '' : AUTO));
  const [pick, setPick] = useState<Pick>(null);
  const [q, setQ] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [hand, setHand] = useState(false);
  // the sheet was closed: nothing more happens
  const gone = useRef(false);
  const ta = useRef<HTMLTextAreaElement | null>(null);
  const btnH = useRef<HTMLButtonElement | null>(null);
  const btnM = useRef<HTMLButtonElement | null>(null);
  const pop = useRef<HTMLDivElement | null>(null);
  const qIn = useRef<HTMLInputElement | null>(null);
  const [pos, setPos] = useState<{ style: CSSProperties; side: boolean } | null>(null);

  useEffect(() => () => { gone.current = true; }, []);
  // a demo's model, once the server's catalog has landed: its own when the harness runs it
  useEffect(() => {
    if (!catalog || !h || m) return;
    const dp = demo != null ? demoPick(demo, bases) : null;
    setM(dp && dp.base && dp.base === h ? dp.model || AUTO : AUTO);
  }, [catalog, h, m, demo, bases]);
  // the caret goes to the end of the sentence on a desktop; a phone keeps its keyboard down
  useEffect(() => {
    const t = setTimeout(() => { const d = ta.current; if (d && window.innerWidth > 700) { d.focus(); d.setSelectionRange(d.value.length, d.value.length); } }, 40);
    return () => clearTimeout(t);
  }, []);

  const hAuto = h === AUTO, mAuto = m === AUTO;
  const hName = h && !hAuto ? baseName(h, bases) : '';
  // the harnesses Auto may pick, as the server's composer reads them
  const autoBases = useMemo(() => offeredOob(bases).filter((o) => bases?.[o.id]?.takesSkills !== false && !OWN_TOKEN_ONLY.includes(o.id)).map((o) => o.id), [bases]);
  // the models on offer: the harness's own, or with the harness on Auto every model one of Auto's harnesses runs
  const models = useMemo(() => {
    if (!catalog) return [];
    if (!hAuto) return h ? runnableModels(h) : [];
    const out: string[] = [];
    for (const b of autoBases) for (const x of runnableModels(b)) if (!out.includes(x)) out.push(x);
    return out;
  }, [h, hAuto, catalog, autoBases]);
  const dp = demo != null ? demoPick(demo, bases) : null;
  const demoNow = demo != null && dp && job.trim() === DEMOS[demo].instr && h === dp.base && m === dp.model ? demo : null;
  const code = codeAsk(job);
  // a model one of this instance's keys runs: on a harness Auto may pick, on any harness, on the one chosen
  const runs = (b: string) => runnableModels(b).length > 0;
  const anyRuns = !!catalog && autoBases.some(runs);
  const noneRuns = !!catalog && !offered.some((o) => runs(o.id));
  const hRuns = !!catalog && !!h && !hAuto && runs(h);
  const ready = offered.length > 0 && !!catalog && !!h && !!m && (hAuto ? anyRuns : hRuns);

  // the drawing: a brick drops in when its choice changes
  const artH = hName, artM = mAuto ? '' : m;
  const prev = useRef({ h: '', m: '' });
  const dropH = !!artH && artH !== prev.current.h, dropM = !!artM && (artM !== prev.current.m || dropH);
  useEffect(() => { prev.current = { h: artH, m: artM }; });
  const art = useMemo(() => nwArt({ h: artH, m: artM, dropH, dropM, parts: { skill: 0, plugin: 0, tool: 0 } }), [artH, artM, dropH, dropM]);

  // the open list sits beside the button it belongs to, top-aligned with it; below (or above) it when
  // the window has no room on the right (the design's placeDD)
  const place = useCallback(() => {
    const bt = pick === 'h' ? btnH.current : pick === 'm' ? btnM.current : null;
    if (!bt) { setPos(null); return; }
    const r = bt.getBoundingClientRect(), vh = window.innerHeight, vw = window.innerWidth, sh = bt.closest('.sheet');
    const sx = sh ? sh.getBoundingClientRect().right - 12 : vw - 12, room = sx - (r.right + 10);
    const w = room >= 216 ? Math.min(264, room) : Math.min(240, vw - 24), side = r.right + 10 + w <= vw - 12;
    if (side) {
      let top = Math.max(12, r.top - 7), mh = Math.min(328, vh - top - 16);
      if (mh < 240) { top = Math.max(12, vh - 16 - 328); mh = Math.min(328, vh - top - 16); }
      setPos({ side, style: { left: r.right + 10, top, bottom: 'auto', width: w, maxHeight: mh } });
    } else {
      const left = Math.min(Math.max(12, r.left), vw - w - 12), below = vh - r.bottom - 16, above = r.top - 16, up = below < 220 && above > below;
      const mh = Math.max(160, Math.min(328, up ? above : below));
      setPos({ side, style: { left, width: w, maxHeight: mh, ...(up ? { top: 'auto', bottom: vh - r.top + 6 } : { bottom: 'auto', top: r.bottom + 6 }) } });
    }
  }, [pick]);
  useLayoutEffect(() => { place(); }, [place]);
  useEffect(() => {
    if (!pick) return;
    const sh = (pick === 'h' ? btnH.current : btnM.current)?.closest('.sheet');
    const down = (e: MouseEvent) => {
      const t = e.target as Node;
      if (pop.current?.contains(t) || btnH.current?.contains(t) || btnM.current?.contains(t)) return;
      setPick(null);
    };
    window.addEventListener('resize', place);
    sh?.addEventListener('scroll', place, { passive: true });
    document.addEventListener('mousedown', down);
    return () => { window.removeEventListener('resize', place); sh?.removeEventListener('scroll', place); document.removeEventListener('mousedown', down); };
  }, [pick, place]);
  // the search box takes focus as the list opens
  useEffect(() => { if (pick && pos) qIn.current?.focus(); }, [pick, pos]);

  const toggle = (k: 'h' | 'm') => { if (busy) return; setQ(''); setPick((p) => (p === k ? null : k)); };
  const closePick = () => { const b = pick === 'h' ? btnH.current : btnM.current; setPick(null); setQ(''); b?.focus(); };
  const chooseH = (id: string) => {
    if (id !== h) {
      // a chosen model the new harness does not run gives way to Auto, and says so
      const runs = (b: string) => runnableModels(b).includes(m);
      if (!mAuto && m && (id === AUTO ? !autoBases.some(runs) : !runs(id))) {
        toast(id === AUTO ? `No harness Auto picks from runs ${m}. Model set to Auto.` : `${baseName(id, bases)} doesn’t run ${m}. Model set to Auto.`);
        setM(AUTO);
      }
      setH(id);
    }
    closePick();
  };
  const chooseM = (id: string) => { setM(id); closePick(); };
  const close = () => { gone.current = true; onClose(); };

  const send = async () => {
    const j = job.trim();
    if (!j || busy) return;
    if (demoNow == null && tooShort(j)) { setErr(SENTENCE); ta.current?.focus(); return; }
    if (!ready) return;
    setPick(null); setBusy(true); setErr(''); gone.current = false;
    // the sheet closes and the setup's page opens at once: the rest happens there (start/build.ts), and
    // the only place it lands is that setup's Tasks (start/open.ts). Auto goes to the server as is: it
    // picks the harness and model, never a guess made here
    const b = startBuild({
      job: j, base: h, model: m, demo: demoNow, baseName: baseName(h, bases),
      pick: { baseName: hAuto ? '' : hName, model: mAuto ? '' : m },
    });
    openNewSetup(router, { build: b.key });
  };

  if (hand) return <Handoff kind="new" onClose={onClose} />;

  const ql = q.trim().toLowerCase();
  const hs = offered.filter((o) => !ql || baseName(o.id, bases).toLowerCase().includes(ql));
  const ms = models.filter((x) => x !== AUTO && (!ql || x.toLowerCase().includes(ql)));
  const def = hAuto ? '' : oobDefaultModel(oobById(h));
  const keyOf = (x: string) => { const c = providers.connectionFor(x); return c ? (providerById(c.provider)?.name || c.provider) : ''; };
  const logo = (id: string) => { const s = harnessLogoSrc(id); return s ? <img className="h-logo" src={s} alt="" /> : null; };
  const onKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    const first = pop.current?.querySelector<HTMLButtonElement>('.dd-o');
    if (e.key === 'Enter') { e.preventDefault(); first?.click(); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); first?.focus(); }
  };
  const autoRow = (on: boolean, choose: () => void) => (!ql ? (
    <button type="button" className={`nw-opt dd-o${on ? ' on' : ''}`} role="option" aria-selected={on} onClick={choose}>
      <span className="chk">{on ? CHECK : null}</span><b>Auto</b><small>picked for the job</small>
    </button>
  ) : null);
  const list = pick && pos ? (
    <div ref={pop} className={`nw-pop pl-dd pl-fly${pos.side ? ' side' : ''}`} style={pos.style} role="listbox" aria-label={pick === 'h' ? 'Agent harness' : 'Model'}>
      <div className="dd-s">
        <input ref={qIn} id="ddQ" className="dd-q" autoComplete="off" spellCheck={false} value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={onKey}
          placeholder={pick === 'h' ? `Search ${offered.length} agent harnesses` : hAuto ? `Search ${models.length} models` : `Search ${models.length} models on ${hName}`}
          aria-label={pick === 'h' ? 'Search agent harnesses' : 'Search models'} />
      </div>
      {pick === 'h' ? (
        <>
          {autoRow(hAuto, () => chooseH(AUTO))}
          {hs.map((o) => {
            const on = o.id === h;
            return (
              <button key={o.id} type="button" className={`nw-opt dd-o${on ? ' on' : ''}`} role="option" aria-selected={on} onClick={() => chooseH(o.id)}>
                <span className="chk">{on ? CHECK : null}</span><b className="dd-hb"><span className="dd-hn">{logo(o.id)}{baseName(o.id, bases)}</span></b>
              </button>
            );
          })}
          {hs.length ? null : <p className="dd-none">No harness matches.</p>}
          <p className="dd-foot">{LOCK}Fixed once saved</p>
        </>
      ) : (
        <>
          {autoRow(mAuto, () => chooseM(AUTO))}
          {ms.map((x) => {
            const on = x === m, kp = keyOf(x);
            return (
              <button key={x} type="button" className={`nw-opt dd-o${on ? ' on' : ''}`} role="option" aria-selected={on} onClick={() => chooseM(x)}>
                <span className="chk">{on ? CHECK : null}</span><b className="mono">{x}</b>
                {x === def ? <small>default</small> : kp ? <small>your {kp} key</small> : null}
              </button>
            );
          })}
          {ms.length ? null : <p className="dd-none">{!catalog ? 'Checking providers…' : models.length ? 'No model matches.' : 'No model can run here yet.'}</p>}
        </>
      )}
    </div>
  ) : null;

  // loading is drawn as the line that lands (Skel), never a sentence about loading
  const sk = (label: string) => <><SkLine w="58%" h={12} style={{ marginTop: 4 }} /><span className="sr">{label}</span></>;
  const msg: [string, React.ReactNode] = err ? ['bad', err]
    : basesRead.failed || catalogRead.failed ? ['bad', <>The agent harnesses could not be read just now.{' '}
      <button type="button" className="link-q inl" onClick={() => { basesRead.retry(); catalogRead.retry(); }}>Try again</button></>]
    : bases && !offered.length ? ['bad', <>No agent harness is available on this instance.</>]
    // nothing runs without a model key: the builder and the setup both run on one of yours
    : catalog && bases && (noneRuns || (hAuto && !anyRuns)) ? ['warn', <>Connect a model key to set up an agent harness. <a className="link-q inl" href="/byok">Connect a key</a></>]
    : catalog && h && !hAuto && !hRuns ? ['warn', <>None of your keys runs a model on {hName} yet. <a className="link-q inl" href="/byok">Add a key</a> or choose another harness.</>]
    : code ? ['warn', <><b>Changing code in your project?</b> Your coding agent does that.</>]
    : demo != null && bases && dp && !dp.base ? ['warn', <>{`${baseName(DEMOS[demo].base, bases)} is not available to you, so Auto picks the harness.`}</>]
    : !bases || !catalog ? ['', sk('Loading')]
    : ['', null];
  const pickH = hAuto ? <span>Auto</span> : <>{h ? logo(h) : null}<span>{hName}</span></>;
  const pickM = mAuto ? <span>Auto</span> : <span className="mono">{m}</span>;
  return (
    // Escape closes an open list first, then the sheet
    <Sheet onClose={() => { if (pick) closePick(); else close(); }} labelledBy="nwh"
      className={`nw-sheet nw-q${code ? ' code-ask' : ''}`} initialFocus="dialog">
      <div className="sheet-top">
        <div><h3 id="nwh">Set up an agent harness</h3></div>
        <button type="button" className="icon-btn" aria-label="Close" onClick={close}>{X}</button>
      </div>
      <div className="nw-build">
        <span className="nw-art" id="nwArt" dangerouslySetInnerHTML={{ __html: art }} />
        <div className="nw-picks" id="nwPicks">
          <button ref={btnH} type="button" className={`nw-pk${pick === 'h' ? ' on' : ''}`} aria-haspopup="listbox" aria-expanded={pick === 'h'}
            disabled={busy} onClick={() => toggle('h')}>
            <span>Agent harness</span><b>{pickH}</b>{CHEV}
          </button>
          <button ref={btnM} type="button" className={`nw-pk${pick === 'm' ? ' on' : ''}`} aria-haspopup="listbox" aria-expanded={pick === 'm'}
            disabled={busy} onClick={() => toggle('m')}>
            <span>Model</span><b>{pickM}</b>{CHEV}
          </button>
          {list}
        </div>
      </div>
      <>
          <label className="nw-l" htmlFor="nwJob">What should it do for your users?</label>
          <div className="nw-ask">
            <div className="nw-field">
              <textarea ref={ta} id="nwJob" className="nw-in" rows={3} placeholder=" " aria-describedby="nwCost"
                aria-invalid={err === SENTENCE ? true : undefined}
                value={job} readOnly={busy}
                onChange={(e) => { setJob(e.target.value); if (err) setErr(''); }}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(); } }} />
              <div className="nw-ph" aria-hidden="true">
                {NW_SAMPLES.map((t, i) => <span key={i} className="hx-exl" style={{ '--i': i } as CSSProperties}>e.g. {t}</span>)}
              </div>
            </div>
            <div className="nw-ask-bar">
              <span aria-hidden="true" />
              <button type="button" className="send" id={demoNow != null ? 'nwBuild' : 'nwSend'} aria-label="Save setup"
                aria-busy={busy || undefined} disabled={!job.trim() || busy || !ready} onClick={() => void send()}>{UP}</button>
            </div>
          </div>
          <div className={`nw-cost nw-msg ${msg[0]}`} id="nwCost" role="status">{msg[1]}</div>
          <div className="au-or nw-or" role="separator"><span>OR</span></div>
          <div className="nw-alt">
            <span><b>Building in your own codebase?</b></span>
            <button type="button" className="link-q inl" disabled={busy} onClick={() => setHand(true)}>Use your coding agent ›</button>
          </div>
      </>
    </Sheet>
  );
}
