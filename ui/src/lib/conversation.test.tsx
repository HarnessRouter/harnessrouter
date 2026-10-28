/** @jest-environment jsdom */
// The conversation controller (lib/conversation) without fallbacks (Richard 10-19):
// - a task's record that cannot be read writes nothing: the task is not opened empty, a live turn is
//   not wiped or ended, and the page is told (loadFailed, reload) instead;
// - a state the record says is live (queued too), or one this console does not know, is never "done";
// - a turn's end is never left to a timer: it is read from the record when its own stream ends before
//   it, when the setup's feed comes up again, and when the workspace watch reports the task's end;
// - one live feed per setup in a tab: a delta drawn from it lands once.
import type { Root } from 'react-dom/client';
import type { BusMsg, BusState, SessionTurn, StreamHandlers, StreamOpts } from './chat';
import type { FeedFrame } from './workspace-feed';

const mockChat = {
  load: jest.fn(),
  stream: jest.fn(),
  bus: [] as { harness: string; onMsg: (m: BusMsg) => void; onState?: (s: BusState) => void; stop: jest.Mock }[],
};
jest.mock('@/lib/chat', () => ({
  loadSessionTurns: (...a: unknown[]) => mockChat.load(...a),
  streamResponse: (...a: unknown[]) => mockChat.stream(...a),
  cancelSession: jest.fn(async () => ({ cancelled: true, status: 'cancelled' })),
  subscribeHarnessEvents: (harness: string, onMsg: (m: BusMsg) => void, onState?: (s: BusState) => void) => {
    const stop = jest.fn();
    mockChat.bus.push({ harness, onMsg, onState, stop });
    return stop;
  },
}));
const mockFeed = { frames: new Set<(f: FeedFrame) => void>() };
jest.mock('@/lib/workspace-feed', () => ({
  subscribeWorkspaceFeed: (f: (x: FeedFrame) => void) => { mockFeed.frames.add(f); return () => { mockFeed.frames.delete(f); }; },
}));
jest.mock('@/lib/analytics', () => ({ track: jest.fn() }));
jest.mock('@/lib/harness', () => ({ oobById: () => null }));
jest.mock('@/lib/workspace', () => ({ getCurrentWorkspaceRef: () => ({ id: 'ws.a' }) }));
jest.mock('@/lib/feed-turns', () => ({ emitFeedTurn: jest.fn() }));

import type * as Conversation from './conversation';
import type { AsstMsg, Msg } from './conversation';

// each test reads the controller from a fresh module registry (its store, feeds and settlers are
// module state), and React with it, so the renderer and the hooks share one React
let C: typeof Conversation;
let act: (f: () => unknown) => Promise<void>;
let createRoot: (c: Element) => Root;

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const turn = (over: Partial<SessionTurn> & Record<string, unknown> = {}): SessionTurn =>
  ({ id: 'r1', status: 'completed', user: 'hi', assistant: 'Hello there', tools: [], files: [], ...over } as SessionTurn);
const record = (turns: SessionTurn[], last = turns.length ? turns[turns.length - 1].id : null) => ({ turns, lastResponseId: last });
const textOf = (m: Msg | undefined) => (m && m.role === 'assistant' ? (m as AsstMsg).blocks.map((b) => (b.kind === 'text' ? b.text : '')).join('') : '');
const lastA = (sid: string) => [...C.getConvState(sid).msgs].reverse().find((m) => m.role === 'assistant') as AsstMsg | undefined;
const tick = async (ms = 0) => {
  await act(async () => { await jest.advanceTimersByTimeAsync(ms); });
  for (let i = 0; i < 8; i++) await act(async () => { await Promise.resolve(); });
};

let api: ReturnType<typeof Conversation.useConversationTurn>;
let root: Root;
let el: HTMLDivElement;
let n = 0;
let missing: jest.Mock;
function Conv({ sid, harness = 'h1' }: { sid: string | null; harness?: string }) {
  api = C.useConversationTurn({ harnessId: harness, sessionId: sid, target: { name: 'Helper', backend: 'claude' }, onRan: () => {}, onMissing: missing });
  return null;
}
function Bus({ harness, onActivity }: { harness: string; onActivity?: () => void }) { C.useHarnessBus(harness, onActivity); return null; }
async function render(node: React.ReactNode) {
  await act(async () => { root.render(node); });
  await tick();
}
/** a fresh task id per test: the store is module-level */
const sidNew = () => `s${++n}`;

beforeEach(() => {
  jest.useFakeTimers({ doNotFake: ['queueMicrotask', 'nextTick', 'setImmediate'] });
  mockChat.load.mockReset();
  mockChat.stream.mockReset();
  mockChat.bus = [];
  missing = jest.fn();
  jest.resetModules();
  act = require('react').act;
  createRoot = require('react-dom/client').createRoot;
  C = require('./conversation');
  el = document.createElement('div');
  document.body.appendChild(el);
  root = createRoot(el);
});
afterEach(async () => {
  await act(async () => { root.unmount(); });
  el.remove();
  jest.useRealTimers();
});

