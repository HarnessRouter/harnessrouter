/** @jest-environment jsdom */
// Studio stays current without a reload (Richard, 10-18: "if a task is running, the list must show it
// live"). The workspace watch (lib/workspace-feed, mocked here) tells each task start and end of the
// workspace, and a frame updates that setup's row; each time the watch comes up the rows are read once.
// The page itself reads nothing on a timer: while the watch is not up it says its list may be out of
// date, with Try again. A turn a harness feed in this tab reports reads its setup's row at once too.
// Every state below comes from the setup's own task cards as the server answers them, or from the
// watch's own frames.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { CustomHarness } from '@/lib/harness';
import type { TraceCard } from '@/lib/revamp-data';
import type { FeedFrame, FeedState } from '@/lib/workspace-feed';

jest.mock('next/navigation', () => ({ useRouter: () => ({ push: jest.fn(), replace: jest.fn() }) }));
jest.mock('next/link', () => ({ __esModule: true, default: ({ href, children, ...p }: { href: string; children: React.ReactNode }) => <a href={href} {...p}>{children}</a> }));
jest.mock('@/lib/harness', () => ({
  ...jest.requireActual('@/lib/harness'),
  listCustom: jest.fn(), readCustom: jest.fn(), loadBases: jest.fn(async () => null),
}));
jest.mock('@/lib/revamp-data', () => ({ ...jest.requireActual('@/lib/revamp-data'), fetchHarnessTasks: jest.fn() }));
jest.mock('@/lib/workspace', () => ({
  ...jest.requireActual('@/lib/workspace'),
  useWorkspace: () => ({ current: { id: 'ws.t', name: 'Test Workspace', site: '' } }),
}));
jest.mock('@/components/HarnessLogo', () => ({ harnessLogoSrc: () => '' }));
jest.mock('@/components/hrui/ws', () => ({ WsBadge: () => null }));
jest.mock('@/components/hrui/Iso', () => ({ Iso: () => null }));
jest.mock('@/components/hrui/NewSetup', () => ({ NewSetup: () => null }));
jest.mock('@/components/hrui/Skel', () => ({ Skel: () => null, SkCards: () => null, SkRows: () => null, SkLine: () => <i className="sk-line" /> }));
jest.mock('@/components/hrui/WorkspaceSheets', () => ({ openWorkspaceMenu: jest.fn() }));
// the workspace feed as the tab holds it: each test says whether its stream is up, and sends frames
const mockFeed = {
  state: 'down' as FeedState,
  frames: new Set<(f: FeedFrame) => void>(),
  states: new Set<(s: FeedState) => void>(),
  opened: 0, closed: 0, reconnects: 0,
};
jest.mock('@/lib/workspace-feed', () => ({
  reconnectWorkspaceFeed: () => { mockFeed.reconnects += 1; },
  subscribeWorkspaceFeed: (onFrame: (f: FeedFrame) => void, onState?: (s: FeedState) => void) => {
    mockFeed.opened += 1;
    mockFeed.frames.add(onFrame);
    if (onState) { mockFeed.states.add(onState); onState(mockFeed.state); }
    return () => { mockFeed.closed += 1; mockFeed.frames.delete(onFrame); if (onState) mockFeed.states.delete(onState); };
  },
}));

import * as harness from '@/lib/harness';
import * as data from '@/lib/revamp-data';
import { emitFeedTurn } from '@/lib/feed-turns';
import StudioPage from '@/app/(app)/studio/page';
import { BACK_FULL_MS, FIRST_DRAW_MS, READS_IN_FLIGHT, READ_TIMEOUT_MS, RETRY_FIRST_MS, forgetSetupReads } from './setups';
import { PAUSED_AFTER_MS } from '@/lib/use-workspace-feed';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const hx = harness as jest.Mocked<typeof harness>;
const dx = data as jest.Mocked<typeof data>;
// a harness feed in this tab reports a turn's start or end, as useHarnessBus does
const turn = (sid: string, h: string, on: boolean) => act(() => { emitFeedTurn(sid, h, on); });
// the workspace feed's stream comes up, drops, or sends a frame
const feedState = async (s: FeedState) => {
  mockFeed.state = s;
  await act(async () => { mockFeed.states.forEach((f) => f(s)); });
  await flush();
};
// the stream drops and comes back at once (a gateway restart): one catch-up read
const reconnect = async () => { await feedState('down'); await feedState('up'); };
const STATUS: Record<string, string> = { 'harness.turn.started': 'running', 'response.completed': 'completed', 'response.failed': 'failed', 'response.incomplete': 'incomplete' };
const frame = (sid: string, harness: string, type = 'harness.turn.started') => act(() => {
  mockFeed.frames.forEach((f) => f({ session_id: sid, harness_id: harness, workspace: 'ws.t', member: 'ana@example.com', type, status: STATUS[type], at: Date.now() / 1000 }));
});

