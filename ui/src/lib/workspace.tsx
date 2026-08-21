'use client';
// Workspace context, Workspaces ARE AgentStudio Spaces (product decision 2026-07-18):
// org root -> 'HarnessRouter' container Space -> one child Space per workspace, with a
// 'Default Workspace' child always present (created at subscription; the engine's
// GET /v1/hr/workspaces ensures it idempotently, which also lazily backfills old orgs).
//
// The current selection is persisted per-org in localStorage and exposed to non-React
// callers (harness.ts gwHeaders, revamp-data fetches) via getCurrentWorkspaceRef() /
// workspaceHeaders() so every gateway call is workspace-scoped without prop drilling.
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { authFetch, getSession } from '@/lib/auth';
import { SELF_HOSTED } from '@/lib/edition';

/** Where workspaces live. Hosted, the Spaces service behind the engine; self-hosted, the
 *  gateway's own store via the BFF — same requests, same shapes. The registry used to be
 *  localStorage on self-host, which meant every browser had its own workspace list while the
 *  records those workspaces scoped sat server-side: two laptops on one instance disagreed
 *  about what existed. The directory now lives with the data it scopes. */
const selfhostWsFetch = (path: string, init?: RequestInit) =>
  fetch('/api/harness' + path, { ...init, cache: 'no-store' });
const wsFetch = SELF_HOSTED ? selfhostWsFetch : authFetch;

/** One-time migration: push any localStorage-era workspaces up to the server WITH their
 *  browser-minted ids, so records stamped by them reattach. Idempotent server-side (an id
 *  that already exists is that workspace), so racing tabs are harmless. The key is left in
 *  place after a marker is set — recovery data beats tidiness until a release later. */
const LS_LEGACY = 'hr.selfhost.workspaces';
const LS_MIGRATED = 'hr.selfhost.workspaces.migrated';
async function migrateLegacyWorkspaces(): Promise<void> {
  if (!SELF_HOSTED || typeof window === 'undefined') return;
  try {
    if (localStorage.getItem(LS_MIGRATED)) return;
    const rows = JSON.parse(localStorage.getItem(LS_LEGACY) || '[]') as
      { id?: string; name?: string; description?: string }[];
    for (const w of Array.isArray(rows) ? rows : []) {
      if (!w?.id || w.id === 'default' || !w.name) continue;
      await selfhostWsFetch('/v1/hr/workspaces', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ id: w.id, name: w.name, description: w.description || '' }),
      }).catch(() => undefined);
    }
    localStorage.setItem(LS_MIGRATED, '1');
  } catch { /* private mode: nothing stored, nothing to migrate */ }
}

export interface Workspace {
  id: string;
  name: string;
  description: string;
}

const LS_CURRENT = 'hr.workspace.current.';   // + orgId -> JSON {id, def}

export interface WorkspaceRef { id: string; isDefault: boolean }

/** The active workspace for gateway scoping, readable outside React (module consumers). */
export function getCurrentWorkspaceRef(): WorkspaceRef | null {
  if (typeof window === 'undefined') return null;
  const org = getSession()?.orgId;
  if (!org) return null;
  try {
    const raw = JSON.parse(localStorage.getItem(LS_CURRENT + org) || 'null');
    if (raw?.id) return { id: String(raw.id), isDefault: !!raw.def };
  } catch { /* unset */ }
  return null;
}

function setCurrentWorkspaceRef(orgId: string, ref: WorkspaceRef): void {
  try { localStorage.setItem(LS_CURRENT + orgId, JSON.stringify({ id: ref.id, def: ref.isDefault })); } catch { /* private mode */ }
}

/** Gateway scoping headers for the active workspace ({} when none resolved yet). */
export function workspaceHeaders(): Record<string, string> {
  const ref = getCurrentWorkspaceRef();
  if (!ref) return {};
  const h: Record<string, string> = { 'x-harness-workspace': ref.id };
  if (ref.isDefault) h['x-harness-workspace-default'] = '1';
  return h;
}

/** Append the workspace filter params to a gateway list query. */
export function appendWorkspaceQuery(q: URLSearchParams): void {
  const ref = getCurrentWorkspaceRef();
  if (!ref) return;
  q.set('workspace', ref.id);
  if (ref.isDefault) q.set('workspace_default', '1');
}

