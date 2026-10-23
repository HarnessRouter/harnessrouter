'use client';
// One environment, in the redesign (Add-ons › Environments; Richard, 10-18: the old console's
// whole environment experience, in the new design). The old page's capabilities, each in its place:
//   Files     the project's tree beside the open file, edited in place in the console's code editor
//             (CodeEditor: highlighted, long lines wrapped); a file that is not text shown as itself
//             (an image, a PDF, a video, a sound; Richard 10-21); find a file; new file and folder;
//             upload files or a folder; import a git repository (URL and branch or tag) or an
//             archive, over the current files or replacing them; remove a file or a folder.
//   Packages  pip, npm and apt packages declared per manager, each checked with its registry on Add
//             (the old page's rule, ext/envModel planAdd); the Python a build uses; the version each
//             one has in the active build; everything that build installed.
//   Builds    start a build, its live stage and log while it runs, why it failed; every version with
//             its status, which one tasks read, and a switch back to an older finished one.
//   Details   name, description, how it is run, where tasks find it, the setups that use it (each a
//             link), and delete.
// Edits to files, packages and details are held here until Save; Save and build saves them and starts
// a build, so what a task reads is what the sheet shows. Every value is the service's: nothing is
// estimated, and a value it has not given is not drawn.
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import Link from 'next/link';
import dynamic from 'next/dynamic';
import {
  activateEnvironmentVersion, buildEnvironment, checkPackage, deleteEnvironmentPath, environmentHarnesses, fmtBytes,
  getEnvironment, getEnvironmentBuild, importEnvironmentArchive, importEnvironmentGit, listEnvironmentFiles, listRuntimes,
  makeEnvironmentDir, readEnvironmentFile, updateEnvironment, writeEnvironmentFile,
  type Environment, type EnvironmentBuildRecord, type EnvironmentFileEntry, type EnvironmentRuntimes, type Manager,
} from '@/lib/environments';
import { Sheet, SheetTop } from '../Sheet';
import { Skel, SkLine, SkRows } from '../Skel';
import { toast } from '../toast';
import { tabKeys } from '../tabKeys';
import { plural, setupHref } from './shared';
import {
  MANAGERS, SPEC_HINT, VERSION_STATUS, dur, folderFiles, gitUrl, limitOf, pkgRow, planAdd, sayFail, specParts, specProblem, statusView, took,
  treeOf, uploadSummary, versionRows, when, type Node,
} from './envModel';
import './envs.css';

// the editor and its languages load when a file is opened, not with the page
const CodeEditor = dynamic(() => import('../CodeEditor').then((m) => m.CodeEditor), {
  ssr: false, loading: () => <div className="hr-code-wait" aria-hidden="true" />,
});

export type EnvTab = 'files' | 'packages' | 'builds' | 'details';
type Declared = Record<Manager, string[]>;
export type EnvUser = { id: string; name: string };
type Busy = '' | 'save' | 'build' | 'files' | 'check' | 'use' | 'delete';

const declaredOf = (e: Environment): Declared =>
  ({ pip: (e.declared?.pip || []).map((x) => x.spec), npm: (e.declared?.npm || []).map((x) => x.spec), apt: (e.declared?.apt || []).map((x) => x.spec) });
const sameDeclared = (a: Declared, b: Declared) => MANAGERS.every((m) => a[m].length === b[m].length && a[m].every((x, i) => x === b[m][i]));

const svg = (d: ReactNode) => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{d}</svg>
);
const FOLDER = 'M3 6.5A1.5 1.5 0 0 1 4.5 5H9l2 2h8.5A1.5 1.5 0 0 1 21 8.5v9a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5z';
const IC = {
  file: svg(<><path d="M6 3h8l4 4v14H6z" /><path d="M14 3v4h4" /></>),
  folder: svg(<path d={FOLDER} />),
  fileAdd: svg(<><path d="M6 3h8l4 4v14H6z" /><path d="M12 11v6M9 14h6" /></>),
  folderAdd: svg(<><path d={FOLDER} /><path d="M12 10.5v5M9.5 13h5" /></>),
  upload: svg(<><path d="M12 15V4M7.5 8.5L12 4l4.5 4.5" /><path d="M4 15v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4" /></>),
  folderUp: svg(<><path d={FOLDER} /><path d="M12 16v-5M9.8 13.2L12 11l2.2 2.2" /></>),
  git: svg(<><circle cx="6" cy="6" r="2.2" /><circle cx="6" cy="18" r="2.2" /><circle cx="18" cy="8" r="2.2" /><path d="M6 8.2v7.6M18 10.2c0 3.3-3.4 4-6.2 4.6-2.3.5-4.6 1.1-5.4 2.4" /></>),
  archive: svg(<><rect x="4" y="3" width="16" height="18" rx="2" /><path d="M12 3v2M12 7v2M12 11v2" /><rect x="10" y="14" width="4" height="4" rx="1" /></>),
  chev: svg(<path d="M9 6l6 6-6 6" />),
  x: svg(<path d="M6 6l12 12M18 6L6 18" />),
  search: svg(<><circle cx="11" cy="11" r="6.5" /><path d="M20 20l-4-4" /></>),
};

