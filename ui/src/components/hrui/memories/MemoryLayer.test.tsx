/** @jest-environment jsdom */
// A setup's Settings, Memory: access is a grant to the setup's own principal, the default is one it can
// write, and whether finished tasks are kept is said in what the provider really does with them.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { CAPS, memory, service } from './fixtures';
import type { Provider } from '@/lib/memories';

jest.mock('next/navigation', () => ({ useRouter: () => ({ push: jest.fn() }) }));
jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
jest.mock('@/lib/harness', () => ({ gwHeaders: () => ({}), listCustom: jest.fn(async () => []) }));
jest.mock('../setup/settingsModel', () => ({
  plain: (e: unknown, f: string) => (e instanceof Error && e.message ? e.message : f),
  plural: (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`,
}));

import { harnessFetch } from '@/lib/hfetch';
import { MemoryLayer, memorySummary } from './MemoryLayer';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let root: Root; let el: HTMLElement;
const flush = async () => { for (let i = 0; i < 14; i++) await act(async () => { await Promise.resolve(); }); };
const button = (t: string) => Array.from(el.querySelectorAll('button')).find((b) => (b.textContent || '').trim() === t) as HTMLButtonElement | undefined;
const H = 'chrn_a';
const row = (id: string, name: string, write: boolean, def = false) => ({ id, name, description: '', records: { count: 3 }, privileges: write ? ['read', 'write'] : ['read'], default: def });
function backend(o: { data: ReturnType<typeof row>[]; def?: string | null; observe?: boolean; providers?: Provider[]; all?: ReturnType<typeof memory>[] }) {
  const state = { default_memory_id: o.def ?? null, observe: o.observe ?? true };
  const s = service({
    'GET /v1/memories/providers': { data: o.providers || [CAPS.graphiti] },
    'GET /v1/memories': { data: o.all || [memory({ id: 'm1', name: 'Brand kits' }), memory({ id: 'm2', name: 'Support' })] },
    [`GET /v1/harnesses/${H}/memories`]: () => ({ object: 'harness.memories', principal: `member:${H}`, ...state, data: o.data }),
    [`PUT /v1/harnesses/${H}/memories`]: (c: { body: object }) => { Object.assign(state, c.body); return { object: 'harness.memories', principal: `member:${H}`, ...state, data: o.data }; },
    'GET /v1/memories/m1/schema': { types: [{ name: 'Company' }], relations: [] },
    'GET /v1/memories/m2/schema': { types: [], relations: [] },
    'POST /v1/memories/m1/grants': { id: 'g' }, 'POST /v1/memories/m2/grants': { id: 'g' },
    'GET /v1/memories/m1/grants': { data: [{ id: 'g1', memory_id: 'm1', principal: `member:${H}`, privileges: ['read'], inherited: false }] },
    'DELETE /v1/memories/m1/grants/g1': { deleted: true },
  });
  (harnessFetch as jest.Mock).mockImplementation(s.fetcher);
  return s;
}
async function draw() { await act(async () => { root.render(<MemoryLayer hid={H} name="Photo cut" />); }); await flush(); }
beforeEach(() => { el = document.createElement('div'); el.id = 'hrui'; document.body.appendChild(el); root = createRoot(el); });
afterEach(() => { act(() => root.unmount()); el.remove(); jest.clearAllMocks(); });

test('each memory says its access and which is the default, from what was read', async () => {
  backend({ data: [row('m1', 'Brand kits', true, true), row('m2', 'Support', false)], def: 'm1' });
  await draw();
  const rows = Array.from(el.querySelectorAll('.mm-hr'));
  expect(rows[0].querySelector('b')?.textContent).toBe('Brand kitsDefault');
  expect(rows[0].querySelector('small')?.textContent).toBe('1 type · 3 records · Graphiti');
  expect((rows[0].querySelector('select') as HTMLSelectElement).value).toBe('w');
  expect((rows[1].querySelector('select') as HTMLSelectElement).value).toBe('r');
});
test('giving a memory is a read grant to the setup’s principal', async () => {
  const s = backend({ data: [row('m1', 'Brand kits', false)] });
  await draw();
  await act(async () => { button('Give a memory')!.click(); });
  await act(async () => { (el.querySelector('.mm-give-r') as HTMLButtonElement).click(); });
  await flush();
  expect(s.sent('POST', '/v1/memories/m2/grants')[0].body).toEqual({ principal: `member:${H}`, privileges: ['read'] });
});
test('the first memory it can write becomes its default', async () => {
  const s = backend({ data: [row('m1', 'Brand kits', false)] });
  await draw();
  const sel = el.querySelector('.mm-hr select') as HTMLSelectElement;
  await act(async () => { sel.value = 'w'; sel.dispatchEvent(new Event('change', { bubbles: true })); });
  await flush();
  expect(s.sent('POST', '/v1/memories/m1/grants')[0].body).toEqual({ principal: `member:${H}`, privileges: ['read', 'write'] });
  expect(s.sent('PUT', `/v1/harnesses/${H}/memories`)[0].body).toEqual({ default_memory_id: 'm1' });
});
test('removing takes away the grant on that memory', async () => {
  const s = backend({ data: [row('m1', 'Brand kits', false)] });
  await draw();
  await act(async () => { (el.querySelector('button[aria-label="Remove Brand kits"]') as HTMLButtonElement).click(); });
  await flush();
  expect(s.sent('DELETE', '/v1/memories/m1/grants/g1')).toHaveLength(1);
});
test('keeping tasks needs a default, and says what the provider really does with them', async () => {
  backend({ data: [row('m1', 'Brand kits', false)] });
  await draw();
  expect((el.querySelector('button.tog') as HTMLButtonElement).disabled).toBe(true);
  expect(el.textContent).toContain('Needs a default memory: one it can write.');
  await act(async () => { root.unmount(); }); root = createRoot(el);
  const s = backend({ data: [row('m1', 'Brand kits', true, true)], def: 'm1', observe: false });
  await draw();
  expect(el.textContent).toContain('Each task is kept in Brand kits as an episode, so later tasks can recall it.');
  await act(async () => { (el.querySelector('button.tog') as HTMLButtonElement).click(); });
  await flush();
  expect(s.sent('PUT', `/v1/harnesses/${H}/memories`)[0].body).toEqual({ observe: true });
  await act(async () => { root.unmount(); }); root = createRoot(el);
  backend({ data: [row('m1', 'Kept', true, true)], def: 'm1', providers: [CAPS.mem0], all: [memory({ id: 'm1', name: 'Kept', provider: 'mem0' })] });
  await draw();
  expect(el.textContent).toContain('Mem0 pulls what matters out of each task and keeps it in Kept');
  expect(el.textContent).not.toContain('as an episode');
});
test('a default whose provider keeps no tasks: nothing to turn on, so no row', async () => {
  const { observe: _o, ...rest } = CAPS.graphiti;
  backend({ data: [row('m1', 'Brand kits', true, true)], def: 'm1', providers: [rest as Provider] });
  await draw();
  expect(el.querySelector('button.tog')).toBeNull();
});
test('the layers list says it plainly', () => {
  const base = { object: 'harness.memories' as const, principal: 'x', default_memory_id: null, observe: true };
  expect(memorySummary({ ...base, data: [] })).toBe('None');
  expect(memorySummary({ ...base, data: [row('a', 'A', true)] as never })).toBe('1 memory');
  expect(memorySummary({ ...base, default_memory_id: 'a', data: [row('a', 'A', true), row('b', 'B', false)] as never })).toBe('2 memories · keeps tasks');
  expect(memorySummary(null)).toBe('');
});
