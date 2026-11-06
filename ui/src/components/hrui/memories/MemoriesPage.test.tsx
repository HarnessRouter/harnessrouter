/** @jest-environment jsdom */
// The Memories list and who keeps a new memory. Nothing connected leads to connecting, in one sentence.
// Kept by lists every service with one honest line, and one not connected offers Connect in place of
// being chosen. The Create button and where it leads follow the service's schema mode. A refused
// connection says the service's own words. Every figure on a card is the service's.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { Provider } from '@/lib/memories';
import { allProviders, CAPS, memory, service } from './fixtures';

const push = jest.fn();
jest.mock('next/navigation', () => ({ useRouter: () => ({ push, replace: jest.fn() }) }));
jest.mock('next/link', () => ({ __esModule: true, default: ({ children, href, className }: { children: React.ReactNode; href: string; className?: string }) => <a className={className} href={href}>{children}</a> }));
jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
jest.mock('@/lib/harness', () => ({ gwHeaders: () => ({}), listCustom: jest.fn(async () => [{ id: 'chrn_a', name: 'Photo cut' }]), instructionFileLabel: () => 'AGENTS.md' }));
jest.mock('../setup/settingsModel', () => ({
  plain: (e: unknown, f: string) => (e instanceof Error && e.message ? e.message : f),
  plural: (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`,
}));

import { harnessFetch } from '@/lib/hfetch';
import { MemoriesPage } from './MemoriesPage';
import { Art } from './parts';

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

describe('nothing connected', () => {
  test('the page explains in one sentence and leads to connecting, not to a memory that could not be made', async () => {
    backend({ 'GET /v1/memories/providers': { data: allProviders(NONE) } });
    await open();
    expect(page().querySelector('.mm-empty-list h2')?.textContent).toBe('Connect a memory service');
    expect(page().querySelectorAll('.mm-empty-list p')).toHaveLength(1);
    expect(button('New memory')).toBeUndefined();
    await press('Connect a service');
    const offered = Array.from(page().querySelectorAll('.mm-pv-o b')).map((b) => b.textContent);
    expect(offered).toEqual(['Mem0', 'Graphiti', 'Hindsight', 'ReMe']);
    expect(page().textContent).toContain('Plain Markdown files you can read and edit.');
    expect(page().querySelectorAll('.mm-pv-o .btn')).toHaveLength(4);
  });

  test('connecting sends the address and key, shows a refusal in the service’s words, then goes on to New memory', async () => {
    let refuse = true;
    const s = backend({
      'GET /v1/memories/providers': () => ({ data: allProviders(refuse ? NONE : { ...NONE, graphiti: true }) }),
      'PUT /v1/plugs/graphiti': () => (refuse ? { $status: 422, error: { code: 'memory_invalid', message: 'That address did not answer.' } } : { type: 'graphiti' }),
    });
    await open();
    await press('Connect a service');
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
    expect(page().querySelector('.mm-pv-o.on b')?.textContent).toBe('Graphiti');
  });

  test('a service that may go without an address needs a key then, and no key is sent when none is typed', async () => {
    const s = backend({
      'GET /v1/memories/providers': { data: allProviders(NONE) },
      'PUT /v1/plugs/mem0': { type: 'mem0' },
    });
    await open();
    await press('Connect a service');
    await act(async () => { (Array.from(page().querySelectorAll('.mm-pv-o')).find((o) => o.textContent?.includes('Mem0'))!.querySelector('button') as HTMLButtonElement).click(); });
    await flush();
    const go = () => page().querySelector('.sheet button[type=submit]') as HTMLButtonElement;
    expect(go().disabled).toBe(true);
    await type('#mmCnBase', 'https://m.example.com');
    expect(go().disabled).toBe(false);
    await press('Connect');
    expect(s.sent('PUT', '/v1/plugs/mem0')[0].body).toEqual({ enabled: true, config: { base_url: 'https://m.example.com' } });
  });
});

describe('New memory', () => {
  const connected = { ...NONE, mem0: true, graphiti: true, hindsight: true };
  const start = async () => {
    const s = backend({
      'GET /v1/memories/providers': { data: allProviders(connected) },
      'POST /v1/memories': (c: { body: { name: string; provider: string } }) => memory({ id: 'hmem_new', name: c.body.name, provider: c.body.provider }),
    });
    await open();
    await press('New memory');
    await type('#mmCrName', 'Accounts');
    return s;
  };
  const choose = async (name: string) => {
    await act(async () => { (Array.from(page().querySelectorAll('button.mm-pv-o')).find((o) => o.textContent?.includes(name)) as HTMLButtonElement).click(); });
  };

  test('lists all four: one not connected offers Connect and cannot be chosen', async () => {
    await start();
    expect(Array.from(page().querySelectorAll('.mm-prov b')).map((b) => b.textContent)).toEqual(['Mem0', 'Graphiti', 'Hindsight', 'ReMe']);
    expect(Array.from(page().querySelectorAll('button.mm-pv-o b')).map((b) => b.textContent)).toEqual(['Mem0', 'Graphiti', 'Hindsight']);
    const reme = Array.from(page().querySelectorAll('.mm-pv-o')).find((o) => o.textContent?.includes('ReMe')) as HTMLElement;
    expect(reme.tagName).toBe('DIV');
    expect(reme.querySelector('button')?.textContent).toBe('Connect');
    // open source ships no memory of its own to offer
    expect(page().textContent).not.toContain('HarnessRouter');
  });

  test('what starts chosen is one that is connected, and it is what gets created', async () => {
    const s = backend({
      'GET /v1/memories/providers': { data: allProviders({ ...NONE, graphiti: true }) },
      'POST /v1/memories': (c: { body: { name: string; provider: string } }) => memory({ id: 'hmem_new', name: c.body.name, provider: c.body.provider }),
    });
    await open();
    await press('New memory');
    await type('#mmCrName', 'Accounts');
    expect(page().querySelector('.mm-pv-o.on b')?.textContent).toBe('Graphiti');
    await press('Create and design schema');
    expect((s.sent('POST', '/v1/memories')[0].body as { provider: string }).provider).toBe('graphiti');
  });

  test('none connected, with memories already here: nothing can be created until one is', async () => {
    backend({ 'GET /v1/memories/providers': { data: allProviders(NONE) }, 'GET /v1/memories': { data: [memory({ records: { count: null } })] } });
    await open();
    await press('New memory');
    await type('#mmCrName', 'Accounts');
    expect(button('Create')?.disabled).toBe(true);
    expect(page().querySelectorAll('button.mm-pv-o')).toHaveLength(0);
  });

  test('where no schema is read the button says Create and leads to Data', async () => {
    const s = await start();
    await choose('Mem0');
    expect(button('Create and design schema')).toBeUndefined();
    await press('Create');
    expect(s.sent('POST', '/v1/memories')[0].body).toEqual({ name: 'Accounts', description: '', provider: 'mem0' });
    expect(push).toHaveBeenCalledWith('/memories/hmem_new?tab=data');
  });

  test('where a schema guides it the button says so and leads to Schema', async () => {
    await start();
    await choose('Graphiti');
    expect(button('Create')).toBeUndefined();
    await press('Create and design schema');
    expect(push).toHaveBeenCalledWith('/memories/hmem_new?tab=schema');
  });

  test('where labels apply it says labels, never schema', async () => {
    await start();
    await choose('Hindsight');
    expect(page().textContent).not.toContain('design its schema');
    await press('Create and add labels');
    expect(push).toHaveBeenCalledWith('/memories/hmem_new?tab=schema');
  });
});

describe('the cards', () => {
  test('every figure is the service’s: types from the schema, records and setups read, a dash for what is not known', async () => {
    backend({
      'GET /v1/memories/providers': { data: [CAPS.graphiti, CAPS.mem0] },
      'GET /v1/memories': { data: [memory(), memory({ id: 'hmem_2', name: 'Support', provider: 'mem0', records: { count: null }, description: '' })] },
      'GET /v1/memories/hmem_1/schema': { types: [{ name: 'Company' }, { name: 'Person' }], relations: [] },
      'GET /v1/memories/hmem_1/grants': { data: [{ id: 'g1', memory_id: 'hmem_1', principal: 'member:chrn_a', privileges: ['read'], inherited: false }, { id: 'g2', memory_id: 'hmem_1', principal: 'member:someone', privileges: ['read'], inherited: false }] },
    });
    await open();
    const [a, b] = Array.from(page().querySelectorAll('.mm-card'));
    const figures = (c: Element) => Array.from(c.querySelectorAll('.mm-cs > span')).map((x) => `${x.querySelector('small')?.textContent} ${x.querySelector('b')?.textContent}`);
    expect(figures(a)).toEqual(['Types 2', 'Records 1', 'Setups 1']);
    // no schema is read here: no Types figure at all; its count could not be read: a dash, never 0
    expect(figures(b)).toEqual(['Records —', 'Setups —']);
    expect(a.querySelector('.mm-cp')?.textContent).toBe('Kept by Graphiti');
    expect(b.querySelector('.mm-cd')?.textContent).toBe('No description yet.');
  });
});

describe('a card draws what is kept', () => {
  const dots = (records: number) => {
    const host = document.createElement('div');
    const root = createRoot(host);
    act(() => root.render(<Art s={null} w={300} h={150} records={records} />));
    const out = { filled: host.querySelectorAll('circle[fill="var(--faint)"]').length, ring: host.querySelectorAll('circle[fill="none"]').length };
    act(() => root.unmount());
    return out;
  };
  test('one dot a record where there is no schema, never more than fit', () => {
    expect(dots(4)).toEqual({ filled: 4, ring: 0 });
    expect(dots(400)).toEqual({ filled: 15, ring: 0 });
  });
  test('an empty memory stays an empty ring, so it does not read as one with records', () => {
    expect(dots(0)).toEqual({ filled: 0, ring: 1 });
  });
  const MADE = {
    types: [{ name: 'episode', description: 'e' }, { name: 'entity', description: 'n' }, { name: 'fact', description: 'f' }],
    relations: [{ name: 'about', from: 'fact', to: 'entity', description: 'a' }, { name: 'derived_from', from: 'fact', to: 'fact', description: 'o' }],
  };
  const makes = { ...CAPS.graphiti, schema: { ...CAPS.graphiti.schema, builtin: MADE } } as Provider;
  test('a vendor that says what it makes: the cover is its concepts, named and linked, not a dot a record', () => {
    const host = document.createElement('div');
    const r = createRoot(host);
    act(() => r.render(<Art s={null} w={300} h={150} records={41} provider={makes} />));
    expect(Array.from(host.querySelectorAll('text')).map((t) => t.textContent).sort()).toEqual(['Entity', 'Episode', 'Fact']);
    expect(host.querySelectorAll('circle[fill="var(--faint)"]')).toHaveLength(0);
    expect(host.querySelectorAll('line')).toHaveLength(1);
    expect(host.querySelectorAll('circle[fill="none"]')).toHaveLength(1);   // an observation drawn from facts
    act(() => r.unmount());
  });
  test('its types count what it makes and what a person set', async () => {
    backend({
      'GET /v1/memories/providers': { data: [makes] },
      'GET /v1/memories': { data: [memory()] },
      'GET /v1/memories/hmem_1/schema': { types: [{ name: 'Company' }, { name: 'Person' }], relations: [] },
      'GET /v1/memories/hmem_1/grants': { data: [] },
    });
    await open();
    const card = page().querySelector('.mm-card') as Element;
    expect(Array.from(card.querySelectorAll('.mm-cs > span')).map((x) => `${x.querySelector('small')?.textContent} ${x.querySelector('b')?.textContent}`)[0]).toBe('Types 5');
    expect(Array.from(card.querySelectorAll('.mm-art text')).map((t) => t.textContent).sort()).toEqual(['Company', 'Entity', 'Episode', 'Fact', 'Person']);
  });
});
