'use client';
// The sheets of the Memories pages: New memory (a name and, if you like, a description: every engine listed, the one
// chosen for you from them picked and marked Recommended), Use in (give a memory to a setup, which then remembers there), Connect (an engine's
// address and a key, tried by the service at once), the list of engines to connect, and Rename. Each is the console's
// Sheet.
import { useEffect, useMemo, useRef, useState } from 'react';
import { listCustom, type CustomHarness } from '@/lib/harness';
import {
  agentMemoryOf, chooseEngine, connectProvider, createMemory, listProviderPlugs, setAgentMemory, updateMemory, type EngineChoice, type Memory, type Provider,
} from '@/lib/memories';
import { lastTaskBySetup } from '@/lib/workspace-feed';
import { ConfirmSheet, Sheet, SheetTop } from '../Sheet';
import { Skel, SkLine } from '../Skel';
import { plain } from '../setup/settingsModel';
import { serviceFacts, shapeOf } from './caps';
import { KindArt, type Kind } from './CardArt';
import { GUIDE, inVendorOrder, VENDORS, vendorName } from './vendors';

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
  // the instance's connection, used here with none of this workspace's own: its address and key are not this
  // workspace's to keep, so the form starts empty and connecting makes one of its own
  const [inherited, setInherited] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  // changing a connection starts from the address it has; a key is only ever said to be kept
  useEffect(() => {
    if (!connected) return;
    let live = true;
    listProviderPlugs().then((l) => {
      if (!live) return;
      const p = l.find((x) => x.type === id);
      if (p?.inherited) { setInherited(p.note || `This workspace uses this instance’s ${name} (inherited).`); return; }
      setBase(String(p?.config?.base_url || ''));
      setKeptKey(!!p?.secrets_set?.includes('api_key'));
    }).catch(() => {});
    return () => { live = false; };
  }, [connected, id, name]);
  const own = connected && !inherited;
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
      <SheetTop id="mmCn" title={own ? `Change ${name}` : inherited ? `Connect ${name} for this workspace` : `Connect ${name}`} sub={VENDORS[id]?.line} onClose={onClose} />
      <form noValidate onSubmit={(e) => { e.preventDefault(); void go(); }}>
        {inherited ? <p className="set-help mm-inherited" role="note">{inherited} Connect one here to use it in this workspace instead.</p> : null}
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
          <button type="submit" className="btn primary" disabled={!ready || busy}>{busy ? 'Connecting…' : own ? 'Save' : 'Connect'}</button>
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

/** How long typing rests before the service is asked which engine fits what was typed. */
const CHOOSE_AFTER_MS = 300;

/** The service's choice of engine for a new memory with this name and description (GET /v1/memories/choose): asked
 *  when the sheet opens and again once typing rests. undefined until it first answers; `failed` when it couldn't. */
function useEngineChoice(name: string, desc: string, on: boolean) {
  const [choice, setChoice] = useState<EngineChoice | undefined>(undefined);
  const [failed, setFailed] = useState(false);
  const [again, setAgain] = useState(0);
  const asked = useRef(0);
  const answered = useRef(false);
  useEffect(() => {
    if (!on) return undefined;
    const n = ++asked.current;
    const ask = () => chooseEngine(name, desc)
      .then((c) => { answered.current = true; if (asked.current === n) { setChoice(c); setFailed(false); } })
      .catch(() => { if (asked.current === n) setFailed(true); });
    // until it first answers each question goes at once, so the sheet opens with its engine; then typing rests first
    const t = setTimeout(() => void ask(), answered.current ? CHOOSE_AFTER_MS : 0);
    return () => clearTimeout(t);
  }, [name, desc, on, again]);
  return { choice, failed, retry: () => setAgain((x) => x + 1) };
}

/** New memory: a name and, if you like, a description, and under Engine every engine at once, one row each with what
 *  kind of memory it keeps. The one the service chooses from the name and description (GET /v1/memories/choose, the
 *  same reading an agent gets) is picked and marked Recommended, with why, and follows what is typed until the person
 *  picks one themselves. An engine not connected and answering here is shown, and can't be picked. Connecting another
 *  lives on the page, under More. */