describe('a turn’s state as the record says it', () => {
  test.each(['queued', 'starting', 'running', 'in_progress'])('%s is live: running', (s) => {
    expect(C.turnStatus(s)).toBe('running');
    expect(C.msgsFromTurns([turn({ status: s })]).running).toBe(true);
  });
  test.each(['', 'paused_for_review', undefined])('a state this console does not know (%p) is never done', (s) => {
    expect(C.turnStatus(s)).toBe('running');
    expect(C.msgsFromTurns([turn({ status: s as string })]).running).toBe(true);
  });
  test.each([['completed', 'done'], ['done', 'done'], ['failed', 'failed'], ['error', 'failed'], ['cancelled', 'cancelled'],
    ['incomplete', 'incomplete'], ['max_turns', 'incomplete'], ['timeout', 'incomplete']])('%s is %s', (s, want) => {
    expect(C.turnStatus(s)).toBe(want);
    expect(C.msgsFromTurns([turn({ status: s })]).running).toBe(false);
  });
});

describe('opening a task', () => {
  test('a record that cannot be read writes nothing and says so; Try again reads it', async () => {
    const sid = sidNew();
    mockChat.load.mockRejectedValue(new Error('503'));
    await render(<Conv sid={sid} />);
    expect(api.loading).toBe(true);
    await tick(1000);                                   // the one quiet second try
    expect(mockChat.load).toHaveBeenCalledTimes(2);
    expect(api.loading).toBe(false);
    expect(api.loadFailed).toBe(true);
    expect(C.getConvState(sid)).toMatchObject({ msgs: [], loaded: false });
    // nothing is sent onto a task whose record is not known
    await expect(act(async () => api.send('next'))).resolves.toBe(false);
    expect(mockChat.stream).not.toHaveBeenCalled();
    mockChat.load.mockReset();
    mockChat.load.mockResolvedValue(record([turn()]));
    await act(async () => { api.reload(); });
    await tick();
    expect(api.loadFailed).toBe(false);
    expect(textOf(lastA(sid))).toBe('Hello there');
    expect(C.getConvState(sid)).toMatchObject({ loaded: true, busy: false, prevId: 'r1' });
  });

  test('a task running here keeps its live turn when the read fails: not wiped, not ended', async () => {
    const sid = sidNew();
    const live: Msg[] = [{ role: 'user', text: 'go' }, { role: 'assistant', blocks: [{ kind: 'text', text: 'Working on it' }], files: [], status: 'running' }];
    C.convStore.seed(sid, { msgs: live, busy: true, prevId: 'r0', firstTurn: false, loaded: true });
    mockChat.load.mockRejectedValue(new Error('network'));
    await render(<Conv sid={sid} />);
    await tick(1000);
    expect(api.loadFailed).toBe(true);
    expect(C.getConvState(sid)).toMatchObject({ msgs: live, busy: true, prevId: 'r0' });
  });

  test('a deleted task (404) is let go of, nothing written', async () => {
    const sid = sidNew();
    mockChat.load.mockResolvedValue({ turns: [], lastResponseId: null, missing: true });
    await render(<Conv sid={sid} />);
    expect(missing).toHaveBeenCalledWith(sid);
    expect(api.loadFailed).toBe(false);
    expect(C.getConvState(sid).loaded).toBe(false);
  });

  test('a queued turn opens as running: busy, never drawn done', async () => {
    const sid = sidNew();
    mockChat.load.mockResolvedValue(record([turn({ status: 'queued', assistant: '' })]));
    await render(<Conv sid={sid} />);
    expect(C.getConvState(sid).busy).toBe(true);
    expect(lastA(sid)?.status).toBe('running');
  });
});

