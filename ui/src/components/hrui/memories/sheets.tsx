'use client';
// The sheets of the Memories pages: New memory (a name and, if you like, a description: every engine listed, the one
// chosen for you from them picked and marked Recommended), Connect (an engine's address and a key, tried by the service
// at once), the list of engines to connect, and Rename. Each is the console's Sheet. A memory is given to an agent from
// its own Settings, never from a sheet here (Richard 11-09: "Used in is sloppy, put it in a Setting tab").
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  chooseEngine, connectProvider, createMemory, listProviderPlugs, updateMemory, type EngineChoice, type Memory, type Provider,
} from '@/lib/memories';
import { Sheet, SheetTop } from '../Sheet';
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
      <SheetTop id="mmCn" title={own ? `修改${name}` : inherited ? `为当前工作区连接${name}` : `连接${name}`} sub={VENDORS[id]?.line} onClose={onClose} />
      <form noValidate onSubmit={(e) => { e.preventDefault(); void go(); }}>
        {inherited ? <p className="set-help mm-inherited" role="note">{inherited} 可在此处单独连接，以便当前工作区使用。</p> : null}
        <div className="set-f">
          <label htmlFor="mmCnBase">服务地址</label>
          <input id="mmCnBase" className="set-in" type="url" inputMode="url" value={base} autoComplete="off" placeholder="https://memory.example.com" onChange={(e) => setBase(e.target.value)} />
          <p className="set-help">
            {addressOptional ? `留空表示使用${name}云端服务，此时需要填写密钥。` : null}
            <a className="link-q inl" href={GUIDE} target="_blank" rel="noopener noreferrer">如何运行服务</a>
          </p>
        </div>
        <div className="set-f">
          <label htmlFor="mmCnKey">{needsKey ? '密钥' : '密钥（可选）'}</label>
          <input id="mmCnKey" className="set-in" type="password" value={key} autoComplete="off" placeholder={keptKey ? '保留已保存的密钥' : undefined} onChange={(e) => setKey(e.target.value)} />
          <p className="set-help">密钥会安全保存，之后不会再次显示。</p>
        </div>
        {err ? <p className="mm-err" role="alert">{err}</p> : null}
        <div className="sheet-actions">
          <span className="grow" />
          <button type="button" className="btn" disabled={busy} onClick={onClose}>取消</button>
          <button type="submit" className="btn primary" disabled={!ready || busy}>{busy ? '连接中…' : own ? '保存' : '连接'}</button>
        </div>
      </form>
    </Sheet>
  );
}

/** A memory's name and description, the same in every window that makes or renames one: the name, then the
 *  description, each on its own row (Richard 11-09), and under the description what it is for, which stays when the
 *  field is filled. */
