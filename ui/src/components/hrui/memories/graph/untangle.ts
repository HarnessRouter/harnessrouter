// Nothing on anything else, in a schema's drawing (the Schema tab and a memory's cover): a link never passes under a type
// it doesn't join, and a link's name never sits on a type, a type's name or another link's name. Where the straight line
// would, the link bows to one side, as little as it takes (cytoscape's unbundled bezier, its one control point
// `control-point-distances` from the middle, along the left-hand normal of source to target, which puts the curve's
// middle, and its name, half that far out). Types stay where they were put: two a person set on top of each other stay
// so, and are counted as a clash, which the cover reads to stop drawing larger.
//
// Sizes are the canvas stylesheet's (CytoscapeCanvas.jsx) at `k` times, as the tab and the cover draw them.
export interface UNode { id: string; x: number; y: number; caption: string }
export interface UEdge { id: string; source: string; target: string; caption: string }
export interface USizes { r: number; font: number; nodeText: number; edgeText: number }
export const sizesAt = (k: number): USizes => ({ r: 19 * k, font: 10 * k, nodeText: 140 * k, edgeText: 120 * k });

interface Box { x0: number; y0: number; x1: number; y1: number }
const hit = (a: Box, b: Box) => a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;
function hitsDisc(b: Box, cx: number, cy: number, r: number): boolean {
  const x = Math.max(b.x0, Math.min(cx, b.x1)), y = Math.max(b.y0, Math.min(cy, b.y1));
  return (x - cx) ** 2 + (y - cy) ** 2 < r * r;
}
// text widths as the canvas sets them (its system sans, weight 600 for a type's name, 500 for a link's)
const NODE_CHAR = 0.6, EDGE_CHAR = 0.56;

/** A type's name under it: as wide as its longest line (wrapped at its widest), with its soft background around it. */
function nameBox(n: UNode, s: USizes): Box | null {
  const lines = n.caption.split('\n').filter(Boolean);
  if (!lines.length) return null;
  const w = Math.min(Math.max(...lines.map((l) => l.length)) * s.font * NODE_CHAR, s.nodeText) + 8;
  const rows = lines.reduce((t, l) => t + Math.max(1, Math.ceil((l.length * s.font * NODE_CHAR) / s.nodeText)), 0);
  const top = n.y + s.r + 6 - 4;       // the stylesheet's 6 below the disc, less the name's background
  return { x0: n.x - w / 2, y0: top, x1: n.x + w / 2, y1: top + rows * s.font * 1.25 + 8 };
}

/** The middle of a link bowed by `d`, its direction there, and points along it. */
function along(a: UNode, b: UNode, d: number) {
  const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1;
  const nx = -dy / len, ny = dx / len;
  const cx = (a.x + b.x) / 2 + nx * d, cy = (a.y + b.y) / 2 + ny * d;
  const pts: [number, number][] = [];
  for (let i = 0; i <= 24; i++) {
    const t = i / 24, u = 1 - t;
    pts.push([u * u * a.x + 2 * u * t * cx + t * t * b.x, u * u * a.y + 2 * u * t * cy + t * t * b.y]);
  }
  const mid = pts[12];
  // the tangent at the middle of a quadratic bezier runs from start to end, whatever the bow
  return { mid, angle: Math.atan2(dy, dx), pts, len };
}

/** A link's name, turned along it as the canvas turns it: its middle, its half length and height, and its direction. */
interface Turned { cx: number; cy: number; hw: number; hh: number; ux: number; uy: number }
function linkName(e: UEdge, mid: [number, number], angle: number, s: USizes): Turned | null {
  if (!e.caption) return null;
  const w = Math.min(e.caption.length * s.font * EDGE_CHAR, s.edgeText) + 6, h = s.font + 6;
  return { cx: mid[0], cy: mid[1], hw: w / 2, hh: h / 2, ux: Math.cos(angle), uy: Math.sin(angle) };
}
/** The corners of a name turned along its link. */
const corners = (t: Turned): [number, number][] => [[1, 1], [1, -1], [-1, -1], [-1, 1]].map(([a, b]) => [
  t.cx + a * t.hw * t.ux - b * t.hh * t.uy, t.cy + a * t.hw * t.uy + b * t.hh * t.ux] as [number, number]);
