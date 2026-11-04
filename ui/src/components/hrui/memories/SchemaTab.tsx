'use client';
// A memory's schema, as its provider reads it. Types and relations on a canvas where the provider
// guides by them (the design's mmSchemaHtml, mmPanelHtml, mmTypePanel, mmRelPanel); a plain list of
// names where it applies labels. Only what the provider reads is offered: no property section where
// it reads no properties, no way to draw a relation where it reads none.
import { useEffect, useRef, useState, type PointerEvent as RPointerEvent } from 'react';
import type { Memory, PropType, Provider } from '@/lib/memories';
import { ConfirmSheet } from '../Sheet';
import { plural } from '../setup/settingsModel';
import { toast } from '../toast';
import { guideLine, hasProperties, hasRelations, NO_RELATIONS_LINE, relText, RELATIONS_LINE, schemaGuides, TYPES_LINE } from './caps';
import { ARRANGE, ARROW, MmIco, PLUS, RELATE, X } from './parts';
import {
  circle, freeSpot, MM_COLORS, MM_ICONS, MM_PTYPES, MM_STARTS, propNameOf, relNameOf, startSchema, typeLabel, typeNameOf, uid, VB, type LRel, type LType,
} from './schemaModel';
import type { SchemaDoc } from './useSchemaDoc';

interface TabProps {
  memory: Memory; provider: Provider; doc: SchemaDoc; ro: boolean;
  /** how many read records are of a type; null when not all were read */
  countOf: (typeName: string) => number | null;
  onOpenData: (typeName: string) => void;
}

/** Saving, saved or why not, in the words a person needs. */
function SaveLine({ doc }: { doc: SchemaDoc }) {
  if (doc.state === 'error') {
    return <p className="mm-sstat bad" role="alert">{doc.error} <button type="button" className="link-q inl" onClick={doc.saveNow}>Try again</button></p>;
  }
  if (doc.state === 'saving') return <p className="mm-sstat" role="status">Saving…</p>;
  if (doc.state === 'saved') return <p className="mm-sstat" role="status">Saved</p>;
  return null;
}

// ── labels: a flat list ─────────────────────────────────────────────────────────────────────
export function LabelsTab({ provider, doc, ro }: Pick<TabProps, 'provider' | 'doc' | 'ro'>) {
  if (!doc.schema) {
    return doc.failed ? <div className="scroll mm-labels"><div className="mm-labels-col" role="alert">The labels could not be read just now. <button type="button" className="link-q inl" onClick={doc.retry}>Try again</button></div></div> : null;
  }
  const list = doc.schema.types;
  const add = () => doc.update((d) => { d.types.push({ id: uid('t'), name: '', description: '', properties: [], color: MM_COLORS[d.types.length % MM_COLORS.length], icon: 'tag', x: 0, y: 0, caption: 'title' }); }, false);
  return (
    <div className="scroll mm-labels">
      <div className="mm-labels-col">
        <h2>Labels</h2>
        <p className="mm-pd">{guideLine(provider)}</p>
        {list.length ? (
          <div className="mm-lablist">
            <div className="mm-labrow mm-prh"><span>Name</span><span>What it means</span><span /></div>
            {list.map((t) => (
              <div className="mm-labrow" key={t.id}>
                <input className="set-in slim" aria-label="Label name" placeholder="Name" value={typeLabel(t.name)} disabled={ro}
                  onChange={(e) => { const n = typeNameOf(e.target.value); doc.update((d) => { const x = d.types.find((y) => y.id === t.id); if (x) x.name = n; }); }} />
                <input className="set-in slim" aria-label={`What ${typeLabel(t.name) || 'this label'} means`} placeholder="What a fact with this label is about" value={t.description} disabled={ro}
                  onChange={(e) => { const v = e.target.value; doc.update((d) => { const x = d.types.find((y) => y.id === t.id); if (x) x.description = v; }); }} />
                {ro ? <span /> : <button type="button" className="icon-btn sm" aria-label={`Remove ${typeLabel(t.name) || 'this label'}`} onClick={() => doc.update((d) => { d.types = d.types.filter((y) => y.id !== t.id); })}>{X}</button>}
              </div>
            ))}
          </div>
        ) : <p className="mm-muted">No labels yet.</p>}
        {ro ? null : <button type="button" className="btn small mm-add" onClick={add}>{PLUS}Add label</button>}
        <SaveLine doc={doc} />
      </div>
    </div>
  );
}

