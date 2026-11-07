/** @jest-environment jsdom */
// A setup's Settings, Memory: a row and a switch for every memory, where access is a grant to the setup's own principal,
// the default is one it can write, and whether finished tasks are kept is said in what the provider really does.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { CAPS, memory, service } from './fixtures';
import type { Provider } from '@/lib/memories';

const push = jest.fn();
const toast = jest.fn();
jest.mock('next/navigation', () => ({ useRouter: () => ({ push }) }));
jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
jest.mock('@/lib/harness', () => ({ gwHeaders: () => ({}), listCustom: jest.fn(async () => []) }));
jest.mock('../toast', () => ({ toast: (m: string) => toast(m) }));
jest.mock('../setup/settingsModel', () => ({
  plain: (e: unknown, f: string) => (e instanceof Error && e.message ? e.message : f),
  plural: (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`,
}));

import { harnessFetch } from '@/lib/hfetch';
import { MemoryLayer, memorySummary } from './MemoryLayer';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let root: Root; let el: HTMLElement;
const flush = async () => { for (let i = 0; i < 14; i++) await act(async () => { await Promise.resolve(); }); };
const H = 'chrn_a';
const held = (id: string, name: string, write: boolean, def = false) => ({ id, name, description: '', records: { count: 3 }, privileges: write ? ['read', 'write'] : ['read'], default: def });
const ALL = () => [memory({ id: 'm1', name: 'Brand kits', provider: 'graphiti' }), memory({ id: 'm2', name: 'Support', provider: 'graphiti' })];
function backend(o: { data: ReturnType<typeof held>[]; def?: string | null; observe?: boolean; providers?: Provider[]; all?: ReturnType<typeof memory>[]; extra?: Record<string, unknown> }) {
  const state = { default_memory_id: o.def ?? null, observe: o.observe ?? true };
  const s = service({
    'GET /v1/memories/providers': { data: o.providers || [CAPS.graphiti] },
    'GET /v1/memories': { data: o.all || ALL() },
    [`GET /v1/harnesses/${H}/memories`]: () => ({ object: 'harness.memories', principal: `member:${H}`, ...state, data: o.data }),
    [`PUT /v1/harnesses/${H}/memories`]: (c: { body: object }) => { Object.assign(state, c.body); return { object: 'harness.memories', principal: `member:${H}`, ...state, data: o.data }; },
    'POST /v1/memories/m1/grants': { id: 'g' }, 'POST /v1/memories/m2/grants': { id: 'g' },
    'GET /v1/memories/m1/grants': { data: [{ id: 'g1', memory_id: 'm1', principal: `member:${H}`, privileges: ['read'], inherited: false }] },
    'DELETE /v1/memories/m1/grants/g1': { deleted: true },
    ...o.extra,
  });
  (harnessFetch as jest.Mock).mockImplementation(s.fetcher);
  return s;
}
async function draw() { await act(async () => { root.render(<MemoryLayer hid={H} name="Photo cut" />); }); await flush(); }
const rowOf = (name: string) => Array.from(el.querySelectorAll('.cap-row')).find((r) => r.querySelector('b')?.textContent?.startsWith(name)) as HTMLElement;
const sw = (name: string) => rowOf(name).querySelector('button.tog') as HTMLButtonElement;
const press = async (b: HTMLElement) => { await act(async () => { b.click(); }); await flush(); };
beforeEach(() => { el = document.createElement('div'); el.id = 'hrui'; document.body.appendChild(el); root = createRoot(el); });
afterEach(() => { act(() => root.unmount()); el.remove(); jest.clearAllMocks(); });

test('every memory has a row and a switch, on where the agent holds it and off where it doesn’t', async () => {
  backend({ data: [held('m1', 'Brand kits', true, true)], def: 'm1' });
  await draw();
  expect(sw('Brand kits').getAttribute('aria-pressed')).toBe('true');
  expect(sw('Brand kits').textContent).toBe('On');
  expect(sw('Support').getAttribute('aria-pressed')).toBe('false');
  expect(sw('Support').textContent).toBe('Off');
  expect(rowOf('Support').classList.contains('off')).toBe(true);
  expect(el.textContent).not.toContain('Give a memory');
});
test('its second line is who keeps it and how much, read from the memory', async () => {
  backend({ data: [] });
  await draw();
  expect(rowOf('Support').querySelector('small')?.textContent).toBe('1 record · Graphiti');
});
test('it says what it is with its own brick, not a tool’s', async () => {
  backend({ data: [held('m1', 'Brand kits', false)] });
  await draw();
  expect(rowOf('Brand kits').querySelector('.cap-ic .f-memory')).toBeTruthy();
  expect(rowOf('Brand kits').querySelector('.cap-ic .f-mcp')).toBeNull();
});
test('turning one on is a read grant to the setup’s principal, and says nothing when it works', async () => {
  const s = backend({ data: [] });
  await draw();
  await press(sw('Support'));
  expect(s.sent('POST', '/v1/memories/m2/grants')[0].body).toEqual({ principal: `member:${H}`, privileges: ['read'] });
  expect(toast).not.toHaveBeenCalled();
});
test('turning one off takes away the grant on that memory', async () => {
  const s = backend({ data: [held('m1', 'Brand kits', false)] });
  await draw();
  await press(sw('Brand kits'));
  expect(s.sent('DELETE', '/v1/memories/m1/grants/g1')).toHaveLength(1);
});
test('a switch that fails says so and goes back to what’s true', async () => {
  backend({ data: [], extra: { 'POST /v1/memories/m2/grants': () => { throw new Error('No.'); } } });
  await draw();
  await press(sw('Support'));
  expect(toast).toHaveBeenCalled();
  expect(sw('Support').getAttribute('aria-pressed')).toBe('false');
});
test('how far it may go is beside the switch only where it’s on', async () => {
  backend({ data: [held('m1', 'Brand kits', true, true)], def: 'm1' });
  await draw();
  expect((rowOf('Brand kits').querySelector('select') as HTMLSelectElement).value).toBe('w');
  expect(rowOf('Support').querySelector('select')).toBeNull();
  expect(rowOf('Brand kits').querySelector('.mm-defp')?.textContent).toBe('Default');
});
test('the first memory it can write becomes its default', async () => {
  const s = backend({ data: [held('m1', 'Brand kits', false)] });
  await draw();
  const sel = rowOf('Brand kits').querySelector('select') as HTMLSelectElement;
  await act(async () => { sel.value = 'w'; sel.dispatchEvent(new Event('change', { bubbles: true })); });
  await flush();
  expect(s.sent('POST', '/v1/memories/m1/grants')[0].body).toEqual({ principal: `member:${H}`, privileges: ['read', 'write'] });
  expect(s.sent('PUT', `/v1/harnesses/${H}/memories`)[0].body).toEqual({ default_memory_id: 'm1', observe: false });
});
test('losing write or being turned off hands the default on, or clears it', async () => {
  const s = backend({ data: [held('m1', 'Brand kits', true, true), held('m2', 'Support', true)], def: 'm1' });
  await draw();
  await press(sw('Brand kits'));
  expect(s.sent('PUT', `/v1/harnesses/${H}/memories`)[0].body).toEqual({ default_memory_id: 'm2' });
  await act(async () => { root.unmount(); }); root = createRoot(el);
  const s2 = backend({ data: [held('m1', 'Brand kits', true, true)], def: 'm1' });
  await draw();
  const sel = rowOf('Brand kits').querySelector('select') as HTMLSelectElement;
  await act(async () => { sel.value = 'r'; sel.dispatchEvent(new Event('change', { bubbles: true })); });
  await flush();
  // no default left: keeping tasks goes with it, so what is stored is what the switch shows
  expect(s2.sent('PUT', `/v1/harnesses/${H}/memories`)[0].body).toEqual({ default_memory_id: '', observe: false });
});
test('a default handed on is said, with where finished tasks go now', async () => {
  backend({ data: [held('m1', 'Brand kits', true, true), held('m2', 'Support', true)], def: 'm1', observe: true });
  await draw();
  await press(sw('Brand kits'));
  expect(toast).toHaveBeenCalledWith('Support is now the default. Finished tasks are kept there.');
  await act(async () => { root.unmount(); }); root = createRoot(el); toast.mockClear();
  backend({ data: [held('m1', 'Brand kits', true, true), held('m2', 'Support', true)], def: 'm1', observe: false });
  await draw();
  await press(sw('Brand kits'));
  expect(toast).toHaveBeenCalledWith('Support is now the default.');
});
test('Make default where there is none never turns keeping tasks on: the service would otherwise, unasked', async () => {
  // write given elsewhere, so a memory it writes and no default; the service keeps tasks unless told not to
  const s = backend({ data: [held('m1', 'Brand kits', true)], def: null, observe: true });
  await draw();
  expect(sw('Keep every finished task').textContent).toBe('Off');
  await press(Array.from(rowOf('Brand kits').querySelectorAll('button')).find((b) => b.textContent === 'Make default') as HTMLElement);
  expect(s.sent('PUT', `/v1/harnesses/${H}/memories`)[0].body).toEqual({ default_memory_id: 'm1', observe: false });
  expect(sw('Keep every finished task').textContent).toBe('Off');
});
test('Make default where there is one already moves the default and leaves keeping as the person set it', async () => {
  const s = backend({ data: [held('m1', 'Brand kits', true, true), held('m2', 'Support', true)], def: 'm1', observe: true });
  await draw();
  await press(Array.from(rowOf('Support').querySelectorAll('button')).find((b) => b.textContent === 'Make default') as HTMLElement);
  expect(s.sent('PUT', `/v1/harnesses/${H}/memories`)[0].body).toEqual({ default_memory_id: 'm2' });
});
test('a memory below one that’s on comes with it: on, and not a switch of its own', async () => {
  backend({
    data: [held('m1', 'Brand kits', false)],
    all: [memory({ id: 'm1', name: 'Brand kits', provider: 'graphiti' }), memory({ id: 'c1', name: 'Child', provider: 'graphiti', parent_id: 'm1' }), memory({ id: 'c2', name: 'Private', provider: 'graphiti', parent_id: 'm1', restricted: true })],
  });
  await draw();
  expect(sw('Child').getAttribute('aria-pressed')).toBe('true');
  expect(sw('Child').disabled).toBe(true);
  expect(rowOf('Child').querySelector('small')?.textContent).toBe('Comes with Brand kits · In Brand kits · 1 record · Graphiti');
  expect(sw('Private').getAttribute('aria-pressed')).toBe('false');
  expect(sw('Private').disabled).toBe(false);
});
test('someone who can’t change who holds a memory sees the switch, and it doesn’t move', async () => {
  backend({ data: [], all: [memory({ id: 'm1', name: 'Brand kits', provider: 'graphiti', privileges: ['read'] })] });
  await draw();
  expect(sw('Brand kits').disabled).toBe(true);
  expect(sw('Brand kits').title).toContain('manages this memory');
});
test('what the agent holds and this person can’t list is still shown, on', async () => {
  backend({ data: [held('hidden', 'Their secret', false)], all: [] });
  await draw();
  expect(sw('Their secret').getAttribute('aria-pressed')).toBe('true');
  expect(sw('Their secret').disabled).toBe(true);
  expect(rowOf('Their secret').querySelector('button[aria-label="Open Their secret"]')).toBeNull();
});
test('with several, a search with the real count; it keeps to the names and who keeps them', async () => {
  const many = ['Alpha', 'Beta', 'Gamma', 'Delta', 'Epsilon'].map((n, i) => memory({ id: `x${i}`, name: n, provider: i ? 'graphiti' : 'mem0' }));
  backend({ data: [], all: many, providers: [CAPS.graphiti, CAPS.mem0] });
  await draw();
  const box = el.querySelector('.cap-find input') as HTMLInputElement;
  expect(box.placeholder).toBe('Search 5 memories');
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  const type = async (v: string) => { await act(async () => { set.call(box, v); box.dispatchEvent(new Event('input', { bubbles: true })); }); await flush(); };
  await type('gam');
  expect(Array.from(el.querySelectorAll('.cap-find ~ .cap-list .cap-row b')).map((b) => b.textContent)).toEqual(['Gamma']);
  await type('mem0');
  expect(Array.from(el.querySelectorAll('.cap-find ~ .cap-list .cap-row b')).map((b) => b.textContent)).toEqual(['Alpha']);
  await type('nothing like it');
  expect(el.textContent).toContain('Nothing here matches that.');
});
test('with few, no search: nothing to look through', async () => {
  backend({ data: [] });
  await draw();
  expect(el.querySelector('.cap-find')).toBeNull();
});
test('with none at all, it says what to do, and the way to make one is there', async () => {
  backend({ data: [], all: [] });
  await draw();
  expect(el.querySelector('.cap-empty')?.textContent).toContain('No memories yet');
  await press(Array.from(el.querySelectorAll('button')).find((b) => b.textContent?.includes('New memory')) as HTMLElement);
  expect(push).toHaveBeenCalledWith('/memories?new=1');
});
test('Open goes to the memory', async () => {
  backend({ data: [held('m1', 'Brand kits', false)] });
  await draw();
  await press(rowOf('Brand kits').querySelector('button[aria-label="Open Brand kits"]') as HTMLElement);
  expect(push).toHaveBeenCalledWith('/memories/m1');
});
test('what it can’t do is said, and erasing is never the agent’s', async () => {
  backend({ data: [] });
  await draw();
  expect(el.textContent).toContain('Erasing is never up to an agent.');
});
test('keeping tasks needs a default, and says what the provider really does with them', async () => {
  backend({ data: [held('m1', 'Brand kits', false)] });
  await draw();
  const keep = () => el.querySelector('button.tog[aria-label="Keep every finished task"]') as HTMLButtonElement;
  expect(keep().disabled).toBe(true);
  expect(el.textContent).toContain('Needs a default memory: one it can write.');
  await act(async () => { root.unmount(); }); root = createRoot(el);
  const s = backend({ data: [held('m1', 'Brand kits', true, true)], def: 'm1', observe: false });
  await draw();
  expect(el.textContent).toContain('Each task is kept in Brand kits as an episode, so later tasks can recall it.');
  await press(keep());
  expect(s.sent('PUT', `/v1/harnesses/${H}/memories`)[0].body).toEqual({ observe: true });
  await act(async () => { root.unmount(); }); root = createRoot(el);
  backend({ data: [held('m1', 'Kept', true, true)], def: 'm1', providers: [CAPS.mem0], all: [memory({ id: 'm1', name: 'Kept', provider: 'mem0' })] });
  await draw();
  expect(el.textContent).toContain('Mem0 pulls what matters out of each task and keeps it in Kept');
  expect(el.textContent).not.toContain('as an episode');
});
test('a default whose provider keeps no tasks: nothing to turn on, so no row', async () => {
  const { observe: _o, ...rest } = CAPS.graphiti;
  backend({ data: [held('m1', 'Brand kits', true, true)], def: 'm1', providers: [rest as Provider] });
  await draw();
  expect(el.querySelector('button.tog[aria-label="Keep every finished task"]')).toBeNull();
});
test('the layers list says it plainly', () => {
  const base = { object: 'harness.memories' as const, principal: 'x', default_memory_id: null, observe: true };
  expect(memorySummary({ ...base, data: [] })).toBe('None');
  expect(memorySummary({ ...base, data: [held('a', 'A', true)] as never })).toBe('1 memory');
  expect(memorySummary({ ...base, default_memory_id: 'a', data: [held('a', 'A', true), held('b', 'B', false)] as never })).toBe('2 memories · keeps tasks');
  expect(memorySummary(null)).toBe('');
});
