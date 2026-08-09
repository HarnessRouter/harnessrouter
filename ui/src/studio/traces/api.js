// Traces client — harness-gateway read APIs via the same-origin /api/harness BFF (which injects the
// internal trust key + forwards org/member). Scoped to the signed-in org + member (per-user
// isolation) and, when set, filtered to one harness (the Workbench Traces tab).
import { harnessFetch } from '@/lib/hfetch';
import { getSession } from '@/lib/auth';

function org() { return getSession()?.orgId || 'global'; }
function member() { return getSession()?.member?.email || getSession()?.member?.id || ''; }

let _harness = '';
export function setTraceHarness(h) { _harness = h || ''; }

async function jget(path) {
  const res = await harnessFetch('/api/harness' + path);
  if (!res.ok) throw new Error(`traces ${res.status} ${path}`);
  return res.json();
}

const enc = encodeURIComponent;

export const tracesApi = {
  // Paginated session cards, newest-first, scoped to org + member (+ harness when set).
  list({ limit = 25, cursor = '' } = {}) {
    const q = new URLSearchParams({ org: org(), member: member(), limit: String(limit) });
    if (_harness) q.set('harness', _harness);
    if (cursor) q.set('cursor', cursor);
    return jget(`/v1/traces?${q.toString()}`);
  },
  manifest(sid) { return jget(`/v1/traces/${enc(sid)}`); },
  async events(sid, chunks) {
    // COMPACT load: the gateway returns the transcript with long strings truncated, so even a
    // 30 MB long-horizon trace ships as a few hundred KB and renders instantly. Full event content
    // is fetched lazily (fullEvents) only when the user opens an event. Clipped events carry
    // _clipped:true; structure is identical so flatten() rows align positionally with the full load.
    try {
      const res = await harnessFetch(`/api/harness/v1/traces/${enc(sid)}/all?compact=1`);
      if (res.ok) return parseNdjson(await res.text());
    } catch { /* fall through to per-chunk for older gateways */ }
    const ns = chunks && chunks.length ? chunks.map((_, i) => i) : [0];
    const out = [];
    for (const i of ns) {
      const res = await harnessFetch(`/api/harness/v1/traces/${enc(sid)}/events?chunk=${i}`);
      if (!res.ok) break;
      out.push(...parseNdjson(await res.text()));
    }
    return out;
  },
  // FULL (un-clipped) transcript — fetched lazily the first time a clipped event's detail is opened.
  async fullEvents(sid) {
    const res = await harnessFetch(`/api/harness/v1/traces/${enc(sid)}/all`);
    if (!res.ok) throw new Error(`traces ${res.status} /all`);
    return parseNdjson(await res.text());
  },
};

function parseNdjson(text) {
  const out = [];
  for (const line of text.split('\n')) {
    const t = line.trim();
    if (!t) continue;
    try { out.push(JSON.parse(t)); } catch { /* skip malformed */ }
  }
  return out;
}
