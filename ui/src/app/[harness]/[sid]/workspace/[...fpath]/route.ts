// Canonical artifact URL: /{harness}/{session}/workspace/{path}, proxies to the gateway's
// same-shaped /w/ route. Access is the gateway's single cached session-level shared flag
// (no auth headers injected; the unguessable session id is the lookup key, the flag is the
// gate). Binary-safe passthrough so html/css/js/img/pdf preview inline with relative assets.
import type { NextRequest } from 'next/server';

export const dynamic = 'force-dynamic';

const GATEWAY = process.env.HARNESS_GATEWAY_URL || 'https://api.harnessrouter.ai';

export async function GET(req: NextRequest,
  ctx: { params: Promise<{ harness: string; sid: string; fpath: string[] }> }) {
  const { harness, sid, fpath } = await ctx.params;
  const target = `${GATEWAY.replace(/\/$/, '')}/w/${encodeURIComponent(harness)}/${encodeURIComponent(sid)}` +
    `/workspace/${(fpath || []).map(encodeURIComponent).join('/')}`;
  try {
    const res = await fetch(target, { cache: 'no-store' });
    const out: Record<string, string> = {
      'content-type': res.headers.get('content-type') || 'application/octet-stream',
    };
    for (const h of ['content-disposition', 'cache-control', 'x-content-type-options']) {
      const v = res.headers.get(h);
      if (v) out[h] = v;
    }
    return new Response(res.body, { status: res.status, headers: out });
  } catch {
    return new Response(JSON.stringify({ detail: 'workspace upstream unreachable' }), {
      status: 502, headers: { 'content-type': 'application/json' },
    });
  }
}
