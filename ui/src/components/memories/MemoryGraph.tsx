'use client';
// Memories: one memory drawn as a graph. Every record the service returns is a node and every
// reference it may show is a line, with one exception that makes it readable: a fact that names
// a subject and an object IS the relationship between those two entities, so it is drawn as one
// labelled line between them, and clicking the line opens the fact. "Relate" writes such a fact:
// pick the first entity, the second, and say how they relate. The service returns nodes and
// edges only; where each sits is worked out here, to the shape of the space it has, so a narrow
// screen gets the same graph stood upright.
import { useEffect, useMemo, useRef, useState } from 'react';
import { addRecord, graph, labelOf, MemoryApiError, type Memory, type MemoryGraph as GraphData, type MemoryRecord } from '@/lib/memories';
import { SkelLine } from '@/components/Skel';
import { ICON, Ico, LEGEND, errText, recordIcon, typeColor, typeOne } from './kit';

const LIMIT = 150;
const CW = 176, CH = 118;      // the room one node takes: its circle and the caption under it
const R = 18, CAP_W = 170, CAP_H = 58;

/** Where each node sits. Nodes push each other apart, lines pull their two ends together, and
 *  the whole is drawn to the proportions of the space. The same input gives the same picture. */
function layout(n: number, links: [number, number][], aspect: number): { pts: [number, number][]; w: number; h: number } {
  if (!n) return { pts: [], w: 0, h: 0 };
  const t = Math.min(3, Math.max(0.3, (aspect * CH) / CW));
  const r0 = Math.sqrt(n) * 0.6;
  const p: [number, number][] = Array.from({ length: n }, (_, i) => {
    const a = (i / n) * Math.PI * 2 + 0.6;
    return [Math.cos(a) * r0 * Math.sqrt(t), (Math.sin(a) * r0) / Math.sqrt(t)];
  });
  const K = 0.9, G = 1.4, ITER = 320;
  for (let it = 0; it < ITER; it++) {
    const temp = 0.5 * (1 - it / ITER) + 0.01;
    const d: [number, number][] = p.map(() => [0, 0]);
    for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) {
      const dx = p[i][0] - p[j][0], dy = p[i][1] - p[j][1];
      const dist = Math.max(Math.hypot(dx, dy), 0.05), f = (K * K) / dist;
      d[i][0] += (dx / dist) * f; d[i][1] += (dy / dist) * f; d[j][0] -= (dx / dist) * f; d[j][1] -= (dy / dist) * f;
    }
    for (const [a, b] of links) {
      const dx = p[a][0] - p[b][0], dy = p[a][1] - p[b][1];
      const dist = Math.max(Math.hypot(dx, dy), 0.05), f = ((dist * dist) / K) * 0.6;
      d[a][0] -= (dx / dist) * f; d[a][1] -= (dy / dist) * f; d[b][0] += (dx / dist) * f; d[b][1] += (dy / dist) * f;
    }
    for (let i = 0; i < n; i++) {
      d[i][0] -= (p[i][0] * G) / Math.sqrt(t); d[i][1] -= p[i][1] * G * Math.sqrt(t);
      const len = Math.hypot(d[i][0], d[i][1]) || 1, step = Math.min(len, temp);
      p[i][0] += (d[i][0] / len) * step; p[i][1] += (d[i][1] / len) * step;
    }
  }
  // nothing sits on top of anything else, and two nodes a line joins stand far enough apart for
  // the line and its label to be seen between them
  const linked = new Set(links.map(([a, b]) => (a < b ? `${a}|${b}` : `${b}|${a}`)));
  for (let it = 0; it < 400; it++) {
    let moved = false;
    for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) {
      const dx = p[j][0] - p[i][0], dy = p[j][1] - p[i][1];
      const join = linked.has(`${i}|${j}`);
      const ox = (join ? 1.5 : 1) - Math.abs(dx), oy = (join ? 1.6 : 0.9) - Math.abs(dy);
      if (ox <= 0 || oy <= 0) continue;
      moved = true;
      // a joined pair is parted along the way it already leans; others along the shorter way out
      const alongX = join ? Math.abs(dx) * t >= Math.abs(dy) : ox < oy;
      if (alongX) { const s = (dx >= 0 ? 1 : -1) * (ox / 2 + 0.01); p[i][0] -= s; p[j][0] += s; }
      else { const s = (dy >= 0 ? 1 : -1) * (oy / 2 + 0.01); p[i][1] -= s; p[j][1] += s; }
    }
    if (!moved) break;
  }
  const xs = p.map((q) => q[0]), ys = p.map((q) => q[1]);
  const minX = Math.min(...xs), minY = Math.min(...ys);
  return {
    pts: p.map(([x, y]) => [(x - minX) * CW + 96, (y - minY) * CH + 34]),
    w: (Math.max(...xs) - minX) * CW + 192, h: (Math.max(...ys) - minY) * CH + 34 + CAP_H + 22,
  };
}

