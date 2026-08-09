'use client';
import { harnessFetch } from '@/lib/hfetch';
import { Children, Suspense, useEffect, useId, useMemo, useRef, useState, isValidElement, type CSSProperties, type ReactElement, type ReactNode } from 'react';
import { SkelListItems, SkelPage } from '@/components/Skel';
import { useSearchParams } from 'next/navigation';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Mermaid } from '@/components/Mermaid';
import { OOB, oobById, oobDefaultModel, oobModels, useModelCatalog, saveCustom, listCustom, getSkillFiles, storeMcpSecret, testMcp, type CustomHarness, type OobHarness } from '@/lib/harness';
import { HarnessLogo } from '@/components/HarnessLogo';
import { streamResponse, subscribeHarnessEvents, containerFileUrl, downloadFile, loadSessionTurns, cancelSession, authHeaders, type RespFile, type SessionTurn } from '@/lib/chat';
import { getSession } from '@/lib/auth';
import { appendWorkspaceQuery } from '@/lib/workspace';
import { statusChip, timeAgo } from '@/lib/revamp-data';
// Shared Conversational Agent surface (UI Core), extracted from this page; see
// frontend-ui-core/README.md for the token/transport/slot contracts.
import { Svg, Chevron, IcPlug, IcSkill } from 'reifyui';
import { ChatMessages } from 'reifyui';
import { CodeBlock } from 'reifyui';
import { Composer } from 'reifyui';
import { withText, withReasoning, withStep, withResult, asstText } from 'reifyui';
import { createConversationStore } from 'reifyui';
import TracesMain from '@/studio/traces/TracesMain.jsx';
import { traceStore } from '@/studio/traces/store';
import { FilePreview } from '@/components/FilePreview';
import { FileTypeIcon } from '@/components/FileTypeIcon';

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

const TERMINAL_TURN = new Set(['done', 'completed', 'failed', 'error', 'cancelled', 'incomplete', 'timeout', 'max_turns']);

/** Server turns -> conversation messages (shared by hydration + busy reconciliation). */
function msgsFromTurns(turns: SessionTurn[]): { msgs: Msg[]; running: boolean } {
  const m: Msg[] = [];
  let running = false;
  for (const t of turns) {
    if (t.user || (t.user_files || []).length) {
      m.push({ role: 'user', text: t.user,
        attachments: (t.user_files || []).map((f) => ({ name: f.name })) });
    }
    const steps = (t.tools || []).map((x) => ({ name: x.name, args: x.arguments, result: x.result }));
    const blocks: Block[] = [];
    if (steps.length) blocks.push({ kind: 'tools', reasoning: '', steps });
    if (t.assistant) blocks.push({ kind: 'text', text: t.assistant });
    const st: AsstMsg['status'] = t.status === 'failed' || t.status === 'error' ? 'failed'
      : t.status === 'cancelled' ? 'cancelled'
      : (t.status === 'incomplete' || t.status === 'max_turns' || t.status === 'timeout') ? 'incomplete'
        : (t.status === 'running' || t.status === 'starting' || t.status === 'in_progress') ? 'running' : 'done';
    if (st === 'running') running = true;
    m.push({ role: 'assistant', blocks, files: t.files || [], status: st });
  }
  return { msgs: m, running };
}

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
const IcCopy = () => <Svg><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V5a2 2 0 0 1 2-2h10" /></Svg>;
const IcRetry = () => <Svg><path d="M21 12a9 9 0 1 1-3-6.7" /><path d="M21 4v5h-5" /></Svg>;
const IcPlus = () => <Svg s={18}><path d="M12 5v14M5 12h14" /></Svg>;
const IcDl = () => <Svg s={16}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><path d="M7 10l5 5 5-5" /><path d="M12 15V3" /></Svg>;
const IcTrash = () => <Svg s={15}><path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6" /></Svg>;
const FileGlyph = ({ small }: { small?: boolean }) =>
  <Svg s={small ? 13 : 18}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" /></Svg>;
// Side-panel toggle (collapse/expand the task-history rail), split-rectangle glyph.
const IcPanel = () => <Svg s={18}><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M9 4v16" /></Svg>;
const IcFolder = () => <Svg s={14}><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /></Svg>;
const IcFilePlus = () => <Svg s={17}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" /><path d="M12 12v6M9 15h6" /></Svg>;
const IcFolderPlus = () => <Svg s={17}><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><path d="M12 11v5M9.5 13.5h5" /></Svg>;
const IcUpload = () => <Svg s={17}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><path d="M7 9l5-5 5 5" /><path d="M12 4v12" /></Svg>;
const IcFolderUp = () => <Svg s={17}><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><path d="M12 16v-5.5" /><path d="M9.5 13 12 10.5 14.5 13" /></Svg>;
const IcPencil = () => <Svg s={14}><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" /></Svg>;

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

