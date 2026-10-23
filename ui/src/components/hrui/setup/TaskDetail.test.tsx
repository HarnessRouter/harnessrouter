/** @jest-environment jsdom */
// The open task draws what was read and nothing in place of a read that failed (Richard 10-19: no
// fallback): the delete confirmation says when whether the task has a public link could not be checked
// (never reads as "not shared"). A self-hosted console shows a task as its conversation: the trace view
// is the hosted product's (Richard 10-22), so the bar offers no Trace and nothing here names one.
import { act } from 'react';
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

import { harnessFetch } from '@/lib/hfetch';
import { DeleteTask, TaskHead } from './TaskDetail';

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

test('the task bar offers no trace: its title and its actions, no tabs', async () => {
  (harnessFetch as jest.Mock).mockResolvedValue({ ok: false });
  await show(<TaskHead card={CARD} onStopped={() => {}} onBack={() => {}} />);
  expect(el.textContent).toContain('Draft a reply');
  expect(el.querySelector('[role="tablist"], [role="tab"]')).toBeNull();
  expect(el.textContent).not.toMatch(/trace/i);
});

test('deleting a task names what goes with it, and no trace', async () => {
  (harnessFetch as jest.Mock).mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ enabled: false, token: '' }) });
  await show(<DeleteTask card={CARD} onClose={() => {}} onGone={() => {}} />);
  expect(el.textContent).toContain('is removed with its conversation and files.');
  expect(el.textContent).not.toMatch(/trace/i);
});
