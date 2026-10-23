/** @jest-environment jsdom */
// A trace's step detail (Richard, 10-18: "why is there a loading indicator that keeps spinning above
// the thinking?"). A long step reads clipped; opening it reads its whole content once, with a loading
// line above the content while that read is out. The line must go once the read answers (or fails),
// whatever the trace does meanwhile: a running task's rows are read again as it changes. A full read
// that fails says the rest could not be read, with Try again (Richard, 10-19: no fallbacks).
//
// A setup's trace (useTrace) is read when it opens and when the task starts or stops running, and on
// push while it runs: each event of the task on the setup's own feed (at most a read a second; its end
// among them) and each reconnect of that feed; never on a timer. A read that fails says so, with Try again: the trace could not be read, or with rows shown,
// that they could not be refreshed.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { BusMsg } from '@/lib/chat';

const fullEvents = jest.fn();
const manifest = jest.fn();
const events = jest.fn();
jest.mock('@/studio/traces/api', () => ({ tracesApi: {
  fullEvents: (sid: string) => fullEvents(sid), manifest: (sid: string) => manifest(sid), events: (sid: string, c: unknown[]) => events(sid, c),
} }));
// the full read hands back rows as they are, so a test says what the whole content is
jest.mock('@/studio/traces/flatten', () => ({ flatten: (evs: unknown[]) => evs }));
jest.mock('../setup/TaskThread', () => ({ Md: ({ text }: { text: string }) => <>{text}</>, prettyJson: () => null }));
const bus: { harness: string; on: ((m: BusMsg) => void) | null; state: ((s: 'up' | 'down') => void) | null; unsub: jest.Mock } = { harness: '', on: null, state: null, unsub: jest.fn() };
jest.mock('@/lib/chat', () => ({
  subscribeHarnessEvents: (h: string, on: (m: BusMsg) => void, st?: (s: 'up' | 'down') => void) => { bus.harness = h; bus.on = on; bus.state = st || null; return bus.unsub; },
}));

import { TraceDetailHost, TraceView, useTrace, TRACE_READ_GAP_MS, type TRow } from './TraceView';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
class RO { observe() {} disconnect() {} unobserve() {} }
Object.assign(globalThis, { ResizeObserver: RO });

const CLIP = 'I should read the file first…[clipped 6000 chars — open to load full]';
const WHOLE = 'I should read the file first, then compare it with the plan, and only then write.';
const rowsOf = (): TRow[] => [
  { i: 0, kind: 'user', label: 'User', text: 'Compare the files', ts: 100 },
  { i: 1, kind: 'thinking', label: 'Thinking', text: CLIP, ts: 101, clipped: true },
  { i: 2, kind: 'agent', label: 'Agent', text: 'Done.', ts: 104 },
  { i: 3, kind: 'result', label: 'Result', text: 'Done.', ts: 104, tokens: { in: 10, out: 4 } },
];
const fullOf = (): TRow[] => rowsOf().map((r) => (r.i === 1 ? { ...r, text: WHOLE, clipped: false } : r));

let root: Root;
let el: HTMLElement;
const view = (rows: TRow[], running = false) => <TraceView sid="hsess1" rows={rows} failed={false} running={running} />;
const body = () => (document.body.textContent || '').replace(/\s+/g, ' ');
const detail = () => (document.body.querySelector('.trv-detail')?.textContent || '').replace(/\s+/g, ' ');
// a read over the network answers after the page has drawn again, never in the same tick
// A read that answers when the test lets it (settle), never on a clock: a 5 ms timer raced the click on a fast
// machine, and the loading line had already gone by the time the test looked for it.
const held: Array<() => void> = [];
const later = <T,>(v: T, fail = false) => new Promise<T>((res, rej) => { held.push(() => (fail ? rej(v) : res(v))); });
const loading = () => !!document.body.querySelector('[aria-busy="true"]');
async function open(i: number) {
  const b = document.body.querySelector<HTMLButtonElement>(`[data-ev="${i}"]`);
  if (!b) throw new Error(`no row ${i}`);
  await act(async () => { b.click(); await Promise.resolve(); });
}
const settle = () => act(async () => { held.splice(0).forEach((f) => f()); await new Promise((r) => setTimeout(r, 20)); });

beforeEach(() => {
  held.length = 0;
  fullEvents.mockReset();
  el = document.createElement('div');
  document.body.appendChild(el);
  root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); document.body.innerHTML = ''; });

