// Where a memory's records go on the graph, by the rule Richard set out, as plain functions of the graph so
// they can be tested and measured away from a canvas.
//
// 1. Find the connected components.
// 2. In each, the record with the most links is the centre. Its neighbours go around it. Each further layer goes
//    in the average direction, from the centre, of the records it links to in the layer before; where those
//    cancel out, a random direction. Layers that outgrow their ring carry on to another ring.
// 3. Each component is then a circle, and the circles are packed: biggest in the middle, the rest tangent around.
// 4. A force simulation (simulate.ts) then lets it breathe, from a low energy and with rest lengths and repulsion
//    taken from the same estimate, so nothing moves far.
// 5. New records arrive on rings around what they link to; a new component finds a free place by the same circles.
//
// Nothing here needs a browser, a canvas or a library. Same input, same seed, same answer.

export interface Pt { x: number; y: number }
/** What a record takes up: a disc of radius r, and the disc with its name below it, w wide and h tall from the disc's top. */
export interface Box { r: number; w: number; h: number }
export interface LNode extends Box { id: string }
export interface LEdge { source: string; target: string }
export type Pos = Map<string, Pt>;
export interface Estimate {
  /** The rest length of a link, and the distance from a record to the ring of its neighbours. */
  L: number;
  /** Centre to centre along a ring, so neighbours on it stay clear of each other. */
  sep: number;
  /** From one ring to the next, where a layer takes more than one: a typical box's full width, since at the sides of a ring its records sit side by side. */
  gap: number;
  /** Clear space kept between two boxes. */
  pad: number;
}

/** Room for names to grow this much as the graph is zoomed out, so they never come to overlap. */
export const LABEL_RESERVE = 1.3;
const CHAR = 5.7, WRAP = 132, LINE = 12.5;

/** What a record with this name takes up on the canvas, at the canvas's own label size. */
export function footprint(caption: string, size = 38): Box {
  let lines = 0, widest = 0;
  for (const part of String(caption || '').split('\n')) {
    const w = part.length * CHAR;
    lines += Math.max(1, Math.ceil(w / WRAP));
    widest = Math.max(widest, Math.min(w, 140));
  }
  return { r: size / 2, w: Math.max(size, (widest + 8) * LABEL_RESERVE), h: size + 6 + (lines * LINE + 8) * LABEL_RESERVE };
}

/** Distances for this graph, from the size of what is in it. A link's rest length is what keeps two typical
 *  records clear of each other with a little air, which is also where repulsion and a link balance. */
export function estimate(nodes: Box[]): Estimate {
  const n = Math.max(1, nodes.length);
  const w = nodes.reduce((s, b) => s + b.w, 0) / n || 60, h = nodes.reduce((s, b) => s + b.h, 0) / n || 60;
  const pad = 6;
  const sep = 0.65 * w + 0.35 * h + pad;
  return { L: Math.max(90, ((w + h) / 2 + pad) * 1.2), sep, gap: w + pad, pad };
}

/** A small seeded generator, so a random direction is the same one every time for the same graph. */
export function seeded(seed = 1): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function adjacency(ids: string[], edges: LEdge[]): Map<string, Set<string>> {
  const adj = new Map<string, Set<string>>(ids.map((i) => [i, new Set<string>()]));
  for (const e of edges) {
    if (e.source === e.target) continue;
    const a = adj.get(e.source), b = adj.get(e.target);
    if (a && b) { a.add(e.target); b.add(e.source); }
  }
  return adj;
}

/** The connected components, each in the order its records were given. */
export function components(ids: string[], edges: LEdge[]): string[][] {
  const adj = adjacency(ids, edges);
  const seen = new Set<string>();
  const out: string[][] = [];
  for (const id of ids) {
    if (seen.has(id)) continue;
    const comp: string[] = [];
    const stack = [id];
    seen.add(id);
    while (stack.length) {
      const c = stack.pop() as string;
      comp.push(c);
      for (const o of adj.get(c) || []) if (!seen.has(o)) { seen.add(o); stack.push(o); }
    }
    const order = new Map(ids.map((x, i) => [x, i]));
    out.push(comp.sort((a, b) => (order.get(a) as number) - (order.get(b) as number)));
  }
  return out;
}

