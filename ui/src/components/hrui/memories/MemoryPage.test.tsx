/** @jest-environment jsdom */
// One memory, and the rules that matter most: the capability document drives the page, never a vendor's name, and
// whatever changes in the memory while the page is open reaches it. The tree, the graph and the schema editor have
// their own tests; here they meet.
import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import * as Y from 'yjs';
import { CAPS, memory, record, service } from './fixtures';
import type { Memory, MemoryRecord, Provider } from '@/lib/memories';

const mockRouter = { push: jest.fn(), replace: jest.fn() };
jest.mock('next/navigation', () => ({ useRouter: () => mockRouter }));
jest.mock('next/link', () => ({ __esModule: true, default: ({ children, href, className }: { children: React.ReactNode; href: string; className?: string }) => <a href={href} className={className}>{children}</a> }));
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
jest.mock('next/dynamic', () => ({
  __esModule: true,
  default: (load: () => Promise<React.ComponentType<Record<string, unknown>>>) => {
    const R = jest.requireActual('react') as typeof import('react');
    return function Dyn(props: Record<string, unknown>) {
      const [C, set] = R.useState<React.ComponentType<Record<string, unknown>> | null>(null);
      R.useEffect(() => { void load().then((c) => set(() => c)); }, []);
      return C ? R.createElement(C, props) : null;
    };
  },
}));
// the editor, drawn once it is clicked here (as the real one says when it is ready)
jest.mock('./editor/DocEditor', () => ({ DocEditor: ({ readOnly, onReady }: { readOnly?: boolean; onReady?: () => void }) => <div className="editor-stub" data-readonly={String(!!readOnly)} onClick={onReady} /> }));
// the graph, and the panel a record opens on it, which holds the record's links (linksFor)
jest.mock('./graph/MemoryGraph', () => ({
  MemoryGraph: (p: { activeRecordId: string; refreshKey: number; onOpenRecord: (r: string, m?: string) => void; linksFor?: (id: string) => ReactNode }) => (
    <div className="graph-panel-stub">
      <button type="button" className="graph-stub" data-active={p.activeRecordId} data-tick={p.refreshKey} onClick={() => p.onOpenRecord('far', 'hmem_2')}>graph</button>
      <button type="button" className="graph-here" onClick={() => p.onOpenRecord('r2')}>here</button>
      {p.linksFor ? p.linksFor(p.activeRecordId) : null}
    </div>
  ),
}));
jest.mock('./graph/SchemaEditor', () => ({
  SchemaEditor: (p: { ro: boolean; provider: Provider; onOpenData: (t: string) => void }) => <button type="button" className="schema-stub" data-ro={String(p.ro)} data-mode={p.provider.schema?.mode || 'none'} onClick={() => p.onOpenData('Company')}>schema</button>,
}));

import { harnessFetch } from '@/lib/hfetch';
import { MemoryPage } from './MemoryPage';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

// The two streams a page opens: the memory's events, and the open record's live document.
class FakeSource {
  static all: FakeSource[] = [];
  static canWrite = true;
  static docs = new Map<string, { title: string }>();
  static CLOSED = 2;
  readyState = 1;
  onerror: (() => void) | null = null;
  onopen: (() => void) | null = null;
  private on = new Map<string, ((e: { data: string }) => void)[]>();
  constructor(public url: string) {
    FakeSource.all.push(this);
    if (url.includes('/api/memlive/')) {
      const rid = decodeURIComponent(url.split('?')[0].split('/').pop() || '');
      queueMicrotask(() => this.hello(FakeSource.docs.get(rid)?.title ?? ''));
    }
  }
  addEventListener(k: string, f: (e: { data: string }) => void) { this.on.set(k, [...(this.on.get(k) || []), f]); }
  close() { this.readyState = 2; }
  emit(k: string, d: unknown) { (this.on.get(k) || []).forEach((f) => f({ data: JSON.stringify(d) })); }
  private hello(title: string) {
    const d = new Y.Doc();
    d.getText('title').insert(0, title);
    const b = (u: Uint8Array) => { let s = ''; u.forEach((x) => { s += String.fromCharCode(x); }); return btoa(s); };
    this.emit('hello', { epoch: 'one', state: b(Y.encodeStateAsUpdate(d)), sv: b(Y.encodeStateVector(new Y.Doc())), awareness: b(new Uint8Array([0])), version: 3, canWrite: FakeSource.canWrite, gone: false });
  }
}
const events = () => FakeSource.all.find((s) => s.url.includes('/events') && s.readyState === 1) as FakeSource;
const liveDoc = () => FakeSource.all.filter((s) => s.url.includes('/api/memlive/') && s.readyState === 1).pop() as FakeSource;

