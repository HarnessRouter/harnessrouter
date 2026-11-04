// A schema as the graph view reads it, and what its edits do. The view works in vertex types and edge types with their
// `ui`, as it always has; the service keeps one relation per pair of ends. These are the two conversions between them,
// and the draft that holds cosmetic and additive edits until Save.
import type { ExGraph } from './adapter';
import { relText } from '../caps';
import { uid, type LRel, type LSchema, type LType } from '../schemaModel';

export const cloneSchema = (s: LSchema): LSchema => JSON.parse(JSON.stringify(s)) as LSchema;

export interface VProp { id?: string; name: string; type: string; options?: string; description?: string }
export interface VType { label: string; description: string; properties: VProp[]; ui: { color?: string; icon?: string; position?: { x: number; y: number }; caption?: string }; id?: string }
export interface EType { label: string; description: string; connections: { from_type: string; to_type: string }[]; properties: VProp[]; ui: { color?: string } }
export interface VGraph { vertex_types: VType[]; edge_types: EType[]; /** What a type is called, where that isn't its name. */ titles?: Record<string, string> }
export interface Draft {
  name?: string | null; color?: string | null; icon?: string | null; description?: string | null; labelProps?: string[] | null;
  props?: { name: string; type: string; options?: string }[];
  addConns?: { from_type: string; to_type: string }[]; removeConns?: { from_type: string; to_type: string }[];
}

export function graphOf(s: LSchema): VGraph {
  const nameOf = (id: string) => s.types.find((t) => t.id === id)?.name || '';
  const edges = new Map<string, EType>();
  for (const r of s.relations) {
    const e = edges.get(r.name) || { label: r.name, description: r.description, connections: [], properties: [], ui: { color: r.color } };
    e.connections.push({ from_type: nameOf(r.from), to_type: nameOf(r.to) });
    if (!e.description) e.description = r.description;
    if (!e.ui.color) e.ui.color = r.color;
    edges.set(r.name, e);
  }
  return {
    vertex_types: s.types.map((t) => ({
      id: t.id, label: t.name, description: t.description, properties: t.properties,
      ui: { color: t.color, icon: t.icon, position: { x: t.x, y: t.y }, caption: t.caption },
    })),
    edge_types: [...edges.values()],
  };
}

/** Every pending edit, applied to a copy of the schema: what Save sends, whole. */
export function applyDrafts(s: LSchema, positions: Record<string, { x: number; y: number }>, drafts: Record<string, Draft>): LSchema {
  const out = cloneSchema(s);
  const byName = (n: string) => out.types.find((t) => t.name === n);
  // Links first, while types still answer to the names the draft knows them by.
  for (const [key, d] of Object.entries(drafts)) {
    const sep = key.indexOf(':'), kind = key.slice(0, sep), label = key.slice(sep + 1);
    if (kind !== 'edge') continue;
    const mine = out.relations.filter((r) => r.name === label);
    const gone = new Set((d.removeConns || []).map((c) => `${c.from_type}->${c.to_type}`));
    if (gone.size) {
      out.relations = out.relations.filter((r) => r.name !== label || !gone.has(`${s.types.find((t) => t.id === r.from)?.name}->${s.types.find((t) => t.id === r.to)?.name}`));
    }
    const color = d.color ?? mine[0]?.color, description = d.description ?? mine[0]?.description ?? '';
    for (const c of d.addConns || []) {
      const a = byName(c.from_type), b = byName(c.to_type);
      if (a && b) out.relations.push({ id: uid('r'), name: label, description, from: a.id, to: b.id, ...(color ? { color } : {}) });
    }
    for (const r of out.relations) {
      if (r.name !== label) continue;
      if (d.color != null) r.color = d.color;
      if (d.description != null) r.description = d.description;
    }
    if (d.name) for (const r of out.relations) if (r.name === label) r.name = d.name;
  }
  for (const [label, p] of Object.entries(positions)) {
    const t = byName(label);
    if (t) { t.x = Math.round(p.x); t.y = Math.round(p.y); }
  }
  for (const [key, d] of Object.entries(drafts)) {
    const sep = key.indexOf(':'), kind = key.slice(0, sep), label = key.slice(sep + 1);
    if (kind !== 'vertex') continue;
    const t = byName(label);
    if (!t) continue;
    if (d.color != null) t.color = d.color;
    if (d.icon != null) t.icon = d.icon;
    if (d.description != null) t.description = d.description;
    if (d.labelProps != null) t.caption = d.labelProps[0] || 'title';
    for (const raw of d.props || []) {
      if (!raw.name || !raw.name.trim()) continue;   // blank rows are ignored on Save
      t.properties.push({ id: uid('p'), name: raw.name.trim(), type: raw.type as LType['properties'][number]['type'], description: '', options: raw.options || '' });
    }
    if (d.name) t.name = d.name;
  }
  return out;
}

export const newRelation = (name: string, from: string, to: string, color?: string): LRel => ({ id: uid('r'), name, description: '', from, to, ...(color ? { color } : {}) });

const typeWord = (v: unknown): string => (typeof v === 'number' ? 'number' : typeof v === 'boolean' ? 'yesno' : 'text');

/** For a provider that takes no schema: what the memory holds, as the same shape, read from its records. One type per
 *  kind, with the attribute names actually seen on its records, and one edge type per kind of link seen. */
export function heldGraph(ex: ExGraph, look: (kind: string) => { color: string; icon: string; one: string }): { graph: VGraph; count: Record<string, number> } {
  const types = new Map<string, { n: number; attrs: Map<string, string> }>();
  const edges = new Map<string, { n: number; pairs: Map<string, { from_type: string; to_type: string }> }>();
  const see = (kind: string, attrs: Record<string, unknown> | undefined) => {
    const t = types.get(kind) || { n: 0, attrs: new Map<string, string>() };
    t.n += 1;
    for (const [a, v] of Object.entries(attrs || {})) if (!t.attrs.has(a)) t.attrs.set(a, typeWord(v));
    types.set(kind, t);
  };
  for (const n of Object.values(ex.nodes)) if (n.record) see(n.kind, n.record.attributes);
  const count: Record<string, number> = {};
  for (const e of ex.edges) {
    if (e.fact) see(String(e.fact.attributes?.entity_type || '') || e.fact.type, e.fact.attributes);
    if (!e.available) continue;
    const a = ex.nodes[e.from]?.kind, b = ex.nodes[e.to]?.kind;
    if (!a || !b) continue;
    const word = e.fact ? 'Fact' : relText(e.rel);
    const x = edges.get(word) || { n: 0, pairs: new Map() };
    x.n += 1;
    x.pairs.set(`${a}->${b}`, { from_type: a, to_type: b });
    edges.set(word, x);
  }
  const graph: VGraph = {
    titles: Object.fromEntries([...types.keys()].map((kind) => [kind, look(kind).one])),
    vertex_types: [...types.entries()].map(([kind, t]) => {
      const k = look(kind);
      count[`vertex:${kind}`] = t.n;
      return { label: kind, description: '', properties: [...t.attrs.entries()].map(([name, type]) => ({ name, type })), ui: { color: k.color, icon: k.icon, caption: 'title' } };
    }),
    edge_types: [...edges.entries()].map(([word, x]) => {
      count[`edge:${word}`] = x.n;
      return { label: word, description: '', connections: [...x.pairs.values()], properties: [], ui: {} };
    }),
  };
  return { graph, count };
}
