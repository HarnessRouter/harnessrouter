/** @jest-environment jsdom */
// A setup's Plugins tab as a person uses it (Richard, 10-21: it looked empty, with one big Add plugin):
// every plugin the workspace has connected is a row with a switch for this setup, included ones first.
// A flip writes at once through the setup's plugins binding, waits while it saves, and goes back where
// it was when the write does not take. What the setup includes that the workspace no longer serves is
// listed, warned, and can be left out. Nothing connected says so, with Connect a plugin.
import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { Plug } from '@/lib/harness';

jest.mock('next/link', () => ({ __esModule: true, default: ({ href, children, ...p }: { href: string; children: React.ReactNode }) => <a href={href} {...p}>{children}</a> }));
jest.mock('@/lib/plugs', () => ({
  listPlugs: jest.fn(), plugAttachments: jest.fn(), setPlug: jest.fn(), deletePlug: jest.fn(), plugTools: jest.fn(),
  microsoftStart: jest.fn(), microsoftSignout: jest.fn(),
}));
jest.mock('../bricks', () => ({ partIcon: () => '<svg></svg>' }));
jest.mock('../toast', () => ({ toast: jest.fn() }));

import { toast } from '../toast';
import { PluginSwitches, pluginLines, type PluginsIn } from './PluginSwitches';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const P = (type: string, label: string, status: Plug['status'] = 'connected', over: Partial<Plug> = {}): Plug => ({
  type, label, source: 'platform', official: true, status, config: {}, secrets_set: [], secrets_needed: [], config_fields: [], version: 1, tools: 3, ...over,
});
const LAPSED = 'Its sign-in lapsed. Connect it again.';
const CATALOG = [P('browser', 'Browser'), P('github', 'GitHub', 'needs_auth', { attention: LAPSED }), P('vercel', 'Vercel', 'missing'),
  P('insforge', 'InsForge', 'connected'), P('microsoft365', 'Microsoft 365', 'disabled')];

let root: Root;
let el: HTMLElement;
let onSet: jest.Mock;
let onConnect: jest.Mock;
let onManagePackage: jest.Mock;

const base = (): PluginsIn => ({ plugs: CATALOG, binding: ['browser'], packages: [] });

type Extra = { q?: string; failed?: { retry: () => void } | null };
/** The tab as SetupSettings holds it: the binding as last written, each write through `onSet` (a mock a
 *  test can fail or answer false). */
function Host({ start, extra }: { start: PluginsIn; extra: Extra }) {
  const [b, setB] = useState<string[] | undefined>(start.binding);
  return (
    <PluginSwitches input={{ ...start, binding: b }} setup="Mail helper" q={extra.q || ''} busy={false} failed={extra.failed}
      onSet={async (plugs) => { const ok = await onSet(plugs); if (ok) setB(plugs); return ok; }}
      onPackage={jest.fn(async () => true)} onManagePackage={onManagePackage} onConnect={onConnect} reload={async () => {}} />
  );
}
const flush = async () => { for (let i = 0; i < 6; i++) await act(async () => { await Promise.resolve(); }); };
async function draw(over: Partial<PluginsIn> = {}, extra: Extra = {}) {
  await act(async () => { root.render(<Host key={Math.random()} start={{ ...base(), ...over }} extra={extra} />); });
  await flush();
}
const rows = () => Array.from(el.querySelectorAll('.pl-sw .cap-row'));
const names = () => rows().map((r) => r.querySelector('b')?.textContent);
const rowOf = (name: string) => rows().find((r) => r.querySelector('b')?.textContent === name) as HTMLElement;
const sw = (name: string) => rowOf(name).querySelector('[role=switch]') as HTMLButtonElement;
const button = (t: string) => Array.from(el.querySelectorAll('button')).find((b) => b.textContent === t) as HTMLButtonElement | undefined;
async function click(b: HTMLElement) { await act(async () => { b.click(); }); await flush(); }

beforeEach(() => {
  jest.clearAllMocks();
  onSet = jest.fn().mockResolvedValue(true);
  onConnect = jest.fn();
  onManagePackage = jest.fn();
  document.body.innerHTML = '<div id="hrui"></div>';
  el = document.getElementById('hrui') as HTMLElement;
  root = createRoot(el);
});
afterEach(async () => { await act(async () => { root.unmount(); }); });

