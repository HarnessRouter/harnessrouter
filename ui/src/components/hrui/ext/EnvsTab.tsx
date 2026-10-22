'use client';
// Add-ons › Environments (docs/uxuidesign/console-91: libraryView's envs tab, libUsed, PI.envs),
// with the old console's whole environment experience in it (Richard, 10-18: "把之前原来那个版本的东西
// 给弄过来 … 用新的设计 first principle"). The workspace's environments as the service lists them
// (lib/environments.ts), one row each: its name and where tasks find it, the setups that use it, its
// files, its declared packages per manager and its state. New environment starts from a git repository
// (address and branch or tag), an archive, a folder, or nothing; once its files are in it is built,
// so its packages are installed once. A row opens the environment's own sheet (EnvSheet: files,
// packages, builds and versions, details), and the address remembers it (?env=<id>). Remove first
// takes it off every setup that reads it, as the design says, then removes it. An older console's
// link to one environment (/environments/<id>) lands here with ?env=<id> and opens it.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  listEnvironments, createEnvironment, deleteEnvironment, importEnvironmentGit, importEnvironmentArchive, writeEnvironmentFile, buildEnvironment,
  environmentHarnesses, fmtBytes, type Environment,
} from '@/lib/environments';
import { getCustom, saveCustom, type CustomHarness } from '@/lib/harness';
import { readSettled } from '@/lib/settle';
import { partIcon } from '../bricks';
import { toast } from '../toast';
import { ConfirmSheet, Sheet, SheetTop } from '../Sheet';
import { usedText, plural, PLUS, ReadFailed } from './shared';
import { Skel, SkRows } from '../Skel';
import { EnvSheet, type EnvTab, type EnvUser } from './EnvSheet';
import { MANAGERS, folderFiles, gitUrl, limitOf, sayFail, statusOf, statusView, uploadSummary } from './envModel';
import './envs.css';

export interface EnvironmentsData { envs: Environment[] | null; failed: boolean; reload: () => Promise<void>; retry: () => void }

/** The workspace's environments, read again when the workspace changes ('' while it is not known yet).
 *  The read always ends (readSettled): one that fails after its quiet second try is `failed`, and the
 *  tab says so with Try again; a list read before stays under it. */
export function useEnvironments(workspace: string): EnvironmentsData {
  const [envs, setEnvs] = useState<Environment[] | null>(null);
  const [failed, setFailed] = useState(false);
  const reload = useCallback(async () => {
    if (!workspace) return;
    try { setEnvs(await readSettled((signal) => listEnvironments(signal))); setFailed(false); }
    catch { setFailed(true); }
  }, [workspace]);
  useEffect(() => { void reload(); }, [reload]);
  const retry = useCallback(() => { setFailed(false); void reload(); }, [reload]);
  // a build finishes in the background: while one shows as building, the list reads again
  useEffect(() => {
    if (!envs?.some((e) => e.status === 'building')) return;
    const t = setInterval(() => void reload(), 4000);
    return () => clearInterval(t);
  }, [envs, reload]);
  return { envs, failed, reload, retry };
}

/** The packages column: what the environment declares, counted per manager. */
export function pkgLine(e: Pick<Environment, 'declared'>): string {
  const parts = MANAGERS.map((m) => [e.declared?.[m]?.length || 0, m] as const).filter(([n]) => n > 0).map(([n, m]) => `${n} ${m}`);
  return parts.length ? parts.join(' · ') : 'No packages';
}
/** Under the state, only when it happened: a newer build failed while an older version still serves. */
function stateSub(e: Environment): string {
  return e.status === 'ready' && e.build?.status === 'failed' && e.build.version !== e.version ? 'Newer build failed' : '';
}

function setAddress(id: string | null) {
  const q = new URLSearchParams(window.location.search);
  if (id) q.set('env', id); else q.delete('env');
  const qs = q.toString();
  window.history.replaceState(window.history.state, '', window.location.pathname + (qs ? `?${qs}` : ''));
}