let root: Root; let el: HTMLElement;
const flush = async () => { for (let i = 0; i < 16; i++) await act(async () => { await Promise.resolve(); }); };
const page = () => document.getElementById('hrui') as HTMLElement;
const button = (t: string) => Array.from(page().querySelectorAll('button')).find((b) => (b.textContent || '').trim() === t) as HTMLButtonElement | undefined;
const byLabel = (t: string) => page().querySelector(`button[aria-label="${t}"]`) as HTMLButtonElement | null;
/** What the page's More menu offers, opened and read. */
async function moreItems(): Promise<string[]> {
  await click(page().querySelector('.mm-page .ag-bar button[aria-label="More"]'));
  return Array.from(page().querySelectorAll('.ag-bar .mm-mi b')).map((b) => b.textContent || '');
}
async function fromMore(t: string) {
  if (!page().querySelector('.ag-bar .mm-pop')) await click(page().querySelector('.mm-page .ag-bar button[aria-label="More"]'));
  await click(Array.from(page().querySelectorAll('.ag-bar .mm-mi')).find((b) => b.querySelector('b')?.textContent === t));
}
/** A record that links to another: what makes the graph take its column. */
const linking = (o: Partial<MemoryRecord> = {}) => record({ references: [{ rel: 'about', record_id: 'zz', available: true }], ...o });
async function click(b: Element | null | undefined) {
  if (!b) throw new Error(`nothing to click: ${page().textContent}`);
  await act(async () => { (b as HTMLElement).click(); });
  await flush();
}
const editable = () => page().querySelector('.mm-doc [contenteditable="plaintext-only"]');
const editorReadOnly = () => page().querySelector('.editor-stub')?.getAttribute('data-readonly');

function open(o: { provider: Provider; memory?: Memory; records?: MemoryRecord[]; schema?: unknown; graph?: unknown; extra?: Record<string, unknown> }) {
  const m = o.memory || memory({ provider: o.provider.id });
  FakeSource.canWrite = !!m.privileges?.includes('write');
  FakeSource.docs = new Map((o.records || []).map((r) => [r.id, { title: r.title }]));
  const s = service({
    'GET /v1/memories/providers': { data: [o.provider] },
    'GET /v1/memories/hmem_1': m,
    'GET /v1/memories/hmem_1/grants': { data: [] },
    'GET /v1/memories/hmem_1/records': { data: o.records || [], next: null },
    'GET /v1/memories/hmem_1/schema': o.schema || { types: [], relations: [] },
    'POST /v1/memories/hmem_1/graph': o.graph || { nodes: [], edges: [], truncated: false, degraded: [] },
    ...o.extra,
  });
  (harnessFetch as jest.Mock).mockImplementation(s.fetcher);
  return s;
}
const onTab = jest.fn();
async function draw(tab: string | null = null, rec: string | null = null) {
  await act(async () => { root.render(<MemoryPage id="hmem_1" tabParam={tab} recordParam={rec} onTab={onTab} />); });
  await flush();
}
beforeEach(() => {
  el = document.createElement('div'); el.id = 'hrui';
  document.body.appendChild(el);
  Object.assign(globalThis, { EventSource: FakeSource, fetch: jest.fn(async () => ({ ok: true, status: 204 })) });
  if (!globalThis.crypto) Object.assign(globalThis, { crypto: {} });
  if (!globalThis.crypto.getRandomValues) Object.assign(globalThis.crypto, { getRandomValues: (a: Uint8Array) => a.fill(7) });
  FakeSource.all = [];
  root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); el.remove(); jest.clearAllMocks(); });

describe('data comes first; the schema is under More, and says what this provider does with it', () => {
  test('there are no tabs: the page is its data, and Schema is in More', async () => {
    open({ provider: CAPS.graphiti, records: [record()] });
    await draw();
    expect(page().querySelector('.ag-tabs')).toBeNull();
    expect(page().querySelector('.mm-data')).toBeTruthy();
    expect(await moreItems()).toEqual(['Schema', 'Show graph', 'Copy memory ID', 'Rename and describe', 'Delete memory']);
    await fromMore('Schema');
    expect(onTab).toHaveBeenCalledWith('schema');
  });
  test('a provider that decides for itself still has its schema, and nothing asks it for one', async () => {
    const s = open({ provider: CAPS.mem0, records: [record()] });
    await draw('schema');
    expect(page().querySelector('.schema-stub')?.getAttribute('data-mode')).toBe('none');
    expect(s.sent('GET', '/v1/memories/hmem_1/schema')).toHaveLength(0);
    await click(button('Back to data'));
    expect(onTab).toHaveBeenCalledWith('data');
  });
  test('one that a schema guides is called Schema', async () => {
    const s = open({ provider: CAPS.graphiti, records: [record()] });
    await draw('schema');
    expect(page().querySelector('.schema-stub')?.getAttribute('data-mode')).toBe('guides');
    expect(s.sent('GET', '/v1/memories/hmem_1/schema').length).toBeGreaterThan(0);
  });
  test('one that applies labels calls it Labels in More, and shows what the provider makes beside them', async () => {
    open({ provider: CAPS.hindsight, records: [record()], schema: { types: [{ name: 'Company' }] } });
    await draw();
    expect((await moreItems())[0]).toBe('Labels');
    await act(async () => { root.unmount(); }); root = createRoot(el);
    open({ provider: CAPS.hindsight, records: [record()], schema: { types: [{ name: 'Company' }] } });
    await draw('labels');
    expect(page().querySelector('.schema-stub')?.getAttribute('data-mode')).toBe('labels');
  });
  test('with nothing in it, a memory opens on its data whatever guides it (Richard 11-09: schema is not the first thing)', async () => {
    open({ provider: CAPS.graphiti, memory: memory({ provider: 'graphiti', records: { count: 0 } }), records: [] });
    await draw();
    expect(page().querySelector('.schema-stub')).toBeNull();
    expect(page().querySelector('.mm-data')).toBeTruthy();
  });
  test('someone who may only read can look, and the editor is told', async () => {
    open({ provider: CAPS.graphiti, memory: memory({ provider: 'graphiti', privileges: ['read'] }), records: [record()] });
    await draw('schema');
    expect(page().querySelector('.schema-stub')?.getAttribute('data-ro')).toBe('true');
  });
});

