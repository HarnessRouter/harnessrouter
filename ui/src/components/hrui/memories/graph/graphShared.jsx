'use client';
// The explore pane's pieces, from the original graph view: the truncation of a canvas label, the node's right-click
// menu, and the detail panels. What is new in the panels is that a record is a thing with links, so each link and each
// end of a line is a button that goes there.
import { useEffect, useMemo, useRef, useState } from 'react';
import { bodyOf, labelOf } from '@/lib/memories';
import { kindOf, relText } from '../caps';
import { kindInfo } from '../tree';
import { colorFor } from './CytoscapeCanvas.jsx';
import { I, IconByName } from './graphIcons.jsx';
import { lineCaption } from './adapter';

// Canvas labels must END WITH AN ELLIPSIS when they overflow, never hard-cut mid-word.
export function truncateLabel(s, max = 40) {
  const str = String(s == null ? '' : s);
  if (str.length <= max) return str;
  return str.slice(0, Math.max(1, max - 1)).trimEnd() + '…';
}


export function NodeContextMenu({
  x, y, edgeOptions, collapsed,
  edgeColorByLabel, vertexColorByLabel, vertexIconByLabel,
  onExpandAll, onExpandFiltered, onCollapse, onReExpand, onClose,
}) {
  const rootRef = useRef(null);
  const [hoverEdge, setHoverEdge] = useState(false);

  useEffect(() => {
    function onDoc(ev) {
      if (rootRef.current && !rootRef.current.contains(ev.target)) onClose();
    }
    function onKey(ev) { if (ev.key === 'Escape') onClose(); }
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [onClose]);

  const sortedOpts = useMemo(
    () => [...(edgeOptions || [])].sort(
      (a, b) => a.edge.localeCompare(b.edge) || a.target.localeCompare(b.target),
    ),
    [edgeOptions],
  );

  return (
    <div
      ref={rootRef}
      className="cy-ctx-menu"
      style={{ position: 'fixed', left: x, top: y, zIndex: 1000 }}
    >
      <button className="cy-ctx-item" onClick={onExpandAll}>Expand all</button>
      <div
        className={'cy-ctx-item cy-ctx-has-sub' + (hoverEdge ? ' open' : '')}
        onMouseEnter={() => setHoverEdge(true)}
        onMouseLeave={() => setHoverEdge(false)}
      >
        <span>Expand by link</span>
        <span className="cy-ctx-chev">›</span>
        {hoverEdge && (
          <div className="cy-ctx-sub">
            {sortedOpts.length === 0 && (
              <div className="cy-ctx-empty">Nothing is known to link from this kind</div>
            )}
            {sortedOpts.map(({ edge, target }) => {
              const edgeColor   = edgeColorByLabel[edge] || '#94A3B8';
              const targetColor = vertexColorByLabel[target] || colorFor(target).ring;
              const targetIcon  = vertexIconByLabel[target];
              return (
                <button
                  key={`${edge}|${target}`}
                  className="cy-ctx-item cy-ctx-leaf"
                  onClick={() => onExpandFiltered(edge, target)}
                >
                  <span className="cy-ctx-edge-pill" style={{ background: edgeColor }}>
                    {edge}
                  </span>
                  <span className="cy-ctx-arrow" style={{ color: edgeColor }}>→</span>
                  <span className="cy-ctx-node-chip" style={{ background: targetColor }}>
                    {targetIcon
                      ? <IconByName name={targetIcon} size={12} color="#fff"/>
                      : <span style={{ fontSize: 11, color: '#fff', fontWeight: 600 }}>{(target[0] || '?').toUpperCase()}</span>}
                  </span>
                  <span className="cy-ctx-target-label">{target}</span>
                </button>
              );
            })}
          </div>
        )}
      </div>
      {collapsed ? (
        <button className="cy-ctx-item" onClick={onReExpand}>Restore collapsed</button>
      ) : (
        <button className="cy-ctx-item" onClick={onCollapse}>Collapse neighbors</button>
      )}
    </div>
  );
}

// A flat, one-row-per-property list (name → value). Arrays render comma-joined;
// residual objects fall back to compact JSON. Shared by node + edge details.
function PropList({ fields, empty }) {
  const entries = Object.entries(fields || {});
  if (entries.length === 0) return <div className="stat-lbl">{empty || 'no properties'}</div>;
  return (
    <div className="dg-prop-list">
      {entries.map(([k, v]) => (
        <div className="dg-prop-item" key={k}>
          <span className="dg-prop-name mono">{k}</span>
          <span className="dg-prop-val" style={{ wordBreak: 'break-word' }}>
            {v === null || v === undefined || v === ''
              ? <span className="stat-lbl">empty</span>
              : Array.isArray(v) ? v.map((x) => (typeof x === 'object' ? JSON.stringify(x) : String(x))).join(', ')
              : typeof v === 'object' ? JSON.stringify(v) : String(v)}
          </span>
        </div>
      ))}
    </div>
  );
}


const CLOSED = 'A record you can’t open';

/** A row that leads to a record, or says plainly that it can't. */
function Jump({ node, onJump, schema }) {
  if (!node || !node.record) return <span className="mm-lt off">{CLOSED}</span>;
  const k = kindInfo(kindOf(node.record), schema);
  return (
    <button type="button" className="mm-lt" onClick={() => onJump(node.record.id, node.memoryId || undefined)}>
      <span className="mm-dot sm" style={{ background: k.color }} />
      <span className="mgv-ell">{labelOf(node.record) || 'Untitled'}</span>
    </button>
  );
}

export function DataNodeDetail({ node, nodes, edges, schema, thisMemoryId, compact, collapsed, onJump, onExpand, onCollapse, onRestore, onClose }) {
  const cls = 'dg-detail' + (compact ? ' compact' : '');
  if (!node) return null;
  if (!node.record) {
    return (
      <div className={cls} role="region" aria-label={CLOSED}>
        <div className="dg-detail-h">
          <div style={{ flex: 1, minWidth: 0 }}><div style={{ fontWeight: 600, fontSize: 13 }}>{CLOSED}</div></div>
          <button type="button" className="pane-btn" aria-label="Close" onClick={onClose}>{I.close}</button>
        </div>
        <div className="dg-detail-b"><div className="stat-lbl">Something here links to it, and you don’t have access to where it is kept.</div></div>
      </div>
    );
  }
  const r = node.record;
  const k = kindInfo(kindOf(r), schema);
  const links = edges.filter((e) => e.from === node.key || e.to === node.key);
  const fields = Object.fromEntries(Object.entries(r.attributes || {}).filter(([a]) => a !== 'folder'));
  const text = bodyOf(r);
  const title = labelOf(r) || 'Untitled';
  const other = node.memoryId && node.memoryId !== thisMemoryId && node.memoryName ? ` · in ${node.memoryName}` : '';
  return (
    <div className={cls} role="region" aria-label={title}>
      <div className="dg-detail-h">
        <span className="av sm" style={{ background: k.color, color: '#fff', display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
          <IconByName name={k.icon} size={16} color="#fff" />
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 600, fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={title}>{title}</div>
          <div className="stat-lbl mono">{k.one}{other}</div>
        </div>
        <button type="button" className="pane-btn" aria-label="Close" onClick={onClose}>{I.close}</button>
      </div>
      <div className="dg-detail-b">
        {text && text !== title ? <p className="mgv-text">{truncateLabel(text, 360)}</p> : null}
        <div className="stat-lbl" style={{ fontWeight: 600, marginBottom: 6 }}>Properties</div>
        <PropList fields={fields} empty="no fields" />
        <div className="stat-lbl" style={{ fontWeight: 600, margin: '14px 0 6px' }}>Links <span className="mono">{links.length}</span></div>
        {links.length ? links.map((e) => {
          const out = e.from === node.key;
          const far = nodes[out ? e.to : e.from];
          if (e.fact) {
            return (
              <div className="mgv-link" key={e.key}>
                <button type="button" className="mgv-sentence" onClick={() => onJump(e.fact.id, e.factMemoryId || undefined)}>{labelOf(e.fact) || lineCaption(e.fact)}</button>
                <Jump node={far} onJump={onJump} schema={schema} />
              </div>
            );
          }
          return (
            <div className="mgv-link" key={e.key}>
              <Jump node={far} onJump={onJump} schema={schema} />
              {e.available ? <small className="mm-lrel">{`${out ? '' : '← '}${relText(e.rel)}${out ? ' →' : ''}`}</small> : null}
            </div>
          );
        }) : <div className="stat-lbl">no links</div>}
      </div>
      <div className="dg-detail-f">
        <button type="button" className="btn sm" onClick={() => onExpand(node.key)}>Expand neighbors</button>
        {collapsed
          ? <button type="button" className="btn sm" onClick={() => onRestore(node.key)}>Restore collapsed</button>
          : links.length ? <button type="button" className="btn sm" onClick={() => onCollapse(node.key)}>Collapse neighbors</button> : null}
      </div>
    </div>
  );
}

/** A line: a fact, or a reference with nothing more to say than what it means. Both ends lead somewhere. */
export function DataEdgeDetail({ edge, nodes, schema, compact, onJump, onClose }) {
  const cls = 'dg-detail' + (compact ? ' compact' : '');
  if (!edge) return null;
  const from = nodes[edge.from], to = nodes[edge.to];
  const title = edge.fact ? (labelOf(edge.fact) || lineCaption(edge.fact)) : edge.available ? relText(edge.rel) : 'Links to a record you can’t open';
  const fields = edge.fact ? edge.fact.attributes || {} : {};
  return (
    <div className={cls} role="region" aria-label="Link">
      <div className="dg-detail-h">
        <span className="av sm" style={{ background: '#94A3B8', color: '#fff', display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
          <IconByName name="ArrowRight" size={16} color="#fff" />
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 600, fontSize: 13, overflowWrap: 'anywhere' }}>{title}</div>
          {edge.fact ? <div className="stat-lbl mono">{`Fact${edge.fact.attributes?.predicate ? ` · ${relText(String(edge.fact.attributes.predicate))}` : ''}`}</div> : null}
        </div>
        <button type="button" className="pane-btn" aria-label="Close" onClick={onClose}>{I.close}</button>
      </div>
      <div className="dg-detail-b">
        <div className="stat-lbl" style={{ fontWeight: 600, marginBottom: 6 }}>Endpoints</div>
        <div className="dg-prop-list">
          <div className="dg-prop-item"><span className="dg-prop-name mono">{edge.directed ? 'source' : 'one end'}</span><span className="dg-prop-val"><Jump node={from} onJump={onJump} schema={schema} /></span></div>
          <div className="dg-prop-item"><span className="dg-prop-name mono">{edge.directed ? 'target' : 'other end'}</span><span className="dg-prop-val"><Jump node={to} onJump={onJump} schema={schema} /></span></div>
        </div>
        {Object.keys(fields).length ? (<>
          <div className="stat-lbl" style={{ fontWeight: 600, margin: '14px 0 6px' }}>Properties</div>
          <PropList fields={fields} empty="no properties" />
        </>) : null}
        {edge.also.length ? (<>
          <div className="stat-lbl" style={{ fontWeight: 600, margin: '14px 0 6px' }}>Came from</div>
          {edge.also.map((a) => <div className="mgv-link" key={a.to}><Jump node={nodes[a.to]} onJump={onJump} schema={schema} /></div>)}
        </>) : null}
      </div>
    </div>
  );
}
