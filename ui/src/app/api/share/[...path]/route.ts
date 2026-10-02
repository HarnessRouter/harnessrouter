// PUBLIC share proxy, same-origin /api/share/* -> gateway /share/*.
// No auth is injected: the unguessable share token IS the credential, and the gateway only
// serves sessions whose sharing is currently enabled. Binary-safe passthrough so html/css/js/
// images/pdf render inline in the browser.
import type { NextRequest } from 'next/server';
import { publicShareResponseHeaders } from '@/lib/public-artifact-response';

export const dynamic = 'force-dynamic';

const GATEWAY = process.env.HARNESS_GATEWAY_URL || 'https://api.harnessrouter.ai';

export async function GET(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const target = `${GATEWAY.replace(/\/$/, '')}/share/${(path || []).map(encodeURIComponent).join('/')}`;
  try {
    const res = await fetch(target, { cache: 'no-store' });
    // Stream the body through (HR-INF-015): shared artifacts (rendered sites, PDFs, media) can be
    // large, pass res.body byte-exact so the BFF never materializes the whole payload in memory.
    const out = publicShareResponseHeaders(res.headers, path[1] === 'f');
    return new Response(res.body, { status: res.status, headers: out });
  } catch {
    return new Response(JSON.stringify({ detail: 'share upstream unreachable' }), {
      status: 502, headers: publicShareResponseHeaders(new Headers({ 'content-type': 'application/json' }), path[1] === 'f'),
    });
  }
}
