// Sign-in route: the username is compared without surrounding whitespace, the password exactly.
// The credentials come from the environment (no stored credential file), set before the route is
// loaded because the credential modules read them at import time.
process.env.NEXT_PUBLIC_HR_EDITION = 'selfhost';
process.env.HR_AUTH_USER = 'alice';
process.env.HR_AUTH_PASSWORD = 'pw';
process.env.HR_AUTH_STORE = '/nonexistent/selfhost-auth.json';

import type { NextRequest } from 'next/server';

// eslint-disable-next-line @typescript-eslint/no-require-imports
const { POST } = require('./route') as typeof import('./route');

function login(username: string, password: string): Promise<Response> {
  const req = new Request('http://localhost/api/selfhost/login', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  return POST(Object.assign(req, { nextUrl: new URL(req.url) }) as unknown as NextRequest);
}

test.each(['alice', ' alice ', '\talice\n'])('signs in as %j', async (username) => {
  const res = await login(username, 'pw');
  expect(res.status).toBe(200);
  expect(res.headers.get('set-cookie')).toMatch(/^hr_selfhost=/);
});

test('a wrong password still fails, and a space is not ignored in the password', async () => {
  expect((await login('alice', 'nope')).status).toBe(401);
  expect((await login('alice', ' pw ')).status).toBe(401);
});
