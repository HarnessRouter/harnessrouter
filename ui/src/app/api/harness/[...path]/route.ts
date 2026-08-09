// BFF proxy to the Harness Gateway (ACA), same-origin /api/harness/* -> gateway.
//
// The gateway's OpenAI Responses-compatible /v1 surface authenticates either by a public
// per-org Bearer API key OR by an internal trust header (the web app, already behind the engine
// JWT). The browser is the latter: this BFF injects X-Harness-Internal (HARNESS_INTERNAL_KEY,
// server-only) and forwards the caller's org/member (X-Harness-Org / X-Harness-Member) so the
// gateway resolves the principal without the browser ever holding the internal key.
//
// SSE responses (text/event-stream from /v1/responses?stream) stream through unbuffered so the
// Workbench gets live reasoning/tool/text deltas instead of one blob at turn end.
//   HARNESS_GATEWAY_URL   e.g. https://harness-gateway.<env>.eastus2.azurecontainerapps.io
//   HARNESS_INTERNAL_KEY  internal trust key (matches the gateway's secret)
//
// SELF-HOSTED: there is no login, so there is no JWT to gate the key on. The BFF is instead the
// only thing that can reach the gateway (it is bound to the container's loopback, and only this
// UI's port is published), so it presents the key on its own and PINS org/member from server
// constants — a request from the browser cannot claim an identity this box doesn't have.
import type { NextRequest } from 'next/server';
import { LOCAL_MEMBER, LOCAL_ORG, SELF_HOSTED } from '@/lib/edition';

export const dynamic = 'force-dynamic';
export const maxDuration = 800; // long agent turns stream for minutes

const GATEWAY =
  process.env.HARNESS_GATEWAY_URL ||
  'https://api.harnessrouter.ai';
const INTERNAL_KEY = process.env.HARNESS_INTERNAL_KEY || '';

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const target = `${GATEWAY.replace(/\/$/, '')}/${(path || []).join('/')}${req.nextUrl.search}`;
  const headers: Record<string, string> = {};
  const ct = req.headers.get('content-type');
  if (ct) headers['content-type'] = ct;
  const auth = req.headers.get('authorization');
  if (auth) headers['authorization'] = auth;
  // Internal trust path (LIVE-B closed): the key is attached ONLY alongside the caller's login
  // JWT, which the console now sends on EVERY /api/harness call via the harnessFetch wrapper. The
  // gateway (HR_IDENTITY_MODE=enforce) VERIFIES that JWT and derives org/member from its signed
  // claims, the forwarded org/member headers are no longer trusted for identity. A request with
  // no bearer (no session) gets no key -> the gateway 401s it, so it can't ride the BFF onto the
  // internal path with self-asserted identity.
  if (INTERNAL_KEY && (auth || SELF_HOSTED)) headers['x-harness-internal'] = INTERNAL_KEY;
  if (SELF_HOSTED) {
    headers['x-harness-org'] = LOCAL_ORG;
    headers['x-harness-member'] = LOCAL_MEMBER;
  } else {
    const org = req.headers.get('x-harness-org');
    if (org) headers['x-harness-org'] = org;
    const member = req.headers.get('x-harness-member');
    if (member) headers['x-harness-member'] = member;
  }

  // Additional Headers (app-level auth pass-through): the Playground sends the harness's declared
  // custom headers as real request headers. Forward anything not hop-by-hop / browser-infra so the
  // gateway can capture declared names and render $headers.{name} refs into MCP configs. Names the
  // gateway hasn't declared on the harness are simply ignored there.
  const HOP: Set<string> = new Set(['host', 'connection', 'content-length', 'accept-encoding',
    'accept', 'accept-language', 'cookie', 'user-agent', 'referer', 'origin', 'dnt', 'priority',
    'upgrade-insecure-requests', 'cache-control', 'pragma', 'te', 'trailer', 'transfer-encoding',
    'keep-alive', 'proxy-authorization', 'proxy-authenticate', 'upgrade']);
  req.headers.forEach((v, k) => {
    const lk = k.toLowerCase();
    if (HOP.has(lk) || lk.startsWith('sec-') || lk.startsWith('x-forwarded') ||
        lk.startsWith('x-vercel') || lk.startsWith('x-real-ip') || lk in headers || headers[lk]) return;
    if (lk === 'x-harness-internal') return;   // never let a browser spoof the trust key
    headers[lk] = v;
  });

  const init: RequestInit = { method: req.method, headers, cache: 'no-store' };
  // STREAM the request body straight through (byte-exact, no buffering) so large uploads (up to GBs)
  // never get fully materialized in the BFF's memory. duplex:'half' is required by undici/fetch when
  // body is a ReadableStream. Falls back to arrayBuffer if the runtime didn't expose a body stream.
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    if (req.body) { init.body = req.body; (init as RequestInit & { duplex: 'half' }).duplex = 'half'; }
    else init.body = await req.arrayBuffer();
  }

  try {
    const res = await fetch(target, init);
    const ctType = res.headers.get('content-type') || 'application/json';
    // Stream SSE through without buffering (live deltas).
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
    // STREAM the response body straight through (HR-INF-015): traces, workspace artifacts, ZIP
    // archives, and file downloads can be GBs, buffering them in the BFF's memory (the old
    // arrayBuffer()) was a per-request materialization. Pass res.body through byte-exact so peak
    // BFF memory stays O(chunk) regardless of payload size. content-length/disposition are
    // preserved when present so downloads still name + size correctly.
    const out: Record<string, string> = { 'content-type': ctType };
    const cd = res.headers.get('content-disposition');
    if (cd) out['content-disposition'] = cd;
    const cl = res.headers.get('content-length');
    if (cl) out['content-length'] = cl;
    return new Response(res.body, { status: res.status, headers: out });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    return new Response(JSON.stringify({ detail: `harness-gateway unreachable: ${msg}` }), {
      status: 502, headers: { 'content-type': 'application/json' },
    });
  }
}
export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
