'use client';
// A setup's Settings, Memory: every memory this person can see, one row each, with a switch that gives it to this
// setup or takes it away, the way the Tools list works. Where it's on, how far the agent may go and whether it's where
// the agent writes by default sit quietly beside the switch. Whether finished tasks are kept is below. Access is a grant
// on the memory to the setup's own principal, and these changes apply at once: nothing here waits for Save.
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  getHarnessMemories, grant, listGrants, listMemories, revokeGrant, setHarnessMemories,
  type HarnessMemories, type Memory, type Provider,
} from '@/lib/memories';
import { partIcon } from '../bricks';
import { announceHarnessMemories } from '../setup/harnessMemories';
import { plain, plural } from '../setup/settingsModel';
import { toast } from '../toast';
import { keepLine, keepsTasks } from './caps';
import { memoriesWord, PLUS, useProviders } from './parts';
import { vendorName } from './vendors';
import './memories.css';
import { Markup } from '../Markup';

/** Open, as everywhere a row leads somewhere else: a quiet arrow at the end of the row. */
const OPEN_IC = <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M7 17 17 7M9 7h8v8" /></svg>;

/** Past this many, a search is worth its row. */
const FIND_FROM = 4;

/** The Memory layer's line in the layers list. */
export const memorySummary = (d: HarnessMemories | null | undefined) => {
  if (!d) return '';
  if (!d.data.length) return 'None';
  return `${memoriesWord(d.data.length)}${d.observe && d.default_memory_id ? ' · keeps tasks' : ''}`;
};

interface Row { id: string; name: string; provider: string; records: number | null; privileges: string[]; parent: string; from: string }

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

