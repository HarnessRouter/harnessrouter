// Client-side auth: a thin wrapper over the engine's /v1/auth endpoints (via the
// /api/engine BFF) plus a localStorage-backed session. The JWT is the source of
// truth; we keep the decoded principal (member/orgs/org_id) alongside it for the
// UI. Stateless on the server, every request just carries the Bearer token.

import { LOCAL_MEMBER, LOCAL_ORG, SELF_HOSTED } from '@/lib/edition';

const SESSION_KEY = 'agentstudio.session';
const ENGINE = '/api/engine';

export interface Org {
  id: string;
  name?: string;
  [k: string]: unknown;
}

export interface Member {
  id: string;
  email?: string;
  name?: string;
  display_name?: string;
  avatar_url?: string;   // external OAuth profile photo (e.g. Google), when available
  [k: string]: unknown;
}

export interface Session {
  token: string;
  member: Member;
  orgs: Org[];
  orgId: string | null;
}

/** A self-hosted box has no accounts service, so the principal is a constant rather than
 *  something signed in. The token is empty on purpose: there is nothing to verify it against,
 *  and the BFF — not the browser — is what authenticates to the gateway. */
const LOCAL_SESSION: Session = {
  token: '',
  member: { id: LOCAL_MEMBER, email: LOCAL_MEMBER, name: 'Local' },
  orgs: [{ id: LOCAL_ORG, name: 'Local' }],
  orgId: LOCAL_ORG,
};

export function getSession(): Session | null {
  if (SELF_HOSTED) return LOCAL_SESSION;
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(SESSION_KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

/** Event fired on every session write so components holding a getSession()
 *  snapshot (e.g. the dock avatar) can re-read without a reload. */
export const SESSION_EVENT = 'agentstudio:session';

// Cross-subdomain login-state cookie. The JWT lives in localStorage (origin-scoped, so the
// marketing apex can't read it). To let harnessrouter.ai's header reflect login without exposing
// the app's storage, we ALSO mirror the token into a cookie scoped to the registrable domain
// (Domain=.harnessrouter.ai) — sent to both app. and the apex. The apex never reads this cookie in
// JS; it calls GET /api/session on the app origin, which reads the cookie server-side and returns
// only {authed, name}. On localhost/preview (not *.harnessrouter.ai) the Domain attribute is
// omitted so the cookie still works same-origin.
const AUTH_COOKIE = 'hr_auth';
function _cookieDomain(): string {
  if (typeof window === 'undefined') return '';
  return window.location.hostname.endsWith('harnessrouter.ai') ? '; Domain=.harnessrouter.ai' : '';
}
function setAuthCookie(token: string): void {
  if (typeof window === 'undefined') return;
  const secure = window.location.protocol === 'https:' ? '; Secure' : '';
  // 7-day lifetime matches the session; SameSite=Lax so top-level navigations from the apex carry it.
  document.cookie = `${AUTH_COOKIE}=${encodeURIComponent(token)}; Path=/; Max-Age=604800${_cookieDomain()}; SameSite=Lax${secure}`;
}
function clearAuthCookie(): void {
  if (typeof window === 'undefined') return;
  document.cookie = `${AUTH_COOKIE}=; Path=/; Max-Age=0${_cookieDomain()}; SameSite=Lax`;
}

function setSession(s: Session): void {
  if (typeof window !== 'undefined') {
    window.localStorage.setItem(SESSION_KEY, JSON.stringify(s));
    if (s.token) setAuthCookie(s.token);
    window.dispatchEvent(new CustomEvent(SESSION_EVENT));
  }
}

export function clearSession(): void {
  if (typeof window !== 'undefined') {
    window.localStorage.removeItem(SESSION_KEY);
    clearAuthCookie();
  }
}

export function getToken(): string | null {
  return getSession()?.token ?? null;
}

export function isAuthed(): boolean {
  // Self-hosted has no sign-in, so there is nothing to be signed out of.
  return SELF_HOSTED || !!getToken();
}

/** True when there's a token AND an active org selected. A multi-org member's login mints an
 *  org-less session (they must pick via the /login org picker); until then every org-scoped
 *  page 400s ("no active organization in session"), so the app guard sends them back to pick. */
export function hasActiveOrg(): boolean {
  if (SELF_HOSTED) return true;   // one implicit org, never picked
  const s = getSession();
  return !!s?.token && !!s.orgId;
}

async function readError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    return typeof body?.detail === 'string' ? body.detail : `request failed (${res.status})`;
  } catch {
    return `request failed (${res.status})`;
  }
}

