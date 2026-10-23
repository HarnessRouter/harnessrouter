'use client';
// Workspace context. An instance's workspaces scope its harnesses, tasks and keys; a "Default Workspace"
// is always present (the gateway's GET /v1/hr/workspaces ensures it idempotently, which also lazily
// backfills older instances).
//
// The current selection is persisted per-org in localStorage and exposed to non-React
// callers (harness.ts gwHeaders, revamp-data fetches) via getCurrentWorkspaceRef() /
// workspaceHeaders() so every gateway call is workspace-scoped without prop drilling.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { getSession } from '@/lib/auth';

/** Workspaces live in this instance's own store, read and written through the API proxy. The
 *  registry used to be localStorage, which meant every browser had its own workspace list while the
 *  records those workspaces scoped sat server-side: two laptops on one instance disagreed about what
 *  existed. The directory now lives with the data it scopes. */
const wsFetch = (path: string, init?: RequestInit) => fetch('/api/harness' + path, { ...init, cache: 'no-store' });

/** One-time migration: push any localStorage-era workspaces up to the server WITH their
 *  browser-minted ids, so records stamped by them reattach. Idempotent server-side (an id
 *  that already exists is that workspace), so racing tabs are harmless. The key is left in
 *  place after a marker is set — recovery data beats tidiness until a release later. */
