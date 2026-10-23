// The workspace watch (lib/workspace-feed): one watch per tab, shared by every listener in it, reading
// the workspace's newest task cards (GET /v1/traces) and telling what changed between two reads as
// frames. Its first read says nothing (it is the watch coming up); a read that fails is 'down' and is
// read again with backoff; Try again reads at once; the last listener leaving stops it. It never asks
// for a workspace stream this gateway does not serve.
import type { FeedFrame, FeedState } from './workspace-feed';

jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
jest.mock('@/lib/auth', () => ({ getSession: () => ({ orgId: 'org.a', member: { email: 'ana@example.com' } }) }));
jest.mock('@/lib/workspace', () => ({
  workspaceHeaders: () => ({ 'x-harness-workspace': mockWs.id }),
  appendWorkspaceQuery: (q: URLSearchParams) => q.set('workspace', mockWs.id),
}));

const mockWs = { id: 'space.a' };

import { harnessFetch } from '@/lib/hfetch';
import { BUSY_MS, FEED_BACKOFF_FIRST_MS, FEED_BACKOFF_MAX_MS, IDLE_MS, framesBetween, reconnectWorkspaceFeed, subscribeWorkspaceFeed } from './workspace-feed';

const hf = harnessFetch as jest.MockedFunction<typeof harnessFetch>;
type Card = { session_id: string; harness_id: string; status: string; finished_at: number; workspace?: string; member_id?: string };
const card = (sid: string, status: string, at: number, harness = 'h1'): Card => ({ session_id: sid, harness_id: harness, status, finished_at: at, workspace: 'space.a', member_id: 'ana@example.com' });
const page = (...cards: Card[]) => new Response(JSON.stringify({ sessions: cards, cursor: '' }), { status: 200, headers: { 'content-type': 'application/json' } });
const fail = (status = 502) => new Response('bad', { status });
const tick = async (ms = 0) => { await jest.advanceTimersByTimeAsync(ms); };
const NOW = () => Date.now() / 1000;

let undo: Array<() => void> = [];
let warn: jest.SpyInstance;
beforeEach(() => { jest.useFakeTimers(); hf.mockReset(); mockWs.id = 'space.a'; warn = jest.spyOn(console, 'warn').mockImplementation(() => {}); });
afterEach(async () => { undo.forEach((u) => u()); undo = []; await tick(); jest.useRealTimers(); warn.mockRestore(); });

function listen() {
  const frames: FeedFrame[] = [];
  const states: FeedState[] = [];
  undo.push(subscribeWorkspaceFeed((f) => frames.push(f), (s) => states.push(s)));
  return { frames, states };
}

test('every listener in the tab shares one watch of the workspace’s task cards; its first read says only that it is up', async () => {
  hf.mockResolvedValueOnce(page(card('s1', 'completed', NOW() - 100)));
  const a = listen(), b = listen();
  await tick();
  expect(hf).toHaveBeenCalledTimes(1);
  const [path, init] = hf.mock.calls[0];
  expect(path).toBe('/api/harness/v1/traces?org=org.a&limit=50&workspace=space.a');
  expect(init?.headers).toEqual({ 'x-harness-org': 'org.a', 'x-harness-member': 'ana@example.com', 'x-harness-workspace': 'space.a' });
  expect(hf.mock.calls.some(([p]) => String(p).includes('/v1/events'))).toBe(false);
  expect(a.states).toEqual(['connecting', 'up']);
  expect(b.states).toEqual(['connecting', 'up']);
  expect(a.frames).toEqual([]);
});

