'use client';
// New setup's build, as the console asks the server for it (POST /v1/harnesses/builds, then GET
// /v1/harnesses/builds/{key}): what a person writes a setup should do for their users becomes a
// harness CONFIGURATION, and the server saves the setup itself (its record, plugins, apps, tools,
// environment) under the console's build key. One key is one build, ever: asking again with the same
// key hands back that build and starts nothing, so a page load picks it up by asking again; Try again
// is a new key. The console only shows how far it has got (its step) and, once saved, opens the setup
// with its example request in the box. Nothing is saved by the console, and nothing in its place
// when the server says a build failed: the person's sentence is never saved as a setup's instructions.
//
// Auto goes to the server as "auto" and the server picks: the console never guesses a harness, a
// model or a name. The configuration on a record is read leniently: its name and standing
// instructions are the server's and nothing is drawn without them; a harness or model it leaves out
// is the one the person chose, else left empty (shown as nothing, never a guess), so one missing
// field never throws the rest away.
//
// This edition has no push for a build: its page follows it by asking for its record by long poll
// (GET /v1/harnesses/builds/{key}?after=<status>.<step>): the server answers at once when the record
// differs from the one the page last drew, else when it changes, or after a while as it is.
import { gwHeaders, type CustomHarness } from '@/lib/harness';
import { harnessFetch } from '@/lib/hfetch';

export const AUTO = 'auto';
/** The media server, offered by the composer as a plugin under this id (its own attach route). */
export const MEDIA_ID = 'media';

export interface Part { id: string; name: string }
export interface Composed {
  name: string;
  instructions: string;
  exampleTask: string;
  base: string;
  baseName: string;
  model: string;
  skills: Part[];
  plugins: Part[];
  connectionsNeeded: Part[];
  /** a demo's own skills, saved with the setup (start/replay.ts templateOf); the composer gives none */
  ownSkills?: CustomHarness['skills'];
}

/** What the person chose: the agent harness and model (their ids, or AUTO, sent as is), and the
 *  harness's name as this account offers it. */
export interface Chosen {
  base: string;
  model: string;
  baseName: string;
}

const str = (v: unknown): v is string => typeof v === 'string' && v.trim().length > 0;
const field = (c: Record<string, unknown>, ...ks: string[]): string => {
  for (const k of ks) if (str(c[k])) return (c[k] as string).trim();
  return '';
};
/** The parts as the server lists them ({id, name}), also a bare id or a part without its name. */
function parts(v: unknown): Part[] {
  if (!Array.isArray(v)) return [];
  const out: Part[] = [];
  for (const p of v) {
    const id = str(p) ? p.trim() : p && typeof p === 'object' && str((p as Part).id) ? (p as Part).id.trim() : '';
    if (!id || out.some((x) => x.id === id)) continue;
    const name = p && typeof p === 'object' && str((p as Part).name) ? (p as Part).name.trim() : id;
    out.push({ id, name });
  }
  return out;
}

/** The configuration in an answer, or null when it holds none (no name or no standing instructions). */
export function readComposed(answer: unknown, chosen: Chosen): Composed | null {
  if (!answer || typeof answer !== 'object') return null;
  const a = answer as { status?: unknown; config?: unknown };
  if (a.status !== undefined && a.status !== 'ok') return null;
  if (!a.config || typeof a.config !== 'object') return null;
  const c = a.config as Record<string, unknown>;
  // the name and the standing instructions are the configuration: without them there is nothing to draw
  const name = field(c, 'name');
  const instructions = typeof c.instructions === 'string' ? c.instructions.trim() : '';
  if (!name || !instructions) return null;
  const mine = (v: string) => (v && v !== AUTO ? v : '');
  const base = field(c, 'base') || mine(chosen.base);
  const model = field(c, 'model') || mine(chosen.model);
  const baseName = field(c, 'baseName', 'base_name') || (base && base === chosen.base && str(chosen.baseName) ? chosen.baseName : base);
  return {
    name, instructions, exampleTask: field(c, 'exampleTask', 'example_task'),
    base, baseName, model,
    skills: parts(c.skills), plugins: parts(c.plugins), connectionsNeeded: parts(c.connectionsNeeded ?? c.connections_needed),
  };
}

export type BuildStep = 'reading' | 'writing' | 'saving';
export type Attached = 'on' | 'off';
/** A build as the server keeps it (one per key). */
export interface BuildRecord {
  key: string;
  status: 'building' | 'saved' | 'failed';
  /** how far a build that is going on has got ('' when the record does not say) */
  step: BuildStep | '';
  /** the setup, once saved */
  setupId: string;
  /** what is being saved, once written (its apps drawn with its plugins) */
  config: Composed | null;
  /** each plugin's and app's attach, by its id */
  attached: Record<string, Attached>;
  /** why it failed, in the server's words ('' when it gives none); nothing was saved */
  reason: string;
}

