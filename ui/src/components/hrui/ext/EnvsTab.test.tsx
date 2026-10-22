/** @jest-environment jsdom */
// Extensions › Environments' list and its New environment: a row is what the service lists (where tasks
// find it, who uses it, its files, its declared packages, its state); New environment from a git
// repository makes it, imports the repository at the branch or tag given, builds it and opens it on
// Builds; one from nothing opens on Files. The service is lib/environments, answered with its shapes.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { Environment } from '@/lib/environments';
import type { CustomHarness } from '@/lib/harness';

jest.mock('next/link', () => ({ __esModule: true, default: ({ href, children, ...p }: { href: string; children: React.ReactNode }) => <a href={href} {...p}>{children}</a> }));
jest.mock('@/lib/environments', () => ({
  listEnvironments: jest.fn(), createEnvironment: jest.fn(), deleteEnvironment: jest.fn(), importEnvironmentGit: jest.fn(), importEnvironmentArchive: jest.fn(),
  writeEnvironmentFile: jest.fn(), buildEnvironment: jest.fn(), environmentHarnesses: jest.fn(), getEnvironment: jest.fn(), listEnvironmentFiles: jest.fn(),
  getEnvironmentBuild: jest.fn(), listRuntimes: jest.fn(), checkPackage: jest.fn(), updateEnvironment: jest.fn(), activateEnvironmentVersion: jest.fn(),
  readEnvironmentFile: jest.fn(), makeEnvironmentDir: jest.fn(), deleteEnvironmentPath: jest.fn(),
  fmtBytes: (n: number) => `${n} B`,
}));
jest.mock('@/lib/harness', () => ({ getCustom: jest.fn(), saveCustom: jest.fn() }));
jest.mock('../bricks', () => ({ partIcon: () => '<svg></svg>' }));
jest.mock('../toast', () => ({ toast: jest.fn() }));

import * as lib from '@/lib/environments';
import { EnvsTab, pkgLine } from './EnvsTab';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const m = lib as jest.Mocked<typeof lib>;

const ENV = (over: Partial<Environment> = {}): Environment => ({
  id: 'henv_1', object: 'environment', name: 'docs-repo', slug: 'docs-repo', description: '', entry: '', status: 'ready', mount: '/env/docs-repo',
  version: 2, latestVersion: 3, files: { count: 12, bytes: 4096 }, packages: [],
  declared: { pip: [{ name: 'flask', version: '', spec: 'flask' }, { name: 'requests', version: '', spec: 'requests' }], npm: [{ name: 'sharp', version: '', spec: 'sharp' }], apt: [] },
  runtime: { python: '' }, versions: [], build: { version: 3, status: 'failed' },
  member: 'm', workspace: 'w', createdAt: 0, updatedAt: 0, ...over,
});

let root: Root;
let el: HTMLDivElement;
const flush = async () => { for (let i = 0; i < 12; i++) await act(async () => { await Promise.resolve(); }); };
const button = (text: string) => Array.from(document.querySelectorAll('button')).find((b) => b.textContent === text) as HTMLButtonElement | undefined;
async function click(b: HTMLElement | undefined) { if (!b) throw new Error('no such button'); await act(async () => { b.click(); }); await flush(); }
async function typeIn(id: string, value: string) {
  const input = document.getElementById(id) as HTMLInputElement;
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  await act(async () => { set.call(input, value); input.dispatchEvent(new Event('input', { bubbles: true })); });
}
async function render(envs: Environment[]) {
  const reload = jest.fn(async () => {});
  await act(async () => { root.render(<EnvsTab data={{ envs, reload, failed: false, retry: jest.fn() }} setups={[{ id: 'h1', name: 'Docs helper', environment: 'henv_1' } as CustomHarness]} reloadSetups={jest.fn(async () => {})} />); });
  await flush();
  return reload;
}

beforeEach(() => {
  jest.clearAllMocks();
  window.history.replaceState(null, '', '/extensions?tab=envs');
  document.body.innerHTML = '<div id="hrui"></div>';
  el = document.getElementById('hrui') as HTMLDivElement;
  root = createRoot(el);
  m.listEnvironmentFiles.mockResolvedValue({ entries: [], count: 0, bytes: 0 });
  m.environmentHarnesses.mockResolvedValue([]);
  m.listRuntimes.mockResolvedValue({ python: [], node: [], os: { name: '', version: '' }, apt: true });
  m.getEnvironmentBuild.mockResolvedValue({ id: 'henv_9', version: 1, status: 'building', stage: 'starting', log: '' });
});
afterEach(async () => { await act(async () => { root.unmount(); }); });

it('lists each environment with what the service knows about it', async () => {
  await render([ENV()]);
  const row = el.querySelector('.eo-row') as HTMLElement;
  expect(row.querySelector('.eo-name')?.textContent).toBe('docs-repo');
  expect(row.querySelector('.sub2')?.textContent).toBe('/env/docs-repo · 12 files · 2 pip · 1 npm');
  expect(row.querySelector('.lib-used')?.textContent).toBe('Used by Docs helper');
  expect(row.querySelector('.eo-c-files')?.textContent).toBe('12 files4096 B');
  expect(row.querySelector('.eo-c-pk')?.textContent).toBe('2 pip · 1 npm');
  expect(row.querySelector('.eo-c-st')?.textContent).toBe('ReadyNewer build failed');
  expect(pkgLine(ENV({ declared: { pip: [], npm: [], apt: [] } }))).toBe('No packages');
});

it('says there are none in one line, with New environment', async () => {
  await render([]);
  expect(el.querySelector('.empty-list')?.textContent).toBe('No environments yet.');
  expect(el.querySelector('.eo-flow')).toBeNull();
  expect(button('New environment')).toBeTruthy();
});

