// Memories (UHP Memories chapter): where agents keep what should outlast one task. Every function
// here is one call to the service; what the console makes of the answers lives in
// components/hrui/memories.
import { harnessFetch } from '@/lib/hfetch';
import { gwHeaders } from '@/lib/harness';
import { getSession } from '@/lib/auth';
import { LOCAL_MEMBER } from '@/lib/edition';

export type Privilege = 'read' | 'write' | 'create' | 'delete';

export interface Memory {
  id: string; object: 'memory'; name: string; description: string; provider: string;
  parent_id: string | null; ancestors: string[]; restricted: boolean; privileges: Privilege[];
  records: { count: number | null }; children?: { count: number }; createdAt?: number; updatedAt?: number;
  /** In a list: what the memory's provider makes itself, as the memory's own workspace reaches it (null: nothing). */
  builtin?: BuiltinSchema | null;
  // From 0.40 (the memories contract, A7 and A9). A gateway before it leaves them out, and the pages then say nothing of them.
  /** The engine that keeps it: the same as `provider`, named for people. */
  engine?: string;
  /** The setups that use it, by name. */
  used_by?: { harness_id: string; name: string }[];
  /** When an agent last read or wrote it (the service gives epoch ms; null: never). */
  last_used_at?: string | number | null;
  /** One plain sentence on the last thing that failed here, and when; and when something last worked (epoch ms). */
  last_error?: string | null; last_error_at?: string | number | null; last_ok_at?: string | number | null;
  /** A memory kept for one person of an agent that keeps each person's memory apart: who that person is, as the
   *  agent's caller named them (the task's `user`). Said only to whoever manages the memory, never to the agent. */
  end_user?: string;
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
/** What a provider makes itself and how it links it: the part of a memory's schema nobody sets, drawn locked. Types are
 *  record types; relations are the references its records carry. */
export interface BuiltinSchema {
  types: { name: string; description: string }[];
  relations: { name: string; from: string; to: string; description: string }[];
}

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
  schema?: { mode?: 'guides' | 'labels' | 'none'; properties?: boolean; relations?: boolean; builtin?: BuiltinSchema };
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
/** `counts: false`: no record counts (null), so the list is one read and asks no memory service anything. `q` finds by
 *  name or description and `sort: 'recent'` puts the last used first, where the service takes them (a service before
 *  0.40 answers the whole list in its own order, and the page narrows and orders it itself). */
export const listMemories = (o: { counts?: boolean; q?: string; sort?: 'recent' } = {}) =>
  call<{ data: Memory[] }>('GET', `/v1/memories${q({ counts: o.counts === false ? 'false' : undefined, q: o.q?.trim() || undefined, sort: o.sort })}`).then((d) => d.data);
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

// ── an agent's own memory (0.40: the platform chooses and provisions it) ──────────────────────
/** What a setup's agent is given: `auto` lets the service choose, `none` gives it nothing, an engine by name, or a
 *  memory that already exists. */
export type MemoryChoice = 'auto' | 'none' | { engine: string } | { id: string };
/** The agent's memory: on a setup, the one it was given (`id` set); on a build not yet saved, the one its save will
 *  give (`id` ''), chosen and not yet made. */
export interface AgentMemory { id: string; name: string; engine: string; scope: 'per_user' | 'shared'; reason: string }
/** The agent's memory and why (`memory` null: none, and `reason` says why). */
export interface AgentMemoryRead { memory: AgentMemory | null; reason: string }
/** The memory a harness record names (`memory: {id, name, engine, scope, reason, observe}`, or `memory: null` and
 *  `memory_reason`), or the one a build's record proposes (`memory: {engine, scope, reason}`, `engine` null for none),
 *  read leniently; undefined where the record says nothing of it (a service before 0.40), so a page says nothing
 *  rather than "none". */
export function agentMemoryOf(raw: unknown): AgentMemoryRead | undefined {
  if (!raw || typeof raw !== 'object' || !('memory' in raw)) return undefined;
  const r = raw as { memory?: unknown; memory_reason?: unknown };
  const m = r.memory;
  const why = typeof r.memory_reason === 'string' ? r.memory_reason : '';
  if (!m || typeof m !== 'object') return { memory: null, reason: why };
  const o = m as Record<string, unknown>;
  const id = typeof o.id === 'string' ? o.id : '';
  const engine = typeof o.engine === 'string' ? o.engine : '';
  const said = typeof o.reason === 'string' ? o.reason : '';
  if (!id && !engine) return { memory: null, reason: said || why };
  return {
    memory: { id, name: String(o.name || ''), engine, scope: o.scope === 'per_user' ? 'per_user' : 'shared', reason: said },
    reason: said || why,
  };
}
/** A setup's own memory as its record says (undefined: the service doesn't say, before 0.40). */
export const getAgentMemory = (hid: string) => call<unknown>('GET', `/v1/harnesses/${encodeURIComponent(hid)}`).then(agentMemoryOf);
/** Give the agent its memory, or another one, or none (PUT /v1/harnesses/{hid}/memory, `{memory}`). Changing the
 *  engine makes a new memory and moves the agent to it; the one before is kept, unattached. The answer is read again,
 *  so what is drawn is what was saved. */
export async function setAgentMemory(hid: string, choice: MemoryChoice): Promise<AgentMemoryRead | undefined> {
  const out = await call<unknown>('PUT', `/v1/harnesses/${encodeURIComponent(hid)}/memory`, { memory: choice });
  return agentMemoryOf(out) || getAgentMemory(hid);
}
/** What looking for engines found, one line each: `connected` (found and connected now, or before), `running` (it
 *  answers, and needs the key the command that started it has), `not_running`, or `refused` (with why). */
export interface EngineFound { engine: string; state: 'connected' | 'running' | 'not_running' | 'refused' | string; message: string }
/** Look for the engines running beside this instance and connect each one found that needs no key (an instance with
 *  one operator). */
export const findEngines = () => call<{ data?: EngineFound[] }>('POST', '/v1/memory-services/discover')
  .then((d) => (Array.isArray(d?.data) ? d.data : []));
/** The engine a new memory with this name and description gets, and why: the service's own reading (the one an agent
 *  gets), among the engines connected and answering here. `engine` null: none is running, and `reason` says how to
 *  start one. */
export interface EngineChoice { engine: string | null; scope: 'per_user' | 'shared'; reason: string }
export const chooseEngine = (name: string, description: string) =>
  call<Partial<EngineChoice> | null>('GET', `/v1/memories/choose${q({ name: name.trim(), description: description.trim() })}`)
    .then((d): EngineChoice => ({
      engine: typeof d?.engine === 'string' && d.engine ? d.engine : null,
      scope: d?.scope === 'per_user' ? 'per_user' : 'shared', reason: typeof d?.reason === 'string' ? d.reason : '',
    }));

/** Why a save failed, as the turn's note gives it: the service's bare reason. A note written before the gateway sent
 *  it bare reads "This conversation wasn't kept: <reason>." and that sentence comes off, so the line never says it
 *  twice; '' where no reason came. */
export function failedReason(raw: unknown): string {
  const t = typeof raw === 'string' ? raw.replace(/\s+/g, ' ').trim() : '';
  return t.replace(/^this conversation wasn['’]t kept\s*[:.]?\s*/i, '').replace(/\.$/, '').trim();
}
/** A failed save as its turn's line says it. */
export const failedLine = (reason: string) => (reason ? `Couldn't remember this one: ${reason}` : "Couldn't remember this one");
/** What a finished task kept, on its turn record (`memory: {remembered, records: [{id, memory_id}], pending?}`), read
 *  leniently: a record may also be a bare id. Null where the turn kept nothing or says nothing of it. A save that
 *  failed is `failed`, with the service's reason ('' where it gave none). */
export interface Remembered { count: number; records: { id: string; memory_id?: string }[]; memoryId: string; failed?: true; reason?: string }
export function rememberedOf(turn: unknown): Remembered | null {
  const m = turn && typeof turn === 'object' ? (turn as { memory?: unknown }).memory : null;
  if (!m || typeof m !== 'object') return null;
  const o = m as { remembered?: unknown; records?: unknown; memory_id?: unknown; failed?: unknown; reason?: unknown };
  // a save that failed says so on its turn, in the service's own words (never a silent miss, never a guessed cause)
  if (o.failed === true) return { count: 0, records: [], memoryId: '', failed: true, reason: failedReason(o.reason) };
  const n = typeof o.remembered === 'number' && Number.isFinite(o.remembered) ? o.remembered : 0;
  if (n <= 0) return null;
  const records = (Array.isArray(o.records) ? o.records : []).flatMap((x) => {
    if (typeof x === 'string' && x) return [{ id: x }];
    if (x && typeof x === 'object' && typeof (x as { id?: unknown }).id === 'string') {
      const r = x as { id: string; memory_id?: unknown };
      return [{ id: r.id, ...(typeof r.memory_id === 'string' && r.memory_id ? { memory_id: r.memory_id } : {}) }];
    }
    return [];
  });
  return { count: n, records, memoryId: typeof o.memory_id === 'string' ? o.memory_id : records.find((r) => r.memory_id)?.memory_id || '' };
}
/** How many things the platform recalled for a turn as it began (what the agent already knew that could matter
 *  there), as its record says (`memory.recalled_at_start`); 0 where it recalled nothing or the record doesn't say. */
export function recalledAtStartOf(turn: unknown): number {
  const m = turn && typeof turn === 'object' ? (turn as { memory?: unknown }).memory : null;
  const n = m && typeof m === 'object' ? (m as { recalled_at_start?: unknown }).recalled_at_start : undefined;
  return typeof n === 'number' && Number.isFinite(n) && n > 0 ? Math.floor(n) : 0;
}

/** Where a record opens. `top` is the memory a person comes from (an agent's own); a record of a memory below it (a
 *  person's own) opens on that page, open in it (`in`), so the person keeps their place and Back is the agent's memory.
 *  Without a `top`, or for a record of `top` itself, the record's own memory's page. */
export function recordHref(top: string, mid: string, rid?: string): string {
  const e = encodeURIComponent;
  const inside = !!top && !!mid && mid !== top;
  return `/memories/${e(inside ? top : mid || top)}?tab=data${inside ? `&in=${e(mid)}` : ''}${rid ? `&record=${e(rid)}` : ''}`;
}

// ── presentation ────────────────────────────────────────────────────────────────────────────
/** The engine that keeps a memory. */
export const engineOf = (m: Pick<Memory, 'provider' | 'engine'>) => m.engine || m.provider;
/** The person a memory kept for one person belongs to, as the service gives it to whoever manages the memory
 *  (`end_user`); '' for any other memory, and for a reader the service doesn't tell. */
export const userOf = (m: Pick<Memory, 'end_user'>): string => (typeof m.end_user === 'string' ? m.end_user.trim() : '');
/** How the console's own tasks are named where they are a person's: a test sent from here runs as the console member
 *  (the gateway takes them as the task's end user when the task names nobody else), which reads as an address, not as
 *  anyone. */
export const CONSOLE_PERSON = 'You (this console)';
/** The person a task's `user` names, as a person reads it: the console member is "You (this console)", anyone else
 *  is the string their app sent. */
export function personName(user: string): string {
  const u = (user || '').trim();
  if (!u) return '';
  const me = getSession()?.member;
  return u === LOCAL_MEMBER || (!!me && (u === me.email || u === me.id)) ? CONSOLE_PERSON : u;
}
/** How a memory is named in a list: a person's memory by that person, any other by its name. */
export const shownName = (m: Pick<Memory, 'name' | 'end_user'>) => personName(userOf(m)) || m.name;
/** Every word of a record's content, in order. */
export const bodyOf = (r: Pick<MemoryRecord, 'content'>) => (r.content || []).filter((p) => p.type === 'text').map((p) => p.text || '').filter(Boolean).join('\n\n');
/** The line a record is listed by: its title, or how its content begins. */
export function labelOf(r: Pick<MemoryRecord, 'title' | 'content'>): string {
  if (r.title) return r.title;
  const first = bodyOf(r).split('\n').find((l) => l.trim()) || '';
  return first.replace(/^#+\s*/, '').slice(0, 120);
}
