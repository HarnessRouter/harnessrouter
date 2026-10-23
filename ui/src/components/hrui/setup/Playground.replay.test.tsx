/** @jest-environment jsdom */
// A setup's recorded first task (start/replay.ts) plays in its task, never sent: right after New setup
// saved it, its request waits in the box like any first test (start/build.ts), and sent as it was
// recorded it plays in proportion, at most REPLAY_MAX_MS long; changed, it runs live. Opened from its
// row, it is drawn whole at once. Its reply says Recorded, with the time the run took when it ran, and
// offers no request that carries on from it (no server holds it). Where the server cannot continue a
// recording (this edition's gateway today), a bar in the composer's place says it is a recorded task,
// with Follow up; a server that says it takes input history gets the box, and a message written there
// goes on as a task of your own carrying the recording.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { CustomHarness, ModelCatalog } from '@/lib/harness';
import type { AsstMsg, Msg } from '@/lib/conversation';
import type { RecordedRun } from '../start/recorded';

const mockConv = {
  msgs: [] as Msg[],
  send: jest.fn(async (_t: string, _f: unknown[], _o?: unknown) => true),
  replay: jest.fn((_text: string, _events: { t: number; ev: unknown }[], _fileOf: (f: unknown) => unknown, _endAt?: number) => () => {}),
  setMsgs: jest.fn(),
};
jest.mock('@/lib/conversation', () => ({
  isInternalOutput: () => false,
  useHarnessBus: () => {},
  useConversationTurn: () => ({
    msgs: mockConv.msgs, busy: false, stopping: false, liveSessionId: '',
    send: (t: string, f: unknown[], o?: unknown) => mockConv.send(t, f, o),
    replay: (...a: Parameters<typeof mockConv.replay>) => mockConv.replay(...a),
    stop: () => {}, setMsgs: mockConv.setMsgs, loadFailed: false, reload: () => {},
  }),
}));
jest.mock('@/lib/chat', () => ({ loadSessionTurns: jest.fn(async () => ({ turns: [] })) }));
const mockCat: { read: { value: ModelCatalog | null; failed: boolean; retry: jest.Mock } } = { read: { value: null, failed: false, retry: jest.fn() } };
jest.mock('@/lib/harness', () => ({
  ...jest.requireActual('@/lib/harness'),
  useModelCatalogRead: () => mockCat.read,
  oobModels: () => ['gpt-5.4'],
  oobDefaultModel: () => 'gpt-5.4',
  modelAvailability: () => 'yes',
}));
jest.mock('@/lib/providers', () => ({ providerById: () => null, useModelProviders: () => ({ connectionFor: () => null }) }));
jest.mock('../toast', () => ({ toast: jest.fn() }));
jest.mock('../Skel', () => ({ Skel: () => null, SkLine: () => null, SkThread: () => null }));
jest.mock('../start/prompts', () => ({ API_BASE: 'https://box.example/api/harness' }));
const mockFork = { history: false };
jest.mock('../start/fork', () => ({
  inputHistory: async () => mockFork.history, forkOffered: () => true, forkFiles: jest.fn(async () => []),
  forkInput: (_r: unknown, answer: string, text: string) => [{ role: 'assistant', content: answer }, { role: 'user', content: text }],
  importedFirst: () => true, noteFork: jest.fn(),
}));
jest.mock('./TaskThread', () => ({ Md: () => null }));
// each answer's foot, as the conversation draws it
jest.mock('./AgentTurns', () => ({
  AgentTurns: ({ msgs, actions }: { msgs: Msg[]; actions: (t: number, m: AsstMsg) => React.ReactNode }) => (
    <div>{msgs.filter((m): m is AsstMsg => m.role === 'assistant').map((m, i) => <div key={i} className="foot">{actions(i, m)}</div>)}</div>
  ),
  harnessMark: () => ({ mark: null, motion: null }),
}));
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
import { REPLAY_MAX_MS } from '../start/replay';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const CAT: ModelCatalog = { hermes: { default: 'gpt-5.4', models: ['gpt-5.4'], unavailable: [] } };
const H = { id: 'chrn_t', name: 'Product images', base: 'hermes', defaultModel: 'gpt-5.4', systemPrompt: '', mcpServers: [], skills: [], createdAt: 1, source: 'demo:0@1792378362430' } as unknown as CustomHarness;
const RUN = {
  demo: 0, ranAt: 1792378362430, base: 'hermes', model: 'gpt-5.4', request: 'Make a product image of a matte black mug.', durMs: 105_166, status: 'completed',
  events: [{ t: 0, ev: { type: 'response.created' } }, { t: 52_000, ev: { type: 'response.output_text.delta', delta: 'Done.' } }, { t: 105_166, ev: { type: 'response.completed' } }],
  files: [{ name: 'output/mug-v3.png', mime: 'image/png', bytes: 3, src: '/demos/product-images/mug-v3.png' }],
  template: { demo: 0, name: 'Product images', base: 'hermes', model: 'gpt-5.4', instructions: 'x', skills: [], plugins: [] },
} as unknown as RecordedRun;
const DONE: Msg[] = [
  { role: 'user', text: RUN.request },
  { role: 'assistant', blocks: [{ kind: 'text', text: 'Done.' }], files: [], status: 'done', clock: { startedAt: 0, endedAt: 15_000 } as AsstMsg['clock'] },
];

