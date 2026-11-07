'use client';
// What the tree has read below the memory it is showing. The memory's own records come from the page,
// which keeps them for the document and the graph too. Each sub memory is read the first time it opens:
// what is below it, its records and, where the provider reads one, its schema. A search reads the whole
// of it at once, as far as a bound, and says so if it stopped there.
import { useCallback, useEffect, useRef, useState } from 'react';
import { getSchema, listProviders, listRecords, type Memory, type MemoryRecord, type Provider } from '@/lib/memories';
import { schemaGuides } from '../caps';
import { pool } from '../parts';
import { schemaIn, type LSchema } from '../schemaModel';
import { listAllRecords, listBelow, listChildren } from './api';

const PAGE = 200;
/** How many records of one memory a search or a look for one record reads. */
export const SEARCH_CAP = 5000;

export interface Branch {
  memory?: Memory; provider?: Provider | null; kinds: LSchema | null;
  records: MemoryRecord[] | null; next: string | null; failed: boolean;
  children: Memory[] | null; childrenFailed: boolean;
  /** what was forgotten or replaced, once someone asked to see it */
  gone: MemoryRecord[];
}
const blank = (): Branch => ({ kinds: null, records: null, next: null, failed: false, children: null, childrenFailed: false, gone: [] });

export function useBranches(memory: Memory, provider: Provider | null) {
  const [branches, setBranches] = useState<Record<string, Branch>>({});
  const ref = useRef(branches);
  const started = useRef(new Set<string>());
  const others = useRef<Promise<Provider[]> | null>(null);
  const [searching, setSearching] = useState(false);
  const [belowFailed, setBelowFailed] = useState(false);
  const [truncated, setTruncated] = useState(false);
  const belowDone = useRef(false);
  const goneOn = useRef(false);

  const patch = useCallback((id: string, p: Partial<Branch> | ((b: Branch) => Partial<Branch>)) => {
    const cur = ref.current[id] || blank();
    ref.current = { ...ref.current, [id]: { ...cur, ...(typeof p === 'function' ? p(cur) : p) } };
    setBranches(ref.current);
  }, []);

  const providerOf = useCallback(async (m: Memory): Promise<Provider | null> => {
    if (m.provider === provider?.id) return provider;
    if (!others.current) others.current = listProviders();
    try { return (await others.current).find((p) => p.id === m.provider) || null; }
    catch { others.current = null; return null; }
  }, [provider]);

  const readChildren = useCallback(async (id: string, count: number | undefined) => {
    if (!count) { patch(id, { children: [], childrenFailed: false }); return; }
    patch(id, { childrenFailed: false });
    try {
      const kids = await listChildren(id);
      patch(id, { children: kids, childrenFailed: false });
      kids.forEach((k) => patch(k.id, { memory: k }));
    } catch { patch(id, { childrenFailed: true }); }
  }, [patch]);

  const readGone = useCallback(async (id: string) => {
    const gone: MemoryRecord[] = [];
    let cursor: string | undefined;
    try {
      do {
        const d = await listAllRecords(id, cursor, PAGE);
        gone.push(...d.data.filter((r) => r.status !== 'active'));
        cursor = d.next || undefined;
      } while (cursor && gone.length < SEARCH_CAP);
      patch(id, { gone });
    } catch { /* the active records stand; only the extra rows are missing */ }
  }, [patch]);

  const readRecords = useCallback(async (m: Memory) => {
    patch(m.id, { failed: false });
    try {
      const d = await listRecords(m.id, { limit: PAGE });
      patch(m.id, { records: d.data, next: d.next || null, failed: false });
    } catch { patch(m.id, { failed: true }); }
  }, [patch]);

  /** Read a sub memory, once. */
  const ensure = useCallback(async (m: Memory) => {
    if (started.current.has(m.id)) return;
    started.current.add(m.id);
    patch(m.id, { memory: m });
    const prov = await providerOf(m);
    patch(m.id, { provider: prov });
    const jobs: Promise<unknown>[] = [readRecords(m)];
    if (ref.current[m.id]?.children === null) jobs.push(readChildren(m.id, m.children?.count));
    if (schemaGuides(prov)) {
      jobs.push(getSchema(m.id).then((s) => patch(m.id, { kinds: schemaIn(s) })).catch(() => {}));
    }
    if (goneOn.current) jobs.push(readGone(m.id));
    await Promise.all(jobs);
  }, [patch, providerOf, readChildren, readRecords, readGone]);

  const more = useCallback(async (id: string) => {
    const b = ref.current[id];
    if (!b?.next) return;
    const d = await listRecords(id, { limit: PAGE, cursor: b.next });
    patch(id, (c) => ({ records: [...(c.records || []), ...d.data], next: d.next || null }));
  }, [patch]);

  /** Read everything below, for a search or to find one record. */
  const loadBelow = useCallback(async () => {
    if (belowDone.current || !memory.children?.count) return;
    belowDone.current = true;
    setSearching(true); setBelowFailed(false);
    try {
      const all = await listBelow(memory.id);
      const under = new Map<string, Memory[]>();
      all.forEach((m) => { const p = m.parent_id || memory.id; under.set(p, [...(under.get(p) || []), m]); });
      patch(memory.id, { children: under.get(memory.id) || [], childrenFailed: false });
      all.forEach((m) => patch(m.id, { memory: m, children: under.get(m.id) || [], childrenFailed: false }));
      await pool(all, 4, async (m) => {
        await ensure(m);
        while (ref.current[m.id]?.next && (ref.current[m.id]?.records?.length || 0) < SEARCH_CAP) await more(m.id);
        if (ref.current[m.id]?.next) setTruncated(true);
      });
    } catch { belowDone.current = false; setBelowFailed(true); }
    finally { setSearching(false); }
  }, [memory.children?.count, memory.id, ensure, more, patch]);

  const retry = useCallback((id: string, what: 'records' | 'children') => {
    const m = ref.current[id]?.memory || (id === memory.id ? memory : null);
    if (!m) return;
    if (what === 'children') void readChildren(id, m.children?.count || 1);
    else void readRecords(m);
  }, [memory, readChildren, readRecords]);

  /** Someone changed records while a sub memory stood open: read it again, in place. */
  const refresh = useCallback((ids: string[]) => {
    ids.forEach((id) => { const m = ref.current[id]?.memory; if (m && started.current.has(id)) void readRecords(m); });
  }, [readRecords]);

  const showGone = useCallback((on: boolean) => {
    goneOn.current = on;
    if (!on) return;
    void readGone(memory.id);
    started.current.forEach((id) => { void readGone(id); });
  }, [memory.id, readGone]);

  // the memory's own sub memories; read again when their count says another came or went
  const count = memory.children?.count;
  useEffect(() => { void readChildren(memory.id, count); }, [memory.id, count, readChildren]);
  useEffect(() => { belowDone.current = false; }, [memory.id, count]);

  return { branches, patch, ensure, more, retry, refresh, loadBelow, showGone, searching, belowFailed, truncated, setTruncated };
}
