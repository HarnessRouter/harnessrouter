'use client';
// Agent harnesses: the one page for the product's core object (the v2 design, 终版).
//
// Three panes. The nav. A harness panel: search across harnesses and tasks, a Dashboard row
// (the index of every harness), and each harness with its own task list, a New task and a
// settings control. A main area that is one of: a task (its conversation and trace), the
// harness index, or a harness's settings. Tasks are not a separate page any more: a task
// belongs to its harness, and it opens where the harness is.
//
// The URL is the state: ?h= names the harness, ?sid= the task, ?view=index|settings the view.
// Old /tasks and /harnesses/[id] links redirect here with the same names.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { SkelListItems } from '@/components/Skel';
import { HarnessLogo } from '@/components/HarnessLogo';
import { CopyId } from '@/components/CopyId';
import { ConfigChat, ShareModal, type ConvTotals } from '@/components/TaskChat';
import { HarnessSettings } from '@/components/HarnessSettings';
import { OOB, oobById, oobDefaultModel, oobModels, useModelCatalog, createCustom, listCustom,
         type CustomHarness } from '@/lib/harness';
import { fetchHarnessRows, groupByHarness, timeAgo, p95Of, avgCreditsOf, RUNNING, TERMINAL_OK, TERMINAL_BAD,
         type HarnessRow, type TraceCard, fetchHarnessTasks, sortByActivity } from '@/lib/revamp-data';
import { track } from '@/lib/analytics';
import { getCurrentWorkspaceRef } from '@/lib/workspace';
import { useEscape } from '@/lib/useEscape';
import { getConvState, type UserMsg } from '@/lib/conversation';

type View = 'index' | 'chat' | 'settings';
type TaskState = 'done' | 'running' | 'failed' | 'cancelled' | 'incomplete';

function taskState(status?: string): TaskState {
  const s = status || '';
  if (TERMINAL_OK.has(s)) return 'done';
  if (RUNNING.has(s)) return 'running';
  if (TERMINAL_BAD.has(s)) return 'failed';
  if (s === 'cancelled') return 'cancelled';
  return 'incomplete';
}

/** A harness's loaded tasks: the pages read so far, the cursor for the next, and whether one is in flight. */
interface TaskSlice { list: TraceCard[]; cursor: string; pages: number; loading: boolean }

/** "4.2s" under a minute, "1m 12s" past it. */
function fmtLatency(s: number): string {
  if (s < 60) return `${s < 10 ? s.toFixed(1) : Math.round(s)}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${Math.round(s - m * 60)}s`;
}

/** "Codex · gpt-5.4" for a row, from the same fields the old list read. */
function runtimeOf(r: HarnessRow): { baseId: string; name: string; model: string } {
  if (r.kind === 'builtin') {
    const o = oobById(r.id);
    return { baseId: r.id, name: o?.name || r.name, model: oobDefaultModel(o) || '' };
  }
  const [rawBase, rawModel] = r.runtime.split(' · ');
  const o = OOB.find((x) => x.id === rawBase || x.name === rawBase || x.id === rawBase?.toLowerCase().replace(/\s+/g, '-'));
  return { baseId: o?.id || '', name: o?.name || rawBase || '—', model: rawModel === 'backend default' ? '' : (rawModel || '') };
}

