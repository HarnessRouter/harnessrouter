'use client';
// Deploy to another workspace (Deploy to Cloud's menu, DeployCloud.tsx): this setup copied to a
// workspace on 云端服务 other than the one its one-click deploy goes to, one way. This
// instance stays the source: a deploy creates the cloud copy, and each later one replaces it. Where it
// goes is one of the cloud workspaces this instance keeps a key for (the workspace settings' Cloud
// upload lists them); one can be added here by pasting a key from that workspace. The key is kept on
// this instance and never read back. What is said of the last deploy (when, and whether the setup
// changed since) is the server's own status.
import { useEffect, useRef, useState } from 'react';
import { addTarget, listTargets, uploadOne, type CloudStatus, type CloudTarget } from '@/lib/cloud-upload';
import { ago } from '../setups';
import { Sheet, SheetTop } from '../Sheet';
import { toast } from '../toast';
import { plain } from './settingsModel';

const ADD = '__add__';

/** The status of a setup's cloud copy, as a short line ('' while it is not read, or never uploaded). */
export function cloudLine(s: CloudStatus | null): string {
  if (!s || !s.uploaded) return '';
  const when = s.uploaded_at ? ago(s.uploaded_at > 1e12 ? s.uploaded_at : s.uploaded_at * 1000) : '';
  return s.changed ? `Changed since its deploy${when ? ` ${when}` : ''}` : `Deployed${when ? ` ${when}` : ''}`;
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
      if (!r.ok) { toast(plain(new Error(r.error || ''), `${name} could not be deployed. Try again.`)); return; }
      toast(r.action === 'create' ? `${name} is deployed to that workspace.` : `${name}’s copy in that workspace is replaced.`);
      onDone();
      onClose();
    } catch (e) { toast(plain(e, `${name} could not be deployed. Try again.`)); }
    finally { setBusy(false); }
  }

  const line = cloudLine(status);
  return (
    <Sheet onClose={onClose} labelledBy="cuh" className="small-sheet" busy={busy}>
      <SheetTop id="cuh" title="部署到其他工作区" sub={`Deploys ${name} to a workspace on 云端服务. This instance stays the source: deploying again replaces the copy.`} onClose={onClose} />
      {line ? <p className="set-help">{line}.</p> : null}
      {targets === null ? (
        failed
          ? <div className="empty-list ld-fail" role="alert">暂时无法读取云端工作区。 <button type="button" className="link-q inl" onClick={read}>重试</button></div>
          : <div className="empty-list" role="status" style={{ padding: '16px 0' }}>正在读取云端工作区…</div>
      ) : (
        <>
          <div className="set-f"><label htmlFor="cloudTo">目标</label>
            <select id="cloudTo" className="set-in" value={choice} disabled={busy} onChange={(e) => setChoice(e.target.value)}>
              {targets.map((t) => <option key={t.id} value={t.id} disabled={t.revoked}>{t.label}{t.revoked ? ' (its key was revoked)' : ''}</option>)}
              <option value={ADD}>添加云端工作区…</option>
            </select>
          </div>
          {adding ? (
            <div className="set-f"><label htmlFor="cloudKey">云端工作区密钥</label>
              <div className="keyrow">
                <input id="cloudKey" ref={keyRef} className="set-in" type="password" autoComplete="off" placeholder="sk-hr-…" value={key}
                  onChange={(e) => setKey(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter' && !e.nativeEvent.isComposing) { e.preventDefault(); void add(); } }} />
                <button type="button" className="btn" disabled={busy || !key.trim()} onClick={() => void add()}>{busy ? 'Adding' : 'Add'}</button>
              </div>
              <p className="set-help">在云端控制台的工作区中打开 API 密钥页面。</p>
            </div>
          ) : null}
        </>
      )}
      <div className="sheet-actions">
        <button type="button" className="btn" disabled={busy} onClick={onClose}>取消</button>
        <button type="button" className="btn primary" disabled={busy || adding || !choice || targets === null} onClick={() => void upload()}>
          {busy && !adding ? 'Deploying…' : 'Deploy'}
        </button>
      </div>
    </Sheet>
  );
}
