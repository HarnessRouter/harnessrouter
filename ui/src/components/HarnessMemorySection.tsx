'use client';
// The Memory section of Harness Settings: what this Harness's agent can recall, and where it
// writes what it learns.
//
// The agent is a member, like a person, so the list here is not a list the Harness stores: it is
// every memory the agent was granted, read from the service. Giving a memory is a grant, changing
// the role is the same grant with other privileges, and taking it away revokes that grant. The
// Harness itself holds two settings only: the memory the agent writes to when it names none, and
// whether finished turns are recorded there. Every change is applied at once, not by Save, since
// none of it is part of the Harness record.
import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  getHarnessMemories, setHarnessMemories, grant, revokeGrant, listGrants, listRoots, listChildren,
  ROLE_PRIVILEGES, roleOf, type HarnessMemories, type Memory, type Role,
} from '@/lib/memories';

/** One memory of the tree as the person signed in sees it: the names above it, and how many
 *  memories sit below it at any depth (an agent given this one reaches all of them). */
interface TreeNode { m: Memory; path: string[]; below: number }

// The whole tree, depth first. `children.count` on a memory counts only the ones directly under
// it, and what a grant reaches is everything below, so the tree is walked rather than summed.
async function loadTree(): Promise<TreeNode[]> {
  const out: TreeNode[] = [];
  const walk = async (list: Memory[], path: string[]) => {
    for (const m of list) {
      const node: TreeNode = { m, path, below: 0 };
      out.push(node);
      const start = out.length;
      if (m.children?.count) await walk(await listChildren(m.id), [...path, m.name]);
      node.below = out.length - start;
    }
  };
  await walk(await listRoots(), []);
  return out;
}

/** The entry the service keeps on a Harness record once its agent holds a memory: how the agent
 *  reaches its memories, and what the two settings ride on. It is this section's, not a custom
 *  server, and a save that left it out would undo both. */
export const MEMORIES_ENTRY_ID = 'mcp.memories';

const ROLES = Object.keys(ROLE_PRIVILEGES) as Role[];
const said = (e: unknown, fallback: string) => (e instanceof Error && e.message) || fallback;

/** `onChanged`: called after each change the service took, so the host can re-read what the
 *  change wrote on the Harness record. */
