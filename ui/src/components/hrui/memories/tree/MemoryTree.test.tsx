/** @jest-environment jsdom */
// The tree in a browser's shape: the capability document decides what it offers, a sub memory reads
// itself when opened, and a search keeps the way to what it finds.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { CAPS, memory, record, service } from '../fixtures';
import type { Memory, MemoryRecord, Provider } from '@/lib/memories';
import { schemaIn } from '../schemaModel';

jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
jest.mock('@/lib/auth', () => ({ getSession: () => null }));
jest.mock('@/lib/edition', () => ({ LOCAL_MEMBER: 'local@localhost' }));
jest.mock('@/lib/harness', () => ({ gwHeaders: () => ({}), listCustom: jest.fn(async () => []) }));
jest.mock('../../setup/settingsModel', () => ({
  plain: (e: unknown, f: string) => (e instanceof Error && e.message ? e.message : f),
  plural: (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`,
}));

import { harnessFetch } from '@/lib/hfetch';
import { MemoryTree, type MemoryTreeProps } from './MemoryTree';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let root: Root; let el: HTMLElement;
const flush = async () => { for (let i = 0; i < 16; i++) await act(async () => { await Promise.resolve(); }); };
const rows = () => Array.from(el.querySelectorAll<HTMLElement>('[role=treeitem]'));
const said = () => rows().map((r) => `${r.getAttribute('aria-level')}:${r.querySelector('.mt-lbl')?.textContent}`);
const row = (t: string) => rows().find((r) => r.querySelector('.mt-lbl')?.textContent === t) as HTMLElement;
const click = async (b: Element | null | undefined) => {
  if (!b) throw new Error(`nothing to click: ${document.body.textContent}`);
  await act(async () => { (b as HTMLElement).click(); });
  await flush();
};
const menuOf = async (t: string) => {
  await click(el.querySelector(`button[aria-label="More actions for ${t}"]`));
  return Array.from(el.querySelectorAll('[role=menuitem]')).map((m) => m.textContent);
};
const menuItem = (t: string) => Array.from(el.querySelectorAll('[role=menuitem]')).find((m) => m.textContent === t);
const sheetButton = (t: string) => Array.from(document.querySelectorAll('button')).find((b) => b.textContent === t);
const type = async (input: HTMLInputElement, v: string) => {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set?.call(input, v);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await flush();
};
const key = async (k: string, target: Element = document.activeElement as Element) => {
  await act(async () => { target.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true })); });
  await flush();
};

interface Open { provider?: Provider; memory?: Memory; records?: MemoryRecord[]; subs?: Memory[]; routes?: Record<string, unknown>; props?: Partial<MemoryTreeProps>; read?: Partial<MemoryTreeProps['read']>; schema?: MemoryTreeProps['schema'] }
function open(o: Open = {}) {
  const provider = o.provider || CAPS.mem0;
  const m = o.memory || memory({ id: 'hmem_1', name: 'Root', provider: provider.id, children: { count: o.subs?.length || 0 } });
  const s = service({
    'GET /v1/memories': (c: { path: string }) => ({ data: c.path.includes('parent=hmem_1') || c.path.includes('ancestor=hmem_1') ? o.subs || [] : [] }),
    ...(o.routes || {}),
  } as Record<string, unknown>);
  (harnessFetch as jest.Mock).mockImplementation(s.fetcher);
  const read = { records: o.records ?? [], failed: false, retry: jest.fn(), more: null, put: jest.fn(), drop: jest.fn(), ...o.read } as MemoryTreeProps['read'];
  const props: MemoryTreeProps = { memory: m, provider, schema: o.schema ?? null, read, activeId: '', onOpen: jest.fn(), onNew: jest.fn(), onChanged: jest.fn(), ...o.props };
  return { s, read, props };
}
async function mount(p: MemoryTreeProps) { await act(async () => { root.render(<MemoryTree {...p} />); }); await flush(); }

beforeEach(() => {
  window.localStorage.clear();
  el = document.createElement('div'); el.id = 'hrui'; document.body.appendChild(el);
  root = createRoot(el);
});
afterEach(async () => { await act(async () => root.unmount()); el.remove(); jest.useRealTimers(); });

const sub = (o: Partial<Memory> = {}) => memory({ id: 'hmem_s', name: 'Sub', parent_id: 'hmem_1', provider: 'mem0', records: { count: 1 }, ...o });
const subRoutes = { 'GET /v1/memories/hmem_s/records': { data: [record({ id: 's1', title: 'In the sub', memory_id: 'hmem_s' })], next: null } };

test('the whole shape: a sub memory as a folder, then a group per kind, with counts from the data', async () => {
  const t = open({ records: [record({ id: 'a', title: 'A note' }), record({ id: 'b', title: 'A fact', type: 'fact' })], subs: [sub()] });
  await mount(t.props);
  expect(said()).toEqual(['1:Sub', '1:Notes', '2:A note', '1:Facts', '2:A fact']);
  expect(row('Facts').querySelector('.mt-count')?.textContent).toBe('1');
  expect(el.querySelector('[role=tree]')).not.toBeNull();
});
test('a person’s memory below an agent’s is listed by the person the service names, never by its hashed name', async () => {
  // the shape GET /v1/memories?parent= answers its manager: `end_user` beside a name that is a hash of it
  const t = open({ subs: [sub({ id: 'hmem_p', name: '5d41402abc4b2a76b9719d91', restricted: true, end_user: 'dana@guests.example' })] });
  await mount(t.props);
  expect(said()).toEqual(['1:dana@guests.example']);
});

test('a sub memory reads itself only when it is opened, and its record opens with its memory', async () => {
  const t = open({ subs: [sub()], routes: subRoutes });
  await mount(t.props);
  expect(t.s.calls.some((c) => c.path.includes('hmem_s/records'))).toBe(false);
  await click(row('Sub'));
  expect(t.s.calls.some((c) => c.path.includes('hmem_s/records'))).toBe(true);
  expect(said()).toEqual(['1:Sub', '2:Notes', '3:In the sub']);
  await click(row('In the sub'));
  expect(t.props.onOpen).toHaveBeenCalledWith('s1', 'hmem_s', expect.objectContaining({ id: 's1' }));
});
test('a record of this memory opens with no memory named', async () => {
  const t = open({ records: [record({ id: 'a', title: 'A note' })] });
  await mount(t.props);
  await click(row('A note'));
  expect(t.props.onOpen).toHaveBeenCalledWith('a', undefined, expect.objectContaining({ id: 'a' }));
});
test('a search reads what is below and keeps the way to a match open', async () => {
  const t = open({ records: [record({ id: 'a', title: 'Nothing like it' })], subs: [sub()], routes: { 'GET /v1/memories/hmem_s/records': { data: [record({ id: 's1', title: 'The needle', memory_id: 'hmem_s' })], next: null } } });
  await mount(t.props);
  expect(said()).toEqual(['1:Sub', '1:Notes', '2:Nothing like it']);
  await type(el.querySelector('input[aria-label="Find in Root"]') as HTMLInputElement, 'needle');
  expect(t.s.calls.some((c) => c.path.includes('ancestor=hmem_1'))).toBe(true);
  expect(said()).toEqual(['1:Sub', '2:Notes', '3:The needle']);
  expect(row('Sub').getAttribute('aria-expanded')).toBe('true');
  expect(el.querySelector('.mt-status')?.textContent).toContain('1 record');
  await type(el.querySelector('input[aria-label="Find in Root"]') as HTMLInputElement, 'not there at all');
  // nothing is said to match until the engine has answered too
  expect(el.textContent).not.toContain('Nothing here matches');
  await act(async () => { await new Promise((r) => setTimeout(r, 350)); });
  await flush();
  expect(el.textContent).toContain('Nothing here matches “not there at all”.');
  expect(rows()).toHaveLength(0);
});

// What the walkthrough saw (11-09): an engine that ranks every record it holds for any words. Its scores as measured:
// a record on the subject well above the rest, and for words on no subject at all, every record alike and low.
const DANA = [
  record({ id: 'n', title: '', type: 'fact', content: [{ type: 'text', text: 'User’s name is Dana' }] }),
  record({ id: 'e', title: '', type: 'fact', content: [{ type: 'text', text: 'User prefers to be contacted by email only and never by phone' }] }),
  record({ id: 'b', title: '', type: 'fact', content: [{ type: 'text', text: 'User prefers all future chat replies in short bullet points' }] }),
  record({ id: 's', title: '', type: 'fact', content: [{ type: 'text', text: 'User experienced the invoices page not loading in Safari' }] }),
];
const ranked = (pairs: [string, number][]) => ({ results: pairs.map(([id, score]) => ({ record: DANA.find((r) => r.id === id), score, why: ['query'] })), degraded: [], abstain: false });
const search = async (words: string) => {
  await type(el.querySelector('input[aria-label="Find in Root"]') as HTMLInputElement, words);
  await act(async () => { await new Promise((r) => setTimeout(r, 350)); });
  await flush();
};
test('a search by meaning lists what the engine found, best first, and hides the rest', async () => {
  const t = open({ records: DANA, routes: { 'POST /v1/memories/hmem_1/recall': ranked([['e', 0.41], ['b', 0.16], ['n', 0.12], ['s', 0.09]]) } });
  await mount(t.props);
  await search('how should we reach');
  expect(said()).toEqual(['1:Facts', '2:User prefers to be contacted by email only and never by phone']);
  expect(el.querySelector('.mt-status')?.textContent).toBe('1 record');
});
test('words on no subject at all: nothing matches, and the tree says so', async () => {
  const t = open({ records: DANA, routes: { 'POST /v1/memories/hmem_1/recall': ranked([['s', 0.14], ['n', 0.12], ['b', 0.1], ['e', 0.08]]) } });
  await mount(t.props);
  await search('zebra quantum volcano');
  expect(rows()).toHaveLength(0);
  expect(el.textContent).toContain('Nothing here matches “zebra quantum volcano”.');
});
test('several finds come in the engine’s order, not by name; a literal match it didn’t rank comes after them', async () => {
  const t = open({ records: DANA, routes: { 'POST /v1/memories/hmem_1/recall': ranked([['s', 0.62], ['e', 0.55], ['n', 0.11], ['b', 0.1]]) } });
  await mount(t.props);
  await search('Dana');
  expect(said()).toEqual(['1:Facts', '2:User experienced the invoices page not loading in Safari', '2:User prefers to be contacted by email only and never by phone', '2:User’s name is Dana']);
});
test('a search reads on through pages it has not seen', async () => {
  const more = jest.fn();
  const t = open({ records: [record({ id: 'a', title: 'Here' })], read: { more } });
  await mount(t.props);
  expect(more).not.toHaveBeenCalled();
  await type(el.querySelector('input[aria-label="Find in Root"]') as HTMLInputElement, 'x');
  expect(more).toHaveBeenCalledTimes(1);
});
test('the keys: down and up move focus, left closes a group, right opens it, enter opens a record', async () => {
  const t = open({ records: [record({ id: 'a', title: 'First' }), record({ id: 'b', title: 'Second' })] });
  await mount(t.props);
  const tree = el.querySelector('[role=tree]') as HTMLElement;
  const g = row('Notes');
  expect(g.tabIndex).toBe(0);
  expect(rows().filter((r) => r.tabIndex === 0)).toHaveLength(1);
  await act(async () => { g.focus(); });
  await key('ArrowDown');
  expect((document.activeElement as HTMLElement).dataset.key).toBe(row('First').dataset.key);
  await key('Enter');
  expect(t.props.onOpen).toHaveBeenCalledWith('a', undefined, expect.objectContaining({ id: 'a' }));
  await key('ArrowUp');
  expect(document.activeElement).toBe(row('Notes'));
  await key('ArrowLeft');
  expect(row('First')).toBeUndefined();
  expect(row('Notes').getAttribute('aria-expanded')).toBe('false');
  await key('ArrowRight', row('Notes'));
  expect(row('First')).toBeDefined();
  expect(tree.getAttribute('aria-label')).toBe('What Root holds');
});
test('a record offers what the provider and this person allow, and nothing else', async () => {
  const live = open({ records: [record({ id: 'a', title: 'Mine' })] });
  await mount(live.props);
  expect(await menuOf('Mine')).toEqual(['Open', 'Copy link', 'Forget']);
  await act(async () => root.unmount()); root = createRoot(el);
  const readOnly = open({ records: [record({ id: 'a', title: 'Mine' })], memory: memory({ id: 'hmem_1', name: 'Root', provider: 'mem0', privileges: ['read'] }) });
  await mount(readOnly.props);
  expect(await menuOf('Mine')).toEqual(['Open', 'Copy link']);
  expect(el.querySelector('button[aria-label="New"]')).toBeNull();
  await act(async () => root.unmount()); root = createRoot(el);
  const noForget = open({ provider: { ...CAPS.mem0, forget: false }, records: [record({ id: 'a', title: 'Mine' })] });
  await mount(noForget.props);
  expect(await menuOf('Mine')).toEqual(['Open', 'Copy link']);
  await act(async () => root.unmount()); root = createRoot(el);
  const episode = open({ records: [record({ id: 'a', title: 'What happened', type: 'episode' })] });
  await mount(episode.props);
  expect(await menuOf('What happened')).toEqual(['Open', 'Copy link']);
});
test('escape closes a row menu and the keys carry on from that row', async () => {
  const t = open({ records: [record({ id: 'a', title: 'Mine' })] });
  await mount(t.props);
  await menuOf('Mine');
  expect(document.activeElement?.getAttribute('role')).toBe('menuitem');
  await key('Escape', document.body);
  expect(el.querySelector('[role=menu]')).toBeNull();
  expect(document.activeElement).toBe(row('Mine'));
});
test('forgetting asks first, says what happens, and the row goes', async () => {
  const t = open({ records: [record({ id: 'a', title: 'Mine' })], routes: { 'DELETE /v1/memories/hmem_1/records/a': { id: 'a' } } });
  await mount(t.props);
  await menuOf('Mine');
  await click(menuItem('Forget'));
  expect(document.body.textContent).toContain('Forget Mine?');
  await click(sheetButton('Forget'));
  expect(t.s.sent('DELETE', '/v1/memories/hmem_1/records/a')).toHaveLength(1);
  expect(t.read.drop).toHaveBeenCalledWith('a');
  expect(t.props.onChanged).toHaveBeenCalled();
});
test('a refusal stays in the sheet in the service\'s words', async () => {
  const t = open({ records: [record({ id: 'a', title: 'Mine' })], routes: { 'DELETE /v1/memories/hmem_1/records/a': { $status: 403, error: { code: 'memory_forbidden', message: 'Only an admin can.' } } } });
  await mount(t.props);
  await menuOf('Mine');
  await click(menuItem('Forget'));
  await click(sheetButton('Forget'));
  expect(document.body.textContent).toContain('Only an admin can.');
  expect(t.read.drop).not.toHaveBeenCalled();
});
test('copy link writes this record\'s address on this page and says so in the console', async () => {
  const writeText = jest.fn(async () => undefined);
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
  const seen: string[] = [];
  const hear = (e: Event) => seen.push(String((e as CustomEvent).detail));
  window.addEventListener('hrui:toast', hear);
  const t = open({ records: [record({ id: 'a b', title: 'Mine' })] });
  await mount(t.props);
  await menuOf('Mine');
  await click(menuItem('Copy link'));
  expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/memories/hmem_1?tab=data&record=a%20b`);
  expect(seen).toContain('Link copied');
  window.removeEventListener('hrui:toast', hear);
});
test('a sub memory offers by its own privileges', async () => {
  const full = open({ subs: [sub()], routes: subRoutes });
  await mount(full.props);
  expect(await menuOf('Sub')).toEqual(['New Note', 'New Fact', 'New Procedure', 'New Entity', 'New sub memory', 'Rename', 'Delete']);
  await act(async () => root.unmount()); root = createRoot(el);
  const readOnly = open({ subs: [sub({ privileges: ['read'] })], routes: subRoutes });
  await mount(readOnly.props);
  expect(el.querySelector('button[aria-label="More actions for Sub"]')).toBeNull();
  expect(row('Sub').querySelector('[title="View only"]')).not.toBeNull();
});
test('a new sub memory goes under its parent, with its parent\'s provider', async () => {
  const made = sub({ id: 'hmem_n', name: 'Fresh', parent_id: 'hmem_1', records: { count: 0 } });
  const t = open({ routes: { 'POST /v1/memories': made } });
  await mount(t.props);
  await click(el.querySelector('button[aria-label="New"]'));
  await click(menuItem('Sub memory'));
  await type(document.getElementById('mtNsN') as HTMLInputElement, 'Fresh');
  await click(sheetButton('Create'));
  expect(t.s.sent('POST', '/v1/memories')[0].body).toMatchObject({ name: 'Fresh', parent_id: 'hmem_1', provider: 'mem0' });
  expect(row('Fresh')).toBeDefined();
  expect(t.props.onChanged).toHaveBeenCalled();
});
test('deleting a sub memory says what goes, and it goes', async () => {
  const t = open({ subs: [sub()], routes: { ...subRoutes, 'DELETE /v1/memories/hmem_s': { memories: ['hmem_s'] } } });
  await mount(t.props);
  await menuOf('Sub');
  await click(menuItem('Delete'));
  expect(document.body.textContent).toContain('Sub, its records and anything below it are destroyed');
  await click(sheetButton('Delete memory'));
  expect(t.s.sent('DELETE', '/v1/memories/hmem_s')).toHaveLength(1);
  expect(row('Sub')).toBeUndefined();
});
test('a new record in a sub memory is made there and opened; this memory\'s goes to the page as a draft', async () => {
  const made = record({ id: 's2', title: 'Made', memory_id: 'hmem_s' });
  const t = open({ subs: [sub()], routes: { ...subRoutes, 'POST /v1/memories/hmem_s/records': made } });
  await mount(t.props);
  await menuOf('Sub');
  await click(menuItem('New Note'));
  await type(document.getElementById('mtNrT') as HTMLInputElement, 'Made');
  await click(sheetButton('Save'));
  expect(t.s.sent('POST', '/v1/memories/hmem_s/records')[0].body).toMatchObject({ type: 'note', title: 'Made' });
  expect(t.props.onOpen).toHaveBeenCalledWith('s2', 'hmem_s', expect.objectContaining({ id: 's2' }));
  expect(t.props.onNew).not.toHaveBeenCalled();
  await click(el.querySelector('button[aria-label="New"]'));
  await click(menuItem('New Fact'));
  expect(t.props.onNew).toHaveBeenCalledWith('fact', undefined);
});
test('a sub memory on another provider offers what that provider can do, with its own schema', async () => {
  const t = open({ subs: [sub({ provider: 'graphiti' })], routes: {
    ...subRoutes, 'GET /v1/memories/providers': { data: [CAPS.mem0, CAPS.graphiti] },
    'GET /v1/memories/hmem_s/schema': { types: [{ name: 'Company' }], relations: [] },
  } });
  await mount(t.props);
  expect(await menuOf('Sub')).toEqual(['New Company', 'New Note', 'New sub memory', 'Rename', 'Delete']);
});
test('a group offers New only for a kind that can be written', async () => {
  const schema = schemaIn({ types: [{ name: 'Company' }], relations: [] });
  const t = open({ provider: CAPS.graphiti, schema, records: [
    record({ id: 'a', title: 'Acme', type: 'entity', attributes: { entity_type: 'Company' } }),
    record({ id: 'b', title: 'A fact', type: 'fact', written_by: { kind: 'provider', id: 'x' } }),
  ] });
  await mount(t.props);
  await click(row('Company').querySelector('button[aria-label="New Company"]'));
  expect(t.props.onNew).toHaveBeenCalledWith('Company', undefined);
  expect(row('Facts').querySelector('.mt-rowact')).toBeNull();
});
test('the header offers the schema\'s types and the provider\'s own kinds, and each reaches the page', async () => {
  const schema = schemaIn({ types: [{ name: 'Company' }], relations: [] });
  const t = open({ provider: CAPS.graphiti, schema });
  await mount(t.props);
  await click(el.querySelector('button[aria-label="New"]'));
  const items = Array.from(el.querySelectorAll('[role=menuitem]')).map((m) => m.textContent);
  expect(items).toEqual(['New Company', 'New Note', 'Sub memory']);
  await click(menuItem('New Note'));
  expect(t.props.onNew).toHaveBeenCalledWith('note', undefined);
});
test('labels: the menu lists them, and choosing one asks the service and shows only what carries it', async () => {
  const schema = schemaIn({ types: [{ name: 'billing' }], relations: [] });
  const hit = record({ id: 'c', title: 'Not read yet', type: 'fact', attributes: { labels: ['billing'] } });
  const t = open({ provider: CAPS.hindsight, schema, records: [record({ id: 'a', title: 'Other', type: 'fact', attributes: { labels: ['support'] } })],
    routes: { 'POST /v1/memories/hmem_1/recall': { results: [{ record: hit, score: null }], degraded: [] } } });
  await mount(t.props);
  await click(el.querySelector('button[aria-label="Filter by label"]'));
  expect(Array.from(el.querySelectorAll('[role=menuitem]')).map((m) => m.textContent)).toEqual(expect.arrayContaining(['billing', 'support']));
  await click(menuItem('billing'));
  // the label's search goes out on a timer (0 ms with no words): let it run, then what it found draws
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
  await flush();
  expect(t.s.sent('POST', '/v1/memories/hmem_1/recall')[0].body).toMatchObject({ filters: { field: 'attributes.labels', op: 'contains', value: 'billing' } });
  expect(row('Not read yet')).toBeDefined();
  expect(row('Other')).toBeUndefined();
  await click(el.querySelector('button[aria-label="Show every label"]'));
  expect(row('Other')).toBeDefined();
});
test('a filter by type, with a chip that takes it off', async () => {
  const t = open({ records: [record({ id: 'a', title: 'A note' }), record({ id: 'b', title: 'A fact', type: 'fact' })] });
  await mount(t.props);
  await click(el.querySelector('button[aria-label="Filter by type"]'));
  await click(menuItem('Fact'));
  expect(row('A note')).toBeUndefined();
  expect(row('A fact')).toBeDefined();
  await click(el.querySelector('button[aria-label="Show every type"]'));
  expect(row('A note')).toBeDefined();
});
test('forgotten and replaced records come only when asked for, marked as such', async () => {
  const t = open({ records: [record({ id: 'a', title: 'Live' })], routes: { 'GET /v1/memories/hmem_1/records': { data: [
    record({ id: 'a', title: 'Live' }), record({ id: 'b', title: 'Old', status: 'forgotten' }), record({ id: 'c', title: 'Older', status: 'superseded' }),
  ], next: null } } });
  await mount(t.props);
  expect(row('Old')).toBeUndefined();
  await click(el.querySelector('button[aria-label="Filter by type"]'));
  await click(menuItem('Show forgotten and replaced'));
  expect(t.s.calls.some((c) => c.path.includes('include=all'))).toBe(true);
  expect(row('Old').querySelector('.mt-mark')?.textContent).toBe('Forgotten');
  expect(row('Older').querySelector('.mt-mark')?.textContent).toBe('Replaced');
  expect(row('Live').querySelector('.mt-mark')).toBeNull();
  await click(el.querySelector('button[aria-label="Hide forgotten and replaced"]'));
  expect(row('Old')).toBeUndefined();
});
test('real folders, a new one, and a new record that lands in the folder chosen', async () => {
  const t = open({ provider: CAPS.reme, records: [record({ id: 'a', title: 'Deep', attributes: { folder: 'plans/q4' } }), record({ id: 'b', title: 'Top' })] });
  await mount(t.props);
  expect(said()).toEqual(['1:plans', '2:q4', '3:Deep', '1:Top']);
  await click(row('q4'));
  expect(row('Deep')).toBeUndefined();
  await click(el.querySelector('button[aria-label="New"]'));
  await click(menuItem('Folder'));
  const box = el.querySelector('input[aria-label="Folder name"]') as HTMLInputElement;
  await type(box, 'drafts');
  await key('Enter', box);
  expect(said()).toContain('3:drafts');
  expect(el.textContent).toContain('A folder is kept once a record is in it.');
  await click(el.querySelector('button[aria-label="New"]'));
  await click(menuItem('New Note'));
  expect(t.props.onNew).toHaveBeenCalledWith('note', 'plans/q4/drafts');
});
test('load more: the row asks the page for the next records', async () => {
  const more = jest.fn();
  const t = open({ records: [record({ id: 'a', title: 'First' })], read: { more } });
  await mount(t.props);
  expect(row('Facts')).toBeUndefined();
  expect(row('Notes').querySelector('.mt-count')?.textContent).toBe('1+');
  await click(row('Show more'));
  expect(more).toHaveBeenCalled();
});
test('a thousand records: the first hundred, then Show all, with every number from the data', async () => {
  const records = Array.from({ length: 1000 }, (_, i) => record({ id: `r${i}`, title: `Record ${String(i).padStart(4, '0')}` }));
  const t = open({ records });
  await mount(t.props);
  expect(rows()).toHaveLength(102);
  expect(row('Notes').querySelector('.mt-count')?.textContent).toBe('1,000');
  await click(row('Show all (900 more)'));
  expect(rows()).toHaveLength(1001);
});
test('which groups were closed is remembered per memory', async () => {
  const t = open({ records: [record({ id: 'a', title: 'First' })] });
  await mount(t.props);
  await click(row('Notes'));
  expect(row('First')).toBeUndefined();
  await act(async () => root.unmount()); root = createRoot(el);
  await mount(open({ records: [record({ id: 'a', title: 'First' })] }).props);
  expect(row('First')).toBeUndefined();
  await act(async () => root.unmount()); root = createRoot(el);
  await mount(open({ memory: memory({ id: 'hmem_2', name: 'Other', provider: 'mem0' }), records: [record({ id: 'a', title: 'First' })] }).props);
  expect(row('First')).toBeDefined();
});
test('opened from elsewhere: a closed group opens to it, and the row comes into view', async () => {
  const scroll = jest.fn();
  Element.prototype.scrollIntoView = scroll;
  const t = open({ records: [record({ id: 'a', title: 'First' })] });
  await mount(t.props);
  await click(row('Notes'));
  expect(row('First')).toBeUndefined();
  await mount({ ...t.props, activeId: 'a' });
  expect(row('First').getAttribute('aria-selected')).toBe('true');
  expect(scroll).toHaveBeenCalled();
});
test('opened from elsewhere in a sub memory: the tree reads below and opens the way', async () => {
  const t = open({ subs: [sub()], routes: subRoutes });
  await mount(t.props);
  await mount({ ...t.props, activeId: 's1' });
  expect(row('In the sub').getAttribute('aria-selected')).toBe('true');
  expect(row('Sub').getAttribute('aria-expanded')).toBe('true');
});
test('a record that changed live is marked, and one that just came slides in', async () => {
  const t = open({ records: [record({ id: 'a', title: 'First' })] });
  await mount(t.props);
  await mount({ ...t.props, pulse: ['a'] });
  expect(row('First').className).toContain('mt-pulse');
  const read = { ...t.read, records: [record({ id: 'b', title: 'Second' }), record({ id: 'a', title: 'First' })] };
  await mount({ ...t.props, read });
  expect(row('Second').className).toContain('mt-fresh');
  expect(row('First').className).not.toContain('mt-fresh');
});
test('honest states: reading, a failure with another try, and nothing kept', async () => {
  const t = open({ read: { records: null } });
  await mount(t.props);
  expect(el.textContent).toContain('Loading…');
  await act(async () => root.unmount()); root = createRoot(el);
  const f = open({ read: { records: null, failed: true } });
  await mount(f.props);
  expect(el.querySelector('[role=alert]')?.textContent).toContain('could not be read just now');
  await click(sheetButton('Try again'));
  expect(f.read.retry).toHaveBeenCalled();
  await act(async () => root.unmount()); root = createRoot(el);
  await mount(open().props);
  expect(el.textContent).toContain('No records yet.');
});
test('a long name truncates and keeps its whole self as a title', async () => {
  const long = 'A very long record name that will not fit in a narrow column at all, however it is drawn';
  const t = open({ records: [record({ id: 'a', title: long })] });
  await mount(t.props);
  expect(row(long).getAttribute('title')).toBe(long);
});

test('a standing instruction says so on its row; one an agent set says agents get it as a note; what an engine drew says nothing', async () => {
  const t = open({ records: [
    record({ id: 'a', title: 'Quote in euros', attributes: { standing: true }, written_by: { kind: 'member', id: 'ada@example.com', type: 'human' } }),
    record({ id: 'b', title: 'Be brief', attributes: { standing: true }, written_by: { kind: 'member', id: 'chrn_desk', type: 'agent' } }),
    record({ id: 'c', title: 'Plain note' }),
    record({ id: 'd', title: 'Drawn', type: 'fact', attributes: { standing: true }, written_by: { kind: 'provider', id: 'x' }, references: [{ rel: 'derived_from', record_id: 'e', available: true }] }),
  ] });
  await mount(t.props);
  expect(row('Quote in euros').querySelector('.mt-stand')?.textContent).toBe('Standing');
  expect(row('Be brief').querySelector('.mt-noted')?.textContent).toBe('Noted by an agent as standing');
  expect(row('Plain note').querySelector('.mt-stand, .mt-noted')).toBeNull();
  expect(row('Drawn').querySelector('.mt-stand, .mt-noted')).toBeNull();
});
