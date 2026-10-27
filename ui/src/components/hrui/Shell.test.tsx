/** @jest-environment jsdom */
// The console's frame on a self-hosted instance: the rail's five places and the team's letter, the account menu
// (How it works, Profile, Bring your own key, Docs, help, Log out through the instance's own sign-in), the workspace menu (the workspaces,
// Workspace settings, New workspace), and the switcher on the strict list: until the list answers no page is
// drawn and no placeholder workspace is named; a list that could not be read is an error in the menu and in
// place of the page; a chosen workspace gone from the list is said once, by name.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const mockNav = { path: '/studio', push: jest.fn(), replace: jest.fn() };
jest.mock('next/link', () => ({ __esModule: true, default: ({ href, children, ...p }: { href: string; children: React.ReactNode }) => <a href={href} {...p}>{children}</a> }));
jest.mock('next/navigation', () => ({ usePathname: () => mockNav.path, useRouter: () => ({ push: mockNav.push, replace: mockNav.replace }) }));
jest.mock('@/lib/workspace', () => ({ useWorkspace: jest.fn() }));
jest.mock('./icons', () => ({ Ic: new Proxy({}, { get: () => null }) }));
jest.mock('./ws', () => ({ wsColor: () => '#285aff', WsBadge: () => null, initials: (n: string) => n.slice(0, 2).toUpperCase() }));
jest.mock('./toast', () => ({ toast: jest.fn(), ToastHost: () => null }));
jest.mock('./WorkspaceSheets', () => ({ NewWorkspaceSheet: () => null, PeopleSheet: () => null, useWorkspaceSheets: () => [null, jest.fn()], WS_MENU_EVENT: 'hrui:wsmenu' }));
jest.mock('./moved', () => ({ movedTo: () => null }));
jest.mock('./Skel', () => ({ Skel: ({ label }: { label: string }) => <div className="skel">{label}</div>, SkHead: () => null, SkRows: () => null }));

import { useWorkspace } from '@/lib/workspace';
import { toast } from './toast';
import { HruiShell } from './Shell';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const DEF = { id: 'ws.def', name: 'Default Workspace', description: '', site: '' };
const UNKNOWN = { id: '', name: '', description: '', site: '' };
let ctx: Record<string, unknown>;
let root: Root;
let el: HTMLElement;
let session: { user: string; gated: boolean } | null;
let stars: number | null;
let fetched: string[];

async function mount() {
  el = document.createElement('div');
  document.body.appendChild(el);
  root = createRoot(el);
  await act(async () => { root.render(<HruiShell><p id="the-page">the page</p></HruiShell>); });
  for (let i = 0; i < 6; i++) await act(async () => { await Promise.resolve(); });
}
const openMe = async () => { await act(async () => { (el.querySelector('.rail-me') as HTMLButtonElement).click(); }); };
const meRows = () => Array.from(el.querySelectorAll('.me-pop [role="menuitem"]')).map((r) => (r.textContent || '').replace('↗', '').trim());

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
  mockNav.path = '/studio';
  session = { user: 'harnessrouter', gated: true };
  stars = null;
  fetched = [];
  global.fetch = jest.fn((url: string) => {
    fetched.push(String(url));
    if (String(url).startsWith('/api/selfhost/session')) return Promise.resolve({ ok: !!session, json: async () => session });
    if (String(url).startsWith('/api/github-stars')) return Promise.resolve({ ok: stars !== null, json: async () => ({ stars }) });
    return Promise.resolve({ ok: true, json: async () => ({}) });
  }) as unknown as typeof fetch;
  ctx = { workspaces: [DEF], current: DEF, known: true, defaultId: 'ws.def', loading: false, failed: false, lost: null,
          clearLost: jest.fn(), setCurrent: jest.fn(), refresh: jest.fn(() => Promise.resolve()) };
  (useWorkspace as jest.Mock).mockImplementation(() => ctx);
});
afterEach(() => { act(() => root.unmount()); el.remove(); });

