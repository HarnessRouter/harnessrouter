// The left column as data: a memory's whole shape flattened into the rows on screen, in reading order.
// Below a memory come its sub memories, then its folders or its groups of one kind, then records. Only
// what is expanded becomes a row, and a long group holds back the rest behind Show all, so a memory with
// thousands of records costs what is on screen. A flat list is also what the arrow keys walk.
import { bodyOf, labelOf, shownName, type Memory, type MemoryRecord, type Provider, type RecallFilter } from '@/lib/memories';
import { coreKindsToWrite, kindOf, recordTypeOfSchemaKind, schemaGuides } from '../caps';
import { folderTree, groupsOf, kindInfo, type FolderNode, type Kind } from '../tree';
import type { LSchema } from '../schemaModel';

/** How many records a group or a folder shows before Show all. */
export const CAP = 100;

interface RowBase { key: string; depth: number; parent: string; memoryId: string }
export interface MemoryRow extends RowBase { kind: 'memory'; memory: Memory; count: number | null; expandable: boolean; open: boolean }
export interface GroupRow extends RowBase { kind: 'group'; group: Kind; count: number; plus: boolean; open: boolean }
export interface FolderRow extends RowBase { kind: 'folder'; path: string; name: string; count: number; plus: boolean; open: boolean }
export interface RecordRow extends RowBase { kind: 'record'; record: MemoryRecord; info: Kind }
export interface MoreRow extends RowBase { kind: 'more'; action: 'all' | 'page'; scope: string; hidden: number }
export interface NoteRow extends RowBase { kind: 'note'; tone: 'loading' | 'failed' | 'empty'; text: string; retry?: 'records' | 'children' }
export type Row = MemoryRow | GroupRow | FolderRow | RecordRow | MoreRow | NoteRow;

/** What one memory holds right now, as far as it has been read. */
export interface BranchView {
  memory: Memory; kinds: LSchema | null; folders: boolean;
  records: MemoryRecord[] | null; failed: boolean; hasMore: boolean;
  children: Memory[] | null; childrenFailed: boolean; made: string[];
}
export interface BuildArgs {
  rootId: string;
  view: (id: string) => BranchView | null;
  match: (r: MemoryRecord) => boolean;
  needle: string;
  /** a search or a filter is on: only what it finds shows, and the way to it stands open */
  filtering: boolean;
  isOpen: (key: string, otherwise: boolean) => boolean;
  showAll: (key: string) => boolean;
  activeId?: string;
  cap?: number;
  /** a search's order for what it found, the best first (rankOf); left out, by name */
  order?: (a: MemoryRecord, b: MemoryRecord) => number;
}

export const memoryKey = (id: string) => `m:${id}`;
export const groupKey = (mid: string, kind: string) => `g:${mid}:${kind}`;
export const folderKey = (mid: string, path: string) => `f:${mid}:${path}`;
export const recordKey = (mid: string, rid: string) => `r:${mid}:${rid}`;

