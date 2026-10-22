// A tablist's keys (WAI-ARIA tabs, automatic activation): Left and Right move to the previous and next tab and
// select it, Home and End the first and last, focus following. Only the selected tab is in the Tab order, so Tab
// enters the list once and leaves it (a staging report, 2026-10-21: the Add-ons tabs ignored the
// arrow keys). A vertical list (aria-orientation="vertical", `{ orientation: 'vertical' }`) also moves with Up and
// Down. Every role="tablist" in the console uses this, each tab with tabIndex={selected ? 0 : -1}.
import type React from 'react';

export interface TabKeysOptions { orientation?: 'horizontal' | 'vertical' }

export function tabKeys<K extends string>(e: React.KeyboardEvent<HTMLElement>, keys: readonly K[], current: K, pick: (k: K) => void,
  { orientation = 'horizontal' }: TabKeysOptions = {}): void {
  const i = keys.indexOf(current);
  if (i < 0 || e.altKey || e.ctrlKey || e.metaKey) return;
  const n = keys.length;
  const v = orientation === 'vertical';
  const next = e.key === 'ArrowRight' || (v && e.key === 'ArrowDown');
  const prev = e.key === 'ArrowLeft' || (v && e.key === 'ArrowUp');
  const to = next ? (i + 1) % n : prev ? (i - 1 + n) % n
    : e.key === 'Home' ? 0 : e.key === 'End' ? n - 1 : -1;
  if (to < 0 || to === i) return;
  e.preventDefault();
  pick(keys[to]);
  const tabs = e.currentTarget.querySelectorAll<HTMLElement>('[role="tab"]');
  tabs[to]?.focus();
}
