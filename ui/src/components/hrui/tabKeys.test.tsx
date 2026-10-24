/** @jest-environment jsdom */
import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { tabKeys } from './tabKeys';

const KEYS = ['plugins', 'skills', 'tools', 'envs'] as const;
type K = typeof KEYS[number];

function Tabs({ vertical = false }: { vertical?: boolean }) {
  const [tab, setTab] = useState<K>('plugins');
  return (
    <div role="tablist" aria-orientation={vertical ? 'vertical' : undefined}
      onKeyDown={(e) => tabKeys(e, KEYS, tab, setTab, vertical ? { orientation: 'vertical' } : undefined)}>
      {KEYS.map((k) => <button key={k} type="button" role="tab" aria-selected={tab === k} tabIndex={tab === k ? 0 : -1} onClick={() => setTab(k)}>{k}</button>)}
    </div>
  );
}

let host: HTMLDivElement; let root: Root;
beforeEach(() => { host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host); });
afterEach(() => { act(() => root.unmount()); host.remove(); });

const selected = () => host.querySelector('[aria-selected="true"]')?.textContent;
const press = (key: string) => act(() => { (document.activeElement || host).dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true })); });

it('moves and selects with the arrow keys, Home and End, focus following, wrapping at the ends', () => {
  act(() => root.render(<Tabs />));
  (host.querySelector('[role="tab"]') as HTMLElement).focus();
  press('ArrowRight'); expect(selected()).toBe('skills'); expect(document.activeElement?.textContent).toBe('skills');
  press('End'); expect(selected()).toBe('envs');
  press('ArrowRight'); expect(selected()).toBe('plugins');
  press('ArrowLeft'); expect(selected()).toBe('envs');
  press('Home'); expect(selected()).toBe('plugins');
  press('a'); expect(selected()).toBe('plugins');
});

it('keeps only the selected tab in the Tab order', () => {
  act(() => root.render(<Tabs />));
  expect([...host.querySelectorAll('[role="tab"]')].map((t) => (t as HTMLElement).tabIndex)).toEqual([0, -1, -1, -1]);
});

it('a horizontal list leaves Up and Down alone', () => {
  act(() => root.render(<Tabs />));
  (host.querySelector('[role="tab"]') as HTMLElement).focus();
  press('ArrowDown'); expect(selected()).toBe('plugins');
  press('ArrowUp'); expect(selected()).toBe('plugins');
});

it('a vertical list also moves with Up and Down, wrapping at the ends, focus following', () => {
  act(() => root.render(<Tabs vertical />));
  (host.querySelector('[role="tab"]') as HTMLElement).focus();
  press('ArrowDown'); expect(selected()).toBe('skills'); expect(document.activeElement?.textContent).toBe('skills');
  press('ArrowUp'); expect(selected()).toBe('plugins');
  press('ArrowUp'); expect(selected()).toBe('envs');
  press('ArrowDown'); expect(selected()).toBe('plugins');
  press('ArrowRight'); expect(selected()).toBe('skills');
  press('End'); expect(selected()).toBe('envs');
  press('Home'); expect(selected()).toBe('plugins');
});
