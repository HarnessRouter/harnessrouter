// Extensions › Environments: the rules the environment sheet follows, apart from its drawing, so they
// can be tested on their own. Everything shown comes from the service (lib/environments.ts): the
// declared packages, what the active build installed, the builds and their versions. Nothing here
// estimates or invents a value; a value the service has not given is left out.
import type { Environment, EnvironmentFileEntry, EnvironmentVersion, Manager, PackageCheck } from '@/lib/environments';

export const MANAGERS: Manager[] = ['pip', 'npm', 'apt'];
export const SPEC_HINT: Record<Manager, string> = { pip: 'name==1.0', npm: 'name@1.0', apt: 'name' };
/** The service keeps at most this many declared packages per manager and drops the rest unsaid. */
export const MAX_PER_MANAGER = 200;
/** The one shape of spec the service keeps (the gateway's _ENV_SPEC_RE); anything else it drops. */
const SPEC_RE = /^@?[A-Za-z0-9][A-Za-z0-9._/+-]{0,99}(?:(?:==|>=|<=|~=|!=|@|=)[A-Za-z0-9._*+^~<>-]{0,60})?$/;

/** The parts of a spec as a row shows them: the name, and the version when one was given (the
 *  service's own split, _env_spec_parts). */
export function specParts(spec: string, m: Manager): { name: string; version: string } {
  if (m === 'npm') { const i = spec.lastIndexOf('@'); return i > 0 ? { name: spec.slice(0, i), version: spec.slice(i + 1) } : { name: spec, version: '' }; }
  for (const sep of ['==', '>=', '<=', '~=', '!=', '=']) {
    const i = spec.indexOf(sep);
    if (i > 0) return { name: spec.slice(0, i), version: (sep === '==' || sep === '=' ? '' : sep) + spec.slice(i + sep.length) };
  }
  return { name: spec, version: '' };
}

/** Before the registry is asked: a spec the service would not keep is refused where it is typed. */
export function specProblem(spec: string, m: Manager, list: string[]): string {
  const t = spec.trim();
  if (!t) return 'Type a package name.';
  if (!SPEC_RE.test(t)) return `Write it as ${SPEC_HINT[m]}${m === 'apt' ? '' : ', or just the name for the latest'}.`;
  const name = specParts(t, m).name.toLowerCase();
  if (list.length >= MAX_PER_MANAGER && !list.some((x) => specParts(x, m).name.toLowerCase() === name)) {
    return `An environment holds at most ${MAX_PER_MANAGER} ${m} packages.`;
  }
  return '';
}

export type AddPlan =
  | { ok: false; error: string }
  | { ok: true; next: string[]; key: string; version: string; note: string };

/** What Add does once the registry answered, the old environment page's rule: a name the registry
 *  does not have, or a pin that was never published, is refused with the registry's own answer; when
 *  the registry could not be asked, the package is added anyway and the build is the check. A name
 *  already in the list is replaced by the new spec. The version the registry reported (the pin, else
 *  the latest) is what the row shows until a build installs it. */
export function planAdd(list: string[], m: Manager, spec: string, c: PackageCheck): AddPlan {
  const t = spec.trim();
  const name = specParts(t, m).name;
  if (c.exists === false || (c.exists && c.error)) return { ok: false, error: c.error || `${c.name || name} was not found.` };
  const next = [...list.filter((x) => specParts(x, m).name.toLowerCase() !== name.toLowerCase()), t];
  return { ok: true, next, key: `${m}:${name.toLowerCase()}`, version: c.version || c.latest || '', note: c.error ? `${c.error} It was added; the build will check it.` : '' };
}

/** What a declared package's row says: the version the active build installed, else that the
 *  running build is installing it, else when it will be installed, with the version the registry
 *  reported on Add (or the pin typed). `saved` is whether the service already holds the spec. */