interface Line { key: string; a: number; b: number; label: string; fact?: MemoryRecord }

export function MemoryGraph({ memory, type, canEdit, rev, recId, onOpen, onAdded }: {
  memory: Memory; type: string; canEdit: boolean; rev: number; recId: string;
  onOpen: (memoryId: string, recordId: string) => void; onAdded: (r: MemoryRecord) => void;
}) {
  const [data, setData] = useState<GraphData | null>(null);
  const [err, setErr] = useState<MemoryApiError | Error | null>(null);
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const [zoom, setZoom] = useState<number | null>(null);
  const [connect, setConnect] = useState<{ from?: string; to?: string } | null>(null);
  const [pred, setPred] = useState('');
  const [busy, setBusy] = useState(false);
  const [relErr, setRelErr] = useState('');
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let alive = true;
    setErr(null);
    graph(memory.id, { limit: LIMIT }).then((g) => { if (alive) setData(g); }).catch((e) => { if (alive) { setData(null); setErr(e); } });
    return () => { alive = false; };
  }, [memory.id, rev]);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const measure = () => setSize((s) => {
      const w = Math.round(el.clientWidth / 40) * 40, h = Math.round(el.clientHeight / 40) * 40;
      return s && s.w === w && s.h === h ? s : { w, h };
    });
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const model = useMemo(() => {
    if (!data || !size) return null;
    const all = new Map(data.nodes.map((n) => [n.record.id, n.record]));
    // a fact with a subject and an object, both on the canvas, is the line between them
    const rels = new Map<string, { from: string; to: string }>();
    for (const r of all.values()) {
      if (r.type !== 'fact') continue;
      const s = r.references.find((f) => f.rel === 'subject' && f.available && all.has(f.record_id));
      const o = r.references.find((f) => f.rel === 'object' && f.available && all.has(f.record_id));
      if (s && o && s.record_id !== o.record_id) rels.set(r.id, { from: s.record_id, to: o.record_id });
    }
    const nodes = [...all.values()].filter((r) => !rels.has(r.id) && (type === 'all' || r.type === type || r.type === 'entity'));
    const at = new Map(nodes.map((r, i) => [r.id, i]));
    const lines: Line[] = [];
    if (type === 'all' || type === 'fact' || type === 'entity') {
      for (const [id, e] of rels) {
        const f = all.get(id)!;
        const a = at.get(e.from), b = at.get(e.to);
        if (a === undefined || b === undefined) continue;
        const p = typeof f.attributes?.predicate === 'string' ? f.attributes.predicate.replace(/_/g, ' ') : '';
        lines.push({ key: id, a, b, label: p || labelOf(f), fact: f });
      }
    }
    for (const e of data.edges) {
      if (!e.available || rels.has(e.from.record_id)) continue;
      const a = at.get(e.from.record_id), b = at.get(e.to.record_id);
      if (a === undefined || b === undefined || a === b) continue;
      lines.push({ key: `${e.from.record_id}>${e.to.record_id}>${e.rel || ''}`, a, b, label: (e.rel || '').toUpperCase().replace(/ /g, '_') });
    }
    const lay = layout(nodes.length, lines.map((l) => [l.a, l.b]), size.w < 520 ? Math.min(0.55, size.w / Math.max(size.h, 200)) : size.w / Math.max(size.h, 200));
    return { nodes, lines, ...lay, entities: nodes.filter((r) => r.type === 'entity').length };
  }, [data, size, type]);

  const fit = model && size && model.w ? Math.min((size.w - 32) / model.w, (size.h - 76) / model.h) : 1;
  const s = zoom ?? Math.max(0.6, Math.min(1, fit));
  const byId = (id?: string) => model?.nodes.find((r) => r.id === id);
  const from = byId(connect?.from), to = byId(connect?.to);

  const pick = (r: MemoryRecord) => {
    if (!connect) { onOpen(r.memory_id, r.id); return; }
    if (r.type !== 'entity') return;
    if (!connect.from) setConnect({ from: r.id });
    else if (connect.from !== r.id && !connect.to) { setConnect({ from: connect.from, to: r.id }); setPred(''); setRelErr(''); }
  };
  const saveRel = async () => {
    const p = pred.trim();
    if (!p || !from || !to || busy) return;
    setBusy(true); setRelErr('');
    try {
      const rec = await addRecord(memory.id, {
        type: 'fact', title: `${labelOf(from)} ${p} ${labelOf(to)}`, attributes: { predicate: p },
        references: [{ rel: 'subject', record_id: from.id, memory_id: from.memory_id }, { rel: 'object', record_id: to.id, memory_id: to.memory_id }],
      });
      setConnect(null); setPred('');
      onAdded(rec);
    } catch (e) { setRelErr(errText(e)); }
    finally { setBusy(false); }
  };

  const drawn = useMemo(() => {
    if (!model) return [];
    // lines between the same two nodes run side by side
    const groups = new Map<string, number[]>();
    model.lines.forEach((l, i) => { const k = l.a < l.b ? `${l.a}|${l.b}` : `${l.b}|${l.a}`; groups.set(k, [...(groups.get(k) || []), i]); });
    const capOf = (r: MemoryRecord) => ({ half: (Math.min(CAP_W, Math.max(44, labelOf(r).length * 6.1)) + 12) / 2 + 4, bottom: CAP_H });
    // a node is its circle plus the caption under it; a line starts and ends outside both
    const exit = (r: MemoryRecord, vx: number, vy: number) => {
      const c = capOf(r);
      if (vy > 0) {
        const tb = c.bottom / vy;
        if (Math.abs(vx * tb) <= c.half) return Math.max(R, tb);
        const ts = c.half / Math.abs(vx);
        if (vy * ts >= R * 0.7) return Math.max(R, ts);
      }
      return R;
    };
    return model.lines.map((l, i) => {
      const k = l.a < l.b ? `${l.a}|${l.b}` : `${l.b}|${l.a}`;
      const g = groups.get(k)!;
      const flip = l.a < l.b ? 1 : -1;
      const off = (g.indexOf(i) - (g.length - 1) / 2) * 22 * flip;
      const [x1, y1] = [model.pts[l.a][0] * s, model.pts[l.a][1] * s], [x2, y2] = [model.pts[l.b][0] * s, model.pts[l.b][1] * s];
      const dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy) || 1, ux = dx / len, uy = dy / len;
      const t1 = exit(model.nodes[l.a], ux, uy) + 2, t2 = exit(model.nodes[l.b], -ux, -uy) + 4;
      if (t1 + t2 >= len - 8) return null;
      const px = -uy * off, py = ux * off;
      const sx = x1 + ux * t1 + px, sy = y1 + uy * t1 + py, ex = x2 - ux * t2 + px, ey = y2 - uy * t2 + py;
      let ang = (Math.atan2(dy, dx) * 180) / Math.PI;
      if (ang > 90) ang -= 180;
      if (ang < -90) ang += 180;
      // a label runs along a line that is close to level; on a steep one it would lie across the
      // two nodes it joins, so there it is set level, in the gap between them
      if (Math.abs(ang) > 32) ang = 0;
      const on = Boolean(recId) && (l.fact ? l.fact.id === recId : model.nodes[l.a].id === recId || model.nodes[l.b].id === recId);
      return { ...l, sx, sy, ex, ey, mx: (sx + ex) / 2, my: (sy + ey) / 2, ang, on };
    }).filter((x): x is NonNullable<typeof x> => x !== null);
  }, [model, s, recId]);

  const total = memory.records?.count;
  const hint = connect && !connect.to ? (connect.from ? 'Now pick the entity it relates to' : 'Pick the first entity') : null;
  const canRelate = Boolean(model && model.entities >= 2);
  return (
    <div className="mem-graph" ref={box}>
      {err ? (
        <div className="mem-state">
          <strong>{err instanceof MemoryApiError && err.code === 'memory_unavailable' ? 'This memory is not answering right now' : 'The graph could not be drawn'}</strong>
          <span>{err.message}</span>
        </div>
      ) : !model ? (
        <div className="mem-state" aria-busy="true"><SkelLine w={180} h={12} /></div>
      ) : model.nodes.length === 0 ? (
        <div className="mem-state"><span>{type === 'all' ? 'Nothing kept here yet.' : `No ${type} records here.`}</span></div>
      ) : (
        <div className="mem-g-scroll">
          <div className="mem-g-canvas" style={{ width: Math.round(model.w * s), height: Math.round(model.h * s) }}>
            <svg width="100%" height="100%" aria-hidden="true">
              <defs>
                <marker id="mem-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 10 5 0 10z" fill="#9ca3af" /></marker>
                <marker id="mem-arrow-on" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 10 5 0 10z" fill="#1a5cf5" /></marker>
              </defs>
              {drawn.map((e) => (
                <g key={e.key}>
                  <line x1={e.sx} y1={e.sy} x2={e.ex} y2={e.ey} stroke={e.on ? '#1a5cf5' : '#a8a29e'} strokeWidth={e.fact ? 1.4 : 1.1} markerEnd={e.on ? 'url(#mem-arrow-on)' : 'url(#mem-arrow)'} />
                  {e.fact && !connect && <line x1={e.sx} y1={e.sy} x2={e.ex} y2={e.ey} stroke="transparent" strokeWidth={14} className="mem-g-hitline" onClick={() => onOpen(e.fact!.memory_id, e.fact!.id)} />}
                </g>
              ))}
            </svg>
            {model.nodes.map((r, i) => {
              const name = labelOf(r) || 'Untitled';
              const picked = connect && (connect.from === r.id || connect.to === r.id);
              const dim = Boolean(connect) && r.type !== 'entity';
              const color = typeColor(r.type);
              return (
                <button key={r.id} type="button" className={'mem-g-node' + (dim ? ' is-dim' : '')} title={name} disabled={dim}
                  aria-label={`${typeOne(r.type)}: ${name}`} aria-pressed={connect ? Boolean(picked) : undefined}
                  style={{ left: model.pts[i][0] * s - 90, top: model.pts[i][1] * s - R }} onClick={() => pick(r)}>
                  <span className="mem-g-dot" style={{ background: color, boxShadow: `0 0 0 ${r.id === recId || picked ? `4px ${color}33` : '3px #ffffff'}, 0 2px 6px rgba(28, 25, 23, 0.18)` }}>
                    <Ico d={recordIcon(r)} size={16} sw={1.5} style={{ color: '#fff' }} />
                  </span>
                  <span className="mem-g-cap"><b>{typeOne(r.type)}</b><span className="mem-ell">{name}</span></span>
                </button>
              );
            })}
            {drawn.filter((e) => e.label).map((e) => {
              const st = { left: e.mx, top: e.my, transform: `translate(-50%, -50%) rotate(${e.ang.toFixed(1)}deg)` };
              return e.fact
                ? <button key={e.key} type="button" className={'mem-g-label is-rel' + (e.on ? ' is-on' : '')} style={st} disabled={Boolean(connect)} title={labelOf(e.fact)} aria-label={`Fact: ${labelOf(e.fact)}`} onClick={() => onOpen(e.fact!.memory_id, e.fact!.id)}>{e.label}</button>
                : <span key={e.key} className={'mem-g-label' + (e.on ? ' is-on' : '')} style={st}>{e.label}</span>;
            })}
          </div>
        </div>
      )}

      {data && data.degraded.length > 0 && <div className="mem-g-note">{`Drawn without: ${data.degraded.join(', ')}`}</div>}
      {canEdit && model && model.nodes.length > 0 && (
        <div className="mem-g-tools">
          {!canRelate && <span className="mem-g-why">Needs two entities</span>}
          <button type="button" className={'mem-g-relate' + (connect ? ' is-on' : '')} disabled={!canRelate} aria-pressed={Boolean(connect)}
            title={canRelate ? 'Say how two entities relate' : 'Add two entities to this memory first'}
            onClick={() => { setConnect(connect ? null : {}); setRelErr(''); }}>
            <Ico d={ICON.relate} size={13} sw={1.5} /><span>Relate</span>
          </button>
        </div>
      )}
      {hint && (
        <div className="mem-g-hint" role="status"><span>{hint}</span><button type="button" onClick={() => setConnect(null)}>Cancel</button></div>
      )}
      {connect && from && to && (
        <div className="mem-g-rel" role="dialog" aria-label="How are they related">
          <div className="mem-g-rel-who"><b>{labelOf(from)}</b> … <b>{labelOf(to)}</b></div>
          <input autoFocus value={pred} onChange={(e) => setPred(e.target.value)} aria-label="How are they related" placeholder="is head of procurement at"
            onKeyDown={(e) => { if (e.key === 'Escape') setConnect(null); if (e.key === 'Enter') void saveRel(); }} />
          {relErr && <div className="mem-field-err" role="alert">{relErr}</div>}
          <div className="mem-g-rel-acts">
            <button type="button" className="mem-btn" onClick={() => setConnect(null)} disabled={busy}>Cancel</button>
            <button type="button" className="mem-btn is-primary" onClick={() => void saveRel()} disabled={busy || !pred.trim()}>{busy ? 'Adding…' : 'Add fact'}</button>
          </div>
        </div>
      )}
      {model && model.nodes.length > 0 && (
        <>
          <div className="mem-g-legend">
            {LEGEND.map((k) => <span key={k}><i style={{ background: typeColor(k) }} />{typeOne(k)}</span>)}
          </div>
          <div className="mem-g-zoom">
            <button type="button" aria-label="Zoom in" onClick={() => setZoom(Math.min(1.6, s * 1.2))}>+</button>
            <button type="button" aria-label="Zoom out" onClick={() => setZoom(Math.max(0.4, s / 1.2))}>−</button>
            <button type="button" aria-label="Fit to view" onClick={() => setZoom(Math.max(0.4, Math.min(1.6, fit)))}><Ico d={ICON.fit} size={13} sw={1.5} /></button>
          </div>
          <div className="mem-g-foot">
            {`${data?.nodes.length ?? 0} of ${typeof total === 'number' ? total : '—'} records`}{data?.truncated ? ' · not all are drawn' : ''}
          </div>
        </>
      )}
    </div>
  );
}
