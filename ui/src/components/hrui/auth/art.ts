// The sign-in and first-run drawings (docs/uxuidesign/console-79: HR_LOGO, auMark, obTower,
// startPiece('demo')), ported from the design's own functions. They are markup strings; the only text
// in them is fixed labels (the parts' names from tower.ts, "Your app", "Agent harnesses").
//
// The isometric helper is the same geometry as tower.ts's and bricks.tsx's (not exported there).
import { SUBS } from '../tower';

const esc = (s: string) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] as string));
const subName = (k: string) => (SUBS.find((x) => x[0] === k) || [0, '智能体网关'])[1] as string;
type Pt = [number, number];

function Iso(u: number, zh: number) {
  const c = 0.866, zH = zh, bb = { x0: 1e9, y0: 1e9, x1: -1e9, y1: -1e9 };
  function P(x: number, y: number, z: number): Pt {
    const X = (x - y) * c * u, Y = (x + y) * 0.5 * u - z * zH * u;
    if (X < bb.x0) bb.x0 = X; if (X > bb.x1) bb.x1 = X; if (Y < bb.y0) bb.y0 = Y; if (Y > bb.y1) bb.y1 = Y;
    return [X, Y];
  }
  const pts = (a: Pt[]) => a.map((p) => p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' ');
  const poly = (a: Pt[], cls: string) => '<polygon class="' + cls + '" points="' + pts(a) + '"/>';
  const box = (x0: number, y0: number, z0: number, x1: number, y1: number, z1: number) =>
    poly([P(x0, y0, z1), P(x1, y0, z1), P(x1, y1, z1), P(x0, y1, z1)], 't') + poly([P(x0, y1, z0), P(x1, y1, z0), P(x1, y1, z1), P(x0, y1, z1)], 'l') +
    poly([P(x1, y0, z0), P(x1, y1, z0), P(x1, y1, z1), P(x1, y0, z1)], 'r') + '<polyline class="hl" points="' + pts([P(x0 + 0.06, y1, z1), P(x1, y1, z1), P(x1, y0 + 0.06, z1)]) + '"/>';
  function stud(x: number, y: number, z: number, sc = 1) {
    const p = P(x, y, z), rx = 0.34 * u * sc, ry = 0.2 * u * sc, h = 0.24 * u * (sc > 1 ? 1.35 : 1); P(x, y, z + 0.4 * sc);
    return '<ellipse class="sd" cx="' + p[0].toFixed(1) + '" cy="' + p[1].toFixed(1) + '" rx="' + rx.toFixed(1) + '" ry="' + ry.toFixed(1) + '"/><rect class="sd" x="' + (p[0] - rx).toFixed(1) + '" y="' + (p[1] - h).toFixed(1) + '" width="' + (2 * rx).toFixed(1) + '" height="' + h.toFixed(1) + '"/><ellipse class="su" cx="' + p[0].toFixed(1) + '" cy="' + (p[1] - h).toFixed(1) + '" rx="' + rx.toFixed(1) + '" ry="' + ry.toFixed(1) + '"/><ellipse class="sh" cx="' + (p[0] - 0.13 * u * sc).toFixed(1) + '" cy="' + (p[1] - h - 0.04 * u * sc).toFixed(1) + '" rx="' + (0.11 * u * sc).toFixed(1) + '" ry="' + (0.055 * u * sc).toFixed(1) + '"/>';
  }
  const tile = (x0: number, y0: number, x1: number, y1: number, cls: string) => poly([P(x0, y0, 0), P(x1, y0, 0), P(x1, y1, 0), P(x0, y1, 0)], cls);
  function wrap(inner: string, pad: number) {
    const w = bb.x1 - bb.x0 + 2 * pad, h = bb.y1 - bb.y0 + 2 * pad;
    return { w, h, tx: pad - bb.x0, ty: pad - bb.y0, svg: '<g transform="translate(' + (pad - bb.x0).toFixed(1) + ',' + (pad - bb.y0).toFixed(1) + ')">' + inner + '</g>' };
  }
  return { P, pts, poly, box, stud, tile, wrap, c, zH, u };
}

/** The official HarnessRouter lockup: the hr mark and the harnessrouter. wordmark. */
export const HR_LOGO = '<span>智能体网关</span>';

/** The sign-in mark: three bricks for the sign-up's three steps (account, email, verified). The
 *  first `n` are built, solid; the rest are dashed ghosts. */
export function auMark(n: number): string {
  const K = Iso(7, 0.9), H = 0.95;
  let g = '', gh = '';
  for (let i = 0; i < 3; i++) {
    const z0 = i * H, z1 = z0 + H;
    if (i < n) g += '<g class="bk run">' + K.box(0, 0, z0, 2, 2, z1) + (i === n - 1 ? K.stud(1, 1, z1, 2) : '') + '</g>';
    else gh += '<g class="au-ghost">' + K.poly([K.P(0, 0, z1), K.P(2, 0, z1), K.P(2, 0, z0), K.P(2, 2, z0), K.P(0, 2, z0), K.P(0, 2, z1)], '') +
      '<polyline points="' + K.pts([K.P(0, 2, z1), K.P(2, 2, z1), K.P(2, 0, z1)]) + '"/><polyline points="' + K.pts([K.P(2, 2, z1), K.P(2, 2, z0)]) + '"/></g>';
  }
  const wr = K.wrap(gh + g, 1.5);
  return '<svg class="iso au-mark" viewBox="0 0 ' + wr.w.toFixed(0) + ' ' + wr.h.toFixed(0) + '" width="' + wr.w.toFixed(0) + '" height="' + wr.h.toFixed(0) + '" aria-hidden="true">' + wr.svg + '</svg>';
}

