'use client';
// Upload to cloud (a setup's Settings, its row under the layers): this setup copied to a workspace on
// HarnessRouter Cloud, one way. This instance stays the source: an upload creates the cloud copy, and
// each later one replaces it. Where it goes is one of the cloud workspaces this instance keeps a key
// for (the workspace settings' Cloud upload lists them); one can be added here by pasting a key from
// that workspace. The key is kept on this instance and never read back. What is said of the last
// upload (when, and whether the setup changed since) is the server's own status.
import { useEffect, useRef, useState } from 'react';
import { addTarget, listTargets, statusOne, uploadOne, type CloudStatus, type CloudTarget } from '@/lib/cloud-upload';
import { ago } from '../setups';
import { Sheet, SheetTop } from '../Sheet';
import { toast } from '../toast';
import { plain } from './settingsModel';

const ADD = '__add__';

/** The status of a setup's cloud copy, as a short line ('' while it is not read, or never uploaded). */
export function cloudLine(s: CloudStatus | null): string {
  if (!s || !s.uploaded) return '';
  const when = s.uploaded_at ? ago(s.uploaded_at > 1e12 ? s.uploaded_at : s.uploaded_at * 1000) : '';
  return s.changed ? `Changed since its upload${when ? ` ${when}` : ''}` : `Uploaded${when ? ` ${when}` : ''}`;
}

/** The setup's cloud status, read once per setup (null while read, or when it could not be). */
export function useCloudStatus(id: string, n = 0): CloudStatus | null {
  const [s, setS] = useState<CloudStatus | null>(null);
  useEffect(() => {
    let alive = true;
    setS(null);
    statusOne(id).then((x) => { if (alive) setS(x); }).catch(() => { /* the row says nothing of it */ });
    return () => { alive = false; };
  }, [id, n]);
  return s;
}

export function CloudUploadSheet({ id, name, status, onClose, onDone }: {
  id: string; name: string; status: CloudStatus | null; onClose: () => void;
  /** an upload answered: the caller reads the status again */
  onDone: () => void;
}) {
  const [targets, setTargets] = useState<CloudTarget[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [choice, setChoice] = useState('');
  const [key, setKey] = useState('');
  const [busy, setBusy] = useState(false);
  const keyRef = useRef<HTMLInputElement | null>(null);
  const read = () => {
    setFailed(false);
    listTargets().then((r) => {
      const live = r.targets.filter((t) => !t.revoked);
      setTargets(r.targets);
      setChoice(live.length ? (live.some((t) => t.id === r.last) ? r.last : live[0].id) : ADD);
    }).catch(() => setFailed(true));
  };
  // read once as the sheet opens
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(read, []);
  const adding = choice === ADD;
  useEffect(() => { if (adding) requestAnimationFrame(() => keyRef.current?.focus()); }, [adding]);

  async function add() {
    if (busy || !key.trim()) return;
    setBusy(true);
    try {
      const t = await addTarget(key.trim());
      const r = await listTargets();
      setTargets(r.targets); setChoice(t.id); setKey('');
    } catch (e) { toast(plain(e, 'That key could not be added. Check it and try again.')); }
    finally { setBusy(false); }
  }
  async function upload() {
    if (busy || adding || !choice) return;
    setBusy(true);
    try {
      const r = await uploadOne(id, choice);
      if (!r.ok) { toast(plain(new Error(r.error || ''), 'The setup could not be uploaded. Try again.')); return; }
      toast(r.action === 'create' ? `${name} is in the cloud workspace.` : `${name}’s cloud copy is replaced.`);
      onDone();
      onClose();
    } catch (e) { toast(plain(e, 'The setup could not be uploaded. Try again.')); }
    finally { setBusy(false); }
  }

  const line = cloudLine(status);
  return (
    <Sheet onClose={onClose} labelledBy="cuh" className="small-sheet" busy={busy}>
      <SheetTop id="cuh" title="Upload to cloud" sub={`Copies ${name} to a workspace on HarnessRouter Cloud. This instance stays the source: uploading again replaces the copy.`} onClose={onClose} />
      {line ? <p className="set-help">{line}.</p> : null}
      {targets === null ? (
        failed
          ? <div className="empty-list ld-fail" role="alert">The cloud workspaces could not be read just now. <button type="button" className="link-q inl" onClick={read}>Try again</button></div>
          : <div className="empty-list" role="status" style={{ padding: '16px 0' }}>Reading your cloud workspaces…</div>
      ) : (
        <>
          <div className="set-f"><label htmlFor="cloudTo">To</label>
            <select id="cloudTo" className="set-in" value={choice} disabled={busy} onChange={(e) => setChoice(e.target.value)}>
              {targets.map((t) => <option key={t.id} value={t.id} disabled={t.revoked}>{t.label}{t.revoked ? ' (its key was revoked)' : ''}</option>)}
              <option value={ADD}>Add a cloud workspace…</option>
            </select>
          </div>
          {adding ? (
            <div className="set-f"><label htmlFor="cloudKey">A key from the cloud workspace</label>
              <div className="keyrow">
                <input id="cloudKey" ref={keyRef} className="set-in" type="password" autoComplete="off" placeholder="sk-hr-…" value={key}
                  onChange={(e) => setKey(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter' && !e.nativeEvent.isComposing) { e.preventDefault(); void add(); } }} />
                <button type="button" className="btn" disabled={busy || !key.trim()} onClick={() => void add()}>{busy ? 'Adding' : 'Add'}</button>
              </div>
              <p className="set-help">From the cloud console, inside the workspace, under API Keys.</p>
            </div>
          ) : null}
        </>
      )}
      <div className="sheet-actions">
        <button type="button" className="btn" disabled={busy} onClick={onClose}>Cancel</button>
        <button type="button" className="btn primary" disabled={busy || adding || !choice || targets === null} onClick={() => void upload()}>
          {busy && !adding ? 'Uploading…' : status?.uploaded ? 'Replace the copy' : 'Upload'}
        </button>
      </div>
    </Sheet>
  );
}
