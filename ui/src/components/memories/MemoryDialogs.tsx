'use client';
// Memories: the three dialogs of the page. New memory (a name, the description agents read, and
// for a memory at the top the engine that keeps it, with that engine's key entered right there
// when the workspace has none); Share (which harnesses may use a memory and as what, what
// reaches it from the memories above, and the switch that stops that); and Delete, which first
// counts everything that would go so the confirmation can name it.
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  connectEngine, createMemory, deleteMemory, grant, listChildren, listEngines, listGrants, revokeGrant, roleOf, updateMemory,
  MemoryApiError, ROLE_PRIVILEGES, type EnginePlug, type Grant, type Memory, type Role,
} from '@/lib/memories';
import { SkelLine } from '@/components/Skel';
import { ConfirmDialog, engineName, errText } from './kit';

const ROLES: Role[] = ['Viewer', 'Editor', 'Manager'];
function useEscape(onClose: () => void, busy: boolean) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape' && !busy) onClose(); };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, [onClose, busy]);
}

// ── new memory ──────────────────────────────────────────────────────────────────────────────
/** The engines the dialog names. One can be chosen today; the rest are said to be coming. */
const ENGINES: { id: string; name: string; blurb: string; soon?: boolean }[] = [
  { id: 'mem0', name: 'Mem0', blurb: 'Picks facts out of conversations. Search by meaning or by exact words.' },
  { id: 'contextualgraph', name: 'ContextualGraph', blurb: 'Coming later.', soon: true },
  { id: 'zep', name: 'Zep', blurb: 'Coming later.', soon: true },
  { id: 'letta', name: 'Letta', blurb: 'Coming later.', soon: true },
  { id: 'cognee', name: 'Cognee', blurb: 'Coming later.', soon: true },
];

