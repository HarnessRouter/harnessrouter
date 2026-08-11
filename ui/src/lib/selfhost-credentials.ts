// Where the self-hosted credentials actually live. Node-only — it reads and writes a file.
//
// Two sources, in order:
//   1. A credential file on the data volume, written when the operator changes their username or
//      password from the profile page. It holds a scrypt hash and a salt — never the password.
//   2. HR_AUTH_USER / HR_AUTH_PASSWORD from the environment, for an instance that has never
//      changed them.
//
// The file wins because it is what the operator changed most recently: an env var set at
// `docker run` months ago should not silently undo a password change. Deleting the file falls
// back to the environment, which is the recovery path for a forgotten password — it is the only
// one, by design, since there is no email to send a reset to.
import { randomBytes, scryptSync, timingSafeEqual } from 'node:crypto';
import { mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { sameSecret } from './selfhost-auth';

/** On the data volume, so a changed password survives `docker rm` and comes back on restart.
 *  The entrypoint reads the same path to derive HR_SESSION_KEY at boot — one location, named
 *  in one place per language, because a second copy of this path is a lockout waiting to happen. */
export const CREDENTIAL_STORE = process.env.HR_AUTH_STORE || '/data/selfhost-auth.json';

const ENV_USER = process.env.HR_AUTH_USER || 'harnessrouter';
const ENV_PASSWORD = process.env.HR_AUTH_PASSWORD || 'harnessrouter';

interface StoredCredentials { user: string; salt: string; hash: string; updatedAt: number }

function readStore(): StoredCredentials | null {
  try {
    const doc = JSON.parse(readFileSync(CREDENTIAL_STORE, 'utf8')) as Partial<StoredCredentials>;
    if (doc.user && doc.salt && doc.hash
        && typeof doc.user === 'string' && typeof doc.salt === 'string'
        && typeof doc.hash === 'string') {
      return doc as StoredCredentials;
    }
    return null;
  } catch {
    // Absent is the normal case (nothing changed yet). Unreadable or corrupt falls back to the
    // environment rather than locking the operator out of their own box.
    return null;
  }
}

function hashPassword(password: string, salt: string): string {
  return scryptSync(password, salt, 32).toString('hex');
}

/** The username required at sign-in and shown in the UI. */
export function authUser(): string {
  return readStore()?.user || ENV_USER;
}

/** Whether this instance is still on the password published in the README. */
export function usingDefaultPassword(): boolean {
  return readStore() === null && ENV_PASSWORD === 'harnessrouter';
}

/** The session signing key for the CURRENT credentials — which is not necessarily the one the
 *  running process booted with. The entrypoint computes the same value at start-up. */
export function currentSessionKey(): string {
  const stored = readStore();
  return stored ? `${stored.user}:${stored.hash}` : `${ENV_USER}:${ENV_PASSWORD}`;
}

export function passwordValid(password: string): boolean {
  const stored = readStore();
  if (!stored) return sameSecret(password, ENV_PASSWORD);
  const want = Buffer.from(stored.hash, 'hex');
  const got = Buffer.from(hashPassword(password, stored.salt), 'hex');
  return want.length === got.length && timingSafeEqual(want, got);
}

export function credentialsValid(user: string, password: string): boolean {
  // Both are always checked, so a wrong username costs the same as a wrong password.
  const okUser = sameSecret(user, authUser());
  const okPass = passwordValid(password);
  return okUser && okPass;
}

/** Write new credentials, atomically. The caller must then restart the console: the middleware
 *  reads its key from the environment at boot and cannot see this file change. */
export function setCredentials(user: string, password: string): void {
  const salt = randomBytes(16).toString('hex');
  const doc: StoredCredentials = {
    user, salt, hash: hashPassword(password, salt), updatedAt: Date.now(),
  };
  mkdirSync(dirname(CREDENTIAL_STORE), { recursive: true });
  // Write-then-rename on the same filesystem, so the swap is atomic. A truncated credential file
  // reads as "no file" and drops the instance back to the environment defaults — a silent
  // password reset is the one failure mode worth designing out.
  const tmp = `${CREDENTIAL_STORE}.tmp`;
  writeFileSync(tmp, JSON.stringify(doc), { mode: 0o600 });
  renameSync(tmp, CREDENTIAL_STORE);
}
