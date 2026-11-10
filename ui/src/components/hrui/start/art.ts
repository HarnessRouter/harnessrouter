// Start's brick drawings (docs/uxuidesign/console-79): `wayArt` (the picture on each of Start's three
// ways in), `nwArt` (the setup being put together in "Set up an agent harness") and `slabIcon` (the
// save card's mark, console-87). Ported from the design's own functions. The drawings are markup strings; the only text in them is fixed labels
// ("Agent harness", "Your app") and, in nwArt's tooltips, the chosen harness and model, escaped.
//
// The isometric helper and the HarnessRouter mark are the same geometry and paths as bricks.tsx's
// (not exported there).

const esc = (s: string) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] as string));

function Iso(u: number, zh: number) {
  const c = 0.866, zH = zh, bb = { x0: 1e9, y0: 1e9, x1: -1e9, y1: -1e9 };
  function P(x: number, y: number, z: number): [number, number] {
    const X = (x - y) * c * u, Y = (x + y) * 0.5 * u - z * zH * u;
    if (X < bb.x0) bb.x0 = X; if (X > bb.x1) bb.x1 = X; if (Y < bb.y0) bb.y0 = Y; if (Y > bb.y1) bb.y1 = Y;
    return [X, Y];
  }
  const pts = (a: [number, number][]) => a.map((p) => p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' ');
  const poly = (a: [number, number][], cls: string) => '<polygon class="' + cls + '" points="' + pts(a) + '"/>';
  const box = (x0: number, y0: number, z0: number, x1: number, y1: number, z1: number) =>
    poly([P(x0, y0, z1), P(x1, y0, z1), P(x1, y1, z1), P(x0, y1, z1)], 't') + poly([P(x0, y1, z0), P(x1, y1, z0), P(x1, y1, z1), P(x0, y1, z1)], 'l') +
    poly([P(x1, y0, z0), P(x1, y1, z0), P(x1, y1, z1), P(x1, y0, z1)], 'r') + '<polyline class="hl" points="' + pts([P(x0 + 0.06, y1, z1), P(x1, y1, z1), P(x1, y0 + 0.06, z1)]) + '"/>';
  function stud(x: number, y: number, z: number, sc = 1) {
    const p = P(x, y, z), rx = 0.34 * u * sc, ry = 0.2 * u * sc, h = 0.24 * u * (sc > 1 ? 1.35 : 1); P(x, y, z + 0.4 * sc);
    return '<ellipse class="sd" cx="' + p[0].toFixed(1) + '" cy="' + p[1].toFixed(1) + '" rx="' + rx.toFixed(1) + '" ry="' + ry.toFixed(1) + '"/><rect class="sd" x="' + (p[0] - rx).toFixed(1) + '" y="' + (p[1] - h).toFixed(1) + '" width="' + (2 * rx).toFixed(1) + '" height="' + h.toFixed(1) + '"/><ellipse class="su" cx="' + p[0].toFixed(1) + '" cy="' + (p[1] - h).toFixed(1) + '" rx="' + rx.toFixed(1) + '" ry="' + ry.toFixed(1) + '"/><ellipse class="sh" cx="' + (p[0] - 0.13 * u * sc).toFixed(1) + '" cy="' + (p[1] - h - 0.04 * u * sc).toFixed(1) + '" rx="' + (0.11 * u * sc).toFixed(1) + '" ry="' + (0.055 * u * sc).toFixed(1) + '"/>';
  }
  function wrap(inner: string, pad: number) {
    const w = bb.x1 - bb.x0 + 2 * pad, h = bb.y1 - bb.y0 + 2 * pad;
    return { w, h, svg: '<g transform="translate(' + (pad - bb.x0).toFixed(1) + ',' + (pad - bb.y0).toFixed(1) + ')">' + inner + '</g>' };
  }
  return { P, box, stud, wrap, c, zH, u };
}

// the HarnessRouter mark, as the design prints it on the plate (its own 675-unit drawing; the rail logo's paths)
const HR_MARK = '<path d="M500 90 850 292v416L500 910 150 708V292L500 90Z" fill="#3654df"/><path d="M350 305h90v145h120V305h90v390h-90V540H440v155h-90V305Z" fill="#fff"/>';

const f = (v: number) => v.toFixed(3);

