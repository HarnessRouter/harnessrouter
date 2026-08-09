'use client';
// Dashboard, org level: which Workspace needs attention. Workspaces are first-level children of
// the org's HarnessRouter Space; each row aggregates that workspace's newest trace window
// client-side (server aggregation is a recorded TODO). Credits are org-level (billing has no
// per-workspace attribution yet).
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useWorkspace, type Workspace } from '@/lib/workspace';
import { fetchTraceWindow, groupByHarness, statsFor, type HarnessStats, type TraceCard } from '@/lib/revamp-data';
import { billing } from '../billing/lib';
import { SkelLine, SkelRows } from '@/components/Skel';

interface WsRow { ws: Workspace; stats: HarnessStats; harnesses: number; cards: TraceCard[];
  degradedHarnesses: number; degradedFailed: number }

export default function DashboardPage() {
  const router = useRouter();
  const { workspaces, defaultId, setCurrent, loading } = useWorkspace();
  const [rows, setRows] = useState<WsRow[] | null>(null);
  const [credits30, setCredits30] = useState<number | null>(null);
  const [search, setSearch] = useState('');

  useEffect(() => {
    if (loading) return;
    let alive = true;
    Promise.all(workspaces.map(async (ws) => {
      const cards = ws.id
        ? await fetchTraceWindow(undefined, { id: ws.id, isDefault: ws.id === defaultId }).catch(() => [] as TraceCard[])
        : await fetchTraceWindow(undefined, null).catch(() => [] as TraceCard[]);
      const harnesses = new Set(cards.map((c) => c.harness_id).filter(Boolean)).size;
      // Per-harness degradation inside this workspace (the mockup's notice is harness-based).
      let degradedHarnesses = 0, degradedFailed = 0;
      for (const [, hc] of groupByHarness(cards)) {
        const s = statsFor(hc);
        if (s.success != null && s.success < 0.9 && s.tasks7d >= 3) { degradedHarnesses += 1; degradedFailed += s.failed7d; }
      }
      return { ws, stats: statsFor(cards), harnesses, cards, degradedHarnesses, degradedFailed };
    })).then((r) => { if (alive) setRows(r); });
    const to = new Date(); const from = new Date(Date.now() - 30 * 86400_000);
    billing.usage({ from: from.toISOString().slice(0, 10), to: to.toISOString().slice(0, 10), bucket: 'day' })
      .then((u) => {
        if (!alive) return;
        const total = (u?.buckets || u?.rows || []).reduce((s: number, b: { credits?: number; total?: number }) => s + Number(b.credits ?? b.total ?? 0), 0);
        setCredits30(Math.round(total));
      }).catch(() => { /* em dash */ });
    return () => { alive = false; };
  }, [loading, workspaces, defaultId]);

  const degradedOf = (r: WsRow) => r.degradedHarnesses > 0;
  const degraded = (rows || []).filter(degradedOf);
  const tasks7d = (rows || []).reduce((s, r) => s + r.stats.tasks7d, 0);

  function openWorkspace(ws: Workspace) {
    if (ws.id) setCurrent(ws.id);
    router.push('/overview');
  }

  return (
    <section className="view is-active" id="view-dashboard">
      <div className="page">
        <div className="page-header">
          <div><h1>Dashboard</h1><p>See which Workspace needs attention, then open it to act.</p></div>
        </div>
        {degraded.length > 0 && (
          <div className="notice">
            <iconify-icon icon="tabler:alert-triangle"></iconify-icon>
            <div><strong>{degraded[0].ws.name} needs attention</strong>
              {degraded[0].degradedHarnesses === 1
                ? `One Harness is degraded after ${degraded[0].degradedFailed} failed Task${degraded[0].degradedFailed === 1 ? '' : 's'} in the last 7 days.`
                : `${degraded[0].degradedHarnesses} Harnesses are degraded in the last 7 days.`}</div>
          </div>
        )}
        <div className="metrics">
          <div className="metric"><span>Workspaces</span><strong>{rows ? rows.length : <SkelLine w={30} h={22} />}</strong><small>{degraded.length === 0 ? 'All healthy' : `${degraded.length} need${degraded.length === 1 ? 's' : ''} attention`}</small></div>
          <div className="metric"><span>Tasks</span><strong>{rows ? tasks7d.toLocaleString() : <SkelLine w={54} h={22} />}</strong><small>Last 7 days</small></div>
          <div className="metric"><span>Credits used</span><strong>{credits30 != null ? credits30.toLocaleString() : <SkelLine w={54} h={22} />}</strong><small>Last 30 days · whole org</small></div>
        </div>
        <div className="section-header"><h2>Workspaces</h2></div>
        <div className="toolbar">
          <input className="search-input" type="search" placeholder="Search workspaces" aria-label="Search workspaces"
            value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Workspace</th><th>Harnesses</th><th>Health</th><th>Tasks (7d)</th><th>Credits (30d)</th><th aria-label="Actions"></th></tr>
            </thead>
            <tbody>
              {(rows || [])
                .filter((r) => !search.trim() || r.ws.name.toLowerCase().includes(search.trim().toLowerCase()))
                .map((r) => {
                const bad = degradedOf(r);
                return (
                  <tr key={r.ws.id || 'default'} className="object-row" onClick={() => openWorkspace(r.ws)} style={{ cursor: 'pointer' }}>
                    <td className="object-cell"><div className="object-title"><span className="object-icon"><iconify-icon icon="tabler:home"></iconify-icon></span><div className="object-copy"><strong>{r.ws.name}</strong><span>{r.ws.description || (r.ws.id === defaultId ? 'All harnesses, tasks, and keys in this organization.' : '')}</span></div></div></td>
                    <td className="number">{r.harnesses}</td>
                    <td><span className={'status ' + (bad ? 'warning' : 'healthy')}>{bad ? `${r.degradedHarnesses} issue${r.degradedHarnesses > 1 ? 's' : ''}` : 'Healthy'}</span></td>
                    <td className="number">{r.stats.tasks7d.toLocaleString()}</td>
                    <td className="number">—</td>
                    <td><button className="row-action" type="button" aria-label={`Open ${r.ws.name}`}><iconify-icon icon="tabler:chevron-right"></iconify-icon></button></td>
                  </tr>
                );
              })}
              {!rows && <SkelRows rows={2} cols={8} first={190} />}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
