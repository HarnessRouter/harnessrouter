'use client';
// A setup's Settings, Memory (the design's memLayerBody): each memory it holds, with its access and which
// one it writes to by default, and whether finished tasks are kept. Access is a grant on the memory to the
// setup's own principal, and these changes apply at once.
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  getHarnessMemories, getSchema, grant, listGrants, listMemories, revokeGrant, setHarnessMemories,
  type HarnessMemories, type Memory, type Provider,
} from '@/lib/memories';
import { plain, plural } from '../setup/settingsModel';
import { toast } from '../toast';
import { hasSchema, keepLine, keepsTasks, schemaWord } from './caps';
import { BADGE, memoriesWord, PLUS, pool, useProviders } from './parts';
import { vendorName } from './vendors';
import './memories.css';

/** The Memory layer's line in the layers list. */
export const memorySummary = (d: HarnessMemories | null | undefined) => {
  if (!d) return '';
  if (!d.data.length) return 'None';
  return `${memoriesWord(d.data.length)}${d.observe && d.default_memory_id ? ' · keeps tasks' : ''}`;
};

export function MemoryLayer({ hid, name, onRead }: { hid: string; name: string; onRead?: (d: HarnessMemories) => void }) {
  const router = useRouter();
  const { providers } = useProviders();
  const [d, setD] = useState<HarnessMemories | null>(null);
  const [all, setAll] = useState<Memory[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [giving, setGiving] = useState(false);
  const [busy, setBusy] = useState(false);
  const [types, setTypes] = useState<Record<string, number>>({});

  const read = useCallback(async () => {
    setFailed(false);
    try {
      const [h, l] = await Promise.all([getHarnessMemories(hid), listMemories()]);
      setD(h); setAll(l); onRead?.(h);
      return h;
    } catch { setFailed(true); return null; }
  }, [hid, onRead]);
  useEffect(() => { void read(); }, [read]);

  const providerOfId = useCallback((mid: string): Provider | null => {
    const m = all?.find((x) => x.id === mid);
    return (m && providers?.find((p) => p.id === m.provider)) || null;
  }, [all, providers]);
  useEffect(() => {
    if (!d || !providers || !all) return;
    let live = true;
    void pool(d.data.filter((x) => hasSchema(providerOfId(x.id))), 4, async (x) => {
      const n = await getSchema(x.id).then((s) => s.types.length).catch(() => null);
      if (live && n != null) setTypes((t) => ({ ...t, [x.id]: n }));
    });
    return () => { live = false; };
  }, [d, providers, all, providerOfId]);

  const held = useMemo(() => new Set((d?.data || []).map((x) => x.id)), [d]);
  const avail = (all || []).filter((m) => !held.has(m.id));
  const run = async (fn: () => Promise<unknown>, fallback: string, done?: string) => {
    if (busy) return;
    setBusy(true);
    try {
      await fn();
      await read();
      if (done) toast(done);
    } catch (e) { toast(plain(e, fallback)); await read(); } finally { setBusy(false); }
  };
  const principal = d?.principal || '';
  const give = (m: Memory) => run(async () => { await grant(m.id, principal, ['read']); setGiving(false); }, 'That memory was not given. Try again.', `${name} can now read ${m.name}`);
  const setAccess = (mid: string, write: boolean) => run(async () => {
    await grant(mid, principal, write ? ['read', 'write'] : ['read']);
    if (!d) return;
    // the default is a memory the agent can write: the first one written becomes it, and losing write hands it on
    if (write && !d.default_memory_id) await setHarnessMemories(hid, { default_memory_id: mid });
    if (!write && d.default_memory_id === mid) {
      const other = d.data.find((x) => x.id !== mid && x.privileges.includes('write'));
      await setHarnessMemories(hid, { default_memory_id: other ? other.id : '' });
    }
  }, 'The access was not changed. Try again.');
  const remove = (mid: string, mname: string) => run(async () => {
    const g = (await listGrants(mid)).find((x) => x.principal === principal && x.memory_id === mid);
    if (g) await revokeGrant(mid, g.id);
    if (d?.default_memory_id === mid) {
      const other = d.data.find((x) => x.id !== mid && x.privileges.includes('write'));
      if (other) await setHarnessMemories(hid, { default_memory_id: other.id });
    }
  }, 'That memory was not removed. Try again.', `${mname} removed from ${name}`);

  if (failed) return <div className="empty-list ws-fail" role="alert">This setup’s memories could not be read just now. <button type="button" className="link-q inl" onClick={() => void read()}>Try again</button></div>;
  if (!d) return null;

  const def = d.data.find((x) => x.id === d.default_memory_id) || null;
  const defProvider = def ? providerOfId(def.id) : null;
  // a default whose provider keeps no tasks has nothing to turn on: the row goes
  const showKeep = !def || !providers || keepsTasks(defProvider);
  return (
    <>
      <div className="lg-sub">
        <div className="lg-sub-h">
          <h3>Memories{d.data.length ? <span className="muted">{d.data.length}</span> : null}</h3>
          <button type="button" className="btn small" aria-expanded={giving} onClick={() => setGiving(!giving)}>{PLUS}Give a memory</button>
        </div>
        {d.data.length ? (
          <div className="cap-list">
            {d.data.map((x) => {
              const isD = d.default_memory_id === x.id, w = x.privileges.includes('write');
              const p = providerOfId(x.id), full = all?.find((m) => m.id === x.id);
              const sub = [hasSchema(p) && types[x.id] != null ? plural(types[x.id], schemaWord(p)) : '', x.records?.count != null ? plural(x.records.count, 'record') : '', full ? vendorName(full.provider) : ''].filter(Boolean).join(' · ');
              return (
                <div className="cap-row mm-hr" key={x.id}>
                  <span className="mm-hic">{BADGE}</span>
                  <span className="grow"><b>{x.name}{isD ? <span className="pill run mm-defp">Default</span> : null}</b>{sub ? <small>{sub}</small> : null}</span>
                  <span className="mm-hacts">
                    <select className="set-in slim mm-acc" aria-label={`Access to ${x.name}`} disabled={busy} value={w ? 'w' : 'r'} onChange={(e) => void setAccess(x.id, e.target.value === 'w')}>
                      <option value="r">Read</option>
                      <option value="w">Read and write</option>
                    </select>
                    {w && !isD ? <button type="button" className="link-q" disabled={busy} onClick={() => void run(() => setHarnessMemories(hid, { default_memory_id: x.id }), 'The default was not changed. Try again.')}>Make default</button> : null}
                    <button type="button" className="link-q" onClick={() => router.push(`/memories/${encodeURIComponent(x.id)}`)}>Open</button>
                    <button type="button" className="link-q danger" disabled={busy} aria-label={`Remove ${x.name}`} onClick={() => void remove(x.id, x.name)}>Remove</button>
                  </span>
                </div>
              );
            })}
          </div>
        ) : <div className="empty-list es cap-empty"><span>No memory yet. Every task starts from nothing.</span></div>}
        {giving ? (
          <div className="mm-give">
            {avail.length ? avail.map((m) => (
              <button key={m.id} type="button" className="mm-give-r" disabled={busy} onClick={() => void give(m)}>
                <span className="mm-hic">{BADGE}</span><span className="grow"><b>{m.name}</b>{m.description ? <small>{m.description}</small> : null}</span><span className="btn small">Give</span>
              </button>
            )) : <p className="mm-muted">{all?.length ? 'Every memory is already here.' : 'No memories yet.'}</p>}
            <button type="button" className="link-q inl mm-give-new" onClick={() => router.push('/memories?new=1')}>{PLUS}New memory</button>
          </div>
        ) : null}
        <p className="set-help">Read lets it recall records. Read and write also lets it remember, revise and forget them. Erasing is never up to an agent. Changes here apply right away.</p>
      </div>
      {showKeep ? (
        <div className="lg-sub">
          <div className="lg-sub-h"><h3>Remember tasks</h3></div>
          <div className="cap-list">
            <div className="cap-row">
              <span className="grow"><b>Keep every finished task</b><small>{def ? keepLine(defProvider, def.name) : 'Needs a default memory: one it can write.'}</small></span>
              <button type="button" className={`tog${d.observe && def ? ' on' : ''}`} aria-pressed={!!(d.observe && def)} aria-label="Keep every finished task" disabled={!def || busy}
                onClick={() => void run(() => setHarnessMemories(hid, { observe: !d.observe }), 'That was not changed. Try again.')}><i />{d.observe && def ? 'On' : 'Off'}</button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