export function EnvSheet({ id, tab: firstTab = 'files', notice = '', taken = [], onClose, onChanged, onDelete }: {
  id: string;
  tab?: EnvTab;
  /** a line to start with in the foot: what did not go through when it was made */
  notice?: string;
  /** the other environments' names, lower case: a rename to one of them is refused here */
  taken?: string[];
  onClose: () => void;
  /** something changed here (saved, built, a version switched): the list reads again */
  onChanged: () => void;
  /** take it off every setup that reads it, then delete it (EnvsTab's removal); true when it went */
  onDelete: (env: Environment, users: EnvUser[]) => Promise<boolean>;
}) {
  const [env, setEnv] = useState<Environment | null>(null);
  const [loadErr, setLoadErr] = useState('');
  const [entries, setEntries] = useState<EnvironmentFileEntry[] | null>(null);
  const [filesErr, setFilesErr] = useState('');
  const [users, setUsers] = useState<EnvUser[] | null>(null);
  const [build, setBuild] = useState<EnvironmentBuildRecord | null>(null);
  const [runtimes, setRuntimes] = useState<EnvironmentRuntimes | null>(null);
  const [tab, setTab] = useState<EnvTab>(firstTab);
  const [busy, setBusy] = useState<Busy>('');
  const [say, setSay] = useState(notice);
  const [now, setNow] = useState(() => Date.now());
  const [ask, setAsk] = useState<'' | 'close' | 'delete'>('');
  // what is edited here, held until Save
  const [declared, setDeclared] = useState<Declared | null>(null);
  const [python, setPython] = useState('');
  const [segment, setSegment] = useState<Manager>('pip');
  const [resolved, setResolved] = useState<Record<string, string>>({});
  const [form, setForm] = useState({ name: '', description: '', entry: '' });
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [picked, setPicked] = useState<number | null>(null);   // a version whose log is open; null: the latest build

  const pkgDirty = !!(env && declared && (!sameDeclared(declared, declaredOf(env)) || python !== (env.runtime?.python || '')));
  const detailsDirty = !!env && (form.name.trim() !== env.name || form.description.trim() !== env.description || form.entry.trim() !== env.entry);
  const editCount = Object.keys(edits).length;
  const needsBuild = pkgDirty || editCount > 0;
  const dirty = needsBuild || detailsDirty;
  const held = useRef({ pkg: false, details: false });
  held.current = { pkg: pkgDirty, details: detailsDirty };
  const changed = useRef(onChanged);
  changed.current = onChanged;

  const load = useCallback(async (first = false) => {
    try {
      const e = await getEnvironment(id);
      // the latest build's record is read before the state moves, so a running build never shows the
      // previous version's outcome for a moment
      const [t, h, b] = await Promise.all([
        listEnvironmentFiles(id).catch(() => null),
        environmentHarnesses(id).catch(() => null),
        e.latestVersion ? getEnvironmentBuild(id, e.latestVersion).catch(() => null) : Promise.resolve(null),
      ]);
      setEnv(e);
      if (t) { setEntries(t.entries); setFilesErr(''); } else if (first) { setEntries([]); setFilesErr('The files could not be read just now. Close and open it again to retry.'); }
      if (h) setUsers(h.map((x) => ({ id: x.id, name: x.name })));
      setBuild(b);
      if (first || !held.current.pkg) { setDeclared(declaredOf(e)); setPython(e.runtime?.python || ''); }
      if (first || !held.current.details) setForm({ name: e.name, description: e.description, entry: e.entry });
      setLoadErr('');
    } catch (err) {
      if (first) setLoadErr(sayFail(err, 'This environment could not be read.', { 404: 'This environment is gone. It may have been deleted.' }));
    }
  }, [id]);
  useEffect(() => { void load(true); }, [load]);
  useEffect(() => { listRuntimes().then(setRuntimes).catch(() => setRuntimes(null)); }, []);

  // while a build runs: read it every three seconds, and count its seconds
  const status = env?.status;
  useEffect(() => {
    if (status !== 'building') return;
    const t = setInterval(() => void load(), 3000);
    const k = setInterval(() => setNow(Date.now()), 1000);
    return () => { clearInterval(t); clearInterval(k); };
  }, [status, load]);
  // a build that ends while the sheet is open says how it went, and the list reads again
  const was = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (was.current === 'building' && status && status !== 'building') {
      const b = env?.build;
      if (b?.status === 'ready') toast(`Version ${b.version} is ready.`);
      else if (b?.status === 'failed') toast(`Version ${b.version} failed. Its log on Builds says why.`);
      changed.current();
    }
    was.current = status;
  }, [status, env?.build]);

  const building = status === 'building';
  const elapsed = build?.status === 'building' && build.started_at ? Math.max(0, Math.round(now / 1000 - build.started_at)) : null;

  async function startBuild() {
    if (!env) return;
    setBusy('build'); setSay('');
    try {
      await buildEnvironment(id);
      setPicked(null); setTab('builds');
      await load(); changed.current();
    } catch (e) {
      setSay(sayFail(e, 'The build could not start.', { 409: env.files.count ? 'A build is already running.' : 'There are no files yet. Put the project in first.' }));
    } finally { setBusy(''); }
  }

  async function save(andBuild: boolean) {
    if (!env || !declared) return;
    const name = form.name.trim();
    if (!name) { setTab('details'); setSay('Give the environment a name.'); return; }
    if (name.toLowerCase() !== env.name.toLowerCase() && taken.includes(name.toLowerCase())) { setTab('details'); setSay(`“${name}” is already taken. Use another name.`); return; }
    setBusy('save'); setSay('');
    let step = 'files';
    try {
      const written: string[] = [];
      for (const [p, text] of Object.entries(edits)) { await writeEnvironmentFile(id, p, text); written.push(p); }
      if (written.length) setEdits((cur) => { const n = { ...cur }; for (const p of written) if (n[p] === edits[p]) delete n[p]; return n; });
      step = 'details';
      if (pkgDirty || detailsDirty) {
        setEnv(await updateEnvironment(id, {
          name, description: form.description.trim(), entry: form.entry.trim(), ...(pkgDirty ? { packages: declared, runtime: { python } } : {}),
        }));
      }
      step = 'build';
      if (andBuild) { await buildEnvironment(id); setPicked(null); setTab('builds'); }
      await load(); changed.current();
      if (!andBuild) toast('Saved.');
    } catch (e) {
      setSay(step === 'build'
        ? sayFail(e, 'Saved, but the build could not start.', { 409: 'Saved. A build is already running; build again when it finishes.' })
        : sayFail(e, step === 'files' ? 'An edited file could not be saved.' : 'Your changes could not be saved.'));
      await load();
    } finally { setBusy(''); }
  }

  function discard() {
    if (!env) return;
    setDeclared(declaredOf(env)); setPython(env.runtime?.python || '');
    setForm({ name: env.name, description: env.description, entry: env.entry });
    setEdits({}); setSay(''); setAsk('');
  }
  const requestClose = () => { if (dirty && !ask) { setAsk('close'); return; } onClose(); };

  async function switchVersion(n: number) {
    setBusy('use'); setSay('');
    try {
      setEnv(await activateEnvironmentVersion(id, n));
      toast(`Version ${n} is in use.`);
      await load(); changed.current();
    } catch (e) {
      setSay(sayFail(e, `Version ${n} could not be put in use.`, { 409: `Version ${n} is not a finished build.` }));
    } finally { setBusy(''); }
  }

  async function remove() {
    if (!env) return;
    setBusy('delete'); setSay('');
    try {
      const fresh = await environmentHarnesses(id).then((h) => h.map((x) => ({ id: x.id, name: x.name }))).catch(() => users || []);
      if (await onDelete(env, fresh)) return;
      setAsk('');
    } finally { setBusy(''); }
  }

  const view = env ? statusView(env) : null;
  const pkgTotal = declared ? MANAGERS.reduce((a, m) => a + declared[m].length, 0) : 0;
  const TABS: [EnvTab, string, number | null][] = [
    ['files', 'Files', env ? env.files.count : null], ['packages', 'Packages', declared ? pkgTotal : null],
    ['builds', 'Builds', env ? (env.versions || []).length : null], ['details', 'Details', null],
  ];

  // the primary action: save what is held (and build it when it changes what tasks read), else build
  // (a build with no files to build is not offered)
  let primary: { label: string; act: () => void; disabled?: boolean } | null = null;
  if (env) {
    if (needsBuild && !building) primary = { label: busy === 'save' ? 'Saving…' : 'Save and build', act: () => void save(true) };
    else if (dirty) primary = { label: busy === 'save' ? 'Saving…' : 'Save', act: () => void save(false) };
    else if (building) primary = { label: 'Building…', act: () => setTab('builds'), disabled: true };
    else if (env.files.count) primary = { label: busy === 'build' ? 'Starting…' : env.version ? 'Build again' : 'Build', act: () => void startBuild() };
  }
  const heldWhat = [editCount ? plural(editCount, 'file') + ' edited' : '', pkgDirty ? 'packages' : '', detailsDirty ? 'details' : ''].filter(Boolean).join(', ');
  const footLine = say ? say
    : building && dirty ? `Not saved yet: ${heldWhat}. Save now, then build when this build finishes.`
      : dirty ? `Not saved yet: ${heldWhat}.`
        : building ? [`Building version ${build?.version ?? env?.latestVersion ?? ''}`, build?.stage || '', elapsed !== null ? dur(elapsed) : ''].filter(Boolean).join(' · ')
          : '';

  return (
    <Sheet onClose={requestClose} labelledBy="eoh" className="eo-sheet" initialFocus="dialog" busy={busy === 'save' || busy === 'delete' || busy === 'files'}>
      <SheetTop id="eoh" onClose={requestClose}
        title={env ? env.name : loadErr ? 'Environment' : <SkLine w={180} h={18} />}
        sub={env && view ? (
          <>
            <span className={`pill ${view.tone}`}>{view.tone === 'run' ? <span className="dot run" aria-hidden="true" /> : null}{view.label}</span>
            {view.note ? <span className="eo-sub">{view.note}</span> : null}
          </>
        ) : undefined} />

      {loadErr ? <p className="eo-msg bad" role="alert">{loadErr}</p> : null}

      {!env && !loadErr ? <Skel label="Loading the environment"><SkRows n={5} /></Skel> : null}

      {env && declared ? (
        <>
          <div className="tabs inline eo-tabs" role="tablist" aria-label="Environment" onKeyDown={(e) => tabKeys(e, TABS.map(([k]) => k), tab, setTab)}>
            {TABS.map(([k, label, n]) => (
              <button key={k} type="button" role="tab" id={`eot-${k}`} aria-controls="eo-panel" aria-selected={tab === k} tabIndex={tab === k ? 0 : -1} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>
                {label}{n !== null ? <span className="count">{n}</span> : null}
                {(k === 'files' && editCount) || (k === 'packages' && pkgDirty) || (k === 'details' && detailsDirty) ? <><span className="eo-held" aria-hidden="true" /><span className="sr">, not saved</span></> : null}
              </button>
            ))}
          </div>
          <div className={`eo-body eo-on-${tab}`} id="eo-panel" role="tabpanel" aria-labelledby={`eot-${tab}`}>
            {tab === 'files' ? (
              <FilesPane id={id} entries={entries} filesErr={filesErr} edits={edits} setEdits={setEdits}
                busy={busy === 'files'} setBusy={(b) => setBusy(b ? 'files' : '')} reload={() => load()} />
            ) : null}
            {tab === 'packages' ? (
              <PackagesPane env={env} runtimes={runtimes} declared={declared} setDeclared={setDeclared} python={python} setPython={setPython}
                segment={segment} setSegment={setSegment} resolved={resolved} setResolved={setResolved} />
            ) : null}
            {tab === 'builds' ? (
              <BuildsPane id={id} env={env} build={build} elapsed={elapsed} picked={picked} setPicked={setPicked}
                busy={busy === 'use'} onUse={(n) => void switchVersion(n)} />
            ) : null}
            {tab === 'details' ? (
              <DetailsPane env={env} form={form} setForm={setForm} users={users} />
            ) : null}
          </div>

          {ask === 'delete' ? (
            <div className="mcp-ask eo-ask" role="alertdialog" aria-labelledby="eoAskD">
              <span id="eoAskD">Delete <b>{env.name}</b>?{' '}
                {users?.length
                  ? <>{users.slice(0, 3).map((u) => u.name).join(', ')}{users.length > 3 ? ` and ${users.length - 3} more` : ''} {users.length === 1 ? 'uses' : 'use'} it; it comes off {users.length === 1 ? 'that setup' : 'them'}, and from the next task {users.length === 1 ? 'its tasks start' : 'their tasks start'} with no files.</>
                  : 'No setup uses it.'}{' '}Its files and every version go. This can’t be undone.</span>
              <span className="mcp-ask-b">
                <button type="button" className="btn small" disabled={busy === 'delete'} onClick={() => setAsk('')}>Keep</button>
                <button type="button" className="btn small del-go" disabled={busy === 'delete'} onClick={() => void remove()} autoFocus>
                  {busy === 'delete' ? 'Deleting…' : 'Delete environment'}</button>
              </span>
            </div>
          ) : null}
          {ask === 'close' ? (
            <div className="mcp-ask eo-ask" role="alertdialog" aria-labelledby="eoAskC">
              <span id="eoAskC">Your changes are not saved: {heldWhat}.</span>
              <span className="mcp-ask-b">
                <button type="button" className="btn small" onClick={() => setAsk('')} autoFocus>Keep editing</button>
                <button type="button" className="btn small del-go" onClick={() => { discard(); onClose(); }}>Discard and close</button>
              </span>
            </div>
          ) : null}

          <div className="sheet-actions eo-foot">
            {/* not while a build runs: the service keeps an environment that is building */}
            {tab === 'details' && !ask && !building ? (
              <button type="button" className="link-q danger eo-del" disabled={!!busy} onClick={() => { setSay(''); setAsk('delete'); }}>Delete</button>
            ) : null}
            <span className={`eo-state${say ? ' bad' : ''}`} role="status" aria-live="polite">{footLine}</span>
            {dirty ? <button type="button" className="btn" disabled={!!busy} onClick={discard}>Discard</button> : null}
            {primary ? (
              <button type="button" className="btn primary" disabled={!!busy || primary.disabled} onClick={primary.act}>{primary.label}</button>
            ) : null}
          </div>
        </>
      ) : null}
    </Sheet>
  );
}