describe('a turn’s end, from its record, never on a timer', () => {
  async function openRunning() {
    const sid = sidNew();
    mockChat.load.mockResolvedValue(record([turn({ status: 'running', assistant: '' })]));
    await render(<><Conv sid={sid} /><Bus harness="h1" /></>);
    expect(C.getConvState(sid).busy).toBe(true);
    mockChat.load.mockReset();
    return sid;
  }

  test('a busy conversation reads nothing on its own, however long it waits', async () => {
    await openRunning();
    await tick(120_000);
    expect(mockChat.load).not.toHaveBeenCalled();
  });

  test('the setup’s feed coming up again: one read, and an ended turn settles from it', async () => {
    const sid = await openRunning();
    mockChat.load.mockResolvedValue(record([turn({ assistant: 'All done' })]));
    await act(async () => { mockChat.bus[0].onState?.('down'); mockChat.bus[0].onState?.('up'); });
    await tick();
    expect(mockChat.load).toHaveBeenCalledTimes(1);
    expect(C.getConvState(sid).busy).toBe(false);
    expect(textOf(lastA(sid))).toBe('All done');
  });

  test('the feed up again while the turn still runs: one read, nothing changes', async () => {
    const sid = await openRunning();
    mockChat.load.mockResolvedValue(record([turn({ status: 'running', assistant: '' })]));
    await act(async () => { mockChat.bus[0].onState?.('up'); });
    await tick(10_000);
    expect(mockChat.load).toHaveBeenCalledTimes(1);
    expect(C.getConvState(sid).busy).toBe(true);
  });

  test('the workspace feed’s end frame for this task: read after a beat, again while the record lags', async () => {
    const sid = await openRunning();
    mockChat.load.mockResolvedValueOnce(record([turn({ status: 'running', assistant: '' })]))
      .mockResolvedValueOnce(record([turn({ assistant: 'Finished' })]));
    const end = (session_id: string) => act(async () => {
      mockFeed.frames.forEach((f) => f({ session_id, harness_id: 'h1', workspace: 'ws.a', member: '', type: 'response.completed', status: 'completed', at: 1 }));
    });
    await end('someone-else');
    await tick(10_000);
    expect(mockChat.load).not.toHaveBeenCalled();
    await end(sid);
    await tick(999);
    expect(mockChat.load).not.toHaveBeenCalled();   // the setup's feed gets a beat to deliver it first
    await tick(1);
    expect(mockChat.load).toHaveBeenCalledTimes(1);
    expect(C.getConvState(sid).busy).toBe(true);
    await tick(1000);
    expect(mockChat.load).toHaveBeenCalledTimes(2);
    expect(C.getConvState(sid).busy).toBe(false);
    expect(textOf(lastA(sid))).toBe('Finished');
  });

  test('the end frame after the setup’s feed already ended the turn reads nothing', async () => {
    const sid = await openRunning();
    await act(async () => { mockChat.bus[0].onMsg({ session_id: sid, response_id: 'r1', event: { type: 'response.completed', response: {} } }); });
    expect(C.getConvState(sid).busy).toBe(false);
    mockFeed.frames.forEach((f) => f({ session_id: sid, harness_id: 'h1', workspace: 'ws.a', member: '', type: 'response.completed', status: 'completed', at: 1 }));
    // (the settled read for the turn's figures, which follows any end, waits 2.5 s: not this)
    await tick(2000);
    expect(mockChat.load).not.toHaveBeenCalled();
  });
});