/** Authenticate. Stores the session (org-less when the member has >1 org). */
export async function login(email: string, password: string): Promise<Session> {
  const res = await fetch(`${ENGINE}/v1/auth/login`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new Error(await readError(res));
  return _store(await res.json());
}

function _store(body: { token: string; member: Member; orgs?: Org[]; org_id?: string | null }): Session {
  const session: Session = { token: body.token, member: body.member, orgs: body.orgs ?? [], orgId: body.org_id ?? null };
  setSession(session);
  return session;
}

/** Sign-up outcome: either a live session (mail infra down -> engine fail-opens) or a
 *  verification hand-off, the user must click the emailed link before signing in. */
export type RegisterResult = { verifyRequired: true; email: string } | Session;

/** Email+password sign-up. Email is the single user id; a later Google login on the same email
 *  signs into the same account. A session is only issued after email verification. */
export async function register(email: string, password: string, name = '', inviteCode = ''): Promise<RegisterResult> {
  const res = await fetch(`${ENGINE}/v1/auth/register`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    // product tells the engine to onboard the new account into HarnessRouter (creates the
    // workspace + subscription) so the user lands straight in the app, not an empty wall.
    // invite_code (from /login?invite=) is redeemed server-side against the new org.
    body: JSON.stringify({ email, password, name, product: 'harnessrouter', invite_code: inviteCode }),
  });
  if (!res.ok) throw new Error(await readError(res));
  const body = await res.json();
  if (body.verify_required) return { verifyRequired: true, email: body.email as string };
  return _store(body);
}

/** Consume the emailed verification token, flips the account verified and signs in. */
export async function verifyEmail(token: string): Promise<Session> {
  const res = await fetch(`${ENGINE}/v1/auth/verify-email`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ token, product: 'harnessrouter' }),
  });
  if (!res.ok) throw new Error(await readError(res));
  return _store(await res.json());
}

/** Re-send the verification mail. Always resolves (never reveals whether the email exists). */
export async function resendVerification(email: string): Promise<void> {
  await fetch(`${ENGINE}/v1/auth/resend-verification`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ email, product: 'harnessrouter' }),
  }).catch(() => {});
}

/** Exchange a Google Identity Services credential (id_token) for a session. */
export async function googleSignIn(credential: string, inviteCode = ''): Promise<{ session: Session; newAccount: boolean }> {
  const res = await fetch(`${ENGINE}/v1/auth/google`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ credential, product: 'harnessrouter', invite_code: inviteCode }),
  });
  if (!res.ok) throw new Error(await readError(res));
  const body = await res.json();
  return { session: _store(body), newAccount: !!body.new_account };
}

/** Request a password-reset email. Always resolves (the server never reveals if the email exists). */
export async function requestPasswordReset(email: string): Promise<void> {
  await fetch(`${ENGINE}/v1/auth/request-password-reset`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ email, product: 'harnessrouter' }),
  }).catch(() => {});
}

/** Complete a password reset with the emailed token; returns a signed-in session. */
export async function resetPassword(token: string, password: string): Promise<Session> {
  const res = await fetch(`${ENGINE}/v1/auth/reset-password`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ token, password, product: 'harnessrouter' }),
  });
  if (!res.ok) throw new Error(await readError(res));
  return _store(await res.json());
}

/** Switch the active org (re-mints an org-scoped token). */
export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  const res = await authFetch('/v1/auth/change-password', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
  if (!res.ok) throw new Error(await readError(res));
}

export async function deleteAccount(password: string, confirm = ''): Promise<void> {
  const res = await authFetch('/v1/auth/delete-account', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ password, confirm }),
  });
  if (!res.ok) throw new Error(await readError(res));
  clearSession();
}

export async function switchOrg(orgId: string): Promise<Session> {
  const current = getSession();
  if (!current) throw new Error('not authenticated');
  const res = await fetch(`${ENGINE}/v1/auth/switch-org`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', authorization: `Bearer ${current.token}` },
    body: JSON.stringify({ org_id: orgId }),
  });
  if (!res.ok) throw new Error(await readError(res));
  const body = await res.json();
  const next: Session = { ...current, token: body.token, orgId: body.org_id };
  setSession(next);
  return next;
}