function farthest(from: string, adj: Map<string, Set<string>>): { far: string; prev: Map<string, string> } {
  const prev = new Map<string, string>([[from, from]]);
  const q = [from];
  let far = from;
  for (let i = 0; i < q.length; i++) {
    far = q[i];
    for (const o of adj.get(far) || []) if (!prev.has(o)) { prev.set(o, far); q.push(o); }
  }
  return { far, prev };
}

/** The record with the most links. Between equals, the one in the middle of the longest path, which is what
 *  makes a chain grow both ways from its middle. */
export function centerOf(comp: string[], adj: Map<string, Set<string>>): string {
  let most = -1;
  for (const id of comp) most = Math.max(most, (adj.get(id) as Set<string>).size);
  const best = comp.filter((id) => (adj.get(id) as Set<string>).size === most);
  if (best.length === 1) return best[0];
  const a = farthest(best[0], adj).far;
  const { far: b, prev } = farthest(a, adj);
  const path = [b];
  for (let c = b; c !== a; c = prev.get(c) as string) path.push(prev.get(c) as string);
  const inBest = new Set(best);
  for (let d = 0; d <= path.length; d++) {
    const i = Math.floor(path.length / 2);
    if (path[i + d] && inBest.has(path[i + d])) return path[i + d];
    if (path[i - d] && inBest.has(path[i - d])) return path[i - d];
  }
  return best[0];
}

/** Neighbours in an order that keeps those sharing further links side by side, so what they share can sit between them. */
function ringOrder(first: string[], adj: Map<string, Set<string>>): string[] {
  if (first.length <= 2 || first.length > 64) return first;
  const shared = (a: string, b: string) => {
    const A = adj.get(a) as Set<string>, B = adj.get(b) as Set<string>;
    let n = A.has(b) ? 2 : 0;
    for (const x of A) if (B.has(x)) n += 1;
    return n;
  };
  const left = new Set(first);
  const start = first.reduce((m, x) => ((adj.get(x) as Set<string>).size > (adj.get(m) as Set<string>).size ? x : m), first[0]);
  const out = [start];
  left.delete(start);
  while (left.size) {
    const cur = out[out.length - 1];
    let best = '', score = -1;
    for (const x of left) { const s = shared(cur, x); if (s > score) { score = s; best = x; } }
    out.push(best);
    left.delete(best);
  }
  return out;
}

const TWO_PI = Math.PI * 2;

/** Angles as near as possible to those wanted, at least `gap` apart around the circle. */
export function spreadAngles(wanted: number[], gap: number): number[] {
  const n = wanted.length;
  if (n <= 1) return wanted.slice();
  const g = Math.min(gap, TWO_PI / n);
  const norm = wanted.map((a) => ((a % TWO_PI) + TWO_PI) % TWO_PI);
  const order = norm.map((_, i) => i).sort((a, b) => norm[a] - norm[b]);
  // cut the circle at its widest gap, and lay the angles out from there
  let cut = 0, widest = -1;
  for (let i = 0; i < n; i++) {
    const here = norm[order[i]], next = i === n - 1 ? norm[order[0]] + TWO_PI : norm[order[i + 1]];
    if (next - here > widest) { widest = next - here; cut = (i + 1) % n; }
  }
  const seq = Array.from({ length: n }, (_, i) => order[(cut + i) % n]);
  const base = norm[seq[0]];
  const want = seq.map((i) => { const a = norm[i]; return a < base ? a + TWO_PI : a; });
  const got = want.slice();
  for (let i = 1; i < n; i++) got[i] = Math.max(got[i], got[i - 1] + g);
  // pushing only forward drifts everything one way: share it out
  const drift = got.reduce((s, a, i) => s + (a - want[i]), 0) / n;
  const out = new Array<number>(n);
  seq.forEach((orig, i) => { out[orig] = got[i] - drift; });
  return out;
}

interface Ring { R: number; take: number }
/** The rings a layer of n records needs, from radius R0 outward. */
function ringsFor(n: number, R0: number, est: Estimate): Ring[] {
  const out: Ring[] = [];
  let left = n, R = R0;
  // A few more than the ring holds: a slightly wider ring, rather than a second one for the last two.
  const oneRing = (n * est.sep) / TWO_PI;
  if (oneRing > R0 && oneRing < R0 + est.gap * 0.75) R = oneRing;
  while (left > 0) {
    const cap = Math.max(1, Math.floor((TWO_PI * R) / est.sep));
    const take = Math.min(cap, left);
    out.push({ R, take });
    left -= take;
    R += est.gap;
  }
  return out;
}