/** HarnessRouter's plate (a 4.4 x 2.2 slab) with its mark printed on the right half. */
function plateOf(K: ReturnType<typeof Iso>, pz: number): string {
  const sz = 1.72, o0 = (2.2 - sz) / 2, o = K.P(2.2 + o0, o0, pz), k = sz / 675;
  return '<g class="bk empty pc-plate">' + K.box(0, 0, 0, 4.4, 2.2, pz) + '</g>' +
    '<g class="pc-logo" transform="matrix(' + [K.c * K.u * k, 0.5 * K.u * k, -K.c * K.u * k, 0.5 * K.u * k, o[0], o[1]].map(f).join(',') + ') translate(-182,-174)">' + HR_MARK + '</g>';
}

export type Way = 'hr' | 'build' | 'move';

/** Start art: one picture per way in, each a short story. The default markup is the end state (your
 *  app on an agent harness on HarnessRouter); the class "play" runs the story from the beginning. */
export function wayArt(kind: Way): string {
  const K = Iso(14, 0.9), pz = 0.42, zh = pz + 1, zm = zh + 0.62;
  // print on a top face, the way HarnessRouter's mark is printed on its plate
  const onTop = (x0: number, y0: number, z: number, inner: string) => {
    const o = K.P(x0, y0, z);
    return '<g transform="matrix(' + [K.c * K.u, 0.5 * K.u, -K.c * K.u, 0.5 * K.u, o[0], o[1]].map(f).join(',') + ')">' + inner + '</g>';
  };
  const brick = (cls: string, z0: number, z1: number, stud?: boolean) => '<g class="bk ' + cls + '">' + K.box(0, 0, z0, 2.2, 2.2, z1) + (stud ? K.stud(1.1, 1.1, z1, 2) : '') + '</g>';
  // a name for a brick: a hairline from its left edge, then the name
  const label = (z: number, text: string) => {
    const a = K.P(0, 2.2, z), L = 12, w = text.length * 6.1, d = (L + w + 4) / (2 * K.c * K.u); K.P(-d, 2.2 + d, z);
    return '<g class="wa-lb"><circle cx="' + f(a[0]) + '" cy="' + f(a[1]) + '" r="1.6"/><line x1="' + f(a[0] - 2) + '" y1="' + f(a[1]) + '" x2="' + f(a[0] - L) + '" y2="' + f(a[1]) + '"/><text x="' + f(a[0] - L - 3) + '" y="' + f(a[1] + 3) + '" text-anchor="end">' + text + '</text></g>';
  };
  // in the two small ways the name sits above the brick, so the picture stays narrow
  const labelUp = (z: number, text: string) => {
    const a = K.P(0, 0, z), L = 11; K.P(0, 0, z + (L + 16) / (K.zH * K.u));
    return '<g class="wa-lb"><circle cx="' + f(a[0]) + '" cy="' + f(a[1]) + '" r="1.6"/><line x1="' + f(a[0]) + '" y1="' + f(a[1] - 2) + '" x2="' + f(a[0]) + '" y2="' + f(a[1] - L) + '"/><text x="' + f(a[0]) + '" y="' + f(a[1] - L - 4) + '" text-anchor="middle">' + text + '</text></g>';
  };
  const win = '<rect class="wa-win" x=".45" y=".55" width="1.3" height="1.1" rx=".12"/><line class="wa-win" x1=".45" y1=".85" x2="1.75" y2=".85"/>';
  const app = (z0: number) => '<g class="bk built app">' + K.box(0, 0, z0, 2.2, 2.2, z0 + 1) + '</g>' + onTop(0, 0, z0 + 1, win);
  let g = '';
  if (kind === 'hr') {
    const tp = K.P(2.2, 0, zm), bx = tp[0] + 12, by = tp[1] - 6;
    g = plateOf(K, pz) + '<g class="wa-h">' + brick('built', pz, zh) + label((pz + zh) / 2 + 0.2, '智能体运行环境') + '</g>' + brick('built wa-m', zh, zm, false) +
      '<g class="wa-g"><g class="bk app pc-ghost">' + K.box(0, 0, zm + 0.35, 2.2, 2.2, zm + 1.35) + '</g>' + label(zm + 0.85, '你的应用') + '</g>' +
      '<g class="wa-log">' + [18, 12, 15].map((w, i) => '<g><circle cx="' + f(bx + 2) + '" cy="' + f(by + i * 7.5 + 1.7) + '" r="2.1"/><rect x="' + f(bx + 7) + '" y="' + f(by + i * 7.5) + '" width="' + w + '" height="3.4" rx="1.7"/></g>').join('') + '</g>';
  } else if (kind === 'build') {
    g = plateOf(K, pz) + brick('built wa-h', pz, zh) +
      [0, 1, 2].map((i) => { const a = zh + i / 3, b = zh + (i + 1) / 3; return '<g class="bk built app wa-s wa-s' + i + '">' + K.box(0, 0, a, 2.2, 2.2, b) + '</g>'; }).join('') +
      '<g class="wa-print">' + onTop(0, 0, zh + 1, win) + labelUp(zh + 1, '你的应用') + '</g>';
  } else {
    g = '<g class="wa-new">' + plateOf(K, pz) + brick('built', pz, zh) + '</g>' + '<g class="wa-old">' + brick('pc-ghost old', pz, zh, false) + '</g>' + '<g class="wa-app">' + app(zh) + labelUp(zh + 1, '你的应用') + '</g>';
  }
  const wr = K.wrap(g, 6);
  return '<svg class="iso pc wa wa-' + kind + '" viewBox="0 0 ' + wr.w.toFixed(0) + ' ' + wr.h.toFixed(0) + '" width="' + wr.w.toFixed(0) + '" height="' + wr.h.toFixed(0) + '" aria-hidden="true">' + wr.svg + '</svg>';
}

