/** @jest-environment jsdom */
// Branching a task from a reply (issue #477). A reply has a Branch action only where the server says
// it branches, and only where a branch could work: not while it runs, not on a turn the task brought
// with it, which has no checkpoint of its own. The action opens a draft that sends nothing; the draft's
// first message is the one request with `branch`, and after it the task is a task like any other.
// A branched task, new or reopened, has its line ("Continued from ...") where its history ends.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { CustomHarness, ModelCatalog } from '@/lib/harness';
import type { AsstMsg, Msg } from '@/lib/conversation';

const mockConv = {
  msgs: [] as Msg[],
  live: '',
  send: jest.fn(async (_t: string, _f: unknown[], _o?: unknown) => true),
  setMsgs: jest.fn(),
};
jest.mock('@/lib/conversation', () => ({
  isInternalOutput: () => false,
  useHarnessBus: () => {},
  useConversationTurn: () => ({
    msgs: mockConv.msgs, busy: false, stopping: false, liveSessionId: mockConv.live,
    // two arguments when the caller gave two: an ordinary message names no branch at all
    send: (...a: [string, unknown[], unknown?]) => mockConv.send(...a),
    replay: () => () => {}, stop: () => {}, setMsgs: mockConv.setMsgs, loadFailed: false, reload: () => {},
  }),
}));
const mockChat = {
  turns: [] as { id: string; imported?: boolean; _model?: string }[],
  origin: jest.fn(),
};
jest.mock('@/lib/chat', () => ({
  loadSessionTurns: jest.fn(async () => ({ turns: mockChat.turns })),
  loadSessionOrigin: (sid: string) => mockChat.origin(sid),
}));
const mockCat: { read: { value: ModelCatalog | null; failed: boolean; retry: jest.Mock } } = { read: { value: null, failed: false, retry: jest.fn() } };
const mockBases: { doc: Record<string, unknown> | null } = { doc: null };
jest.mock('@/lib/hfetch', () => ({
  harnessFetch: async () => { if (!mockBases.doc) throw new Error('down'); return { ok: true, json: async () => mockBases.doc }; },
}));
jest.mock('@/lib/harness', () => ({
  ...jest.requireActual('@/lib/harness'),
  useModelCatalogRead: () => mockCat.read,
  oobModels: () => ['gpt-5.4', 'gpt-5.5'],
  oobDefaultModel: () => 'gpt-5.4',
  modelAvailability: () => 'yes',
}));
jest.mock('@/lib/providers', () => ({ providerById: () => null, useModelProviders: () => ({ connectionFor: () => null }) }));
jest.mock('../toast', () => ({ toast: jest.fn() }));
jest.mock('../Skel', () => ({ Skel: () => null, SkLine: () => null, SkThread: () => null }));
jest.mock('../start/prompts', () => ({ API_BASE: 'https://box.example/api/harness' }));
jest.mock('../start/fork', () => ({ inputHistory: async () => false, forkOffered: () => true, forkFiles: jest.fn(), forkInput: jest.fn(), importedFirst: () => true, noteFork: jest.fn() }));
jest.mock('./TaskThread', () => ({ Md: () => null }));
jest.mock('next/link', () => ({ __esModule: true, default: ({ href, children, ...p }: { href: string; children: React.ReactNode }) => <a href={href} {...p}>{children}</a> }));
// each answer's foot, and the line after a turn, as the conversation draws them
jest.mock('./AgentTurns', () => ({
  AgentTurns: ({ msgs, actions, after }: { msgs: Msg[]; actions: (t: number, m: AsstMsg) => React.ReactNode; after?: (t: number) => React.ReactNode }) => (
    <div>{msgs.filter((m): m is AsstMsg => m.role === 'assistant').map((m, i) => <div key={i} className="turn"><div className="foot">{actions(i, m)}</div>{after?.(i)}</div>)}</div>
  ),
  harnessMark: () => ({ mark: null, motion: null }),
}));
jest.mock('./TurnFiles', () => ({ FileCards: () => null, filesOf: () => [] }));
jest.mock('reifyui/agent-chat', () => ({
  AgentConversation: ({ children, composer }: { children?: React.ReactNode; composer?: React.ReactNode }) => <div>{children}{composer}</div>,
  AgentComposer: (p: { value: string; onChange: (v: string) => void; onSend: () => void; left?: React.ReactNode }) => (
    <div className="composer">
      {p.left}
      <textarea aria-label="message" value={p.value} onChange={(e) => p.onChange(e.target.value)} />
      <button type="button" className="run" onClick={p.onSend}>Run task</button>
    </div>
  ),
}), { virtual: true });

