'use client';
// Harnesses, per-harness operations + the only entry to configuration. Scannable table
// (purpose, health, runtime, tasks, success, last activity); row click opens the single
// Settings form at /harnesses/[id]. Instructions file names intentionally stay OFF the list.
import { useEffect, useState } from 'react';
import { SkelRows } from '@/components/Skel';
import { useRouter } from 'next/navigation';
import { OOB, oobById, oobDefaultModel, oobModels, useModelCatalog, createCustom } from '@/lib/harness';
import { HarnessLogo } from '@/components/HarnessLogo';
import { CopyId } from '@/components/CopyId';
import { fetchHarnessRows, groupByHarness, timeAgo, p95Of, avgCreditsOf, type HarnessRow, type TraceCard } from '@/lib/revamp-data';
import { SELF_HOSTED } from '@/lib/edition';

export default function HarnessesPage() {
  useModelCatalog();   // model list comes from the gateway, not a local copy
  const router = useRouter();
  const [rows, setRows] = useState<HarnessRow[] | null>(null);
  const [byHarness, setByHarness] = useState<Map<string, TraceCard[]>>(new Map());
  const [q, setQ] = useState('');
  const [baseFlt, setBaseFlt] = useState('all');
  const [healthFlt, setHealthFlt] = useState('all');
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState('');
  const [base, setBase] = useState('codex');
  const [model, setModel] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    fetchHarnessRows().then(({ rows, all }) => {
      if (alive) { setRows(rows); setByHarness(groupByHarness(all)); }
    }).catch(() => setRows([]));
    return () => { alive = false; };
  }, []);

  const baseOf = (r: HarnessRow) => (r.kind === 'builtin' ? r.id : (r.runtime.split(' · ')[0] || ''));
  // Display names: old records store base ids (claude-code) in the runtime label, resolve to the
  // OOB display name; model subtitle keeps the stored value, prettified when it's the default marker.
  const baseDisplay = (r: HarnessRow): { id: string; name: string; model: string } => {
    const [rawBase, rawModel] = r.runtime.split(' · ');
    const o = OOB.find((x) => x.id === rawBase || x.name === rawBase || x.id === rawBase?.toLowerCase().replace(/\s+/g, '-'));
    return { id: o?.id || '', name: o?.name || rawBase || '—',
             model: rawModel === 'backend default' ? 'Backend default' : (rawModel || '') };
  };
  const isDegraded = (r: HarnessRow) => r.stats.success != null && r.stats.success < 0.9 && r.stats.tasks7d >= 3;
  const filtered = (rows || [])
    .filter((r) => !q.trim() || r.name.toLowerCase().includes(q.toLowerCase()) || r.purpose.toLowerCase().includes(q.toLowerCase()))
    .filter((r) => {
      if (baseFlt === 'all') return true;
      const b = baseOf(r).toLowerCase();
      if (baseFlt === 'codex') return b.includes('codex');
      if (baseFlt === 'hermes') return b.includes('hermes');
      // 'pi' must be an exact-ish match: substring would also catch every base that merely
      // contains the letters (nothing today, but 'claude' teaches the lesson cheaply).
      if (baseFlt === 'pi') return b === 'pi' || b.startsWith('pi ');
      return b.includes('claude');
    })
    .filter((r) => healthFlt === 'all' || (healthFlt === 'review') === isDegraded(r));

  async function submitAdd() {
    if (!name.trim() || busy) return;
    setBusy(true); setErr(null);
    try {
      const base0 = OOB.find((o) => o.id === base);
      const c = await createCustom({ name: name.trim(), base, defaultModel: model || oobDefaultModel(base0) });
      router.push(`/harnesses/${encodeURIComponent(c.id)}`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <section className="view is-active collection-view" id="view-harnesses">
      <div className="page">
        <div className="page-header">
          <div><h1>Harnesses</h1><p>Create, monitor, and configure the reusable agents in this Workspace.</p></div>
          <button className="button primary" type="button" onClick={() => { setName(''); setAdding(true); }}><iconify-icon icon="tabler:plus"></iconify-icon>Add Harness</button>
        </div>
        <div className="toolbar">
          <div className="collection-tools">
            <input className="search-input" type="search" placeholder="Search Harnesses" aria-label="Search Harnesses"
              value={q} onChange={(e) => setQ(e.target.value)} />
            <select className="select" aria-label="Filter by Base Harness" value={baseFlt} onChange={(e) => setBaseFlt(e.target.value)}>
              <option value="all">All Base Harnesses</option>
              <option value="codex">Codex</option>
              <option value="claude">Claude Code</option>
              <option value="pi">Pi</option>
              <option value="hermes">Hermes</option>
            </select>
            <select className="select" aria-label="Filter Harnesses by health" value={healthFlt} onChange={(e) => setHealthFlt(e.target.value)}>
              <option value="all">All health</option>
              <option value="healthy">Healthy</option>
              <option value="review">Needs review</option>
            </select>
          </div>
          <span className="object-count">{rows ? `${filtered.length} Harness${filtered.length === 1 ? '' : 'es'}` : ''}</span>
        </div>
        <div className="table-wrap">
          <table className="harness-inventory-table">
            <thead><tr><th>Harness</th><th className="harness-desktop-col">Harness ID</th><th>Health</th><th className="harness-desktop-col">Base Harness</th><th className="harness-desktop-col">Tasks (7d)</th><th className="harness-desktop-col">Success</th><th className="harness-desktop-col">p95</th>{SELF_HOSTED ? null : <th className="harness-desktop-col">Credits / Task</th>}<th className="harness-desktop-col">Last activity</th><th aria-label="Open"></th></tr></thead>
            <tbody>
              {filtered.map((r) => {
                const bad = isDegraded(r);
                const { id: baseId, name: baseName, model: modelName } = baseDisplay(r);
                return (
                  <tr key={r.id} className="object-row" style={{ cursor: 'pointer' }}
                    onClick={() => router.push(`/harnesses/${encodeURIComponent(r.id)}`)}>
                    <td className="object-cell"><div className="object-title">
                      <span className="object-icon"><iconify-icon icon={r.kind === 'builtin' ? 'tabler:box' : 'tabler:terminal-2'}></iconify-icon></span>
                      <div className="object-copy"><strong>{r.name}</strong><span>{r.kind === 'builtin' ? `Built-in · ${r.purpose}` : r.purpose}</span></div>
                    </div></td>
                    <td className="harness-desktop-col" onClick={(e) => e.stopPropagation()}><CopyId value={r.id} /></td>
                    <td><span className={'status ' + (bad ? 'warning' : 'healthy')}>{bad ? 'Needs review' : 'Healthy'}</span></td>
                    <td className="harness-desktop-col"><div className="harness-runtime harness-runtime-logo"><HarnessLogo id={r.kind === 'builtin' ? r.id : baseId} size={22} /><div><strong>{baseName}</strong><span>{modelName || ''}</span></div></div></td>
                    <td className="number harness-desktop-col">{r.stats.tasks7d}</td>
                    <td className="number harness-desktop-col">{r.stats.success != null ? (r.stats.success * 100).toFixed(1) + '%' : '—'}</td>
                    <td className="number harness-desktop-col">{p95Of(byHarness.get(r.id)) ?? '—'}</td>
                    {SELF_HOSTED ? null : <td className="number harness-desktop-col">{avgCreditsOf(byHarness.get(r.id)) ?? '—'}</td>}
                    <td className="harness-desktop-col">{timeAgo(r.stats.lastActivity)}</td>
                    <td><button className="row-action" type="button" aria-label={`Open ${r.name}`}><iconify-icon icon="tabler:chevron-right"></iconify-icon></button></td>
                  </tr>
                );
              })}
              {rows && !filtered.length && <tr><td colSpan={10} className="session-empty">No harnesses match.</td></tr>}
              {!rows && <SkelRows rows={4} cols={10} first={200} />}
            </tbody>
          </table>
        </div>
      </div>

      {adding && (
        <div className="modal-backdrop">
          <section className="modal" role="dialog" aria-modal="true" aria-labelledby="addHarnessTitle" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div><h2 id="addHarnessTitle">Add Harness</h2><p>Choose the Base Harness first. You can configure instructions, Tools, Skills, and limits after creation.</p></div>
              <button className="icon-button modal-close" type="button" aria-label="Close dialog" onClick={() => setAdding(false)}><iconify-icon icon="tabler:x"></iconify-icon></button>
            </div>
            <div className="modal-body">
              <div className="field-stack">
                <div className="field"><label htmlFor="newHarnessName">Name</label>
                  <input id="newHarnessName" value={name} placeholder="Customer Support Agent" autoFocus
                    onChange={(e) => setName(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') void submitAdd(); }} />
                  <span className="field-help">Name the reusable agent configuration, not an individual Task.</span></div>
                <fieldset className="field" style={{ margin: 0, padding: 0, border: 0 }}>
                  <legend style={{ marginBottom: 6, color: '#55555f', fontSize: 12, fontWeight: 650 }}>Base Harness</legend>
                  <div className="base-choice-list">
                    {OOB.filter((o) => o.status === 'ready').map((o) => (
                      <label key={o.id} className="base-choice">
                        <input type="radio" name="baseHarness" value={o.id} checked={base === o.id}
                          onChange={() => { setBase(o.id); setModel(''); }} />
                        <span className="base-choice-icon"><HarnessLogo id={o.id} size={24} /></span>
                        <span className="base-choice-copy"><strong>{o.name}</strong>
                          <span>{o.id === 'codex'
                            ? 'Best for repository work, code changes, shell commands, and generated files.'
                            : o.id === 'hermes'
                              ? 'Self-improving agent that builds memory and skills across Tasks, best for evolving, long-running work.'
                              : o.id === 'pi'
                                ? 'Minimal, steerable harness with four core tools, best when you want a lean agent you can shape.'
                                : 'Best for long-context analysis, document workflows, and structured review.'}</span></span>
                        <span className="base-choice-models">{oobDefaultModel(o)} default</span>
                      </label>
                    ))}
                  </div>
                  <span className="field-help">The Base Harness determines compatible models and inherited capabilities. It cannot be changed after creation.</span>
                </fieldset>
                <div className="field"><label htmlFor="newHarnessModel">Default model</label>
                  <select id="newHarnessModel" value={model || oobDefaultModel(oobById(base))} onChange={(e) => setModel(e.target.value)}>
                    {oobModels(oobById(base)).map((m) => <option key={m} value={m}>{m}</option>)}
                  </select></div>
                {err && <div className="notice"><iconify-icon icon="tabler:alert-triangle"></iconify-icon><div><strong>Could not create</strong>{err}</div></div>}
              </div>
              <div className="creation-next"><iconify-icon icon="tabler:arrow-right"></iconify-icon><span>Next, you&rsquo;ll land in Harness Settings to review inherited Tools and Skills, add instructions, set runtime limits, and save the configuration.</span></div>
              <div className="modal-actions">
                <button className="button" type="button" onClick={() => setAdding(false)} disabled={busy}>Cancel</button>
                <button className="button primary" type="button" onClick={() => void submitAdd()} disabled={busy || !name.trim()}>{busy ? 'Creating…' : 'Create and configure'}</button>
              </div>
            </div>
          </section>
        </div>
      )}
    </section>
  );
}
