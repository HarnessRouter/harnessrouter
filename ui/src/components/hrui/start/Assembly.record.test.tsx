/** @jest-environment jsdom */
// A new setup's save card shows what was saved, read again from the setup's record (the memories walkthrough, 11-09:
// the card kept the name and the plugins the build proposed after Settings changed them), and one line for its memory,
// "Memory: <Engine>, <why>", with Change: the four engines and None (the memories spec, C1).
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { CustomHarness } from '@/lib/harness';
import { service } from '../memories/fixtures';
import { CAPS } from '../memories/fixtures';

jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
jest.mock('@/lib/plugs', () => ({ listPlugs: jest.fn(async () => ({ plugs: [] })) }));
jest.mock('../toast', () => ({ toast: jest.fn() }));

import { harnessFetch } from '@/lib/hfetch';
import { rowOf } from '../setups';
import { Assembly, withRecord, type AssemblyState } from './Assembly';
import { readRecord } from './compose';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const CFG = { name: 'Personalized customer support', instructions: 'You serve customers.', exampleTask: 'Hi', base: 'hermes', baseName: 'Hermes', model: 'gpt-5.4',
  skills: [], plugins: [{ id: 'm365', name: 'Microsoft 365' }], connectionsNeeded: [{ id: 'insforge', name: 'InsForge' }] };
const SAVED: AssemblyState = { cfg: CFG, savedAt: 1, plugins: { m365: 'on' }, done: true };
const H = (o: Partial<CustomHarness> = {}) => ({ id: 'chrn_t', name: 'ux-walk-support', base: 'hermes', defaultModel: 'gpt-5.4', systemPrompt: 'You serve customers well.', mcpServers: [], skills: [], createdAt: 1, ...o }) as unknown as CustomHarness;

test('once saved, the card is the record: its name, instructions and model as they stand now', () => {
  const s = withRecord(SAVED, rowOf(H(), 'Hermes', [], false));
  expect(s.cfg.name).toBe('ux-walk-support');
  expect(s.cfg.instructions).toBe('You serve customers well.');
  expect(s.hid).toBe('chrn_t');
});

test('a plugin taken away in Settings leaves the card; while the save goes on nothing is taken away', () => {
  const row = { ...rowOf(H(), 'Hermes', [], false), binding: null, added: { plugins: [{ kind: 'plug' as const, key: 'plug:insforge', type: 'insforge', on: true as const }], skills: [], tools: [] } };
  const done = withRecord(SAVED, row);
  expect(done.cfg.plugins).toEqual([]);
  expect(done.cfg.connectionsNeeded.map((p) => p.name)).toEqual(['InsForge']);
  const saving = withRecord({ ...SAVED, done: false }, row);
  expect(saving.cfg.plugins.map((p) => p.name)).toEqual(['Microsoft 365']);
});

