// The arrangement, as plain functions of the graph: the rule step by step, on real shapes and on generated ones.
import {
  arrive, centerOf, components, displacement, estimate, footprint, freeSpot, initialLayout, meanEdge, overlaps, packCircles, placeAround, rectOf, resolveOverlaps, seeded, spreadAngles,
  type LEdge, type LNode, type Pos,
} from './layout';
import { REAL_SHAPES } from './layout.fixtures';

const node = (id: string, chars = 12, size = 34): LNode => ({ id, ...footprint('x'.repeat(chars), size) });
const edge = (source: string, target: string): LEdge => ({ source, target });
const names = (n: number, p = 'n') => Array.from({ length: n }, (_, i) => `${p}${i}`);
const star = (n: number) => { const ids = names(n); return { nodes: ids.map((i) => node(i)), edges: ids.slice(1).map((x) => edge('n0', x)) }; };
const chain = (n: number) => { const ids = names(n); return { nodes: ids.map((i) => node(i)), edges: ids.slice(1).map((x, i) => edge(ids[i], x)) }; };
const boxesOf = (nodes: LNode[]) => new Map(nodes.map((n) => [n.id, n]));
const real = (name: string) => {
  const s = REAL_SHAPES[name];
  return { nodes: s.captions.map((c, i) => node(`r${i}`, c)), edges: s.edges.map(([a, b]) => edge(`r${a}`, `r${b}`)) };
};
const dist = (p: Pos, a: string, b: string) => Math.hypot((p.get(a) as { x: number }).x - (p.get(b) as { x: number }).x, (p.get(a) as { y: number }).y - (p.get(b) as { y: number }).y);
const angle = (p: Pos, from: string, to: string) => Math.atan2((p.get(to) as { y: number }).y - (p.get(from) as { y: number }).y, (p.get(to) as { x: number }).x - (p.get(from) as { x: number }).x);
const within = (a: number, b: number) => { const d = Math.abs(a - b) % (2 * Math.PI); return Math.min(d, 2 * Math.PI - d); };

describe('rule 1 and 2: each component around its busiest record', () => {
  it('finds the connected components', () => {
    expect(components(['a', 'b', 'c', 'd', 'e'], [edge('a', 'b'), edge('c', 'd')])).toEqual([['a', 'b'], ['c', 'd'], ['e']]);
  });
  it('the record with the most links is the centre, and its neighbours go evenly around it', () => {
    const { nodes, edges } = star(9);
    const { pos, est } = initialLayout(nodes, edges);
    const all = [...nodes.slice(1)].map((n) => dist(pos, 'n0', n.id));
    all.forEach((d) => expect(Math.abs(d - est.L)).toBeLessThan(est.L * 0.35));
    const angles = nodes.slice(1).map((n) => angle(pos, 'n0', n.id)).sort((a, b) => a - b);
    const gaps = angles.map((a, i) => (i ? a - angles[i - 1] : a + 2 * Math.PI - angles[angles.length - 1]));
    expect(Math.max(...gaps) - Math.min(...gaps)).toBeLessThan(0.4);
  });
  it('between equals, the middle of the longest path, so a chain grows both ways', () => {
    const { nodes, edges } = chain(9);
    const adj = new Map(nodes.map((n) => [n.id, new Set<string>()]));
    edges.forEach((e) => { adj.get(e.source)?.add(e.target); adj.get(e.target)?.add(e.source); });
    expect(centerOf(nodes.map((n) => n.id), adj)).toBe('n4');
  });
  it('a second layer goes in the direction of what it links to in the first: outward from one, between two', () => {
    const ids = ['c', 'a', 'b', 'x', 'y', 'z', 'between', 'behind'];
    const nodes = ids.map((i) => node(i));
    const edges = [edge('c', 'a'), edge('c', 'b'), edge('c', 'x'), edge('c', 'y'), edge('c', 'z'), edge('between', 'a'), edge('between', 'b'), edge('behind', 'x')];
    const { pos } = initialLayout(nodes, edges);
    expect(within(angle(pos, 'c', 'behind'), angle(pos, 'c', 'x'))).toBeLessThan(0.45);
    const a = angle(pos, 'c', 'a'), b = angle(pos, 'c', 'b');
    const mid = Math.atan2(Math.sin(a) + Math.sin(b), Math.cos(a) + Math.cos(b));
    expect(within(angle(pos, 'c', 'between'), mid)).toBeLessThan(0.45);
    expect(dist(pos, 'c', 'between')).toBeGreaterThan(dist(pos, 'c', 'a'));
  });
  it('directions that cancel out take a random one, and the same one every time', () => {
    const ids = ['c', 'a', 'b', 'o'];
    const nodes = ids.map((i) => node(i));
    const edges = [edge('c', 'a'), edge('c', 'b'), edge('o', 'a'), edge('o', 'b')];
    const one = initialLayout(nodes, edges, { seed: 4 }).pos, two = initialLayout(nodes, edges, { seed: 4 }).pos, other = initialLayout(nodes, edges, { seed: 9 }).pos;
    expect(one.get('o')).toEqual(two.get('o'));
    expect(one.get('o')).not.toEqual(other.get('o'));
  });
  it('a layer that outgrows its ring carries on to another, so a big star stays round and compact', () => {
    const { nodes, edges } = star(500);
    const { pos } = initialLayout(nodes, edges);
    const r = Math.max(...nodes.slice(1).map((n) => dist(pos, 'n0', n.id)));
    const oneRing = (499 * estimate(nodes).sep) / (2 * Math.PI);
    expect(r).toBeLessThan(oneRing * 0.45);
  });
  it('spreads angles apart, as near as it can to those wanted', () => {
    const got = spreadAngles([1, 1, 1], 0.5).sort((a, b) => a - b);
    expect(got[1] - got[0]).toBeCloseTo(0.5);
    expect((got[0] + got[1] + got[2]) / 3).toBeCloseTo(1);
    expect(spreadAngles([0, 2], 0.1).map((x) => Number(x.toFixed(3)))).toEqual([0, 2]);
  });
});

