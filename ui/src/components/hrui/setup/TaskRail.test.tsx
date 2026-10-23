/** @jest-environment jsdom */
// A setup's task list (Richard, 10-19: no fallbacks; the right path must work). The list itself reads
// nothing on a timer: the workspace watch's start and end of a task of this setup read the newest page
// (again at 1 s and 2 s while the card lags the frame), each time the watch comes up reads it once, and
// so does each start and end on the setup's own feed.
// A read that failed says so: the first, that older tasks could not be read (never a list that looks
// whole); a later one, that it could not refresh; an answer that is not the list is a failed read.
// A task opened by its link is "not here" only on the server's 404 or another setup's card.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { TraceCard } from '@/lib/revamp-data';
import type { FeedFrame } from '@/lib/workspace-feed';

const harnessFetch = jest.fn();
jest.mock('@/lib/hfetch', () => ({ harnessFetch: (...a: unknown[]) => harnessFetch(...a) }));
jest.mock('@/lib/auth', () => ({ getSession: () => ({ orgId: 'org.a', member: { email: 'ana@example.com' } }) }));
let busCb: (() => void) | undefined;
jest.mock('@/lib/conversation', () => ({
  feedTurnOf: () => undefined, livePending: () => [], useFeedTurns: () => 0,
  useHarnessBus: (_id: string, cb?: () => void) => { busCb = cb; },
}));
const feed: { opts: { on: boolean; onFrame: (f: FeedFrame) => void; onUp: (away: number) => void } | null; paused: boolean; reconnect: jest.Mock } = {
  opts: null, paused: false, reconnect: jest.fn(),
};
jest.mock('@/lib/use-workspace-feed', () => ({
  useWorkspaceFeed: (o: typeof feed.opts) => { feed.opts = o; return { paused: feed.paused, reconnect: feed.reconnect }; },
}));
jest.mock('../toast', () => ({ toast: jest.fn() }));
jest.mock('../setups', () => ({ ago: () => '1 min ago' }));
jest.mock('../Skel', () => ({ Skel: ({ label }: { label: string }) => <div aria-busy="true">{label}</div>, SkRows: () => null }));
jest.mock('./TaskDetail', () => ({ DeleteTask: () => null, titleOf: (c: TraceCard) => c.title || c.session_id }));

import { filterTasks, NO_FILTER, readTaskCard, TaskList, useLinkedTask, useTaskList, type TaskList as TL } from './TaskRail';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const H = 'chrn_1';
const now = Math.floor(Date.now() / 1000);
const card = (sid: string, status = 'completed', over: Partial<TraceCard> = {}): TraceCard =>
  ({ session_id: sid, title: `Task ${sid}`, status, harness_id: H, finished_at: now - 60, ...over });
const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body });
const bad = (status: number) => ({ ok: false, status, json: async () => ({}) });
const html = () => ({ ok: true, status: 200, json: async () => { throw new SyntaxError('Unexpected token <'); } });
const frame = (sid: string, type: string, harness = H): FeedFrame => ({ session_id: sid, harness_id: harness, workspace: 'ws', member: '', type, status: type === 'harness.turn.started' ? 'running' : 'completed', at: now });

let root: Root;
let el: HTMLElement;
let list: TL;
function Rail({ cards = [] as TraceCard[] }) {
  list = useTaskList(H, cards, 0);
  return <TaskList setupName="Alpha" list={list} f={NO_FILTER} setF={() => undefined} current={null} isNew={false} onOpen={() => undefined} onNew={() => undefined} onGone={() => undefined} />;
}
const text = () => (el.textContent || '').replace(/\s+/g, ' ');
const flush = async () => { for (let i = 0; i < 6; i++) await act(async () => { await Promise.resolve(); }); };
const later = async (ms: number) => { await act(async () => { jest.advanceTimersByTime(ms); }); await flush(); };
const reads = () => harnessFetch.mock.calls.filter(([u]) => String(u).startsWith('/api/harness/v1/traces?')).length;
const tryAgain = () => Array.from(el.querySelectorAll('button')).find((b) => b.textContent === 'Try again');
const cards24h = [card('s_today')];

beforeEach(() => {
  jest.useFakeTimers();
  harnessFetch.mockReset(); feed.opts = null; feed.paused = false; feed.reconnect.mockReset(); busCb = undefined;
  el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); el.remove(); jest.useRealTimers(); });

