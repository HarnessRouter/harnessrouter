'use client';
// A schema as the canvas draws it: one node per type, one edge per relation between two types. The Schema tab draws it
// live (SchemaEditor.jsx) and a memory's cover is the same drawing, made offscreen (coverShot.js).
import { relText } from '../caps';
import { typeLabel } from '../schemaModel';
import { colorFor } from './CytoscapeCanvas.jsx';
import { iconUrl } from './graphIcons.jsx';

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
    if (vt.builtin) data.builtin = true;
    // what the provider makes itself stays where it is drawn: nobody moves, renames or removes it
    elements.push({ data, position: { x: pos.x, y: pos.y }, grabbable: !vt.builtin, ...(vt.builtin ? { classes: 'builtin' } : {}) });
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
      const classes = [preview ? 'preview' : '', c.builtin ? 'builtin' : ''].filter(Boolean).join(' ');
      elements.push({
        data: {
          id: `e-${label}-${c.from_type}-${c.to_type}`,
          kind: 'edge', edgeLabel: label,
          source: c.from_type, target: c.to_type, caption: relText(d.name || label), lineColor: color,
        },
        ...(classes ? { classes } : {}),
      });
    });
  });
  return elements;
}

/** A type's name as the canvas shows it: its title, and under it "Built in" for what the provider makes itself and
 *  `count` (how many records are of it, in words) where that is known. The Schema tab gives the count, live; a
 *  memory's cover can't keep a number true, so it gives none (coverShot.js). Both name their types here. */
export function schemaCaption(graph, label, d, count) {
  const built = ((graph && graph.vertex_types) || []).some((v) => v.label === label && v.builtin);
  const sub = [built ? 'Built in' : '', count || ''].filter(Boolean).join(' · ');
  return `${(graph && graph.titles && graph.titles[label]) || typeLabel((d && d.name) || label)}${sub ? `\n${sub}` : ''}`;
}