describe('the columns: everything it holds, the open record, and the graph where records link', () => {
  test('where records link, all three are on the page, each by its own name', async () => {
    open({ provider: CAPS.mem0, records: [linking({ id: 'r', title: 'Mine' })] });
    await draw();
    expect(page().querySelector('.rc')).toBeTruthy();
    expect(page().querySelector('.mt, .mm-tree, [role=tree]')).toBeTruthy();
    expect(page().querySelector('.mm-doc .editor-stub')).toBeTruthy();
    expect(page().querySelector('.graph-stub')?.getAttribute('data-active')).toBe('r');
  });
  test('where nothing links, the record takes the graph’s room, and More brings the graph back when asked', async () => {
    open({ provider: CAPS.mem0, records: [record({ id: 'r', title: 'Mine' })] });
    await draw();
    expect(page().querySelector('.graph-stub')).toBeNull();
    expect(page().querySelector('.mm-doc .editor-stub')).toBeTruthy();
    await fromMore('Show graph');
    expect(page().querySelector('.graph-stub')?.getAttribute('data-active')).toBe('r');
    await fromMore('Hide graph');
    expect(page().querySelector('.graph-stub')).toBeNull();
  });
  test('an engine that finds people and things still shows no graph until something links (Richard 11-09)', async () => {
    open({ provider: CAPS.graphiti, records: [record({ id: 'r', title: 'Mine' })] });
    await draw();
    expect(page().querySelector('.graph-stub')).toBeNull();
    await act(async () => { root.unmount(); }); root = createRoot(el);
    open({ provider: CAPS.graphiti, records: [linking({ id: 'r', title: 'Mine' })] });
    await draw();
    expect(page().querySelector('.graph-stub')).toBeTruthy();
  });
  test('a record in another memory, reached from the graph, opens on that memory', async () => {
    open({ provider: CAPS.mem0, records: [linking({ id: 'r', title: 'Mine' })] });
    await draw();
    await click(page().querySelector('.graph-stub'));
    expect(page().querySelector('.graph-stub')?.getAttribute('data-active')).toBe('r');
  });
});

describe('narrow: the columns are tabs', () => {
  const wide = Element.prototype.getBoundingClientRect;
  beforeEach(() => { Element.prototype.getBoundingClientRect = () => ({ width: 390, height: 800, top: 0, left: 0, right: 390, bottom: 800, x: 0, y: 0, toJSON: () => ({}) }); });
  afterEach(() => { Element.prototype.getBoundingClientRect = wide; });
  test('a record picked on the graph opens in its panel there, and the graph stays (Richard 11-06)', async () => {
    open({ provider: CAPS.mem0, records: [linking({ id: 'r', title: 'Mine' }), linking({ id: 'r2', title: 'Other' })] });
    await draw();
    const tab = (id: string) => page().querySelector(`#rc-t-${id}`) as HTMLButtonElement;
    expect(tab('graph')).toBeTruthy();
    await click(tab('graph'));
    await click(page().querySelector('.graph-here'));
    expect(tab('graph').getAttribute('aria-selected')).toBe('true');
    expect(page().querySelector('.graph-stub')?.getAttribute('data-active')).toBe('r2');
  });
});

