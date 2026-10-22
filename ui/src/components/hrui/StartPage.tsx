'use client';
// Start (docs/uxuidesign/console-79, view `start`: startView, startAsk, startDemo, wayArt, wayPlay):
// the question, the box that answers it, then the three ways in side by side, each with its brick
// story. The box is the first way's own door: Continue opens "Set up an agent harness" with what you
// wrote. A demo task types its sentence into the box, so you see how to put it; Continue then opens
// it with the harness and model the design pairs with it, and saving makes a real setup like any other.
// The other two ways open the coding-agent setup guide and the migration guide.
import { useEffect, useRef, useState, type CSSProperties, type MouseEvent } from 'react';
import { useBases, useModelCatalog } from '@/lib/harness';
import { wayPic, type Way } from './start/art';
import { DEMOS, baseName, demoOf, demoPick } from './start/demos';
import { Handoff, type HandKind } from './start/Handoff';
import { NewSetup, type NewSetupPre } from './NewSetup';

const PLAY = <svg viewBox="0 0 10 10" aria-hidden="true"><path d="M2 1l7 4-7 4z" fill="currentColor" /></svg>;
// the stories play once, on the first Start of this tab (the design's stPlayedAt)
let playedAt = 0;
// a hover replays a way's story, at most once every 2.6 s
const lastPlay = new WeakMap<Element, number>();

function Pic({ kind, play }: { kind: Way; play: boolean }) {
  const [svg] = useState(() => wayPic(kind, play));
  return <span className="sg-art" aria-hidden="true" dangerouslySetInnerHTML={{ __html: svg }} />;
}

function replay(e: MouseEvent<HTMLElement>) {
  const a = e.currentTarget.querySelector<SVGSVGElement>('.wa');
  const now = Date.now();
  if (!a || now - (lastPlay.get(a) || 0) < 2600) return;
  lastPlay.set(a, now);
  a.style.setProperty('--wd', '0');
  a.classList.remove('play');
  void a.getBoundingClientRect();
  a.classList.add('play');
}

