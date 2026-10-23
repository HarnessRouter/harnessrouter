/** @jest-environment jsdom */
// A setup saved from a demo's recorded run has that run as its first task (start/replay.ts): the
// list's oldest row, always there, "Recorded" with when the setup was made, blue while it plays, and
// no Delete (it is no task of the server's). It is shown once the list reaches its end, under the same
// filters as any row; a recording that could not be read is said at the list's end with Try again,
// never left out without a word, and the list never says "No tasks yet" over it.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { TraceCard } from '@/lib/revamp-data';

jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
jest.mock('@/lib/auth', () => ({ getSession: () => ({ orgId: 'org.a', member: { email: 'ana@example.com' } }) }));
jest.mock('@/lib/conversation', () => ({ feedTurnOf: () => undefined, livePending: () => [], useFeedTurns: () => 0, useHarnessBus: () => undefined }));
jest.mock('@/lib/use-workspace-feed', () => ({ useWorkspaceFeed: () => ({ paused: false, reconnect: jest.fn() }) }));
jest.mock('../toast', () => ({ toast: jest.fn() }));
jest.mock('../setups', () => ({ ago: () => '3 min ago' }));
jest.mock('../Skel', () => ({ Skel: ({ label }: { label: string }) => <div aria-busy="true">{label}</div>, SkRows: () => null }));
jest.mock('./TaskDetail', () => ({ DeleteTask: () => null, titleOf: (c: TraceCard) => c.title || c.session_id }));

import { NO_FILTER, TaskList, type RecordedRow, type TaskFilter, type TaskList as TL } from './TaskRail';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const now = Math.floor(Date.now() / 1000);
const card = (sid: string, status = 'completed'): TraceCard => ({ session_id: sid, title: `Task ${sid}`, status, harness_id: 'chrn_1', finished_at: now - 60, created_at: now - 60 } as TraceCard);
const listOf = (cards: TraceCard[], o: Partial<TL> = {}): TL => ({
  all: cards, byId: new Map(cards.map((c) => [c.session_id, c])), ready: true, failed: false, stale: false, more: false, reading: false,
  older: jest.fn(), refresh: jest.fn(), paused: false, reconnect: jest.fn(), drop: jest.fn(), add: jest.fn(), pending: [], ...o,
});
const REQ = 'Generate a product image for our store from a short brief.\n\nA matte black ceramic mug with a bamboo lid.';

let root: Root;
let el: HTMLElement;
const text = () => (el.textContent || '').replace(/\s+/g, ' ');
const rows = () => Array.from(el.querySelectorAll<HTMLButtonElement>('button.tk-r'));
async function show(list: TL, recorded: RecordedRow | null, o: { f?: TaskFilter; retry?: () => void } = {}) {
  await act(async () => {
    root.render(<TaskList setupName="Product images" list={list} f={o.f || NO_FILTER} setF={() => undefined} current={null} isNew={false}
      recorded={recorded} recordedRetry={o.retry} onOpen={() => undefined} onNew={() => undefined} onGone={() => undefined} />);
  });
}
beforeEach(() => { el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el); });
afterEach(() => { act(() => root.unmount()); el.remove(); });

test('the recorded first task is the oldest row: its request, Recorded, when the setup was made; opening it opens it', async () => {
  const onOpen = jest.fn();
  await show(listOf([card('s2'), card('s1')]), { title: REQ, at: Date.now() - 180_000, on: false, onOpen });
  const rs = rows();
  expect(rs).toHaveLength(3);
  expect(rs[2].textContent).toContain('A matte black ceramic mug');
  expect(rs[2].querySelector('small')?.textContent).toBe('Recorded · 3 min ago');
  expect(rs[2].querySelector('.dot')?.className).toBe('dot ok');
  // it is no task of the server's: it has no Delete
  expect(el.querySelectorAll('.tk-rdel')).toHaveLength(2);
  act(() => { rs[2].click(); });
  expect(onOpen).toHaveBeenCalledTimes(1);
});

test('blue while it plays, and marked open while it is the one open', async () => {
  await show(listOf([]), { title: REQ, at: Date.now(), on: true, running: true });
  const r = rows()[0];
  expect(r.querySelector('.dot')?.className).toBe('dot run');
  expect(r.getAttribute('aria-current')).toBe('true');
  expect(r.textContent).toContain('Running');
  // a setup whose one task is its recording is not one with none
  expect(text()).not.toContain('No tasks yet');
});

test('shown only once the list reaches its end, and only where the filter would show it', async () => {
  await show(listOf([card('s1')], { more: true }), { title: REQ, at: Date.now(), on: false });
  expect(rows()).toHaveLength(1);                                  // older tasks still to read: not yet
  await show(listOf([card('s1', 'failed')]), { title: REQ, at: Date.now(), on: false }, { f: { ...NO_FILTER, view: 'failed' } });
  expect(text()).not.toContain('Recorded');                        // it did not fail
  await show(listOf([card('s1')]), { title: REQ, at: Date.now(), on: false }, { f: { ...NO_FILTER, q: 'mug' } });
  expect(text()).toContain('Recorded');                            // searched by its request
  await show(listOf([card('s1')]), { title: REQ, at: Date.now(), on: false }, { f: { ...NO_FILTER, q: 'contract' } });
  expect(text()).not.toContain('Recorded');
  await show(listOf([]), { title: REQ, at: Date.now() - 2 * 86400e3, on: false }, { f: { ...NO_FILTER, range: '24h' } });
  expect(text()).not.toContain('Recorded');
});

test('a recording that could not be read is said at the list’s end, with Try again; never "No tasks yet"', async () => {
  const retry = jest.fn();
  await show(listOf([]), null, { retry });
  expect(text()).toContain('The recorded first task could not be read.');
  expect(text()).not.toContain('No tasks yet');
  expect(text()).not.toContain('No tasks match');
  const again = Array.from(el.querySelectorAll('button')).find((b) => b.textContent === 'Try again');
  act(() => { again?.click(); });
  expect(retry).toHaveBeenCalledTimes(1);
});

test('a setup with no recording reads as before', async () => {
  await show(listOf([]), null);
  expect(text()).toContain('No tasks yet');
  expect(text()).not.toContain('Recorded');
});
