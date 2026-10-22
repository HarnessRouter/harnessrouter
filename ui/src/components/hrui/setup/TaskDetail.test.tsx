/** @jest-environment jsdom */
// The open task draws what was read and nothing in place of a read that failed (Richard 10-19: no
// fallback): its trace is always the trace (no lock, no receipt), its last error picked when it failed,
// and the delete confirmation says when whether the task has a public link could not be checked (never
// reads as "not shared").
import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { TraceCard } from '@/lib/revamp-data';

jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
jest.mock('@/lib/chat', () => ({ authHeaders: () => ({}), cancelSession: jest.fn() }));
jest.mock('@/lib/harness', () => ({ deleteSession: jest.fn() }));
jest.mock('@/lib/conversation', () => ({ feedTurnOf: () => null, useFeedTurns: () => undefined }));
jest.mock('../Sheet', () => ({
  Sheet: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SheetTop: () => null,
  ConfirmSheet: ({ body }: { body: React.ReactNode }) => <p className="del-p">{body}</p>,
}));
jest.mock('../toast', () => ({ toast: jest.fn() }));
jest.mock('./parts', () => ({ BACK_IC: null }));
jest.mock('./TaskTrace', () => ({
  TraceBody: ({ st, openError }: { st: string; openError: boolean }) => <div data-trace-body="1">{st}:{openError ? 'error' : 'none'}</div>,
}));

import { harnessFetch } from '@/lib/hfetch';
import { DeleteTask, TaskHead, TaskTraceView, type DetailTab } from './TaskDetail';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const CARD = { session_id: 'hsess_1', title: 'Draft a reply', status: 'completed', model: '' } as unknown as TraceCard;
let root: Root;
let el: HTMLElement;
async function flush() { for (let i = 0; i < 4; i++) await act(async () => { await new Promise((r) => setTimeout(r, 0)); }); }
async function show(node: React.ReactNode) {
  el = document.createElement('div'); document.body.appendChild(el);
  root = createRoot(el);
  await act(async () => { root.render(node); });
  await flush();
}
afterEach(() => { act(() => root.unmount()); el.remove(); jest.clearAllMocks(); });

test('a task’s trace is its trace: no lock and nothing read before it; a failed task opens on its error', async () => {
  await show(<TaskTraceView card={CARD} />);
  expect(el.textContent).toBe('done:none');
  act(() => root.unmount()); el.remove();
  await show(<TaskTraceView card={{ ...CARD, status: 'failed' } as TraceCard} />);
  expect(el.textContent).toBe('failed:error');
});

test('delete: a share read that failed is said; a shared task says its link stops working', async () => {
  (harnessFetch as jest.Mock).mockResolvedValueOnce({ ok: false, status: 502, json: async () => ({}) });
  await show(<DeleteTask card={CARD} onClose={() => {}} onGone={() => {}} />);
  expect(el.textContent).toContain('Whether it has a public link could not be checked.');
  act(() => root.unmount()); el.remove();
  (harnessFetch as jest.Mock).mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ enabled: true, token: 'tk' }) });
  await show(<DeleteTask card={CARD} onClose={() => {}} onGone={() => {}} />);
  expect(el.textContent).toContain('Its public link stops working.');
  expect(el.textContent).not.toContain('could not be checked');
});

test('a task’s Conversation and Trace tabs move with the arrow keys, only the open one in the Tab order', async () => {
  (harnessFetch as jest.Mock).mockResolvedValue({ ok: false });
  function Head() {
    const [tab, setTab] = useState<DetailTab>('conversation');
    return <TaskHead card={CARD} tab={tab} onTab={setTab} onStopped={() => {}} onBack={() => {}} />;
  }
  await show(<Head />);
  const tabs = () => Array.from(el.querySelectorAll('.tp-tabs [role="tab"]')) as HTMLElement[];
  expect(tabs().map((t) => t.tabIndex)).toEqual([0, -1]);
  tabs()[0].focus();
  await act(async () => { tabs()[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })); });
  expect(el.querySelector('.tp-tabs [aria-selected="true"]')?.textContent).toBe('Trace');
  expect(document.activeElement?.textContent).toBe('Trace');
  expect(tabs().map((t) => t.tabIndex)).toEqual([-1, 0]);
});
