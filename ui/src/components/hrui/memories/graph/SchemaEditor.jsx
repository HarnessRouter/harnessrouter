'use client';
// A memory's schema: the graph view's schema pane. The canvas, its toolbar, and the panel that opens when a type or a
// link is clicked are the original's, function by function, with the service's schema underneath. Cosmetic and additive
// edits draw at once and wait for Save; renaming or deleting a property, deleting a type and drawing a link apply at once.
//
// The panel is the same whatever the provider. Where a provider can't take something it still shows all of it, not
// editable: a type's colour where labels have none, what a memory holds where a provider decides for itself. Information
// is never hidden because it can't be edited.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ConfirmSheet } from '../../Sheet';
import { toast } from '../../toast';
import { plural } from '../../setup/settingsModel';
import { guideLine, hasProperties, hasRelations, NO_RELATIONS_LINE, RELATIONS_LINE, relText, schemaGuides, schemaLabels, schemaWord, TYPES_LINE } from '../caps';
import { MM_COLORS, MM_PTYPES, MM_STARTS, propNameOf, schemaProblem, startSchema, typeLabel, typeNameOf, uid } from '../schemaModel';
import { kindInfo } from '../tree';
import { vendorName } from '../vendors';
import CytoscapeCanvas, { colorFor } from './CytoscapeCanvas.jsx';
import { exploreOf, readGraph, GRAPH_LIMIT } from './adapter';
import { I, IconByName, iconUrl, needsCatalog, useIconCatalog } from './graphIcons.jsx';
import { arrive, footprint, initialLayout } from './layout';
import { applyDrafts, cloneSchema, graphOf, heldGraph, newRelation } from './schemaDraft';
import './graph.css';

const SWATCHES = [
  '#42309C', '#8B73FF', '#A78BFA', '#3B82F6', '#0EA5E9', '#14B8A6',
  '#10B981', '#F59E0B', '#EF4444', '#EC4899', '#64748B', '#111827',
];
const COMPACT_PANE_WIDTH = 460;
const typeWord = (t) => (MM_PTYPES.find(([v]) => v === t) || [t, t])[1];

// ── Schema → Cytoscape elements (one node per vertex type, one edge per rule).
// `posDrafts` overlays dragged-but-unsaved positions; `typeDrafts` overlays unsaved color/icon + connection add/remove
// edits so the canvas previews the pending schema change before Save.
export function buildSchemaElements(graph, posDrafts, typeDrafts, captionOf) {
  if (!graph) return [];
  const drafts = typeDrafts || {};
  const elements = [];
  const vts = graph.vertex_types || [];
  vts.forEach((vt, i) => {
    const label = vt.label;
    const d = drafts[`vertex:${label}`] || {};
    const color = d.color || (vt.ui && vt.ui.color) || colorFor(label).ring;
    const iconKey = d.icon != null ? d.icon : (vt.ui && vt.ui.icon);
    const url = iconKey ? iconUrl(iconKey, '#FFFFFF') : null;
    const pos = (posDrafts && posDrafts[label]) || (vt.ui && vt.ui.position) || { x: 120 * i, y: 0 };
    const data = { id: label, kind: 'vertex', caption: captionOf ? captionOf(label, d) : typeLabel(d.name || label), color };
    if (url) data.iconUrl = url;
    elements.push({ data, position: { x: pos.x, y: pos.y }, grabbable: true });
  });
  (graph.edge_types || []).forEach((et) => {
    const label = et.label;
    const d = drafts[`edge:${label}`] || {};
    const color = d.color || (et.ui && et.ui.color) || '#94A3B8';
    const removed = new Set((d.removeConns || []).map((c) => `${c.from_type}->${c.to_type}`));
    const merged = [
      ...(et.connections || []).filter((c) => !removed.has(`${c.from_type}->${c.to_type}`)),
      ...(d.addConns || []),
    ];
    const seen = new Set();
    merged.forEach((c) => {
      if (!c.from_type || !c.to_type) return;
      const key = `${c.from_type}->${c.to_type}`;
      if (seen.has(key)) return; seen.add(key);
      const preview = !(et.connections || []).some((x) => `${x.from_type}->${x.to_type}` === key);
      elements.push({
        data: {
          id: `e-${label}-${c.from_type}-${c.to_type}`,
          kind: 'edge', edgeLabel: label,
          source: c.from_type, target: c.to_type, caption: relText(d.name || label), lineColor: color,
        },
        ...(preview ? { classes: 'preview' } : {}),
      });
    });
  });
  return elements;
}

// ── Schema editing controls ─────────────────────────────────────────────────
function ColorPicker({ value, onPick, disabled }) {
  const lower = (value || '').toLowerCase();
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
      {SWATCHES.map((hex) => (
        <button key={hex} type="button" title={hex} disabled={disabled} aria-label={`Color ${hex}`} aria-pressed={hex.toLowerCase() === lower} onClick={() => onPick(hex)}
          style={{ width: 22, height: 22, borderRadius: 6, padding: 0, cursor: disabled ? 'default' : 'pointer', background: hex,
            border: '2px solid ' + (hex.toLowerCase() === lower ? '#111827' : 'rgba(0,0,0,.12)') }}/>
      ))}
    </div>
  );
}

function IconPicker({ value, onPick, disabled }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const ref = useRef(null);
  const cat = useIconCatalog(open);
  useEffect(() => {
    if (!open) return undefined;
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    const k = (e) => { if (e.key === 'Escape') { e.stopPropagation(); setOpen(false); setQ(''); } };
    document.addEventListener('mousedown', h);
    document.addEventListener('keydown', k);
    return () => { document.removeEventListener('mousedown', h); document.removeEventListener('keydown', k); };
  }, [open]);
  const matches = useMemo(() => (cat ? cat.searchIcons(q, 160) : []), [q, cat]);
  return (
    <div ref={ref} className="icon-combo">
      <button type="button" className="icon-combo-trigger" disabled={disabled} aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <span className="icon-combo-glyph">{value ? <IconByName name={value} size={14}/> : null}</span>
        <span className="icon-combo-name">{value || 'Choose an icon'}</span>
        {disabled ? null : <span className="icon-combo-caret" aria-hidden>{open ? '▴' : '▾'}</span>}
      </button>
      {open && (
        <div className="icon-combo-popover">
          <input className="icon-combo-search" autoFocus placeholder="type to filter…" aria-label="Filter icons" value={q} onChange={(e) => setQ(e.target.value)}/>
          <div className="icon-combo-list">
            {matches.map((n) => (
              <button key={n} type="button" className={'icon-combo-item' + (n === value ? ' active' : '')}
                      onClick={() => { onPick(n); setOpen(false); setQ(''); }}>
                <span className="icon-combo-glyph"><IconByName name={n} size={14}/></span>
                <span className="icon-combo-name">{n}</span>
              </button>
            ))}
            {cat && matches.length === 0 && <div className="icon-combo-empty">no icons match “{q}”</div>}
          </div>
        </div>
      )}
    </div>
  );
}