/** Records with the directions they want, onto rings: spread evenly between the rings along the circle, so no
 *  ring takes one side, and each kept as near its direction as its ring allows. Returns the outermost radius. */
function placeLayer(items: { id: string; theta: number }[], R0: number, est: Estimate, pos: Pos): number {
  const n = items.length;
  if (!n) return R0;
  const sorted = items.slice().sort((a, b) => a.theta - b.theta);
  const rings = ringsFor(n, R0, est);
  const given = rings.map(() => [] as { id: string; theta: number }[]);
  sorted.forEach((it, i) => {
    let best = 0, lack = -Infinity;
    rings.forEach((r, j) => {
      const d = (r.take * (i + 1)) / n - given[j].length;
      if (given[j].length < r.take && d > lack) { lack = d; best = j; }
    });
    given[best].push(it);
  });
  rings.forEach((r, j) => {
    const list = given[j];
    const angles = spreadAngles(list.map((x) => x.theta), est.sep / r.R);
    list.forEach((it, i) => pos.set(it.id, { x: r.R * Math.cos(angles[i]), y: r.R * Math.sin(angles[i]) }));
  });
  return rings[rings.length - 1].R;
}

export interface Rect { x0: number; y0: number; x1: number; y1: number }
export const rectOf = (p: Pt, b: Box, pad = 0): Rect => ({ x0: p.x - b.w / 2 - pad, x1: p.x + b.w / 2 + pad, y0: p.y - b.r - pad, y1: p.y - b.r + b.h + pad });
const hit = (a: Rect, b: Rect) => a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;

/** Pairs of records close enough to overlap, found through a grid: every box fits a cell, so a pair that touches
 *  has its centres in neighbouring cells. */
export function closePairs(ids: string[], pos: Pos, boxes: Map<string, Box>, pad: number): [string, string][] {
  let cell = 1;
  for (const id of ids) { const b = boxes.get(id) as Box; cell = Math.max(cell, b.w + pad * 2, b.h + pad * 2); }
  const grid = new Map<string, string[]>();
  const keyOf = (i: number, j: number) => `${i}:${j}`;
  const mid = (id: string): Pt => { const b = boxes.get(id) as Box, p = pos.get(id) as Pt; return { x: p.x, y: p.y - b.r + b.h / 2 }; };
  for (const id of ids) {
    if (!pos.has(id)) continue;
    const m = mid(id), k = keyOf(Math.floor(m.x / cell), Math.floor(m.y / cell));
    const l = grid.get(k);
    if (l) l.push(id); else grid.set(k, [id]);
  }
  const out: [string, string][] = [];
  for (const [k, list] of grid) {
    const [i, j] = k.split(':').map(Number);
    for (let a = 0; a < list.length; a++) for (let b = a + 1; b < list.length; b++) out.push([list[a], list[b]]);
    for (const [di, dj] of [[1, 0], [0, 1], [1, 1], [1, -1]]) {
      const other = grid.get(keyOf(i + di, j + dj));
      if (other) for (const a of list) for (const b of other) out.push([a, b]);
    }
  }
  return out;
}

/** How many pairs of records overlap, discs and names both. */
export function overlaps(ids: string[], pos: Pos, boxes: Map<string, Box>, pad = 0): number {
  let n = 0;
  for (const [a, b] of closePairs(ids, pos, boxes, pad)) {
    if (hit(rectOf(pos.get(a) as Pt, boxes.get(a) as Box, pad / 2), rectOf(pos.get(b) as Pt, boxes.get(b) as Box, pad / 2))) n += 1;
  }
  return n;
}

