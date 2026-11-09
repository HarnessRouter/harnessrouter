/** @jest-environment node */
// The public share relay, /api/share/* -> the gateway's /share/*. fetch() resolves '.' and '..' in the
// URL it is given, and encodeURIComponent leaves both as they are, so a token or a file name of '..'
// carried this relay, open to anyone, to another of the gateway's routes. Every segment is checked as
// Next hands it over (decoded once), and a refused address is the gateway's own 404, before anything
// is fetched. Every file a share page opens comes through here (#594).
import { GET } from './route';

let urls: string[] = [];
beforeEach(() => {
  urls = [];
  global.fetch = jest.fn(async (url: string) => {
    urls.push(String(url));
    return new Response('bytes', { status: 200, headers: { 'content-type': 'text/plain' } });
  }) as unknown as typeof fetch;
});
const asNext = (raw: string) => raw.split('/').map(decodeURIComponent);
const call = (raw: string) => GET({} as never, { params: Promise.resolve({ path: asNext(raw) }) });
const body = (message: string) => ({ error: { type: 'invalid_request_error', code: 'not_found', message, param: null, detail: null }, detail: message });

test.each([
  ['shr1/f/%2e%2e/%2e%2e/%2e%2e/v1/internal/x', 'file not found'],
  ['shr1/f/..%2f..%2f..%2fv1%2fx', 'file not found'],
  ['shr1/f/a%2fb', 'file not found'],
  ['shr1/f/a%5cb', 'file not found'],
  ['shr1/f/dir//file.txt', 'file not found'],
  ['shr1/f/../../v1/x', 'file not found'],
  ['%2e%2e/%2e%2e/v1/internal/x', 'share not found'],
  ['..%2f..%2fv1%2fsessions', 'share not found'],
  ['../meta', 'share not found'],
  ['shr1/%2e%2e/%2e%2e/v1/x', 'share not found'],
  // decoded to a fixed point (CAT, via the pentest session): a dot encoded more than once is still a dot
  ['shr1/f/%252e%252e', 'file not found'],
  ['shr1/f/%25252e%25252e/x', 'file not found'],
  ['shr1/f/%2525252e%2525252e/internal/x', 'file not found'],
  ['%25252e%25252e/internal/x', 'share not found'],
  ['shr1/f/%2525252525252e', 'file not found'],
  ['shr1/f/%25E0%25A4%25A', 'file not found'],
])('%p is a 404 and nothing is fetched', async (raw, message) => {
  const res = await call(raw);
  expect(res.status).toBe(404);
  expect(await res.json()).toEqual(body(message));
  expect(res.headers.get('cache-control')).toBe('private, no-store');
  expect(global.fetch).not.toHaveBeenCalled();
});

test('a refused file read keeps the artifact sandbox', async () => {
  const res = await call('shr1/f/..%2fx');
  expect(res.headers.get('content-security-policy')).toContain('sandbox allow-scripts');
});

test('a nested file, a name with a space, dots and a bare %, the meta and the files list still reach the share', async () => {
  for (const raw of ['shr1/f/dir/sub/file.txt', 'shr1/meta', 'shr1/files', 'shr1/f/report%20v2..final%25.pptx']) {
    expect((await call(raw)).status).toBe(200);
  }
  expect(urls.map((u) => new URL(u).pathname)).toEqual(['/share/shr1/f/dir/sub/file.txt', '/share/shr1/meta',
    '/share/shr1/files', '/share/shr1/f/report%20v2..final%25.pptx']);
});
