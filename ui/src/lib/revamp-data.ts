// Shared data layer for the revamped IA pages (Dashboard / Overview / Harnesses / Analytics).
//
// Aggregates are computed client-side from the newest trace cards (up to WINDOW per scope), the
// gateway has no server-side aggregation API yet. That approximation is labeled in the UI where it
// matters. TODO(board): server-side aggregation endpoints (tasks/success by day, per-harness) so
// dashboards stop being window-limited.
import { harnessFetch } from '@/lib/hfetch';
import { getSession } from '@/lib/auth';
import { OOB, listCustom, type CustomHarness, type OobHarness } from '@/lib/harness';
import { appendWorkspaceQuery } from '@/lib/workspace';

export interface TraceCard {
  session_id: string;
  title?: string;
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
  credits?: number;
  created_at?: number;
}

const WINDOW = 200;

/** Newest trace cards, scoped to the ACTIVE workspace by default. Pass `ws` to target a
 *  specific workspace (Dashboard's comparison rows), or `ws: null` for the org-wide view. */
export async function fetchTraceWindow(harness?: string,
  ws?: { id: string; isDefault: boolean } | null): Promise<TraceCard[]> {
  const org = getSession()?.orgId;
  if (!org) return [];
  const q = new URLSearchParams({ org, limit: String(WINDOW) });
  if (harness) q.set('harness', harness);
  if (ws === undefined) appendWorkspaceQuery(q);
  else if (ws) { q.set('workspace', ws.id); if (ws.isDefault) q.set('workspace_default', '1'); }
  const r = await harnessFetch(`/api/harness/v1/traces?${q.toString()}`);
  if (!r.ok) return [];
  const d = await r.json().catch(() => null);
  return Array.isArray(d?.sessions) ? d.sessions : [];
}

/** One page of a harness's own tasks, newest first, from that harness's index. `cursor` continues
 *  the listing; an empty cursor back means the end. Scoped to the active workspace like the window. */
export const TASK_PAGE = 50;
export async function fetchHarnessTasks(harness: string, cursor = ''): Promise<{ sessions: TraceCard[]; cursor: string }> {
  const org = getSession()?.orgId;
  if (!org) return { sessions: [], cursor: '' };
  const q = new URLSearchParams({ org, limit: String(TASK_PAGE), harness });
  if (cursor) q.set('cursor', cursor);
  appendWorkspaceQuery(q);
  const r = await harnessFetch(`/api/harness/v1/traces?${q.toString()}`);
  if (!r.ok) return { sessions: [], cursor: '' };
  const d = await r.json().catch(() => null);
  return { sessions: Array.isArray(d?.sessions) ? d.sessions : [], cursor: typeof d?.cursor === 'string' ? d.cursor : '' };
}

export const TERMINAL_OK = new Set(['done', 'completed']);
export const TERMINAL_BAD = new Set(['failed', 'error']);
export const RUNNING = new Set(['running', 'starting', 'in_progress']);

export interface HarnessStats {
  tasks7d: number;
  success: number | null;   // 0..1 over terminal tasks in the window; null = no terminal tasks
  lastActivity: number | null;
  running: number;
  failed7d: number;
}

const DAY = 86400_000;

export function statsFor(cards: TraceCard[], now = Date.now()): HarnessStats {
  const wk = cards.filter((c) => ((c.finished_at || 0) * 1000) > now - 7 * DAY);
  const terminal = wk.filter((c) => TERMINAL_OK.has(c.status || '') || TERMINAL_BAD.has(c.status || ''));
  const ok = terminal.filter((c) => TERMINAL_OK.has(c.status || '')).length;
  return {
    tasks7d: wk.length,
    success: terminal.length ? ok / terminal.length : null,
    lastActivity: cards.length ? Math.max(...cards.map((c) => (c.finished_at || 0) * 1000)) : null,
    running: cards.filter((c) => RUNNING.has(c.status || '')).length,
    failed7d: wk.filter((c) => TERMINAL_BAD.has(c.status || '')).length,
  };
}

/** p95 wall-clock duration over a harness's recent terminal cards; null when too few. */
export function p95Of(cards: TraceCard[] | undefined): string | null {
  const el = (cards || []).map((c) => c.elapsed || 0).filter((x) => x > 0).sort((a, b) => a - b);
  if (el.length < 3) return null;
  const v = el[Math.min(el.length - 1, Math.floor(el.length * 0.95))];
  const m = Math.floor(v / 60), s = Math.round(v % 60);
  return m ? `${m}m ${String(s).padStart(2, '0')}s` : `${s}s`;
}

/** Average credits per task for a harness (over the runs that carry a credit total — older runs
 *  from before per-run metering have none, so we average only the priced ones). Null when none. */
export function avgCreditsOf(cards: TraceCard[] | undefined): string | null {
  const c = (cards || []).map((x) => x.credits).filter((v): v is number => typeof v === 'number' && v > 0);
  if (!c.length) return null;
  const avg = c.reduce((s, v) => s + v, 0) / c.length;
  return avg >= 100 ? Math.round(avg).toLocaleString() : avg.toFixed(avg < 10 ? 2 : 1);
}

