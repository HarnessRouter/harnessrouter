// The design's brick tower (docs/uxuidesign/console-87: isoSvg / agentModel / brickStates), ported line
// for line. "A brick is always a real part of a setup in its real state (empty, next, built, running);
// never decoration": every state below is computed from the setup's own record and its own tasks by
// `towerOf`, never typed in. Four layers: the agent harness, its model, the setup's instructions and
// HarnessRouter, which runs it (its parts drawn as its own bricks); the optional parts a person added
// stand on top.
//
// The drawing is an SVG string, as in the design; the only text in it is the harness and model
// names, escaped.

export type BrickState = 'empty' | 'next' | 'built' | 'run';
export type States = Record<string, BrickState>;

/** How many of each optional part a setup has (0 when none): one brick each on the tower, up to
 *  PART_STACK high; past that the top brick carries the count. */
export type PartCounts = { skill: number; plugin: number; mcp: number; env: number };

export interface Tower {
  harness: string;
  model: string;
  parts: PartCounts;
  st: States;
}

/** the four layers of a tower, bottom first, with the names the Agent stack panel prints */
export const LAYERS = [
  { key: 'b-runtime', name: 'Agent harness', z: 0 }, { key: 'model', name: 'Model', z: 1 }, { key: 'task', name: 'Instructions', z: 2 },
  { key: 'backend', name: 'HarnessRouter', z: 3, h: 2.25 },
] as const;
type Bk = [string, number, number, number, number, number, number];
const BK: Bk[] = [['b-sandbox', 0, 0, 6, 4, 0, 1], ['b-orch', 0, 4, 6, 6, 0, 1],
  ['b-fill', 0, 0, 4, 4, 1, 1.25], ['b-errors', 4, 0, 6, 2, 1, 1.25], ['b-files', 4, 2, 6, 4, 1, 1.25], ['b-sessions', 0, 4, 2, 6, 1, 1.25], ['b-stream', 2, 4, 4, 6, 1, 1.25], ['b-trace', 4, 4, 6, 6, 1, 1.25]];
export const SUBS: [string, string, string][] = [['b-sandbox', 'Sandbox', 'Sandbox'], ['b-orch', 'Orchestration', 'Orchestration'], ['b-sessions', 'Sessions', 'Sessions'], ['b-stream', 'Streaming', 'Streaming'], ['b-trace', 'Trace', 'Trace'], ['b-files', 'Files', 'Files & artifacts'], ['b-errors', 'Errors', 'Cancellation & errors']];
export const PARTS: [keyof Tower['parts'], string][] = [['plugin', 'Plugin'], ['skill', 'Skill'], ['mcp', 'Tool'], ['env', 'Environment']];
const PART_AT: Record<string, [number, number]> = { plugin: [0, 0], skill: [4, 0], mcp: [0, 4], env: [4, 4] };
const FAM: Record<string, string> = { 'b-runtime': 'harness', model: 'model', task: 'task', backend: 'backend', skill: 'skill', plugin: 'plugin', mcp: 'mcp', env: 'tool' };
const ZTOP = 5.25, PART_STACK = 3;

const esc = (s: string) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] as string));
const subName = (k: string) => (SUBS.find((x) => x[0] === k) || [0, 'HarnessRouter'])[1] as string;
const cardFs = (t: string, W: number, u: number) => (W - 0.7) * u / (String(t).length * 0.57);
/** A name too long for its brick is cut at a hyphen or dot and ends with an ellipsis. */
function cardCut(t: string, n: number): string {
  t = String(t); if (t.length <= n) return t;
  const c = t.slice(0, n - 1), i = Math.max(c.lastIndexOf('-'), c.lastIndexOf('.'));
  return (i > n * 0.5 ? c.slice(0, i) : c) + '…';
}
function tierFs(tier: number, u: number): number {
  let f = 0.34 * u;
  BK.forEach((B) => { if (B[0] === 'b-fill' || B[5] !== tier) return; const nm = subName(B[0]); f = Math.min(f, ((B[4] === 6 ? B[3] - B[1] : B[4] - B[2]) - 0.35) * u / (nm.length * 0.58)); });
  return f;
}

