// Push local harnesses to a hosted HarnessRouter account.
//
// ONE-WAY BY CONSTRUCTION. This route can only send. There is no pull counterpart anywhere in
// this repo, and that is a design decision rather than an omission: a local instance is a
// scratchpad you iterate in, and letting hosted state flow back would make "which copy is
// real?" a question users have to answer on every edit. Promotion is a deliberate act with one
// direction, so the hosted copy is always the authority once a harness is promoted.
//
// The hosted API key is supplied per request by the browser and used for exactly this call. It
// is never written to disk, never logged, and never stored server-side — if you close the tab,
// it is gone. That is why the key is a parameter here rather than instance configuration.
import { NextRequest } from 'next/server';
import { harnessBody, type Harness } from '@/lib/harness';

const DEFAULT_CLOUD = 'https://api.harnessrouter.ai';

interface PushBody {
  apiKey: string;
  cloudUrl?: string;
  harnesses: Harness[];
}

export const runtime = 'nodejs';

export async function POST(req: NextRequest) {
  let body: PushBody;
  try {
    body = await req.json();
  } catch {
    return Response.json({ detail: 'invalid request body' }, { status: 400 });
  }

  const apiKey = String(body.apiKey || '').trim();
  const base = String(body.cloudUrl || DEFAULT_CLOUD).replace(/\/$/, '');
  const list = Array.isArray(body.harnesses) ? body.harnesses : [];
  if (!apiKey) return Response.json({ detail: 'a hosted API key is required' }, { status: 400 });
  if (!list.length) return Response.json({ detail: 'select at least one harness' }, { status: 400 });

  const results: { name: string; ok: boolean; id?: string; error?: string }[] = [];
  for (const h of list) {
    // The same mapping the local console writes with — the hosted API takes the same body, which
    // is what makes promotion a copy rather than a translation. Local bookkeeping (id, timestamps,
    // org, workspace) isn't in it, so the hosted side mints its own.
    const payload = harnessBody(h);
    const name = String(payload.name || 'untitled');
    try {
      const r = await fetch(`${base}/v1/harnesses`, {
        method: 'POST',
        headers: { 'content-type': 'application/json', authorization: `Bearer ${apiKey}` },
        body: JSON.stringify(payload),
      });
      if (r.ok) {
        const created = await r.json().catch(() => ({}));
        results.push({ name, ok: true, id: created?.id });
      } else {
        // Surface the hosted side's reason (bad key, name clash, quota) but never echo the key.
        let detail = `HTTP ${r.status}`;
        try { detail = (await r.json())?.detail || detail; } catch { /* keep the status */ }
        results.push({ name, ok: false, error: String(detail) });
      }
    } catch {
      results.push({ name, ok: false, error: 'could not reach the hosted API' });
    }
  }
  return Response.json({ results, pushed: results.filter((r) => r.ok).length });
}
