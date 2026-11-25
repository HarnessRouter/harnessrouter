/** @jest-environment jsdom */
// The model menu on a harness names the key a task on THAT harness runs through (#696): it asks for the
// key with the harness's own base, never the instance-wide key for the model, which a harness that
// speaks one provider's API may not be able to use.
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
const mockConnectionFor = jest.fn((_m: string, _b?: string): null | { name: string; provider: string } => null);
jest.mock('@/lib/providers', () => ({ providerById: () => null, useModelProviders: () => ({ connectionFor: mockConnectionFor }) }));
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
  mockConnectionFor.mockReset();
  mockConnectionFor.mockImplementation((m: string, b?: string) => (m === 'glm-5.3' && b === 'hermes' ? { name: 'Mine', provider: 'zai' } : null));
  el = document.createElement('div');
  document.body.appendChild(el);
  root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); el.remove(); });

test('the model menu asks for each model\'s key with the harness\'s own base, and names that key', async () => {
  await open(H());
  await act(async () => { pill().click(); });
  await flush();
  expect(mockConnectionFor).toHaveBeenCalledWith('glm-5.3', 'hermes');
  expect(mockConnectionFor.mock.calls.every(([, b]) => b === 'hermes')).toBe(true);
  const opts = Array.from(document.querySelectorAll('[role="option"]')).map((o) => o.textContent || '');
  expect(opts.find((t) => t.includes('glm-5.3'))).toContain('your zai key');
  expect(opts.find((t) => t.includes('kimi-k3'))).not.toContain('your');
});
