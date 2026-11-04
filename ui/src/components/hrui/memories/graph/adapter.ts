// A memory's graph as the canvas draws it (UHP Memories §6.6). Records are nodes and references are
// edges, and that is the whole of the input: what differs between providers is how much is in it, so
// nothing here asks which provider this is and nothing is drawn that the read did not answer.
import { harnessFetch } from '@/lib/hfetch';
import { gwHeaders } from '@/lib/harness';
import { labelOf, MemoryApiError, type GraphEdge, type MemoryGraph, type MemoryRecord } from '@/lib/memories';
import { kindOf, relText } from '../caps';

/** The most records one read asks for. A read with more says `truncated`, and the page says so. */
export const GRAPH_LIMIT = 500;

/** The graph read itself, with `around` left out for the whole memory (§6.6). */
export async function readGraph(mid: string, o: { around?: string; hops?: number; limit?: number } = {}): Promise<MemoryGraph> {
  const r = await harnessFetch(`/api/harness/v1/memories/${encodeURIComponent(mid)}/graph`, {
    method: 'POST', headers: gwHeaders(), cache: 'no-store',
    body: JSON.stringify({ hops: o.hops ?? 1, limit: o.limit ?? GRAPH_LIMIT, ...(o.around ? { around: o.around } : {}) }),
  });
  if (!r.ok) throw new MemoryApiError(r.status, '', `The service answered ${r.status}.`);
  const d = await r.json();
  return { nodes: d.nodes || [], edges: d.edges || [], truncated: !!d.truncated, degraded: d.degraded || [] };
}

export interface ExNode {
  /** The record's id, and the id of its element on the canvas. */
  key: string;
  /** The memory it is in; null for a record the reader may not open, whose memory is not named. */
  memoryId: string | null;
  memoryName: string;
  /** Null for a record the reader may not open. */
  record: MemoryRecord | null;
  kind: string;
  title: string;
}
export interface ExEdge {
  key: string;
  from: string;
  to: string;
  /** The reference's meaning; null where it is not said (a reference the reader can't follow). */
  rel: string | null;
  available: boolean;
  /** Set when this line is a fact: the record that opens when the line is clicked. */
  fact: MemoryRecord | null;
  factMemoryId: string | null;
  /** What the fact also points at, which a line has no end to draw from. */
  also: { rel: string | null; to: string }[];
  /** False where the read says only that two things are related, not which way. */
  directed: boolean;
}
export interface ExGraph { nodes: Record<string, ExNode>; edges: ExEdge[]; truncated: boolean; degraded: string[] }

export const closedKey = (recordId: string) => `closed:${recordId}`;
const edgeKey = (from: string, rel: string | null, to: string) => `e:${from}:${rel || ''}:${to}`;
export const lineKey = (factId: string) => `line:${factId}`;

// What a fact may hold and still be drawn as one line: the two it relates, and where it came from.
const LINE_RELS = new Set(['subject', 'object', 'about', 'derived_from']);

/** The two ends a fact relates, when it can be drawn as one line between them (§4.2): a subject and an
 *  object, or just two entities it is about, which says they are related and not which way. */
function endsOf(id: string, out: GraphEdge[], incoming: boolean, nodes: Map<string, MemoryRecord>): { from: string; to: string; directed: boolean } | null {
  // A line has no end for anything else to attach to, so a fact others point at stays a node.
  if (incoming || out.some((e) => !e.available || !LINE_RELS.has(String(e.rel)))) return null;
  const to = (rel: string) => out.filter((e) => e.rel === rel).map((e) => e.to.record_id);
  const subj = to('subject'), obj = to('object');
  if (subj.length === 1 && obj.length === 1) {
    return nodes.has(subj[0]) && nodes.has(obj[0]) ? { from: subj[0], to: obj[0], directed: true } : null;
  }
  if (subj.length || obj.length) return null;
  const about = [...new Set(to('about'))];
  if (about.length === 2 && about.every((x) => nodes.get(x)?.type === 'entity' && x !== id)) {
    return { from: about[0], to: about[1], directed: false };
  }
  return null;
}

export function exploreOf(g: MemoryGraph): ExGraph {
  const nodes: Record<string, ExNode> = {};
  const records = new Map<string, MemoryRecord>();
  const memoryOf = new Map<string, { id: string; name: string }>();
  for (const n of g.nodes) { records.set(n.record.id, n.record); memoryOf.set(n.record.id, n.memory); }
  const outOf = new Map<string, GraphEdge[]>();
  const pointedAt = new Set<string>();
  for (const e of g.edges) {
    const l = outOf.get(e.from.record_id) || [];
    l.push(e);
    outOf.set(e.from.record_id, l);
    if (e.available) pointedAt.add(e.to.record_id);
  }
  const lines = new Map<string, { from: string; to: string; directed: boolean }>();
  for (const r of records.values()) {
    if (r.type !== 'fact') continue;
    const ends = endsOf(r.id, outOf.get(r.id) || [], pointedAt.has(r.id), records);
    if (ends) lines.set(r.id, ends);
  }
  for (const r of records.values()) {
    if (lines.has(r.id)) continue;
    const m = memoryOf.get(r.id);
    nodes[r.id] = { key: r.id, memoryId: m?.id || null, memoryName: m?.name || '', record: r, kind: kindOf(r), title: labelOf(r) };
  }
  const edges: ExEdge[] = [];
  const seen = new Set<string>();
  const push = (e: ExEdge) => { if (!seen.has(e.key)) { seen.add(e.key); edges.push(e); } };
  for (const [id, ends] of lines) {
    const r = records.get(id) as MemoryRecord;
    push({
      key: lineKey(id), from: ends.from, to: ends.to, rel: null, available: true, fact: r,
      factMemoryId: memoryOf.get(id)?.id || null, directed: ends.directed,
      also: (outOf.get(id) || []).filter((e) => e.rel === 'derived_from').map((e) => ({ rel: e.rel || null, to: e.to.record_id })),
    });
  }
  for (const e of g.edges) {
    const from = e.from.record_id;
    if (lines.has(from) || !nodes[from]) continue;
    if (!e.available) {
      // The rule of §4.2 unchanged: that there is a record, and nothing about it. Not its memory, not what the reference means.
      const key = closedKey(e.to.record_id);
      nodes[key] = nodes[key] || { key, memoryId: null, memoryName: '', record: null, kind: '', title: '' };
      push({ key: edgeKey(from, null, key), from, to: key, rel: null, available: false, fact: null, factMemoryId: null, also: [], directed: false });
      continue;
    }
    // Its target is a node only when the read returned it. An end outside this read isn't drawn.
    if (!nodes[e.to.record_id]) continue;
    push({ key: edgeKey(from, e.rel || null, e.to.record_id), from, to: e.to.record_id, rel: e.rel || null, available: true, fact: null, factMemoryId: null, also: [], directed: true });
  }
  return { nodes, edges, truncated: !!g.truncated, degraded: g.degraded || [] };
}

