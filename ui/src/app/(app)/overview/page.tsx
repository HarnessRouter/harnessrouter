'use client';
// Workspace Overview, the merged Overview + Analytics page, per the finalized 2026-07-19
// design revision (prototype view-workspace): KPI cards, activity chart (Tasks bars +
// success line), needs-attention card, Harness health table, Recent Tasks, readiness strip.
// Aggregates are computed client-side from the newest trace-card window (up to 200), the
// gateway has no server aggregation yet (recorded on the board); the footnote states the
// window. Revenue reads "—" until Stripe Connect lands (CT-125): no invented numbers.
import { useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Chart, registerables } from 'chart.js';
import { getSession } from '@/lib/auth';
import { useWorkspace } from '@/lib/workspace';
import { fetchHarnessRows, statsFor, timeAgo, statusChip, TERMINAL_BAD, TERMINAL_OK,
  type HarnessRow, type TraceCard } from '@/lib/revamp-data';
import { billing } from '../billing/lib';
import { SkelLine, SkelRows } from '@/components/Skel';

Chart.register(...registerables);

const RANGES = [
  { key: '7d', label: 'Last 7 days', days: 7 },
  { key: '24h', label: 'Last 24 hours', days: 1 },
  { key: '30d', label: 'Last 30 days', days: 30 },
] as const;
type RangeKey = typeof RANGES[number]['key'];
const DAY = 86400_000;

function inRange(c: TraceCard, days: number, endOffsetDays = 0, now = Date.now()): boolean {
  const t = (c.finished_at || 0) * 1000;
  return t > now - (days + endOffsetDays) * DAY && t <= now - endOffsetDays * DAY;
}

/** Per-day buckets over `days` (oldest first): task count + success % of terminal tasks. */
function activityBuckets(cards: TraceCard[], days: number, now = Date.now()) {
  const out: { label: string; count: number; success: number | null }[] = [];
  for (let i = days - 1; i >= 0; i--) {
    const d0 = new Date(now - i * DAY);
    const dayStart = new Date(d0.getFullYear(), d0.getMonth(), d0.getDate()).getTime();
    const inDay = cards.filter((c) => { const t = (c.finished_at || 0) * 1000; return t >= dayStart && t < dayStart + DAY; });
    const term = inDay.filter((c) => TERMINAL_OK.has(c.status || '') || TERMINAL_BAD.has(c.status || ''));
    const ok = term.filter((c) => TERMINAL_OK.has(c.status || '')).length;
    out.push({
      label: d0.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
      count: inDay.length,
      success: term.length ? Math.round((ok / term.length) * 1000) / 10 : null,
    });
  }
  return out;
}

function ActivityChart({ cards, days }: { cards: TraceCard[]; days: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const buckets = activityBuckets(cards, Math.max(days, 2));
    // Dynamic success floor like the design (94-100 band): the line floats mid-chart instead of
    // hugging the top, and clip:false keeps the 100% dots from being cut at the plot edge.
    const vals = buckets.map((b) => b.success).filter((x): x is number => x != null);
    const yMin = vals.length ? Math.min(94, Math.max(0, Math.floor(Math.min(...vals)) - 2)) : 94;
    const chart = new Chart(ref.current, {
      type: 'line',
      data: {
        labels: buckets.map((b) => b.label),
        datasets: [
          { type: 'bar', label: 'Tasks', data: buckets.map((b) => b.count), yAxisID: 'y1', order: 2,
            backgroundColor: 'rgba(40,90,255,.13)', borderColor: 'rgba(40,90,255,.22)',
            borderWidth: 1, borderRadius: 4, maxBarThickness: 28 },
          { type: 'line', label: 'Overall success', data: buckets.map((b) => b.success),
            borderColor: '#285aff', backgroundColor: '#285aff', borderWidth: 2.5, pointRadius: 2.5,
            tension: .3, spanGaps: true, clip: false },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        plugins: { legend: { display: false }, tooltip: { intersect: false, mode: 'index' } },
        scales: {
          x: { grid: { display: false }, ticks: { color: '#777782', font: { size: 10 } } },
          y: { min: yMin, max: 100, grid: { color: '#eeeef2' },
            ticks: { color: '#777782', font: { size: 10 }, callback: (v) => `${v}%` } },
          y1: { position: 'right', beginAtZero: true, grid: { drawOnChartArea: false },
            ticks: { color: '#777782', font: { size: 10 }, precision: 0 } },
        },
      },
    });
    return () => chart.destroy();
  }, [cards, days]);
  return <canvas ref={ref} role="img" aria-label="Daily Task volume and overall success rate" />;
}

