// Memories (UHP Memories chapter): where agents keep what should outlast one task. Every function
// here is one call to the service; what the console makes of the answers lives in
// components/hrui/memories.
import { harnessFetch } from '@/lib/hfetch';
import { gwHeaders } from '@/lib/harness';

export type Privilege = 'read' | 'write' | 'create' | 'delete';

export interface Memory {
  id: string; object: 'memory'; name: string; description: string; provider: string;
  parent_id: string | null; ancestors: string[]; restricted: boolean; privileges: Privilege[];
  records: { count: number | null }; children?: { count: number }; createdAt?: number; updatedAt?: number;
}
export interface Writer { kind: string; id: string; type?: 'human' | 'agent'; on_behalf_of?: string; consolidation_id?: string }
export interface ContentPart { type: string; text?: string; role?: string; file?: { id: string; name?: string; media_type?: string; bytes?: number }; text_source?: string }
export interface Reference { rel?: string; memory_id?: string; record_id: string; available: boolean }
export interface MemoryRecord {
  id: string; object: 'memory.record'; memory_id: string; type: string; title: string;
  content: ContentPart[]; attributes: Record<string, unknown>;
  version: number; status: 'active' | 'superseded' | 'forgotten'; supersedes: number | null;
  time: { valid_from: string | null; valid_to: string | null; written_at: string | null; invalidated_at: string | null };
  written_by: Writer; references: Reference[]; trust: 'untrusted';
  /** Present only on a record the service derives from a source it keeps elsewhere (a section of a
   *  document). It changes when its source does, and is not revised or forgotten here. */
  follows?: { kind?: string; id?: string; name?: string };
}
export interface GraphNode { record: MemoryRecord; memory: { id: string; name: string } }
export interface GraphEdge { from: { memory_id?: string; record_id: string }; to: { memory_id?: string; record_id: string }; rel?: string; available: boolean }
export interface MemoryGraph { nodes: GraphNode[]; edges: GraphEdge[]; truncated: boolean; degraded: string[] }
export interface Grant { id: string; memory_id: string; principal: string; privileges: Privilege[]; inherited: boolean }

/** What a provider says it does (GET /v1/memories/providers). The console offers from this and
 *  nothing else: never from a provider's name. */
export interface Provider {
  id: string; connected?: boolean; isolation?: string; derivation?: string;
  observe?: { keeps_episodes?: boolean; answers?: string };
  recall?: { signals?: string[]; abstain?: boolean };
  history?: { content?: 'versions' | 'snapshots' | 'none'; structure?: string; emulated?: boolean };
  /** A plain word speaks of what a writer stated. `{ derived: true }` opens what the provider found. */
  revise?: string | { derived?: boolean } | false | null;
  forget?: string | false | null;
  erase?: { unreachable?: string } | false | null;
  prime?: boolean; consolidate?: string | false; holds?: boolean;
  graph?: { entities?: 'derived' | 'stated' | 'none' };
  /** `none`: nothing reads a schema. `guides`: types, with properties and relations as declared.
   *  `labels`: a flat vocabulary of names applied to facts. */
  schema?: { mode?: 'guides' | 'labels' | 'none'; properties?: boolean; relations?: boolean };
  layout?: string;
  content?: { media?: string[]; bytes?: string; describes?: string[] };
}

export type PropType = 'text' | 'choice' | 'date' | 'number' | 'yesno';
export interface SchemaProperty { name: string; type: PropType; description?: string; options?: string[] }
export interface SchemaType { name: string; description?: string; properties?: SchemaProperty[]; color?: string; icon?: string; x?: number; y?: number; caption?: string }
export interface SchemaRelation { name: string; description?: string; from: string; to: string }
export interface MemorySchema { types: SchemaType[]; relations?: SchemaRelation[] }

export interface HarnessMemoryRow { id: string; name: string; description: string; records: { count: number | null }; children?: { count: number }; privileges: Privilege[]; default: boolean }
export interface HarnessMemories { object: 'harness.memories'; principal: string; default_memory_id: string | null; observe: boolean; data: HarnessMemoryRow[] }

/** A refusal of the service, with its code (`memory_not_found`, `memory_forbidden`,
 *  `memory_invalid`, `memory_unsupported`, `memory_unavailable`, …) and the field it names. */