import { rowOf } from '../setups';
import { Playground, type Slot } from './Playground';
import type { BranchDraft } from './branch';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const CAT: ModelCatalog = { hermes: { default: 'gpt-5.4', models: ['gpt-5.4', 'gpt-5.5'], unavailable: [] } };
const H = { id: 'chrn_t', name: 'Helper', base: 'hermes', defaultModel: 'gpt-5.4', systemPrompt: '', mcpServers: [], skills: [], createdAt: 1 } as unknown as CustomHarness;
const asst = (text: string, over: Partial<AsstMsg> = {}): AsstMsg => ({ role: 'assistant', blocks: [{ kind: 'text', text }], files: [], status: 'done', ...over });
const THREE: Msg[] = [
  { role: 'user', text: 'first\nmore' }, asst('one'),
  { role: 'user', text: 'second' }, asst('two'),
  { role: 'user', text: 'third' }, asst('three'),
];
const IDS = [{ id: 'r1', _model: 'gpt-5.4' }, { id: 'r2', _model: 'gpt-5.5' }, { id: 'r3', _model: 'gpt-5.4' }];
const DRAFT: BranchDraft = {
  from: 's1', title: 'Enable the service', responseId: 'r2', models: ['gpt-5.4', 'gpt-5.5'], model: 'gpt-5.5',
  msgs: THREE.slice(0, 4).map((m) => ({ ...m, imported: true as const })),
};

let root: Root;
let el: HTMLElement;
const flush = async () => { for (let i = 0; i < 12; i++) await act(async () => { await Promise.resolve(); }); };
const onBranch = jest.fn();
async function open(slot: Slot, taskTitle?: string) {
  await act(async () => {
    root.render(<Playground r={rowOf(H, 'Hermes', [], false)} onRan={() => {}} onBorn={() => {}} onPreview={() => {}} onBranch={onBranch} taskHref={(sid) => `/tasks/${sid}`} slot={slot} taskTitle={taskTitle} />);
  });
  await flush();
}
const OPENED: Slot = { key: 's1', resume: 's1' };
const branches = () => [...el.querySelectorAll<HTMLButtonElement>('button[aria-label="Branch in a new task"]')];
const box = () => el.querySelector('textarea[aria-label="message"]') as HTMLTextAreaElement;
const send = async (t: string) => {
  const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;
  act(() => { set?.call(box(), t); box().dispatchEvent(new Event('input', { bubbles: true })); });
  await act(async () => { (el.querySelector('button.run') as HTMLButtonElement).click(); });
  await flush();
};
const marks = () => [...el.querySelectorAll('.pg-branch')];

beforeEach(() => {
  mockCat.read = { value: CAT, failed: false, retry: jest.fn() };
  mockConv.msgs = [];
  mockConv.live = '';
  mockConv.send.mockClear(); mockConv.setMsgs.mockClear(); onBranch.mockClear();
  mockChat.turns = [];
  mockChat.origin.mockReset();
  mockBases.doc = { capabilities: { session_branching: true } };
  el = document.createElement('div'); el.id = 'hrui'; document.body.appendChild(el);
  root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); el.remove(); });

