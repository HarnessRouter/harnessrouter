/** @jest-environment jsdom */
// The workspace's keys as every key step reads them (start/keys useWsKeys). A read that fails is never
// "no keys": the list stays unread (or as it last answered), the state says the read failed, and Try
// again reads it once more. A read that answers is the list, newest first, this workspace's only.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
jest.mock('@/lib/auth', () => ({ getSession: () => ({ orgId: 'org1', member: { email: 'ana@example.com' } }) }));
jest.mock('@/lib/workspace', () => ({ useWorkspace: () => ({ current: { id: 'ws1', name: 'Default' }, defaultId: 'ws1' }) }));
jest.mock('@/lib/analytics', () => ({ track: jest.fn() }));
// one try per read here: the quiet second try is lib/settle's own (settle.test.ts)
jest.mock('@/lib/settle', () => ({ readSettled: (read: (s: AbortSignal) => Promise<unknown>) => read(new AbortController().signal) }));
jest.mock('../toast', () => ({ toast: jest.fn() }));

import { harnessFetch } from '@/lib/hfetch';
import { useWsKeys, type KeysState } from './keys';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const fetchMock = harnessFetch as jest.Mock;
const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body });
const down = () => ({ ok: false, status: 503, json: async () => ({}) });
let root: Root;
let el: HTMLElement;
let state: KeysState;

function Probe() { state = useWsKeys(); return null; }
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

beforeEach(() => {
  fetchMock.mockReset();
  el = document.createElement('div'); document.body.appendChild(el);
  root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); el.remove(); });

it('a first read that fails leaves the keys unread, says it failed, and claims no live key', async () => {
  fetchMock.mockResolvedValue(down());
  await act(async () => { root.render(<Probe />); });
  await flush();
  expect(state.keys).toBeNull();
  expect(state.live).toBeNull();
  expect(state.error).toBe(true);
});

it('Try again reads the list again; an answer is the workspace’s keys, newest first, and clears the failure', async () => {
  fetchMock.mockResolvedValueOnce(down());
  await act(async () => { root.render(<Probe />); });
  await flush();
  expect(state.error).toBe(true);
  fetchMock.mockResolvedValue(ok({ keys: [
    { id: 'a', name: 'old', created_at: 1_700_000_000, workspace: 'ws1' },
    { id: 'b', name: 'new', created_at: 1_760_000_000, workspace: 'ws1' },
    { id: 'c', name: 'elsewhere', created_at: 1_770_000_000, workspace: 'ws2' },
  ] }));
  await act(async () => { state.retry(); });
  await flush();
  expect(state.error).toBe(false);
  expect(state.keys?.map((k) => k.id)).toEqual(['b', 'a']);
  expect(state.live?.id).toBe('b');
});

it('a later read that fails keeps the list it last answered, and says it failed', async () => {
  fetchMock.mockResolvedValueOnce(ok({ keys: [{ id: 'a', name: 'prod', created_at: 1_760_000_000, workspace: 'ws1' }] }));
  await act(async () => { root.render(<Probe />); });
  await flush();
  expect(state.keys?.map((k) => k.id)).toEqual(['a']);
  fetchMock.mockRejectedValue(new Error('offline'));
  await act(async () => { state.retry(); });
  await flush();
  expect(state.keys?.map((k) => k.id)).toEqual(['a']);
  expect(state.error).toBe(true);
});
