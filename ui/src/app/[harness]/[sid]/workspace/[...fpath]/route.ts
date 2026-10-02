// Canonical artifact URL: /{harness}/{session}/workspace/{path}, proxies to the gateway's
// same-shaped /w/ route. Access is the gateway's fresh session-level shared flag
// (no auth headers injected; the unguessable session id is the lookup key, the flag is the
// gate). Binary-safe passthrough so html/css/js/img/pdf preview inline with relative assets.
import type { NextRequest } from 'next/server';
import { publicShareResponseHeaders } from '@/lib/public-artifact-response';

export const dynamic = 'force-dynamic';

const GATEWAY = process.env.HARNESS_GATEWAY_URL || 'https://api.harnessrouter.ai';

export async function GET(req: NextRequest,
  ctx: { params: Promise<{ harness: string; sid: string; fpath: string[] }> }) {
  const { harness, sid, fpath } = await ctx.params;
  const target = `${GATEWAY.replace(/\/$/, '')}/w/${encodeURIComponent(harness)}/${encodeURIComponent(sid)}` +
    `/workspace/${(fpath || []).map(encodeURIComponent).join('/')}`;
  try {
    const res = await fetch(target, { cache: 'no-store' });
    const out = publicShareResponseHeaders(res.headers, true);
    return new Response(res.body, { status: res.status, headers: out });
  } catch {
    return new Response(JSON.stringify({ detail: 'workspace upstream unreachable' }), {
      status: 502, headers: publicShareResponseHeaders(new Headers({ 'content-type': 'application/json' }), true),
    });
  }
}
