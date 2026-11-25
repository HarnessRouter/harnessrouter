'use client';
// A setup's Settings, Memory: the memories this agent can use, and nothing else (Richard 11-09: "just enable/disable
// each memory in the list"). One row each, its name and its engine, a switch and an arrow that opens it, the way the
// Tools list works. An agent either uses a memory or it doesn't: On is full use, a grant of read and write to the
// setup's own principal, so it recalls what's relevant there and keeps what matters; Off takes the grant away. The
// agent's own memory is a row like any other, On. These changes apply at once: nothing here waits for Save.
//
// Where the agent writes by default, and whether finished tasks are kept, have no control here. They follow the
// switches: turning the agent's own memory on makes it the default again and keeps finished tasks there, as when the
// service first gave it; any other memory turned on where there is no default becomes the default, without keeping
// finished tasks (the service would otherwise turn that on unasked); one turned off hands the default on, or clears it.
// The memories are listed without their record counts, so the page is one quick read.
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  getHarnessMemories, grant, listGrants, listMemories, revokeGrant, setHarnessMemories,
  type HarnessMemories, type Memory,
} from '@/lib/memories';
import { partIcon } from '../bricks';
import { announceHarnessMemories } from '../setup/harnessMemories';
import { plain, plural } from '../setup/settingsModel';
import { Skel, SkLine } from '../Skel';
import { toast } from '../toast';
import { useAgentMemory } from './AgentMemory';
import { memoriesWord, PLUS } from './parts';
import { vendorName } from './vendors';
import './memories.css';
import { Markup } from '../Markup';

/** Open, as everywhere a row leads somewhere else: a quiet arrow at the end of the row. */
const OPEN_IC = <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M7 17 17 7M9 7h8v8" /></svg>;

/** Past this many, a search is worth its row. */
const FIND_FROM = 4;

/** The Memory layer's line in the layers list: how many memories the agent uses, from the same read as the list. */
export const memorySummary = (d: HarnessMemories | null | undefined) => {
  if (!d) return '';
  return d.data.length ? `${memoriesWord(d.data.length)} on` : 'None on';
};

/** The list while it is read, drawn as it will stand. */
function LayerSkel() {
  return (
    <Skel label="Loading memory">
      <div className="lg-sub mm-layer">
        <div className="lg-sub-h"><SkLine w={150} h={14} /><SkLine w={118} h={30} r={8} /></div>
        <div className="cap-list">{[0, 1, 2].map((i) => (
          <div className="cap-row mm-sl am-sk" key={i}>
            <SkLine w={30} h={30} r={8} /><span className="grow"><SkLine w="34%" h={13} /><SkLine w="18%" h={11} style={{ marginTop: 8 }} /></span><SkLine w={56} h={26} r={13} />
          </div>
        ))}</div>
      </div>
    </Skel>
  );
}

interface Row { id: string; name: string; provider: string; records: number | null; privileges: string[]; parent: string; from: string; first: boolean }

/** The memory above this one that already gives it to the agent: a grant reaches everything below it, down to the
 *  first restricted one (§3.2). */
function reachedThrough(m: Memory, by: Map<string, Memory>, held: Set<string>): Memory | null {
  let cur: Memory | undefined = m;
  while (cur && !cur.restricted && cur.parent_id) {
    const up = by.get(cur.parent_id);
    if (up && held.has(up.id)) return up;
    cur = up;
  }
  return null;
}

