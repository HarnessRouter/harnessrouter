'use client';
// The two sheets the tree opens itself: a sub memory under this one, and a record in a sub memory (a
// record of the memory on the page opens as a draft in the middle column instead).
import { useState } from 'react';
import { addRecord, createMemory, type Memory, type MemoryRecord } from '@/lib/memories';
import { Sheet, SheetTop } from '../../Sheet';
import { plain } from '../../setup/settingsModel';
import { NameFields } from '../sheets';

export function NewSubMemorySheet({ parent, onClose, onDone }: { parent: Memory; onClose: () => void; onDone: (m: Memory) => void }) {
  const [name, setName] = useState('');
  const [desc, setDesc] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const go = async () => {
    if (!name.trim() || busy) return;
    setBusy(true); setErr('');
    // the sub memory stays with its parent's provider, and the service checks `create` on the parent
    const body = { name: name.trim(), description: desc.trim(), provider: parent.provider, parent_id: parent.id };
    try { onDone(await createMemory(body)); }
    catch (e) { setErr(plain(e, 'That was not created. Try again.')); setBusy(false); }
  };
  return (
    <Sheet onClose={onClose} labelledBy="mtNs" className="mm-sheet mm-nd-sheet" busy={busy}>
      <SheetTop id="mtNs" title="New sub memory" sub={`Inside ${parent.name}. Kept by the same service.`} onClose={onClose} />
      <form noValidate onSubmit={(e) => { e.preventDefault(); void go(); }}>
        <NameFields nameId="mtNsN" descId="mtNsD" name={name} desc={desc} onName={setName} onDesc={setDesc} focus />
        {err ? <p className="mm-err" role="alert">{err}</p> : null}
        <div className="sheet-actions">
          <span className="grow" />
          <button type="button" className="btn" disabled={busy} onClick={onClose}>Cancel</button>
          <button type="submit" className="btn primary" disabled={!name.trim() || busy}>Create</button>
        </div>
      </form>
    </Sheet>
  );
}

export function NewRecordSheet({ memory, label, type, attributes, onClose, onDone }: {
  memory: Memory; label: string; type: string; attributes: Record<string, unknown>; onClose: () => void; onDone: (r: MemoryRecord) => void;
}) {
  const [title, setTitle] = useState('');
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const ready = !!title.trim() || !!text.trim();
  const go = async () => {
    if (!ready || busy) return;
    setBusy(true); setErr('');
    try {
      onDone(await addRecord(memory.id, { type, ...(title.trim() ? { title: title.trim() } : {}), ...(text.trim() ? { content: text } : {}), attributes }));
    } catch (e) { setErr(plain(e, 'That was not saved. Try again.')); setBusy(false); }
  };
  return (
    <Sheet onClose={onClose} labelledBy="mtNr" className="small-sheet mm-sheet" busy={busy}>
      <SheetTop id="mtNr" title={`New ${label}`} sub={`In ${memory.name}`} onClose={onClose} />
      <form noValidate onSubmit={(e) => { e.preventDefault(); void go(); }}>
        <div className="set-f"><label htmlFor="mtNrT">Title</label><input id="mtNrT" className="set-in" value={title} autoComplete="off" autoFocus onChange={(e) => setTitle(e.target.value)} /></div>
        <div className="set-f"><label htmlFor="mtNrB">Text</label><textarea id="mtNrB" className="set-in" rows={4} value={text} onChange={(e) => setText(e.target.value)} /></div>
        {err ? <p className="mm-err" role="alert">{err}</p> : null}
        <div className="sheet-actions">
          <span className="grow" />
          <button type="button" className="btn" disabled={busy} onClick={onClose}>Cancel</button>
          <button type="submit" className="btn primary" disabled={!ready || busy}>Save</button>
        </div>
      </form>
    </Sheet>
  );
}