describe('a derived record', () => {
  const found = (o: Partial<MemoryRecord> = {}) => record({ id: 'd', type: 'fact', title: 'Acme uses Slack', written_by: { kind: 'provider', id: 'graphiti' }, ...o });
  test('reads as found, under Details, and cannot be edited', async () => {
    open({ provider: CAPS.graphiti, records: [found()] });
    await draw('data');
    expect(page().querySelector('.mm-details')?.textContent).toContain('Found by Graphiti');
    expect(editable()).toBeNull();
    expect(editorReadOnly()).toBe('true');
  });
  test('an agent this workspace cannot name reads as an agent, never as its id', async () => {
    open({ provider: CAPS.graphiti, records: [found({ written_by: { kind: 'member', id: 'chrn_elsewhere', type: 'agent' } })] });
    await draw('data');
    expect(page().textContent).toContain('An agent');
    expect(page().textContent).not.toContain('chrn_elsewhere');
  });
  test('a word in `revise` speaks of what a writer stated, so it stays read only', async () => {
    open({ provider: { ...CAPS.graphiti, revise: 'native' }, records: [found()] });
    await draw('data');
    expect(editable()).toBeNull();
    expect(editorReadOnly()).toBe('true');
  });
  test('is open only where `revise` says otherwise', async () => {
    open({ provider: { ...CAPS.graphiti, revise: { derived: true } }, records: [found()] });
    await draw('data');
    expect(editable()).toBeTruthy();
    expect(editorReadOnly()).toBe('false');
    expect(page().textContent).not.toContain('Read only');
  });
  test('a record a person wrote stays open on the same provider', async () => {
    open({ provider: CAPS.graphiti, records: [record({ id: 'w', title: 'Mine' })] });
    await draw('data');
    expect(editable()).toBeTruthy();
    expect(editable()?.textContent).toBe('Mine');
  });
  test('a fact with no title leads with its text, its word comes second, and RELATES_TO reads as related to', async () => {
    const f = found({ title: '', content: [{ type: 'text', text: 'Dana reports to Sam at Acme.' }], attributes: { predicate: 'RELATES_TO' }, references: [{ rel: 'RELATES_TO', record_id: 'e', available: true }] });
    open({
      provider: CAPS.graphiti, records: [f],
      graph: {
        nodes: [{ record: f, memory: { id: 'hmem_1', name: 'Brand kits' } }, { record: found({ id: 'e', type: 'entity', title: 'Acme', content: [], attributes: {} }), memory: { id: 'hmem_1', name: 'Brand kits' } }],
        edges: [{ from: { memory_id: 'hmem_1', record_id: 'd' }, to: { memory_id: 'hmem_1', record_id: 'e' }, rel: 'RELATES_TO', available: true }], truncated: false, degraded: [],
      },
    });
    await draw('data');
    expect((page().querySelector('.mm-doc-col') as HTMLElement).firstElementChild?.className).toContain('mm-live');
    expect(page().querySelector('.mm-pred')?.textContent).toBe('related to');
    expect(page().querySelector('.mm-lrel')?.textContent).toContain('related to');
    expect(page().textContent).not.toContain('RELATES_TO');
  });
  test('each fact shows its labels', async () => {
    const f = record({ id: 'f1', type: 'fact', title: '', content: [{ type: 'text', text: 'Acme signed up.' }], attributes: { labels: ['Company', 'Big_deal'] }, written_by: { kind: 'provider', id: 'hindsight' } });
    open({ provider: CAPS.hindsight, schema: { types: [{ name: 'Company' }] }, records: [f] });
    await draw('data');
    expect(Array.from(page().querySelectorAll('.mm-lab')).map((x) => x.textContent)).toEqual(['Company', 'Big deal']);
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
    expect(editable()).toBeNull();
    expect(editorReadOnly()).toBe('true');
  });
  test('an episode is what happened: not edited and not forgotten; an entity the provider derives is not forgotten either', async () => {
    const ep = record({ id: 'ep', type: 'episode', title: 'Task', written_by: { kind: 'provider', id: 'graphiti' } });
    open({ provider: CAPS.graphiti, records: [ep] });
    await draw('data', 'ep');
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
  test('reading only: nothing that writes is offered, and the live document agrees', async () => {
    open({ provider: CAPS.graphiti, memory: memory({ provider: 'graphiti', privileges: ['read'] }), records: [mine] });
    await draw('data');
    expect(editable()).toBeNull();
    expect(editorReadOnly()).toBe('true');
    expect(page().querySelector('.mm-doc-bar button[aria-label="More"]')).toBeNull();
    expect(await moreItems()).toEqual(['Schema', 'Show graph', 'Copy memory ID']);
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

describe('links', () => {
  test('none kept and none to show: no list and no graph, and More doesn’t offer one', async () => {
    open({ provider: { ...CAPS.mem0, graph: { entities: 'none' } }, records: [record({ id: 'r' })] });
    await draw();
    expect(page().querySelector('.mm-clist')).toBeNull();
    expect(page().querySelector('.graph-stub')).toBeNull();
    expect(await moreItems()).not.toContain('Show graph');
  });
  test('a provider with no links at all isn’t asked what a record links to', async () => {
    const { graph: _g, ...rest } = CAPS.mem0;
    const s = open({ provider: rest as Provider, records: [record({ id: 'r' })] });
    await draw();
    expect(page().querySelector('.mm-clist')).toBeNull();
    expect(s.sent('POST', '/v1/memories/hmem_1/graph')).toHaveLength(0);
  });
  test('one that keeps stated links: a link can be made with a word of your own', async () => {
    const a = record({ id: 'a', title: 'Alpha' }), b = record({ id: 'b', title: 'Beta' });
    const s = open({
      provider: CAPS.mem0, records: [a, b],
      graph: { nodes: [{ record: a, memory: { id: 'hmem_1', name: 'x' } }], edges: [], truncated: false, degraded: [] },
      extra: { 'PATCH /v1/memories/hmem_1/records/a': a, 'PATCH /v1/memories/hmem_1/records/b': b },
    });
    await draw();
    // nothing links yet, so the graph (where links are made) is asked for
    await fromMore('Show graph');
    await click(button('Link a record'));
    await click(button('Link'));
    const patched = [...s.sent('PATCH', '/v1/memories/hmem_1/records/a'), ...s.sent('PATCH', '/v1/memories/hmem_1/records/b')][0].body;
    expect(patched).toMatchObject({ references: [{ rel: 'related' }] });
  });
  test('a schema that relates this type to nothing still lets a person link it, in a word of their own', async () => {
    const a = record({ id: 'a', title: 'Alpha' }), b = record({ id: 'b', title: 'Beta' });
    const s = open({
      provider: CAPS.graphiti, records: [a, b], schema: { types: [], relations: [] },
      graph: { nodes: [{ record: a, memory: { id: 'hmem_1', name: 'x' } }], edges: [], truncated: false, degraded: [] },
      extra: { 'PATCH /v1/memories/hmem_1/records/a': a, 'PATCH /v1/memories/hmem_1/records/b': b },
    });
    await draw('data');
    expect(page().textContent).not.toContain('no relations in the schema');
    await fromMore('Show graph');
    await click(button('Link a record'));
    expect(page().querySelector('input[aria-label="How they relate"]')).toBeTruthy();
    await click(button('Link'));
    const patched = [...s.sent('PATCH', '/v1/memories/hmem_1/records/a'), ...s.sent('PATCH', '/v1/memories/hmem_1/records/b')][0].body;
    expect(patched).toMatchObject({ references: [{ rel: 'related' }] });
  });
  test('labels read no relations, so no link is offered on a record', async () => {
    open({ provider: CAPS.hindsight, records: [record({ id: 'a', title: 'Alpha' }), record({ id: 'b', title: 'Beta' })], schema: { types: [] } });
    await draw('data');
    expect(button('Link a record')).toBeUndefined();
  });
});

describe('what changes while the page is open', () => {
  const mine = record({ id: 'r', title: 'Mine' });
  const tell = async (type: string, d: object) => { await act(async () => { events().emit(type, { type, ...d }); }); await flush(); };
  test('a revision by anyone reaches the list and the graph, read under this person’s privileges', async () => {
    const s = open({ provider: CAPS.mem0, records: [mine, record({ id: 'o', title: 'Other' })], extra: { 'GET /v1/memories/hmem_1/records/o': record({ id: 'o', title: 'Other, as the agent left it', version: 2 }) } });
    await draw();
    const before = Number(page().querySelector('.graph-stub')?.getAttribute('data-tick'));
    expect(page().textContent).not.toContain('as the agent left it');
    await tell('record.revised', { record_id: 'o', version: 2, written_by: { kind: 'member', id: 'chrn_a', type: 'agent' } });
    expect(s.sent('GET', '/v1/memories/hmem_1/records/o')).toHaveLength(1);
    expect(page().textContent).toContain('Other, as the agent left it');
    expect(Number(page().querySelector('.graph-stub')?.getAttribute('data-tick'))).toBe(before + 1);
  });
  test('a new record arrives, a forgotten one goes', async () => {
    open({ provider: CAPS.mem0, records: [mine], extra: { 'GET /v1/memories/hmem_1/records/n': record({ id: 'n', title: 'Just written' }) } });
    await draw();
    await tell('record.created', { record_id: 'n', version: 1 });
    expect(page().querySelector('[role=tree]')?.textContent).toContain('Just written');
    await tell('record.forgotten', { record_id: 'n' });
    expect(page().querySelector('[role=tree]')?.textContent).not.toContain('Just written');
  });
  test('told to read everything again, it does', async () => {
    const s = open({ provider: CAPS.mem0, records: [mine] });
    await draw();
    const n = s.sent('GET', '/v1/memories/hmem_1/records').length;
    await tell('reset', {});
    expect(s.sent('GET', '/v1/memories/hmem_1/records').length).toBeGreaterThan(n);
  });
  test('a schema someone else changed is read again', async () => {
    const s = open({ provider: CAPS.graphiti, records: [mine] });
    await draw('schema');
    const n = s.sent('GET', '/v1/memories/hmem_1/schema').length;
    await tell('schema.changed', {});
    expect(s.sent('GET', '/v1/memories/hmem_1/schema').length).toBeGreaterThan(n);
  });
  test('the open record says how saving is going, and a refusal in words', async () => {
    open({ provider: CAPS.mem0, records: [mine] });
    await draw();
    const bar = () => page().querySelector('.mm-saved')?.textContent;
    expect(bar()).toBe('Saved · v3');
    await act(async () => { liveDoc().emit('saving', {}); });
    expect(bar()).toBe('Saving…');
    await act(async () => { liveDoc().emit('saved', { version: 4 }); });
    expect(bar()).toBe('Saved · v4');
    await act(async () => { liveDoc().emit('refused', { message: 'A title is one line.' }); });
    expect(bar()).toBe('Not saved');
    expect(page().querySelector('.mm-err')?.textContent).toBe('A title is one line.');
  });
  test('a record forgotten while it’s open stops being editable and says so', async () => {
    open({ provider: CAPS.mem0, records: [mine] });
    await draw();
    expect(editorReadOnly()).toBe('false');
    await act(async () => { liveDoc().emit('gone', {}); });
    await flush();
    expect(editorReadOnly()).toBe('true');
    expect(page().textContent).toContain('This record was forgotten.');
  });
  test('losing the right to write while it’s open takes effect at once', async () => {
    open({ provider: CAPS.mem0, records: [mine] });
    await draw();
    await act(async () => { liveDoc().emit('access', { canWrite: false }); });
    await flush();
    expect(editable()).toBeNull();
    expect(editorReadOnly()).toBe('true');
  });
});

describe('a record reads as what it says', () => {
  test('the engine’s fields (the task, the model, the kind) are under Details, not on the record', async () => {
    const f = record({ id: 'f', type: 'fact', title: '', content: [{ type: 'text', text: 'Dana prefers written steps.' }], attributes: { session_id: 'hsess_1', model: 'm-5', kind: 'turn' } });
    open({ provider: CAPS.mem0, records: [f] });
    await draw();
    const props = page().querySelector('.mm-doc-col > .mm-props') as HTMLElement;
    expect(props.textContent).not.toMatch(/session_id|hsess_1|kind/);
    const details = page().querySelector('.mm-details') as HTMLDetailsElement;
    expect(details.querySelector('summary')?.textContent).toBe('Details');
    expect(details.textContent).toContain('session_id');
    expect(details.textContent).toContain('hsess_1');
  });
  test('it opens on the most recent record that says something, never on a role’s bare name or an episode', async () => {
    const at = (d: string) => ({ valid_from: null, valid_to: null, written_at: d, invalidated_at: null });
    open({
      provider: CAPS.mem0,
      records: [
        record({ id: 'old', title: 'Dana is on the Team plan', time: at('2026-11-01T00:00:00Z') }),
        record({ id: 'new', title: 'Dana prefers written steps', time: at('2026-11-05T00:00:00Z') }),
        record({ id: 'u', type: 'entity', title: 'user', time: at('2026-11-07T00:00:00Z') }),
        record({ id: 'ep', type: 'episode', title: 'A whole task', time: at('2026-11-08T00:00:00Z') }),
      ],
    });
    await draw();
    expect(page().querySelector('.mm-doc-col .mm-title')?.textContent).toBe('Dana prefers written steps');
  });
  test('with nothing worth opening, nothing is open', async () => {
    open({ provider: CAPS.mem0, records: [record({ id: 'u', type: 'entity', title: 'user' })] });
    await draw();
    expect(page().textContent).toContain('Pick a record');
  });
});

describe('who uses it', () => {
  const contract = (o: Partial<Memory> = {}) => memory({ provider: 'mem0', engine: 'mem0', used_by: [], ...o });
  test('nothing uses it yet: Use in gives it to a setup, which then remembers there', async () => {
    const s = open({ provider: CAPS.mem0, memory: contract(), records: [record()], extra: { 'PUT /v1/harnesses/chrn_a/memory': { id: 'chrn_a', memory: { id: 'hmem_1', name: 'Brand kits', engine: 'mem0', scope: 'shared', reason: '' } } } });
    await draw();
    expect(button('Not used yet')).toBeUndefined();
    await click(button('Use in…'));
    expect(page().querySelector('#mmUse')?.textContent).toBe('Use Brand kits in…');
    await click(button('Use here'));
    expect(s.sent('PUT', '/v1/harnesses/chrn_a/memory')[0].body).toEqual({ memory: { id: 'hmem_1' } });
  });
  test('a service before 0.40 says nothing of it: no Use in, the old way stays', async () => {
    open({ provider: CAPS.mem0, records: [record()] });
    await draw();
    expect(button('Use in…')).toBeUndefined();
    expect(button('Not used yet')).toBeTruthy();
  });
  test('the last thing that failed is said until something works again', async () => {
    open({ provider: CAPS.mem0, memory: contract({ last_error: 'Mem0 could not pull facts out: it has no model key.', last_error_at: '2026-11-08T10:00:00Z', last_ok_at: '2026-11-08T09:00:00Z' }), records: [record()] });
    await draw();
    expect(page().querySelector('.mm-failing')?.textContent).toContain('it has no model key');
    await act(async () => { root.unmount(); }); root = createRoot(el);
    open({ provider: CAPS.mem0, memory: contract({ last_error: 'Old trouble.', last_error_at: '2026-11-08T09:00:00Z', last_ok_at: '2026-11-08T10:00:00Z' }), records: [record()] });
    await draw();
    expect(page().querySelector('.mm-failing')).toBeNull();
  });
});

describe('finding in it', () => {
  test('words are asked of the engine by meaning, and what it finds is listed with what matches the words', async () => {
    const said = record({ id: 'p', title: 'Prefers written steps, no phone calls' });
    const s = open({ provider: CAPS.mem0, records: [said, record({ id: 'q', title: 'On the Team plan' })],
      extra: { 'POST /v1/memories/hmem_1/recall': { results: [{ record: said, score: 0.8 }], degraded: [] } } });
    jest.useFakeTimers();
    try {
      await draw();
      const box = page().querySelector('.mt-top input') as HTMLInputElement;
      const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
      await act(async () => { set.call(box, 'how does she like help'); box.dispatchEvent(new Event('input', { bubbles: true })); });
      await act(async () => { jest.advanceTimersByTime(400); });
    } finally { jest.useRealTimers(); }
    await flush();
    expect(s.sent('POST', '/v1/memories/hmem_1/recall')[0].body).toEqual({ query: 'how does she like help', limit: 50 });
    const tree = page().querySelector('[role=tree]')?.textContent || '';
    expect(tree).toContain('Prefers written steps');
    expect(tree).not.toContain('On the Team plan');
  });
});

// An agent's memory that keeps each person apart (the polish round, C1, C2, C8, C9): it holds nothing itself, and each
// person's records are in their own memory below it.
describe('an agent’s memory that keeps each person apart', () => {
  const agent = () => memory({ provider: 'mem0', engine: 'mem0', records: { count: 0 }, children: { count: 1 }, used_by: [{ harness_id: 'chrn_a', name: 'Photo cut' }] });
  const person = (o: Partial<Memory> = {}) => memory({ id: 'hmem_p', name: '5d41402abc4b2a76', end_user: 'local@localhost', provider: 'mem0', engine: 'mem0', parent_id: 'hmem_1', ancestors: ['hmem_1'],
    restricted: true, records: { count: 2 }, children: { count: 0 }, used_by: [], last_used_at: 1762650000000, ...o });
  const facts = [
    record({ id: 'f1', memory_id: 'hmem_p', type: 'fact', title: '', content: [{ type: 'text', text: 'User’s name is Dana' }], written_by: { kind: 'provider', id: 'mem0' } }),
    record({ id: 'f2', memory_id: 'hmem_p', type: 'fact', title: '', content: [{ type: 'text', text: 'User prefers email, never phone' }], written_by: { kind: 'provider', id: 'mem0' } }),
  ];
  const routes = (p = person()) => ({
    'GET /v1/memories': (c: { path: string }) => ({ data: c.path.includes('hmem_1') ? [p] : [] }),
    'GET /v1/memories/hmem_p': p,
    'GET /v1/memories/hmem_p/grants': { data: [] },
    'GET /v1/memories/hmem_p/records': { data: facts, next: null },
    'GET /v1/memories/hmem_p/records/f2': facts[1],
    'GET /v1/memories/hmem_p/schema': { types: [], relations: [] },
  });
  const row = (t: string) => Array.from(page().querySelectorAll<HTMLElement>('[role=treeitem]')).find((r) => r.querySelector('.mt-lbl')?.textContent === t);

  test('with its people’s records below it, it never says nothing is kept; the console’s own person reads as you', async () => {
    open({ provider: CAPS.mem0, memory: agent(), records: [], extra: routes() });
    await draw();
    expect(page().querySelector('.mm-doc-empty h2')?.textContent).toBe('Pick a record');
    expect(page().querySelector('.mm-doc-empty')?.textContent).toContain('under their name');
    expect(page().textContent).not.toContain('Nothing kept yet');
    expect(row('You (this console)')).toBeTruthy();
    expect(page().textContent).not.toContain('local@localhost');
  });
  test('truly empty below too: then it says so', async () => {
    open({ provider: CAPS.mem0, memory: agent(), records: [], extra: routes(person({ records: { count: 0 } })) });
    await draw();
    expect(page().querySelector('.mm-doc-empty h2')?.textContent).toBe('Nothing kept yet');
  });
  test('a person’s record opens here, in their memory, under "agent’s memory › person"', async () => {
    open({ provider: CAPS.mem0, memory: agent(), records: [], extra: routes() });
    await draw();
    await click(row('You (this console)'));
    await click(row('User prefers email, never phone'));
    // still this memory's page: its own name on top, and where the record is said above it
    expect(page().querySelector('.ag-name')?.textContent).toBe('Brand kits');
    const crumbs = page().querySelector('.mm-crumbs.has-up');
    expect(Array.from(crumbs?.querySelectorAll('.mm-cr') || []).map((c) => c.textContent)).toEqual(['Brand kits', 'You (this console)']);
    // the record itself, live, in the person's memory
    expect(liveDoc().url.split('?')[0]).toBe('/api/memlive/hmem_p/f2');
  });
  test('a link to a person’s record (?in=) opens it on the agent’s memory', async () => {
    open({ provider: CAPS.mem0, memory: agent(), records: [], extra: routes() });
    await act(async () => { root.render(<MemoryPage id="hmem_1" tabParam="data" recordParam="f2" inParam="hmem_p" onTab={onTab} />); });
    await flush();
    expect(page().querySelector('.mm-crumbs.has-up')?.textContent).toContain('You (this console)');
    expect(liveDoc().url.split('?')[0]).toBe('/api/memlive/hmem_p/f2');
  });
  test('a person’s own page: Back is the agent’s memory, used by whoever uses it, and when this person’s was last used', async () => {
    const s = service({
      'GET /v1/memories/providers': { data: [CAPS.mem0] },
      'GET /v1/memories/hmem_1': agent(),
      ...routes(),
    });
    (harnessFetch as jest.Mock).mockImplementation(s.fetcher);
    await act(async () => { root.render(<MemoryPage id="hmem_p" tabParam={null} recordParam={null} onTab={onTab} />); });
    await flush();
    expect(page().querySelector('.ag-name')?.textContent).toBe('You (this console)');
    expect(page().querySelector('.ag-back')?.getAttribute('href')).toBe('/memories/hmem_1?tab=data');
    expect(page().querySelector('.mm-up')?.textContent).toBe('Brand kits·Used 2 d ago');
    expect(button('Used by 1 setup')).toBeTruthy();
    expect(button('Not used yet')).toBeUndefined();
  });
  test('on a phone, a person’s record shows what the list said of it at once, and its address names their memory', async () => {
    const wide = Element.prototype.getBoundingClientRect;
    Element.prototype.getBoundingClientRect = () => ({ width: 390, height: 800, top: 0, left: 0, right: 390, bottom: 800, x: 0, y: 0, toJSON: () => ({}) });
    // the person's memory is read slowly (a phone, 11-09: "Opening…" 2.5 s after the tap)
    let release: () => void = () => {};
    const slow = new Promise<void>((r) => { release = r; });
    try {
      open({ provider: CAPS.mem0, memory: agent(), records: [], extra: { ...routes(), 'GET /v1/memories/hmem_p': () => slow.then(() => person()) } });
      await draw('data');
      await click(page().querySelector('#rc-t-tree'));
      // (the tree keeps a person's branch open from before)
      if (!row('User prefers email, never phone')) await click(row('You (this console)'));
      await click(row('User prefers email, never phone'));
      expect(mockRouter.push).toHaveBeenCalledWith('/memories/hmem_1?tab=data&in=hmem_p&record=f2', { scroll: false });
      const doc = page().querySelector('#rc-p-doc') as HTMLElement;
      expect(doc.querySelector('.mm-peek')?.textContent).toBe('User prefers email, never phone');
      expect(doc.querySelector('.mm-saved')?.textContent).toBe('Opening…');
      await act(async () => { release(); });
      await flush();
      expect(doc.querySelector('.mm-peek')).toBeNull();
      expect(doc.querySelector('.mm-crumbs.has-up')).toBeTruthy();
    } finally { Element.prototype.getBoundingClientRect = wide; }
  });
});

describe('a record open in the address (the final walkthrough, 11-09: a phone’s Back left the memory)', () => {
  const narrowRect = () => ({ width: 390, height: 800, top: 0, left: 0, right: 390, bottom: 800, x: 0, y: 0, toJSON: () => ({}) });
  const wide = Element.prototype.getBoundingClientRect;
  afterEach(() => { Element.prototype.getBoundingClientRect = wide; });
  const tab = (id: string) => page().querySelector(`#rc-t-${id}`) as HTMLButtonElement;
  const row = (t: string) => Array.from(page().querySelectorAll<HTMLElement>('[role=treeitem]')).find((r) => r.querySelector('.mt-lbl')?.textContent === t);
  /** the address as Next hands it to the page after a push, Back or Forward */
  const at = async (rec: string | null) => { await act(async () => { root.render(<MemoryPage id="hmem_1" tabParam="data" recordParam={rec} onTab={onTab} />); }); await flush(); };
  const two = () => open({ provider: CAPS.mem0, records: [record({ id: 'r', title: 'Mine' }), record({ id: 'r2', title: 'Other', content: [{ type: 'text', text: 'What the other says.' }] })] });

  test('on a phone, opening a record from the list is pushed: Back is the list, Forward the record again', async () => {
    Element.prototype.getBoundingClientRect = narrowRect;
    two();
    await draw('data');
    expect(tab('tree').getAttribute('aria-selected')).toBe('true');
    await click(row('Other'));
    expect(mockRouter.push).toHaveBeenCalledWith('/memories/hmem_1?tab=data&record=r2', { scroll: false });
    expect(mockRouter.replace).not.toHaveBeenCalled();
    expect(tab('doc').getAttribute('aria-selected')).toBe('true');
    await at('r2');
    expect(tab('doc').getAttribute('aria-selected')).toBe('true');
    // Back: the list, still in the memory
    await at(null);
    expect(tab('tree').getAttribute('aria-selected')).toBe('true');
    expect(page().querySelector('.ag-name')?.textContent).toBeTruthy();
    // Forward: the record
    await at('r2');
    expect(tab('doc').getAttribute('aria-selected')).toBe('true');
    expect(liveDoc().url.split('?')[0]).toBe('/api/memlive/hmem_1/r2');
  });
  test('on a phone, the Records tab after a pushed record is Back; the Record tab is pushed too', async () => {
    Element.prototype.getBoundingClientRect = narrowRect;
    const back = jest.spyOn(window.history, 'back').mockImplementation(() => {});
    try {
      two();
      await draw('data');
      await click(row('Other'));
      await at('r2');
      await click(tab('tree'));
      expect(back).toHaveBeenCalledTimes(1);
      expect(tab('tree').getAttribute('aria-selected')).toBe('true');
      await at(null);
      mockRouter.push.mockClear();
      await click(tab('doc'));
      expect(mockRouter.push).toHaveBeenCalledWith('/memories/hmem_1?tab=data&record=r2', { scroll: false });
    } finally { back.mockRestore(); }
  });
  test('side by side, picking a record follows in place: nothing to go Back through', async () => {
    two();
    await draw('data');
    await click(row('Other'));
    expect(mockRouter.replace).toHaveBeenCalledWith('/memories/hmem_1?tab=data&record=r2', { scroll: false });
    expect(mockRouter.push).not.toHaveBeenCalled();
  });
  test('the record’s own words show until the editor is drawn, never "Opening…"', async () => {
    two();
    await draw('data', 'r2');
    const doc = page().querySelector('.mm-doc') as HTMLElement;
    expect(doc.textContent).not.toContain('Opening…');
    expect(doc.querySelector('.mm-live .mm-ed-wait')?.textContent).toBe('What the other says.');
    expect((doc.querySelector('.mm-ed-box') as HTMLElement).hidden).toBe(true);
    await click(doc.querySelector('.editor-stub'));
    expect(doc.querySelector('.mm-ed-wait')).toBeNull();
    expect((doc.querySelector('.mm-ed-box') as HTMLElement).hidden).toBe(false);
  });
});

describe('narrow: it opens on the list, never on an empty record', () => {
  const wide = Element.prototype.getBoundingClientRect;
  beforeEach(() => { Element.prototype.getBoundingClientRect = () => ({ width: 390, height: 800, top: 0, left: 0, right: 390, bottom: 800, x: 0, y: 0, toJSON: () => ({}) }); });
  afterEach(() => { Element.prototype.getBoundingClientRect = wide; });
  const tab = (id: string) => page().querySelector(`#rc-t-${id}`) as HTMLButtonElement;
  test('nothing open: the Records tab', async () => {
    open({ provider: CAPS.mem0, memory: memory({ provider: 'mem0', records: { count: 0 }, children: { count: 1 } }), records: [],
      extra: { 'GET /v1/memories': { data: [memory({ id: 'hmem_p', parent_id: 'hmem_1', end_user: 'Dana', records: { count: 3 } })] } } });
    await draw();
    expect(tab('tree').getAttribute('aria-selected')).toBe('true');
    expect(tab('doc').getAttribute('aria-selected')).toBe('false');
  });
  test('sent to a record: that record', async () => {
    open({ provider: CAPS.mem0, records: [record({ id: 'r', title: 'Mine' })] });
    await draw('data', 'r');
    expect(tab('doc').getAttribute('aria-selected')).toBe('true');
  });
});