test('a task that starts and ends between reads is told to every listener, as frames', async () => {
  const t0 = NOW();
  hf.mockResolvedValueOnce(page(card('s1', 'completed', t0 - 100)));
  const a = listen(), b = listen();
  await tick();
  hf.mockResolvedValueOnce(page(card('s2', 'running', t0 + 1), card('s1', 'completed', t0 - 100)));
  await tick(IDLE_MS);
  expect(a.frames.map((f) => [f.session_id, f.type, f.status])).toEqual([['s2', 'harness.turn.started', 'running']]);
  expect(b.frames).toHaveLength(1);
  expect(a.frames[0]).toMatchObject({ harness_id: 'h1', workspace: 'space.a', member: 'ana@example.com' });
  // a task runs: the next read comes sooner
  hf.mockResolvedValueOnce(page(card('s2', 'failed', t0 + 5), card('s1', 'completed', t0 - 100)));
  await tick(BUSY_MS);
  expect(a.frames.map((f) => [f.session_id, f.type, f.status])).toEqual([
    ['s2', 'harness.turn.started', 'running'], ['s2', 'response.failed', 'failed']]);
  expect(hf).toHaveBeenCalledTimes(3);
});

test('framesBetween: a follow-up that ran whole between two reads ends; a finished task that only came into view says nothing', () => {
  const seen = new Map([['s1', { running: false, at: 100 }]]);
  expect(framesBetween(seen, [card('s1', 'completed', 160)] as never, 150).map((f) => f.type)).toEqual(['response.completed']);
  expect(framesBetween(seen, [card('s1', 'completed', 100)] as never, 150)).toEqual([]);
  expect(framesBetween(seen, [card('old', 'completed', 90)] as never, 150)).toEqual([]);
  expect(framesBetween(seen, [card('new', 'cancelled', 155)] as never, 150).map((f) => [f.type, f.status])).toEqual([['response.failed', 'cancelled']]);
  expect(framesBetween(seen, [card('cut', 'incomplete', 155)] as never, 150).map((f) => f.type)).toEqual(['response.incomplete']);
});

test('a read that fails is down, read again with backoff, and up again with no frames for what passed meanwhile', async () => {
  hf.mockResolvedValueOnce(page());
  const a = listen();
  await tick();
  hf.mockResolvedValueOnce(fail());
  await tick(IDLE_MS);
  expect(a.states).toEqual(['connecting', 'up', 'down']);
  expect(warn).toHaveBeenCalledTimes(1);
  hf.mockResolvedValueOnce(fail());
  await tick(FEED_BACKOFF_FIRST_MS);
  expect(hf).toHaveBeenCalledTimes(3);
  expect(warn).toHaveBeenCalledTimes(1);                     // the same failure is said once
  hf.mockResolvedValueOnce(page(card('s9', 'running', NOW())));
  await tick(FEED_BACKOFF_FIRST_MS * 2);
  expect(a.states).toEqual(['connecting', 'up', 'down', 'up']);
  expect(a.frames).toEqual([]);                              // a fresh start: the listeners read once instead
});

test('the backoff never waits longer than its cap; a page that is not the list is a failed read', async () => {
  hf.mockImplementation(async () => new Response('<html>', { status: 200, headers: { 'content-type': 'text/html' } }));
  const a = listen();
  await tick();
  expect(a.states).toEqual(['connecting', 'down']);
  for (let i = 0; i < 8; i++) await tick(FEED_BACKOFF_MAX_MS);
  const n = hf.mock.calls.length;
  await tick(FEED_BACKOFF_MAX_MS);
  expect(hf.mock.calls.length).toBe(n + 1);
});

test('Try again reads at once', async () => {
  hf.mockResolvedValueOnce(fail());
  listen();
  await tick();
  expect(hf).toHaveBeenCalledTimes(1);
  hf.mockResolvedValueOnce(page());
  reconnectWorkspaceFeed();
  await tick();
  expect(hf).toHaveBeenCalledTimes(2);
});

test('the last listener leaving stops the watch; a workspace switch watches the new workspace', async () => {
  hf.mockImplementation(async () => page());
  const offA = subscribeWorkspaceFeed(() => {});
  const offB = subscribeWorkspaceFeed(() => {});
  await tick();
  offA();
  await tick(IDLE_MS);
  expect(hf).toHaveBeenCalledTimes(2);
  offB();
  await tick(IDLE_MS * 3);
  expect(hf).toHaveBeenCalledTimes(2);
  mockWs.id = 'space.b';
  undo.push(subscribeWorkspaceFeed(() => {}));
  await tick();
  expect(String(hf.mock.calls[2][0])).toContain('workspace=space.b');
});
