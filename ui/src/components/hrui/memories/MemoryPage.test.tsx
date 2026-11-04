/** @jest-environment jsdom */
// One memory, and the rule that matters most: the capability document drives the page, never a vendor's
// name. Each test gives the page a capability document and reads what it offers.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { CAPS, memory, record, service } from './fixtures';
import type { Memory, MemoryRecord, Provider } from '@/lib/memories';

jest.mock('next/navigation', () => ({ useRouter: () => ({ push: jest.fn(), replace: jest.fn() }) }));
jest.mock('next/link', () => ({ __esModule: true, default: ({ children, href, className }: { children: React.ReactNode; href: string; className?: string }) => <a className={className} href={href}>{children}</a> }));
jest.mock('react-markdown', () => ({ __esModule: true, default: ({ children }: { children: string }) => <p>{children}</p> }));
jest.mock('remark-gfm', () => ({ __esModule: true, default: () => undefined }));
jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
jest.mock('@/lib/auth', () => ({ getSession: () => null }));
jest.mock('@/lib/edition', () => ({ LOCAL_MEMBER: 'local@localhost' }));
jest.mock('@/lib/harness', () => ({ gwHeaders: () => ({}), listCustom: jest.fn(async () => [{ id: 'chrn_a', name: 'Photo cut' }]) }));
jest.mock('../setups', () => ({ ago: () => '2 d ago' }));
jest.mock('../setup/settingsModel', () => ({
  plain: (e: unknown, f: string) => (e instanceof Error && e.message ? e.message : f),
  plural: (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`,
}));

import { harnessFetch } from '@/lib/hfetch';
import { MemoryPage } from './MemoryPage';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let root: Root; let el: HTMLElement;
const flush = async () => { for (let i = 0; i < 14; i++) await act(async () => { await Promise.resolve(); }); };
const page = () => document.getElementById('hrui') as HTMLElement;
const button = (t: string) => Array.from(page().querySelectorAll('button')).find((b) => (b.textContent || '').trim() === t) as HTMLButtonElement | undefined;
const byLabel = (t: string) => page().querySelector(`button[aria-label="${t}"]`) as HTMLButtonElement | null;
const tabs = () => Array.from(page().querySelectorAll('[role=tab]')).map((t) => t.textContent);
async function click(b: Element | null | undefined) {
  if (!b) throw new Error(`nothing to click: ${page().textContent}`);
  await act(async () => { (b as HTMLElement).click(); });
  await flush();
}
const SCHEMA = {
  types: [{ name: 'Company', description: 'A customer.', properties: [{ name: 'seats', type: 'number' }], x: 200, y: 200 }, { name: 'Person', description: '', properties: [], x: 500, y: 200 }],
  relations: [{ name: 'WORKS_AT', from: 'Person', to: 'Company' }],
};
function open(o: { provider: Provider; memory?: Memory; records?: MemoryRecord[]; schema?: unknown; tab?: string | null; graph?: unknown; extra?: Record<string, unknown> }) {
  const m = o.memory || memory({ provider: o.provider.id });
  const s = service({
    'GET /v1/memories/providers': { data: [o.provider] },
    'GET /v1/memories/hmem_1': m,
    'GET /v1/memories/hmem_1/grants': { data: [] },
    'GET /v1/memories/hmem_1/records': { data: o.records || [], next: null },
    'GET /v1/memories/hmem_1/schema': o.schema || { types: [], relations: [] },
    'PUT /v1/memories/hmem_1/schema': (c: { body: object }) => c.body,
    'POST /v1/memories/hmem_1/graph': o.graph || { nodes: [], edges: [], truncated: false, degraded: [] },
    ...o.extra,
  });
  (harnessFetch as jest.Mock).mockImplementation(s.fetcher);
  return s;
}
async function draw(tab: string | null = null) {
  await act(async () => { root.render(<MemoryPage id="hmem_1" tabParam={tab} recordParam={null} onTab={() => {}} />); });
  await flush();
}
beforeEach(() => {
  el = document.createElement('div'); el.id = 'hrui';
  document.body.appendChild(el);
  root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); el.remove(); jest.clearAllMocks(); });

describe('a schema exists only where something reads it', () => {
  test('mode none: no Schema tab, no tabs at all, no schema read, just Data', async () => {
    const s = open({ provider: CAPS.mem0, records: [record()] });
    await draw('schema');   // even when the address asks for it
    expect(page().querySelector('[role=tablist]')).toBeNull();
    expect(page().textContent).not.toContain('Schema');
    expect(s.sent('GET', '/v1/memories/hmem_1/schema')).toHaveLength(0);
    expect(page().querySelector('.mm-data')).toBeTruthy();
    expect(page().querySelector('.mm-schema')).toBeNull();
  });
  test('mode guides: Schema and Data, the line that says what reads it, and what was measured', async () => {
    open({ provider: CAPS.graphiti, schema: SCHEMA, records: [record()] });
    await draw('schema');
    expect(tabs()).toEqual(['Schema', 'Data']);
    expect(page().querySelector('.mm-guide')?.textContent).toBe('Graphiti uses these types to decide what to pull out of each task.');
    expect(page().textContent).toContain('Types work best for things with a name, like people, companies and products.');
    expect(page().textContent).toContain('Relations you name replace the words we’d otherwise pick, so name every kind you care about. Anything else stays linked as related, with its sentence kept.');
    expect(page().querySelector('.mm-svg')).toBeTruthy();
  });
  test('with no relations yet, leaving them out is offered as a choice', async () => {
    open({ provider: CAPS.graphiti, schema: { types: SCHEMA.types, relations: [] }, records: [record()] });
    await draw('schema');
    expect(page().textContent).toContain('Relations are optional.');
    expect(page().textContent).not.toContain('Relations you name replace');
  });
  test('a starting point keeps to things with a name and draws no relation for you', async () => {
    const s = open({ provider: CAPS.graphiti, records: [] });
    await draw('schema');
    expect(page().textContent).not.toMatch(/Issue|Fix\b/);
    await click(button('CustomersCompany, person, product') || page().querySelector('.mm-start'));
    await act(async () => { await new Promise((r) => setTimeout(r, 700)); });
    await flush();
    const put = s.sent('PUT', '/v1/memories/hmem_1/schema')[0].body as { types: { name: string }[]; relations: unknown[] };
    expect(put.types.map((t) => t.name)).toEqual(['Company', 'Person', 'Product']);
    expect(put.relations).toEqual([]);
  });
});

describe('what the schema declares', () => {
  const guides = (schema: Provider['schema']): Provider => ({ ...CAPS.graphiti, schema });
  test('relations false: no way to draw a relation, on the canvas or on a type', async () => {
    open({ provider: guides({ mode: 'guides', properties: true, relations: false }), schema: { types: SCHEMA.types }, records: [record()] });
    await draw('schema');
    expect(button('Relate')).toBeUndefined();
    expect(page().querySelector('.mm-svg')).toBeTruthy();   // the canvas still works, without edges
    await click(Array.from(page().querySelectorAll('.mm-li')).find((b) => b.textContent?.includes('Company')));
    expect(button('Add relation')).toBeUndefined();
    expect(button('Add property')).toBeTruthy();
  });
  test('relations true: the way to draw one is there', async () => {
    open({ provider: CAPS.graphiti, schema: SCHEMA, records: [record()] });
    await draw('schema');
    expect(button('Relate')).toBeTruthy();
    await click(Array.from(page().querySelectorAll('.mm-li')).find((b) => b.textContent?.includes('Company')));
    expect(button('Add relation')).toBeTruthy();
  });
  test('properties false: the type panel has no property section, and none is written', async () => {
    const s = open({ provider: guides({ mode: 'guides', properties: false, relations: true }), schema: SCHEMA, records: [record()] });
    await draw('schema');
    await click(Array.from(page().querySelectorAll('.mm-li')).find((b) => b.textContent?.includes('Company')));
    expect(page().querySelector('[data-section=properties]')).toBeNull();
    expect(button('Add property')).toBeUndefined();
    const name = page().querySelector('.mm-tdesc') as HTMLTextAreaElement;
    const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!;
    await act(async () => { set.call(name, 'A customer we serve.'); name.dispatchEvent(new Event('input', { bubbles: true })); });
    await act(async () => { await new Promise((r) => setTimeout(r, 700)); });
    await flush();
    const put = s.sent('PUT', '/v1/memories/hmem_1/schema')[0].body as { types: { properties: unknown[] }[] };
    expect(put.types.every((t) => t.properties.length === 0)).toBe(true);
  });
  test('a type saved with a space in its name goes as one word and reads as two', async () => {
    const s = open({ provider: CAPS.graphiti, schema: SCHEMA, records: [record()] });
    await draw('schema');
    await click(Array.from(page().querySelectorAll('.mm-li')).find((b) => b.textContent?.includes('Company')));
    const name = page().querySelector('.mm-tname') as HTMLInputElement;
    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
    await act(async () => { set.call(name, 'Big company'); name.dispatchEvent(new Event('input', { bubbles: true })); });
    await act(async () => { await new Promise((r) => setTimeout(r, 700)); });
    await flush();
    expect((page().querySelector('.mm-tname') as HTMLInputElement).value).toBe('Big company');
    const put = s.sent('PUT', '/v1/memories/hmem_1/schema')[0].body as { types: { name: string }[]; relations: { to: string }[] };
    expect(put.types[0].name).toBe('Big_company');
    expect(put.relations[0].to).toBe('Big_company');
  });
});

describe('mode labels: a vocabulary applied to facts', () => {
  const fact = (id: string, text: string, labels?: string[]) => record({ id, type: 'fact', title: '', content: [{ type: 'text', text }], attributes: labels ? { labels } : {}, written_by: { kind: 'provider', id: 'hindsight' } });
  test('called Labels: no canvas, no properties, no relations, and PUT sends names and descriptions alone', async () => {
    const s = open({ provider: CAPS.hindsight, schema: { types: [{ name: 'Company', description: 'A business.' }], relations: [] }, records: [fact('f1', 'Acme signed up.')] });
    await draw('labels');
    expect(tabs()).toEqual(['Labels', 'Data']);
    expect(page().querySelector('.mm-svg')).toBeNull();
    expect(page().querySelector('.mm-canvas')).toBeNull();
    expect(button('Relate')).toBeUndefined();
    expect(button('Add property')).toBeUndefined();
    expect(page().textContent).not.toContain('Hindsight uses these types');
    const desc = page().querySelector('input[aria-label="What Company means"]') as HTMLInputElement;
    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
    await act(async () => { set.call(desc, 'A business we sell to.'); desc.dispatchEvent(new Event('input', { bubbles: true })); });
    await act(async () => { await new Promise((r) => setTimeout(r, 700)); });
    await flush();
    expect(s.sent('PUT', '/v1/memories/hmem_1/schema')[0].body).toEqual({ types: [{ name: 'Company', description: 'A business we sell to.' }] });
  });
  test('each fact shows its labels', async () => {
    open({ provider: CAPS.hindsight, schema: { types: [{ name: 'Company' }] }, records: [fact('f1', 'Acme signed up.', ['Company', 'Big_deal'])] });
    await draw('data');
    expect(Array.from(page().querySelectorAll('.mm-lab')).map((x) => x.textContent)).toEqual(['Company', 'Big deal']);
  });
  test('filtering by a label asks with the contains filter, and lists only what carries it whatever comes back', async () => {
    const s = open({
      provider: CAPS.hindsight, schema: { types: [{ name: 'Company' }] }, records: [fact('f1', 'Acme signed up.', ['Company']), fact('f2', 'Dana reports to Sam.')],
      extra: { 'POST /v1/memories/hmem_1/recall': { results: [{ record: fact('f1', 'Acme signed up.', ['Company']), score: 1 }, { record: fact('f3', 'A fact with no label.'), score: 1 }, { record: fact('f4', 'Beta signed up.', ['Company']), score: 1 }], degraded: [] } },
    });
    await draw('data');
    await click(byLabel('Filter by label'));
    await click(Array.from(page().querySelectorAll('.mm-pop .mm-mi')).find((b) => b.textContent === 'Company'));
    await act(async () => { await new Promise((r) => setTimeout(r, 5)); });
    await flush();
    expect(s.sent('POST', '/v1/memories/hmem_1/recall')[0].body).toEqual({ filters: { field: 'attributes.labels', op: 'contains', value: 'Company' }, limit: 100 });
    const rows = Array.from(page().querySelectorAll('.mm-trr .mm-tt')).map((x) => x.textContent);
    expect(rows.sort()).toEqual(['Acme signed up.', 'Beta signed up.']);
  });
});

describe('folders are the provider’s', () => {
  const note = (id: string, title: string, folder?: string) => record({ id, title, attributes: folder ? { folder } : {} });
  test('layout files: real folders from attributes.folder, and a new folder is allowed and files what comes next', async () => {
    const s = open({
      provider: CAPS.reme, records: [note('a', 'Rules', 'lumen/launch'), note('b', 'Loose')],
      extra: { 'POST /v1/memories/hmem_1/records': (c: { body: { title: string; attributes: Record<string, unknown> } }) => record({ id: 'c', title: c.body.title, attributes: c.body.attributes }) },
    });
    await draw();
    expect(Array.from(page().querySelectorAll('.mm-tf .mm-tt')).map((x) => x.textContent)).toEqual(['lumen', 'launch']);
    await click(byLabel('New'));
    expect(Array.from(page().querySelectorAll('.mm-pop .mm-mi')).map((b) => b.textContent)).toContain('Folder');
    await click(Array.from(page().querySelectorAll('.mm-pop .mm-mi')).find((b) => b.textContent === 'Folder'));
    const input = page().querySelector('input[aria-label="Folder name"]') as HTMLInputElement;
    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
    await act(async () => { set.call(input, 'Spring'); input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); });
    await flush();
    expect(Array.from(page().querySelectorAll('.mm-tf .mm-tt')).map((x) => x.textContent)).toContain('Spring');
    await click(byLabel('New'));
    expect(page().querySelector('.mm-pop-h')?.textContent).toBe('New record in Spring');
    await click(Array.from(page().querySelectorAll('.mm-pop .mm-mi')).find((b) => b.textContent === 'Note'));
    const title = page().querySelector('h1.mm-title') as HTMLElement;
    await act(async () => { title.textContent = 'In the folder'; title.dispatchEvent(new FocusEvent('focusout', { bubbles: true })); });
    await flush();
    expect(s.sent('POST', '/v1/memories/hmem_1/records')[0].body).toEqual({ type: 'note', title: 'In the folder', attributes: { folder: 'Spring' } });
  });
  test('anywhere else: no folders, the tree groups by type, and no new folder', async () => {
    open({ provider: CAPS.mem0, records: [note('a', 'Rules', 'lumen'), record({ id: 'f', type: 'fact', title: 'A fact' }), note('b', 'Loose')] });
    await draw();
    expect(Array.from(page().querySelectorAll('.mm-tf .mm-tt')).map((x) => x.textContent)).toEqual(['Notes', 'Facts']);
    await click(byLabel('New'));
    expect(Array.from(page().querySelectorAll('.mm-pop .mm-mi')).map((b) => b.textContent)).not.toContain('Folder');
  });
});

describe('a derived record', () => {
  const found = (o: Partial<MemoryRecord> = {}) => record({ id: 'd', type: 'fact', title: 'Acme uses Slack', written_by: { kind: 'provider', id: 'graphiti' }, ...o });
  test('reads as found and cannot be edited', async () => {
    open({ provider: CAPS.graphiti, records: [found()] });
    await draw('data');
    expect(page().textContent).toContain('Found by Graphiti');
    expect(page().querySelector('.mm-doc [contenteditable]')).toBeNull();
    expect(page().querySelector('.mm-doc [role=textbox]')).toBeNull();
    expect(page().querySelector('.mm-doc textarea')).toBeNull();
  });
  test('a word in `revise` speaks of what a writer stated, so it stays read only', async () => {
    open({ provider: { ...CAPS.graphiti, revise: 'native' }, records: [found()] });
    await draw('data');
    expect(page().querySelector('.mm-doc [contenteditable]')).toBeNull();
  });
  test('is open only where `revise` says otherwise', async () => {
    open({ provider: { ...CAPS.graphiti, revise: { derived: true } }, records: [found()] });
    await draw('data');
    expect(page().querySelector('h1.mm-title')?.getAttribute('contenteditable')).toBe('plaintext-only');
    expect(page().textContent).not.toContain('Read only');
  });
  test('a record a person wrote stays open on the same provider', async () => {
    open({ provider: CAPS.graphiti, records: [record({ id: 'w', title: 'Mine' })] });
    await draw('data');
    expect(page().querySelector('h1.mm-title')?.getAttribute('contenteditable')).toBe('plaintext-only');
  });
  test('a fact leads with its sentence, its word comes second, and RELATES_TO reads as related to', async () => {
    const sentence = 'Dana reports to Sam at Acme.';
    const f = found({ title: '', content: [{ type: 'text', text: sentence }], attributes: { predicate: 'RELATES_TO' }, references: [] });
    open({
      provider: CAPS.graphiti, records: [f],
      graph: {
        nodes: [{ record: f, memory: { id: 'hmem_1', name: 'Brand kits' } }, { record: found({ id: 'e', type: 'entity', title: 'Acme', content: [], attributes: {} }), memory: { id: 'hmem_1', name: 'Brand kits' } }],
        edges: [{ from: { memory_id: 'hmem_1', record_id: 'd' }, to: { memory_id: 'hmem_1', record_id: 'e' }, rel: 'RELATES_TO', available: true }], truncated: false, degraded: [],
      },
    });
    await draw('data');
    const col = page().querySelector('.mm-doc-col') as HTMLElement;
    expect(col.firstElementChild?.textContent).toBe(sentence);
    expect(page().querySelector('.mm-pred')?.textContent).toBe('related to');
    expect(page().querySelector('.mm-lrel')?.textContent).toContain('related to');
    expect(page().textContent).not.toContain('RELATES_TO');
  });
});

describe('an action a provider does not serve is not shown', () => {
  const mine = record({ id: 'r', title: 'Mine' });
  test('with everything served: versions, forget, erase', async () => {
    open({ provider: CAPS.mem0, records: [mine] });
    await draw();
    expect(byLabel('Versions')).toBeTruthy();
    await click(page().querySelector('.mm-doc-bar button[aria-label="More"]'));
    expect(Array.from(page().querySelectorAll('.mm-doc-bar .mm-mi b')).map((b) => b.textContent)).toEqual(['Forget', 'Erase']);
  });
  test('no history: no versions; no forget and no erase: no menu', async () => {
    open({ provider: { ...CAPS.mem0, history: { content: 'none' }, forget: false, erase: false }, records: [mine] });
    await draw();
    expect(byLabel('Versions')).toBeNull();
    expect(page().querySelector('.mm-doc-bar button[aria-label="More"]')).toBeNull();
  });
  test('no revise: the record cannot be edited, even one a person wrote', async () => {
    open({ provider: { ...CAPS.mem0, revise: false }, records: [mine] });
    await draw();
    expect(page().querySelector('.mm-doc [contenteditable]')).toBeNull();
  });
  test('an episode is what happened: not edited and not forgotten; an entity the provider derives is not forgotten either', async () => {
    const ep = record({ id: 'ep', type: 'episode', title: 'Task', written_by: { kind: 'provider', id: 'graphiti' } });
    open({ provider: CAPS.graphiti, records: [ep] });
    await draw('data');
    expect(page().textContent).toContain('Kept from a finished task. Read only.');
    await click(page().querySelector('.mm-doc-bar button[aria-label="More"]'));
    expect(Array.from(page().querySelectorAll('.mm-doc-bar .mm-mi b')).map((b) => b.textContent)).toEqual(['Erase']);
    await act(async () => { root.unmount(); }); root = createRoot(el);
    const ent = record({ id: 'en', type: 'entity', title: 'Acme', written_by: { kind: 'provider', id: 'graphiti' } });
    open({ provider: CAPS.graphiti, records: [ent] });
    await draw('data');
    await click(page().querySelector('.mm-doc-bar button[aria-label="More"]'));
    expect(Array.from(page().querySelectorAll('.mm-doc-bar .mm-mi b')).map((b) => b.textContent)).toEqual(['Erase']);
  });
  test('reading only: nothing that writes is offered', async () => {
    open({ provider: CAPS.graphiti, memory: memory({ provider: 'graphiti', privileges: ['read'] }), schema: SCHEMA, records: [mine] });
    await draw('data');
    expect(byLabel('New')).toBeNull();
    expect(page().querySelector('.mm-doc [contenteditable]')).toBeNull();
    expect(page().querySelector('.mm-doc-bar button[aria-label="More"]')).toBeNull();
    expect(page().querySelector('.mm-page .ag-bar button[aria-label="More"]')).toBeNull();
  });
  test('what could not be erased is said', async () => {
    const s = open({ provider: CAPS.mem0, records: [mine], extra: { 'POST /v1/memories/hmem_1/erase': { erased: ['r'], unreachable: ['r'] } } });
    await draw();
    await click(page().querySelector('.mm-doc-bar button[aria-label="More"]'));
    await click(Array.from(page().querySelectorAll('.mm-doc-bar .mm-mi')).find((b) => b.textContent?.startsWith('Erase')));
    await click(button('Erase'));
    expect(s.sent('POST', '/v1/memories/hmem_1/erase')[0].body).toEqual({ record_ids: ['r'] });
    expect(page().textContent).toContain('Not all of it could be erased');
  });
});

describe('connections', () => {
  test('none kept and none to show: the panel goes', async () => {
    open({ provider: { ...CAPS.mem0, graph: { entities: 'none' } }, records: [record({ id: 'r' })] });
    await draw();
    expect(page().querySelector('.mm-conn')).toBeNull();
    expect(button('Connections')).toBeUndefined();
    expect(page().querySelector('.mm-data')?.classList.contains('no-conn')).toBe(true);
  });
  test('a provider with no links at all: the panel goes, and the graph is not asked', async () => {
    const { graph: _g, ...rest } = CAPS.mem0;
    const s = open({ provider: rest as Provider, records: [record({ id: 'r' })] });
    await draw();
    expect(page().querySelector('.mm-conn')).toBeNull();
    expect(s.sent('POST', '/v1/memories/hmem_1/graph')).toHaveLength(0);
  });
  test('one that keeps stated links: the panel stays, and a link can be made with a word of your own', async () => {
    const a = record({ id: 'a', title: 'Alpha' }), b = record({ id: 'b', title: 'Beta' });
    const s = open({
      provider: CAPS.mem0, records: [a, b],
      graph: { nodes: [{ record: a, memory: { id: 'hmem_1', name: 'x' } }], edges: [], truncated: false, degraded: [] },
      extra: { 'PATCH /v1/memories/hmem_1/records/a': a, 'PATCH /v1/memories/hmem_1/records/b': b },
    });
    await draw();
    expect(page().querySelector('.mm-conn')).toBeTruthy();
    await click(button('Link a record'));
    await click(button('Link'));
    const patched = [...s.sent('PATCH', '/v1/memories/hmem_1/records/a'), ...s.sent('PATCH', '/v1/memories/hmem_1/records/b')][0].body;
    expect(patched).toMatchObject({ references: [{ rel: 'related' }] });
  });
  test('labels read no relations, so no link is offered on a record', async () => {
    const a = record({ id: 'a', title: 'Alpha' });
    open({ provider: CAPS.hindsight, records: [a, record({ id: 'b', title: 'Beta' })], schema: { types: [] } });
    await draw('data');
    expect(button('Link a record')).toBeUndefined();
  });
});
