// The routing document as Bring your own key reads and writes it (GET/PUT /v1/admin/integrations), and
// the rules the server applies to it, so the page can say what will happen before it happens:
//
// - A connection ("key") is one integration: a name, a provider, a config, and the models it serves
//   (the server resolves them from its catalog; a custom endpoint lists its own). Several per provider
//   are allowed; names are unique. Secrets never come back: a stored one reads as the sentinel and goes
//   back as the sentinel, which keeps it.
// - What each provider asks for (its fields, its secret, its endpoint, its models) is the server's
//   catalog (`catalog`), never a copy kept in the console.
// - Which connection serves a model is the model map (chat models) and the image model map (image
//   models). The server answers with the effective maps: a stored route wins, every other model a
//   connection can serve is claimed by the first one that can, and a stored empty route means "off"
//   (no key serves it, so it cannot be chosen). A model a connection can serve that the effective map
//   leaves out is therefore one switched off on purpose.
// - A PUT that carries a map stores it as the stored routes, whole; one that leaves a map out leaves
//   it as it was. So every write that sends a map sends the effective routes that still point at a
//   connection, plus every model switched off, plus the change being made: nothing routes differently
//   except what the person changed.
// - Video, speech and music are not routed by a map: each capability is an ordered chain, and the
//   first candidate whose provider is connected wins (media_chains, media_policy).
import { providerById, type Provider } from '@/lib/providers';
import { harnessFetch } from '@/lib/hfetch';
import { authHeaders } from '@/lib/chat';

export interface ModelRow { canonical: string; provider_id: string }
export interface Integration {
  name: string; provider: string; config: Record<string, string>;
  models: ModelRow[];
  /** image models it can serve, routed apart from chat models */
  image_models?: ModelRow[];
  /** what is left on a HarnessRouter API key's account, read by the server; absent while unknown */
  balance?: { usd: number; is_deficit: boolean; as_of: string };
}
export interface ProviderField { key: string; label: string; placeholder?: string }
export interface CatalogEntry {
  id: string; label: string;
  /** the endpoint the server applies; null when it varies, and a field asks for it */
  base_url: string | null;
  fields: ProviderField[];
  secret: string; secret_label: string; key_hint?: string;
  /** the provider can also be reached as an application in the operator's Microsoft Entra directory */
  entra?: { fields: ProviderField[]; secret: string; secret_label: string };
  models: ModelRow[];
  /** a custom endpoint: every model id a harness can ask for, offered for its rows */
  canonicals?: string[];
  /** a custom endpoint: the harnesses each API format drives */
  format_backends?: Record<string, string[]>;
  backends: string[];
}
export interface MediaCandidate {
  model: string; provider: string; connected: boolean; off: boolean;
  resolution?: string; seconds?: number | null; duration_ignored?: boolean; accepts_input_image?: boolean | null;
  usd?: number | null; unavailable?: string;
}
export interface MediaChain { capability: string; unit: string; candidates: MediaCandidate[] }
export type MediaPolicy = Record<string, { order?: string[]; disabled?: string[] }>;
export interface Doc {
  integrations: Integration[];
  model_map: Record<string, string>;
  image_model_map?: Record<string, string>;
  providers: string[];
  catalog: CatalogEntry[];
  media_chains?: MediaChain[];
  media_policy?: MediaPolicy;
  /** where a HarnessRouter API key's credit is added */
  hosted_console?: string;
}

export const SECRET = '__secret__';
/** The provider whose key comes from the HarnessRouter hand-off (POST /v1/admin/connect). */
export const HOSTED = 'harnessrouter';
export const isEntra = (i: Integration) => i.config?.auth === 'entra';
export const servable = (i: Integration) => (i.models || []).map((m) => m.canonical);
export const servableImages = (i: Integration) => (i.image_models || []).map((m) => m.canonical);

/** How a provider is drawn: the console's own mark and group when it has one, else the catalog's
 *  label in the group the catalog implies (a custom endpoint is its own group). */
export function look(c: Pick<CatalogEntry, 'id' | 'label'>): Provider {
  const p = providerById(c.id);
  return { id: c.id, name: c.label || p?.name || c.id, group: p?.group || (c.id === 'custom' ? 'custom' : 'gateway'), logo: p?.logo };
}

const RANK: Record<Provider['group'], number> = { direct: 0, cloud: 1, gateway: 2, custom: 2 };
/** the design's preference among keys that can serve a model: direct, then your cloud, then a gateway */
export const rankOf = (provider: string) => RANK[providerById(provider)?.group || 'gateway'];

