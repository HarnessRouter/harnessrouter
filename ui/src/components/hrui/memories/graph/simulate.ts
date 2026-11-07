// The last step of the layout (rule 4): a force simulation that starts from the arrangement, at a low energy,
// with its rest lengths and repulsion taken from the same estimate the arrangement used. It is there to let the
// graph breathe, not to rearrange it: every record is tied lightly to where it began, and what was already on
// the canvas when new records arrive is tied firmly. It steps on demand, so a canvas can draw every step.
//
// d3-force is loaded when first needed: it is ESM only, and nothing else on the page should pay for it.
import { estimate, resolveOverlaps, seeded, type Box, type Estimate, type LEdge, type LNode, type Pos } from './layout';

export const loadForce = () => import('d3-force');
type D3 = Pick<typeof import('d3-force'), 'forceSimulation' | 'forceLink' | 'forceManyBody' | 'forceX' | 'forceY'>;

export const TUNE = {
  alpha: 0.08, alphaMin: 0.004, alphaDecay: 0.045, velocityDecay: 0.55,
  /** Repulsion, as a share of L²: at this share a link settles within a few percent of its rest length. */
  charge: 0.012, chargeReach: 2.5,
  /** Links, shared out between a record's links as usual. */
  link: 0.25,
  /** How firmly a record is tied to where it began; a record that was already there before new ones arrived. */
  anchor: 0.05, hold: 0.7,
};

interface SNode { id: string; x: number; y: number; vx: number; vy: number; x0: number; y0: number; box: Box; held: boolean; fx?: number | null; fy?: number | null; index?: number }
export interface LiveSim {
  /** One or more steps. False once it has come to rest. */
  step: (n?: number) => boolean;
  positions: () => Pos;
  /** Hold one record where a hand has it, or let it go. */
  pin: (id: string, p: { x: number; y: number } | null) => void;
  /** The final positions: at rest, nothing overlapping. */
  finish: () => Pos;
  ticks: () => number;
}

/** Boxes keep clear of each other: the pair is parted along whichever way is shorter, a held record giving way last. */
function boxCollide(pad: number, strength: number) {
  let nodes: SNode[] = [];
  const force = () => {
    let cell = 1;
    for (const n of nodes) cell = Math.max(cell, n.box.w + pad, n.box.h + pad);
    const grid = new Map<string, SNode[]>();
    for (const n of nodes) {
      const k = `${Math.floor((n.x + n.vx) / cell)}:${Math.floor((n.y + n.vy - n.box.r + n.box.h / 2) / cell)}`;
      const l = grid.get(k);
      if (l) l.push(n); else grid.set(k, [n]);
    }
    const part = (a: SNode, b: SNode) => {
      const ax = a.x + a.vx, ay = a.y + a.vy - a.box.r + a.box.h / 2, bx = b.x + b.vx, by = b.y + b.vy - b.box.r + b.box.h / 2;
      const ox = (a.box.w + b.box.w) / 2 + pad - Math.abs(ax - bx), oy = (a.box.h + b.box.h) / 2 + pad - Math.abs(ay - by);
      if (ox <= 0 || oy <= 0) return;
      const wa = a.held && !b.held ? 0.1 : !a.held && b.held ? 0.9 : 0.5, wb = 1 - wa;
      if (ox < oy) {
        const s = ax < bx ? -1 : 1;
        a.vx += s * ox * wa * strength; b.vx -= s * ox * wb * strength;
      } else {
        const s = ay < by ? -1 : 1;
        a.vy += s * oy * wa * strength; b.vy -= s * oy * wb * strength;
      }
    };
    for (const [k, list] of grid) {
      const [i, j] = k.split(':').map(Number);
      for (let a = 0; a < list.length; a++) for (let b = a + 1; b < list.length; b++) part(list[a], list[b]);
      for (const [di, dj] of [[1, 0], [0, 1], [1, 1], [1, -1]]) {
        const other = grid.get(`${i + di}:${j + dj}`);
        if (other) for (const a of list) for (const b of other) part(a, b);
      }
    }
  };
  force.initialize = (ns: SNode[]) => { nodes = ns; };
  return force;
}

/** A simulation from these positions. `held` is what must barely move: what was on the canvas before new records arrived. */
export function createSim(d3: D3, list: LNode[], edges: LEdge[], start: Pos, o: { held?: Set<string>; est?: Estimate; seed?: number } = {}): LiveSim {
  const est = o.est || estimate(list);
  const held = o.held || new Set<string>();
  const nodes: SNode[] = list.map((n) => {
    const p = start.get(n.id) || { x: 0, y: 0 };
    return { id: n.id, x: p.x, y: p.y, vx: 0, vy: 0, x0: p.x, y0: p.y, box: n, held: held.has(n.id) };
  });
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const degree = new Map<string, number>();
  const links = edges.filter((e) => e.source !== e.target && byId.has(e.source) && byId.has(e.target)).map((e) => {
    degree.set(e.source, (degree.get(e.source) || 0) + 1);
    degree.set(e.target, (degree.get(e.target) || 0) + 1);
    const a = byId.get(e.source) as SNode, b = byId.get(e.target) as SNode;
    // A link that starts longer than the estimate (a far ring, a link across the circle) rests about where it is:
    // pulling it to L would undo the arrangement. Only one that starts short is drawn out to it.
    const rest = Math.max(est.L, Math.hypot(a.x - b.x, a.y - b.y));
    return { source: e.source, target: e.target, rest };
  });
  const sim = d3.forceSimulation<SNode>(nodes)
    .randomSource(seeded(o.seed ?? 1))
    .alpha(TUNE.alpha).alphaMin(TUNE.alphaMin).alphaDecay(TUNE.alphaDecay).velocityDecay(TUNE.velocityDecay)
    .force('link', d3.forceLink<SNode, { source: string; target: string; rest: number }>(links).id((n) => n.id).distance((l) => l.rest)
      .strength((l) => TUNE.link / Math.max(1, Math.min(degree.get(String((l.source as unknown as SNode).id ?? l.source)) || 1, degree.get(String((l.target as unknown as SNode).id ?? l.target)) || 1))))
    .force('charge', d3.forceManyBody<SNode>().strength(-TUNE.charge * est.L * est.L).distanceMax(est.L * TUNE.chargeReach).theta(0.9))
    .force('anchorX', d3.forceX<SNode>((n) => n.x0).strength((n) => (n.held ? TUNE.hold : TUNE.anchor)))
    .force('anchorY', d3.forceY<SNode>((n) => n.y0).strength((n) => (n.held ? TUNE.hold : TUNE.anchor)))
    .force('box', boxCollide(est.pad, 0.5) as never)
    .stop();
  let count = 0;
  const positions = (): Pos => new Map(nodes.map((n) => [n.id, { x: n.x, y: n.y }]));
  return {
    step: (n = 1) => {
      for (let i = 0; i < n; i++) {
        if (sim.alpha() < TUNE.alphaMin) return false;
        sim.tick();
        count += 1;
      }
      return sim.alpha() >= TUNE.alphaMin;
    },
    positions,
    pin: (id, p) => { const n = byId.get(id); if (n) { n.fx = p ? p.x : null; n.fy = p ? p.y : null; } },
    finish: () => {
      const pos = positions();
      resolveOverlaps(list.map((n) => n.id), pos, new Map(list.map((n) => [n.id, n])), { pad: est.pad, held });
      return pos;
    },
    ticks: () => count,
  };
}
