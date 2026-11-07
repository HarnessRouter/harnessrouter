'use client';
// Memories (docs: the design's memoriesView): one card per memory, each with the picture of its schema,
// who keeps it, and what was read of it. Every figure is the service's; what could not be read is a
// dash. With no memory service connected the page says so in one sentence and leads to connecting one.
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useState } from 'react';
import { getSchema, labelOf, listMemories, listRecords, type Memory, type Provider } from '@/lib/memories';
import { Skel, SkCards, SkHead } from '../Skel';
import { toast } from '../toast';
import { builtinOf, hasSchema, schemaLabels } from './caps';
import { CardArt, Ghost, MiniArt } from './CardArt';
import { concepts } from './graph/builtin';
import { pool, PLUS, useProviders } from './parts';
import { schemaIn, type LSchema } from './schemaModel';
import { ChooseServiceSheet, NewMemorySheet } from './sheets';
import { vendorName } from './vendors';
import './memories.css';

/** How many types a provider makes itself. */
const made = (p: Provider | null | undefined) => builtinOf(p)?.types.length || 0;
/** What a memory's picture draws (Richard 11-06): labels as Vivian's chips where a person set them; otherwise the
 *  provider's own concepts with any types a person set, as the Schema tab draws them. */
const pictureOf = (f: { schema?: LSchema | null } | undefined, p: Provider | null | undefined) => {
  const asLabels = schemaLabels(p) && !!f?.schema?.types.length;
  return { s: asLabels ? f?.schema : concepts(f?.schema, p), labels: asLabels };
};

// `recent`: what a memory with no schema to draw shows on its card, the first few records it keeps
interface Facts { schema?: LSchema | null; recent?: string[] | null }
type Open = { k: 'new'; picked?: string } | { k: 'choose' } | null;
const enc = encodeURIComponent;
// Cards or a list, as on Studio, and remembered the same way (for this person, in this browser)
const VM_KEY = 'hr.memories.view';
type View = 'cards' | 'list';
const GRID_IC = <svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" strokeWidth={1.6} aria-hidden="true"><rect x="2" y="2" width="5" height="5" rx="1.2" /><rect x="9" y="2" width="5" height="5" rx="1.2" /><rect x="2" y="9" width="5" height="5" rx="1.2" /><rect x="9" y="9" width="5" height="5" rx="1.2" /></svg>;
const LIST_IC = <svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" aria-hidden="true"><path d="M2.5 4h11M2.5 8h11M2.5 12h11" /></svg>;