export function StartPage() {
  const bases = useBases();
  const catalog = useModelCatalog();
  const [play] = useState(() => { if (!playedAt) playedAt = Date.now(); return Date.now() - playedAt < 400; });
  const [ask, setAsk] = useState('');
  const [typingDemo, setTypingDemo] = useState<number | null>(null);
  const [pulse, setPulse] = useState(false);
  const [nw, setNw] = useState<NewSetupPre | null>(null);
  const [hand, setHand] = useState<HandKind | null>(null);
  const ta = useRef<HTMLTextAreaElement | null>(null);
  const go = useRef<HTMLButtonElement | null>(null);
  const box = useRef<HTMLDivElement | null>(null);
  const typeTok = useRef(0);
  useEffect(() => () => { typeTok.current++; }, []);
  // where the cursor goes once a demo has typed its sentence: moved after the render that ends the typing, as
  // Continue is disabled until then and focusing a disabled button does nothing (on a phone the cursor stayed
  // on the demo task's button)
  const focusAfterDemo = useRef<'box' | 'go' | null>(null);
  useEffect(() => {
    const where = focusAfterDemo.current;
    if (typingDemo != null || !where) return;
    focusAfterDemo.current = null;
    if (where === 'go') { go.current?.focus(); return; }
    const el = ta.current;
    if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); }
  }, [typingDemo]);

  // the box grows with what is written, up to a point
  useEffect(() => { const el = ta.current; if (el) { el.style.height = 'auto'; el.style.height = Math.min(el.scrollHeight + 2, 240) + 'px'; } }, [ask]);

  // the first way starts in the box above it: a click on its card (not on a demo task) puts the cursor there, at the end of
  // anything already written (Richard, 10-21: the card did nothing when clicked)
  const focusAsk = () => {
    const el = ta.current;
    if (!el) return;
    el.focus();
    el.setSelectionRange(el.value.length, el.value.length);
    box.current?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' });
  };
  const startAsk = () => {
    const v = ask.trim();
    if (!v) return;
    typeTok.current++;
    const di = demoOf(v);
    setNw(di >= 0 ? { demo: di } : { job: v });
  };

  // a demo writes its sentence into the box, as if someone were typing it; reduced motion gets it at once
  const startDemo = (i: number) => {
    const txt = DEMOS[i].instr, tok = ++typeTok.current;
    setTypingDemo(i); setPulse(false);
    const bx = box.current;
    if (bx) { const r = bx.getBoundingClientRect(); if (r.top < 0 || r.bottom > window.innerHeight) bx.scrollIntoView({ block: 'center', behavior: 'smooth' }); }
    const fin = () => {
      focusAfterDemo.current = window.innerWidth > 700 ? 'box' : 'go';
      setTypingDemo(null); setPulse(true);
    };
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) { setAsk(txt); setTimeout(fin, 0); return; }
    const step = Math.max(1, Math.ceil(txt.length / 46));
    let k = 0;
    setAsk('');
    const tick = () => {
      if (typeTok.current !== tok) return;
      k = Math.min(txt.length, k + step);
      setAsk(txt.slice(0, k));
      if (k < txt.length) setTimeout(tick, 16); else fin();
    };
    tick();
  };

  const onDemo = typingDemo ?? demoOf(ask);
  const titleOf = (i: number) => {
    if (!catalog) return undefined;
    const p = demoPick(i, bases);
    if (!p.base) return `${baseName(DEMOS[i].base, bases)} is not available to you`;
    return p.model ? `${baseName(p.base, bases)} · ${p.model}` : baseName(p.base, bases);
  };

  return (
    <div className="scroll">
      <div className="sg sg5">
        <header className="sg-head">
          <p className="sg-eye">Three ways to start</p>
          <h1 className="sg-q"><label htmlFor="stAsk">What do you want to ship to your users?</label></h1>
        </header>
        <div ref={box} className="st-ask-box sg-ask">
          <textarea ref={ta} id="stAsk" rows={1} placeholder="e.g. Support replies: look up the order, then draft an answer in our tone." value={ask}
            onChange={(e) => { typeTok.current++; setTypingDemo(null); setAsk(e.target.value); }}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); startAsk(); } }} />
          <div className="st-ask-bar">
            <span className="st-ask-n" id="stAskN" />
            <button ref={go} type="button" className={`btn primary${pulse ? ' pulse' : ''}`} id="stAskGo" disabled={!ask.trim() || typingDemo != null} onClick={startAsk}>Continue</button>
          </div>
        </div>
        <div className="sg-tiles">
          <section className="tile tile-demo sg-way sg-main" style={{ '--wd': 0 } as CSSProperties} aria-labelledby="sgMainT" onMouseEnter={replay}
            onClick={(e) => { if (!(e.target as HTMLElement).closest('button, a')) focusAsk(); }}>
            <Pic kind="hr" play={play} />
            <h2 className="sg-tt" id="sgMainT">Start in HarnessRouter</h2>
            <p className="sg-d"><span className="sg-d1">Choose an agent harness and model, run a task, and see the full trace.</span> <span className="sg-d2">Then your coding agent connects it to your app.</span></p>
            <div className="sg-ex">
              <span className="sg-exl">Pick a demo task</span>
              <div className="td-list">
                {DEMOS.map((d, i) => (
                  <button key={i} type="button" className={`td${onDemo === i ? ' on' : ''}`} aria-pressed={onDemo === i} title={titleOf(i)} onClick={() => startDemo(i)}>
                    <span className="hx-play" aria-hidden="true">{PLAY}</span><b>{d.from}</b><span>→ {d.to}</span>
                  </button>
                ))}
              </div>
            </div>
          </section>
          <button type="button" className="tile sg-way sg-side" style={{ '--wd': 1 } as CSSProperties} onMouseEnter={replay} onClick={() => setHand('new')}>
            <Pic kind="build" play={play} />
            <span className="sg-go" aria-hidden="true">›</span>
            <h2 className="sg-tt">Start in your codebase</h2>
            <p className="sg-d"><span className="sg-d1">Use the setup guide with your coding agent to build a new agent feature in your app</span> <span className="sg-d2">and connect the app to HarnessRouter.</span></p>
          </button>
          <button type="button" className="tile sg-way sg-side" style={{ '--wd': 2 } as CSSProperties} onMouseEnter={replay} onClick={() => setHand('move')}>
            <Pic kind="move" play={play} />
            <span className="sg-go" aria-hidden="true">›</span>
            <h2 className="sg-tt">Migrate an existing agent</h2>
            <p className="sg-d"><span className="sg-d1">Use the migration guide with your coding agent to move your existing agent’s execution to HarnessRouter</span> <span className="sg-d2">while keeping your app and user experience.</span></p>
          </button>
        </div>
      </div>
      {nw ? <NewSetup pre={nw} onClose={() => setNw(null)} /> : null}
      {hand ? <Handoff kind={hand} onClose={() => setHand(null)} /> : null}
    </div>
  );
}