const H = (id: string, name: string, more: Partial<CustomHarness> = {}): CustomHarness => ({
  id, name, base: 'hermes', baseLabel: 'Hermes', defaultModel: 'glm-5', systemPrompt: '', mcpServers: [], skills: [], createdAt: 1, ...more,
} as unknown as CustomHarness);
const secs = () => Math.floor(Date.now() / 1000);
const card = (sid: string, status: string, elapsed = 0): TraceCard => ({
  session_id: sid, status, harness_id: 'h1', finished_at: secs() - (status === 'running' ? 5 : 0), ...(elapsed ? { elapsed } : {}),
});
// each setup's tasks, newest first, as the server answers them now; a setup in `fail` answers with an
// error (the console's proxy under a burst), one in `hang` never answers
let tasks: Record<string, TraceCard[]> = {};
const fail = new Set<string>();
const hang = new Set<string>();
let vis: DocumentVisibilityState = 'visible';

let root: Root;
let el: HTMLElement;
const flush = async () => { for (let i = 0; i < 10; i++) await act(async () => { await Promise.resolve(); }); };
const wait = async (ms: number) => { await act(async () => { jest.advanceTimersByTime(ms); }); await flush(); };
const cardOf = (id: string) => el.querySelector(`.card[data-agent="${id}"]`) as HTMLElement;
const rowOfList = (id: string) => el.querySelector(`.row[data-agent="${id}"]`) as HTMLElement;
const pill = (box: HTMLElement) => box.querySelector('.pill')?.textContent;
const figures = (id: string) => Array.from(cardOf(id).querySelectorAll('.card-stats dd')).map((d) => d.textContent);
const meta = () => el.querySelector('.meta')?.textContent || '';
const liveOff = () => el.querySelector('.live-off');
const reads = () => dx.fetchHarnessTasks.mock.calls.length;
const view = async (label: 'Cards' | 'List') => {
  const b = Array.from(el.querySelectorAll('.vm-seg button')).find((x) => x.textContent === label) as HTMLButtonElement;
  await act(async () => { b.click(); });
};
const setVis = async (v: DocumentVisibilityState) => { vis = v; await act(async () => { document.dispatchEvent(new Event('visibilitychange')); }); await flush(); };

async function open() {
  el = document.createElement('div');
  document.body.appendChild(el);
  root = createRoot(el);
  await act(async () => { root.render(<StudioPage />); });
  await flush();
}

beforeAll(() => {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => vis });
});
beforeEach(() => {
  jest.useFakeTimers({ doNotFake: ['queueMicrotask', 'nextTick'] });
  jest.clearAllMocks();
  forgetSetupReads();
  vis = 'visible';
  try { localStorage.clear(); } catch { /* none */ }
  tasks = { h1: [], h2: [] };
  Object.assign(mockFeed, { state: 'down', opened: 0, closed: 0, reconnects: 0 });
  hx.listCustom.mockResolvedValue([H('h1', 'Support bot'), H('h2', 'Quiet one')]);
  fail.clear(); hang.clear();
  dx.fetchHarnessTasks.mockImplementation(async (id: string) => {
    if (hang.has(id)) return new Promise<never>(() => {});
    if (fail.has(id)) throw new data.TasksReadError(id, 502);
    return { sessions: tasks[id] || [], cursor: '' };
  });
});
afterEach(() => { act(() => root.unmount()); el.remove(); jest.useRealTimers(); });