it('lists every connected plugin with a switch, included first, then the rest, each alphabetical', async () => {
  await draw();
  expect(names()).toEqual(['Browser', 'GitHub', 'InsForge']);
  expect(sw('Browser').getAttribute('aria-checked')).toBe('true');
  expect(sw('InsForge').getAttribute('aria-checked')).toBe('false');
  expect(sw('InsForge').getAttribute('aria-label')).toBe('Include InsForge in Mail helper');
  expect(rowOf('InsForge').classList.contains('off')).toBe(true);
  // not connected (never, or turned off in the workspace): Connect another plugin offers it
  expect(names()).not.toContain('Vercel');
  expect(names()).not.toContain('Microsoft 365');
  // a credential that lapsed says so, with its fix
  expect(rowOf('GitHub').querySelector('small.warn')?.textContent).toBe(LAPSED);
  expect(rowOf('GitHub').querySelector('.pl-sw-fix button')?.textContent).toBe('Reconnect');
  expect(button('Connect another plugin')).toBeTruthy();
});

it('includes and leaves out with one tap through the binding, and the row stays where it was', async () => {
  await draw();
  await click(sw('InsForge'));
  expect(onSet).toHaveBeenLastCalledWith(['browser', 'insforge']);
  expect(sw('InsForge').getAttribute('aria-checked')).toBe('true');
  expect(names()).toEqual(['Browser', 'GitHub', 'InsForge']);
  await click(sw('Browser'));
  expect(onSet).toHaveBeenLastCalledWith(['insforge']);
  expect(sw('Browser').getAttribute('aria-checked')).toBe('false');
  expect(names()).toEqual(['Browser', 'GitHub', 'InsForge']);   // never moves under the finger
});

it('a write that does not take leaves the switch where it was; one that throws says so', async () => {
  await draw();
  onSet.mockResolvedValueOnce(false);
  await click(sw('InsForge'));
  expect(sw('InsForge').getAttribute('aria-checked')).toBe('false');
  onSet.mockRejectedValueOnce(new Error('502'));
  await click(sw('InsForge'));
  expect(sw('InsForge').getAttribute('aria-checked')).toBe('false');
  expect(toast).toHaveBeenCalledWith('InsForge was not changed. Try again.');
});

it('what the setup includes that the workspace no longer serves is listed, warned, and can be left out', async () => {
  await draw({ binding: ['browser', 'microsoft365', 'gone'] });
  expect(rowOf('Microsoft 365').querySelector('small.warn')?.textContent).toBe('Turned off in this workspace');
  expect(rowOf('gone').querySelector('small.warn')?.textContent).toBe('Not connected in this workspace');
  expect(rowOf('gone').querySelector('.pl-sw-fix a')?.getAttribute('href')).toBe('/extensions');
  await click(sw('Microsoft 365'));
  expect(onSet).toHaveBeenLastCalledWith(['browser', 'gone']);
  // left out, it stays listed, off, so it can be switched back
  expect(sw('Microsoft 365').getAttribute('aria-checked')).toBe('false');
});

it('nothing connected says so, with Connect a plugin; a catalog that could not be read says so, with Try again', async () => {
  await draw({ plugs: [P('vercel', 'Vercel', 'missing')], binding: [] });
  expect(el.textContent).toContain('No plugins are connected in this workspace yet.');
  await click(button('Connect a plugin') as HTMLButtonElement);
  expect(onConnect).toHaveBeenCalled();
  const retry = jest.fn();
  await draw({ plugs: null }, { failed: { retry } });
  expect(el.textContent).toContain('Your plugins could not be loaded just now.');
  await click(button('Try again') as HTMLButtonElement);
  expect(retry).toHaveBeenCalled();
});

it('a package installed on the setup is a row with Manage; the search narrows the rows', async () => {
  await draw({ packages: [{ name: 'brand-kit', on: true, desc: 'Brand voice', left: 0 }, { name: 'half', on: true, desc: '', left: 2 }] });
  expect(rowOf('brand-kit').querySelector('small')?.textContent).toBe('Brand voice');
  expect(rowOf('half').querySelector('small.warn')?.textContent).toBe('2 parts not loaded');
  await click(rowOf('brand-kit').querySelector('.pl-sw-fix button') as HTMLButtonElement);
  expect(onManagePackage).toHaveBeenCalledWith('brand-kit');
  await draw({}, { q: 'git' });
  expect(names()).toEqual(['GitHub']);
});

it('pluginLines: nothing about the workspace’s plugins before both they and the binding are read', () => {
  expect(pluginLines({ plugs: null, binding: ['browser'], packages: [] })).toEqual([]);
  expect(pluginLines({ plugs: CATALOG, binding: undefined, packages: [] })).toEqual([]);
});