test('a finished task: opening a clipped thought reads it whole once, and the loading line goes', async () => {
  fullEvents.mockImplementation(() => later(fullOf()));
  await act(async () => { root.render(view(rowsOf())); });
  await open(1);
  expect(loading()).toBe(true);
  await settle();
  expect(fullEvents).toHaveBeenCalledTimes(1);
  expect(loading()).toBe(false);
  expect(detail()).toContain(WHOLE);
  expect(detail()).not.toContain('clipped 6000 chars');
  // closed and opened again: already whole, nothing reads or loads
  await open(1); await open(1);
  expect(fullEvents).toHaveBeenCalledTimes(1);
  expect(loading()).toBe(false);
  expect(detail()).toContain(WHOLE);
});

test('a running task: rows read again while the full read is out still end the loading line', async () => {
  let answer: (v: TRow[]) => void = () => undefined;
  fullEvents.mockImplementation(() => new Promise<TRow[]>((res) => { answer = res; }));
  await act(async () => { root.render(view(rowsOf(), true)); });
  await open(1);
  expect(loading()).toBe(true);
  // the 2.5 s re-read: the same events as new row objects, one more row
  await act(async () => { root.render(view([...rowsOf(), { i: 4, kind: 'agent', label: 'Agent', text: 'More', ts: 105 }], true)); });
  await act(async () => { answer(fullOf()); });
  await settle();
  expect(fullEvents).toHaveBeenCalledTimes(1);
  expect(loading()).toBe(false);
  expect(detail()).toContain(WHOLE);
});

test('a full read that fails ends the loading line, keeps the clipped words and says the rest could not be read', async () => {
  fullEvents.mockImplementation(() => later(new Error('traces 502 /all'), true));
  await act(async () => { root.render(view(rowsOf())); });
  await open(1);
  await settle();
  expect(loading()).toBe(false);
  expect(detail()).toContain('I should read the file first');
  expect(detail()).toContain('The rest of this step could not be read.');
  // Try again reads it, and the whole content takes the clipped words' place
  fullEvents.mockImplementation(() => later(fullOf()));
  const again = Array.from(document.body.querySelectorAll<HTMLButtonElement>('.trv-detail button')).find((b) => b.textContent === 'Try again');
  await act(async () => { again?.click(); });
  await settle();
  expect(fullEvents).toHaveBeenCalledTimes(2);
  expect(detail()).toContain(WHOLE);
  expect(detail()).not.toContain('could not be read');
});

test('a finished trace draws nothing live; a running one only its Working line', async () => {
  await act(async () => { root.render(view(rowsOf())); });
  expect(document.body.querySelector('.dot.run')).toBeNull();
  expect(body()).not.toContain('Working');
  await act(async () => { root.render(view(rowsOf(), true)); });
  expect(document.body.querySelectorAll('.dot.run').length).toBe(1);
});

test("a setup page's host takes a narrow trace's step detail, never the whole window", async () => {
  // the setup page's right column (studio/[id] .tk-trv-host); jsdom lays nothing out, so the trace is narrow
  const host = document.createElement('div');
  host.className = 'tk-trv-host';
  document.body.appendChild(host);
  await act(async () => { root.render(<TraceDetailHost.Provider value={host}>{view(rowsOf())}</TraceDetailHost.Provider>); });
  await open(2);
  expect(host.querySelector('.trv-over .trv-detail')).not.toBeNull();
  expect(document.body.querySelector('.trv-over-fixed')).toBeNull();
  // without a host (a kit's panel names its own), it covers the window as before
  await act(async () => { root.render(view(rowsOf())); });
  await open(2);
  expect(host.querySelector('.trv-detail')).toBeNull();
  expect(document.body.querySelector('.trv-over-fixed .trv-detail')).not.toBeNull();
});