export function MemoriesPage() {
  const router = useRouter();
  const { providers, failed: providersFailed, reload: reloadProviders } = useProviders();
  const [list, setList] = useState<Memory[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [facts, setFacts] = useState<Record<string, Facts>>({});
  const [open, setOpen] = useState<Open>(null);
  const [vm, setVm] = useState<View>('cards');
  useEffect(() => { try { if (localStorage.getItem(VM_KEY) === 'list') setVm('list'); } catch { /* none */ } }, []);
  const pick = (v: View) => { setVm(v); try { localStorage.setItem(VM_KEY, v); } catch { /* none */ } };

  const read = useCallback(() => {
    setFailed(false);
    // no counts: the page shows none, and counting asked every memory's service in turn (13 s for sixty, 2026-11-06)
    listMemories({ counts: false }).then(setList).catch(() => setFailed(true));
  }, []);
  useEffect(() => { read(); }, [read]);
  // a setup's Settings sends a person here to make a memory
  useEffect(() => { if (new URLSearchParams(window.location.search).get('new') === '1') setOpen({ k: 'new' }); }, []);

  // A memory's provider as the memory's own workspace reaches it: what a provider makes itself can differ by connection
  // (Mem0's own service makes facts; a Mem0 server, facts and the names in them), and the list says which.
  const providerOf = useCallback((m: Memory) => {
    const p = (providers || []).find((x) => x.id === m.provider) || null;
    return p && m.builtin !== undefined ? { ...p, schema: { ...p.schema, builtin: m.builtin || undefined } } : p;
  }, [providers]);
  useEffect(() => {
    if (!list || !providers) return;
    let live = true;
    void pool(list, 4, async (m) => {
      const withSchema = hasSchema(providerOf(m));
      // the picture's own reads only: a schema where one is read, and the first records where a service has neither
      // a schema nor concepts of its own to draw
      const p = providerOf(m);
      const [schema, recent] = await Promise.all([
        withSchema ? getSchema(m.id).then(schemaIn).catch(() => null) : Promise.resolve(null),
        !withSchema && !made(p) ? listRecords(m.id, { limit: 3 }).then((d) => d.data.map(labelOf).filter(Boolean)).catch(() => null) : Promise.resolve(null),
      ]);
      if (live) setFacts((f) => ({ ...f, [m.id]: { schema, recent } }));
    });
    return () => { live = false; };
  }, [list, providers, providerOf]);

  const created = (m: Memory, p: Provider) => {
    const toSchema = hasSchema(p);
    toast(toSchema ? (schemaLabels(p) ? `${m.name} created. Add its labels.` : `${m.name} created. Design its schema.`) : `${m.name} created.`);
    router.push(`/memories/${enc(m.id)}?tab=${toSchema ? 'schema' : 'data'}`);
  };

  const loading = !failed && (!list || (!providers && !providersFailed));
  const noneConnected = !!providers && !providers.some((p) => p.connected);
  const L = list || [];

  const top = (
    <div className="list-top">
      <div>
        <h1>Memories</h1>
        {L.length ? null : <p className="sub">What your setups keep from one task to the next.</p>}
      </div>
      {loading || failed || (noneConnected && !L.length) ? null : (
        <div className="top-actions">
          {L.length ? (
            <div className="seg vm-seg" role="group" aria-label="View">
              <button type="button" className={vm === 'cards' ? 'on' : ''} aria-pressed={vm === 'cards'} onClick={() => pick('cards')}>{GRID_IC}Cards</button>
              <button type="button" className={vm === 'list' ? 'on' : ''} aria-pressed={vm === 'list'} onClick={() => pick('list')}>{LIST_IC}List</button>
            </div>
          ) : null}
          <button type="button" className="btn primary" onClick={() => setOpen({ k: 'new' })}>{PLUS}New memory</button>
        </div>
      )}
    </div>
  );

  let body: React.ReactNode;
  if (failed) {
    body = <div className="empty-list ws-fail" role="alert">Your memories could not be read just now. <button type="button" className="link-q inl" onClick={read}>Try again</button></div>;
  } else if (loading) {
    body = <Skel label="Loading memories"><div className="cards mm-cards"><SkCards n={3} /></div></Skel>;
  } else if (noneConnected && !L.length) {
    body = (
      <div className="mm-empty-list">
        <div className="mm-art big"><Ghost /></div>
        <h2>Connect a memory service</h2>
        <p>A memory lives in a memory service you connect, and your setups read and write it from one task to the next.</p>
        <button type="button" className="btn primary" onClick={() => setOpen({ k: 'choose' })}>Connect a service</button>
      </div>
    );
  } else if (!L.length) {
    body = (
      <div className="mm-empty-list">
        <div className="mm-art big"><Ghost /></div>
        <h2>No memories yet</h2>
        <p>A memory is where your setups keep what should outlast one task: who your customers are, the rules they follow, what happened last time.</p>
        <button type="button" className="btn primary" onClick={() => setOpen({ k: 'new' })}>{PLUS}New memory</button>
      </div>
    );
  } else if (vm === 'list') {
    body = (
      <>
        <div className="rows-head mm-rows-g"><span>Name</span><span>Description</span></div>
        <div className="rows mm-rows">
          {L.map((m) => {
            const p = providerOf(m), f = facts[m.id];
            return (
              <Link key={m.id} href={`/memories/${enc(m.id)}`} className="row mm-rows-g mm-row">
                <span className="t with-mini">
                  <span className="mm-mini-box">{f ? <MiniArt {...pictureOf(f, p)} records={f.recent?.length ?? null} /> : null}</span>
                  <span className="mm-rn">
                    <span className="mm-ct"><b>{m.name}</b>{p && !p.connected ? <span className="pill neutral">Not connected</span> : null}</span>
                    <small className="sub2 mm-cp">{`Kept by ${vendorName(m.provider)}`}</small>
                  </span>
                </span>
                <span className="mm-rd">{m.description || 'No description yet.'}</span>
              </Link>
            );
          })}
        </div>
      </>
    );
  } else {
    body = (
      <div className="cards mm-cards">
        {L.map((m) => {
          const p = providerOf(m), f = facts[m.id];
          return (
            <Link key={m.id} href={`/memories/${enc(m.id)}`} className="card mm-card">
              <span className="mm-art"><CardArt {...pictureOf(f, p)} records={f?.recent?.length ?? null} recent={f?.recent} pending={!f} /></span>
              <span className="mm-cb">
                <span className="mm-ct"><b>{m.name}</b>{p && !p.connected ? <span className="pill neutral">Not connected</span> : null}</span>
                <span className="mm-cp">{`Kept by ${vendorName(m.provider)}`}</span>
                <span className="mm-cd">{m.description || 'No description yet.'}</span>
              </span>
            </Link>
          );
        })}
        <button type="button" className="card new-card mm-new" onClick={() => setOpen({ k: 'new' })}>
          <span className="mm-art"><Ghost /></span>
          <span className="nc-b">{PLUS}<span>New memory</span></span>
        </button>
      </div>
    );
  }

  return (
    <div className="scroll">
      <div className="list-wrap">
        {loading ? <Skel label="Loading"><SkHead /></Skel> : top}
        {body}
      </div>
      {open?.k === 'new' ? (
        <NewMemorySheet providers={providers} failed={providersFailed} retry={() => void reloadProviders()} picked={open.picked}
          reloadProviders={reloadProviders} onClose={() => setOpen(null)} onCreated={created} />
      ) : null}
      {open?.k === 'choose' && providers ? (
        <ChooseServiceSheet providers={providers} onClose={() => setOpen(null)}
          onConnected={async (id) => { await reloadProviders(); setOpen({ k: 'new', picked: id }); toast(`${vendorName(id)} connected.`); }} />
      ) : null}
    </div>
  );
}
