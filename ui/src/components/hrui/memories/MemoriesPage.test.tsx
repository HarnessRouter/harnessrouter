/** @jest-environment jsdom */
// The Memories list, and New memory. Nothing connected leads to connecting (or finding the engines running here), in
// one sentence. A new memory takes a name and, if you like, a description; its engine is chosen from them, said with
// why, and can be changed to another connected engine. Each card names its engine, who uses it and when, where the
// service says. A refused connection says the engine's own words. Every figure on a card is the service's.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { Provider } from '@/lib/memories';
import { allProviders, CAPS, memory, service } from './fixtures';

const push = jest.fn();
jest.mock('next/navigation', () => ({ useRouter: () => ({ push, replace: jest.fn() }) }));
jest.mock('next/link', () => ({ __esModule: true, default: ({ children, href, className }: { children: React.ReactNode; href: string; className?: string }) => <a className={className} href={href}>{children}</a> }));
jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
jest.mock('../toast', () => ({ toast: jest.fn() }));
jest.mock('@/lib/harness', () => ({ gwHeaders: () => ({}), listCustom: jest.fn(async () => [{ id: 'chrn_a', name: 'Photo cut' }]), instructionFileLabel: () => 'AGENTS.md' }));
jest.mock('../setup/settingsModel', () => ({
  plain: (e: unknown, f: string) => (e instanceof Error && e.message ? e.message : f),
  plural: (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`,
}));

import { harnessFetch } from '@/lib/hfetch';
import { MemoriesPage } from './MemoriesPage';
import { toast } from '../toast';
import { CardArt } from './CardArt';
import { concepts } from './graph/builtin';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let root: Root; let el: HTMLElement;
const NONE = { mem0: false, graphiti: false, hindsight: false, reme: false };
const flush = async () => { for (let i = 0; i < 12; i++) await act(async () => { await Promise.resolve(); }); };
function backend(routes: Record<string, unknown>) {
  const s = service({ 'GET /v1/memories': { data: [] }, 'GET /v1/plugs': { plugs: [] }, ...routes });
  (harnessFetch as jest.Mock).mockImplementation(s.fetcher);
  return s;
}
async function open() { await act(async () => { root.render(<MemoriesPage />); }); await flush(); }
const page = () => document.getElementById('hrui') as HTMLElement;
const button = (t: string) => Array.from(page().querySelectorAll('button')).find((b) => (b.textContent || '').trim() === t) as HTMLButtonElement | undefined;
async function press(t: string) {
  const b = button(t);
  if (!b) throw new Error(`no button ${t}: ${page().textContent}`);
  await act(async () => { b.click(); });
  await flush();
}
async function type(sel: string, v: string) {
  const i = page().querySelector(sel) as HTMLInputElement;
  const set = Object.getOwnPropertyDescriptor(i.constructor.prototype, 'value')!.set!;
  await act(async () => { set.call(i, v); i.dispatchEvent(new Event('input', { bubbles: true })); });
}
beforeEach(() => {
  push.mockReset();
  window.history.replaceState(null, '', '/memories');
  el = document.createElement('div'); el.id = 'hrui';
  document.body.appendChild(el);
  root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); el.remove(); jest.clearAllMocks(); });

const more = async (t: string) => {
  await press_(page().querySelector('.mm-top button[aria-label="More"]') as HTMLElement);
  await press_(Array.from(page().querySelectorAll('.mm-top .mm-mi')).find((b) => b.querySelector('b')?.textContent === t) as HTMLElement);
};
async function press_(b: HTMLElement | null | undefined) {
  if (!b) throw new Error(`nothing to press: ${page().textContent}`);
  await act(async () => { b.click(); });
  await flush();
}

describe('nothing connected', () => {
  test('the page explains in one sentence and leads to connecting, or to finding the engines running here', async () => {
    backend({ 'GET /v1/memories/providers': { data: allProviders(NONE) } });
    await open();
    expect(page().querySelector('.mm-empty-list h2')?.textContent).toBe('Connect a memory engine');
    expect(page().querySelectorAll('.mm-empty-list p')).toHaveLength(1);
    expect(button('New memory')).toBeUndefined();
    expect(button('Find engines')).toBeTruthy();
    await press('Connect an engine');
    const offered = Array.from(page().querySelectorAll('.mm-pv-o b')).map((b) => b.textContent);
    expect(offered).toEqual(['Mem0', 'Graphiti', 'Hindsight', 'ReMe']);
    expect(page().textContent).toContain('Plain Markdown files you can read and edit.');
    expect(page().querySelectorAll('.mm-pv-o .btn')).toHaveLength(4);
  });

  test('connecting sends the address and key, shows a refusal in the engine’s words, then goes on to New memory', async () => {
    let refuse = true;
    const s = backend({
      'GET /v1/memories/providers': () => ({ data: allProviders(refuse ? NONE : { ...NONE, graphiti: true }) }),
      'PUT /v1/plugs/graphiti': () => (refuse ? { $status: 422, error: { code: 'memory_invalid', message: 'That address did not answer.' } } : { type: 'graphiti' }),
    });
    await open();
    await press('Connect an engine');
    await act(async () => { (Array.from(page().querySelectorAll('.mm-pv-o')).find((o) => o.textContent?.includes('Graphiti'))!.querySelector('button') as HTMLButtonElement).click(); });
    await flush();
    // an address is required here
    expect((page().querySelector('.sheet button[type=submit]') as HTMLButtonElement).disabled).toBe(true);
    await type('#mmCnBase', 'https://g.example.com');
    await type('#mmCnKey', 'k1');
    await press('Connect');
    expect(s.sent('PUT', '/v1/plugs/graphiti')[0].body).toEqual({ enabled: true, config: { base_url: 'https://g.example.com' }, secrets: { api_key: 'k1' } });
    expect(page().querySelector('.sheet [role=alert]')?.textContent).toBe('That address did not answer.');
    refuse = false;
    await press('Connect');
    expect(page().querySelector('#mmCrT')?.textContent).toBe('New memory');
    expect(page().querySelector('.mm-eng-now b')?.textContent).toBe('Graphiti');
  });

  test('an engine that may go without an address needs a key then, and no key is sent when none is typed', async () => {
    const s = backend({
      'GET /v1/memories/providers': { data: allProviders(NONE) },
      'PUT /v1/plugs/mem0': { type: 'mem0' },
    });
    await open();
    await press('Connect an engine');
    await act(async () => { (Array.from(page().querySelectorAll('.mm-pv-o')).find((o) => o.textContent?.includes('Mem0'))!.querySelector('button') as HTMLButtonElement).click(); });
    await flush();
    const go = () => page().querySelector('.sheet button[type=submit]') as HTMLButtonElement;
    expect(go().disabled).toBe(true);
    await type('#mmCnBase', 'https://m.example.com');
    expect(go().disabled).toBe(false);
    await press('Connect');
    expect(s.sent('PUT', '/v1/plugs/mem0')[0].body).toEqual({ enabled: true, config: { base_url: 'https://m.example.com' } });
  });

  test('Find engines asks the service to look, and says which it connected, from what it reads after', async () => {
    let found = false;
    const s = backend({
      'GET /v1/memories/providers': () => ({ data: allProviders(found ? { ...NONE, mem0: true, reme: true } : NONE) }),
      'POST /v1/memory-services/discover': () => { found = true; return { object: 'list' }; },
    });
    await open();
    await press('Find engines');
    expect(s.sent('POST', '/v1/memory-services/discover')).toHaveLength(1);
    expect(toast).toHaveBeenCalledWith('Mem0, ReMe connected.');
  });
});

describe('New memory: a name, a description if you like, and the engine chosen for you', () => {
  const connected = { ...NONE, mem0: true, graphiti: true, hindsight: true };
  const start = async (on: Record<string, boolean> = connected) => {
    const s = backend({
      'GET /v1/memories/providers': { data: allProviders(on) },
      'GET /v1/memories': { data: [memory()] },
      'POST /v1/memories': (c: { body: { name: string; provider: string } }) => memory({ id: 'hmem_new', name: c.body.name, provider: c.body.provider }),
    });
    await open();
    await press('New memory');
    return s;
  };
  const chosen = () => page().querySelector('.mm-eng-now b')?.textContent;

  test('nothing to compare and nothing to lock: no Kept by, no Fixed once created', async () => {
    await start();
    expect(page().textContent).not.toContain('Kept by');
    expect(page().textContent).not.toContain('Fixed once created');
    expect(page().querySelector('.mm-sv-facts')).toBeNull();
    expect(page().querySelector('label[for=mmCrDesc]')?.textContent).toContain('optional');
  });

  test('the engine follows what the memory is for, and says why', async () => {
    await start();
    await type('#mmCrName', 'Customer preferences');
    expect(chosen()).toBe('Mem0');
    expect(page().querySelector('.mm-eng-now small')?.textContent).toContain('each person');
    await type('#mmCrName', 'Account research');
    expect(chosen()).toBe('Graphiti');
    await type('#mmCrName', 'Incident lessons');
    expect(chosen()).toBe('Hindsight');
  });

  test('the best fit not running here: the next one that is, and the reason says so', async () => {
    await start({ ...NONE, mem0: true, graphiti: true });
    await type('#mmCrName', 'Team wiki');
    expect(chosen()).toBe('Mem0');
    expect(page().querySelector('.mm-eng-now small')?.textContent).toBe('ReMe fits best; it isn’t running here, so Mem0 keeps it for now.');
  });

  test('Change offers the connected engines only, as a group of radio buttons, and the choice is what gets created', async () => {
    const s = await start();
    await type('#mmCrName', 'Accounts');
    await press('Change');
    expect(Array.from(page().querySelectorAll('[role=radiogroup] [role=radio] b')).map((b) => b.textContent)).toEqual(['Mem0', 'Graphiti', 'Hindsight']);
    await act(async () => { (page().querySelector('[role=radiogroup]') as HTMLElement).dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })); });
    const now = page().querySelector('[role=radiogroup] [aria-checked=true] b')?.textContent;
    expect(chosen()).toBe(now);
    await press('Create');
    expect((s.sent('POST', '/v1/memories')[0].body as { provider: string }).provider).toBe(now?.toLowerCase());
  });

  test('Create makes it with its name and description and opens its data, whatever the engine reads', async () => {
    const s = await start();
    await type('#mmCrName', 'Accounts');
    await type('#mmCrDesc', 'Who our customers are.');
    await press('Create');
    expect(s.sent('POST', '/v1/memories')[0].body).toEqual({ name: 'Accounts', description: 'Who our customers are.', provider: 'mem0' });
    expect(push).toHaveBeenCalledWith('/memories/hmem_new?tab=data');
  });

  test('none connected, with memories already here: nothing can be created, and the way to connect is there', async () => {
    backend({ 'GET /v1/memories/providers': { data: allProviders(NONE) }, 'GET /v1/memories': { data: [memory({ records: { count: null } })] } });
    await open();
    await press('New memory');
    await type('#mmCrName', 'Accounts');
    expect(button('Create')?.disabled).toBe(true);
    await press('Connect an engine');
    expect(page().querySelector('#mmCh')?.textContent).toBe('Connect a memory engine');
  });
});

describe('the cards', () => {
  test('no counts: the list is read without them, in the order it was last used, and a card names its engine', async () => {
    // Richard 11-06: the counts (memories, records, setups; a card's types, records and setups) made the list slow
    const s = backend({
      'GET /v1/memories/providers': { data: [CAPS.graphiti, CAPS.mem0] },
      'GET /v1/memories': { data: [memory(), memory({ id: 'hmem_2', name: 'Support', provider: 'mem0', records: { count: null }, description: '' })] },
      'GET /v1/memories/hmem_1/schema': { types: [{ name: 'Company' }, { name: 'Person' }], relations: [] },
    });
    await open();
    const [a, b] = Array.from(page().querySelectorAll('.mm-card'));
    expect(page().querySelectorAll('.mm-cs')).toHaveLength(0);
    expect(page().querySelector('.list-top')?.textContent).not.toMatch(/\d+ (memories|memory|records?)|used by/);
    expect(s.sent('GET', '/v1/memories').map((c) => c.path)).toEqual(['/v1/memories?counts=false&sort=recent']);
    expect(s.calls.filter((c) => c.path.includes('/grants'))).toEqual([]);
    expect(a.querySelector('.mm-cp')?.textContent).toBe('Graphiti');
    expect(b.querySelector('.mm-cd')?.textContent).toBe('No description yet.');
    expect(page().textContent).not.toContain('Kept by');
    // a service before 0.40 says nothing of who uses a memory: nothing is drawn of it
    expect(page().querySelector('.mm-ub')).toBeNull();
    expect(page().querySelector('.mm-sort')).toBeNull();
  });

  test('who uses each one, as chips, and when it was last used; the most recently used first', async () => {
    backend({
      'GET /v1/memories/providers': { data: [CAPS.mem0] },
      'GET /v1/memories': { data: [
        memory({ id: 'a', name: 'Older', provider: 'mem0', engine: 'mem0', used_by: [{ harness_id: 'chrn_a', name: 'Photo cut' }], last_used_at: '2026-11-01T00:00:00Z' }),
        memory({ id: 'b', name: 'Busy', provider: 'mem0', engine: 'mem0', used_by: [{ harness_id: 'chrn_a', name: 'Photo cut' }, { harness_id: 'chrn_b', name: 'Support bot' }, { harness_id: 'chrn_c', name: 'Sales' }], last_used_at: '2026-11-08T00:00:00Z' }),
        memory({ id: 'c', name: 'Idle', provider: 'mem0', engine: 'mem0', used_by: [], last_used_at: null }),
      ] },
    });
    await open();
    const cards = Array.from(page().querySelectorAll('.mm-card'));
    expect(cards.map((c) => c.querySelector('.mm-ct b')?.textContent)).toEqual(['Busy', 'Older', 'Idle']);
    expect(Array.from(cards[0].querySelectorAll('.mm-uc')).map((c) => c.textContent)).toEqual(['Photo cut', 'Support bot', '+1']);
    expect(cards[0].querySelector('.mm-cp')?.textContent).toMatch(/^Mem0 · Used .+ ago$/);
    expect(cards[2].querySelector('.mm-ub')?.textContent).toBe('Not used yet');
    expect(cards[2].querySelector('.mm-cp')?.textContent).toBe('Mem0');
    // Use in sits beside the card nothing uses, never inside its link
    const use = Array.from(page().querySelectorAll('.mm-cardw')).map((w) => !!w.querySelector(':scope > .mm-usein'));
    expect(use).toEqual([false, false, true]);
    // by name, a click away
    const sel = page().querySelector('.mm-sort select') as HTMLSelectElement;
    await act(async () => { sel.value = 'name'; sel.dispatchEvent(new Event('change', { bubbles: true })); });
    expect(Array.from(page().querySelectorAll('.mm-card .mm-ct b')).map((b) => b.textContent)).toEqual(['Busy', 'Idle', 'Older']);
  });

  test('search narrows by name, description, engine or the setups that use it', async () => {
    backend({
      'GET /v1/memories/providers': { data: [CAPS.mem0, CAPS.graphiti] },
      'GET /v1/memories': { data: [
        memory({ id: 'a', name: 'Accounts', description: 'Who our customers are.', provider: 'graphiti', used_by: [] }),
        memory({ id: 'b', name: 'Prefs', description: '', provider: 'mem0', used_by: [{ harness_id: 'chrn_b', name: 'Support bot' }] }),
      ] },
    });
    await open();
    const names = () => Array.from(page().querySelectorAll('.mm-card .mm-ct b')).map((b) => b.textContent);
    await type('.mm-lfind input', 'customers');
    expect(names()).toEqual(['Accounts']);
    await type('.mm-lfind input', 'support bot');
    expect(names()).toEqual(['Prefs']);
    await type('.mm-lfind input', 'mem0');
    expect(names()).toEqual(['Prefs']);
    await type('.mm-lfind input', 'nothing like it');
    expect(page().textContent).toContain('No memory matches that.');
  });

  test('Use in gives a memory to a setup, which then remembers there', async () => {
    const s = backend({
      'GET /v1/memories/providers': { data: [CAPS.mem0] },
      'GET /v1/memories': { data: [memory({ id: 'c', name: 'Idle', provider: 'mem0', engine: 'mem0', used_by: [] })] },
      'PUT /v1/harnesses/chrn_a/memory': { id: 'chrn_a', memory: { id: 'c', name: 'Idle', engine: 'mem0', scope: 'shared', reason: '' } },
    });
    await open();
    await press('Use in…');
    await press('Use here');
    expect(s.sent('PUT', '/v1/harnesses/chrn_a/memory')[0].body).toEqual({ id: 'c' });
    expect(toast).toHaveBeenCalledWith('Photo cut remembers in Idle now.');
  });

  test('connecting and finding engines are under More', async () => {
    backend({ 'GET /v1/memories/providers': { data: [CAPS.mem0] }, 'GET /v1/memories': { data: [memory({ provider: 'mem0' })] } });
    await open();
    expect(button('Connect an engine')).toBeUndefined();
    await more('Connect an engine');
    expect(page().querySelector('#mmCh')?.textContent).toBe('Connect a memory engine');
    // one connected already says Change, not Connect
    expect(Array.from(page().querySelectorAll('.mm-pv-o .btn')).map((b) => b.textContent)).toEqual(['Change']);
  });
});

describe('a card draws what is kept', () => {
  const MADE = {
    types: [{ name: 'episode', description: 'e' }, { name: 'entity', description: 'n' }, { name: 'fact', description: 'f' }],
    relations: [{ name: 'about', from: 'fact', to: 'entity', description: 'a' }, { name: 'derived_from', from: 'fact', to: 'episode', description: 'o' }],
  };
  const makes = { ...CAPS.graphiti, schema: { ...CAPS.graphiti.schema, builtin: MADE } } as Provider;
  const names = (el: Element) => Array.from(el.querySelectorAll('text.mm-ca-type')).map((x) => x.textContent).sort();
  test('where nobody set a schema it draws what the vendor makes, named and linked, not the records (Richard 11-06)', () => {
    const host = document.createElement('div');
    const r = createRoot(host);
    act(() => r.render(<CardArt s={concepts(null, makes)} labels={false} records={41} recent={['Caroline gave a talk']} />));
    expect(names(host)).toEqual(['Entity', 'Episode', 'Fact']);
    expect(host.querySelectorAll('line')).toHaveLength(2);
    expect(host.textContent).not.toContain('Caroline gave a talk');
    act(() => r.unmount());
  });
  test('the picture has what the vendor makes and what a person set', async () => {
    backend({
      'GET /v1/memories/providers': { data: [makes] },
      'GET /v1/memories': { data: [memory()] },
      'GET /v1/memories/hmem_1/schema': { types: [{ name: 'Company' }, { name: 'Person' }], relations: [] },
      'GET /v1/memories/hmem_1/grants': { data: [] },
    });
    await open();
    const card = page().querySelector('.mm-card') as Element;
    expect(names(card)).toEqual(['Company', 'Entity', 'Episode', 'Fact', 'Person']);
  });
  test("each memory draws what its provider makes where the memory is kept, not where the list is read", async () => {
    // Mem0's own service makes facts; a Mem0 server, facts and the names in them: two Mem0 memories draw differently
    const factsOnly = { ...CAPS.mem0, schema: { mode: 'none', builtin: { types: [{ name: 'fact', description: 'f' }], relations: [] } } } as Provider;
    const server = { types: [{ name: 'fact', description: 'f' }, { name: 'entity', description: 'n' }], relations: [{ name: 'about', from: 'fact', to: 'entity', description: 'a' }] };
    backend({
      'GET /v1/memories/providers': { data: [factsOnly] },
      'GET /v1/memories': { data: [{ ...memory(), id: 'hmem_1', name: 'Kept by the service', provider: 'mem0', builtin: factsOnly.schema!.builtin },
        { ...memory(), id: 'hmem_2', name: 'Kept by a server', provider: 'mem0', builtin: server }] },
    });
    await open();
    const card = (n: string) => Array.from(page().querySelectorAll('.mm-card')).find((c) => c.textContent?.includes(n)) as Element;
    expect(names(card('Kept by the service'))).toEqual(['Fact']);
    expect(names(card('Kept by a server'))).toEqual(['Entity', 'Fact']);
  });
  test('labels a person set are drawn as labels; with none yet, what the vendor makes', () => {
    const labelled = { ...CAPS.hindsight, schema: { mode: 'labels', builtin: MADE } } as Provider;
    const host = document.createElement('div');
    const r = createRoot(host);
    act(() => r.render(<CardArt s={concepts({ types: [], relations: [] }, labelled)} labels={false} records={3} />));
    expect(names(host)).toEqual(['Entity', 'Episode', 'Fact']);
    act(() => r.unmount());
  });
});

describe('cards or a list', () => {
  test('List shows a row a memory, its name and description, and the choice is remembered', async () => {
    localStorage.removeItem('hr.memories.view');
    backend({
      'GET /v1/memories/providers': { data: [CAPS.graphiti, CAPS.mem0] },
      'GET /v1/memories': { data: [memory(), memory({ id: 'hmem_2', name: 'Support', provider: 'mem0', records: { count: null }, description: '' })] },
      'GET /v1/memories/hmem_1/schema': { types: [{ name: 'Company' }, { name: 'Person' }], relations: [] },
      'GET /v1/memories/hmem_1/grants': { data: [{ id: 'g1', memory_id: 'hmem_1', principal: 'member:chrn_a', privileges: ['read'], inherited: false }] },
    });
    await open();
    expect(page().querySelectorAll('.mm-card')).toHaveLength(2);
    await press('List');
    const rows = Array.from(page().querySelectorAll('.mm-row'));
    expect(rows).toHaveLength(2);
    const cells = (r: Element) => Array.from(r.children).slice(1).map((c) => c.textContent);
    expect(cells(rows[0])).toEqual(['What each brand wants.']);
    expect(cells(rows[1])).toEqual(['No description yet.']);
    expect(localStorage.getItem('hr.memories.view')).toBe('list');
    await press('Cards');
    expect(page().querySelectorAll('.mm-card')).toHaveLength(2);
    expect(localStorage.getItem('hr.memories.view')).toBe('cards');
  });
});
