/** @jest-environment jsdom */
// The coding-agent guides' step 5 (Start in your codebase, Migrate an existing agent): the setup the
// coding agent saved (new since the guide opened, saved after the prompt was copied) is connected once a
// task has ended on it. Nothing pushes a save or a task's end here, so while the sheet waits it reads
// the list and each new setup's newest tasks every POLL_MS, and stops once everything is connected.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

jest.mock('next/navigation', () => ({ useRouter: () => ({ push: jest.fn() }) }));
jest.mock('@/lib/harness', () => ({ listCustom: jest.fn() }));
jest.mock('@/lib/revamp-data', () => ({ RUNNING: new Set(['running', 'queued', 'in_progress']) }));
jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn(async () => ({ ok: true, status: 200, json: async () => ({ keys: [] }) })) }));
jest.mock('@/lib/auth', () => ({ getSession: jest.fn(() => ({ orgId: 'org.t', member: { email: 'me@example.com' } })) }));
jest.mock('@/lib/workspace', () => ({ useWorkspace: jest.fn(() => ({ current: { id: 'ws.test', name: 'Test Workspace' }, defaultId: 'ws.default' })) }));
jest.mock('@/lib/analytics', () => ({ track: jest.fn() }));
jest.mock('../toast', () => ({ toast: jest.fn() }));
jest.mock('../setups', () => ({ newestTasks: jest.fn() }));

import { listCustom } from '@/lib/harness';
import { newestTasks } from '../setups';
import { Handoff, POLL_MS } from './Handoff';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const list = listCustom as jest.Mock;
const tasks = newestTasks as jest.Mock;
const OLD = { id: 'chrn_old', name: 'Old', createdAt: 1 };
let saved: Record<string, unknown>[];
let root: Root;
let el: HTMLElement;

const body = () => (document.body.textContent || '').replace(/\s+/g, ' ');
const button = (label: string) => Array.from(document.body.querySelectorAll('button')).find((b) => (b.textContent || '').trim() === label) || null;
const passTime = (ms: number) => act(async () => { await jest.advanceTimersByTimeAsync(ms); });
const connected = () => document.querySelector('.hand-foot .ok-t')?.textContent === 'Connected';

async function openAndCopy() {
  await act(async () => { root.render(<Handoff kind="new" onClose={() => {}} />); });
  await passTime(0);
  await act(async () => { button('Copy prompt')!.click(); });
  await passTime(0);
}
/** the coding agent saves its setup; the sheet's list read finds it */
async function agentSaves(extra: Record<string, unknown> = {}) {
  saved = [{ id: 'chrn_new', name: 'Support bot', createdAt: Date.now(), ...extra }];
  await passTime(5000);
}

beforeEach(() => {
  jest.useFakeTimers();
  saved = [];
  list.mockReset();
  list.mockImplementation(async () => [OLD, ...saved]);
  tasks.mockReset();
  tasks.mockResolvedValue({ sessions: [], cursor: '' });
  Object.defineProperty(navigator, 'clipboard', { value: { writeText: jest.fn(async () => undefined) }, configurable: true });
  el = document.createElement('div'); document.body.appendChild(el);
  root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); el.remove(); document.body.innerHTML = ''; jest.useRealTimers(); });

// each test ends connected, so the next opens a fresh guide (a guide picks up where it was left)
it('before the prompt is copied it reads the list once (what was there), and nothing on a timer', async () => {
  await act(async () => { root.render(<Handoff kind="new" onClose={() => {}} />); });
  await passTime(0);
  expect(list).toHaveBeenCalledTimes(1);
  await passTime(POLL_MS * 4);
  expect(list).toHaveBeenCalledTimes(1);
  expect(tasks).not.toHaveBeenCalled();
  // finish this guide, so the next test opens a fresh one
  await act(async () => { button('Copy prompt')!.click(); });
  saved = [{ id: 'chrn_new', name: 'Support bot', createdAt: Date.now() }];
  tasks.mockResolvedValue({ sessions: [{ session_id: 's0', status: 'completed' }], cursor: '' });
  await passTime(POLL_MS);
  expect(connected()).toBe(true);
});

it('finds the saved setup on the list, and it is connected once a task has ended on it; then nothing more is read', async () => {
  await openAndCopy();
  await agentSaves();
  expect(body()).toContain('chrn_new');
  expect(connected()).toBe(false);
  expect(tasks).toHaveBeenLastCalledWith('chrn_new');
  // the app's first task is still running: not yet
  tasks.mockResolvedValue({ sessions: [{ session_id: 's1', status: 'running' }], cursor: '' });
  await passTime(POLL_MS);
  expect(connected()).toBe(false);
  // it ends
  tasks.mockResolvedValue({ sessions: [{ session_id: 's1', status: 'completed' }], cursor: '' });
  await passTime(POLL_MS);
  expect(connected()).toBe(true);
  const reads = list.mock.calls.length, taskReads = tasks.mock.calls.length;
  await passTime(POLL_MS * 4);
  expect(list.mock.calls.length).toBe(reads);
  expect(tasks.mock.calls.length).toBe(taskReads);
});

it('a setup that was there before the guide opened is never the one saved, and its tasks are not read', async () => {
  await openAndCopy();
  await passTime(POLL_MS * 2);
  expect(tasks).not.toHaveBeenCalled();
  expect(body()).not.toContain('chrn_old');
  await agentSaves();
  tasks.mockResolvedValue({ sessions: [{ session_id: 's2', status: 'failed' }], cursor: '' });
  await passTime(POLL_MS);
  expect(tasks.mock.calls.every(([id]) => id === 'chrn_new')).toBe(true);
  expect(connected()).toBe(true);
});

it('a list read that fails claims nothing and is read again', async () => {
  await openAndCopy();
  list.mockRejectedValueOnce(new Error('offline'));
  saved = [{ id: 'chrn_new', name: 'Support bot', createdAt: Date.now() }];
  await passTime(POLL_MS);
  expect(body()).not.toContain('chrn_new');
  expect(connected()).toBe(false);
  tasks.mockResolvedValue({ sessions: [{ session_id: 's3', status: 'completed' }], cursor: '' });
  await passTime(POLL_MS);
  expect(connected()).toBe(true);
});

it('a tasks read that fails claims nothing and is read again', async () => {
  await openAndCopy();
  tasks.mockRejectedValueOnce(new Error('503'));
  await agentSaves();
  expect(connected()).toBe(false);
  tasks.mockResolvedValue({ sessions: [{ session_id: 's4', status: 'completed' }], cursor: '' });
  await passTime(POLL_MS);
  expect(connected()).toBe(true);
});