describe('a send whose own stream ends before the turn does', () => {
  function streamThatStops(text: string) {
    mockChat.stream.mockImplementation(async (_o: StreamOpts, h: StreamHandlers) => {
      h.onCreated?.('r2'); h.onSession?.(currentSid); h.onTextDelta?.(text);
      return 'r2';                                       // ended (dropped or silent past its deadline), no terminal event
    });
  }
  let currentSid = '';
  async function openIdle() {
    const sid = sidNew();
    currentSid = sid;
    mockChat.load.mockResolvedValue(record([turn()]));
    await render(<><Conv sid={sid} /><Bus harness="h1" /></>);
    mockChat.load.mockReset();
    return sid;
  }

  test('the record is read at once: a turn that ended settles from it', async () => {
    const sid = await openIdle();
    streamThatStops('Par');
    mockChat.load.mockResolvedValue(record([turn(), turn({ id: 'r2', user: 'next', assistant: 'Partial and then the rest' })]));
    await act(async () => { await api.send('next'); });
    await tick();
    expect(mockChat.load).toHaveBeenCalledTimes(1);
    expect(C.getConvState(sid).busy).toBe(false);
    expect(textOf(lastA(sid))).toBe('Partial and then the rest');
  });

  test('a record that has not caught up is read again at 1, 2 and 4 s, then left to the feeds', async () => {
    const sid = await openIdle();
    streamThatStops('Par');
    mockChat.load.mockResolvedValue(record([turn()]));           // the new turn has no record yet
    await act(async () => { await api.send('next'); });
    await tick();
    expect(mockChat.load).toHaveBeenCalledTimes(1);
    await tick(1000); expect(mockChat.load).toHaveBeenCalledTimes(2);
    await tick(1000); expect(mockChat.load).toHaveBeenCalledTimes(3);
    await tick(2000); expect(mockChat.load).toHaveBeenCalledTimes(4);
    await tick(60_000); expect(mockChat.load).toHaveBeenCalledTimes(4);
    expect(C.getConvState(sid).busy).toBe(true);
  });

  test('a failed read is the next one’s to try', async () => {
    const sid = await openIdle();
    streamThatStops('Par');
    mockChat.load.mockRejectedValueOnce(new Error('503'))
      .mockResolvedValue(record([turn(), turn({ id: 'r2', user: 'next', assistant: 'Done' })]));
    await act(async () => { await api.send('next'); });
    await tick();
    expect(C.getConvState(sid).busy).toBe(true);
    await tick(1000);
    expect(C.getConvState(sid).busy).toBe(false);
    expect(textOf(lastA(sid))).toBe('Done');
  });

  test('the feed draws the rest and ends it; the answer then is the record’s whole one, not the gap', async () => {
    const sid = await openIdle();
    streamThatStops('Par');
    mockChat.load.mockResolvedValue(record([turn(), turn({ id: 'r2', user: 'next', status: 'running', assistant: '' })]));
    await act(async () => { await api.send('next'); });
    await tick(8000);                                  // read now and at 1, 2, 4 s: still running
    // what was said while the stream was silent never reached this tab; the feed draws from here on
    await act(async () => { mockChat.bus[0].onMsg({ session_id: sid, response_id: 'r2', event: { type: 'response.output_text.delta', delta: ' the end' } }); });
    expect(textOf(lastA(sid))).toBe('Par the end');
    await act(async () => { mockChat.bus[0].onMsg({ session_id: sid, response_id: 'r2', event: { type: 'response.completed', response: {} } }); });
    expect(C.getConvState(sid).busy).toBe(false);
    mockChat.load.mockResolvedValue(record([turn(), turn({ id: 'r2', user: 'next', assistant: 'Partial, the middle, the end', elapsed: 12 })]));
    await tick(2500);                                  // the settled read
    expect(textOf(lastA(sid))).toBe('Partial, the middle, the end');
    expect(lastA(sid)?.elapsed).toBe(12);
  });

  test('a produced file arriving after elapsed is recorded appears without reloading', async () => {
    const sid = await openIdle();
    streamThatStops('Done');
    const producedFile = {
      container_id: 'container-1',
      file_id: 'file-1',
      filename: 'report.csv',
    };

    mockChat.load.mockResolvedValue(record([
      turn(),
      turn({ id: 'r2', user: 'next', assistant: 'Done', elapsed: 12, files: [] }),
    ]));

    await act(async () => { await api.send('next'); });
    await tick();

    await act(async () => {
      mockChat.bus[0].onMsg({
        session_id: sid,
        response_id: 'r2',
        event: { type: 'response.completed', response: {} },
      });
    });

    await tick(2500);
    expect(lastA(sid)?.elapsed).toBe(12);
    expect(lastA(sid)?.files).toEqual([]);

    mockChat.load.mockResolvedValue(record([
      turn(),
      turn({
        id: 'r2',
        user: 'next',
        assistant: 'Done',
        elapsed: 12,
        files: [producedFile],
      }),
    ]));

    await tick(5000);

    expect(lastA(sid)?.files).toContainEqual(producedFile);
  });

});

describe('one live feed per setup in a tab', () => {
  test('two surfaces listening share one connection; each delta lands once; both hear the edges', async () => {
    const sid = sidNew();
    C.setConvState(sid, { msgs: [{ role: 'user', text: 'go' }, { role: 'assistant', blocks: [], files: [], status: 'running' }], busy: true, loaded: true });
    const a = jest.fn(), b = jest.fn();
    await render(<><Bus harness="h9" onActivity={a} /><Bus harness="h9" onActivity={b} /></>);
    expect(mockChat.bus.filter((x) => x.harness === 'h9')).toHaveLength(1);
    await act(async () => { mockChat.bus[0].onMsg({ session_id: sid, response_id: 'r1', event: { type: 'response.output_text.delta', delta: 'once' } }); });
    expect(textOf(lastA(sid))).toBe('once');
    await act(async () => { mockChat.bus[0].onMsg({ session_id: sid, response_id: 'r1', event: { type: 'response.completed', response: {} } }); });
    expect(a).toHaveBeenCalledTimes(1);
    expect(b).toHaveBeenCalledTimes(1);
    await render(<Bus harness="h9" onActivity={a} />);
    expect(mockChat.bus[0].stop).not.toHaveBeenCalled();
    await render(null);
    expect(mockChat.bus[0].stop).toHaveBeenCalledTimes(1);
  });

  test('a settled answer takes no more text from the feed (it can run behind the record)', async () => {
    const sid = sidNew();
    C.setConvState(sid, { msgs: [{ role: 'user', text: 'go' }, { role: 'assistant', blocks: [{ kind: 'text', text: 'Whole answer' }], files: [], status: 'done' }], busy: false, loaded: true });
    await render(<Bus harness="h8" />);
    await act(async () => { mockChat.bus[0].onMsg({ session_id: sid, response_id: 'r1', event: { type: 'response.output_text.delta', delta: 'answer' } }); });
    expect(textOf(lastA(sid))).toBe('Whole answer');
  });
});

