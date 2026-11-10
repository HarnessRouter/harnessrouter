'use client';
// A memory's Settings tab (Richard 11-09): its name and description, edited in place; its ID; the agent harnesses, each
// with a switch; and Delete, last. The list is an agent's own Settings, Memory, seen from the memory, row for row (the
// same row, MemoryLayer's): a switch here sends exactly what the switch for this memory sends there (turnOn, turnOff),
// so the two always agree. A harness this memory reaches through a memory above it says so and has no switch here.
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { listCustom, type CustomHarness } from '@/lib/harness';
import {
  agentMemoryOf, deleteMemory, getHarnessMemories, getMemory, grant, listGrants, revokeGrant, setHarnessMemories, updateMemory,
  type Grant, type Memory,
} from '@/lib/memories';
import { partIcon } from '../bricks';
import { Markup } from '../Markup';
import { ConfirmSheet } from '../Sheet';
import { Skel, SkLine } from '../Skel';
import { plain } from '../setup/settingsModel';
import { toast } from '../toast';
import { COPY } from './parts';
import { NameFields } from './sheets';

/** Open, as everywhere a row leads somewhere else: a quiet arrow at the end of the row. */
const OPEN_IC = <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M7 17 17 7M9 7h8v8" /></svg>;
const who = (hid: string) => `member:${hid}`;
/** Past this many, a search is worth its row (as in an agent's own Settings, Memory). */
const FIND_FROM = 4;

