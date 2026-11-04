'use client';
// The sheets of the Memories pages: New memory (name, description, who keeps it), Connect (a server's
// address and a key, tried by the service at once), the list of services when none is connected yet,
// and Rename. Each is the console's Sheet.
import { useEffect, useState } from 'react';
import { connectProvider, createMemory, listProviderPlugs, updateMemory, type Memory, type Provider } from '@/lib/memories';
import { Sheet, SheetTop } from '../Sheet';
import { plain } from '../setup/settingsModel';
import { hasSchema, schemaLabels } from './caps';
import { GUIDE, VENDORS, vendorName } from './vendors';

/** Connecting one service: its address and, optionally, its key. The service tries both, and its
 *  refusal is shown here in its own words. */
export function ConnectSheet({ id, connected, onClose, onConnected }: {
  id: string; connected?: boolean; onClose: () => void; onConnected: (id: string) => void | Promise<unknown>;
}) {
  const name = vendorName(id);
  const addressOptional = VENDORS[id]?.address === 'optional';
  const [base, setBase] = useState('');
  const [key, setKey] = useState('');
  const [keptKey, setKeptKey] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  // changing a connection starts from the address it has; a key is only ever said to be kept
  useEffect(() => {
    if (!connected) return;
    let live = true;
    listProviderPlugs().then((l) => {
      if (!live) return;
      const p = l.find((x) => x.type === id);
      setBase(String(p?.config?.base_url || ''));
      setKeptKey(!!p?.secrets_set?.includes('api_key'));
    }).catch(() => {});
    return () => { live = false; };
  }, [connected, id]);
  const needsKey = addressOptional && !base.trim() && !keptKey;
  const ready = (addressOptional || !!base.trim()) && (!needsKey || !!key.trim());
  const go = async () => {
    if (!ready || busy) return;
    setBusy(true); setErr('');
    try {
      await connectProvider(id, { baseUrl: base.trim(), apiKey: key.trim() });
      await onConnected(id);
    } catch (e) { setErr(plain(e, `${name} could not be connected. Check the address and the key.`)); setBusy(false); }
  };
  return (
    <Sheet onClose={onClose} labelledBy="mmCn" className="small-sheet mm-sheet" busy={busy}>
      <SheetTop id="mmCn" title={`${connected ? 'Change' : 'Connect'} ${name}`} sub={VENDORS[id]?.line} onClose={onClose} />
      <form noValidate onSubmit={(e) => { e.preventDefault(); void go(); }}>
        <div className="set-f">
          <label htmlFor="mmCnBase">Server address</label>
          <input id="mmCnBase" className="set-in" type="url" inputMode="url" value={base} autoComplete="off" placeholder="https://memory.example.com" onChange={(e) => setBase(e.target.value)} />
          <p className="set-help">
            {addressOptional ? `Leave it empty to use ${name}’s own service. A key is needed then. ` : null}
            <a className="link-q inl" href={GUIDE} target="_blank" rel="noopener noreferrer">How to run a server</a>
          </p>
        </div>
        <div className="set-f">
          <label htmlFor="mmCnKey">{needsKey ? 'Key' : 'Key (optional)'}</label>
          <input id="mmCnKey" className="set-in" type="password" value={key} autoComplete="off" placeholder={keptKey ? 'Keep the key already saved' : undefined} onChange={(e) => setKey(e.target.value)} />
          <p className="set-help">Stored securely. It is never shown again.</p>
        </div>
        {err ? <p className="mm-err" role="alert">{err}</p> : null}
        <div className="sheet-actions">
          <span className="grow" />
          <button type="button" className="btn" disabled={busy} onClick={onClose}>Cancel</button>
          <button type="submit" className="btn primary" disabled={!ready || busy}>{busy ? 'Connecting…' : connected ? 'Save' : 'Connect'}</button>
        </div>
      </form>
    </Sheet>
  );
}

/** One service in a list: its name and its one honest line. */
const Says = ({ p }: { p: Provider }) => <span className="grow"><b>{vendorName(p.id)}</b>{VENDORS[p.id]?.line ? <small>{VENDORS[p.id].line}</small> : null}</span>;

/** The services when none is connected yet: pick one and connect it. */
export function ChooseServiceSheet({ providers, onClose, onConnected }: { providers: Provider[]; onClose: () => void; onConnected: (id: string) => void | Promise<unknown> }) {
  const [picked, setPicked] = useState('');
  if (picked) return <ConnectSheet id={picked} onClose={() => setPicked('')} onConnected={onConnected} />;
  return (
    <Sheet onClose={onClose} labelledBy="mmCh" className="mm-sheet">
      <SheetTop id="mmCh" title="Connect a memory service" sub="Your setups keep what they learn there." onClose={onClose} />
      <div className="mm-prov">
        {providers.map((p) => (
          <div key={p.id} className="mm-pv-o off"><Says p={p} />
            <button type="button" className="btn small" onClick={() => setPicked(p.id)}>Connect</button>
          </div>
        ))}
      </div>
    </Sheet>
  );
}

/** New memory: who keeps it lists every service, and one not connected offers Connect in place of
 *  being chosen. A schema is designed only where the service reads one, so Create says what comes next. */