export function buildRows(a: BuildArgs): Row[] {
  const { view, match, needle, filtering, isOpen, showAll, activeId, cap = CAP, order } = a;

  const leaves = (mid: string, kinds: LSchema | null, recs: MemoryRecord[], depth: number, parent: string, scope: string): Row[] => {
    let list = recs, hidden = 0;
    if (recs.length > cap && !showAll(scope)) {
      // the record open now is never the one held back
      const at = activeId ? recs.findIndex((r) => r.id === activeId) : -1;
      if (at < cap) { list = recs.slice(0, cap); hidden = recs.length - cap; }
    }
    const out: Row[] = list.map((r) => ({ kind: 'record', key: recordKey(mid, r.id), depth, parent, memoryId: mid, record: r, info: kindInfo(kindOf(r), kinds) }));
    if (hidden) out.push({ kind: 'more', key: `all:${scope}`, depth, parent, memoryId: mid, action: 'all', scope, hidden });
    return out;
  };

  const folderRows = (mid: string, kinds: LSchema | null, n: FolderNode, depth: number, parent: string, plus: boolean): Row[] => {
    const out: Row[] = [];
    for (const f of n.folders) {
      const key = folderKey(mid, f.path);
      const open = filtering || isOpen(key, true);
      out.push({ kind: 'folder', key, depth, parent, memoryId: mid, path: f.path, name: f.name, count: f.total, plus, open });
      if (open) out.push(...folderRows(mid, kinds, f, depth + 1, key, plus));
    }
    out.push(...leaves(mid, kinds, n.records, depth, parent, folderKey(mid, n.path)));
    return out;
  };

  const visit = (mid: string, depth: number, parent: string): Row[] => {
    const v = view(mid);
    if (!v) return filtering ? [] : [{ kind: 'note', key: `load:${mid}`, depth, parent, memoryId: mid, tone: 'loading', text: 'Loading…' }];
    const out: Row[] = [];
    // the signed-in person's own memory first (Richard 11-10), then the others as the service listed them
    const kids = [...(v.children || [])].sort((a, b) => Number(!!b.yours) - Number(!!a.yours));
    for (const child of kids) {
      const key = memoryKey(child.id);
      const count = child.records?.count ?? null;
      const inner = () => visit(child.id, depth + 1, key);
      if (filtering) {
        const found = inner();
        const named = !!needle && shownName(child).toLowerCase().includes(needle);
        if (!found.length && !named) continue;
        out.push({ kind: 'memory', key, depth, parent, memoryId: child.id, memory: child, count, expandable: found.length > 0, open: found.length > 0 });
        out.push(...found);
        continue;
      }
      // a count the service could not say is no reason to hide the way in
      const expandable = (child.children?.count || 0) > 0 || count === null || count > 0;
      const open = expandable && isOpen(key, !!child.yours);       // one's own stands open until closed
      out.push({ kind: 'memory', key, depth, parent, memoryId: child.id, memory: child, count, expandable, open });
      if (open) out.push(...inner());
    }
    if (v.childrenFailed) out.push({ kind: 'note', key: `kidsfail:${mid}`, depth, parent, memoryId: mid, tone: 'failed', text: 'What is below this could not be read just now.', retry: 'children' });
    if (v.failed) {
      out.push({ kind: 'note', key: `recfail:${mid}`, depth, parent, memoryId: mid, tone: 'failed', text: 'The records could not be read just now.', retry: 'records' });
      return out;
    }
    if (!v.records) {
      if (!filtering) out.push({ kind: 'note', key: `recload:${mid}`, depth, parent, memoryId: mid, tone: 'loading', text: 'Loading…' });
      return out;
    }
    const shown = v.records.filter(match);
    const before = out.length;
    if (v.folders) {
      out.push(...folderRows(mid, v.kinds, folderTree(shown, filtering ? [] : v.made, order), depth, parent, v.hasMore));
    } else {
      for (const g of groupsOf(shown, v.kinds, order)) {
        const key = groupKey(mid, g.kind.key);
        const open = filtering || isOpen(key, true);
        out.push({ kind: 'group', key, depth, parent, memoryId: mid, group: g.kind, count: g.records.length, plus: v.hasMore, open });
        if (open) out.push(...leaves(mid, v.kinds, g.records, depth + 1, key, key));
      }
    }
    if (!filtering && out.length === before && v.children && !v.children.length) {
      out.push({ kind: 'note', key: `none:${mid}`, depth, parent, memoryId: mid, tone: 'empty', text: depth ? 'Nothing here yet.' : 'No records yet.' });
    }
    if (v.hasMore && !filtering) out.push({ kind: 'more', key: `page:${mid}`, depth, parent, memoryId: mid, action: 'page', scope: mid, hidden: 0 });
    return out;
  };
  return visit(a.rootId, 0, '');
}

export const isExpandable = (r: Row) => (r.kind === 'memory' ? r.expandable : r.kind === 'group' || r.kind === 'folder');
export const isOpenRow = (r: Row) => (r.kind === 'memory' || r.kind === 'group' || r.kind === 'folder') && r.open;

export interface KeyMove { focus?: string; open?: string; close?: string; activate?: string }
/** What a key does to the tree: Up and Down walk it, Right opens a row and then enters it, Left closes a
 *  row and then goes to its parent, Home and End go to the ends, Enter and Space act on the row. */
export function treeKey(rows: Row[], focus: string, key: string): KeyMove | null {
  const list = rows.filter((r) => r.kind !== 'note');
  if (!list.length) return null;
  const at = list.findIndex((r) => r.key === focus);
  const me = at >= 0 ? list[at] : null;
  switch (key) {
    case 'ArrowDown': return { focus: list[Math.min(at + 1, list.length - 1)].key };
    case 'ArrowUp': return { focus: list[Math.max(at - 1, 0)].key };
    case 'Home': return { focus: list[0].key };
    case 'End': return { focus: list[list.length - 1].key };
    case 'ArrowRight':
      if (!me || !isExpandable(me)) return null;
      if (!isOpenRow(me)) return { open: me.key };
      return list[at + 1] && list[at + 1].depth > me.depth ? { focus: list[at + 1].key } : null;
    case 'ArrowLeft':
      if (!me) return null;
      if (isExpandable(me) && isOpenRow(me)) return { close: me.key };
      return me.parent ? { focus: me.parent } : null;
    case 'Enter':
    case ' ':
      return me ? { activate: me.key } : null;
    default: return null;
  }
}

