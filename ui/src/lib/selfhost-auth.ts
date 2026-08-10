// The self-hosted session: one operator, one password, a signed cookie.
//
// Runs in middleware (the Edge runtime), so it uses Web Crypto rather than node:crypto — the same
// primitives are available, and keeping one implementation means the cookie is minted and verified
// by identical code.
//
// The cookie carries an expiry and an HMAC over it, signed with the password. Two consequences,
// both wanted: nothing is stored server-side, so a restart doesn't sign anyone out unexpectedly;
// and CHANGING THE PASSWORD INVALIDATES EVERY EXISTING SESSION, because the old signature can no
// longer be verified. That is the behaviour you want from a password change.
export const SESSION_COOKIE = 'hr_selfhost';
const VERSION = 'v1';

export const AUTH_USER = process.env.HR_AUTH_USER || 'harnessrouter';
export const AUTH_PASSWORD = process.env.HR_AUTH_PASSWORD || 'harnessrouter';
export const AUTH_DISABLED = process.env.HR_AUTH_DISABLED === '1';
export const SELF_HOSTED = process.env.NEXT_PUBLIC_HR_EDITION === 'selfhost';

/** How long a session lasts. Long enough not to be a nuisance on a box you use daily. */
export const SESSION_TTL_MS = 7 * 24 * 60 * 60 * 1000;

const enc = new TextEncoder();

async function hmac(message: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    'raw', enc.encode(`hr-selfhost:${AUTH_PASSWORD}`),
    { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'],
  );
  const sig = await crypto.subtle.sign('HMAC', key, enc.encode(message));
  return Array.from(new Uint8Array(sig)).map((b) => b.toString(16).padStart(2, '0')).join('');
}

/** Length-independent comparison. A plain === leaks how much of a secret was right via timing. */
export function sameSecret(a: string, b: string): boolean {
  const x = enc.encode(a);
  const y = enc.encode(b);
  let diff = x.length ^ y.length;
  const n = Math.max(x.length, y.length);
  for (let i = 0; i < n; i++) diff |= (x[i] ?? 0) ^ (y[i] ?? 0);
  return diff === 0;
}

export function credentialsValid(user: string, password: string): boolean {
  // Both are always checked, so a wrong username costs the same as a wrong password.
  const okUser = sameSecret(user, AUTH_USER);
  const okPass = sameSecret(password, AUTH_PASSWORD);
  return okUser && okPass;
}

export async function mintSession(): Promise<string> {
  const expires = Date.now() + SESSION_TTL_MS;
  const body = `${VERSION}.${expires}`;
  return `${body}.${await hmac(body)}`;
}

export async function sessionValid(token: string | undefined): Promise<boolean> {
  if (!token) return false;
  const parts = token.split('.');
  if (parts.length !== 3 || parts[0] !== VERSION) return false;
  const [, expiresRaw, sig] = parts;
  const expires = Number(expiresRaw);
  if (!Number.isFinite(expires) || Date.now() > expires) return false;
  // Verify the signature LAST but always — an expired cookie and a forged one both just fail.
  return sameSecret(sig, await hmac(`${VERSION}.${expiresRaw}`));
}
