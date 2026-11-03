/** @jest-environment node */
// This relay takes the session cookie, so a plain link to it carries the visitor's login. An agent's HTML
// or SVG file opened through it ran with the console's origin: the relay passed on no sandbox and dropped
// the gateway's own (GHSA-fx92).
jest.mock('undici', () => ({ Agent: class { constructor() { /* no connection pool in a test */ } } }));
jest.mock('@/lib/edition', () => ({ LOCAL_MEMBER: 'owner', LOCAL_ORG: 'local', SELF_HOSTED: true }));
jest.mock('@/lib/selfhost-auth', () => ({ AUTH_DISABLED: false, SESSION_COOKIE: 'hr_session', sessionValid: async () => true }));

import { GET } from './route';
import { PUBLIC_ARTIFACT_CSP } from '@/lib/public-artifact-response';

const originalFetch = global.fetch;
afterEach(() => { global.fetch = originalFetch; });

async function relay(path: string[], upstream: Response) {
  global.fetch = jest.fn().mockResolvedValue(upstream) as unknown as typeof fetch;
  const req = {
    headers: new Headers({ cookie: 'hr_session=s' }),
    cookies: { get: () => undefined },
    nextUrl: { search: '' },
    method: 'GET',
  };
  return GET(req as never, { params: Promise.resolve({ path }) });
}

function expectSandboxed(res: Response) {
  const csp = res.headers.get('content-security-policy') || '';
  const sandbox = csp.split(/[;,]/).map((p) => p.trim()).find((p) => p.startsWith('sandbox'));
  expect(sandbox).toBe('sandbox allow-scripts');
  expect(csp).not.toContain('allow-same-origin');
  expect(csp).toContain("frame-ancestors 'none'");
  expect(res.headers.get('x-content-type-options')).toBe('nosniff');
}

test.each(['text/html', 'image/svg+xml', 'application/xhtml+xml', 'text/xml', 'text/plain', 'application/json'])(
  '%s opened through the relay is sandboxed, never the console origin', async (media) => {
    const res = await relay(['a', 'hsess1', 'page'], new Response('<script>1</script>', { headers: { 'content-type': media } }));
    expect(res.status).toBe(200);
    expect(res.headers.get('content-type')).toBe(media);
    expectSandboxed(res);
  });

test("a shared file keeps the gateway's own sandbox, with ours beside it", async () => {
  const gw = "sandbox allow-scripts; base-uri 'none'";
  const res = await relay(['w', 'h', 'hsess1', 'workspace', 'page.html'],
    new Response('<script>1</script>', { headers: { 'content-type': 'text/html', 'content-security-policy': gw } }));
  expect(res.headers.get('content-security-policy')).toBe(`${gw}, ${PUBLIC_ARTIFACT_CSP}`);
});

test('a PDF still opens in the browser viewer, unframable', async () => {
  const res = await relay(['a', 'hsess1', 'report.pdf'], new Response('%PDF-1.7', { headers: { 'content-type': 'application/pdf' } }));
  expect(res.headers.get('content-security-policy')).toBe("frame-ancestors 'none'");
  expect(res.headers.get('x-content-type-options')).toBe('nosniff');
});

test('a live event stream is sandboxed too', async () => {
  const res = await relay(['v1', 'responses'], new Response('data: {}\n\n', { headers: { 'content-type': 'text/event-stream' } }));
  expect(res.headers.get('content-type')).toBe('text/event-stream');
  expectSandboxed(res);
});