/** Part overlapping records by the least movement that does it. A record in `held` stays put. */
export function resolveOverlaps(ids: string[], pos: Pos, boxes: Map<string, Box>, o: { pad?: number; held?: Set<string>; rounds?: number } = {}): number {
  const pad = o.pad ?? 6, held = o.held;
  for (let round = 0; round < (o.rounds ?? 800); round++) {
    let moved = 0;
    for (const [a, b] of closePairs(ids, pos, boxes, pad)) {
      const pa = pos.get(a) as Pt, pb = pos.get(b) as Pt;
      const ra = rectOf(pa, boxes.get(a) as Box, pad / 2), rb = rectOf(pb, boxes.get(b) as Box, pad / 2);
      if (!hit(ra, rb)) continue;
      const ox = Math.min(ra.x1, rb.x1) - Math.max(ra.x0, rb.x0), oy = Math.min(ra.y1, rb.y1) - Math.max(ra.y0, rb.y0);
      const ha = held?.has(a), hb = held?.has(b);
      if (ha && hb) continue;
      const wa = ha ? 0 : hb ? 1 : 0.5, wb = hb ? 0 : ha ? 1 : 0.5;
      if (ox < oy) {
        const s = pa.x < pb.x || (pa.x === pb.x && a < b) ? -1 : 1;
        pa.x += s * (ox + 0.5) * wa; pb.x -= s * (ox + 0.5) * wb;
      } else {
        const s = pa.y < pb.y || (pa.y === pb.y && a < b) ? -1 : 1;
        pa.y += s * (oy + 0.5) * wa; pb.y -= s * (oy + 0.5) * wb;
      }
      moved += 1;
    }
    if (!moved) return round;
  }
  return -1;
}

interface Placed { ids: string[]; local: Pos; radius: number }

/** One component, around its centre: rules 1 and 2. Its positions are relative to the middle of its circle. */
export function placeComponent(comp: string[], adj: Map<string, Set<string>>, boxes: Map<string, Box>, est: Estimate, rng: () => number): Placed {
  const local: Pos = new Map();
  const center = centerOf(comp, adj);
  local.set(center, { x: 0, y: 0 });
  const depth = new Map<string, number>([[center, 0]]);
  let layer = [center];
  let outer = 0;
  while (layer.length) {
    const next: string[] = [];
    for (const id of layer) for (const o of adj.get(id) as Set<string>) if (!depth.has(o)) { depth.set(o, (depth.get(id) as number) + 1); next.push(o); }
    if (!next.length) break;
    const d = depth.get(next[0]) as number;
    let items: { id: string; theta: number }[];
    if (d === 1) {
      const order = ringOrder(next, adj);
      // A record's name hangs below it, so no spoke runs straight down through the centre's name: an odd number
      // starts from straight up, and an even one from half a step round. Two would then lie level, with their names
      // side by side along the link, so they slant.
      const start = order.length === 2 ? -Math.PI / 6 : -Math.PI / 2 + (order.length % 2 ? 0 : Math.PI / order.length);
      items = order.map((id, i) => ({ id, theta: start + (i * TWO_PI) / order.length }));
    } else {
      items = next.map((id) => {
        let dx = 0, dy = 0;
        for (const p of adj.get(id) as Set<string>) {
          if (depth.get(p) !== d - 1) continue;
          const q = local.get(p) as Pt, len = Math.hypot(q.x, q.y) || 1;
          dx += q.x / len; dy += q.y / len;
        }
        const len = Math.hypot(dx, dy);
        return { id, theta: len < 0.05 ? rng() * TWO_PI : Math.atan2(dy, dx) };
      });
    }
    outer = placeLayer(items, outer + est.L, est, local);
    layer = next;
  }
  resolveOverlaps(comp, local, boxes, { pad: est.pad });
  // the circle it now takes up
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  for (const id of comp) { const r = rectOf(local.get(id) as Pt, boxes.get(id) as Box); x0 = Math.min(x0, r.x0); x1 = Math.max(x1, r.x1); y0 = Math.min(y0, r.y0); y1 = Math.max(y1, r.y1); }
  const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
  let radius = 0;
  for (const id of comp) {
    const p = local.get(id) as Pt;
    p.x -= cx; p.y -= cy;
    const r = rectOf(p, boxes.get(id) as Box);
    radius = Math.max(radius, Math.hypot(Math.max(Math.abs(r.x0), Math.abs(r.x1)), Math.max(Math.abs(r.y0), Math.abs(r.y1))));
  }
  return { ids: comp, local, radius };
}

