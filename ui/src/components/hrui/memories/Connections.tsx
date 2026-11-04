'use client';
// What the open record links to, as a list you can change: a fact's sentence is what a link reads as, the word it was
// filed under comes second, and a link with no real name is plainly "related to". The graph above it draws the same.
import { useState } from 'react';
import { labelOf, type GraphEdge, type MemoryGraph, type MemoryRecord, type Provider } from '@/lib/memories';
import { kindOf, relText } from './caps';
import { PLUS, X } from './parts';
import { typeLabel, type LSchema } from './schemaModel';
import { kindInfo } from './tree';

export type LinkOption = { key: string; rel: string; out: boolean; other: string | null; label: string };

const secondWord = (node: MemoryRecord | undefined, e: GraphEdge) => relText(String(node?.attributes?.predicate || '') || e.rel);

export function Connections({ record, graph, failed, retry, schema, options, candidates, provider, onOpen, onLink, onUnlink, canUnlink }: {
  record: MemoryRecord | null; graph: MemoryGraph | null; failed: boolean; retry: () => void; schema: LSchema | null;
  options: LinkOption[] | null; candidates: (o: LinkOption) => MemoryRecord[]; provider: Provider | null;
  onOpen: (rid: string, memoryId?: string) => void;
  onLink: (o: LinkOption, rel: string, to: string) => Promise<void>;
  onUnlink: (e: GraphEdge) => void; canUnlink: (e: GraphEdge) => boolean;
}) {
  const [adding, setAdding] = useState(false);
  const [optKey, setOptKey] = useState('');
  const [freeRel, setFreeRel] = useState('related');
  const [to, setTo] = useState('');
  const [busy, setBusy] = useState(false);
  if (!record || !record.id) return null;
  if (failed) return <p className="mm-muted mm-cpad" role="alert">What this links to could not be read just now. <button type="button" className="link-q inl" onClick={retry}>Try again</button></p>;
  const g: MemoryGraph = graph || { nodes: [{ record, memory: { id: record.memory_id, name: '' } }], edges: [], truncated: false, degraded: [] };
  const nodeOf = (id: string) => g.nodes.find((n) => n.record.id === id);
  const mine = g.edges.filter((e) => e.from.record_id === record.id || e.to.record_id === record.id);
  const cur = options?.find((o) => o.key === optKey) || options?.[0] || null;
  const cands = cur ? candidates(cur) : [];
  const link = async () => {
    if (!cur || busy) return;
    const target = to || cands[0]?.id;
    if (!target) return;
    setBusy(true);
    try { await onLink(cur, cur.other === null ? freeRel.trim() || 'related' : cur.rel, target); setAdding(false); setTo(''); }
    finally { setBusy(false); }
  };
  return (
    <div className="mm-clist">
      <div className="mm-clist-h">Links</div>
      {mine.length ? mine.map((e, i) => {
        const out = e.from.record_id === record.id;
        const other = out ? e.to.record_id : e.from.record_id;
        const n = e.available ? nodeOf(other) : undefined;
        if (!n) return <div className="mm-lr" key={i}><span className="mm-lb"><span className="mm-lt off">A record you can’t open</span></span></div>;
        const k = kindInfo(kindOf(n.record), schema);
        return (
          <div className="mm-lr" key={i}>
            <span className="mm-lb">
              <button type="button" className="mm-lt" onClick={() => onOpen(other, n.memory.id)}><span className="mm-dot sm" style={{ background: k.color }} />{labelOf(n.record) || 'Untitled'}</button>
              <small className="mm-lrel">{`${out ? '' : '← '}${secondWord(n.record, e)}${out ? ' →' : ''}`}</small>
            </span>
            {canUnlink(e) ? <button type="button" className="icon-btn xs" aria-label={`Remove link to ${labelOf(n.record) || 'this record'}`} onClick={() => onUnlink(e)}>{X}</button> : null}
          </div>
        );
      }) : <p className="mm-muted">No links yet.</p>}
      {g.truncated ? <p className="set-help">Only the nearest are shown.</p> : null}
      {adding && options?.length ? (
        <div className="mm-lform">
          {cur && cur.other !== null ? (
            <select className="set-in slim" aria-label="Relation" value={cur.key} onChange={(e) => { setOptKey(e.target.value); setTo(''); }}>
              {options.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
            </select>
          ) : (
            <input className="set-in slim" aria-label="How they relate" placeholder="How they relate" value={freeRel} onChange={(e) => setFreeRel(e.target.value)} />
          )}
          <select className="set-in slim" aria-label="Record" value={to || cands[0]?.id || ''} onChange={(e) => setTo(e.target.value)}>
            {cands.length ? cands.map((x) => <option key={x.id} value={x.id}>{labelOf(x) || 'Untitled'}</option>) : (
              <option value="">{`No ${cur?.other ? typeLabel(cur.other) : ''} records yet`.replace('  ', ' ')}</option>
            )}
          </select>
          <div className="mm-lform-a">
            <button type="button" className="link-q" onClick={() => setAdding(false)}>Cancel</button>
            <button type="button" className="btn small primary" disabled={!cands.length || busy} onClick={() => void link()}>Link</button>
          </div>
        </div>
      ) : null}
      {adding || options === null ? null : options.length ? (
        <button type="button" className="btn small mm-add" onClick={() => { setAdding(true); setOptKey(''); setTo(''); }}>{PLUS}Link a record</button>
      ) : provider ? <p className="set-help">This type has no relations in the schema yet.</p> : null}
    </div>
  );
}
