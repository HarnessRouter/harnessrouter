/** @jest-environment jsdom */
// A task's Trace tab: its events in the shared trace view, with how long it ran in the head line and
// nothing else (no cost, no lock: every task keeps its trace), and its state in the design's words.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { TraceCard } from '@/lib/revamp-data';

const mockView = { props: null as null | Record<string, unknown> };
jest.mock('../trace/TraceView', () => ({
  TraceView: (p: Record<string, unknown>) => { mockView.props = p; return <div className="trv">{p.head as React.ReactNode}</div>; },
  useTrace: () => ({ rows: [], failed: false }),
}));

import { StatusPill, TraceBody } from './TaskTrace';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let root: Root;
let el: HTMLElement;
beforeEach(() => { el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el); mockView.props = null; });
afterEach(() => { act(() => root.unmount()); el.remove(); });

test('the trace of a finished task: its events, how long it ran, and no cost', async () => {
  const card = { session_id: 'hsess_1', status: 'completed', elapsed: 12.5 } as TraceCard;
  await act(async () => { root.render(<TraceBody card={card} st="done" openError={false} />); });
  expect(mockView.props).toMatchObject({ sid: 'hsess_1', running: false, openError: false });
  expect(el.querySelector('.trv .chip')?.textContent).toBe('12.5 s');
  expect(el.textContent).not.toMatch(/\$|Cost/);
});

test('a running task is read as running; one with no duration says none', async () => {
  const card = { session_id: 'hsess_2', status: 'running' } as TraceCard;
  await act(async () => { root.render(<TraceBody card={card} st="running" openError={false} />); });
  expect(mockView.props).toMatchObject({ running: true });
  expect(el.querySelector('.trv .chip')).toBeNull();
});

test('each state in the design’s words', async () => {
  await act(async () => {
    root.render(<>{(['running', 'done', 'failed', 'incomplete', 'cancelled', 'unknown'] as const).map((s) => <StatusPill key={s} st={s} />)}</>);
  });
  expect(Array.from(el.querySelectorAll('.pill')).map((p) => p.textContent)).toEqual(['Running', 'Completed', 'Failed', 'Incomplete', 'Cancelled']);
});
