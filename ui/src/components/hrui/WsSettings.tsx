'use client';
// A workspace's settings, inside its settings sheet (one sheet, settings inline as compact rows, not a
// separate page): its name and description in one small form, then Cloud upload as one row, its state on
// the row and Manage opening its manager right under it. A row whose read fails is shown as could not be
// read, with Try again, never left out as if it did not apply.
import { useCallback, useEffect, useRef, useState } from 'react';
import { addTarget, listTargets, removeTarget, type CloudTarget } from '@/lib/cloud-upload';
import { useWorkspace } from '@/lib/workspace';
import { useEscapeLayer } from './escape';
import { toast } from './toast';

const sameName = (a: string, b: string) => a.trim().toLowerCase() === b.trim().toLowerCase();

/** Name and description, saved together through the workspace's own PATCH. */
export function WsProfile({ onSaving }: { onSaving: (busy: boolean) => void }) {
  const { workspaces, current, update } = useWorkspace();
  const [name, setName] = useState(current.name);
  const [desc, setDesc] = useState(current.description);
  const [busy, setBusy] = useState(false);
  const [bad, setBad] = useState('');
  const nameRef = useRef<HTMLInputElement | null>(null);
  useEffect(() => { setName(current.name); setDesc(current.description); setBad(''); },
    [current.id, current.name, current.description]);

  const nm = name.trim();
  const dirty = nm !== current.name || desc.trim() !== current.description;

  async function save() {
    if (busy || !dirty) return;
    if (!nm) { setBad('name'); toast('Name can’t be empty.'); nameRef.current?.focus(); return; }
    if (workspaces.some((w) => w.id !== current.id && sameName(w.name, nm))) {
      setBad('name'); toast(`You already have a workspace named ${nm}.`); nameRef.current?.focus(); return;
    }
    setBusy(true); onSaving(true);
    try {
      const patch: { name?: string; description?: string } = {};
      if (nm !== current.name) patch.name = nm;
      if (desc.trim() !== current.description) patch.description = desc.trim();
      await update(patch);
      toast('Saved');
    } catch (e) {
      toast(e instanceof Error && e.message && !/^save failed/.test(e.message) ? e.message : 'It could not be saved. Try again in a moment.');
    } finally { setBusy(false); onSaving(false); }
  }
  const enter = (e: React.KeyboardEvent) => { if (e.key === 'Enter' && !e.nativeEvent.isComposing) { e.preventDefault(); void save(); } };

  return (
    <div className="set-form">
      <label className="set-row" htmlFor="wsName"><span className="set-l">Name</span>
        <input id="wsName" ref={nameRef} className={`keyname plain${bad === 'name' ? ' bad' : ''}`} aria-invalid={bad === 'name' || undefined}
          autoComplete="off" maxLength={80} value={name} onKeyDown={enter} onChange={(e) => { setName(e.target.value); setBad(''); }} />
      </label>
      <label className="set-row" htmlFor="wsDesc"><span className="set-l">Description</span>
        <input id="wsDesc" className="keyname plain" autoComplete="off" maxLength={300} placeholder="Optional" value={desc}
          onKeyDown={enter} onChange={(e) => setDesc(e.target.value)} />
      </label>
      <div className="set-act">
        <button type="button" className="btn" disabled={busy || !dirty} onClick={() => void save()}>{busy ? 'Saving' : 'Save'}</button>
      </div>
    </div>
  );
}

/** One setting as a row: its name, its state, and Manage opening its manager under the row.
 *  Escape closes an open manager before it closes the sheet (escape.ts). */
function SetRow({ label, state, onDone, children }: { label: string; state: string; onDone: () => void; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const btn = useRef<HTMLButtonElement | null>(null);
  const id = `set-${label.toLowerCase().replace(/[^a-z]+/g, '-')}`;
  const close = () => { setOpen(false); onDone(); btn.current?.focus(); };
  useEscapeLayer(open, close);
  return (
    <div className={`set-item${open ? ' open' : ''}`}>
      <div className="set-row">
        <span className="set-l">{label}</span>
        <span className="set-v">{state}</span>
        <button ref={btn} type="button" className="link-q" aria-expanded={open} aria-controls={id}
          onClick={() => (open ? close() : setOpen(true))}>{open ? 'Done' : 'Manage'}</button>
      </div>
      {open ? <div id={id} className="set-more">{children}</div> : null}
    </div>
  );
}

/** A row whose read failed: its name, that it could not be read, and Try again in place of Manage
 *  (whether it applies is not known, so it is not left out). */
function FailedRow({ label, onRetry }: { label: string; onRetry: () => void }) {
  return (
    <div className="set-item">
      <div className="set-row" role="alert">
        <span className="set-l">{label}</span>
        <span className="set-v">Could not be read just now.</span>
        <button type="button" className="link-q" onClick={onRetry}>Try again</button>
      </div>
    </div>
  );
}


/** Cloud upload: the hosted workspaces this instance may upload a harness to, each added with a key from
 *  that workspace and removed any time. Uploading replaces the cloud copy. */
export function CloudUploadRow() {
  const [targets, setTargets] = useState<CloudTarget[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [key, setKey] = useState('');
  const [busy, setBusy] = useState(false);
  const read = useCallback(() => {
    setFailed(false);
    listTargets().then((r) => setTargets(r.targets)).catch(() => setFailed(true));
  }, []);
  useEffect(read, [read]);
  if (failed && targets === null) return <FailedRow label="Cloud upload" onRetry={read} />;
  const n = targets ? targets.length : 0;
  const state = targets === null ? '' : n ? `${n} workspace${n === 1 ? '' : 's'}` : 'Off';

  async function add() {
    if (busy || !key.trim()) return;
    setBusy(true);
    try { await addTarget(key.trim()); setKey(''); setTargets((await listTargets()).targets); toast('Added'); }
    catch (e) { toast(e instanceof Error && e.message ? e.message : 'It could not be added. Try again in a moment.'); }
    finally { setBusy(false); }
  }
  async function remove(id: string) {
    setBusy(true);
    try { setTargets((await removeTarget(id)).targets); }
    catch (e) { toast(e instanceof Error && e.message ? e.message : 'It could not be removed. Try again in a moment.'); }
    finally { setBusy(false); }
  }

  return (
    <SetRow label="Cloud upload" state={state} onDone={() => setKey('')}>
      <p className="set-note">Uploading a harness replaces its cloud copy.</p>
      {(targets || []).map((t) => (
        <div key={t.id} className="set-row set-sub">
          <span className="set-l">{t.label}</span>
          <span className="set-v">{t.revoked ? 'Key revoked. Paste a new one.' : t.key_hint}</span>
          <button type="button" className="link-q" disabled={busy} onClick={() => void remove(t.id)}>Remove</button>
        </div>
      ))}
      <div className="keyrow">
        <label className="sr" htmlFor="cloudKey">A key from the cloud workspace</label>
        <input id="cloudKey" className="keyname plain" type="password" autoComplete="off" placeholder="sk-hr-…  (the cloud console, inside the workspace, under API Keys)"
          value={key} onChange={(e) => setKey(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.nativeEvent.isComposing) { e.preventDefault(); void add(); } }} />
        <button type="button" className="btn" disabled={busy || !key.trim()} onClick={() => void add()}>{busy ? 'Adding' : 'Add'}</button>
      </div>
    </SetRow>
  );
}