// ── types and relations: the canvas ─────────────────────────────────────────────────────────
export function SchemaTab({ memory, provider, doc, ro, countOf, onOpenData }: TabProps) {
  const s = doc.schema || { types: [], relations: [] };
  const [sel, setSel] = useState<string | null>(null);
  const [relate, setRelate] = useState<{ from: string | null } | null>(null);
  const [confirm, setConfirm] = useState<{ kind: 'type'; t: LType } | { kind: 'rel'; r: LRel } | null>(null);
  const relations = hasRelations(provider);
  const svg = useRef<SVGSVGElement | null>(null);
  const drag = useRef<{ id: string; dx: number; dy: number; moved: boolean; x0: number; y0: number } | null>(null);
  // however narrow the canvas, a type stays big enough to read and to press: the drawing scales with the
  // window, and each node is drawn larger by as much as the scale took away (the design's fixed size is
  // unreadable on a phone)
  const [k, setK] = useState(1);
  const drawn = s.types.length > 0;
  useEffect(() => {
    const el = svg.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const fit = () => {
      const r = el.getBoundingClientRect();
      const f = Math.min(r.width / VB[0], r.height / VB[1]);
      setK(f > 0 ? Math.max(1, Math.min(2, 0.72 / f)) : 1);
    };
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    return () => ro.disconnect();
  }, [drawn]);
  const focusName = useRef(false);
  const nameRef = (el: HTMLInputElement | null) => { if (el && focusName.current) { focusName.current = false; el.focus(); el.select(); } };

  const type = s.types.find((t) => t.id === sel) || null;
  const rel = type ? null : s.relations.find((r) => r.id === sel) || null;

  const addType = () => {
    const [x, y] = freeSpot(s);
    const id = uid('t');
    doc.update((d) => { d.types.push({ id, name: 'New_type', description: '', properties: [], color: MM_COLORS[d.types.length % MM_COLORS.length], icon: 'tag', x, y, caption: 'title' }); });
    focusName.current = true;
    setSel(id);
    setRelate(null);
  };
  const addRelation = (from: string, to: string) => {
    const id = uid('r');
    doc.update((d) => { d.relations.push({ id, name: 'RELATES_TO', description: '', from, to }); });
    focusName.current = true;
    setRelate(null);
    setSel(id);
    toast('Relation added. Name it.');
  };
  const arrange = () => {
    const spots = circle(s.types.length);
    doc.update((d) => { d.types.forEach((t, k) => { [t.x, t.y] = spots[k]; }); });
  };
  const start = (i: number) => {
    const fresh = startSchema(i, provider);
    doc.update((d) => { d.types = fresh.types; d.relations = fresh.relations; });
    setSel(null);
    toast(`Started from ${MM_STARTS[i][0]}. Rename or remove anything.`);
  };

  const pt = (e: RPointerEvent) => {
    const sv = svg.current, m = sv?.getScreenCTM?.();
    if (!sv || !m) return { x: 0, y: 0 };
    const p = sv.createSVGPoint();
    p.x = e.clientX; p.y = e.clientY;
    const q = p.matrixTransform(m.inverse());
    return { x: q.x, y: q.y };
  };
  const down = (e: RPointerEvent<SVGSVGElement>) => {
    const g = (e.target as Element).closest('[data-mmnode]');
    if (!g) {
      const ed = (e.target as Element).closest('[data-mmedge]');
      if (ed) { setSel(ed.getAttribute('data-mmedge')); setRelate(null); } else if (sel && !relate) setSel(null);
      return;
    }
    const t = s.types.find((x) => x.id === g.getAttribute('data-mmnode'));
    if (!t) return;
    const p = pt(e);
    drag.current = { id: t.id, dx: p.x - t.x, dy: p.y - t.y, moved: false, x0: e.clientX, y0: e.clientY };
    try { svg.current?.setPointerCapture(e.pointerId); } catch { /* a node that went away */ }
    e.preventDefault();
  };
  const move = (e: RPointerEvent<SVGSVGElement>) => {
    const d = drag.current;
    if (!d || ro) return;
    if (!d.moved && Math.hypot(e.clientX - d.x0, e.clientY - d.y0) < 4) return;
    d.moved = true;
    const p = pt(e);
    const x = Math.max(40, Math.min(VB[0] - 40, Math.round(p.x - d.dx))), y = Math.max(30, Math.min(VB[1] - 70, Math.round(p.y - d.dy)));
    doc.update((o) => { const t = o.types.find((n) => n.id === d.id); if (t) { t.x = x; t.y = y; } }, false);
  };
  const up = () => {
    const d = drag.current;
    drag.current = null;
    if (!d) return;
    if (d.moved) { doc.saveNow(); return; }
    if (relate) {
      if (!relate.from) { setRelate({ from: d.id }); return; }
      addRelation(relate.from, d.id);
      return;
    }
    setSel(d.id);
  };

  const editType = (fn: (t: LType) => void) => doc.update((d) => { const t = d.types.find((x) => x.id === sel); if (t) fn(t); });
  const editRel = (fn: (r: LRel) => void) => doc.update((d) => { const r = d.relations.find((x) => x.id === sel); if (r) fn(r); });
  const typeName = (id: string) => typeLabel(s.types.find((t) => t.id === id)?.name || '');

  const panel = type ? (
    <TypePanel t={type} ro={ro} provider={provider} rels={s.relations} typeName={typeName} count={countOf(type.name)} nameRef={nameRef}
      onEdit={editType} onClose={() => setSel(null)} onSel={setSel} onDelete={() => setConfirm({ kind: 'type', t: type })}
      onAddRelation={() => { const other = s.types.find((x) => x.id !== type.id) || type; addRelation(type.id, other.id); }}
      onOpenData={() => onOpenData(type.name)} />
  ) : rel ? (
    <RelPanel r={rel} ro={ro} types={s.types} typeName={typeName} nameRef={nameRef} onEdit={editRel} onClose={() => setSel(null)} onDelete={() => setConfirm({ kind: 'rel', r: rel })} />
  ) : (
    <div>
      <div className="mm-ph"><div className="grow"><h2>Schema</h2>
        <p className="mm-pd">{relations ? `${plural(s.types.length, 'type')} and ${plural(s.relations.length, 'relation')}.` : `${plural(s.types.length, 'type')}.`}</p>
      </div></div>
      <div className="mm-sec"><div className="mm-sh">Types</div>
        {schemaGuides(provider) ? <p className="set-help mm-always">{TYPES_LINE}</p> : null}
        {s.types.length ? s.types.map((x) => (
          <button key={x.id} type="button" className="mm-li" onClick={() => { setSel(x.id); setRelate(null); }}>
            <span className="mm-dot" style={{ background: x.color }}><MmIco k={x.icon} size={12} color="#fff" /></span><b>{typeLabel(x.name) || 'Untitled'}</b>
            {hasProperties(provider) ? <small>{x.properties.length === 1 ? '1 property' : `${x.properties.length} properties`}</small> : null}
          </button>
        )) : <p className="mm-muted">No types yet.</p>}
      </div>
      {relations ? (
        <div className="mm-sec"><div className="mm-sh">Relations</div>
          <p className="set-help mm-always">{s.relations.length ? RELATIONS_LINE : NO_RELATIONS_LINE}</p>
          {s.relations.map((x) => (
            <button key={x.id} type="button" className="mm-li" onClick={() => { setSel(x.id); setRelate(null); }}>
              <span className="mm-rn mono">{relText(x.name)}</span><small>{typeName(x.from)} → {typeName(x.to)}</small>
            </button>
          ))}
          {s.relations.length || ro ? null : <p className="mm-muted">Use Relate to link two types.</p>}
        </div>
      ) : null}
    </div>
  );

  return (
    <div className={`mm-schema${sel && (type || rel) ? ' has-sel' : ''}`}>
      <div className="mm-canvas">
        {ro || !doc.schema ? null : (
          <div className="mm-tools" role="toolbar" aria-label="Schema">
            <button type="button" className="mm-tb" onClick={addType}>{PLUS}Type</button>
            {relations ? <button type="button" className={`mm-tb${relate ? ' on' : ''}`} aria-pressed={!!relate} onClick={() => setRelate(relate ? null : { from: null })}>{RELATE}Relate</button> : null}
            <button type="button" className="mm-tb" title="Arrange in a circle" onClick={arrange}>{ARRANGE}Arrange</button>
          </div>
        )}
        {relate ? (
          <div className="mm-hint on">{relate.from ? 'Now pick the type it points to.' : 'Pick the type the relation starts from.'}
            <button type="button" className="link-q inl" onClick={() => setRelate(null)}>Cancel</button>
          </div>
        ) : null}
        {!doc.schema && doc.failed ? (
          <div className="mm-sch-empty" role="alert"><p>The schema could not be read just now. <button type="button" className="link-q inl" onClick={doc.retry}>Try again</button></p></div>
        ) : doc.schema && !s.types.length ? (
          <div className="mm-sch-empty">
            <h2>Design what this memory keeps</h2>
            <p>{`A type is a kind of thing, like a person, a company or a product. ${hasProperties(provider) ? 'Give it properties.' : 'Give it a name and say what it is.'}${relations ? ' Relating types is optional.' : ''}`}</p>
            {ro ? null : (
              <div className="mm-starts">
                {MM_STARTS.map(([n, sub], i) => <button key={n} type="button" className="mm-start" onClick={() => start(i)}><b>{n}</b><small>{sub}</small></button>)}
                <button type="button" className="mm-start" onClick={addType}><b>Blank</b><small>Start with one type</small></button>
              </div>
            )}
          </div>
        ) : null}
        {s.types.length ? (
          <svg ref={svg} className="mm-svg" viewBox={`0 0 ${VB[0]} ${VB[1]}`} preserveAspectRatio="xMidYMid meet" onPointerDown={down} onPointerMove={move} onPointerUp={up}>
            <defs>
              <marker id="mmArw" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" className="mm-ah" /></marker>
              <marker id="mmArwOn" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" className="mm-ah on" /></marker>
            </defs>
            {s.relations.map((r) => <Edge key={r.id} r={r} a={s.types.find((t) => t.id === r.from)} b={s.types.find((t) => t.id === r.to)} on={sel === r.id} k={k} />)}
            {s.types.map((t) => {
              const n = countOf(t.name);
              return (
                <g key={t.id} className={`mm-n${sel === t.id || relate?.from === t.id ? ' on' : ''}${relate ? ' pickable' : ''}`} data-mmnode={t.id} transform={`translate(${t.x} ${t.y})`} tabIndex={0} role="button" aria-label={typeLabel(t.name) || 'Untitled'}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSel(t.id); } }}>
                  <g transform={`scale(${k})`}>
                    <circle className="mm-halo" r="31" /><circle r="23" fill={t.color} />
                    <g transform="translate(-11 -11) scale(.917)"><path d={MM_ICONS[t.icon] || MM_ICONS.note} fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></g>
                    <text className="mm-nl" y="44">{typeLabel(t.name) || 'Untitled'}</text>
                    {n != null ? <text className="mm-ns" y="59">{plural(n, 'record')}</text> : null}
                  </g>
                </g>
              );
            })}
          </svg>
        ) : null}
        <div className="mm-foot">
          <SaveLine doc={doc} />
          <p className="mm-guide">{guideLine(provider)}</p>
          {s.types.length && !relate && !ro ? <p className="mm-hint">Drag types to arrange them. Click one to edit it.</p> : null}
        </div>
      </div>
      <aside className="mm-panel" aria-label="Schema details">{panel}</aside>
      {confirm?.kind === 'type' ? (
        <ConfirmSheet id="mmDt" title={`Delete ${typeLabel(confirm.t.name)}?`} confirmLabel={`Delete ${typeLabel(confirm.t.name)}`}
          body={`Removes ${typeLabel(confirm.t.name)} from the schema of ${memory.name}, and every relation that uses it. Records already kept stay as they are.`}
          onClose={() => setConfirm(null)}
          onConfirm={() => {
            const id = confirm.t.id;
            doc.update((d) => { d.types = d.types.filter((x) => x.id !== id); d.relations = d.relations.filter((r) => r.from !== id && r.to !== id); });
            setSel(null); setConfirm(null); toast(`${typeLabel(confirm.t.name)} deleted`);
          }} />
      ) : null}
      {confirm?.kind === 'rel' ? (
        <ConfirmSheet id="mmDr" title={`Delete ${relText(confirm.r.name)}?`} confirmLabel="Delete relation"
          body="Removes the relation from the schema. Links already made stay on their records."
          onClose={() => setConfirm(null)}
          onConfirm={() => {
            const id = confirm.r.id;
            doc.update((d) => { d.relations = d.relations.filter((r) => r.id !== id); });
            setSel(null); setConfirm(null); toast(`${relText(confirm.r.name)} deleted`);
          }} />
      ) : null}
    </div>
  );
}