// ── Files ─────────────────────────────────────────────────────────────────────────────────────────

type Imp = { kind: 'git' | 'archive'; url: string; ref: string; file: File | null; replace: boolean };

function FilesPane({ id, entries, filesErr, edits, setEdits, busy, setBusy, reload }: {
  id: string; entries: EnvironmentFileEntry[] | null; filesErr: string;
  edits: Record<string, string>; setEdits: (f: (e: Record<string, string>) => Record<string, string>) => void;
  busy: boolean; setBusy: (b: boolean) => void; reload: () => Promise<void>;
}) {
  const [q, setQ] = useState('');
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [sel, setSel] = useState('');
  const [openPath, setOpenPath] = useState('');
  const [file, setFile] = useState<{ text: string | null; bytes: number; type: string; blob?: Blob | null } | null>(null);
  const [fileErr, setFileErr] = useState('');
  const [newPath, setNewPath] = useState<{ kind: 'file' | 'dir'; value: string } | null>(null);
  const [imp, setImp] = useState<Imp | null>(null);
  const [asking, setAsking] = useState<{ path: string; dir: boolean; count: number } | null>(null);
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null);
  const filesRef = useRef<HTMLInputElement | null>(null);
  const folderRef = useRef<HTMLInputElement | null>(null);
  const archiveRef = useRef<HTMLInputElement | null>(null);
  // a folder picker: the attribute React does not type
  useEffect(() => { folderRef.current?.setAttribute('webkitdirectory', ''); }, []);

  const tree = useMemo(() => treeOf(entries || []), [entries]);
  const needle = q.trim().toLowerCase();
  const matches = useMemo(() => (needle ? (entries || []).filter((e) => !e.dir && e.path.toLowerCase().includes(needle)) : []), [entries, needle]);
  const isDir = (p: string) => !!entries?.some((e) => e.path === p && e.dir);
  const parentDir = () => { if (!sel) return ''; if (isDir(sel)) return sel; const i = sel.lastIndexOf('/'); return i < 0 ? '' : sel.slice(0, i); };
  const under = (p: string, root: string) => p === root || p.startsWith(root + '/');

  async function openFile(path: string) {
    setSel(path); setOpenPath(path); setFile(null); setFileErr('');
    try { setFile(await readEnvironmentFile(id, path)); }
    catch { setFileErr('This file could not be read just now. Open it again to retry.'); }
  }
  const toggle = (p: string) => setOpen((s) => { const n = new Set(s); if (n.has(p)) n.delete(p); else n.add(p); return n; });

  async function work(fn: () => Promise<void>) {
    setBusy(true); setMsg(null);
    try { await fn(); } finally { setBusy(false); }
  }

  const createPath = () => work(async () => {
    if (!newPath) return;
    const v = newPath.value.trim().replace(/^\/+|\/+$/g, '');
    if (!v) { setMsg({ text: newPath.kind === 'dir' ? 'Type a folder name.' : 'Type a file name.', bad: true }); return; }
    if (v.split('/').some((s) => !s || s === '.' || s === '..')) { setMsg({ text: 'Use a name without . or .. parts.', bad: true }); return; }
    const base = parentDir();
    const p = (base ? base + '/' : '') + v;
    if (entries?.some((e) => e.path === p)) { setMsg({ text: `${p} is already there.`, bad: true }); return; }
    try {
      if (newPath.kind === 'dir') { await makeEnvironmentDir(id, p); setOpen((s) => new Set(s).add(p)); setSel(p); }
      else { await writeEnvironmentFile(id, p, ''); }
      setNewPath(null);
      await reload();
      if (newPath.kind === 'file') await openFile(p);
    } catch (e) {
      setMsg({ text: sayFail(e, `${p} could not be made.`, { 409: 'A file is already at that path.' }), bad: true });
    }
  });

  const upload = (list: FileList | null, folder: boolean) => work(async () => {
    // every file, its folders kept; only the service's own limits refuse one
    const files = folderFiles(Array.from(list || []), false);
    if (!files.length) return;
    const base = parentDir();
    let done = 0, full = false; const failed: { path: string; tooBig: boolean }[] = [];
    for (const f of files) {
      setMsg({ text: `Uploading ${done + failed.length + 1} of ${files.length}…` });
      try { await writeEnvironmentFile(id, (base ? base + '/' : '') + f.path, f.file); done++; }
      catch (e) {
        const limit = limitOf(e);
        if (limit === 'entries') { full = true; break; }     // past it every file is refused: stop here
        failed.push({ path: f.path, tooBig: limit === 'size' });
      }
    }
    if (folder && files[0]?.path.includes('/')) setOpen((s) => new Set(s).add((base ? base + '/' : '') + files[0].path.split('/')[0]));
    await reload();
    const said = uploadSummary(done, failed, full);
    setMsg(failed.length || full ? { text: said, bad: true } : { text: `${said} Build to use ${done === 1 ? 'it' : 'them'}.` });
  });

  const runImport = () => work(async () => {
    if (!imp) return;
    let url = '';
    if (imp.kind === 'git') {
      const u = gitUrl(imp.url);
      if (!u) { setMsg({ text: 'Paste a git repository address, like https://github.com/your-org/project.', bad: true }); return; }
      url = u;
    } else if (!imp.file) { setMsg({ text: 'Choose a zip or tar of the project folder.', bad: true }); return; }
    setMsg({ text: imp.kind === 'git' ? 'Importing the repository…' : `Importing ${imp.file?.name}…` });
    try {
      const r: { written?: number; skipped?: number; count: number } = imp.kind === 'git'
        ? await importEnvironmentGit(id, url, imp.ref.trim(), imp.replace)
        : await importEnvironmentArchive(id, imp.file as File, imp.replace);
      setImp(null);
      if (imp.replace) { setSel(''); setOpenPath(''); setFile(null); setEdits(() => ({})); }
      await reload();
      setMsg({ text: [typeof r.written === 'number' ? `Imported ${plural(r.written, 'file')}.` : 'Imported.',
        r.skipped ? `${plural(r.skipped, 'entry')} left out.` : '', 'Build to use them.'].filter(Boolean).join(' ') });
    } catch (e) {
      setMsg({ bad: true, text: imp.kind === 'git'
        ? sayFail(e, 'The repository could not be imported.', { 422: 'That repository could not be imported. Check the address and the branch or tag; a private repository needs an access token in the address.', 400: 'That address cannot be used.' })
        : sayFail(e, 'The archive could not be imported.', { 422: 'That file is not a zip or tar archive.' }) });
    }
  });

  const remove = () => work(async () => {
    if (!asking) return;
    const p = asking.path;
    try {
      await deleteEnvironmentPath(id, p);
      setAsking(null);
      if (under(sel, p)) setSel('');
      if (under(openPath, p)) { setOpenPath(''); setFile(null); }
      setEdits((cur) => Object.fromEntries(Object.entries(cur).filter(([k]) => !under(k, p))));
      await reload();
      setMsg({ text: `${p} removed.` });
    } catch (e) {
      setMsg({ text: sayFail(e, `${p} could not be removed.`, { 404: `${p} is already gone.` }), bad: true });
      await reload();
    }
  });

  const text = openPath && file?.text !== null && file ? (edits[openPath] ?? file.text ?? '') : '';
  const setText = (v: string) => setEdits((cur) => {
    const n = { ...cur };
    if (file && v === file.text) delete n[openPath]; else n[openPath] = v;
    return n;
  });

  const row = (n: Node, depth: number): ReactNode => (
    <li key={n.path}>
      <div className={`eo-node${sel === n.path ? ' on' : ''}`} style={{ paddingLeft: depth * 14 }}>
        <button type="button" className="eo-item" aria-expanded={n.dir ? open.has(n.path) : undefined}
          onClick={() => { if (n.dir) { toggle(n.path); setSel(n.path); } else void openFile(n.path); }}>
          <span className={`eo-chev${n.dir && open.has(n.path) ? ' open' : ''}`} aria-hidden="true">{n.dir ? IC.chev : null}</span>
          <span className="eo-ic" aria-hidden="true">{n.dir ? IC.folder : IC.file}</span>
          <span className="eo-fn">{n.name}</span>
          {n.dir ? <span className="eo-n">{n.count}</span> : edits[n.path] !== undefined ? <><span className="eo-held" aria-hidden="true" /><span className="sr">, edited</span></> : null}
        </button>
        <button type="button" className="eo-ib" aria-label={`Remove ${n.name}`} title="Remove" disabled={busy}
          onClick={() => { setMsg(null); setAsking({ path: n.path, dir: n.dir, count: n.count }); }}>{IC.x}</button>
      </div>
      {n.dir && open.has(n.path) && n.children.length ? <ul>{n.children.map((c) => row(c, depth + 1))}</ul> : null}
    </li>
  );

  const empty = entries !== null && !entries.length;
  const pickers = (
    <>
      <input ref={filesRef} type="file" hidden multiple onChange={(ev) => { void upload(ev.target.files, false); ev.target.value = ''; }} />
      <input ref={folderRef} type="file" hidden multiple onChange={(ev) => { void upload(ev.target.files, true); ev.target.value = ''; }} />
      <input ref={archiveRef} type="file" hidden accept=".zip,.tar,.tgz,.tar.gz,application/zip,application/x-tar,application/gzip"
        onChange={(ev) => { const f = ev.target.files?.[0] || null; ev.target.value = ''; if (f) setImp((cur) => ({ ...(cur || { url: '', ref: '', replace: false }), kind: 'archive', file: f })); }} />
    </>
  );

  return (
    <div className="eo-files-pane">
      {pickers}
      <div className="eo-bar">
        <label className="eo-find"><span className="sr">Find a file</span>{IC.search}
          <input type="search" value={q} placeholder="Find a file" spellCheck={false} onChange={(ev) => setQ(ev.target.value)} /></label>
        <span className="eo-tools">
          <button type="button" className="eo-tool" disabled={busy} onClick={() => { setMsg(null); setNewPath({ kind: 'file', value: '' }); }} title="New file">{IC.fileAdd}<span>New file</span></button>
          <button type="button" className="eo-tool" disabled={busy} onClick={() => { setMsg(null); setNewPath({ kind: 'dir', value: '' }); }} title="New folder">{IC.folderAdd}<span>New folder</span></button>
          <button type="button" className="eo-tool" disabled={busy} onClick={() => filesRef.current?.click()} title="Upload files">{IC.upload}<span>Upload files</span></button>
          <button type="button" className="eo-tool" disabled={busy} onClick={() => folderRef.current?.click()} title="Upload a folder">{IC.folderUp}<span>Upload a folder</span></button>
          <button type="button" className="eo-tool" disabled={busy} onClick={() => { setMsg(null); setImp({ kind: 'git', url: '', ref: '', file: null, replace: false }); }} title="Import a git repository or an archive">{IC.git}<span>Import</span></button>
        </span>
      </div>

      {imp ? (
        <div className="eo-imp" role="group" aria-label="Import a project">
          <div className="seg" role="radiogroup" aria-label="Import from">
            <button type="button" role="radio" aria-checked={imp.kind === 'git'} className={imp.kind === 'git' ? 'on' : ''} onClick={() => setImp({ ...imp, kind: 'git' })}>Git repository</button>
            <button type="button" role="radio" aria-checked={imp.kind === 'archive'} className={imp.kind === 'archive' ? 'on' : ''} onClick={() => setImp({ ...imp, kind: 'archive' })}>Archive</button>
          </div>
          {imp.kind === 'git' ? (
            <div className="eo-two">
              <div className="set-f"><label htmlFor="eoGitU">Repository address</label>
                <input id="eoGitU" className="set-in mono" value={imp.url} placeholder="https://github.com/your-org/project" spellCheck={false} autoFocus
                  onChange={(ev) => setImp({ ...imp, url: ev.target.value })} onKeyDown={(ev) => { if (ev.key === 'Enter') void runImport(); }} /></div>
              <div className="set-f"><label htmlFor="eoGitR">Branch or tag <span className="muted">optional</span></label>
                <input id="eoGitR" className="set-in mono" value={imp.ref} placeholder="main" spellCheck={false}
                  onChange={(ev) => setImp({ ...imp, ref: ev.target.value })} onKeyDown={(ev) => { if (ev.key === 'Enter') void runImport(); }} /></div>
            </div>
          ) : (
            <div className="eo-pick">
              <button type="button" className="btn line" onClick={() => archiveRef.current?.click()}>{IC.archive}{imp.file ? 'Choose another' : 'Choose a zip or tar'}</button>
              {imp.file ? <span className="set-help"><b>{imp.file.name}</b> · {fmtBytes(imp.file.size)}</span> : null}
            </div>
          )}
          <label className="eo-check"><input type="checkbox" checked={imp.replace} onChange={(ev) => setImp({ ...imp, replace: ev.target.checked })} />
            <span><b>Replace the current files</b></span></label>
          <div className="eo-imp-act">
            <button type="button" className="btn small" disabled={busy} onClick={() => setImp(null)}>Cancel</button>
            <button type="button" className="btn small primary" disabled={busy || (imp.kind === 'git' ? !imp.url.trim() : !imp.file)} onClick={() => void runImport()}>{busy ? 'Importing…' : 'Import'}</button>
          </div>
        </div>
      ) : null}

      {newPath ? (
        <div className="eo-new">
          <span className="eo-at mono">{parentDir() ? parentDir() + '/' : ''}</span>
          <label className="sr" htmlFor="eoNewP">{newPath.kind === 'dir' ? 'Folder name' : 'File name'}</label>
          <input id="eoNewP" className="set-in slim mono" value={newPath.value} autoFocus spellCheck={false} placeholder={newPath.kind === 'dir' ? 'folder name' : 'file name, e.g. run.py'}
            onChange={(ev) => setNewPath({ ...newPath, value: ev.target.value })}
            onKeyDown={(ev) => { if (ev.key === 'Enter') void createPath(); }} />
          <button type="button" className="btn small" disabled={busy} onClick={() => setNewPath(null)}>Cancel</button>
          <button type="button" className="btn small primary" disabled={busy} onClick={() => void createPath()}>{newPath.kind === 'dir' ? 'Add folder' : 'Add file'}</button>
        </div>
      ) : null}

      {asking ? (
        <div className="mcp-ask" role="alertdialog" aria-labelledby="eoAskP">
          <span id="eoAskP">Remove <b className="mono">{asking.path}</b>{asking.dir ? ` and the ${plural(asking.count, 'file')} in it` : ''}?</span>
          <span className="mcp-ask-b">
            <button type="button" className="btn small" disabled={busy} onClick={() => setAsking(null)}>Keep</button>
            <button type="button" className="btn small del-go" disabled={busy} onClick={() => void remove()} autoFocus>Remove</button>
          </span>
        </div>
      ) : null}

      {msg || filesErr ? <p className={`eo-msg${msg?.bad || (!msg && filesErr) ? ' bad' : ''}`} role="status">{msg?.text || filesErr}</p> : null}

      {entries === null ? <Skel label="Loading the files"><SkRows n={4} lead={false} /></Skel>
        : empty ? (imp || newPath ? null : (
          // the bar above has every way in: one line and the likeliest one
          <p className="eo-none eo-nofiles">No files yet.{' '}
            <button type="button" className="link-q inl" onClick={() => { setMsg(null); setImp({ kind: 'git', url: '', ref: '', file: null, replace: false }); }}>Import a project</button></p>
        )) : (
          <div className="eo-files">
            <div className="eo-tree-pane">
              {needle ? (
                matches.length ? (
                  <ul className="eo-tree">{matches.map((m) => (
                    <li key={m.path}><div className={`eo-node${sel === m.path ? ' on' : ''}`}>
                      <button type="button" className="eo-item" onClick={() => void openFile(m.path)}>
                        <span className="eo-ic" aria-hidden="true">{IC.file}</span><span className="eo-fn">{m.path}</span></button>
                    </div></li>
                  ))}</ul>
                ) : <p className="eo-none">No file matches.</p>
              ) : <ul className="eo-tree" aria-label="Project files">{tree.map((n) => row(n, 0))}</ul>}
            </div>
            <div className="eo-view">
              {openPath ? (
                <>
                  <div className="eo-view-head">
                    <code title={openPath}>{openPath}</code>
                    <span className="eo-dim">{file ? fmtBytes(file.bytes) : ''}{edits[openPath] !== undefined ? ' · edited' : ''}</span>
                    {edits[openPath] !== undefined ? <button type="button" className="link-q" onClick={() => setEdits((cur) => { const n = { ...cur }; delete n[openPath]; return n; })}>Undo edits</button> : null}
                  </div>
                  {fileErr ? <p className="eo-none bad">{fileErr}</p>
                    : !file ? <Skel label="Opening the file" className="eo-view-sk"><SkLine w="60%" /><SkLine w="80%" style={{ marginTop: 10 }} /><SkLine w="45%" style={{ marginTop: 10 }} /></Skel>
                      : file.text === null ? <FileShow path={openPath} blob={file.blob || null} type={file.type} />
                        : (
                          // the one scroll for the open file: the editor grows with its lines inside it
                          <div className="eo-code">
                            <CodeEditor path={openPath} ariaLabel={`Contents of ${openPath}`} value={text} onChange={setText} />
                          </div>
                        )}
                </>
              ) : <p className="eo-none">{entries?.length ? 'Open a file to edit it.' : ''}</p>}
            </div>
          </div>
        )}
    </div>
  );
}

