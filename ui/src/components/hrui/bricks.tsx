'use client';
// Small brick drawings of the design (docs/uxuidesign/console-79): `partIcon` (one brick, a
// setup's optional part: plugin, skill, tool, environment) and `pageArt` / `pagePic` (the
// illustration beside the API Keys and Extensions titles). Ported from the design's own
// functions. The drawings are markup strings with no text from data in them.
//
// The isometric helper is the same geometry as tower.ts's (not exported there).
import { useState } from 'react';

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
/** One small brick in a family's colour: `mcp` a tool, `skill`, `plugin`, `tool` an environment. */
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
  return <span className="stud" dangerouslySetInnerHTML={{ __html: studIcon(color, st, u) /* SVG from our own palette (wsColor hashes the name to a COLORS entry); never data */ }} />;
}

// the HarnessRouter mark, as the design prints it on the plate (its own 675-unit drawing)
const HR_MARK = '<path class="hr-k" fill-rule="evenodd" d="M228 174 227 175 223 175 222 176 216 177 203 184 192 195 192 196 190 198 185 208 184 214 183 215 183 219 182 220 182 803 183 804 183 808 184 809 185 815 190 825 192 827 192 828 203 839 219 847 227 848 228 849 240 849 241 848 246 848 247 847 253 846 267 838 276 829 276 828 280 823 283 817 283 815 285 811 285 808 286 807 286 801 287 800 287 547 288 546 288 541 289 540 289 536 291 532 292 526 295 521 295 519 298 513 300 511 303 505 310 497 310 496 325 482 326 482 329 479 332 478 334 476 337 475 339 473 343 471 345 471 348 469 350 469 353 467 356 467 360 465 368 464 369 463 376 463 377 462 392 462 393 463 400 463 401 464 405 464 406 465 413 466 414 467 419 468 422 470 424 470 432 474 434 476 441 480 451 489 452 489 454 491 454 492 461 499 461 500 464 503 464 504 468 509 476 525 476 527 478 531 478 534 480 538 480 542 481 543 481 549 482 550 482 555 484 555 484 543 485 542 485 536 486 535 486 531 488 527 489 520 490 519 490 517 491 516 493 508 496 503 496 501 503 487 505 485 505 484 507 482 511 475 514 472 516 468 523 461 523 460 540 444 541 444 544 441 545 441 547 439 547 438 546 438 542 434 542 433 537 428 537 427 518 408 517 408 512 403 511 403 508 400 507 400 504 397 503 397 500 394 499 394 494 390 491 389 486 385 464 374 462 374 454 370 452 370 451 369 449 369 445 367 442 367 441 366 439 366 435 364 432 364 431 363 427 363 426 362 422 362 421 361 417 361 416 360 401 359 400 358 368 358 367 359 352 360 351 361 347 361 346 362 342 362 341 363 333 364 332 365 330 365 326 367 323 367 322 368 314 370 311 372 309 372 306 374 304 374 288 382 287 381 287 224 286 223 286 216 285 215 285 212 284 211 283 206 280 200 278 198 276 194 267 185 266 185 261 181 250 176 247 176 246 175 241 175 240 174Z"/><path class="hr-b" fill-rule="evenodd" d="M712 358 708 358 706 359 703 363 703 409 701 411 616 411 615 412 608 412 607 413 602 413 601 414 598 414 597 415 591 416 590 417 587 417 586 418 578 420 573 423 571 423 557 430 555 432 554 432 552 434 551 434 549 436 542 440 531 450 530 450 522 458 522 459 515 466 513 470 510 473 510 474 502 485 495 499 495 501 492 506 492 508 491 509 491 511 490 512 490 514 488 518 487 525 485 529 485 533 484 534 484 540 483 541 483 553 482 554 482 802 483 803 484 812 486 815 486 817 489 823 493 828 493 829 505 840 517 846 520 846 524 848 531 848 532 849 537 849 538 848 545 848 546 847 549 847 562 841 568 836 569 836 577 827 578 824 580 822 582 818 582 816 585 810 585 806 586 805 586 559 587 558 587 551 588 550 589 544 595 533 604 524 605 524 607 522 617 517 620 517 621 516 624 516 625 515 702 515 703 516 703 563 705 566 712 568 722 561 723 561 726 558 733 554 736 551 743 547 746 544 753 540 756 537 763 533 766 530 773 526 776 523 783 519 786 516 793 512 796 509 803 505 806 502 813 498 816 495 823 491 826 488 833 484 836 481 843 477 846 474 853 470 856 466 856 464 857 463 856 459 852 455 845 451 842 448 835 444 832 441 825 437 822 434 815 430 812 427 805 423 802 420 795 416 792 413 785 409 782 406 775 402 772 399 765 395 762 392 755 388 752 385 745 381 742 378 735 374 732 371 725 367 722 364 721 364 719 362Z"/>';

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
    g = '<g class="pa-app"><g class="bk built app">' + K.box(0, 0, 0, 2.2, 2.2, 1) + '</g>' + onTop(0, 0, 1, win) + label(0, 2.2, 0.5, 'Your app') + '</g>' +
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
  return <span className="ph-art" aria-hidden="true" dangerouslySetInnerHTML={{ __html: svg }} />;
}

/** A brick as an inline drawing, in the wrapper class the design gives it (`tab-brick`, `lib-ic`, `es-art`). */
export function Part({ state, fam, className, off }: { state: PartState; fam: string; className: string; off?: boolean }) {
  return <span className={className + (off ? ' off' : '')} aria-hidden="true" dangerouslySetInnerHTML={{ __html: partIcon(state, fam) }} />;
}