function SavedPropRow({ p, busy, readOnly, onRename, onDelete, onOptions }) {
  const [name, setName] = useState(p.name);
  useEffect(() => { setName(p.name); }, [p.name]);
  const dirty = name.trim() !== p.name;
  const commit = () => { if (dirty && name.trim()) onRename(p, name.trim()); };
  const revert = () => setName(p.name);
  return (
    <div className="prop-row" style={{ gridTemplateColumns: '1fr 1fr auto', alignItems: 'center', gap: 6 }}>
      <input className="input sm mono" aria-label="Property name" value={name} disabled={busy || readOnly}
             onChange={(e) => setName(propNameOf(e.target.value))}
             onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); commit(); } if (e.key === 'Escape') revert(); }}/>
      <select className="input sm" aria-label="Property type" disabled><option>{typeWord(p.type)}</option></select>
      <span className="dg-prop-actions">
        {readOnly ? null : dirty ? (<>
          <button type="button" className="dg-row-btn confirm" title="Save new name" aria-label="Save new name" disabled={busy} onClick={commit}>
            <IconByName name="Check" size={14}/>
          </button>
          <button type="button" className="dg-row-btn" title="Keep the old name" aria-label="Keep the old name" disabled={busy} onClick={revert}>
            <IconByName name="Undo2" size={14}/>
          </button>
        </>) : (
          onDelete && (
            <button type="button" className="dg-row-btn danger" title="Delete this field" aria-label={`Delete ${p.name}`} disabled={busy}
                    onClick={() => onDelete(p)}>
              <IconByName name="Trash2" size={14}/>
            </button>
          )
        )}
      </span>
      {p.type === 'choice' ? (
        <input className="input sm" style={{ gridColumn: '1 / -1' }} aria-label="Choices" placeholder="Choices, separated by commas" disabled={busy || readOnly} defaultValue={p.options}
               onBlur={(e) => { if (e.target.value !== p.options) onOptions(p, e.target.value); }}/>
      ) : null}
    </div>
  );
}