/** How a file that is not text is shown, as the console's file preview shows one (FilePreview): an
 *  image, a PDF, a video or a sound. The type it is shown with is one of these, never the type the
 *  file came with, so nothing it holds can run in the page; an SVG is shown from a data address for
 *  the same reason. Anything else has no preview. */
const MEDIA: Record<string, string> = {
  png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', gif: 'image/gif', webp: 'image/webp', bmp: 'image/bmp',
  ico: 'image/x-icon', avif: 'image/avif', svg: 'image/svg+xml', pdf: 'application/pdf',
  mp4: 'video/mp4', m4v: 'video/mp4', webm: 'video/webm', mov: 'video/quicktime', ogv: 'video/ogg',
  mp3: 'audio/mpeg', wav: 'audio/wav', ogg: 'audio/ogg', oga: 'audio/ogg', m4a: 'audio/mp4', flac: 'audio/flac', aac: 'audio/aac',
};
export type Media = { kind: 'image' | 'svg' | 'pdf' | 'video' | 'audio'; type: string };
export function mediaOf(path: string, type: string): Media | null {
  const name = (path.split('/').pop() || '').toLowerCase();
  const dot = name.lastIndexOf('.');
  const byName = dot > 0 ? MEDIA[name.slice(dot + 1)] || '' : '';
  const said = (type || '').toLowerCase().split(';')[0].trim();
  const t = said === 'image/svg+xml' || byName === 'image/svg+xml' ? 'image/svg+xml'
    : /^(image|video|audio)\/[\w.+-]+$|^application\/pdf$/.test(said) ? said : byName;
  if (!t) return null;
  if (t === 'image/svg+xml') return { kind: 'svg', type: t };
  if (t === 'application/pdf') return { kind: 'pdf', type: t };
  return { kind: t.slice(0, t.indexOf('/')) as Media['kind'], type: t };
}

