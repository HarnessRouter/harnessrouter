/** @jest-environment node */
// /data/workspaces/<session>/<path>: a task's file by the path the agent wrote. The session id goes into the
// gateway URL this route builds, and fetch() resolves '.' and '..' in it, so a session id of '..' carried the
// relay to another gateway route with the box's key. Every segment is checked first, by the rule the console's
// API proxy keeps (lib/relay-path), and a session id is a name, never a path; a refusal fetches nothing.
const mockEdition = { selfHosted: true };
jest.mock('@/lib/edition', () => ({ get SELF_HOSTED() { return mockEdition.selfHosted; }, LOCAL_ORG: 'local', LOCAL_MEMBER: 'local@localhost' }));
process.env.HARNESS_INTERNAL_KEY = 'internal-key';
export {};   // a module, so its helpers don't meet other test files' in the global scope

// eslint-disable-next-line @typescript-eslint/no-require-imports
const { GET } = require('./route') as typeof import('./route');

let urls: string[] = [];
beforeEach(() => {
  urls = [];
  global.fetch = jest.fn(async (url: string) => {
    urls.push(String(url));
    if (String(url).endsWith('/files')) {
      return new Response(JSON.stringify({ files: [{ id: 'wf_1', path: 'deliverables/report.xlsx', filename: 'report.xlsx', media_type: 'text/plain' }] }),
        { status: 200, headers: { 'content-type': 'application/json' } });
    }
    return new Response('bytes', { status: 200, headers: { 'content-type': 'text/plain' } });
  }) as unknown as typeof fetch;
});
const asNext = (raw: string) => raw.split('/').map(decodeURIComponent);
const call = (sid: string, raw: string) => GET({ headers: new Headers() } as never,
  { params: Promise.resolve({ sid: decodeURIComponent(sid), path: asNext(raw) }) });

test.each(['%2e%2e', '..', '.%2e', '.', 'a%2Fb', '..%2f..%2fv1', 'a%5cb', '', '%20x', 'x%09'])('the session %p is a 404 and nothing is fetched', async (sid) => {
  const res = await call(sid, 'deliverables/report.xlsx');
  expect(res.status).toBe(404);
  expect(global.fetch).not.toHaveBeenCalled();
});

test.each(['..%2f..%2fx', '%2e%2e/x', 'a/../x', 'a%5cb', 'a//b', '%2Fx', 'x%2F', 'x%20', 'a%00b'])('the path %p is a 404 and nothing is fetched', async (raw) => {
  const res = await call('hsess_1', raw);
  expect(res.status).toBe(404);
  expect(global.fetch).not.toHaveBeenCalled();
});

test('a nested path opens, written with slashes or with one encoded inside a name', async () => {
  for (const raw of ['deliverables/report.xlsx', 'deliverables%2Freport.xlsx']) {
    const res = await call('hsess_1', raw);
    expect(res.status).toBe(200);
    expect(await res.text()).toBe('bytes');
  }
  expect(urls.map((u) => new URL(u).pathname)).toEqual(['/v1/sessions/hsess_1/files', '/v1/containers/hsess_1/files/wf_1/content',
    '/v1/sessions/hsess_1/files', '/v1/containers/hsess_1/files/wf_1/content']);
});

// The same fixed point as the API proxy (lib/relay-path): a dot or a slash encoded more than once is
// checked fully decoded, and escapes that are not UTF-8 are refused.
test.each([['%25252e%25252e', 'x'], ['hsess_1', '%25252e%25252e/x'], ['hsess_1', 'a%25252f%25252e%25252e'],
  ['%25E0%25A4%25A', 'x'], ['hsess_1', '%2525252525252e']])('the session %p with the path %p is a 404 and nothing is fetched', async (sid, raw) => {
  const res = await call(sid, raw);
  expect(res.status).toBe(404);
  expect(global.fetch).not.toHaveBeenCalled();
});
