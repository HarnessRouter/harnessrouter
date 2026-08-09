// PUBLIC share proxy, same-origin /api/share/* -> gateway /share/*.
// No auth is injected: the unguessable share token IS the credential, and the gateway only
// serves sessions whose sharing is currently enabled. Binary-safe passthrough so html/css/js/
// images/pdf render inline in the browser.
import type { NextRequest } from 'next/server';

export const dynamic = 'force-dynamic';

const GATEWAY = process.env.HARNESS_GATEWAY_URL || 'https://api.harnessrouter.ai';

export async function GET(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const target = `${GATEWAY.replace(/\/$/, '')}/share/${(path || []).map(encodeURIComponent).join('/')}`;
  try {
    const res = await fetch(target, { cache: 'no-store' });
    // Stream the body through (HR-INF-015): shared artifacts (rendered sites, PDFs, media) can be
    // large, pass res.body byte-exact so the BFF never materializes the whole payload in memory.
    const out: Record<string, string> = {
      'content-type': res.headers.get('content-type') || 'application/octet-stream',
    };
    const cd = res.headers.get('content-disposition');
    if (cd) out['content-disposition'] = cd;
    const cc = res.headers.get('cache-control');
    if (cc) out['cache-control'] = cc;
    const cl = res.headers.get('content-length');
    if (cl) out['content-length'] = cl;
    return new Response(res.body, { status: res.status, headers: out });
  } catch {
    return new Response(JSON.stringify({ detail: 'share upstream unreachable' }), {
      status: 502, headers: { 'content-type': 'application/json' },
    });
  }
}