// Schema type editor. Cosmetic + additive edits accumulate into `draft` (via onDraft), color, icon, description, caption,
// added properties, connection add/remove, with a live canvas preview; the page's global Save/Discard commits or reverts
// the whole draft. Destructive/structural edits (rename or delete a property, delete the type) are IMMEDIATE operations
// passed in as handlers, and each confirms where it destroys anything.
function TypeDetail({
  graph, sel, draft, onDraft, compact, onClose, caps, count, onOpenData, relationsLine,
  rowBusy, onRenameProp, onDeleteProp, onPropOptions, onDeleteType,
  dirty, busy, onSave, onDiscard,
}) {
  const [pendConn, setPendConn] = useState({ from_type: '', to_type: '' });
  const cls = 'dg-detail' + (compact ? ' compact' : '');
  if (!graph || !sel) {
    return (
      <div className={cls}>
        <div className="dg-detail-h"><div style={{ flex: 1 }}>
          <div style={{ fontWeight: 600, fontSize: 13 }}>Nothing selected</div>
          <div className="stat-lbl">click a type in the diagram to edit it</div>
        </div>
        {onClose && <button className="pane-btn dg-detail-close" onClick={onClose} title="Close" aria-label="Close">{I.close}</button>}
        </div>
      </div>
    );
  }
  const isVertex = sel.kind === 'vertex';
  const list = isVertex ? (graph.vertex_types || []) : (graph.edge_types || []);
  const t = list.find((x) => x.label === sel.label);
  if (!t) return null;
  const label = t.label;
  const titleOf = (l) => graph.titles?.[l] || typeLabel(l);
  const shownName = isVertex ? typeLabel(draft?.name ?? label) : (draft?.name ?? label);
  const d = draft || { color: null, icon: null, props: [], addConns: [], removeConns: [] };
  const ring = d.color || (t.ui && t.ui.color) || (isVertex ? colorFor(label).ring : '#94A3B8');
  const iconName = d.icon != null ? d.icon : ((t.ui && t.ui.icon) || '');
  const savedProps = t.properties || [];
  const draftProps = d.props || [];
  const removedSet = new Set((d.removeConns || []).map((c) => `${c.from_type}->${c.to_type}`));
  const savedConns = (t.connections || []).filter((c) => !removedSet.has(`${c.from_type}->${c.to_type}`));
  const draftConns = d.addConns || [];
  const vLabels = (graph.vertex_types || []).map((v) => v.label);
  const description = d.description != null ? d.description : (t.description || '');

  const setColor = (color) => onDraft({ color });
  const setIcon = (icon) => onDraft({ icon });
  const setName = (v) => onDraft((p) => ({ ...p, name: v === label ? null : v }));
  const setDescription = (v) => onDraft((p) => ({ ...p, description: v === (t.description || '') ? null : v }));
  // Properties: "+ Add property" drops an editable blank row straight into the draft (no sub-form / Cancel-Add). Edits
  // update it in place; the global Save/Discard commits or reverts. Blank-name rows are ignored on Save.
  const addDraftProp = () => onDraft((p) => ({ ...p, props: [...(p.props || []), { name: '', type: 'text', options: '' }] }));
  const updateDraftProp = (i, patch) => onDraft((p) => ({ ...p, props: (p.props || []).map((x, idx) => idx === i ? { ...x, ...patch } : x) }));
  const removeDraftProp = (i) => onDraft((p) => ({ ...p, props: (p.props || []).filter((_, idx) => idx !== i) }));
  const addConn = () => {
    if (!pendConn.from_type || !pendConn.to_type) return;
    const key = `${pendConn.from_type}->${pendConn.to_type}`;
    onDraft((p) => {
      // Re-adding a pending-removed connection just cancels the removal.
      if ((p.removeConns || []).some((c) => `${c.from_type}->${c.to_type}` === key)) {
        return { ...p, removeConns: p.removeConns.filter((c) => `${c.from_type}->${c.to_type}` !== key) };
      }
      if ((p.addConns || []).some((c) => `${c.from_type}->${c.to_type}` === key)) return p;
      // Already a saved connection? no-op.
      if ((t.connections || []).some((c) => `${c.from_type}->${c.to_type}` === key)) return p;
      return { ...p, addConns: [...(p.addConns || []), { from_type: pendConn.from_type, to_type: pendConn.to_type }] };
    });
    setPendConn({ from_type: '', to_type: '' });
  };
  const removeSavedConn = (c) => onDraft((p) => ({ ...p, removeConns: [...(p.removeConns || []), { from_type: c.from_type, to_type: c.to_type }] }));
  const removeDraftConn = (c) => onDraft((p) => ({ ...p, addConns: (p.addConns || []).filter((x) => !(x.from_type === c.from_type && x.to_type === c.to_type)) }));

  // Caption: the property whose value labels each record on the explore canvas.
  const savedCaption = (t.ui && t.ui.caption && t.ui.caption !== 'title') ? t.ui.caption : '';
  const captionValue = d.labelProps != null ? (d.labelProps[0] || '') : savedCaption;
  const setCaption = (v) => onDraft((p) => ({ ...p, labelProps: v === savedCaption ? null : (v ? [v] : []) }));

  return (
    <div className={cls} role="region" aria-label={shownName || 'Type'}>
      <div className="dg-detail-h" style={{ alignItems: 'flex-start' }}>
        {isVertex ? (
          <span style={{ width: 32, height: 32, borderRadius: 16, flexShrink: 0, background: ring, display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
            {iconName ? <IconByName name={iconName} size={16} color="#fff"/> : null}
          </span>
        ) : (
          <span style={{ width: 32, height: 32, flexShrink: 0, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', color: ring }}>
            <IconByName name="ArrowRight" size={26} color={ring} strokeWidth={2.25}/>
          </span>
        )}
        <div style={{ flex: 1, minWidth: 0 }}>
          {caps.name ? (
            <input className="dg-inline-input" aria-label="Name" style={{ fontWeight: 600, fontSize: 14 }} value={shownName}
              onChange={(e) => setName(isVertex ? typeNameOf(e.target.value) : normalizeEdgeLabel(e.target.value))}/>
          ) : (
            <div style={{ fontWeight: 600, fontSize: 14, padding: '0 6px' }}>{isVertex ? titleOf(label) : relText(label)}</div>
          )}
          <textarea
            className="dg-inline-input stat-lbl" rows={description.length > 70 ? 3 : 1} aria-label="Description"
            value={description} placeholder={caps.description ? 'Add a description…' : ''} disabled={!caps.description}
            onChange={(e) => setDescription(e.target.value)}
            style={{ lineHeight: 1.5, fontSize: 11 }}
          />
        </div>
        {onClose && <button className="pane-btn dg-detail-close" onClick={onClose} title="Close" aria-label="Close">{I.close}</button>}
      </div>
      <div className="dg-detail-b">
        <div className="dg-field-label">Color</div>
        <ColorPicker value={ring} onPick={setColor} disabled={!caps.color}/>
        {isVertex && (<>
          <div className="dg-field-label" style={{ marginTop: 16 }}>Icon</div>
          <IconPicker value={iconName} onPick={setIcon} disabled={!caps.icon}/>
          {savedProps.length > 0 && (<>
            <div className="dg-field-label" style={{ marginTop: 16 }}>Caption</div>
            <select className="input sm" aria-label="Caption" disabled={!caps.caption} value={captionValue} onChange={(e) => setCaption(e.target.value)} style={{ width: '100%' }}>
              <option value="">Title</option>
              {savedProps.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}
            </select>
            <div className="stat-lbl" style={{ marginTop: 4 }}>Which field labels each {titleOf(label)} on the canvas.</div>
          </>)}
        </>)}

        {!isVertex && (<>
          <hr className="hr"/>
          <div className="dg-field-label">Endpoints</div>
          <div className="endpoint-table">
            <div className="endpoint-head"><span>source</span><span>target</span><span aria-label="remove"/></div>
            {savedConns.map((c) => (
              <div className="endpoint-row" key={`${c.from_type}->${c.to_type}`}>
                <span className="mono">{titleOf(c.from_type)}</span><span className="mono">{titleOf(c.to_type)}</span>
                {caps.conns ? <button type="button" className="dg-conn-x" title="Remove" aria-label="Remove" onClick={() => removeSavedConn(c)}>×</button> : <span/>}
              </div>
            ))}
            {draftConns.map((c) => (
              <div className="endpoint-row" key={`draft-${c.from_type}->${c.to_type}`} style={{ background: 'var(--accent-soft)' }}>
                <span className="mono">{typeLabel(c.from_type)}</span><span className="mono">{typeLabel(c.to_type)}</span>
                <button type="button" className="dg-conn-x" title="Remove pending" aria-label="Remove pending" onClick={() => removeDraftConn(c)}>×</button>
              </div>
            ))}
            {caps.conns ? (
              <div className="endpoint-row endpoint-add">
                <select className="input sm" aria-label="Source" value={pendConn.from_type} onChange={(e) => setPendConn({ ...pendConn, from_type: e.target.value })}>
                  <option value="">source…</option>{vLabels.map((l) => <option key={l} value={l}>{typeLabel(l)}</option>)}
                </select>
                <select className="input sm" aria-label="Target" value={pendConn.to_type} onChange={(e) => setPendConn({ ...pendConn, to_type: e.target.value })}>
                  <option value="">target…</option>{vLabels.map((l) => <option key={l} value={l}>{typeLabel(l)}</option>)}
                </select>
                <button type="button" className="dg-conn-x endpoint-add-btn" title="Add endpoint" aria-label="Add endpoint"
                        disabled={!pendConn.from_type || !pendConn.to_type} onClick={addConn}>+</button>
              </div>
            ) : null}
          </div>
          {relationsLine ? <div className="stat-lbl" style={{ marginTop: 8 }}>{relationsLine}</div> : null}
        </>)}

        <hr className="hr"/>
        <div className="dg-field-label">Properties</div>
        {savedProps.length === 0 && draftProps.length === 0 ? <div className="stat-lbl" style={{ marginBottom: 8 }}>no properties yet</div> : (
          <div className="prop-table">
            <div className="prop-head" style={{ gridTemplateColumns: '1fr 1fr auto' }}><span>name</span><span>type</span><span/></div>
            {savedProps.map((p) => (
              <SavedPropRow key={p.id || p.name} p={p} readOnly={!caps.props}
                busy={!!(rowBusy && rowBusy[p.name])}
                onRename={onRenameProp} onDelete={onDeleteProp} onOptions={onPropOptions}/>
            ))}
            {draftProps.map((p, i) => (
              <div className="prop-row" key={`draft-${i}`} style={{ gridTemplateColumns: '1fr 1fr auto', alignItems: 'center', gap: 6 }}>
                <input className="input sm mono" placeholder="property_name" aria-label="New property name" autoFocus={!p.name} value={p.name}
                       onChange={(e) => updateDraftProp(i, { name: propNameOf(e.target.value) })} style={{ borderColor: 'var(--accent)' }}/>
                <select className="input sm" aria-label="New property type" value={p.type} onChange={(e) => updateDraftProp(i, { type: e.target.value })}>
                  {MM_PTYPES.map(([v, w]) => <option key={v} value={v}>{w}</option>)}
                </select>
                <span className="dg-prop-actions">
                  <button type="button" className="dg-row-btn danger" title="Remove pending" aria-label="Remove pending" onClick={() => removeDraftProp(i)}>
                    <IconByName name="Trash2" size={14}/>
                  </button>
                </span>
                {p.type === 'choice' ? (
                  <input className="input sm" style={{ gridColumn: '1 / -1' }} aria-label="Choices" placeholder="Choices, separated by commas" value={p.options || ''}
                         onChange={(e) => updateDraftProp(i, { options: e.target.value })}/>
                ) : null}
              </div>
            ))}
          </div>
        )}
        {isVertex && caps.props ? (
          <div style={{ marginTop: 8 }}>
            <button type="button" className="btn sm" onClick={addDraftProp}>+ Add property</button>
          </div>
        ) : null}
        {isVertex && caps.typesLine ? <div className="stat-lbl" style={{ marginTop: 8 }}>{TYPES_LINE}</div> : null}

        {count != null ? (<>
          <hr className="hr"/>
          <div className="stat-lbl" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
            <span>{isVertex ? `${plural(count, 'record')} of this type` : plural(count, 'link')}</span>
            {count && isVertex && onOpenData ? <button type="button" className="link-q inl" onClick={onOpenData}>Open in Data</button> : null}
          </div>
        </>) : null}

        {onDeleteType && caps.del && (<>
          <hr className="hr"/>
          <button type="button" className="btn sm dg-danger-btn" onClick={() => onDeleteType(sel.kind, label)}>
            Delete this type
          </button>
          <div className="stat-lbl" style={{ marginTop: 6 }}>
            {isVertex
              ? `Removes ${typeLabel(label)} from the schema, and every link that uses it. Records already kept stay as they are.`
              : `Removes ${relText(label)} from the schema. Links already made stay on their records.`}
          </div>
        </>)}
      </div>
      {/* Pending-edit footer. The toolbar also offers Save/Discard, but a compact (full-pane floating) editor covers
          it: the footer keeps committing reachable everywhere. */}
      {dirty && (
        <div className="dg-detail-f">
          <span className="stat-lbl">Unsaved changes</span>
          <span style={{ flex: 1 }}/>
          <button type="button" className="btn sm" disabled={busy} onClick={onDiscard}>Discard</button>
          <button type="button" className="btn sm primary" disabled={busy} onClick={onSave}>{busy ? 'Saving…' : 'Save'}</button>
        </div>
      )}
    </div>
  );
}

// Edge labels read as UPPER_SNAKE_CASE link names (WORKS_AT). Normalize as the user types: uppercase, spaces to
// underscores, strip everything else, and never start with a digit.
function normalizeEdgeLabel(v) {
  return String(v || '')
    .toUpperCase()
    .replace(/\s+/g, '_')
    .replace(/[^A-Z0-9_]/g, '')
    .replace(/^[0-9]+/, '')
    .slice(0, 64);
}

function AddTypeForm({ onCreate, busy, onClose, vertexLabels = [], edges = true, word = 'type' }) {
  const [d, setD] = useState({ label: '', kind: 'vertex', color: SWATCHES[0], from_type: '', to_type: '' });
  const isEdge = d.kind === 'edge';
  // An edge type needs its two endpoints up front: without them it renders nowhere on the canvas, which is how
  // "created but invisible" bugs felt.
  const canCreate = !!d.label.trim() && (!isEdge || (d.from_type && d.to_type));
  function commit() {
    if (!canCreate) return;
    onCreate({
      label: d.label.trim(), kind: d.kind, color: d.color,
      connections: isEdge ? [{ from_type: d.from_type, to_type: d.to_type }] : undefined,
    });
    onClose();
  }
  return (
    // Escape closes the popover from anywhere inside it.
    <div className="sp-graph-addtype card"
         onKeyDown={(e) => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); onClose(); } }}>
      <div className="dg-field-label">New {word}</div>
      <input className="input sm mono" autoFocus aria-label="Label"
             placeholder={isEdge ? 'Label (e.g. WORKS_AT)' : 'Label (e.g. Project)'}
             value={d.label}
             onChange={(e) => setD({ ...d, label: isEdge ? normalizeEdgeLabel(e.target.value) : e.target.value })}
             onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); commit(); } }}
             style={{ marginBottom: 8 }}/>
      {edges ? (
        <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
          <button type="button" className={'btn sm' + (!isEdge ? ' primary' : '')} onClick={() => setD({ ...d, kind: 'vertex' })}>Vertex</button>
          <button type="button" className={'btn sm' + (isEdge ? ' primary' : '')} onClick={() => setD({ ...d, kind: 'edge', label: normalizeEdgeLabel(d.label) })}>Edge</button>
        </div>
      ) : null}
      {isEdge && (vertexLabels.length ? (
        <>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 6 }}>
            <select className="input sm" aria-label="Source" value={d.from_type} style={{ flex: 1, minWidth: 0 }}
                    onChange={(e) => setD({ ...d, from_type: e.target.value })}>
              <option value="">Source…</option>
              {vertexLabels.map((l) => <option key={l} value={l}>{typeLabel(l)}</option>)}
            </select>
            <span className="dg-eh-pop-arrow" aria-hidden><IconByName name="ArrowRight" size={14}/></span>
            <select className="input sm" aria-label="Target" value={d.to_type} style={{ flex: 1, minWidth: 0 }}
                    onChange={(e) => setD({ ...d, to_type: e.target.value })}>
              <option value="">Target…</option>
              {vertexLabels.map((l) => <option key={l} value={l}>{typeLabel(l)}</option>)}
            </select>
          </div>
          <div className="stat-lbl" style={{ marginBottom: 8 }}>
            Links point from the source type to the target type. Both can be the same type.
          </div>
        </>
      ) : (
        <div className="stat-lbl" style={{ marginBottom: 8 }}>
          Add a vertex type first. An edge links two vertex types.
        </div>
      ))}
      <ColorPicker value={d.color} onPick={(color) => setD({ ...d, color })}/>
      <div style={{ display: 'flex', gap: 6, marginTop: 12, justifyContent: 'flex-end' }}>
        <button type="button" className="btn sm" disabled={busy} onClick={onClose}>Cancel</button>
        <button type="button" className="btn sm primary" disabled={busy || !canCreate} onClick={commit}>Create</button>
      </div>
    </div>
  );
}

