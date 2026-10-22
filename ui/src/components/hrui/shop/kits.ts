'use client';
// The starter kits as the Shop shows them (docs/uxuidesign/console-79, views `harbor` and `kit`).
// Every fact here is read from the server's kit catalog (GET /v1/kits): the kit's own manifest,
// what this workspace has launched, and which runtimes this organization can actually serve.
// Nothing about a kit is typed into the console.
import { authHeaders } from '@/lib/chat';
import { harnessFetch } from '@/lib/hfetch';
import { getSession } from '@/lib/auth';
import { syncWorkspaceCookie } from '@/lib/workspace';
import { PARTS, SUBS, type States, type Tower } from '../tower';

export interface Choice { base: string; model: string; baseLabel: string; available: boolean; recommended: boolean }
export interface Kit {
  id: string; title: string; tagline: string; description: string;
  icon: string; accent: string; route: string;
  /** the kit's own mark, served beside its app; empty when it ships none */
  iconUrl: string;
  launched: boolean; harnessId: string | null;
  skills: string[];
  runningOn: { base: string; model: string } | null;
  choices: Choice[];
  /** present when the kit reads a database: declaring it is the requirement */
  database?: { engines: string[] };
}
export interface Base { id: string; label: string; models: { id: string; available: boolean }[] }

export async function fetchKits(): Promise<Kit[]> {
  const r = await harnessFetch('/api/harness/v1/kits', { headers: authHeaders(), cache: 'no-store' });
  if (!r.ok) throw new Error(String(r.status));
  const d = await r.json().catch(() => null);
  return Array.isArray(d?.kits) ? (d.kits as Kit[]) : [];
}

/** The agent harnesses and models this organization can run, for choosing another pairing. A read
 *  that fails throws: it is never "nothing can run". */
export async function fetchKitBases(): Promise<Base[]> {
  const r = await harnessFetch('/api/harness/v1/bases', { headers: authHeaders(), cache: 'no-store' });
  if (!r.ok) throw new Error(String(r.status));
  const d = await r.json();
  if (!Array.isArray(d?.bases)) throw new Error('bases');
  return d.bases as Base[];
}

/** What the kit runs on, as the card says it. A LAUNCHED kit reports what its setup really runs
 *  (the person may have chosen otherwise at launch, or changed it since), or nothing when that is not
 *  known; never the suggestion in its place. A kit not launched yet shows the pairing it suggests: the
 *  one this organization can run, else the kit's first choice. */
export function runtimeOf(kit: Kit, bases?: Base[] | null): { base: string; label: string; model: string; suggested: boolean } | null {
  if (kit.launched) {
    const b = kit.runningOn?.base;
    if (!b) return null;
    const label = kit.choices?.find((x) => x.base === b)?.baseLabel || bases?.find((x) => x.id === b)?.label || b;
    return { base: b, label, model: kit.runningOn?.model || '', suggested: false };
  }
  const c = kit.choices?.find((x) => x.recommended) || kit.choices?.[0];
  return c ? { base: c.base, label: c.baseLabel || c.base, model: c.model, suggested: true } : null;
}

/** What to call each kind of database: short on a card, in full where one is chosen. */
const ENGINE_SHORT: Record<string, string> = { postgres: 'PostgreSQL', mysql: 'MySQL' };
export const ENGINE_LABEL: Record<string, string> = { postgres: 'PostgreSQL', mysql: 'MySQL / MariaDB' };
export const ENGINE_EXAMPLE: Record<string, string> = {
  postgres: 'postgresql://user:password@host:5432/database',
  mysql: 'mysql://user:password@host:3306/database',
};

/** The kit's parts beyond its runtime, as the design's chips: [kind, value]. */
export function partsOf(kit: Kit): [string, string][] {
  const out: [string, string][] = (kit.skills || []).map((s) => ['skill', s]);
  if (kit.database) out.push(['database', (kit.database.engines || []).map((e) => ENGINE_SHORT[e] || e).join(' · ')]);
  return out;
}