test('a turn starting turns the setup\'s running indicator on, in both views, and its end turns it off', async () => {
  await open();
  expect(cardOf('h1').querySelector('.card-run')).toBeNull();

  // a person's test task starts on the setup: its feed says so, and the row is read again
  tasks.h1 = [card('s1', 'running')];
  await turn('s1', 'h1', true);
  await wait(600);
  expect(cardOf('h1').querySelector('.card-run')?.textContent).toBe('Running');
  expect(cardOf('h2').querySelector('.card-run')).toBeNull();
  await view('List');
  expect(rowOfList('h1').querySelector('.dot.run.ag-run')?.getAttribute('aria-label')).toBe('Running');
  expect(rowOfList('h2').querySelector('.ag-run')).toBeNull();

  // it ends
  tasks.h1 = [card('s1', 'completed')];
  await turn('s1', 'h1', false);
  await wait(600);
  expect(rowOfList('h1').querySelector('.ag-run')).toBeNull();
  await view('Cards');
  expect(cardOf('h1').querySelector('.card-run')).toBeNull();
  // only that setup was read again: one read of each at the start, two more of h1
  expect(dx.fetchHarnessTasks.mock.calls.filter(([id]) => id === 'h2')).toHaveLength(1);
  expect(dx.fetchHarnessTasks.mock.calls.filter(([id]) => id === 'h1')).toHaveLength(3);
});

test('a task that started while the watch was down shows once it is back: running, then healthy, with its numbers', async () => {
  mockFeed.state = 'up';
  await open();
  expect(pill(cardOf('h1'))).toBe('Idle');
  expect(cardOf('h1').querySelector('.card-conn')?.textContent).toBe('No tasks yet');

  // the watch goes down; a task (an app's, sent with an API key) starts meanwhile: no frame says it,
  // and the page reads nothing in the watch's place
  await feedState('down');
  const before = reads();
  tasks.h1 = [card('s2', 'running')];
  await wait(10 * 60_000);
  expect(reads()).toBe(before);
  expect(cardOf('h1').querySelector('.card-run')).toBeNull();   // the list as last read, and the page says so
  expect(liveOff()).not.toBeNull();

  // the watch is back: one catch-up read shows the task running
  await feedState('up');
  expect(reads()).toBe(before + 2);
  expect(cardOf('h1').querySelector('.card-run')).not.toBeNull();
  expect(liveOff()).toBeNull();

  // it finishes: its end frame
  tasks.h1 = [card('s2', 'completed', 8)];
  await frame('s2', 'h1', 'response.completed');
  await wait(600);
  const c = cardOf('h1');
  expect(pill(c)).toBe('Healthy');
  expect(c.querySelector('.card-run')).toBeNull();
  expect(c.querySelector('.card-conn')?.textContent).toBe('Last task just now');
  expect(figures('h1')).toEqual(['1', '100.0%', '—']);        // a p95 needs three finished tasks
  await view('List');
  expect(pill(rowOfList('h1'))).toBe('Healthy');
  expect(pill(rowOfList('h2'))).toBe('Idle');
});

test('a setup’s health and p95 come from its tasks of the day: three finished, two failed is Failing', async () => {
  tasks.h1 = [card('a', 'failed', 12), card('b', 'failed', 30), card('c', 'completed', 61)];
  tasks.h2 = [card('d', 'completed', 5), card('e', 'completed', 9), card('f', 'completed', 90)];
  await open();
  expect(pill(cardOf('h1'))).toBe('Failing');
  expect(figures('h1')).toEqual(['3', '33.3%', '1m 01s']);
  expect(pill(cardOf('h2'))).toBe('Healthy');
  expect(figures('h2')).toEqual(['3', '100.0%', '1m 30s']);
  expect(meta()).toContain('6 tasks in 24 h');
  expect(meta()).not.toMatch(/\$/);
});