export function EnvsTab({ data, setups, reloadSetups }: {
  data: EnvironmentsData; setups: CustomHarness[] | null; reloadSetups: () => Promise<void>;
}) {
  const { envs, reload } = data;
  const [creating, setCreating] = useState(false);
  const [opened, setOpened] = useState<{ id: string; tab: EnvTab; notice?: string } | null>(null);
  const [busy, setBusy] = useState('');
  const [del, setDel] = useState<{ e: Environment; users: EnvUser[] } | null>(null);

  // a link can open one: ?tab=envs&env=<id>
  useEffect(() => { const id = new URLSearchParams(window.location.search).get('env'); if (id) setOpened({ id, tab: 'files' }); }, []);
  const open = (id: string, tab: EnvTab = 'files', notice?: string) => { setOpened({ id, tab, notice }); setAddress(id); };
  const close = () => { setOpened(null); setAddress(null); };

  const usersOf = useMemo(() => {
    const m: Record<string, string[]> = {};
    for (const h of setups || []) if (h.environment) (m[h.environment] ||= []).push(h.name);
    return m;
  }, [setups]);
  const names = useMemo(() => (envs || []).map((e) => ({ id: e.id, name: e.name.toLowerCase() })), [envs]);

  async function askRemove(e: Environment) {
    setBusy(e.id);
    try { setDel({ e, users: (await environmentHarnesses(e.id)).map((h) => ({ id: h.id, name: h.name })) }); }
    catch { toast('The environment could not be checked. Try again.'); }
    finally { setBusy(''); }
  }
  /** Off every setup that reads it first (the service keeps an environment a setup still reads), then deleted. */
  async function remove(e: Environment, users: EnvUser[]): Promise<boolean> {
    setBusy(e.id);
    try {
      for (const u of users) {
        const h = await getCustom(u.id);
        if (!h) throw new Error('setup');
        if (h.environment === e.id) await saveCustom({ ...h, environment: '' });
      }
      await deleteEnvironment(e.id);
      setDel(null);
      if (opened?.id === e.id) close();
      toast(`Environment removed${users.length ? `. ${plural(users.length, 'setup')} updated.` : '.'}`);
      await Promise.all([reload(), reloadSetups()]);
      return true;
    } catch (err) {
      toast(sayFail(err, 'The environment could not be removed.', { 409: 'It cannot be removed while a build runs or a setup still uses it. Try again in a moment.' }));
      return false;
    } finally { setBusy(''); }
  }

  const newBtn = <button type="button" className="btn primary" onClick={() => setCreating(true)}>{PLUS}New environment</button>;

  return (
    <>
      <div className="lib-form">{newBtn}</div>
      {data.failed ? <ReadFailed what="environments" retry={data.retry} /> : null}
      {envs === null ? (data.failed ? null : <div className="rows"><Skel label="Loading your environments"><SkRows n={4} cols={2} /></Skel></div>)
        : envs.length ? (
          // one grid for the head and every row (envs.css), so each column starts at the same place in all of them
          <div className="eo-plate">
            <div className="rows-head eo-head" aria-hidden="true">
              <span>Environment</span><span className="eo-c-files">Files</span><span className="eo-c-pk">Packages</span><span>State</span><span />
            </div>
            <div className="rows">
              {envs.map((e) => {
                const v = statusView(e), sub = stateSub(e);
                return (
                  <div key={e.id} className="row eo-row">
                    <span className="t lib-t">
                      <span className="lib-ic" aria-hidden="true" dangerouslySetInnerHTML={{ __html: partIcon(e.status === 'ready' || e.status === 'building' ? 'built' : 'empty', 'tool') }} />
                      <span className="eo-row-t">
                        <b><button type="button" className="eo-name" onClick={() => open(e.id)}>{e.name}</button></b>
                        <small className="sub2 mono">{e.mount}<span className="eo-narrow"> · {plural(e.files.count, 'file')} · {pkgLine(e)}</span></small>
                        <small className="lib-used">{usedText(usersOf[e.id] || [])}</small>
                      </span>
                    </span>
                    <span className="eo-c-files">{plural(e.files.count, 'file')}{e.files.bytes ? <small>{fmtBytes(e.files.bytes)}</small> : null}</span>
                    <span className="eo-c-pk mono">{pkgLine(e)}</span>
                    <span className="eo-c-st"><span className={`pill ${v.tone}`}>{v.tone === 'run' ? <span className="dot run" aria-hidden="true" /> : null}{v.label}</span>{sub ? <small>{sub}</small> : null}</span>
                    <span className="lib-act">
                      <button type="button" className="btn small line" disabled={busy === e.id} onClick={() => open(e.id)}>Open</button>
                      <button type="button" className="link-q danger" disabled={!!busy} onClick={() => void askRemove(e)}>Remove</button>
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        ) : (
          <div className="empty-list es"><span className="es-art" aria-hidden="true" dangerouslySetInnerHTML={{ __html: partIcon('empty', 'tool') }} /><span>No environments yet.</span></div>
        )}

      {creating ? (
        <NewEnvSheet taken={names.map((n) => n.name)} onClose={() => setCreating(false)}
          onCreated={(e, tab, notice) => { setCreating(false); void reload(); open(e.id, tab, notice); }} />
      ) : null}

      {opened ? (
        <EnvSheet key={opened.id} id={opened.id} tab={opened.tab} notice={opened.notice}
          taken={names.filter((n) => n.id !== opened.id).map((n) => n.name)}
          onClose={close} onChanged={() => { void reload(); void reloadSetups(); }} onDelete={remove} />
      ) : null}

      {del ? (
        <ConfirmSheet id="edl" title={`Remove environment · ${del.e.name}`} confirmLabel="Remove environment" busy={busy === del.e.id}
          onClose={() => setDel(null)} onConfirm={() => void remove(del.e, del.users)}
          body={del.users.length
            ? <><b>{del.users.slice(0, 3).map((u) => u.name).join(', ')}{del.users.length > 3 ? ` and ${del.users.length - 3} more` : ''}</b> {del.users.length === 1 ? 'uses' : 'use'} it. From the next task, {del.users.length === 1 ? 'its tasks start' : 'their tasks start'} with no files. This can’t be undone.</>
            : 'No setup uses it. This can’t be undone.'} />
      ) : null}
    </>
  );
}

// ── New environment ───────────────────────────────────────────────────────────────────────────────

type Src = 'git' | 'archive' | 'folder' | 'empty';
const SRC: [Src, string][] = [['git', 'Git repository'], ['archive', 'Archive'], ['folder', 'Folder'], ['empty', 'Nothing yet']];

export function NewEnvSheet({ taken, onClose, onCreated }: {
  taken: string[]; onClose: () => void;
  /** made: open it on `tab`, with `notice` when part of it did not go through */
  onCreated: (e: Environment, tab: EnvTab, notice?: string) => void;
}) {
  const [name, setName] = useState('');
  const [src, setSrc] = useState<Src>('git');
  const [url, setUrl] = useState('');
  const [ref, setRef] = useState('');
  const [archive, setArchive] = useState<File | null>(null);
  const [folder, setFolder] = useState<{ name: string; files: { path: string; file: File }[] } | null>(null);
  const [description, setDescription] = useState('');
  const [entry, setEntry] = useState('');
  const [step, setStep] = useState('');
  const [err, setErr] = useState<{ field: string; text: string } | null>(null);
  const archiveRef = useRef<HTMLInputElement | null>(null);
  const folderRef = useRef<HTMLInputElement | null>(null);
  useEffect(() => { folderRef.current?.setAttribute('webkitdirectory', ''); }, [src]);

  const bad = (field: string, text: string) => { setErr({ field, text }); };
  function pickFolder(list: FileList | null) {
    const all = Array.from(list || []);
    if (!all.length) return;
    const top = ((all[0] as File & { webkitRelativePath?: string }).webkitRelativePath || '').split('/')[0] || '';
    setErr(null); setFolder({ name: top, files: folderFiles(all, true) });
  }

  async function create() {
    const n = name.trim();
    if (!n) return bad('name', 'Give the environment a name.');
    if (taken.includes(n.toLowerCase())) return bad('name', `“${n}” is already taken. Use another name.`);
    let git = '';
    if (src === 'git') { const u = gitUrl(url); if (!u) return bad('url', 'Paste a git repository address, like https://github.com/your-org/project.'); git = u; }
    if (src === 'archive' && !archive) return bad('archive', 'Choose a zip or tar of the project folder.');
    if (src === 'folder' && !folder?.files.length) return bad('folder', 'Choose the project folder.');
    setErr(null); setStep('Creating…');
    let env: Environment;
    try {
      env = await createEnvironment({ name: n, description: description.trim(), entry: entry.trim() });
    } catch (e) {
      setStep('');
      return bad('name', sayFail(e, 'The environment could not be created.', {
        409: `An environment named like “${n}” already exists. Use another name.`, 422: 'Give it a name that starts with a letter or a digit.',
      }));
    }
    let files = 0, notice = '';
    try {
      if (src === 'git') { setStep('Importing the repository…'); files = (await importEnvironmentGit(env.id, git, ref.trim(), false)).count; }
      else if (src === 'archive' && archive) { setStep(`Importing ${archive.name}…`); files = Number((await importEnvironmentArchive(env.id, archive, false))?.count) || 0; }
      else if (src === 'folder' && folder) {
        // every file, its folders kept; only the service's own limits refuse one
        const failed: { path: string; tooBig: boolean }[] = [];
        let full = false;
        for (const [i, f] of folder.files.entries()) {
          setStep(`Uploading ${i + 1} of ${folder.files.length}…`);
          try { await writeEnvironmentFile(env.id, f.path, f.file); files++; }
          catch (e) {
            const limit = limitOf(e);
            if (limit === 'entries') { full = true; break; }   // past it every file is refused: stop here
            failed.push({ path: f.path, tooBig: limit === 'size' });
          }
        }
        if (failed.length || full) notice = uploadSummary(files, failed, full);
      }
    } catch (e) {
      const why = limitOf(e) === 'entries' ? ' It has more files and folders than one environment holds.'
        : limitOf(e) === 'size' ? ' It is too large to import here.'
          : statusOf(e) !== 422 ? '' : src === 'git' ? ' Check the address and the branch or tag; a private repository needs an access token in the address.' : ' That file is not a zip or tar archive.';
      notice = `It was made, but the ${src === 'git' ? 'repository' : 'archive'} could not be imported.${why} Import it again here on Files.`;
    }
    // with its files in, it is built at once, so its packages are installed once
    let built = false;
    if (files > 0) {
      setStep('Starting the build…');
      try { await buildEnvironment(env.id); built = true; }
      catch (e) { notice = notice || sayFail(e, 'It was made, but its build could not start. Build it here.').replace(/ Try again\.$/, ''); }
    }
    setStep('');
    onCreated(env, built ? 'builds' : 'files', notice || undefined);
  }

  const enter = (ev: React.KeyboardEvent) => { if (ev.key === 'Enter') { ev.preventDefault(); void create(); } };
  const busy = !!step;
  return (
    <Sheet onClose={onClose} labelledBy="eonh" className="small-sheet eo-new eo-full" busy={busy}>
      <SheetTop id="eonh" title="New environment" onClose={onClose} />
      <div className="set-f">
        <label htmlFor="eonName">Name</label>
        <input id="eonName" className={`set-in${err?.field === 'name' ? ' bad' : ''}`} placeholder="docs-repo" value={name} disabled={busy}
          aria-invalid={err?.field === 'name' || undefined} onChange={(ev) => { setName(ev.target.value); if (err?.field === 'name') setErr(null); }} onKeyDown={enter} />
      </div>
      <div className="set-f">
        <span className="eo-l" id="eonSrcL">Start from</span>
        <div className="seg eo-src" role="radiogroup" aria-labelledby="eonSrcL">
          {SRC.map(([k, label]) => (
            <button key={k} type="button" role="radio" aria-checked={src === k} className={src === k ? 'on' : ''} disabled={busy}
              onClick={() => { setSrc(k); setErr(null); }}>{label}</button>
          ))}
        </div>
      </div>
      {src === 'git' ? (
        <div className="eo-two">
          <div className="set-f"><label htmlFor="eonUrl">Repository address</label>
            <input id="eonUrl" className={`set-in mono${err?.field === 'url' ? ' bad' : ''}`} value={url} placeholder="https://github.com/your-org/project" spellCheck={false} disabled={busy}
              onChange={(ev) => { setUrl(ev.target.value); if (err?.field === 'url') setErr(null); }} onKeyDown={enter} /></div>
          <div className="set-f"><label htmlFor="eonRef">Branch or tag <span className="muted">optional</span></label>
            <input id="eonRef" className="set-in mono" value={ref} placeholder="main" spellCheck={false} disabled={busy} onChange={(ev) => setRef(ev.target.value)} onKeyDown={enter} /></div>
        </div>
      ) : null}
      {src === 'archive' ? (
        <div className="set-f eo-pick">
          <input ref={archiveRef} type="file" hidden accept=".zip,.tar,.tgz,.tar.gz,application/zip,application/x-tar,application/gzip"
            onChange={(ev) => { const f = ev.target.files?.[0] || null; ev.target.value = ''; if (f) { setArchive(f); setErr(null); } }} />
          <button type="button" className={`btn line${err?.field === 'archive' ? ' bad' : ''}`} disabled={busy} onClick={() => archiveRef.current?.click()}>{archive ? 'Choose another' : 'Choose a zip or tar'}</button>
          {archive ? <span className="set-help"><b>{archive.name}</b> · {fmtBytes(archive.size)}</span> : null}
        </div>
      ) : null}
      {src === 'folder' ? (
        <div className="set-f eo-pick">
          <input ref={folderRef} type="file" hidden multiple onChange={(ev) => { pickFolder(ev.target.files); ev.target.value = ''; }} />
          <button type="button" className={`btn line${err?.field === 'folder' ? ' bad' : ''}`} disabled={busy} onClick={() => folderRef.current?.click()}>{folder ? 'Choose another' : 'Choose a folder'}</button>
          {folder ? <span className="set-help"><b>{folder.name || 'The folder'}</b> · {plural(folder.files.length, 'file')}</span> : null}
        </div>
      ) : null}

      <details className="eo-more">
        <summary>Description and how it is run <span className="muted">optional</span></summary>
        <div className="set-f"><label htmlFor="eonDesc">Description</label>
          <input id="eonDesc" className="set-in" value={description} placeholder="What the project does" disabled={busy} onChange={(ev) => setDescription(ev.target.value)} /></div>
        <div className="set-f"><label htmlFor="eonEntry">How it is run</label>
          <input id="eonEntry" className="set-in mono" value={entry} placeholder="python3 run.py --episode <id>" spellCheck={false} disabled={busy} onChange={(ev) => setEntry(ev.target.value)} /></div>
      </details>

      {err ? <p className="eo-msg bad" role="alert">{err.text}</p> : null}

      <div className="sheet-actions eo-new-act">
        <span className="eo-state" role="status" aria-live="polite">{step}</span>
        <button type="button" className="btn" disabled={busy} onClick={onClose}>Cancel</button>
        <button type="button" className="btn primary" disabled={busy} onClick={() => void create()}>{busy ? 'Creating…' : 'Create environment'}</button>
      </div>
    </Sheet>
  );
}
