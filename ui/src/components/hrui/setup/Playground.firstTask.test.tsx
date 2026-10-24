/** @jest-environment jsdom */
// A new setup's first task (start/build.ts), as the hosted console draws it: its save card at the top
// (start/Assembly), the request the build wrote waiting in the box, never sent for the person (Richard
// 2026-10-19, "Ready in the box"), not even once the model is known to run; held while the save goes
// on, and the rest of a save that did not answer said under the card with Try again. A past task never
// takes it, and the sentence the person wrote in New setup is never what is sent.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { CustomHarness, ModelCatalog } from '@/lib/harness';

const mockConv = { send: jest.fn(async (_t: string, _f: unknown[]) => true), target: null as null | { model?: string }, loadFailed: false, reload: jest.fn() };
jest.mock('@/lib/conversation', () => ({
  isInternalOutput: () => false,
  useHarnessBus: () => {},
  useConversationTurn: (o: { target: { model?: string } }) => {
    mockConv.target = o.target;
    return {
      msgs: [], busy: false, stopping: false, liveSessionId: '',
      send: (t: string, f: unknown[]) => { mockConv.send(t, f); return Promise.resolve(true); },
      stop: () => {}, setMsgs: () => {}, loadFailed: mockConv.loadFailed, reload: mockConv.reload,
    };
  },
}));
jest.mock('@/lib/chat', () => ({ loadSessionTurns: jest.fn(async () => ({ turns: [] })) }));
const mockCat: { read: { value: ModelCatalog | null; failed: boolean; retry: jest.Mock } } = { read: { value: null, failed: false, retry: jest.fn() } };
jest.mock('@/lib/harness', () => ({
  ...jest.requireActual('@/lib/harness'),
  useModelCatalogRead: () => mockCat.read,
  oobModels: () => (mockCat.read.value ? mockCat.read.value.hermes.models : []),
  oobDefaultModel: () => (mockCat.read.value ? mockCat.read.value.hermes.default : ''),
  modelAvailability: (_b: string, m: string) => (!mockCat.read.value ? 'unknown' : mockCat.read.value.hermes.unavailable.includes(m) ? 'no' : 'yes'),
}));
jest.mock('@/lib/providers', () => ({ providerById: () => null, useModelProviders: () => ({ connectionFor: () => null }) }));
jest.mock('../toast', () => ({ toast: jest.fn() }));
jest.mock('../Skel', () => ({ Skel: () => null, SkLine: () => null, SkThread: () => null }));
jest.mock('../start/prompts', () => ({ API_BASE: 'https://box.example/api/harness' }));
jest.mock('./TaskThread', () => ({ Md: () => null }));
jest.mock('./AgentTurns', () => ({ AgentTurns: () => null, harnessMark: () => ({ mark: null, motion: null }) }));
jest.mock('./TurnFiles', () => ({ FileCards: () => null, filesOf: () => [] }));
const mockBuild: { b: unknown } = { b: null };
jest.mock('../start/build', () => ({ useBuildOf: () => mockBuild.b, noteFirstSid: jest.fn(), retryBuild: jest.fn() }));
jest.mock('reifyui/agent-chat', () => ({
  AgentConversation: ({ children, composer }: { children?: React.ReactNode; composer?: React.ReactNode }) => <div>{children}{composer}</div>,
  AgentComposer: (p: { value: string; onChange: (v: string) => void; onSend: () => void; sendDisabled?: boolean; onAttachFiles: (f: File[]) => void; left?: React.ReactNode }) => (
    <div className="composer">
      <textarea aria-label="message" value={p.value} onChange={(e) => p.onChange(e.target.value)} />
      <input aria-label="file" type="file" onChange={(e) => p.onAttachFiles(Array.from(e.target.files || []))} />
      <button type="button" className="run" disabled={p.sendDisabled} onClick={p.onSend}>Run task</button>
      {p.left}
    </div>
  ),
}), { virtual: true });

import { loadSessionTurns } from '@/lib/chat';
import { rowOf } from '../setups';
import { Playground, type Slot } from './Playground';
import { retryBuild } from '../start/build';
import type { Build } from '../start/build';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const CAT = (unavailable: string[] = []): ModelCatalog => ({ hermes: { default: 'gpt-5.4', models: ['gpt-5.4', 'glm-5.3', 'kimi-k3'], unavailable } });
const H = (o: Partial<CustomHarness> = {}) => ({ id: 'chrn_t', name: 'Support', base: 'hermes', defaultModel: '', systemPrompt: '', mcpServers: [], skills: [], createdAt: 1, ...o }) as unknown as CustomHarness;

