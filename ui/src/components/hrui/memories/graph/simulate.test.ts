// The simulation, measured: how far anything moves while it runs, in mean link lengths, on the shapes of real memories
// and on generated graphs. The bounds below are what "minimise the drastic re-layout" means here.
import { join } from 'node:path';
import { arrive, displacement, footprint, initialLayout, meanEdge, overlaps, type LEdge, type LNode, type Pos } from './layout';
import { REAL_SHAPES } from './layout.fixtures';
import { createSim } from './simulate';

// d3-force ships ES modules only, and jest here runs CommonJS: its own UMD builds, here and nowhere else.
jest.mock('d3-dispatch', () => jest.requireActual(require('node:path').join(process.cwd(), 'node_modules/d3-dispatch/dist/d3-dispatch.js')));
jest.mock('d3-quadtree', () => jest.requireActual(require('node:path').join(process.cwd(), 'node_modules/d3-quadtree/dist/d3-quadtree.js')));
jest.mock('d3-timer', () => jest.requireActual(require('node:path').join(process.cwd(), 'node_modules/d3-timer/dist/d3-timer.js')));
// eslint-disable-next-line @typescript-eslint/no-require-imports
const d3 = require(join(process.cwd(), 'node_modules/d3-force/dist/d3-force.js'));

const node = (id: string, chars = 12, deg = 0): LNode => ({ id, ...footprint('x'.repeat(chars), 30 + Math.min(deg, 10) * 2.2) });
function shape(ids: string[], edges: LEdge[], chars: (i: number) => number = (i) => 8 + (i * 7) % 24) {
  const d = new Map<string, number>();
  edges.forEach((e) => { d.set(e.source, (d.get(e.source) || 0) + 1); d.set(e.target, (d.get(e.target) || 0) + 1); });
  return { nodes: ids.map((id, i) => node(id, chars(i), d.get(id) || 0)), edges };
}
const ids = (n: number, p = 'n') => Array.from({ length: n }, (_, i) => `${p}${i}`);
let s = 7;
const rnd = () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
function generated(): Record<string, { nodes: LNode[]; edges: LEdge[] }> {
  const star = ids(500); const chain = ids(300);
  const a = ids(70, 'a'), b = ids(50, 'b'), e2: LEdge[] = [];
  for (const cl of [a, b]) {
    for (let i = 1; i < cl.length; i++) e2.push({ source: cl[i], target: cl[Math.floor(rnd() * i)] });
    for (let i = 0; i < cl.length * 0.6; i++) { const x = cl[Math.floor(rnd() * cl.length)], y = cl[Math.floor(rnd() * cl.length)]; if (x !== y) e2.push({ source: x, target: y }); }
  }
  const big = ids(500, 'r'), e3: LEdge[] = [];
  for (let i = 1; i < 460; i++) e3.push({ source: big[i], target: big[Math.floor(rnd() * rnd() * i)] });
  for (let i = 0; i < 120; i++) { const x = big[Math.floor(rnd() * 460)], y = big[Math.floor(rnd() * 460)]; if (x !== y) e3.push({ source: x, target: y }); }
  return {
    'star of 500': shape(star, star.slice(1).map((x) => ({ source: 'n0', target: x }))),
    'chain of 300': shape(chain, chain.slice(1).map((x, i) => ({ source: chain[i], target: x }))),
    'two clusters and 80 singletons': shape([...a, ...b, ...ids(80, 'x')], e2),
    '500 records with hubs': shape(big, e3),
  };
}
const real = Object.fromEntries(Object.entries(REAL_SHAPES).map(([k, v]) => [k, shape(v.captions.map((_, i) => `r${i}`), v.edges.map(([a, b]) => ({ source: `r${a}`, target: `r${b}` })), (i) => v.captions[i])]));
const ALL = { ...real, ...generated() };

