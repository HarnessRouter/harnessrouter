// Login-state probe for the marketing site header, and the cookie that backs it.
//
// The console keeps its JWT in localStorage (origin-scoped). For harnessrouter.ai's header to know
// whether this browser is signed in, the console asks its OWN server to mirror the login into a
// cookie that only this host receives and only the server can read: `hr_session`, HttpOnly,
// Secure, SameSite=Lax, host-only (no Domain attribute). The marketing page fetches
// GET /api/session with credentials:include; the browser attaches the cookie because
// harnessrouter.ai and app.harnessrouter.ai are same-site, and the answer carries only
// {authed, initial, avatarUrl, dashboardUrl}. Nothing here returns, echoes, or logs the token, and no script
// on any origin can read the cookie.
//
//   POST   same-origin, Authorization: Bearer   verify with the engine, then set the cookie
//   DELETE same-origin                          clear the cookie (sign-out)
//   GET    marketing origins only               read + verify the cookie, answer the minimal state
//          (avatarUrl is the member's OAuth photo when there is one; https only)
//
// Every unknown origin, missing cookie, engine error or invalid token is answered as signed out
// or refused BEFORE any authenticated work, so the route cannot be used to make the engine verify
// tokens on behalf of arbitrary pages.
import type { NextRequest } from 'next/server';
import { SELF_HOSTED } from '@/lib/edition';

export const dynamic = 'force-dynamic';
export const maxDuration = 15;

// No default: see the engine BFF. Unconfigured means unavailable, not "use someone else's".
const ENGINE = process.env.WORKFLOW_ENGINE_URL || '';

const COOKIE = 'hr_session';
/** The earlier JavaScript-set, domain-wide mirror of the JWT. Cleared whenever it is seen. */
const LEGACY_COOKIE = 'hr_auth';
const COOKIE_MAX_AGE_S = 7 * 24 * 60 * 60; // matches the session lifetime

// Only the marketing site (apex + www) may read cross-origin login state.
const MARKETING_ORIGINS = new Set(['https://harnessrouter.ai', 'https://www.harnessrouter.ai']);
const DASHBOARD_URL = 'https://app.harnessrouter.ai/dashboard';

const BASE_HEADERS: Record<string, string> = {
  'cache-control': 'no-store',
  vary: 'Origin',
};

function corsHeaders(origin: string): Record<string, string> {
  return {
    ...BASE_HEADERS,
    'access-control-allow-origin': origin,
    'access-control-allow-credentials': 'true',
    'access-control-allow-methods': 'GET, OPTIONS',
  };
}

function isSecure(req: NextRequest): boolean {
  return req.nextUrl.protocol === 'https:';
}

/** POST/DELETE come from the console itself; anything else is refused. */
function isSameOrigin(req: NextRequest): boolean {
  const origin = req.headers.get('origin');
  if (origin) return origin === req.nextUrl.origin;
  // Older browsers may omit Origin on same-origin requests; Fetch Metadata still tells us.
  return req.headers.get('sec-fetch-site') === 'same-origin';
}

function cookie(name: string, value: string, maxAge: number, secure: boolean, domain = ''): string {
  return (
    `${name}=${value}; Path=/; Max-Age=${maxAge}; HttpOnly; SameSite=Lax` +
    (secure ? '; Secure' : '') +
    domain
  );
}

/** Set-Cookie lines that retire the legacy domain-wide cookie (both scopes it may live under). */
function clearLegacyCookies(req: NextRequest): string[] {
  const secure = isSecure(req);
  const lines = [cookie(LEGACY_COOKIE, '', 0, secure)];
  if (req.nextUrl.hostname.endsWith('harnessrouter.ai')) {
    lines.push(cookie(LEGACY_COOKIE, '', 0, secure, '; Domain=.harnessrouter.ai'));
  }
  return lines;
}

function withCookies(res: Response, lines: string[]): Response {
  for (const line of lines) res.headers.append('set-cookie', line);
  return res;
}

type Verified = { ok: true; initial: string; avatarUrl: string | null } | { ok: false };

