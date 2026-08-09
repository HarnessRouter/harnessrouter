// Gateway client for the self-hosted console.
//
// No auth. A self-hosted instance is a single-tenant box the operator already controls — the
// hosted product's login, org switching and JWTs would be ceremony with nothing behind it. So
// identity is a constant here, and the gateway runs with its identity mode off.
//
// Everything else is deliberately the SAME wire protocol as the hosted deployment: the same
// /v1 routes, the same workspace headers, the same Responses SSE shape. That is what makes
// "push my harnesses to the cloud" a straight copy later rather than a translation.

import { LOCAL_ORG } from './identity';
import { harnessBody, type Harness } from './harness';

export type { Harness };

const BASE = '/api/gw';

// ── workspaces ────────────────────────────────────────────────────────────────
// Workspaces are a first-class local concept: one instance, many isolated sets of harnesses
// and tasks. The hosted product models them as spaces in a separate service; self-hosted keeps
// the same header contract but stores the list locally, so no external service is involved.
const WS_KEY = 'hr.workspace';
const WS_LIST_KEY = 'hr.workspaces';

export interface Workspace { id: string; name: string }

export const DEFAULT_WORKSPACE: Workspace = { id: 'default', name: 'Default Workspace' };

export function listWorkspaces(): Workspace[] {
  if (typeof window === 'undefined') return [DEFAULT_WORKSPACE];
  try {
    const raw = window.localStorage.getItem(WS_LIST_KEY);
    const arr = raw ? (JSON.parse(raw) as Workspace[]) : null;
    return Array.isArray(arr) && arr.length ? arr : [DEFAULT_WORKSPACE];
  } catch {
    return [DEFAULT_WORKSPACE];
  }
}

export function saveWorkspaces(list: Workspace[]): void {
  try { window.localStorage.setItem(WS_LIST_KEY, JSON.stringify(list)); } catch { /* private mode */ }
}

export function currentWorkspace(): string {
  if (typeof window === 'undefined') return DEFAULT_WORKSPACE.id;
  try { return window.localStorage.getItem(WS_KEY) || DEFAULT_WORKSPACE.id; } catch { return DEFAULT_WORKSPACE.id; }
}

export function setCurrentWorkspace(id: string): void {
  try { window.localStorage.setItem(WS_KEY, id); } catch { /* private mode */ }
}

/** Headers every gateway call carries: which workspace we're scoped to.
 *
 *  Identity is deliberately absent — the proxy pins org and member server-side, so the browser
 *  cannot name a different one. */
export function gwHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const ws = currentWorkspace();
  return {
    'content-type': 'application/json',
    'x-harness-workspace': ws,
    ...(ws === DEFAULT_WORKSPACE.id ? { 'x-harness-workspace-default': '1' } : {}),
    ...extra,
  };
}

function qs(params: Record<string, string | number | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== '') q.set(k, String(v));
  q.set('org', LOCAL_ORG);
  q.set('workspace', currentWorkspace());
  return q.toString();
}

async function gw<T>(path: string, init: RequestInit = {}): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    ...init,
    headers: gwHeaders((init.headers as Record<string, string>) || {}),
    cache: 'no-store',
  });
  if (!r.ok) {
    let detail = `${r.status}`;
    try { detail = (await r.json())?.detail || detail; } catch { /* keep the status */ }
    throw new Error(String(detail));
  }
  return r.json() as Promise<T>;
}

// ── harnesses ─────────────────────────────────────────────────────────────────
export const listHarnesses = () =>
  gw<{ harnesses?: Harness[] }>(`/v1/harnesses?${qs({})}`).then((d) => d.harnesses || []);

export const getHarness = (id: string) => gw<Harness>(`/v1/harnesses/${encodeURIComponent(id)}`);

export const createHarness = (h: Partial<Harness> & { name: string; base: string }) =>
  gw<Harness>('/v1/harnesses', { method: 'POST', body: JSON.stringify(harnessBody(h)) });

export const updateHarness = (id: string, h: Harness) =>
  gw<Harness>(`/v1/harnesses/${encodeURIComponent(id)}`,
              { method: 'PUT', body: JSON.stringify(harnessBody(h)) });

export const deleteHarness = (id: string) =>
  gw<{ ok?: boolean }>(`/v1/harnesses/${encodeURIComponent(id)}`, { method: 'DELETE' });

export interface ModelCatalog {
  [backend: string]: { default: string; models: { id: string }[] };
}
export const listModels = () =>
  gw<{ backends?: ModelCatalog }>('/v1/models').then((d) => d.backends || {});

// ── tasks (runs/sessions) ─────────────────────────────────────────────────────
export interface TaskCard {
  session_id: string;
  title?: string;
  status?: string;
  updated_at?: number;
  harness_id?: string;
  [k: string]: unknown;
}

/** One page of tasks. `cursor` is opaque; '' means no more pages. */
export async function listTasks(harnessId: string, cursor = ''):
    Promise<{ items: TaskCard[]; cursor: string }> {
  const d = await gw<{ sessions?: TaskCard[]; cursor?: string }>(
    `/v1/traces?${qs({ harness: harnessId, limit: 40, cursor })}`);
  return { items: d.sessions || [], cursor: d.cursor || '' };
}

export const deleteTask = (sid: string) =>
  gw<{ ok?: boolean }>(`/v1/traces/${encodeURIComponent(sid)}`, { method: 'DELETE' });

export const loadTurns = (sid: string) =>
  gw<{ turns?: unknown[] }>(`/v1/sessions/${encodeURIComponent(sid)}/turns?limit=200`)
    .then((d) => d.turns || []);

export const cancelTask = (sid: string) =>
  gw<{ ok?: boolean }>(`/v1/sessions/${encodeURIComponent(sid)}/cancel`, { method: 'POST' });

/** Start a turn. Returns the raw Response so the caller can hand it to ReifyUI's SSE parser. */
export function streamTurn(body: Record<string, unknown>): Promise<Response> {
  return fetch(`${BASE}/v1/responses`, {
    method: 'POST',
    headers: gwHeaders({ accept: 'text/event-stream' }),
    body: JSON.stringify({ ...body, stream: true }),
  });
}
