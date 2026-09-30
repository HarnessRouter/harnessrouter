'use client';
// Environments: a project's files and its installed dependencies, built once and read by every
// Task session that names it (read-only at /env/<slug>, beside the session's own workspace).
// This page is the shelf: one row per environment with what the service knows about it; the work
// (files, build, versions) happens on the environment's own page.
import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { SkelRows } from '@/components/Skel';
import { createEnvironment, deleteEnvironment, listEnvironments, updateEnvironment, type Environment } from '@/lib/environments';

/** The packages column: what the active build installed, counted per manager, or the state that explains why there is none. */
function packagesLine(e: Environment): string {
  const parts = (['pip', 'npm', 'apt'] as const).map((m) => [e.declared?.[m]?.length || 0, m] as const).filter(([n]) => n > 0).map(([n, m]) => `${n} ${m}`);
  return parts.length ? parts.join(' \u00b7 ') : 'no packages';
}

export default function EnvironmentsPage() {
  const router = useRouter();
  const [items, setItems] = useState<Environment[] | null>(null);
  const [err, setErr] = useState('');
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Environment | null>(null);
  const [confirm, setConfirm] = useState<string>('');
  const [form, setForm] = useState({ name: '', description: '', entry: '' });
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    try { setItems(await listEnvironments()); setErr(''); }
    catch (e) { setErr(e instanceof Error ? e.message : 'The environments could not be read.'); }
  }, []);
  useEffect(() => { void reload(); }, [reload]);
  // a build finishes in the background: while one shows as building, the list re-reads
  useEffect(() => {
    if (!items?.some((e) => e.status === 'building')) return;
    const t = setInterval(() => void reload(), 4000);
    return () => clearInterval(t);
  }, [items, reload]);

  const create = async () => {
    if (!form.name.trim()) return;
    setBusy(true); setErr('');
    try {
      if (editing) {
        await updateEnvironment(editing.id, { name: form.name.trim(), description: form.description.trim(), entry: form.entry.trim() });
        setEditing(null); setForm({ name: '', description: '', entry: '' }); await reload();
      } else {
        const e = await createEnvironment({ name: form.name.trim(), description: form.description.trim(), entry: form.entry.trim() });
        setCreating(false); setForm({ name: '', description: '', entry: '' });
        router.push(`/environments/${e.id}`);
      }
    } catch (e) { setErr(e instanceof Error ? e.message : 'The environment could not be saved.'); }
    finally { setBusy(false); }
  };
  const remove = async (id: string) => {
    setBusy(true); setErr('');
    try { await deleteEnvironment(id); setConfirm(''); await reload(); }
    catch (e) { setErr(e instanceof Error ? e.message : 'The environment could not be deleted.'); }
    finally { setBusy(false); }
  };
  const openEdit = (e: Environment) => { setForm({ name: e.name, description: e.description, entry: e.entry }); setEditing(e); };

  return (
    <section className="view is-active collection-view" id="view-environments"><div className="page">
      <div className="page-header">
        <div>
          <h1>Environments</h1>
          <p>A working directory and its packages, built once. Attach it to a harness and every task starts ready.</p>
        </div>
        <div className="page-actions">
          <button className="button primary" type="button" onClick={() => setCreating(true)}>
            <iconify-icon icon="tabler:plus"></iconify-icon>New environment</button>
        </div>
      </div>

      {err && <div className="hr-error" role="alert">{err}</div>}

      {items === null && !err && <SkelRows rows={3} />}

      {/* Nothing yet: the flow the design draws at the top of every environment (you add, built
          once, every task starts from it); the one action is the header's button. */}
      {items !== null && items.length === 0 && (
        <div className="env-landing">
          <div className="env-flow">
            <div><div className="env-flow-k">01 · You add</div><div className="env-flow-t">Files and packages</div><div className="env-flow-m">An archive, a git repository, or files, folders kept.</div></div>
            <span className="env-flow-arrow" aria-hidden="true">→</span>
            <div><div className="env-flow-k">02 · Built once</div><div className="env-flow-t">A ready snapshot</div><div className="env-flow-m">Packages from requirements.txt and package.json are installed into it.</div></div>
            <span className="env-flow-arrow" aria-hidden="true">→</span>
            <div><div className="env-flow-k">03 · Every task</div><div className="env-flow-t">Starts from it</div><div className="env-flow-m">Every Task of that Harness reads it, read-only, beside its own workspace.</div></div>
          </div>
        </div>
      )}

      {items !== null && items.length > 0 && (
        <div className="env-list">
          <div className="env-row env-row-head"><span>Environment</span><span>Project files</span><span>Packages</span><span /></div>
          {items.map((e) => (
            <div key={e.id} className="env-row">
              <a className="env-name" href={`/environments/${e.id}`} title={e.description || e.mount}>{e.name}</a>
              <span className="env-mono">{e.files.count} {e.files.count === 1 ? 'file' : 'files'}</span>
              <span className="env-mono">{packagesLine(e)}</span>
              <span className="env-row-actions">
                {confirm === e.id ? (
                  <>
                    <span className="env-dim">Delete every version and file?</span>
                    <button className="button danger small" type="button" disabled={busy} onClick={() => void remove(e.id)}>Delete</button>
                    <button className="button small" type="button" onClick={() => setConfirm('')}>Keep</button>
                  </>
                ) : (
                  <>
                    <button className="icon-button" type="button" aria-label={`Edit ${e.name}`} title="Name, description, how it is run" onClick={() => openEdit(e)}><iconify-icon icon="tabler:pencil"></iconify-icon></button>
                    <button className="icon-button" type="button" aria-label={`Delete ${e.name}`} title="Delete" onClick={() => setConfirm(e.id)}><iconify-icon icon="tabler:trash"></iconify-icon></button>
                    <a className="button small" href={`/environments/${e.id}`}>Open</a>
                  </>
                )}
              </span>
            </div>
          ))}
        </div>
      )}

      {(creating || editing) && (
        <div className="kit-overlay" role="dialog" aria-modal="true" aria-labelledby="env-new-title"
             onMouseDown={(ev) => { if (ev.target === ev.currentTarget) { setCreating(false); setEditing(null); } }}>
          <div className="kit-dialog">
            <button className="kit-dialog-x" type="button" onClick={() => { setCreating(false); setEditing(null); }} aria-label="Close"><iconify-icon icon="tabler:x"></iconify-icon></button>
            <h2 id="env-new-title">{editing ? editing.name : 'New environment'}</h2>
            <p className="kit-dialog-sub">{editing
              ? <>Sessions keep finding it at <code>{editing.mount}</code>; the name, the description and how it is run can change.</>
              : 'Name it after the project. Sessions will find it at a path made from the name; that path does not change afterwards.'}</p>
            <div className="kit-custom">
              <label className="kit-field"><span>Name</span>
                <input value={form.name} placeholder="Content Studio" autoFocus onChange={(ev) => setForm({ ...form, name: ev.target.value })}
                  onKeyDown={(ev) => { if (ev.key === 'Enter') void create(); }} /></label>
              <label className="kit-field"><span>Description</span>
                <input value={form.description} placeholder="What the project does" onChange={(ev) => setForm({ ...form, description: ev.target.value })} /></label>
              <label className="kit-field"><span>How it is run</span>
                <input value={form.entry} placeholder="python3 run.py --episode <id>" onChange={(ev) => setForm({ ...form, entry: ev.target.value })} /></label>
              <p className="env-help">Optional. Told to the agent word for word, so it starts the project the way you do.</p>
            </div>
            <div className="kit-dialog-actions">
              <span className="kit-dialog-spacer" />
              <button className="button" type="button" onClick={() => { setCreating(false); setEditing(null); }}>Cancel</button>
              <button className="button primary" type="button" disabled={busy || !form.name.trim()} onClick={() => void create()}>{busy ? (editing ? 'Saving\u2026' : 'Creating\u2026') : editing ? 'Save' : 'Create'}</button>
            </div>
          </div>
        </div>
      )}
    </div></section>
  );
}
