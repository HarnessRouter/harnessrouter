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

type Params = { harness: string; sid: string; fpath: string[] };
const FILE: Params = { harness: 'chrn_1', sid: 'hsess_1', fpath: ['out', 'hello world.pptx'] };
function call(GET: (req: never, ctx: never) => Promise<Response>, cookie = '', headers: Record<string, string> = {}, params: Params = FILE) {
  const req = {
    headers: new Headers({ ...headers, cookie }),
    cookies: { get: (n: string) => { const m = cookie.match(new RegExp(`(?:^|; )${n}=([^;]*)`)); return m ? { value: decodeURIComponent(m[1]) } : undefined; } },
  };
  return GET(req as never, { params: Promise.resolve(params) } as never);
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

// CAT's review of #594: fetch() resolves '.' and '..' in the URL it is given, and encodeURIComponent
// leaves both as they are, so a segment of '..' moved the relay to another gateway route (with the
// box's key on the signed-in branch). Every segment is checked as Next hands it over, decoded once,
// and a refused address is the gateway's own 404 for a missing file, before anything is fetched.
describe('an address that is not plain names is refused before the gateway is asked', () => {
  /** a raw address segment run as Next hands it to the route: split on '/', each part decoded once */
  const asNext = (raw: string) => raw.split('/').map(decodeURIComponent);
  const BAD = ['%2e%2e/%2e%2e/v1/internal/x', '..%2f..%2fv1%2finternal', 'a%2fb', 'a%5cb', 'dir//file.txt', '../../v1/x', '.%2e/x', './x'];
  const BAD_SID = ['%2e%2e', '..%2f..%2fv1', 'a%2fb', 'a%5cb', '', '..'];
  const refused = async (res: Response) => {
    expect(res.status).toBe(404);
    expect(await res.json()).toEqual({ error: { type: 'invalid_request_error', code: 'not_found', message: 'file not found', param: null, detail: null }, detail: 'file not found' });
    expect(res.headers.get('content-security-policy')).toContain('sandbox allow-scripts');
    expect(res.headers.get('cache-control')).toBe('private, no-store');
  };

  for (const cookie of ['hr_selfhost=signed-in', '']) {
    const who = cookie ? 'signed in' : 'not signed in';
    test.each(BAD)(`${who}: the file path %p is a 404 and nothing is fetched`, async (raw) => {
      await refused(await call(route().GET, cookie, {}, { harness: 'chrn_1', sid: 'hsess_1', fpath: asNext(raw) }));
      expect(global.fetch).not.toHaveBeenCalled();
    });
    test.each(BAD_SID)(`${who}: the session %p is a 404 and nothing is fetched`, async (raw) => {
      await refused(await call(route().GET, cookie, {}, { harness: 'chrn_1', sid: decodeURIComponent(raw), fpath: ['file.txt'] }));
      expect(global.fetch).not.toHaveBeenCalled();
    });
    test(`${who}: a harness of '..' is a 404 and nothing is fetched`, async () => {
      await refused(await call(route().GET, cookie, {}, { harness: '..', sid: 'hsess_1', fpath: ['file.txt'] }));
      expect(global.fetch).not.toHaveBeenCalled();
    });
  }

  test('a nested path still opens, signed in and not', async () => {
    await call(route().GET, 'hr_selfhost=signed-in', {}, { harness: 'chrn_1', sid: 'hsess_1', fpath: asNext('dir/sub/file.txt') });
    await call(route().GET, '', {}, { harness: 'chrn_1', sid: 'hsess_1', fpath: asNext('dir/sub/file.txt') });
    expect(sent.map((x) => x.url)).toEqual(['http://gateway.test/a/hsess_1/dir/sub/file.txt',
      'http://gateway.test/w/chrn_1/hsess_1/workspace/dir/sub/file.txt']);
  });

  // CAT, via the pentest session (LOW): the check read a segment as Next hands it over, decoded once, so a dot
  // encoded twice or more (%252e%252e arrives as %2e%2e) passed it. This route re-encodes every segment, so
  // nothing reached another route, but the guard holds on its own now: each segment is checked decoded to a
  // fixed point (at most five rounds), and one still changing after five, or not UTF-8, is refused.
  const DEEP = ['%252e%252e/x', '%25252e%25252e/x', '%2525252e%2525252e/internal/x', '%25252e%25252e/internal/x',
    'a%25252fb', '%25255cb', '%2525252525252e', '%25E0%25A4%25A', '%25C0%25AE%25C0%25AE'];
  for (const cookie of ['hr_selfhost=signed-in', '']) {
    test.each(DEEP)(`${cookie ? 'signed in' : 'not signed in'}: the file path %p, decoded to a fixed point, is a 404 and nothing is fetched`, async (raw) => {
      await refused(await call(route().GET, cookie, {}, { harness: 'chrn_1', sid: 'hsess_1', fpath: asNext(raw) }));
      expect(global.fetch).not.toHaveBeenCalled();
    });
    test(`${cookie ? 'signed in' : 'not signed in'}: a session encoded three times as '..' is a 404 and nothing is fetched`, async () => {
      await refused(await call(route().GET, cookie, {}, { harness: 'chrn_1', sid: decodeURIComponent('%25252e%25252e'), fpath: ['file.txt'] }));
      expect(global.fetch).not.toHaveBeenCalled();
    });
  }

  test('a space, dots and a bare % inside a name still open, sent as before', async () => {
    await call(route().GET, 'hr_selfhost=signed-in', {}, { harness: 'chrn_1', sid: 'hsess_1', fpath: asNext('out/report%20v2..final%25.pptx') });
    await call(route().GET, '', {}, { harness: 'chrn_1', sid: 'hsess_1', fpath: asNext('50%25%20off.pdf') });
    expect(sent.map((x) => x.url)).toEqual(['http://gateway.test/a/hsess_1/out/report%20v2..final%25.pptx',
      'http://gateway.test/w/chrn_1/hsess_1/workspace/50%25%20off.pdf']);
  });
});