export default function OverviewPage() {
  const router = useRouter();
  const { current, loading } = useWorkspace();
  const [rows, setRows] = useState<HarnessRow[] | null>(null);
  const [all, setAll] = useState<TraceCard[]>([]);
  const [credits30, setCredits30] = useState<number | null>(null);
  const [range, setRange] = useState<RangeKey>('7d');
  const days = RANGES.find((r) => r.key === range)!.days;

  useEffect(() => {
    if (loading) return;
    let alive = true;
    fetchHarnessRows().then(({ rows, all }) => { if (alive) { setRows(rows); setAll(all); } }).catch(() => setRows([]));
    const to = new Date(); const from = new Date(Date.now() - 30 * DAY);
    billing.usage({ from: from.toISOString().slice(0, 10), to: to.toISOString().slice(0, 10), bucket: 'day' })
      .then((u) => {
        if (!alive) return;
        const total = (u?.buckets || u?.rows || []).reduce((s: number, b: { credits?: number; total?: number }) => s + Number(b.credits ?? b.total ?? 0), 0);
        setCredits30(Math.round(total));
      }).catch(() => { /* em dash */ });
    return () => { alive = false; };
  }, [loading, current.id]);

  const cur = useMemo(() => all.filter((c) => inRange(c, days)), [all, days]);
  const prev = useMemo(() => all.filter((c) => inRange(c, days, days)), [all, days]);
  const terminal = cur.filter((c) => TERMINAL_OK.has(c.status || '') || TERMINAL_BAD.has(c.status || ''));
  const failed = cur.filter((c) => TERMINAL_BAD.has(c.status || '')).length;
  const success = terminal.length ? (terminal.length - failed) / terminal.length : null;
  // Delta only when the card window plausibly covers both periods (oldest card predates them).
  const oldest = all.length ? Math.min(...all.map((c) => (c.finished_at || 0) * 1000)) : 0;
  const windowCovers = oldest > 0 && oldest < Date.now() - 2 * days * DAY;
  const delta = windowCovers && prev.length > 0 ? ((cur.length - prev.length) / prev.length) * 100 : null;

  const degraded = (rows || []).filter((r) => r.stats.success != null && r.stats.success < 0.9 && r.stats.tasks7d >= 3);
  const recent = all.slice(0, 5);
  // Harness display names for Recent Tasks: cards may predate harness_name stamping and only
  // carry the id, resolve through the harness rows before falling back.
  const harnessName = (c: TraceCard) => {
    const byId = (rows || []).find((r) => r.id === c.harness_id)?.name;
    return byId || c.harness_name || '—';
  };

  const openTasks = (harnessId?: string, sid?: string) => {
    const q = new URLSearchParams();
    if (harnessId) q.set('h', harnessId);
    if (sid) q.set('sid', sid);
    const qs = q.toString();
    router.push(qs ? `/tasks?${qs}` : '/tasks');
  };

  return (
    <section className="view is-active" id="view-workspace">
      <div className="page">
        <div className="page-header">
          <div><h1 className="workspace-name">{current.name}</h1>
            <p>{current.description || 'Workspace overview'}</p></div>
          <div className="header-actions">
            <select className="select operational-range" aria-label="Operational time range" value={range}
              onChange={(e) => setRange(e.target.value as RangeKey)}>
              {RANGES.map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}
            </select>
          </div>
        </div>

        <div className="dashboard-kpis kpis-3" aria-label="Workspace key metrics">
          <button className="kpi-card primary-tint actionable" type="button" onClick={() => openTasks()}>
            <span>Tasks</span><strong>{rows ? cur.length.toLocaleString() : <SkelLine w={54} h={22} />}</strong>
            <small className={delta != null && delta >= 0 ? 'delta-up' : undefined}>
              {delta != null ? `${delta >= 0 ? '↑' : '↓'} ${Math.abs(delta).toFixed(1)}% vs previous period` : RANGES.find((r) => r.key === range)!.label}
            </small>
            <iconify-icon icon="tabler:list-check"></iconify-icon>
          </button>
          <button className="kpi-card green actionable" type="button" onClick={() => openTasks()}>
            <span>Success rate</span><strong>{rows ? (success != null ? `${(success * 100).toFixed(1)}%` : '—') : <SkelLine w={70} h={22} />}</strong>
            <small>{rows ? `${failed} failed Task${failed === 1 ? '' : 's'}` : 'No terminal tasks in range'}</small>
            <iconify-icon icon="tabler:trending-up"></iconify-icon>
          </button>
          <div className="kpi-card blue">
            <span>Credits used</span><strong>{credits30 != null ? credits30.toLocaleString() : <SkelLine w={54} h={22} />}</strong>
            <small>Last 30 days · account-wide</small>
            <iconify-icon icon="tabler:coins"></iconify-icon>
          </div>
        </div>

        <div className="dashboard-main-grid">
          <section className="dashboard-card" aria-labelledby="workspaceActivityTitle">
            <div className="dashboard-card-head">
              <div><h2 id="workspaceActivityTitle">Workspace activity</h2>
                <div className="chart-legend">
                  <span className="legend-item"><span className="legend-swatch bar"></span>Tasks</span>
                  <span className="legend-item"><span className="legend-swatch"></span>Overall success</span>
                </div></div>
              <button className="button quiet small" type="button" onClick={() => router.push('/harnesses')}>View Harnesses</button>
            </div>
            <div className="chart-wrap"><ActivityChart cards={all} days={days} /></div>
          </section>
          <aside className="dashboard-card attention-card" aria-labelledby="attentionTitle">
            <div className="dashboard-card-head">
              <div className="attention-title"><iconify-icon icon="tabler:alert-triangle"></iconify-icon><h2 id="attentionTitle">Needs attention</h2></div>
              <span>{degraded.length ? `${degraded.length} issue${degraded.length > 1 ? 's' : ''}` : 'All clear'}</span>
            </div>
            {degraded.length ? (
              <>
                <div className="attention-body">
                  <h3>{degraded[0].name} · degraded</h3>
                  <p>Success under 90% across its recent Tasks.</p>
                </div>
                <div className="attention-meta">
                  <div><span>Failed Tasks (7d)</span><strong>{degraded[0].stats.failed7d}</strong></div>
                  <div><span>Last activity</span><strong>{timeAgo(degraded[0].stats.lastActivity)}</strong></div>
                </div>
                <button className="button" type="button" onClick={() => openTasks(degraded[0].id)}>View failed Tasks</button>
              </>
            ) : (
              <div className="attention-body">
                <h3>No degraded Harnesses</h3>
                <p>Every Harness with recent activity is above the 90% success threshold.</p>
              </div>
            )}
          </aside>
        </div>

        <div className="dashboard-lower-grid">
          <section className="dashboard-card" aria-labelledby="overviewHarnessesTitle">
            <div className="dashboard-card-head"><div><h2 id="overviewHarnessesTitle">Harnesses</h2><p>Operational health · Last 7 days</p></div></div>
            <table className="dashboard-table"><thead><tr><th>Harness</th><th>Status</th><th>Tasks</th><th>Success</th><th>Last activity</th><th></th></tr></thead><tbody>
              {(rows || []).slice(0, 5).map((r) => {
                const bad = r.stats.success != null && r.stats.success < 0.9 && r.stats.tasks7d >= 3;
                return (
                  <tr key={r.id}>
                    <td><strong>{r.name}</strong></td>
                    <td><span className={'status ' + (bad ? 'warning' : 'healthy')}>{bad ? 'Degraded' : 'Healthy'}</span></td>
                    <td className="number">{r.stats.tasks7d.toLocaleString()}</td>
                    <td className="number">{r.stats.success != null ? `${(r.stats.success * 100).toFixed(1)}%` : '—'}</td>
                    <td>{timeAgo(r.stats.lastActivity)}</td>
                    <td><button className="row-action" type="button" aria-label={`Open ${r.name}`}
                      onClick={() => router.push(`/harnesses/${encodeURIComponent(r.id)}`)}><iconify-icon icon="tabler:chevron-right"></iconify-icon></button></td>
                  </tr>
                );
              })}
              {rows && rows.length === 0 && <tr><td colSpan={6} style={{ color: 'var(--muted)' }}>No Harnesses yet.</td></tr>}
              {!rows && <SkelRows rows={3} cols={6} first={150} />}
            </tbody></table>
            <div className="dashboard-card-foot"><button className="button quiet small" type="button" onClick={() => router.push('/harnesses')}>View all Harnesses</button></div>
          </section>
          <section className="dashboard-card" aria-labelledby="recentTasksTitle">
            <div className="dashboard-card-head"><div><h2 id="recentTasksTitle">Recent Tasks</h2><p>Latest activity across this Workspace</p></div></div>
            <table className="dashboard-table recent-tasks-table"><thead><tr><th>Task</th><th>Harness</th><th>Status</th><th>Updated</th><th></th></tr></thead><tbody>
              {recent.map((c) => {
                const chip = statusChip(c.status);
                const title = c.title || c.session_id;
                const hn = harnessName(c);
                return (
                  <tr key={c.session_id}>
                    <td className="cell-ellip cell-task" title={title}><strong>{title}</strong></td>
                    <td className="cell-ellip cell-harness" title={hn !== '—' ? hn : undefined}>{hn}</td>
                    <td><span className={'status ' + chip.cls}>{chip.label}</span></td>
                    <td className="cell-nowrap">{c.finished_at ? timeAgo(c.finished_at * 1000) : '—'}</td>
                    <td><button className="row-action" type="button" aria-label={`Open ${title}`}
                      onClick={() => openTasks(c.harness_id, c.session_id)}><iconify-icon icon="tabler:chevron-right"></iconify-icon></button></td>
                  </tr>
                );
              })}
              {rows && recent.length === 0 && <tr><td colSpan={5} style={{ color: 'var(--muted)' }}>No Tasks yet. Open Quickstart to connect a coding agent.</td></tr>}
              {!rows && <SkelRows rows={3} cols={5} first={170} />}
            </tbody></table>
            <div className="dashboard-card-foot"><button className="button quiet small" type="button" onClick={() => openTasks()}>View all Tasks</button></div>
          </section>
        </div>

      </div>
    </section>
  );
}