export function HarnessMemorySection({ id, builtIn, onChanged }: { id: string; builtIn: boolean; onChanged?: () => void }) {
  const router = useRouter();
  const [hm, setHm] = useState<HarnessMemories | null>(null);
  const [tree, setTree] = useState<TreeNode[] | null>(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState('');
  const [pickOpen, setPickOpen] = useState(false);
  const [pickId, setPickId] = useState<string | null>(null);
  const [pickRole, setPickRole] = useState<Role>('Editor');
  const pickRef = useRef<HTMLDivElement>(null);

  // A built-in Harness has no agent of its own to grant to, so nothing is asked of the service.
  useEffect(() => {
    if (!id || builtIn) return;
    let alive = true;
    getHarnessMemories(id).then((d) => { if (alive) setHm(d); })
      .catch((e) => { if (alive) setErr(said(e, 'This agent’s memories could not be read. Reload the page.')); });
    loadTree().then((t) => { if (alive) setTree(t); }).catch(() => { if (alive) setTree([]); });
    return () => { alive = false; };
  }, [id, builtIn]);

  useEffect(() => {
    if (!pickOpen) return;
    const away = (e: MouseEvent) => { if (!pickRef.current?.contains(e.target as Node)) setPickOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setPickOpen(false); };
    document.addEventListener('mousedown', away);
    document.addEventListener('keydown', esc);
    return () => { document.removeEventListener('mousedown', away); document.removeEventListener('keydown', esc); };
  }, [pickOpen]);

  // One change at a time: the list is re-read from the service after each, so what is shown is
  // what the agent holds, and a refusal is shown in the service's own words.
  const act = useCallback(async (key: string, fn: () => Promise<HarnessMemories | void>) => {
    if (busy) return;
    setBusy(key); setErr('');
    try { setHm((await fn()) || await getHarnessMemories(id)); onChanged?.(); }
    catch (e) {
      setErr(said(e, 'That was not changed. Try again.'));
      getHarnessMemories(id).then(setHm).catch(() => { /* the list stays as it was */ });
    }
    finally { setBusy(''); }
  }, [busy, id, onChanged]);

  if (builtIn) {
    return (
      <section className="form-section">
        <div><h3>Memory</h3><p>What this agent can recall, and where it writes what it learns.</p></div>
        <div className="field-stack">
          <div className="capability-list">
            <div className="capability-row">
              <span className="capability-icon"><iconify-icon icon="tabler:archive"></iconify-icon></span>
              <div className="capability-copy"><strong>No memories</strong>
                <span>A built-in Harness has no memory. Create a Harness of your own to give its agent one.</span></div>
            </div>
          </div>
        </div>
      </section>
    );
  }

  const granted = hm?.data || [];
  const nodeOf = (mid: string) => (tree || []).find((n) => n.m.id === mid);
  // Only a memory the person may share, and one the agent does not hold already.
  const giveable = (tree || []).filter((n) => (n.m.privileges || []).includes('delete') && !granted.some((g) => g.id === n.m.id));
  // Indented by the memories above it that are themselves in the list, so a memory whose parent
  // cannot be given does not sit under an empty step.
  const depthOf = (n: TreeNode) => n.m.ancestors.filter((a) => giveable.some((x) => x.m.id === a)).length;
  const picked = giveable.find((n) => n.m.id === pickId) || null;
  const noneToGive = (tree || []).length === 0
    ? 'There are no memories to give yet. Create one on the Memories page.'
    : 'There is no other memory you can give. You can give the memories you manage.';
  // Where the agent writes. A role can be lowered after a memory was chosen, and the choice stays
  // on the Harness; a memory the agent may only read is no place to write, so it is not named as one.
  const chosen = granted.find((g) => g.id === hm?.default_memory_id);
  const writesTo = hm?.default_memory_id && (!chosen || chosen.privileges.includes('write')) ? hm.default_memory_id : null;
  const defaultName = writesTo ? (chosen?.name || nodeOf(writesTo)?.m.name || '') : '';

  const give = () => {
    if (!hm || !picked) return;
    const mid = picked.m.id, role = pickRole;
    void act('give', async () => {
      await grant(mid, hm.principal, ROLE_PRIVILEGES[role]);
      setPickOpen(false); setPickId(null);
      // The first memory the agent may write becomes the one it writes to.
      if (!hm.default_memory_id && ROLE_PRIVILEGES[role].includes('write')) return setHarnessMemories(id, { default_memory_id: mid });
    });
  };
  // The Harness keeps naming the memory it writes to after the agent can no longer write it. When
  // that memory is taken away or lowered to Viewer, the choice moves to another memory the agent
  // may write, or to none.
  const moveDefaultFrom = (mid: string) => {
    if (hm?.default_memory_id !== mid) return undefined;
    const next = granted.find((g) => g.id !== mid && g.privileges.includes('write'));
    return setHarnessMemories(id, { default_memory_id: next ? next.id : null });
  };
  const takeAway = (mid: string) => {
    if (!hm) return;
    void act('take:' + mid, async () => {
      const own = (await listGrants(mid)).find((g) => g.principal === hm.principal && !g.inherited);
      if (!own) throw new Error('This memory reaches the agent through a memory above it. Take that one away instead.');
      await revokeGrant(mid, own.id);
      return moveDefaultFrom(mid);
    });
  };
  const setRole = (mid: string, role: Role) => {
    if (!hm) return;
    void act('role:' + mid, async () => {
      await grant(mid, hm.principal, ROLE_PRIVILEGES[role]);
      if (!ROLE_PRIVILEGES[role].includes('write')) return moveDefaultFrom(mid);
    });
  };

  return (
    <section className="form-section">
      <div><h3>Memory</h3><p>What this agent can recall, and where it writes what it learns.</p></div>
      <div className="field-stack">
        <div className="section-actions memory-head" ref={pickRef}>
          <strong>{hm === null ? '' : granted.length ? `${granted.length} ${granted.length === 1 ? 'memory' : 'memories'}` : 'No memories'}</strong>
          <button className="button small" type="button" disabled={!hm || tree === null} aria-haspopup="dialog" aria-expanded={pickOpen}
            onClick={() => { setPickOpen(!pickOpen); setPickId(null); }}>
            <iconify-icon icon="tabler:plus"></iconify-icon>Give a memory</button>
          {pickOpen && (
            <div className="memory-pick" role="dialog" aria-label="Give a memory">
              {giveable.length === 0 ? (
                <div className="memory-pick-empty">
                  <span>{noneToGive}</span>
                  <button className="button small" type="button" onClick={() => router.push('/memories')}>Open Memories</button>
                </div>
              ) : (<>
                <div className="memory-pick-list">
                  {giveable.map((n) => (
                    <button key={n.m.id} type="button" className="memory-pick-row" aria-pressed={pickId === n.m.id}
                      style={{ paddingLeft: 10 + depthOf(n) * 16 }} onClick={() => setPickId(n.m.id)}>
                      <span>{n.m.name}</span>
                      {n.below > 0 && <small>{n.below} inside</small>}
                    </button>
                  ))}
                </div>
                <div className="memory-pick-foot">
                  <select className="select" aria-label="Role" value={pickRole} onChange={(e) => setPickRole(e.target.value as Role)}>
                    {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                  </select>
                  <span>{!picked ? 'Pick a memory' : picked.below ? `Gives ${picked.m.name} and ${picked.below} inside` : `Gives ${picked.m.name}`}</span>
                  <button className="button primary small" type="button" disabled={!picked || busy === 'give'} onClick={give}>Give</button>
                </div>
              </>)}
            </div>
          )}
        </div>
        {err && <div className="plugin-note is-error" role="alert">{err}</div>}
        <div className="capability-list memory-list">
          {hm === null && !err && <div className="capability-row"><span className="capability-icon"><iconify-icon icon="tabler:archive"></iconify-icon></span><div className="capability-copy"><strong>Reading this agent&rsquo;s memories</strong></div></div>}
          {granted.map((g) => {
            const node = nodeOf(g.id);
            // Everything below when the tree shows this memory to the person; otherwise what the
            // service counts directly under it.
            const below = node ? node.below : (g.children?.count || 0);
            const role = roleOf(g.privileges);
            const writes = g.privileges.includes('write');
            const rowBusy = busy.endsWith(':' + g.id);
            return (
              <div key={g.id} className="capability-row memory-row">
                <span className="capability-icon"><iconify-icon icon="tabler:archive"></iconify-icon></span>
                <div className="capability-copy"><strong>{g.name}</strong>
                  <span>{[...(node?.path || []), g.name].join(' / ')}{below ? `, and ${below} inside` : ''}</span></div>
                <div className="capability-actions">
                  <select className="select memory-role" aria-label={`Role of this agent on ${g.name}`} value={role || ''} disabled={rowBusy}
                    onChange={(e) => setRole(g.id, e.target.value as Role)}>
                    {!role && <option value="" disabled>No role</option>}
                    {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                  </select>
                  {writes
                    ? <button className="toggle-button memory-default" type="button" aria-pressed={g.default} disabled={rowBusy}
                        onClick={() => { if (!g.default) void act('default:' + g.id, () => setHarnessMemories(id, { default_memory_id: g.id })); }}>
                        {g.default ? 'Writes here' : 'Write here'}</button>
                    : <span className="memory-readonly">read only</span>}
                  <button className="icon-button" type="button" title="Take away" aria-label={`Take ${g.name} away from this agent`} disabled={rowBusy}
                    onClick={() => takeAway(g.id)}><iconify-icon icon="tabler:x"></iconify-icon></button>
                </div>
              </div>
            );
          })}
          {hm !== null && granted.length === 0 && (
            <div className="capability-row">
              <span className="capability-icon"><iconify-icon icon="tabler:archive"></iconify-icon></span>
              <div className="capability-copy"><strong>This agent has no memory yet.</strong>
                <span>{tree !== null && giveable.length === 0 ? noneToGive : 'Give it one to start.'}</span></div>
              {tree !== null && giveable.length === 0 && <div className="capability-actions"><button className="button small" type="button" onClick={() => router.push('/memories')}>Open Memories</button></div>}
            </div>
          )}
        </div>
        {hm !== null && (
          <div className="memory-observe">
            <div><strong id="hsObserve">Record conversations</strong>
              <span>{!hm.observe ? 'Off: the agent only keeps what it chooses to remember.'
                : !writesTo ? 'Pick a memory it writes to first.'
                : defaultName ? `Each finished turn is saved to ${defaultName}.` : 'Each finished turn is saved to the memory it writes to.'}</span></div>
            <button className="memory-switch" type="button" role="switch" aria-checked={hm.observe} aria-labelledby="hsObserve" disabled={busy === 'observe'}
              onClick={() => void act('observe', () => setHarnessMemories(id, { observe: !hm.observe }))}><span /></button>
          </div>
        )}
      </div>
    </section>
  );
}