// Pack circles so the LARGEST is centered and the rest are tangent-packed around it (d3-pack-style front chain):
// each new circle is placed tangent to two front circles at the candidate nearest the global center that overlaps
// nothing. Input: radii. Output: {x,y} centers, SAME order, no overlap (a GAP is kept between circles).
// The original canvas's function, as it is.
export function packCircles(radii: number[], gap = 14): Pt[] {
  const GAP = gap;
  const n = radii.length;
  if (n === 0) return [];
  const HG = GAP / 2;
  const order = radii.map((_, i) => i).sort((a, b) => radii[b] - radii[a]);
  const centers = new Array<Pt>(n);
  if (n === 1) { centers[order[0]] = { x: 0, y: 0 }; return centers; }
  interface Disc { i: number; x: number; y: number; er: number }
  const placed: Disc[] = [];
  const node = (oi: number, x: number, y: number): Disc => ({ i: order[oi], x, y, er: radii[order[oi]] + HG });
  function overlapsAny(x: number, y: number, er: number, skipA: number, skipB: number) {
    for (let k = 0; k < placed.length; k++) {
      if (k === skipA || k === skipB) continue;
      const p = placed[k];
      const need = er + p.er, dx = x - p.x, dy = y - p.y;
      if (dx * dx + dy * dy < need * need - 1e-6) return true;
    }
    return false;
  }
  function tangentTo(A: Disc, B: Disc, er: number) {
    const rA = A.er + er, rB = B.er + er;
    const dx = B.x - A.x, dy = B.y - A.y, d = Math.hypot(dx, dy);
    if (d < 1e-9 || d > rA + rB + 1e-9 || d < Math.abs(rA - rB) - 1e-9) return null;
    const a = (rA * rA - rB * rB + d * d) / (2 * d);
    const h = Math.sqrt(Math.max(0, rA * rA - a * a));
    const mx = A.x + (a * dx) / d, my = A.y + (a * dy) / d;
    const ox = (-dy / d) * h, oy = (dx / d) * h;
    const c1 = { x: mx + ox, y: my + oy }, c2 = { x: mx - ox, y: my - oy };
    return (c1.x * c1.x + c1.y * c1.y) <= (c2.x * c2.x + c2.y * c2.y) ? [c1, c2] : [c2, c1];
  }
  const c0 = node(0, 0, 0); placed.push(c0);
  placed.push(node(1, c0.er + (radii[order[1]] + HG), 0));
  let front = [0, 1];
  if (n >= 3) {
    const er2 = radii[order[2]] + HG;
    const t = tangentTo(placed[0], placed[1], er2);
    const c = t ? t[0] : { x: 0, y: c0.er + er2 };
    placed.push(node(2, c.x, c.y)); front = [0, 2, 1];
  }
  function spiralPlace(er: number) {
    let maxR = 0;
    for (const p of placed) maxR = Math.max(maxR, Math.hypot(p.x, p.y) + p.er);
    const baseR = maxR + er, stepPerTurn = Math.max(er, 4);
    for (let ang = 0; ang < 400000; ang += 0.12) {
      const rad = baseR + (ang / (2 * Math.PI)) * stepPerTurn * 0.5;
      const x = Math.cos(ang) * rad, y = Math.sin(ang) * rad;
      if (!overlapsAny(x, y, er, -1, -1)) return { x, y };
    }
    return { x: baseR + er * 3, y: 0 };
  }
  for (let oi = 3; oi < n; oi++) {
    const er = radii[order[oi]] + HG;
    let best: { x: number; y: number; m?: number; score?: number } | null = null;
    for (let m = 0; m < front.length; m++) {
      const ia = front[m], ib = front[(m + 1) % front.length];
      const cand = tangentTo(placed[ia], placed[ib], er);
      if (!cand) continue;
      for (const c of cand) {
        if (overlapsAny(c.x, c.y, er, ia, ib)) continue;
        const score = c.x * c.x + c.y * c.y;
        if (!best || score < (best.score as number)) best = { x: c.x, y: c.y, m, score };
      }
    }
    if (!best) best = { ...spiralPlace(er), m: undefined };
    const newIdx = placed.length;
    placed.push(node(oi, best.x, best.y));
    if (best.m === undefined) front.push(newIdx);
    else front.splice((best.m as number) + 1, 0, newIdx);
  }
  for (const p of placed) centers[p.i] = { x: p.x, y: p.y };
  return centers;
}

const boxMap = (nodes: LNode[]) => new Map<string, Box>(nodes.map((n) => [n.id, n]));