/** A build the server refused to start, in its own words ('' when it gives none). */
export class BuildRefused extends Error {
  constructor(public reason: string) { super(reason || 'refused'); }
}

/** The record in a server answer, or null when it holds none. */
export function readRecord(raw: unknown, chosen: Chosen): BuildRecord | null {
  if (!raw || typeof raw !== 'object') return null;
  const r = raw as Record<string, unknown>;
  const status = r.status === 'building' || r.status === 'saved' || r.status === 'failed' ? r.status : null;
  if (!status) return null;
  const step = r.step === 'reading' || r.step === 'writing' || r.step === 'saving' ? r.step : '';
  const rc = r.config && typeof r.config === 'object' ? (r.config as Record<string, unknown>) : null;
  const config = rc ? readComposed({ status: 'ok', config: rc }, chosen) : null;
  if (config && rc) {
    const apps = parts(rc.apps).filter((a) => !config.plugins.some((p) => p.id === a.id));
    config.plugins = [...config.plugins, ...apps];
  }
  const attached: Record<string, Attached> = {};
  if (r.attached && typeof r.attached === 'object') {
    for (const [id, v] of Object.entries(r.attached as Record<string, unknown>)) if (v === 'on' || v === 'off') attached[id] = v;
  }
  return {
    key: str(r.key) ? r.key.trim() : '', status, step, setupId: str(r.setupId) ? r.setupId.trim() : '',
    config, attached, reason: str(r.reason) ? r.reason.trim() : '',
  };
}

/** A sentence the server refused with, never a code or an object. */
function sentence(data: unknown): string {
  const d = data && typeof data === 'object' ? (data as { detail?: unknown }).detail : null;
  const t = typeof d === 'string' ? d.trim() : '';
  return /\s/.test(t) ? t : '';
}

/** How long a long poll is given in all: longer than the server holds one (about 25 s). */
export const POLL_END_MS = 40_000;

async function call(method: 'GET' | 'POST', path: string, body?: unknown, endMs = 0): Promise<{ status: number; data: unknown }> {
  // a long poll has its own end in place of harnessFetch's 30 s
  const ctl = endMs ? new AbortController() : null;
  const t = ctl ? setTimeout(() => ctl.abort(), endMs) : null;
  try {
    const r = await harnessFetch(`/api/harness${path}`, {
      method, headers: gwHeaders(), cache: 'no-store', body: body === undefined ? undefined : JSON.stringify(body),
      ...(ctl ? { signal: ctl.signal } : {}),
    });
    return { status: r.status, data: await r.json().catch(() => null) };
  } finally { if (t) clearTimeout(t); }
}

/** Start the build under this key, or hand back the one it already is. Throws BuildRefused when the
 *  server will not start it, and an Error when it could not be asked (a page load cut the call off,
 *  the connection dropped, the server could not answer). */
export async function startServerBuild(key: string, job: string, chosen: Chosen, workspace: string): Promise<BuildRecord> {
  const { status, data } = await call('POST', '/v1/harnesses/builds', { job, base: chosen.base, model: chosen.model, workspace, key });
  if (status >= 200 && status < 300) {
    const rec = readRecord(data, chosen);
    if (rec) return rec;
    throw new Error('no record');
  }
  if (status >= 400 && status < 500 && status !== 408 && status !== 429) throw new BuildRefused(sentence(data));
  throw new Error(String(status));
}

/** Where a record stands, as the long poll names it (`after`): its status, and its step while building. */
export const standOf = (r: Pick<BuildRecord, 'status' | 'step'>): string => `${r.status}.${r.status === 'building' ? r.step : ''}`;

/** The build under this key, or null when the server has none. Throws when it could not be read.
 *  `after`: where the record the page last drew stood (standOf): the server answers once it stands
 *  anywhere else, or after a while as it is. */
export async function readServerBuild(key: string, chosen: Chosen, after = ''): Promise<BuildRecord | null> {
  const q = after ? `?after=${encodeURIComponent(after)}` : '';
  const { status, data } = await call('GET', `/v1/harnesses/builds/${encodeURIComponent(key)}${q}`, undefined, after ? POLL_END_MS : 0);
  if (status === 404) return null;
  if (status >= 200 && status < 300) {
    const rec = readRecord(data, chosen);
    if (rec) return rec;
  }
  throw new Error(String(status));
}
