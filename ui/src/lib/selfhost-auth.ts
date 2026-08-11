// The self-hosted session cookie: minting and verifying. Edge-safe on purpose.
//
// This module runs in the middleware, which Next.js bundles for the Edge runtime — no filesystem,
// and (verified, not assumed) no visibility into environment variables a Node route mutates after
// the server started. So the middleware can only ever know the credentials the process BOOTED
// with, and everything here is built around that fact rather than around wishing it away.
//
// The signing key is `HR_SESSION_KEY`, which the entrypoint derives from whatever the credentials
// are at boot: the stored credential file if the operator has changed them, otherwise
// HR_AUTH_USER/HR_AUTH_PASSWORD. Because the key IS the credentials, a changed password cannot
// verify against an old cookie — which is what makes "change the password" a real answer to
// "someone else has my password". Making that true at runtime is why changing credentials
// restarts the console process (see the profile route and the entrypoint's supervisor loop).
//
// Reading and writing the credential file lives in selfhost-credentials.ts, which is Node-only.
// The split is deliberate: importing that module from here would drag node:fs into the Edge
// bundle and fail the build — a failure that is much better than a gate that silently degrades.
export const SESSION_COOKIE = 'hr_selfhost';
const VERSION = 'v1';

export const AUTH_DISABLED = process.env.HR_AUTH_DISABLED === '1';
export const SELF_HOSTED = process.env.NEXT_PUBLIC_HR_EDITION === 'selfhost';

/** The credentials this process booted with. The entrypoint resolves the stored file first, so
 *  these are only the fallback for an instance whose credentials were never changed. */
const ENV_USER = process.env.HR_AUTH_USER || 'harnessrouter';
const ENV_PASSWORD = process.env.HR_AUTH_PASSWORD || 'harnessrouter';

/** How long a session lasts. Long enough not to be a nuisance on a box you use daily. */
export const SESSION_TTL_MS = 7 * 24 * 60 * 60 * 1000;

const enc = new TextEncoder();

/** Key material for the signature, as of boot. */
export function bootSessionKey(): string {
  return process.env.HR_SESSION_KEY || `${ENV_USER}:${ENV_PASSWORD}`;
}

async function hmac(message: string, key: string): Promise<string> {
  const k = await crypto.subtle.importKey(
    'raw', enc.encode(`hr-selfhost:${key}`),
    { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'],
  );
  const sig = await crypto.subtle.sign('HMAC', k, enc.encode(message));
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

/** Mint a cookie signed with `key`. The profile route passes the NEW key after a credential
 *  change, so the cookie it hands back is already valid for the process about to take over —
 *  otherwise changing your own password would sign you out of the tab you changed it in. */
export async function mintSessionWith(key: string): Promise<string> {
  const expires = Date.now() + SESSION_TTL_MS;
  const body = `${VERSION}.${expires}`;
  return `${body}.${await hmac(body, key)}`;
}

export function mintSession(): Promise<string> {
  return mintSessionWith(bootSessionKey());
}

export async function sessionValid(token: string | undefined): Promise<boolean> {
  if (!token) return false;
  const parts = token.split('.');
  if (parts.length !== 3 || parts[0] !== VERSION) return false;
  const [, expiresRaw, sig] = parts;
  const expires = Number(expiresRaw);
  if (!Number.isFinite(expires) || Date.now() > expires) return false;
  // Verify the signature LAST but always — an expired cookie and a forged one both just fail.
  return sameSecret(sig, await hmac(`${VERSION}.${expiresRaw}`, bootSessionKey()));
}
