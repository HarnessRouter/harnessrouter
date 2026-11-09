'use client';
// The sheets of the Memories pages: New memory (a name and, if you like, a description: the engine is chosen for you
// from them, and can be changed), Use in (give a memory to a setup, which then remembers there), Connect (an engine's
// address and a key, tried by the service at once), the list of engines to connect, and Rename. Each is the console's
// Sheet.
import { useEffect, useMemo, useState } from 'react';
import { listCustom } from '@/lib/harness';
import { connectProvider, createMemory, listProviderPlugs, setAgentMemory, updateMemory, type Memory, type Provider } from '@/lib/memories';
import { Sheet, SheetTop } from '../Sheet';
import { Skel, SkLine } from '../Skel';
import { plain } from '../setup/settingsModel';
import { serviceFacts, shapeOf } from './caps';
import { KindArt, type Kind } from './CardArt';
import { chooseEngine, GUIDE, VENDORS, vendorName } from './vendors';

/** Connecting one engine: its address and, optionally, its key. The service tries both, and its
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
            {addressOptional ? `Leave it empty to use ${name}’s own cloud. A key is needed then. ` : null}
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
export function NameFields({ nameId, descId, name, desc, onName, onDesc, focus, optional }: {
  nameId: string; descId: string; name: string; desc: string; onName: (v: string) => void; onDesc: (v: string) => void; focus?: boolean;
  /** the description may be left out (New memory says so) */
  optional?: boolean;
}) {
  return (
    <div className="mm-nf">
      <div className="set-f">
        <label htmlFor={nameId}>Name</label>
        <input id={nameId} className="set-in" value={name} placeholder="Brand kits" autoComplete="off" autoFocus={focus} onChange={(e) => onName(e.target.value)} />
      </div>
      <div className="set-f">
        <label htmlFor={descId}>{optional ? <>Description <span className="mm-opt">optional</span></> : 'Description'}</label>
        <textarea id={descId} className="set-in" rows={2} value={desc} placeholder="What is kept here, in a sentence." aria-describedby={`${descId}H`} onChange={(e) => onDesc(e.target.value)} />
      </div>
      <p className="set-help mm-nf-h" id={`${descId}H`}>Agents read the description to decide whether to look inside.</p>
    </div>
  );
}

/** One engine in a list: its name and its one honest line. */
const Says = ({ p }: { p: Provider }) => <span className="grow"><b>{vendorName(p.id)}</b>{VENDORS[p.id]?.line ? <small>{VENDORS[p.id].line}</small> : null}</span>;

/** The shape an engine gives a memory, read from what it says it does. */
const kindOf = (p: Provider | null): Kind => shapeOf(p);

/** One engine, as a column of the comparison: the shape of memory it keeps, its name and line, then
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

/** Every engine, each offering Connect, or Change where it is connected already: the page's More, Connect an engine. */
export function ChooseServiceSheet({ providers, onClose, onConnected }: { providers: Provider[]; onClose: () => void; onConnected: (id: string) => void | Promise<unknown> }) {
  const [picked, setPicked] = useState<{ id: string; connected: boolean } | null>(null);
  if (picked) return <ConnectSheet id={picked.id} connected={picked.connected} onClose={() => setPicked(null)} onConnected={onConnected} />;
  return (
    <Sheet onClose={onClose} labelledBy="mmCh" className="mm-sheet mm-new-sheet">
      <SheetTop id="mmCh" title="Connect a memory engine" sub="Your agents keep what they learn in an engine. Each keeps it its own way." onClose={onClose} />
      <div className="mm-prov mm-sv mm-sv-cn">
        {providers.map((p) => (
          <div key={p.id} className="mm-pv-o cn">
            <ServiceBody p={p} />
            <button type="button" className="btn small" onClick={() => setPicked({ id: p.id, connected: !!p.connected })}>{p.connected ? 'Change' : 'Connect'}</button>
          </div>
        ))}
      </div>
      <p className="set-help mm-sv-guide">Each runs as its own server. <a className="link-q inl" href={GUIDE} target="_blank" rel="noopener noreferrer">How to run them</a></p>
    </Sheet>
  );
}