function Iso(u: number, zh?: number) {
  const c = 0.866, zH = zh || 0.8, bb = { x0: 1e9, y0: 1e9, x1: -1e9, y1: -1e9 };
  function P(x: number, y: number, z: number): [number, number] {
    const X = (x - y) * c * u, Y = (x + y) * 0.5 * u - z * zH * u;
    if (X < bb.x0) bb.x0 = X; if (X > bb.x1) bb.x1 = X; if (Y < bb.y0) bb.y0 = Y; if (Y > bb.y1) bb.y1 = Y;
    return [X, Y];
  }
  const pts = (a: [number, number][]) => a.map((p) => p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' ');
  const poly = (a: [number, number][], cls: string, extra = '') => '<polygon class="' + cls + '" points="' + pts(a) + '"' + extra + '/>';
  const box = (x0: number, y0: number, z0: number, x1: number, y1: number, z1: number) =>
    poly([P(x0, y0, z1), P(x1, y0, z1), P(x1, y1, z1), P(x0, y1, z1)], 't') + poly([P(x0, y1, z0), P(x1, y1, z0), P(x1, y1, z1), P(x0, y1, z1)], 'l') +
    poly([P(x1, y0, z0), P(x1, y1, z0), P(x1, y1, z1), P(x1, y0, z1)], 'r') + '<polyline class="hl" points="' + pts([P(x0 + 0.06, y1, z1), P(x1, y1, z1), P(x1, y0 + 0.06, z1)]) + '"/>';
  function stud(x: number, y: number, z: number, sc = 1) {
    const p = P(x, y, z), rx = 0.34 * u * sc, ry = 0.2 * u * sc, h = 0.24 * u * (sc > 1 ? 1.35 : 1); P(x, y, z + 0.4 * sc);
    return '<ellipse class="sd" cx="' + p[0].toFixed(1) + '" cy="' + p[1].toFixed(1) + '" rx="' + rx.toFixed(1) + '" ry="' + ry.toFixed(1) + '"/><rect class="sd" x="' + (p[0] - rx).toFixed(1) + '" y="' + (p[1] - h).toFixed(1) + '" width="' + (2 * rx).toFixed(1) + '" height="' + h.toFixed(1) + '"/><ellipse class="su" cx="' + p[0].toFixed(1) + '" cy="' + (p[1] - h).toFixed(1) + '" rx="' + rx.toFixed(1) + '" ry="' + ry.toFixed(1) + '"/><ellipse class="sh" cx="' + (p[0] - 0.13 * u * sc).toFixed(1) + '" cy="' + (p[1] - h - 0.04 * u * sc).toFixed(1) + '" rx="' + (0.11 * u * sc).toFixed(1) + '" ry="' + (0.055 * u * sc).toFixed(1) + '"/>';
  }
  const tile = (x0: number, y0: number, x1: number, y1: number, cls: string) => poly([P(x0, y0, 0), P(x1, y0, 0), P(x1, y1, 0), P(x0, y1, 0)], cls);
  function tree(x: number, y: number, s: number) {
    const t0 = P(x, y, 0), t1 = P(x, y, 0.7 * s), top = P(x, y, 2.6 * s), l = P(x - 0.75 * s, y + 0.75 * s, 0.6 * s), r = P(x + 0.75 * s, y - 0.75 * s, 0.6 * s), m = P(x + 0.15 * s, y + 0.15 * s, 0.45 * s);
    return '<g class="tree"><line class="trunk" x1="' + t0[0].toFixed(1) + '" y1="' + t0[1].toFixed(1) + '" x2="' + t1[0].toFixed(1) + '" y2="' + t1[1].toFixed(1) + '" stroke-width="' + (0.22 * u).toFixed(1) + '"/>' + poly([top, l, m], 'leaf-l') + poly([top, m, r], 'leaf-r') + '</g>';
  }
  function wrap(inner: string, pad: number) {
    const w = bb.x1 - bb.x0 + 2 * pad, h = bb.y1 - bb.y0 + 2 * pad;
    return { w, h, svg: '<g transform="translate(' + (pad - bb.x0).toFixed(1) + ',' + (pad - bb.y0).toFixed(1) + ')">' + inner + '</g>' };
  }
  return { P, poly, box, stud, tile, tree, wrap, c, zH, u };
}

/** `drops`: bricks landing now, each after its own delay in ms (the design's drops: a layer by its
 *  key, HarnessRouter's parts by theirs, an optional part as `part:<key>`); a ripple marks the spot */