/** The whole arrangement: rules 1 to 3. */
export function initialLayout(nodes: LNode[], edges: LEdge[], o: { seed?: number; est?: Estimate; spread?: number } = {}): { pos: Pos; est: Estimate; circles: { ids: string[]; x: number; y: number; r: number }[] } {
  const base = o.est || estimate(nodes);
  // `spread` for a drawing whose links carry their names along them, which need the room
  const est = o.spread ? { ...base, L: base.L * o.spread } : base;
  const ids = nodes.map((n) => n.id), boxes = boxMap(nodes), rng = seeded(o.seed ?? 1);
  const adj = adjacency(ids, edges);
  const placed = components(ids, edges).map((c) => placeComponent(c, adj, boxes, est, rng));
  const centers = packCircles(placed.map((p) => p.radius), est.pad * 2);
  const pos: Pos = new Map();
  const circles = placed.map((p, i) => {
    const c = centers[i];
    for (const id of p.ids) { const q = p.local.get(id) as Pt; pos.set(id, { x: q.x + c.x, y: q.y + c.y }); }
    return { ids: p.ids, x: c.x, y: c.y, r: p.radius };
  });
  return { pos, est, circles };
}

/** The mean length of the links between records that have a place. */
export function meanEdge(edges: LEdge[], pos: Pos, or = 120): number {
  let sum = 0, n = 0;
  for (const e of edges) {
    const a = pos.get(e.source), b = pos.get(e.target);
    if (!a || !b || e.source === e.target) continue;
    sum += Math.hypot(a.x - b.x, a.y - b.y); n += 1;
  }
  return n ? sum / n : or;
}

/** How far records moved between two arrangements, in mean link lengths. */
export function displacement(a: Pos, b: Pos, unit: number, only?: Set<string>): { mean: number; worst: number } {
  let sum = 0, n = 0, worst = 0;
  for (const [id, p] of a) {
    if (only && !only.has(id)) continue;
    const q = b.get(id);
    if (!q) continue;
    const d = Math.hypot(p.x - q.x, p.y - q.y);
    sum += d; n += 1; worst = Math.max(worst, d);
  }
  return { mean: n ? sum / n / unit : 0, worst: worst / unit };
}

/** New records on rings around their parent: the ring spacing the graph's mean link length, neighbours on a ring
 *  no closer than that allows, as many rings as they need. A place something already holds is skipped. The first
 *  ring opens away from what is already around the parent, so a few new records land in the free side. */
export function placeAround(parent: string, newIds: string[], pos: Pos, boxes: Map<string, Box>, unit: number, est: Estimate): void {
  const at = pos.get(parent) as Pt;
  const taken: Rect[] = [];
  for (const [id, p] of pos) taken.push(rectOf(p, boxes.get(id) as Box, est.pad / 2));
  let ax = 0, ay = 0;
  for (const [id, p] of pos) {
    if (id === parent) continue;
    const d = Math.hypot(p.x - at.x, p.y - at.y);
    if (d > 0 && d < unit * 2.5) { ax += (p.x - at.x) / d; ay += (p.y - at.y) / d; }
  }
  const outward = ax || ay ? Math.atan2(-ay, -ax) : -Math.PI / 2;
  const left = newIds.slice();
  // A graph with big hubs has long links on its far rings: what arrives stays near its parent all the same.
  const spacing = Math.max(Math.min(unit, est.L * 2), est.sep);
  const neighbour = Math.max(est.sep, spacing * 0.8);
  for (let ring = 1; left.length; ring++) {
    const R = spacing * ring;
    const cap = Math.max(1, Math.floor((TWO_PI * R) / neighbour));
    const count = Math.max(cap, left.length <= cap ? left.length : cap);
    const free: Pt[] = [];
    const box = boxes.get(left[0]) as Box;
    for (let i = 0; i < count; i++) {
      const a = outward + (i * TWO_PI) / count + (ring % 2 ? 0 : Math.PI / count);
      const p = { x: at.x + R * Math.cos(a), y: at.y + R * Math.sin(a) };
      const r = rectOf(p, box, est.pad / 2);
      if (!taken.some((t) => hit(t, r))) free.push(p);
    }
    if (!free.length) continue;
    // as many as this ring can take, evenly around what is free on it, each clear of the ones just placed
    const want = Math.min(free.length, left.length);
    const tried = new Set<number>();
    for (let i = 0; i < want && left.length; i++) {
      const first = Math.floor((i * free.length) / want);
      const id = left[0];
      const b = boxes.get(id) as Box;
      for (let k = 0; k < free.length; k++) {
        const j = (first + k) % free.length;
        if (tried.has(j)) continue;
        const r = rectOf(free[j], b, est.pad / 2);
        tried.add(j);
        if (taken.some((t) => hit(t, r))) continue;
        pos.set(id, { x: free[j].x, y: free[j].y });
        taken.push(r);
        left.shift();
        break;
      }
    }
  }
}