let root: Root;
let el: HTMLElement;
const flush = async () => { for (let i = 0; i < 8; i++) await act(async () => { await Promise.resolve(); }); };
async function open(h: CustomHarness, slot: Partial<Slot> = {}) {
  await act(async () => {
    root.render(<Playground r={rowOf(h, 'Hermes', [], false)} onRan={() => {}} onBorn={() => {}} onPreview={() => {}}
      slot={{ key: 'k1', resume: null, ...slot }} />);
  });
  await flush();
}
const run = () => el.querySelector('button.run') as HTMLButtonElement;

beforeEach(() => {
  sessionStorage.clear();
  mockCat.read = { value: CAT(), failed: false, retry: jest.fn() };
  mockConv.send.mockClear();
  mockConv.loadFailed = false;
  mockConv.reload.mockClear();
  (loadSessionTurns as jest.Mock).mockReset();
  (loadSessionTurns as jest.Mock).mockResolvedValue({ turns: [] });
  el = document.createElement('div');
  el.id = 'hrui';
  document.body.appendChild(el);
  root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); el.remove(); });


const box = () => (el.querySelector('textarea[aria-label="message"]') as HTMLTextAreaElement).value;
const FIRST = { input: 'Please review the payment and change order clauses and redline them.', send: false, free: false, setup: true };
const CFG = { name: 'Contract redlines', instructions: 'You review each construction contract a user sends.', exampleTask: FIRST.input,
  base: 'hermes', baseName: 'Hermes', model: 'gpt-5.4', skills: [], plugins: [], connectionsNeeded: [] };
const BUILD = (o: Partial<Build>): Build => ({ key: 'bk1', at: 0, job: 'the sentence', pick: { baseName: '', model: '' }, phase: 'done', step: '',
  asm: { cfg: CFG, savedAt: 1, plugins: {}, done: true }, id: 'chrn_t', first: { input: FIRST.input, send: false, free: false }, recording: null,
  firstSid: '', demo: null, error: '', ...o });
beforeEach(() => { mockBuild.b = null; (retryBuild as jest.Mock).mockClear(); });

test('the request the build wrote waits in the box under the save card, and nothing is sent for the person', async () => {
  mockBuild.b = BUILD({});
  await open(H({ defaultModel: 'gpt-5.4' }), { key: 'n0', first: FIRST });
  expect(box()).toBe(FIRST.input);
  expect(el.querySelector('.bs-save')?.textContent).toContain('Setup saved.');
  expect(mockConv.send).not.toHaveBeenCalled();
  expect(run().disabled).toBe(false);
  await act(async () => { run().click(); });
  await flush();
  expect(mockConv.send).toHaveBeenCalledTimes(1);
  expect(mockConv.send.mock.calls[0]).toEqual([FIRST.input, []]);
  expect(mockConv.target?.model).toBe('gpt-5.4');
});

test('while the save goes on, its request is held under the card', async () => {
  mockBuild.b = BUILD({ phase: 'saving', asm: { cfg: CFG, savedAt: null, plugins: {}, done: false } });
  await open(H({ defaultModel: 'gpt-5.4' }), { key: 'n0', first: FIRST });
  expect(el.querySelector('.bs-save')?.textContent).toContain('Saving your setup');
  expect(run().disabled).toBe(true);
});

test('the rest of a save that did not answer is said under the card, with Try again', async () => {
  mockBuild.b = BUILD({ phase: 'failed', error: 'Your setup couldn’t be finished just now.' });
  await open(H({ defaultModel: 'gpt-5.4' }), { key: 'n0', first: FIRST });
  expect(el.querySelector('.bd-fail')?.textContent).toContain('Your setup couldn’t be finished just now.');
  const again = Array.from(el.querySelectorAll('.bd-fail button')).find((b) => b.textContent === 'Try again') as HTMLButtonElement;
  act(() => { again.click(); });
  expect(retryBuild).toHaveBeenCalledWith('bk1');
  expect(run().disabled).toBe(true);
});

test('a past task never takes it, and a new task without one starts empty', async () => {
  mockBuild.b = BUILD({});
  await open(H({ defaultModel: 'gpt-5.4' }), { key: 'old', resume: 'hsess_old' });
  expect(mockConv.send).not.toHaveBeenCalled();
  await act(async () => { root.render(<div />); });
  mockBuild.b = null;
  await open(H({ defaultModel: 'gpt-5.4' }), { key: 'n1' });
  expect(box()).toBe('');
  expect(mockConv.send).not.toHaveBeenCalled();
});