let root: Root;
let el: HTMLElement;
const flush = async () => { for (let i = 0; i < 8; i++) await act(async () => { await Promise.resolve(); }); };
const followUp = jest.fn();
async function open(slot: Partial<Slot> = {}, handedRec: RecordedRun | null = null) {
  await act(async () => {
    root.render(<Playground r={rowOf(H, 'Hermes', [], false)} onRan={() => {}} onBorn={() => {}} onPreview={() => {}} onFollowUp={followUp}
      slot={{ key: 'rec', resume: null, recorded: RUN, ...slot }} handedRec={handedRec} />);
  });
  await flush();
}
/** The first test New setup handed over for an unchanged demo: its recorded request, waiting in the box. */
const HANDED: Partial<Slot> = { key: 'n0', recorded: null, first: { input: RUN.request, send: false, free: false, setup: true } };
const box = () => el.querySelector('textarea[aria-label="message"]') as HTMLTextAreaElement;
const typeIn = (t: string) => {
  const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;
  act(() => { set?.call(box(), t); box().dispatchEvent(new Event('input', { bubbles: true })); });
};
const text = () => (el.textContent || '').replace(/\s+/g, ' ');

beforeEach(() => {
  sessionStorage.clear();
  mockCat.read = { value: CAT, failed: false, retry: jest.fn() };
  mockConv.msgs = [];
  mockConv.send.mockClear(); mockConv.replay.mockClear(); mockConv.setMsgs.mockClear(); followUp.mockClear();
  mockFork.history = false;
  el = document.createElement('div'); el.id = 'hrui'; document.body.appendChild(el);
  root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); el.remove(); });

test('right after its save its request waits in the box; sent as recorded it plays in proportion, and nothing is sent', async () => {
  await open(HANDED, RUN);
  expect(box().value).toBe(RUN.request);
  expect(mockConv.replay).not.toHaveBeenCalled();
  await act(async () => { (el.querySelector('button.run') as HTMLButtonElement).click(); });
  await flush();
  expect(mockConv.replay).toHaveBeenCalledTimes(1);
  const [request, events, fileOf, endAt] = mockConv.replay.mock.calls[0];
  expect(request).toBe(RUN.request);
  const speed = RUN.durMs / REPLAY_MAX_MS;
  expect(events.map((e) => Math.round(e.t))).toEqual([0, Math.round(52_000 / speed), Math.round(105_166 / speed)]);
  expect(endAt).toBeCloseTo(REPLAY_MAX_MS, 0);
  // the files it made are its kept copies; one it kept none of is left out
  expect(fileOf({ container_id: 'recorded', file_id: 'recorded-file-1', filename: 'output/mug-v3.png' })).toMatchObject({ url: '/demos/product-images/mug-v3.png' });
  expect(fileOf({ container_id: 'recorded', file_id: 'x', filename: 'other.png' })).toBeNull();
  expect(mockConv.send).not.toHaveBeenCalled();
  // opened again from its row it is drawn whole
  await act(async () => { root.render(<div />); });
  await open({ key: 'rec2' });
  expect(mockConv.replay).toHaveBeenCalledTimes(2);
  const [, again, , end2] = mockConv.replay.mock.calls[1];
  expect(again.every((e) => e.t === 0)).toBe(true);
  expect(end2).toBe(0);
});

test('opened from its row it is drawn whole at once', async () => {
  await open();
  const [, events, , endAt] = mockConv.replay.mock.calls[0];
  expect(events.every((e) => e.t === 0)).toBe(true);
  expect(endAt).toBe(0);
});

test('its request changed is a request of the person’s own: it runs live, not the recording', async () => {
  await open(HANDED, RUN);
  typeIn(`${RUN.request} On a white background.`);
  await act(async () => { (el.querySelector('button.run') as HTMLButtonElement).click(); });
  await flush();
  expect(mockConv.replay).not.toHaveBeenCalled();
  expect(mockConv.send).toHaveBeenCalledTimes(1);
  expect(mockConv.send.mock.calls[0][0]).toBe(`${RUN.request} On a white background.`);
});

test('its reply says Recorded with the time it took when it ran, and offers no request to carry on', async () => {
  mockConv.msgs = DONE;
  await open();
  const foot = el.querySelector('.foot') as HTMLElement;
  expect(foot.querySelector('.replay-tag')?.textContent).toBe('Recorded');
  expect(foot.textContent).toContain('Done in 105.2 s');          // as it ran, not as it played
  expect(foot.querySelector('[aria-label="Copy a request that continues this conversation"]')).toBeNull();
});

test('where the server cannot continue a recording, a bar says so, with Follow up', async () => {
  mockConv.msgs = DONE;
  await open();
  expect(el.querySelector('textarea[aria-label="message"]')).toBeNull();
  expect(el.querySelector('.readonly')?.textContent).toContain('Recorded task');
  const btn = Array.from(el.querySelectorAll('button')).find((b) => b.textContent === 'Follow up') as HTMLButtonElement;
  act(() => { btn.click(); });
  expect(followUp).toHaveBeenCalledTimes(1);
  expect(text()).not.toMatch(/trace/i);
});

test('where the server takes input history, a message written under it goes on as a task of your own', async () => {
  mockFork.history = true;
  mockConv.msgs = DONE;
  await open();
  const ta = el.querySelector('textarea[aria-label="message"]') as HTMLTextAreaElement;
  expect(ta).not.toBeNull();
  const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;
  act(() => { set?.call(ta, 'Make the background pure white.'); ta.dispatchEvent(new Event('input', { bubbles: true })); });
  await act(async () => { (el.querySelector('button.run') as HTMLButtonElement).click(); });
  await flush();
  expect(mockConv.send).toHaveBeenCalledTimes(1);
  const [t, files, o] = mockConv.send.mock.calls[0];
  expect(t).toBe('Make the background pure white.');
  expect(files).toEqual([]);
  expect(o).toEqual({ input: [{ role: 'assistant', content: 'Done.' }, { role: 'user', content: 'Make the background pure white.' }] });
});