describe('rule 3: the components as circles, the biggest in the middle', () => {
  it('packs them with the original packCircles: the largest centred, tangent, none overlapping', () => {
    const radii = [10, 50, 30, 30, 20, 8, 8, 8];
    const c = packCircles(radii, 2);
    expect(c[1]).toEqual({ x: 0, y: 0 });
    for (let i = 0; i < radii.length; i++) for (let j = i + 1; j < radii.length; j++) {
      expect(Math.hypot(c[i].x - c[j].x, c[i].y - c[j].y)).toBeGreaterThanOrEqual(radii[i] + radii[j] + 2 - 1e-6);
    }
    // the second is tangent to the first
    expect(Math.hypot(c[2].x, c[2].y)).toBeCloseTo(50 + 30 + 2);
  });
  it('no two components share space, whatever is in them', () => {
    const big = star(30);
    const nodes = [...big.nodes, ...names(8, 'b').map((i) => node(i)), ...names(40, 's').map((i) => node(i))];
    const edges = [...big.edges, ...names(7, 'b').map((x, i) => edge(`b${i}`, `b${i + 1}`))];
    const { pos, circles } = initialLayout(nodes, edges);
    expect(overlaps(nodes.map((n) => n.id), pos, boxesOf(nodes))).toBe(0);
    const biggest = circles.reduce((m, c) => (c.r > m.r ? c : m), circles[0]);
    expect(Math.hypot(biggest.x, biggest.y)).toBeLessThan(1);
    circles.forEach((a, i) => circles.slice(i + 1).forEach((b) => expect(Math.hypot(a.x - b.x, a.y - b.y)).toBeGreaterThanOrEqual(a.r + b.r - 1e-6)));
    // bounds: each record is inside its circle
    circles.forEach((c) => c.ids.forEach((id) => {
      const r = rectOf(pos.get(id) as { x: number; y: number }, boxesOf(nodes).get(id) as LNode);
      expect(Math.hypot(Math.max(Math.abs(r.x0 - c.x), Math.abs(r.x1 - c.x)), Math.max(Math.abs(r.y0 - c.y), Math.abs(r.y1 - c.y)))).toBeLessThanOrEqual(c.r + 1e-6);
    }));
  });
  it('real memories start with nothing on top of anything', () => {
    for (const name of Object.keys(REAL_SHAPES)) {
      const { nodes, edges } = real(name);
      expect(overlaps(nodes.map((n) => n.id), initialLayout(nodes, edges).pos, boxesOf(nodes))).toBe(0);
    }
  });
  it('a free spot is tangent and clear, as near the middle as there is', () => {
    const circles = [{ x: 0, y: 0, r: 100 }, { x: 130, y: 0, r: 30 }];
    const at = freeSpot(circles, 20, 2);
    circles.forEach((c) => expect(Math.hypot(at.x - c.x, at.y - c.y)).toBeGreaterThanOrEqual(c.r + 20 + 2 - 1e-6));
    expect(Math.hypot(at.x, at.y)).toBeLessThan(100 + 20 + 2 + 30);
  });
});

