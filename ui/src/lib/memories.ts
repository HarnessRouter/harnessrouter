// Memories (UHP Memories chapter): places in a tree where agents keep what should outlast one
// conversation. Every function here is one call to the service; nothing is derived on the client
// except the two presentation helpers at the bottom (a role's name for a set of privileges, and
// the line a record is listed by).
import { harnessFetch } from '@/lib/hfetch';
import { gwHeaders } from '@/lib/harness';

export type Privilege = 'read' | 'write' | 'create' | 'delete';
export type RecordType = 'fact' | 'note' | 'procedure' | 'episode' | 'link' | 'entity';
export const RECORD_TYPES: RecordType[] = ['fact', 'note', 'procedure', 'episode', 'link', 'entity'];

export interface MemoryBrief { id: string; name: string; description: string; records: { count: number | null }; children?: { count: number }; privileges?: Privilege[] }
export interface Memory {
  id: string; object: 'memory'; name: string; description: string; provider: string;
  parent_id: string | null; ancestors: string[]; restricted: boolean; privileges: Privilege[];
  records: { count: number | null }; children?: { count: number }; created_at?: number; created_by?: string;
}
export interface Writer { kind: string; id: string; type?: 'human' | 'agent'; on_behalf_of?: string; consolidation_id?: string }
export interface ContentPart { type: string; text?: string; role?: string; file?: { id: string; name?: string; media_type?: string; bytes?: number }; text_source?: string }
export interface Reference { rel?: string; memory_id: string; record_id: string; available: boolean }
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
export interface Neighbours { parent?: MemoryBrief; children: MemoryBrief[] }
export interface RecallResult { record: MemoryRecord; memory: { id: string; name: string }; score: number | null; why: string[] }
export interface Recall extends Neighbours { results: RecallResult[]; degraded: string[]; abstain: boolean }
export interface GraphEdge { from: { memory_id: string; record_id: string }; to: { memory_id: string; record_id: string }; rel?: string; available: boolean }
export interface MemoryGraph { nodes: { record: MemoryRecord; memory: { id: string; name: string } }[]; edges: GraphEdge[]; truncated: boolean; degraded: string[] }
export interface Grant { id: string; memory_id: string; principal: string; privileges: Privilege[]; inherited: boolean }
/** What a provider says it does. The console enables and disables from this and nothing else. */
export interface Provider {
  id: string; isolation?: string; derivation?: string;
  recall?: { signals?: string[]; abstain?: boolean };
  history?: { content?: 'versions' | 'snapshots' | 'none'; structure?: string };
  content?: { media?: string[]; bytes?: string; describes?: string[] };
  graph?: { entities?: 'derived' | 'stated' | 'none' };
  queries?: { named?: boolean; free?: { languages?: string[] } };
  consolidate?: string; erase?: { unreachable?: string };
}
/** A memory engine as the workspace connects it: one row of GET /v1/plugs?kind=memory. */
export interface EnginePlug { type: string; label: string; status: 'connected' | 'disabled' | 'needs_auth' | 'missing'; secrets_set: string[]; secrets_needed: string[] }
export interface HarnessMemories {
  object: 'harness.memories'; principal: string; default_memory_id: string | null; observe: boolean;
  data: (MemoryBrief & { privileges: Privilege[]; default: boolean })[];
}

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

// ── engines ─────────────────────────────────────────────────────────────────────────────────
export const listProviders = () => call<{ data: Provider[] }>('GET', '/v1/memories/providers').then((d) => d.data);
export const listEngines = () => call<{ plugs: EnginePlug[] }>('GET', '/v1/plugs?kind=memory').then((d) => d.plugs);
/** Connect an engine with the workspace's own key. The service tries it at the vendor at once. */
export const connectEngine = (type: string, apiKey: string) =>
  call<EnginePlug>('PUT', `/v1/plugs/${encodeURIComponent(type)}`, { enabled: true, secrets: { api_key: apiKey } });
export const disconnectEngine = (type: string) => call<{ removed: boolean }>('DELETE', `/v1/plugs/${encodeURIComponent(type)}`);

// ── the tree ────────────────────────────────────────────────────────────────────────────────
/** Where the caller enters the tree. */
export const listRoots = () => call<{ data: Memory[] }>('GET', '/v1/memories').then((d) => d.data);
export const listChildren = (parent: string) => call<{ data: Memory[] }>('GET', `/v1/memories${q({ parent })}`).then((d) => d.data);
export const getMemory = (id: string) => call<Memory>('GET', M(id));
export const createMemory = (b: { name: string; description?: string; provider?: string; parent_id?: string; restricted?: boolean }) =>
  call<Memory>('POST', '/v1/memories', b);