function run(nodes: LNode[], edges: LEdge[], start: Pos, held?: Set<string>, unitOf = meanEdge(edges, start)) {
  const sim = createSim(d3, nodes, edges, start, held ? { held } : {});
  let worst = 0;
  const only = held || undefined;
  while (sim.step(1)) worst = Math.max(worst, displacement(start, sim.positions(), unitOf, only).worst);
  const end = sim.finish();
  const d = displacement(start, end, unitOf, only);
  return { end, mean: d.mean, worst: Math.max(worst, d.worst), ticks: sim.ticks() };
}

describe.each(Object.keys(ALL))('%s', (name) => {
  const { nodes, edges } = ALL[name];
  const start = initialLayout(nodes, edges, { seed: 3 });
  const boxes = new Map(nodes.map((n) => [n.id, n]));
  const copy: Pos = new Map([...start.pos].map(([k, v]) => [k, { ...v }]));
  it('barely moves anything, and comes to rest with nothing overlapping', () => {
    const unit = meanEdge(edges, copy, start.est.L);
    const r = run(nodes, edges, copy, undefined, unit);
    // in mean link lengths, over every step of the run, not only where it ended
    expect(r.mean).toBeLessThan(0.08);
    expect(r.worst).toBeLessThan(0.15);
    expect((r.worst * unit) / start.est.L).toBeLessThan(0.2);
    expect(overlaps(nodes.map((n) => n.id), r.end, boxes)).toBe(0);
  });
});

describe('what arrives', () => {
  it.each([
    ['one real memory', Object.keys(REAL_SHAPES)[1], 12],
    ['a sparse one', 'two clusters and 80 singletons', 60],
    ['500 records', '500 records with hubs', 80],
  ])('%s: what is there barely moves, and what is new settles around its parent', (_label, key, k) => {
    const { nodes, edges } = ALL[key as string];
    const first = initialLayout(nodes, edges, { seed: 3 });
    const known = run(nodes, edges, first.pos).end;
    const unit = meanEdge(edges, known, first.est.L);
    const degree = new Map<string, number>();
    edges.forEach((e) => { degree.set(e.source, (degree.get(e.source) || 0) + 1); degree.set(e.target, (degree.get(e.target) || 0) + 1); });
    const parent = nodes.slice().sort((a, b) => (degree.get(b.id) || 0) - (degree.get(a.id) || 0))[0].id;
    const add = ids(k as number, 'new').map((id, i) => node(id, 6 + i % 14));
    const all = [...nodes, ...add], allE = [...edges, ...add.map((n) => ({ source: parent, target: n.id }))];
    const start: Pos = new Map([...known, ...arrive(all, allE, known, { seed: 5 })]);
    const held = new Set(nodes.map((n) => n.id));
    const r = run(all, allE, start, held, unit);
    expect(r.mean).toBeLessThan(0.05);
    expect(r.worst).toBeLessThan(0.08);
    expect(overlaps(all.map((n) => n.id), r.end, new Map(all.map((n) => [n.id, n])))).toBe(0);
    const p = r.end.get(parent) as { x: number; y: number };
    const d = add.map((n) => { const q = r.end.get(n.id) as { x: number; y: number }; return Math.hypot(q.x - p.x, q.y - p.y); });
    expect(Math.min(...d)).toBeLessThan(Math.max(unit, first.est.L) * 2.2);
  });
});

describe('a hand and a clock', () => {
  it('a record in someone\'s hand stays there', () => {
    const { nodes, edges } = ALL['two clusters and 80 singletons'];
    const { pos } = initialLayout(nodes, edges);
    const sim = createSim(d3, nodes, edges, pos);
    sim.pin(nodes[0].id, { x: 5000, y: 5000 });
    while (sim.step(4));
    expect(sim.positions().get(nodes[0].id)).toEqual({ x: 5000, y: 5000 });
  });
  it('500 records take few enough milliseconds a step to run every frame', () => {
    const { nodes, edges } = ALL['500 records with hubs'];
    const { pos } = initialLayout(nodes, edges);
    const sim = createSim(d3, nodes, edges, pos);
    const t = Date.now();
    while (sim.step(1));
    expect((Date.now() - t) / sim.ticks()).toBeLessThan(16);
  });
});
