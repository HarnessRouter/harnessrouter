/** @jest-environment jsdom */
// A setup's Settings, Memory: only the list. A row and a switch for every memory, On first; On is full use, a grant
// of read and write to the setup's own principal, and Off takes the grant away.
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
    // the service leaves each count unknown (null) when asked for none, as the page asks
    'GET /v1/memories': (c: { path: string }) => ({ data: (o.all || ALL()).map((m) => (c.path.includes('counts=false') ? { ...m, records: { count: null } } : m)) }),
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
async function draw() { await act(async () => { root.render(<MemoryLayer hid={H} />); }); await flush(); }
const rowOf = (name: string) => Array.from(el.querySelectorAll('.cap-row')).find((r) => r.querySelector('b')?.textContent?.startsWith(name)) as HTMLElement;
const names = () => Array.from(el.querySelectorAll('.cap-list .cap-row b')).map((b) => b.textContent);
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
test('only the list: no Remember, no engines, no scope, no level, no default, no finished tasks, no help line', async () => {
  backend({ data: [held('m1', 'Brand kits', true, true), held('m2', 'Support', false)], def: 'm1', observe: true, providers: [CAPS.graphiti, CAPS.mem0] });
  await draw();
  expect(Array.from(el.querySelectorAll('.lg-sub-h h3')).map((h) => h.childNodes[0]?.textContent)).toEqual(['Memories it can use']);
  expect(el.querySelector('button.tog[aria-label="Remember"]')).toBeNull();
  expect(el.querySelector('[role=radiogroup], [role=radio]')).toBeNull();
  expect(el.querySelector('dl, dt')).toBeNull();
  expect(el.querySelector('select')).toBeNull();
  expect(el.querySelector('button.tog[aria-label="Keep finished tasks"]')).toBeNull();
  expect(el.querySelector('.pill')).toBeNull();
  expect(Array.from(el.querySelectorAll('button')).map((b) => b.textContent)).not.toContain('Make default');
  for (const gone of ['Engine', 'Scope', 'Finished tasks', 'Recall only', 'Recall and remember', 'Default', 'Erasing is never up to an agent.']) expect(el.textContent).not.toContain(gone);
  // each row: its name, its engine under it, a switch and the arrow, and nothing else to press
  expect(rowOf('Brand kits').querySelector('small')?.textContent).toBe('Graphiti');
  expect(Array.from(rowOf('Brand kits').querySelectorAll('button')).map((b) => b.getAttribute('aria-label'))).toEqual(['Brand kits', 'Open Brand kits']);
});
test('it reads the memories without their counts, so it loads at once, and a row says who keeps it', async () => {
  const s = backend({ data: [] });
  await draw();
  expect(s.sent('GET', '/v1/memories').map((c) => c.path)).toEqual(['/v1/memories?counts=false']);
  // no count read, so none is said
  expect(rowOf('Support').querySelector('small')?.textContent).toBe('Graphiti');
});
test('the ones that are on come first, then the rest by name', async () => {
  const many = ['Alpha', 'Beta', 'Gamma', 'Delta', 'Epsilon'].map((n, i) => memory({ id: `x${i}`, name: n, provider: 'graphiti' }));
  backend({ data: [held('x4', 'Epsilon', true), held('x2', 'Gamma', true)], all: many });
  await draw();
  expect(names()).toEqual(['Epsilon', 'Gamma', 'Alpha', 'Beta', 'Delta']);
});
test('the order holds while switches are pressed, so a row never moves under the pointer', async () => {
  const data = [held('m2', 'Support', true)];
  backend({ data, extra: { 'POST /v1/memories/m1/grants': () => { data.push(held('m1', 'Brand kits', true)); return { id: 'g' }; } } });
  await draw();
  expect(names()).toEqual(['Support', 'Brand kits']);
  await press(sw('Brand kits'));
  expect(sw('Brand kits').getAttribute('aria-pressed')).toBe('true');
  expect(names()).toEqual(['Support', 'Brand kits']);
});
test('it says what it is with its own brick, not a tool’s', async () => {
  backend({ data: [held('m1', 'Brand kits', false)] });
  await draw();
  expect(rowOf('Brand kits').querySelector('.cap-ic .f-memory')).toBeTruthy();
  expect(rowOf('Brand kits').querySelector('.cap-ic .f-mcp')).toBeNull();
});
test('On is full use: a read and write grant to the harness’s principal, the same call as before, and says nothing when it works', async () => {
  const s = backend({ data: [held('m1', 'Brand kits', true, true)], def: 'm1' });
  await draw();
  await press(sw('Support'));
  expect(s.sent('POST', '/v1/memories/m2/grants').map((c) => c.body)).toEqual([{ principal: `member:${H}`, privileges: ['read', 'write'] }]);
  // a default is there already: it stays where it is
  expect(s.sent('PUT', `/v1/harnesses/${H}/memories`)).toHaveLength(0);
  expect(toast).not.toHaveBeenCalled();
});
test('On where there is no default makes that memory where it writes, keeping finished tasks there (the same whichever switch came first)', async () => {
  const s = backend({ data: [], observe: true });
  await draw();
  await press(sw('Support'));
  expect(s.sent('POST', '/v1/memories/m2/grants')[0].body).toEqual({ principal: `member:${H}`, privileges: ['read', 'write'] });
  expect(s.sent('PUT', `/v1/harnesses/${H}/memories`).map((c) => c.body)).toEqual([{ default_memory_id: 'm2', observe: true }]);
});
test('turning one off takes away the grant on that memory', async () => {
  const s = backend({ data: [held('m1', 'Brand kits', false)] });
  await draw();
  await press(sw('Brand kits'));
  expect(s.sent('DELETE', '/v1/memories/m1/grants/g1')).toHaveLength(1);
  expect(s.sent('POST', '/v1/memories/m1/grants')).toHaveLength(0);
});
test('a switch that fails says so and goes back to what’s true', async () => {
  backend({ data: [], extra: { 'POST /v1/memories/m2/grants': () => { throw new Error('No.'); } } });
  await draw();
  await press(sw('Support'));
  expect(toast).toHaveBeenCalled();
  expect(sw('Support').getAttribute('aria-pressed')).toBe('false');
});
test('turned off, the default is handed on, or cleared, and nothing is said: the switch is the feedback', async () => {
  const s = backend({ data: [held('m1', 'Brand kits', true, true), held('m2', 'Support', true)], def: 'm1', observe: true });
  await draw();
  await press(sw('Brand kits'));
  expect(s.sent('PUT', `/v1/harnesses/${H}/memories`)[0].body).toEqual({ default_memory_id: 'm2' });
  expect(toast).not.toHaveBeenCalled();
  await act(async () => { root.unmount(); }); root = createRoot(el);
  const s2 = backend({ data: [held('m1', 'Brand kits', true, true)], def: 'm1' });
  await draw();
  await press(sw('Brand kits'));
  // no default left: keeping tasks goes with it
  expect(s2.sent('PUT', `/v1/harnesses/${H}/memories`)[0].body).toEqual({ default_memory_id: '', observe: false });
  expect(toast).not.toHaveBeenCalled();
});
test('a memory below one that’s on comes with it: on, and not a switch of its own', async () => {
  backend({
    data: [held('m1', 'Brand kits', false)],
    all: [memory({ id: 'm1', name: 'Brand kits', provider: 'graphiti' }), memory({ id: 'c1', name: 'Child', provider: 'graphiti', parent_id: 'm1' }), memory({ id: 'c2', name: 'Private', provider: 'graphiti', parent_id: 'm1', restricted: true })],
  });
  await draw();
  expect(sw('Child').getAttribute('aria-pressed')).toBe('true');
  expect(sw('Child').disabled).toBe(true);
  expect(rowOf('Child').querySelector('small')?.textContent).toBe('Comes with Brand kits · In Brand kits · Graphiti');
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
test('the layers list says how many are on, from the same read, and nothing of engines or people', () => {
  const base = { object: 'harness.memories' as const, principal: 'x', default_memory_id: null, observe: true };
  expect(memorySummary({ ...base, data: [] })).toBe('None on');
  expect(memorySummary({ ...base, data: [held('a', 'A', true)] as never })).toBe('1 memory on');
  expect(memorySummary({ ...base, default_memory_id: 'a', data: [held('a', 'A', true), held('b', 'B', false)] as never })).toBe('2 memories on');
  expect(memorySummary(null)).toBe('');
});
test('while it is read, its shape is drawn, never a blank pane', async () => {
  let answer: (v: unknown) => void = () => {};
  (harnessFetch as jest.Mock).mockImplementation(() => new Promise((r) => { answer = r; }));
  await act(async () => { root.render(<MemoryLayer hid={H} />); });
  expect(el.querySelector('[aria-busy="true"]')).toBeTruthy();
  expect(el.textContent).toContain('Loading memory');
  void answer;
});

describe('the agent’s own memory, where the service gives one (0.40): a row like any other, on', () => {
  const OWN = { id: 'm1', name: 'Photo cut', engine: 'mem0', scope: 'per_user', reason: 'It serves people, so it keeps each person’s facts and preferences, separately per person.' };
  function contract(o: { on: boolean; def?: string | null; observe?: boolean; others?: ReturnType<typeof held>[] }) {
    return backend({
      data: [...(o.on ? [held('m1', 'Photo cut', true, (o.def ?? 'm1') === 'm1')] : []), ...(o.others || [])],
      def: o.def === undefined ? (o.on ? 'm1' : null) : o.def, observe: o.observe,
      all: [memory({ id: 'm1', name: 'Photo cut', provider: 'mem0' }), memory({ id: 'm2', name: 'Support', provider: 'graphiti' })],
      providers: [CAPS.mem0, CAPS.graphiti],
      extra: { [`GET /v1/harnesses/${H}`]: () => ({ id: H, memory: OWN }), 'GET /v1/memories/m1/grants': { data: [{ id: 'g1', memory_id: 'm1', principal: `member:${H}`, privileges: ['read', 'write'], inherited: false }] } },
    });
  }
  test('it is a row that is on, first, with its engine and nothing beside it', async () => {
    contract({ on: true });
    await draw();
    expect(names()).toEqual(['Photo cut', 'Support']);
    expect(sw('Photo cut').getAttribute('aria-pressed')).toBe('true');
    expect(rowOf('Photo cut').querySelector('small')?.textContent).toBe('Mem0');
    expect(rowOf('Photo cut').querySelector('.pill')).toBeNull();
    expect(el.querySelector('button.tog[aria-label="Remember"]')).toBeNull();
    expect(el.querySelector('[role=radio]')).toBeNull();
    expect(el.textContent).not.toContain('Separately for each person');
  });
  test('off is the same call as any row: its grant taken away, and no default left keeps nothing', async () => {
    const s = contract({ on: true });
    await draw();
    await press(sw('Photo cut'));
    expect(s.sent('DELETE', '/v1/memories/m1/grants/g1')).toHaveLength(1);
    expect(s.sent('PUT', `/v1/harnesses/${H}/memories`).map((c) => c.body)).toEqual([{ default_memory_id: '', observe: false }]);
    expect(s.sent('PUT', `/v1/harnesses/${H}/memory`)).toHaveLength(0);
    expect(toast).not.toHaveBeenCalled();
  });
  test('off while another memory is on: the default goes there, keeping finished tasks as before, and nothing is said', async () => {
    const s = contract({ on: true, observe: true, others: [held('m2', 'Support', true)] });
    await draw();
    await press(sw('Photo cut'));
    expect(s.sent('DELETE', '/v1/memories/m1/grants/g1')).toHaveLength(1);
    expect(s.sent('PUT', `/v1/harnesses/${H}/memories`).map((c) => c.body)).toEqual([{ default_memory_id: 'm2' }]);
    expect(toast).not.toHaveBeenCalled();
  });
  test('on again: the full grant, and it is the default again, keeping finished tasks, wherever the default had gone', async () => {
    const s = contract({ on: false, def: 'm2', observe: false, others: [held('m2', 'Support', true, true)] });
    await draw();
    await press(sw('Photo cut'));
    expect(s.sent('POST', '/v1/memories/m1/grants').map((c) => c.body)).toEqual([{ principal: `member:${H}`, privileges: ['read', 'write'] }]);
    expect(s.sent('PUT', `/v1/harnesses/${H}/memories`).map((c) => c.body)).toEqual([{ default_memory_id: 'm1', observe: true }]);
    expect(s.sent('PUT', `/v1/harnesses/${H}/memory`)).toHaveLength(0);
  });
});
