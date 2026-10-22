/** @jest-environment jsdom */
// A first turn the gateway refuses for credits is a CREDITS refusal all the way to the UI: the
// error the stream throws carries the HTTP status, so the controller opens the credits door and
// reads the balance, and reports the block as out_of_credits. A real transport failure (the POST
// never answered) still reports as transport and opens no door — the status is what tells them
// apart, and an error without one is a transport drop.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const mockFetch = jest.fn();
jest.mock('@/lib/hfetch', () => ({ harnessFetch: (...a: unknown[]) => mockFetch(...a) }));
jest.mock('@/lib/auth', () => ({ getSession: () => ({ orgId: 'o1', token: 't', member: { email: 'a@b.c' } }), handleAuthExpired: jest.fn() }));
jest.mock('@/lib/workspace', () => ({ getCurrentWorkspaceRef: () => null, workspaceHeaders: () => ({}) }));
const mockTrack = jest.fn();
jest.mock('@/lib/analytics', () => ({ track: (...a: unknown[]) => mockTrack(...a) }));
const mockBalance = jest.fn(async () => ({ balance: 12.4 }));
jest.mock('@/app/(app)/billing/lib', () => ({ billing: { balance: () => mockBalance(), refresh: jest.fn(), get: () => null } }));
jest.mock('@/lib/harness', () => ({ oobById: () => null }));
jest.mock('@/lib/tool-steps', () => ({ fillStep: (s: unknown) => s }));
jest.mock('reifyui', () => {
  const { useSyncExternalStore } = jest.requireActual('react');
  const store = new Map<string, Record<string, unknown>>();
  const subs = new Map<string, Set<() => void>>();
  const get = (k: string) => { let s = store.get(k); if (!s) { s = { msgs: [], busy: false, prevId: null, firstTurn: true, loaded: false }; store.set(k, s); } return s; };
  const set = (k: string, p: unknown) => { const cur = get(k); store.set(k, { ...cur, ...(typeof p === 'function' ? (p as (c: unknown) => object)(cur) : p as object) }); subs.get(k)?.forEach((f) => f()); };
  const use = (k: string) => useSyncExternalStore((cb: () => void) => { const x = subs.get(k) || new Set(); subs.set(k, x); x.add(cb); return () => { x.delete(cb); }; }, () => get(k), () => get(k));
  const id = <T,>(x: T) => x;
  return { createConversationStore: () => ({ get, set, use, seed: (k: string, v: Record<string, unknown>) => store.set(k, v), updateLastAssistant: () => undefined }),
           withText: id, withReasoning: id, withStep: id, withResult: id,
           pumpResponsesStream: async () => null, readSSEStream: async () => undefined };
});

import { useConversationTurn } from './conversation';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let api: ReturnType<typeof useConversationTurn>;
let root: Root; let el: HTMLDivElement;
function Conv() {
  api = useConversationTurn({ harnessId: 'h1', sessionId: null, target: { name: 'Helper', backend: 'codex' } as never, onRan: () => {} });
  return null;
}
const flush = async (ms = 0) => {
  await act(async () => { await jest.advanceTimersByTimeAsync(ms); });
  for (let i = 0; i < 6; i++) await act(async () => { await Promise.resolve(); });
};
/** The broadcast-bus subscription shares harnessFetch; keep it quiet and answer /v1/responses. */
const answerResponses = (reply: () => unknown) => {
  mockFetch.mockImplementation((path: string) => {
    if (String(path).includes('/v1/responses')) return reply();
    return Promise.resolve({ ok: false, body: null, status: 503 });
  });
};
const blockedCalls = () => mockTrack.mock.calls.filter((c) => c[0] === 'task_blocked');

beforeEach(() => { jest.useFakeTimers(); mockFetch.mockReset(); mockTrack.mockReset(); mockBalance.mockClear();
  el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el); });
afterEach(() => { act(() => root.unmount()); el.remove(); jest.useRealTimers(); });

test('a 402 on the first turn is reported out_of_credits and opens the credits door with the balance', async () => {
  answerResponses(() => Promise.resolve({
    ok: false, status: 402, body: null,
    text: async () => JSON.stringify({ detail: 'Out of credits. Top up to keep running turns.' }),
  }));
  await act(async () => { root.render(<Conv />); });
  await flush();
  await act(async () => { await api.send('hello'); });
  await flush();
  expect(blockedCalls()).toHaveLength(1);
  expect(blockedCalls()[0][1]).toMatchObject({ reason: 'out_of_credits' });
  expect(mockBalance).toHaveBeenCalledTimes(1);
  expect(api.outOfCredits).toEqual({ balance: 12 });
});

test('a POST that never answers is still reported transport and opens no credits door', async () => {
  answerResponses(() => Promise.reject(new TypeError('Failed to fetch')));
  await act(async () => { root.render(<Conv />); });
  await flush();
  await act(async () => { await api.send('hello'); });
  await flush();
  expect(blockedCalls()).toHaveLength(1);
  expect(blockedCalls()[0][1]).toMatchObject({ reason: 'transport' });
  expect(mockBalance).not.toHaveBeenCalled();
  expect(api.outOfCredits).toBe(null);
});

test('a 500 on the first turn is reported other, not credits', async () => {
  answerResponses(() => Promise.resolve({ ok: false, status: 500, body: null, text: async () => 'boom' }));
  await act(async () => { root.render(<Conv />); });
  await flush();
  await act(async () => { await api.send('hello'); });
  await flush();
  expect(blockedCalls()[0][1]).toMatchObject({ reason: 'other' });
  expect(api.outOfCredits).toBe(null);
});