test('nothing is read on a timer; shown again, the stream opens and the rows are read once', async () => {
  mockFeed.state = 'up';
  await open();
  // the first load, and one catch-up read after it (the stream came up while it read)
  expect(reads()).toBe(4);
  await wait(10 * 60_000);
  expect(reads()).toBe(4);

  await setVis('hidden');
  await wait(45_000);
  expect(reads()).toBe(4);

  // shown again after 45 s: the stream is up again and the tasks are read once, the records are not
  await setVis('visible');
  expect(reads()).toBe(6);
  expect(hx.listCustom).toHaveBeenCalledTimes(1);
  await wait(10 * 60_000);
  expect(reads()).toBe(6);

  // away longer than a minute: the records are read again too (a setup may have been made meanwhile)
  await setVis('hidden');
  await wait(BACK_FULL_MS + 1000);
  await setVis('visible');
  expect(hx.listCustom).toHaveBeenCalledTimes(2);
  expect(reads()).toBe(8);
  await wait(10 * 60_000);
  expect(reads()).toBe(8);
});

// ── the workspace feed ─────────────────────────────────────────────────────────────────────────────

const readsOf = (id: string) => dx.fetchHarnessTasks.mock.calls.filter(([x]) => x === id).length;

test('a frame from the workspace feed updates its setup\'s card at once, with no polling while the stream is up', async () => {
  mockFeed.state = 'up';
  await open();
  expect(mockFeed.opened).toBe(1);                       // one watch for the tab
  expect(pill(cardOf('h1'))).toBe('Idle');
  const [h1, h2] = [readsOf('h1'), readsOf('h2')];

  // a minute passes with the stream up: nothing is read
  await wait(60_000);
  expect([readsOf('h1'), readsOf('h2')]).toEqual([h1, h2]);

  // a task starts: its frame shows on that setup at once, with no read
  await frame('s9', 'h1');
  expect(cardOf('h1').querySelector('.card-run')?.textContent).toBe('Running');
  await wait(600);
  expect([readsOf('h1'), readsOf('h2')]).toEqual([h1, h2]);

  // it ends: at once, and only that setup is read again for its numbers
  tasks.h1 = [card('s9', 'completed')];
  await frame('s9', 'h1', 'response.completed');
  expect(cardOf('h1').querySelector('.card-run')).toBeNull();
  await wait(600);
  expect(figures('h1')).toEqual(['1', '100.0%', '—']);
  expect(pill(cardOf('h1'))).toBe('Healthy');
  await view('List');
  expect(pill(rowOfList('h1'))).toBe('Healthy');
  expect(rowOfList('h1').querySelector('.ag-run')).toBeNull();
  expect([readsOf('h1'), readsOf('h2')]).toEqual([h1 + 1, h2]);

  // a frame for a task of no setup on this page reads nothing
  await frame('s10', 'h-elsewhere');
  await wait(600);
  expect(dx.fetchHarnessTasks).toHaveBeenCalledTimes(h1 + h2 + 1);
});

test('when the stream drops nothing is read in its place; past a few seconds the page says so, with Try again; back up, it reads once', async () => {
  mockFeed.state = 'up';
  await open();
  const base = reads();

  // the stream errors (a gateway restart ends it) and comes back within moments: nothing is said
  await feedState('down');
  await wait(PAUSED_AFTER_MS - 1000);
  expect(liveOff()).toBeNull();
  await feedState('up');
  expect(reads()).toBe(base + 2);                           // its one catch-up read
  await wait(PAUSED_AFTER_MS * 2);
  expect(liveOff()).toBeNull();

  // it drops and stays down: past PAUSED_AFTER_MS the page says its list may be out of date
  await feedState('down');
  tasks.h2 = [card('s3', 'running')];
  await wait(PAUSED_AFTER_MS);
  expect(liveOff()?.textContent).toBe('Live updates paused. This list may be out of date. Try again');
  expect(liveOff()?.getAttribute('role')).toBe('status');
  await wait(10 * 60_000);
  expect(reads()).toBe(base + 2);                           // no read in the feed's place
  expect(cardOf('h2').querySelector('.card-run')).toBeNull();   // the list as last read
  await view('List');
  expect(liveOff()).not.toBeNull();                         // both views
  await view('Cards');

  // Try again connects the stream at once
  const again = liveOff()?.querySelector('button') as HTMLButtonElement;
  await act(async () => { again.click(); });
  expect(mockFeed.reconnects).toBe(1);

  // it is back: one read at once (the turn that started meanwhile), and the line goes
  await feedState('up');
  expect(reads()).toBe(base + 4);
  expect(cardOf('h2').querySelector('.card-run')?.textContent).toBe('Running');
  expect(liveOff()).toBeNull();
  await wait(10 * 60_000);
  expect(reads()).toBe(base + 4);
});