describe('the first read', () => {
  test('the correct path: the newest page is the list, and an empty one says No tasks yet', async () => {
    harnessFetch.mockResolvedValueOnce(ok({ sessions: [card('s1'), card('s2')], cursor: '' }));
    await act(async () => { root.render(<Rail />); });
    await flush();
    expect(text()).toContain('Task s1');
    expect(text()).toContain('Task s2');
    expect(list.failed).toBe(false);
    expect(filterTasks(list, NO_FILTER).complete).toBe(true);
    act(() => root.unmount());
    root = createRoot(el);
    harnessFetch.mockResolvedValueOnce(ok({ sessions: [], cursor: '' }));
    await act(async () => { root.render(<Rail />); });
    await flush();
    expect(text()).toContain('No tasks yet.');
  });

  test("a failed read with the page's own cards says older tasks could not be read, and the list is never complete", async () => {
    harnessFetch.mockResolvedValueOnce(bad(502));
    await act(async () => { root.render(<Rail cards={cards24h} />); });
    await flush();
    expect(text()).toContain('Task s_today');
    expect(text()).toContain('Older tasks could not be read.');
    expect(list.ready).toBe(true);
    expect(list.failed).toBe(true);
    expect(filterTasks(list, NO_FILTER).complete).toBe(false);
    // Try again reads it, and the list is whole
    harnessFetch.mockResolvedValueOnce(ok({ sessions: [card('s_today'), card('s_old')], cursor: '' }));
    await act(async () => { tryAgain()?.click(); });
    await flush();
    expect(text()).toContain('Task s_old');
    expect(text()).not.toContain('could not be read');
    expect(filterTasks(list, NO_FILTER).complete).toBe(true);
  });

  test('an answer that is not the list (an edge answering a page of its own) is a failed read, never "No tasks yet."', async () => {
    harnessFetch.mockResolvedValueOnce(html());
    await act(async () => { root.render(<Rail />); });
    await flush();
    expect(text()).toContain('Tasks could not be read.');
    expect(text()).not.toContain('No tasks yet.');
    act(() => root.unmount());
    root = createRoot(el);
    harnessFetch.mockResolvedValueOnce(ok({ detail: 'something else' }));
    await act(async () => { root.render(<Rail />); });
    await flush();
    expect(text()).toContain('Tasks could not be read.');
    expect(text()).not.toContain('No tasks yet.');
  });
});

describe('kept current on push', () => {
  async function shown(sessions: TraceCard[]) {
    harnessFetch.mockResolvedValue(ok({ sessions, cursor: '' }));
    await act(async () => { root.render(<Rail />); });
    await flush();
    harnessFetch.mockClear();
  }

  test('nothing reads on a timer, a running card included', async () => {
    await shown([card('s1', 'running')]);
    await later(120_000);
    expect(reads()).toBe(0);
  });

  test('a start of a task of this setup reads now, then at 1 s and 2 s while it is not listed', async () => {
    await shown([card('s1')]);
    await act(async () => { feed.opts?.onFrame(frame('s_new', 'harness.turn.started')); });
    await flush();
    expect(reads()).toBe(1);
    await later(1000);
    expect(reads()).toBe(2);
    // the card is listed by the 1 s read: the 2 s read is not needed
    harnessFetch.mockResolvedValue(ok({ sessions: [card('s1')], cursor: '' }));
    await later(1000);
    expect(reads()).toBe(3);
    harnessFetch.mockClear();
    harnessFetch.mockResolvedValue(ok({ sessions: [card('s_new', 'running'), card('s1')], cursor: '' }));
    await act(async () => { feed.opts?.onFrame(frame('s_two', 'harness.turn.started')); });
    await flush();
    harnessFetch.mockResolvedValue(ok({ sessions: [card('s_two', 'running'), card('s_new', 'running'), card('s1')], cursor: '' }));
    await later(1000);
    expect(text()).toContain('Task s_two');
    await later(1000);
    expect(reads()).toBe(2);
  });

  test("another setup's task reads nothing", async () => {
    await shown([card('s1')]);
    await act(async () => { feed.opts?.onFrame(frame('s_other', 'harness.turn.started', 'chrn_2')); });
    await later(3000);
    expect(reads()).toBe(0);
  });

  test('an end reads now, and again while the card still says running', async () => {
    await shown([card('s1', 'running')]);
    harnessFetch.mockResolvedValue(ok({ sessions: [card('s1', 'running')], cursor: '' }));
    await act(async () => { feed.opts?.onFrame(frame('s1', 'response.completed')); });
    await flush();
    expect(reads()).toBe(1);
    harnessFetch.mockResolvedValue(ok({ sessions: [card('s1', 'completed')], cursor: '' }));
    await later(1000);
    expect(reads()).toBe(2);
    await later(1000);
    expect(reads()).toBe(2);
  });

  test('each (re)connect of the feed reads once', async () => {
    await shown([card('s1')]);
    await act(async () => { feed.opts?.onUp(0); });
    await flush();
    expect(reads()).toBe(1);
  });

  test("the setup's own feed still reads on its starts and ends", async () => {
    await shown([card('s1')]);
    await act(async () => { busCb?.(); });
    await later(500);
    expect(reads()).toBe(1);
  });

  test('a read again that fails says it could not refresh, until one answers', async () => {
    await shown([card('s1')]);
    harnessFetch.mockResolvedValueOnce(bad(503));
    await act(async () => { feed.opts?.onUp(0); });
    await flush();
    expect(text()).toContain('Task s1');
    expect(text()).toContain('Could not refresh.');
    harnessFetch.mockResolvedValueOnce(ok({ sessions: [card('s1'), card('s2')], cursor: '' }));
    await act(async () => { tryAgain()?.click(); });
    await flush();
    expect(text()).not.toContain('Could not refresh.');
    expect(text()).toContain('Task s2');
  });

  test('while live updates are down the list says so, and Try again connects again', async () => {
    feed.paused = true;
    await shown([card('s1')]);
    expect(text()).toContain('Live updates paused. This list may be out of date.');
    await act(async () => { tryAgain()?.click(); });
    expect(feed.reconnect).toHaveBeenCalledTimes(1);
    feed.paused = false;
    await act(async () => { root.render(<Rail />); });
    expect(text()).not.toContain('Live updates paused');
  });
});