/** A place for a circle of radius r, tangent to a circle already there, as near the middle as is free. */
export function freeSpot(circles: { x: number; y: number; r: number }[], r: number, gap: number): Pt {
  if (!circles.length) return { x: 0, y: 0 };
  const big = circles.reduce((m, c) => (c.r > m.r ? c : m), circles[0]);
  let best: Pt | null = null, score = Infinity;
  for (const c of circles) {
    for (let k = 0; k < 24; k++) {
      const a = (k * TWO_PI) / 24, d = c.r + r + gap;
      const p = { x: c.x + d * Math.cos(a), y: c.y + d * Math.sin(a) };
      if (circles.some((o) => Math.hypot(o.x - p.x, o.y - p.y) < o.r + r + gap - 1e-6)) continue;
      const s = (p.x - big.x) ** 2 + (p.y - big.y) ** 2;
      if (s < score) { score = s; best = p; }
    }
  }
  if (best) return best;
  const far = Math.max(...circles.map((c) => Math.hypot(c.x - big.x, c.y - big.y) + c.r));
  return { x: big.x + far + r + gap, y: big.y };
}

/** Where everything new goes, with what is already there left alone (rule 5, and a refresh): what links to
 *  something there arrives around it, layer by layer, and a new component takes a free place by the circles. */
export function arrive(nodes: LNode[], edges: LEdge[], known: Pos, o: { seed?: number } = {}): Pos {
  const ids = nodes.map((n) => n.id), boxes = boxMap(nodes), est = estimate(nodes), rng = seeded(o.seed ?? 1);
  const adj = adjacency(ids, edges);
  const pos: Pos = new Map();
  for (const id of ids) { const p = known.get(id); if (p) pos.set(id, { x: p.x, y: p.y }); }
  const unit = meanEdge(edges, pos, est.L);
  const out: Pos = new Map();
  const newOnes = new Set(ids.filter((i) => !pos.has(i)));
  let frontier = true;
  while (frontier && newOnes.size) {
    frontier = false;
    const byParent = new Map<string, string[]>();
    for (const id of newOnes) {
      let parent = '', most = -1;
      for (const o2 of adj.get(id) as Set<string>) {
        if (!pos.has(o2)) continue;
        const deg = (adj.get(o2) as Set<string>).size;
        if (deg > most) { most = deg; parent = o2; }
      }
      if (parent) byParent.set(parent, [...(byParent.get(parent) || []), id]);
    }
    for (const [parent, list] of byParent) {
      placeAround(parent, list, pos, boxes, unit, est);
      for (const id of list) { out.set(id, pos.get(id) as Pt); newOnes.delete(id); }
      frontier = true;
    }
  }
  if (newOnes.size) {
    const rest = [...newOnes];
    const circles: { x: number; y: number; r: number }[] = [];
    const knownIds = ids.filter((i) => pos.has(i));
    for (const c of components(knownIds, edges)) {
      let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
      for (const id of c) { const r = rectOf(pos.get(id) as Pt, boxes.get(id) as Box); x0 = Math.min(x0, r.x0); x1 = Math.max(x1, r.x1); y0 = Math.min(y0, r.y0); y1 = Math.max(y1, r.y1); }
      circles.push({ x: (x0 + x1) / 2, y: (y0 + y1) / 2, r: Math.hypot(x1 - x0, y1 - y0) / 2 });
    }
    const placed = components(rest, edges).map((c) => placeComponent(c, adj, boxes, est, rng)).sort((a, b) => b.radius - a.radius);
    for (const p of placed) {
      const at = freeSpot(circles, p.radius, est.pad * 2);
      circles.push({ x: at.x, y: at.y, r: p.radius });
      for (const id of p.ids) {
        const q = p.local.get(id) as Pt, here = { x: q.x + at.x, y: q.y + at.y };
        pos.set(id, here); out.set(id, here);
      }
    }
  }
  return out;
}