function FileShow({ path, blob, type }: { path: string; blob: Blob | null; type: string }) {
  const media = blob ? mediaOf(path, type) : null;
  const kind = media?.kind, as = media?.type;
  const [src, setSrc] = useState('');
  useEffect(() => {
    setSrc('');
    if (!blob || !kind || !as) return;
    let live = true;
    let url = '';
    const typed = new Blob([blob], { type: as });
    if (kind === 'svg') {
      const fr = new FileReader();
      fr.onload = () => { if (live && typeof fr.result === 'string') setSrc(fr.result); };
      fr.readAsDataURL(typed);
    } else if (typeof URL.createObjectURL === 'function') {
      url = URL.createObjectURL(typed);
      setSrc(url);
    }
    return () => { live = false; if (url) URL.revokeObjectURL(url); };
  }, [blob, kind, as]);

  const name = path.split('/').pop() || path;
  if (!media) return <p className="eo-none">This file is not text, and it has no preview here.</p>;
  if (!src) return <Skel label="Opening the file" className="eo-view-sk"><SkLine h={160} r={10} /></Skel>;
  // ph-no-capture: the person's own file, kept out of session recordings (as FilePreview does)
  return (
    <div className={`eo-show is-${media.kind} ph-no-capture`}>
      {media.kind === 'image' || media.kind === 'svg' ? <img src={src} alt={name} />
        : media.kind === 'pdf' ? <iframe src={src} title={name} />
          : media.kind === 'video' ? <video src={src} controls aria-label={name} />
            : <audio src={src} controls aria-label={name} />}
    </div>
  );
}