test('the rail has the five places of this console and the letter, and nothing a self-hosted instance does not have', async () => {
  await mount();
  const places = Array.from(el.querySelectorAll('.rail a.rail-btn')).map((a) => a.getAttribute('href'));
  expect(places).toEqual(['/start', '/studio', '/shop', '/extensions', '/keys', '/letter']);
  expect(el.querySelector('.rail a.rail-btn[aria-current="page"]')?.getAttribute('href')).toBe('/studio');
  // the letter sits last, right above the account button
  expect(el.querySelector('.rail .rail-letter')?.nextElementSibling?.classList.contains('rail-me')).toBe(true);
  for (const gone of ['/arena', '/usage', '/billing', '/organization', '/account']) {
    expect(el.querySelector(`a[href="${gone}"]`)).toBeNull();
  }
});

test('the account menu: the signed-in user, Profile, Bring your own key, Docs, help, Log out', async () => {
  await mount();
  await openMe();
  expect(el.querySelector('.me-pop .me-h')?.textContent).toBe('harnessrouter');
  const rows = meRows();
  for (const want of ['How it works', 'Profile', 'Bring your own key', 'Docs', 'Join our Discord', 'Book a demo', 'Star us on GitHub', 'Log out']) {
    expect(rows).toContain(want);
  }
  expect(rows[0]).toBe('How it works');
  for (const gone of ['Account', 'Organization', 'Billing', 'View all plans', 'Insights']) {
    expect(rows).not.toContain(gone);
  }
  await act(async () => { (Array.from(el.querySelectorAll('.me-pop [role="menuitem"]')).find((r) => r.textContent === 'Profile') as HTMLButtonElement).click(); });
  expect(mockNav.push).toHaveBeenCalledWith('/profile');
});

test('the letter carries a dot until it is opened, and How it works opens it', async () => {
  await mount();
  const dot = el.querySelector('.rail-letter .letter-dot') as HTMLElement;
  expect(dot.hidden).toBe(false);
  expect(el.querySelector('.rail-me')?.classList.contains('dot')).toBe(true);
  await openMe();
  expect(el.querySelector('.me-pop .me-dot')).toBeTruthy();
  await act(async () => { (Array.from(el.querySelectorAll('.me-pop [role="menuitem"]')).find((r) => r.textContent === 'How it works') as HTMLButtonElement).click(); });
  expect(mockNav.push).toHaveBeenCalledWith('/letter');
  act(() => root.unmount()); el.remove();
  // opened: the rail marks the letter as here, and no dot is left anywhere
  mockNav.path = '/letter';
  await mount();
  expect(el.querySelector('.rail a.rail-btn[aria-current="page"]')?.getAttribute('href')).toBe('/letter');
  expect((el.querySelector('.rail-letter .letter-dot') as HTMLElement).hidden).toBe(true);
  expect(el.querySelector('.rail-me')?.classList.contains('dot')).toBe(false);
  act(() => root.unmount()); el.remove();
  mockNav.path = '/studio';
  await mount();
  expect((el.querySelector('.rail-letter .letter-dot') as HTMLElement).hidden).toBe(true);
  await openMe();
  expect(el.querySelector('.me-pop .me-dot')).toBeNull();
});

test('Log out ends the instance\'s own session', async () => {
  const assign = jest.fn();
  Object.defineProperty(window, 'location', { configurable: true, value: { ...window.location, assign } });
  await mount();
  await openMe();
  await act(async () => { (Array.from(el.querySelectorAll('.me-pop [role="menuitem"]')).find((r) => r.textContent === 'Log out') as HTMLButtonElement).click(); });
  for (let i = 0; i < 4; i++) await act(async () => { await Promise.resolve(); });
  expect(fetched).toContain('/api/selfhost/logout');
  expect(assign).toHaveBeenCalledWith('/login');
});

