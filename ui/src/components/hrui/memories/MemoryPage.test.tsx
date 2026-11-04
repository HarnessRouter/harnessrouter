/** @jest-environment jsdom */
// One memory, and the rules that matter most: the capability document drives the page, never a vendor's name, and
// whatever changes in the memory while the page is open reaches it. The tree, the graph and the schema editor have
// their own tests; here they meet.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import * as Y from 'yjs';
import { CAPS, memory, record, service } from './fixtures';
import type { Memory, MemoryRecord, Provider } from '@/lib/memories';

jest.mock('next/navigation', () => ({ useRouter: () => ({ push: jest.fn(), replace: jest.fn() }) }));
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
jest.mock('./editor/DocEditor', () => ({ DocEditor: ({ readOnly }: { readOnly?: boolean }) => <div className="editor-stub" data-readonly={String(!!readOnly)} /> }));
jest.mock('./graph/MemoryGraph', () => ({
  MemoryGraph: (p: { activeRecordId: string; refreshKey: number; onOpenRecord: (r: string, m?: string) => void }) => (
    <button type="button" className="graph-stub" data-active={p.activeRecordId} data-tick={p.refreshKey} onClick={() => p.onOpenRecord('far', 'hmem_2')}>graph</button>
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
const tabs = () => Array.from(page().querySelectorAll('.ag-tabs [role=tab]')).map((t) => t.textContent);
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
async function draw(tab: string | null = null) {
  await act(async () => { root.render(<MemoryPage id="hmem_1" tabParam={tab} recordParam={null} onTab={() => {}} />); });
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

describe('the schema is always somewhere to go, and says what this provider does with it', () => {
  test('a provider that decides for itself still has the tab, and nothing asks it for a schema', async () => {
    const s = open({ provider: CAPS.mem0, records: [record()] });
    await draw('schema');
    expect(tabs()).toEqual(['Schema', 'Data']);
    expect(page().querySelector('.schema-stub')?.getAttribute('data-mode')).toBe('none');
    expect(s.sent('GET', '/v1/memories/hmem_1/schema')).toHaveLength(0);
  });
  test('one that a schema guides is called Schema', async () => {
    const s = open({ provider: CAPS.graphiti, records: [record()] });
    await draw('schema');
    expect(tabs()).toEqual(['Schema', 'Data']);
    expect(page().querySelector('.schema-stub')?.getAttribute('data-mode')).toBe('guides');
    expect(s.sent('GET', '/v1/memories/hmem_1/schema').length).toBeGreaterThan(0);
  });
  test('one that applies labels is called Labels', async () => {
    open({ provider: CAPS.hindsight, records: [record()], schema: { types: [{ name: 'Company' }] } });
    await draw('labels');
    expect(tabs()).toEqual(['Labels', 'Data']);
    expect(page().querySelector('.schema-stub')?.getAttribute('data-mode')).toBe('labels');
  });
  test('with nothing in it, a memory a schema guides opens on its schema; one that decides for itself on its data', async () => {
    open({ provider: CAPS.graphiti, memory: memory({ provider: 'graphiti', records: { count: 0 } }), records: [] });
    await draw();
    expect(page().querySelector('.schema-stub')).toBeTruthy();
    await act(async () => { root.unmount(); }); root = createRoot(el);
    open({ provider: CAPS.mem0, memory: memory({ provider: 'mem0', records: { count: 0 } }), records: [] });
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

describe('three columns: everything it holds, the open record, and the graph', () => {
  test('all three are on the page, each by its own name', async () => {
    open({ provider: CAPS.mem0, records: [record({ id: 'r', title: 'Mine' })] });
    await draw();
    expect(page().querySelector('.rc')).toBeTruthy();
    expect(page().querySelector('.mt, .mm-tree, [role=tree]')).toBeTruthy();
    expect(page().querySelector('.mm-doc .editor-stub')).toBeTruthy();
    expect(page().querySelector('.graph-stub')?.getAttribute('data-active')).toBe('r');
  });
  test('a record in another memory, reached from the graph, opens on that memory', async () => {
    open({ provider: CAPS.mem0, records: [record({ id: 'r', title: 'Mine' })] });
    await draw();
    await click(page().querySelector('.graph-stub'));
    expect(page().querySelector('.graph-stub')?.getAttribute('data-active')).toBe('r');
  });
});

describe('a derived record', () => {
  const found = (o: Partial<MemoryRecord> = {}) => record({ id: 'd', type: 'fact', title: 'Acme uses Slack', written_by: { kind: 'provider', id: 'graphiti' }, ...o });
  test('reads as found and cannot be edited', async () => {
    open({ provider: CAPS.graphiti, records: [found()] });
    await draw('data');
    expect(page().textContent).toContain('Found by Graphiti');
    expect(editable()).toBeNull();
    expect(editorReadOnly()).toBe('true');
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
    const f = found({ title: '', content: [{ type: 'text', text: 'Dana reports to Sam at Acme.' }], attributes: { predicate: 'RELATES_TO' }, references: [] });
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
  test('reading only: nothing that writes is offered, and the live document agrees', async () => {
    open({ provider: CAPS.graphiti, memory: memory({ provider: 'graphiti', privileges: ['read'] }), records: [mine] });
    await draw('data');
    expect(editable()).toBeNull();
    expect(editorReadOnly()).toBe('true');
    expect(page().querySelector('.mm-doc-bar button[aria-label="More"]')).toBeNull();
    await click(page().querySelector('.mm-page .ag-bar button[aria-label="More"]'));
    expect(Array.from(page().querySelectorAll('.ag-bar .mm-mi b')).map((b) => b.textContent)).toEqual(['Copy memory ID']);
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
  test('none kept and none to show: the list goes and the graph stays, which still draws the records', async () => {
    open({ provider: { ...CAPS.mem0, graph: { entities: 'none' } }, records: [record({ id: 'r' })] });
    await draw();
    expect(page().querySelector('.mm-linksbox')).toBeNull();
    expect(page().querySelector('.graph-stub')).toBeTruthy();
  });
  test('a provider with no links at all isn’t asked what a record links to', async () => {
    const { graph: _g, ...rest } = CAPS.mem0;
    const s = open({ provider: rest as Provider, records: [record({ id: 'r' })] });
    await draw();
    expect(page().querySelector('.mm-linksbox')).toBeNull();
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
    await click(button('Link a record'));
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