export const updateMemory = (id: string, b: { name?: string; description?: string; parent_id?: string | null; restricted?: boolean }) =>
  call<Memory>('PUT', M(id), b);
export const deleteMemory = (id: string) => call<{ memories: string[] }>('DELETE', M(id));

// ── records ─────────────────────────────────────────────────────────────────────────────────
export const listRecords = (id: string, o: { type?: string; include?: 'active' | 'all'; limit?: number; cursor?: string } = {}) =>
  call<{ data: MemoryRecord[]; next: string | null } & Neighbours>('GET', `${M(id)}/records${q(o)}`);
export const getRecord = (id: string, rid: string) => call<MemoryRecord>('GET', `${M(id)}/records/${encodeURIComponent(rid)}`);
export const getHistory = (id: string, rid: string) =>
  call<{ data: MemoryRecord[] }>('GET', `${M(id)}/records/${encodeURIComponent(rid)}/history`).then((d) => d.data);
export interface RecordInput { type?: string; title?: string; content?: string | ContentPart[]; attributes?: Record<string, unknown>; references?: { rel: string; record_id: string; memory_id?: string }[] }
export const addRecord = (id: string, b: RecordInput) => call<MemoryRecord>('POST', `${M(id)}/records`, b);
/** A revision appends a version; the earlier one stays in the record's history. */
export const reviseRecord = (id: string, rid: string, b: RecordInput) => call<MemoryRecord>('PATCH', `${M(id)}/records/${encodeURIComponent(rid)}`, b);
/** Closed and kept: the everyday remove. */
export const forgetRecord = (id: string, rid: string) => call<MemoryRecord>('DELETE', `${M(id)}/records/${encodeURIComponent(rid)}`);
/** Destroyed. `unreachable` names what the engine could not remove, and must be shown. */
export const eraseRecords = (id: string, record_ids: string[]) => call<{ erased: string[]; unreachable: string[] }>('POST', `${M(id)}/erase`, { record_ids });

// ── finding ─────────────────────────────────────────────────────────────────────────────────
/** Searches this memory and everything below it the caller may read; each result names its memory. */
export const recall = (id: string, b: { query?: string; text?: string; types?: string[]; depth?: number; limit?: number }) =>
  call<Recall>('POST', `${M(id)}/recall`, b);
/** Records as nodes and their references as edges, around one record or for the whole memory. */
export const graph = (id: string, b: { around?: string; hops?: number; types?: string[]; limit?: number } = {}) =>
  call<MemoryGraph>('POST', `${M(id)}/graph`, b);

// ── access ──────────────────────────────────────────────────────────────────────────────────
export const listGrants = (id: string) => call<{ data: Grant[] }>('GET', `${M(id)}/grants`).then((d) => d.data);
export const grant = (id: string, principal: string, privileges: Privilege[]) => call<Grant>('POST', `${M(id)}/grants`, { principal, privileges });
export const revokeGrant = (id: string, grantId: string) => call<unknown>('DELETE', `${M(id)}/grants/${encodeURIComponent(grantId)}`);

// ── a harness's agent ───────────────────────────────────────────────────────────────────────
const H = (hid: string) => `/v1/harnesses/${encodeURIComponent(hid)}/memories`;
/** Who the agent is to the access model, what it was granted, and the harness's two settings. */
export const getHarnessMemories = (hid: string) => call<HarnessMemories>('GET', H(hid));
export const setHarnessMemories = (hid: string, b: { default_memory_id?: string | null; observe?: boolean }) => call<HarnessMemories>('PUT', H(hid), b);

// ── presentation ────────────────────────────────────────────────────────────────────────────
export type Role = 'Viewer' | 'Editor' | 'Manager';
export const ROLE_PRIVILEGES: Record<Role, Privilege[]> = {
  Viewer: ['read'], Editor: ['read', 'write', 'create'], Manager: ['read', 'write', 'create', 'delete'],
};
/** The role a set of privileges amounts to, or null when it holds none. */
export function roleOf(p: Privilege[] | undefined): Role | null {
  if (!p || !p.includes('read')) return null;
  return p.includes('delete') ? 'Manager' : p.includes('write') ? 'Editor' : 'Viewer';
}
/** Every word of a record's content, in order. */
export const bodyOf = (r: Pick<MemoryRecord, 'content'>) => (r.content || []).map((p) => p.text || '').filter(Boolean).join('\n\n');
/** The line a record is listed by: its title, or how its content begins. */
export function labelOf(r: Pick<MemoryRecord, 'title' | 'content'>): string {
  if (r.title) return r.title;
  const first = bodyOf(r).split('\n').find((l) => l.trim()) || '';
  return first.replace(/^#+\s*/, '').slice(0, 120);
}