function Workbench() {
  const sp = useSearchParams();
  const [harnessId, setHarnessId] = useState(sp.get('h') || '');
  const [custom, setCustom] = useState<CustomHarness[]>([]);
  const [customLoaded, setCustomLoaded] = useState(false);
  useEffect(() => { listCustom().then((cs) => { setCustom(cs); setCustomLoaded(true); }).catch(() => setCustomLoaded(true)); }, []);
  // Default selection: the user's newest CUSTOM harness; built-in Codex only when none exist.
  // Gate on customLoaded, defaulting before the list arrives would lock onto the built-in.
  useEffect(() => { if (!harnessId && customLoaded) setHarnessId(custom[0]?.id || OOB[0].id); }, [harnessId, custom, customLoaded]);
  // Reflect the selected harness in the URL (?h=<id>) so a refresh restores the selection.
  useEffect(() => {
    if (!harnessId) return;
    const url = new URL(window.location.href);
    if (url.searchParams.get('h') !== harnessId) {
      url.searchParams.set('h', harnessId);
      window.history.replaceState(null, '', url.toString());
    }
  }, [harnessId]);

  const oob = oobById(harnessId);
  const ch = oob ? null : (custom.find((c) => c.id === harnessId) || null);
  const curName = oob?.name || ch?.name || '';
  // Deep link: /tasks?h=<harness>&sid=<session> opens that exact task. Bad ids surface a
  // visible error instead of silently landing on an empty New Task. Consumed ONCE, switching
  // harness clears it (and the URL param) so the new harness starts on a clean New Task.
  const [deepSid, setDeepSid] = useState(() => sp.get('sid') || '');
  const harnessMissing = customLoaded && !!sp.get('h') && !oob && !ch;

  // Harness selector lives in the task-list panel as a filter (finalized design, no title row).
  const harnessSelect = (
    <select className="select" aria-label="Select Harness" value={harnessId} onChange={(e) => {
      const url = new URL(window.location.href);
      if (url.searchParams.has('sid')) { url.searchParams.delete('sid'); window.history.replaceState(null, '', url.toString()); }
      setDeepSid('');
      setHarnessId(e.target.value);
    }}>
      <optgroup label="My Harnesses">
        {custom.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
      </optgroup>
      <optgroup label="System">
        {OOB.map((o) => (
          <option key={o.id} value={o.id} disabled={o.status === 'soon'}>
            {o.name}{o.status === 'soon' ? ' (soon)' : ''}
          </option>
        ))}
      </optgroup>
    </select>
  );

  return (
    <section className="view is-active" id="view-tasks">
      <div className="page tasks-page">
        {harnessMissing && (
          <div className="notice" style={{ marginBottom: 12 }}>
            <iconify-icon icon="tabler:alert-triangle"></iconify-icon>
            <div><strong>Harness not found</strong>
              The linked Harness (<code>{sp.get('h')}</code>) doesn&rsquo;t exist in this Workspace, it may have been
              deleted or belong to another Workspace. Pick a Harness from the list to continue.</div>
          </div>
        )}
        <ConfigChat key={harnessId} oob={oob} ch={ch} harnessId={harnessId}
          harnessName={curName} harnessSelect={harnessSelect} deepSid={deepSid}
          onClearDeepSid={() => setDeepSid('')}
          onSaved={() => listCustom().then(setCustom)} />
      </div>
    </section>
  );
}

// ── Session sharing (session-level only; artifacts inherit the session's share state) ────────
function ShareModal({ sid, onClose }: { sid: string; onClose: () => void }) {
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
function ConfigChat({ oob, ch, harnessId, harnessName, harnessSelect, deepSid, onClearDeepSid, onSaved }: {
  oob: OobHarness | null; ch: CustomHarness | null; harnessId: string; harnessName: string;
  harnessSelect?: React.ReactNode; deepSid?: string; onClearDeepSid?: () => void; onSaved: () => void;
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

  const [recentsOpen, setRecentsOpen] = useState(true);
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
  const [shareOpen, setShareOpen] = useState(false);
  // Deep-linked session validation: confirm the manifest exists; 404 -> visible error + New Task.
  // A 200 manifest also serves as the title/meta fallback when the session isn't in MY recents
  // (deep links can point at another member's task).
  const [deepErr, setDeepErr] = useState('');
  const [deepCard, setDeepCard] = useState<TraceCard | null>(null);
  useEffect(() => {
    if (!deepSid) return;
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
          }
        }
      })
      .catch(() => { if (alive) setDeepErr('Could not reach the server to open the linked Task.'); });
    return () => { alive = false; };
  }, [deepSid]);
  // Keep ?sid= in the URL in sync with the shown task so every task view is shareable.
  useEffect(() => {
    const url = new URL(window.location.href);
    const cur = url.searchParams.get('sid');
    const want = activeSid ?? selectedSid;
    if (want && cur !== want) { url.searchParams.set('sid', want); window.history.replaceState(null, '', url.toString()); }
    else if (!want && cur) { url.searchParams.delete('sid'); window.history.replaceState(null, '', url.toString()); }
  }, [activeSid, selectedSid]);
  // Bumped on "New Task" so the conversation fully resets even when selectedSid is already null
  // (a fresh, never-saved task), keys the Conversation to remount it clean.
  const [newTaskNonce, setNewTaskNonce] = useState(0);
  // Trace is a diagnostics TAB of the selected Task (per the IA review), not a separate surface.
  const [detailTab, setDetailTab] = useState<'conversation' | 'trace'>('conversation');
  // Narrow screens alternate between the task list and the detail pane (CSS ≤820px); desktop
  // ignores this. Narrow DEFAULTS to the detail view (list collapsed), the title-row toggle
  // expands the list; picking a task collapses it again.
  const isNarrow = () => typeof window !== 'undefined' && window.matchMedia('(max-width: 820px)').matches;
  const [mobileDetail, setMobileDetail] = useState(() => isNarrow());
  const toggleList = () => { if (isNarrow()) setMobileDetail((v) => !v); else setRecentsOpen((v) => !v); };
  // The task cards (lifted from RecentsPanel) drive the detail header's title + meta row.
  const [cards, setCards] = useState<TraceCard[]>([]);
  const backend = oob?.backend ?? (oobById(draft?.base || '')?.backend ?? null);

  const startNew = () => {
    setSelectedSid(null); setActiveSid(null); setDetailTab('conversation');
    // A New Task must be a BRAND-NEW session: kill the deep-link sid + its error so nothing
    // can rebind the fresh conversation to an old session.
    setDeepErr(''); onClearDeepSid?.();
    setNewTaskNonce((n) => n + 1); setMobileDetail(true);
  };

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
    <div className={'run-layout' + (mobileDetail ? ' m-detail' : '')}
      style={recentsOpen ? undefined : { gridTemplateColumns: 'minmax(0,1fr)' }}>
      {recentsOpen && (
        <RecentsPanel key={`r${harnessId}`} refreshNonce={recentsKey} harnessId={harnessId}
          harnessName={harnessName} selected={activeSid} onCards={setCards} harnessSelect={harnessSelect}
          onSelect={(sid) => { setSelectedSid(sid); setActiveSid(sid); setDetailTab('conversation'); setDeepErr(''); onClearDeepSid?.(); setMobileDetail(true); }}
          onNew={startNew} />
      )}
      <article className="run-detail">
        {deepErr && (
          <div className="notice" style={{ margin: '14px 18px 0' }}>
            <iconify-icon icon="tabler:alert-triangle"></iconify-icon>
            <div><strong>Task not found</strong>{deepErr}</div>
          </div>
        )}
        <div className="task-detail-shell">
          <div className="session-detail-head">
            <div className="session-detail-lead">
              <div className="session-title-row">
                <button className="wbx-panel-tgl" type="button"
                  title="Show or hide the task list"
                  aria-pressed={recentsOpen} onClick={toggleList}><IcPanel /></button>
                <h2 className="session-title-ellip" title={selCard?.title || undefined}>
                  {selCard?.title || (shownSid ? 'Task' : 'New Task')}</h2>
                {shownSid && typeof selCard?.credits === 'number' && selCard.credits > 0 && (
                  <span className="run-credits-chip" title="Credits this task has used">
                    <iconify-icon icon="tabler:coins"></iconify-icon>
                    {selCard.credits < 1 ? selCard.credits.toFixed(2) : selCard.credits.toLocaleString(undefined, { maximumFractionDigits: 1 })} cr
                  </span>
                )}
                {shownSid && (
                  <button className="wbx-panel-tgl session-share-btn" type="button" title="Share this Task"
                    onClick={() => setShareOpen(true)}>
                    <iconify-icon icon="tabler:share-2"></iconify-icon>
                  </button>
                )}
              </div>
            </div>
          </div>
          <div className="tabs" role="tablist" aria-label="Task detail">
            <button className="tab" type="button" role="tab" aria-selected={detailTab === 'conversation'}
              onClick={() => setDetailTab('conversation')}>Conversation</button>
            <button className="tab" type="button" role="tab" aria-selected={detailTab === 'trace'}
              disabled={!shownSid} onClick={() => shownSid && setDetailTab('trace')}>Trace</button>
          </div>
        </div>
        {/* Conversation stays MOUNTED while the Trace tab shows, its store writes + bus rendering
            must not be interrupted by a diagnostics peek. */}
        <div className="run-detail-fill" style={{ display: detailTab === 'conversation' ? undefined : 'none' }}>
          <Conversation key={`conv-${harnessId}-${selectedSid ?? 'new'}-${newTaskNonce}`} harnessId={harnessId} sessionId={selectedSid}
            target={{ name: harnessName, backend, model, baseId: oob?.id ?? oobById(draft?.base || '')?.id }}
            additionalHeaders={(draft?.additionalHeaders || []).filter(Boolean)}
            models={models} onModel={(m) => setModel(m)}
            recentsOpen={recentsOpen} onToggleRecents={() => setRecentsOpen((v) => !v)} showToggle={false}
            onSession={(sid) => { setActiveSid(sid); setRecentsKey((k) => k + 1); }}
            onRan={() => setRecentsKey((k) => k + 1)} />
        </div>
        {detailTab === 'trace' && <TraceView sid={shownSid} />}
      </article>
      {shareOpen && shownSid && <ShareModal sid={shownSid} onClose={() => setShareOpen(false)} />}
    </div>
  );
}

