// Canonical artifact URL: /{harness}/{session}/workspace/{path}. Binary-safe passthrough so html/css/
// js/img/pdf preview inline with relative assets, always in the public artifact sandbox.
//
// Who it answers (#594):
//   - anyone, for a SHARED task: the gateway's same-shaped /w/ route, no credential of ours attached
//     (the unguessable session id is the lookup key, the gateway's fresh shared flag is the gate);
//   - signed in to a self-hosted box (its session cookie verifies, or its sign-in is switched off):
//     the gateway's signed-in read by path, /a/{session}/{path}, as the box's member, which is exactly
//     what /api/harness and /data/workspaces already give that cookie. A reply's link to its own file
//     opened "file not found" here unless the task was shared.
// The hosted console's sign-in is a bearer the browser holds, which a plain link cannot carry, so this
// address stays public-only there; the console opens a reply's file with the sign-in instead (Md).
//
// This handler checks the cookie itself: the self-hosted gate lets a path ending in .png or .css
// through without one (STATIC_ASSET in middleware.ts), and this route must not lean on it.
import type { NextRequest } from 'next/server';
import { LOCAL_MEMBER, LOCAL_ORG, SELF_HOSTED } from '@/lib/edition';
import { AUTH_DISABLED, SESSION_COOKIE, sessionValid } from '@/lib/selfhost-auth';
import { publicShareResponseHeaders } from '@/lib/public-artifact-response';

export const dynamic = 'force-dynamic';

const GATEWAY = (process.env.HARNESS_GATEWAY_URL || 'https://api.harnessrouter.ai').replace(/\/$/, '');
const INTERNAL_KEY = process.env.HARNESS_INTERNAL_KEY || '';

async function signedIn(req: NextRequest): Promise<boolean> {
  if (!SELF_HOSTED || !INTERNAL_KEY) return false;
  return AUTH_DISABLED || sessionValid(req.cookies?.get(SESSION_COOKIE)?.value);
}

export async function GET(req: NextRequest,
  ctx: { params: Promise<{ harness: string; sid: string; fpath: string[] }> }) {
  const { harness, sid, fpath } = await ctx.params;
  const path = (fpath || []).map(encodeURIComponent).join('/');
  const member = await signedIn(req);
  const target = member
    ? `${GATEWAY}/a/${encodeURIComponent(sid)}/${path}`
    : `${GATEWAY}/w/${encodeURIComponent(harness)}/${encodeURIComponent(sid)}/workspace/${path}`;
  // Nothing the browser sent is forwarded. The member's identity is the box's own, pinned here; the
  // public read carries no header of ours at all.
  const init: RequestInit = member
    ? { headers: { 'x-harness-internal': INTERNAL_KEY, 'x-harness-org': LOCAL_ORG, 'x-harness-member': LOCAL_MEMBER }, cache: 'no-store' }
    : { cache: 'no-store' };
  try {
    const res = await fetch(target, init);
    const out = publicShareResponseHeaders(res.headers, true);
    return new Response(res.body, { status: res.status, headers: out });
  } catch {
    return new Response(JSON.stringify({ detail: 'workspace upstream unreachable' }), {
      status: 502, headers: publicShareResponseHeaders(new Headers({ 'content-type': 'application/json' }), true),
    });
  }
}
