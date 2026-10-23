/** @jest-environment jsdom */
// The Shop page: the starter kits this instance serves, and nothing else (no listings, no publishing).
// A catalog that could not be read says so with Try again, and keeps saying so whatever is typed in the
// search: what it holds is not known, so it never reads as matching nothing, and "Nothing in the Shop
// matches that" is said only once the kits were read.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { Kit } from './shop/kits';

jest.mock('next/link', () => ({ __esModule: true, default: ({ children, href, className }: { children: React.ReactNode; href: string; className?: string }) => <a className={className} href={href}>{children}</a> }));
jest.mock('@/lib/workspace', () => ({ useWorkspace: () => ({ current: { id: 'ws1', name: 'Default' }, loading: false }) }));
jest.mock('./shop/parts', () => ({ HLogo: () => null, KitIc: () => null, Pieces: () => null }));
jest.mock('./shop/kits', () => ({ ...jest.requireActual('./shop/kits'), fetchKits: jest.fn() }));

import { fetchKits } from './shop/kits';
import { ShopPage } from './ShopPage';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const KIT = { id: 'dashboard', title: 'Dashboard', tagline: 'Charts from your data', description: '', icon: '', accent: '', route: '', iconUrl: '',
  launched: false, harnessId: null, skills: [], runningOn: null, choices: [] } as Kit;
let root: Root;
let el: HTMLElement;

const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });
const alerts = () => Array.from(el.querySelectorAll('[role="alert"]')).map((x) => (x.textContent || '').trim());
const noMatch = () => Array.from(el.querySelectorAll('p.kc-nomatch')).some((p) => p.textContent === 'Nothing in the Shop matches that.' && !(p as HTMLElement).hidden);
async function search(q: string) {
  const i = el.querySelector('#shopQ') as HTMLInputElement;
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  await act(async () => { set.call(i, q); i.dispatchEvent(new Event('input', { bubbles: true })); });
}
async function click(label: string) {
  const b = Array.from(el.querySelectorAll('button')).find((x) => (x.textContent || '').trim() === label) as HTMLButtonElement | undefined;
  if (!b) throw new Error(`no button ${label}: ${el.textContent}`);
  await act(async () => { b.click(); await new Promise((r) => setTimeout(r, 0)); });
}
async function open() { await act(async () => { root.render(<ShopPage />); }); await flush(); }

beforeEach(() => {
  (fetchKits as jest.Mock).mockReset().mockResolvedValue([KIT]);
  window.history.replaceState(null, '', '/shop');
  el = document.createElement('div'); document.body.appendChild(el);
  root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); el.remove(); });

it('the kits, each with Try it to its own page; a search that matches nothing says so', async () => {
  await open();
  expect(el.textContent).toContain('Dashboard');
  expect(el.querySelector('a.kc-launch')?.getAttribute('href')).toBe('/shop/dashboard');
  // kits only: no switch between sections, no listings from teams, no publishing
  expect(el.querySelector('.seg')).toBeNull();
  expect(el.textContent).not.toMatch(/From teams|Publish to Shop/);
  await search('zebra');
  expect(noMatch()).toBe(true);
  expect(alerts()).toEqual([]);
});

it('starter kits that could not be read: the error stays through a search, and never reads as no match; Try again reads them', async () => {
  (fetchKits as jest.Mock).mockRejectedValueOnce(new Error('503'));
  await open();
  expect(alerts()).toEqual(['The starter kits could not be read just now. Try again']);
  expect(el.textContent).not.toContain('No starter kits are available right now.');
  await search('zebra');
  expect(alerts()).toEqual(['The starter kits could not be read just now. Try again']);
  expect(noMatch()).toBe(false);
  await search('');
  await click('Try again');
  await flush();
  expect(fetchKits).toHaveBeenCalledTimes(2);
  expect(alerts()).toEqual([]);
  expect(el.textContent).toContain('Dashboard');
});

it('a search that matches a kit shows only it', async () => {
  (fetchKits as jest.Mock).mockResolvedValue([KIT, { ...KIT, id: 'video', title: 'Video', tagline: 'Clips from a brief' }]);
  await open();
  await search('clips');
  expect(el.textContent).toContain('Video');
  expect(el.textContent).not.toContain('Dashboard');
  expect(noMatch()).toBe(false);
});