function AttachCard({ name, dataUri, onRemove }: { name: string; dataUri?: string; onRemove?: () => void }) {
  const ext = (name.split('.').pop() || '').toLowerCase();
  const isImg = /^(png|jpe?g|gif|webp|bmp|svg|avif)$/.test(ext) && !!dataUri && dataUri.startsWith('data:image');
  return (
    <div className={'wbx-attach' + (isImg ? ' img' : '')}>
      {onRemove && <button className="wbx-attach-x" title="Remove" onClick={onRemove}>×</button>}
      {isImg
        ? <img className="wbx-attach-thumb" src={dataUri} alt={name} />
        : <><span className="wbx-attach-ic"><FileTypeIcon name={name} size={26} /></span>
            <span className="wbx-attach-meta"><span className="wbx-attach-name">{name}</span>
              <span className="wbx-attach-ext">{ext.toUpperCase() || 'FILE'}</span></span></>}
    </div>
  );
}

function ModelSelect({ models, value, onChange }: { models: string[]; value: string; onChange: (m: string) => void }) {
  return (
    <div className="wbx-select-wrap block">
      <select className="wbx-select full" value={value} onChange={(e) => onChange(e.target.value)}>
        {models.map((m) => <option key={m} value={m}>{m}</option>)}
      </select>
      <span className="wbx-select-chev"><Chevron dir="down" size={15} /></span>
    </div>
  );
}

// ── Recents: this user's sessions for this harness (clickable → loads its chat history) ─────────
interface TraceCard {
  session_id: string; title?: string; status?: string; finished_at?: number;
  model?: string; event_count?: number; elapsed?: number; credits?: number;
}

