'use client';
// A record's neighbourhood (the design's mmConnHtml): the record in the middle, what it links to around
// it, a second ring at two hops, and the same links as a list. A fact's sentence is what a link reads as;
// the word it was filed under comes second, and a link with no real name is plainly "related to".
import { useState } from 'react';
import { labelOf, type GraphEdge, type MemoryGraph, type MemoryRecord, type Provider } from '@/lib/memories';
import { kindOf, relText } from './caps';
import { PLUS, X } from './parts';
import { MM_ICONS, typeLabel, type LSchema } from './schemaModel';
import { kindInfo } from './tree';

export type LinkOption = { key: string; rel: string; out: boolean; other: string | null; label: string };

const secondWord = (node: MemoryRecord | undefined, e: GraphEdge) => relText(String(node?.attributes?.predicate || '') || e.rel);

function layout(rid: string, g: MemoryGraph, hops: number) {
  const W = 380, H = 330, cx = W / 2, cy = H / 2;
  const P = new Map<string, [number, number, number, boolean]>([[rid, [cx, cy, 0, false]]]);
  const have = new Set(g.nodes.map((n) => n.record.id));
  const ends = (e: GraphEdge): [string, string] => [e.from.record_id, e.to.record_id];
  const near = (id: string) => g.edges.filter((e) => ends(e).includes(id) && e.available).map((e) => (e.from.record_id === id ? e.to.record_id : e.from.record_id)).filter((o) => have.has(o));
  const seen = new Set([rid]);
  const r1: string[] = [];
  near(rid).forEach((o) => { if (!seen.has(o)) { seen.add(o); r1.push(o); } });
  const R1 = hops > 1 ? 86 : 104;
  r1.forEach((id, i) => { const a = -Math.PI / 2 + (i * 2 * Math.PI) / Math.max(1, r1.length); P.set(id, [cx + R1 * Math.cos(a), cy + R1 * Math.sin(a), a, false]); });
  if (hops > 1) {
    for (const pid of r1) {
      const kids = near(pid).filter((o) => !seen.has(o));
      kids.forEach((o) => seen.add(o));
      const pa = (P.get(pid) as [number, number, number, boolean])[2];
      kids.forEach((id, j) => {
        const a = pa + (j - (kids.length - 1) / 2) * 0.42;
        P.set(id, [Math.max(24, Math.min(W - 24, cx + 148 * Math.cos(a))), Math.max(18, Math.min(H - 28, cy + 142 * Math.sin(a))), a, true]);
      });
    }
  }
  return { P, W, H };
}