export default function HarnessesPage() {
  const router = useRouter();
  const params = useSearchParams();
  useModelCatalog();
  const h = params.get('h') || '';
  const sid = params.get('sid') || '';
  const view: View = params.get('view') === 'settings' && h ? 'settings' : (h && params.get('view') !== 'index') ? 'chat' : 'index';

  const [custom, setCustom] = useState<CustomHarness[]>([]);
  const [rows, setRows] = useState<HarnessRow[] | null>(null);
  const [cards, setCards] = useState<TraceCard[]>([]);
  const [q, setQ] = useState('');
  // One harness is expanded at a time (an accordion), so the task refresh has one folder to keep
  // current and the panel never becomes a wall of every harness's tasks.
  const [open, setOpen] = useState<string | null>(h || null);
  // Each expanded harness lists ITS OWN tasks, paged 50 at a time from that harness's index with
  // "Load more" at the foot of the folder. The org-wide window (`cards`) is the newest 200
  // sessions across the workspace; in a busy org that is a few days, and every harness whose
  // last task is older would read "No tasks yet".
  const [perHarness, setPerHarness] = useState<Record<string, TaskSlice>>({});
  const [tick, setTick] = useState(0);
  const loadTasks = useCallback(async (id: string, cursor = '') => {
    setPerHarness((p) => ({ ...p, [id]: { list: p[id]?.list ?? [], cursor: p[id]?.cursor ?? '', pages: p[id]?.pages ?? 0, loading: true } }));
    const { sessions, cursor: next } = await fetchHarnessTasks(id, cursor);
    setPerHarness((p) => {
      const prev = p[id] ?? { list: [], cursor: '', pages: 0, loading: false };
      const seen = new Set(sessions.map((c) => c.session_id));
      // A refresh re-reads the first page and keeps the deeper pages already loaded; a
      // "Load more" appends. Either way one entry per session, most recent activity first.
      const list = sortByActivity(cursor ? [...prev.list, ...sessions.filter((c) => !prev.list.some((x) => x.session_id === c.session_id))]
                                        : [...sessions, ...prev.list.filter((c) => !seen.has(c.session_id))]);
      return { ...p, [id]: { list, cursor: cursor || prev.pages <= 1 ? next : prev.cursor, pages: cursor ? prev.pages + 1 : Math.max(prev.pages, 1), loading: false } };
    });
  }, []);
  const [adding, setAdding] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [totals, setTotals] = useState<ConvTotals | null>(null);
  useEffect(() => { setTotals(null); }, [sid]);
  // Narrow screens (CSS <=820px) alternate between the panel and the main area, as Tasks did.
  const [mobileDetail, setMobileDetail] = useState(false);
  useEffect(() => { if (h || view === 'index') setMobileDetail(!!h || params.get('view') === 'index'); }, [h, view]); // eslint-disable-line react-hooks/exhaustive-deps

  const reloadCustom = useCallback(() => { void listCustom().then(setCustom).catch(() => setCustom([])); }, []);
  const refresh = useCallback(() => {
    void fetchHarnessRows().then(({ rows: r, all }) => { setRows(r); setCards(all); }).catch(() => setRows((prev) => prev || []));
    setTick((t) => t + 1);
  }, []);
  useEffect(() => { if (open) void loadTasks(open); }, [open, tick, loadTasks]);
  useEffect(() => { reloadCustom(); refresh(); }, [reloadCustom, refresh]);
  // A running task keeps the panel fresh; an idle page does not poll.
  const anyRunning = cards.some((c) => RUNNING.has(c.status || ''));
  useEffect(() => {
    if (!anyRunning) return;
    const iv = setInterval(refresh, 15000);
    return () => clearInterval(iv);
  }, [anyRunning, refresh]);
  // The selected harness's own tasks stay open in the panel.
  useEffect(() => { if (h) setOpen(h); }, [h]);

  const byHarness = useMemo(() => groupByHarness(cards), [cards]);
  const tasksOf = useCallback((id: string) => perHarness[id]?.list ?? byHarness.get(id) ?? [], [perHarness, byHarness]);
  const oob = oobById(h);
  const ch = oob ? null : (custom.find((c) => c.id === h) || null);
  const harnessName = oob?.name || ch?.name || '';
  const row = (rows || []).find((r) => r.id === h) || null;
  const card = sid ? cards.find((c) => c.session_id === sid) || Object.values(perHarness).flatMap((s) => s.list).find((c) => c.session_id === sid) || null : null;
  // A session that was born in this tab has a conversation before it has an index record: its
  // first message is the title until the record lands.
  const liveFirst = sid && !card
    ? ((getConvState(sid)?.msgs || []).find((m) => m.role === 'user') as UserMsg | undefined)?.text?.split('\n')[0].slice(0, 120) || ''
    : '';

  const go = useCallback((next: { h?: string; sid?: string; view?: 'index' | 'settings' }, replace = false) => {
    const p = new URLSearchParams();
    if (next.h) p.set('h', next.h);
    if (next.sid) p.set('sid', next.sid);
    if (next.view) p.set('view', next.view);
    const url = `/harnesses${p.toString() ? `?${p.toString()}` : ''}`;
    if (replace) router.replace(url); else router.push(url);
  }, [router]);

  // ── the panel: harnesses with their tasks, filtered by one search ──
  const needle = q.trim().toLowerCase();
  const panel = useMemo(() => (rows || []).map((r) => {
    const tasks = tasksOf(r.id);
    const shownTasks = needle ? tasks.filter((c) => (c.title || '').toLowerCase().includes(needle)) : tasks;
    const nameHit = !needle || r.name.toLowerCase().includes(needle);
    const slice = perHarness[r.id];
    return { r, tasks: shownTasks, loaded: (slice?.pages ?? 0) > 0, more: !needle && !!slice?.cursor, loading: !!slice?.loading, visible: nameHit || shownTasks.length > 0 };
  }).filter((x) => x.visible), [rows, tasksOf, perHarness, needle]);

  // ── the header ──
  const rt = row ? runtimeOf(row) : null;
  const crumb = view === 'index' ? ['Agent harnesses', 'reusable agents']
    : [harnessName || '…', rt ? [rt.name, rt.model].filter(Boolean).join(' · ') : ''];
  const title = view === 'index' ? 'Agent harnesses' : view === 'settings' ? harnessName : (card?.title || liveFirst || (sid ? 'Task' : 'New task'));
  const pill = view === 'index' ? 'workspace' : view === 'settings' ? 'harness settings' : (sid ? taskState(card?.status) : 'draft');

  const openIndex = () => { setMobileDetail(true); go({ view: 'index' }); };
  const openTask = (hid: string, s: string) => { setMobileDetail(true); go({ h: hid, sid: s }); };
  const openNew = (hid: string) => {
    setMobileDetail(true);
    // already on this harness's fresh draft: there is nowhere to go, so put the caret back in the box
    if (hid === h && !sid && view === 'chat') { (document.querySelector('.wbx-conv-main .wbx-composer textarea') as HTMLTextAreaElement | null)?.focus(); return; }
    go({ h: hid });
  };
  const openSettings = (hid: string) => { setMobileDetail(true); go({ h: hid, view: 'settings' }); };
  const toggle = (hid: string) => setOpen((s) => (s === hid ? null : hid));

  return (
    <section className={'hx-root' + (mobileDetail ? ' m-detail' : '')} id="view-harnesses">
      <aside className="hx-side" aria-label="Harnesses and their tasks">
        <div className="hx-side-head">
          <span className="hx-side-title">Agent harnesses</span>
          <label className="hx-search">
            <iconify-icon icon="tabler:search"></iconify-icon>
            <input type="search" placeholder="Search harnesses and tasks" aria-label="Search harnesses and tasks"
              value={q} onChange={(e) => setQ(e.target.value)} autoComplete="off" />
          </label>
        </div>
        {/* The Dashboard row stays put; only the harness list scrolls. */}
        <div className="hx-side-fixed">
          <button type="button" className={'hx-index' + (view === 'index' ? ' is-on' : '')} aria-current={view === 'index' ? 'page' : undefined} onClick={openIndex}>
            <iconify-icon icon="tabler:layout-grid"></iconify-icon>
            <span>Dashboard</span>
            {rows && <b>{rows.length}</b>}
          </button>
          <div className="hx-div" />
        </div>
        <div className="hx-side-scroll">
          {!rows ? <SkelListItems rows={4} /> : panel.length === 0 ? (
            <div className="hx-empty">{needle ? 'Nothing matches that.' : 'No harnesses yet.'}</div>
          ) : panel.map(({ r, tasks, loaded, more, loading }) => {
            const isOpen = open === r.id || !!needle;
            const running = tasks.filter((c) => RUNNING.has(c.status || '')).length;
            return (
              <div key={r.id} className={'hx-proj' + (r.id === h ? ' is-current' : '')}>
                <div className="hx-proj-row">
                  <button type="button" className="hx-proj-btn" aria-expanded={isOpen} onClick={() => toggle(r.id)}>
                    <iconify-icon icon={isOpen ? 'tabler:chevron-down' : 'tabler:chevron-right'} className="hx-caret"></iconify-icon>
                    <HarnessLogo id={r.kind === 'builtin' ? r.id : runtimeOf(r).baseId} size={14} />
                    <span className="hx-proj-name">{r.name}</span>
                    {running > 0 && <span className="hx-proj-badge" title={`${running} running`}>{running}</span>}
                  </button>
                  <button type="button" className="hx-ic" title="New task" aria-label={`New task in ${r.name}`} onClick={() => openNew(r.id)}>
                    <iconify-icon icon="tabler:plus"></iconify-icon>
                  </button>
                  <button type="button" className="hx-ic" title="Harness settings" aria-label={`Settings for ${r.name}`} onClick={() => openSettings(r.id)}>
                    <iconify-icon icon="tabler:settings"></iconify-icon>
                  </button>
                </div>
                {isOpen && (
                  <div className="hx-tasks">
                    {tasks.length === 0 ? (loaded ? <div className="hx-tasks-empty">No tasks yet</div> : null) : tasks.map((c) => {
                      const on = c.session_id === sid;
                      return (
                        <button key={c.session_id} type="button" className={'hx-task' + (on ? ' is-on' : '')}
                          aria-current={on ? 'true' : undefined} onClick={() => openTask(r.id, c.session_id)}>
                          <i className={'hx-dot is-' + taskState(c.status)} aria-hidden="true" />
                          <span>{c.title || 'Task'}</span>
                        </button>
                      );
                    })}
                    {more && (
                      <button type="button" className="hx-more" disabled={loading} onClick={() => void loadTasks(r.id, perHarness[r.id]?.cursor)}>
                        {loading ? 'Loading' : 'Load more'}
                      </button>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </aside>

      <div className="hx-main">
        <header className={'hx-head' + (view === 'chat' ? ' has-tabs' : '')}>
          <div className="hx-head-row">
            <div className="hx-head-lead">
              <button className="hx-back" type="button" onClick={() => setMobileDetail(false)}>
                <iconify-icon icon="tabler:chevron-left"></iconify-icon>Harnesses
              </button>
              <div className="hx-crumb"><span>{crumb[0]}</span>{crumb[1] ? <><span className="hx-crumb-sep">/</span><span className="hx-crumb-cfg">{crumb[1]}</span></> : null}</div>
              <div className="hx-title-row">
                <h1 className="hx-title" title={title}>{title}</h1>
                <span className={'hx-pill is-' + (view === 'chat' ? pill : 'neutral')}>{pill}</span>
                {/* What this task has taken and cost. Credits come from the task record (the whole
                    session, priced at every settle); latency from the turns that carry it, "≥" when
                    older turns do not. Nothing is shown before either is known. */}
                {view === 'chat' && sid && (() => {
                  const credits = card?.credits != null && card.credits > 0 ? card.credits
                    : totals && totals.costed > 0 ? totals.credits : null;
                  const creditsPartial = !(card?.credits != null && card.credits > 0) && !!totals && totals.costed < totals.finished;
                  // latency from the turns that carry it; a record from before per-turn stamping still
                  // knows its own elapsed, so fall back to that rather than show nothing
                  const latency = totals && totals.timed > 0 ? totals.elapsed : (card?.elapsed != null && card.elapsed > 0 ? card.elapsed : null);
                  const latencyPartial = !!totals && totals.timed > 0 && totals.timed < totals.finished;
                  if (credits == null && latency == null) return null;
                  return (
                    <span className="hx-badges" aria-label="Task totals">
                      {latency != null && (
                        <span className="hx-badge" title={`Total latency${latencyPartial ? `, from ${totals!.timed} of ${totals!.finished} turns` : ''}`}>
                          <iconify-icon icon="tabler:clock"></iconify-icon>{latencyPartial ? '≥ ' : ''}{fmtLatency(latency)}
                        </span>
                      )}
                      {credits != null && (
                        <span className="hx-badge" title="Credits this task has used">
                          <iconify-icon icon="tabler:coins"></iconify-icon>{creditsPartial ? '≥ ' : ''}{credits < 1 ? credits.toFixed(3) : credits.toLocaleString(undefined, { maximumFractionDigits: 2 })} credits
                        </span>
                      )}
                    </span>
                  );
                })()}
              </div>
            </div>
            <div className="hx-head-actions">
              {view === 'chat' && sid && (
                <button className="hx-icbtn" type="button" title="Share this task" aria-label="Share this task" onClick={() => setSharing(true)}>
                  <iconify-icon icon="tabler:share-2"></iconify-icon>
                </button>
              )}
              {view === 'chat' && h && <button className="hx-secondary" type="button" onClick={() => openNew(h)}>New task</button>}
              {view === 'settings' && h && <button className="hx-secondary" type="button" onClick={() => go({ h })}>Back to tasks</button>}
              {view === 'index' && <button className="hx-primary" type="button" onClick={() => setAdding(true)}>New harness</button>}
            </div>
          </div>
        </header>

        <div className={'hx-body' + (view === 'chat' ? ' is-chat' : '')}>
          {view === 'index' && (
            <IndexTable rows={rows} byHarness={byHarness} onOpen={(r) => {
              // Open the harness's newest task, from its own index, else a fresh draft.
              const pick = (list: TraceCard[]) => { const newest = list[0]; if (newest) openTask(r.id, newest.session_id); else openNew(r.id); };
              if (perHarness[r.id]?.pages) pick(perHarness[r.id].list); else void fetchHarnessTasks(r.id).then(({ sessions }) => pick(sortByActivity(sessions)));
            }} />
          )}
          {view === 'settings' && h && (
            <HarnessSettings key={h} id={h} embedded
              onNavigate={(to) => { if (to === 'tasks') go({ h }); else go({ view: 'index' }); reloadCustom(); refresh(); }} />
          )}
          {/* Keyed by harness only: the task to show travels through deepSid, so a draft that
              just became a session keeps streaming instead of being remounted. */}
          {view === 'chat' && h && (oob || ch) && (
            <ConfigChat key={h}
              oob={oob} ch={ch} harnessId={h} harnessName={harnessName} deepSid={sid || undefined}
              onActiveSid={(s) => {
                if (!s || s === sid) return;
                go({ h, sid: s }, true);
                // The index lists the new session a moment after it is accepted; read it again then.
                refresh(); setTimeout(refresh, 2500); setTimeout(refresh, 8000);
              }}
              onHarness={(id) => { if (id !== h) go({ h: id, sid }, true); }}
              onActivity={() => { refresh(); setTimeout(refresh, 2500); setTimeout(refresh, 8000); }}
              onTotals={setTotals}
              onSaved={reloadCustom} />
          )}
          {view === 'chat' && h && !oob && !ch && custom.length > 0 && (
            <div className="hx-empty-main">This harness is not in this workspace. Pick one from the list.</div>
          )}
        </div>
      </div>

      {sharing && sid && <ShareModal sid={sid} onClose={() => setSharing(false)} />}
      {adding && (
        <AddHarness onClose={() => setAdding(false)} existing={(rows || []).filter((r) => r.kind !== 'builtin').length}
          onCreated={(id) => { setAdding(false); reloadCustom(); refresh(); openSettings(id); }} />
      )}
    </section>
  );
}

// ── the index: every harness, its health and its numbers over the last 7 days ─────────────
function IndexTable({ rows, byHarness, onOpen }: {
  rows: HarnessRow[] | null; byHarness: Map<string, TraceCard[]>; onOpen: (r: HarnessRow) => void;
}) {
  return (
    <div className="hx-index-wrap">
      <div className="hx-index-note">{rows ? `${rows.length} ${rows.length === 1 ? 'harness' : 'harnesses'} · last 7 days` : ''}</div>
      <div className="hx-card">
        <div className="hx-thead" aria-hidden="true">
          <span>Harness</span><span className="hx-th-id">Harness ID</span><span>Health</span><span className="hx-th-rt">Runtime</span>
          <span className="hx-th-n">Tasks</span><span className="hx-th-n hx-th-success">Success</span><span className="hx-th-n hx-th-p95">P95</span><span className="hx-th-n hx-th-cpt">Cr / task</span>
          <span className="hx-th-last">Last activity</span><span />
        </div>
        {!rows ? <SkelListItems rows={4} /> : rows.length === 0 ? (
          <div className="hx-empty-main">No harnesses yet. Create one to give an agent a name, instructions and tools.</div>
        ) : rows.map((r) => {
          const rt = runtimeOf(r);
          const s = r.stats;
          const idle = s.tasks7d === 0;
          const bad = s.success != null && s.success < 0.9 && s.tasks7d >= 3;
          const health = idle ? 'idle' : bad ? 'degraded' : 'healthy';
          return (
            <button key={r.id} type="button" className="hx-row" onClick={() => onOpen(r)}>
              <span className="hx-row-name">
                <b>{r.name}</b>
                <small>{r.kind === 'builtin' ? `Built-in · ${r.purpose}` : r.purpose}</small>
              </span>
              <span className="hx-row-id hx-th-id" onClick={(e) => e.stopPropagation()}><CopyId value={r.id} /></span>
              <span className={'hx-health is-' + health}><i aria-hidden="true" />{health}</span>
              <span className="hx-row-rt hx-th-rt">
                <HarnessLogo id={rt.baseId} size={16} />
                <span><b>{rt.name}</b>{rt.model ? <small>{rt.model}</small> : null}</span>
              </span>
              <span className="hx-num hx-th-n">{s.tasks7d}</span>
              <span className={'hx-num hx-th-n hx-th-success' + (bad ? ' is-bad' : '')}>{s.success != null ? `${Math.round(s.success * 100)}%` : '—'}</span>
              <span className="hx-num hx-th-n hx-th-p95">{p95Of(byHarness.get(r.id)) ?? '—'}</span>
              <span className="hx-num hx-th-n hx-th-cpt">{avgCreditsOf(byHarness.get(r.id)) ?? '—'}</span>
              <span className="hx-num hx-th-last">{s.lastActivity ? timeAgo(s.lastActivity) : '—'}</span>
              <span className="hx-row-chev" aria-hidden="true">›</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ── add a harness: name, base, default model; lands in its settings ───────────────────────
function AddHarness({ onClose, onCreated, existing }: { onClose: () => void; onCreated: (id: string) => void; existing: number }) {
  const ready = OOB.filter((o) => o.status === 'ready');
  const [name, setName] = useState('');
  const [base, setBase] = useState(ready[0]?.id || 'codex');
  const [model, setModel] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  useEscape(true, () => { if (!busy) onClose(); });
  const baseObj = oobById(base);
  async function submit() {
    if (!name.trim() || busy) return;
    setBusy(true); setErr('');
    try {
      const chosen = model || oobDefaultModel(baseObj);
      const c = await createCustom({ name: name.trim(), base, defaultModel: chosen });
      track('harness_created', { base, model: chosen || null, harness_count_before: existing,
                                 workspace_id: getCurrentWorkspaceRef()?.id || null });
      onCreated(c.id);
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); setBusy(false); }
  }
  const blurb = (id: string) => id === 'codex' ? 'Repository work, code changes, shell commands, generated files.'
    : id === 'hermes' ? 'Self-improving agent that builds memory and skills across tasks.'
    : 'Long-context analysis, document workflows, structured review.';
  return (
    <div className="ak-scrim" onMouseDown={() => { if (!busy) onClose(); }}>
      <section className="ak-modal hx-add" role="dialog" aria-modal="true" aria-labelledby="hxAddTitle" onMouseDown={(e) => e.stopPropagation()}>
        <div className="ak-modal-body">
          <h2 id="hxAddTitle">Add harness</h2>
          <p className="ak-modal-sub">Choose the base harness first. Instructions, tools, skills and limits are configured after creation.</p>
          <div className="ak-field">
            <div className="ak-field-k">Name</div>
            <input value={name} placeholder="Customer Support Agent" autoFocus aria-label="Harness name"
              onChange={(e) => setName(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') void submit(); }} />
            <div className="hx-add-help">Name the reusable agent configuration, not an individual task.</div>
          </div>
          <div className="ak-field">
            <div className="ak-field-k">Base harness</div>
            <div className="hx-bases" role="radiogroup" aria-label="Base harness">
              {ready.map((o) => (
                <button key={o.id} type="button" role="radio" aria-checked={base === o.id} className={'hx-base' + (base === o.id ? ' is-on' : '')}
                  onClick={() => { setBase(o.id); setModel(''); }}>
                  <HarnessLogo id={o.id} size={18} />
                  <span className="hx-base-copy"><b>{o.name}</b><small>{blurb(o.id)}</small></span>
                  <span className="hx-base-def">{oobDefaultModel(o)}</span>
                </button>
              ))}
            </div>
            <div className="hx-add-help">The base harness determines compatible models and inherited capabilities. It cannot be changed after creation.</div>
          </div>
          <div className="ak-field">
            <div className="ak-field-k">Default model</div>
            <select className="hx-add-select" aria-label="Default model" value={model || oobDefaultModel(baseObj)} onChange={(e) => setModel(e.target.value)}>
              {oobModels(baseObj).map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
          {err && <div className="ak-err" style={{ marginTop: 14 }} role="alert">Could not create the harness. {err}</div>}
        </div>
        <div className="ak-modal-foot">
          <span className="hx-add-next">Next you land in harness settings to review inherited tools and skills.</span>
          <button className="ak-secondary" type="button" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="ak-primary" type="button" onClick={() => void submit()} disabled={busy || !name.trim()}>{busy ? 'Creating…' : 'Create and configure'}</button>
        </div>
      </section>
    </div>
  );
}
