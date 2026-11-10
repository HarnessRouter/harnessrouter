// A record open for editing together: GET is its event stream, POST carries this browser's changes. The middleware
// has already refused anyone without a session; this says who they are to the gateway, the way the proxy does, and
// the hub asks the gateway what they may do. Only for a self-hosted console, whose server this is.
import { NextRequest, NextResponse } from 'next/server';
import { LOCAL_MEMBER, LOCAL_ORG, SELF_HOSTED } from '@/lib/edition';
import { hub, MAX_UPDATE_BYTES, Refused, type Who } from '@/lib/memlive/hub';
import { AUTH_DISABLED, SESSION_COOKIE, sessionValid } from '@/lib/selfhost-auth';

export const dynamic = 'force-dynamic';
export const maxDuration = 86_400;

const CONN = /^[A-Za-z0-9-]{8,64}$/;
const ID = /^[A-Za-z0-9._:-]{1,200}$/;

async function whoOf(req: NextRequest): Promise<Who | null> {
  const key = process.env.HARNESS_INTERNAL_KEY || '';
  if (!SELF_HOSTED || !key) return null;
  if (!(AUTH_DISABLED || await sessionValid(req.cookies.get(SESSION_COOKIE)?.value))) return null;
  const headers: Record<string, string> = { 'x-harness-internal': key, 'x-harness-org': LOCAL_ORG, 'x-harness-member': LOCAL_MEMBER };
  const [ws, isDefault] = (req.cookies.get('hr_workspace')?.value || '').split('|');
  if (ws && /^[A-Za-z0-9._-]{1,128}$/.test(ws)) {
    headers['x-harness-workspace'] = ws;
    if (isDefault === '1') headers['x-harness-workspace-default'] = '1';
  }
  return { headers, member: LOCAL_MEMBER };
}

const say = (status: number, detail: string) => NextResponse.json({ detail }, { status });
const refusal = (e: unknown) => (e instanceof Refused ? say(e.status, e.message || 'Not allowed.') : say(500, 'This record could not be opened just now.'));

export async function GET(req: NextRequest, ctx: { params: Promise<{ mid: string; rid: string }> }) {
  const who = await whoOf(req);
  if (!who) return say(401, 'Sign in again.');
  const { mid, rid } = await ctx.params;
  const c = req.nextUrl.searchParams.get('c') || '';
  if (!ID.test(mid) || !ID.test(rid) || !CONN.test(c)) return say(400, 'Not a record.');

  const text = new TextEncoder();
  let leave: (() => void) | null = null;
  let closed = false;
  let out: ReadableStreamDefaultController<Uint8Array> | null = null;
  const finish = () => {
    if (closed) return;
    closed = true;
    leave?.();
    try { out?.close(); } catch { /* the reader has gone */ }
  };
  const send = (event: string, data: unknown) => {
    if (closed || !out) return;
    try {
      out.enqueue(text.encode(event ? `event: ${event}\ndata: ${JSON.stringify(data)}\n\n` : ': still here\n\n'));
    } catch { finish(); }
  };
  const stream = new ReadableStream<Uint8Array>({
    start(controller) { out = controller; },
    cancel() { finish(); },
  });
  req.signal.addEventListener('abort', finish);
  try {
    leave = await hub.join(mid, rid, c, who, send, finish);
  } catch (e) {
    closed = true;
    return refusal(e);
  }
  if (req.signal.aborted) { leave(); return new Response(null, { status: 204 }); }
  return new Response(stream, {
    headers: { 'content-type': 'text/event-stream', 'cache-control': 'no-cache, no-transform', 'x-accel-buffering': 'no' },
  });
}

export async function POST(req: NextRequest, ctx: { params: Promise<{ mid: string; rid: string }> }) {
  // a cookie is sent from anywhere, so a write says it came from this console's own pages
  const origin = req.headers.get('origin');
  const host = req.headers.get('x-forwarded-host') || req.headers.get('host');
  if (origin && host && new URL(origin).host !== host) return say(403, 'Not from this console.');
  const who = await whoOf(req);
  if (!who) return say(401, 'Sign in again.');
  const { mid, rid } = await ctx.params;
  const raw = await req.text();
  if (raw.length > MAX_UPDATE_BYTES * 1.4) return say(413, 'Too much at once.');
  let b: { c?: string; u?: string; a?: string };
  try { b = JSON.parse(raw); } catch { return say(400, 'Not an update.'); }
  if (!b.c || !CONN.test(b.c)) return say(400, 'Not an update.');
  try {
    hub.update(mid, rid, b.c, b.u ? new Uint8Array(Buffer.from(b.u, 'base64')) : undefined, b.a ? new Uint8Array(Buffer.from(b.a, 'base64')) : undefined);
    return new Response(null, { status: 204 });
  } catch (e) {
    if (e instanceof Refused) return refusal(e);
    return say(400, 'Not an update.');
  }
}