export function pkgRow(env: Pick<Environment, 'packages' | 'status'>, m: Manager, spec: string, resolved: Record<string, string>, saved: boolean): { name: string; text: string; note: string } {
  const p = specParts(spec, m);
  const installed = env.packages.find((x) => x.manager === m && x.name.toLowerCase() === p.name.toLowerCase())?.version || '';
  const range = /^[<>=~^!*]/.test(p.version);
  if (saved && installed && (!p.version || range || p.version === installed)) return { name: p.name, text: installed, note: '' };
  const known = p.version || resolved[`${m}:${p.name.toLowerCase()}`] || '';
  if (!saved) return { name: p.name, text: known || 'latest', note: 'installs when you save and build' };
  if (env.status === 'building') return { name: p.name, text: known, note: 'installing' };
  return { name: p.name, text: known || 'latest', note: 'installs on the next build' };
}

export type Tone = 'ok' | 'run' | 'bad' | 'neutral';

/** The environment's state as its head and its row show it, from the service's status and the latest
 *  build. The note is said only when something happened that the state alone hides: a newer build
 *  failed while an older version still serves. (Which version is in use is on Builds.) */
export function statusView(env: Pick<Environment, 'status' | 'version' | 'build'>): { tone: Tone; label: string; note: string } {
  const b = env.build;
  if (env.status === 'building') return { tone: 'run', label: 'Building', note: '' };
  if (env.status === 'ready') return { tone: 'ok', label: 'Ready', note: b && b.status === 'failed' && b.version !== env.version ? `Version ${b.version} failed` : '' };
  if (env.status === 'failed') return { tone: 'bad', label: 'Build failed', note: '' };
  return { tone: 'neutral', label: 'Not built yet', note: '' };
}

export const VERSION_STATUS: Record<EnvironmentVersion['status'], { tone: Tone; label: string }> = {
  building: { tone: 'run', label: 'Building' }, ready: { tone: 'ok', label: 'Ready' }, failed: { tone: 'bad', label: 'Failed' }, unknown: { tone: 'neutral', label: 'Unknown' },
};

/** The builds, newest first, each marked when it is the one tasks read and when it can be switched
 *  to: a finished build that is not in use, while no build runs (a running build makes its own
 *  version the one in use when it finishes, so a switch then would not hold). */
export function versionRows(env: Pick<Environment, 'versions' | 'version' | 'status'>): (EnvironmentVersion & { active: boolean; canUse: boolean })[] {
  return [...(env.versions || [])]
    .sort((a, b) => b.version - a.version)
    .map((v) => {
      const active = env.version === v.version;
      return { ...v, active, canUse: v.status === 'ready' && !active && env.status !== 'building' };
    });
}

/** How long something took, from two of the service's timestamps (seconds); empty when one is missing. */
export function took(from?: number | null, to?: number | null): string {
  if (!from || !to) return '';
  return dur(Math.max(0, Math.round(to - from)));
}
export function dur(s: number): string {
  if (s < 60) return `${s} s`;
  if (s < 3600) { const m = Math.floor(s / 60), r = s % 60; return r ? `${m} min ${r} s` : `${m} min`; }
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return m ? `${h} h ${m} min` : `${h} h`;
}
/** A timestamp (seconds) as a short local date and time; empty when the service gave none. */
export function when(sec?: number | null): string {
  if (!sec) return '';
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).format(new Date(sec * 1000));
}

export type Node = { name: string; path: string; dir: boolean; bytes: number; children: Node[]; count: number };

/** The flat listing as a tree, folders first, each folder counting the files under it. */
export function treeOf(entries: EnvironmentFileEntry[]): Node[] {
  const root: Node = { name: '', path: '', dir: true, bytes: 0, children: [], count: 0 };
  const byPath = new Map<string, Node>([['', root]]);
  const ensure = (p: string, dir: boolean, bytes = 0): Node => {
    const have = byPath.get(p);
    if (have) return have;
    const i = p.lastIndexOf('/');
    const parent = ensure(i < 0 ? '' : p.slice(0, i), true);
    const n: Node = { name: i < 0 ? p : p.slice(i + 1), path: p, dir, bytes, children: [], count: 0 };
    parent.children.push(n); byPath.set(p, n);
    return n;
  };
  for (const e of entries) ensure(e.path, e.dir, e.bytes);
  const count = (n: Node): number => { n.count = n.dir ? n.children.reduce((a, c) => a + count(c), 0) : 1; return n.count; };
  count(root);
  const sort = (n: Node) => { n.children.sort((a, b) => Number(b.dir) - Number(a.dir) || a.name.localeCompare(b.name)); n.children.forEach(sort); };
  sort(root);
  return root.children;
}