describe('the Branch action on a reply', () => {
  test('every finished reply has one where the server says it branches', async () => {
    mockConv.msgs = THREE; mockChat.turns = IDS;
    await open(OPENED);
    expect(branches()).toHaveLength(3);
  });

  test.each([
    ['says nothing of branching', { capabilities: {} }],
    ['says it does not', { capabilities: { session_branching: false } }],
    ['could not be read', null],
  ])('none on a server that %s', async (_w, doc) => {
    mockBases.doc = doc; mockConv.msgs = THREE; mockChat.turns = IDS;
    await open(OPENED);
    expect(branches()).toHaveLength(0);
  });

  test('none on a reply still running: the server refuses a branch from one', async () => {
    mockConv.msgs = [{ role: 'user', text: 'a' }, asst('', { status: 'running' })]; mockChat.turns = [{ id: 'r1' }];
    await open(OPENED);
    expect(branches()).toHaveLength(0);
  });

  test('none on a turn the task brought with it, which has no checkpoint to branch from', async () => {
    mockConv.msgs = [{ role: 'user', text: 'a', imported: true }, asst('old', { imported: true }), { role: 'user', text: 'b' }, asst('new')];
    mockChat.turns = [{ id: 'r1', imported: true }, { id: 'r2' }];
    mockChat.origin.mockResolvedValue({ title: '', branchedFrom: null });
    await open(OPENED);
    const feet = [...el.querySelectorAll('.foot')];
    expect(feet[0].querySelector('button[aria-label="Branch in a new task"]')).toBeNull();
    expect(feet[1].querySelector('button[aria-label="Branch in a new task"]')).not.toBeNull();
  });

  test('none on a reply whose response ID is not known yet', async () => {
    mockConv.msgs = THREE; mockChat.turns = [];
    await open(OPENED);
    expect(branches()).toHaveLength(0);
  });

  test('clicking one hands over the task up to that reply, and sends nothing', async () => {
    mockConv.msgs = THREE; mockChat.turns = IDS;
    await open(OPENED, 'Enable the service');
    await act(async () => { branches()[1].click(); });
    expect(onBranch).toHaveBeenCalledTimes(1);
    const b = onBranch.mock.calls[0][0] as BranchDraft;
    expect(b).toMatchObject({ from: 's1', title: 'Enable the service', responseId: 'r2', models: ['gpt-5.4', 'gpt-5.5'], model: 'gpt-5.5' });
    expect(b.msgs.map((m) => (m.role === 'user' ? m.text : 'answer'))).toEqual(['first\nmore', 'answer', 'second', 'answer']);
    expect(b.msgs.every((m) => m.imported)).toBe(true);
    expect(mockConv.send).not.toHaveBeenCalled();
  });

  test('without a title in hand, the task is called by the first line of its first message', async () => {
    mockConv.msgs = THREE; mockChat.turns = IDS;
    await open(OPENED);
    await act(async () => { branches()[0].click(); });
    expect((onBranch.mock.calls[0][0] as BranchDraft).title).toBe('first');
  });
});