export function NewMemorySheet({ providers, failed, retry, picked, onClose, onCreated, onConnect }: {
  providers: Provider[] | null; failed: boolean; retry: () => void; picked?: string;
  onClose: () => void; onCreated: (m: Memory, p: Provider) => void;
  /** where no engine is connected yet: the way to connect one */
  onConnect?: () => void;
}) {
  const [name, setName] = useState('');
  const [desc, setDesc] = useState('');
  const [chosen, setChosen] = useState(picked || '');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const all = useMemo(() => inVendorOrder(providers || []), [providers]);
  const open = useMemo(() => all.filter((p) => p.connected), [all]);
  const { choice: auto, failed: choiceFailed, retry: chooseAgain } = useEngineChoice(name, desc, open.length > 0);
  const recommended = open.find((p) => !!auto?.engine && p.id === auto.engine) || null;
  const sel = open.find((p) => p.id === chosen) || recommended;
  const go = async () => {
    if (!sel || !name.trim() || busy) return;
    setBusy(true); setErr('');
    try { onCreated(await createMemory({ name: name.trim(), description: desc.trim(), provider: sel.id }), sel); }
    catch (e) { setErr(plain(e, 'The memory was not created. Try again.')); setBusy(false); }
  };
  // arrows move the choice along the engines that can be picked, as in any group of radio buttons
  const onKey = (e: React.KeyboardEvent) => {
    const d = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1 : e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 0;
    if (!d || !open.length) return;
    e.preventDefault();
    const at = sel ? open.indexOf(sel) : -1;
    const next = open[(at + d + open.length) % open.length];
    setChosen(next.id);
    (e.currentTarget.querySelector(`[data-sv="${next.id}"]`) as HTMLElement | null)?.focus();
  };
  return (
    <Sheet onClose={onClose} labelledBy="mmCrT" className="mm-sheet mm-nd-sheet mm-new-mem" busy={busy}>
      <SheetTop id="mmCrT" title="New memory" onClose={onClose} />
      <form className="mm-new-f" noValidate onSubmit={(e) => { e.preventDefault(); void go(); }}>
        <NameFields nameId="mmCrName" descId="mmCrDesc" name={name} desc={desc} onName={setName} onDesc={setDesc} focus optional />
        <div className="set-f mm-eng">
          <span className="set-lb" id="mmCrEng">Engine</span>
          {failed ? (
            <p className="mm-err" role="alert">The engines could not be read just now. <button type="button" className="link-q inl" onClick={retry}>Try again</button></p>
          ) : !providers ? (
            <Skel label="Reading the engines">{[0, 1, 2, 3].map((i) => <SkLine key={i} w="100%" h={52} r={12} style={{ marginTop: i ? 6 : 0 }} />)}</Skel>
          ) : !all.length ? (
            <p className="set-help mm-eng-none">No engine is connected yet. {onConnect ? <button type="button" className="link-q inl" onClick={onConnect}>Connect an engine</button> : null}</p>
          ) : (
            <>
              <div className="mm-engs" role="radiogroup" aria-labelledby="mmCrEng" onKeyDown={onKey}>
                {all.map((p) => {
                  const can = !!p.connected, on = sel?.id === p.id, rec = recommended?.id === p.id;
                  const line = VENDORS[p.id]?.line || '';
                  return (
                    <button key={p.id} type="button" role="radio" aria-checked={on} disabled={!can} data-sv={p.id}
                      tabIndex={can && (sel ? on : p === open[0]) ? 0 : -1}
                      className={`mm-eng-o${on ? ' on' : ''}${can ? '' : ' off'}`} onClick={() => setChosen(p.id)}>
                      <i className="mm-eng-dot" aria-hidden="true" />
                      <span className="mm-eng-t">
                        <span className="mm-eng-n"><b>{vendorName(p.id)}</b>
                          {rec ? <span className="pill run mm-eng-rec">Recommended</span> : null}
                          {can ? null : <span className="mm-eng-nr">Not running here</span>}
                        </span>
                        {line ? <small>{line}</small> : null}
                        {rec && auto?.reason ? <small className="mm-eng-why">{auto.reason}</small> : null}
                      </span>
                    </button>
                  );
                })}
              </div>
              {choiceFailed ? (
                <p className="mm-err" role="alert">The engine couldn’t be chosen just now. <button type="button" className="link-q inl" onClick={chooseAgain}>Try again</button></p>
              ) : auto && !auto.engine && auto.reason ? (
                // nothing answering here to recommend: the service says why, and the connected ones can still be picked
                <p className="set-help mm-eng-none" role="status">{auto.reason}</p>
              ) : null}
              {!open.length && onConnect ? <p className="set-help mm-eng-none">No engine is connected yet. <button type="button" className="link-q inl" onClick={onConnect}>Connect an engine</button></p> : null}
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

/** A setup as Use in lists it: when it last ran a task (seconds, 0 for none among the newest), when it was made, and
 *  the memory it has now, as its record says. */
export interface SetupPick { id: string; name: string; last: number; created: number; has: SetupMemoryNow }
/** What memory a setup has now: the one it remembers in (`own`), none (`none`, with the service's why), some it was
 *  given before memory came with every setup (`count`), or nothing said (a service before 0.40). */
export type SetupMemoryNow = { k: 'own'; id: string; name: string } | { k: 'none' } | { k: 'count'; n: number } | { k: 'unsaid' };
export function setupMemoryNow(h: CustomHarness): SetupMemoryNow {
  const r = agentMemoryOf(h);
  if (r?.memory?.id) return { k: 'own', id: r.memory.id, name: r.memory.name };
  if (r) return { k: 'none' };
  const n = h.memories?.count || 0;
  return n ? { k: 'count', n } : { k: 'unsaid' };
}
/** The order Use in lists setups in: the ones that ran a task most lately first, then the newest made, then by name. */
export const byRecent = (a: SetupPick, b: SetupPick) => b.last - a.last || b.created - a.created || a.name.localeCompare(b.name);
/** The memory a setup remembers in, as Use in names it: by its name, or "its own memory" where it is named after the
 *  setup (the one made for it) or has no name. */
const ownName = (has: SetupMemoryNow, setup: string) => (has.k === 'own' && has.name && has.name !== setup ? has.name : 'its own memory');
/** A setup's line under its name in Use in. */
export function memoryNowLine(has: SetupMemoryNow, here: string, setup = ''): string {
  if (has.k === 'own') return has.id === here ? 'Remembers here' : `Remembers in ${ownName(has, setup)}`;
  if (has.k === 'none') return 'No memory';
  if (has.k === 'count') return `Uses ${has.n} ${has.n === 1 ? 'memory' : 'memories'}`;
  return '';
}
/** What Use in asks before it replaces the memory a setup has now with `next`. */
export function replaceAsk(x: Pick<SetupPick, 'name' | 'has'>, next: string): { title: string; body: string } {
  const then = `From its next task it remembers in ${next} instead.`;
  if (x.has.k === 'count') {
    const one = x.has.n === 1;
    return { title: `Replace its memory in ${x.name}?`, body: `${x.name} uses ${x.has.n} ${one ? 'memory' : 'memories'} now. ${then} ${one ? 'It is kept, with everything in it.' : 'They are kept, with everything in them.'}` };
  }
  const now = ownName(x.has, x.name);
  const kept = now === 'its own memory' ? 'Its own memory' : now;
  return { title: `Replace ${now} in ${x.name}?`, body: `${x.name} remembers in ${now} now. ${then} ${kept} is kept, with everything in it.` };
}

/** Use in: give a memory to a setup. The setup then remembers there: it recalls from it, writes to it by default and
 *  keeps what matters from each finished task (PUT /v1/harnesses/{hid}/memory with the memory). The setups come the
 *  ones in use first, each saying the memory it has now; one that has another memory asks before it is replaced, and
 *  one that uses this memory already says so and can't be picked again. */
export function UseInSheet({ m, onClose, onDone }: { m: Memory; onClose: () => void; onDone: (setup: string) => void }) {
  const [setups, setSetups] = useState<SetupPick[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [q, setQ] = useState('');
  const [busy, setBusy] = useState('');
  const [err, setErr] = useState('');
  const [asking, setAsking] = useState<SetupPick | null>(null);
  const read = () => {
    setFailed(false);
    // the order is the workspace's newest tasks; without them, the newest made first (never a failed read)
    Promise.all([listCustom(), lastTaskBySetup().catch(() => new Map<string, number>())])
      .then(([l, last]) => setSetups(l.map((h) => ({ id: h.id, name: h.name, last: last.get(h.id) || 0, created: h.createdAt || 0, has: setupMemoryNow(h) })).sort(byRecent)))
      .catch(() => setFailed(true));
  };
  useEffect(read, []);
  const using = new Set((m.used_by || []).map((u) => u.harness_id));
  const here = (x: SetupPick) => using.has(x.id) || (x.has.k === 'own' && x.has.id === m.id);
  const needle = q.trim().toLowerCase();
  const shown = (setups || []).filter((x) => !needle || x.name.toLowerCase().includes(needle) || memoryNowLine(x.has, m.id, x.name).toLowerCase().includes(needle));
  const use = async (x: SetupPick) => {
    if (busy) return;
    setBusy(x.id); setErr('');
    try { await setAgentMemory(x.id, { id: m.id }); onDone(x.name); }
    catch (e) { setErr(plain(e, `${x.name} was not given ${m.name}. Try again.`)); setBusy(''); setAsking(null); }
  };
  const pick = (x: SetupPick) => { if (x.has.k === 'own' || x.has.k === 'count') setAsking(x); else void use(x); };
  if (asking) {
    const ask = replaceAsk(asking, m.name);
    return (
      <ConfirmSheet id="mmUseR" title={ask.title} confirmLabel="Replace" busy={!!busy} body={ask.body}
        onClose={() => { if (!busy) { setAsking(null); setErr(''); } }} onConfirm={() => void use(asking)} />
    );
  }
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
          <div className="mm-use-list" role="list" aria-label="Setups, the ones in use first">
            {shown.map((x) => {
              const line = memoryNowLine(x.has, m.id, x.name);
              return (
                <div key={x.id} className="mm-use-row" role="listitem">
                  <span className="mm-use-n"><b title={x.name}>{x.name}</b>{line && !here(x) ? <small>{line}</small> : null}</span>
                  {here(x) ? <small className="mm-use-here">Remembers here</small>
                    : <button type="button" className="btn small" disabled={!!busy} onClick={() => pick(x)}>{busy === x.id ? 'Giving…' : 'Use here'}</button>}
                </div>
              );
            })}
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