type Routes = Record<string, string>;
/** Models a connection can serve, by `of`, that `eff` (an effective map) leaves out: switched off. */
function offOf(integrations: Integration[], eff: Routes, of: (i: Integration) => string[]): string[] {
  const all = new Set(integrations.flatMap(of));
  return [...all].filter((m) => !(m in eff));
}
function routesFor(eff: Routes, before: Integration[], after: Integration[], of: (i: Integration) => string[], change: Routes): Routes {
  const names = new Set(after.map((i) => i.name));
  const mm: Routes = Object.fromEntries(Object.entries(eff).filter(([, v]) => names.has(v)));
  for (const m of offOf(before, eff, of)) mm[m] = '';
  return { ...mm, ...change };
}

/** The chat model map to send with `integrations`: today's routes that still point at a connection,
 *  the models switched off, then `change`. */
export function mapFor(doc: Doc, integrations: Integration[], change: Routes = {}): Routes {
  return routesFor(doc.model_map || {}, doc.integrations, integrations, servable, change);
}
/** The image model map to send with `integrations`, by the same rule. */
export function imageMapFor(doc: Doc, integrations: Integration[], change: Routes = {}): Routes {
  return routesFor(doc.image_model_map || {}, doc.integrations, integrations, servableImages, change);
}

/** When a key is added: the models it can serve that today run on a key the design ranks lower (a
 *  gateway, when the new key is the maker's own) move to it. Equal rank: nothing moves. */
export function claimsFor(doc: Doc, provider: string, name: string, models: string[]): Routes {
  const r = rankOf(provider);
  const byName = new Map(doc.integrations.map((i) => [i.name, i]));
  const out: Routes = {};
  for (const m of models) {
    const cur = doc.model_map?.[m];
    const at = cur ? byName.get(cur) : undefined;
    if (at && rankOf(at.provider) > r) out[m] = name;
  }
  return out;
}

export interface PutBody { integrations: Integration[]; model_map?: Routes; image_model_map?: Routes; media_policy?: MediaPolicy }

/** Replace the document. A map left out stays as it was on the server. `detail` is the server's own
 *  reason when it refused (a connection's sign-in that failed names what is missing). */
export async function putDoc(body: PutBody): Promise<{ ok: true } | { ok: false; detail: string }> {
  try {
    const r = await harnessFetch('/api/harness/v1/admin/integrations', { method: 'PUT', headers: authHeaders(), body: JSON.stringify(body) });
    if (r.ok) return { ok: true };
    const d = await r.json().catch(() => null) as { detail?: unknown } | null;
    return { ok: false, detail: typeof d?.detail === 'string' ? d.detail : '' };
  } catch { return { ok: false, detail: '' }; }
}

export async function getDoc(): Promise<Doc> {
  const r = await harnessFetch('/api/harness/v1/admin/integrations', { headers: authHeaders() });
  if (!r.ok) throw new Error(String(r.status));
  const d = await r.json() as Doc | null;
  if (!d || !Array.isArray(d.integrations) || !Array.isArray(d.catalog)) throw new Error('unreadable document');
  return d;
}

/** A new connection's name: the label, else "default", then "key N"; unique in the document. */
export function nameFor(doc: Doc, provider: string, label: string): string {
  const mine = doc.integrations.filter((i) => i.provider === provider);
  const base = label.trim();
  let name = base || (mine.length ? `key ${mine.length + 1}` : 'default');
  const taken = new Set(doc.integrations.map((i) => i.name));
  for (let n = 2; taken.has(name); n += 1) name = `${base || 'key'} ${n}`;
  return name;
}

/** The HarnessRouter API key hand-off: this instance asks its own server to open one (the secret
 *  stays there), the person finishes it on the page `url` names, and `poll` reads the code until
 *  the key is ready (202 while it waits). */
export async function startHandoff(): Promise<{ code: string; url: string }> {
  const r = await harnessFetch('/api/harness/v1/admin/connect', {
    method: 'POST', headers: authHeaders(),
    body: JSON.stringify({ instance: typeof window !== 'undefined' ? window.location.host : '' }),
  });
  if (!r.ok) throw new Error(String(r.status));
  const j = await r.json() as { code?: string; url?: string };
  if (!j?.code || !j.url) throw new Error('no code');
  return { code: j.code, url: j.url };
}
export interface HandedKey { api_key: string; endpoint?: string; models_url?: string; balance_url?: string; name?: string }
/** One read of the hand-off: the key once it is ready, 'waiting' while it is not, 'failed' when the
 *  code is gone or refused. A read that gets no answer is 'waiting' (the next read asks again). */
export async function pollHandoff(code: string): Promise<HandedKey | 'waiting' | 'failed'> {
  let r: Response;
  try { r = await harnessFetch(`/api/harness/v1/admin/connect/${encodeURIComponent(code)}`, { headers: authHeaders() }); }
  catch { return 'waiting'; }
  if (r.status === 202) return 'waiting';
  const j = await r.json().catch(() => null) as (HandedKey & { status?: string }) | null;
  return r.ok && j?.status === 'ready' && j.api_key ? j : 'failed';
}
