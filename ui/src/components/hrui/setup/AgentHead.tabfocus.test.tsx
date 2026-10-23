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
const tabNamed = (t: string) => Array.from(document.querySelectorAll<HTMLElement>('[role="tab"]')).find((b) => b.textContent?.startsWith(t));
afterEach(() => { act(() => root.unmount()); el.remove(); document.body.innerHTML = ''; });

function draw(tab: SetupTab, onTab: (t: SetupTab) => void) {
  act(() => { root.render(<AgentHead r={ROW} tab={tab} onTab={onTab} onSetUpApp={() => {}} />); });
}

test('an arrow picks the next tab, and the bar drawn for it puts the keyboard on that tab', () => {
  el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el);
  const onTab = jest.fn();
  draw('tasks', onTab);
  tabNamed('Tasks')!.focus();
  act(() => { tabNamed('Tasks')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })); });
  expect(onTab).toHaveBeenCalledWith('settings');
  // the page draws the bar again for the new address, as a new tree
  act(() => root.unmount()); el.remove(); document.body.innerHTML = '';
  el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el);
  draw('settings', onTab);
  expect(document.activeElement).toBe(tabNamed('Settings'));
});

test('a click on a tab changes nothing about where focus goes', () => {
  el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el);
  const onTab = jest.fn();
  draw('tasks', onTab);
  act(() => { tabNamed('Settings')!.click(); });
  draw('settings', onTab);
  expect(document.activeElement).not.toBe(tabNamed('Settings'));
});
