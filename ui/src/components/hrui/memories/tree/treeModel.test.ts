import { buildRows, CAP, groupKey, kindsToWrite, memoryKey, recordOfKind, treeKey, type BranchView, type Row } from './treeModel';
import { CAPS, memory, record } from '../fixtures';
import type { Memory, MemoryRecord } from '@/lib/memories';
import { schemaIn } from '../schemaModel';

const m = (id: string, o: Partial<Memory> = {}) => memory({ id, name: id, records: { count: 1 }, ...o });
const r = (id: string, o: Partial<MemoryRecord> = {}) => record({ id, title: id, ...o });
function tree(views: Record<string, Partial<BranchView>>) {
  return (id: string): BranchView | null => (views[id] ? {
    memory: m(id), kinds: null, folders: false, records: [], failed: false, hasMore: false, children: [], childrenFailed: false, made: [], ...views[id],
  } : null);
}
const rows = (view: (id: string) => BranchView | null, o: Partial<Parameters<typeof buildRows>[0]> = {}) => buildRows({
  rootId: 'root', view, match: () => true, needle: '', filtering: false, isOpen: (_k, d) => d, showAll: () => false, ...o,
});
const said = (l: Row[]) => l.map((x) => `${x.depth}:${x.kind}:${x.kind === 'record' ? x.record.id : x.kind === 'memory' ? x.memory.id : x.kind === 'group' ? x.group.key : x.kind === 'folder' ? x.path : x.kind}`);