test('a watch that never comes up (its reads fail): the rows are read once, never on a timer, and the page says so', async () => {
  mockFeed.state = 'down';
  await open();
  expect(reads()).toBe(2);
  expect(pill(cardOf('h1'))).toBe('Idle');
  expect(liveOff()).toBeNull();
  await wait(PAUSED_AFTER_MS);
  expect(liveOff()).not.toBeNull();
  await wait(10 * 60_000);
  expect(reads()).toBe(2);
});

test('a setup list that could not be read says only that: no paused line, no empty-workspace cue', async () => {
  hx.listCustom.mockRejectedValue(new Error('Request failed.'));
  await open();
  await wait(PAUSED_AFTER_MS);
  expect(el.querySelector('[role="alert"]')?.textContent).toContain('Your setups could not be read just now.');
  expect(liveOff()).toBeNull();
  expect(el.querySelector('.new-card.hi')).toBeNull();
  expect(el.querySelector('.btn.primary.pulse')).toBeNull();
  expect(meta()).not.toContain('No setups yet');
});

test('the stream is closed while the page is hidden and opened again when it is shown', async () => {
  mockFeed.state = 'up';
  await open();
  expect([mockFeed.opened, mockFeed.closed]).toEqual([1, 0]);
  await setVis('hidden');
  expect([mockFeed.opened, mockFeed.closed]).toEqual([1, 1]);
  const n = reads();
  await wait(30_000);
  expect(reads()).toBe(n);                                // hidden: nothing read, no stream
  await setVis('visible');
  expect([mockFeed.opened, mockFeed.closed]).toEqual([2, 1]);
  act(() => root.unmount());
  expect(mockFeed.closed).toBe(2);
  root = createRoot(el);                                  // afterEach unmounts it again
});

// ── what a row claims when a read fails (Richard, 10-19) ──────────────────────────────────────────

test('a read that fails keeps the row: a healthy setup stays as it was read, with its numbers, in both views', async () => {
  tasks.h1 = [card('s1', 'completed')];
  mockFeed.state = 'up';
  await open();
  expect(pill(cardOf('h1'))).toBe('Healthy');
  expect(figures('h1')).toEqual(['1', '100.0%', '—']);
  expect(meta()).toContain('1 task in 24 h');

  // the next reads of it fail (the catch-up when the stream comes back)
  fail.add('h1');
  await reconnect();
  expect(pill(cardOf('h1'))).toBe('Healthy');
  expect(figures('h1')).toEqual(['1', '100.0%', '—']);
  expect(cardOf('h1').querySelector('.card-conn')?.textContent).toBe('Last task just now');
  // the header totals only what every row's read says: one row's read failed, so it totals nothing
  expect(meta()).not.toContain('task');
  await view('List');
  expect(pill(rowOfList('h1'))).toBe('Healthy');
  expect(Array.from(rowOfList('h1').querySelectorAll('span.r')).map((x) => x.textContent)).toEqual(['1', '100.0%', '—', 'just now']);

  // it answers again: the setup alone is read again shortly, and the header totals again
  fail.delete('h1');
  const before = readsOf('h1');
  await wait(RETRY_FIRST_MS);
  expect(readsOf('h1')).toBe(before + 1);
  expect(meta()).toContain('1 task in 24 h');
});