it('opens the environment its address names, as an older console link to one lands here', async () => {
  m.getEnvironment.mockResolvedValue(ENV());
  window.history.replaceState(null, '', '/extensions?tab=environments&env=henv_1');
  await render([ENV()]);
  expect(m.getEnvironment).toHaveBeenCalledWith('henv_1');
  expect(document.querySelector('.eo-sheet #eoh')?.textContent).toBe('docs-repo');
});

it('says nothing under a ready state unless a newer build failed', async () => {
  await render([ENV({ build: { version: 2, status: 'ready' } })]);
  expect(el.querySelector('.eo-c-st')?.textContent).toBe('Ready');
});

it('makes one from a git repository, imports it at the branch given, builds it and opens it on Builds', async () => {
  const made = ENV({ id: 'henv_9', name: 'site', mount: '/env/site', status: 'empty', version: null, latestVersion: null, files: { count: 0, bytes: 0 }, declared: { pip: [], npm: [], apt: [] }, build: null });
  m.createEnvironment.mockResolvedValue(made);
  m.importEnvironmentGit.mockResolvedValue({ written: 40, count: 40, bytes: 1000 });
  m.buildEnvironment.mockResolvedValue({ version: 1, status: 'building' });
  m.getEnvironment.mockResolvedValue({ ...made, status: 'building', latestVersion: 1, files: { count: 40, bytes: 1000 }, build: { version: 1, status: 'building' } });
  const reload = await render([ENV()]);
  await click(button('New environment'));

  await click(button('Create environment'));
  expect(document.querySelector('.eo-new .eo-msg')?.textContent).toBe('Give the environment a name.');
  await typeIn('eonName', 'Docs-Repo');
  await click(button('Create environment'));
  expect(document.querySelector('.eo-new .eo-msg')?.textContent).toBe('“Docs-Repo” is already taken. Use another name.');
  await typeIn('eonName', 'site');
  await typeIn('eonUrl', 'not a repo');
  await click(button('Create environment'));
  expect(document.querySelector('.eo-new .eo-msg')?.textContent).toBe('Paste a git repository address, like https://github.com/your-org/project.');
  expect(m.createEnvironment).not.toHaveBeenCalled();

  await typeIn('eonUrl', 'github.com/acme/site');
  await typeIn('eonRef', 'v2');
  await click(button('Create environment'));
  expect(m.createEnvironment).toHaveBeenCalledWith({ name: 'site', description: '', entry: '' });
  expect(m.importEnvironmentGit).toHaveBeenCalledWith('henv_9', 'https://github.com/acme/site', 'v2', false);
  expect(m.buildEnvironment).toHaveBeenCalledWith('henv_9');
  expect(reload).toHaveBeenCalled();
  expect(document.querySelector('.eo-new')).toBeNull();
  expect(document.querySelector('.eo-tabs [aria-selected="true"]')?.textContent).toContain('Builds');
  expect(window.location.search).toBe('?tab=envs&env=henv_9');
});

it('opens one made from nothing on Files, where the project goes in', async () => {
  const made = ENV({ id: 'henv_8', name: 'blank', status: 'empty', version: null, latestVersion: null, files: { count: 0, bytes: 0 }, declared: { pip: [], npm: [], apt: [] }, build: null });
  m.createEnvironment.mockResolvedValue(made);
  m.getEnvironment.mockResolvedValue(made);
  await render([]);
  await click(button('New environment'));
  await typeIn('eonName', 'blank');
  await click(button('Nothing yet'));
  await click(button('Create environment'));
  expect(m.importEnvironmentGit).not.toHaveBeenCalled();
  expect(m.buildEnvironment).not.toHaveBeenCalled();
  expect(document.querySelector('.eo-nofiles')?.textContent).toBe('No files yet. Import a project');
  expect(button('Build')).toBeUndefined();                           // nothing to build until files are in: not offered
});

it('makes one from a folder with every file in it, its own name dropped, then builds it', async () => {
  const made = ENV({ id: 'henv_7', name: 'proj', status: 'empty', version: null, latestVersion: null, files: { count: 0, bytes: 0 }, declared: { pip: [], npm: [], apt: [] }, build: null });
  m.createEnvironment.mockResolvedValue(made);
  m.writeEnvironmentFile.mockResolvedValue({});
  m.buildEnvironment.mockResolvedValue({ version: 1, status: 'building' });
  m.getEnvironment.mockResolvedValue({ ...made, status: 'building', latestVersion: 1, build: { version: 1, status: 'building' } });
  await render([]);
  await click(button('New environment'));
  await typeIn('eonName', 'proj');
  await click(button('Folder'));
  expect(document.querySelector('.eo-new')?.textContent).not.toContain('node_modules');
  const input = document.querySelector('.eo-new input[webkitdirectory]') as HTMLInputElement;
  const files = ['proj/run.py', 'proj/node_modules/x/index.js', 'proj/.git/HEAD', 'proj/.venv/bin/python']
    .map((p) => Object.defineProperty(new File(['x'], p.split('/').pop() as string), 'webkitRelativePath', { value: p }));
  Object.defineProperty(input, 'files', { value: files, configurable: true });
  await act(async () => { input.dispatchEvent(new Event('change', { bubbles: true })); });
  expect(document.querySelector('.eo-pick .set-help')?.textContent).toBe('proj · 4 files');
  await click(button('Create environment'));
  expect(m.writeEnvironmentFile.mock.calls.map((c) => c[1])).toEqual(['run.py', 'node_modules/x/index.js', '.git/HEAD', '.venv/bin/python']);
  expect(m.buildEnvironment).toHaveBeenCalledWith('henv_7');
});