export function MemoryLayer({ hid, name, onRead }: { hid: string; name: string; onRead?: (d: HarnessMemories) => void }) {
  const router = useRouter();
  const { providers } = useProviders();
  const [d, setD] = useState<HarnessMemories | null>(null);
  const [all, setAll] = useState<Memory[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [q, setQ] = useState('');

  const read = useCallback(async () => {
    setFailed(false);
    try {
      const [h, l] = await Promise.all([getHarnessMemories(hid), listMemories()]);
      setD(h); setAll(l); onRead?.(h);
      announceHarnessMemories(hid, h);
      return h;
    } catch { setFailed(true); return null; }
  }, [hid, onRead]);
  useEffect(() => { void read(); }, [read]);

  const held = useMemo(() => new Map((d?.data || []).map((x) => [x.id, x])), [d]);
  // every memory in one steady order, so a row doesn't move under the switch just pressed. What the agent holds and
  // this person can't list is still shown: it's on, and they should see that.
  const rows = useMemo<Row[]>(() => {
    const by = new Map((all || []).map((m) => [m.id, m]));
    const heldIds = new Set(held.keys());
    const seen: Row[] = (all || []).map((m) => ({
      id: m.id, name: m.name, provider: m.provider, records: m.records?.count ?? null, privileges: m.privileges || [],
      parent: (m.parent_id && by.get(m.parent_id)?.name) || '', from: reachedThrough(m, by, heldIds)?.name || '',
    }));
    const unseen: Row[] = (d?.data || []).filter((x) => !by.has(x.id)).map((x) => ({
      id: x.id, name: x.name, provider: '', records: x.records?.count ?? null, privileges: [], parent: '', from: '',
    }));
    return [...seen, ...unseen].sort((a, b) => a.name.localeCompare(b.name) || a.id.localeCompare(b.id));
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
  // The default is a memory the agent can write: the first one written becomes it, and losing write hands it on.
  // Keeping every finished task is a person's choice, made for the default they see. So a default that appears
  // where there was none (by either way: the first write, or Make default) comes with keeping off, and a default
  // that goes takes keeping with it; the service's own setting would otherwise turn it on unasked.
  const makeDefault = (mid: string) => setHarnessMemories(hid, d?.default_memory_id ? { default_memory_id: mid } : { default_memory_id: mid, observe: false });
  const handOn = async (mid: string) => {
    if (d?.default_memory_id !== mid) return;
    const other = d.data.find((x) => x.id !== mid && x.privileges.includes('write'));
    if (!other) { await setHarnessMemories(hid, { default_memory_id: '', observe: false }); return; }
    await setHarnessMemories(hid, { default_memory_id: other.id });
    // what changed without being pressed is said: where the agent writes now, and where tasks are kept now
    toast(d.observe ? `${other.name} is now the default. Finished tasks are kept there.` : `${other.name} is now the default.`);
  };
  const turnOn = (mid: string) => run(() => grant(mid, principal, ['read']), 'That memory was not given. Try again.');
  const turnOff = (mid: string) => run(async () => {
    const g = (await listGrants(mid)).find((x) => x.principal === principal && x.memory_id === mid);
    if (g) await revokeGrant(mid, g.id);
    await handOn(mid);
  }, 'That memory was not taken away. Try again.');
  const setAccess = (mid: string, write: boolean) => run(async () => {
    await grant(mid, principal, write ? ['read', 'write'] : ['read']);
    // What gets written is the agent's own call. Keeping every task as well, whatever the agent thought of it, is a person's choice: the switch below stays as it reads.
    if (write && !d?.default_memory_id) await makeDefault(mid);
    if (!write) await handOn(mid);
  }, 'The access was not changed. Try again.');

  if (failed) return <div className="empty-list ws-fail" role="alert">This setup’s memories could not be read just now. <button type="button" className="link-q inl" onClick={() => void read()}>Try again</button></div>;
  if (!d) return null;

  const def = d.data.find((x) => x.id === d.default_memory_id) || null;
  const providerOf = (mid: string): Provider | null => {
    const m = all?.find((x) => x.id === mid);
    return (m && providers?.find((p) => p.id === m.provider)) || null;
  };
  const defProvider = def ? providerOf(def.id) : null;
  // a default whose provider keeps no tasks has nothing to turn on: the row goes
  const showKeep = !def || !providers || keepsTasks(defProvider);
  const needle = q.trim().toLowerCase();
  const shown = rows.filter((r) => !needle || r.name.toLowerCase().includes(needle) || (r.provider && vendorName(r.provider).toLowerCase().includes(needle)));
  return (
    <>
      <div className="lg-sub mm-layer">
        <div className="lg-sub-h">
          <h3>Memories{d.data.length ? <span className="muted">{`${d.data.length} on`}</span> : null}</h3>
          <button type="button" className="btn small" onClick={() => router.push('/memories?new=1')}>{PLUS}New memory</button>
        </div>
        {rows.length >= FIND_FROM ? (
          <div className="cap-find">
            <input className="set-in slim" type="search" placeholder={`Search ${memoriesWord(rows.length)}`} aria-label="Search memories" autoComplete="off" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
        ) : null}
        {!rows.length ? (
          <div className="empty-list es cap-empty"><span>No memories yet, so every task starts from nothing. Make one and this setup can keep what it learns.</span></div>
        ) : shown.length ? (
          <div className="cap-list">
            {shown.map((m) => {
              const mine = held.get(m.id), on = !!mine || !!m.from, w = !!mine?.privileges.includes('write'), isD = d.default_memory_id === m.id;
              const mayChange = m.privileges.includes('delete');
              const sub = [m.parent ? `In ${m.parent}` : '', m.records != null ? plural(m.records, 'record') : '', m.provider ? vendorName(m.provider) : ''].filter(Boolean).join(' · ');
              const why = m.from ? `Comes with ${m.from}` : !mayChange ? 'Only someone who manages this memory can change who holds it' : undefined;
              return (
                <div className={`cap-row cap-mcp mm-sl${on ? '' : ' off'}`} key={m.id}>
                  <Markup className="cap-ic" html={partIcon(on ? 'built' : 'empty', 'memory')} />
                  <span className="grow"><b className="mm-sl-name"><span title={m.name}>{m.name}</span>{isD ? <span className="pill run mm-defp">Default</span> : null}</b>{sub || m.from ? <small>{[m.from ? `Comes with ${m.from}` : '', sub].filter(Boolean).join(' · ')}</small> : null}</span>
                  {/* the same columns in every row, filled only where the memory is on, so the switches and arrows line up */}
                  <span className="mm-sl-c mm-sl-acc">
                    {mine ? (
                      <select className="mm-acc-q" aria-label={`What this setup may do with ${m.name}`} disabled={busy || !mayChange} value={w ? 'w' : 'r'} onChange={(e) => void setAccess(m.id, e.target.value === 'w')}>
                        <option value="r">Reads</option>
                        <option value="w">Reads and writes</option>
                      </select>
                    ) : null}
                  </span>
                  <span className="mm-sl-c mm-sl-def">
                    {mine && w && !isD ? <button type="button" className="link-q mm-row-a" disabled={busy} onClick={() => void run(() => makeDefault(m.id), 'The default was not changed. Try again.')}>Make default</button> : null}
                  </span>
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
        <p className="set-help mm-sl-help">Reading lets it recall records. Writing also lets it remember, revise and forget them. Erasing is never up to an agent. Changes here apply right away.</p>
      </div>
      {showKeep ? (
        <div className="lg-sub mm-layer">
          <div className="lg-sub-h"><h3>Remember tasks</h3></div>
          <div className="cap-list">
            <div className="cap-row mm-sl">
              <span className="grow"><b>Keep every finished task</b><small>{def ? keepLine(defProvider, def.name) : 'Needs a default memory: one it can write.'}</small></span>
              <button type="button" className={`tog${d.observe && def ? ' on' : ''}`} aria-pressed={!!(d.observe && def)} aria-label="Keep every finished task" disabled={!def || busy}
                onClick={() => void run(() => setHarnessMemories(hid, { observe: !d.observe }), 'That was not changed. Try again.')}><i />{d.observe && def ? 'On' : 'Off'}</button>
              {/* the arrow's column, empty here, so this switch lines up with the memories' switches above */}
              <span className="mm-sl-c mm-sl-open" aria-hidden="true" />
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