type Opts = { text?: boolean; only?: string[] | null; big?: boolean; zones?: boolean; drops?: Drops | null };
export type Drops = Record<string, number>;

function agentModel(K: ReturnType<typeof Iso>, o: Tower, opts: Opts) {
  const st = o.st, W = 6, D = 6, Z = ZTOP, ox = 0, oy = 0, u = K.u, out: string[] = [], drops = opts.drops || {};
  const ripple = (x0: number, y0: number, x1: number, y1: number, z: number, delay: number) =>
    K.poly([K.P(x0, y0, z), K.P(x1, y0, z), K.P(x1, y1, z), K.P(x0, y1, z)], 'ripple', ' style="animation-delay:' + (delay + 380) + 'ms"');
  LAYERS.forEach((L) => {
    const lh = ('h' in L ? L.h : 1) as number, s2 = st[L.key] || 'empty', x0 = ox, x1 = ox + W, y0 = oy, y1 = oy + D, z0 = L.z, z1 = L.z + lh;
    const above = LAYERS.find((A) => Math.abs(A.z - z1) < 1e-6), covered = !!above && (st[above.key] === 'built' || st[above.key] === 'run');
    if (L.key === 'backend') {
      BK.forEach((B) => {
        const k = B[0], s4 = (k === 'b-fill' ? st['b-sessions'] : st[k]) || 'empty', bx0 = ox + B[1], by0 = oy + B[2], bx1 = ox + B[3], by1 = oy + B[4], bz0 = z0 + B[5], bz1 = bz0 + B[6], infra = B[5] === 0;
        let bi = K.box(bx0, by0, bz0, bx1, by1, bz1);
        if (!infra && !covered) for (let sx = B[1] + 1; sx < B[3]; sx += 2) for (let sy = B[2] + 1; sy < B[4]; sy += 2) bi += K.stud(ox + sx, oy + sy, bz1, 2);
        if (opts.text && !opts.only && k !== 'b-fill') {
          const nm2 = subName(k), fs2 = tierFs(B[5], u), ty2 = (K.zH * u * B[6] * 0.5 + fs2 * 0.36).toFixed(1), front = B[4] === 6, q = front ? K.P(bx0, by1, bz1) : K.P(bx1, by1, bz1);
          bi += '<text class="lbl" transform="matrix(' + K.c + ',' + (front ? '0.5' : '-0.5') + ',0,1,' + q[0].toFixed(1) + ',' + q[1].toFixed(1) + ')" x="' + (0.2 * u).toFixed(1) + '" y="' + ty2 + '" font-size="' + fs2.toFixed(1) + '">' + nm2 + '</text>';
        }
        const say = ({ empty: 'add-on, off', built: 'included', run: 'running a task now', next: 'included' } as Record<string, string>)[s4];
        const dkk = k === 'b-fill' ? 'b-sessions' : k, dkb = drops[dkk] != null, dlb = dkb ? drops[dkk] : 0;
        if (dkb) out.push(ripple(bx0, by0, bx1, by1, z0, dlb));
        out.push('<g class="bk f-backend' + (infra ? ' infra' : '') + ' ' + s4 + (dkb ? ' drop' : '') + '" data-tw="backend" style="--z:' + (infra ? 3 : 4) + (dkb ? ';animation-delay:' + dlb + 'ms' : '') + '"><title>' + (k === 'b-fill' ? 'HarnessRouter' : subName(k) + ', run by HarnessRouter') + ': ' + say + '</title>' + bi + '</g>');
      });
      return;
    }
    let inner = K.box(x0, y0, z0, x1, y1, z1);
    if (!covered) for (let xi = 1; xi < W; xi += 2) for (let yi = 1; yi < D; yi += 2) inner += K.stud(ox + xi, oy + yi, z1, 2);
    if (opts.text && (!opts.only || opts.only.includes(L.key))) {
      let lab: string = L.key === 'b-runtime' ? (o.harness || 'Harness') : L.key === 'model' ? (o.model || 'Model') : L.name;
      const fs = opts.big ? Math.min(Math.max(cardFs(lab, W, u), 6.3), K.zH * u * lh * 0.62) : Math.min(0.39 * u, (W - 0.35) * u / (lab.length * 0.58), K.zH * u * lh * 0.62);
      const ty = (K.zH * u * lh * 0.5 + fs * 0.36).toFixed(1), a0 = K.P(x0, y1, z1);
      if (opts.big && cardFs(lab, W, u) < 6.3) lab = cardCut(lab, Math.floor((W - 0.7) * u / (0.57 * 6.3)));
      inner += '<text class="lbl' + (opts.big ? ' lbl-card' : '') + '" transform="matrix(' + K.c + ',0.5,0,1,' + a0[0].toFixed(1) + ',' + a0[1].toFixed(1) + ')" x="' + (opts.big ? W * u / 2 : 0.2 * u).toFixed(1) + '" y="' + ty + '" font-size="' + fs.toFixed(1) + '"' + (opts.big ? ' text-anchor="middle"' : '') + '>' + esc(lab) + '</text>';
    }
    const say = ({ empty: 'not set up', built: 'set up', run: 'running a task now', next: 'next step' } as Record<string, string>)[s2];
    const dk = drops[L.key] != null, delay = dk ? drops[L.key] : 0;
    if (dk) out.push(ripple(x0, y0, x1, y1, z0, delay));
    out.push('<g class="bk f-' + FAM[L.key] + ' ' + s2 + (dk ? ' drop' : '') + '" data-tw="' + L.key + '" style="--z:' + Math.round(L.z) + (dk ? ';animation-delay:' + delay + 'ms' : '') + '"><title>' + esc(L.name) + (L.key === 'b-runtime' && o.harness ? ' · ' + esc(o.harness) : L.key === 'model' && o.model ? ' · ' + esc(o.model) : '') + ': ' + say + '</title>' + inner + '</g>');
  });
  // HarnessRouter is the top layer; the four part slots sit on it, a stud of its own until a part is
  // attached. Every tower keeps room for its four parts stacked to their full height, so towers are
  // drawn at one scale whatever they hold. One brick per item, same colour, up to PART_STACK high;
  // past that the top brick carries the count, printed like the layer names.
  PARTS.forEach(([k, name]) => {
    const px = ox + PART_AT[k][0], py = oy + PART_AT[k][1], HS = PART_STACK;
    K.P(px, py, Z + HS); K.P(px + 2, py, Z + HS); K.P(px, py + 2, Z + HS); K.P(px + 2, py + 2, Z + HS); K.P(px + 1, py + 1, Z + HS + 0.8);
    const n = o.parts[k] || 0;
    if (!n) return;
    const pk = 'part:' + k, dk2 = drops[pk] != null, dl2 = dk2 ? drops[pk] : 0;
    if (dk2) out.push(ripple(px, py, px + 2, py + 2, Z, dl2));
    const h = Math.min(n, PART_STACK);
    let g = '';
    for (let j = 0; j < h; j++) g += K.box(px, py, Z + j, px + 2, py + 2, Z + j + 1);
    g += K.stud(px + 1, py + 1, Z + h, 2);
    if (n > PART_STACK) {
      const fs = 0.5 * u, q = K.P(px, py + 2, Z + h);
      g += '<text class="lbl part-n-lbl" transform="matrix(' + K.c + ',0.5,0,1,' + q[0].toFixed(1) + ',' + q[1].toFixed(1) + ')" x="' + u.toFixed(1) + '" y="' + (K.zH * u * 0.5 + fs * 0.36).toFixed(1) + '" font-size="' + fs.toFixed(1) + '" text-anchor="middle">' + n + '</text>';
    }
    out.push('<g class="bk f-' + FAM[k] + ' ' + (st[k] || 'empty') + (dk2 ? ' drop' : '') + '" data-tw="' + k + '"' + (dk2 ? ' style="animation-delay:' + dl2 + 'ms"' : '') + '><title>' + name + (n === 1 ? '' : 's') + ': ' + n + '</title>' + g + '</g>');
  });
  if (opts.zones) {
    const ZN: [number, number, string, string][] = [[0, 3, 'You choose', ''], [3, Z, 'We run it', 'acc']], d1 = 0.3, d2 = 0.5, gap = 3;
    ZN.forEach((zn) => {
      const a = K.P(ox + 6 + d1, oy - d1, zn[0]), b = K.P(ox + 6 + d1, oy - d1, zn[1]), m = K.P(ox + 6 + d2, oy - d2, (zn[0] + zn[1]) / 2), ax = a[0].toFixed(1), y0 = (a[1] - gap).toFixed(1), y1 = (b[1] + gap).toFixed(1);
      out.push('<g class="zone ' + zn[3] + '"><line x1="' + ax + '" y1="' + y0 + '" x2="' + ax + '" y2="' + y1 + '"/><line x1="' + (a[0] - 4).toFixed(1) + '" y1="' + y0 + '" x2="' + (a[0] + 2).toFixed(1) + '" y2="' + y0 + '"/><line x1="' + (a[0] - 4).toFixed(1) + '" y1="' + y1 + '" x2="' + (a[0] + 2).toFixed(1) + '" y2="' + y1 + '"/>' +
        '<text text-anchor="middle" transform="translate(' + m[0].toFixed(1) + ',' + m[1].toFixed(1) + ') rotate(-90)">' + zn[2] + '</text></g>');
    });
    K.P(ox + 6 + 0.72, oy - 0.72, 0);
  }
  return out.join('');
}

