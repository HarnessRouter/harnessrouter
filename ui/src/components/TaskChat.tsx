'use client';
import { harnessFetch } from '@/lib/hfetch';
import { useEscape } from '@/lib/useEscape';
import { Children, Suspense, useEffect, useId, useMemo, useRef, useState, isValidElement, type CSSProperties, type ReactElement, type ReactNode } from 'react';
import { SkelListItems, SkelPage } from '@/components/Skel';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Mermaid } from '@/components/Mermaid';
import { OOB, oobById, oobDefaultModel, oobModels, useModelCatalog, modelAvailable, saveCustom, listCustom, getSkillFiles, storeMcpSecret, testMcp, type CustomHarness, type OobHarness } from '@/lib/harness';
import { HarnessLogo } from '@/components/HarnessLogo';
import { streamResponse, subscribeHarnessEvents, containerFileUrl, downloadFile, loadSessionTurns, cancelSession, authHeaders, type RespFile, type SessionTurn } from '@/lib/chat';
import { appendWorkspaceQuery, getCurrentWorkspaceRef } from '@/lib/workspace';
import { track } from '@/lib/analytics';
import { InsufficientCreditsModal } from '@/components/InsufficientCreditsModal';
import { billing } from '@/app/(app)/billing/lib';
import { statusChip, timeAgo } from '@/lib/revamp-data';
// Shared Conversational Agent surface (UI Core), extracted from this page; see
// frontend-ui-core/README.md for the token/transport/slot contracts.
import { Svg, Chevron, IcPlug, IcSkill } from 'reifyui';
import { ChatMessages } from 'reifyui';
import { Popover } from 'reifyui';
import { SELF_HOSTED } from '@/lib/edition';
import { Chip } from 'reifyui';
import { CodeBlock } from 'reifyui';
import { Composer } from 'reifyui';
import { IcPaperclip } from 'reifyui';
import { withText, withReasoning, withStep, withResult, asstText } from 'reifyui';
import {
  // The conversation controller and its module-level singletons now live in one place so Tasks and
  // Arena share a single store, one realtime bus wiring and one turn lifecycle (see lib/conversation).
  useConversationTurn, useHarnessBus, useConvState, getConvState, setConvState, convStore,
  msgsFromTurns, turnIndexOf, trackTaskFinished, isInternalOutput,
  addPendingCard, setPendingSid, dropPending, livePending,
  _busSuppress, _runningSids,
  type ChatTarget, type Msg, type UserMsg, type AsstMsg, type Block, type ToolStep, type TraceCard,
} from '@/lib/conversation';
import TracesMain from '@/studio/traces/TracesMain.jsx';
import { traceStore } from '@/studio/traces/store';
import { FilePreview } from '@/components/FilePreview';
import { FileTypeIcon } from '@/components/FileTypeIcon';
import { AttachCard, OutputFiles } from '@/components/ChatAttachments';

type Tab = 'config' | 'traces';