export function MemoryLayer({ hid, onRead }: { hid: string; onRead?: (d: HarnessMemories) => void }) {
  const router = useRouter();
  // which row is the agent's own memory: on, it is where finished tasks are kept again
  const own = useAgentMemory(hid);
  const [d, setD] = useState<HarnessMemories | null>(null);
  const [all, setAll] = useState<Memory[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [q, setQ] = useState('');
  // what was on when the list was first read: those rows lead, and the order holds for the visit, so a row never
  // moves under the switch just pressed
  const first = useRef<{ hid: string; on: Set<string> } | null>(null);

  const read = useCallback(async () => {
    setFailed(false);
    try {
      // no counts: a row that has none says nothing of it, and counting asked every memory's engine (6.5 s for 170)
      const [h, l] = await Promise.all([getHarnessMemories(hid), listMemories({ counts: false })]);
      if (first.current?.hid !== hid) first.current = { hid, on: new Set((h.data || []).map((x) => x.id)) };
      setD(h); setAll(l); onRead?.(h);
      announceHarnessMemories(hid, h);
      return h;
    } catch { setFailed(true); return null; }
  }, [hid, onRead]);
  useEffect(() => { void read(); }, [read]);

  const held = useMemo(() => new Map((d?.data || []).map((x) => [x.id, x])), [d]);
  // the ones that were on first, then the rest, each by name. What the agent holds and this person can't list is
  // still shown: it's on, and they should see that.
  const rows = useMemo<Row[]>(() => {
    const by = new Map((all || []).map((m) => [m.id, m]));
    const heldIds = new Set(held.keys());
    const wasOn = first.current?.on || new Set<string>();
    const seen: Row[] = (all || []).map((m) => ({
      id: m.id, name: m.name, provider: m.provider, records: m.records?.count ?? null, privileges: m.privileges || [],
      parent: (m.parent_id && by.get(m.parent_id)?.name) || '', from: reachedThrough(m, by, heldIds)?.name || '',
      first: wasOn.has(m.id) || !!reachedThrough(m, by, wasOn),
    }));
    const unseen: Row[] = (d?.data || []).filter((x) => !by.has(x.id)).map((x) => ({
      id: x.id, name: x.name, provider: '', records: x.records?.count ?? null, privileges: [], parent: '', from: '', first: wasOn.has(x.id),
    }));
    return [...seen, ...unseen].sort((a, b) => Number(b.first) - Number(a.first) || a.name.localeCompare(b.name) || a.id.localeCompare(b.id));
  }, [all, d, held]);

  const run = async (fn: () => Promise<unknown>, fallback: string) => {
    if (busy) return;
    setBusy(true);
    try {
      await fn();
      await read();
    } catch (e) { toast(plain(e, fallback)); await read(); } finally { setBusy(false); }
  };
  const principal = d?.principal || '';
  // The default is a memory the agent can write; losing it hands it on.
  const handOn = async (mid: string) => {
    if (d?.default_memory_id !== mid) return;
    const other = d.data.find((x) => x.id !== mid && x.privileges.includes('write'));
    if (!other) { await setHarnessMemories(hid, { default_memory_id: '', observe: false }); return; }
    // said by nothing: the page has no default to name, and the switch's own state is the feedback
    await setHarnessMemories(hid, { default_memory_id: other.id });
  };
  const ownId = own.read?.memory?.id || '';
  const turnOn = (mid: string) => run(async () => {
    await grant(mid, principal, ['read', 'write']);
    // its own memory back on: the default again, keeping finished tasks, as the service set it when it gave it.
    // Any other memory switched on while the agent has nowhere to write becomes where it writes, keeping finished
    // tasks too: the outcome can't depend on which switch was pressed first (own Off then this On kept nothing).
    if (mid === ownId) await setHarnessMemories(hid, { default_memory_id: mid, observe: true });
    else if (!d?.default_memory_id) await setHarnessMemories(hid, { default_memory_id: mid, observe: true });
  }, 'That memory was not given. Try again.');
  const turnOff = (mid: string) => run(async () => {
    const g = (await listGrants(mid)).find((x) => x.principal === principal && x.memory_id === mid);
    if (g) await revokeGrant(mid, g.id);
    await handOn(mid);
  }, 'That memory was not taken away. Try again.');

  if (failed) return <div className="empty-list ws-fail" role="alert">This harness’s memories could not be read just now. <button type="button" className="link-q inl" onClick={() => void read()}>Try again</button></div>;
  if (!d || own.said === null) return <LayerSkel />;

  const needle = q.trim().toLowerCase();
  const shown = rows.filter((r) => !needle || r.name.toLowerCase().includes(needle) || (r.provider && vendorName(r.provider).toLowerCase().includes(needle)));

  return (
    <div className="lg-sub mm-layer">
      <div className="lg-sub-h">
        <h3>Memories it can use{d.data.length ? <span className="muted">{`${d.data.length} on`}</span> : null}</h3>
        <button type="button" className="btn small" onClick={() => router.push('/memories?new=1')}>{PLUS}New memory</button>
      </div>
      {rows.length >= FIND_FROM ? (
        <div className="cap-find">
          <input className="set-in slim" type="search" placeholder={`Search ${memoriesWord(rows.length)}`} aria-label="Search memories" autoComplete="off" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
      ) : null}
      {!rows.length ? (
        <div className="empty-list es cap-empty"><span>No memories yet, so every task starts from nothing. Make one and this harness can keep what it learns.</span></div>
      ) : shown.length ? (
        <div className="cap-list">
          {shown.map((m) => {
            const mine = held.get(m.id), on = !!mine || !!m.from;
            const mayChange = m.privileges.includes('delete');
            const sub = [m.parent ? `In ${m.parent}` : '', m.records != null ? plural(m.records, 'record') : '', m.provider ? vendorName(m.provider) : ''].filter(Boolean).join(' · ');
            const why = m.from ? `Comes with ${m.from}` : !mayChange ? 'Only someone who manages this memory can change who holds it' : undefined;
            return (
              <div className={`cap-row cap-mcp mm-sl${on ? '' : ' off'}`} key={m.id}>
                <Markup className="cap-ic" html={partIcon(on ? 'built' : 'empty', 'memory')} />
                <span className="grow"><b className="mm-sl-name"><span title={m.name}>{m.name}</span></b>{sub || m.from ? <small>{[m.from ? `Comes with ${m.from}` : '', sub].filter(Boolean).join(' · ')}</small> : null}</span>
                <button type="button" className={`tog${on ? ' on' : ''}`} aria-pressed={on} aria-label={m.name} title={why} disabled={busy || !!m.from || !mayChange}
                  onClick={() => void (mine ? turnOff(m.id) : turnOn(m.id))}><i />{on ? 'On' : 'Off'}</button>
                <span className="mm-sl-c mm-sl-open">
                  {all?.some((x) => x.id === m.id) ? <button type="button" className="icon-btn" aria-label={`Open ${m.name}`} title="Open" onClick={() => router.push(`/memories/${encodeURIComponent(m.id)}`)}>{OPEN_IC}</button> : null}
                </span>
                <i className="cap-br" aria-hidden="true" />
              </div>
            );
          })}
        </div>
      ) : <p className="set-help" role="status">Nothing here matches that.</p>}
    </div>
  );
}