// Inline popover after a drag-to-connect drop: the two endpoints are already chosen by the gesture, so ask only for the
// link's name (and a color when it is a brand-new link type). Enter creates, Escape cancels.
function LinkDrawPopover({ pend, edgeTypes, colorByLabel, busy, onCreate, onCancel }) {
  const [label, setLabel] = useState('');
  const [color, setColor] = useState('#94A3B8');
  const existing = label && (edgeTypes || []).find((e) => e.label === label);
  const canCreate = !!label && !busy;
  return (
    <div className="dg-eh-pop" style={{ left: pend.x, top: pend.y }}>
      <div className="dg-eh-pop-ends">
        <span className="dg-eh-pop-end" style={{ background: colorByLabel[pend.from] || 'var(--accent)' }}>{typeLabel(pend.from)}</span>
        <span className="dg-eh-pop-arrow" aria-hidden><IconByName name="ArrowRight" size={14}/></span>
        <span className="dg-eh-pop-end" style={{ background: colorByLabel[pend.to] || 'var(--accent)' }}>{typeLabel(pend.to)}</span>
      </div>
      <input className="input sm mono" autoFocus placeholder="LINK_NAME (e.g. WORKS_AT)" aria-label="Link name"
             value={label} style={{ width: '100%' }}
             onChange={(e) => setLabel(normalizeEdgeLabel(e.target.value))}
             onKeyDown={(e) => {
               if (e.key === 'Enter' && canCreate) { e.preventDefault(); onCreate({ label, color }); }
               if (e.key === 'Escape') { e.preventDefault(); onCancel(); }
             }}/>
      {existing ? (
        <div className="stat-lbl" style={{ marginTop: 8 }}>Adds this pair to the existing {label} links.</div>
      ) : (
        <div style={{ marginTop: 8 }}><ColorPicker value={color} onPick={setColor}/></div>
      )}
      <div style={{ display: 'flex', gap: 6, marginTop: 12, justifyContent: 'flex-end' }}>
        <button type="button" className="btn sm" disabled={busy} onClick={onCancel}>Cancel</button>
        <button type="button" className="btn sm primary" disabled={!canCreate} onClick={() => onCreate({ label, color })}>
          Create
        </button>
      </div>
    </div>
  );
}

