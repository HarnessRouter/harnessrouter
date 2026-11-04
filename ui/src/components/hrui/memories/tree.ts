// How a memory's records are arranged in the Data tab's tree: real folders where the provider keeps
// files (a record's folder is `attributes.folder`), else one group per kind of record.
import { labelOf, type MemoryRecord } from '@/lib/memories';
import { CORE, kindOf } from './caps';
import { typeLabel, type LSchema } from './schemaModel';

export interface Kind { key: string; one: string; many: string; color: string; icon: string }
const OTHER = { color: '#64748b', icon: 'note' };

/** What a kind of record is called and how it is drawn: its schema type, else the kinds every memory has. */
export function kindInfo(key: string, schema: LSchema | null): Kind {
  const t = schema?.types.find((x) => x.name === key);
  if (t) return { key, one: typeLabel(t.name), many: typeLabel(t.name), color: t.color, icon: t.icon };
  const c = CORE[key];
  if (c) return { key, ...c };
  return { key, one: typeLabel(key), many: typeLabel(key), ...OTHER };
}

export const byLabel = (a: MemoryRecord, b: MemoryRecord) => labelOf(a).localeCompare(labelOf(b));

/** One group per kind that has records: the schema's types in its order, then the kinds every memory
 *  has, then any other. */
export function groupsOf(records: MemoryRecord[], schema: LSchema | null): { kind: Kind; records: MemoryRecord[] }[] {
  const seen = new Map<string, MemoryRecord[]>();
  for (const r of records) {
    const k = kindOf(r);
    seen.set(k, [...(seen.get(k) || []), r]);
  }
  const order = [...(schema?.types.map((t) => t.name) || []), ...Object.keys(CORE)];
  const rank = (k: string) => { const i = order.indexOf(k); return i < 0 ? order.length : i; };
  return [...seen.keys()].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b))
    .map((k) => ({ kind: kindInfo(k, schema), records: (seen.get(k) || []).sort(byLabel) }));
}

export const folderOf = (r: Pick<MemoryRecord, 'attributes'>) => String(r.attributes?.folder || '').split('/').map((p) => p.trim()).filter(Boolean).join('/');
/** A folder's name as the service keeps it: plain words only, so it stays inside the memory. */
export const folderName = (v: string) => v.replace(/[^A-Za-z0-9 _.-]+/g, '').replace(/^[ .]+|[ .]+$/g, '');

export interface FolderNode { path: string; name: string; folders: FolderNode[]; records: MemoryRecord[]; total: number }
/** The folder tree: every folder a record names, and the ones just made here and not yet filled. */
export function folderTree(records: MemoryRecord[], extra: string[]): FolderNode {
  const root: FolderNode = { path: '', name: '', folders: [], records: [], total: 0 };
  const walk = (path: string) => {
    let at = root, sofar = '';
    for (const name of path.split('/').filter(Boolean)) {
      sofar = sofar ? `${sofar}/${name}` : name;
      let n = at.folders.find((f) => f.name === name);
      if (!n) { n = { path: sofar, name, folders: [], records: [], total: 0 }; at.folders.push(n); }
      at = n;
    }
    return at;
  };
  extra.forEach(walk);
  for (const r of records) walk(folderOf(r)).records.push(r);
  const finish = (n: FolderNode): number => {
    n.folders.sort((a, b) => a.name.localeCompare(b.name));
    n.records.sort(byLabel);
    n.total = n.records.length + n.folders.reduce((c, f) => c + finish(f), 0);
    return n.total;
  };
  finish(root);
  return root;
}
/** Every folder path, for Move to. */
export const allFolders = (n: FolderNode): string[] => n.folders.flatMap((f) => [f.path, ...allFolders(f)]);
