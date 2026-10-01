// The console's proxy must outlast the gateway's own hour-long read of a synchronous turn. It
// allowed 800 s until 2026-09-30, and every synchronous turn longer than 13.4 minutes came back
// 502 while the runner kept working (a customer benchmark). Pinned on the source: the route
// segment config has to be a literal.
const fs = require('fs');
const path = require('path');

test('the harness proxy allows at least the gateway hour', () => {
  const src = fs.readFileSync(path.join(__dirname, '[...path]', 'route.ts'), 'utf8');
  const m = src.match(/export const maxDuration = (\d+);/);
  expect(m).not.toBeNull();
  expect(Number(m[1])).toBeGreaterThanOrEqual(3600);
  expect(src).toMatch(/headersTimeout: maxDuration \* 1000, bodyTimeout: maxDuration \* 1000/);
});
