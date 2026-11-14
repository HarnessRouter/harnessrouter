// Provider keys, as the console knows them: how each provider the router is wired to is drawn (its
// name, its mark, the group it sits in on Bring your own key) and, for this instance, which of its own
// keys serves each model (GET /v1/admin/integrations, the routing document as the server resolves it).
// What a provider asks for (its fields, its secret, its models) is the server's catalog, never a copy
// kept here (components/hrui/ByokPage.tsx reads it from the same document).
import { useEffect, useState } from 'react';
import { harnessFetch } from '@/lib/hfetch';
import { authHeaders } from '@/lib/chat';

/** How a provider is drawn. direct: the model maker itself; cloud: the operator's own cloud account;
 *  gateway: a service routing to many; custom: an endpoint the operator names. A row shows only when
 *  the server's catalog lists the provider. */
export interface Provider {
  id: string; name: string; group: 'direct' | 'cloud' | 'gateway' | 'custom'; logo?: string;
}
export const PROVIDERS: Provider[] = [
  { id: 'anthropic', name: 'Anthropic', group: 'direct', logo: '/providers/anthropic.svg' },
  { id: 'openai', name: 'OpenAI', group: 'direct', logo: '/providers/openai.svg' },
  { id: 'google', name: 'Google AI', group: 'direct', logo: '/providers/google.svg' },
  { id: 'typesafe', name: 'TypeSafe AI', group: 'direct', logo: '/providers/typesafe.png' },
  { id: 'qoder', name: 'Qoder', group: 'direct', logo: '/logos/qoder.png' },
  { id: 'elevenlabs', name: 'ElevenLabs', group: 'direct' },
  { id: 'openrouter', name: 'OpenRouter', group: 'gateway', logo: '/providers/openrouter.svg' },
  { id: 'tokenrouter', name: 'TokenRouter', group: 'gateway', logo: '/providers/tokenrouter.png' },
  { id: 'vercel', name: 'Vercel AI Gateway', group: 'gateway', logo: '/providers/vercel.svg' },
  { id: 'llmtr', name: 'LLMTR', group: 'gateway', logo: '/providers/llmtr.svg' },
  { id: 'azure-foundry', name: 'Azure OpenAI', group: 'cloud', logo: '/providers/azure.svg' },
  { id: 'bedrock', name: 'AWS Bedrock', group: 'cloud', logo: '/providers/aws.svg' },
  { id: 'custom', name: 'Custom endpoint', group: 'custom' },
];
export const providerById = (id: string): Provider | undefined => PROVIDERS.find((p) => p.id === id);

/** One of this instance's keys: the name it was saved under and the provider it is at. */
export interface Connection { name: string; provider: string }
interface ConnectionRow extends Connection {
  key_state?: string; models?: { canonical: string }[]; config?: { api_format?: string };
}
/** A provider in the server's catalog: the backends it can drive, and for a custom endpoint the
 *  backends each API format can drive. */
interface CatalogRow { id: string; backends?: string[]; format_backends?: Record<string, string[]> }

export interface ModelProviders {
  /** The key that serves this model, or null: none of this instance's keys serves it, or (while
   *  `state` is not 'ready') it is not known which. With a backend, the key a turn on it runs
   *  through: the mapped one when that backend can use it, else the first by name that it can use
   *  and that serves the model, as the gateway's _integration_driving picks (per-model channel
   *  refusals are not in this document). */
  connectionFor: (model: string, backend?: string) => Connection | null;
  /** At least one key has been added. */
  hasConnections: boolean;
  /** The keys whose provider refused them the last time this instance asked (a HarnessRouter API key
   *  Cloud answered 401): a surface that would ask for a key says this instead. Absent until read. */
  refused?: Connection[];
  /** 'loading' until the keys are read, 'failed' when they could not be (after a few tries). Until
   *  'ready' nothing may be said about what a model runs on: no badge, and no line that tells someone
   *  who has a key to add one. */
  state: 'loading' | 'ready' | 'failed';
}

const unknown = (state: 'loading' | 'failed'): ModelProviders => ({ connectionFor: () => null, hasConnections: false, state });
const LOADING = unknown('loading');
const FAILED = unknown('failed');

/** How many times the document is asked for, and the wait before each retry (doubling). */
export const PROVIDERS_TRIES = 3;
const RETRY_MS = 800;

/** Whether a turn on `backend` can run through this key (the gateway's _integration_serves_backend). */
function drives(row: ConnectionRow, backend: string, catalog: CatalogRow[]): boolean {
  const provider = (row.provider || '').toLowerCase();
  const entry = catalog.find((c) => c.id === provider);
  if (provider !== 'custom') return !!entry?.backends?.includes(backend);
  const fmt = (row.config?.api_format || '').trim().toLowerCase();
  return !!entry?.format_backends?.[fmt]?.includes(backend);
}

const servesModel = (row: ConnectionRow, model: string) => {
  const canon = model.trim();
  return !!row.models?.some((m) => m.canonical === canon || m.canonical === canon.toLowerCase());
};

async function readConnections(): Promise<ModelProviders> {
  const r = await harnessFetch('/api/harness/v1/admin/integrations', { headers: authHeaders() });
  if (!r.ok) throw new Error(String(r.status));
  const doc = await r.json() as { integrations?: ConnectionRow[]; model_map?: Record<string, string>; catalog?: CatalogRow[] } | null;
  if (!doc || !Array.isArray(doc.integrations)) throw new Error('unreadable document');
  // model_map is the effective routing: canonical model -> the name of the key serving it
  const rows = doc.integrations;
  const byName = new Map(rows.map((i) => [i.name, i]));
  const byNameOrder = [...rows].sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
  const map = doc.model_map || {};
  const catalog = Array.isArray(doc.catalog) ? doc.catalog : [];
  const conn = (i: ConnectionRow | undefined): Connection | null => (i ? { name: i.name, provider: i.provider } : null);
  const connectionFor = (model: string, backend?: string) => {
    const mapped = map[model];
    if (!mapped) return null;
    const first = byName.get(mapped);
    if (backend === undefined || (first && drives(first, backend, catalog))) return conn(first);
    return conn(byNameOrder.find((i) => i !== first && drives(i, backend, catalog) && servesModel(i, model)));
  };
  const refused = rows.filter((i) => i.key_state === 'refused').map((i) => ({ name: i.name, provider: i.provider }));
  return { connectionFor, hasConnections: byName.size > 0, refused, state: 'ready' };
}

/** Which of this instance's keys serves each model, for a menu that lists models. The document is
 *  read once when the surface mounts and kept for its life: it is small, and a key added on Bring
 *  your own key has to show on the next visit here, so nothing outlives the mount. A read that fails
 *  is asked again a few times; until it lands, or once it has failed, no model is badged and `state`
 *  says the keys are not known (never "no key serves it" guessed). */
export function useModelProviders(): ModelProviders {
  const [mp, setMp] = useState<ModelProviders>(LOADING);
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const read = (attempt: number) => {
      readConnections()
        .then((v) => { if (alive) setMp(v); })
        .catch(() => {
          if (!alive) return;
          if (attempt + 1 >= PROVIDERS_TRIES) { setMp(FAILED); return; }
          timer = setTimeout(() => read(attempt + 1), RETRY_MS * 2 ** attempt);
        });
    };
    read(0);
    return () => { alive = false; if (timer) clearTimeout(timer); };
  }, []);
  return mp;
}