function Edge({ r, a, b, on, k }: { r: LRel; a?: LType; b?: LType; on: boolean; k: number }) {
  if (!a || !b) return null;
  const end = `url(#mmArw${on ? 'On' : ''})`;
  if (a === b) {
    const cx = a.x, cy = a.y;
    return (
      <g className={`mm-e${on ? ' on' : ''}`} data-mmedge={r.id}>
        <path d={`M${cx + 18} ${cy - 18} C${cx + 70} ${cy - 80} ${cx + 80} ${cy + 10} ${cx + 24} ${cy + 6}`} fill="none" className="mm-el" markerEnd={end} />
        <text className="mm-elabel" style={{ fontSize: 9.5 * k }} x={cx + 70} y={cy - 40}>{relText(r.name)}</text>
      </g>
    );
  }
  const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1, ux = dx / len, uy = dy / len;
  const sx = a.x + ux * 27 * k, sy = a.y + uy * 27 * k, ex = b.x - ux * 31 * k, ey = b.y - uy * 31 * k, mx = (sx + ex) / 2, my = (sy + ey) / 2;
  let ang = (Math.atan2(dy, dx) * 180) / Math.PI;
  if (ang > 90) ang -= 180;
  if (ang < -90) ang += 180;
  return (
    <g className={`mm-e${on ? ' on' : ''}`} data-mmedge={r.id}>
      <line className="mm-hit" x1={sx} y1={sy} x2={ex} y2={ey} />
      <line className="mm-el" x1={sx} y1={sy} x2={ex} y2={ey} markerEnd={end} />
      <text className="mm-elabel" style={{ fontSize: 9.5 * k }} x={mx} y={my - 5 * k} transform={`rotate(${ang.toFixed(1)} ${mx} ${my})`}>{relText(r.name)}</text>
    </g>
  );
}

