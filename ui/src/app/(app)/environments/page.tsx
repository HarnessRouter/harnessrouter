'use client';
// Environments: a project's files and its installed dependencies, built once and read by every
// Task session that names it (read-only at /env/<slug>, beside the session's own workspace).
// This page is the shelf: one row per environment with what the service knows about it; the work
// (files, build, versions) happens on the environment's own page.
import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { SkelRows } from '@/components/Skel';
import { createEnvironment, fmtBytes, listEnvironments, type Environment } from '@/lib/environments';

const STATUS_LABEL: Record<Environment['status'], string> = { empty: 'Not built', building: 'Building', ready: 'Ready', failed: 'Build failed' };
const STATUS_CLASS: Record<Environment['status'], string> = { empty: 'neutral', building: 'warn', ready: 'ok', failed: 'err' };

export default function EnvironmentsPage() {
  const router = useRouter();
  const [items, setItems] = useState<Environment[] | null>(null);
  const [err, setErr] = useState('');
  const [creating, setCreating] = useState(false);
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
      const e = await createEnvironment({ name: form.name.trim(), description: form.description.trim(), entry: form.entry.trim() });
      setCreating(false); setForm({ name: '', description: '', entry: '' });
      router.push(`/environments/${e.id}`);
    } catch (e) { setErr(e instanceof Error ? e.message : 'The environment could not be created.'); }
    finally { setBusy(false); }
  };

  return (
    <section className="view is-active collection-view" id="view-environments"><div className="page">
      <div className="page-header">
        <div>
          <h1>Environments</h1>
          <p>A project and its installed dependencies, built once and opened by every Task that uses it. Sessions read it at its own path and keep their outputs in their own workspace.</p>
        </div>
        <div className="page-actions">
          <button className="button primary" type="button" onClick={() => setCreating(true)}>
            <iconify-icon icon="tabler:plus"></iconify-icon>New environment</button>
        </div>
      </div>

      {err && <div className="hr-error" role="alert">{err}</div>}

      {items === null && !err && <SkelRows rows={3} />}

      {items !== null && items.length === 0 && (
        <div className="session-empty env-empty">
          <iconify-icon icon="tabler:stack-2"></iconify-icon>
          <strong>No environments yet</strong>
          <span>Create one, import your project (an archive or a git repository), build it, and name it on a Harness. Every Task of that Harness then starts with the project in place and its packages installed.</span>
        </div>
      )}

      {items !== null && items.length > 0 && (
        <div className="env-list">
          <div className="env-row env-row-head"><span>Name</span><span>Status</span><span>Version</span><span>Files</span><span>Packages</span><span>Updated</span></div>
          {items.map((e) => (
            <a key={e.id} className="env-row" href={`/environments/${e.id}`}>
              <span className="env-name"><iconify-icon icon="tabler:stack-2"></iconify-icon><span><strong>{e.name}</strong><em>{e.mount}</em></span></span>
              <span><span className={'status ' + STATUS_CLASS[e.status]}>{STATUS_LABEL[e.status]}</span></span>
              <span className="env-mono">{e.version ? `v${e.version}` : '—'}</span>
              <span className="env-mono">{e.files.count}{e.files.bytes ? <em> {fmtBytes(e.files.bytes)}</em> : null}</span>
              <span className="env-mono">{e.status === 'ready' ? e.packages.length : '—'}</span>
              <span className="env-dim">{e.updatedAt ? new Date(e.updatedAt).toLocaleString() : ''}</span>
            </a>
          ))}
        </div>
      )}

      {creating && (
        <div className="kit-overlay" role="dialog" aria-modal="true" aria-labelledby="env-new-title"
             onMouseDown={(ev) => { if (ev.target === ev.currentTarget) setCreating(false); }}>
          <div className="kit-dialog">
            <button className="kit-dialog-x" type="button" onClick={() => setCreating(false)} aria-label="Close"><iconify-icon icon="tabler:x"></iconify-icon></button>
            <h2 id="env-new-title">New environment</h2>
            <p className="kit-dialog-sub">Name it after the project. Sessions will find it at a path made from the name; that path does not change afterwards.</p>
            <div className="kit-custom">
              <label className="kit-field"><span>Name</span>
                <input value={form.name} placeholder="Content Studio" autoFocus onChange={(ev) => setForm({ ...form, name: ev.target.value })}
                  onKeyDown={(ev) => { if (ev.key === 'Enter') void create(); }} /></label>
              <label className="kit-field"><span>Description</span>
                <input value={form.description} placeholder="What the project does" onChange={(ev) => setForm({ ...form, description: ev.target.value })} /></label>
              <label className="kit-field"><span>How it is run</span>
                <input value={form.entry} placeholder="python3 run.py --episode <id>" onChange={(ev) => setForm({ ...form, entry: ev.target.value })} />
                <span className="kit-choice-why">Optional. Told to the agent word for word, so it starts the project the way you do.</span></label>
            </div>
            <div className="kit-dialog-actions">
              <span className="kit-dialog-spacer" />
              <button className="button" type="button" onClick={() => setCreating(false)}>Cancel</button>
              <button className="button primary" type="button" disabled={busy || !form.name.trim()} onClick={() => void create()}>{busy ? 'Creating…' : 'Create'}</button>
            </div>
          </div>
        </div>
      )}
    </div></section>
  );
}