test('the workspace menu: the workspaces, Workspace settings and New workspace, no organization or invitations', async () => {
  await mount();
  expect(el.querySelector('#the-page')).toBeTruthy();
  await act(async () => { (el.querySelector('.ws-rail') as HTMLButtonElement).click(); });
  const menu = el.querySelector('.ws-pop') as HTMLElement;
  expect(menu.textContent).toContain('Default Workspace');
  expect(menu.textContent).toContain('Workspace settings');
  expect(menu.textContent).toContain('New workspace');
  expect(menu.textContent).not.toContain('Invite people');
  expect(toast).not.toHaveBeenCalled();
});

test('the workspace menu fits the window: its workspaces scroll, its two actions stay outside the list', async () => {
  await mount();
  await act(async () => { (el.querySelector('.ws-rail') as HTMLButtonElement).click(); });
  const menu = el.querySelector('.ws-pop') as HTMLElement;
  const list = menu.querySelector('.ws-list') as HTMLElement;
  expect(list).toBeTruthy();
  expect(list.textContent).toContain('Default Workspace');
  // the actions are the menu's own, never inside the list that scrolls
  const actions = Array.from(menu.querySelectorAll<HTMLButtonElement>(':scope > .ws-row.plain')).map((b) => b.textContent);
  expect(actions).toEqual(['Workspace settings', 'New workspace']);
  expect(list.textContent).not.toContain('New workspace');
  // held to the room under its top (jsdom's window is 768 tall, the menu at its top: 768 - 0 - 8)
  expect(menu.style.maxHeight).toBe(`${window.innerHeight - 8}px`);
});

test('before the list answers: no page, no workspace named, a loading state in the menu', async () => {
  ctx = { ...ctx, workspaces: [], current: UNKNOWN, known: false, loading: true };
  await mount();
  expect(el.querySelector('#the-page')).toBeNull();
  expect(el.querySelector('.page')?.textContent).toContain('Loading');
  const rail = el.querySelector('.ws-rail') as HTMLButtonElement;
  expect(rail.textContent).toBe('');
  expect(rail.title).toBe('Switch workspace');
  await act(async () => { rail.click(); });
  const menu = el.querySelector('.ws-pop') as HTMLElement;
  expect(menu.textContent).toContain('Loading workspaces');
  expect(menu.textContent).not.toContain('New workspace');
});

test('a list that could not be read: an error in place of the page and in the menu, and Try again reads it again', async () => {
  ctx = { ...ctx, workspaces: [], current: UNKNOWN, known: false, failed: true };
  await mount();
  expect(el.querySelector('#the-page')).toBeNull();
  expect(el.querySelector('[role="alert"]')?.textContent).toContain('Your workspaces could not be read just now.');
  await act(async () => { (el.querySelector('.ws-rail') as HTMLButtonElement).click(); });
  const menu = el.querySelector('.ws-pop') as HTMLElement;
  expect(menu.textContent).toContain('Your workspaces could not be read just now.');
  expect(menu.textContent).not.toContain('New workspace');
  await act(async () => { (menu.querySelector('.ws-fail') as HTMLButtonElement).click(); });
  expect(ctx.refresh).toHaveBeenCalled();
});

test('a chosen workspace gone from the list is said once, by its name', async () => {
  ctx = { ...ctx, lost: { name: 'PhotoMagic' } };
  await mount();
  expect(toast).toHaveBeenCalledWith('You no longer have access to PhotoMagic.');
  expect(ctx.clearLost).toHaveBeenCalled();
});

test('the star count is GitHub\'s when it answers, and no number when the count could not be read', async () => {
  await mount();
  await openMe();
  expect(el.querySelector('.me-gh')?.textContent).toBe('Star us on GitHub');
  expect(el.querySelector('.me-star')).toBeNull();
  act(() => root.unmount()); el.remove();
  stars = 1234;
  await mount();
  await openMe();
  expect(el.querySelector('.me-star')?.textContent).toBe('1.2k');
});
