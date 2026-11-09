'use client';
// A setup's own memory, as the service chose it for the agent (the memories spec, A1 and C1): on a new setup's save card
// one line, "Memory: <Engine>, <why>", and Change, which offers the four engines and None in a small menu; in its
// Settings the same choice as a list (EngineList). Drawn from the setup's record, so what is drawn is what was saved. A service before 0.40 says nothing of an
// agent's memory, and then nothing is drawn.
import { useCallback, useEffect, useRef, useState } from 'react';
import { getAgentMemory, getHarnessMemories, setAgentMemory, type AgentMemoryRead, type MemoryChoice } from '@/lib/memories';
import { announceHarnessMemories } from '../setup/harnessMemories';
import { plain } from '../setup/settingsModel';
import { toast } from '../toast';
import { after, useDismiss, useProviders } from './parts';
import { VENDORS, vendorName } from './vendors';
import './memories.css';

const SAID = 'hrui:agent-memory';

/** The engine a person reads, and why: the service's own sentence. */
export function lineOf(r: AgentMemoryRead): { engine: string; why: string } {
  return r.memory ? { engine: vendorName(r.memory.engine), why: r.memory.reason || r.reason } : { engine: 'None', why: r.reason };
}

/** Read a setup's memory again and tell every view of it (after something else changed it: a rename it followed). */
export async function announceAgentMemory(hid: string): Promise<void> {
  const r = await getAgentMemory(hid);
  if (r) window.dispatchEvent(new CustomEvent(SAID, { detail: { hid, r } }));
}

/** One setup's memory: undefined while it is read, or where the service doesn't say (`said` false). Every view of the
 *  same setup hears a change made in any of them. */
export function useAgentMemory(hid: string | null | undefined) {
  const [read, setRead] = useState<AgentMemoryRead | undefined>(undefined);
  const [said, setSaid] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const take = useCallback((r: AgentMemoryRead | undefined) => { setRead(r); setSaid(r !== undefined); }, []);
  useEffect(() => {
    if (!hid) { setRead(undefined); setSaid(null); return undefined; }
    let live = true;
    getAgentMemory(hid).then((r) => { if (live) take(r); }).catch(() => { if (live) setSaid(false); });
    const heard = (e: Event) => {
      const d = (e as CustomEvent<{ hid: string; r: AgentMemoryRead }>).detail;
      if (live && d?.hid === hid) take(d.r);
    };
    window.addEventListener(SAID, heard);
    return () => { live = false; window.removeEventListener(SAID, heard); };
  }, [hid, take]);
  /** Give the agent this memory, or none. True once saved; a refusal is said in the service's words. */
  const set = useCallback(async (choice: MemoryChoice, done?: string): Promise<boolean> => {
    if (!hid || busy) return false;
    setBusy(true);
    try {
      const r = await setAgentMemory(hid, choice);
      take(r);
      if (r) window.dispatchEvent(new CustomEvent(SAID, { detail: { hid, r } }));
      // the Agent stack counts what the agent holds: it hears the change too
      getHarnessMemories(hid).then((d) => announceHarnessMemories(hid, d)).catch(() => {});
      if (done) toast(done);
      return true;
    } catch (e) {
      toast(plain(e, 'The memory was not changed. Try again.'));
      return false;
    } finally { setBusy(false); }
  }, [hid, busy, take]);
  return { read, said, busy, set };
}

