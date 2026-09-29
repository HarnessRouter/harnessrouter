'use client';
// One environment, from Richard's console design (2026-09-28): a white head with the back link
// and the name; a card with two tabs, Project files (a tree with folder counts, find-a-file, new
// file / new folder / upload, and the file open beside it with line numbers) and Packages (what
// the active build installed). Above the card, what the service knows: status, version, mount,
// the Harnesses that read it, and the actions: build, import, rename, delete. Nothing here is
// derived on the client; every count and status is the service's.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useParams } from 'next/navigation';
import { SkelPage } from '@/components/Skel';
import { PrismAsync as SyntaxHL } from 'react-syntax-highlighter';
import oneLightTheme from 'react-syntax-highlighter/dist/esm/styles/prism/one-light';
import {
  buildEnvironment, deleteEnvironmentPath, environmentHarnesses,
  fmtBytes, getEnvironment, getEnvironmentBuild, importEnvironmentArchive, importEnvironmentGit, listEnvironmentFiles, listRuntimes,
  makeEnvironmentDir, readEnvironmentFile, updateEnvironment, writeEnvironmentFile,
  type Environment, type EnvironmentBuildRecord, type EnvironmentFileEntry, type EnvironmentRuntimes, type Manager, checkPackage,
} from '@/lib/environments';

const MANAGERS: Manager[] = ['pip', 'npm', 'apt'];
const SPEC_HINT: Record<Manager, string> = { pip: 'name==1.0', npm: 'name@1.0', apt: 'name' };
/** The parts of a spec as the row shows them: the name, and the version when one was given. */
function specParts(spec: string, m: Manager): { name: string; version: string } {
  if (m === 'npm') { const i = spec.lastIndexOf('@'); return i > 0 ? { name: spec.slice(0, i), version: spec.slice(i + 1) } : { name: spec, version: '' }; }
  for (const sep of ['==', '>=', '<=', '~=', '!=', '=']) { const i = spec.indexOf(sep); if (i > 0) return { name: spec.slice(0, i), version: (sep === '==' || sep === '=' ? '' : sep) + spec.slice(i + sep.length) }; }
  return { name: spec, version: '' };
}
/** The highlighter's language for a file, by extension; plain text for anything else. */
const LANG: Record<string, string> = {
  py: 'python', js: 'javascript', mjs: 'javascript', cjs: 'javascript', ts: 'typescript', tsx: 'tsx', jsx: 'jsx', json: 'json',
  yaml: 'yaml', yml: 'yaml', md: 'markdown', html: 'markup', htm: 'markup', xml: 'markup', svg: 'markup', css: 'css', scss: 'scss',
  sh: 'bash', bash: 'bash', zsh: 'bash', toml: 'toml', ini: 'ini', cfg: 'ini', env: 'bash', sql: 'sql', go: 'go', rs: 'rust',
  java: 'java', rb: 'ruby', php: 'php', c: 'c', h: 'c', cpp: 'cpp', hpp: 'cpp', cs: 'csharp', swift: 'swift', kt: 'kotlin',
  r: 'r', txt: 'text', csv: 'text', lock: 'text', dockerfile: 'docker', makefile: 'makefile',
};
const langOf = (path: string) => { const name = path.split('/').pop() || ''; const ext = name.includes('.') ? name.split('.').pop()!.toLowerCase() : name.toLowerCase(); return LANG[ext] || 'text'; };
const STATUS_CLASS: Record<Environment['status'], string> = { empty: 'neutral', building: 'warn', ready: 'ok', failed: 'err' };

type Node = { name: string; path: string; dir: boolean; bytes: number; children: Node[]; count: number };

