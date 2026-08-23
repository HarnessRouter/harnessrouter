'use client';
// One dialog for one harness or many. The destination is a picker over the stored workspaces,
// with "Add a workspace" inline: paste a key, Test shows where it lands, and the upload uses it.
// Rows run independently on the server; each answers for itself here.
import { useEffect, useState } from 'react';
import { addTarget, listTargets, uploadMany, type CloudTarget, type UploadRow } from '@/lib/cloud-upload';

export interface UploadItem { id: string; name: string; builtin?: boolean; includes?: string; uploaded?: boolean }
const ADD = '__add__';

export function CloudUploadDialog({ items, onClose, onDone }: {
  items: UploadItem[]; onClose: () => void; onDone?: (rows: UploadRow[]) => void;
}) {
  const [targets, setTargets] = useState<CloudTarget[] | null>(null);
  const [choice, setChoice] = useState<string>('');
  const [key, setKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [rows, setRows] = useState<UploadRow[] | null>(null);

  useEffect(() => {
    listTargets().then((r) => { const live = r.targets.filter((t) => !t.revoked); setTargets(r.targets); setChoice(live.length ? ((live.find((t) => t.id === r.last) ? r.last : live[0].id)) : ADD); })
      .catch(() => { setTargets([]); setChoice(ADD); });
  }, []);

  const eligible = items.filter((i) => !i.builtin);
  const single = items.length === 1;
  const adding = choice === ADD;

  async function add() {
    // One verb: Add verifies the key, stores the workspace, and the picker lands on it.
    setBusy(true); setErr(null);
    try {
      const t = await addTarget(key.trim());
      const r = await listTargets();
      setTargets(r.targets); setChoice(t.id); setKey('');
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  async function run() {
    setBusy(true); setErr(null);
    try {
      const r = await uploadMany(eligible.map((i) => i.id), choice);
      setRows(r.results); onDone?.(r.results);
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }

  const title = single ? `Upload "${items[0].name}"` : `Upload ${eligible.length} to cloud`;
  const canUpload = !busy && eligible.length > 0 && !adding;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <section className="modal" role="dialog" aria-modal="true" aria-labelledby="cloudUploadTitle" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div><h2 id="cloudUploadTitle">{title}</h2></div>
          <button className="icon-button modal-close" type="button" aria-label="Close dialog" onClick={onClose}><iconify-icon icon="tabler:x"></iconify-icon></button>
        </div>
        <div className="modal-body">
          {targets === null ? <p className="field-help">Loading</p> : rows ? (
            <div className="table-wrap cloud-rows"><table><tbody>
              {rows.map((r) => {
                const it = items.find((i) => i.id === r.id);
                return (<tr key={r.id}>
                  <td><strong>{it?.name || r.name || ''}</strong></td>
                  <td>{r.ok ? (r.action === 'create' ? 'Created' : 'Replaced') : r.action === 'skip' ? 'Skipped' : 'Failed'}</td>
                  <td className="cloud-note">{r.ok ? '' : r.error}</td>
                </tr>);
              })}
            </tbody></table></div>
          ) : (
            <div className="field-stack">
              <div className="field"><label htmlFor="cloudTo">To</label>
                <select id="cloudTo" value={choice} disabled={busy}
                  onChange={(e) => { setChoice(e.target.value); setErr(null); }}>
                  {targets.map((t) => <option key={t.id} value={t.id} disabled={t.revoked}>{t.label}{t.revoked ? ' (key revoked)' : ''}</option>)}
                  <option value={ADD}>Add a workspace…</option>
                </select>
              </div>
              {adding && (
                <div className="field"><label htmlFor="cloudKey">Workspace API key</label>
                  <div className="cloud-keyrow">
                    <input id="cloudKey" type="password" autoComplete="off" placeholder="sk-hr-" value={key}
                      onChange={(e) => setKey(e.target.value)} />
                    <button className="button primary" type="button" disabled={busy || !key.trim()} onClick={() => void add()}>{busy ? 'Adding…' : 'Add'}</button>
                  </div>
                  <span className="field-help">From the cloud console, inside the workspace, under Keys.</span>
                </div>
              )}
              {single && (
                <dl className="cloud-kv">
                  <div><dt>Includes</dt><dd>{items[0].includes || 'instructions'}</dd></div>
                </dl>
              )}
              {!single && (
                <div className="table-wrap cloud-rows"><table><tbody>
                  {items.map((i) => (<tr key={i.id}>
                    <td><strong>{i.name}</strong></td>
                    <td>{i.builtin ? 'Skip' : i.uploaded ? 'Replace' : 'Create'}</td>
                    <td className="cloud-note">{i.builtin ? 'built-in' : ''}</td>
                  </tr>))}
                </tbody></table></div>
              )}
              {single && items[0].uploaded && <span className="field-help">Replaces the cloud copy.</span>}
              {err && <div className="notice"><iconify-icon icon="tabler:alert-triangle"></iconify-icon><div>{err}</div></div>}
            </div>
          )}
          <div className="modal-actions">
            {rows ? <button className="button primary" type="button" onClick={onClose}>Done</button> : (<>
              <button className="button" type="button" onClick={onClose} disabled={busy}>Cancel</button>
              <button className="button primary" type="button" disabled={!canUpload} onClick={() => void run()}>
                {busy ? 'Uploading…' : single ? 'Upload' : `Upload ${eligible.length}`}
              </button>
            </>)}
          </div>
        </div>
      </section>
    </div>
  );
}
