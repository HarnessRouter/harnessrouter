'use client';
// Small brick drawings of the design (docs/uxuidesign/console-79): `partIcon` (one brick, a
// setup's optional part: plugin, skill, tool, environment) and `pageArt` / `pagePic` (the
// illustration beside the API Keys and Extensions titles). Ported from the design's own
// functions. The drawings are markup strings with no text from data in them.
//
// The isometric helper is the same geometry as tower.ts's (not exported there).
import { useState } from 'react';
import { useHtml } from './Markup';

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

export type PartState = 'empty' | 'next' | 'built' | 'run';
/** One small brick in a family's colour: `mcp` a tool, `skill`, `plugin`, `tool` an environment, `memory` a memory. */
export function partIcon(state: PartState, fam: string): string {
  const K = Iso(8, 0.9), g = K.box(0, 0, 0, 2, 2, 1) + K.stud(1, 1, 1, 2);
  const wr = K.wrap('<g class="bk f-' + (fam || 'parts') + ' ' + state + '">' + g + '</g>', 2);
  return '<svg class="iso" viewBox="0 0 ' + wr.w.toFixed(0) + ' ' + wr.h.toFixed(0) + '" width="100%" aria-hidden="true">' + wr.svg + '</svg>';
}

export type StudState = 'on' | 'inv' | 'off';
/** One workspace's brick on the Organization page (console_103's studHtml): `on` opens it, in the
 *  workspace's colour; `inv` a pending invite will open it; `off` does not. `u` the unit size (8 in the
 *  grid, smaller in a chip). */
export function studIcon(color: string, st: StudState, u?: number): string {
  const K = Iso(u || 8, 0.9), H = u ? 1 : 1.45, g = K.box(0, 0, 0, 2, 2, H) + K.stud(1, 1, H, 2), wr = K.wrap(g, 1.5);
  const cls = st === 'on' ? 'built' : st === 'inv' ? 'inv' : 'empty';
  const sty = st === 'on'
    ? ' style="--b-top:color-mix(in srgb,' + color + ' 30%,var(--bg));--b-left:color-mix(in srgb,' + color + ' 52%,var(--bg));--b-right:color-mix(in srgb,' + color + ' 70%,var(--bg));--b-line:color-mix(in srgb,' + color + ' 88%,var(--fg))"'
    : st === 'inv' ? ' style="--c:' + color + '"' : '';
  return '<svg class="iso acc" viewBox="0 0 ' + wr.w.toFixed(0) + ' ' + wr.h.toFixed(0) + '" width="' + wr.w.toFixed(0) + '" height="' + wr.h.toFixed(0) + '" aria-hidden="true"><g class="bk ' + cls + '"' + sty + '>' + wr.svg + '</g></svg>';
}

export function Stud({ color, st, u }: { color: string; st: StudState; u?: number }) {
  // the markup is geometry and a colour this console computes (wsColor), no text from data
  const html = useHtml(studIcon(color, st, u) /* SVG from our own palette (wsColor hashes the name to a COLORS entry); never data */);
  return <span className="stud" dangerouslySetInnerHTML={html} />;
}

// the HarnessRouter mark, as the design prints it on the plate (its own 675-unit drawing)
const HR_MARK = '<path d="M500 90 850 292v416L500 910 150 708V292L500 90Z" fill="#3654df"/><path d="M350 305h90v145h120V305h90v390h-90V540H440v155h-90V305Z" fill="#fff"/>';

/** The page illustration: `keys` (your app, a key, HarnessRouter) or `ext` (a setup on
 *  HarnessRouter with a plugin, a skill, a tool and an environment snapped on). */
