// Nothing on anything else in a schema's drawing: what a provider makes is set out as a figure no line crosses, and the
// check says where a straight link would pass under a type it doesn't join, or a name would sit on something.
import { figure, withBuiltin, type BGraph } from './builtin';
import { sizesAt, untangle, type UEdge, type UNode } from './untangle';
import type { Provider } from '@/lib/memories';

const N = (id: string, x: number, y: number, caption = id): UNode => ({ id, x, y, caption });
const E = (source: string, target: string, caption = 'RELATES'): UEdge => ({ id: `${source}-${target}`, source, target, caption });
/** The line of a link bowed by `d`, as the canvas draws it (a quadratic bezier, its control point d along the normal). */
function line(a: UNode, b: UNode, d: number): [number, number][] {
  const dx = b.x - a.x, dy = b.y - a.y, l = Math.hypot(dx, dy);
  const cx = (a.x + b.x) / 2 - (dy / l) * d, cy = (a.y + b.y) / 2 + (dx / l) * d;
  return Array.from({ length: 41 }, (_, i) => { const t = i / 40, u = 1 - t; return [u * u * a.x + 2 * u * t * cx + t * t * b.x, u * u * a.y + 2 * u * t * cy + t * t * b.y]; });
}

test('a provider’s own types are a figure: a triangle with its first on top, two side by side, never three in a line', () => {
  const [top, right, left] = figure(3);
  expect(top.y).toBeLessThan(right.y);
  expect(right.y).toBe(left.y);
  expect(right.x).toBeGreaterThan(0);
  expect(left.x).toBeLessThan(0);
  const [a, b] = figure(2);
  expect([a.y, b.y]).toEqual([0, 0]);
  expect(a.x).toBeLessThan(b.x);
  expect(figure(1)).toEqual([{ x: 0, y: 0 }]);
});

test.each([
  ['Graphiti', ['episode', 'entity', 'fact'], [['about', 'fact', 'entity'], ['derived_from', 'fact', 'episode']]],
  ['Hindsight', ['episode', 'fact', 'entity'], [['about', 'fact', 'entity'], ['derived_from', 'fact', 'episode']]],
  ['ReMe', ['episode', 'note'], [['derived_from', 'note', 'episode']]],
])('%s’s own types: no link under a type, no name on anything, at every size the tab and the cover draw', (_, types, rels) => {
  const p = { id: 'x', schema: { mode: 'guides', builtin: { types: types.map((name) => ({ name, description: '' })),
    relations: (rels as string[][]).map(([name, from, to]) => ({ name, from, to, description: '' })) } } } as Provider;
  const g = withBuiltin({ vertex_types: [], edge_types: [] }, p) as BGraph;
  // named as the canvas names them, with a count: the longest a name gets there (schemaCaption)
  const nodes = g.vertex_types.map((v) => N(v.label, v.ui.position!.x, v.ui.position!.y, `${g.titles?.[v.label] || v.label}\nBuilt in · 1,234 records`));
  const edges = g.edge_types.flatMap((e) => e.connections.map((c) => E(c.from_type, c.to_type, e.label)));
  // the canvas draws every link straight (and the cover is the canvas). It draws types at their own size (k 1) unless a
  // pane is too small to hold the graph at 80%, which this figure never is from 390 px up: there, nothing needs a bow
  const out = untangle(nodes, edges, sizesAt(1));
  expect([out.clashes, out.bows.size]).toEqual([0, 0]);
  // and with an everyday count, a little larger too
  const everyday = nodes.map((n) => ({ ...n, caption: n.caption.replace('1,234 records', '2 records') }));
  expect([untangle(everyday, edges, sizesAt(1.25)).clashes, untangle(everyday, edges, sizesAt(1.25)).bows.size]).toEqual([0, 0]);
});

test('a link that would pass under a type it doesn’t join bows round it', () => {
  const nodes = [N('A', 0, 0), N('B', 200, 0), N('C', 400, 0)];
  const edges = [E('A', 'B'), E('B', 'C'), E('A', 'C', 'FAR')];
  const s = sizesAt(1);
  const out = untangle(nodes, edges, s);
  expect(out.clashes).toBe(0);
  const d = out.bows.get('A-C') as number;
  expect(Math.abs(d)).toBeGreaterThan(0);
  expect(line(nodes[0], nodes[2], d).every(([x, y]) => Math.hypot(x - 200, y) >= s.r)).toBe(true);
  expect(out.bows.has('A-B') || out.bows.has('B-C')).toBe(false);
});

test('two links whose names would sit on each other: one bows until they are apart', () => {
  // a square's two diagonals cross at the middle, where both names would be
  const nodes = [N('A', 0, 0), N('B', 300, 0), N('C', 300, 300), N('D', 0, 300)];
  const out = untangle(nodes, [E('A', 'C', 'LEADS'), E('B', 'D', 'FOLLOWS')], sizesAt(1.5));
  expect(out.clashes).toBe(0);
  expect(out.bows.size).toBe(1);
});

test('types a person put on top of each other stay where they were put, and are counted, so the cover stops growing', () => {
  const out = untangle([N('A', 0, 0), N('B', 20, 0)], [], sizesAt(1));
  expect(out.clashes).toBe(1);
  expect(untangle([N('A', 0, 0), N('B', 300, 0)], [], sizesAt(1)).clashes).toBe(0);
  // grown large enough, two that were apart meet: the size that does it is a clash
  expect(untangle([N('A', 0, 0), N('B', 100, 0)], [], sizesAt(3)).clashes).toBe(1);
});
