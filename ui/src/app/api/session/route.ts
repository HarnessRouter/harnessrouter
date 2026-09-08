// The marketing site's login-state probe, and the console's own session cookie.
//
// The console keeps the login JWT in localStorage (origin-scoped). At sign-in it POSTs the token
// here and this route sets hr_auth as an HttpOnly, Secure, SameSite=Lax, host-only cookie; at
// sign-out it DELETEs it. No script on any subdomain can read or remove that cookie (a JS-set copy
// on the registrable domain used to exist, and a cleanup on the marketing site expired it on every
// visit, signing everyone out). The marketing apex calls GET here with credentials; the app-host
// cookie rides along, is verified server-side via the engine's /v1/auth/me, and the answer is ONLY
// {authed, name, dashboardUrl}, never the token. GET has no side effects, so no CSRF surface; POST
// and DELETE are same-origin only (no CORS headers on them). Self-hosted has no engine to ask and
// no marketing header, so every answer there is "not signed in" and no cookie is written.
import type { NextRequest } from 'next/server';
import { SELF_HOSTED } from '@/lib/edition';

export const dynamic = 'force-dynamic';
export const maxDuration = 15;

// No default: see the engine BFF. Unconfigured means unavailable, not "use someone else's".
const ENGINE = process.env.WORKFLOW_ENGINE_URL || '';

// Only the marketing site (apex + www) may read cross-origin login state.
const ALLOWED_ORIGINS = new Set([
  'https://harnessrouter.ai',
  'https://www.harnessrouter.ai',
]);
const DASHBOARD_URL = 'https://app.harnessrouter.ai/dashboard';
const COOKIE = 'hr_auth';
const COOKIE_MAX_AGE = 604800;   // 7 days, the session's own lifetime

function cookieHeader(value: string, maxAge: number, req: NextRequest): string {
  // host-only on purpose: no Domain attribute, so it belongs to the console host alone
  const secure = req.nextUrl.protocol === 'https:' ? '; Secure' : '';
  return `${COOKIE}=${encodeURIComponent(value)}; Path=/; Max-Age=${maxAge}; HttpOnly; SameSite=Lax${secure}`;
}

async function verified(token: string): Promise<{ name: string } | null> {
  const r = await fetch(`${ENGINE.replace(/\/$/, '')}/v1/auth/me`, {
    headers: { authorization: `Bearer ${token}` },
    cache: 'no-store',
  });
  if (!r.ok) return null;
  const d = await r.json().catch(() => null);
  const m = d?.member || {};
  return { name: m.name || m.email || 'Account' };
}

const plain = { 'content-type': 'application/json', 'Cache-Control': 'no-store' };

/** Sign-in: the console hands its bearer over and gets the HttpOnly cookie back. */
export async function POST(req: NextRequest) {
  if (SELF_HOSTED || !ENGINE) return new Response(JSON.stringify({ ok: true }), { status: 200, headers: plain });
  const auth = req.headers.get('authorization') || '';
  const token = auth.toLowerCase().startsWith('bearer ') ? auth.slice(7).trim() : '';
  if (!token) return new Response(JSON.stringify({ ok: false }), { status: 401, headers: plain });
  try {
    if (!(await verified(token))) return new Response(JSON.stringify({ ok: false }), { status: 401, headers: plain });
  } catch {
    return new Response(JSON.stringify({ ok: false }), { status: 503, headers: plain });
  }
  return new Response(JSON.stringify({ ok: true }), { status: 200, headers: { ...plain, 'Set-Cookie': cookieHeader(token, COOKIE_MAX_AGE, req) } });
}

/** Sign-out: the cookie is gone. */
export async function DELETE(req: NextRequest) {
  return new Response(JSON.stringify({ ok: true }), { status: 200, headers: { ...plain, 'Set-Cookie': cookieHeader('', 0, req) } });
}

function corsHeaders(origin: string | null): Record<string, string> {
  const h: Record<string, string> = {
    'Cache-Control': 'no-store',
    'Vary': 'Origin',
  };
  if (origin && ALLOWED_ORIGINS.has(origin)) {
    h['Access-Control-Allow-Origin'] = origin;
    h['Access-Control-Allow-Credentials'] = 'true';
  }
  return h;
}

export async function OPTIONS(req: NextRequest) {
  const origin = req.headers.get('origin');
  return new Response(null, {
    status: 204,
    headers: { ...corsHeaders(origin), 'Access-Control-Allow-Methods': 'GET, OPTIONS' },
  });
}

export async function GET(req: NextRequest) {
  const origin = req.headers.get('origin');
  const headers = { ...corsHeaders(origin), 'content-type': 'application/json' };
  // Self-hosted has no sign-in and no engine to ask, so the answer is always "not signed in" —
  // the same fail-closed answer this route already gives when the engine can't be reached.
  const token = SELF_HOSTED || !ENGINE ? '' : (req.cookies.get(COOKIE)?.value || '');
  if (!token) {
    return new Response(JSON.stringify({ authed: false }), { status: 200, headers });
  }
  try {
    const who = await verified(token);
    if (!who) {
      // expired / revoked / invalid → treat as logged out
      return new Response(JSON.stringify({ authed: false }), { status: 200, headers });
    }
    return new Response(
      JSON.stringify({ authed: true, name: who.name, dashboardUrl: DASHBOARD_URL }),
      { status: 200, headers },
    );
  } catch {
    // engine unreachable → fail closed to logged-out (header just shows Sign up, never a token)
    return new Response(JSON.stringify({ authed: false }), { status: 200, headers });
  }
}
