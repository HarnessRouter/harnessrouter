/** @jest-environment jsdom */
// The Next bar (start/NextBar) ends a new setup's first test once it has run: the first test New setup
// handed over (live, or an unchanged demo's recorded run played when its request is sent), the
// setup's recorded first task opened from its row, and the handed first test reopened by its task.
// Never while a turn runs, never before an answer has finished, never under any other task.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { CustomHarness, ModelCatalog } from '@/lib/harness';
import type { AsstMsg, Msg } from '@/lib/conversation';
import type { RecordedRun } from '../start/recorded';
import type { Build } from '../start/build';

const mockConv = { msgs: [] as Msg[], busy: false, replay: jest.fn(() => () => {}) };
jest.mock('@/lib/conversation', () => ({
  isInternalOutput: () => false,
  useHarnessBus: () => {},
  useConversationTurn: () => ({
    msgs: mockConv.msgs, busy: mockConv.busy, stopping: false, liveSessionId: '',
    send: async () => true, replay: (...a: unknown[]) => (mockConv.replay as (...x: unknown[]) => unknown)(...a),
    stop: () => {}, setMsgs: () => {}, loadFailed: false, reload: () => {},
  }),
}));
jest.mock('@/lib/chat', () => ({ loadSessionTurns: jest.fn(async () => ({ turns: [] })) }));
jest.mock('@/lib/harness', () => ({
  ...jest.requireActual('@/lib/harness'),
  useModelCatalogRead: () => ({ value: { hermes: { default: 'gpt-5.4', models: ['gpt-5.4'], unavailable: [] } } as ModelCatalog, failed: false, retry: () => {} }),
  oobModels: () => ['gpt-5.4'],
  oobDefaultModel: () => 'gpt-5.4',
  modelAvailability: () => 'yes',
}));
jest.mock('@/lib/providers', () => ({ providerById: () => null, useModelProviders: () => ({ connectionFor: () => null }) }));
jest.mock('../toast', () => ({ toast: jest.fn() }));
jest.mock('../Skel', () => ({ Skel: () => null, SkLine: () => null, SkThread: () => null }));
jest.mock('../start/prompts', () => ({ API_BASE: 'https://box.example/api/harness' }));
jest.mock('../start/fork', () => ({
  inputHistory: async () => false, forkOffered: () => false, forkFiles: jest.fn(async () => []),
  forkInput: () => [], importedFirst: () => true, noteFork: jest.fn(),
}));
const mockBuild: { b: Build | null } = { b: null };
jest.mock('../start/build', () => ({ useBuildOf: () => mockBuild.b, noteFirstSid: jest.fn(), retryBuild: jest.fn() }));
jest.mock('./TaskThread', () => ({ Md: () => null }));
jest.mock('./AgentTurns', () => ({ AgentTurns: () => null, harnessMark: () => ({ mark: null, motion: null }) }));
jest.mock('./TurnFiles', () => ({ FileCards: () => null, filesOf: () => [] }));
jest.mock('reifyui/agent-chat', () => ({
  AgentConversation: ({ children, composer }: { children?: React.ReactNode; composer?: React.ReactNode }) => <div>{children}{composer}</div>,
  AgentComposer: (p: { value: string; onChange: (v: string) => void; onSend: () => void; sendDisabled?: boolean }) => (
    <div className="composer">
      <textarea aria-label="message" value={p.value} onChange={(e) => p.onChange(e.target.value)} />
      <button type="button" className="run" disabled={p.sendDisabled} onClick={p.onSend}>Run task</button>
    </div>
  ),
}), { virtual: true });