export function CreateDialog({ parent, onClose, onCreated }: { parent: Memory | null; onClose: () => void; onCreated: (m: Memory) => void }) {
  const [name, setName] = useState('');
  const [desc, setDesc] = useState('');
  const [engines, setEngines] = useState<EnginePlug[] | null>(null);
  const [enginesErr, setEnginesErr] = useState('');
  const [key, setKey] = useState('');
  const [keyBusy, setKeyBusy] = useState(false);
  const [keyErr, setKeyErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<{ message: string; param?: string } | null>(null);
  useEscape(onClose, busy || keyBusy);

  useEffect(() => {
    if (parent) return;
    let alive = true;
    listEngines().then((e) => { if (alive) setEngines(e); }).catch((e) => { if (alive) { setEngines([]); setEnginesErr(errText(e)); } });
    return () => { alive = false; };
  }, [parent]);

  const connected = engines?.find((e) => e.type === 'mem0')?.status === 'connected';
  const needsKey = !parent && engines !== null && !connected;
  const ready = Boolean(name.trim()) && (parent ? true : connected) && !busy;

  const connect = async () => {
    const k = key.trim();
    if (!k || keyBusy) return;
    setKeyBusy(true); setKeyErr('');
    // the key is tried at the service at once; a refused key fails here with the service's reason
    try { const plug = await connectEngine('mem0', k); setEngines((es) => [...(es || []).filter((e) => e.type !== 'mem0'), plug]); setKey(''); }
    catch (e) { setKeyErr(errText(e)); }
    finally { setKeyBusy(false); }
  };
  const create = async () => {
    if (!ready) return;
    setBusy(true); setErr(null);
    try {
      onCreated(await createMemory({ name: name.trim(), description: desc.trim(), ...(parent ? { parent_id: parent.id } : { provider: 'mem0' }) }));
    } catch (e) { setErr({ message: errText(e), param: e instanceof MemoryApiError ? e.param : undefined }); setBusy(false); }
  };

  return (
    <div className="modal-backdrop" onClick={() => busy || keyBusy || onClose()}>
      <section className="modal mem-dlg mem-dlg-form" role="dialog" aria-modal="true" aria-labelledby="mem-create-title" onClick={(e) => e.stopPropagation()}>
        <div className="mem-dlg-head is-ruled">
          <h2 id="mem-create-title">{parent ? `New memory in ${parent.name}` : 'New memory'}</h2>
          <button type="button" className="mem-xbtn" aria-label="Close" onClick={onClose}>✕</button>
        </div>
        <form className="mem-dlg-body" onSubmit={(e) => { e.preventDefault(); void create(); }}>
          <label className="mem-field">
            <span>Name</span>
            <input autoFocus value={name} placeholder="Sales" onChange={(e) => setName(e.target.value)} aria-invalid={err?.param === 'name'} />
            {err?.param === 'name' && <em className="mem-field-err" role="alert">{err.message}</em>}
          </label>
          <label className="mem-field">
            <span>Description</span>
            <textarea rows={2} value={desc} placeholder="What the sales team knows: accounts and pricing decisions." onChange={(e) => setDesc(e.target.value)} aria-invalid={err?.param === 'description'} />
            {err?.param === 'description' && <em className="mem-field-err" role="alert">{err.message}</em>}
            <small>Agents read this to decide whether to look inside.</small>
          </label>
          <div className="mem-field">
            <span>Engine</span>
            {parent ? (
              <p className="mem-engine-locked">{`Uses ${engineName(parent.provider)}, like ${parent.name}. A memory always uses its parent’s engine.`}</p>
            ) : (
              <>
                <div className="mem-engines" role="radiogroup" aria-label="Engine">
                  {ENGINES.map((e) => {
                    const on = !e.soon;
                    const state = e.soon ? 'Soon' : engines === null ? '' : connected ? 'Your key' : 'Needs a key';
                    return (
                      <div key={e.id}>
                        <button type="button" role="radio" aria-checked={on} disabled={e.soon} className={'mem-engine' + (on ? ' is-on' : '') + (e.soon ? ' is-soon' : '')}>
                          <i className="mem-radio" />
                          <span className="mem-engine-id"><b>{e.name}</b><span>{e.blurb}</span></span>
                          <span className={'mem-engine-state' + (e.soon ? ' is-soon' : connected ? ' is-ok' : '')}>{state || (e.soon ? '' : <SkelLine w={48} h={9} />)}</span>
                        </button>
                        {on && needsKey && (
                          <div className="mem-engine-key">
                            <div>
                              <input type="password" autoComplete="off" spellCheck={false} value={key} aria-label="Mem0 API key" placeholder="Mem0 API key"
                                onChange={(ev) => { setKey(ev.target.value); setKeyErr(''); }}
                                onKeyDown={(ev) => { if (ev.key === 'Enter') { ev.preventDefault(); void connect(); } }} />
                              <button type="button" className="mem-btn" disabled={keyBusy || !key.trim()} onClick={() => void connect()}>{keyBusy ? 'Checking…' : 'Connect'}</button>
                            </div>
                            {keyErr && <p className="mem-field-err" role="alert">{keyErr}</p>}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
                <p className="mem-engine-note">{enginesErr || 'Mem0 uses your own key, so Mem0 bills you.'}</p>
              </>
            )}
          </div>
          {err && err.param !== 'name' && err.param !== 'description' && <div className="mem-field-err" role="alert">{err.message}</div>}
          <button type="submit" hidden />
        </form>
        <div className="mem-dlg-foot">
          {needsKey && <span className="mem-dlg-why">Connect Mem0 first.</span>}
          <button type="button" className="mem-btn" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="button" className="mem-btn is-primary" disabled={!ready} onClick={() => void create()}>{busy ? 'Creating…' : 'Create'}</button>
        </div>
      </section>
    </div>
  );
}

// ── share ───────────────────────────────────────────────────────────────────────────────────
export function ShareDialog({ memory, parentName, harnesses, memoryName, onClose, onGoMemory, onMemory }: {
  memory: Memory; parentName: string | null; harnesses: { id: string; name: string }[]; memoryName: (id: string) => string | undefined;
  onClose: () => void; onGoMemory: (id: string) => void; onMemory: (m: Memory) => void;
}) {
  const [grants, setGrants] = useState<Grant[] | null>(null);
  const [err, setErr] = useState('');
  const [invite, setInvite] = useState('');
  const [role, setRole] = useState<Role>('Viewer');
  const [picker, setPicker] = useState(false);
  const [busy, setBusy] = useState(false);
  const [pendingLimit, setPendingLimit] = useState(false);
  const pickerBox = useRef<HTMLDivElement>(null);
  useEscape(onClose, busy);

  const load = useCallback(() => listGrants(memory.id).then(setGrants).catch((e) => { setGrants([]); setErr(errText(e)); }), [memory.id]);
  useEffect(() => { void load(); }, [load]);

  // in this edition a memory is shared with harnesses: a harness's agent is the member of that id
  const harnessOf = (g: Grant) => harnesses.find((h) => g.principal === `member:${h.id}`);
  const rows = (grants || []).map((g) => ({ g, h: harnessOf(g) })).filter((x): x is { g: Grant; h: { id: string; name: string } } => Boolean(x.h))
    .sort((a, b) => Number(a.g.inherited) - Number(b.g.inherited) || a.g.memory_id.localeCompare(b.g.memory_id));
  const direct = rows.filter((x) => !x.g.inherited), inherited = rows.filter((x) => x.g.inherited);
  const candidates = harnesses.filter((h) => !direct.some((x) => x.h.id === h.id) && (!invite.trim() || h.name.toLowerCase().includes(invite.trim().toLowerCase())));

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true); setErr('');
    try { await fn(); await load(); } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  };
  const limit = (on: boolean) => run(async () => { onMemory(await updateMemory(memory.id, { restricted: on })); setPendingLimit(false); });

  return (
    <div className="modal-backdrop" onClick={() => busy || onClose()}>
      <section className="modal mem-dlg mem-dlg-form" role="dialog" aria-modal="true" aria-labelledby="mem-share-title" onClick={(e) => { e.stopPropagation(); if (picker && !pickerBox.current?.contains(e.target as Node)) setPicker(false); }}>
        <div className="mem-dlg-head">
          <h2 id="mem-share-title" className="mem-ell">Share {memory.name}</h2>
          <button type="button" className="mem-xbtn" aria-label="Close" onClick={onClose}>✕</button>
        </div>
        <div className="mem-dlg-body is-share">
          <div className="mem-invite" ref={pickerBox}>
            <input value={invite} aria-label="Add a harness" placeholder="Add a harness" role="combobox" aria-expanded={picker} aria-controls="mem-share-picker"
              onChange={(e) => { setInvite(e.target.value); setPicker(true); }} onFocus={() => setPicker(true)} />
            <select value={role} aria-label="Role" onChange={(e) => setRole(e.target.value as Role)}>{ROLES.map((r) => <option key={r} value={r}>{r}</option>)}</select>
            {picker && (
              <div className="mem-menu mem-picker" id="mem-share-picker" role="listbox">
                {candidates.map((h) => (
                  <button key={h.id} type="button" role="option" aria-selected={false} disabled={busy}
                    onClick={() => { setPicker(false); setInvite(''); void run(() => grant(memory.id, `member:${h.id}`, ROLE_PRIVILEGES[role])); }}>
                    <span className="mem-av">{h.name.charAt(0).toUpperCase()}</span><span className="mem-ell">{h.name}</span>
                  </button>
                ))}
                {candidates.length === 0 && <p>{harnesses.length === 0 ? 'This workspace has no harnesses yet.' : invite.trim() ? 'No harness matches that.' : 'Every harness already has access.'}</p>}
              </div>
            )}
          </div>

          <div className="mem-share-title">Harnesses with access</div>
          <div className="mem-grants">
            {grants === null && <div className="mem-grant" aria-busy="true"><SkelLine w={28} h={28} /><SkelLine w={160} h={12} /></div>}
            {grants !== null && rows.length === 0 && <div className="mem-grant is-none">No harness has been given this memory yet.</div>}
            {rows.map(({ g, h }) => {
              const from = g.inherited ? memoryName(g.memory_id) : null;
              return (
                <div key={g.id + (g.inherited ? ':i' : '')} className="mem-grant">
                  <span className="mem-av">{h.name.charAt(0).toUpperCase()}</span>
                  <span className="mem-grant-id">
                    <span className="mem-ell">{h.name}</span>
                    {g.inherited && <button type="button" onClick={() => onGoMemory(g.memory_id)}>{`From ${from || 'a memory above'}, change it there`}</button>}
                  </span>
                  {g.inherited ? <span className="mem-grant-role">{roleOf(g.privileges) || '—'}</span> : (
                    <>
                      <select value={roleOf(g.privileges) || 'Viewer'} aria-label={`Role for ${h.name}`} disabled={busy}
                        onChange={(e) => void run(() => grant(memory.id, g.principal, ROLE_PRIVILEGES[e.target.value as Role]))}>
                        {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                      </select>
                      <button type="button" className="mem-grant-x" aria-label={`Remove ${h.name}`} title="Remove access" disabled={busy} onClick={() => void run(() => revokeGrant(memory.id, g.id))}>✕</button>
                    </>
                  )}
                </div>
              );
            })}
          </div>

          {memory.parent_id && (
            <div className="mem-limit">
              <div className="mem-limit-row">
                <span id="mem-limit-label"><b>Limit access</b>
                  <span>{memory.restricted ? 'Only the harnesses listed above.' : `Any harness with access to ${parentName || 'the memory above'} can use it.`}</span></span>
                <button type="button" role="switch" aria-checked={memory.restricted} aria-labelledby="mem-limit-label" className={'mem-switch' + (memory.restricted ? ' is-on' : '')} disabled={busy}
                  onClick={() => { if (memory.restricted) void limit(false); else if (inherited.length) setPendingLimit(true); else void limit(true); }}><i /></button>
              </div>
              {pendingLimit && (
                <div className="mem-limit-warn" role="alert">
                  <span>{`${[...new Set(inherited.map((x) => x.h.name))].join(', ')} will lose access to this memory.`}</span>
                  <span><button type="button" className="mem-textbtn" onClick={() => setPendingLimit(false)}>Cancel</button>
                    <button type="button" className="mem-btn is-sm" disabled={busy} onClick={() => void limit(true)}>Limit access</button></span>
                </div>
              )}
            </div>
          )}
          {err && <div className="mem-field-err" role="alert">{err}</div>}
        </div>
        <div className="mem-dlg-foot is-plain">
          <button type="button" className="mem-btn is-primary" onClick={onClose}>Done</button>
        </div>
      </section>
    </div>
  );
}

// ── delete ──────────────────────────────────────────────────────────────────────────────────
export function DeleteDialog({ memory, onClose, onDeleted }: { memory: Memory; onClose: () => void; onDeleted: (ids: string[]) => void }) {
  const [all, setAll] = useState<Memory[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  // everything below it goes too, so it is counted before the question is asked
  useEffect(() => {
    let alive = true;
    (async () => {
      const out: Memory[] = [memory];
      for (let i = 0; i < out.length; i++) if ((out[i].children?.count ?? 1) > 0) out.push(...await listChildren(out[i].id));
      if (alive) setAll(out);
    })().catch((e) => { if (alive) { setAll([memory]); setErr(errText(e)); } });
    return () => { alive = false; };
  }, [memory]);

  const n = all?.length ?? 0;
  const counted = all?.every((m) => typeof m.records?.count === 'number');
  const records = all?.reduce((s, m) => s + (m.records?.count ?? 0), 0) ?? 0;
  const noun = n === 1 ? 'memory' : 'memories';
  return (
    <ConfirmDialog title={`Delete ${memory.name}?`} busy={busy} wait={!all} error={err}
      label={!all ? 'Counting…' : busy ? 'Deleting…' : `Delete ${n} ${noun}`}
      body={!all ? <SkelLine w="80%" h={12} /> : counted
        ? `This deletes ${n} ${noun} and their ${records} ${records === 1 ? 'record' : 'records'}. Agents that were given them lose them.`
        : `This deletes ${n} ${noun} and everything kept in them. Agents that were given them lose them.`}
      list={all && n > 1 ? all.map((m) => m.name).join(', ') : null}
      onCancel={onClose}
      onConfirm={() => {
        setBusy(true); setErr('');
        deleteMemory(memory.id).then((d) => onDeleted(d.memories || [memory.id])).catch((e) => { setErr(errText(e)); setBusy(false); });
      }} />
  );
}