interface WorkspaceCtx {
  workspaces: Workspace[];
  current: Workspace;
  defaultId: string;
  loading: boolean;
  setCurrent: (id: string) => void;
  create: (name: string, description?: string) => Promise<Workspace>;
  update: (patch: Partial<Pick<Workspace, 'name' | 'description'>>) => Promise<void>;
  refresh: () => Promise<void>;
}

const FALLBACK: Workspace = {
  id: '', name: 'Default Workspace',
  description: 'All harnesses, tasks, and keys in this organization.',
};

const Ctx = createContext<WorkspaceCtx | null>(null);

export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([FALLBACK]);
  const [defaultId, setDefaultId] = useState('');
  const [currentId, setCurrentId] = useState<string>(() => getCurrentWorkspaceRef()?.id || '');
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    const org = getSession()?.orgId;
    if (!org) { setLoading(false); return; }
    try {
      await migrateLegacyWorkspaces();
      const wanted = getCurrentWorkspaceRef()?.id || '';
      let rows: Workspace[] = [];
      let def = '';
      // A just-created Space can lag the list read (graph read-after-write); retry briefly
      // before concluding the stored selection is gone, so creating a workspace doesn't
      // snap the switcher back to Default.
      for (let attempt = 0; attempt < 3; attempt++) {
        const r = await wsFetch('/v1/hr/workspaces');
        if (!r.ok) throw new Error(String(r.status));
        const d = await r.json();
        rows = (d.workspaces || []).map((w: Record<string, string>) => ({
          id: w.id, name: w.name || 'Untitled',
          description: w.description || '',
        }));
        def = String(d.default_workspace_id || rows[0]?.id || '');
        if (!wanted || rows.some((w) => w.id === wanted)) break;
        await new Promise((res) => setTimeout(res, 1200));
      }
      setDefaultId(def);
      setWorkspaces(rows.length ? rows : [FALLBACK]);
      setCurrentId((prev) => {
        const keep = prev || wanted;
        const next = rows.some((w) => w.id === keep) ? keep : def;
        if (next) setCurrentWorkspaceRef(org, { id: next, isDefault: next === def });
        return next;
      });
    } catch { /* keep fallback, pages degrade to org-wide views */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const value = useMemo<WorkspaceCtx>(() => {
    const current = workspaces.find((w) => w.id === currentId) || workspaces[0] || FALLBACK;
    return {
      workspaces, current, defaultId, loading,
      setCurrent: (id) => {
        const org = getSession()?.orgId;
        if (!workspaces.some((w) => w.id === id)) return;
        setCurrentId(id);
        if (org) setCurrentWorkspaceRef(org, { id, isDefault: id === defaultId });
      },
      create: async (name, description = '') => {
        const r = await wsFetch('/v1/hr/workspaces', {
          method: 'POST', headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ name, description }),
        });
        if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail || `create failed (${r.status})`);
        const w = await r.json();
        // Auto-switch to the just-created workspace. Persist the selection FIRST (before refresh
        // and before any hard-nav) so it survives the graph read-after-write lag: refresh()'s retry
        // loop keys on the stored ref and waits for the new Space to appear, and a subsequent page
        // reload re-reads this same ref instead of snapping back to Default. A new workspace is
        // never the default one, so isDefault=false.
        const org = getSession()?.orgId;
        if (org) setCurrentWorkspaceRef(org, { id: w.id, isDefault: false });
        setCurrentId(w.id);
        await refresh();
        return { id: w.id, name: w.name, description: w.description || '' };
      },
      update: async (patch) => {
        if (!current.id) return;
        const r = await wsFetch(`/v1/hr/workspaces/${encodeURIComponent(current.id)}`, {
          method: 'PATCH', headers: { 'content-type': 'application/json' },
          body: JSON.stringify(patch),
        });
        if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail || `save failed (${r.status})`);
        await refresh();
      },
      refresh,
    };
  }, [workspaces, currentId, defaultId, loading, refresh]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useWorkspace(): WorkspaceCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error('useWorkspace outside WorkspaceProvider');
  return v;
}