/** A git repository's address, as the service clones it; null when the text is not one. */
export function gitUrl(src: string): string | null {
  const s = src.trim();
  if (/^(https?:\/\/|ssh:\/\/|git@)\S+$/i.test(s)) return s;
  if (/^[\w.-]+\.[a-z]{2,}\/\S+$/i.test(s)) return 'https://' + s;    // github.com/acme/docs
  return null;
}

/** The files of a picked folder (or of picked files) with the path each lands at: every file, its
 *  folders kept (Richard, 10-19: "Upload everything"). `stripTop` drops the picked folder's own name,
 *  so its contents are the project's root. */
export function folderFiles(files: File[], stripTop: boolean): { path: string; file: File }[] {
  const out: { path: string; file: File }[] = [];
  for (const f of files) {
    const rel = (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name;
    const parts = rel.split('/').filter(Boolean);
    if (!parts.length) continue;
    out.push({ path: (stripTop && parts.length > 1 ? parts.slice(1) : parts).join('/'), file: f });
  }
  return out;
}

/** The HTTP status a failed call carried (lib/environments puts it on the error, or the error is the
 *  bare status), 0 when there is none. */
export function statusOf(e: unknown): number {
  const s = (e as { status?: unknown } | null)?.status;
  if (typeof s === 'number') return s;
  const m = e instanceof Error ? /^(\d{3})$/.exec(e.message.trim()) : null;
  return m ? Number(m[1]) : 0;
}

/** Which of the service's own limits refused a call: the most files and folders one environment
 *  holds, or the size of one file or archive; '' for any other refusal. */
export function limitOf(e: unknown): 'entries' | 'size' | '' {
  if (statusOf(e) !== 413) return '';
  const d = (e as { detail?: unknown } | null)?.detail;
  return d && typeof d === 'object' && 'max_entries' in d ? 'entries' : 'size';
}
export const TOO_MANY = 'That is more files and folders than one environment holds.';
export const TOO_BIG = 'That is too large to upload here.';

/** A failure in plain words: the caller's sentence for a status it knows, the shared ones for being
 *  busy or over a limit of the service's, else what failed and to try again. Never the server's own text. */
export function sayFail(e: unknown, what: string, by: Partial<Record<number, string>> = {}): string {
  const s = statusOf(e);
  if (by[s]) return by[s] as string;
  if (s === 503) return 'We are busy right now. Try again in a minute.';
  if (s === 429) return 'Too much is running at once. Try again when something finishes.';
  if (s === 413) return limitOf(e) === 'entries' ? TOO_MANY : TOO_BIG;
  return `${what} Try again.`;
}

const files = (n: number) => `${n} ${n === 1 ? 'file' : 'files'}`;
const some = (l: { path: string }[]) => l.slice(0, 2).map((f) => f.path).join(', ') + (l.length > 2 ? ' and more' : '');

/** How an upload of many files ended, in plain words: how many went in, the ones too large for the
 *  service, the ones refused for another reason, and whether the environment filled up (the service
 *  holds a set number of files and folders; past it every file is refused, so the upload stops). */
export function uploadSummary(done: number, failed: { path: string; tooBig: boolean }[], full: boolean): string {
  const big = failed.filter((f) => f.tooBig), other = failed.filter((f) => !f.tooBig);
  return [
    `${files(done)} uploaded.`,
    big.length === 1 ? `${big[0].path} is too large to upload.` : big.length ? `${big.length} files are too large to upload (${some(big)}).` : '',
    other.length === 1 ? `${other[0].path} could not be uploaded.` : other.length ? `${other.length} files could not be uploaded (${some(other)}).` : '',
    full ? 'Then the environment held as many files and folders as it can, so the rest were not uploaded.' : '',
  ].filter(Boolean).join(' ');
}