// the welcome picture's HarnessRouter parts: [key, x0, y0, x1, y1, tier], back to front
const OB_PARTS: [string, number, number, number, number, number][] = [['b-sandbox', 0, 0, 6, 3, 0], ['b-orch', 0, 3, 6, 6, 0], ['b-files', 3, 0, 6, 3, 1], ['b-sessions', 0, 3, 3, 6, 1], ['b-stream', 3, 3, 6, 6, 1], ['b-errors', 3, 0, 6, 3, 2]];

/** The welcome picture: a complete app as one stack. Your app on top, HarnessRouter's parts in the
 *  middle (each named on its brick, from the parts list), the agent harnesses at the bottom; a
 *  bracket marks HarnessRouter's share. `zl` places the bracket's label, in percent of the drawing. */
export function obTower(): { svg: string; zl: { left: string; top: string }; parts: string } {
  const u = 22, K = Iso(u, 0.9), f = (v: number) => v.toFixed(1), TOP = 5;
  let out = K.tile(0.3, 0.5, 6.3, 6.5, 'iso-shadow');
  const label = (x0: number, y0: number, x1: number, y1: number, z1: number, h: number, txt: string, big?: boolean) => {
    const front = y1 === 6, w = front ? x1 - x0 : y1 - y0, fs = Math.min((big ? 0.5 : 0.42) * u, (w - 0.45) * u / (txt.length * 0.56)), q = front ? K.P(x0, y1, z1) : K.P(x1, y1, z1);
    return '<text class="lbl" transform="matrix(' + K.c + ',' + (front ? '0.5' : '-0.5') + ',0,1,' + f(q[0]) + ',' + f(q[1]) + ')" x="' + f(0.22 * u) + '" y="' + f(K.zH * u * h * 0.5 + fs * 0.36) + '" font-size="' + f(fs) + '">' + esc(txt) + '</text>';
  };
  out += '<g class="bk f-harness built">' + K.box(0, 0, 0, 6, 6, 1) + label(0, 0, 6, 6, 1, 1, 'Agent harnesses', true) + '</g>';
  out += '<g class="bk f-backend built">' + K.box(0, 0, 2, 3, 3, 3) + K.box(0, 0, 1, 3, 3, 2) + '</g>';
  OB_PARTS.forEach((B) => { const z0 = 1 + B[5]; out += '<g class="bk f-backend built">' + K.box(B[1], B[2], z0, B[3], B[4], z0 + 1) + label(B[1], B[2], B[3], B[4], z0 + 1, 1, subName(B[0])) + '</g>'; });
  let app = '<g class="bk wapp">' + K.box(0, 0, 4, 6, 6, TOP);
  for (let xi = 1; xi < 6; xi += 2) for (let yi = 1; yi < 6; yi += 2) app += K.stud(xi, yi, TOP, 2);
  out += app + label(0, 0, 6, 6, TOP, 1, '你的应用', true) + '</g>';
  const a = K.P(6.3, -0.3, 0), b = K.P(6.3, -0.3, 4), x = a[0], y0 = a[1] - 2, y1 = b[1] + 2;
  out += '<g class="zone acc"><line x1="' + f(x) + '" y1="' + f(y0) + '" x2="' + f(x) + '" y2="' + f(y1) + '"/><line x1="' + f(x - 4) + '" y1="' + f(y0) + '" x2="' + f(x) + '" y2="' + f(y0) + '"/><line x1="' + f(x - 4) + '" y1="' + f(y1) + '" x2="' + f(x) + '" y2="' + f(y1) + '"/></g>';
  const wr = K.wrap(out, 6);
  return {
    svg: '<svg class="iso" viewBox="0 0 ' + wr.w.toFixed(0) + ' ' + wr.h.toFixed(0) + '" aria-hidden="true">' + wr.svg + '</svg>',
    zl: { left: ((x + 7 + wr.tx) / wr.w * 100).toFixed(2) + '%', top: (((y0 + y1) / 2 + wr.ty) / wr.h * 100).toFixed(2) + '%' },
    parts: OB_PARTS.map((B) => subName(B[0]).toLowerCase()).join(', '),
  };
}

/** "Walk through the full demo": a running brick with a play mark on top (the design's startPiece('demo')). */
export function demoPiece(): string {
  const K = Iso(13, 0.9), z = 1.2;
  const g = '<g class="bk run pc-a">' + K.box(0, 0, 0, 2.4, 2.4, z) + K.poly([K.P(0.78, 0.62, z), K.P(0.78, 1.78, z), K.P(1.78, 1.2, z)], 'pr') + '</g>';
  const wr = K.wrap(g, 4);
  return '<svg class="iso pc" viewBox="0 0 ' + wr.w.toFixed(0) + ' ' + wr.h.toFixed(0) + '" width="' + wr.w.toFixed(0) + '" height="' + wr.h.toFixed(0) + '" aria-hidden="true">' + wr.svg + '</svg>';
}
