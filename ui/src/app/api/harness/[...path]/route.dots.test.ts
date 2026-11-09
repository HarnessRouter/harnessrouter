/** @jest-environment node */
// fetch() resolves '.' and '..' in the URL it is handed (also written %2e), and takes a backslash for a slash.
// This proxy joins the path's segments as Next decodes them, so '..%2finternal%2fx' (one segment, decoded
// to '../internal/x') or '%2e%2e' carried a call to another of the gateway's routes, the hosted edition's
// /internal/* block among them, which looked only at the first segment as written. A segment the gateway
// could read as another path is refused before anything is fetched, the rule the hosted console's proxy
// has kept since 11-05; a name with a slash or a space inside it still passes, as the file routes need.
jest.mock('undici', () => ({ Agent: class { constructor() { /* no connection pool in a test */ } } }));
const mockEdition = { selfHosted: false };
jest.mock('@/lib/edition', () => ({ get SELF_HOSTED() { return mockEdition.selfHosted; }, LOCAL_ORG: 'local', LOCAL_MEMBER: 'local@localhost' }));
jest.mock('@/lib/selfhost-auth', () => ({ AUTH_DISABLED: false, SESSION_COOKIE: 'hr_selfhost', sessionValid: async () => true }));

import { GET } from './route';

let urls: string[] = [];
beforeEach(() => {
  urls = [];
  mockEdition.selfHosted = false;
  global.fetch = jest.fn(async (url: string) => {
    urls.push(String(url));
    return new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } });
  }) as unknown as typeof fetch;
});
/** an address as Next hands it to the route: split on '/', each part decoded once */
const asNext = (raw: string) => raw.split('/').map(decodeURIComponent);
function call(raw: string) {
  const req = {
    headers: new Headers({ authorization: 'Bearer a.b.c', cookie: 'hr_selfhost=s' }),
    cookies: { get: (n: string) => (n === 'hr_selfhost' ? { value: 's' } : undefined) },
    nextUrl: { search: '' },
    method: 'GET',
  };
  return GET(req as never, { params: Promise.resolve({ path: asNext(raw) }) });
}
const sent = () => urls.map((u) => new URL(u).pathname);
const refused = async (res: Response) => {
  expect(res.status).toBe(404);
  expect(await res.json()).toEqual({ detail: 'not found' });
  expect(res.headers.get('x-content-type-options')).toBe('nosniff');
  expect(global.fetch).not.toHaveBeenCalled();
};

// refused in both editions, before anything is fetched
const ODD = [
  'v1/..%2finternal%2fx',            // CAT: one segment, decoded '../internal/x'
  '%2e%2e/internal/x',               // CAT
  'v1/%2e%2e/internal/x', 'v1/.%2e/internal/x', 'v1/../internal/x', 'v1/./internal',
  'v1/%252e%252e/internal/x',        // decoded once to '%2e%2e', which fetch() still reads as '..'
  'v1/sessions/s/files/a%2F..%2F..%2F..%2Finternal%2Fx',
  'v1/a%5cb', 'v1/%2Fx', 'v1/x%2F', 'v1/%20x', 'v1/x%20', 'v1/a%09b', 'v1/a%00b', 'v1//x',
];
for (const edition of ['hosted', 'self-hosted']) {
  test.each(ODD)(`${edition}: %p is a 404 and nothing is fetched`, async (raw) => {
    mockEdition.selfHosted = edition === 'self-hosted';
    await refused(await call(raw));
  });
}

// the hosted console never forwards the gateway's /internal/*, however its first segment is written
test.each(['internal/x', 'internal%2Fconnections', '%2569nternal/x'])('hosted: %p is a 404 and nothing is fetched', async (raw) => {
  await refused(await call(raw));
});

test('a self-hosted box still reaches its own /internal/* (its signed-in operator may)', async () => {
  mockEdition.selfHosted = true;
  expect((await call('internal/x')).status).toBe(200);
  expect(sent()).toEqual(['/internal/x']);
});

test('a name with a slash, a space or dots inside it still passes, as the file routes need', async () => {
  for (const raw of ['v1/sessions/hsess_1/files/dir%2Fsub%2Freport%20v2.pdf', 'v1/environments/env_1/files/a%2Fb.txt',
    'v1/sessions/hsess_1/files/dir/sub/notes..md', 'v1/memories/hmem_1/records/rec.1', 'v1/harnesses/chrn_1']) {
    expect((await call(raw)).status).toBe(200);
  }
  expect(sent()).toEqual(['/v1/sessions/hsess_1/files/dir/sub/report%20v2.pdf', '/v1/environments/env_1/files/a/b.txt',
    '/v1/sessions/hsess_1/files/dir/sub/notes..md', '/v1/memories/hmem_1/records/rec.1', '/v1/harnesses/chrn_1']);
});
