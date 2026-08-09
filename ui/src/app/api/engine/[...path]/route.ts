// BFF proxy to the AgentStudio Workflow Engine (ACA).
//
// Same-origin /api/engine/* from the browser -> the engine, server-side. The
// engine URL (and any future internal key) stay on the server. Used by the auth
// flow (/v1/auth/login, /switch-org, /me) and any other engine call from the UI.
// Authorization: Bearer is forwarded verbatim so the engine verifies the JWT.
//
//   WORKFLOW_ENGINE_URL  the engine to proxy to. There is deliberately NO default: an
//   unconfigured deployment must fail closed rather than silently reach someone else's engine.
//   Self-hosted there is no engine at all, and this route refuses outright.
import type { NextRequest } from 'next/server';
import { SELF_HOSTED } from '@/lib/edition';

export const dynamic = 'force-dynamic';
// Allow long-lived SSE run-progress streams + slow engine calls. On Vercel Hobby
// the function cap is 60s (the studio's EventSource auto-reconnects past that and
// the getRun poll fills any gap); raise on Pro if you want longer single streams.
export const maxDuration = 60;

const ENGINE = process.env.WORKFLOW_ENGINE_URL || '';

const unavailable = (detail: string) =>
  new Response(JSON.stringify({ detail }), {
    status: 501, headers: { 'content-type': 'application/json' },
  });

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  // A self-hosted box has no accounts service. Refusing here is the point: the alternative is
  // reaching out to whatever host happened to be compiled in, which would make "nothing leaves
  // the box" false.
  if (SELF_HOSTED) return unavailable('this instance has no accounts service');
  if (!ENGINE) return unavailable('WORKFLOW_ENGINE_URL is not configured');
  const { path } = await ctx.params;
  const target = `${ENGINE.replace(/\/$/, '')}/${(path || []).join('/')}${req.nextUrl.search}`;

  const headers: Record<string, string> = {};
  const ct = req.headers.get('content-type');
  if (ct) headers['content-type'] = ct;
  const auth = req.headers.get('authorization');
  if (auth) headers['authorization'] = auth;
  // Forward the caller's address so the engine can attribute and rate-limit by source. Without
  // this every request looks like it came from this server, which is why a 2026-07-30/31 signup
  // flood was un-attributable and un-throttleable at the app layer. nginx sets these from the
  // real peer; we only relay them (the engine is not publicly reachable, so it can trust us).
  const fwd = req.headers.get('x-forwarded-for');
  if (fwd) headers['x-forwarded-for'] = fwd;
  const realIp = req.headers.get('x-real-ip');
  if (realIp) headers['x-real-ip'] = realIp;

  // Forward the body as raw bytes, not text, multipart/form-data uploads (chat
  // attachments) carry binary that req.text() would corrupt by round-tripping
  // through UTF-8 (0x89… PNG header → U+FFFD). arrayBuffer is byte-exact for JSON
  // too, so it is safe for every method.
  const init: RequestInit = { method: req.method, headers, cache: 'no-store' };
  if (req.method !== 'GET' && req.method !== 'HEAD') init.body = await req.arrayBuffer();

  try {
    const res = await fetch(target, init);
    const ctType = res.headers.get('content-type') || 'application/json';
    // Stream Server-Sent Events (run progress) through WITHOUT buffering, so the
    // studio's EventSource gets live node_run/result events instead of one blob
    // when the run finally ends. Plain JSON is buffered as before.
    if (ctType.includes('text/event-stream') && res.body) {
      return new Response(res.body, {
        status: res.status,
        headers: {
          'content-type': 'text/event-stream',
          'cache-control': 'no-cache, no-transform',
          connection: 'keep-alive',
          'x-accel-buffering': 'no',
        },
      });
    }
    const body = await res.text();
    return new Response(body, {
      status: res.status,
      headers: { 'content-type': ctType },
    });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    return new Response(JSON.stringify({ detail: `workflow-engine unreachable: ${msg}` }), {
      status: 502,
      headers: { 'content-type': 'application/json' },
    });
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