import { rowOf } from '../setups';
import { Playground, type Slot } from './Playground';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const H = { id: 'chrn_t', name: 'Contract redlines', base: 'hermes', defaultModel: 'gpt-5.4', systemPrompt: 'x', mcpServers: [], skills: [], createdAt: 1 } as unknown as CustomHarness;
const FIRST = { input: 'Redline the payment clause of this contract.', send: false, free: false, setup: true };
const RUN = {
  demo: 1, ranAt: 1792378362430, base: 'hermes', model: 'gpt-5.4', request: 'Review this clause.', durMs: 9_000, status: 'completed',
  events: [{ t: 0, ev: { type: 'response.created' } }, { t: 9_000, ev: { type: 'response.completed' } }], files: [],
  template: { demo: 1, name: 'Contract review', base: 'hermes', model: 'gpt-5.4', instructions: 'x', skills: [], plugins: [] },
} as unknown as RecordedRun;
const done = (text: string): Msg[] => [
  { role: 'user', text },
  { role: 'assistant', blocks: [{ kind: 'text', text: 'Done.' }], files: [], status: 'done', clock: { startedAt: 0, endedAt: 9_000 } as AsstMsg['clock'] },
];
const BUILD = (o: Partial<Build> = {}): Build => ({ key: 'bk1', at: 0, job: 'the sentence', pick: { baseName: '', model: '' }, phase: 'done', step: '',
  asm: null, id: 'chrn_t', first: { input: FIRST.input, send: false, free: false }, recording: null, firstSid: '', demo: null, error: '', ...o });

let root: Root;
let el: HTMLElement;
const flush = async () => { for (let i = 0; i < 8; i++) await act(async () => { await Promise.resolve(); }); };
async function open(slot: Partial<Slot>, handedRec: RecordedRun | null = null) {
  await act(async () => {
    root.render(<Playground r={rowOf(H, 'Hermes', [], false)} onRan={() => {}} onBorn={() => {}} onPreview={() => {}}
      slot={{ key: 'k1', resume: null, ...slot }} handedRec={handedRec} />);
  });
  await flush();
}
const bar = () => el.querySelector('.bs-next.nx2');

beforeEach(() => {
  mockConv.msgs = [];
  mockConv.busy = false;
  mockBuild.b = null;
  el = document.createElement('div');
  el.id = 'hrui';
  document.body.appendChild(el);
  root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); el.remove(); });

test('the first test New setup handed over ends in the Next bar once its answer has finished', async () => {
  mockBuild.b = BUILD();
  await open({ key: 'n0', first: FIRST });
  expect(bar()).toBeNull();                                   // nothing has run yet
  mockConv.msgs = done(FIRST.input);
  mockConv.busy = true;
  await open({ key: 'n0', first: FIRST });
  expect(bar()).toBeNull();                                   // still running
  mockConv.busy = false;
  mockConv.msgs = [done(FIRST.input)[0], { ...(done(FIRST.input)[1] as AsstMsg), status: 'running' }];
  await open({ key: 'n0', first: FIRST });
  expect(bar()).toBeNull();                                   // its answer has not finished
  mockConv.msgs = done(FIRST.input);
  await open({ key: 'n0', first: FIRST });
  expect(bar()).not.toBeNull();
  expect(bar()?.querySelector('.nx-setup b')?.textContent).toBe('Contract redlines');
  expect(bar()?.querySelector('button')?.textContent).toBe('Connect your app');
  expect(bar()?.textContent).not.toContain('Cloud');
});

test('an unchanged demo’s recorded run, played when its request was sent, ends in it too', async () => {
  mockBuild.b = BUILD({ recording: RUN });
  mockConv.msgs = done(RUN.request);
  await open({ key: 'n0', first: { ...FIRST, input: RUN.request } }, RUN);
  expect(bar()).not.toBeNull();
});

test('the setup’s recorded first task opened from its row ends in it', async () => {
  mockConv.msgs = done(RUN.request);
  await open({ key: 'rec', recorded: RUN });
  expect(bar()).not.toBeNull();
});

test('the handed first test reopened by its task ends in it; any other task does not', async () => {
  mockBuild.b = BUILD({ firstSid: 'hsess_first' });
  mockConv.msgs = done(FIRST.input);
  await open({ key: 'r1', resume: 'hsess_first' });
  expect(bar()).not.toBeNull();
  await open({ key: 'r2', resume: 'hsess_other' });
  expect(bar()).toBeNull();
  mockBuild.b = null;
  await open({ key: 'n2' });                                  // a new test of the person's own
  expect(bar()).toBeNull();
});