/** Change: the four engines and None, in a small menu. An engine not running here is shown, and not offered. */
export function EngineMenu({ current, busy, onPick, label = 'Change' }: {
  current: string | null; busy?: boolean; onPick: (choice: MemoryChoice) => void; label?: string;
}) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLSpanElement | null>(null);
  const close = useCallback(() => setOpen(false), []);
  useDismiss(open, wrap, close);
  const { providers } = useProviders();
  const running = (id: string) => !providers || !!providers.find((p) => p.id === id)?.connected;
  const pick = (c: MemoryChoice) => { setOpen(false); onPick(c); };
  return (
    <span className="mm-popw am-menu" ref={wrap}>
      <button type="button" className="link-q inl" aria-haspopup="menu" aria-expanded={open} disabled={busy} onClick={() => setOpen(!open)}>{label}</button>
      {open ? (
        <div className="mm-pop am-pop" role="menu" aria-label="Engine">
          {Object.keys(VENDORS).map((id) => {
            const on = current === id, can = running(id);
            return (
              <button key={id} type="button" role="menuitemradio" aria-checked={on} className={`mm-mi${on ? ' on' : ''}`} disabled={!can || on}
                onClick={() => pick({ engine: id })}>
                <b>{vendorName(id)}</b><small>{can ? VENDORS[id].line : 'Not running here'}</small>
              </button>
            );
          })}
          <div className="mm-pop-sep" />
          <button type="button" role="menuitemradio" aria-checked={current === ''} className={`mm-mi${current === '' ? ' on' : ''}`} disabled={current === ''}
            onClick={() => pick('none')}>
            <b>None</b><small>Every task starts from nothing.</small>
          </button>
        </div>
      ) : null}
    </span>
  );
}

/** The engine an agent's memory is kept by, as a list in its Settings (Richard 11-09: never behind a click): the four
 *  engines and None, each with what kind of memory it keeps, the current one picked and why it was chosen said under
 *  it. An engine not running here is shown, and can't be picked. Picking is `onPick`'s to confirm and do. */
export function EngineList({ current, why, busy, onPick }: {
  current: string; why?: string; busy?: boolean; onPick: (choice: MemoryChoice) => void;
}) {
  const { providers } = useProviders();
  const running = (id: string) => !providers || !!providers.find((p) => p.id === id)?.connected;
  // arrows move along the list as in any group of radio buttons; picking stays a press, since it asks first
  const onKey = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const d = e.key === 'ArrowDown' || e.key === 'ArrowRight' ? 1 : e.key === 'ArrowUp' || e.key === 'ArrowLeft' ? -1 : 0;
    if (!d) return;
    const all = Array.from(e.currentTarget.querySelectorAll<HTMLButtonElement>('[role=radio]:not(:disabled)'));
    const at = all.indexOf(document.activeElement as HTMLButtonElement);
    if (!all.length) return;
    e.preventDefault();
    all[(at + d + all.length) % all.length].focus();
  };
  const row = (id: string, name: string, line: string, can: boolean) => {
    const on = current === id;
    return (
      <button key={id || 'none'} type="button" role="radio" aria-checked={on} disabled={busy || !can}
        className={`mm-eng-o${on ? ' on' : ''}${can ? '' : ' off'}`} onClick={() => { if (!on) onPick(id ? { engine: id } : 'none'); }}>
        <i className="mm-eng-dot" aria-hidden="true" />
        <span className="mm-eng-t">
          <span className="mm-eng-n"><b>{name}</b>{can ? null : <span className="mm-eng-nr">Not running here</span>}</span>
          {line ? <small>{line}</small> : null}
          {on && why ? <small className="mm-eng-why">{why}</small> : null}
        </span>
      </button>
    );
  };
  return (
    <div className="mm-engs am-engs" role="radiogroup" aria-label="Engine" onKeyDown={onKey}>
      {Object.keys(VENDORS).map((id) => row(id, vendorName(id), VENDORS[id].line, running(id)))}
      {row('', 'None', 'Every task starts from nothing.', true)}
    </div>
  );
}

/** "Memory: Mem0, it serves people…" and Change. `hid` absent: the line as a build proposes it, before there is a
 *  setup to change. */
export function MemoryLine({ hid, proposed }: { hid?: string; proposed?: AgentMemoryRead | null }) {
  const { read, busy, set } = useAgentMemory(hid);
  const r = hid ? read : proposed || undefined;
  if (!r) return null;
  const { engine, why } = lineOf(r);
  const pick = (c: MemoryChoice) => void set(c, c === 'none' ? 'Memory off. Each task starts from nothing.' : 'Memory changed.');
  return (
    <div className="am-line" role="status">
      <span className="am-k">Memory:</span>{' '}
      <b>{engine}</b>{why ? <span className="am-why">{`, ${after(why)}`}</span> : null}
      {hid ? <>{' '}<EngineMenu current={r.memory ? r.memory.engine : ''} busy={busy} onPick={pick} /></> : null}
    </div>
  );
}
