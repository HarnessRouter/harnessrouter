'use client';
// Workspace Settings, name and description of the ACTIVE workspace, persisted onto its
// AgentStudio Space record via the engine (Workspaces ARE Spaces). Members/Connections/
// Revenue-source do NOT get fake placeholder rows (per the IA review); they arrive as real
// manageable flows once the backend supports them. (The old Environment select was removed
// 2026-07-22, a pure label with no runtime effect is noise, not a setting.)
import { useEffect, useState } from 'react';
import { useWorkspace } from '@/lib/workspace';
import { SELF_HOSTED } from '@/lib/edition';
import { CloudUploadCard } from '@/components/CloudUploadCard';

export default function WorkspaceSettingsPage() {
  const { current, update, loading } = useWorkspace();
  const [name, setName] = useState(current.name);
  const [desc, setDesc] = useState(current.description);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [savedTick, setSavedTick] = useState(false);
  useEffect(() => { setName(current.name); setDesc(current.description); }, [current.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const dirty = name !== current.name || desc !== current.description;

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (busy || !dirty) return;
    setBusy(true); setErr('');
    try {
      await update({ name: name.trim() || current.name, description: desc });
      setSavedTick(true); setTimeout(() => setSavedTick(false), 1500);
    } catch (ex) { setErr(ex instanceof Error ? ex.message : 'save failed'); }
    finally { setBusy(false); }
  }

  return (
    <section className="view is-active" id="view-settings">
      <div className="page">
        <div className="page-header"><div><h1>Workspace settings</h1><p>Manage the name and description used to identify <span className="workspace-name">{current.name}</span>.</p></div></div>
        <form className="settings-form" onSubmit={save}>
          <div className="settings-form-head">
            <div><h2>Workspace profile</h2><p>Shown in the Workspace selector, Dashboard, and Overview.</p></div>
            <div className="header-actions">
              <span className="save-state">{savedTick ? 'Saved' : dirty ? 'Unsaved changes' : 'No unsaved changes'}</span>
              <button className="button primary" type="submit" disabled={!dirty || busy || loading}>{busy ? 'Saving…' : 'Save changes'}</button>
            </div>
          </div>
          <section className="form-section">
            <div><h3>Name and description</h3><p>Use a stable business name developers can recognize.</p></div>
            <div className="field-stack">
              <div className="field"><label htmlFor="wsName">Name</label>
                <input id="wsName" value={name} onChange={(e) => setName(e.target.value)} /></div>
              <div className="field"><label htmlFor="wsDesc">Description</label>
                <textarea id="wsDesc" rows={3} value={desc} onChange={(e) => setDesc(e.target.value)} />
                <span className="field-help">Shown on Dashboard and Workspace Overview.</span></div>
              {err && <div className="notice"><iconify-icon icon="tabler:alert-triangle"></iconify-icon><div><strong>Could not save</strong>{err}</div></div>}
            </div>
          </section>
        </form>
        {SELF_HOSTED && <CloudUploadCard />}
      </div>
    </section>
  );
}
