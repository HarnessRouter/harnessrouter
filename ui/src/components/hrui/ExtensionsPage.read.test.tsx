/** @jest-environment jsdom */
// Add-ons when its reads fail or never answer (2026-10-19 06:03Z: a store stalled for about a minute
// and Plugins showed its skeleton forever, saying nothing). Every tab's list is read
// to an end (lib/settle.ts): a failed read is asked once more, quietly, and then the tab says plainly
// that the list could not be loaded, with Try again; a read with no answer does the same within 15 s.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

jest.mock('next/link', () => ({ __esModule: true, default: ({ href, children, ...p }: { href: string; children: React.ReactNode }) => <a href={href} {...p}>{children}</a> }));
jest.mock('@/lib/workspace', () => ({
  useWorkspace: () => ({ current: { id: 'ws', name: 'Default Workspace' }, defaultId: 'ws', loading: false }),
  appendWorkspaceQuery: (q: URLSearchParams) => { q.set('workspace', 'ws'); },
}));
jest.mock('@/lib/harness', () => {
  class GwError extends Error { constructor(public status: number, public code: string, message: string) { super(message); } }
  return {
    GwError, listCustom: jest.fn(), basesDoc: jest.fn(async () => ({})), gwSay: jest.fn(), gw: jest.fn(),
    getCustom: jest.fn(), saveCustom: jest.fn(), getSkillFiles: jest.fn(), useBases: () => ({}), storeMcpSecret: jest.fn(), testMcp: jest.fn(),
  };
});
jest.mock('@/lib/environments', () => ({
  listEnvironments: jest.fn(), createEnvironment: jest.fn(), updateEnvironment: jest.fn(), deleteEnvironment: jest.fn(),
  importEnvironmentGit: jest.fn(), buildEnvironment: jest.fn(), environmentHarnesses: jest.fn(),
}));
jest.mock('@/lib/plugs', () => ({
  listPlugs: jest.fn(), setPlug: jest.fn(), deletePlug: jest.fn(), plugTools: jest.fn(), plugAttachments: jest.fn(),
  microsoftStart: jest.fn(), microsoftComplete: jest.fn(), microsoftSignout: jest.fn(),
}));
jest.mock('@/lib/auth', () => ({ getSession: () => null }));
jest.mock('./bricks', () => ({ partIcon: () => '<svg></svg>', PagePic: () => null }));
jest.mock('./toast', () => ({ toast: jest.fn() }));
jest.mock('./skills/SkillEditor', () => ({ SkillEditor: () => null }));
jest.mock('./setup/settingsModel', () => ({ isServiceEntry: () => false }));
jest.mock('@/components/HarnessLogo', () => ({ harnessLogoSrc: () => '' }));

import * as harness from '@/lib/harness';
import * as envs from '@/lib/environments';
import * as plugs from '@/lib/plugs';
import { ExtensionsPage, tabOf } from './ExtensionsPage';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const h = harness as jest.Mocked<typeof harness>;
const e = envs as jest.Mocked<typeof envs>;
const p = plugs as jest.Mocked<typeof plugs>;
const never = <T,>() => new Promise<T>(() => { /* no answer */ });

let root: Root;
let el: HTMLDivElement;
const flush = async (ms = 0) => {
  for (let i = 0; i < 6; i++) await act(async () => { await Promise.resolve(); });
  if (ms) await act(async () => { await jest.advanceTimersByTimeAsync(ms); });
  for (let i = 0; i < 6; i++) await act(async () => { await Promise.resolve(); });
};
const alert = () => el.querySelector('[role="alert"]');
const skeleton = () => el.querySelector('.hrui-skel[aria-busy="true"]');
const button = (text: string) => Array.from(el.querySelectorAll('button')).find((b) => b.textContent?.trim().startsWith(text)) as HTMLButtonElement;
async function open() { await act(async () => { root.render(<ExtensionsPage />); }); }
async function tab(name: string) { await act(async () => { button(name).click(); }); }