// Optimistic Recents entries: a just-sent NEW task shows in the list INSTANTLY. The durable card
// only lands after session allocation + the first trace write (seconds on a cold start), so without
// this the list lags every new send. An entry drops the moment the server list contains its session
// (sid learned from response.created), or after a safety expiry if the send failed before a session
// existed. Module-level (like _runningSids) so it survives panel re-renders.
type PendingCard = { tempId: string; harness: string; title: string; at: number; sid?: string };
let _pendingCards: PendingCard[] = [];
function addPendingCard(harness: string, title: string): string {
  const tempId = 'pend_' + Math.random().toString(36).slice(2);
  _pendingCards.push({ tempId, harness, title, at: Date.now() });
  return tempId;
}
function setPendingSid(tempId: string, sid: string) {
  const p = _pendingCards.find((x) => x.tempId === tempId);
  if (p) p.sid = sid;
}
function dropPending(tempId: string) { _pendingCards = _pendingCards.filter((x) => x.tempId !== tempId); }
/** Pending entries still worth showing for this harness, given the server list; prunes the store. */
function livePending(harness: string, cards: TraceCard[] | null): PendingCard[] {
  const now = Date.now();
  _pendingCards = _pendingCards.filter((p) =>
    now - p.at < 180_000 && !(p.sid && (cards || []).some((c) => c.session_id === p.sid)));
  return _pendingCards.filter((p) => p.harness === harness);
}
function RecentsPanel({ harnessId, harnessName, selected, onSelect, onNew, onCards, harnessSelect, refreshNonce }: {
  harnessId: string; harnessName: string; selected: string | null;
  onSelect: (sid: string) => void; onNew: () => void;
  onCards?: (cards: TraceCard[]) => void; harnessSelect?: React.ReactNode; refreshNonce?: number;
}) {
  const [cards, _setCards] = useState<TraceCard[] | null>(null);
  const setCards = (v: TraceCard[] | null | ((prev: TraceCard[] | null) => TraceCard[] | null)) => {
    _setCards((prev) => (typeof v === 'function' ? v(prev) : v));
  };
  // REAL pagination over the gateway's cursor-paged /v1/traces: `cards` is the polled first
  // page (stays fresh); `tail` accumulates older pages appended by scroll-load; `cursor`
  // points past the last loaded page ('' = exhausted or not yet known).
  const [tail, setTail] = useState<TraceCard[]>([]);
  const [cursor, setCursor] = useState('');
  const [loadingMore, setLoadingMore] = useState(false);
  const merged = useMemo(() => {
    const head = cards || [];
    const seen = new Set(head.map((c) => c.session_id));
    return [...head, ...tail.filter((t) => !seen.has(t.session_id))];
  }, [cards, tail]);
  // The detail header's title derives from the loaded cards (head + tail).
  useEffect(() => { onCards?.(merged); }, [merged]); // eslint-disable-line react-hooks/exhaustive-deps

  const listQuery = () => {
    const s = getSession(); const org = s?.orgId; const member = s?.member?.email || s?.member?.id || '';
    if (!org) return null;
    const q = new URLSearchParams({ org, member, harness: harnessId, limit: '40' });
    appendWorkspaceQuery(q);
    return q;
  };
  const loadMore = () => {
    if (!cursor || loadingMore) return;
    const q = listQuery(); if (!q) return;
    q.set('cursor', cursor);
    setLoadingMore(true);
    harnessFetch(`/api/harness/v1/traces?${q.toString()}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`traces ${r.status}`))))
      .then((d) => {
        if (Array.isArray(d?.sessions)) setTail((t) => [...t, ...d.sessions]);
        setCursor(d?.cursor || '');
      })
      .catch(() => { /* keep cursor; the next scroll retries */ })
      .finally(() => setLoadingMore(false));
  };
  const onListScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    if (el.scrollTop + el.clientHeight > el.scrollHeight - 140) loadMore();
  };
  const [delTarget, setDelTarget] = useState<TraceCard | null>(null);
  const [flt, setFlt] = useState('');
  const [stFlt, setStFlt] = useState<'all' | 'working' | 'done' | 'failed'>('all');
  const [fltOpen, setFltOpen] = useState(false);
  const fltRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (fltRef.current && !fltRef.current.contains(e.target as Node)) setFltOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, []);
  const [deleting, setDeleting] = useState(false);
  // Refresh the list in place (never null it out) so it doesn't flash. Used by the 6s poll AND by
  // refreshNonce bumps (after a turn runs / a session is picked), previously the parent remounted
  // this whole panel via `key`, which blanked the list and caused the visible flash.
  // While nothing is paginated yet, the head page's cursor seeds scroll-load.
  const tailLenRef = useRef(0);
  useEffect(() => { tailLenRef.current = tail.length; }, [tail]);
  const load = () => {
    const q = listQuery();
    if (!q) return Promise.resolve();
    return harnessFetch(`/api/harness/v1/traces?${q.toString()}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`traces ${r.status}`))))
      // Only overwrite with a genuine array. A transient error / cold-start / gateway rollover must
      // NEVER blank an already-loaded list, that reads to the user as "all my sessions are gone".
      .then((d) => {
        if (Array.isArray(d?.sessions)) setCards(d.sessions);
        if (tailLenRef.current === 0) setCursor(d?.cursor || '');
      })
      .catch(() => { /* keep prior list on error */ });
  };
  useEffect(() => {
    let alive = true;
    const tick = () => {
      const q = listQuery();
      if (!q) return;
      harnessFetch(`/api/harness/v1/traces?${q.toString()}`)
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`traces ${r.status}`))))
        .then((d) => {
          if (!alive) return;
          if (Array.isArray(d?.sessions)) setCards(d.sessions);
          if (tailLenRef.current === 0) setCursor(d?.cursor || '');
        })
        .catch(() => { /* keep prior list */ });
    };
    tick(); const t = setInterval(tick, 6000); return () => { alive = false; clearInterval(t); };
  }, [harnessId]); // eslint-disable-line react-hooks/exhaustive-deps
  // Refresh-in-place when the parent signals a change (turn ran / session switched), no remount, no flash.
  const firstNonce = useRef(true);
  useEffect(() => {
    if (firstNonce.current) { firstNonce.current = false; return; }
    load();
  }, [refreshNonce]); // eslint-disable-line react-hooks/exhaustive-deps

  const confirmDelete = async () => {
    if (!delTarget) return;
    setDeleting(true);
    const sid = delTarget.session_id;
    try {
      await harnessFetch(`/api/harness/v1/traces/${encodeURIComponent(sid)}`, { method: 'DELETE' });
    } catch { /* surfaced via the list staying put */ }
    setCards((cs) => (cs || []).filter((c) => c.session_id !== sid));
    if (selected === sid) onNew();          // viewing the deleted one -> reset to a fresh task
    setDeleting(false); setDelTarget(null);
    load();
  };

  // Working = the bus says this session has a live turn (instant + accurate), OR its card status is
  // a running-ish state. The card's MANIFEST status is authoritative: once a session is terminal
  // (done/completed/failed/incomplete/…), it isn't "working" even if a stale _runningSids entry
  // lingers from a turn.started whose terminal bus event was missed.
  const _TERMINAL = new Set(['done', 'completed', 'failed', 'incomplete', 'max_turns', 'error', 'timeout', 'cancelled']);
  const isWorking = (sid: string, s?: string) =>
    !_TERMINAL.has((s || '').toLowerCase()) &&
    (_runningSids.has(sid) || s === 'running' || s === 'starting' || s === 'in_progress');
  // Design's .session-state chip: Working (green dot), Done (muted), Failed/Cancelled (amber).
  const stateChip = (sid: string, s?: string): { cls: string; label: string } => {
    if (isWorking(sid, s)) return { cls: '', label: 'Working' };
    const st = (s || '').toLowerCase();
    if (['failed', 'error', 'timeout'].includes(st)) return { cls: ' attention', label: 'Failed' };
    if (st === 'cancelled') return { cls: ' attention', label: 'Cancelled' };
    if (['incomplete', 'max_turns'].includes(st)) return { cls: ' attention', label: 'Incomplete' };
    return { cls: ' completed', label: 'Done' };
  };
  const updatedAt = (c: TraceCard) => (c.finished_at ? `Updated ${timeAgo(c.finished_at * 1000)}` : 'Updated just now');
  return (
    <div className="run-list">
      <div className="run-list-head">
        <span className="run-list-hint">Switch Harness</span>
        {harnessSelect}
        <button className="button primary run-list-new" type="button" onClick={onNew}>
          <iconify-icon icon="tabler:plus"></iconify-icon>New Task
        </button>
        <span className="list-scope">Tasks for <strong>{harnessName}</strong></span>
        <div className="run-filter-row" ref={fltRef}>
          <input className="search-input" type="search" placeholder="Filter tasks…" aria-label="Filter tasks"
            value={flt} onChange={(e) => setFlt(e.target.value)} />
          <button className={'run-flt-btn' + (stFlt !== 'all' ? ' active' : '')} type="button"
            title="Filter by status" aria-haspopup="menu" aria-expanded={fltOpen}
            onClick={() => setFltOpen((v) => !v)}>
            <iconify-icon icon="tabler:filter"></iconify-icon>
          </button>
          {fltOpen && (
            <div className="run-flt-menu" role="menu">
              {(['all', 'working', 'done', 'failed'] as const).map((k) => (
                <button key={k} role="menuitemradio" aria-checked={stFlt === k} type="button"
                  className={'run-flt-item' + (stFlt === k ? ' on' : '')}
                  onClick={() => { setStFlt(k); setFltOpen(false); }}>
                  {k === 'all' ? 'All statuses' : k[0].toUpperCase() + k.slice(1)}
                  {stFlt === k && <iconify-icon icon="tabler:check"></iconify-icon>}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="run-list-scroll" onScroll={onListScroll}>
      {(() => { const pend = livePending(harnessId, merged); const shown = merged.filter((c) => !pend.some((p) => p.sid === c.session_id))
          .filter((c) => !flt.trim() || (c.title || c.session_id).toLowerCase().includes(flt.trim().toLowerCase()))
          .filter((c) => {
            if (stFlt === 'all') return true;
            const working = isWorking(c.session_id, c.status);
            if (stFlt === 'working') return working;
            const st = (c.status || '').toLowerCase();
            const failed = ['failed', 'error', 'timeout', 'cancelled'].includes(st);
            return stFlt === 'failed' ? failed : (!working && !failed);
          });
        return (<>
        {pend.map((p) => (
          <button key={p.tempId} className="run-item task-item" type="button" aria-pressed="false">
            <span className="run-item-top"><strong>{p.title}</strong><span className="session-state">Working</span></span>
            <span>Updated just now</span>
          </button>
        ))}
        {cards === null && pend.length === 0 && <SkelListItems rows={6} />}
        {cards && shown.length === 0 && pend.length === 0 && (
          <div className="session-empty">{merged.length === 0 ? 'No Tasks yet. Send a message to start.' : 'No Tasks match this filter.'}</div>
        )}
        {shown.map((c) => { const st = stateChip(c.session_id, c.status); return (
          <button key={c.session_id} type="button" aria-pressed={selected === c.session_id}
            className={'run-item task-item' + (selected === c.session_id ? ' active' : '')}
            onClick={() => onSelect(c.session_id)}>
            <span className="run-item-top">
              <strong>{c.title || c.session_id}</strong>
              <span className={'session-state' + st.cls}>{st.label}</span>
              <span className="run-item-del" role="button" tabIndex={0} title="Delete conversation"
                onClick={(e) => { e.stopPropagation(); setDelTarget(c); }}
                onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); setDelTarget(c); } }}><IcTrash /></span>
            </span>
            <span>{updatedAt(c)}</span>
          </button>
        ); })}
        {loadingMore && <SkelListItems rows={2} />}
        </>); })()}
      </div>
      {delTarget && (
        <div className="hr-modal-scrim" onClick={() => !deleting && setDelTarget(null)}>
          <div className="hr-auth-card" style={{ width: 380 }} onClick={(e) => e.stopPropagation()}>
            <h1 style={{ fontSize: 17 }}>Delete conversation</h1>
            <p className="sub">This permanently deletes <b>{delTarget.title || 'this conversation'}</b> and its workspace. This can&apos;t be undone.</p>
            <div className="hr-card-actions" style={{ marginTop: 18 }}>
              <button className="hr-btn" disabled={deleting} onClick={() => setDelTarget(null)}>Cancel</button>
              <button className="hr-btn danger" disabled={deleting} onClick={confirmDelete}>{deleting ? 'Deleting…' : 'Delete'}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

interface ChatTarget { name: string; backend: string | null; model?: string; baseId?: string }
interface UserMsg { role: 'user'; text: string; attachments?: { name: string; dataUri?: string }[] }
interface ToolStep { name: string; args: string; result?: string; callId?: string }
// An assistant turn is an ORDERED list of blocks appended as events arrive, so tool activity is
// interleaved with prose in real time (not all tools hoisted to the top).
type Block = { kind: 'text'; text: string } | { kind: 'tools'; reasoning: string; steps: ToolStep[] };
interface AsstMsg { role: 'assistant'; blocks: Block[]; files: RespFile[]; status: 'running' | 'done' | 'failed' | 'cancelled' | 'incomplete' }
// AGENTS.md / CLAUDE.md are harness-internal instruction files the runner seeds into the workspace
// (they surface installed skills to the agent). They are never user-facing outputs, so they must
// never render as output file cards, including on older sessions that captured them before the
// gateway started excluding them.
const _INTERNAL_OUT = new Set(['AGENTS.md', 'CLAUDE.md']);
const isInternalOutput = (name?: string) =>
  !!name && (_INTERNAL_OUT.has(name) || name.startsWith('.harness/') || name.includes('/.harness/'));
type Msg = UserMsg | AsstMsg;

// The ordered-block state machine (withText/withReasoning/withStep/withResult/asstText) is
// imported from UI Core, identical semantics to the original in-file implementation.

// ── Per-conversation store (module-level, survives panel remount + tab switches) ────────────────
// The Conversation component used to hold msgs/busy/stream in component-local state, so switching
// conversations destroyed the optimistic user message AND the in-flight stream, that's why a
// message "sent" to one conversation vanished when you came back, and why only the turn that had
// already finished (reloadable from the server) ever showed. Hoisting this state here keeps every
// conversation's messages + run status alive in the background; streams write to the store by key,
// so switching is just a re-view and N concurrent turns all keep streaming.
// The store mechanics live in UI Core (createConversationStore); these thin typed wrappers keep
// every call site unchanged.
type ConvState = { msgs: Msg[]; busy: boolean; prevId: string | null; firstTurn: boolean; loaded: boolean };
const convStore = createConversationStore();
function getConvState(key: string): ConvState { return convStore.get(key) as ConvState; }
function setConvState(key: string, patch: Partial<ConvState> | ((s: ConvState) => Partial<ConvState>)): void {
  convStore.set(key, patch);
}
function useConvState(key: string): ConvState { return convStore.use(key) as ConvState; }

// ── realtime broadcast bus → conv store ──────────────────────────────────────────────────────────
// The gateway broadcasts every event of every session of a harness. We apply each event to the
// conv store keyed by the REAL session id, so any conversation renders live regardless of which tab
// (or none) started the turn, fixing "open a running session and see nothing until a hard refresh".
// `_busSuppress` holds session ids whose turn THIS tab is already rendering via its own POST stream
// (convKey === sid), so we don't double-apply deltas for those.
const _busSuppress = new Set<string>();
// Sessions with a turn currently in flight, maintained from the bus (authoritative, no trace-card
// lag) so the Recents "working" dot is accurate the instant a turn starts/ends.
const _runningSids = new Set<string>();
const _busFn: Record<string, { name: string; callId: string }> = {};
function busUpdateLast(sid: string, fn: (a: AsstMsg) => void) {
  setConvState(sid, (s) => {
    const out = s.msgs.slice();
    for (let i = out.length - 1; i >= 0; i--) {
      if (out[i].role === 'assistant') { const a = { ...(out[i] as AsstMsg) }; fn(a); out[i] = a; break; }
    }
    return { msgs: out };
  });
}
function applyBusEvent(sid: string, responseId: string, ev: Record<string, unknown>, replay = false) {
  if (!sid || _busSuppress.has(sid)) return;        // initiating tab's POST stream owns this one
  // History catch-up frames are dropped: an in-flight turn's progress-so-far is loaded from the
  // authoritative durable trace via GET /v1/sessions/{sid}/turns (msgsFromTurns). Re-applying the
  // same events off the bus would double-render (append the same text/tools twice). The bus is the
  // live-FORWARD channel only; the trace snapshot + the reconcile poll own history + repair.
  if (replay) return;
  const t = ev.type as string;
  switch (t) {
    case 'harness.turn.started': {
      // Ignore a REPLAYED start of a turn we've already finished (its response_id is our last prevId):
      // a stale/duplicate start would otherwise append a phantom "Working…" turn that never completes.
      if (responseId && getConvState(sid).prevId === responseId) return;
      setConvState(sid, (s) => {
        const last = s.msgs[s.msgs.length - 1];
        if (last && last.role === 'assistant' && (last as AsstMsg).status === 'running') return {}; // already showing it
        const user = String((ev.user_text as string) || '');
        const add: Msg[] = [];
        if (user) add.push({ role: 'user', text: user });
        add.push({ role: 'assistant', blocks: [], files: [], status: 'running' });
        return { msgs: [...s.msgs, ...add], busy: true, loaded: true };
      });
      break;
    }
    case 'response.reasoning_summary_text.delta':
      busUpdateLast(sid, (a) => { a.blocks = withReasoning(a.blocks, ev.delta as string); }); break;
    case 'response.output_item.added': {
      const item = ev.item as Record<string, unknown>;
      if (item?.type === 'function_call') _busFn[`${sid}:${ev.output_index}`] = { name: item.name as string, callId: (item.call_id as string) || '' };
      else if (item?.type === 'function_call_output') busUpdateLast(sid, (a) => { a.blocks = withResult(a.blocks, (item.call_id as string) || '', String(item.output ?? '')); });
      break;
    }
    case 'response.function_call_arguments.done': {
      const fn = _busFn[`${sid}:${ev.output_index}`] || { name: 'tool', callId: '' };
      busUpdateLast(sid, (a) => { a.blocks = withStep(a.blocks, { name: fn.name, args: (ev.arguments as string) || '', callId: fn.callId }); }); break;
    }
    case 'response.output_text.delta':
      busUpdateLast(sid, (a) => { a.blocks = withText(a.blocks, ev.delta as string); }); break;
    case 'response.output_text.annotation.added': {
      const a = ev.annotation as Record<string, unknown>;
      if (a?.type === 'container_file_citation') busUpdateLast(sid, (m) => { m.files = [...m.files, { container_id: a.container_id as string, file_id: a.file_id as string, filename: a.filename as string }]; });
      break;
    }
    case 'response.completed':
      busUpdateLast(sid, (a) => { a.status = 'done'; }); setConvState(sid, { busy: false, prevId: responseId, firstTurn: false }); break;
    case 'response.incomplete':
      busUpdateLast(sid, (a) => { a.status = 'incomplete'; }); setConvState(sid, { busy: false, prevId: responseId, firstTurn: false }); break;
    case 'response.failed': {
      // A user Stop arrives as response.failed with reason/status "cancelled", show it as
      // Cancelled, not Failed (the session card + turn record already say cancelled).
      const wasCancelled = ev.reason === 'cancelled'
        || (ev.response as Record<string, unknown> | undefined)?.status === 'cancelled';
      busUpdateLast(sid, (a) => { a.status = wasCancelled ? 'cancelled' : 'failed'; });
      setConvState(sid, { busy: false, prevId: responseId, firstTurn: false }); break;
    }
    case 'error':
      busUpdateLast(sid, (a) => { a.blocks = withText(a.blocks, '\n\nError: ' + ((ev.message as string) || 'stream error')); }); break;
  }
}
function useHarnessBus(harnessId: string, onActivity?: () => void) {
  useEffect(() => {
    if (!harnessId) return;
    const unsub = subscribeHarnessEvents(harnessId, (m) => {
      const t = (m.event as Record<string, unknown>)?.type as string;
      // track in-flight sessions (authoritative for the Recents dot) regardless of suppress/replay:
      // a replayed start still tells us the session is live (its terminal event clears it).
      if (t === 'harness.turn.started') _runningSids.add(m.session_id);
      else if (t === 'response.completed' || t === 'response.failed' || t === 'response.incomplete') _runningSids.delete(m.session_id);
      applyBusEvent(m.session_id, m.response_id, m.event || {}, Boolean(m.replay));
      if (t === 'harness.turn.started' || t === 'response.completed' || t === 'response.failed' || t === 'response.incomplete') onActivity?.();
    });
    return unsub;
  }, [harnessId]); // eslint-disable-line react-hooks/exhaustive-deps
}

function Conversation({ harnessId, sessionId, target, models, onModel, onRan, onSession, recentsOpen, onToggleRecents, showToggle = true, additionalHeaders }: {
  harnessId: string; sessionId: string | null; target: ChatTarget;
  models: string[]; onModel: (m: string) => void; onRan: () => void; onSession?: (sid: string) => void;
  recentsOpen: boolean; onToggleRecents: () => void; showToggle?: boolean; additionalHeaders?: string[];
}) {
  // Additional Headers (app-level auth): per-harness VALUES for the declared header names, kept
  // client-side only (localStorage) and attached to every Playground call, the same pass-through
  // path an external caller uses, so the Playground exercises real app auth.
  const hdrKey = 'hr.hdrs.' + harnessId;
  const [hdrVals, setHdrVals] = useState<Record<string, string>>(() => {
    try { return JSON.parse(localStorage.getItem(hdrKey) || '{}'); } catch { return {}; }
  });
  const [hdrOpen, setHdrOpen] = useState(false);
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
  // Conversation state lives in the module store (see ConvState) keyed by the session id, or a
  // stable per-mount id for a not-yet-saved new conversation, so it survives switching away/back.
  // Once the gateway allocates the real session id (onSession), a new conversation REBINDS to that
  // key: the local POST stream and the broadcast bus then write to the same entry, so prevId can't
  // split across keys (the split was one way a follow-up forked a brand-new session).
  const genId = useId();
  const [boundSid, setBoundSid] = useState<string | null>(null);
  const sidRef = useRef<string | null>(sessionId);
  // Workspace-file links inside agent replies resolve against the LIVE session id.
  const mdRenderer = useMemo(() => makeWbMarkdown(() => sessionId ?? sidRef.current, () => harnessId || null), [sessionId, harnessId]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (sessionId) sidRef.current = sessionId; }, [sessionId]);
  const convKey = sessionId ?? boundSid ?? `new-${genId}`;
  const convKeyRef = useRef(convKey);
  convKeyRef.current = convKey;
  const conv = useConvState(convKey);
  const msgs = conv.msgs;
  const setMsgs = (u: Msg[] | ((m: Msg[]) => Msg[])) =>
    setConvState(convKeyRef.current, (s) => ({ msgs: typeof u === 'function' ? (u as (m: Msg[]) => Msg[])(s.msgs) : u }));
  const [input, setInput] = useState('');
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);   // shared Composer auto-grows it (15-row cap)
  const busy = conv.busy;
  const setBusy = (b: boolean) => setConvState(convKeyRef.current, { busy: b });
  const prevId = conv.prevId;
  const setPrevId = (id: string | null) => setConvState(convKeyRef.current, { prevId: id });
  const firstTurn = conv.firstTurn;
  const setFirstTurn = (b: boolean) => setConvState(convKeyRef.current, { firstTurn: b });
  const [loading, setLoading] = useState(false);
  const [files, setFiles] = useState<{ name: string; dataUri: string }[]>([]);
  const [preview, setPreview] = useState<{ url: string; name: string } | null>(null);
  // Stop is one-shot: disabled the moment it's clicked so a slow cancel can't be spammed.
  // Re-armed whenever the busy state settles (turn ended) or a new turn starts.
  const [stopping, setStopping] = useState(false);
  useEffect(() => { setStopping(false); }, [busy]);
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

  // Load a session's chat history into the store, reconciling against the AUTHORITATIVE backend.
  // Opening a session always checks the real turn status: a session the backend reports terminal is
  // shown done with its content even if the store was left stuck at busy:true (e.g. a terminal bus
  // event was dropped on a full queue / reconnect race), which previously stranded it at "Working…"
  // until a hard refresh. A genuinely in-flight turn keeps its live placeholder for the bus to stream.
  useEffect(() => {
    const existing = getConvState(convKey);
    if (!sessionId) { if (!existing.loaded) setConvState(convKey, { loaded: true }); return; }
    // Already loaded, idle, and has content → trust it (no refetch on every open).
    if (existing.loaded && !existing.busy && existing.msgs.length) return;
    setLoading(true);
    loadSessionTurns(sessionId).then(({ turns, lastResponseId }) => {
      const { msgs: m, running } = msgsFromTurns(turns);
      const cur = getConvState(convKey);
      if (!running) {
        // Backend is terminal → authoritative. Show its content and clear any stale busy flag.
        setConvState(convKey, { msgs: m, prevId: lastResponseId, firstTurn: false, loaded: true, busy: false });
      } else if (!cur.msgs.length) {
        // In-flight with nothing local yet → load the turn's progress-so-far (the backend
        // reconstructs a running turn's partial output from its durable trace) and let the bus
        // stream new events on top. If the trace was still empty this is just the placeholder.
        setConvState(convKey, { msgs: m, prevId: lastResponseId, firstTurn: false, loaded: true, busy: true });
      } else {
        // In-flight and we already hold live msgs (switched away/back mid-turn) → keep them.
        setConvState(convKey, { loaded: true });
      }
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [convKey, sessionId]);

  // RECONCILIATION: SSE (POST stream or bus) is best-effort delivery, a reconnect gap, a
  // replica switch, or a dropped terminal event must NEVER strand the conversation at
  // "Working…". While busy, poll the authoritative turn state; the moment the backend says
  // the turn is over, rebuild from /turns and settle. This is the load-bearing guarantee;
  // streaming is just the fast path on top of it.
  useEffect(() => {
    if (!busy) return;
    const sid = sessionId ?? sidRef.current;
    if (!sid) return;
    let stop = false;
    const iv = setInterval(async () => {
      if (stop) return;
      try {
        const { turns, lastResponseId } = await loadSessionTurns(sid);
        if (stop || !turns.length) return;
        const last = turns[turns.length - 1];
        if (!TERMINAL_TURN.has(String(last.status || ''))) return;
        const { msgs: m } = msgsFromTurns(turns);
        _busSuppress.delete(sid);
        setConvState(convKeyRef.current, { msgs: m, prevId: lastResponseId, firstTurn: false, loaded: true, busy: false });
      } catch { /* transient, next tick */ }
    }, 4000);
    return () => { stop = true; clearInterval(iv); };
  }, [busy, sessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  const updateLast = (fn: (a: AsstMsg) => void) =>
    setMsgs((m) => { const out = m.slice(); for (let i = out.length - 1; i >= 0; i--) { if (out[i].role === 'assistant') { const a = { ...(out[i] as AsstMsg) }; fn(a); out[i] = a; break; } } return out; });

  async function send(textOverride?: string) {
    const text = (textOverride ?? input).trim();
    if ((!text && files.length === 0) || busy || !target.backend) return;
    const sent = files;
    // OpenAI Responses input: a string, or a user MESSAGE whose content is text + file parts.
    // (The gateway parses {role,content:[…]}, a bare content-part array reads as empty input.)
    const input_payload: string | unknown[] = sent.length
      ? [{ role: 'user', content: [
          ...(text ? [{ type: 'input_text', text }] : []),
          ...sent.map((f) => ({ type: 'input_file', filename: f.name, file_data: f.dataUri })),
        ] }]
      : text;
    setInput(''); setFiles([]); setBusy(true); setAtBottom(true);
    setMsgs((m) => [...m, { role: 'user', text, attachments: sent.map((f) => ({ name: f.name, dataUri: f.dataUri })) }, { role: 'assistant', blocks: [], files: [], status: 'running' }]);
    // NEW task (no session yet): surface it in Recents IMMEDIATELY via an optimistic entry, the
    // durable card takes seconds (session allocation + first trace write). onRan() re-renders the
    // panel now; the entry swaps for the real card as soon as the server list carries this session.
    const pendId = !sessionId ? addPendingCard(harnessId, (text || sent[0]?.name || 'New task').split('\n')[0].slice(0, 120)) : null;
    if (pendId) onRan();
    // This tab renders the turn via its own POST stream below; tell the broadcast bus to NOT also
    // apply deltas to this same session (convKey === sid) to avoid double-rendering. Other tabs /
    // other conversations still get it live from the bus.
    const knownSid = sessionId ?? sidRef.current;
    if (knownSid) _busSuppress.add(knownSid);
    try {
      const id = await streamResponse(
        // No `instructions`: the harness's configured Agent Instructions are written into the
        // workspace as AGENTS.md/CLAUDE.md (server-side, from the saved harness), so the model keeps
        // its default system prompt rather than having instructions prepended to the first message.
        // sessionHint: continuity fallback, the gateway continues this session even if prevId was
        // lost client-side (interrupted stream), instead of forking a new one.
        { input: input_payload, backend: target.backend, model: target.model || undefined, previousResponseId: prevId,
          sessionHint: knownSid, harnessId, harnessName: target.name, extraHeaders: extraHeaders() },
        { onCreated: (rid) => setPrevId(rid),
          onSession: (sid) => {
            if (pendId) setPendingSid(pendId, sid);
            // First turn of a new conversation: rebind the conv store to the real session id so all
            // future writes (this stream, the bus, follow-up turns) land on ONE key.
            if (!sessionId && !sidRef.current && sid) {
              convStore.seed(sid, { ...getConvState(convKeyRef.current) });
              _busSuppress.add(sid);
              sidRef.current = sid;
              setBoundSid(sid);
            }
            onSession?.(sid);
          },
          onReasoningDelta: (d) => updateLast((a) => { a.blocks = withReasoning(a.blocks, d); }),
          onToolCall: (name, args, callId) => updateLast((a) => { a.blocks = withStep(a.blocks, { name, args, callId }); }),
          onToolResult: (callId, output) => updateLast((a) => { a.blocks = withResult(a.blocks, callId, output); }),
          onTextDelta: (d) => updateLast((a) => { a.blocks = withText(a.blocks, d); }),
          onFile: (f) => updateLast((a) => { a.files = [...a.files, f]; }),
          onError: (msg) => updateLast((a) => { a.blocks = withText(a.blocks, '\n\nError: ' + msg); }),
          onDone: (status) => updateLast((a) => {
            a.status = status === 'completed' ? 'done'
              : (['failed', 'cancelled', 'incomplete'].includes(status) ? status as AsstMsg['status'] : 'failed');
          }) },
      );
      if (id) setPrevId(id); setFirstTurn(false);
    } catch (e) {
      // A throw here is a TRANSPORT failure (the POST stream dropped), never an agent failure, which
      // arrives via onError + onDone('failed'). If the turn already reached a session it is STILL
      // running server-side (a gateway redeploy rolling the SSE, a network blip), so painting it
      // "failed" is a lie that strands the user. Leave it running and let the finally hand rendering
      // to the auto-reconnecting broadcast bus. Only a start failure (no session yet) is a real error.
      const sk = sessionId ?? sidRef.current;
      if (!sk) {
        if (pendId) dropPending(pendId);
        updateLast((a) => { a.blocks = withText(a.blocks, '\n\nError: ' + (e instanceof Error ? e.message : String(e))); a.status = 'failed'; });
      }
    } finally {
      const sk = sessionId ?? sidRef.current;
      // If the stream ended (returned or threw) but no terminal event set the assistant status, the
      // turn is still live server-side (transport drop OR a clean drain-close mid-turn). Hand it to the
      // broadcast bus, which auto-reconnects, by releasing suppression, and KEEP the working state so
      // the indicator stands until the bus (or the on-focus reconcile) lands the true terminal status.
      const ms = getConvState(convKeyRef.current).msgs;
      const lastA = ms[ms.length - 1];
      const stillRunning = !!lastA && lastA.role === 'assistant' && (lastA as AsstMsg).status === 'running';
      if (sk && stillRunning) {
        _busSuppress.delete(sk);            // bus renders the remainder; keep busy=true (composer stays disabled)
      } else {
        if (sk) _busSuppress.delete(sk);
        setBusy(false);
      }
      onRan();
    }
  }

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
      <div className="wbx-conv-main">
      <div className="wbx-conv-bar">
        {showToggle && (
          <button className="wbx-panel-tgl" title={recentsOpen ? 'Hide task history' : 'Show task history'}
            aria-pressed={recentsOpen} onClick={onToggleRecents}><IcPanel /></button>
        )}
        <span className="wbx-conv-bar-title">{target.baseId ? <HarnessLogo id={target.baseId} size={18} /> : null}{target.name}</span>
        {declared.length > 0 && (
          <button className="wbx-hdr-gear" title="Header values for this preview"
            aria-haspopup="dialog" aria-expanded={hdrOpen}
            onClick={() => setHdrOpen(true)}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></svg>
            {declared.some((n) => !hdrVals[n]) && <span className="wbx-hdr-dot" title="Some header values are not set" />}
          </button>
        )}
      </div>
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
        {!loading && msgs.length === 0 && <div className="hr-empty" style={{ marginTop: 60 }}>Send a message to run a turn on <b>{target.name}</b>.</div>}
        {/* Shared message list (UI Core): blocks render in stream order so tool activity
            interleaves with prose. HR-specific chrome rides the override slots. */}
        {!loading && (
          <ChatMessages
            messages={msgs}
            renderMarkdown={mdRenderer}
            userExtras={(m: UserMsg) => (m.attachments && m.attachments.length > 0 ? (
              <div className="wbx-attach-row">
                {m.attachments.map((f, j) => <AttachCard key={j} name={f.name} dataUri={f.dataUri} />)}
              </div>
            ) : null)}
            assistantFooter={(m: AsstMsg, i: number) => (
              <>
                {m.files.filter((f) => !isInternalOutput(f.filename)).length > 0 && (
                  <div className="wbx-files">
                    {m.files.filter((f) => !isInternalOutput(f.filename)).map((f, j) => (
                      <div key={j} className="wbx-filecard" onClick={() => setPreview({ url: containerFileUrl(f), name: f.filename })}>
                        <span className="wbx-filecard-ic"><FileTypeIcon name={f.filename} size={32} /></span>
                        <span className="wbx-filecard-meta">
                          <span className="wbx-filecard-name">{f.filename}</span>
                          <span className="wbx-filecard-sub">{(f.filename.split('.').pop() || 'file').toUpperCase()} · output</span>
                        </span>
                        {/* Authed download (LIVE-B): a bare href carries no session and is rejected. */}
                        <button className="wbx-filecard-dl" title="Download" type="button"
                          onClick={(e) => { e.stopPropagation(); downloadFile(containerFileUrl(f), f.filename).catch(() => undefined); }}><IcDl /></button>
                        <span className="wbx-filecard-open">Preview</span>
                      </div>
                    ))}
                    {/* One-click zip of THIS turn's outputs (folder hierarchy preserved inside the
                        archive). Only worth a row when there's more than one file. */}
                    {(() => {
                      const outs = m.files.filter((f) => !isInternalOutput(f.filename));
                      if (outs.length < 2) return null;
                      const zipUrl = `/api/harness/v1/sessions/${encodeURIComponent(outs[0].container_id)}` +
                        `/files/archive?files=${encodeURIComponent(outs.map((f) => f.file_id).join(','))}`;
                      return (
                        <button className="wbx-zipall" type="button"
                          onClick={(e) => { e.stopPropagation(); downloadFile(zipUrl, 'outputs.zip').catch(() => undefined); }}>
                          <IcDl /> Download all ({outs.length}) as .zip
                        </button>
                      );
                    })()}
                  </div>
                )}
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
        value={input}
        onChange={setInput}
        onSend={() => send()}
        disabled={!target.backend || busy}
        placeholder={target.backend ? 'Write a message…' : 'This harness is coming soon'}
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
            <button className="wbx-comp-ic" title="Attach file" disabled={!target.backend || busy} onClick={() => fileRef.current?.click()}><IcPlus /></button>
            {models.length > 0 && (
              <div className="wbx-select-wrap mini">
                <select className="wbx-select mini" value={target.model || ''} onChange={(e) => onModel(e.target.value)}>
                  {models.map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
                <span className="wbx-select-chev"><Chevron dir="down" size={13} /></span>
              </div>
            )}
          </>
        )}
        renderSend={() => (busy && (sessionId ?? sidRef.current) ? (
          // A running turn can't Send anyway, the slot becomes Stop (square icon).
          <button className="hr-btn primary wbx-send wbx-send-stop" title="Stop this turn" disabled={stopping}
            onClick={() => {
              const sid = sessionId ?? sidRef.current;
              if (!sid || stopping) return;
              setStopping(true);
              // Settle from the server's verdict too, the bus event alone can be missed
              // (dropped SSE, reconnect race), which used to leave Stop looking like a no-op.
              void cancelSession(sid).then((r) => {
                const terminal = ['cancelled', 'failed', 'error', 'done', 'completed', 'incomplete', 'max_turns', 'timeout'];
                if (r.cancelled || terminal.includes(r.status)) {
                  updateLast((a) => { a.status = 'cancelled'; });
                  setBusy(false);
                } else {
                  setStopping(false);   // cancel didn't land, let the user retry
                }
              }).catch(() => setStopping(false));
            }}>
            <iconify-icon icon="tabler:player-stop-filled"></iconify-icon>
            {stopping ? 'Stopping…' : 'Stop'}
          </button>
        ) : (
          <button className="hr-btn primary wbx-send" onClick={() => send()} disabled={!target.backend || busy || (!input.trim() && files.length === 0)}>Send</button>
        ))}
      />
      </div>
      {preview && <>
        <div className="wbx-vresize" onMouseDown={onPreviewResize} title="Drag to resize" />
        <div className="wbx-preview-pane" style={{ width: previewW, flex: '0 0 auto' }}>
          <FilePreview file={preview} onClose={() => setPreview(null)} />
        </div>
      </>}
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
export default function WorkbenchPage() {
  return <Suspense fallback={<SkelPage />}><Workbench /></Suspense>;
}
