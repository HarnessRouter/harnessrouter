/** @jest-environment jsdom */
// The recordings' import (start/replay). One that fails is asked for again with a bounded backoff; one
// that still fails throws, and is never "no recording": a demo is not saved to run live in its place,
// and a saved demo's recorded first task is not dropped (the state says it failed, with Try again).
// The run here is a test fixture: no page ever shows one.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { RecordedRun } from './recorded';

const mockImport = { fails: 0, run: null as unknown };
jest.mock('./recorded', () => {
  if (mockImport.fails > 0) { mockImport.fails -= 1; throw new Error('Loading chunk 412 failed.'); }
  return { RECORDED: [mockImport.run] };
});

import { IMPORT_RETRY_MS, loadRecording, recordedMark, useRecordedRun, useRecordedRunState } from './replay';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const RUN = {
  demo: 0, ranAt: 1_760_000_000_000, base: 'hermes', model: 'gpt-5.4', request: 'A matte black mug.', durMs: 7000, status: 'completed',
  events: [{ t: 0, ev: { type: 'response.created' } }], files: [],
  template: { demo: 0, name: 'Product images', base: 'hermes', model: 'gpt-5.4', instructions: 'x', skills: [], plugins: [] },
} as unknown as RecordedRun;
mockImport.run = RUN;
const passTime = (ms: number) => act(async () => { await jest.advanceTimersByTimeAsync(ms); });
const ALL_TRIES = IMPORT_RETRY_MS.length + 1;
const WAITS = IMPORT_RETRY_MS.reduce((a, b) => a + b, 0);

let root: Root;
let el: HTMLElement;
let state: ReturnType<typeof useRecordedRunState>;
let legacy: RecordedRun | null | undefined;
// every render's answer, with the source it was for
let seen: { source: string | undefined; run: RecordedRun | null | undefined }[] = [];
function Probe({ source }: { source: string | undefined }) {
  state = useRecordedRunState(source); legacy = useRecordedRun(source);
  seen.push({ source, run: state.run });
  return null;
}

beforeEach(() => {
  jest.useFakeTimers();
  el = document.createElement('div'); document.body.appendChild(el);
  root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); el.remove(); jest.useRealTimers(); });

// the import, once it has loaded, stays loaded for this file: the failures come first
it('an import that keeps failing throws after its retries, never "no recording"', async () => {
  mockImport.fails = ALL_TRIES;
  const p = loadRecording(0);
  const seen = p.then(() => 'answered', (e: Error) => e.message);
  await passTime(WAITS);
  expect(await seen).toBe('Loading chunk 412 failed.');
  expect(mockImport.fails).toBe(0);
});

it('a saved demo whose recordings could not be read: failed, with Try again; never "saved from none"', async () => {
  mockImport.fails = ALL_TRIES;
  await act(async () => { root.render(<Probe source={recordedMark(RUN)} />); });
  await passTime(WAITS);
  expect(state.failed).toBe(true);
  expect(state.run).toBeUndefined();
  expect(legacy).toBeUndefined();                                 // the run alone: not known, never null
  await act(async () => { state.retry(); });
  await passTime(0);
  expect(state.failed).toBe(false);
  expect(state.run).toBe(RUN);
});

it('an import that fails once is asked for again, and the recording plays', async () => {
  jest.resetModules();
  // a fresh copy of the module, so its import has not loaded yet
  const fresh = jest.requireActual('./replay') as typeof import('./replay');
  mockImport.fails = 1;
  const p = fresh.loadRecording(0);
  await passTime(IMPORT_RETRY_MS[0]);
  expect(await p).toBe(RUN);
  expect(await fresh.loadRecording(1)).toBeNull();               // a demo with none: null, it runs live
});

it('a setup saved from no recording is null at once', async () => {
  await act(async () => { root.render(<Probe source="" />); });
  expect(state.run).toBeNull();
  expect(state.failed).toBe(false);
});

it('a source that arrives after the page opened is being read, never taken for the last one\'s answer', async () => {
  // the setup's record is read after its page has opened: no source first, then its own
  seen = [];
  await act(async () => { root.render(<Probe source={undefined} />); });
  expect(state.run).toBeNull();
  await act(async () => { root.render(<Probe source={recordedMark(RUN)} />); });
  await passTime(0);
  expect(state.run).toBe(RUN);
  // every render with the source said "being read" until its own read answered: none said "none",
  // which would have opened New task in the recorded task's place
  const forMark = seen.filter((x) => x.source === recordedMark(RUN)).map((x) => x.run);
  expect(forMark[0]).toBeUndefined();
  expect(forMark).not.toContain(null);
  // a run no longer kept (re-recorded since) is none, once its own read says so
  seen = [];
  await act(async () => { root.render(<Probe source="demo:0@1" />); });
  await passTime(0);
  expect(state.run).toBeNull();
  const forGone = seen.filter((x) => x.source === 'demo:0@1').map((x) => x.run);
  expect(forGone[0]).toBeUndefined();
  expect(forGone).not.toContain(RUN);
});