/** The tower as SVG markup. `text`: false (none), true (every brick named), 'card' (harness and model
 *  only, large). `drops`: bricks landing now. */
export function isoSvg(o: Tower, u: number, text: boolean | 'card', zones = false, drops: Drops | null = null): string {
  const K = Iso(u, 0.9), card = text === 'card';
  const m = agentModel(K, o, { text: !!text, only: card ? ['b-runtime', 'model'] : null, big: card, zones, drops });
  const wr = K.wrap(K.tile(0.3, 0.5, 6.3, 6.5, 'iso-shadow') + m, 8);
  return '<svg class="iso" viewBox="0 0 ' + wr.w.toFixed(0) + ' ' + wr.h.toFixed(0) + '" width="100%" role="img" aria-label="Agent model">' + wr.svg + '</svg>';
}

/** What a setup is made of and what has happened to it, as read from its record and its tasks. */
export interface SetupFacts {
  harness: string;            // the base harness's name
  model: string;
  instructions: boolean;      // it has instructions of its own
  tested: boolean;            // a task of it has finished (the design's "first")
  parts: Tower['parts'];
  running: boolean;           // a task of it running now
}

/** The design's builtMap + brickStates + runningSet for an existing setup, from its facts. */
export function towerOf(f: SetupFacts): Tower {
  const done = f.tested, b: Record<string, boolean> = {};
  b['b-runtime'] = !!f.harness; b.model = !!f.model; b.task = f.instructions || done; b.backend = true;
  SUBS.forEach((x) => { b[x[0]] = true; });
  b.skill = f.parts.skill > 0; b.plugin = f.parts.plugin > 0; b.mcp = f.parts.mcp > 0; b.env = f.parts.env > 0;
  const run: Record<string, boolean> = {};
  if (f.running) {
    ['b-runtime', 'model', 'task', 'backend', 'b-sandbox', 'b-orch', 'b-sessions', 'b-stream', 'b-trace'].forEach((k) => { run[k] = true; });
    if (f.parts.skill) run.skill = true; if (f.parts.plugin) run.plugin = true; if (f.parts.env) run.env = true;
  }
  const st: States = {};
  const keys = [...LAYERS.map((L) => L.key as string), ...PARTS.map((x) => x[0] as string), ...SUBS.map((x) => x[0])];
  keys.forEach((k) => {
    const attached = k === 'skill' ? f.parts.skill > 0 : k === 'plugin' ? f.parts.plugin > 0 : k === 'mcp' ? f.parts.mcp > 0 : k === 'env' ? f.parts.env > 0 : false;
    const next = (k === 'b-runtime' && !b[k]) || (k === 'model' && b['b-runtime'] && !b.model) || (k === 'task' && b.model && !b.task)
      || (/^b-/.test(k) && k !== 'b-runtime' && b.task && !b[k]) || (attached && !done);
    st[k] = run[k] && b[k] ? 'run' : b[k] ? 'built' : next ? 'next' : 'empty';
  });
  return { harness: f.harness, model: f.model, parts: f.parts, st };
}

/** The empty tower on the "New setup" card: nothing built, the harness is the next step. */
export function ghostTower(): Tower {
  const st: States = {};
  [...LAYERS.map((L) => L.key as string), ...SUBS.map((x) => x[0]), ...PARTS.map((x) => x[0] as string)].forEach((k) => { st[k] = 'empty'; });
  st['b-runtime'] = 'next';
  return { harness: '', model: '', parts: { skill: 0, plugin: 0, mcp: 0, env: 0 }, st };
}