// Decorative ghost schema, used by the quiet empty state.
function GhostSchemaGlyph() {
  return (
    <svg className="dg-blank-quiet-glyph" width="120" height="60" viewBox="0 0 120 60" aria-hidden="true">
      <g fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M25.2 39.7 L52.8 19.3" strokeDasharray="3 4"/>
        <path d="M67.2 19.3 L94.8 39.7" strokeDasharray="3 4"/>
        <circle cx="18" cy="45" r="9"/>
        <circle cx="60" cy="14" r="9"/>
        <circle cx="102" cy="45" r="9"/>
      </g>
    </svg>
  );
}

/** Saving, saved or why not, in the words a person needs. */
function SaveLine({ doc }) {
  if (!doc) return null;
  if (doc.state === 'error') {
    return <p className="mm-sstat bad" role="alert">{doc.error} <button type="button" className="link-q inl" onClick={doc.saveNow}>Try again</button></p>;
  }
  if (doc.state === 'saving') return <p className="mm-sstat" role="status">Saving…</p>;
  if (doc.state === 'saved') return <p className="mm-sstat" role="status">Saved</p>;
  return null;
}

// One deferred fit: frame everything once the pane has its final size, with a zoom cap so a tiny schema doesn't blow up.
function fitCanvas(ref) {
  const cy = ref.current?.getCy?.();
  if (!cy || cy.nodes().length === 0) return;
  try {
    cy.resize();
    if (cy.width() < 2 || cy.height() < 2) return;
    cy.fit(undefined, 40);
    if (cy.zoom() > 1.3) { cy.zoom(1.3); cy.center(); }
    // however narrow the pane, a type stays big enough to read and to press: the drawing scales with the pane, and each
    // node is drawn larger by as much as the scale took away
    const k = Math.max(1, Math.min(2.4, 0.8 / cy.zoom()));
    cy.batch(() => {
      cy.nodes().style({ width: 38 * k, height: 38 * k, 'font-size': 10 * k, 'background-width': 18 * k, 'background-height': 18 * k, 'text-max-width': 140 * k });
      cy.edges().style({ width: 1.4 * k, 'font-size': 10 * k });
    });
  } catch { /* gone */ }
}
const fitSoon = (ref) => requestAnimationFrame(() => requestAnimationFrame(() => { fitCanvas(ref); setTimeout(() => fitCanvas(ref), 60); }));