function TypePanel({ t, ro, provider, rels, typeName, count, nameRef, onEdit, onClose, onSel, onDelete, onAddRelation, onOpenData }: {
  t: LType; ro: boolean; provider: Provider; rels: LRel[]; typeName: (id: string) => string; count: number | null;
  nameRef: (el: HTMLInputElement | null) => void; onEdit: (fn: (t: LType) => void) => void;
  onClose: () => void; onSel: (id: string) => void; onDelete: () => void; onAddRelation: () => void; onOpenData: () => void;
}) {
  const label = typeLabel(t.name);
  const mine = rels.filter((r) => r.from === t.id || r.to === t.id);
  return (
    <div>
      <div className="mm-ph">
        <span className="mm-tic" style={{ background: t.color }}><MmIco k={t.icon} size={18} color="#fff" /></span>
        <div className="grow">
          <input ref={nameRef} className="mm-tname" aria-label="Type name" placeholder="Type name" disabled={ro} value={label}
            onChange={(e) => { const n = typeNameOf(e.target.value); onEdit((x) => { x.name = n; }); }}
            onBlur={() => { if (/^_|_$/.test(t.name)) onEdit((x) => { x.name = x.name.replace(/^_+|_+$/g, ''); }); }} />
          <textarea className="mm-tdesc" rows={2} aria-label="Description" placeholder="What is one of these? Agents read this." disabled={ro} value={t.description}
            onChange={(e) => { const v = e.target.value; onEdit((x) => { x.description = v; }); }} />
        </div>
        <button type="button" className="icon-btn sm" aria-label="Close" onClick={onClose}>{X}</button>
      </div>
      {schemaGuides(provider) ? <p className="mm-note">{TYPES_LINE}</p> : null}
      {ro ? null : (
        <>
          <div className="mm-sec"><div className="mm-sh">Color</div>
            <div className="mm-sw">{MM_COLORS.map((c) => <button key={c} type="button" className={c === t.color ? 'on' : ''} style={{ background: c }} aria-label={`Color ${c}`} aria-pressed={c === t.color} onClick={() => onEdit((x) => { x.color = c; })} />)}</div>
          </div>
          <div className="mm-sec"><div className="mm-sh">Icon</div>
            <div className="mm-ig">{Object.keys(MM_ICONS).map((k) => <button key={k} type="button" className={k === t.icon ? 'on' : ''} aria-label={`Icon ${k}`} aria-pressed={k === t.icon} onClick={() => onEdit((x) => { x.icon = k; })}><MmIco k={k} size={17} /></button>)}</div>
          </div>
        </>
      )}
      {hasProperties(provider) ? (
        <>
          <div className="mm-sec"><div className="mm-sh">Caption</div>
            <select className="set-in slim" aria-label="Caption" disabled={ro} value={t.caption} onChange={(e) => { const v = e.target.value; onEdit((x) => { x.caption = v; }); }}>
              {[['title', 'Title'], ...t.properties.map((p) => [p.name, p.name])].map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
            <p className="set-help">{`Which field labels each ${label || 'record'} on graphs.`}</p>
          </div>
          <div className="mm-sec" data-section="properties">
            <div className="mm-sh">Properties<span className="mm-shn">{t.properties.length}</span></div>
            <p className="set-help mm-always">Every record also has a title, text and links.</p>
            {t.properties.length ? (
              <div className="mm-props-ed">
                <div className="mm-pr mm-prh"><span>Name</span><span>Type</span><span /></div>
                {t.properties.map((p) => (
                  <div className="mm-pr" key={p.id}>
                    <input className="set-in slim mono" aria-label="Property name" placeholder="name" disabled={ro} value={p.name}
                      onChange={(e) => { const n = propNameOf(e.target.value), old = p.name; onEdit((x) => { const y = x.properties.find((o) => o.id === p.id); if (y) y.name = n; if (x.caption === old) x.caption = n; }); }} />
                    <select className="set-in slim" aria-label="Property type" disabled={ro} value={p.type}
                      onChange={(e) => { const v = e.target.value as PropType; onEdit((x) => { const y = x.properties.find((o) => o.id === p.id); if (y) y.type = v; }); }}>
                      {MM_PTYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                    </select>
                    {ro ? <span /> : (
                      <button type="button" className="icon-btn sm" aria-label={`Remove ${p.name}`}
                        onClick={() => onEdit((x) => { x.properties = x.properties.filter((o) => o.id !== p.id); if (x.caption === p.name) x.caption = 'title'; })}>{X}</button>
                    )}
                    {p.type === 'choice' ? (
                      <input className="set-in slim mm-popt" aria-label="Choices" placeholder="Choices, separated by commas" disabled={ro} value={p.options}
                        onChange={(e) => { const v = e.target.value; onEdit((x) => { const y = x.properties.find((o) => o.id === p.id); if (y) y.options = v; }); }} />
                    ) : null}
                  </div>
                ))}
              </div>
            ) : null}
            {ro ? null : (
              <button type="button" className="btn small mm-add" onClick={() => onEdit((x) => { x.properties.push({ id: uid('p'), name: `property_${x.properties.length + 1}`, type: 'text', description: '', options: '' }); })}>{PLUS}Add property</button>
            )}
          </div>
        </>
      ) : null}
      {hasRelations(provider) ? (
        <div className="mm-sec"><div className="mm-sh">Relations</div>
          <p className="set-help mm-always">{mine.length ? RELATIONS_LINE : NO_RELATIONS_LINE}</p>
          {mine.map((r) => {
            const out = r.from === t.id;
            return <button key={r.id} type="button" className="mm-li" onClick={() => onSel(r.id)}><span className="mm-rn mono">{relText(r.name)}</span><small>{out ? `→ ${typeName(r.to)}` : `← from ${typeName(r.from)}`}</small></button>;
          })}
          {ro ? null : <button type="button" className="btn small mm-add" onClick={onAddRelation}>{PLUS}Add relation</button>}
        </div>
      ) : null}
      {count != null ? (
        <div className="mm-sec mm-recs"><span>{`${plural(count, 'record')} of this type`}</span>{count ? <button type="button" className="link-q inl" onClick={onOpenData}>Open in Data</button> : null}</div>
      ) : null}
      {ro ? null : (
        <div className="mm-sec mm-danger">
          <button type="button" className="btn small danger" onClick={onDelete}>Delete this type</button>
          <p className="set-help">{`Removes ${label || 'it'} from the schema. Records already kept stay as they are.`}</p>
        </div>
      )}
    </div>
  );
}

function RelPanel({ r, ro, types, typeName, nameRef, onEdit, onClose, onDelete }: {
  r: LRel; ro: boolean; types: LType[]; typeName: (id: string) => string; nameRef: (el: HTMLInputElement | null) => void;
  onEdit: (fn: (r: LRel) => void) => void; onClose: () => void; onDelete: () => void;
}) {
  const pick = (k: 'from' | 'to', value: string) => (
    <select className="set-in slim" disabled={ro} aria-label={k === 'from' ? 'From' : 'To'} value={value} onChange={(e) => { const v = e.target.value; onEdit((x) => { x[k] = v; }); }}>
      {types.map((t) => <option key={t.id} value={t.id}>{typeLabel(t.name) || 'Untitled'}</option>)}
    </select>
  );
  return (
    <div>
      <div className="mm-ph">
        <span className="mm-tic mm-tic-r">{ARROW}</span>
        <div className="grow">
          <input ref={nameRef} className="mm-tname mono" aria-label="Relation name" placeholder="RELATION_NAME" disabled={ro} value={r.name}
            onChange={(e) => { const n = relNameOf(e.target.value); onEdit((x) => { x.name = n; }); }}
            onBlur={() => { if (/^_|_$/.test(r.name) || !r.name) onEdit((x) => { x.name = x.name.replace(/^_+|_+$/g, '') || 'RELATES_TO'; }); }} />
          <p className="mm-pd">{`A link from ${typeName(r.from)} to ${typeName(r.to)}.`}</p>
        </div>
        <button type="button" className="icon-btn sm" aria-label="Close" onClick={onClose}>{X}</button>
      </div>
      <p className="mm-note">{RELATIONS_LINE}</p>
      <div className="mm-sec mm-two">
        <label><span className="mm-sh">From</span>{pick('from', r.from)}</label>
        <label><span className="mm-sh">To</span>{pick('to', r.to)}</label>
      </div>
      <div className="mm-sec">
        <div className="mm-sh">What it means</div>
        <textarea className="set-in slim" rows={2} aria-label="What it means" placeholder="Say when this relation applies." disabled={ro} value={r.description} onChange={(e) => { const v = e.target.value; onEdit((x) => { x.description = v; }); }} />
      </div>
      {ro ? null : (
        <div className="mm-sec mm-danger">
          <button type="button" className="btn small danger" onClick={onDelete}>Delete this relation</button>
          <p className="set-help">Links already made stay on their records.</p>
        </div>
      )}
    </div>
  );
}
