// Same-origin proxy to the local gateway.
//
// Why proxy at all when there is no auth to inject? Two reasons that still apply self-hosted:
// the browser gets one origin (no CORS, no second hostname to configure), and the gateway can
// stay bound to the container's internal network instead of being published to the host. The
// only thing published is this UI.
//
// It carries exactly one credential, and only ever server-side: the gateway's internal key,
// generated per container and never sent to the browser. This is the same service-to-service
// mechanism the hosted deployment uses — the gateway trusts the caller's identity headers only
// when that key is present, which is why they are set HERE and not forwarded from the browser.
// Provider keys are not involved at all: they live in the gateway's secret store and never
// travel this path.
import { NextRequest } from 'next/server';
import { LOCAL_MEMBER, LOCAL_ORG } from '@/lib/identity';

const GATEWAY = (process.env.GATEWAY_URL || 'http://127.0.0.1:8080').replace(/\/$/, '');
const INTERNAL_KEY = process.env.HARNESS_INTERNAL_KEY || '';

// Streaming turns must not be buffered by the runtime, so this runs on Node and pipes the body.
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

async function proxy(req: NextRequest, path: string[]) {
  // Without the key the gateway rejects everything as unauthenticated, which looks like a bug in
  // the console rather than a missing variable. Say what is actually wrong.
  if (!INTERNAL_KEY) {
    return new Response(
      JSON.stringify({ detail: 'HARNESS_INTERNAL_KEY is not set for the console process' }),
      { status: 500, headers: { 'content-type': 'application/json' } },
    );
  }

  const search = req.nextUrl.search || '';
  const url = `${GATEWAY}/${path.join('/')}${search}`;

  const headers = new Headers();
  // Forward only what the gateway reads. Copying blindly would drag along hop-by-hop headers
  // (host, connection, content-length) that break a proxied streaming response.
  //
  // Note which headers are NOT in this list: org and member. Those are set below from server
  // constants, so a request from the browser cannot claim a different identity than the one
  // this instance has. Workspace is browser-chosen because it is a user-facing scope the
  // operator switches between, not a trust boundary.
  for (const k of ['content-type', 'accept', 'x-harness-workspace',
                   'x-harness-workspace-default', 'x-harness-id', 'idempotency-key']) {
    const v = req.headers.get(k);
    if (v) headers.set(k, v);
  }
  headers.set('x-harness-org', LOCAL_ORG);
  headers.set('x-harness-member', LOCAL_MEMBER);
  headers.set('x-harness-internal', INTERNAL_KEY);

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
