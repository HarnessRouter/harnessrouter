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
const HR_MARK = '<path class="hr-k" fill-rule="evenodd" d="M228 174 227 175 223 175 222 176 216 177 203 184 192 195 192 196 190 198 185 208 184 214 183 215 183 219 182 220 182 803 183 804 183 808 184 809 185 815 190 825 192 827 192 828 203 839 219 847 227 848 228 849 240 849 241 848 246 848 247 847 253 846 267 838 276 829 276 828 280 823 283 817 283 815 285 811 285 808 286 807 286 801 287 800 287 547 288 546 288 541 289 540 289 536 291 532 292 526 295 521 295 519 298 513 300 511 303 505 310 497 310 496 325 482 326 482 329 479 332 478 334 476 337 475 339 473 343 471 345 471 348 469 350 469 353 467 356 467 360 465 368 464 369 463 376 463 377 462 392 462 393 463 400 463 401 464 405 464 406 465 413 466 414 467 419 468 422 470 424 470 432 474 434 476 441 480 451 489 452 489 454 491 454 492 461 499 461 500 464 503 464 504 468 509 476 525 476 527 478 531 478 534 480 538 480 542 481 543 481 549 482 550 482 555 484 555 484 543 485 542 485 536 486 535 486 531 488 527 489 520 490 519 490 517 491 516 493 508 496 503 496 501 503 487 505 485 505 484 507 482 511 475 514 472 516 468 523 461 523 460 540 444 541 444 544 441 545 441 547 439 547 438 546 438 542 434 542 433 537 428 537 427 518 408 517 408 512 403 511 403 508 400 507 400 504 397 503 397 500 394 499 394 494 390 491 389 486 385 464 374 462 374 454 370 452 370 451 369 449 369 445 367 442 367 441 366 439 366 435 364 432 364 431 363 427 363 426 362 422 362 421 361 417 361 416 360 401 359 400 358 368 358 367 359 352 360 351 361 347 361 346 362 342 362 341 363 333 364 332 365 330 365 326 367 323 367 322 368 314 370 311 372 309 372 306 374 304 374 288 382 287 381 287 224 286 223 286 216 285 215 285 212 284 211 283 206 280 200 278 198 276 194 267 185 266 185 261 181 250 176 247 176 246 175 241 175 240 174Z"/><path class="hr-b" fill-rule="evenodd" d="M712 358 708 358 706 359 703 363 703 409 701 411 616 411 615 412 608 412 607 413 602 413 601 414 598 414 597 415 591 416 590 417 587 417 586 418 578 420 573 423 571 423 557 430 555 432 554 432 552 434 551 434 549 436 542 440 531 450 530 450 522 458 522 459 515 466 513 470 510 473 510 474 502 485 495 499 495 501 492 506 492 508 491 509 491 511 490 512 490 514 488 518 487 525 485 529 485 533 484 534 484 540 483 541 483 553 482 554 482 802 483 803 484 812 486 815 486 817 489 823 493 828 493 829 505 840 517 846 520 846 524 848 531 848 532 849 537 849 538 848 545 848 546 847 549 847 562 841 568 836 569 836 577 827 578 824 580 822 582 818 582 816 585 810 585 806 586 805 586 559 587 558 587 551 588 550 589 544 595 533 604 524 605 524 607 522 617 517 620 517 621 516 624 516 625 515 702 515 703 516 703 563 705 566 712 568 722 561 723 561 726 558 733 554 736 551 743 547 746 544 753 540 756 537 763 533 766 530 773 526 776 523 783 519 786 516 793 512 796 509 803 505 806 502 813 498 816 495 823 491 826 488 833 484 836 481 843 477 846 474 853 470 856 466 856 464 857 463 856 459 852 455 845 451 842 448 835 444 832 441 825 437 822 434 815 430 812 427 805 423 802 420 795 416 792 413 785 409 782 406 775 402 772 399 765 395 762 392 755 388 752 385 745 381 742 378 735 374 732 371 725 367 722 364 721 364 719 362Z"/>';

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
    g = plateOf(K, pz) + '<g class="wa-h">' + brick('built', pz, zh) + label((pz + zh) / 2 + 0.2, 'Agent harness') + '</g>' + brick('built wa-m', zh, zm, false) +
      '<g class="wa-g"><g class="bk app pc-ghost">' + K.box(0, 0, zm + 0.35, 2.2, 2.2, zm + 1.35) + '</g>' + label(zm + 0.85, 'Your app') + '</g>' +
      '<g class="wa-log">' + [18, 12, 15].map((w, i) => '<g><circle cx="' + f(bx + 2) + '" cy="' + f(by + i * 7.5 + 1.7) + '" r="2.1"/><rect x="' + f(bx + 7) + '" y="' + f(by + i * 7.5) + '" width="' + w + '" height="3.4" rx="1.7"/></g>').join('') + '</g>';
  } else if (kind === 'build') {
    g = plateOf(K, pz) + brick('built wa-h', pz, zh) +
      [0, 1, 2].map((i) => { const a = zh + i / 3, b = zh + (i + 1) / 3; return '<g class="bk built app wa-s wa-s' + i + '">' + K.box(0, 0, a, 2.2, 2.2, b) + '</g>'; }).join('') +
      '<g class="wa-print">' + onTop(0, 0, zh + 1, win) + labelUp(zh + 1, 'Your app') + '</g>';
  } else {
    g = '<g class="wa-new">' + plateOf(K, pz) + brick('built', pz, zh) + '</g>' + '<g class="wa-old">' + brick('pc-ghost old', pz, zh, false) + '</g>' + '<g class="wa-app">' + app(zh) + labelUp(zh + 1, 'Your app') + '</g>';
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