describe('rule 5: what is new arrives around what it links to', () => {
  const base = () => {
    const { nodes, edges } = star(7);
    return { nodes, edges, known: initialLayout(nodes, edges).pos };
  };
  it('on as many rings as it needs, around the parent, clear of what is there, nothing else moved', () => {
    const { nodes, edges, known } = base();
    const add = names(40, 'new').map((i) => node(i));
    const all = [...nodes, ...add], allE = [...edges, ...add.map((n) => edge('n3', n.id))];
    const before = JSON.stringify([...known]);
    const seeds = arrive(all, allE, known);
    expect(JSON.stringify([...known])).toBe(before);
    expect(seeds.size).toBe(40);
    const pos = new Map([...known, ...seeds]);
    expect(overlaps(all.map((n) => n.id), pos, boxesOf(all))).toBe(0);
    const unit = meanEdge(edges, known);
    const rings = [...seeds.keys()].map((k) => Math.round(dist(pos, 'n3', k) / unit));
    expect(new Set(rings).size).toBeGreaterThan(1);
    // around it: a new record in every direction
    const quads = new Set([...seeds.keys()].map((k) => Math.floor(((angle(pos, 'n3', k) + Math.PI) / (2 * Math.PI)) * 4)));
    expect(quads.size).toBe(4);
  });
  it('a few new ones sit about one link from the parent', () => {
    const add = names(3, 'new').map((i) => node(i));
    const nodes = [node('a'), node('b'), ...add];
    const edges = [edge('a', 'b'), ...add.map((n) => edge('a', n.id))];
    const known: Pos = new Map([['a', { x: 0, y: 0 }], ['b', { x: 150, y: 0 }]]);
    const pos = new Map([...known, ...arrive(nodes, edges, known)]);
    add.forEach((n) => { expect(dist(pos, 'a', n.id)).toBeGreaterThan(100); expect(dist(pos, 'a', n.id)).toBeLessThan(220); });
  });
  it('what links only to something new follows it outward', () => {
    const nodes = [node('a'), node('b'), node('c')];
    const known: Pos = new Map([['a', { x: 0, y: 0 }]]);
    const seeds = arrive(nodes, [edge('a', 'b'), edge('b', 'c')], known);
    expect(seeds.has('b') && seeds.has('c')).toBe(true);
  });
  it('a new component finds a free place by the circles', () => {
    const { nodes, edges, known } = base();
    const add = names(5, 'k').map((i) => node(i));
    const all = [...nodes, ...add], allE = [...edges, ...add.slice(1).map((n) => edge('k0', n.id))];
    const seeds = arrive(all, allE, known);
    const pos = new Map([...known, ...seeds]);
    expect(overlaps(all.map((n) => n.id), pos, boxesOf(all))).toBe(0);
    const inner = Math.max(...nodes.map((n) => { const p = known.get(n.id) as { x: number; y: number }; return Math.hypot(p.x, p.y); }));
    const center = seeds.get('k0') as { x: number; y: number };
    expect(Math.hypot(center.x, center.y)).toBeGreaterThan(inner);
  });
  it('rings keep clear of what is already there, and placeAround leaves it alone', () => {
    const nodes = [node('p'), node('q')];
    const pos: Pos = new Map([['p', { x: 0, y: 0 }], ['q', { x: 140, y: 0 }]]);
    const add = names(6, 'z').map((i) => node(i));
    const boxes = boxesOf([...nodes, ...add]);
    placeAround('p', add.map((n) => n.id), pos, boxes, 140, estimate([...nodes, ...add]));
    expect(pos.get('q')).toEqual({ x: 140, y: 0 });
    expect(overlaps([...boxes.keys()], pos, boxes)).toBe(0);
  });
});

describe('the small tools', () => {
  it('a record takes up its disc and its name, with room for the name to grow', () => {
    const short = footprint('Acme', 34), long = footprint('x'.repeat(32), 34);
    expect(short.w).toBeLessThan(long.w);
    expect(long.w).toBeLessThanOrEqual(148 * 1.3);
    expect(long.h).toBeGreaterThan(short.h);
    expect(footprint('Company\n3 records', 38).h).toBeGreaterThan(footprint('Company', 38).h);
  });
  it('parts what overlaps, by the least it can, and leaves what is held', () => {
    const nodes = [node('a'), node('b'), node('c')];
    const pos: Pos = new Map([['a', { x: 0, y: 0 }], ['b', { x: 10, y: 0 }], ['c', { x: 900, y: 0 }]]);
    const boxes = boxesOf(nodes);
    expect(resolveOverlaps(['a', 'b', 'c'], pos, boxes, { held: new Set(['a']) })).toBeGreaterThanOrEqual(0);
    expect(pos.get('a')).toEqual({ x: 0, y: 0 });
    expect(pos.get('c')).toEqual({ x: 900, y: 0 });
    expect(overlaps(['a', 'b', 'c'], pos, boxes)).toBe(0);
  });
  it('the same seed is the same stream', () => {
    const a = seeded(3), b = seeded(3);
    expect([a(), a()]).toEqual([b(), b()]);
  });
  it('measures movement in mean link lengths', () => {
    const a: Pos = new Map([['x', { x: 0, y: 0 }], ['y', { x: 0, y: 0 }]]);
    const b: Pos = new Map([['x', { x: 3, y: 4 }], ['y', { x: 0, y: 0 }]]);
    expect(displacement(a, b, 10)).toEqual({ mean: 0.25, worst: 0.5 });
  });
});
