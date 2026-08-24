'use client';
// Settings: the stored cloud workspaces. Add with a key, remove any time. One sentence of
// contract. Self-hosted only.
import { useEffect, useState } from 'react';
import { addTarget, listTargets, removeTarget, type CloudTarget } from '@/lib/cloud-upload';

export function CloudUploadCard() {
  const [targets, setTargets] = useState<CloudTarget[] | null>(null);
  const [key, setKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => { listTargets().then((r) => setTargets(r.targets)).catch(() => setTargets([])); }, []);

  async function add(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setErr(null);
    try { await addTarget(key.trim()); setKey(''); setTargets((await listTargets()).targets); }
    catch (er) { setErr(er instanceof Error ? er.message : String(er)); }
    finally { setBusy(false); }
  }
  async function remove(id: string) {
    setBusy(true); setErr(null);
    try { setTargets((await removeTarget(id)).targets); }
    catch (er) { setErr(er instanceof Error ? er.message : String(er)); }
    finally { setBusy(false); }
  }

  return (
    <form className="settings-form" onSubmit={add}>
      <div className="settings-form-head">
        <div><h2>Cloud upload</h2><p>Uploading replaces the cloud copy.</p></div>
        <div className="header-actions">
          <span className="save-state">{targets && targets.length ? `${targets.length} workspace${targets.length === 1 ? '' : 's'}` : 'No workspaces yet'}</span>
        </div>
      </div>
      <section className="form-section">
        <div><h3>Workspaces</h3></div>
        <div className="field-stack">
          {targets && targets.length > 0 && (
            <div className="table-wrap cloud-rows"><table><tbody>
              {targets.map((t) => (<tr key={t.id}>
                <td><strong>{t.label}</strong></td>
                <td className="cloud-note">{t.revoked ? 'Key revoked. Paste a new one.' : t.key_hint}</td>
                <td className="cloud-remove"><button className="button quiet small" type="button" disabled={busy} onClick={() => void remove(t.id)}>Remove</button></td>
              </tr>))}
            </tbody></table></div>
          )}
          <div className="field"><label htmlFor="cloudKey">Add a workspace</label>
            <div className="cloud-keyrow">
              <input id="cloudKey" type="password" autoComplete="off" placeholder="sk-hr-" value={key}
                onChange={(e) => setKey(e.target.value)} />
              <button className="button primary" type="submit" disabled={busy || !key.trim()}>{busy ? 'Adding…' : 'Add'}</button>
            </div>
            <span className="field-help">From the cloud console, inside the workspace, under Keys.</span>
          </div>
          {err && <div className="notice"><iconify-icon icon="tabler:alert-triangle"></iconify-icon><div>{err}</div></div>}
        </div>
      </section>
    </form>
  );
}
