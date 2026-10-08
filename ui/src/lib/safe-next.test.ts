import { safeNext } from './safe-next';

// GHSA-59mq-hx4p-fw48: a sign-in link must not be able to send the person to another site.
test.each([
  ['https://evil.example/'],
  ['http://evil.example'],
  ['javascript:alert(1)'],
  ['data:text/html,hi'],
  ['evil.example'],
  ['//evil.example'],
  ['//evil.example/harnesses'],
  ['/\\evil.example'],
  ['\\\\evil.example'],
  ['/\\/evil.example'],
  ['/%2F%2Fevil.example'],
  ['/%2fevil.example'],
  ['/%5Cevil.example'],
  ['/%5cevil.example'],
  ['/\t/evil.example'],
  ['/\n/evil.example'],
  ['/\r//evil.example'],
  [' /harnesses'],
  [''],
])('%j is refused for the default', (raw) => {
  expect(safeNext(raw)).toBe('/harnesses');
});

test.each([
  ['/harnesses', '/harnesses'],
  ['/kits?tab=sheets', '/kits?tab=sheets'],
  ['/harnesses/chrn_abc#settings', '/harnesses/chrn_abc#settings'],
  ['/plugins?q=a%20b', '/plugins?q=a%20b'],
])('%j, a path on this site, is kept', (raw, want) => {
  expect(safeNext(raw)).toBe(want);
});

test('what the middleware writes survives the round trip', () => {
  const pathname = '/harnesses/chrn_abc';
  const search = '?view=tasks';
  const link = `/login?next=${encodeURIComponent(pathname + search)}`;
  const next = new URLSearchParams(link.split('?')[1]).get('next');
  expect(safeNext(next)).toBe(pathname + search);
});

test('nothing at all, and a custom default', () => {
  expect(safeNext(null)).toBe('/harnesses');
  expect(safeNext(undefined, '/quickstart')).toBe('/quickstart');
});
