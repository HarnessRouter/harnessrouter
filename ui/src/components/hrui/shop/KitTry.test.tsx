/** @jest-environment jsdom */
// One kit's page. After a launch its header names what the launch says the setup runs on, the pairing
// the person chose, never the suggestion in its place; with no such answer it names nothing. What this
// organization can run, unread, is said in the launch sheet with Try again. The page is the kit's app
// alone: a self-hosted console shows no trace beside it (the trace view is the hosted product's).
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { Kit } from './kits';

jest.mock('next/link', () => ({ __esModule: true, default: ({ children, href, className }: { children: React.ReactNode; href: string; className?: string }) => <a className={className} href={href}>{children}</a> }));
jest.mock('next/navigation', () => ({ useRouter: () => ({ push: jest.fn() }) }));
jest.mock('@/lib/workspace', () => ({ useWorkspace: () => ({ current: { id: 'ws1', name: 'Default' }, loading: false }) }));
jest.mock('@/lib/harness', () => ({ getCustom: jest.fn(), testDatabase: jest.fn() }));
jest.mock('@/lib/revamp-data', () => ({ RUNNING: new Set(['running']), TERMINAL_OK: new Set(['completed']), TERMINAL_BAD: new Set(['failed']) }));
jest.mock('@/components/HarnessLogo', () => ({ harnessLogoSrc: () => '' }));
jest.mock('../Iso', () => ({ Iso: () => null }));
jest.mock('../toast', () => ({ toast: jest.fn() }));
jest.mock('../setups', () => ({ rowOf: jest.fn() }));
jest.mock('../SetUpApp', () => ({ SetUpApp: () => null }));
jest.mock('../start/open', () => ({ openNewSetup: jest.fn() }));
jest.mock('./kits', () => ({ ...jest.requireActual('./kits'), fetchKits: jest.fn(), fetchKitBases: jest.fn(), launchKit: jest.fn() }));

import { fetchKitBases, fetchKits, launchKit } from './kits';
import { KitTryPage } from './KitTry';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const KIT: Kit = {
  id: 'dashboard', title: 'Dashboard', tagline: '', description: '', icon: '', accent: '', route: '/kits/dashboard', iconUrl: '',
  launched: false, harnessId: null, skills: [], runningOn: null,
  choices: [
    { base: 'claude-code', model: 'opus', baseLabel: 'Claude Code', available: true, recommended: true },
    { base: 'codex', model: 'gpt-b', baseLabel: 'Codex', available: true, recommended: false },
  ],
};
const BASES = [{ id: 'codex', label: 'Codex', models: [{ id: 'gpt-b', available: true }] }];
let root: Root;
let el: HTMLElement;

const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });
const meta = () => (document.querySelector('.kt-meta')?.textContent || '').replace(/\s+/g, ' ').trim();
async function click(label: string, scope: ParentNode = document) {
  const b = Array.from(scope.querySelectorAll('button')).find((x) => (x.textContent || '').trim() === label) as HTMLButtonElement | undefined;
  if (!b) throw new Error(`no button ${label}: ${document.body.textContent}`);
  await act(async () => { b.click(); await new Promise((r) => setTimeout(r, 0)); });
}
async function open() { await act(async () => { root.render(<KitTryPage kitId="dashboard" />); }); await flush(); }

beforeEach(() => {
  (fetchKits as jest.Mock).mockResolvedValue([KIT]);
  (fetchKitBases as jest.Mock).mockReset().mockResolvedValue(BASES);
  (launchKit as jest.Mock).mockReset().mockResolvedValue({ harnessId: 'h1', route: '/kits/dashboard', created: true, runningOn: { base: 'codex', model: 'gpt-b' } });
  el = document.createElement('div'); document.body.appendChild(el);
  root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); el.remove(); document.body.innerHTML = ''; });

it('after a launch on another pairing, the header names that pairing, not the suggestion', async () => {
  await open();
  expect(meta()).toBe('Claude Codeopus');                        // not set up: the suggestion
  await click('Try it', document.querySelector('.kt-app')!);
  await click('Choose a different one');
  await click('Try it', document.querySelector('[role="dialog"]')!);
  expect(launchKit).toHaveBeenCalledWith('dashboard', expect.objectContaining({ base: 'codex', model: 'gpt-b' }));
  expect(meta()).toBe('Codexgpt-b');
});

it('a launch whose answer names no pairing leaves the header naming none', async () => {
  (launchKit as jest.Mock).mockResolvedValue({ harnessId: 'h1', route: '/kits/dashboard', created: true, runningOn: null });
  await open();
  await click('Try it', document.querySelector('.kt-app')!);
  await click('Try it', document.querySelector('[role="dialog"]')!);
  expect(meta()).toBe('');
});

it('what can run, unread: the launch sheet says so with Try again, which reads it again', async () => {
  (fetchKitBases as jest.Mock).mockReset().mockRejectedValueOnce(new Error('503')).mockResolvedValue(BASES);
  await open();
  await click('Try it', document.querySelector('.kt-app')!);
  await click('Choose a different one');
  expect(document.querySelector('[role="dialog"] [role="alert"]')?.textContent).toContain('could not be read just now');
  expect(document.body.textContent).not.toContain('Nothing you have connected');
  await click('Try again', document.querySelector('[role="dialog"]')!);
  await flush();
  expect(fetchKitBases).toHaveBeenCalledTimes(2);
  expect(document.querySelector('[role="dialog"] [role="alert"]')).toBeNull();
  expect((document.getElementById('klBase') as HTMLSelectElement).value).toBe('codex');
});

it('a kit\'s page is its app: no trace, no tabs, and Make it yours under the app', async () => {
  (fetchKits as jest.Mock).mockResolvedValue([{ ...KIT, launched: true, harnessId: 'h1', runningOn: { base: 'codex', model: 'gpt-b' } }]);
  await open();
  expect(document.querySelector('.kt')?.classList.contains('kt-solo')).toBe(true);
  expect(document.querySelector('[role="tablist"], .kt-play, .kt-live')).toBeNull();
  expect(document.body.textContent).not.toMatch(/trace/i);
  expect(document.querySelector('.kt-app .kt-next-m')?.textContent).toContain('Make it yours');
});

it('names no plan, no price and no paused feed', async () => {
  await open();
  expect(document.body.textContent).not.toMatch(/your plan|See plans|Live updates paused/i);
  expect(document.querySelector('a[href^="/billing"]')).toBeNull();
});
