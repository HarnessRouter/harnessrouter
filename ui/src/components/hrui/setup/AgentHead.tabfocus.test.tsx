/** @jest-environment jsdom */
// The setup's Tasks/Settings tabs keep the keyboard on the tab chosen with the arrows (audit, 2026-10-21): the page
// changes its address and draws the bar again, and the focus tabKeys gave the new tab fell to the page body.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

jest.mock('next/link', () => ({ __esModule: true, default: ({ children, ...p }: { children: React.ReactNode }) => <a {...p}>{children}</a> }));
jest.mock('../toast', () => ({ toast: jest.fn() }));

import { AgentHead, type SetupTab } from './parts';
import type { SetupRow } from '../setups';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const ROW = { h: { id: 'chrn_0123456789abcdef', name: 'Morning email brief', base: 'hermes', defaultModel: 'gpt-5.4' }, baseName: 'Hermes', conn: 'none' } as unknown as SetupRow;
let root: Root; let el: HTMLElement;
const tabOf = (tab: SetupTab) => document.querySelectorAll<HTMLElement>('[role="tab"]')[tab === 'tasks' ? 0 : 1];
afterEach(() => { act(() => root.unmount()); el.remove(); document.body.innerHTML = ''; });

function draw(tab: SetupTab, onTab: (t: SetupTab) => void) {
  act(() => { root.render(<AgentHead r={ROW} tab={tab} onTab={onTab} onSetUpApp={() => {}} />); });
}

test('an arrow picks the next tab, and the bar drawn for it puts the keyboard on that tab', () => {
  el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el);
  const onTab = jest.fn();
  draw('tasks', onTab);
  tabOf('tasks')!.focus();
  act(() => { tabOf('tasks')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })); });
  expect(onTab).toHaveBeenCalledWith('settings');
  // the page draws the bar again for the new address, as a new tree
  act(() => root.unmount()); el.remove(); document.body.innerHTML = '';
  el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el);
  draw('settings', onTab);
  expect(document.activeElement).toBe(tabOf('settings'));
});

test('a click on a tab changes nothing about where focus goes', () => {
  el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el);
  const onTab = jest.fn();
  draw('tasks', onTab);
  act(() => { tabOf('settings')!.click(); });
  draw('settings', onTab);
  expect(document.activeElement).not.toBe(tabOf('settings'));
});

test('the bar no longer carries the Harness ID: it lives in Settings', () => {
  el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el);
  draw('tasks', () => {});
  expect(el.textContent).not.toContain('chrn_0123456789abcdef');
  expect(el.querySelector('[aria-label="Copy Harness ID"]')).toBeNull();
  expect(el.querySelector('[aria-label="Connect your app"]')).not.toBeNull();
});

// Hexa's setup page: Tasks · Settings at the bar's right end, each with its icon; Connect your app sits just before them.
test('Tasks · Settings carry their icons and end the bar, after its actions', () => {
  el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el);
  draw('tasks', () => {});
  const bar = el.querySelector('header.ag-bar')!;
  expect(bar.classList.contains('ag-rt')).toBe(true);
  expect(Array.from(el.querySelectorAll('[role="tab"]')).map((t) => [t.getAttribute('aria-selected'), !!t.querySelector('svg')])).toEqual([['true', true], ['false', true]]);
  expect(Array.from(bar.children).map((c) => c.className)).toEqual(['ag-lft', 'ag-right', 'tabs inline ag-tabs']);
});