export function NewMemorySheet({ providers, failed, retry, picked, onClose, onCreated, reloadProviders }: {
  providers: Provider[] | null; failed: boolean; retry: () => void; picked?: string;
  onClose: () => void; onCreated: (m: Memory, p: Provider) => void; reloadProviders: () => Promise<Provider[] | null>;
}) {
  const [name, setName] = useState('');
  const [desc, setDesc] = useState('');
  const [chosen, setChosen] = useState(picked || '');
  const [connecting, setConnecting] = useState<{ id: string; connected: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const open = (providers || []).filter((p) => p.connected);
  const sel = open.find((p) => p.id === chosen) || open[0] || null;
  const guided = hasSchema(sel);
  const go = async () => {
    if (!sel || !name.trim() || busy) return;
    setBusy(true); setErr('');
    try { onCreated(await createMemory({ name: name.trim(), description: desc.trim(), provider: sel.id }), sel); }
    catch (e) { setErr(plain(e, 'The memory was not created. Try again.')); setBusy(false); }
  };
  if (connecting) {
    return (
      <ConnectSheet id={connecting.id} connected={connecting.connected} onClose={() => setConnecting(null)}
        onConnected={async (id) => { await reloadProviders(); setChosen(id); setConnecting(null); }} />
    );
  }
  return (
    <Sheet onClose={onClose} labelledBy="mmCrT" className="mm-sheet" busy={busy}>
      <SheetTop id="mmCrT" title="New memory" onClose={onClose}
        sub={schemaLabels(sel) ? 'Name it, then add its labels.' : guided ? 'Name it, then design its schema.' : 'Name it, then start keeping records in it.'} />
      <div className="set-f">
        <label htmlFor="mmCrName">Name</label>
        <input id="mmCrName" className="set-in" value={name} placeholder="Brand kits" autoComplete="off" onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="set-f">
        <label htmlFor="mmCrDesc">Description</label>
        <textarea id="mmCrDesc" className="set-in" rows={2} value={desc} placeholder="What is kept here, in a sentence. Agents read it to decide whether to look inside." onChange={(e) => setDesc(e.target.value)} />
      </div>
      <div className="set-f">
        <span className="set-lb">Kept by</span>
        {failed ? (
          <p className="mm-err" role="alert">The memory services could not be read just now. <button type="button" className="link-q inl" onClick={retry}>Try again</button></p>
        ) : (
          <div className="mm-prov">
            {(providers || []).map((p) => (p.connected ? (
              <div key={p.id} className={`mm-pv-r${sel?.id === p.id ? ' on' : ''}`}>
                <button type="button" className={`mm-pv-o${sel?.id === p.id ? ' on' : ''}`} aria-pressed={sel?.id === p.id} onClick={() => setChosen(p.id)}>
                  <i aria-hidden="true" /><Says p={p} />
                </button>
                <button type="button" className="link-q mm-pv-ch" aria-label={`Change ${vendorName(p.id)} connection`} onClick={() => setConnecting({ id: p.id, connected: true })}>Change</button>
              </div>
            ) : (
              <div key={p.id} className="mm-pv-o off"><Says p={p} />
                <button type="button" className="btn small" onClick={() => setConnecting({ id: p.id, connected: false })}>Connect</button>
              </div>
            )))}
          </div>
        )}
        <p className="set-help">Fixed once created.</p>
      </div>
      {err ? <p className="mm-err" role="alert">{err}</p> : null}
      <div className="sheet-actions">
        <span className="grow" />
        <button type="button" className="btn" disabled={busy} onClick={onClose}>Cancel</button>
        <button type="button" className="btn primary" disabled={!sel || !name.trim() || busy} onClick={() => void go()}>
          {!guided ? 'Create' : schemaLabels(sel) ? 'Create and add labels' : 'Create and design schema'}
        </button>
      </div>
    </Sheet>
  );
}

/** Its name and description. The description is what an agent reads to decide whether to look inside. */
export function RenameSheet({ m, onClose, onDone }: { m: Memory; onClose: () => void; onDone: (m: Memory) => void }) {
  const [name, setName] = useState(m.name);
  const [desc, setDesc] = useState(m.description);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const go = async () => {
    if (!name.trim() || busy) return;
    setBusy(true); setErr('');
    try { onDone(await updateMemory(m.id, { name: name.trim(), description: desc.trim() })); }
    catch (e) { setErr(plain(e, 'That was not saved. Try again.')); setBusy(false); }
  };
  return (
    <Sheet onClose={onClose} labelledBy="mmRn" className="small-sheet mm-sheet" busy={busy}>
      <SheetTop id="mmRn" title="Rename and describe" onClose={onClose} />
      <div className="set-f"><label htmlFor="mmRnN">Name</label><input id="mmRnN" className="set-in" value={name} autoComplete="off" onChange={(e) => setName(e.target.value)} /></div>
      <div className="set-f"><label htmlFor="mmRnD">Description</label><textarea id="mmRnD" className="set-in" rows={3} value={desc} placeholder="What is kept here, in a sentence. Agents read it to decide whether to look inside." onChange={(e) => setDesc(e.target.value)} /></div>
      {err ? <p className="mm-err" role="alert">{err}</p> : null}
      <div className="sheet-actions">
        <span className="grow" />
        <button type="button" className="btn" disabled={busy} onClick={onClose}>Cancel</button>
        <button type="button" className="btn primary" disabled={!name.trim() || busy} onClick={() => void go()}>Save</button>
      </div>
    </Sheet>
  );
}
