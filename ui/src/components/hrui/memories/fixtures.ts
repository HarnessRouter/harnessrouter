// For the tests: each provider's capability document as the service answers it (copied from its
// adapter), and a stand-in for the service at the one place the console calls it.
import type { Memory, MemoryRecord, Provider } from '@/lib/memories';

export const CAPS: Record<string, Provider> = {
  mem0: { id: 'mem0', connected: true, derivation: 'write_time', observe: { keeps_episodes: false, answers: 'job' }, graph: { entities: 'stated' },
    recall: { signals: ['query', 'text', 'filters'] }, history: { content: 'versions', structure: 'none' }, revise: 'native', forget: 'native', erase: { unreachable: 'reported' }, schema: { mode: 'none' } },
  graphiti: { id: 'graphiti', connected: true, derivation: 'write_time', observe: { keeps_episodes: true, answers: 'records' }, graph: { entities: 'derived' },
    recall: { signals: ['query', 'text', 'filters'] }, history: { content: 'versions', structure: 'versions', emulated: true }, revise: 'native', forget: 'native', erase: { unreachable: 'reported' }, schema: { mode: 'guides', properties: true, relations: true } },
  hindsight: { id: 'hindsight', connected: true, derivation: 'background', observe: { keeps_episodes: true, answers: 'job' }, graph: { entities: 'derived' },
    recall: { signals: ['query', 'text', 'filters'] }, history: { content: 'versions', structure: 'none', emulated: true }, revise: 'native', forget: 'native', erase: { unreachable: 'reported' }, schema: { mode: 'labels' } },
  reme: { id: 'reme', connected: true, derivation: 'agent', layout: 'files', observe: { keeps_episodes: true, answers: 'records' }, graph: { entities: 'stated' },
    recall: { signals: ['text', 'filters'] }, history: { content: 'versions', structure: 'none', emulated: true }, revise: 'native', forget: 'emulated', erase: { unreachable: 'none' }, schema: { mode: 'none' } },
};
export const allProviders = (connected: Record<string, boolean>): Provider[] =>
  Object.values(CAPS).map((p) => ({ ...p, connected: !!connected[p.id] }));

export const memory = (o: Partial<Memory> = {}): Memory => ({
  id: 'hmem_1', object: 'memory', name: 'Brand kits', description: 'What each brand wants.', provider: 'graphiti', parent_id: null, ancestors: [], restricted: false,
  privileges: ['read', 'write', 'create', 'delete'], records: { count: 1 }, ...o,
});
export const record = (o: Partial<MemoryRecord> = {}): MemoryRecord => ({
  id: 'hrec_1', object: 'memory.record', memory_id: 'hmem_1', type: 'note', title: 'A note', content: [{ type: 'text', text: 'What it says.' }], attributes: {},
  version: 1, status: 'active', supersedes: null, time: { valid_from: null, valid_to: null, written_at: '2026-11-01T00:00:00Z', invalidated_at: null },
  written_by: { kind: 'member', id: 'local@localhost', type: 'human' }, references: [], trust: 'untrusted', ...o,
});

export interface Call { method: string; path: string; body: unknown; headers: Record<string, string> }
export type Answer = unknown | ((c: Call) => unknown);
/** `routes`: "GET /v1/memories" to an answer; an answer of `{ $status, ... }` is that status with that
 *  body, and a Blob is a picture. A route not listed answers 404, so a call a page should not make is
 *  seen in `calls`. A body that is a Blob (a picture sent) is kept as it is. */
export function service(routes: Record<string, Answer>) {
  const calls: Call[] = [];
  const fetcher = jest.fn(async (url: string, init: RequestInit = {}) => {
    const path = String(url).replace(/^\/api\/harness/, '');
    const method = String(init.method || 'GET');
    const body = init.body instanceof Blob ? init.body : init.body ? JSON.parse(String(init.body)) : undefined;
    const call: Call = { method, path, body, headers: { ...(init.headers as Record<string, string> | undefined) } };
    calls.push(call);
    const key = `${method} ${path.split('?')[0]}`;
    if (!(key in routes)) return { ok: false, status: 404, json: async () => ({ error: { code: 'not_found', message: 'Not here.' } }) };
    const a = routes[key];
    const out = (typeof a === 'function' ? (a as (c: Call) => unknown)(call) : a) as { $status?: number } | null;
    if (out instanceof Blob) return { ok: true, status: 200, blob: async () => out, json: async () => { throw new Error('a picture'); } };
    const status = out?.$status || 200;
    return { ok: status < 400, status, json: async () => out };
  });
  return { calls, fetcher, sent: (method: string, path: string) => calls.filter((c) => c.method === method && c.path.split('?')[0] === path) };
}
