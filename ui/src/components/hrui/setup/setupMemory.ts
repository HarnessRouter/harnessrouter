// What happens to a setup's own memory when the setup changes: deleted with it, or renamed with it. From 0.40 the
// service makes a memory for a new setup's agent (named after the setup) and says so on the setup's record
// (`memory.provisioned: true`). Every line here is read from the service at the moment it is said; a service that
// doesn't say (before 0.40, or a memory a person gave the setup) gets nothing said and nothing done.
import { getCustom, type SetupDeleted } from '@/lib/harness';
import { getMemory, updateMemory, type Memory } from '@/lib/memories';
import { listBelow } from '../memories/tree/api';

/** The memory a setup's record names, with whether the service made it for the setup (`provisioned`). */
export interface OwnMemoryRef { id: string; name: string; engine: string; provisioned: boolean }
export function ownMemoryOf(raw: unknown): OwnMemoryRef | null {
  const m = raw && typeof raw === 'object' ? (raw as { memory?: unknown }).memory : null;
  if (!m || typeof m !== 'object') return null;
  const o = m as Record<string, unknown>;
  if (typeof o.id !== 'string' || !o.id) return null;
  return { id: o.id, name: String(o.name || ''), engine: String(o.engine || ''), provisioned: o.provisioned === true };
}

// ── delete ────────────────────────────────────────────────────────────────────────────────────
/** A setup's own memory as its delete is about to touch it: what it holds (its records and those of the people below
 *  it; null where any count could not be said) and the other setups that use it. */
export interface MemoryOnDelete { name: string; engine: string; count: number | null; others: string[] }

/** Read when the delete dialog opens: null where the setup's memory wasn't made for it (or nothing says). */
export async function memoryOnDelete(hid: string): Promise<MemoryOnDelete | null> {
  const own = ownMemoryOf(await getCustom(hid));
  if (!own?.provisioned) return null;
  let m: Memory;
  try { m = await getMemory(own.id); } catch { return { name: own.name, engine: own.engine, count: null, others: [] }; }
  const others = (m.used_by || []).filter((u) => u.harness_id !== hid).map((u) => u.name).filter(Boolean);
  let count: number | null = m.records?.count ?? null;
  if (count !== null && m.children?.count) {
    try {
      const below = await listBelow(m.id);
      for (const k of below) {
        if (k.id === m.id) continue;
        const n = k.records?.count;
        if (typeof n !== 'number') { count = null; break; }
        count += n;
      }
    } catch { count = null; }
  }
  return { name: m.name || own.name, engine: m.engine || m.provider || own.engine, count, others };
}

const names = (l: string[]) => (l.length <= 2 ? l.join(' and ') : `${l.slice(0, -1).join(', ')} and ${l[l.length - 1]}`);
/** What one thing in a memory is called: Mem0 keeps facts; anything else, records. */
const thing = (engine: string, n: number) => `${n.toLocaleString('en-US')} ${engine === 'mem0' ? (n === 1 ? 'fact' : 'facts') : n === 1 ? 'record' : 'records'}`;

/** The delete dialog's line about the setup's memory. */
export function memoryOnDeleteLine(x: MemoryOnDelete | null): string {
  if (!x) return '';
  if (x.others.length) return `Its memory, ${x.name}, stays: ${names(x.others)} ${x.others.length === 1 ? 'uses' : 'use'} it too.`;
  return `This also deletes its memory${x.count !== null ? ` (${thing(x.engine, x.count)})` : ''}, unless another agent uses it.`;
}

/** The toast once the setup is deleted, from what the service says it did with the memory. */
export function deletedToast(setup: string, out: SetupDeleted | null | undefined): string {
  const name = setup.trim() || 'The setup';
  if (out?.memory_deleted) return `${name} deleted, and its memory with it.`;
  const kept = out?.memory_kept;
  if (kept) {
    const by = kept && typeof kept === 'object' && Array.isArray((kept as { used_by?: unknown }).used_by)
      ? ((kept as { used_by: unknown[] }).used_by).map((u) => (u && typeof u === 'object' ? String((u as { name?: unknown }).name || '') : '')).filter(Boolean)
      : [];
    return by.length ? `${name} deleted. Its memory stays: ${names(by)} ${by.length === 1 ? 'uses' : 'use'} it.` : `${name} deleted. Its memory stays: another agent uses it.`;
  }
  return `${name} deleted`;
}

// ── rename ────────────────────────────────────────────────────────────────────────────────────
/** The name and description the service gives the memory it makes for a setup (gateway _memory_provision). */
export const autoMemoryName = (setup: string) => (setup || 'Agent').slice(0, 120);
export const autoMemoryDescription = (setup: string) => `What ${(setup || 'this agent').slice(0, 80)} remembers from its work.`;

/** What a setup's memory takes when the setup is renamed: the new name where it still has the one it was made with,
 *  the new description where it still has that one too. Null where nothing changes: a memory a person renamed keeps
 *  its name, and so does one the setup was given rather than made for it. */
export function memoryRenameOf(was: string, now: string, m: Pick<Memory, 'name' | 'description'>, provisioned: boolean): { name?: string; description?: string } | null {
  if (!provisioned || !now.trim() || was === now) return null;
  const out: { name?: string; description?: string } = {};
  if (m.name === autoMemoryName(was) && autoMemoryName(now) !== m.name) out.name = autoMemoryName(now);
  if (out.name && m.description === autoMemoryDescription(was)) out.description = autoMemoryDescription(now);
  return out.name ? out : null;
}

/** After a setup is renamed: its memory follows, where the service made it for the setup and it still carries the
 *  name it was made with. True when it was renamed. */
export async function followRename(raw: unknown, was: string, now: string): Promise<boolean> {
  const own = ownMemoryOf(raw);
  if (!own?.provisioned) return false;
  const m = await getMemory(own.id);
  const patch = memoryRenameOf(was, now, m, true);
  if (!patch) return false;
  await updateMemory(own.id, patch);
  return true;
}