describe("a setup's trace, read on push", () => {
  const ROWS = rowsOf();
  function Live({ sid = 'hsess1', live }: { sid?: string; live: boolean }) {
    const t = useTrace(sid, live);
    return <TraceView sid={sid} rows={t.rows} failed={t.failed} running={live} />;
  }
  const flush = async () => { for (let i = 0; i < 6; i++) await act(async () => { await Promise.resolve(); }); };
  const later2 = async (ms: number) => { await act(async () => { jest.advanceTimersByTime(ms); }); await flush(); };
  const msg = (sid: string, type: string, replay = false): BusMsg => ({ session_id: sid, response_id: 'resp_1', event: { type }, replay });
  const tryAgain = () => Array.from(document.body.querySelectorAll<HTMLButtonElement>('button')).find((b) => b.textContent === 'Try again');

  beforeEach(() => {
    jest.useFakeTimers();
    manifest.mockReset(); events.mockReset(); bus.harness = ''; bus.on = null; bus.state = null; bus.unsub.mockReset();
    manifest.mockResolvedValue({ harness_id: 'chrn_1', chunks: [] });
    events.mockResolvedValue(ROWS);
  });
  afterEach(() => { jest.useRealTimers(); });

  test('the correct path: read once, and never again on a timer while it runs', async () => {
    await act(async () => { root.render(<Live live />); });
    await flush();
    expect(events).toHaveBeenCalledTimes(1);
    expect(body()).toContain('4 events');
    await later2(60_000);
    expect(events).toHaveBeenCalledTimes(1);
  });

  test("a trace that could not be read says so, never \"No events recorded.\"; Try again reads it", async () => {
    events.mockRejectedValueOnce(new Error('traces 502 /all'));
    await act(async () => { root.render(<Live live={false} />); });
    await flush();
    expect(body()).toContain('The trace could not be read.');
    expect(body()).not.toContain('No events recorded.');
    await act(async () => { tryAgain()?.click(); });
    await flush();
    expect(events).toHaveBeenCalledTimes(2);
    expect(body()).toContain('4 events');
    expect(body()).not.toContain('could not be read');
  });

  test("while it runs, each of its events on the setup's feed reads it again, at most once a second", async () => {
    await act(async () => { root.render(<Live live />); });
    await flush();
    expect(bus.harness).toBe('chrn_1');
    events.mockResolvedValue([...ROWS, { i: 4, kind: 'agent', label: 'Agent', text: 'More', ts: 105 }]);
    await act(async () => { for (let i = 0; i < 5; i++) bus.on?.(msg('hsess1', 'response.output_text.delta')); });
    // another task's events and a replay of what was read ask for nothing
    await act(async () => { bus.on?.(msg('hsess2', 'response.output_text.delta')); bus.on?.(msg('hsess1', 'response.output_text.delta', true)); });
    await later2(TRACE_READ_GAP_MS);
    expect(events).toHaveBeenCalledTimes(2);
    expect(body()).toContain('5 events');
    await later2(5000);
    expect(events).toHaveBeenCalledTimes(2);
  });

  test("each reconnect of the setup's feed reads it once; its first connect does not", async () => {
    await act(async () => { root.render(<Live live />); });
    await flush();
    await act(async () => { bus.state?.('up'); });
    await later2(TRACE_READ_GAP_MS);
    expect(events).toHaveBeenCalledTimes(1);
    await act(async () => { bus.state?.('down'); bus.state?.('up'); });
    await later2(TRACE_READ_GAP_MS);
    expect(events).toHaveBeenCalledTimes(2);
  });

  test('a finished trace holds no feed of its events', async () => {
    await act(async () => { root.render(<Live live={false} />); });
    await flush();
    expect(bus.on).toBeNull();
  });

  test('its end on the setup’s feed reads it, and the task’s end on its card reads it once more', async () => {
    await act(async () => { root.render(<Live live />); });
    await flush();
    await act(async () => { bus.on?.(msg('hsess2', 'response.completed')); });
    await later2(TRACE_READ_GAP_MS);
    expect(events).toHaveBeenCalledTimes(1);
    await act(async () => { bus.on?.(msg('hsess1', 'response.completed')); });
    await later2(TRACE_READ_GAP_MS);
    expect(events).toHaveBeenCalledTimes(2);
    await act(async () => { root.render(<Live live={false} />); });
    await flush();
    expect(events).toHaveBeenCalledTimes(3);
  });

  test('a read again that fails keeps the rows and says they could not be refreshed, with Try again', async () => {
    await act(async () => { root.render(<Live live />); });
    await flush();
    events.mockRejectedValueOnce(new Error('traces 503 /all'));
    await act(async () => { bus.on?.(msg('hsess1', 'response.output_text.delta')); });
    await later2(TRACE_READ_GAP_MS);
    expect(body()).toContain('4 events');
    expect(body()).toContain('Could not refresh the trace.');
    await act(async () => { tryAgain()?.click(); });
    await flush();
    expect(body()).not.toContain('Could not refresh');
  });
});
