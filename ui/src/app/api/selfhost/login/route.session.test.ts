/** @jest-environment node */
import { webcrypto } from 'node:crypto';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { NextRequest } from 'next/server';

const password = ' password with spaces ';
const env = { ...process.env };
const cryptoDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'crypto');
const store = mkdtempSync(join(tmpdir(), 'harnessrouter-login-'));
let POST: typeof import('./route').POST;
let sessionValid: typeof import('@/lib/selfhost-auth').sessionValid;

beforeAll(async () => {
  process.env.NEXT_PUBLIC_HR_EDITION = 'selfhost';
  process.env.HR_AUTH_DISABLED = '0';
  process.env.HR_AUTH_USER = 'alice';
  process.env.HR_AUTH_PASSWORD = password;
  process.env.HR_AUTH_STORE = join(store, 'credentials.json');
  delete process.env.HR_SESSION_KEY;
  Object.defineProperty(globalThis, 'crypto', { value: webcrypto, configurable: true });
  jest.resetModules();
  ({ POST } = await import('./route'));
  ({ sessionValid } = await import('@/lib/selfhost-auth'));
});

afterAll(() => {
  process.env = env;
  if (cryptoDescriptor) Object.defineProperty(globalThis, 'crypto', cryptoDescriptor);
  else Reflect.deleteProperty(globalThis, 'crypto');
  rmSync(store, { recursive: true, force: true });
});

const signIn = (username: string, suppliedPassword = password) => POST(new NextRequest(
  'https://instance.example/api/selfhost/login',
  { method: 'POST', body: JSON.stringify({ username, password: suppliedPassword }) },
));

test.each(['alice', ' alice ', '\talice\t'])('%j signs in with a valid session', async (username) => {
  const response = await signIn(username);
  expect(response.status).toBe(200);
  expect(await response.json()).toEqual({ ok: true });
  const cookie = response.headers.get('set-cookie');
  expect(cookie).toContain('; HttpOnly; SameSite=Lax; Secure');
  expect(await sessionValid(cookie!.split(';')[0].split('=')[1])).toBe(true);
});

test.each([
  ['alice', password.trim()],
  ['bob', password],
  ['   ', password],
])('invalid credentials %j are still rejected', async (username, suppliedPassword) => {
  const response = await signIn(username, suppliedPassword);
  expect(response.status).toBe(401);
  expect(await response.json()).toEqual({ detail: 'Incorrect username or password.' });
  expect(response.headers.get('set-cookie')).toBeNull();
});
