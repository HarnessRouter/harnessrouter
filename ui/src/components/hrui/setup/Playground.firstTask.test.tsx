/** @jest-environment jsdom */
// The task a setup was made with runs as its page opens (New setup: the sentence the person sent there is
// what they asked to see run; Richard 10-22, the flow went on to an empty task): once, on the setup's own
// model, as soon as that model is known to run; a model no provider serves leaves it in the box instead;
// a past task never takes it.
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
jest.mock('reifyui/agent-chat', () => ({
  AgentConversation: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
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
import { peekFirstTask, setFirstTask } from '../start/seed';

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
const pill = () => el.querySelector('.pg-opts .nw-pk') as HTMLButtonElement;
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

test('the first task runs as the new setup\'s page opens, once', async () => {
  setFirstTask('chrn_t', 'Generate a product image for our store');
  await open(H({ defaultModel: 'gpt-5.4' }));
  expect(mockConv.send).toHaveBeenCalledTimes(1);
  expect(mockConv.send.mock.calls[0]).toEqual(['Generate a product image for our store', []]);
  expect(mockConv.target?.model).toBe('gpt-5.4');           // on the model chosen when it was made
  expect(peekFirstTask('chrn_t')).toBe('');                  // handed over: a reopen never runs it again
  await act(async () => { root.render(<div />); });
  await open(H({ defaultModel: 'gpt-5.4' }));
  expect(mockConv.send).toHaveBeenCalledTimes(1);
});

test('it waits while the model is still being checked, then runs', async () => {
  mockCat.read = { value: null, failed: false, retry: jest.fn() };
  setFirstTask('chrn_t', 'Review this contract');
  await open(H({ defaultModel: 'gpt-5.4' }));
  expect(mockConv.send).not.toHaveBeenCalled();
  expect(peekFirstTask('chrn_t')).toBe('Review this contract');
  mockCat.read = { value: CAT(), failed: false, retry: jest.fn() };
  await open(H({ defaultModel: 'gpt-5.4' }));
  expect(mockConv.send).toHaveBeenCalledTimes(1);
  expect(mockConv.send.mock.calls[0][0]).toBe('Review this contract');
});

test('a model no provider serves leaves it in the box, sent by nobody', async () => {
  mockCat.read = { value: CAT(['gpt-5.4']), failed: false, retry: jest.fn() };
  setFirstTask('chrn_t', 'Check this user message');
  await open(H({ defaultModel: 'gpt-5.4' }));
  expect(mockConv.send).not.toHaveBeenCalled();
  expect(box()).toBe('Check this user message');
});

test('a past task never takes it, and a setup with none sends nothing', async () => {
  setFirstTask('chrn_t', 'not for an old task');
  await open(H({ defaultModel: 'gpt-5.4' }), { key: 'old', resume: 'hsess_old' });
  expect(mockConv.send).not.toHaveBeenCalled();
  expect(peekFirstTask('chrn_t')).toBe('not for an old task');
  sessionStorage.clear();
  await act(async () => { root.render(<div />); });
  await open(H({ id: 'chrn_other', defaultModel: 'gpt-5.4' } as never));
  expect(mockConv.send).not.toHaveBeenCalled();
});
