// What a memory holds, drawn as its Schema tab draws it where nobody sets types (Mem0, ReMe): the kinds
// of record it holds and how they refer to each other, with what the engine makes itself beside them. The Schema tab
// shows it with each kind's count; the memory's cover is the same drawing (Richard 11-10: the card drew Mem0's lone
// "Fact" as a brick while the Schema tab showed five kinds and how they relate). Kinds and links are placed in a fixed
// order, so the same ones always land in the same places and a cover is made again only when one first appears.
import type { MemoryGraph, Provider } from '@/lib/memories';
import { kindInfo } from '../tree';
import { typeLabel } from '../schemaModel';
import { exploreOf, readGraph } from './adapter';
import { withBuiltin, type BGraph } from './builtin';
import { footprint, initialLayout } from './layout';
import { heldGraph, type VGraph } from './schemaDraft';

export interface Held {
  /** The drawing: marked `held`, so its cover says it shows what the memory holds (cover.ts coverSig). */
  graph: (VGraph | BGraph) & { held: true };
  /** `vertex:<kind>` and `edge:<link>`: how many of each the read found. */
  count: Record<string, number>;
  /** The read stopped short of everything the memory holds. */
  truncated: boolean;
}

const byLabel = (a: { label: string }, b: { label: string }) => (a.label < b.label ? -1 : a.label > b.label ? 1 : 0);
const end = (c: { from_type: string; to_type: string }) => `${c.from_type}\n${c.to_type}`;

/** The drawing of what a read of the memory found. */
export function heldOf(g: MemoryGraph, provider: Provider | null | undefined): Held {
  const { graph, count } = heldGraph(exploreOf(g), (k) => kindInfo(k, null));
  graph.vertex_types.sort(byLabel);
  graph.edge_types.sort(byLabel);
  for (const e of graph.edge_types) e.connections.sort((a, b) => (end(a) < end(b) ? -1 : end(a) > end(b) ? 1 : 0));
  const nodes = graph.vertex_types.map((v) => ({ id: v.label, ...footprint(`${typeLabel(v.label)}\n00 records`, 38) }));
  const edges = graph.edge_types.flatMap((e) => e.connections.map((c) => ({ source: c.from_type, target: c.to_type })));
  const { pos } = initialLayout(nodes, edges, { spread: 1.7 });
  graph.vertex_types.forEach((v) => {
    const p = pos.get(v.label);
    if (p) v.ui.position = { x: Math.round(p.x), y: Math.round(p.y) };
  });
  return { graph: { ...withBuiltin(graph, provider), held: true }, count, truncated: !!g.truncated };
}

/** Read the memory and draw what it holds. */
export async function readHeld(mid: string, provider: Provider | null | undefined): Promise<Held> {
  return heldOf(await readGraph(mid), provider);
}
