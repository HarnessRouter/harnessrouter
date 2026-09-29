'use client';
// One environment, from Richard's console design (2026-09-28): a white head with the back link
// and the name; a card with two tabs, Project files (a tree with folder counts, find-a-file, new
// file / new folder / upload, and the file open beside it with line numbers) and Packages (what
// the active build installed). Above the card, what the service knows: status, version, mount,
// the Harnesses that read it, and the actions: build, import, rename, delete. Nothing here is
// derived on the client; every count and status is the service's.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { SkelPage } from '@/components/Skel';
import {
  activateEnvironmentVersion, buildEnvironment, deleteEnvironment, deleteEnvironmentPath, environmentHarnesses,
  fmtBytes, getEnvironment, getEnvironmentBuild, importEnvironmentArchive, importEnvironmentGit, listEnvironmentFiles,
  makeEnvironmentDir, readEnvironmentFile, updateEnvironment, writeEnvironmentFile,
  type Environment, type EnvironmentBuildRecord, type EnvironmentFileEntry,
} from '@/lib/environments';

const STATUS_LABEL: Record<Environment['status'], string> = { empty: 'Not built', building: 'Building', ready: 'Ready', failed: 'Build failed' };
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
  const router = useRouter();
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
  const [showLog, setShowLog] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [meta, setMeta] = useState({ name: '', description: '', entry: '' });
  const [gitOpen, setGitOpen] = useState(false);
  const [git, setGit] = useState({ url: '', ref: '', replace: false });
  const [newPath, setNewPath] = useState<{ kind: 'file' | 'dir'; value: string } | null>(null);
  const uploadRef = useRef<HTMLInputElement>(null);
  const archiveRef = useRef<HTMLInputElement>(null);

  const reload = useCallback(async () => {
    try {
      const [e, t, h] = await Promise.all([getEnvironment(id), listEnvironmentFiles(id), environmentHarnesses(id).catch(() => [])]);
      setEnv(e); setEntries(t.entries); setHarnesses(h); setMeta({ name: e.name, description: e.description, entry: e.entry });
      if (e.latestVersion) setBuild(await getEnvironmentBuild(id, e.latestVersion).catch(() => null));
    } catch (e) { setErr(e instanceof Error ? e.message : 'The environment could not be read.'); }
  }, [id]);
  useEffect(() => { void reload(); }, [reload]);
  useEffect(() => {
    if (env?.status !== 'building') return;
    const t = setInterval(() => void reload(), 3000);
    return () => clearInterval(t);
  }, [env?.status, reload]);

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
  const saveFile = () => act('save', async () => { if (editing === null) return; await writeEnvironmentFile(id, openPath, editing); setFile({ text: editing, bytes: new TextEncoder().encode(editing).length, type: file?.type || 'text/plain' }); setEditing(null); });
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
  const startBuild = () => act('build', async () => { await buildEnvironment(id); setTab('packages'); setShowLog(true); });
  const activate = (n: number) => act('activate', () => activateEnvironmentVersion(id, n));
  const saveMeta = () => act('rename', async () => { await updateEnvironment(id, meta); setRenaming(false); });
  const destroy = () => act('delete', async () => { await deleteEnvironment(id); router.push('/environments'); });

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

  const lines = editing === null && file?.text !== null && file?.text !== undefined ? file.text.split('\n') : [];

  return (
    <section className="view is-active collection-view" id="view-environment">
      <div className="env-head">
        <a className="env-back" href="/environments"><iconify-icon icon="tabler:arrow-left"></iconify-icon>Environments</a>
        {env && (
          <div className="env-title-row">
            {renaming ? (
              <div className="env-rename">
                <input value={meta.name} aria-label="Name" onChange={(ev) => setMeta({ ...meta, name: ev.target.value })} />
                <input value={meta.description} placeholder="Description" aria-label="Description" onChange={(ev) => setMeta({ ...meta, description: ev.target.value })} />
                <input value={meta.entry} placeholder="How it is run" aria-label="How it is run" onChange={(ev) => setMeta({ ...meta, entry: ev.target.value })} />
                <button className="button primary small" type="button" disabled={busy === 'rename'} onClick={() => void saveMeta()}>Save</button>
                <button className="button small" type="button" onClick={() => { setRenaming(false); setMeta({ name: env.name, description: env.description, entry: env.entry }); }}>Cancel</button>
              </div>
            ) : (
              <h1>{env.name}</h1>
            )}
            <div className="env-actions">
              <span className={'status ' + STATUS_CLASS[env.status]}>{STATUS_LABEL[env.status]}{env.version ? ` · v${env.version}` : ''}</span>
              <button className="button primary" type="button" disabled={env.status === 'building' || busy === 'build' || !env.files.count}
                      title={!env.files.count ? 'Add files first' : 'Snapshot the files and install the packages they declare'} onClick={() => void startBuild()}>
                <iconify-icon icon="tabler:hammer"></iconify-icon>{env.status === 'building' ? 'Building…' : env.version ? 'Rebuild' : 'Build'}</button>
              <button className="button" type="button" onClick={() => archiveRef.current?.click()} disabled={busy === 'import'}><iconify-icon icon="tabler:file-zip"></iconify-icon>Import archive</button>
              <input ref={archiveRef} type="file" hidden accept=".zip,.tar,.tgz,.tar.gz" onChange={(ev) => { void importArchive(ev.target.files); ev.target.value = ''; }} />
              <button className="button" type="button" onClick={() => setGitOpen(true)}><iconify-icon icon="tabler:brand-git"></iconify-icon>Import from git</button>
              <button className="button" type="button" onClick={() => setRenaming(true)}><iconify-icon icon="tabler:pencil"></iconify-icon>Rename</button>
              {confirmDelete ? (
                <span className="env-confirm">
                  <span>Delete every version and file?</span>
                  <button className="button danger small" type="button" disabled={busy === 'delete'} onClick={() => void destroy()}>Delete</button>
                  <button className="button small" type="button" onClick={() => setConfirmDelete(false)}>Keep</button>
                </span>
              ) : (
                <button className="button" type="button" onClick={() => setConfirmDelete(true)}><iconify-icon icon="tabler:trash"></iconify-icon>Delete</button>
              )}
            </div>
          </div>
        )}
        {env && (
          <div className="env-facts">
            <span><em>Path in every session</em><code>{env.mount}</code><span className="env-dim">read-only</span></span>
            {env.entry && <span><em>Run with</em><code>{env.entry}</code></span>}
            <span><em>Read by</em>{harnesses.length ? harnesses.map((h) => <a key={h.id} href={`/harnesses/${h.id}`}>{h.name}</a>) : <span className="env-dim">no Harness yet. Name it under a Harness&apos;s settings.</span>}</span>
            {env.description && <span><em>About</em>{env.description}</span>}
          </div>
        )}
      </div>

      <div className="env-body">
        {err && <div className="hr-error" role="alert">{err}</div>}
        {env && (
          <div className="env-card">
            <div className="env-tabs" role="tablist">
              <button type="button" role="tab" aria-selected={tab === 'files'} className={'env-tab' + (tab === 'files' ? ' is-on' : '')} onClick={() => setTab('files')}>Project files <span>{env.files.count}</span></button>
              <button type="button" role="tab" aria-selected={tab === 'packages'} className={'env-tab' + (tab === 'packages' ? ' is-on' : '')} onClick={() => setTab('packages')}>Packages <span>{env.status === 'ready' ? env.packages.length : (build?.packages?.length ?? 0)}</span></button>
            </div>

            {tab === 'files' && (
              <div className="env-files">
                <aside className="env-tree-pane">
                  <div className="env-tree-tools">
                    <label className="env-find"><iconify-icon icon="tabler:search"></iconify-icon><input value={q} placeholder="Find a file" aria-label="Find a file" onChange={(ev) => setQ(ev.target.value)} /></label>
                    <button className="icon-button" type="button" title="New file" aria-label="New file" onClick={() => setNewPath({ kind: 'file', value: '' })}><iconify-icon icon="tabler:file-plus"></iconify-icon></button>
                    <button className="icon-button" type="button" title="New folder" aria-label="New folder" onClick={() => setNewPath({ kind: 'dir', value: '' })}><iconify-icon icon="tabler:folder-plus"></iconify-icon></button>
                    <button className="icon-button" type="button" title="Upload files" aria-label="Upload files" onClick={() => uploadRef.current?.click()}><iconify-icon icon="tabler:upload"></iconify-icon></button>
                    <input ref={uploadRef} type="file" hidden multiple onChange={(ev) => { void upload(ev.target.files); ev.target.value = ''; }} />
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
                      <div className="env-tree-empty">No files yet. Upload files, or import an archive or a git repository from the header.</div>
                    )}
                  </div>
                </aside>
                <div className="env-view">
                  {openPath && file ? (
                    <>
                      <div className="env-view-head">
                        <code>{openPath}</code>
                        <span className="env-dim">{fmtBytes(file.bytes)}</span>
                        {file.text !== null && (editing === null
                          ? <button className="button small" type="button" onClick={() => setEditing(file.text || '')}>Edit</button>
                          : <><button className="button primary small" type="button" disabled={busy === 'save'} onClick={() => void saveFile()}>Save</button>
                              <button className="button small" type="button" onClick={() => setEditing(null)}>Cancel</button></>)}
                      </div>
                      {file.text === null ? (
                        <div className="env-binary">A binary file ({file.type}, {fmtBytes(file.bytes)}). It is in the environment as uploaded.</div>
                      ) : editing !== null ? (
                        <textarea className="env-editor" value={editing} spellCheck={false} onChange={(ev) => setEditing(ev.target.value)} />
                      ) : (
                        <pre className="env-code">{lines.map((l, i) => <span key={i} className="env-line"><span className="env-ln">{i + 1}</span><span className="env-lt">{l}</span></span>)}</pre>
                      )}
                    </>
                  ) : (
                    <div className="env-view-empty">{entries?.length ? 'Open a file to read it.' : ''}</div>
                  )}
                </div>
              </div>
            )}

            {tab === 'packages' && (
              <div className="env-packages">
                <div className="env-pk-head">
                  {env.status === 'ready' && env.version
                    ? <span>Installed in version {env.version}, the one every session reads.</span>
                    : env.status === 'building' ? <span>Building version {env.latestVersion}…</span>
                    : env.status === 'failed' ? <span>The last build failed. Fix the manifests and build again.</span>
                    : <span>Nothing built yet. Add a <code>requirements.txt</code>, <code>pyproject.toml</code> or <code>package.json</code> (and a <code>setup.sh</code> for anything else), then build.</span>}
                  {build && <button className="button small" type="button" onClick={() => setShowLog((v) => !v)}>{showLog ? 'Hide build log' : 'Build log'}</button>}
                </div>
                {showLog && build && (
                  <pre className="env-log">{`version ${build.version} · ${build.status}${build.error ? ' · ' + build.error : ''}\n${build.log || ''}`}</pre>
                )}
                {env.packages.length > 0 && (
                  <table className="env-table">
                    <thead><tr><th>Package</th><th>Version</th><th>Manager</th></tr></thead>
                    <tbody>{env.packages.map((p) => <tr key={p.manager + p.name}><td><code>{p.name}</code></td><td className="env-mono">{p.version}</td><td>{p.manager}</td></tr>)}</tbody>
                  </table>
                )}
                {env.versions.length > 0 && (
                  <div className="env-versions">
                    <h3>Versions</h3>
                    {env.versions.slice().reverse().map((v) => (
                      <div key={v.version} className="env-version">
                        <span className="env-mono">v{v.version}</span>
                        <span className={'status ' + (v.status === 'ready' ? 'ok' : v.status === 'failed' ? 'err' : 'warn')}>{v.status}</span>
                        <span className="env-dim">{v.finished_at ? new Date(v.finished_at * 1000).toLocaleString() : ''}{v.packages ? ` · ${v.packages} packages` : ''}{v.bytes ? ` · ${fmtBytes(v.bytes)}` : ''}</span>
                        {v.status === 'ready' && (env.version === v.version
                          ? <span className="env-dim">active</span>
                          : <button className="button small" type="button" disabled={busy === 'activate'} onClick={() => void activate(v.version)}>Use this version</button>)}
                        {v.error && <span className="env-err">{v.error}</span>}
                      </div>
                    ))}
                  </div>
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
    </section>
  );
}
