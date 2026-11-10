'use client';
// Add-ons › Environments (docs/uxuidesign/console-91: libraryView's envs tab, libUsed, PI.envs),
// with the old console's whole environment experience in it (Richard, 10-18: "把之前原来那个版本的东西
// 给弄过来 … 用新的设计 first principle"). The workspace's environments as the service lists them
// (lib/environments.ts), one row each: its name and where tasks find it, the setups that use it, its
// files, its declared packages per manager and its state. New environment asks only a name and a
// description (Richard, 11-09: "just give name and description"); it is made empty and opens on its own
// sheet, where files and packages go in. A row opens the environment's own sheet (EnvSheet: files,
// packages, builds and versions, details), and the address remembers it (?env=<id>). Remove first
// takes it off every setup that reads it, as the design says, then removes it. An older console's
// link to one environment (/environments/<id>) lands here with ?env=<id> and opens it.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  listEnvironments, createEnvironment, deleteEnvironment, environmentHarnesses, fmtBytes, type Environment,
} from '@/lib/environments';
import { getCustom, saveCustom, type CustomHarness } from '@/lib/harness';
import { readSettled } from '@/lib/settle';
import { partIcon } from '../bricks';
import { toast } from '../toast';
import { ConfirmSheet, Sheet, SheetTop } from '../Sheet';
import { usedText, plural, harnesses, PLUS, ReadFailed } from './shared';
import { Skel, SkRows } from '../Skel';
import { EnvSheet, type EnvTab, type EnvUser } from './EnvSheet';
import { MANAGERS, sayFail, statusView } from './envModel';
import './envs.css';
import { Markup } from '../Markup';

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
      toast(`Environment removed${users.length ? `. ${harnesses(users.length)} updated.` : '.'}`);
      await Promise.all([reload(), reloadSetups()]);
      return true;
    } catch (err) {
      toast(sayFail(err, 'The environment could not be removed.', { 409: 'It cannot be removed while a build runs or a harness still uses it. Try again in a moment.' }));
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
                      <Markup className="lib-ic" html={partIcon(e.status === 'ready' || e.status === 'building' ? 'built' : 'empty', 'tool')} />
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
          <div className="empty-list es"><Markup className="es-art" html={partIcon('empty', 'tool')} /><span>No environments yet.</span></div>
        )}

      {creating ? (
        <NewEnvSheet taken={names.map((n) => n.name)} onClose={() => setCreating(false)}
          onCreated={(e) => { setCreating(false); void reload(); open(e.id, 'files'); }} />
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
            : 'No harness uses it. This can’t be undone.'} />
      ) : null}
    </>
  );
}

// ── New environment ───────────────────────────────────────────────────────────────────────────────

/** New environment: a name and, if the person wants, a description; nothing else (Richard, 11-09: "just give name
 *  and description"). It is made empty and opens on its own sheet, on Files, where files and packages go in. The
 *  product's own form sheet, as Add MCP server and Connect a plugin draw it: the title alone on its row, each field
 *  under its label at full width, Cancel then the primary action; a bottom sheet on a phone. */
export function NewEnvSheet({ taken, onClose, onCreated }: {
  taken: string[]; onClose: () => void;
  /** made: open it */
  onCreated: (e: Environment) => void;
}) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const nameRef = useRef<HTMLInputElement | null>(null);

  async function create() {
    if (busy) return;
    const n = name.trim();
    const bad = (text: string) => { setErr(text); nameRef.current?.focus(); };
    if (!n) return bad('Give the environment a name.');
    if (taken.includes(n.toLowerCase())) return bad(`“${n}” is already taken. Use another name.`);
    setErr(''); setBusy(true);
    let env: Environment;
    try {
      env = await createEnvironment({ name: n, description: description.trim() });
    } catch (e) {
      setBusy(false);
      return bad(sayFail(e, 'The environment could not be created.', {
        409: `An environment named like “${n}” already exists. Use another name.`, 422: 'Give it a name that starts with a letter or a digit.',
      }));
    }
    onCreated(env);
  }

  return (
    <Sheet onClose={onClose} labelledBy="eonh" className="small-sheet mcp-sheet eo-create" busy={busy} initialFocus={nameRef}>
      <SheetTop id="eonh" title="New environment" onClose={onClose} />
      <div className="set-f"><label htmlFor="eonName">Name</label>
        <input id="eonName" ref={nameRef} className={`set-in${err ? ' bad' : ''}`} placeholder="my-project" autoComplete="off" spellCheck={false}
          value={name} disabled={busy} aria-invalid={err ? true : undefined} aria-describedby={err ? 'eonErr' : undefined}
          onChange={(ev) => { setName(ev.target.value); if (err) setErr(''); }}
          onKeyDown={(ev) => { if (ev.key === 'Enter' && !ev.nativeEvent.isComposing) { ev.preventDefault(); void create(); } }} />
        {err ? <p className="set-help eo-err" id="eonErr" role="alert">{err}</p> : null}
      </div>
      <div className="set-f"><label htmlFor="eonDesc">Description <span className="muted">optional</span></label>
        <textarea id="eonDesc" className="set-in" rows={3} placeholder="What the project does" value={description} disabled={busy}
          onChange={(ev) => setDescription(ev.target.value)} /></div>
      <div className="sheet-actions">
        <button type="button" className="btn" disabled={busy} onClick={onClose}>Cancel</button>
        <button type="button" className="btn primary" disabled={busy} onClick={() => void create()}>{busy ? 'Creating…' : 'Create environment'}</button>
      </div>
    </Sheet>
  );
}
