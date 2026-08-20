// Serve a task's produced files by their workspace path:
//
//   /data/workspaces/<session-id>/deliverables/report.xlsx
//
// The file cards link by opaque file id, which is right for the console but useless anywhere else:
// you cannot paste it into a browser, drop it in a chat message, or point another tool at it. This
// route makes the path the agent actually wrote to the addressable name.
//
// It resolves the path through the gateway's own listing for that session rather than touching a
// filesystem, so a path cannot escape the session it names — `../` resolves to nothing, because
// nothing in the list matches it. There is no directory index either: an unknown path is a 404,
// not a browse.
//
// Authentication is the same gate as everything else. Self-hosted, the middleware has already
// checked the session cookie by the time this runs, so the BFF presents the internal key on its
// own (identical to /api/harness). Otherwise the caller's bearer is forwarded and the gateway
// decides — a request with no credentials gets no key and is refused there.
import { NextResponse, type NextRequest } from 'next/server';
import { LOCAL_MEMBER, LOCAL_ORG, SELF_HOSTED } from '@/lib/edition';

export const dynamic = 'force-dynamic';

const GATEWAY = (process.env.HARNESS_GATEWAY_URL || 'https://api.harnessrouter.ai').replace(/\/$/, '');
const INTERNAL_KEY = process.env.HARNESS_INTERNAL_KEY || '';

function gwHeaders(req: NextRequest): Record<string, string> {
  const h: Record<string, string> = {};
  const auth = req.headers.get('authorization');
  if (auth) h['authorization'] = auth;
  if (INTERNAL_KEY && (auth || SELF_HOSTED)) h['x-harness-internal'] = INTERNAL_KEY;
  if (SELF_HOSTED) {
    h['x-harness-org'] = LOCAL_ORG;
    h['x-harness-member'] = LOCAL_MEMBER;
  } else {
    const org = req.headers.get('x-harness-org');
    if (org) h['x-harness-org'] = org;
    const member = req.headers.get('x-harness-member');
    if (member) h['x-harness-member'] = member;
  }
  return h;
}

interface SessionFile { id?: string; file_id?: string; path?: string; filename?: string; media_type?: string }

export async function GET(req: NextRequest, ctx: { params: Promise<{ sid: string; path: string[] }> }) {
  const { sid, path } = await ctx.params;
  // Next has already URL-decoded each segment; rejoin to the path the agent wrote.
  const wanted = (path || []).join('/');
  if (!sid || !wanted) return new NextResponse('Not found', { status: 404 });

  const headers = gwHeaders(req);
  const listed = await fetch(`${GATEWAY}/v1/sessions/${encodeURIComponent(sid)}/files`,
                             { headers, cache: 'no-store' });
  if (!listed.ok) {
    // Pass the gateway's verdict through rather than inventing one: 401/403 mean "sign in", 404
    // means the session is gone, and flattening them all to 404 hides which.
    return new NextResponse(listed.status === 404 ? 'Not found' : 'Not authorized',
                            { status: listed.status === 404 ? 404 : listed.status });
  }
  const doc = await listed.json().catch(() => null) as { files?: SessionFile[] } | null;
  const files = doc?.files || [];
  const hit = files.find((f) => f.path === wanted) || files.find((f) => f.filename === wanted);
  if (!hit) return new NextResponse('Not found', { status: 404 });

  const fid = hit.id || hit.file_id;
  const res = await fetch(
    `${GATEWAY}/v1/containers/${encodeURIComponent(sid)}/files/${encodeURIComponent(String(fid))}/content`,
    { headers, cache: 'no-store' });
  if (!res.ok || !res.body) return new NextResponse('Not found', { status: 404 });

  const name = (hit.filename || wanted).split('/').pop() || 'download';
  const out = new Headers();
  out.set('content-type', hit.media_type || res.headers.get('content-type') || 'application/octet-stream');
  const len = res.headers.get('content-length');
  if (len) out.set('content-length', len);
  // Attacker-influenceable content served from the console's own origin: nosniff so a text/plain
  // artifact can never be re-interpreted as script, and a filename so a save keeps its extension.
  out.set('x-content-type-options', 'nosniff');
  out.set('content-disposition', `inline; filename="${name.replace(/"/g, '')}"`);
  out.set('cache-control', 'private, no-store');
  return new NextResponse(res.body, { status: 200, headers: out });
}
