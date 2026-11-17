'use client';
// A workspace's settings, inside its settings sheet (one sheet, settings inline as compact rows, not a
// separate page): its name and description in one small form, with the workspace fields only, its state on
// the row and Manage opening its manager right under it. A row whose read fails is shown as could not be
// read, with Try again, never left out as if it did not apply.
import { useEffect, useRef, useState } from 'react';
import { useWorkspace } from '@/lib/workspace';
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
      toast('已保存');
    } catch (e) {
      toast(e instanceof Error && e.message && !/^save failed/.test(e.message) ? e.message : 'It could not be saved. Try again in a moment.');
    } finally { setBusy(false); onSaving(false); }
  }
  const enter = (e: React.KeyboardEvent) => { if (e.key === 'Enter' && !e.nativeEvent.isComposing) { e.preventDefault(); void save(); } };

  return (
    <div className="set-form">
      <label className="set-row" htmlFor="wsName"><span className="set-l">名称</span>
        <input id="wsName" ref={nameRef} className={`keyname plain${bad === 'name' ? ' bad' : ''}`} aria-invalid={bad === 'name' || undefined}
          autoComplete="off" maxLength={80} value={name} onKeyDown={enter} onChange={(e) => { setName(e.target.value); setBad(''); }} />
      </label>
      <label className="set-row" htmlFor="wsDesc"><span className="set-l">描述</span>
        <input id="wsDesc" className="keyname plain" autoComplete="off" maxLength={300} placeholder="可选" value={desc}
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
