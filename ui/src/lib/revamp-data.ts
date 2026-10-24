// A setup's task cards, as the gateway's trace index lists them (GET /v1/traces), and the few readings
// of them the console draws from: the states a card says, and a p95 duration. Every figure is computed
// from the cards a read brought; nothing here is estimated.
import { harnessFetch } from '@/lib/hfetch';
import { getSession } from '@/lib/auth';
import { appendWorkspaceQuery } from '@/lib/workspace';
import { minutesAndSeconds } from '@/lib/duration';

/** A task card, as the gateway writes it: once as the turn is accepted (running) and again as it
 *  settles. `finished_at` is the time of the card's latest write (seconds). */
export interface TraceCard {
  session_id: string;
  title?: string;
  /** the task's request as it was sent (its first 1,500 characters) */
  user_prompt?: string;
  status?: string;
  model?: string;
  backend?: string;
  elapsed?: number;
  finished_at?: number;
  harness_id?: string;
  harness_name?: string;
  member_id?: string;
  last_response_id?: string;
  workspace?: string;
  event_count?: number;
}

/** One page of a harness's own tasks, newest first, from that harness's index. `cursor` continues
 *  the listing; an empty cursor back means the end. */
export const TASK_PAGE = 50;

/** A page of a harness's tasks that could not be read: the service answered with an error, with
 *  something that is not the list (a proxy's page), or not at all. Never the same as an empty list. */
export class TasksReadError extends Error {
  constructor(readonly harness: string, readonly status: number | string) {
    super(`tasks of ${harness}: ${typeof status === 'number' ? `HTTP ${status}` : status}`);
    this.name = 'TasksReadError';
  }
}

/** One line in the browser console per failed read, naming the setup and the answer (no content). */
function readFailed(harness: string, status: number | string): TasksReadError {
  const e = new TasksReadError(harness, status);
  console.warn(`Task list read failed: ${e.message}`);
  return e;
}

/** One page of a harness's task cards, newest first. The list is narrowed to the current workspace
 *  unless `anyWorkspace`: a setup's own pages ask for every task of that setup, since the setup opens
 *  from any workspace while a card stamped with another workspace would otherwise be dropped.
 *  `signal`: the caller's own deadline; an abort is the caller's to report. */
export async function fetchHarnessTasks(harness: string, cursor = '', opts: { anyWorkspace?: boolean; signal?: AbortSignal } = {}): Promise<{ sessions: TraceCard[]; cursor: string }> {
  const org = getSession()?.orgId;
  if (!org) throw new TasksReadError(harness, 'not signed in');
  const q = new URLSearchParams({ org, limit: String(TASK_PAGE), harness });
  if (cursor) q.set('cursor', cursor);
  if (!opts.anyWorkspace) appendWorkspaceQuery(q);
  let r: Response;
  try {
    r = await harnessFetch(`/api/harness/v1/traces?${q.toString()}`, opts.signal ? { signal: opts.signal } : {});
  } catch (e) {
    if (opts.signal?.aborted) throw e;
    throw readFailed(harness, 'no answer');
  }
  if (!r.ok) throw readFailed(harness, r.status);
  let d: { sessions?: unknown; cursor?: unknown } | null = null;
  try { d = await r.json(); } catch (e) { if (opts.signal?.aborted) throw e; }
  if (!d || !Array.isArray(d.sessions)) throw readFailed(harness, `HTTP ${r.status}, not a task list`);
  return { sessions: d.sessions as TraceCard[], cursor: typeof d.cursor === 'string' ? d.cursor : '' };
}

export const TERMINAL_OK = new Set(['done', 'completed']);
export const TERMINAL_BAD = new Set(['failed', 'error']);
export const RUNNING = new Set(['running', 'starting', 'in_progress']);

/** p95 wall-clock duration over a harness's recent terminal cards; null when too few. */
export function p95Of(cards: TraceCard[] | undefined): string | null {
  const el = (cards || []).map((c) => c.elapsed || 0).filter((x) => x > 0).sort((a, b) => a - b);
  if (el.length < 3) return null;
  const v = el[Math.min(el.length - 1, Math.floor(el.length * 0.95))];
  const [m, s] = minutesAndSeconds(v);
  return m ? `${m}m ${String(s).padStart(2, '0')}s` : `${s}s`;
}