/** The kit's setup as a brick tower (the design's staticComp): what a setup made from it has, with
 *  nothing connected yet. Its parts are the kit's own: skills, and the tool that reads a database. */
export function kitTower(kit: Kit, rt: { label: string; model: string } | null): Tower {
  const st: States = {};
  ['b-runtime', 'model', 'task', 'backend'].forEach((k) => { st[k] = 'built'; });
  st.product = 'empty'; st.live = 'empty';
  SUBS.forEach(([k]) => { st[k] = 'built'; });
  const parts = { skill: (kit.skills || []).length, plugin: 0, mcp: kit.database ? 1 : 0, env: 0 };
  PARTS.forEach(([k]) => { st[k] = parts[k] > 0 ? 'built' : 'empty'; });
  return { harness: rt?.label || '', model: rt?.model || '', parts, st };
}

/** A kit app is a page on this origin with no bearer of its own: it rides the console's HttpOnly
 *  session cookie and the active-workspace cookie beside it. Both are made current here. */
export async function ensureKitSession(): Promise<void> {
  syncWorkspaceCookie();
  const token = getSession()?.token;
  if (!token) return;
  try {
    await fetch('/api/session', { method: 'POST', headers: { authorization: `Bearer ${token}` }, cache: 'no-store' });
  } catch { /* the app's own requests will say so */ }
}

export interface LaunchBody { base?: string; model?: string; database?: { engine: string; connectionString: string; sampleRows: boolean } }
export interface Launched {
  harnessId: string; route: string; created: boolean;
  /** what the kit's setup runs on, from the launch's own answer (its setup's record); null when the
   *  answer carries none */
  runningOn: { base: string; model: string } | null;
}

export class KitError extends Error {
  constructor(public code: string) { super(code); }
}

/** Provision the kit's setup in this workspace, or hand back the one it already has. Idempotent on
 *  the server; it is also where a launched kit picks up what its kit definition changed since. A
 *  connection string is sent only when one was typed, and held nowhere but this request. */
export async function launchKit(kitId: string, body: LaunchBody = {}): Promise<Launched> {
  await ensureKitSession();
  const cs = body.database?.connectionString.trim();
  const r = await harnessFetch(`/api/harness/v1/kits/${encodeURIComponent(kitId)}/launch`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({
      ...(body.base ? { base: body.base, model: body.model || '' } : {}),
      ...(cs && body.database ? { database: { engine: body.database.engine, connection_string: cs, sample_rows: body.database.sampleRows } } : {}),
    }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => null);
    throw new KitError(String(d?.error?.code || r.status));
  }
  const d = await r.json();
  const h = d.harness && typeof d.harness === 'object' ? d.harness as { base?: unknown; defaultModel?: unknown } : null;
  return {
    harnessId: String(d.harnessId || ''), route: String(d.route || ''), created: !!d.created,
    runningOn: h && h.base ? { base: String(h.base), model: String(h.defaultModel || '') } : null,
  };
}

/** A failed launch in plain words: what to do next, never what was sent. */
export function launchError(e: unknown, kit: Kit, reconnect: boolean): string {
  const code = e instanceof KitError ? e.code : '';
  switch (code) {
    case 'connection_required': return 'This kit reads a database. Add its connection string first.';
    case 'invalid_connection_string': return 'That connection string could not be read. Check it and try again.';
    case 'unreachable_host': return 'That database is on a private address, so it cannot be reached from here.';
    case 'model_unavailable': return 'Nothing you have connected can run that model. Choose another one.';
    case 'invalid_base': return 'That agent harness is not available. Choose another one.';
    case 'kit_not_found': return 'This kit is not available right now.';
    default: return reconnect ? 'The database could not be connected just now. Try again.' : `${kit.title} could not be set up just now. Try again.`;
  }
}

/** The app's address as the address bar shows it ("kits/dashboard"). */
export const appPath = (kit: Kit) => (kit.route || `/kits/${kit.id}`).replace(/^\/+/, '');
export const appHref = (kit: Kit) => kit.route || `/kits/${kit.id}`;
