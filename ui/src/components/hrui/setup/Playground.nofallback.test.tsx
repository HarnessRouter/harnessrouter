/** @jest-environment jsdom */
// A test's composer sends what the person chose, nothing in its place (Richard 10-19: no fallbacks):
// a file alone goes with no words put in the person's mouth; a setup with no model of its own sends no
// model (the server runs it on its default); a past task goes on with no model named until its record
// says which (server side it keeps its last model); a model that cannot run now stays chosen and says
// so instead of being swapped; and a catalog that could not be read is said, with Try again.
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

test('a file alone is sent with no words: nothing is put in the person\'s mouth', async () => {
  await open(H({ defaultModel: 'gpt-5.4' }));
  const input = el.querySelector('input[aria-label="file"]') as HTMLInputElement;
  const f = new File(['png'], 'shelf.png', { type: 'image/png' });
  Object.defineProperty(input, 'files', { value: [f], configurable: true });
  await act(async () => { input.dispatchEvent(new Event('change', { bubbles: true })); });
  await flush();
  await act(async () => { run().click(); });
  expect(mockConv.send).toHaveBeenCalledTimes(1);
  expect(mockConv.send.mock.calls[0][0]).toBe('');
  expect((mockConv.send.mock.calls[0][1] as { name: string }[])[0].name).toBe('shelf.png');
});

test('a setup with no model of its own sends none: the pill says its default, and no model is filled in', async () => {
  await open(H({ defaultModel: '' }));
  expect(pill().textContent).toContain('Setup default (gpt-5.4)');
  expect(mockConv.target?.model).toBe('');
});

test('a setup with no model, before the catalog has landed, still sends none (never a model guessed here)', async () => {
  mockCat.read = { value: null, failed: false, retry: jest.fn() };
  await open(H({ defaultModel: '' }));
  expect(pill().textContent).toContain('Setup default');
  expect(mockConv.target?.model).toBe('');
});

test('a past task goes on with no model named until its record says its last one', async () => {
  let answer!: (v: { turns: unknown[] }) => void;
  (loadSessionTurns as jest.Mock).mockImplementation(() => new Promise((r) => { answer = r; }));
  await open(H({ defaultModel: 'gpt-5.4' }), { resume: 'sess_1' });
  // the setup's own model is not sent in the task's place while the record is read
  expect(mockConv.target?.model).toBe('');
  await act(async () => { answer({ turns: [{ id: 'resp_1', _model: 'kimi-k3' }] }); });
  await flush();
  expect(mockConv.target?.model).toBe('kimi-k3');
});

test('a past task whose model cannot run now keeps it and says so; it is never swapped for the default', async () => {
  mockCat.read = { value: CAT(['kimi-k3']), failed: false, retry: jest.fn() };
  (loadSessionTurns as jest.Mock).mockResolvedValue({ turns: [{ id: 'resp_1', _model: 'kimi-k3' }] });
  await open(H({ defaultModel: 'gpt-5.4' }), { resume: 'sess_1' });
  expect(mockConv.target?.model).toBe('kimi-k3');
});

test('a setup whose own model cannot run now keeps it and says so on the pill, never swapped', async () => {
  mockCat.read = { value: CAT(['glm-5.3']), failed: false, retry: jest.fn() };
  await open(H({ defaultModel: 'glm-5.3' }));
  expect(mockConv.target?.model).toBe('glm-5.3');
  expect(pill().textContent).toContain('can’t run now');
});

test('a failed read of the task\'s turns is read again, never taken as "no turns"', async () => {
  jest.useFakeTimers({ doNotFake: ['queueMicrotask', 'nextTick'] });
  try {
    (loadSessionTurns as jest.Mock).mockRejectedValueOnce(new Error('502')).mockResolvedValueOnce({ turns: [{ id: 'resp_1', _model: 'glm-5.3' }] });
    await open(H({ defaultModel: 'gpt-5.4' }), { resume: 'sess_1' });
    expect(mockConv.target?.model).toBe('');
    await act(async () => { jest.advanceTimersByTime(2000); });
    await flush();
    expect(loadSessionTurns).toHaveBeenCalledTimes(2);
    expect(mockConv.target?.model).toBe('glm-5.3');
  } finally { jest.useRealTimers(); }
});

test('models that could not be read are said in the picker, with Try again', async () => {
  const retry = jest.fn();
  mockCat.read = { value: null, failed: true, retry };
  await open(H({ defaultModel: 'gpt-5.4' }));
  await act(async () => { pill().click(); });
  await flush();
  const line = Array.from(document.querySelectorAll('[role="alert"]')).find((x) => x.textContent?.includes('The models could not be read just now.'));
  expect(line).toBeTruthy();
  await act(async () => { (line!.querySelector('button') as HTMLButtonElement).click(); });
  expect(retry).toHaveBeenCalled();
});

test('a task whose record could not be read says so, with Try again, and takes no message', async () => {
  mockConv.loadFailed = true;
  await open(H({ defaultModel: 'gpt-5.4' }), { resume: 'sess_1' });
  const line = el.querySelector('.pg-opening [role="alert"]');
  expect(line?.textContent).toBe('This task could not be read just now. Try again');
  await act(async () => { (line?.querySelector('button') as HTMLButtonElement).click(); });
  expect(mockConv.reload).toHaveBeenCalled();
});