export const emptyGraph = (): MemoryGraph => ({ nodes: [], edges: [], truncated: false, degraded: [] });

/** Two reads as one, before anything is made of them: whether a fact is a line depends on all the
 *  references read so far, so the same fact can't be a node in one read and a line in another. The later
 *  read's copy of a record wins. */
export function mergeGraphs(a: MemoryGraph, b: MemoryGraph): MemoryGraph {
  const nodes = new Map(a.nodes.map((n) => [n.record.id, n]));
  b.nodes.forEach((n) => nodes.set(n.record.id, n));
  const sig = (e: GraphEdge) => `${e.from.record_id}|${e.rel || ''}|${e.to.record_id}|${e.available}`;
  const edges = new Map(a.edges.map((e) => [sig(e), e]));
  b.edges.forEach((e) => edges.set(sig(e), e));
  return {
    nodes: [...nodes.values()], edges: [...edges.values()], truncated: a.truncated || b.truncated,
    degraded: [...new Set([...(a.degraded || []), ...(b.degraded || [])])],
  };
}

const NOT_A_NAME = new Set(['relates_to', 'related', 'related_to']);
/** Short enough for a line's label, ending between words where there is a place to. */
function short(s: string, max: number): string {
  if (s.length <= max) return s;
  const cut = s.slice(0, Math.max(1, max - 1));
  const sp = cut.lastIndexOf(' ');
  return `${(sp > max * 0.5 ? cut.slice(0, sp) : cut).trimEnd()}…`;
}
/** What a line reads as on the canvas: the word it was filed under where that says anything, else its sentence. */
export function lineCaption(fact: MemoryRecord): string {
  const p = String(fact.attributes?.predicate || '');
  if (p && !NOT_A_NAME.has(p.toLowerCase())) return relText(p);
  return short(labelOf(fact) || 'related to', 28);
}
/** What a bare reference reads as. */
export const edgeCaption = (e: ExEdge) => (e.fact ? lineCaption(e.fact) : e.available ? relText(e.rel) : '');

/** The records this read holds, by what a person would look for, including the facts drawn as lines. */
export function recordsIn(g: ExGraph): { record: MemoryRecord; memoryId: string | null }[] {
  const out: { record: MemoryRecord; memoryId: string | null }[] = [];
  for (const n of Object.values(g.nodes)) if (n.record) out.push({ record: n.record, memoryId: n.memoryId });
  for (const e of g.edges) if (e.fact) out.push({ record: e.fact, memoryId: e.factMemoryId });
  return out;
}

/** The canvas element a record is drawn as: its node, or the line that is the fact. */
export function elementOf(g: ExGraph, recordId: string): string | null {
  if (g.nodes[recordId]) return recordId;
  return g.edges.some((e) => e.key === lineKey(recordId)) ? lineKey(recordId) : null;
}

/** What `kind` a record's element counts under, for the legend. */
export function kindsIn(g: ExGraph): Map<string, number> {
  const m = new Map<string, number>();
  for (const { record } of recordsIn(g)) { const k = kindOf(record); m.set(k, (m.get(k) || 0) + 1); }
  return m;
}

/** Collapsing a node folds away every line at it and hides only the neighbours left with nothing else;
 *  the ones the person put on the canvas themselves stay. Null when there is nothing at it to fold. */
export function computeCollapse(anchor: string, edges: ExEdge[], roots: Set<string>): { hidden: string[]; removed: string[] } | null {
  const incident = edges.filter((e) => e.from === anchor || e.to === anchor);
  if (!incident.length) return null;
  const gone = new Set(incident.map((e) => e.key));
  const degree = new Map<string, number>();
  for (const e of edges) {
    if (gone.has(e.key)) continue;
    degree.set(e.from, (degree.get(e.from) || 0) + 1);
    degree.set(e.to, (degree.get(e.to) || 0) + 1);
  }
  const hidden = new Set<string>();
  for (const e of incident) {
    const other = e.from === anchor ? e.to : e.from;
    if (other !== anchor && !roots.has(other) && !degree.get(other)) hidden.add(other);
  }
  return { hidden: [...hidden], removed: [...gone] };
}