// react-markdown v9 override: a ```mermaid fence renders as a real diagram; every other fenced
// block renders through the shared CodeBlock (language-aware syntax highlighting, lazy
// highlight.js). We override `pre` (not `code`) because in v9 the language class lives on the
// inner <code>, so replacing the block happens at the `pre` level.
const MD_COMPONENTS = {
  pre({ children }: { children?: ReactNode }) {
    const el = Children.toArray(children).find(isValidElement) as
      ReactElement<{ className?: string; children?: React.ReactNode }> | undefined;
    const cls = el?.props?.className || '';
    const lang = /language-([\w#+-]+)/.exec(cls);
    const code = String(el?.props?.children ?? '').replace(/\n$/, '');
    if (lang && lang[1] === 'mermaid') {
      return <Mermaid code={code} />;
    }
    return <CodeBlock code={code} language={lang ? lang[1] : ''} />;
  },
};
const renderWbMarkdown = (t: string) => (
  <ReactMarkdown remarkPlugins={[remarkGfm]} components={MD_COMPONENTS}>{t}</ReactMarkdown>
);

// Agent replies reference workspace files as /workspace/... or sandbox: links, served nowhere as
// written (they 404 on the app origin). This renderer rewrites those hrefs to the authenticated
// by-path artifact route for the CURRENT session, so clicking opens the real file inline.
const WS_LINK_RE = /^(?:sandbox:)?\/?(?:workspace\/)?(.+)$/;
function isWorkspaceHref(href: string): boolean {
  if (!href || href.startsWith('#')) return false;
  if (/^[a-z][a-z0-9+.-]*:/i.test(href) && !href.startsWith('sandbox:')) return false;  // http(s), mailto…
  return href.startsWith('sandbox:') || href.startsWith('/workspace/') || href.startsWith('workspace/')
    || (!href.startsWith('/') && /\.[A-Za-z0-9]{1,8}$/.test(href));
}
function makeWbMarkdown(getSid: () => string | null, getHarness?: () => string | null) {
  const components = {
    ...MD_COMPONENTS,
    a: ({ href, children }: { href?: string; children?: React.ReactNode }) => {
      const sid = getSid();
      if (href && sid && isWorkspaceHref(href)) {
        const m = decodeURIComponent(href).match(WS_LINK_RE);
        const path = m ? m[1].replace(/^\/+/, '') : '';
        if (path) {
          const enc = path.split('/').map(encodeURIComponent).join('/');
          const h = getHarness?.();
          // canonical address: /{harness}/{session}/workspace/{path}
          const url = h ? `/${encodeURIComponent(h)}/${encodeURIComponent(sid)}/workspace/${enc}`
            : `/api/harness/a/${encodeURIComponent(sid)}/${enc}`;
          return <a href={url} target="_blank" rel="noreferrer">{children}</a>;
        }
      }
      return <a href={href} target="_blank" rel="noreferrer">{children}</a>;
    },
  };
  return (t: string) => (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>{t}</ReactMarkdown>
  );
}


/** Server turns -> conversation messages (shared by hydration + busy reconciliation). */

// Each base harness gets a stable assigned accent so the badge reads at a glance.
const BASE_TINT: Record<string, string> = {
  codex: '#0E8C6A', 'claude-code': '#C2613D', pi: '#6E55FF', hermes: '#2563EB',
};
function baseTint(id: string): string {
  if (BASE_TINT[id]) return BASE_TINT[id];
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return `hsl(${h % 360} 52% 42%)`;
}

// Svg / Chevron / IcPlug / IcSkill come from UI Core; the icons below are workbench-specific.
const IcFolder = () => <Svg s={14}><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /></Svg>;

// Tool-step icons, toolMeta, summarizeSteps and the activity timeline (ToolGroup/ToolRow)
// live in UI Core (frontend-ui-core/src/components/*), rendered via ChatMessages below.

// Drag-to-resize a pane width. fromRight: handle is on the pane's left edge (dragging right shrinks).
function useHResize(initial: number, min: number, max: number, fromRight = false) {
  const [w, setW] = useState(initial);
  const onDown = (e: React.MouseEvent) => {
    e.preventDefault();
    const sx = e.clientX, base = w, dir = fromRight ? -1 : 1;
    // While dragging, neutralize iframes/text-selection so the embedded PDF/preview can't swallow
    // mousemove/mouseup (which would strand the drag and make narrowing impossible).
    document.body.classList.add('hr-resizing');
    const move = (ev: MouseEvent) => setW(Math.min(max, Math.max(min, base + dir * (ev.clientX - sx))));
    const up = () => {
      window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up);
      document.body.style.cursor = ''; document.body.classList.remove('hr-resizing');
    };
    window.addEventListener('mousemove', move); window.addEventListener('mouseup', up); document.body.style.cursor = 'col-resize';
  };
  return [w, onDown] as const;
}

export function ShareModal({ sid, onClose }: { sid: string; onClose: () => void }) {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [err, setErr] = useState('');
  useEffect(() => {
    let alive = true;
    harnessFetch(`/api/harness/v1/sessions/${encodeURIComponent(sid)}/share`, { headers: authHeaders() })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d) => { if (alive) { setEnabled(Boolean(d.enabled)); setToken(d.token || ''); } })
      .catch(() => { if (alive) setErr('Could not load sharing state.'); });
    return () => { alive = false; };
  }, [sid]);
  const set = async (on: boolean) => {
    if (busy) return;
    setBusy(true); setErr('');
    try {
      const r = await harnessFetch(`/api/harness/v1/sessions/${encodeURIComponent(sid)}/share`, {
        method: 'POST', headers: authHeaders(), body: JSON.stringify({ enabled: on }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || String(r.status));
      setEnabled(Boolean(d.enabled)); setToken(d.token || '');
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  const link = token ? `${window.location.origin}/share/${token}` : '';
  return (
    <div className="modal-backdrop">
      <section className="modal" role="dialog" aria-modal="true" aria-labelledby="shareTitle" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div><h2 id="shareTitle">Share Task</h2><p>Anyone with the link sees a read-only view of this conversation and ALL of its artifacts. Turn sharing off at any time to revoke the link.</p></div>
          <button className="icon-button modal-close" type="button" aria-label="Close dialog" onClick={onClose}><iconify-icon icon="tabler:x"></iconify-icon></button>
        </div>
        <div className="modal-body">
          <div className="share-choice-list">
            <button type="button" className={'share-choice' + (enabled === false ? ' on' : '')} disabled={busy} onClick={() => void set(false)}>
              <iconify-icon icon="tabler:lock"></iconify-icon>
              <span><strong>Keep private</strong><span>Only members of this Workspace&rsquo;s organization have access</span></span>
              {enabled === false && <iconify-icon icon="tabler:check"></iconify-icon>}
            </button>
            <button type="button" className={'share-choice' + (enabled === true ? ' on' : '')} disabled={busy} onClick={() => void set(true)}>
              <iconify-icon icon="tabler:world"></iconify-icon>
              <span><strong>Create public link</strong><span>Anyone with the link can view the conversation and artifacts</span></span>
              {enabled === true && <iconify-icon icon="tabler:check"></iconify-icon>}
            </button>
          </div>
          {enabled && link && (
            <div className="share-link-row">
              <input readOnly value={link} onClick={(e) => (e.target as HTMLInputElement).select()} />
              <button className="button" type="button" onClick={async () => { try { await navigator.clipboard.writeText(link); setCopied(true); setTimeout(() => setCopied(false), 1400); } catch { /* blocked */ } }}>
                <iconify-icon icon={copied ? 'tabler:check' : 'tabler:copy'}></iconify-icon>{copied ? 'Copied' : 'Copy'}
              </button>
            </div>
          )}
          {err && <div className="notice"><iconify-icon icon="tabler:alert-triangle"></iconify-icon><div><strong>Sharing error</strong>{err}</div></div>}
          <div className="modal-actions"><button className="button primary" type="button" onClick={onClose}>Done</button></div>
        </div>
      </section>
    </div>
  );
}

// ── Task list (left) | Task detail (right), the design's run-layout master-detail ────────────
// The host page (Agent harnesses) owns the task list, the title row, sharing and the URL; this
// renders the conversation, its tabs and the trace, and reports the live session id, activity,
// and a deep-linked task that belongs to another harness.
/** What a conversation has taken and cost, summed over the finished turns that carry figures;
 *  `timed`/`costed` against `finished` say whether the sum is the whole story. */
export interface ConvTotals { elapsed: number; credits: number; timed: number; costed: number; finished: number }

export function ConfigChat({ oob, ch, harnessId, harnessName, deepSid, onClearDeepSid,
                     onHarness, onSaved, onActiveSid, onActivity, onTotals }: {
  oob: OobHarness | null; ch: CustomHarness | null; harnessId: string; harnessName: string;
  deepSid?: string; onClearDeepSid?: () => void;
  onHarness?: (id: string) => void; onSaved: () => void;
  onActiveSid?: (sid: string | null) => void; onActivity?: () => void;
  onTotals?: (t: ConvTotals) => void;
}) {
  const [draft, setDraft] = useState<CustomHarness | null>(ch);
  useEffect(() => setDraft(ch), [ch?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  useModelCatalog();   // server catalog is the source of truth for the picker
  const models = oobModels(oob).length ? oobModels(oob) : oobModels(oobById(draft?.base || ''));
  // The safe fallback is the BACKEND DEFAULT (gpt-5.4 / sonnet-4.6), never models[0], the lists
  // lead with the newest/priciest entries (gpt-5.6-*, fable-5) and those must never be picked
  // implicitly.
  const fallbackModel = oobDefaultModel(oob) || oobDefaultModel(oobById(draft?.base || '')) || '';
  // Resolve a stored model name against the current option list, tolerate legacy bare names
  // (sonnet-4.6) now that options carry the claude- prefix, so the saved default still applies.
  const normModel = (m: string | undefined): string => {
    if (!m) return fallbackModel || models[0] || '';
    if (models.includes(m)) return m;
    if (models.includes('claude-' + m)) return 'claude-' + m;
    const bare = m.replace(/^claude-/, '');
    if (models.includes(bare)) return bare;
    return fallbackModel || m;
  };
  const [model, setModel] = useState(oob ? (oobDefaultModel(oob) || '') : normModel(ch?.defaultModel));
  // Re-sync the active model to the harness's saved default whenever the config loads or its default
  // changes (ch arrives async after mount; without ch in deps the saved default was never applied).
  // Resolve against the BASE's model list directly so it doesn't depend on draft-render timing.
  // GUARD: skip when a session is open — an existing task's model is what IT ran with (set by the
  // taskModel effect below), and this effect fires LATE on reload (ch loads async) so without the
  // guard it clobbered the session's model back to the harness default (fable-5 → opus-4.8 on reload).
  useEffect(() => {
    if (deepSid) return;   // reloading straight into a session → its own model wins, not the default
    if (oob) { setModel(oobDefaultModel(oob) || ''); return; }
    const base0 = oobById(ch?.base || '');
    const ms = oobModels(base0);
    const dm = ch?.defaultModel || '';
    const pick = ms.includes(dm) ? dm
      : ms.includes('claude-' + dm) ? 'claude-' + dm
      : ms.includes(dm.replace(/^claude-/, '')) ? dm.replace(/^claude-/, '')
      : (oobDefaultModel(base0) || dm);
    setModel(pick);
  }, [harnessId, ch?.defaultModel, ch?.base, deepSid]); // eslint-disable-line react-hooks/exhaustive-deps

  const [recentsKey, setRecentsKey] = useState(0);
  // Realtime broadcast: subscribe ONCE per harness. Every session's live events flow into the conv
  // store by session id, so any open conversation updates live (no per-tab stream, no hard refresh).
  // Turn start/finish also refreshes Recents so its status dots track in realtime.
  useHarnessBus(harnessId, () => setRecentsKey((k) => k + 1));
  const [selectedSid, setSelectedSid] = useState<string | null>(deepSid || null);
  // activeSid = the session the conversation pane is actually showing (drives the Recents highlight).
  // Kept SEPARATE from selectedSid so a new chat reporting its own session id highlights the row
  // WITHOUT remounting the live conversation (the Conversation is keyed by selectedSid).
  const [activeSid, setActiveSid] = useState<string | null>(deepSid || null);
  useEffect(() => { onActiveSid?.(activeSid); }, [activeSid]); // eslint-disable-line react-hooks/exhaustive-deps
  // Deep-linked session validation: confirm the manifest exists; 404 -> visible error + New Task.
  // A 200 manifest also serves as the title/meta fallback when the session isn't in MY recents
  // (deep links can point at another member's task).
  const [deepErr, setDeepErr] = useState('');
  const [deepCard, setDeepCard] = useState<TraceCard | null>(null);
  useEffect(() => {
    // A session born in this tab needs no lookup: its conversation is already here, and the
    // index may not list it for a moment, which would read as a task that does not exist.
    if (!deepSid || deepSid === activeSid) return;
    let alive = true;
    harnessFetch(`/api/harness/v1/traces/${encodeURIComponent(deepSid)}`)
      .then(async (r) => {
        if (!alive) return;
        if (r.status === 404) {
          setDeepErr(`The linked Task (${deepSid.slice(0, 18)}…) doesn't exist, it may have been deleted.`);
          setSelectedSid(null); setActiveSid(null); onClearDeepSid?.();
        } else if (!r.ok) {
          setDeepErr(`Could not open the linked Task (HTTP ${r.status}). Try again or pick it from the list.`);
        } else {
          const m = await r.json().catch(() => null);
          if (alive && m?.session_id) {
            setDeepCard({ session_id: m.session_id, title: m.title, status: m.status,
              finished_at: m.finished_at, model: m.model, event_count: m.event_count, elapsed: m.elapsed, credits: m.credits });
            // A session belongs to the harness that ran it, and the trace says which one. Trusting
            // ?h= instead meant a link with a missing or stale harness rendered the transcript
            // under whatever harness happened to be selected: another vendor's name and logo on
            // top of this harness's answer, with that other harness's tasks listed beside it.
            if (m.harness_id && m.harness_id !== harnessId) onHarness?.(m.harness_id);
          }
        }
      })
      .catch(() => { if (alive) setDeepErr('Could not reach the server to open the linked Task.'); });
    return () => { alive = false; };
  }, [deepSid]); // eslint-disable-line react-hooks/exhaustive-deps
  // Bumped on "New Task" so the conversation fully resets even when selectedSid is already null
  // (a fresh, never-saved task), keys the Conversation to remount it clean.
  const [newTaskNonce, setNewTaskNonce] = useState(0);
  // Trace is a diagnostics TAB of the selected Task (per the IA review), not a separate surface.
  const [detailTab, setDetailTab] = useState<'conversation' | 'trace'>('conversation');
  // Narrow screens alternate between the task list and the detail pane (CSS ≤820px); desktop
  // ignores this. Narrow DEFAULTS to the detail view (list collapsed), the title-row toggle
  // expands the list; picking a task collapses it again.
  // The task cards (lifted from RecentsPanel) drive the detail header's title + meta row.
  const [cards, setCards] = useState<TraceCard[]>([]);
  const backend = oob?.backend ?? (oobById(draft?.base || '')?.backend ?? null);

  const startNew = () => {
    setSelectedSid(null); setActiveSid(null); setDetailTab('conversation');
    // A New Task must be a BRAND-NEW session: kill the deep-link sid + its error so nothing
    // can rebind the fresh conversation to an old session.
    setDeepErr(''); onClearDeepSid?.();
    setNewTaskNonce((n) => n + 1);
  };
  // The host owns the URL and tells this component which task to show through `deepSid`. Three
  // cases: no task means a fresh draft; a task already live here (the session this draft just
  // created, whose id the host wrote back) means nothing, so the streaming conversation is not
  // torn down; any other task means switch to it.
  useEffect(() => {
    if (!deepSid) { if (activeSid || selectedSid) startNew(); return; }
    if (deepSid === activeSid || deepSid === selectedSid) return;
    setSelectedSid(deepSid); setActiveSid(deepSid); setDetailTab('conversation'); setDeepErr('');
  }, [deepSid]); // eslint-disable-line react-hooks/exhaustive-deps

  const shownSid = activeSid ?? selectedSid;
  const selCard = shownSid
    ? cards.find((c) => c.session_id === shownSid)
      || (deepCard && deepCard.session_id === shownSid ? deepCard : null)
    : null;
  const chip = selCard ? statusChip(selCard.status) : { cls: 'healthy', label: 'Ready' };
  // An existing task's selector shows the model IT actually ran with last turn (from the trace
  // card), not the harness default, resuming a conversation must not silently switch models.
  const taskModel = selCard?.model || '';
  useEffect(() => {
    if (!shownSid || !taskModel) return;
    setModel(normModel(taskModel));
  }, [shownSid, taskModel]); // eslint-disable-line react-hooks/exhaustive-deps
  const fmtDur = (s?: number) => {
    if (!s) return '';
    const m = Math.floor(s / 60), sec = Math.round(s % 60);
    return m ? `${m}m ${sec}s` : `${sec}s`;
  };

  return (
    <div className="run-layout is-embedded">
      <article className="run-detail">
        {deepErr && (
          <div className="notice" style={{ margin: '14px 18px 0' }}>
            <iconify-icon icon="tabler:alert-triangle"></iconify-icon>
            <div><strong>Task not found</strong>{deepErr}</div>
          </div>
        )}
        <div className="task-detail-shell">
          {/* Trace is a diagnostics surface backed by the hosted tracing pipeline; a self-hosted
              box has no such pipeline, so a single tab with nothing behind it is worse than none. */}
          {SELF_HOSTED ? null : (
          <div className="tabs" role="tablist" aria-label="Task detail">
            <button className="tab" type="button" role="tab" aria-selected={detailTab === 'conversation'}
              onClick={() => setDetailTab('conversation')}>Conversation</button>
            <button className="tab" type="button" role="tab" aria-selected={detailTab === 'trace'}
              disabled={!shownSid} onClick={() => shownSid && setDetailTab('trace')}>Trace</button>
          </div>
          )}
        </div>
        {/* Conversation stays MOUNTED while the Trace tab shows, its store writes + bus rendering
            must not be interrupted by a diagnostics peek. */}
        <div className="run-detail-fill" style={{ display: detailTab === 'conversation' ? undefined : 'none' }}>
          <Conversation key={`conv-${harnessId}-${selectedSid ?? 'new'}-${newTaskNonce}`} harnessId={harnessId} sessionId={selectedSid}
            target={{ name: harnessName, backend, model, baseId: oob?.id ?? oobById(draft?.base || '')?.id,
                      runtime: (oob ?? oobById(draft?.base || ''))?.name, defaultModel: oob ? (oobDefaultModel(oob) || '') : normModel(ch?.defaultModel) }}
            additionalHeaders={(draft?.additionalHeaders || []).filter(Boolean)}
            models={models} onModel={(m) => setModel(m)}
            onSession={(sid) => { setActiveSid(sid); setRecentsKey((k) => k + 1); }}
            onTotals={onTotals}
            onRan={() => { setRecentsKey((k) => k + 1); onActivity?.(); }} />
        </div>
        {!SELF_HOSTED && detailTab === 'trace' && <TraceView sid={shownSid} />}
      </article>
    </div>
  );
}

function ModelSelect({ models, value, onChange, backend }: {
  models: string[]; value: string; onChange: (m: string) => void; backend?: string | null;
}) {
  return (
    <div className="wbx-select-wrap block">
      <select className="wbx-select full" value={value} onChange={(e) => onChange(e.target.value)}>
        {models.map((m) => (
          <option key={m} value={m} disabled={!modelAvailable(backend, m)}>
            {m}{modelAvailable(backend, m) ? '' : ' (no provider)'}
          </option>
        ))}
      </select>
      <span className="wbx-select-chev"><Chevron dir="down" size={15} /></span>
    </div>
  );
}

// ── Recents: this user's sessions for this harness (clickable → loads its chat history) ─────────

function Conversation({ harnessId, sessionId, target, models, onModel, onRan, onSession, additionalHeaders, onTotals }: {
  harnessId: string; sessionId: string | null; target: ChatTarget;
  models: string[]; onModel: (m: string) => void; onRan: () => void; onSession?: (sid: string) => void;
  additionalHeaders?: string[]; onTotals?: (t: ConvTotals) => void;
}) {
  // Additional Headers (app-level auth): per-harness VALUES for the declared header names, kept
  // client-side only (localStorage) and attached to every Playground call, the same pass-through
  // path an external caller uses, so the Playground exercises real app auth.
  const hdrKey = 'hr.hdrs.' + harnessId;
  const [hdrVals, setHdrVals] = useState<Record<string, string>>(() => {
    try { return JSON.parse(localStorage.getItem(hdrKey) || '{}'); } catch { return {}; }
  });
  const [hdrOpen, setHdrOpen] = useState(false);
  useEscape(hdrOpen, () => setHdrOpen(false));
  const declared = (additionalHeaders || []).filter(Boolean);
  const saveHdrVals = (vals: Record<string, string>) => {
    setHdrVals(vals);
    try { localStorage.setItem(hdrKey, JSON.stringify(vals)); } catch { /* private mode */ }
  };
  const extraHeaders = () => {
    const out: Record<string, string> = {};
    for (const n of declared) { const v = hdrVals[n]; if (v) out[n] = v; }
    return out;
  };
  // The turn lifecycle (store binding, history load, send, reconcile, stop) lives in the shared
  // controller so Tasks and Arena run the exact same machine; this component owns only the view
  // and its own composer state.
  const { msgs, busy, loading, stopping, outOfCredits, clearOutOfCredits,
          liveSessionId, send, stop, setMsgs, updateLast } = useConversationTurn({
    harnessId, sessionId, target, onRan, onSession, extraHeaders,
    onSendStart: () => { setInput(''); setFiles([]); setAtBottom(true); },
  });
  useEffect(() => {
    if (!onTotals) return;
    const finished = msgs.filter((m): m is AsstMsg => m.role === 'assistant' && m.status !== 'running');
    const timed = finished.filter((m) => m.elapsed != null), costed = finished.filter((m) => m.credits != null);
    onTotals({ elapsed: timed.reduce((a, m) => a + (m.elapsed || 0), 0), credits: costed.reduce((a, m) => a + (m.credits || 0), 0),
               timed: timed.length, costed: costed.length, finished: finished.length });
  }, [msgs]); // eslint-disable-line react-hooks/exhaustive-deps
  const sidRef = useRef<string | null>(sessionId);
  useEffect(() => { if (sessionId) sidRef.current = sessionId; }, [sessionId]);
  useEffect(() => { if (liveSessionId) sidRef.current = liveSessionId; }, [liveSessionId]);
  // Workspace-file links inside agent replies resolve against the LIVE session id.
  const mdRenderer = useMemo(() => makeWbMarkdown(() => sessionId ?? sidRef.current, () => harnessId || null), [sessionId, harnessId]); // eslint-disable-line react-hooks/exhaustive-deps
  const [input, setInput] = useState('');
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);   // shared Composer auto-grows it (15-row cap)
  // A fresh draft is for typing: the caret is already in the box when the page settles on it.
  const hero = !loading && msgs.length === 0 && !busy;
  useEffect(() => { if (hero) taRef.current?.focus(); }, [hero]);
  const [files, setFiles] = useState<{ name: string; dataUri: string }[]>([]);
  const [preview, setPreview] = useState<{ url: string; name: string } | null>(null);
  const [modelOpen, setModelOpen] = useState(false);
  const modelBtnRef = useRef<HTMLElement>(null);
  const [previewW, onPreviewResize] = useHResize(520, 340, 1100, true);
  const [atBottom, setAtBottom] = useState(true);
  const fileRef = useRef<HTMLInputElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const jumpToBottom = () => requestAnimationFrame(() => requestAnimationFrame(() => {
    const el = scrollRef.current; if (el) el.scrollTop = el.scrollHeight;
  }));
  // Auto-stick to the newest message only when the user is already near the bottom.
  useEffect(() => { if (atBottom) jumpToBottom(); }, [msgs, atBottom]);
  const onScroll = () => {
    const el = scrollRef.current; if (!el) return;
    setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 60);
  };
  async function pickFiles(list: FileList | null) {
    if (!list) return;
    const out: { name: string; dataUri: string }[] = [];
    for (const f of Array.from(list)) {
      const b64: string = await new Promise((res) => {
        const r = new FileReader(); r.onload = () => res(String(r.result || '').split(',')[1] || ''); r.readAsDataURL(f);
      });
      out.push({ name: f.name, dataUri: `data:${f.type || 'application/octet-stream'};base64,${b64}` });
    }
    setFiles((p) => [...p, ...out]);
  }
  // Drag-and-drop attach: dropping files anywhere on the conversation adds them to the composer.
  // dragCount tracks nested enter/leave pairs (children fire their own events) so the highlight
  // doesn't flicker off while moving across the pane.
  const [dragOver, setDragOver] = useState(false);
  const dragCount = useRef(0);
  const canAttach = !!target.backend && !busy;
  const onDragEnter = (e: React.DragEvent) => {
    if (!canAttach || !Array.from(e.dataTransfer?.types || []).includes('Files')) return;
    e.preventDefault();
    dragCount.current += 1;
    setDragOver(true);
  };
  const onDragOver = (e: React.DragEvent) => {
    if (!canAttach || !Array.from(e.dataTransfer?.types || []).includes('Files')) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
  };
  const onDragLeave = (e: React.DragEvent) => {
    if (!dragOver) return;
    e.preventDefault();
    dragCount.current = Math.max(0, dragCount.current - 1);
    if (dragCount.current === 0) setDragOver(false);
  };
  const onDrop = (e: React.DragEvent) => {
    if (!canAttach) return;
    e.preventDefault();
    dragCount.current = 0;
    setDragOver(false);
    if (e.dataTransfer?.files?.length) void pickFiles(e.dataTransfer.files);
  };

  return (
    <div className={'wbx-conv' + (preview ? ' split' : '')}
      onDragEnter={onDragEnter} onDragOver={onDragOver} onDragLeave={onDragLeave} onDrop={onDrop}>
      {dragOver && (
        <div className="wbx-droparea" aria-hidden="true">
          <div className="wbx-droparea-inner">
            <iconify-icon icon="tabler:file-upload"></iconify-icon>
            Drop files to attach
          </div>
        </div>
      )}
      {/* A fresh draft centers on what it is for: the harness, named under its base's mark, with
          the composer right under it. The first message turns it into the running thread. */}
      <div className={'wbx-conv-main' + (!loading && msgs.length === 0 && !busy ? ' is-hero' : '')}>
      {/* The bar exists for one thing: the header-values gear of a harness with declared headers.
          The host page names the harness above; nothing else belongs here. */}
      {declared.length > 0 && (
      <div className="wbx-conv-bar">
        {declared.length > 0 && (
          <button className="wbx-hdr-gear" title="Header values for this preview"
            aria-haspopup="dialog" aria-expanded={hdrOpen}
            onClick={() => setHdrOpen(true)}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></svg>
            {declared.some((n) => !hdrVals[n]) && <span className="wbx-hdr-dot" title="Some header values are not set" />}
          </button>
        )}
      </div>
      )}
      {hdrOpen && (
        <div className="hr-modal-scrim" onClick={() => setHdrOpen(false)}>
          <div className="wbx-hdr-pop" role="dialog" aria-label="Preview header values" onClick={(e) => e.stopPropagation()}>
            <div className="wbx-hdr-pop-title">Preview header values</div>
            <div className="hr-meta" style={{ marginBottom: 10 }}>
              Sent with every call from this preview, like your product would. Stored only in this browser.
            </div>
            {declared.map((n) => (
              <label key={n} style={{ display: 'block', marginBottom: 8 }}>
                <div className="wb-label" style={{ marginBottom: 3 }}>{n}</div>
                <input className="wb-input" type="password" autoComplete="off" placeholder="value"
                  value={hdrVals[n] || ''}
                  onChange={(e) => setHdrVals({ ...hdrVals, [n]: e.target.value })} />
              </label>
            ))}
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 12 }}>
              <button className="hr-btn" onClick={() => setHdrOpen(false)}>Cancel</button>
              <button className="hr-btn primary" onClick={() => { saveHdrVals(hdrVals); setHdrOpen(false); }}>Save</button>
            </div>
          </div>
        </div>
      )}
      <div className="wbx-conv-msgs" ref={scrollRef} onScroll={onScroll}>
        {loading && <div className="hr-empty" style={{ marginTop: 40 }}>Loading conversation…</div>}
        {!loading && msgs.length === 0 && (
          <div className="wbx-hero">
            <h1>{target.baseId ? <HarnessLogo id={target.baseId} size={30} /> : null}<span>{target.name}</span></h1>
          </div>
        )}
        {/* Shared message list (UI Core): blocks render in stream order so tool activity
            interleaves with prose. HR-specific chrome rides the override slots. */}
        {!loading && (
          <ChatMessages
            messages={msgs}
            roleLabel={(m: { role: string }) => (m.role === 'user' ? 'You' : target.name)}
            renderMarkdown={mdRenderer}
            // The default incomplete badge asserted "hit its step or time limit" for EVERY
            // incomplete turn, including turns that hit neither — a deploy restart landing under
            // a live turn settles as incomplete too. The badge now claims only what is true of
            // every cause; the specific cause renders below, and only when the record knows it.
            statusLabels={{
              failed: '✕ Failed. See the output above for the reason',
              cancelled: '◼ Stopped by you',
              incomplete: '◔ Stopped before finishing. Continue to resume',
            }}
            userExtras={(m: UserMsg) => (m.attachments && m.attachments.length > 0 ? (
              <div className="wbx-attach-row">
                {m.attachments.map((f, j) => <AttachCard key={j} name={f.name} dataUri={f.dataUri} />)}
              </div>
            ) : null)}
            assistantFooter={(m: AsstMsg, i: number) => (
              <>
                {m.status === 'incomplete' && m.incompleteReason && (
                  <div className="wbx-incomplete-why">
                    {m.incompleteReason === 'max_steps' ? 'It hit its step limit.'
                      : m.incompleteReason === 'timeout' ? 'It hit its time limit.'
                      : m.incompleteReason === 'interrupted'
                        ? 'The turn was interrupted before it finished, for example by a server restart. No limit was hit.'
                        : null}
                  </div>
                )}
                <OutputFiles files={m.files.filter((f) => !isInternalOutput(f.filename))}
                  onPreview={setPreview} />
                {m.status !== 'running' && asstText(m) && (
                  <div className="wbx-actrow">
                    <button className="wbx-act-ic" title={copiedIdx === i ? 'Copied' : 'Copy'}
                      onClick={async () => {
                        try { await navigator.clipboard.writeText(asstText(m)); setCopiedIdx(i); setTimeout(() => setCopiedIdx((x) => (x === i ? null : x)), 1400); } catch { /* blocked */ }
                      }}>{copiedIdx === i ? <iconify-icon icon="tabler:check"></iconify-icon> : <iconify-icon icon="tabler:copy"></iconify-icon>}</button>
                    {i === msgs.length - 1 && !busy && (
                      <>
                        {/* Continue = one more turn on the SAME session (prevId threads automatically). */}
                        <button className="wbx-act-ic" title="Continue"
                          onClick={() => void send('Continue where you left off and finish the remaining work.')}><iconify-icon icon="tabler:arrow-forward"></iconify-icon></button>
                        {/* Revise = put the prior prompt back in the composer for editing; sending it
                            continues this session rather than forking a new one. */}
                        <button className="wbx-act-ic" title="Revise"
                          onClick={() => {
                            const lu = [...msgs].reverse().find((x) => x.role === 'user');
                            if (lu && 'text' in lu && lu.text) { setInput(lu.text); taRef.current?.focus(); }
                          }}><iconify-icon icon="tabler:pencil"></iconify-icon></button>
                      </>
                    )}
                  </div>
                )}
              </>
            )}
          />
        )}
      </div>

      {!atBottom && (
        <button className="wbx-jump" title="Jump to latest" onClick={() => { setAtBottom(true); jumpToBottom(); }}>
          <Chevron dir="down" size={18} />
        </button>
      )}

      {/* Shared composer (UI Core): Enter sends, auto-grows to 15 rows; HR chrome via slots. */}
      <Composer
        inline
        value={input}
        onChange={setInput}
        onSend={() => send(input, files)}
        disabled={!target.backend || busy}
        placeholder={!target.backend ? 'This harness is coming soon' : (sessionId || msgs.length > 0) ? `Reply to ${target.name}…` : 'Describe a task…'}
        inputRef={taRef}
        attachments={files.length > 0 ? (
          <div className="wbx-attach-row in-composer">
            {files.map((f, j) => (
              <AttachCard key={j} name={f.name} dataUri={f.dataUri} onRemove={() => setFiles((p) => p.filter((_, k) => k !== j))} />
            ))}
          </div>
        ) : null}
        accessoriesLeft={(
          <>
            <input ref={fileRef} type="file" multiple hidden onChange={(e) => { pickFiles(e.target.files); e.target.value = ''; }} />
            <button className="wbx-comp-ic" type="button" title="Attach files" aria-label="Attach files" disabled={!target.backend || busy} onClick={() => fileRef.current?.click()}><IcPaperclip size={16} /></button>
          </>
        )}
        renderSend={() => (busy && (sessionId ?? sidRef.current) ? (
          // A running turn can't Send anyway, the slot becomes Stop.
          <button className="hr-btn primary wbx-send wbx-send-stop" type="button" title="Stop this turn" disabled={stopping} onClick={stop}>
            <iconify-icon icon="tabler:player-stop-filled"></iconify-icon>{stopping ? 'Stopping…' : 'Stop'}
          </button>
        ) : (
          <button className="hr-btn primary wbx-send" type="button" onClick={() => send(input, files)} disabled={!target.backend || busy || (!input.trim() && files.length === 0)}>Send</button>
        ))}
        tray={models.length > 0 ? (
          // The route chip, as in Arena: the runtime, the model for this task, a menu to change it.
          <Chip ref={modelBtnRef} slot={false} className={'ar2-chip' + (modelOpen ? ' is-menu-open' : '')}
            icon={target.baseId ? <HarnessLogo id={target.baseId} size={14} /> : undefined}
            label={(
              <>
                <span className="uic-chip-t">{target.runtime || target.name}</span>
                <span className="ar2-route-model">{target.model || 'default model'}</span>
                <iconify-icon icon="tabler:chevron-down" className="ar2-route-chev"></iconify-icon>
              </>
            )}
            onClick={() => setModelOpen((v) => !v)}
            aria-haspopup="listbox" aria-expanded={modelOpen}
            aria-label={`${target.runtime || target.name}, model ${target.model || 'default'}. Change model`} />
        ) : null}
      />
      <Popover open={modelOpen} anchorRef={modelBtnRef} onClose={() => setModelOpen(false)} width={280} minHeight={120} placement="above" className="wbx-model-pop" label="Model for this task">
        <div className="wbx-model-head">Model for this task</div>
        <div role="listbox" aria-label="Model for this task">
          {models.map((m) => {
            const ok = modelAvailable(target.backend, m);
            return (
              <button key={m} type="button" role="option" aria-selected={m === target.model} className={'wbx-model-opt' + (m === target.model ? ' is-on' : '')} disabled={!ok}
                onClick={() => { onModel(m); setModelOpen(false); }}>
                <span>{m}</span>{!ok && <span className="wbx-model-meta">no provider</span>}
              </button>
            );
          })}
        </div>
      </Popover>
      </div>
      {preview && <>
        <div className="wbx-vresize" onMouseDown={onPreviewResize} title="Drag to resize" />
        <div className="wbx-preview-pane" style={{ width: previewW, flex: '0 0 auto' }}>
          <FilePreview file={preview} onClose={() => setPreview(null)} />
        </div>
      </>}
      {outOfCredits && (
        <InsufficientCreditsModal balance={outOfCredits.balance}
          onClose={clearOutOfCredits} />
      )}
    </div>
  );
}

// ── Trace tab: the ORIGINAL Traces component (TracesMain) scoped to the selected Task, the
// session list is unnecessary here because the task list on the left already selects the session.
function TraceView({ sid }: { sid: string | null }) {
  useEffect(() => {
    traceStore.select(sid || null);
    return () => { traceStore.select(null); };
  }, [sid]);
  if (!sid) {
    return (
      <div className="run-trace-embed"><div className="session-empty">Run the task first, its trace appears here.</div></div>
    );
  }
  return (
    <div className="run-trace-embed">
      <TracesMain />
    </div>
  );
}