/** First letter or digit of the member's name (or email), uppercased; "A" when there is none. */
function initialOf(member: Record<string, unknown> | null | undefined): string {
  const source = [member?.display_name, member?.name, member?.email].find(
    (v): v is string => typeof v === 'string' && v.trim().length > 0,
  );
  const match = source?.match(/\p{L}|\p{N}/u);
  return match ? match[0].toUpperCase() : 'A';
}

/** The member's OAuth profile photo, only when it is an https URL; anything else is dropped. */
function avatarOf(member: Record<string, unknown> | null | undefined): string | null {
  const raw = member?.avatar_url;
  if (typeof raw !== 'string' || raw.length > 2048) return null;
  try {
    const url = new URL(raw);
    return url.protocol === 'https:' ? url.toString() : null;
  } catch {
    return null;
  }
}

/** Ask the engine whether this token is a live session. Never throws; failures read as invalid. */
async function verify(token: string): Promise<Verified> {
  if (!token || !ENGINE) return { ok: false };
  try {
    const r = await fetch(`${ENGINE.replace(/\/$/, '')}/v1/auth/me`, {
      headers: { authorization: `Bearer ${token}` },
      cache: 'no-store',
    });
    if (!r.ok) return { ok: false };
    const d = await r.json().catch(() => null);
    return { ok: true, initial: initialOf(d?.member), avatarUrl: avatarOf(d?.member) };
  } catch {
    return { ok: false };
  }
}

function json(body: unknown, headers: Record<string, string>, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...headers, 'content-type': 'application/json' },
  });
}

export async function OPTIONS(req: NextRequest) {
  const origin = req.headers.get('origin') || '';
  if (!MARKETING_ORIGINS.has(origin)) return new Response(null, { status: 403, headers: BASE_HEADERS });
  return new Response(null, { status: 204, headers: corsHeaders(origin) });
}

/** Marketing header probe. Refuses unknown origins before touching the cookie or the engine. */
export async function GET(req: NextRequest) {
  const origin = req.headers.get('origin') || '';
  if (!MARKETING_ORIGINS.has(origin)) {
    return json({ authed: false }, BASE_HEADERS, 403);
  }
  const headers = corsHeaders(origin);
  const legacy = req.cookies.get(LEGACY_COOKIE) ? clearLegacyCookies(req) : [];
  // Self-hosted has no sign-in and no engine to ask, so the answer is always "not signed in".
  const token = SELF_HOSTED ? '' : req.cookies.get(COOKIE)?.value || '';
  const verified = await verify(token);
  if (!verified.ok) {
    // missing / expired / revoked / engine unreachable: fail closed to signed out
    return withCookies(json({ authed: false }, headers), legacy);
  }
  return withCookies(
    json(
      { authed: true, initial: verified.initial, avatarUrl: verified.avatarUrl, dashboardUrl: DASHBOARD_URL },
      headers,
    ),
    legacy,
  );
}

/** Console sign-in: mirror a verified token into the HttpOnly probe cookie. */
export async function POST(req: NextRequest) {
  if (SELF_HOSTED) return json({ detail: 'not available on this edition' }, BASE_HEADERS, 404);
  if (!isSameOrigin(req)) return json({ detail: 'forbidden' }, BASE_HEADERS, 403);
  const auth = req.headers.get('authorization') || '';
  const token = auth.startsWith('Bearer ') ? auth.slice(7).trim() : '';
  if (!token) return json({ detail: 'missing bearer token' }, BASE_HEADERS, 401);
  const verified = await verify(token);
  if (!verified.ok) return json({ detail: 'invalid session' }, BASE_HEADERS, 401);
  const res = new Response(null, { status: 204, headers: BASE_HEADERS });
  return withCookies(res, [
    cookie(COOKIE, encodeURIComponent(token), COOKIE_MAX_AGE_S, isSecure(req)),
    ...clearLegacyCookies(req),
  ]);
}

/** Console sign-out: drop the probe cookie so the marketing header shows Sign up again. */
export async function DELETE(req: NextRequest) {
  if (!isSameOrigin(req)) return json({ detail: 'forbidden' }, BASE_HEADERS, 403);
  const res = new Response(null, { status: 204, headers: BASE_HEADERS });
  return withCookies(res, [cookie(COOKIE, '', 0, isSecure(req)), ...clearLegacyCookies(req)]);
}
