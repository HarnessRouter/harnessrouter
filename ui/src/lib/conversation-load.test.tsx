/** @jest-environment jsdom */
// Opening a task whose turns could not be read writes nothing: the task is not drawn new and empty,
// the page is told (loadFailed) with a way to read again (reload), and no message is sent from it
// until a read succeeds. A 404 is still a task that is gone.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const mockLoad = jest.fn();
const mockStream = jest.fn();
jest.mock('@/lib/chat', () => ({
  loadSessionTurns: (...a: unknown[]) => mockLoad(...a),
  streamResponse: (...a: unknown[]) => mockStream(...a),
  subscribeHarnessEvents: () => () => {},
  cancelSession: jest.fn(async () => ({ cancelled: true, status: 'cancelled' })),
}));
jest.mock('@/lib/workspace', () => ({ getCurrentWorkspaceRef: () => null }));
jest.mock('@/lib/analytics', () => ({ track: jest.fn() }));
jest.mock('@/app/(app)/billing/lib', () => ({ billing: { refresh: jest.fn(), get: () => null } }));
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
           withText: id, withReasoning: id, withStep: id, withResult: id };
});

import { useConversationTurn, getConvState } from './conversation';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let api: ReturnType<typeof useConversationTurn>;
let root: Root; let el: HTMLDivElement;
const missing = jest.fn();
function Conv({ sid }: { sid: string }) {
  api = useConversationTurn({ harnessId: 'h1', sessionId: sid, target: { name: 'Helper', backend: 'codex' } as never, onRan: () => {}, onMissing: missing });
  return null;
}
const flush = async (ms = 0) => {
  await act(async () => { await jest.advanceTimersByTimeAsync(ms); });
  for (let i = 0; i < 6; i++) await act(async () => { await Promise.resolve(); });
};
const turn = { id: 'resp_1', status: 'completed', user: 'hi', assistant: 'Done.', tools: [], files: [] };

beforeEach(() => { jest.useFakeTimers(); mockLoad.mockReset(); mockStream.mockReset(); missing.mockReset();
  el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el); });
afterEach(() => { act(() => root.unmount()); el.remove(); jest.useRealTimers(); });

test('a read that fails twice writes nothing and says so; Try again reads it', async () => {
  mockLoad.mockRejectedValue(new Error('503'));
  await act(async () => { root.render(<Conv sid="hsessA" />); });
  await flush();
  expect(mockLoad).toHaveBeenCalledTimes(1);
  expect(api.loadFailed).toBe(false);                    // one quiet second try first
  await flush(1500);
  expect(mockLoad).toHaveBeenCalledTimes(2);
  expect(api.loadFailed).toBe(true);
  expect(api.loading).toBe(false);
  expect(getConvState('hsessA').msgs).toEqual([]);
  expect(getConvState('hsessA').loaded).toBe(false);      // not opened as a task with no turns
  // nothing is sent from a task whose conversation is not known
  await act(async () => { await api.send('next'); });
  expect(mockStream).not.toHaveBeenCalled();
  // Try again
  mockLoad.mockResolvedValue({ turns: [turn], lastResponseId: 'resp_1' });
  await act(async () => { api.reload(); });
  await flush();
  expect(api.loadFailed).toBe(false);
  expect(getConvState('hsessA').loaded).toBe(true);
  expect(getConvState('hsessA').msgs.length).toBe(2);
  expect(getConvState('hsessA').prevId).toBe('resp_1');
});

test('a read that fails once and then answers loads quietly', async () => {
  mockLoad.mockRejectedValueOnce(new Error('503')).mockResolvedValue({ turns: [turn], lastResponseId: 'resp_1' });
  await act(async () => { root.render(<Conv sid="hsessB" />); });
  await flush(1500);
  expect(api.loadFailed).toBe(false);
  expect(getConvState('hsessB').msgs.length).toBe(2);
});

test('a task that is gone is still let go of', async () => {
  mockLoad.mockResolvedValue({ turns: [], lastResponseId: null, missing: true });
  await act(async () => { root.render(<Conv sid="hsessC" />); });
  await flush();
  expect(missing).toHaveBeenCalledWith('hsessC');
  expect(api.loadFailed).toBe(false);
});