/** The pane. `graph` is what it draws, `caps` what may change, and `doc` where a change goes (none for what a provider holds on its own). */
function SchemaPane({ memory, provider, graph, saved, doc, caps, loading, failed, retry, countOf, onOpenData, placeholder, footLine }) {
  const [schemaSel, setSchemaSel] = useState(null);   // { kind, label }
  const [edit, setEdit] = useState(false);
  const [addType, setAddType] = useState(false);
  const [positionDrafts, setPositionDrafts] = useState({});
  const [typeDrafts, setTypeDrafts] = useState({});
  const [linkDraw, setLinkDraw] = useState(null);
  const [confirm, setConfirm] = useState(null);
  const [problem, setProblem] = useState('');
  const [expanded, setExpanded] = useState(false);
  const [compact, setCompact] = useState(false);
  const [rowBusy] = useState({});
  const schemaRef = useRef(null);
  const bodyRef = useRef(null);
  const word = schemaWord(provider);

  const draftHasContent = (d) => !!d && (d.name != null || d.color != null || d.icon != null || d.description != null || d.labelProps != null || (d.props && d.props.length) || (d.addConns && d.addConns.length) || (d.removeConns && d.removeConns.length));
  const typeDirty = Object.values(typeDrafts).some(draftHasContent);
  const positionsDirty = Object.keys(positionDrafts).length > 0;
  const refused = doc?.state === 'error';
  const schemaDirty = positionsDirty || typeDirty || refused;
  const busy = doc?.state === 'saving';

  // Auto-select the first vertex type once, so the pencil has something to open.
  const autoSel = useRef(false);
  useEffect(() => {
    if (autoSel.current) return;
    const vts = graph && graph.vertex_types;
    if (vts && vts.length) { setSchemaSel({ kind: 'vertex', label: vts[0].label }); autoSel.current = true; }
  }, [graph]);

  const selKey = schemaSel ? `${schemaSel.kind}:${schemaSel.label}` : null;
  const selDraft = (selKey && typeDrafts[selKey]) || null;
  const updateSelDraft = useCallback((patch) => {
    if (!selKey) return;
    setProblem('');
    setTypeDrafts((m) => {
      const cur = m[selKey] || { color: null, icon: null, props: [], addConns: [], removeConns: [] };
      const next = typeof patch === 'function' ? patch(cur) : { ...cur, ...patch };
      return { ...m, [selKey]: next };
    });
  }, [selKey]);

  // The immediate operations: they go to the schema document, and on to the service, at once.
  const apply = useCallback((fn) => { if (!doc) return; doc.update(fn, false); doc.saveNow(); }, [doc]);

  const createType = useCallback(({ label, kind, color, connections }) => {
    if (kind === 'vertex') {
      const name = typeNameOf(label);
      if (saved?.types.some((t) => t.name === name)) { toast(`A ${word} called ${typeLabel(name)} is already here.`); return; }
      const nodes = [...(saved?.types || []).map((t) => ({ id: t.id, ...footprint(typeLabel(t.name), 38) })), { id: 'new', ...footprint(typeLabel(name), 38) }];
      const known = new Map((saved?.types || []).map((t) => [t.id, { x: t.x, y: t.y }]));
      const at = known.size ? arrive(nodes, [], known).get('new') : { x: 470, y: 320 };
      const id = uid('t');
      apply((d) => {
        d.types.push({ id, name, description: '', properties: [], color: color || MM_COLORS[0], icon: 'box', x: Math.round(at.x), y: Math.round(at.y), caption: 'title' });
      });
      setSchemaSel({ kind: 'vertex', label: name });
      setEdit(true);
      return;
    }
    apply((d) => {
      for (const c of connections || []) {
        const a = d.types.find((t) => t.name === c.from_type), b = d.types.find((t) => t.name === c.to_type);
        if (a && b) d.relations.push(newRelation(label, a.id, b.id, color));
      }
    });
    setSchemaSel({ kind: 'edge', label });
    setEdit(true);
  }, [apply, saved, word]);

  // ── Drag-to-connect (schema canvas): the gesture ends on a target node, and the popover asks for the link's name.
  const onSchemaEdgeDraw = useCallback((sourceId, targetId, pos) => {
    if (!caps.conns) return;
    const cy = schemaRef.current && schemaRef.current.getCy && schemaRef.current.getCy();
    const W = cy ? cy.width() : 600, H = cy ? cy.height() : 400;
    setLinkDraw({
      from: sourceId, to: targetId,
      x: Math.max(10, Math.min(pos.x - 126, W - 262)),
      y: Math.max(10, Math.min(pos.y + 16, H - 210)),
    });
  }, [caps.conns]);
  const createDrawnLink = useCallback(({ label, color }) => {
    const pend = linkDraw;
    if (!pend || !label) return;
    const et = (graph?.edge_types || []).find((e) => e.label === label);
    if (et && (et.connections || []).some((c) => c.from_type === pend.from && c.to_type === pend.to)) {
      setLinkDraw(null);
      toast(`${typeLabel(pend.from)} and ${typeLabel(pend.to)} are already linked with ${label}.`);
      return;
    }
    apply((d) => {
      const a = d.types.find((t) => t.name === pend.from), b = d.types.find((t) => t.name === pend.to);
      if (a && b) d.relations.push(newRelation(label, a.id, b.id, et?.ui?.color || color));
    });
    setLinkDraw(null);
    setSchemaSel({ kind: 'edge', label });
    setEdit(true);
  }, [linkDraw, graph, apply]);

  const IDENT = /^[\p{L}_][\p{L}\p{N}_]*$/u;
  const renameProperty = useCallback((label, prop, newName) => {
    if (!IDENT.test(newName)) { toast('Field names start with a letter or underscore and use only letters, numbers, and underscores.'); return; }
    apply((d) => {
      const t = d.types.find((x) => x.name === label);
      const p = t?.properties.find((x) => x.name === prop.name);
      if (p) p.name = newName;
      if (t && t.caption === prop.name) t.caption = newName;
    });
  }, [apply]);  // eslint-disable-line react-hooks/exhaustive-deps
  const setPropertyOptions = useCallback((label, prop, options) => {
    apply((d) => { const p = d.types.find((x) => x.name === label)?.properties.find((x) => x.name === prop.name); if (p) p.options = options; });
  }, [apply]);

  const saveChanges = useCallback(() => {
    if (!doc || !doc.schema) return;
    if (!positionsDirty && !typeDirty) { doc.saveNow(); return; }
    const next = applyDrafts(doc.schema, positionDrafts, typeDrafts);
    const p = schemaProblem(next, word);
    if (p) { setProblem(p); return; }
    doc.update((d) => { d.types = next.types; d.relations = next.relations; }, false);
    doc.saveNow();
    const renamed = selKey && typeDrafts[selKey]?.name;
    if (renamed) setSchemaSel((s) => (s ? { ...s, label: renamed } : s));
    setPositionDrafts({}); setTypeDrafts({}); setProblem('');
  }, [doc, positionDrafts, typeDrafts, positionsDirty, typeDirty, word, selKey]);
  const discardChanges = useCallback(() => {
    setPositionDrafts({}); setTypeDrafts({}); setProblem(''); setLinkDraw(null);
    // a write the service refused left the document ahead of what it holds
    if (refused) doc.retry();
  }, [refused, doc]);

  // Vertex-type position drags go to drafts, and Save persists them.
  const onSchemaNodeDragEnd = useCallback((cyNodeId, pos) => {
    if (!caps.position || !cyNodeId || !pos) return;
    setPositionDrafts((p) => ({ ...p, [cyNodeId]: { x: Math.round(pos.x), y: Math.round(pos.y) } }));
  }, [caps.position]);

  // RULE: any panel appearing/disappearing changes the canvas's available size, so it must recalculate and re-center.
  useEffect(() => { fitSoon(schemaRef); }, [edit, compact, expanded, !!graph]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const cy = schemaRef.current?.getCy?.();
    if (cy) cy.autoungrabify(!caps.position);
  }, [caps.position, !!graph]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const el = bodyRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return undefined;
    let t = null, last = 0;
    const ro = new ResizeObserver((es) => {
      const w = es[es.length - 1].contentRect.width;
      setCompact(w > 0 && w < COMPACT_PANE_WIDTH);
      if (Math.abs(w - last) < 2) return;
      last = w;
      clearTimeout(t);
      t = setTimeout(() => fitCanvas(schemaRef), 160);
    });
    ro.observe(el);
    return () => { clearTimeout(t); ro.disconnect(); };
  }, []);

  const icons = useMemo(() => (graph?.vertex_types || []).map((v) => v.ui?.icon).concat(Object.values(typeDrafts).map((d) => d.icon)), [graph, typeDrafts]);
  const catalog = useIconCatalog(needsCatalog(icons));
  const captionOf = useCallback((label, d) => {
    const n = countOf(`vertex:${label}`, label);
    return `${graph?.titles?.[label] || typeLabel(d?.name || label)}${n != null ? `\n${plural(n, 'record')}` : ''}`;
  }, [countOf, graph]);
  const schemaElements = useMemo(() => buildSchemaElements(graph, positionDrafts, typeDrafts, captionOf), [graph, positionDrafts, typeDrafts, captionOf, catalog]); // eslint-disable-line react-hooks/exhaustive-deps
  const vertexColorByLabel = useMemo(() => {
    const m = {};
    for (const v of ((graph && graph.vertex_types) || [])) m[v.label] = (v.ui && v.ui.color) || colorFor(v.label).ring;
    return m;
  }, [graph]);
  const schemaAriaLabel = useMemo(() => {
    const nv = ((graph && graph.vertex_types) || []).length, ne = ((graph && graph.edge_types) || []).length;
    return `Schema: ${nv} node type${nv === 1 ? '' : 's'}, ${ne} relationship type${ne === 1 ? '' : 's'}`;
  }, [graph]);
  // With the canvas focused, Left/Right cycle the selection, Enter opens the panel, Escape closes it.
  const onSchemaCanvasKeyDown = useCallback((e) => {
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      const labels = ((graph && graph.vertex_types) || []).map((v) => v.label);
      if (!labels.length) return;
      e.preventDefault();
      setSchemaSel((sel) => {
        const cur = sel && sel.kind === 'vertex' ? labels.indexOf(sel.label) : -1;
        const next = e.key === 'ArrowRight' ? (cur + 1) % labels.length : (cur <= 0 ? labels.length - 1 : cur - 1);
        return { kind: 'vertex', label: labels[next] };
      });
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (schemaSel) setEdit(true);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      if (edit) setEdit(false); else setSchemaSel(null);
    }
  }, [graph, schemaSel, edit]);

  const openSel = (sel) => { setSchemaSel(sel); setEdit(true); };
  const selCount = schemaSel ? countOf(`${schemaSel.kind}:${schemaSel.label}`, schemaSel.label) : null;
  const empty = !loading && !failed && graph && !schemaElements.length;

  return (
    <>
      <div className={`mgv${expanded ? ' is-max' : ''}`}>
        <div className="dg-body" ref={bodyRef}>
          <div className="dg-canvas">
            <div className="dg-canvas-tools" style={{ zIndex: edit ? 4 : undefined }}>
              <button className={'pane-btn' + (edit ? ' active' : '')} onClick={() => setEdit(!edit)} title={caps.any ? 'Inspect / edit selected type' : 'Inspect selected type'} aria-label="Inspect selected type" aria-pressed={edit}>{(caps.any ? I.pencil : I.info)}</button>
              {caps.any ? null : <span className="pill neutral" title="This can be read here, not changed">Read only</span>}
              {caps.add ? <button type="button" className="btn sm" onClick={() => setAddType((v) => !v)} title={`Add a ${word}`}>+ {word === 'label' ? 'Label' : 'Type'}</button> : null}
              <button className={'pane-btn' + (expanded ? ' active' : '')} onClick={() => setExpanded((v) => !v)} title={expanded ? 'restore' : 'expand'} aria-label={expanded ? 'restore' : 'expand'} aria-pressed={expanded}>{expanded ? I.cornersIn : I.cornersOut}</button>
              {caps.any && schemaDirty && (
                <>
                  <button type="button" className="btn sm" disabled={busy} onClick={discardChanges}>Discard</button>
                  <button type="button" className="btn sm primary" disabled={busy} onClick={saveChanges}>{busy ? 'Saving…' : 'Save'}</button>
                </>
              )}
            </div>
            <CytoscapeCanvas
              ref={schemaRef}
              elements={schemaElements}
              layout="preset"
              selectedId={schemaSel && schemaSel.kind === 'vertex' ? schemaSel.label : null}
              onTapNode={(id) => openSel({ kind: 'vertex', label: id })}
              onDblTapNode={(id) => openSel({ kind: 'vertex', label: id })}
              onTapEdge={(_id, data) => { if (data && data.edgeLabel) openSel({ kind: 'edge', label: data.edgeLabel }); }}
              onDblTapEdge={(_id, data) => { if (data && data.edgeLabel) openSel({ kind: 'edge', label: data.edgeLabel }); }}
              onNodeDragEnd={onSchemaNodeDragEnd}
              edgeDrawEnabled={!!caps.conns}
              onEdgeDraw={onSchemaEdgeDraw}
              background="var(--surface)"
              ariaLabel={schemaAriaLabel}
              onCanvasKeyDown={onSchemaCanvasKeyDown}
            />
            {linkDraw && (
              <LinkDrawPopover pend={linkDraw} edgeTypes={(graph && graph.edge_types) || []} colorByLabel={vertexColorByLabel} busy={busy}
                onCreate={createDrawnLink} onCancel={() => setLinkDraw(null)}/>
            )}
            {loading ? <div className="dg-canvas-blank"><div className="dg-blank-quiet"><div className="dg-blank-quiet-line" role="status">Reading the schema</div></div></div> : null}
            {failed ? (
              <div className="dg-canvas-blank"><div className="dg-blank-quiet"><div className="dg-blank-quiet-line" role="alert">{failed} <button type="button" className="link-q inl" onClick={retry}>Try again</button></div></div></div>
            ) : null}
            {empty ? (
              caps.add ? (
                <div className="mm-sch-empty mgv-live">
                  <h2>{memory?.records?.count ? 'No types yet' : 'Design what this memory keeps'}</h2>
                  <p>{`${memory?.records?.count ? `It already holds ${plural(memory.records.count, 'record')}. Types shape what is kept from here on. ` : ''}A type is a kind of thing, like a person, a company or a product. ${hasProperties(provider) ? 'Give it properties.' : 'Give it a name and say what it is.'}${hasRelations(provider) ? ' Relating types is optional.' : ''}`}</p>
                  {schemaGuides(provider) ? (
                    <div className="mm-starts">
                      {MM_STARTS.map(([n, sub], i) => (
                        <button key={n} type="button" className="mm-start" onClick={() => {
                          const fresh = startSchema(i, provider);
                          apply((d) => { d.types = fresh.types; d.relations = fresh.relations; });
                          toast(`Started from ${n}. Rename or remove anything.`);
                        }}><b>{n}</b><small>{sub}</small></button>
                      ))}
                      <button type="button" className="mm-start" onClick={() => setAddType(true)}><b>Blank</b><small>Start with one type</small></button>
                    </div>
                  ) : null}
                </div>
              ) : (
                <div className="dg-canvas-blank">
                  <div className="dg-blank-quiet">
                    <GhostSchemaGlyph/>
                    <div className="dg-blank-quiet-line">{placeholder || 'Nothing is kept here yet.'}</div>
                  </div>
                </div>
              )
            ) : null}
            {addType && (
              <div className="sp-graph-addtype-wrap">
                <AddTypeForm onCreate={createType} busy={busy} onClose={() => setAddType(false)} vertexLabels={((graph && graph.vertex_types) || []).map((v) => v.label)} edges={!!caps.conns} word={word}/>
              </div>
            )}
            <div className="mm-foot">
              {problem ? <p className="mm-sstat bad" role="alert">{problem}</p> : <SaveLine doc={doc}/>}
              {footLine ? <p className="mm-guide">{footLine}</p> : null}
            </div>
          </div>
          {edit && (
            <TypeDetail
              graph={graph} sel={schemaSel} draft={selDraft} onDraft={updateSelDraft}
              compact={compact} onClose={() => setEdit(false)}
              caps={caps} count={selCount}
              onOpenData={schemaSel && schemaSel.kind === 'vertex' ? () => onOpenData(schemaSel.label) : null}
              relationsLine={caps.conns ? ((graph?.edge_types || []).length ? RELATIONS_LINE : NO_RELATIONS_LINE) : ''}
              rowBusy={rowBusy}
              onRenameProp={(p, newName) => renameProperty(schemaSel.label, p, newName)}
              onDeleteProp={(p) => setConfirm({ kind: 'prop', label: schemaSel.label, p })}
              onPropOptions={(p, v) => setPropertyOptions(schemaSel.label, p, v)}
              onDeleteType={(kind, label) => setConfirm({ kind, label })}
              dirty={caps.any && schemaDirty} busy={busy} onSave={saveChanges} onDiscard={discardChanges}
            />
          )}
        </div>
      </div>
      {confirm?.kind === 'prop' ? (
        <ConfirmSheet id="mmDp" title={`Delete field "${confirm.p.name}"`} confirmLabel="Delete"
          body={`This removes "${confirm.p.name}" from the ${typeLabel(confirm.label)} type. Values already kept on records stay on them.`}
          onClose={() => setConfirm(null)}
          onConfirm={() => {
            const { label, p } = confirm;
            apply((d) => { const t = d.types.find((x) => x.name === label); if (t) { t.properties = t.properties.filter((o) => o.name !== p.name); if (t.caption === p.name) t.caption = 'title'; } });
            setConfirm(null);
          }} />
      ) : null}
      {confirm?.kind === 'vertex' ? (
        <ConfirmSheet id="mmDt" title={`Delete ${typeLabel(confirm.label)}?`} confirmLabel={`Delete ${typeLabel(confirm.label)}`}
          body={`Removes ${typeLabel(confirm.label)} from the schema of ${memory.name}, and every relation that uses it. Records already kept stay as they are.`}
          onClose={() => setConfirm(null)}
          onConfirm={() => {
            const label = confirm.label;
            apply((d) => {
              const t = d.types.find((x) => x.name === label);
              d.types = d.types.filter((x) => x.name !== label);
              if (t) d.relations = d.relations.filter((r) => r.from !== t.id && r.to !== t.id);
            });
            setTypeDrafts((m) => { const { [`vertex:${label}`]: _, ...rest } = m; return rest; });
            setPositionDrafts((p) => { const { [label]: _, ...rest } = p; return rest; });
            setSchemaSel(null); setEdit(false); setConfirm(null);
          }} />
      ) : null}
      {confirm?.kind === 'edge' ? (
        <ConfirmSheet id="mmDr" title={`Delete ${relText(confirm.label)}?`} confirmLabel="Delete relation"
          body="Removes the relation from the schema. Links already made stay on their records."
          onClose={() => setConfirm(null)}
          onConfirm={() => {
            const label = confirm.label;
            apply((d) => { d.relations = d.relations.filter((r) => r.name !== label); });
            setTypeDrafts((m) => { const { [`edge:${label}`]: _, ...rest } = m; return rest; });
            setSchemaSel(null); setEdit(false); setConfirm(null);
          }} />
      ) : null}
    </>
  );
}

