// Local workspace store for the self-hosted edition.
//
// Hosted, workspaces are Spaces in a separate service. A self-hosted box has no such service —
// but workspaces are still wanted: one instance, several isolated sets of harnesses and tasks.
//
// So this is a STORE swap, not a second implementation. It answers the exact three requests the
// workspace provider makes, with the exact JSON the hosted API returns, from localStorage. The
// provider, the switcher UI, the scoping headers and every consumer stay identical — which is
// the same adapter seam the backend uses to run on SQLite instead of the hosted graph.
const KEY = 'hr.selfhost.workspaces';
const DEFAULT_ID = 'default';

export interface StoredWorkspace { id: string; name: string; description: string }

const seed = (): StoredWorkspace[] => [{
  id: DEFAULT_ID,
  name: 'Default Workspace',
  description: 'All harnesses and tasks on this instance.',
}];

function read(): StoredWorkspace[] {
  if (typeof window === 'undefined') return seed();
  try {
    const raw = JSON.parse(window.localStorage.getItem(KEY) || 'null');
    return Array.isArray(raw) && raw.length ? (raw as StoredWorkspace[]) : seed();
  } catch {
    return seed();
  }
}

function write(rows: StoredWorkspace[]): void {
  try { window.localStorage.setItem(KEY, JSON.stringify(rows)); } catch { /* private mode */ }
}

/** Turn a name into a stable id. Ids scope stored records, so they must not change when a
 *  workspace is renamed — this only runs at creation. */
function mint(name: string, taken: Set<string>): string {
  const base = name.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'workspace';
  if (!taken.has(base)) return base;
  for (let n = 2; ; n++) if (!taken.has(`${base}-${n}`)) return `${base}-${n}`;
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

/** Drop-in for authFetch over /v1/hr/workspaces, serving the same shapes from localStorage. */
export async function localWorkspaceFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const method = (init.method || 'GET').toUpperCase();
  const rows = read();

  if (method === 'GET') {
    return json({ workspaces: rows, default_workspace_id: DEFAULT_ID });
  }

  const body = (() => {
    try { return JSON.parse(String(init.body || '{}')) as Partial<StoredWorkspace>; }
    catch { return {} as Partial<StoredWorkspace>; }
  })();

  if (method === 'POST') {
    const name = String(body.name || '').trim();
    if (!name) return json({ detail: 'a workspace needs a name' }, 400);
    const created: StoredWorkspace = {
      id: mint(name, new Set(rows.map((w) => w.id))),
      name,
      description: String(body.description || ''),
    };
    write([...rows, created]);
    return json(created);
  }

  if (method === 'PATCH') {
    const id = decodeURIComponent(path.split('/').pop() || '');
    const idx = rows.findIndex((w) => w.id === id);
    if (idx < 0) return json({ detail: 'workspace not found' }, 404);
    rows[idx] = {
      ...rows[idx],
      ...(body.name !== undefined ? { name: String(body.name) } : {}),
      ...(body.description !== undefined ? { description: String(body.description) } : {}),
    };
    write(rows);
    return json(rows[idx]);
  }

  return json({ detail: `unsupported method ${method}` }, 405);
}