describe('a task opened by its link', () => {
  test('readTaskCard: a card, null only for the 404, and a throw for anything else', async () => {
    harnessFetch.mockResolvedValueOnce(ok(card('s9')));
    expect((await readTaskCard('s9'))?.session_id).toBe('s9');
    harnessFetch.mockResolvedValueOnce(bad(404));
    expect(await readTaskCard('s9')).toBeNull();
    harnessFetch.mockResolvedValueOnce(bad(503));
    await expect(readTaskCard('s9')).rejects.toThrow('503');
    harnessFetch.mockResolvedValueOnce(html());
    await expect(readTaskCard('s9')).rejects.toThrow();
    harnessFetch.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    await expect(readTaskCard('s9')).rejects.toThrow();
  });

  function Linked({ sid, onGone }: { sid: string; onGone: () => void }) {
    const l = useTaskList(H, [], 0);
    const r = useLinkedTask(H, sid, l, false, onGone);
    list = l;
    return <div>{r.failed ? <button type="button" onClick={r.retry}>Try again</button> : 'fine'}</div>;
  }
  const route = (byCard: () => unknown) => harnessFetch.mockImplementation(async (u: string) =>
    (u.startsWith('/api/harness/v1/traces?') ? ok({ sessions: [], cursor: '' }) : byCard()));

  test('a failed read keeps the task and says so; Try again reads it and keeps it with the rest', async () => {
    const onGone = jest.fn();
    route(() => bad(502));
    await act(async () => { root.render(<Linked sid="s_old" onGone={onGone} />); });
    await flush();
    expect(onGone).not.toHaveBeenCalled();
    expect(tryAgain()).toBeTruthy();
    route(() => ok(card('s_old')));
    await act(async () => { tryAgain()?.click(); });
    await flush();
    expect(onGone).not.toHaveBeenCalled();
    expect(text()).toContain('fine');
    expect(list.byId.has('s_old')).toBe(true);
  });

  test("only a task that is gone (404) or another setup's lets go", async () => {
    const onGone = jest.fn();
    route(() => bad(404));
    await act(async () => { root.render(<Linked sid="s_gone" onGone={onGone} />); });
    await flush();
    expect(onGone).toHaveBeenCalledTimes(1);
    act(() => root.unmount());
    root = createRoot(el);
    route(() => ok(card('s_x', 'completed', { harness_id: 'chrn_2' })));
    await act(async () => { root.render(<Linked sid="s_x" onGone={onGone} />); });
    await flush();
    expect(onGone).toHaveBeenCalledTimes(2);
  });
});

describe('the rows', () => {
  test('every task not running can be deleted from its row; a running one is stopped first', async () => {
    harnessFetch.mockResolvedValueOnce(ok({ sessions: [card('s_run', 'running'), card('s_done'), card('s_bad', 'failed')], cursor: '' }));
    await act(async () => { root.render(<Rail />); });
    await flush();
    const del = Array.from(el.querySelectorAll('button.tk-rdel')).map((b) => b.getAttribute('aria-label'));
    expect(del).toEqual(['Delete task Task s_done', 'Delete task Task s_bad']);
    // a row says when the task last did something and how it ended, never who sent it
    expect(text()).toContain('Task s_bad1 min ago · Failed');
  });

  test('the filter holds All and Failed, with the time ranges', async () => {
    harnessFetch.mockResolvedValueOnce(ok({ sessions: [card('s_done'), card('s_bad', 'failed')], cursor: '' }));
    await act(async () => { root.render(<Rail />); });
    await flush();
    await act(async () => { (el.querySelector('button[aria-haspopup="menu"]') as HTMLButtonElement).click(); });
    const items = Array.from(el.querySelectorAll('[role="menuitemradio"]')).map((b) => b.textContent);
    expect(items.slice(0, 2)).toEqual(['All', 'Failed1']);
    expect(items.slice(2)).toEqual(['1 h', '24 h', '7 d', '30 d', 'Any time']);
    expect(filterTasks(list, { ...NO_FILTER, view: 'failed' }).shown.map((c) => c.session_id)).toEqual(['s_bad']);
  });
});