const LS_LEGACY = 'hr.selfhost.workspaces';
const LS_MIGRATED = 'hr.selfhost.workspaces.migrated';
async function migrateLegacyWorkspaces(): Promise<void> {
  if (typeof window === 'undefined') return;
  try {
    if (localStorage.getItem(LS_MIGRATED)) return;
    const rows = JSON.parse(localStorage.getItem(LS_LEGACY) || '[]') as
      { id?: string; name?: string; description?: string }[];
    for (const w of Array.isArray(rows) ? rows : []) {
      if (!w?.id || w.id === 'default' || !w.name) continue;
      await wsFetch('/v1/hr/workspaces', {
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
  /** where the workspace's users reach its product ('' when none yet); the first setup marked live sets it */
  site: string;
  /** opened only by the people and teams given it; false: everyone in the organization opens it */
  restricted?: boolean;
  /** your role here, as the gateway's list answers it : "admin" holds delete (and manages
   *  its people), "member" reads and writes. Absent where the list does not answer it. */
  role?: 'admin' | 'member';
}

const LS_CURRENT = 'hr.workspace.current.';   // + orgId -> JSON {id, def, name}

/** A workspace the gateway did not make: its own words when it gave a sentence for a person (a 402 at the plan's
 *  ceiling, a 403, a name it refused), else one plain line; `status`, so a caller can offer the plans on a 402. */
export class WorkspaceError extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}
const CREATE_FAILED = 'The workspace could not be created. Try again in a moment.';
// the web framework's own words for a status, and anything a 5xx carries: not a sentence for a person
const FRAMEWORK_WORDS = new Set(['Not Found', 'Method Not Allowed', 'Unauthorized', 'Forbidden', 'Internal Server Error']);
async function createRefusal(r: Response): Promise<WorkspaceError> {
  const d = (await r.json().catch(() => null)) as { detail?: unknown } | null;
  const said = typeof d?.detail === 'string' ? d.detail.trim()
    : d?.detail && typeof d.detail === 'object' && typeof (d.detail as { message?: unknown }).message === 'string' ? String((d.detail as { message: string }).message).trim() : '';
  return new WorkspaceError(r.status < 500 && said && !FRAMEWORK_WORDS.has(said) ? said : CREATE_FAILED, r.status);
}

/** `name`: the workspace's name when it was chosen, so a workspace that is gone from the list later can
 *  be named when the selection moves to Default (absent on a choice stored before it was kept). */
export interface WorkspaceRef { id: string; isDefault: boolean; name?: string }

/** The active workspace for gateway scoping, readable outside React (module consumers). */
export function getCurrentWorkspaceRef(): WorkspaceRef | null {
  if (typeof window === 'undefined') return null;
  const org = getSession()?.orgId;
  if (!org) return null;
  try {
    const raw = JSON.parse(localStorage.getItem(LS_CURRENT + org) || 'null');
    if (raw?.id) return { id: String(raw.id), isDefault: !!raw.def, ...(raw.name ? { name: String(raw.name) } : {}) };
  } catch { /* unset */ }
  return null;
}

function setCurrentWorkspaceRef(orgId: string, ref: WorkspaceRef): void {
  try { localStorage.setItem(LS_CURRENT + orgId, JSON.stringify({ id: ref.id, def: ref.isDefault, ...(ref.name ? { name: ref.name } : {}) })); } catch { /* private mode */ }
  writeWorkspaceCookie(ref);
}

/** The active workspace as a cookie, for pages on this origin that send no headers of their own:
 *  a kit app's requests are scoped by the API proxy from this cookie. Not HttpOnly (nothing
 *  secret in it) and host-only, like the session cookie it rides beside. */
function writeWorkspaceCookie(ref: WorkspaceRef | null): void {
  if (typeof document === 'undefined') return;
  const secure = window.location.protocol === 'https:' ? '; Secure' : '';
  document.cookie = ref
    ? `hr_workspace=${encodeURIComponent(ref.id + (ref.isDefault ? '|1' : ''))}; Path=/; Max-Age=2592000; SameSite=Lax${secure}`
    : `hr_workspace=; Path=/; Max-Age=0; SameSite=Lax${secure}`;
}

/** Make the cookie say what localStorage says, for a choice made before the cookie existed. */
export function syncWorkspaceCookie(): void {
  writeWorkspaceCookie(getCurrentWorkspaceRef());
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
  /** the workspaces the gateway listed; empty until it has answered */
  workspaces: Workspace[];
  /** The current workspace, once the list has answered. Until then, and while the list cannot be read,
   *  it is UNKNOWN: no id and no name, never a placeholder that reads as a real workspace (`known` says
   *  which). The redesign's frame draws no page until it is known; the old console's pages read the
   *  empty name as nothing to show. */
  current: Workspace;
  /** `current` is a workspace from the list the gateway answered */
  known: boolean;
  defaultId: string;
  loading: boolean;
  /** the list could not be read and the current workspace is not known from an earlier read in this
   *  tab: nothing may stand in for it (the redesign shows an error with Try again) */
  failed: boolean;
  /** the chosen workspace is not in the list the gateway answered (no longer reachable): the selection
   *  moved to Default, and that is said; `name` is the gone workspace's, '' when it was never kept */
  lost: { name: string } | null;
  clearLost: () => void;
  setCurrent: (id: string) => void;
  create: (name: string, description?: string) => Promise<Workspace>;
  update: (patch: Partial<Pick<Workspace, 'name' | 'description' | 'site'>>) => Promise<void>;
  refresh: () => Promise<void>;
}

/** The current workspace while it is not known: nothing to show, nothing to scope by. */
const UNKNOWN: Workspace = Object.freeze({ id: '', name: '', description: '', site: '' });

/** One read of the list. The gateway always names its Default Workspace and lists it (it is never
 *  restricted), so an answer without it, or one that is not the list, is a failed read. */
async function readList(): Promise<{ rows: Workspace[]; def: string }> {
  const r = await wsFetch('/v1/hr/workspaces');
  if (!r.ok) throw new Error(String(r.status));
  const d = await r.json() as { workspaces?: unknown; default_workspace_id?: unknown } | null;
  if (!d || !Array.isArray(d.workspaces) || typeof d.default_workspace_id !== 'string' || !d.default_workspace_id) {
    throw new Error('unreadable list');
  }
  const def = d.default_workspace_id;
  const rows: Workspace[] = (d.workspaces as Record<string, unknown>[]).map((w) => ({
    id: String(w.id || ''), name: String(w.name || '') || 'Untitled',
    description: String(w.description || ''), site: String(w.site || ''), restricted: w.restricted === true,
    ...(w.role === 'admin' || w.role === 'member' ? { role: w.role } : {}),
  }));
  if (!rows.some((w) => w.id === def)) throw new Error('the list does not name its Default Workspace');
  return { rows, def };
}

const Ctx = createContext<WorkspaceCtx | null>(null);

export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [defaultId, setDefaultId] = useState('');
  const [currentId, setCurrentId] = useState<string>(() => getCurrentWorkspaceRef()?.id || '');
  const [loading, setLoading] = useState(true);
  const [readFailed, setReadFailed] = useState(false);   // the last read of the list failed
  const [lost, setLost] = useState<{ name: string } | null>(null);
  const known = useRef<Workspace[] | null>(null);    // the last list the gateway answered in this tab

  const refresh = useCallback(async () => {
    const org = getSession()?.orgId;
    if (!org) { setLoading(false); return; }
    try {
      await migrateLegacyWorkspaces();
      const stored = getCurrentWorkspaceRef();
      const wanted = stored?.id || '';
      // A just-created Space can lag the list read (graph read-after-write); retry briefly
      // before concluding the stored selection is gone, so creating a workspace doesn't
      // snap the switcher back to Default.
      let { rows, def } = await readList();
      for (let attempt = 1; attempt < 3 && wanted && !rows.some((w) => w.id === wanted); attempt++) {
        await new Promise((res) => setTimeout(res, 1200));
        ({ rows, def } = await readList());
      }
      // the chosen workspace is gone from the gateway's list: say which one, by the name it had
      if (wanted && !rows.some((w) => w.id === wanted)) {
        setLost({ name: stored?.name || known.current?.find((w) => w.id === wanted)?.name || '' });
      }
      known.current = rows;
      setReadFailed(false);
      setDefaultId(def);
      setWorkspaces(rows);
      setCurrentId((prev) => {
        const keep = prev || wanted;
        const next = rows.some((w) => w.id === keep) ? keep : def;
        const name = rows.find((w) => w.id === next)?.name || '';
        if (next) setCurrentWorkspaceRef(org, { id: next, isDefault: next === def, name });
        return next;
      });
    } catch {
      // Nothing stands in for the list. A list read before in this tab still stands, and with it the
      // current workspace when it is in it; otherwise the current workspace is not known, and `failed`.
      setReadFailed(true);
    }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const value = useMemo<WorkspaceCtx>(() => {
    const found = workspaces.find((w) => w.id === currentId);
    const current = found || UNKNOWN;
    return {
      workspaces, current, known: !!found, defaultId, loading, failed: readFailed && !found, lost,
      clearLost: () => setLost(null),
      setCurrent: (id) => {
        const org = getSession()?.orgId;
        const w = workspaces.find((x) => x.id === id);
        if (!w) return;
        setCurrentId(id);
        if (org) setCurrentWorkspaceRef(org, { id, isDefault: id === defaultId, name: w.name });
      },
      create: async (name, description = '') => {
        const r = await wsFetch('/v1/hr/workspaces', {
          method: 'POST', headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ name, description }),
        });
        if (!r.ok) throw await createRefusal(r);
        const w = await r.json();
        // Auto-switch to the just-created workspace. Persist the selection FIRST (before refresh
        // and before any hard-nav) so it survives the graph read-after-write lag: refresh()'s retry
        // loop keys on the stored ref and waits for the new Space to appear, and a subsequent page
        // reload re-reads this same ref instead of snapping back to Default. A new workspace is
        // never the default one, so isDefault=false.
        // The server's answer to the create is the workspace, so it is in the list (and current, known)
        // from here, while the list read catches up with it.
        const made: Workspace = { id: String(w.id || ''), name: String(w.name || name), description: String(w.description || ''), site: '' };
        const org = getSession()?.orgId;
        if (org) setCurrentWorkspaceRef(org, { id: made.id, isDefault: false, name: made.name });
        if (made.id) setWorkspaces((l) => (l.some((x) => x.id === made.id) ? l : [...l, made]));
        setCurrentId(made.id);
        await refresh();
        return made;
      },
      update: async (patch) => {
        // never a silent "saved" for a workspace that is not known
        if (!found) throw new Error('Your workspaces could not be read just now. Try again in a moment.');
        const r = await wsFetch(`/v1/hr/workspaces/${encodeURIComponent(current.id)}`, {
          method: 'PATCH', headers: { 'content-type': 'application/json' },
          body: JSON.stringify(patch),
        });
        if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail || `save failed (${r.status})`);
        await refresh();
      },
      refresh,
    };
  }, [workspaces, currentId, defaultId, loading, readFailed, lost, refresh]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useWorkspace(): WorkspaceCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error('useWorkspace outside WorkspaceProvider');
  return v;
}
