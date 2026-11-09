// The reads the tree makes that the Memories client does not carry: one level below a memory, the whole
// of what is below it, and a list that includes what was forgotten or replaced.
import { harnessFetch } from '@/lib/hfetch';
import { gwHeaders } from '@/lib/harness';
import { MemoryApiError, type Memory, type MemoryRecord } from '@/lib/memories';

const enc = encodeURIComponent;

async function read<T>(path: string): Promise<T> {
  const r = await harnessFetch(`/api/harness${path}`, { method: 'GET', headers: gwHeaders(), cache: 'no-store' });
  if (!r.ok) throw new MemoryApiError(r.status, '', `The service answered ${r.status}.`);
  return r.json() as Promise<T>;
}

/** The direct children of a memory. */
export const listChildren = (parent: string) => read<{ data: Memory[] }>(`/v1/memories?parent=${enc(parent)}`).then((d) => d.data);
/** Everything below a memory that this person may reach, parents before children. */
export const listBelow = (ancestor: string) => read<{ data: Memory[] }>(`/v1/memories?ancestor=${enc(ancestor)}`).then((d) => d.data);
/** One page of a memory's records, with what was forgotten or replaced among them. */
export const listAllRecords = (mid: string, cursor?: string, limit = 200) =>
  read<{ data: MemoryRecord[]; next: string | null }>(`/v1/memories/${enc(mid)}/records?include=all&limit=${limit}${cursor ? `&cursor=${enc(cursor)}` : ''}`);
