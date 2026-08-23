'use client';
// Settings: where uploads land. One key, one Test, one sentence of contract. Self-hosted only.
import { useEffect, useState } from 'react';
import { clearTarget, destination, getTarget, saveTarget, testTarget, type CloudTarget } from '@/lib/cloud-upload';

export function CloudUploadCard() {
  const [target, setTarget] = useState<CloudTarget | null>(null);
  const [key, setKey] = useState('');
  const [tested, setTested] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [savedTick, setSavedTick] = useState(false);

  useEffect(() => { getTarget().then(setTarget).catch(() => setTarget({ configured: false } as CloudTarget)); }, []);

  async function test() {
    setBusy(true); setErr(null);
    try { setTested(destination(await testTarget(key.trim() || undefined))); }
    catch (e) { setTested(null); setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  async function save(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setErr(null);
    try { setTarget(await saveTarget(key.trim())); setKey(''); setTested(null); setSavedTick(true); setTimeout(() => setSavedTick(false), 2000); }
    catch (er) { setErr(er instanceof Error ? er.message : String(er)); }
    finally { setBusy(false); }
  }
  async function disconnect() {
    setBusy(true); setErr(null);
    try { await clearTarget(); setTarget({ configured: false } as CloudTarget); setTested(null); }
    catch (er) { setErr(er instanceof Error ? er.message : String(er)); }
    finally { setBusy(false); }
  }

  const shown = tested || (target?.configured ? destination(target) : null);
  return (
    <form className="settings-form" onSubmit={save}>
      <div className="settings-form-head">
        <div><h2>Cloud upload</h2><p>Uploading replaces the cloud copy.</p></div>
        <div className="header-actions">
          <span className="save-state">{savedTick ? 'Saved' : target?.configured ? 'Connected' : 'Not connected'}</span>
          {target?.configured && <button className="button" type="button" disabled={busy} onClick={() => void disconnect()}>Disconnect</button>}
          <button className="button primary" type="submit" disabled={busy || !key.trim()}>{busy ? 'Saving…' : 'Save'}</button>
        </div>
      </div>
      <section className="form-section">
        <div><h3>Workspace API key</h3></div>
        <div className="field-stack">
          <div className="field"><label htmlFor="cloudKey">Key</label>
            <div className="cloud-keyrow">
              <input id="cloudKey" type="password" autoComplete="off" placeholder={target?.configured ? target.key_hint : 'sk-hr-'}
                value={key} onChange={(e) => { setKey(e.target.value); setTested(null); }} />
              <button className="button" type="button" disabled={busy || (!key.trim() && !target?.configured)} onClick={() => void test()}>Test</button>
            </div>
            {shown && <span className="field-help"><span className="status healthy">{shown}</span></span>}
          </div>
          {err && <div className="notice"><iconify-icon icon="tabler:alert-triangle"></iconify-icon><div>{err}</div></div>}
        </div>
      </section>
    </form>
  );
}
