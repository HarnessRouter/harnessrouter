// The sign-in and first-run drawings (docs/uxuidesign/console-79: HR_LOGO, auMark, obTower,
// startPiece('demo')), ported from the design's own functions. They are markup strings; the only text
// in them is fixed labels (the parts' names from tower.ts, "Your app", "Agent harnesses").
//
// The isometric helper is the same geometry as tower.ts's and bricks.tsx's (not exported there).
import { SUBS } from '../tower';

const esc = (s: string) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] as string));
const subName = (k: string) => (SUBS.find((x) => x[0] === k) || [0, 'HarnessRouter'])[1] as string;
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
export const HR_LOGO = '<svg class="hr-logo" viewBox="0 0 3200 503" aria-hidden="true"><path class="hr-k" fill-rule="evenodd" d="M31 0 16 7 7 16 0 31 0 471 7 486 19 497 31 502 47 502 63 494 72 484 77 472 78 465 78 278 83 259 91 245 109 227 129 217 147 214 171 217 193 228 210 245 218 259 222 272 223 286 225 286 225 275 227 264 236 239 248 220 267 201 272 198 272 196 247 171 227 157 204 146 180 139 166 137 128 138 106 143 79 154 78 153 78 38 77 30 70 15 57 4 47 0Z"/><path class="hr-b" fill-rule="evenodd" d="M396 137 390 137 387 141 387 175 386 176 323 176 307 179 285 187 265 200 247 218 239 230 231 246 226 262 223 285 223 466 227 481 231 487 239 495 246 499 254 502 270 502 280 498 294 486 300 473 301 467 301 282 303 275 309 265 319 257 327 254 386 254 387 255 387 288 390 292 394 293 502 218 502 212 499 209Z"/><g transform="translate(676 0)"><path class="hr-k" fill-rule="evenodd" d="M253 198 245 206 238 216 231 232 229 246 284 246 291 234 304 224 318 221 329 222 336 224 343 228 352 239 354 244 354 267 352 269 317 268 277 272 255 279 238 289 228 300 224 307 220 319 220 343 222 347 222 351 227 362 234 372 242 379 258 388 271 392 296 394 303 392 310 392 324 387 336 378 342 368 347 363 352 361 354 363 354 391 415 391 416 389 416 242 414 231 405 213 395 202 380 191 363 184 342 180 303 179 284 182 263 191ZM352 301 352 328 346 338 332 350 321 354 305 354 292 350 282 341 279 332 280 321 284 314 291 307 303 302 318 302 330 300 351 300ZM1253 186 1242 191 1233 197 1223 207 1215 222 1212 235 1212 251 1215 264 1219 273 1233 289 1252 300 1275 305 1315 309 1328 314 1334 319 1338 326 1339 331 1338 338 1332 346 1324 351 1311 354 1297 354 1288 352 1277 346 1270 338 1268 331 1210 331 1211 344 1215 355 1221 364 1235 377 1249 385 1270 392 1289 395 1321 395 1341 392 1362 385 1375 377 1387 365 1394 352 1397 337 1396 317 1391 303 1375 283 1361 277 1336 270 1293 265 1279 260 1270 251 1270 248 1268 245 1268 239 1272 231 1282 223 1293 220 1309 220 1318 222 1328 228 1334 235 1336 242 1338 243 1392 243 1393 241 1391 228 1386 216 1378 205 1370 198 1359 191 1335 182 1318 179 1295 178 1276 180ZM1060 184 1047 189 1033 198 1023 209 1017 220 1014 232 1014 254 1015 260 1020 272 1026 281 1032 287 1043 295 1054 300 1077 305 1116 309 1128 313 1138 323 1140 329 1140 335 1137 342 1131 348 1123 352 1113 354 1098 354 1089 352 1078 346 1073 340 1069 331 1012 331 1011 332 1012 342 1017 356 1023 365 1041 380 1064 390 1068 390 1071 392 1077 392 1081 394 1091 395 1132 394 1149 390 1167 383 1175 378 1187 367 1196 350 1198 343 1198 319 1191 301 1187 295 1178 286 1165 278 1142 271 1094 265 1080 260 1073 253 1070 247 1070 237 1076 228 1086 222 1095 220 1111 220 1119 222 1127 226 1134 233 1139 243 1193 243 1194 242 1193 231 1187 215 1174 200 1164 193 1149 186 1136 182 1120 179 1097 178 1077 180 1072 182 1067 182 1064 184ZM758 195 741 184 730 180 720 178 693 179 682 182 668 189 656 199 648 209 642 220 639 222 638 221 638 183 637 182 577 182 577 391 637 391 638 390 638 262 639 255 646 241 654 233 662 228 673 225 684 225 698 230 705 235 712 243 718 258 718 391 779 391 780 390 780 238 778 227 774 216 765 202ZM564 178 554 178 543 180 524 189 511 203 502 221 500 220 500 183 499 182 438 182 438 390 439 391 499 391 500 390 500 258 506 247 512 241 526 233 541 229 550 229 565 233 565 179ZM888 177 869 180 846 189 828 202 817 214 804 236 797 258 797 264 795 269 795 306 799 325 809 349 820 365 835 379 844 385 865 394 887 398 907 398 930 394 950 385 963 376 974 365 984 351 991 337 993 329 992 328 936 328 932 335 923 344 913 350 901 353 887 352 880 350 873 346 861 334 855 321 854 303 855 302 997 302 999 301 1000 297 1000 278 996 253 994 250 991 238 978 215 964 200 948 189 932 182 915 178ZM854 261 857 247 865 235 876 226 891 221 903 221 911 223 922 229 932 239 939 254 939 264 938 265 855 265ZM0 112 0 391 62 391 62 259 64 255 64 251 70 241 82 230 96 225 113 226 122 230 132 238 137 245 141 254 142 259 142 390 143 391 203 391 204 390 204 240 201 224 192 206 177 191 165 184 162 184 154 180 143 178 123 178 106 182 92 189 79 200 70 212 65 222 63 223 62 222 62 112Z"/><path class="hr-b" fill-rule="evenodd" d="M2479 329 2467 335 2459 344 2455 355 2456 372 2462 383 2470 390 2478 394 2484 395 2498 394 2509 388 2516 381 2521 370 2521 353 2516 342 2512 337 2505 332 2494 328ZM1767 182 1767 338 1772 355 1781 370 1795 383 1814 392 1828 395 1854 394 1869 389 1885 379 1895 369 1905 352 1907 351 1908 352 1908 390 1910 391 1969 391 1970 390 1970 182 1909 182 1908 183 1908 316 1904 327 1894 339 1882 346 1875 348 1861 348 1847 342 1835 330 1829 317 1829 183 1828 182ZM2469 178 2459 178 2447 180 2430 188 2416 202 2406 222 2404 221 2404 182 2343 182 2342 183 2342 390 2343 391 2404 391 2404 260 2411 246 2419 239 2430 233 2445 229 2454 229 2469 233ZM1641 178 1614 182 1596 189 1579 200 1563 216 1552 233 1543 257 1540 275 1540 301 1543 320 1552 344 1563 361 1570 369 1591 385 1606 392 1625 397 1650 399 1671 396 1690 390 1709 379 1726 363 1737 347 1746 326 1751 301 1751 277 1746 251 1737 230 1728 216 1712 200 1702 193 1683 184 1672 182 1668 180ZM1639 226 1652 226 1659 228 1673 239 1680 249 1684 258 1687 268 1689 283 1688 303 1686 313 1680 328 1673 338 1665 345 1660 348 1650 351 1641 351 1631 348 1623 343 1616 336 1607 320 1602 297 1603 273 1609 252 1616 241 1624 233ZM1538 178 1518 180 1511 182 1500 188 1489 198 1480 212 1478 218 1475 221 1474 220 1474 182 1413 182 1413 391 1473 391 1474 390 1474 260 1479 249 1489 239 1495 235 1515 229 1524 229 1539 233 1539 179ZM2204 178 2194 180 2191 182 2187 182 2185 184 2182 184 2168 191 2153 202 2136 223 2127 242 2120 271 2120 305 2122 310 2122 316 2131 343 2140 358 2159 378 2169 385 2184 392 2204 397 2233 398 2247 396 2261 392 2275 385 2287 377 2301 363 2308 353 2317 335 2318 329 2317 328 2262 328 2251 342 2238 350 2226 353 2212 352 2196 344 2184 330 2180 319 2180 303 2181 302 2322 302 2325 300 2325 275 2323 260 2318 243 2309 224 2299 210 2280 193 2263 184 2240 178 2231 177ZM2180 255 2184 244 2188 238 2198 228 2208 223 2216 221 2228 221 2243 226 2255 236 2263 250 2265 263 2263 265 2181 265ZM2011 131 2009 132 2009 181 2008 182 1978 182 1977 183 1977 226 2007 226 2009 228 2009 357 2010 363 2016 376 2028 388 2041 394 2106 395 2108 394 2108 350 2107 349 2081 349 2075 346 2071 339 2071 227 2072 226 2109 226 2109 182 2072 182 2071 181 2071 132 2070 131Z"/></g></svg>';

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
const OB_PARTS: [string, number, number, number, number, number][] = [['b-sandbox', 0, 0, 6, 3, 0], ['b-orch', 0, 3, 6, 6, 0], ['b-files', 3, 0, 6, 3, 1], ['b-sessions', 0, 3, 3, 6, 1], ['b-stream', 3, 3, 6, 6, 1], ['b-errors', 3, 0, 6, 3, 2], ['b-trace', 0, 3, 6, 6, 2]];

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
  out += app + label(0, 0, 6, 6, TOP, 1, 'Your app', true) + '</g>';
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
