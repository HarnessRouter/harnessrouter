'use client';
// One dialog for one harness or many. Without a saved key the key step is inlined on top, so the
// first upload is two clicks and every later one is one. Rows run independently on the server;
// each answers for itself here.
import { useEffect, useState } from 'react';
import { destination, getTarget, saveTarget, testTarget, uploadMany, type CloudTarget, type UploadRow } from '@/lib/cloud-upload';

export interface UploadItem { id: string; name: string; builtin?: boolean; includes?: string; uploaded?: boolean }

export function CloudUploadDialog({ items, onClose, onDone }: {
  items: UploadItem[]; onClose: () => void; onDone?: (rows: UploadRow[]) => void;
}) {
  const [target, setTarget] = useState<CloudTarget | null>(null);
  const [key, setKey] = useState('');
  const [tested, setTested] = useState<{ org_name: string; org: string; workspace_name: string; workspace: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [rows, setRows] = useState<UploadRow[] | null>(null);

  useEffect(() => { getTarget().then(setTarget).catch(() => setTarget({ configured: false } as CloudTarget)); }, []);

  const eligible = items.filter((i) => !i.builtin);
  const single = items.length === 1;
  const needKey = target !== null && !target.configured;
  const dest = target?.configured ? destination(target) : tested ? destination(tested) : '';

  async function test() {
    setBusy(true); setErr(null);
    try { setTested(await testTarget(key.trim())); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); setTested(null); }
    finally { setBusy(false); }
  }
  async function run() {
    setBusy(true); setErr(null);
    try {
      if (needKey) setTarget(await saveTarget(key.trim()));
      const r = await uploadMany(eligible.map((i) => i.id));
      setRows(r.results); onDone?.(r.results);
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }

  const title = single ? `Upload "${items[0].name}"` : `Upload ${eligible.length} to cloud`;
  const canUpload = !busy && eligible.length > 0 && (!needKey || (key.trim().length > 0 && tested !== null));

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <section className="modal" role="dialog" aria-modal="true" aria-labelledby="cloudUploadTitle" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div><h2 id="cloudUploadTitle">{title}</h2></div>
          <button className="icon-button modal-close" type="button" aria-label="Close dialog" onClick={onClose}><iconify-icon icon="tabler:x"></iconify-icon></button>
        </div>
        <div className="modal-body">
          {target === null ? <p className="field-help">Loading</p> : rows ? (
            <div className="table-wrap cloud-rows"><table><tbody>
              {rows.map((r) => {
                const it = items.find((i) => i.id === r.id);
                return (<tr key={r.id}>
                  <td><strong>{it?.name || r.name || r.id}</strong></td>
                  <td>{r.ok ? (r.action === 'create' ? 'Created' : 'Replaced') : r.action === 'skip' ? 'Skipped' : 'Failed'}</td>
                  <td className="cloud-note">{r.ok ? '' : r.error}</td>
                </tr>);
              })}
            </tbody></table></div>
          ) : (
            <div className="field-stack">
              {needKey && (
                <div className="field"><label htmlFor="cloudKey">Workspace API key</label>
                  <div className="cloud-keyrow">
                    <input id="cloudKey" type="password" autoComplete="off" placeholder="sk-hr-" value={key}
                      onChange={(e) => { setKey(e.target.value); setTested(null); }} />
                    <button className="button" type="button" disabled={busy || !key.trim()} onClick={() => void test()}>Test</button>
                  </div>
                  <span className="field-help">Get one in the cloud console under Keys, inside the workspace.</span>
                </div>
              )}
              <dl className="cloud-kv">
                <div><dt>To</dt><dd>{dest || '…'}</dd></div>
                {single ? (
                  <div><dt>Includes</dt><dd>{items[0].includes || 'instructions'}</dd></div>
                ) : null}
              </dl>
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
