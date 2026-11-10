/** @jest-environment jsdom */
// Extensions › Environments' list and its New environment: a row is what the service lists (where tasks
// find it, who uses it, its files, its declared packages, its state); New environment asks a name and a
// description and nothing else (Richard, 11-09), makes it empty, and opens it on Files, where adding
// files comes first. The service is lib/environments, answered with its shapes.
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
  const input = document.getElementById(id) as HTMLInputElement | HTMLTextAreaElement;
  const set = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(input), 'value')!.set!;
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


describe('New environment', () => {
  const dialog = () => document.querySelector('.eo-create') as HTMLElement | null;
  const MADE = () => ENV({ id: 'henv_9', name: 'site', slug: 'site', description: 'Docs site', mount: '/env/site', status: 'empty', version: null, latestVersion: null,
    files: { count: 0, bytes: 0 }, declared: { pip: [], npm: [], apt: [] }, build: null });

  it('asks a name and a description, each under its label on its own row, and nothing else', async () => {
    await render([ENV()]);
    await click(button('New environment'));
    const d = dialog() as HTMLElement;
    expect(d.getAttribute('role')).toBe('dialog');
    // the title row holds the title and the close button only
    const top = d.querySelector('.sheet-top') as HTMLElement;
    expect(top.querySelector('h3')?.textContent).toBe('New environment');
    expect(Array.from(top.querySelectorAll('button')).map((b) => b.getAttribute('aria-label'))).toEqual(['Close']);
    expect(top.querySelector('input, textarea, select')).toBeNull();
    // two fields, stacked, each a label above its field
    expect(Array.from(d.querySelectorAll('input, textarea, select')).map((f) => f.id)).toEqual(['eonName', 'eonDesc']);
    const rows = Array.from(d.querySelectorAll(':scope > .set-f'));
    expect(rows.map((r) => r.firstElementChild?.tagName)).toEqual(['LABEL', 'LABEL']);
    expect(rows.map((r) => r.firstElementChild?.textContent)).toEqual(['Name', 'Description optional']);
    expect(rows[1].querySelector('textarea')?.getAttribute('rows')).toBe('3');
    // none of what it used to ask before the environment existed
    for (const gone of ['Start from', 'Git repository', 'Archive', 'Folder', 'Nothing yet', 'Repository address', 'Branch or tag', 'How it is run']) {
      expect(d.textContent).not.toContain(gone);
    }
    expect(d.querySelector('[role="radiogroup"], details, input[type="file"]')).toBeNull();
    // Cancel, then the primary action
    expect(Array.from(d.querySelectorAll('.sheet-actions button')).map((b) => b.textContent)).toEqual(['Cancel', 'Create environment']);
    await click(button('Cancel'));
    expect(dialog()).toBeNull();
  });

  it('refuses a missing or taken name under the field, without asking the service', async () => {
    await render([ENV()]);
    await click(button('New environment'));
    await click(button('Create environment'));
    expect(document.getElementById('eonErr')?.textContent).toBe('Give the environment a name.');
    expect(document.getElementById('eonName')?.getAttribute('aria-invalid')).toBe('true');
    await typeIn('eonName', 'Docs-Repo');
    expect(document.getElementById('eonErr')).toBeNull();               // typing clears it
    await click(button('Create environment'));
    expect(document.getElementById('eonErr')?.textContent).toBe('“Docs-Repo” is already taken. Use another name.');
    expect(m.createEnvironment).not.toHaveBeenCalled();
  });

  it('makes it empty from the name and description, then opens it on Files, adding files first', async () => {
    const made = MADE();
    m.createEnvironment.mockResolvedValue(made);
    m.getEnvironment.mockResolvedValue(made);
    const reload = await render([ENV()]);
    await click(button('New environment'));
    await typeIn('eonName', '  site ');
    await typeIn('eonDesc', ' Docs site ');
    await click(button('Create environment'));
    expect(m.createEnvironment).toHaveBeenCalledTimes(1);
    expect(m.createEnvironment).toHaveBeenCalledWith({ name: 'site', description: 'Docs site' });
    // nothing else is done to it: no files, no build
    expect(m.importEnvironmentGit).not.toHaveBeenCalled();
    expect(m.importEnvironmentArchive).not.toHaveBeenCalled();
    expect(m.writeEnvironmentFile).not.toHaveBeenCalled();
    expect(m.buildEnvironment).not.toHaveBeenCalled();
    expect(reload).toHaveBeenCalled();
    expect(dialog()).toBeNull();
    // its own sheet, on Files, with Packages next
    expect(window.location.search).toBe('?tab=envs&env=henv_9');
    expect(document.getElementById('eoh')?.textContent).toBe('site');
    expect(Array.from(document.querySelectorAll('.eo-tabs [role="tab"]')).slice(0, 2).map((t) => t.textContent)).toEqual(['Files0', 'Packages0']);
    expect(document.querySelector('.eo-tabs [aria-selected="true"]')?.textContent).toContain('Files');
    expect(document.querySelector('.eo-nofiles h4')?.textContent).toBe('Add files');
    expect(Array.from(document.querySelectorAll('.eo-start-act button')).map((b) => b.textContent)).toEqual(['Upload files', 'Upload a folder']);
    expect(button('Build')).toBeUndefined();                           // nothing to build until files are in: not offered
  });

  it('says the service’s refusal under the name and stays open', async () => {
    m.createEnvironment.mockRejectedValue(Object.assign(new Error('An environment is already mounted'), { status: 409 }));
    await render([]);
    await click(button('New environment'));
    await typeIn('eonName', 'site');
    await click(button('Create environment'));
    expect(document.getElementById('eonErr')?.textContent).toBe('An environment named like “site” already exists. Use another name.');
    expect(dialog()).not.toBeNull();
    expect(button('Create environment')?.disabled).toBe(false);
    expect(window.location.search).toBe('?tab=envs');
  });
});