// ── Packages ──────────────────────────────────────────────────────────────────────────────────────

function PackagesPane({ env, runtimes, declared, setDeclared, python, setPython, segment, setSegment, resolved, setResolved }: {
  env: Environment; runtimes: EnvironmentRuntimes | null;
  declared: Declared; setDeclared: (d: Declared) => void; python: string; setPython: (p: string) => void;
  segment: Manager; setSegment: (m: Manager) => void;
  resolved: Record<string, string>; setResolved: (f: (r: Record<string, string>) => Record<string, string>) => void;
}) {
  const [spec, setSpec] = useState('');
  const [checking, setChecking] = useState(false);
  const [err, setErr] = useState('');
  const [note, setNote] = useState('');
  const saved = declaredOf(env);
  const aptOff = runtimes !== null && !runtimes.apt;

  async function add() {
    const t = spec.trim();
    if (checking) return;
    const bad = specProblem(t, segment, declared[segment]);
    if (bad) { setErr(bad); return; }
    setChecking(true); setErr(''); setNote('');
    try {
      const plan = planAdd(declared[segment], segment, t, await checkPackage(segment, t));
      if (!plan.ok) { setErr(plan.error); return; }
      setDeclared({ ...declared, [segment]: plan.next });
      setResolved((r) => ({ ...r, [plan.key]: plan.version }));
      setNote(plan.note); setSpec('');
    } catch (e) {
      setErr(sayFail(e, 'The registry could not be asked about it.', { 400: `Write it as ${SPEC_HINT[segment]}${segment === 'apt' ? '' : ', or just the name for the latest'}.` }));
    } finally { setChecking(false); }
  }
  const drop = (x: string) => setDeclared({ ...declared, [segment]: declared[segment].filter((y) => y !== x) });

  const runtimeOf: ReactNode = segment === 'pip'
    ? (runtimes?.python.length ? (
      <label className="eo-rt">Python
        <select className="set-in slim" value={python} onChange={(ev) => setPython(ev.target.value)}>
          <option value="">Default</option>
          {runtimes.python.map((v) => <option key={v} value={v}>{v}</option>)}
          {python && !runtimes.python.includes(python) ? <option value={python}>{python}</option> : null}
        </select>
      </label>
    ) : python ? <span className="eo-rt">Python {python}</span> : null)
    : segment === 'npm' ? (runtimes?.node[0] ? <span className="eo-rt">Node {runtimes.node[0]}</span> : null)
      : (runtimes?.os.name ? <span className="eo-rt">{runtimes.os.name[0].toUpperCase() + runtimes.os.name.slice(1)} {runtimes.os.version}</span> : null);
  const installed = env.packages.filter((p) => p.manager === segment);
  const managers = MANAGERS.filter((m) => !(m === 'apt' && aptOff && !declared.apt.length));
  const pickManager = (m: Manager) => { setSegment(m); setErr(''); setNote(''); };

  return (
    <div className="eo-pk">
      <div className="eo-pk-bar">
        <div className="seg" role="tablist" aria-label="Package manager" onKeyDown={(e) => tabKeys(e, managers, segment, pickManager)}>
          {/* apt where the service builds without it is left out, unless packages are declared for it */}
          {managers.map((m) => (
            <button key={m} type="button" role="tab" aria-selected={segment === m} tabIndex={segment === m ? 0 : -1} className={segment === m ? 'on' : ''}
              onClick={() => pickManager(m)}>{m} <span className="eo-c">{declared[m].length}</span></button>
          ))}
        </div>
        {runtimeOf}
      </div>
      {segment === 'apt' && aptOff ? null : (
        <form className="eo-add" onSubmit={(ev) => { ev.preventDefault(); void add(); }}>
          <label className="sr" htmlFor="eoSpec">Add a {segment} package</label>
          <input id="eoSpec" className={`set-in mono${err ? ' bad' : ''}`} value={spec} placeholder={SPEC_HINT[segment]} spellCheck={false} autoComplete="off"
            aria-invalid={err ? true : undefined} aria-describedby="eoSpecSay"
            onChange={(ev) => { setSpec(ev.target.value); if (err) setErr(''); }} />
          <button type="submit" className="btn" disabled={!spec.trim() || checking}>{checking ? 'Checking…' : 'Add'}</button>
        </form>
      )}
      <p id="eoSpecSay" className={`eo-msg${err ? ' bad' : note ? ' warn' : ''}`} role={err ? 'alert' : 'status'}>{err || note}</p>

      {declared[segment].length ? (
        <ul className="eo-pkgs" aria-label={`${segment} packages`}>
          {declared[segment].map((x) => {
            const r = pkgRow(env, segment, x, resolved, saved[segment].includes(x));
            return (
              <li key={x} className="eo-pkg">
                <code className="eo-pkg-n">{r.name}</code>
                <span className="eo-pkg-v">{r.text ? <span className="mono">{r.text}</span> : null}{r.note ? <em>{r.note}</em> : null}</span>
                <button type="button" className="eo-ib" aria-label={`Remove ${r.name}`} title="Remove" onClick={() => drop(x)}>{IC.x}</button>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="eo-none left">No {segment} packages yet.</p>
      )}

      {env.version && installed.length ? (
        <details className="eo-all">
          <summary>Everything version {env.version} installed with {segment} <span className="count">{installed.length}</span></summary>
          <ul>{installed.map((p) => <li key={p.name}><code>{p.name}</code><span className="mono">{p.version}</span></li>)}</ul>
        </details>
      ) : null}
    </div>
  );
}

// ── Builds ────────────────────────────────────────────────────────────────────────────────────────

export function buildHead(b: EnvironmentBuildRecord, elapsed: number | null): { title: string; line: string } {
  if (b.status === 'building') return { title: `Building version ${b.version}`, line: [b.stage || 'starting', elapsed !== null ? dur(elapsed) : ''].filter(Boolean).join(' · ') };
  if (b.status === 'ready') {
    return {
      title: `Version ${b.version} is ready`,
      line: [took(b.started_at, b.finished_at), b.packages ? plural(b.packages.length, 'package') : '', typeof b.files === 'number' ? plural(b.files, 'file') : '',
        b.bytes ? fmtBytes(b.bytes) : ''].filter(Boolean).join(' · '),
    };
  }
  return { title: `Version ${b.version} failed`, line: b.error || 'The build failed.' };
}

function BuildsPane({ id, env, build, elapsed, picked, setPicked, busy, onUse }: {
  id: string; env: Environment; build: EnvironmentBuildRecord | null; elapsed: number | null;
  picked: number | null; setPicked: (n: number | null) => void; busy: boolean; onUse: (n: number) => void;
}) {
  const [rec, setRec] = useState<EnvironmentBuildRecord | null>(null);
  const [recErr, setRecErr] = useState('');
  const term = useRef<HTMLPreElement | null>(null);
  const showing = picked !== null && picked !== build?.version ? rec : build;
  useEffect(() => {
    if (picked === null || picked === build?.version) { setRec(null); setRecErr(''); return; }
    let live = true;
    setRec(null); setRecErr('');
    getEnvironmentBuild(id, picked).then((r) => { if (live) setRec(r); }).catch(() => { if (live) setRecErr(`The log of version ${picked} could not be read.`); });
    return () => { live = false; };
  }, [id, picked, build?.version]);
  // the log follows its end while it grows, unless the reader scrolled up
  const atEnd = useRef(true);
  useEffect(() => { const el = term.current; if (el && atEnd.current) el.scrollTop = el.scrollHeight; }, [showing?.log, showing?.version]);

  const rows = versionRows(env);
  const head = showing ? buildHead(showing, showing.status === 'building' ? elapsed : null) : null;

  return (
    <div className="eo-builds">
      {showing && head ? (
        <section className={`eo-run is-${showing.status}`} aria-label={head.title}>
          <div className="eo-run-head">
            <span className={`pill ${VERSION_STATUS[showing.status].tone}`}>{showing.status === 'building' ? <span className="dot run" aria-hidden="true" /> : null}{VERSION_STATUS[showing.status].label}</span>
            <b>{head.title}</b>
            {picked !== null && picked !== build?.version ? <button type="button" className="link-q" onClick={() => setPicked(null)}>Back to the latest</button> : null}
          </div>
          <p className={`eo-run-line${showing.status === 'failed' ? ' bad' : ''}`}>{showing.status === 'failed' ? <><b>Why it failed:</b> {head.line}</> : head.line}</p>
          {showing.log || showing.status === 'building' ? (
            <pre className="eo-term" ref={term} aria-live={showing.status === 'building' ? 'polite' : undefined} aria-label={`Build log of version ${showing.version}`} tabIndex={0}
              onScroll={(ev) => { const el = ev.currentTarget; atEnd.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24; }}>
              {(showing.log || '').split('\n').map((l, k) => <span key={k} className={l.startsWith('$ ') ? 'cmd' : undefined}>{l}{'\n'}</span>)}
              {showing.status === 'building' ? <span className="eo-cursor" aria-hidden="true" /> : null}
            </pre>
          ) : <p className="eo-none left">This build kept no log.</p>}
        </section>
      ) : recErr ? <p className="eo-msg bad">{recErr}</p>
        : picked !== null ? <Skel label="Opening the log"><SkLine w="40%" /><SkLine h={140} r={12} style={{ marginTop: 12 }} /></Skel>
          : <p className="eo-none left">{env.files.count ? 'No builds yet.' : 'No builds yet. Add files first.'}</p>}

      {rows.length ? (
        <>
          <h4 className="eo-h">Versions</h4>
          <div className="eo-v eo-vh" aria-hidden="true">
            <span>Version</span><span>Status</span><span className="eo-c-start">Started</span><span className="eo-c-took">Took</span>
            <span className="eo-c-files">Files</span><span className="eo-c-pk">Packages</span><span className="eo-c-act" />
          </div>
          <ul className="eo-vt" aria-label="Versions">
            {rows.map((v) => {
              const st = VERSION_STATUS[v.status] || VERSION_STATUS.unknown;
              const shown = (picked ?? build?.version) === v.version;
              const files = typeof v.files === 'number' && v.status === 'ready' ? plural(v.files, 'file') : '';
              const pk = typeof v.packages === 'number' && v.status === 'ready' ? plural(v.packages, 'package') : '';
              return (
                <li key={v.version} className={`eo-v${shown ? ' shown' : ''}`}>
                  <span className="eo-c-ver"><b>Version {v.version}</b>{v.active ? <span className="chip eo-inuse">In use</span> : null}
                    <small className="eo-c-sub">{[when(v.started_at), v.status === 'building' ? '' : took(v.started_at, v.finished_at), files, pk].filter(Boolean).join(' · ')}</small></span>
                  <span><span className={`pill ${st.tone}`}>{st.label}</span></span>
                  <span className="eo-c-start">{when(v.started_at)}</span>
                  <span className="eo-c-took">{v.status === 'building' ? '' : took(v.started_at, v.finished_at)}</span>
                  <span className="eo-c-files">{files}</span>
                  <span className="eo-c-pk">{pk}</span>
                  <span className="eo-c-act">
                    <button type="button" className="link-q" aria-pressed={shown} aria-label={`${v.status === 'failed' ? 'Why version' : 'Log of version'} ${v.version} ${v.status === 'failed' ? 'failed' : ''}`.trim()}
                      onClick={() => setPicked(v.version === build?.version ? null : v.version)}>{v.status === 'failed' ? 'Why' : 'Log'}</button>
                    {v.canUse ? <button type="button" className="btn small line" disabled={busy} onClick={() => onUse(v.version)}>Use this version</button> : null}
                  </span>
                  {v.status === 'failed' && v.error ? <small className="eo-v-err">{v.error}</small> : null}
                </li>
              );
            })}
          </ul>
        </>
      ) : null}
    </div>
  );
}

// ── Details ───────────────────────────────────────────────────────────────────────────────────────

function DetailsPane({ env, form, setForm, users }: {
  env: Environment; form: { name: string; description: string; entry: string };
  setForm: (f: { name: string; description: string; entry: string }) => void; users: EnvUser[] | null;
}) {
  return (
    <div className="eo-details">
      <div className="set-f"><label htmlFor="eoName">Name</label>
        <input id="eoName" className={`set-in${form.name.trim() ? '' : ' bad'}`} value={form.name} onChange={(ev) => setForm({ ...form, name: ev.target.value })} /></div>
      <div className="set-f"><label htmlFor="eoDesc">Description <span className="muted">optional</span></label>
        <input id="eoDesc" className="set-in" value={form.description} placeholder="What the project does" onChange={(ev) => setForm({ ...form, description: ev.target.value })} /></div>
      <div className="set-f"><label htmlFor="eoEntry">How it is run <span className="muted">optional</span></label>
        <input id="eoEntry" className="set-in mono" value={form.entry} placeholder="python3 run.py --episode <id>" spellCheck={false} onChange={(ev) => setForm({ ...form, entry: ev.target.value })} /></div>
      <div className="set-f"><span className="eo-l">Where tasks find it</span>
        <div className="set-ro"><code>{env.mount}</code></div></div>
      <div className="set-f"><span className="eo-l">Used by</span>
        {users === null ? <Skel label="Reading the setups that use it"><SkLine w="50%" /></Skel>
          : users.length ? (
            <ul className="eo-users">{users.map((u) => <li key={u.id}><Link className="link-q inl" href={setupHref(u.id)}>{u.name || 'Untitled setup'}</Link></li>)}</ul>
          ) : <p className="set-help">No setup uses it yet.</p>}
      </div>
    </div>
  );
}