export function MemorySettings({ memory, onSaved, onDeleted }: { memory: Memory; onSaved: (m: Memory) => void; onDeleted: () => void }) {
  const router = useRouter();
  const write = !!memory.privileges?.includes('write'), del = !!memory.privileges?.includes('delete');

  // ── name and description, saved as they're left ───────────────────────────────────────────
  const [name, setName] = useState(memory.name);
  const [desc, setDesc] = useState(memory.description || '');
  const [said, setSaid] = useState('');
  useEffect(() => { setName(memory.name); setDesc(memory.description || ''); }, [memory.name, memory.description]);
  const save = async () => {
    const n = name.trim(), d = desc.trim();
    if (!n || (n === memory.name && d === (memory.description || ''))) { if (!n) setName(memory.name); return; }
    setSaid('');
    try { onSaved(await updateMemory(memory.id, { name: n, description: d })); setSaid('Saved'); }
    catch (e) { setSaid(plain(e, 'That was not saved. Try again.')); }
  };

  // ── the agent harnesses ───────────────────────────────────────────────────────────────────
  const [setups, setSetups] = useState<CustomHarness[] | null>(null);
  const [grants, setGrants] = useState<Grant[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [q, setQ] = useState('');
  // the names of the memories above this one whose grant reaches it ("Comes with …")
  const [above, setAbove] = useState<Record<string, string>>({});
  // who was on when the list was first read: those rows lead, and the order holds for the visit, so a row never moves
  // under the switch just pressed
  const first = useRef<Set<string> | null>(null);
  const read = useCallback(async () => {
    setFailed(false);
    try {
      const [l, g] = await Promise.all([listCustom(), listGrants(memory.id)]);
      if (!first.current) first.current = new Set(g.filter((x) => x.privileges.length).map((x) => x.principal));
      setSetups(l); setGrants(g);
    } catch { setFailed(true); }
  }, [memory.id]);
  useEffect(() => { void read(); }, [read]);
  const held = useMemo(() => new Map((grants || []).filter((g) => g.privileges.length).map((g) => [g.principal, g])), [grants]);
  const asked = useRef(new Set<string>());
  useEffect(() => {
    (grants || []).filter((g) => g.memory_id !== memory.id && !asked.current.has(g.memory_id)).forEach((g) => {
      asked.current.add(g.memory_id);
      getMemory(g.memory_id).then((u) => setAbove((n) => ({ ...n, [g.memory_id]: u.name }))).catch(() => undefined);
    });
  }, [grants, memory.id]);
  const rows = useMemo(() => {
    const wasOn = first.current || new Set<string>();
    return [...(setups || [])].sort((a, b) => Number(wasOn.has(who(b.id))) - Number(wasOn.has(who(a.id))) || a.name.localeCompare(b.name) || a.id.localeCompare(b.id));
  }, [setups]);

  // MemoryLayer's run, turnOn, turnOff and handOn, for one agent at a time: read what the agent holds, then the same calls
  const run = async (fn: () => Promise<unknown>, fallback: string) => {
    if (busy) return;
    setBusy(true);
    try { await fn(); } catch (e) { toast(plain(e, fallback)); } finally { await read(); setBusy(false); }
  };
  const turnOn = (h: CustomHarness) => run(async () => {
    const d = await getHarnessMemories(h.id);
    await grant(memory.id, d.principal, ['read', 'write']);
    // its own memory back on: the default again, keeping finished tasks, as the service set it when it gave it.
    // Any other memory switched on for an agent with nowhere to write becomes where it writes, keeping finished
    // tasks too, the same whichever switch was pressed first.
    if (agentMemoryOf(h)?.memory?.id === memory.id) await setHarnessMemories(h.id, { default_memory_id: memory.id, observe: true });
    else if (!d.default_memory_id) await setHarnessMemories(h.id, { default_memory_id: memory.id, observe: true });
  }, 'That memory was not given. Try again.');
  const turnOff = (h: CustomHarness) => run(async () => {
    const d = await getHarnessMemories(h.id);
    const g = (await listGrants(memory.id)).find((x) => x.principal === d.principal && x.memory_id === memory.id);
    if (g) await revokeGrant(memory.id, g.id);
    // the default is a memory the agent can write; losing it hands it on, said by nothing
    if (d.default_memory_id !== memory.id) return;
    const other = d.data.find((x) => x.id !== memory.id && x.privileges.includes('write'));
    await setHarnessMemories(h.id, other ? { default_memory_id: other.id } : { default_memory_id: '', observe: false });
  }, 'That memory was not taken away. Try again.');

  const needle = q.trim().toLowerCase();
  const shown = rows.filter((h) => !needle || h.name.toLowerCase().includes(needle) || (h.baseLabel || '').toLowerCase().includes(needle));

  // ── delete ────────────────────────────────────────────────────────────────────────────────
  const [asking, setAsking] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [refused, setRefused] = useState('');
  const remove = async () => {
    setDeleting(true); setRefused('');
    try { await deleteMemory(memory.id); toast(`${memory.name} deleted`); onDeleted(); }
    catch (e) { setRefused(plain(e, 'The memory was not deleted. Try again.')); setDeleting(false); }
  };
  const copy = async () => {
    try { await navigator.clipboard.writeText(memory.id); toast('Memory ID copied'); }
    catch { toast('Text selected. Press Cmd or Ctrl + C.'); }
  };

  return (
    <div className="scroll mm-settings">
      <div className="mm-set-col">
        <section className="lg-sub mm-layer">
          {write ? (
            <div onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) void save(); }}
              onKeyDown={(e) => { if (e.key === 'Enter' && (e.target as HTMLElement).tagName === 'INPUT') { e.preventDefault(); void save(); } }}>
              <NameFields nameId="mmSetName" descId="mmSetDesc" name={name} desc={desc} onName={(v) => { setName(v); setSaid(''); }} onDesc={(v) => { setDesc(v); setSaid(''); }} />
            </div>
          ) : (
            <div className="mm-nf">
              <div className="set-f"><span className="set-lb">Name</span><p className="mm-set-v">{memory.name}</p></div>
              <div className="set-f"><span className="set-lb">Description</span><p className="mm-set-v">{memory.description || 'No description yet.'}</p></div>
            </div>
          )}
          {said ? <p className="mm-sstat" role="status">{said}</p> : null}
          <div className="set-f mm-set-id">
            <span className="set-lb">ID</span>
            <span className="mm-set-idv"><code className="mono">{memory.id}</code>
              <button type="button" className="icon-btn sm" aria-label="Copy memory ID" title="Copy" onClick={() => void copy()}>{COPY}</button></span>
          </div>
        </section>

        <section className="lg-sub mm-layer">
          <div className="lg-sub-h">
            <h3>Agent harnesses{held.size ? <span className="muted">{`${held.size} on`}</span> : null}</h3>
          </div>
          {failed ? (
            <div className="empty-list ws-fail" role="alert">The agent harnesses could not be read just now. <button type="button" className="link-q inl" onClick={() => void read()}>Try again</button></div>
          ) : !setups || !grants ? (
            <Skel label="Loading agent harnesses">
              <div className="cap-list">{[0, 1, 2].map((i) => (
                <div className="cap-row mm-sl am-sk" key={i}>
                  <SkLine w={30} h={30} r={8} /><span className="grow"><SkLine w="34%" h={13} /><SkLine w="18%" h={11} style={{ marginTop: 8 }} /></span><SkLine w={56} h={26} r={13} />
                </div>
              ))}</div>
            </Skel>
          ) : (
            <>
              {rows.length >= FIND_FROM ? (
                <div className="cap-find">
                  <input className="set-in slim" type="search" placeholder={`Search ${rows.length} agent harnesses`} aria-label="Search agent harnesses" autoComplete="off" value={q} onChange={(e) => setQ(e.target.value)} />
                </div>
              ) : null}
              {!rows.length ? (
                <div className="empty-list es cap-empty"><span>No agent harnesses yet.</span></div>
              ) : shown.length ? (
                <div className="cap-list">
                  {shown.map((h) => {
                    const g = held.get(who(h.id)), mine = !!g && g.memory_id === memory.id;
                    const from = g && !mine ? above[g.memory_id] || 'the memory it is in' : '';
                    const on = !!g;
                    const sub = [h.baseLabel, h.defaultModel].filter(Boolean).join(' · ');
                    const why = from ? `Comes with ${from}` : !del ? 'Only someone who manages this memory can change who holds it' : undefined;
                    return (
                      <div className={`cap-row cap-mcp mm-sl${on ? '' : ' off'}`} key={h.id}>
                        <Markup className="cap-ic" html={partIcon(on ? 'built' : 'empty', 'memory')} />
                        <span className="grow"><b className="mm-sl-name"><span title={h.name}>{h.name}</span></b>{sub || from ? <small>{[from ? `Comes with ${from}` : '', sub].filter(Boolean).join(' · ')}</small> : null}</span>
                        <button type="button" className={`tog${on ? ' on' : ''}`} aria-pressed={on} aria-label={h.name} title={why} disabled={busy || !!from || !del}
                          onClick={() => void (mine ? turnOff(h) : turnOn(h))}><i />{on ? 'On' : 'Off'}</button>
                        <span className="mm-sl-c mm-sl-open">
                          <button type="button" className="icon-btn" aria-label={`Open ${h.name}`} title="Open" onClick={() => router.push(`/studio/${encodeURIComponent(h.id)}?tab=settings&layer=memory`)}>{OPEN_IC}</button>
                        </span>
                        <i className="cap-br" aria-hidden="true" />
                      </div>
                    );
                  })}
                </div>
              ) : <p className="set-help" role="status">Nothing here matches that.</p>}
            </>
          )}
        </section>

        {del ? (
          <section className="lg-sub mm-layer mm-set-del">
            <div className="lg-sub-h"><h3>Delete</h3></div>
            <button type="button" className="btn small danger" onClick={() => { setRefused(''); setAsking(true); }}>Delete memory</button>
          </section>
        ) : null}
      </div>
      {asking ? (
        <ConfirmSheet id="mmDl" title={`Delete ${memory.name}?`} confirmLabel="Delete memory" busy={deleting} refused={refused || undefined}
          body={`${memory.name}, its records and anything below it are destroyed, and harnesses lose it at once. This cannot be undone.`}
          onClose={() => setAsking(false)} onConfirm={() => void remove()} />
      ) : null}
    </div>
  );
}