/** When a task last did something: the settle of its latest turn, else its creation. */
export function activityAt(c: TraceCard): number { return c.finished_at || c.created_at || 0; }

/** Cards per harness, most recent activity first: a task that is running now leads, then the
 *  rest by their latest settle, so a follow-up on an old task brings it back to the top. */
export function groupByHarness(cards: TraceCard[]): Map<string, TraceCard[]> {
  const m = new Map<string, TraceCard[]>();
  for (const c of cards) {
    const k = c.harness_id || 'unknown';
    if (!m.has(k)) m.set(k, []);
    m.get(k)!.push(c);
  }
  for (const [k, list] of m) m.set(k, sortByActivity(list));
  return m;
}

/** Most recent activity first: running tasks lead, then the rest by their latest settle. */
export function sortByActivity(list: TraceCard[]): TraceCard[] {
  const live = (c: TraceCard) => (RUNNING.has(c.status || '') ? 1 : 0);
  return [...list].sort((a, b) => live(b) - live(a) || activityAt(b) - activityAt(a));
}

/** Tasks-per-day buckets for the last `days`, oldest first. */
export function dailyBuckets(cards: TraceCard[], days = 7, now = Date.now()): { label: string; count: number; ok: number; bad: number }[] {
  const out: { label: string; count: number; ok: number; bad: number }[] = [];
  for (let i = days - 1; i >= 0; i--) {
    const d0 = new Date(now - i * DAY);
    const label = d0.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    const dayStart = new Date(d0.getFullYear(), d0.getMonth(), d0.getDate()).getTime();
    const inDay = cards.filter((c) => {
      const t = (c.finished_at || 0) * 1000;
      return t >= dayStart && t < dayStart + DAY;
    });
    out.push({
      label,
      count: inDay.length,
      ok: inDay.filter((c) => TERMINAL_OK.has(c.status || '')).length,
      bad: inDay.filter((c) => TERMINAL_BAD.has(c.status || '')).length,
    });
  }
  return out;
}

export interface HarnessRow {
  id: string;
  name: string;
  purpose: string;
  kind: 'builtin' | 'custom';
  runtime: string;
  stats: HarnessStats;
}

export async function fetchHarnessRows(): Promise<{ rows: HarnessRow[]; all: TraceCard[] }> {
  const [custom, all] = await Promise.all([
    listCustom().catch(() => [] as CustomHarness[]),
    fetchTraceWindow(),
  ]);
  const byHarness = groupByHarness(all);
  const rows: HarnessRow[] = [];
  for (const o of OOB.filter((x: OobHarness) => x.status === 'ready')) {
    rows.push({
      id: o.id, name: o.name, purpose: o.systemPrompt?.split('.')[0] || 'Built-in harness', kind: 'builtin',
      runtime: `${o.name} · ${o.defaultModel || o.models[0] || ''}`,
      stats: statsFor(byHarness.get(o.id) || []),
    });
  }
  for (const c of custom) {
    rows.push({
      id: c.id, name: c.name, purpose: c.systemPrompt?.split('.')[0]?.slice(0, 90) || 'Custom harness', kind: 'custom',
      runtime: `${c.baseLabel || c.base} · ${c.defaultModel || 'backend default'}`,
      stats: statsFor(byHarness.get(c.id) || []),
    });
  }
  // Customs first (the things you made, most recently active on top); built-ins after, in
  // their fixed catalog order. Activity-sorting the built-ins made the list reshuffle under
  // you — whichever base you had just tried jumped the queue.
  const oobIndex = new Map(OOB.map((o: OobHarness, i: number) => [o.id, i]));
  rows.sort((a, b) => {
    if (a.kind !== b.kind) return a.kind === 'custom' ? -1 : 1;
    if (a.kind === 'builtin') return (oobIndex.get(a.id) ?? 99) - (oobIndex.get(b.id) ?? 99);
    return (b.stats.lastActivity || 0) - (a.stats.lastActivity || 0);
  });
  return { rows, all };
}

export function timeAgo(ts: number | null): string {
  if (!ts) return '—';
  const s = Math.max(0, (Date.now() - ts) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} hr ago`;
  return `${Math.round(s / 86400)}d ago`;
}

export function statusChip(status?: string): { cls: string; label: string } {
  const s = (status || '').toLowerCase();
  if (TERMINAL_OK.has(s)) return { cls: 'healthy', label: 'Done' };
  if (TERMINAL_BAD.has(s)) return { cls: 'failed', label: 'Failed' };
  if (RUNNING.has(s)) return { cls: 'running', label: 'Working' };
  if (s === 'cancelled') return { cls: 'warning', label: 'Cancelled' };
  if (s === 'incomplete' || s === 'timeout' || s === 'max_turns') return { cls: 'warning', label: 'Incomplete' };
  return { cls: 'healthy', label: status || '—' };
}
