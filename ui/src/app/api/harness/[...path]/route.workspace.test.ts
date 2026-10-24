/** @jest-environment node */
// A kit app (served at /kits/<id> on this origin) sends no workspace of its own, so the proxy takes the
// active workspace from the cookie the console keeps (lib/workspace.tsx). Without it a kit app listed
// every workspace's harnesses and ran another workspace's (Super Mario, 10-22). A request that names its
// workspace keeps it, and a cookie that is not a workspace id is not sent on.
jest.mock('undici', () => ({ Agent: class { constructor() { /* no connection pool in a test */ } } }));
jest.mock('@/lib/edition', () => ({ LOCAL_MEMBER: 'owner', LOCAL_ORG: 'local', SELF_HOSTED: true }));
jest.mock('@/lib/selfhost-auth', () => ({ AUTH_DISABLED: false, SESSION_COOKIE: 'hr_session', sessionValid: async () => true }));

import { GET } from './route';

type Sent = { url: string; headers: Record<string, string> };
let sent: Sent[] = [];
beforeEach(() => {
  sent = [];
  global.fetch = jest.fn(async (url: string, init: { headers: Record<string, string> }) => {
    sent.push({ url: String(url), headers: init.headers });
    return new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } });
  }) as unknown as typeof fetch;
});

function call(cookie: string, headers: Record<string, string> = {}) {
  const req = {
    headers: new Headers({ ...headers, cookie }),
    cookies: { get: (n: string) => { const m = cookie.match(new RegExp(`(?:^|; )${n}=([^;]*)`)); return m ? { value: decodeURIComponent(m[1]) } : undefined; } },
    nextUrl: { search: '' },
    method: 'GET',
  };
  return GET(req as never, { params: Promise.resolve({ path: ['v1', 'harnesses'] }) });
}

test('a kit app\'s request is scoped to the workspace the console has open', async () => {
  await call('hr_session=s; hr_workspace=default-workspace-2');
  expect(sent[0].headers['x-harness-workspace']).toBe('default-workspace-2');
  expect(sent[0].headers['x-harness-workspace-default']).toBeUndefined();
  await call('hr_session=s; hr_workspace=default%7C1');
  expect(sent[1].headers['x-harness-workspace']).toBe('default');
  expect(sent[1].headers['x-harness-workspace-default']).toBe('1');
});

test('a request that names its workspace keeps it', async () => {
  await call('hr_session=s; hr_workspace=default-workspace-2', { 'x-harness-workspace': 'research' });
  expect(sent[0].headers['x-harness-workspace']).toBe('research');
});

test('no cookie, or a cookie that is not a workspace id, sends no workspace', async () => {
  await call('hr_session=s');
  expect(sent[0].headers['x-harness-workspace']).toBeUndefined();
  await call('hr_session=s; hr_workspace=a%20b%0Ax');
  expect(sent[1].headers['x-harness-workspace']).toBeUndefined();
});
