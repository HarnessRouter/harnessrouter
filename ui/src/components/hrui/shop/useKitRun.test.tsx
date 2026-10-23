/** @jest-environment jsdom */
// The kit page's Trace follows its setup's task. Nothing pushes a task's start or end here, so the
// setup's newest tasks are read every POLL_MS while the page is visible: a new task is found, its end
// turns its card and makes the trace's final read. A running task's trace is read every TRACE_MS. A
// tasks read that fails is read again shortly and claims no task; a trace whose manifest cannot be
// read is a trace that could not be read (Try again), never an empty one.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

jest.mock('@/lib/revamp-data', () => ({ RUNNING: new Set(['running', 'in_progress']), TERMINAL_OK: new Set(['completed']), TERMINAL_BAD: new Set(['failed']) }));
jest.mock('../setups', () => ({ newestTasks: jest.fn() }));
jest.mock('@/studio/traces/api', () => ({ tracesApi: { manifest: jest.fn(), events: jest.fn() } }));
jest.mock('@/studio/traces/flatten', () => ({ flatten: (evs: unknown[]) => evs.map((e, i) => ({ i, kind: 'tool', ...(e as object) })) }));

import { newestTasks } from '../setups';
import { tracesApi } from '@/studio/traces/api';
import { POLL_MS, TRACE_MS, useKitRun, type KitRun } from './useKitRun';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const tasks = newestTasks as jest.Mock;
const manifest = tracesApi.manifest as jest.Mock;
const events = tracesApi.events as jest.Mock;
const nowS = () => Math.floor(Date.now() / 1000);
let run: KitRun;
let root: Root;
let el: HTMLElement;

function Probe({ id }: { id: string | null }) { run = useKitRun(id); return null; }
const passTime = (ms: number) => act(async () => { await jest.advanceTimersByTimeAsync(ms); });
async function open(id: string | null = 'chrn_kit') { await act(async () => { root.render(<Probe id={id} />); }); await passTime(0); }

beforeEach(() => {
  jest.useFakeTimers();
  tasks.mockReset(); tasks.mockResolvedValue({ sessions: [], cursor: '' });
  manifest.mockReset(); manifest.mockResolvedValue({ chunks: [{}] });
  events.mockReset(); events.mockResolvedValue([{ label: 'search' }]);
  el = document.createElement('div'); document.body.appendChild(el);
  root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); el.remove(); jest.useRealTimers(); });

it('reads as the page opens, then every POLL_MS; an older finished task is not happening now', async () => {
  tasks.mockResolvedValue({ sessions: [{ session_id: 's0', status: 'completed', finished_at: nowS() - 3600 }], cursor: '' });
  await open();
  expect(tasks).toHaveBeenCalledTimes(1);
  expect(tasks).toHaveBeenLastCalledWith('chrn_kit');
  await passTime(POLL_MS);
  expect(tasks).toHaveBeenCalledTimes(2);
  expect(run.card).toBeNull();
});

it('no setup yet: nothing is read', async () => {
  await open(null);
  await passTime(POLL_MS * 3);
  expect(tasks).not.toHaveBeenCalled();
});

it('a task that starts is found on the next read; its trace is read while it runs, and its end makes the final read', async () => {
  await open();
  expect(run.card).toBeNull();
  tasks.mockResolvedValue({ sessions: [{ session_id: 's1', status: 'running', created_at: nowS() }], cursor: '' });
  await passTime(POLL_MS);
  expect(run.card?.session_id).toBe('s1');
  expect(run.st).toBe('running');
  expect(run.rows?.length).toBe(1);
  const reads = events.mock.calls.length;
  await passTime(TRACE_MS);
  expect(events.mock.calls.length).toBeGreaterThan(reads);
  // it ends: the card turns, the trace is read a last time, and its trace is read no more
  tasks.mockResolvedValue({ sessions: [{ session_id: 's1', status: 'completed', finished_at: nowS(), elapsed: 4 }], cursor: '' });
  events.mockResolvedValue([{ label: 'search' }, { label: 'answer' }]);
  await passTime(POLL_MS);
  expect(run.st).toBe('done');
  expect(run.rows?.length).toBe(2);
  const after = events.mock.calls.length;
  await passTime(POLL_MS * 5);
  expect(events.mock.calls.length).toBe(after);
});

it('a tasks read that fails is read again shortly, and claims no task meanwhile', async () => {
  tasks.mockRejectedValueOnce(new Error('offline'))
    .mockResolvedValue({ sessions: [{ session_id: 's3', status: 'running', created_at: nowS() }], cursor: '' });
  await open();
  expect(run.card).toBeNull();
  await passTime(2000);
  expect(tasks).toHaveBeenCalledTimes(2);
  expect(run.card?.session_id).toBe('s3');
});

it('a manifest that cannot be read is a trace that could not be read; Try again reads it again', async () => {
  tasks.mockResolvedValue({ sessions: [{ session_id: 's4', status: 'completed', finished_at: nowS(), elapsed: 3 }], cursor: '' });
  manifest.mockRejectedValueOnce(new Error('traces 503'));
  await open();
  expect(run.card?.session_id).toBe('s4');
  expect(run.failed).toBe(true);
  expect(run.rows).toBeNull();
  expect(events).not.toHaveBeenCalled();
  await act(async () => { run.retry(); });
  await passTime(0);
  expect(run.failed).toBe(false);
  expect(run.rows?.length).toBe(1);
});
