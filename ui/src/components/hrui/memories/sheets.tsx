'use client';
// The sheets of the Memories pages: New memory (name, description, who keeps it), Connect (a server's
// address and a key, tried by the service at once), the list of services when none is connected yet,
// and Rename. Each is the console's Sheet.
import { useEffect, useState } from 'react';
import { connectProvider, createMemory, listProviderPlugs, updateMemory, type Memory, type Provider } from '@/lib/memories';
import { Sheet, SheetTop } from '../Sheet';
import { plain } from '../setup/settingsModel';
import { hasSchema, schemaLabels, serviceFacts, shapeOf } from './caps';
import { KindArt, type Kind } from './CardArt';
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

/** A memory's name and description, the same in every window that makes or renames one: side by side, and under
 *  them what the description is for, which stays when the field is filled. */
export function NameFields({ nameId, descId, name, desc, onName, onDesc, focus }: {
  nameId: string; descId: string; name: string; desc: string; onName: (v: string) => void; onDesc: (v: string) => void; focus?: boolean;
}) {
  return (
    <div className="mm-nf">
      <div className="set-f">
        <label htmlFor={nameId}>Name</label>
        <input id={nameId} className="set-in" value={name} placeholder="Brand kits" autoComplete="off" autoFocus={focus} onChange={(e) => onName(e.target.value)} />
      </div>
      <div className="set-f">
        <label htmlFor={descId}>Description</label>
        <textarea id={descId} className="set-in" rows={2} value={desc} placeholder="What is kept here, in a sentence." aria-describedby={`${descId}H`} onChange={(e) => onDesc(e.target.value)} />
      </div>
      <p className="set-help mm-nf-h" id={`${descId}H`}>Agents read the description to decide whether to look inside.</p>
    </div>
  );
}

/** One service in a list: its name and its one honest line. */
const Says = ({ p }: { p: Provider }) => <span className="grow"><b>{vendorName(p.id)}</b>{VENDORS[p.id]?.line ? <small>{VENDORS[p.id].line}</small> : null}</span>;

const LOCK = <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" aria-hidden="true"><rect x="5" y="11" width="14" height="9" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></svg>;

/** The shape a service gives a memory, read from what it says it does. */
const kindOf = (p: Provider | null): Kind => shapeOf(p);

/** One service, as a column of the comparison: the shape of memory it keeps, its name and line, then
 *  the same three facts as every other column, so they line up and read across. */
function ServiceBody({ p }: { p: Provider }) {
  return (
    <>
      <span className="mm-sv-pic"><KindArt kind={kindOf(p)} /></span>
      <Says p={p} />
      <span className="mm-sv-facts">
        {serviceFacts(p).map((f) => <span key={f.label}><small>{f.label}</small><em>{f.value}</em></span>)}
      </span>
    </>
  );
}

/** The services when none is connected yet: the same comparison New memory chooses from, every column
 *  offering Connect, so the first choice is made the way every later one is. */
export function ChooseServiceSheet({ providers, onClose, onConnected }: { providers: Provider[]; onClose: () => void; onConnected: (id: string) => void | Promise<unknown> }) {
  const [picked, setPicked] = useState('');
  if (picked) return <ConnectSheet id={picked} onClose={() => setPicked('')} onConnected={onConnected} />;
  return (
    <Sheet onClose={onClose} labelledBy="mmCh" className="mm-sheet mm-new-sheet">
      <SheetTop id="mmCh" title="Connect a memory service" sub="Your setups keep what they learn there. Each service keeps it its own way." onClose={onClose} />
      <div className="mm-prov mm-sv mm-sv-cn">
        {providers.map((p) => (
          <div key={p.id} className="mm-pv-o cn">
            <ServiceBody p={p} />
            <button type="button" className="btn small" onClick={() => setPicked(p.id)}>Connect</button>
          </div>
        ))}
      </div>
      <p className="set-help mm-sv-guide">Each runs as its own server. <a className="link-q inl" href={GUIDE} target="_blank" rel="noopener noreferrer">How to run a server</a></p>
    </Sheet>
  );
}