describe('the memory line', () => {
  let root: Root; let el: HTMLElement;
  const flush = async () => { for (let i = 0; i < 12; i++) await act(async () => { await Promise.resolve(); }); };
  beforeEach(() => { el = document.createElement('div'); el.id = 'hrui'; document.body.appendChild(el); root = createRoot(el); });
  afterEach(() => { act(() => root.unmount()); el.remove(); });
  const OWN = { id: 'hmem_a', name: 'ux-walk-support', engine: 'mem0', scope: 'per_user', reason: 'It serves people, so it keeps each person’s facts and preferences, separately per person.' };

  test('saved: the engine and why, read from the harness, and Change offers the four engines and None', async () => {
    let mem: unknown = OWN;
    const s = service({
      'GET /v1/harnesses/chrn_t': () => ({ id: 'chrn_t', memory: mem }),
      'PUT /v1/harnesses/chrn_t/memory': (c: { body: { memory?: unknown } }) => { mem = c.body?.memory === 'none' ? null : mem; return { id: 'chrn_t', memory: mem, memory_reason: 'Turned off here.' }; },
      'GET /v1/memories/providers': { data: [CAPS.mem0, CAPS.graphiti] },
      'GET /v1/harnesses/chrn_t/memories': { object: 'harness.memories', principal: 'member:chrn_t', default_memory_id: null, observe: false, data: [] },
    });
    (harnessFetch as jest.Mock).mockImplementation(s.fetcher);
    await act(async () => { root.render(<Assembly s={withRecord(SAVED, rowOf(H(), 'Hermes', [], false))} />); });
    await flush();
    expect(el.querySelector('.am-line')?.textContent).toBe('Memory: Mem0, it serves people, so it keeps each person’s facts and preferences, separately per person. Change');
    await act(async () => { (el.querySelector('.am-line button') as HTMLButtonElement).click(); });
    expect(Array.from(el.querySelectorAll('.am-pop .mm-mi b')).map((b) => b.textContent)).toEqual(['Mem0', 'Graphiti', 'Hindsight', 'ReMe', 'None']);
    await act(async () => { (Array.from(el.querySelectorAll('.am-pop .mm-mi')).find((b) => b.textContent?.startsWith('None')) as HTMLButtonElement).click(); });
    await flush();
    expect(s.sent('PUT', '/v1/harnesses/chrn_t/memory')[0].body).toEqual({ memory: 'none' });
    expect(el.querySelector('.am-line')?.textContent).toBe('Memory: None, turned off here. Change');
  });

  test('a service before 0.40 says nothing of an agent’s memory, and the card draws no line', async () => {
    const s = service({ 'GET /v1/harnesses/chrn_t': { id: 'chrn_t', name: 'x' } });
    (harnessFetch as jest.Mock).mockImplementation(s.fetcher);
    await act(async () => { root.render(<Assembly s={withRecord(SAVED, rowOf(H(), 'Hermes', [], false))} />); });
    await flush();
    expect(el.querySelector('.am-line')).toBeNull();
  });

  test('the build’s record, as the service writes it while it saves, draws the proposed line', async () => {
    const raw = { key: 'k-build-1', status: 'building', step: 'saving',
      config: { name: CFG.name, instructions: CFG.instructions, base: 'hermes', model: 'gpt-5.4', skills: [], plugins: [], connectionsNeeded: [],
        memoryHint: 'each customer’s plan', memory: { engine: 'graphiti', scope: 'shared', reason: 'It tracks people, things and how they relate over time.' } } };
    const rec = readRecord(raw, { base: 'auto', model: 'auto', baseName: '' });
    await act(async () => { root.render(<Assembly s={{ cfg: rec!.config!, savedAt: null, plugins: {}, done: false }} />); });
    expect(el.querySelector('.am-line')?.textContent).toBe('Memory: Graphiti, it tracks people, things and how they relate over time.');
    // none running: the service's reason, with no engine
    const none = readRecord({ ...raw, config: { ...raw.config, memory: { engine: null, scope: 'per_user', reason: 'No memory engine is running here; one command starts them: deploy/memories/up.sh' } } },
      { base: 'auto', model: 'auto', baseName: '' });
    await act(async () => { root.render(<Assembly s={{ cfg: none!.config!, savedAt: null, plugins: {}, done: false }} />); });
    expect(el.querySelector('.am-line')?.textContent).toBe('Memory: None, no memory engine is running here; one command starts them: deploy/memories/up.sh');
  });

  test('before the harness exists, the line is what the build proposes, with nothing to change yet', async () => {
    await act(async () => { root.render(<Assembly s={{ cfg: { ...CFG, memory: { memory: { ...OWN, engine: 'graphiti', scope: 'shared', reason: 'It tracks people, things and how they relate over time.' }, reason: '' } }, savedAt: null, plugins: {}, done: false }} />); });
    expect(el.querySelector('.am-line')?.textContent).toBe('Memory: Graphiti, it tracks people, things and how they relate over time.');
    expect(el.querySelector('.am-line button')).toBeNull();
  });
});