const NOTHING = { any: false, name: false, description: false, color: false, icon: false, caption: false, props: false, conns: false, del: false, add: false, position: false, typesLine: false };

function WrittenSchema({ memory, provider, doc, ro, countOf, onOpenData }) {
  const guides = schemaGuides(provider);
  const caps = useMemo(() => {
    if (ro) return { ...NOTHING, typesLine: guides };
    if (guides) {
      return { any: true, name: true, description: true, color: true, icon: true, caption: hasProperties(provider), props: hasProperties(provider), conns: hasRelations(provider), del: true, add: true, position: true, typesLine: true };
    }
    // a label has a name and what it means, and the provider reads nothing more
    return { ...NOTHING, any: true, name: true, description: true, del: true, add: true };
  }, [ro, guides, provider]);
  const graph = useMemo(() => (doc.schema ? graphOf(doc.schema) : null), [doc.schema]);
  const count = useCallback((key, label) => (key.startsWith('vertex:') ? countOf(label) : null), [countOf]);
  return (
    <SchemaPane memory={memory} provider={provider} graph={graph} saved={doc.schema} doc={doc} caps={caps}
      loading={!doc.schema && !doc.failed} failed={!doc.schema && doc.failed ? (schemaLabels(provider) ? 'The labels could not be read just now.' : 'The schema could not be read just now.') : ''}
      retry={doc.retry} countOf={count} onOpenData={onOpenData} footLine={guideLine(provider)} />
  );
}

