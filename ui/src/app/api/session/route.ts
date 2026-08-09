// Read-only cross-origin login-state probe for the marketing site header.
//
// The console keeps the login JWT in localStorage (origin-scoped) AND mirrors it into an
// hr_auth cookie scoped to .harnessrouter.ai (see lib/auth.ts). The marketing apex
// (harnessrouter.ai) can't read the app's localStorage or an HttpOnly cookie in JS, so its header
// calls THIS endpoint with credentials:include; the cookie rides along cross-subdomain. We verify
// it server-side via the engine's /v1/auth/me and return ONLY {authed, name, dashboardUrl} — never
// the token. GET + no side effects, so no CSRF surface. CORS is restricted to the apex origins.
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
  const token = SELF_HOSTED || !ENGINE ? '' : (req.cookies.get('hr_auth')?.value || '');
  if (!token) {
    return new Response(JSON.stringify({ authed: false }), { status: 200, headers });
  }
  try {
    const r = await fetch(`${ENGINE.replace(/\/$/, '')}/v1/auth/me`, {
      headers: { authorization: `Bearer ${token}` },
      cache: 'no-store',
    });
    if (!r.ok) {
      // expired / revoked / invalid → treat as logged out
      return new Response(JSON.stringify({ authed: false }), { status: 200, headers });
    }
    const d = await r.json().catch(() => null);
    const m = d?.member || {};
    return new Response(
      JSON.stringify({ authed: true, name: m.name || m.email || 'Account', dashboardUrl: DASHBOARD_URL }),
      { status: 200, headers },
    );
  } catch {
    // engine unreachable → fail closed to logged-out (header just shows Sign up, never a token)
    return new Response(JSON.stringify({ authed: false }), { status: 200, headers });
  }
}