beforeEach(() => {
  jest.useFakeTimers({ doNotFake: ['queueMicrotask', 'nextTick', 'setImmediate'] });
  jest.clearAllMocks();
  window.history.replaceState(null, '', '/extensions');
  document.body.innerHTML = '<div id="hrui"></div>';
  el = document.getElementById('hrui') as HTMLDivElement;
  root = createRoot(el);
});
afterEach(async () => {
  await act(async () => { root.unmount(); });
  jest.useRealTimers();
});

test('each list that could not be read says so, with Try again, after one quiet second try', async () => {
  p.listPlugs.mockRejectedValue(new Error('503'));
  h.listCustom.mockRejectedValue(new Error('503'));
  e.listEnvironments.mockRejectedValue(new Error('503'));
  await open();
  await flush();
  // the first failure is asked again, quietly: still the skeleton, no error yet
  expect(skeleton()).not.toBeNull();
  expect(alert()).toBeNull();
  await flush(1000);
  expect(p.listPlugs).toHaveBeenCalledTimes(2);
  expect(h.listCustom).toHaveBeenCalledTimes(2);
  expect(e.listEnvironments).toHaveBeenCalledTimes(2);

  expect(alert()?.textContent).toBe('Your plugins could not be loaded just now. Try again');
  expect(skeleton()).toBeNull();
  expect(el.textContent).not.toContain('Nothing connected yet');
  await tab('Skills');
  expect(alert()?.textContent).toBe('Your skills could not be loaded just now. Try again');
  expect(skeleton()).toBeNull();
  expect(el.textContent).not.toContain('No skills yet');
  await tab('Tools');
  expect(alert()?.textContent).toBe('Your tools could not be loaded just now. Try again');
  expect(el.textContent).not.toContain('No MCP servers yet');
  await tab('Environments');
  expect(alert()?.textContent).toBe('Your environments could not be loaded just now. Try again');
  expect(el.textContent).not.toContain('No environments yet');
});

test('Try again goes back to the skeleton and reads again', async () => {
  e.listEnvironments.mockRejectedValue(new Error('503'));
  p.listPlugs.mockResolvedValue({ workspace: 'ws', plugs: [] });
  h.listCustom.mockResolvedValue([]);
  window.history.replaceState(null, '', '/extensions?tab=envs');
  await open();
  await flush(1000);
  expect(alert()?.textContent).toContain('Your environments could not be loaded just now.');
  e.listEnvironments.mockResolvedValue([]);
  await act(async () => { button('Try again').click(); });
  await flush();
  expect(alert()).toBeNull();
  expect(el.textContent).toContain('No environments yet.');
  expect(e.listEnvironments).toHaveBeenCalledTimes(3);
});

test('a read with no answer ends: the skeleton gives way to the error within 15 s, its requests cancelled', async () => {
  const signals: AbortSignal[] = [];
  p.listPlugs.mockImplementation((signal?: AbortSignal) => { if (signal) signals.push(signal); return never(); });
  h.listCustom.mockResolvedValue([]);
  e.listEnvironments.mockResolvedValue([]);
  await open();
  await flush(14_000);
  expect(skeleton()).not.toBeNull();
  expect(alert()).toBeNull();
  await flush(1_000);
  expect(alert()?.textContent).toBe('Your plugins could not be loaded just now. Try again');
  expect(skeleton()).toBeNull();
  expect(signals).toHaveLength(2);
  expect(signals.every((s) => s.aborted)).toBe(true);
});

test('the tab is in the address, and an older console link to Environments opens it', async () => {
  expect(tabOf('skills')).toBe('skills');
  expect(tabOf('environments')).toBe('envs');
  expect(tabOf('billing')).toBeNull();
  p.listPlugs.mockResolvedValue({ workspace: 'ws', plugs: [] });
  h.listCustom.mockResolvedValue([]);
  e.listEnvironments.mockResolvedValue([]);
  window.history.replaceState(null, '', '/extensions?tab=environments');
  await open();
  await flush();
  expect(el.querySelector('[role="tab"][aria-selected="true"]')?.textContent).toContain('Environments');
  expect(el.textContent).toContain('No environments yet.');
});