export function NameFields({ nameId, descId, name, desc, onName, onDesc, focus, optional }: {
  nameId: string; descId: string; name: string; desc: string; onName: (v: string) => void; onDesc: (v: string) => void; focus?: boolean;
  /** the description may be left out (New memory says so) */
  optional?: boolean;
}) {
  return (
    <div className="mm-nf">
      <div className="set-f">
        <label htmlFor={nameId}>名称</label>
        <input id={nameId} className="set-in" value={name} placeholder="Brand kits" autoComplete="off" autoFocus={focus} onChange={(e) => onName(e.target.value)} />
      </div>
      <div className="set-f">
        <label htmlFor={descId}>{optional ? <>描述 <span className="mm-opt">可选</span></> : '描述'}</label>
        <textarea id={descId} className="set-in" rows={2} value={desc} placeholder="What is kept here, in a sentence." aria-describedby={`${descId}H`} onChange={(e) => onDesc(e.target.value)} />
      </div>
      <p className="set-help mm-nf-h" id={`${descId}H`}>Agent 会根据描述判断是否需要读取这里的内容。</p>
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
      <SheetTop id="mmCh" title="连接记忆引擎" sub="Agent 将学习到的内容保存在引擎中，每种引擎的保存方式不同。" onClose={onClose} />
      <div className="mm-prov mm-sv mm-sv-cn">
        {providers.map((p) => (
          <div key={p.id} className="mm-pv-o cn">
            <ServiceBody p={p} />
            <button type="button" className="btn small" onClick={() => setPicked({ id: p.id, connected: !!p.connected })}>{p.connected ? '修改' : '连接'}</button>
          </div>
        ))}
      </div>
      <p className="set-help mm-sv-guide">每个引擎都作为独立服务运行。<a className="link-q inl" href={GUIDE} target="_blank" rel="noopener noreferrer">如何运行引擎</a></p>
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
  /** connecting an engine: the one named (from its "Not running here" row), or a choice of them */
  onConnect?: (id?: string) => void;
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
      <SheetTop id="mmCrT" title="新建记忆" onClose={onClose} />
      <form className="mm-new-f" noValidate onSubmit={(e) => { e.preventDefault(); void go(); }}>
        <NameFields nameId="mmCrName" descId="mmCrDesc" name={name} desc={desc} onName={setName} onDesc={setDesc} focus optional />
        <div className="set-f mm-eng">
          <span className="set-lb" id="mmCrEng">引擎</span>
          {failed ? (
            <p className="mm-err" role="alert">暂时无法读取引擎。<button type="button" className="link-q inl" onClick={retry}>重试</button></p>
          ) : !providers ? (
            <Skel label="正在读取引擎">{[0, 1, 2, 3].map((i) => <SkLine key={i} w="100%" h={52} r={12} style={{ marginTop: i ? 6 : 0 }} />)}</Skel>
          ) : !all.length ? (
            <p className="set-help mm-eng-none">还没有连接引擎。{onConnect ? <button type="button" className="link-q inl" onClick={() => onConnect()}>连接引擎</button> : null}</p>
          ) : (
            <>
              <div className="mm-engs" role="radiogroup" aria-labelledby="mmCrEng" onKeyDown={onKey}>
                {all.map((p) => {
                  const can = !!p.connected, on = sel?.id === p.id, rec = recommended?.id === p.id;
                  const line = VENDORS[p.id]?.line || '';
                  if (!can) {
                    // not running here: shown, and connected from its own row
                    return (
                      <div key={p.id} role="radio" aria-checked={false} aria-disabled="true" data-sv={p.id} className="mm-eng-o off">
                        <i className="mm-eng-dot" aria-hidden="true" />
                        <span className="mm-eng-t">
                          <span className="mm-eng-n"><b>{vendorName(p.id)}</b><span className="mm-eng-nr">Not running here</span></span>
                          {line ? <small>{line}</small> : null}
                        </span>
                        {onConnect ? <button type="button" className="link-q inl mm-eng-cn" onClick={() => onConnect(p.id)}>连接</button> : null}
                      </div>
                    );
                  }
                  return (
                    <button key={p.id} type="button" role="radio" aria-checked={on} disabled={!can} data-sv={p.id}
                      tabIndex={can && (sel ? on : p === open[0]) ? 0 : -1}
                      className={`mm-eng-o${on ? ' on' : ''}${can ? '' : ' off'}`} onClick={() => setChosen(p.id)}>
                      <i className="mm-eng-dot" aria-hidden="true" />
                      <span className="mm-eng-t">
                        <span className="mm-eng-n"><b>{vendorName(p.id)}</b>
                          {rec ? <span className="pill run mm-eng-rec">推荐</span> : null}
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
                <p className="mm-err" role="alert">暂时无法选择引擎。<button type="button" className="link-q inl" onClick={chooseAgain}>重试</button></p>
              ) : auto && !auto.engine && auto.reason ? (
                // nothing answering here to recommend: the service says why, and the connected ones can still be picked
                <p className="set-help mm-eng-none" role="status">{auto.reason}</p>
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
