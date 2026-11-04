'use client';
// Memories (docs: the design's memoriesView): one card per memory, each with the picture of its schema,
// who keeps it, and what was read of it. Every figure is the service's; what could not be read is a
// dash. With no memory service connected the page says so in one sentence and leads to connecting one.
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useState } from 'react';
import { getSchema, listGrants, listMemories, type Memory, type Provider } from '@/lib/memories';
import { Skel, SkCards, SkHead } from '../Skel';
import { toast } from '../toast';
import { plural } from '../setup/settingsModel';
import { hasSchema, schemaLabels } from './caps';
import { Art, memoriesWord, pool, PLUS, setupsOf, useProviders, useSetupNames } from './parts';
import { schemaIn, type LSchema } from './schemaModel';
import { ChooseServiceSheet, NewMemorySheet } from './sheets';
import { vendorName } from './vendors';
import './memories.css';

interface Facts { schema?: LSchema | null; grants?: Awaited<ReturnType<typeof listGrants>> | null }
type Open = { k: 'new'; picked?: string } | { k: 'choose' } | null;
const enc = encodeURIComponent;

export function MemoriesPage() {
  const router = useRouter();
  const { providers, failed: providersFailed, reload: reloadProviders } = useProviders();
  const names = useSetupNames();
  const [list, setList] = useState<Memory[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [facts, setFacts] = useState<Record<string, Facts>>({});
  const [open, setOpen] = useState<Open>(null);

  const read = useCallback(() => {
    setFailed(false);
    listMemories().then(setList).catch(() => setFailed(true));
  }, []);
  useEffect(() => { read(); }, [read]);
  // a setup's Settings sends a person here to make a memory
  useEffect(() => { if (new URLSearchParams(window.location.search).get('new') === '1') setOpen({ k: 'new' }); }, []);

  const providerOf = useCallback((id: string) => (providers || []).find((p) => p.id === id) || null, [providers]);
  useEffect(() => {
    if (!list || !providers) return;
    let live = true;
    void pool(list, 4, async (m) => {
      const [schema, grants] = await Promise.all([
        hasSchema(providerOf(m.provider)) ? getSchema(m.id).then(schemaIn).catch(() => null) : Promise.resolve(null),
        listGrants(m.id).catch(() => null),
      ]);
      if (live) setFacts((f) => ({ ...f, [m.id]: { schema, grants } }));
    });
    return () => { live = false; };
  }, [list, providers, providerOf]);

  const created = (m: Memory, p: Provider) => {
    const toSchema = hasSchema(p);
    toast(toSchema ? (schemaLabels(p) ? `${m.name} created. Add its labels.` : `${m.name} created. Design its schema.`) : `${m.name} created.`);
    router.push(`/memories/${enc(m.id)}?tab=${toSchema ? 'schema' : 'data'}`);
  };
  const setupsFor = (m: Memory) => { const g = facts[m.id]?.grants; return g && names ? setupsOf(g, names) : null; };

  const loading = !failed && (!list || (!providers && !providersFailed));
  const noneConnected = !!providers && !providers.some((p) => p.connected);
  const L = list || [];
  const recs = L.every((m) => m.records?.count != null) ? L.reduce((n, m) => n + (m.records.count as number), 0) : null;
  const used = new Set(L.flatMap((m) => (setupsFor(m) || []).map((s) => s.id)));

  const top = (
    <div className="list-top">
      <div>
        <h1>Memories</h1>
        <p className="sub meta">
          {L.length ? (
            <span className="meta-in">
              <span className="meta-i">{memoriesWord(L.length)}</span>
              {recs != null ? <span className="meta-i">{plural(recs, 'record')}</span> : null}
              {used.size ? <span className="meta-i">{`used by ${plural(used.size, 'setup')}`}</span> : null}
            </span>
          ) : 'What your setups keep from one task to the next.'}
        </p>
      </div>
      {loading || failed || (noneConnected && !L.length) ? null : (
        <div className="top-actions"><button type="button" className="btn primary" onClick={() => setOpen({ k: 'new' })}>{PLUS}New memory</button></div>
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
        <div className="mm-art big"><Art s={null} w={220} h={120} /></div>
        <h2>Connect a memory service</h2>
        <p>A memory lives in a memory service you connect, and your setups read and write it from one task to the next.</p>
        <button type="button" className="btn primary" onClick={() => setOpen({ k: 'choose' })}>Connect a service</button>
      </div>
    );
  } else if (!L.length) {
    body = (
      <div className="mm-empty-list">
        <div className="mm-art big"><Art s={null} w={220} h={120} /></div>
        <h2>No memories yet</h2>
        <p>A memory is where your setups keep what should outlast one task: who your customers are, the rules they follow, what happened last time.</p>
        <button type="button" className="btn primary" onClick={() => setOpen({ k: 'new' })}>{PLUS}New memory</button>
      </div>
    );
  } else {
    body = (
      <div className="cards mm-cards">
        {L.map((m) => {
          const p = providerOf(m.provider), f = facts[m.id], us = setupsFor(m);
          return (
            <Link key={m.id} href={`/memories/${enc(m.id)}`} className="card mm-card">
              <span className="mm-art"><Art s={f?.schema} w={300} h={150} /></span>
              <span className="mm-cb">
                <span className="mm-ct"><b>{m.name}</b></span>
                <span className="mm-cp">{`Kept by ${vendorName(m.provider)}`}{p && !p.connected ? ' · not connected' : ''}</span>
                <span className="mm-cd">{m.description || 'No description yet.'}</span>
                <span className="mm-cs">
                  {hasSchema(p) ? <span><small>{schemaLabels(p) ? 'Labels' : 'Types'}</small><b>{f?.schema ? f.schema.types.length : '—'}</b></span> : null}
                  <span><small>Records</small><b>{m.records?.count ?? '—'}</b></span>
                  <span><small>Setups</small><b>{us && us.length ? us.length : '—'}</b></span>
                </span>
              </span>
            </Link>
          );
        })}
        <button type="button" className="card new-card mm-new" onClick={() => setOpen({ k: 'new' })}>
          <span className="mm-art"><Art s={null} w={300} h={150} /></span>
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
