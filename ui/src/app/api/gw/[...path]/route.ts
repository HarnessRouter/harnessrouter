// Same-origin proxy to the local gateway.
//
// Why proxy at all when there is no auth to inject? Two reasons that still apply self-hosted:
// the browser gets one origin (no CORS, no second hostname to configure), and the gateway can
// stay bound to the container's internal network instead of being published to the host. The
// only thing published is this UI.
//
// It adds NO credentials. There is nothing to add: the gateway runs with identity off, and the
// provider keys live server-side in the gateway's secret store — they never reach the browser
// and therefore never pass through here.
import { NextRequest } from 'next/server';

const GATEWAY = (process.env.GATEWAY_URL || 'http://127.0.0.1:8080').replace(/\/$/, '');

// Streaming turns must not be buffered by the runtime, so this runs on Node and pipes the body.
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

async function proxy(req: NextRequest, path: string[]) {
  const search = req.nextUrl.search || '';
  const url = `${GATEWAY}/${path.join('/')}${search}`;

  const headers = new Headers();
  // Forward only what the gateway reads. Copying blindly would drag along hop-by-hop headers
  // (host, connection, content-length) that break a proxied streaming response.
  for (const k of ['content-type', 'accept', 'x-harness-org', 'x-harness-member',
                   'x-harness-workspace', 'x-harness-workspace-default', 'x-harness-id',
                   'idempotency-key']) {
    const v = req.headers.get(k);
    if (v) headers.set(k, v);
  }

  const method = req.method.toUpperCase();
  const body = method === 'GET' || method === 'HEAD' ? undefined : await req.arrayBuffer();

  let upstream: Response;
  try {
    upstream = await fetch(url, { method, headers, body, redirect: 'manual',
                                  // @ts-expect-error -- Node fetch streaming duplex
                                  duplex: 'half' });
  } catch {
    return new Response(JSON.stringify({ detail: 'gateway unreachable' }),
                        { status: 502, headers: { 'content-type': 'application/json' } });
  }

  // Pass the body through untouched so Server-Sent Events stream rather than accumulate.
  const out = new Headers();
  for (const k of ['content-type', 'cache-control', 'x-harness-session']) {
    const v = upstream.headers.get(k);
    if (v) out.set(k, v);
  }
  if (upstream.headers.get('content-type')?.includes('text/event-stream')) {
    out.set('cache-control', 'no-cache, no-transform');
    out.set('x-accel-buffering', 'no');
  }
  return new Response(upstream.body, { status: upstream.status, headers: out });
}

type Ctx = { params: Promise<{ path: string[] }> };
export async function GET(req: NextRequest, ctx: Ctx) { return proxy(req, (await ctx.params).path); }
export async function POST(req: NextRequest, ctx: Ctx) { return proxy(req, (await ctx.params).path); }
export async function PUT(req: NextRequest, ctx: Ctx) { return proxy(req, (await ctx.params).path); }
export async function PATCH(req: NextRequest, ctx: Ctx) { return proxy(req, (await ctx.params).path); }
export async function DELETE(req: NextRequest, ctx: Ctx) { return proxy(req, (await ctx.params).path); }