export function pageArt(kind: 'keys' | 'ext', play: boolean): string {
  const K = Iso(15, 0.9), pz = 0.42, f = (v: number) => v.toFixed(3);
  const onTop = (x0: number, y0: number, z: number, inner: string) => {
    const o = K.P(x0, y0, z);
    return '<g transform="matrix(' + [K.c * K.u, 0.5 * K.u, -K.c * K.u, 0.5 * K.u, o[0], o[1]].map(f).join(',') + ')">' + inner + '</g>';
  };
  const plate = (x0: number) => {
    const sz = 1.72, o0 = (2.2 - sz) / 2, o = K.P(x0 + 2.2 + o0, o0, pz), k = sz / 675;
    return '<g class="bk empty pc-plate">' + K.box(x0, 0, 0, x0 + 4.4, 2.2, pz) + '</g>' +
      '<g class="pc-logo" transform="matrix(' + [K.c * K.u * k, 0.5 * K.u * k, -K.c * K.u * k, 0.5 * K.u * k, o[0], o[1]].map(f).join(',') + ') translate(-182,-174)">' + HR_MARK + '</g>';
  };
  const label = (x: number, y: number, z: number, text: string) => {
    const a = K.P(x, y, z), L = 12, w = text.length * 6.1, d = (L + w + 4) / (2 * K.c * K.u); K.P(x - d, y + d, z);
    return '<g class="wa-lb"><circle cx="' + f(a[0]) + '" cy="' + f(a[1]) + '" r="1.6"/><line x1="' + f(a[0] - 2) + '" y1="' + f(a[1]) + '" x2="' + f(a[0] - L) + '" y2="' + f(a[1]) + '"/><text x="' + f(a[0] - L - 3) + '" y="' + f(a[1] + 3) + '" text-anchor="end">' + text + '</text></g>';
  };
  const labelDown = (x: number, y: number, z: number, text: string) => {
    const a = K.P(x, y, z), b = [a[0], a[1] + 14]; K.P(x + 1.6, y + 1.6, z - 1.4);
    return '<g class="wa-lb"><circle cx="' + f(a[0]) + '" cy="' + f(a[1]) + '" r="1.6"/><line x1="' + f(a[0]) + '" y1="' + f(a[1] + 2) + '" x2="' + f(b[0]) + '" y2="' + f(b[1]) + '"/><text x="' + f(b[0]) + '" y="' + f(b[1] + 11) + '" text-anchor="middle">' + text + '</text></g>';
  };
  const win = '<rect class="wa-win" x=".45" y=".55" width="1.3" height="1.1" rx=".12"/><line class="wa-win" x1=".45" y1=".85" x2="1.75" y2=".85"/>';
  const key = '<circle class="wa-win" cx=".62" cy=".62" r=".26"/><line class="wa-win" x1=".82" y1=".82" x2="1.5" y2="1.5"/><line class="wa-win" x1="1.2" y1="1.2" x2="1.38" y2="1.02"/>';
  let g = '';
  if (kind === 'keys') {
    // your app, a key, HarnessRouter: the key drops in between and your app turns blue
    const kx = 2.75;
    g = '<g class="pa-app"><g class="bk built app">' + K.box(0, 0, 0, 2.2, 2.2, 1) + '</g>' + onTop(0, 0, 1, win) + label(0, 2.2, 0.5, '你的应用') + '</g>' +
      '<g class="pa-key"><g class="bk built f-tool">' + K.box(kx, 0.5, 0, kx + 1.3, 1.7, 0.28) + '</g>' + onTop(kx, 0.5, 0.28, '<g transform="scale(.6)">' + key + '</g>') + labelDown(kx + 1.3, 1.7, 0, 'API key') + '</g>' +
      '<g transform="translate(' + f(4.6 * K.c * K.u) + ',' + f(4.6 * 0.5 * K.u) + ')">' + plate(0) + '</g>';
    K.P(9.0, 0, 0); K.P(9.0, 2.2, 0);
  } else {
    // a setup on HarnessRouter; a plugin, a skill, a tool and an environment snap on, in tab order
    const zt = pz + 1.2;
    const part = (i: number, fam: string, x: number, y: number) => '<g class="pa-p pa-p' + i + '"><g class="bk built f-' + fam + '">' + K.box(x, y, zt, x + 0.85, y + 0.85, zt + 0.55) + K.stud(x + 0.425, y + 0.425, zt + 0.55, 1) + '</g></g>';
    g = plate(0) + '<g class="bk built">' + K.box(0, 0, pz, 2.2, 2.2, zt) + '</g>' + label(0, 2.2, (pz + zt) / 2, 'Your setup') +
      part(0, 'plugin', 0.15, 0.15) + part(1, 'skill', 1.2, 0.15) + part(2, 'mcp', 0.15, 1.2) + part(3, 'tool', 1.2, 1.2);
    K.P(0, 0, zt + 1.6);
  }
  const wr = K.wrap(g, 6);
  return '<svg class="iso pc wa pa ' + (play ? 'play ' : '') + 'pa-' + kind + '" viewBox="0 0 ' + wr.w.toFixed(0) + ' ' + wr.h.toFixed(0) + '" width="' + wr.w.toFixed(0) + '" height="' + wr.h.toFixed(0) + '" aria-hidden="true">' + wr.svg + '</svg>';
}

// the drawing plays its little animation the first time a page shows it in this tab, as the design's does
const played = new Set<string>();

/** The illustration at the right of a page title (`.ph-art`, hidden on narrow screens by the stylesheet). */
export function PagePic({ kind }: { kind: 'keys' | 'ext' }) {
  const [svg] = useState(() => { const first = !played.has(kind); played.add(kind); return pageArt(kind, first); });
  const html = useHtml(svg);
  return <span className="ph-art" aria-hidden="true" dangerouslySetInnerHTML={html} />;
}

/** A brick as an inline drawing, in the wrapper class the design gives it (`tab-brick`, `lib-ic`, `es-art`). */
export function Part({ state, fam, className, off }: { state: PartState; fam: string; className: string; off?: boolean }) {
  const html = useHtml(partIcon(state, fam));
  return <span className={className + (off ? ' off' : '')} aria-hidden="true" dangerouslySetInnerHTML={html} />;
}