/** New memory: a name and, if you like, a description. The engine is chosen for you from them (vendors.ts
 *  chooseEngine, the reading the service gives an agent), shown with why, and can be changed under Engine to any
 *  engine that is connected. Connecting another lives on the page, under More. */
export function NewMemorySheet({ providers, failed, retry, picked, onClose, onCreated, onConnect }: {
  providers: Provider[] | null; failed: boolean; retry: () => void; picked?: string;
  onClose: () => void; onCreated: (m: Memory, p: Provider) => void;
  /** where no engine is connected yet: the way to connect one */
  onConnect?: () => void;
}) {
  const [name, setName] = useState('');
  const [desc, setDesc] = useState('');
  const [chosen, setChosen] = useState(picked || '');
  const [changing, setChanging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const open = useMemo(() => (providers || []).filter((p) => p.connected), [providers]);
  const auto = chooseEngine(`${name} ${desc}`, open.map((p) => p.id));
  const sel = open.find((p) => p.id === chosen) || open.find((p) => p.id === auto?.id) || null;
  const why = sel && sel.id === chosen ? VENDORS[sel.id]?.line || '' : auto?.why || '';
  const go = async () => {
    if (!sel || !name.trim() || busy) return;
    setBusy(true); setErr('');
    try { onCreated(await createMemory({ name: name.trim(), description: desc.trim(), provider: sel.id }), sel); }
    catch (e) { setErr(plain(e, 'The memory was not created. Try again.')); setBusy(false); }
  };
  // arrows move the choice along the connected engines, as in any group of radio buttons
  const onKey = (e: React.KeyboardEvent) => {
    const d = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1 : e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 0;
    if (!d || !open.length || !sel) return;
    e.preventDefault();
    const next = open[(open.indexOf(sel) + d + open.length) % open.length];
    setChosen(next.id);
    (e.currentTarget.querySelector(`[data-sv="${next.id}"]`) as HTMLElement | null)?.focus();
  };
  return (
    <Sheet onClose={onClose} labelledBy="mmCrT" className="mm-sheet mm-nd-sheet mm-new-mem" busy={busy}>
      <SheetTop id="mmCrT" title="New memory" onClose={onClose} />
      <form className="mm-new-f" noValidate onSubmit={(e) => { e.preventDefault(); void go(); }}>
        <NameFields nameId="mmCrName" descId="mmCrDesc" name={name} desc={desc} onName={setName} onDesc={setDesc} focus optional />
        <div className="set-f mm-eng">
          <div className="mm-kept-h">
            <span className="set-lb" id="mmCrEng">Engine</span>
            {sel && open.length > 1 ? <button type="button" className="link-q inl" aria-expanded={changing} aria-controls="mmCrEngs" onClick={() => setChanging(!changing)}>{changing ? 'Done' : 'Change'}</button> : null}
          </div>
          {failed ? (
            <p className="mm-err" role="alert">The engines could not be read just now. <button type="button" className="link-q inl" onClick={retry}>Try again</button></p>
          ) : !providers ? (
            <Skel label="Reading the engines"><SkLine w="40%" h={13} /><SkLine w="70%" h={11} style={{ marginTop: 8 }} /></Skel>
          ) : !sel ? (
            <p className="set-help mm-eng-none">No engine is connected yet. {onConnect ? <button type="button" className="link-q inl" onClick={onConnect}>Connect an engine</button> : null}</p>
          ) : (
            <>
              {changing ? null : (
                <div className="mm-eng-now" aria-labelledby="mmCrEng">
                  <span className="grow"><b>{vendorName(sel.id)}</b>{why ? <small>{why}</small> : null}</span>
                </div>
              )}
              {changing ? (
                <div className="mm-prov mm-eng-list" id="mmCrEngs" role="radiogroup" aria-labelledby="mmCrEng" onKeyDown={onKey}>
                  {open.map((p) => (
                    <button key={p.id} type="button" role="radio" aria-checked={sel.id === p.id} tabIndex={sel.id === p.id ? 0 : -1} data-sv={p.id}
                      className={`mm-pv-o${sel.id === p.id ? ' on' : ''}`} onClick={() => setChosen(p.id)}>
                      <i className="mm-sv-dot" aria-hidden="true" /><Says p={p} />
                    </button>
                  ))}
                </div>
              ) : null}
            </>
          )}
        </div>
        {err ? <p className="mm-err" role="alert">{err}</p> : null}
        <div className="sheet-actions mm-new-act">
          <span className="grow" />
          <button type="button" className="btn" disabled={busy} onClick={onClose}>Cancel</button>
          <button type="submit" className="btn primary" disabled={!sel || !name.trim() || busy}>{busy ? 'Creating…' : 'Create'}</button>
        </div>
      </form>
    </Sheet>
  );
}

/** Use in: give a memory to a setup. The setup then remembers there: it recalls from it, writes to it by default and
 *  keeps what matters from each finished task (PUT /v1/harnesses/{hid}/memory with the memory). A setup that uses it
 *  already says so and can't be picked again. */
export function UseInSheet({ m, onClose, onDone }: { m: Memory; onClose: () => void; onDone: (setup: string) => void }) {
  const [setups, setSetups] = useState<{ id: string; name: string }[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [q, setQ] = useState('');
  const [busy, setBusy] = useState('');
  const [err, setErr] = useState('');
  const read = () => {
    setFailed(false);
    listCustom().then((l) => setSetups(l.map((h) => ({ id: h.id, name: h.name })).sort((a, b) => a.name.localeCompare(b.name)))).catch(() => setFailed(true));
  };
  useEffect(read, []);
  const using = new Set((m.used_by || []).map((u) => u.harness_id));
  const needle = q.trim().toLowerCase();
  const shown = (setups || []).filter((x) => !needle || x.name.toLowerCase().includes(needle));
  const use = async (x: { id: string; name: string }) => {
    if (busy) return;
    setBusy(x.id); setErr('');
    try { await setAgentMemory(x.id, { id: m.id }); onDone(x.name); }
    catch (e) { setErr(plain(e, `${x.name} was not given ${m.name}. Try again.`)); setBusy(''); }
  };
  return (
    <Sheet onClose={onClose} labelledBy="mmUse" className="small-sheet mm-sheet mm-use" busy={!!busy}>
      <SheetTop id="mmUse" title={`Use ${m.name} in…`} sub="The setup remembers here from its next task: it recalls before it answers, and keeps what matters." onClose={onClose} />
      {failed ? (
        <p className="mm-err" role="alert">Your setups could not be read just now. <button type="button" className="link-q inl" onClick={read}>Try again</button></p>
      ) : !setups ? (
        <Skel label="Reading your setups">{[60, 44, 52].map((w, i) => <SkLine key={i} w={`${w}%`} h={13} style={{ margin: '12px 0' }} />)}</Skel>
      ) : !setups.length ? (
        <p className="set-help">No setups yet. Make one in Studio, and it can remember here.</p>
      ) : (
        <>
          {setups.length > 6 ? <input className="set-in slim mm-use-q" type="search" placeholder={`Search ${setups.length} setups`} aria-label="Search setups" autoComplete="off" value={q} onChange={(e) => setQ(e.target.value)} /> : null}
          <div className="mm-use-list" role="list">
            {shown.map((x) => (
              <div key={x.id} className="mm-use-row" role="listitem">
                <b title={x.name}>{x.name}</b>
                {using.has(x.id) ? <small>Remembers here</small>
                  : <button type="button" className="btn small" disabled={!!busy} onClick={() => void use(x)}>{busy === x.id ? 'Giving…' : 'Use here'}</button>}
              </div>
            ))}
            {!shown.length ? <p className="set-help" role="status">No setup matches that.</p> : null}
          </div>
        </>
      )}
      {err ? <p className="mm-err" role="alert">{err}</p> : null}
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