/** New memory. The service it is kept by is fixed once created, so it is chosen from a comparison:
 *  every service side by side, each with the same facts read from its capability document. One not
 *  connected is drawn unbuilt (dashed) and offers Connect. Name and description come first; Create,
 *  next to the choice it follows from, says what comes next. */
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
  // arrows move the choice along the connected services, as in any group of radio buttons
  const onKey = (e: React.KeyboardEvent) => {
    const d = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1 : e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 0;
    if (!d || !open.length || !sel) return;
    e.preventDefault();
    const next = open[(open.indexOf(sel) + d + open.length) % open.length];
    setChosen(next.id);
    (e.currentTarget.querySelector(`[data-sv="${next.id}"]`) as HTMLElement | null)?.focus();
  };
  if (connecting) {
    return (
      <ConnectSheet id={connecting.id} connected={connecting.connected} onClose={() => setConnecting(null)}
        onConnected={async (id) => { await reloadProviders(); setChosen(id); setConnecting(null); }} />
    );
  }
  return (
    <Sheet onClose={onClose} labelledBy="mmCrT" className="mm-sheet mm-new-sheet" busy={busy}>
      <SheetTop id="mmCrT" title="New memory" onClose={onClose} />
      <NameFields nameId="mmCrName" descId="mmCrDesc" name={name} desc={desc} onName={setName} onDesc={setDesc} />
      <div className="set-f mm-kept">
        <div className="mm-kept-h">
          <span className="set-lb" id="mmCrKept">Kept by</span>
          {sel ? <button type="button" className="link-q inl" aria-label={`Change ${vendorName(sel.id)} connection`} onClick={() => setConnecting({ id: sel.id, connected: true })}>Change connection</button> : null}
        </div>
        {failed ? (
          <p className="mm-err" role="alert">The memory services could not be read just now. <button type="button" className="link-q inl" onClick={retry}>Try again</button></p>
        ) : (
          <div className="mm-prov mm-sv" role="radiogroup" aria-labelledby="mmCrKept" onKeyDown={onKey}>
            {(providers || []).map((p) => (p.connected ? (
              <button key={p.id} type="button" role="radio" aria-checked={sel?.id === p.id} tabIndex={sel?.id === p.id ? 0 : -1} data-sv={p.id}
                className={`mm-pv-o${sel?.id === p.id ? ' on' : ''}`} onClick={() => setChosen(p.id)}>
                <i className="mm-sv-dot" aria-hidden="true" /><ServiceBody p={p} />
              </button>
            ) : (
              <div key={p.id} className="mm-pv-o off">
                <ServiceBody p={p} />
                <button type="button" className="btn small" onClick={() => setConnecting({ id: p.id, connected: false })}>Connect</button>
              </div>
            )))}
          </div>
        )}
      </div>
      {err ? <p className="mm-err" role="alert">{err}</p> : null}
      <div className="sheet-actions">
        <span className="mm-lock">{LOCK}Fixed once created</span>
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
    <Sheet onClose={onClose} labelledBy="mmRn" className="mm-sheet mm-nd-sheet" busy={busy}>
      <SheetTop id="mmRn" title="Rename and describe" onClose={onClose} />
      <NameFields nameId="mmRnN" descId="mmRnD" name={name} desc={desc} onName={setName} onDesc={setDesc} />
      {err ? <p className="mm-err" role="alert">{err}</p> : null}
      <div className="sheet-actions">
        <span className="grow" />
        <button type="button" className="btn" disabled={busy} onClick={onClose}>Cancel</button>
        <button type="button" className="btn primary" disabled={!name.trim() || busy} onClick={() => void go()}>Save</button>
      </div>
    </Sheet>
  );
}