export class MemoryApiError extends Error {
  constructor(public status: number, public code: string, message: string, public param?: string) { super(message); }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await harnessFetch(`/api/harness${path}`, {
    method, headers: gwHeaders(), cache: 'no-store',
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) {
    let code = '', message = `The service answered ${r.status}.`, param: string | undefined;
    try {
      const j = await r.json();
      const e = j?.error || j?.detail || {};
      if (typeof e === 'string') message = e;
      else { code = e.code || ''; message = e.message || message; param = e.param || undefined; }
    } catch { /* keep the status */ }
    throw new MemoryApiError(r.status, code, message, param);
  }
  return r.json() as Promise<T>;
}
const q = (o: Record<string, string | number | undefined | null>) => {
  const p = Object.entries(o).filter(([, v]) => v !== undefined && v !== null && v !== '').map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`);
  return p.length ? `?${p.join('&')}` : '';
};
const M = (id: string) => `/v1/memories/${encodeURIComponent(id)}`;
const R = (id: string, rid: string) => `${M(id)}/records/${encodeURIComponent(rid)}`;

// ── providers ───────────────────────────────────────────────────────────────────────────────
export const listProviders = () => call<{ data: Provider[] }>('GET', '/v1/memories/providers').then((d) => d.data);
/** A provider as the workspace connected it: its address, and which of its secrets are set. */
export interface ProviderPlug { type: string; status: string; config: { base_url?: string }; secrets_set: string[] }
export const listProviderPlugs = () => call<{ plugs: ProviderPlug[] }>('GET', '/v1/plugs?kind=memory').then((d) => d.plugs);
/** Connect a provider. The service tries the address and the key at once and refuses with a
 *  readable message when either fails. An empty address clears the one kept. */
export const connectProvider = (type: string, b: { baseUrl: string; apiKey: string }) =>
  call<ProviderPlug>('PUT', `/v1/plugs/${encodeURIComponent(type)}`, {
    enabled: true, config: { base_url: b.baseUrl }, ...(b.apiKey ? { secrets: { api_key: b.apiKey } } : {}),
  });

// ── memories ────────────────────────────────────────────────────────────────────────────────
export const listMemories = () => call<{ data: Memory[] }>('GET', '/v1/memories').then((d) => d.data);
export const getMemory = (id: string) => call<Memory>('GET', M(id));
export const createMemory = (b: { name: string; description?: string; provider: string }) => call<Memory>('POST', '/v1/memories', b);
export const updateMemory = (id: string, b: { name?: string; description?: string }) => call<Memory>('PUT', M(id), b);
export const deleteMemory = (id: string) => call<{ memories: string[] }>('DELETE', M(id));

// ── schema ──────────────────────────────────────────────────────────────────────────────────
export const getSchema = (id: string) => call<MemorySchema>('GET', `${M(id)}/schema`);
export const putSchema = (id: string, s: MemorySchema) => call<MemorySchema>('PUT', `${M(id)}/schema`, s);

// ── records ─────────────────────────────────────────────────────────────────────────────────
export const listRecords = (id: string, o: { type?: string; limit?: number; cursor?: string } = {}) =>
  call<{ data: MemoryRecord[]; next: string | null }>('GET', `${M(id)}/records${q(o)}`);
export const getHistory = (id: string, rid: string) => call<{ data: MemoryRecord[] }>('GET', `${R(id, rid)}/history`).then((d) => d.data);
export interface RecordInput { type?: string; title?: string; content?: string | ContentPart[]; attributes?: Record<string, unknown>; references?: { rel: string; record_id: string; memory_id?: string }[] }
export const addRecord = (id: string, b: RecordInput) => call<MemoryRecord>('POST', `${M(id)}/records`, b);
/** A revision appends a version; the earlier one stays in the record's history. */
export const reviseRecord = (id: string, rid: string, b: RecordInput) => call<MemoryRecord>('PATCH', R(id, rid), b);
/** Closed and kept: the everyday remove. */
export const getRecord = (id: string, rid: string) => call<MemoryRecord>('GET', R(id, rid));
export const forgetRecord = (id: string, rid: string) => call<MemoryRecord>('DELETE', R(id, rid));
/** Destroyed. `unreachable` names what the provider could not remove, and must be shown. */
export const eraseRecords = (id: string, record_ids: string[]) => call<{ erased: string[]; unreachable: string[] }>('POST', `${M(id)}/erase`, { record_ids });
/** Where one file part of a record is read. */
export const recordFileUrl = (id: string, rid: string, index: number) => `/api/harness${R(id, rid)}/content/${index}`;
/** A search of this memory: a question, words, or a filter such as a fact's label. */
export interface RecallFilter { field: string; op: string; value: unknown }
export const recall = (id: string, b: { query?: string; text?: string; filters?: RecallFilter; limit?: number }) =>
  call<{ results: { record: MemoryRecord; score: number | null }[]; degraded: string[] }>('POST', `${M(id)}/recall`, b);
/** Records as nodes and their references as edges, around one record. */
export const graphAround = (id: string, around: string, hops: number) => call<MemoryGraph>('POST', `${M(id)}/graph`, { around, hops });

// ── access ──────────────────────────────────────────────────────────────────────────────────
export const listGrants = (id: string) => call<{ data: Grant[] }>('GET', `${M(id)}/grants`).then((d) => d.data);
export const grant = (id: string, principal: string, privileges: Privilege[]) => call<Grant>('POST', `${M(id)}/grants`, { principal, privileges });
export const revokeGrant = (id: string, grantId: string) => call<unknown>('DELETE', `${M(id)}/grants/${encodeURIComponent(grantId)}`);

// ── a setup's agent ─────────────────────────────────────────────────────────────────────────
const H = (hid: string) => `/v1/harnesses/${encodeURIComponent(hid)}/memories`;
/** Who the agent is to the access model, what it was granted, and the setup's two settings. */
export const getHarnessMemories = (hid: string) => call<HarnessMemories>('GET', H(hid));
export const setHarnessMemories = (hid: string, b: { default_memory_id?: string | null; observe?: boolean }) => call<HarnessMemories>('PUT', H(hid), b);

// ── presentation ────────────────────────────────────────────────────────────────────────────
/** Every word of a record's content, in order. */
export const bodyOf = (r: Pick<MemoryRecord, 'content'>) => (r.content || []).filter((p) => p.type === 'text').map((p) => p.text || '').filter(Boolean).join('\n\n');
/** The line a record is listed by: its title, or how its content begins. */
export function labelOf(r: Pick<MemoryRecord, 'title' | 'content'>): string {
  if (r.title) return r.title;
  const first = bodyOf(r).split('\n').find((l) => l.trim()) || '';
  return first.replace(/^#+\s*/, '').slice(0, 120);
}