test('a read that fails on the first load claims nothing: no health, no number, and it is read again shortly', async () => {
  tasks.h2 = [card('t1', 'completed')];
  fail.add('h1');
  await open();
  const c = cardOf('h1');
  expect(c.querySelector('.pill')).toBeNull();
  expect(c.querySelector('.pill-sk')).not.toBeNull();
  expect(c.textContent).not.toContain('Idle');
  expect(c.textContent).not.toContain('No tasks yet');
  expect(figures('h1')).toEqual(['—', '—', '—']);
  expect(pill(cardOf('h2'))).toBe('Healthy');
  // a total over the rows that answered would read as the whole: the header leaves it out
  expect(meta()).toContain('2 setups');
  expect(meta()).not.toContain('task');
  await view('List');
  expect(rowOfList('h1').querySelector('.pill-sk')).not.toBeNull();
  expect(rowOfList('h1').textContent).not.toContain('Idle');

  // its read answers on the retry
  fail.delete('h1');
  tasks.h1 = [card('s1', 'completed')];
  await wait(RETRY_FIRST_MS);
  expect(pill(rowOfList('h1'))).toBe('Healthy');
  expect(meta()).toContain('2 tasks in 24 h');
});

test('a start frame shows running at once; an end frame reads again, and again shortly while the card does not show the end', async () => {
  mockFeed.state = 'up';
  await open();
  // a task starts: running at once
  await frame('s5', 'h1', 'harness.turn.started');
  expect(cardOf('h1').querySelector('.card-run')?.textContent).toBe('Running');
  const [r0, other] = [readsOf('h1'), readsOf('h2')];

  // it ends while its card still reads running: the row shows the end at once, the read a moment
  // after does not take it back, and one more read follows a second later
  tasks.h1 = [card('s5', 'running')];
  await frame('s5', 'h1', 'response.completed');
  expect(cardOf('h1').querySelector('.card-run')).toBeNull();
  await wait(600);
  expect(readsOf('h1')).toBe(r0 + 1);
  expect(cardOf('h1').querySelector('.card-run')).toBeNull();
  tasks.h1 = [card('s5', 'completed')];
  await wait(1000);
  expect(readsOf('h1')).toBe(r0 + 2);
  await wait(10_000);
  expect(readsOf('h1')).toBe(r0 + 2);           // the card shows the end: nothing more is read
  expect(readsOf('h2')).toBe(other);
});

test('a catch-up read that hangs ends at its deadline, and the next catch-up runs', async () => {
  const warn = jest.spyOn(console, 'warn').mockImplementation(() => {});
  mockFeed.state = 'up';
  await open();
  hang.add('h1');
  await reconnect();                            // the catch-up: h1's read never answers
  const h2 = readsOf('h2');
  await wait(READ_TIMEOUT_MS);                  // its deadline
  expect(warn).toHaveBeenCalledWith(expect.stringContaining('h1'));
  expect(pill(cardOf('h1'))).toBe('Idle');      // what it last read, still
  hang.delete('h1');
  await reconnect();
  expect(readsOf('h2')).toBe(h2 + 1);           // the next catch-up ran
  warn.mockRestore();
});

test('at most a few setups are read at once; the rows draw on time and fill in place', async () => {
  const many = Array.from({ length: 14 }, (_, i) => H(`m${i}`, `Setup ${i}`));
  hx.listCustom.mockResolvedValue(many);
  let out = 0, peak = 0;
  const answer: (() => void)[] = [];
  dx.fetchHarnessTasks.mockImplementation(() => new Promise((resolve) => {
    out += 1; peak = Math.max(peak, out);
    answer.push(() => { out -= 1; resolve({ sessions: [], cursor: '' }); });
  }));
  await open();
  expect(out).toBe(READS_IN_FLIGHT);
  expect(el.querySelectorAll('.card[data-agent]')).toHaveLength(0);
  // the rows draw while reads are still out, claiming nothing for those
  await wait(FIRST_DRAW_MS);
  expect(el.querySelectorAll('.card[data-agent]')).toHaveLength(14);
  expect(el.querySelectorAll('.card[data-agent] .pill-sk')).toHaveLength(14);
  while (answer.length) { await act(async () => { answer.shift()?.(); }); await flush(); }
  expect(peak).toBe(READS_IN_FLIGHT);
  expect(dx.fetchHarnessTasks).toHaveBeenCalledTimes(14);
  expect(el.querySelectorAll('.card[data-agent] .pill-sk')).toHaveLength(0);
  expect(pill(cardOf('m13'))).toBe('Idle');
});