/** Refresh the principal from the engine (also validates the token). */
export async function fetchMe(): Promise<{ member: Member; orgId: string | null; orgs: Org[] }> {
  const token = getToken();
  if (!token) throw new Error('not authenticated');
  const res = await fetch(`${ENGINE}/v1/auth/me`, {
    headers: { authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  const body = await res.json();
  return { member: body.member, orgId: body.org_id ?? null, orgs: body.orgs ?? [] };
}

/** Merge a patch into the stored session's member (optimistic UI, e.g. a new
 *  avatar) without a round-trip. No-op when signed out. */
export function patchSessionMember(patch: Partial<Member>): void {
  const current = getSession();
  if (!current) return;
  setSession({ ...current, member: { ...current.member, ...patch } });
}

/** Re-fetch the principal and merge it into the stored session so getSession()
 *  reflects server-side changes (e.g. avatar). Offline-tolerant. */
export async function refreshMe(): Promise<Session | null> {
  const current = getSession();
  if (!current) return null;
  try {
    const fresh = await fetchMe();
    const next: Session = { ...current, member: fresh.member, orgs: fresh.orgs ?? current.orgs };
    setSession(next);
    return next;
  } catch {
    return current;
  }
}

/**
 * Refresh the org list from the server and repair a stale active org.
 *
 * The active org is stored in localStorage; it can become invalid if that org
 * was deleted or the member's access was revoked while they were away. This
 * re-fetches the authoritative membership and, if the stored org is gone,
 * erases it and falls back to the next available org (re-minting an org-scoped
 * token). If no orgs remain, the session is left org-less. On a network/auth
 * error it leaves the session untouched (offline-tolerant). Returns the
 * reconciled session, or null if not authenticated.
 */
export async function reconcileSession(): Promise<Session | null> {
  const current = getSession();
  if (!current) return null;
  let fresh: { member: Member; orgId: string | null; orgs: Org[] };
  try {
    fresh = await fetchMe();
  } catch {
    return current; // offline or token issue, don't destroy the session here
  }
  const orgs = fresh.orgs ?? [];
  const stillValid = !!current.orgId && orgs.some((o) => o.id === current.orgId);

  if (!stillValid && orgs.length > 0) {
    // Active org was deleted/revoked, fall back to the next available org.
    try {
      const switched = await switchOrg(orgs[0].id);
      const next: Session = { ...switched, member: fresh.member, orgs };
      setSession(next);
      return next;
    } catch {
      /* fall through to org-less below */
    }
  }

  const next: Session = {
    ...current,
    member: fresh.member,
    orgs,
    orgId: stillValid ? current.orgId : null,
  };
  setSession(next);
  return next;
}

export function logout(): void {
  clearSession();
}

/** Slide the session: ask the engine for a fresh full-TTL token from the current
 *  (still-valid) one and store it. Keeps an active user signed in indefinitely.
 *  A 401 means the token is truly dead -> hand off to handleAuthExpired. */
export async function refreshToken(): Promise<boolean> {
  if (SELF_HOSTED) return true;   // no token, nothing to slide
  const cur = getSession();
  if (!cur?.token) return false;
  try {
    const res = await fetch(`${ENGINE}/v1/auth/refresh`, {
      method: 'POST',
      headers: { authorization: `Bearer ${cur.token}` },
    });
    if (res.status === 401) { handleAuthExpired(); return false; }
    if (!res.ok) return false;
    const body = await res.json();
    const now = getSession();
    if (body?.token && now) setSession({ ...now, token: body.token });
    return true;
  } catch {
    return false; // offline, keep the session, retry later
  }
}

let _redirecting = false;
/** The token is invalid/expired: clear the session and show the login page.
 *  Idempotent + loop-safe (no-op when already on /login). With refresh active
 *  this should rarely fire, it's the safety net the product requires. */
export function handleAuthExpired(): void {
  // Nothing expires without a session, and there is no /login to land on — a 401 self-hosted
  // means a real error, which the caller surfaces instead of being bounced off the page.
  if (SELF_HOSTED) return;
  if (typeof window === 'undefined' || _redirecting) return;
  if (window.location.pathname === '/login') return;
  _redirecting = true;
  clearSession();
  window.location.assign('/login?expired=1');
}

/** fetch() with the Bearer token attached, for authenticated engine calls.
 *  A 401 with a token attached means the session is dead — same hand-off as harnessFetch. */
export async function authFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const token = getToken();
  const headers = new Headers(init.headers);
  if (token) headers.set('authorization', `Bearer ${token}`);
  const res = await fetch(`${ENGINE}${path}`, { ...init, headers });
  if (res.status === 401 && token) handleAuthExpired();
  return res;
}
