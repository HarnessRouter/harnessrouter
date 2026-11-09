/** @jest-environment node */
// The task's file address, /{harness}/{session}/workspace/{path} (#594). It relayed to the gateway's
// PUBLIC read, which answers only for a shared task, so a reply's link opened "file not found" for the
// person who made the task, signed in to their own box. On a self-hosted box the console's own session
// cookie is the sign-in (the same one /api/harness and /data/workspaces take): with it, the file is
// read as the box's member through the signed-in read by path. Without it, and on the hosted console,
// where this address carries no sign-in at all, it is the public read exactly as before.
const mockEdition = { selfHosted: true, authDisabled: false };
jest.mock('@/lib/edition', () => ({
  get SELF_HOSTED() { return mockEdition.selfHosted; }, LOCAL_ORG: 'local', LOCAL_MEMBER: 'local@localhost',
}));
jest.mock('@/lib/selfhost-auth', () => ({
  get AUTH_DISABLED() { return mockEdition.authDisabled; },
  SESSION_COOKIE: 'hr_selfhost',
  sessionValid: async (t?: string) => t === 'signed-in',
}));

process.env.HARNESS_GATEWAY_URL = 'http://gateway.test';
process.env.HARNESS_INTERNAL_KEY = 'internal-key';

type Sent = { url: string; headers: Record<string, string> };
let sent: Sent[] = [];
beforeEach(() => {
  sent = [];
  mockEdition.selfHosted = true;
  mockEdition.authDisabled = false;
  global.fetch = jest.fn(async (url: string, init: { headers?: Record<string, string> } = {}) => {
    sent.push({ url: String(url), headers: { ...(init.headers || {}) } });
    return new Response('deck', { status: 200, headers: {
      'content-type': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
      'content-disposition': 'inline; filename="hello-world.pptx"', 'cache-control': 'private, max-age=60' } });
  }) as unknown as typeof fetch;
});

function call(GET: (req: never, ctx: never) => Promise<Response>, cookie = '', headers: Record<string, string> = {}) {
  const req = {
    headers: new Headers({ ...headers, cookie }),
    cookies: { get: (n: string) => { const m = cookie.match(new RegExp(`(?:^|; )${n}=([^;]*)`)); return m ? { value: decodeURIComponent(m[1]) } : undefined; } },
  };
  return GET(req as never, { params: Promise.resolve({ harness: 'chrn_1', sid: 'hsess_1', fpath: ['out', 'hello world.pptx'] }) } as never);
}

const PUBLIC = 'http://gateway.test/w/chrn_1/hsess_1/workspace/out/hello%20world.pptx';
const SIGNED_IN = 'http://gateway.test/a/hsess_1/out/hello%20world.pptx';

// eslint-disable-next-line @typescript-eslint/no-require-imports
const route = () => require('./route') as typeof import('./route');

test('signed in to a self-hosted box, the file is read as its member, whether or not the task is shared', async () => {
  const res = await call(route().GET, 'hr_selfhost=signed-in');
  expect(res.status).toBe(200);
  expect(sent).toHaveLength(1);
  expect(sent[0].url).toBe(SIGNED_IN);
  expect(sent[0].headers).toEqual({ 'x-harness-internal': 'internal-key', 'x-harness-org': 'local', 'x-harness-member': 'local@localhost' });
  // what an agent wrote never runs with the console's origin, and a signed-in read is never cached
  expect(res.headers.get('content-security-policy')).toContain('sandbox allow-scripts');
  expect(res.headers.get('content-security-policy')).not.toContain('allow-same-origin');
  expect(res.headers.get('cache-control')).toBe('private, no-store');
  expect(res.headers.get('content-disposition')).toBe('inline; filename="hello-world.pptx"');
});

test('a self-hosted box with its sign-in switched off reads as its member, as /api/harness does', async () => {
  mockEdition.authDisabled = true;
  await call(route().GET);
  expect(sent[0].url).toBe(SIGNED_IN);
});

test('no sign-in, or one that does not verify: the public read, with nothing of ours attached', async () => {
  for (const cookie of ['', 'hr_selfhost=forged', 'hr_auth=a.jwt.here']) {
    sent = [];
    const res = await call(route().GET, cookie, { 'x-harness-internal': 'guess', 'x-harness-org': 'local', authorization: 'Bearer x' });
    expect(res.status).toBe(200);
    expect(sent).toHaveLength(1);
    expect(sent[0].url).toBe(PUBLIC);
    expect(sent[0].headers).toEqual({});
    expect(res.headers.get('content-security-policy')).toContain('sandbox allow-scripts');
  }
});

test('the hosted console takes no cookie here: always the public read', async () => {
  mockEdition.selfHosted = false;
  for (const cookie of ['hr_selfhost=signed-in', 'hr_auth=a.jwt.here']) {
    sent = [];
    await call(route().GET, cookie, { authorization: 'Bearer a.jwt.here' });
    expect(sent[0].url).toBe(PUBLIC);
    expect(sent[0].headers).toEqual({});
  }
});

test('a box with no internal key cannot sign a read: the public read', async () => {
  const before = process.env.HARNESS_INTERNAL_KEY;
  delete process.env.HARNESS_INTERNAL_KEY;
  try {
    let GET: typeof import('./route').GET | undefined;
    jest.isolateModules(() => { GET = route().GET; });
    await call(GET as never, 'hr_selfhost=signed-in');
    expect(sent[0].url).toBe(PUBLIC);
    expect(sent[0].headers).toEqual({});
  } finally {
    process.env.HARNESS_INTERNAL_KEY = before;
  }
});

test('a gateway that cannot be reached is a 502 in the same sandbox', async () => {
  global.fetch = jest.fn(async () => { throw new Error('down'); }) as unknown as typeof fetch;
  const res = await call(route().GET, 'hr_selfhost=signed-in');
  expect(res.status).toBe(502);
  expect(res.headers.get('content-security-policy')).toContain('sandbox allow-scripts');
});
