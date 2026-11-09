// PUBLIC share proxy, same-origin /api/share/* -> gateway /share/*.
// No auth is injected: the unguessable share token IS the credential, and the gateway only
// serves sessions whose sharing is currently enabled. Binary-safe passthrough so html/css/js/
// images/pdf render inline in the browser.
//
// An address whose segments are not plain names (lib/public-artifact-response plainSegments) is
// refused before the gateway is asked: fetch() resolves '..' in the URL it is given, so a token or a
// file name of '..' would have carried this public relay to another of the gateway's routes. The
// refusal is the gateway's own 404 for a share or a file that is not there.
import type { NextRequest } from 'next/server';
import { notFoundResponse, plainSegments, publicShareResponseHeaders } from '@/lib/public-artifact-response';

export const dynamic = 'force-dynamic';

const GATEWAY = process.env.HARNESS_GATEWAY_URL || 'https://api.harnessrouter.ai';

export async function GET(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const segs = path || [];
  if (!segs.length || !plainSegments(segs)) {
    return notFoundResponse(segs[1] === 'f' && plainSegments(segs.slice(0, 2)) ? 'file not found' : 'share not found', segs[1] === 'f');
  }
  const target = `${GATEWAY.replace(/\/$/, '')}/share/${segs.map(encodeURIComponent).join('/')}`;
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