/** One way's picture as Start places it (`.sg-art`): the story plays when `play`, and the drawing's
 *  own height rides along as --hn so short screens scale all three alike. */
export function wayPic(kind: Way, play: boolean): string {
  const sv = wayArt(kind).replace('class="iso pc wa ', 'class="iso pc wa ' + (play ? 'play ' : ''));
  const m = sv.match(/height="(\d+)"/);
  return sv.replace('<svg ', '<svg style="--hn:' + (m ? m[1] : 100) + '" ');
}

/** The setup as it is chosen in "Set up an agent harness": HarnessRouter's plate, then the agent
 *  harness, then the model. A choice lands as a brick (`drop` when it just changed); a part the
 *  setup carries sits on top as a small brick, and drops in as it is saved (`dropParts`). */
export function nwArt(o: { h: string; m: string; dropH: boolean; dropM: boolean; parts: { skill: number; plugin: number; tool: number };
  dropParts?: { skill?: boolean; plugin?: boolean; tool?: boolean } }): string {
  const { h: hv, m: mv, dropH: dh, dropM: dm, parts } = o;
  const dp = (o.dropParts || {}) as Record<string, boolean | undefined>;
  const K = Iso(12, 0.9), pz = 0.42, zh = pz + 1, zm = zh + 0.62;
  const anyPart = parts.skill || parts.plugin || parts.tool;
  const g = plateOf(K, pz) +
    '<g class="bk ' + (hv ? 'built' : 'next') + (dh ? ' drop' : '') + '"><title>Agent harness' + (hv ? ': ' + esc(hv) : '') + '</title>' + K.box(0, 0, pz, 2.2, 2.2, zh) + '</g>' +
    '<g class="bk ' + (mv ? 'built' : hv ? 'next' : 'empty') + (dm ? ' drop' : '') + '" style="animation-delay:' + (dh && dm ? '140ms' : '0ms') + '"><title>Model' + (mv ? ': ' + esc(mv) : '') + '</title>' + K.box(0, 0, zh, 2.2, 2.2, zm) + (anyPart ? '' : K.stud(1.1, 1.1, zm, 2)) + '</g>' +
    ([['skill', parts.skill, 0.15, 0.15], ['plugin', parts.plugin, 1.2, 0.15], ['tool', parts.tool, 1.2, 1.2]] as [string, number, number, number][]).map((q) => {
      if (!q[1] || !mv) return '';
      const x = q[2], y = q[3];
      return '<g class="bk built f-' + q[0] + (dp[q[0]] ? ' drop' : '') + '">' + K.box(x, y, zm, x + 0.85, y + 0.85, zm + 0.55) + K.stud(x + 0.425, y + 0.425, zm + 0.55, 1) + '</g>';
    }).join('');
  const wr = K.wrap(g, 4);
  return '<svg class="iso pc" viewBox="0 0 ' + wr.w.toFixed(0) + ' ' + wr.h.toFixed(0) + '" aria-hidden="true">' + wr.svg + '</svg>';
}

/** The save card's mark (the design's slabIcon): a studded baseplate. */
export function slabIcon(): string {
  const K = Iso(4.4, 0.9);
  let g = K.box(0, 0, 0, 6, 6, 1);
  [1, 3, 5].forEach((x) => { [1, 3, 5].forEach((y) => { g += K.stud(x, y, 1, 2); }); });
  const wr = K.wrap('<g class="bk built f-backend">' + g + '</g>', 2);
  return '<svg class="iso" viewBox="0 0 ' + wr.w.toFixed(0) + ' ' + wr.h.toFixed(0) + '" width="100%" aria-hidden="true">' + wr.svg + '</svg>';
}
