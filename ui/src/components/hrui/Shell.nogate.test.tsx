/** @jest-environment jsdom */
// The console's frame on an instance with no sign-in (HR_AUTH_DISABLED=1): nothing to sign out of, so the
// account menu has no Log out. (Its own file: the operator is read once per page load, Avatar.tsx.)
// Otherwise as Shell.test.tsx: the rail's five places, the account menu (Profile, Bring your
// own key, Docs, help, Log out through the instance's own sign-in), the workspace menu (the workspaces,
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
  session = { user: 'harnessrouter', gated: false };
  stars = null;
  fetched = [];
  global.fetch = jest.fn((url: string) => {
    fetched.push(String(url));
    if (String(url).startsWith('/api/selfhost/session')) return Promise.resolve({ ok: true, json: async () => session });
    return Promise.resolve({ ok: false, json: async () => null });
  }) as unknown as typeof fetch;
  ctx = { workspaces: [DEF], current: DEF, known: true, defaultId: 'ws.def', loading: false, failed: false, lost: null,
          clearLost: jest.fn(), setCurrent: jest.fn(), refresh: jest.fn(() => Promise.resolve()) };
  (useWorkspace as jest.Mock).mockImplementation(() => ctx);
});
afterEach(() => { act(() => root.unmount()); el.remove(); });

test('an instance with no sign-in has no Log out', async () => {
  await mount();
  await openMe();
  expect(meRows()).not.toContain('Log out');
  expect(meRows()).toContain('Profile');
});