const boxCorners = (b: Box): [number, number][] => [[b.x0, b.y0], [b.x1, b.y0], [b.x1, b.y1], [b.x0, b.y1]];
/** Two convex shapes overlap unless one of their sides' directions separates them (the separating axis test). */
function apart(p: [number, number][], q: [number, number][], axes: [number, number][]): boolean {
  return axes.some(([ax, ay]) => {
    const pr = p.map(([x, y]) => x * ax + y * ay), qr = q.map(([x, y]) => x * ax + y * ay);
    return Math.max(...pr) <= Math.min(...qr) || Math.max(...qr) <= Math.min(...pr);
  });
}
const axesOf = (t: Turned): [number, number][] => [[t.ux, t.uy], [-t.uy, t.ux]];
const nameOnBox = (t: Turned, b: Box) => !apart(corners(t), boxCorners(b), [[1, 0], [0, 1], ...axesOf(t)]);
const nameOnName = (t: Turned, o: Turned) => !apart(corners(t), corners(o), [...axesOf(t), ...axesOf(o)]);
function nameOnDisc(t: Turned, x: number, y: number, r: number): boolean {
  const dx = x - t.cx, dy = y - t.cy;
  const lx = dx * t.ux + dy * t.uy, ly = -dx * t.uy + dy * t.ux;
  const qx = Math.max(-t.hw, Math.min(lx, t.hw)), qy = Math.max(-t.hh, Math.min(ly, t.hh));
  return (lx - qx) ** 2 + (ly - qy) ** 2 < r * r;
}

/** How far each link bows (absent: straight), and how many clashes no bow could clear (types on each other, names on
 *  types, a link nothing could route clear). Links between the same two types more than once, and a type's link to
 *  itself, are the canvas's to curve, and are left as they are. */
export function untangle(nodes: UNode[], edges: UEdge[], s: USizes): { bows: Map<string, number>; clashes: number } {
  const at = new Map(nodes.map((n) => [n.id, n]));
  const names = new Map(nodes.map((n) => [n.id, nameBox(n, s)]));
  let clashes = 0;
  // types on types, and a type's name on another type or its name: nothing here moves a type, so these are counted
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i], b = nodes[j], na = names.get(a.id), nb = names.get(b.id);
      if (Math.hypot(a.x - b.x, a.y - b.y) < 2 * s.r + 4) clashes++;
      else if ((na && hitsDisc(na, b.x, b.y, s.r)) || (nb && hitsDisc(nb, a.x, a.y, s.r)) || (na && nb && hit(na, nb))) clashes++;
    }
  }
  const pair = (e: UEdge) => [e.source, e.target].sort().join('\u0000');
  const many = new Map<string, number>();
  for (const e of edges) many.set(pair(e), (many.get(pair(e)) || 0) + 1);
  const placed: Turned[] = [];
  const bows = new Map<string, number>();
  const step = s.r;
  for (const e of edges) {
    const a = at.get(e.source), b = at.get(e.target);
    if (!a || !b || e.source === e.target || (many.get(pair(e)) || 0) > 1) continue;
    const cost = (d: number) => {
      const g = along(a, b, d);
      let n = 0;
      for (const o of nodes) {
        if (o.id === a.id || o.id === b.id) continue;
        // under a type it doesn't join: any point of the line inside its disc
        if (g.pts.some(([x, y]) => Math.hypot(x - o.x, y - o.y) < s.r + 2)) n++;
      }
      const box = linkName(e, g.mid, g.angle, s);
      if (box) {
        for (const o of nodes) {
          if (nameOnDisc(box, o.x, o.y, s.r + 1)) n++;
          const nb = names.get(o.id);
          if (nb && nameOnBox(box, nb)) n++;
        }
        for (const p of placed) if (nameOnName(box, p)) n++;
      }
      return { n, box };
    };
    let best = { d: 0, ...cost(0) };
    for (let i = 1; best.n && i <= 8; i++) {
      for (const d of [i * step, -i * step]) {
        const c = cost(d);
        if (c.n < best.n) best = { d, ...c };
        if (!best.n) break;
      }
    }
    if (best.d) bows.set(e.id, best.d);
    clashes += best.n;
    if (best.box) placed.push(best.box);
  }
  return { bows, clashes };
}

interface CyLike {
  nodes(): { map<T>(f: (n: CyEle) => T): T[] };
  edges(): { map<T>(f: (e: CyEle) => T): T[]; forEach(f: (e: CyEle) => void): void };
  batch(f: () => void): void;
}
interface CyEle { id(): string; position(): { x: number; y: number }; data(k: string): unknown; style(o: Record<string, unknown>): void; removeStyle(names: string): void }
/** Bow the canvas's links as `untangle` says, at the size it is drawn (`k`); answers the clashes left. */
export function untangleCanvas(cy: CyLike, k: number): number {
  const nodes = cy.nodes().map((n) => ({ id: n.id(), ...n.position(), caption: String(n.data('caption') || '') }));
  const edges = cy.edges().map((e) => ({ id: e.id(), source: String(e.data('source')), target: String(e.data('target')), caption: String(e.data('caption') || '') }));
  const { bows, clashes } = untangle(nodes, edges, sizesAt(k));
  cy.batch(() => cy.edges().forEach((e) => {
    const d = bows.get(e.id());
    if (d) e.style({ 'curve-style': 'unbundled-bezier', 'control-point-distances': d, 'control-point-weights': 0.5 });
    else e.removeStyle('curve-style control-point-distances control-point-weights');
  }));
  return clashes;
}