describe('a branch not sent yet', () => {
  const DRAFT_SLOT: Slot = { key: 'b1', resume: null, branch: DRAFT };

  test('opens holding the task up to the reply, with its line after the last of it, and nothing is sent', async () => {
    await open(DRAFT_SLOT);
    expect(mockConv.setMsgs).toHaveBeenCalledWith(DRAFT.msgs);
    expect(mockConv.send).not.toHaveBeenCalled();
    mockConv.msgs = DRAFT.msgs;
    await open({ ...DRAFT_SLOT });
    expect(marks()).toHaveLength(1);
    expect(marks()[0].closest('.turn')).toBe(el.querySelectorAll('.turn')[1]);
    expect(marks()[0].textContent).toBe('Continued from Enable the service');
    expect(marks()[0].querySelector('a')?.getAttribute('href')).toBe('/tasks/s1');
  });

  test('its first message is the request that branches, and only that one', async () => {
    mockConv.msgs = DRAFT.msgs;
    await open(DRAFT_SLOT);
    await send('Try another way');
    expect(mockConv.send).toHaveBeenCalledTimes(1);
    expect(mockConv.send).toHaveBeenLastCalledWith('Try another way', [], { branchFrom: 'r2' });
    // it has a session now: the next message continues it, and names no branch at all
    mockConv.live = 's2';
    await open({ ...DRAFT_SLOT });
    await send('And then?');
    expect(mockConv.send).toHaveBeenCalledTimes(2);
    expect(mockConv.send.mock.calls[1]).toEqual(['And then?', []]);
  });

  test('a first message that was refused leaves it a draft: the next one branches again', async () => {
    mockConv.msgs = DRAFT.msgs;
    mockConv.send.mockResolvedValueOnce(false);
    await open(DRAFT_SLOT);
    await send('one');
    await send('two');
    expect(mockConv.send.mock.calls.map((c) => c[2])).toEqual([{ branchFrom: 'r2' }, { branchFrom: 'r2' }]);
  });

  test('its turns offer no Branch: they are the original task’s, and have no ID here', async () => {
    mockConv.msgs = DRAFT.msgs;
    await open(DRAFT_SLOT);
    expect(branches()).toHaveLength(0);
  });

  test('it starts on the model of the reply it goes on from', async () => {
    mockConv.msgs = DRAFT.msgs;
    await open(DRAFT_SLOT);
    expect(el.querySelector('.pg-opts .nw-pk b')?.textContent).toBe('gpt-5.5');
  });

});

describe('a branched task, opened again', () => {
  const BRANCHED: Msg[] = [
    { role: 'user', text: 'a', imported: true }, asst('old', { imported: true }),
    { role: 'user', text: 'b', imported: true }, asst('old too', { imported: true }),
    { role: 'user', text: 'hi' }, asst('new'),
  ];
  beforeEach(() => { mockChat.turns = [{ id: 'x1', imported: true }, { id: 'x2', imported: true }, { id: 'x3' }]; });

  test('has its line after the last turn it brought, naming and linking the original', async () => {
    mockConv.msgs = BRANCHED;
    mockChat.origin.mockImplementation(async (sid: string) => (sid === 's2' ? { title: 'a', branchedFrom: 's1' } : { title: 'The original', branchedFrom: null }));
    await open({ key: 's2', resume: 's2' });
    expect(marks()).toHaveLength(1);
    expect(marks()[0].closest('.turn')).toBe(el.querySelectorAll('.turn')[1]);
    expect(marks()[0].textContent).toBe('Continued from The original');
    expect(marks()[0].querySelector('a')?.getAttribute('href')).toBe('/tasks/s1');
  });

  test('an original that is gone keeps the line, as words with no link', async () => {
    mockConv.msgs = BRANCHED;
    mockChat.origin.mockImplementation(async (sid: string) => (sid === 's2' ? { title: 'a', branchedFrom: 's1' } : { title: '', branchedFrom: null, missing: true }));
    await open({ key: 's2', resume: 's2' });
    expect(marks()[0].textContent).toBe('Continued from a deleted task');
    expect(marks()[0].querySelector('a')).toBeNull();
  });

  test('imported turns that are not a branch (a recorded run carried on) have no line', async () => {
    mockConv.msgs = BRANCHED;
    mockChat.origin.mockResolvedValue({ title: 'a', branchedFrom: null });
    await open({ key: 's2', resume: 's2' });
    expect(marks()).toHaveLength(0);
  });

  test('an ordinary task is not asked where it came from: no extra read', async () => {
    mockConv.msgs = THREE; mockChat.turns = IDS;
    await open(OPENED);
    expect(mockChat.origin).not.toHaveBeenCalled();
    expect(marks()).toHaveLength(0);
  });
});