/** A provider that decides for itself: what this memory holds, read from its records, in the same panel, not editable. */
function HeldSchema({ memory, provider, onOpenData }) {
  const [state, setState] = useState({ loading: true, failed: false, held: null, truncated: false });
  const read = useCallback(() => {
    setState((x) => ({ ...x, loading: true, failed: false }));
    readGraph(memory.id).then((g) => {
      const ex = exploreOf(g);
      const held = heldGraph(ex, (k) => kindInfo(k, null));
      const nodes = held.graph.vertex_types.map((v) => ({ id: v.label, ...footprint(`${typeLabel(v.label)}\n00 records`, 38) }));
      const edges = held.graph.edge_types.flatMap((e) => e.connections.map((c) => ({ source: c.from_type, target: c.to_type })));
      const { pos } = initialLayout(nodes, edges, { spread: 1.7 });
      held.graph.vertex_types.forEach((v) => { const p = pos.get(v.label); v.ui.position = { x: Math.round(p.x), y: Math.round(p.y) }; });
      setState({ loading: false, failed: false, held, truncated: !!g.truncated });
    }).catch(() => setState({ loading: false, failed: true, held: null, truncated: false }));
  }, [memory.id]);
  useEffect(() => { read(); }, [read]);
  const held = state.held;
  const count = useCallback((key) => (held && held.count[key] != null ? held.count[key] : null), [held]);
  const vendor = vendorName(provider.id);
  const line = `${vendor} decides for itself what to keep, and takes no schema, so there is nothing to set here. This is what it holds now.${state.truncated ? ` Counted from the first ${GRAPH_LIMIT} records.` : ''}`;
  return (
    <SchemaPane memory={memory} provider={provider} graph={held ? held.graph : (state.loading ? null : { vertex_types: [], edge_types: [] })} caps={NOTHING}
      loading={state.loading} failed={state.failed ? 'What this memory holds could not be read just now.' : ''} retry={read}
      countOf={count} onOpenData={onOpenData} footLine={line} />
  );
}

/**
 * @param {{ memory: import('@/lib/memories').Memory, provider: import('@/lib/memories').Provider, doc: import('../useSchemaDoc').SchemaDoc, ro: boolean,
 *   countOf: (type: string) => number | null, onOpenData: (type: string) => void }} props
 */
export function SchemaEditor({ memory, provider, doc, ro, countOf, onOpenData }) {
  if (schemaGuides(provider) || schemaLabels(provider)) {
    return <WrittenSchema memory={memory} provider={provider} doc={doc} ro={ro} countOf={countOf} onOpenData={onOpenData} />;
  }
  return <HeldSchema memory={memory} provider={provider} onOpenData={onOpenData} />;
}