/** One thing a search by meaning found, as the engine answered it (POST /v1/memories/{id}/recall). */
export interface Found { record: MemoryRecord; score: number | null; why?: string[] }
/** Where an engine's best answer stands out from the rest of what it gave (a sentence on the subject among sentences
 *  that aren't), it is a find: measured on one engine (11-09), the records on a subject scored 0.71 to 0.75 and every
 *  other record of the memory 0.08 to 0.17. An engine like that ranks every record it holds for any words at all,
 *  "zebra quantum volcano" included, so its whole list is no answer by itself. */
const STANDS_OUT = 2;
/** A best score this high is on the subject whatever the rest scored (every record on it). */
const ON_SUBJECT = 0.35;
/** A find scores at least this share of the best. */
const NEAR_BEST = 0.5;
/** An engine that ranks without scoring gives each find its place for a score (1, 1 - 1/n, ...): no measure of how
 *  near, so its list is taken as it is. */
function placesOnly(scores: number[]): boolean {
  if (scores.length < 2 || Math.abs(scores[0] - 1) > 1e-3) return false;
  const step = scores[0] - scores[1];
  // each the one before it less the same step: 1, 1 less a step, 1 less two steps, ...
  return step > 0 && scores.every((s, i) => 1e-3 > Math.abs(s + i * step - 1));
}
/** What a search by meaning found that matches, in the engine's order: what it found by the words themselves, and
 *  what scores near its best where its best stands out (from the rest, or on its own). An engine that gives no scores,
 *  or only places, is taken at its word. */
export function meaningHits(found: Found[]): MemoryRecord[] {
  const list = found.filter((x) => x.record?.id);
  const scores = list.map((x) => x.score);
  if (!list.length || scores.some((s) => typeof s !== 'number' || !Number.isFinite(s)) || placesOnly(scores as number[])) return list.map((x) => x.record);
  const nums = scores as number[];
  const best = Math.max(...nums);
  const sorted = [...nums].sort((a, b) => a - b);
  const mid = sorted.length % 2 ? sorted[(sorted.length - 1) / 2] : (sorted[sorted.length / 2 - 1] + sorted[sorted.length / 2]) / 2;
  const standsOut = list.length < 3 || best >= ON_SUBJECT || best >= STANDS_OUT * mid;
  return list.filter((x, i) => (x.why || []).includes('text') || (standsOut && nums[i] >= best * NEAR_BEST)).map((x) => x.record);
}
/** A search's order: what the engine found, in its order, then what holds the words and it didn't find, by name. */
export function rankOf(found: MemoryRecord[]): (a: MemoryRecord, b: MemoryRecord) => number {
  const at = new Map(found.map((r, i) => [r.id, i]));
  const of = (r: MemoryRecord) => at.get(r.id) ?? found.length;
  return (a, b) => of(a) - of(b) || labelOf(a).localeCompare(labelOf(b));
}

/** Does this record hold the words being looked for? The same test on its line and its text. */
export const hitRecord = (r: MemoryRecord, q: string) => !q || labelOf(r).toLowerCase().includes(q) || bodyOf(r).toLowerCase().includes(q);
/** The filter that finds a fact by one of its labels. */
export const labelFilter = (value: string): RecallFilter => ({ field: 'attributes.labels', op: 'contains', value });

/** The kinds of record this provider and schema let a person write, in the order they are offered. */
export function kindsToWrite(p: Provider | null | undefined, schema: LSchema | null): Kind[] {
  const typed = schemaGuides(p) ? (schema?.types || []).map((t) => kindInfo(t.name, schema)) : [];
  return [...typed, ...coreKindsToWrite(p).map((k) => kindInfo(k, null))];
}
/** A kind as the service takes it: a schema's type is a record that names it, anything else is its own type. */
export function recordOfKind(kind: string, p: Provider | null | undefined, schema: LSchema | null): { type: string; attributes: Record<string, unknown> } {
  if (schemaGuides(p) && schema?.types.some((t) => t.name === kind)) return { type: recordTypeOfSchemaKind(p), attributes: { entity_type: kind } };
  return { type: kind, attributes: {} };
}