export function Connections({ record, graph, failed, retry, hops, setHops, schema, options, candidates, provider, onOpen, onLink, onUnlink, canUnlink, onClose }: {
  record: MemoryRecord | null; graph: MemoryGraph | null; failed: boolean; retry: () => void;
  hops: number; setHops: (n: number) => void; schema: LSchema | null;
  options: LinkOption[] | null; candidates: (o: LinkOption) => MemoryRecord[]; provider: Provider | null;
  onOpen: (rid: string, memoryId?: string) => void;
  onLink: (o: LinkOption, rel: string, to: string) => Promise<void>;
  onUnlink: (e: GraphEdge) => void; canUnlink: (e: GraphEdge) => boolean; onClose: () => void;
}) {
  const [adding, setAdding] = useState(false);
  const [optKey, setOptKey] = useState('');
  const [freeRel, setFreeRel] = useState('related');
  const [to, setTo] = useState('');
  const [busy, setBusy] = useState(false);
  const head = (
    <div className="mm-conn-bar"><b>Connections</b>
      <div className="seg mm-hops" role="group" aria-label="Depth">
        {[1, 2].map((n) => <button key={n} type="button" className={hops === n ? 'on' : ''} aria-pressed={hops === n} onClick={() => setHops(n)}>{`${n} hop${n > 1 ? 's' : ''}`}</button>)}
      </div>
      <button type="button" className="icon-btn sm mm-cclose" aria-label="Close connections" onClick={onClose}>{X}</button>
    </div>
  );
  if (!record || !record.id) return <>{head}<p className="mm-muted mm-cpad">Open a record to see what it links to.</p></>;
  if (failed) return <>{head}<p className="mm-muted mm-cpad" role="alert">What this links to could not be read just now. <button type="button" className="link-q inl" onClick={retry}>Try again</button></p></>;
  const g: MemoryGraph = graph || { nodes: [{ record, memory: { id: record.memory_id, name: '' } }], edges: [], truncated: false, degraded: [] };
  const { P, W, H } = layout(record.id, g, hops);
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
    <>
      {head}
      <div className="mm-cgw">
        <svg className="mm-cg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Records linked to ${labelOf(record) || 'this record'}`}>
          {g.edges.map((e, i) => {
            const a = P.get(e.from.record_id), b = P.get(e.to.record_id);
            if (!a || !b) return null;
            return <line key={i} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} className={`mm-cl${e.from.record_id === record.id || e.to.record_id === record.id ? ' near' : ''}`} />;
          })}
          {[...P.entries()].map(([id, p]) => {
            const n = nodeOf(id);
            if (!n) return null;
            const k = kindInfo(kindOf(n.record), schema), me = id === record.id, far = p[3];
            const rad = me ? 17 : far ? 8 : 11, mx = me ? 24 : far ? 13 : 17;
            const cap = schema?.types.find((t) => t.name === kindOf(n.record))?.caption;
            const full = (cap && cap !== 'title' ? String(n.record.attributes?.[cap] || '') : '') || labelOf(n.record) || 'Untitled';
            const ca = Math.cos(p[2]), sa = Math.sin(p[2]);
            let lx = 0, ly = rad + 14, an: 'middle' | 'start' | 'end' = 'middle';
            if (!me && !far && hops === 1) {
              if (ca > 0.35) { lx = rad + 6; ly = 4; an = 'start'; } else if (ca < -0.35) { lx = -rad - 6; ly = 4; an = 'end'; } else if (sa < 0) ly = -rad - 7;
            }
            // a label beside its node has only the room up to the panel's edge
            const room = an === 'end' ? p[0] - rad - 6 : an === 'start' ? W - p[0] - rad - 6 : W;
            const fit = Math.min(mx, Math.max(4, Math.floor(room / 6)));
            const lab = full.length > fit ? `${full.slice(0, fit - 1).trim()}…` : full;
            return (
              <g key={id} className={`mm-cn${me ? ' me' : ''}`} transform={`translate(${p[0].toFixed(1)} ${p[1].toFixed(1)})`} onClick={() => onOpen(id, n.memory.id)}>
                <circle r={rad + 5} className="mm-cnh" /><circle r={rad} fill={k.color} />
                <g transform={`translate(${-rad * 0.55} ${-rad * 0.55}) scale(${(rad * 1.1) / 24})`}><path d={MM_ICONS[k.icon] || MM_ICONS.note} fill="none" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" /></g>
                <text x={lx} y={ly} textAnchor={an} className={`mm-cnl${far ? ' far' : ''}`}>{lab}</text>
                <title>{full}</title>
              </g>
            );
          })}
        </svg>
      </div>
      <div className="mm-clist">
        {mine.length ? mine.map((e, i) => {
          const out = e.from.record_id === record.id;
          const other = out ? e.to.record_id : e.from.record_id;
          const n = e.available ? nodeOf(other) : undefined;
          if (!n) {
            return <div className="mm-lr" key={i}><span className="mm-lb"><span className="mm-lt off">A record you can’t open</span></span></div>;
          }
          const k = kindInfo(kindOf(n.record), schema);
          return (
            <div className="mm-lr" key={i}>
              <span className="mm-lb">
                <button type="button" className="mm-lt" onClick={() => onOpen(other, n.memory.id)}><span className="mm-dot sm" style={{ background: k.color }} /><span>{labelOf(n.record) || 'Untitled'}</span></button>
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
    </>
  );
}
