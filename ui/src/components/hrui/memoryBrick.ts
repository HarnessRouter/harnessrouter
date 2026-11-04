// The Memory part's brick. Every other part is a square brick with a stud, because they snap on: this one is what
// the stack keeps, so it's drawn as what keeps things, a round drum of stacked discs with the Memories mark on its
// top, in the same isometric projection and the same light (the left and right halves take the faces' classes).
type Project = (x: number, y: number, z: number) => [number, number];

/** Its radius on the plan: as wide across as a square brick looks, and clear of the four corner slots beside it. */
export const MEMORY_R = 1.25;
const f = (v: number) => v.toFixed(1);

export function memoryDrum(P: Project, u: number, cx: number, cy: number, z0: number, z1: number): string {
  // a circle on the plan, in this projection: the ellipse every stud is
  const rx = 1.2247 * MEMORY_R * u, ry = 0.7071 * MEMORY_R * u, a = MEMORY_R / Math.SQRT2;
  [z0, z1].forEach((z) => { P(cx + a, cy - a, z); P(cx - a, cy + a, z); P(cx + a, cy + a, z); P(cx - a, cy - a, z); });
  const [x, yT] = P(cx, cy, z1), [, yB] = P(cx, cy, z0);
  const L = x - rx, R = x + rx;
  const arc = (y: number) => `A${f(rx)} ${f(ry)} 0 0 0 ${f(x)} ${f(y + ry)}`, arcR = (y: number) => `A${f(rx)} ${f(ry)} 0 0 0 ${f(R)} ${f(y)}`;
  let g = `<path class="l" d="M${f(L)} ${f(yT)}${arc(yT)}L${f(x)} ${f(yB + ry)}A${f(rx)} ${f(ry)} 0 0 1 ${f(L)} ${f(yB)}Z"/>`
    + `<path class="r" d="M${f(x)} ${f(yT + ry)}${arcR(yT)}L${f(R)} ${f(yB)}A${f(rx)} ${f(ry)} 0 0 1 ${f(x)} ${f(yB + ry)}Z"/>`;
  // the discs it's made of, each half a brick high
  for (let z = z0 + 0.5; z < z1 - 1e-6; z += 0.5) {
    const y = P(cx, cy, z)[1];
    g += `<path class="dk" d="M${f(L)} ${f(y)}${arc(y)}${arcR(y)}"/>`;
  }
  g += `<ellipse class="t" cx="${f(x)}" cy="${f(yT)}" rx="${f(rx)}" ry="${f(ry)}"/><path class="hl" d="M${f(L)} ${f(yT)}${arc(yT)}${arcR(yT)}"/>`;
  // the Memories mark, lying on the top: three points and what joins them
  const n = [[-0.55, -0.55], [-0.2, 0.8], [0.8, -0.2]].map(([dx, dy]) => P(cx + dx, cy + dy, z1));
  const ln = (p: [number, number], q: [number, number]) => `<line class="mk" x1="${f(p[0])}" y1="${f(p[1])}" x2="${f(q[0])}" y2="${f(q[1])}"/>`;
  g += ln(n[0], n[1]) + ln(n[0], n[2]) + ln(n[1], n[2]);
  n.forEach((p) => { g += `<ellipse class="mkd" cx="${f(p[0])}" cy="${f(p[1])}" rx="${f(0.2 * u)}" ry="${f(0.12 * u)}"/>`; });
  return g;
}