/** The flat listing as a tree, directories first, each directory counting the files under it. */
function treeOf(entries: EnvironmentFileEntry[]): Node[] {
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

export default function EnvironmentPage() {
  const { id } = useParams<{ id: string }>();
  const [env, setEnv] = useState<Environment | null>(null);
  const [entries, setEntries] = useState<EnvironmentFileEntry[] | null>(null);
  const [harnesses, setHarnesses] = useState<{ id: string; name: string; base: string }[]>([]);
  const [tab, setTab] = useState<'files' | 'packages'>('files');
  const [q, setQ] = useState('');
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [sel, setSel] = useState<string>('');          // the highlighted node: a file or a folder (where new files land)
  const [openPath, setOpenPath] = useState<string>(''); // the file in the viewer; selecting a folder leaves it in place
  const [file, setFile] = useState<{ text: string | null; bytes: number; type: string } | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState('');
  const [build, setBuild] = useState<EnvironmentBuildRecord | null>(null);
  const [buildOpen, setBuildOpen] = useState(false);       // the build pop-up: opens when a build starts, stays until closed
  const termRef = useRef<HTMLPreElement>(null);
  const [segment, setSegment] = useState<Manager>('pip');
  const [declared, setDeclared] = useState<Record<Manager, string[]> | null>(null);   // what the page holds; saved from the head
  const [python, setPython] = useState('');
  const [runtimes, setRuntimes] = useState<EnvironmentRuntimes | null>(null);
  const [spec, setSpec] = useState('');
  const [checking, setChecking] = useState(false);          // the registry is being asked about the spec in the Add field
  const [addErr, setAddErr] = useState('');                  // what the registry said when it refused the spec
  const [resolved, setResolved] = useState<Record<string, string>>({});   // `${manager}:${name}` → the version the registry reported on Add
  const [now, setNow] = useState(() => Date.now());          // ticks while a build runs, for the elapsed seconds
  const [pkgDirty, setPkgDirty] = useState(false);
  const [gitOpen, setGitOpen] = useState(false);
  const [menu, setMenu] = useState<'add' | null>(null);
  const [git, setGit] = useState({ url: '', ref: '', replace: false });
  const [newPath, setNewPath] = useState<{ kind: 'file' | 'dir'; value: string } | null>(null);
  const uploadRef = useRef<HTMLInputElement>(null);
  const archiveRef = useRef<HTMLInputElement>(null);

  const reload = useCallback(async () => {
    try {
      const [e, t, h] = await Promise.all([getEnvironment(id), listEnvironmentFiles(id), environmentHarnesses(id).catch(() => [])]);
      // The latest build's record is read BEFORE the page state moves: a status of building opens
      // the pop-up, and with the record read afterwards the pop-up showed the previous version's
      // outcome for a moment (the hosted port's finding, 2026-09-29).
      const b = e.latestVersion ? await getEnvironmentBuild(id, e.latestVersion).catch(() => null) : null;
      setEnv(e); setEntries(t.entries); setHarnesses(h); setBuild(b);
      if (!pkgDirty) { setDeclared({ pip: (e.declared?.pip || []).map((x) => x.spec), npm: (e.declared?.npm || []).map((x) => x.spec), apt: (e.declared?.apt || []).map((x) => x.spec) }); setPython(e.runtime?.python || ''); }
    } catch (e) { setErr(e instanceof Error ? e.message : 'The environment could not be read.'); }
  }, [id, pkgDirty]);
  useEffect(() => { void reload(); }, [reload]);
  useEffect(() => { listRuntimes().then(setRuntimes).catch(() => setRuntimes(null)); }, []);
  useEffect(() => {
    if (!menu) return;
    const off = (ev: MouseEvent) => { if (!(ev.target as HTMLElement).closest('.env-menu-wrap')) setMenu(null); };
    window.addEventListener('mousedown', off);
    return () => window.removeEventListener('mousedown', off);
  }, [menu]);
  useEffect(() => {
    if (env?.status !== 'building') return;
    setBuildOpen(true);
    const t = setInterval(() => void reload(), 3000);
    const tick = setInterval(() => setNow(Date.now()), 1000);
    return () => { clearInterval(t); clearInterval(tick); };
  }, [env?.status, reload]);
  useEffect(() => { const el = termRef.current; if (el) el.scrollTop = el.scrollHeight; }, [build?.log, buildOpen]);

  const tree = useMemo(() => treeOf(entries || []), [entries]);
  const needle = q.trim().toLowerCase();
  const matches = useMemo(() => (needle ? (entries || []).filter((e) => !e.dir && e.path.toLowerCase().includes(needle)) : []), [entries, needle]);

  const openFile = async (path: string) => {
    setSel(path); setOpenPath(path); setEditing(null);
    try { setFile(await readEnvironmentFile(id, path)); } catch (e) { setFile(null); setErr(e instanceof Error ? e.message : 'The file could not be read.'); }
  };
  const toggle = (p: string) => setOpen((s) => { const n = new Set(s); if (n.has(p)) n.delete(p); else n.add(p); return n; });
  const parentDir = () => { if (!sel) return ''; const e = (entries || []).find((x) => x.path === sel); if (e?.dir) return sel; const i = sel.lastIndexOf('/'); return i < 0 ? '' : sel.slice(0, i); };

  const act = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label); setErr('');
    try { await fn(); await reload(); } catch (e) { setErr(e instanceof Error ? e.message : `${label} failed.`); }
    finally { setBusy(''); }
  };
  /** Save changes, from the head: the open file's edit, the declared packages and the runtime, then a
   *  build, so what a session reads is what the page shows. */
  const saveChanges = () => act('save', async () => {
    if (editing !== null) {
      await writeEnvironmentFile(id, openPath, editing);
      setFile({ text: editing, bytes: new TextEncoder().encode(editing).length, type: file?.type || 'text/plain' }); setEditing(null);
    }
    if (pkgDirty && declared && env) {
      await updateEnvironment(id, { name: env.name, description: env.description, entry: env.entry, packages: declared, runtime: { python } });
      setPkgDirty(false);
    }
    setBuild(null);            // the pop-up waits for the new build's record, never showing the old one
    await buildEnvironment(id);
  });
  /** Add asks the registry first: a name that is not there, or a pin that was never published, is
   *  refused here with the registry's own answer instead of failing a build minutes later. What
   *  the registry reported (the pin, else the latest) is what the row shows until a build installs it. */
  const addSpec = async () => {
    const t = spec.trim();
    if (!t || !declared || checking) return;
    setChecking(true); setAddErr('');
    try {
      const c = await checkPackage(segment, t);
      if (c.exists === false || (c.exists && c.error)) { setAddErr(c.error || `${c.name} was not found.`); return; }
      if (c.error) setAddErr(c.error);   // the registry could not be asked: added anyway; the build is then the check
      const name = specParts(t, segment).name;
      setDeclared({ ...declared, [segment]: [...declared[segment].filter((x) => specParts(x, segment).name !== name), t] });
      setResolved((r) => ({ ...r, [`${segment}:${name.toLowerCase()}`]: c.version || c.latest || '' }));
      setSpec(''); setPkgDirty(true);
    } catch (e) { setAddErr(e instanceof Error ? e.message : 'The package could not be checked.'); }
    finally { setChecking(false); }
  };
  const dropSpec = (m: Manager, x: string) => { if (!declared) return; setDeclared({ ...declared, [m]: declared[m].filter((y) => y !== x) }); setPkgDirty(true); };
  const dirty = editing !== null || pkgDirty;
  const installedVersion = (m: Manager, name: string) => env?.packages.find((p) => p.manager === m && p.name.toLowerCase() === name.toLowerCase())?.version || '';
  /** What a row's version column says: the version the active build installed, else that a build
   *  is installing it now, else that it installs on save, with the version the registry reported. */
  const rowState = (m: Manager, x: string): { text: string; note: string } => {
    const p = specParts(x, m);
    const installed = installedVersion(m, p.name);
    if (installed && (!p.version || p.version === installed)) return { text: installed, note: '' };
    const known = p.version || resolved[`${m}:${p.name.toLowerCase()}`] || '';
    if (env?.status === 'building') return { text: known, note: 'installing' };
    return { text: known || 'latest', note: 'installs on save' };
  };
  const buildElapsed = build?.started_at ? Math.max(0, Math.round(now / 1000 - build.started_at)) : null;
  const createPath = () => act('create', async () => {
    if (!newPath?.value.trim()) return;
    const base = parentDir(); const p = (base ? base + '/' : '') + newPath.value.trim().replace(/^\/+/, '');
    if (newPath.kind === 'dir') { await makeEnvironmentDir(id, p); setOpen((s) => new Set(s).add(p)); }
    else { await writeEnvironmentFile(id, p, ''); setNewPath(null); await openFile(p); return; }
    setNewPath(null);
  });
  const upload = (files: FileList | null) => act('upload', async () => {
    if (!files?.length) return;
    const base = parentDir();
    for (const f of Array.from(files)) {
      const rel = (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name;
      await writeEnvironmentFile(id, (base ? base + '/' : '') + rel, f);
    }
  });
  const importArchive = (files: FileList | null) => act('import', async () => { if (files?.[0]) await importEnvironmentArchive(id, files[0]); });
  const importGit = () => act('import', async () => { if (!git.url.trim()) return; await importEnvironmentGit(id, git.url.trim(), git.ref.trim(), git.replace); setGitOpen(false); });
  const remove = (p: string) => act('remove', async () => { await deleteEnvironmentPath(id, p); if (sel === p || sel.startsWith(p + '/')) setSel(''); if (openPath === p || openPath.startsWith(p + '/')) { setOpenPath(''); setFile(null); } });
  const startBuild = () => act('build', async () => { await buildEnvironment(id); setTab('packages'); setBuildOpen(true); });

  if (!env && !err) return <SkelPage />;

  const renderNode = (n: Node, depth: number): React.ReactNode => (
    <div key={n.path}>
      <div className={'env-node' + (sel === n.path ? ' is-selected' : '')} style={{ paddingLeft: 12 + depth * 14 }}
           onClick={() => (n.dir ? (toggle(n.path), setSel(n.path)) : void openFile(n.path))}
           onKeyDown={(ev) => { if (ev.key === 'Enter') { if (n.dir) toggle(n.path); else void openFile(n.path); } }} role="treeitem" tabIndex={0}
           aria-expanded={n.dir ? open.has(n.path) : undefined}>
        {n.dir ? <iconify-icon icon={open.has(n.path) ? 'tabler:chevron-down' : 'tabler:chevron-right'} className="env-chev"></iconify-icon> : <span className="env-chev" />}
        <iconify-icon icon={n.dir ? 'tabler:folder' : 'tabler:file'}></iconify-icon>
        <span className="env-node-name">{n.name}</span>
        {n.dir && <span className="env-node-count">{n.count}</span>}
        <button className="env-node-x" type="button" aria-label={`Remove ${n.name}`} title="Remove" onClick={(ev) => { ev.stopPropagation(); void remove(n.path); }}>
          <iconify-icon icon="tabler:x"></iconify-icon></button>
      </div>
      {n.dir && open.has(n.path) && n.children.map((c) => renderNode(c, depth + 1))}
    </div>
  );


  return (
    <section className="env-root" id="view-environment">
      <div className="env-head">
        <a className="env-back" href="/environments"><iconify-icon icon="tabler:arrow-left"></iconify-icon>Environments</a>
        {env && (
          <div className="env-title-row">
            <h1>{env.name}</h1>
            <button className="button primary" type="button" disabled={env.status !== 'building' && (!dirty || busy === 'save')}
              onClick={() => { if (env.status === 'building') setBuildOpen(true); else void saveChanges(); }}>
              {busy === 'save' ? 'Saving\u2026' : env.status === 'building' ? 'Building\u2026' : 'Save changes'}</button>
          </div>
        )}
      </div>

      <div className="env-body">
        {err && <div className="hr-error" role="alert">{err}</div>}
        {env?.status === 'failed' && build?.error && (
          <div className="hr-error env-build-failed" role="alert">
            <div><strong>The last build failed.</strong> {build.error} Fix the packages or the files and save again.</div>
            <button className="button small" type="button" onClick={() => setBuildOpen(true)}>Open the log</button>
          </div>
        )}
        {env && (
          <div className="env-card">
            <div className="env-card-head">
              <div className="env-tabs" role="tablist">
                <button type="button" role="tab" aria-selected={tab === 'files'} className={'env-tab' + (tab === 'files' ? ' is-on' : '')} onClick={() => setTab('files')}>Project files <span>{env.files.count}</span></button>
                <button type="button" role="tab" aria-selected={tab === 'packages'} className={'env-tab' + (tab === 'packages' ? ' is-on' : '')} onClick={() => setTab('packages')}>Packages <span>{declared ? MANAGERS.reduce((a, m) => a + declared[m].length, 0) : 0}</span></button>
              </div>
              {tab === 'packages' && declared && (
                <>
                  <div className="env-segments" role="tablist" aria-label="Package manager">
                    {MANAGERS.map((m) => (
                      <button key={m} type="button" role="tab" aria-selected={segment === m} className={'env-segment' + (segment === m ? ' is-on' : '')} onClick={() => setSegment(m)}
                        disabled={m === 'apt' && runtimes !== null && !runtimes.apt} title={m === 'apt' && runtimes !== null && !runtimes.apt ? 'apt is not available on this instance' : undefined}>
                        {m} <span>{declared[m].length}</span></button>
                    ))}
                  </div>
                  <label className="env-runtime">
                    {segment === 'pip' ? 'Python' : segment === 'npm' ? 'Node' : (runtimes?.os.name ? runtimes.os.name[0].toUpperCase() + runtimes.os.name.slice(1) : 'OS')}
                    {segment === 'pip' ? (
                      <select value={python || (runtimes?.python[0] ?? '')} onChange={(ev) => { setPython(ev.target.value); setPkgDirty(true); }}>
                        {(runtimes?.python.length ? runtimes.python : [python || '']).map((v) => <option key={v} value={v}>{v || 'default'}</option>)}
                      </select>
                    ) : segment === 'npm' ? (
                      <select value={runtimes?.node[0] ?? ''} disabled><option value={runtimes?.node[0] ?? ''}>{runtimes?.node[0] ?? ''}</option></select>
                    ) : (
                      <select value={runtimes?.os.version ?? ''} disabled><option value={runtimes?.os.version ?? ''}>{runtimes?.os.version ?? ''}</option></select>
                    )}
                  </label>
                  <form className="env-add" onSubmit={(ev) => { ev.preventDefault(); void addSpec(); }}>
                    <input value={spec} placeholder={SPEC_HINT[segment]} aria-label={`Add a ${segment} package`} spellCheck={false} onChange={(ev) => { setSpec(ev.target.value); if (addErr) setAddErr(''); }} />
                    <button className="button" type="submit" disabled={!spec.trim() || checking}>{checking ? 'Checking\u2026' : 'Add'}</button>
                  </form>
                </>
              )}
            </div>

            {tab === 'files' && (
              <div className="env-files">
                <aside className="env-tree-pane">
                  <div className="env-tree-tools">
                    <label className="env-find"><iconify-icon icon="tabler:search"></iconify-icon><input value={q} placeholder="Find a file" aria-label="Find a file" onChange={(ev) => setQ(ev.target.value)} /></label>
                    <button className="icon-button" type="button" title="New file" aria-label="New file" onClick={() => setNewPath({ kind: 'file', value: '' })}><iconify-icon icon="tabler:file-plus"></iconify-icon></button>
                    <button className="icon-button" type="button" title="New folder" aria-label="New folder" onClick={() => setNewPath({ kind: 'dir', value: '' })}><iconify-icon icon="tabler:folder-plus"></iconify-icon></button>
                    <span className="env-menu-wrap">
                      <button className="icon-button" type="button" title="Upload files, or import a project" aria-label="Upload files, or import a project" aria-haspopup="menu" aria-expanded={menu === 'add'} onClick={() => setMenu(menu === 'add' ? null : 'add')}><iconify-icon icon="tabler:upload"></iconify-icon></button>
                      {menu === 'add' && (
                        <div className="env-menu is-right" role="menu">
                          <button type="button" role="menuitem" onClick={() => { setMenu(null); uploadRef.current?.click(); }}><iconify-icon icon="tabler:upload"></iconify-icon>Upload files</button>
                          <button type="button" role="menuitem" onClick={() => { setMenu(null); archiveRef.current?.click(); }}><iconify-icon icon="tabler:file-zip"></iconify-icon>Import an archive</button>
                          <button type="button" role="menuitem" onClick={() => { setMenu(null); setGitOpen(true); }}><iconify-icon icon="tabler:brand-git"></iconify-icon>Import from git</button>
                        </div>
                      )}
                    </span>
                    <input ref={uploadRef} type="file" hidden multiple onChange={(ev) => { void upload(ev.target.files); ev.target.value = ''; }} />
                    <input ref={archiveRef} type="file" hidden accept=".zip,.tar,.tgz,.tar.gz" onChange={(ev) => { void importArchive(ev.target.files); ev.target.value = ''; }} />
                  </div>
                  {newPath && (
                    <div className="env-newpath">
                      <span className="env-dim">{parentDir() ? parentDir() + '/' : ''}</span>
                      <input value={newPath.value} autoFocus placeholder={newPath.kind === 'dir' ? 'folder name' : 'file name'} aria-label={newPath.kind === 'dir' ? 'Folder name' : 'File name'}
                        onChange={(ev) => setNewPath({ ...newPath, value: ev.target.value })}
                        onKeyDown={(ev) => { if (ev.key === 'Enter') void createPath(); if (ev.key === 'Escape') setNewPath(null); }} />
                      <button className="button small" type="button" onClick={() => void createPath()}>Add</button>
                    </div>
                  )}
                  <div className="env-tree" role="tree">
                    {needle ? (
                      matches.length ? matches.map((m) => (
                        <div key={m.path} className={'env-node' + (sel === m.path ? ' is-selected' : '')} style={{ paddingLeft: 12 }} role="treeitem" tabIndex={0}
                             onClick={() => void openFile(m.path)} onKeyDown={(ev) => { if (ev.key === 'Enter') void openFile(m.path); }}>
                          <span className="env-chev" /><iconify-icon icon="tabler:file"></iconify-icon><span className="env-node-name">{m.path}</span></div>
                      )) : <div className="env-tree-empty">No file matches.</div>
                    ) : tree.length ? tree.map((n) => renderNode(n, 0)) : (
                      <div className="env-tree-empty">No files yet.</div>
                    )}
                  </div>
                </aside>
                <div className="env-view">
                  {!entries?.length && !needle ? (
                    <div className="env-onboard is-files">
                      <h2>Put the project in</h2>
                      <p>The whole folder, as it is on your machine. Folders and relative paths are kept; a build installs its packages afterwards.</p>
                      <div className="env-choices">
                        <button type="button" className="env-choice" onClick={() => archiveRef.current?.click()}>
                          <iconify-icon icon="tabler:file-zip"></iconify-icon><strong>Import an archive</strong><em>A zip or tar of the project folder.</em></button>
                        <button type="button" className="env-choice" onClick={() => setGitOpen(true)}>
                          <iconify-icon icon="tabler:brand-git"></iconify-icon><strong>Import from git</strong><em>A repository URL and a branch or tag.</em></button>
                        <button type="button" className="env-choice" onClick={() => uploadRef.current?.click()}>
                          <iconify-icon icon="tabler:upload"></iconify-icon><strong>Upload files</strong><em>Pick files; they land at the root.</em></button>
                      </div>
                      <span className="env-onboard-note">Or start from nothing with New file in the tree.</span>
                    </div>
                  ) : openPath && file ? (
                    <>
                      <div className="env-view-head">
                        <code>{openPath}</code>
                        <span className="env-dim">{fmtBytes(file.bytes)}{editing !== null ? ' \u00b7 edited' : ''}</span>
                        {editing !== null && <button className="button small" type="button" onClick={() => setEditing(null)}>Discard</button>}
                      </div>
                      {file.text === null ? (
                        <div className="env-binary">A binary file ({file.type}, {fmtBytes(file.bytes)}). It is in the environment as uploaded.</div>
                      ) : editing !== null ? (
                        <textarea className="env-editor" value={editing} spellCheck={false} autoFocus onChange={(ev) => setEditing(ev.target.value)} />
                      ) : (
                        <div className="env-code" title="Click to edit" onClick={() => setEditing(file.text || '')}>
                          <SyntaxHL language={langOf(openPath)} style={oneLightTheme} showLineNumbers
                            customStyle={{ margin: 0, padding: '14px 0', background: 'transparent', fontSize: 12.5, lineHeight: 1.7, whiteSpace: 'pre', overflowX: 'auto' }}
                            codeTagProps={{ style: { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' } }}
                            lineNumberStyle={{ minWidth: 48, paddingRight: 16, textAlign: 'right', color: 'var(--line-strong)', userSelect: 'none' }}>
                            {file.text || ' '}
                          </SyntaxHL>
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="env-view-empty">{entries?.length ? 'Open a file to read it.' : ''}</div>
                  )}
                </div>
              </div>
            )}

            {tab === 'packages' && declared && (
              <div className="env-packages">
                {addErr && <div className="env-add-error" role="alert">{addErr}</div>}
                {declared[segment].length ? declared[segment].map((x) => {
                  const p = specParts(x, segment);
                  const st = rowState(segment, x);
                  return (
                    <div key={x} className="env-pkg">
                      <code className="env-pkg-name">{p.name}</code>
                      <span className="env-pkg-version">{st.text}{st.note && <em className="env-pkg-note">{st.note}</em>}</span>
                      <button className="env-pkg-x" type="button" aria-label={`Remove ${p.name}`} onClick={() => dropSpec(segment, x)}><iconify-icon icon="tabler:x"></iconify-icon></button>
                    </div>
                  );
                }) : (
                  <div className="env-pkg-empty">No {segment} packages yet. Add one above as <code>{SPEC_HINT[segment]}</code>{segment === 'pip' && ' (the project\u2019s requirements.txt is installed too)'}{segment === 'npm' && ' (the project\u2019s package.json is installed too)'}.</div>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {gitOpen && (
        <div className="kit-overlay" role="dialog" aria-modal="true" aria-labelledby="env-git-title" onMouseDown={(ev) => { if (ev.target === ev.currentTarget) setGitOpen(false); }}>
          <div className="kit-dialog">
            <button className="kit-dialog-x" type="button" onClick={() => setGitOpen(false)} aria-label="Close"><iconify-icon icon="tabler:x"></iconify-icon></button>
            <h2 id="env-git-title">Import from git</h2>
            <p className="kit-dialog-sub">The repository&apos;s tree at a branch or tag, without its history. A private repository needs a token in the URL.</p>
            <div className="kit-custom">
              <label className="kit-field"><span>Repository URL</span><input value={git.url} autoFocus placeholder="https://github.com/org/project" onChange={(ev) => setGit({ ...git, url: ev.target.value })} /></label>
              <label className="kit-field"><span>Branch or tag</span><input value={git.ref} placeholder="main" onChange={(ev) => setGit({ ...git, ref: ev.target.value })} /></label>
              <label className="db-sample"><input type="checkbox" checked={git.replace} onChange={(ev) => setGit({ ...git, replace: ev.target.checked })} /><span><strong>Replace the current files</strong><em>Otherwise the repository lands over what is here.</em></span></label>
            </div>
            <div className="kit-dialog-actions">
              <span className="kit-dialog-spacer" />
              <button className="button" type="button" onClick={() => setGitOpen(false)}>Cancel</button>
              <button className="button primary" type="button" disabled={busy === 'import' || !git.url.trim()} onClick={() => void importGit()}>{busy === 'import' ? 'Importing…' : 'Import'}</button>
            </div>
          </div>
        </div>
      )}
      {buildOpen && build && (
        <div className="kit-overlay" role="dialog" aria-modal="true" aria-labelledby="env-build-title"
             onMouseDown={(ev) => { if (ev.target === ev.currentTarget) setBuildOpen(false); }}>
          <div className="kit-dialog env-build-dialog">
            <button className="kit-dialog-x" type="button" onClick={() => setBuildOpen(false)} aria-label="Close"><iconify-icon icon="tabler:x"></iconify-icon></button>
            <h2 id="env-build-title">{build.status === 'building' ? `Building version ${build.version}` : build.status === 'ready' ? `Version ${build.version} is ready` : `Version ${build.version} failed`}</h2>
            <p className="kit-dialog-sub">
              {build.status === 'building' && <>{build.stage || 'starting'}{buildElapsed !== null && <> · {buildElapsed} s</>}</>}
              {build.status === 'ready' && <>{build.started_at && build.finished_at ? `${Math.max(0, build.finished_at - build.started_at)} s` : ''}{build.packages ? ` \u00b7 ${build.packages.length} ${build.packages.length === 1 ? 'package' : 'packages'}` : ''}{typeof build.files === 'number' ? ` \u00b7 ${build.files} files` : ''}</>}
              {build.status === 'failed' && (build.error || 'The build failed.')}
            </p>
            <pre className="env-term" ref={termRef} aria-live="polite">
              {(build.log || '').split('\n').map((l, k) => <span key={k} className={l.startsWith('$ ') ? 'env-term-cmd' : undefined}>{l}{'\n'}</span>)}
              {build.status === 'building' && <span className="env-term-cursor" aria-hidden="true" />}
            </pre>
            <div className="kit-dialog-actions">
              <span className="kit-dialog-spacer" />
              <button className="button" type="button" onClick={() => setBuildOpen(false)}>{build.status === 'building' ? 'Hide' : 'Close'}</button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