test('a memory reads top down: its sub memories, then its groups, then the records in them', () => {
  const view = tree({ root: { children: [m('sub')], records: [r('n1'), r('f1', { type: 'fact' })] }, sub: { records: [r('s1')] } });
  expect(said(rows(view))).toEqual(['0:memory:sub', '0:group:note', '1:record:n1', '0:group:fact', '1:record:f1']);
});
test('a sub memory that stands open shows what is in it, one level in', () => {
  const view = tree({ root: { children: [m('sub')] }, sub: { records: [r('s1')] } });
  expect(said(rows(view, { isOpen: (k, d) => (k === memoryKey('sub') ? true : d) }))).toEqual(['0:memory:sub', '1:group:note', '2:record:s1']);
});
test('a sub memory opened before it is read says so, and one that failed offers another try', () => {
  const open = (k: string, d: boolean) => (k === memoryKey('sub') ? true : d);
  expect(said(rows(tree({ root: { children: [m('sub')] } }), { isOpen: open }))).toEqual(['0:memory:sub', '1:note:note']);
  const failed = rows(tree({ root: { children: [m('sub')] }, sub: { failed: true } }), { isOpen: open });
  expect(failed[1]).toMatchObject({ kind: 'note', tone: 'failed', retry: 'records' });
});
test('a sub memory with nothing in it has no way in; one whose count is unknown keeps it', () => {
  const none = rows(tree({ root: { children: [m('a', { records: { count: 0 } }), m('b', { records: { count: null } })] } }));
  expect(none.map((x) => (x.kind === 'memory' ? x.expandable : null))).toEqual([false, true]);
});
test('a search keeps a match and the way to it, and nothing else', () => {
  const view = tree({ root: { children: [m('sub'), m('other')], records: [r('n1')] }, sub: { children: [m('deep')], records: [r('s1')] }, deep: { records: [r('needle')] }, other: { records: [r('o1')] } });
  const found = rows(view, { filtering: true, needle: 'needle', match: (x) => x.id === 'needle' });
  expect(said(found)).toEqual(['0:memory:sub', '1:memory:deep', '2:group:note', '3:record:needle']);
  expect(found.filter((x) => x.kind === 'memory').every((x) => x.kind === 'memory' && x.open)).toBe(true);
});
test('a search also finds a sub memory by its name, without opening it', () => {
  const view = tree({ root: { children: [m('needle sub')] }, 'needle sub': { records: [r('x')] } });
  const found = rows(view, { filtering: true, needle: 'needle', match: () => false });
  expect(said(found)).toEqual(['0:memory:needle sub']);
  expect(found[0]).toMatchObject({ open: false, expandable: false });
});
test('a filter stands every group open, even one a person closed', () => {
  const view = tree({ root: { records: [r('n1')] } });
  const closed = (k: string, d: boolean) => (k === groupKey('root', 'note') ? false : d);
  expect(said(rows(view, { isOpen: closed }))).toEqual(['0:group:note']);
  expect(said(rows(view, { isOpen: closed, filtering: true }))).toEqual(['0:group:note', '1:record:n1']);
});
test('folders where the provider keeps files, with what was just made and not yet filled', () => {
  const view = tree({ root: { folders: true, made: ['empty'], records: [r('a', { attributes: { folder: 'x/y' } }), r('b')] } });
  expect(said(rows(view))).toEqual(['0:folder:empty', '0:folder:x', '1:folder:x/y', '2:record:a', '0:record:b']);
});
test('a long group holds the rest back, and never the record that is open', () => {
  const many = Array.from({ length: CAP + 50 }, (_, i) => r(`r${String(i).padStart(3, '0')}`));
  const view = tree({ root: { records: many } });
  const l = rows(view);
  expect(l.filter((x) => x.kind === 'record')).toHaveLength(CAP);
  expect(l[l.length - 1]).toMatchObject({ kind: 'more', action: 'all', hidden: 50 });
  expect(rows(view, { activeId: `r${CAP + 10}` }).filter((x) => x.kind === 'record')).toHaveLength(CAP + 50);
  expect(rows(view, { showAll: () => true }).filter((x) => x.kind === 'record')).toHaveLength(CAP + 50);
});
test('more pages to read: a row for them, and the group says its count is not the whole', () => {
  const l = rows(tree({ root: { hasMore: true, records: [r('n1')] } }));
  expect(l[0]).toMatchObject({ kind: 'group', count: 1, plus: true });
  expect(l[l.length - 1]).toMatchObject({ kind: 'more', action: 'page' });
});
test('an empty memory says so, and only once it has been read', () => {
  expect(rows(tree({ root: {} }))[0]).toMatchObject({ kind: 'note', tone: 'empty', text: 'No records yet.' });
  expect(rows(tree({ root: { records: null } }))[0]).toMatchObject({ kind: 'note', tone: 'loading' });
  expect(rows(tree({ root: { children: null } })).map((x) => x.kind)).toEqual([]);
});
test('the keys walk the rows: down, up, ends; right opens then enters; left closes then goes up', () => {
  const view = tree({ root: { records: [r('n1'), r('n2')] } });
  const l = rows(view);
  const [g, a, b] = l.map((x) => x.key);
  expect(treeKey(l, g, 'ArrowDown')).toEqual({ focus: a });
  expect(treeKey(l, a, 'ArrowUp')).toEqual({ focus: g });
  expect(treeKey(l, g, 'End')).toEqual({ focus: b });
  expect(treeKey(l, b, 'Home')).toEqual({ focus: g });
  expect(treeKey(l, g, 'ArrowLeft')).toEqual({ close: g });
  expect(treeKey(l, a, 'ArrowLeft')).toEqual({ focus: g });
  expect(treeKey(l, g, 'ArrowRight')).toEqual({ focus: a });
  expect(treeKey(l, a, 'Enter')).toEqual({ activate: a });
  const closed = rows(view, { isOpen: () => false });
  expect(treeKey(closed, g, 'ArrowRight')).toEqual({ open: g });
});
test('what can be written follows the provider and the schema', () => {
  const schema = schemaIn({ types: [{ name: 'Company' }], relations: [] });
  expect(kindsToWrite(CAPS.graphiti, schema).map((k) => k.key)).toEqual(['Company', 'note']);
  expect(kindsToWrite(CAPS.mem0, null).map((k) => k.key)).toEqual(['note', 'fact', 'procedure', 'entity']);
  expect(recordOfKind('Company', CAPS.graphiti, schema)).toEqual({ type: 'entity', attributes: { entity_type: 'Company' } });
  expect(recordOfKind('note', CAPS.graphiti, schema)).toEqual({ type: 'note', attributes: {} });
});
