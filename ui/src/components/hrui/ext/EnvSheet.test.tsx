/** @jest-environment jsdom */
// The environment sheet as a person uses it (Richard, 10-18: the old environment page's whole experience
// in the new design): a package added is checked with its registry first and refused with its answer,
// then saved and built; a running build shows its stage, its seconds and its log, a failed one why; an
// older finished version can be put back in use. The service is lib/environments, answered here with
// the shapes the gateway sends. A text file opens in the console's code editor (CodeEditor, tested on
// its own and drawn here as a plain field); a file that is not text is shown as itself.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { Environment, EnvironmentBuildRecord } from '@/lib/environments';

jest.mock('next/link', () => ({ __esModule: true, default: ({ href, children, ...p }: { href: string; children: React.ReactNode }) => <a href={href} {...p}>{children}</a> }));
jest.mock('@/lib/environments', () => ({
  getEnvironment: jest.fn(), listEnvironmentFiles: jest.fn(), environmentHarnesses: jest.fn(), getEnvironmentBuild: jest.fn(), listRuntimes: jest.fn(),
  checkPackage: jest.fn(), updateEnvironment: jest.fn(), buildEnvironment: jest.fn(), activateEnvironmentVersion: jest.fn(),
  readEnvironmentFile: jest.fn(), writeEnvironmentFile: jest.fn(), makeEnvironmentDir: jest.fn(), deleteEnvironmentPath: jest.fn(),
  importEnvironmentArchive: jest.fn(), importEnvironmentGit: jest.fn(),
  fmtBytes: (n: number) => `${n} B`,
}));
jest.mock('../toast', () => ({ toast: jest.fn() }));
// CodeMirror needs a laid-out page: the editor is stood in for by a field that shows what it was given
jest.mock('../CodeEditor', () => ({
  CodeEditor: (p: { value: string; onChange?: (v: string) => void; path: string; ariaLabel: string; readOnly?: boolean }) => (
    <textarea className="code-stub" aria-label={p.ariaLabel} data-path={p.path} readOnly={p.readOnly} value={p.value} onChange={(e) => p.onChange?.(e.target.value)} />
  ),
}));

import * as lib from '@/lib/environments';
import { toast } from '../toast';
import { EnvSheet, mediaOf, type EnvTab } from './EnvSheet';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const m = lib as jest.Mocked<typeof lib>;
const say = toast as jest.Mock;

const ENV = (over: Partial<Environment> = {}): Environment => ({
  id: 'henv_1', object: 'environment', name: 'docs-repo', slug: 'docs-repo', description: '', entry: '', status: 'ready', mount: '/env/docs-repo',
  version: 2, latestVersion: 2, files: { count: 3, bytes: 300 },
  packages: [{ manager: 'pip', name: 'requests', version: '2.31.0' }],
  declared: { pip: [{ name: 'requests', version: '', spec: 'requests' }], npm: [], apt: [] },
  runtime: { python: '' },
  versions: [
    { version: 1, status: 'ready', started_at: 1_760_000_000, finished_at: 1_760_000_040, files: 3, packages: 4 },
    { version: 2, status: 'ready', started_at: 1_760_100_000, finished_at: 1_760_100_050, files: 3, packages: 5 },
  ],
  build: { version: 2, status: 'ready', started_at: 1_760_100_000, finished_at: 1_760_100_050 },
  member: 'm', workspace: 'w', createdAt: 0, updatedAt: 0, ...over,
});
const REC = (over: Partial<EnvironmentBuildRecord> = {}): EnvironmentBuildRecord => ({
  id: 'henv_1', version: 2, status: 'ready', started_at: 1_760_100_000, finished_at: 1_760_100_050, log: '$ pip install requests\nSuccessfully installed requests', packages: [], files: 3, ...over,
});

let env: Environment;
let rec: EnvironmentBuildRecord;
let root: Root;
let el: HTMLDivElement;

const flush = async () => { for (let i = 0; i < 10; i++) await act(async () => { await Promise.resolve(); }); };
const button = (text: string) => Array.from(document.querySelectorAll('button')).find((b) => b.textContent === text) as HTMLButtonElement | undefined;
async function click(b: HTMLElement | undefined) { if (!b) throw new Error('no such button'); await act(async () => { b.click(); }); await flush(); }
async function typeIn(input: HTMLInputElement, value: string) {
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  await act(async () => { set.call(input, value); input.dispatchEvent(new Event('input', { bubbles: true })); });
}
async function submit(form: HTMLFormElement) { await act(async () => { form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); }); await flush(); }
async function open(tab: EnvTab) {
  await act(async () => { root.render(<EnvSheet id="henv_1" tab={tab} onClose={jest.fn()} onChanged={jest.fn()} onDelete={jest.fn(async () => true)} />); });
  await flush();
}
const pkgRows = () => Array.from(document.querySelectorAll('.eo-pkg')).map((r) => r.textContent);
const spec = () => document.getElementById('eoSpec') as HTMLInputElement;

beforeEach(() => {
  jest.clearAllMocks();
  env = ENV();
  rec = REC();
  m.getEnvironment.mockImplementation(async () => env);
  m.listEnvironmentFiles.mockResolvedValue({ entries: [{ path: 'run.py', dir: false, bytes: 10, mtime: 0 }, { path: 'requirements.txt', dir: false, bytes: 9, mtime: 0 }], count: 2, bytes: 19 });
  m.environmentHarnesses.mockResolvedValue([{ id: 'h1', name: 'Docs helper', base: 'claude-code' }]);
  m.getEnvironmentBuild.mockImplementation(async (_id: string, n: number) => (n === rec.version ? rec : REC({ version: n, log: `log of ${n}` })));
  m.listRuntimes.mockResolvedValue({ python: ['3.11', '3.12'], node: ['22'], os: { name: 'debian', version: '12' }, apt: true });
  m.updateEnvironment.mockImplementation(async (_id, body) => {
    env = ENV({ ...env, name: body.name, declared: { pip: (body.packages?.pip || []).map((s) => ({ name: s, version: '', spec: s })), npm: [], apt: [] }, runtime: body.runtime || env.runtime });
    return env;
  });
  m.buildEnvironment.mockImplementation(async () => { env = ENV({ ...env, status: 'building', latestVersion: 3, build: { version: 3, status: 'building', started_at: 1_760_200_000 } }); rec = REC({ version: 3, status: 'building', stage: 'installing pip packages', log: '$ pip install flask', finished_at: null }); return { version: 3, status: 'building' }; });
  document.body.innerHTML = '<div id="hrui"></div>';
  el = document.getElementById('hrui') as HTMLDivElement;
  root = createRoot(el);
});
afterEach(async () => { await act(async () => { root.unmount(); }); });

describe('packages', () => {
  it('checks a package with its registry on Add, refuses what it does not have, and saves and builds what it does', async () => {
    m.checkPackage.mockImplementation(async (_m, s) => (s === 'flsak'
      ? { manager: 'pip', name: 'flsak', spec: s, exists: false, latest: '', version: '', error: 'flsak was not found on PyPI' }
      : { manager: 'pip', name: 'flask', spec: s, exists: true, latest: '3.0.3', version: '', error: '' }));
    await open('packages');
    expect(pkgRows()).toEqual(['requests2.31.0']);                  // the version the active build installed
    expect(button('Build again')).toBeTruthy();                      // nothing held: the action is a build

    // a spec the service would not keep never reaches the registry
    await typeIn(spec(), 'flask >= 3');
    await submit(spec().form as HTMLFormElement);
    expect(m.checkPackage).not.toHaveBeenCalled();
    expect(document.getElementById('eoSpecSay')?.textContent).toBe('Write it as name==1.0, or just the name for the latest.');

    // a name the registry does not have is refused with its own words, and not added
    await typeIn(spec(), 'flsak');
    await submit(spec().form as HTMLFormElement);
    expect(m.checkPackage).toHaveBeenLastCalledWith('pip', 'flsak');
    expect(document.getElementById('eoSpecSay')?.textContent).toBe('flsak was not found on PyPI');
    expect(pkgRows()).toHaveLength(1);

    // one it has is added with the version it reported, held until Save
    await typeIn(spec(), 'flask');
    await submit(spec().form as HTMLFormElement);
    expect(pkgRows()).toEqual(['requests2.31.0', 'flask3.0.3installs when you save and build']);
    expect(spec().value).toBe('');
    expect(document.querySelector('.eo-state')?.textContent).toBe('Not saved yet: packages.');

    await click(button('Save and build'));
    expect(m.updateEnvironment).toHaveBeenCalledWith('henv_1', { name: 'docs-repo', description: '', entry: '', packages: { pip: ['requests', 'flask'], npm: [], apt: [] }, runtime: { python: '' } });
    expect(m.buildEnvironment).toHaveBeenCalledWith('henv_1');
    // the build tab takes over, with the build that just started
    expect(document.querySelector('.eo-run-head b')?.textContent).toBe('Building version 3');
  });

  it('leaves apt out where the service builds without it', async () => {
    m.listRuntimes.mockResolvedValue({ python: ['3.11'], node: [], os: { name: '', version: '' }, apt: false });
    await open('packages');
    const tabs = Array.from(document.querySelectorAll('.eo-pk-bar [role="tab"]')).map((b) => b.textContent);
    expect(tabs).toEqual(['pip 1', 'npm 0']);
  });

  it('removes a package and offers the Python versions the service builds with', async () => {
    await open('packages');
    const sel = document.querySelector('.eo-rt select') as HTMLSelectElement;
    expect(Array.from(sel.options).map((o) => o.textContent)).toEqual(['Default', '3.11', '3.12']);
    await click(document.querySelector('[aria-label="Remove requests"]') as HTMLButtonElement);
    expect(pkgRows()).toEqual([]);
    await click(button('Save and build'));
    expect(m.updateEnvironment).toHaveBeenCalledWith('henv_1', expect.objectContaining({ packages: { pip: [], npm: [], apt: [] } }));
  });
});

describe('builds', () => {
  it('shows a running build’s stage, its seconds and its log, and reads it again while it runs', async () => {
    jest.useFakeTimers({ doNotFake: ['queueMicrotask', 'nextTick', 'setImmediate'] });
    jest.setSystemTime(1_760_200_012_000);
    env = ENV({ status: 'building', latestVersion: 3, build: { version: 3, status: 'building', started_at: 1_760_200_000 } });
    rec = REC({ version: 3, status: 'building', stage: 'installing pip packages', log: '$ pip install flask\nCollecting flask', finished_at: null, started_at: 1_760_200_000 });
    try {
      await open('builds');
      expect(document.querySelector('.eo-run-head b')?.textContent).toBe('Building version 3');
      expect(document.querySelector('.eo-run-line')?.textContent).toBe('installing pip packages · 12 s');
      expect(document.querySelector('.eo-term')?.textContent).toContain('Collecting flask');
      expect(document.querySelector('.eo-term .cmd')?.textContent).toBe('$ pip install flask\n');
      expect(document.querySelector('.sheet-top .pill')?.textContent).toBe('Building');
      // no switching versions while it runs
      expect(button('Use this version')).toBeUndefined();

      const reads = m.getEnvironment.mock.calls.length;
      rec = REC({ version: 3, status: 'failed', error: 'pip could not find a version of \'flsak\'', log: '$ pip install flsak\nERROR: No matching distribution', finished_at: 1_760_200_030 });
      env = ENV({ status: 'ready', version: 2, latestVersion: 3, build: { version: 3, status: 'failed', started_at: 1_760_200_000, finished_at: 1_760_200_030, error: 'pip could not find a version of \'flsak\'' },
        versions: [...ENV().versions, { version: 3, status: 'failed', started_at: 1_760_200_000, finished_at: 1_760_200_030, error: 'pip could not find a version of \'flsak\'' }] });
      await act(async () => { jest.advanceTimersByTime(3000); });
      await flush();
      expect(m.getEnvironment.mock.calls.length).toBeGreaterThan(reads);
      // the failure, in the build's own reason, and the head says the older version still serves
      expect(document.querySelector('.eo-run-head b')?.textContent).toBe('Version 3 failed');
      expect(document.querySelector('.eo-run-line')?.textContent).toBe('Why it failed: pip could not find a version of \'flsak\'');
      expect(document.querySelector('.eo-sub')?.textContent).toBe('Version 3 failed');
      expect(say).toHaveBeenCalledWith('Version 3 failed. Its log on Builds says why.');
    } finally { jest.useRealTimers(); }
  });

  it('opens an older version’s log from its row', async () => {
    await open('builds');
    expect(document.querySelector('.eo-run-head b')?.textContent).toBe('Version 2 is ready');
    const v1 = Array.from(document.querySelectorAll('.eo-vt .eo-v')).find((r) => r.textContent?.includes('Version 1')) as HTMLElement;
    await click(v1.querySelector('.link-q') as HTMLButtonElement);
    expect(m.getEnvironmentBuild).toHaveBeenCalledWith('henv_1', 1);
    expect(document.querySelector('.eo-term')?.textContent).toContain('log of 1');
    await click(button('Back to the latest'));
    expect(document.querySelector('.eo-run-head b')?.textContent).toBe('Version 2 is ready');
  });
});

describe('versions', () => {
  it('puts an older finished version back in use', async () => {
    m.activateEnvironmentVersion.mockImplementation(async (_id, n) => { env = ENV({ version: n }); return env; });
    await open('builds');
    const rows = Array.from(document.querySelectorAll('.eo-vt .eo-v'));
    expect(rows.map((r) => r.querySelector('.eo-c-ver b')?.textContent)).toEqual(['Version 2', 'Version 1']);
    expect(rows[0].querySelector('.eo-inuse')?.textContent).toBe('In use');
    expect(rows[0].textContent).not.toContain('Use this version');      // the one in use offers no switch

    await click(rows[1].querySelector('.btn') as HTMLButtonElement);
    expect(m.activateEnvironmentVersion).toHaveBeenCalledWith('henv_1', 1);
    expect(say).toHaveBeenCalledWith('Version 1 is in use.');
    const after = Array.from(document.querySelectorAll('.eo-vt .eo-v'));
    expect(after[1].querySelector('.eo-inuse')?.textContent).toBe('In use');
    expect(after[0].textContent).toContain('Use this version');
  });

  it('says plainly when the switch is refused', async () => {
    m.activateEnvironmentVersion.mockRejectedValue(new Error('409'));
    await open('builds');
    await click(button('Use this version'));
    expect(document.querySelector('.eo-state')?.textContent).toBe('Version 1 is not a finished build.');
  });
});

describe('files', () => {
  const pick = (input: HTMLInputElement, paths: string[]) => {
    const files = paths.map((p) => Object.defineProperty(new File(['x'], p.split('/').pop() as string), 'webkitRelativePath', { value: p }));
    Object.defineProperty(input, 'files', { value: files, configurable: true });
    input.dispatchEvent(new Event('change', { bubbles: true }));
  };
  const folderInput = () => document.querySelector('input[webkitdirectory]') as HTMLInputElement;

  it('uploads every file of a folder, .git, node_modules and the rest included', async () => {
    m.writeEnvironmentFile.mockResolvedValue({});
    await open('files');
    expect(document.body.textContent).not.toContain('node_modules');
    await act(async () => { pick(folderInput(), ['proj/run.py', 'proj/node_modules/x/index.js', 'proj/.git/HEAD', 'proj/__pycache__/a.pyc', 'proj/.venv/bin/python']); });
    await flush();
    expect(m.writeEnvironmentFile.mock.calls.map((c) => c[1])).toEqual(['proj/run.py', 'proj/node_modules/x/index.js', 'proj/.git/HEAD', 'proj/__pycache__/a.pyc', 'proj/.venv/bin/python']);
    expect(document.querySelector('.eo-files-pane > .eo-msg')?.textContent).toBe('5 files uploaded. Build to use them.');
  });

  const FILES = [
    { path: 'run.py', dir: false, bytes: 8, mtime: 0 }, { path: 'logo.png', dir: false, bytes: 37000, mtime: 0 },
    { path: 'guide.pdf', dir: false, bytes: 52000, mtime: 0 }, { path: 'model.bin', dir: false, bytes: 900, mtime: 0 },
  ];
  const READS: Record<string, { text: string | null; bytes: number; type: string; blob: Blob | null }> = {
    'run.py': { text: 'print(1)', bytes: 8, type: 'text/x-python', blob: null },
    'logo.png': { text: null, bytes: 37000, type: 'image/png', blob: new Blob(['png'], { type: 'image/png' }) },
    'guide.pdf': { text: null, bytes: 52000, type: 'application/pdf', blob: new Blob(['%PDF'], { type: 'application/pdf' }) },
    'model.bin': { text: null, bytes: 900, type: 'application/octet-stream', blob: new Blob(['x'], { type: 'application/octet-stream' }) },
  };
  const openFile = async (name: string) => click(Array.from(document.querySelectorAll('.eo-item')).find((b) => b.textContent === name) as HTMLButtonElement);
  const code = () => document.querySelector('.eo-code .code-stub') as HTMLTextAreaElement | null;
  let made: Blob[];
  beforeEach(() => {
    made = [];
    m.listEnvironmentFiles.mockResolvedValue({ entries: FILES, count: FILES.length, bytes: 0 });
    m.readEnvironmentFile.mockImplementation(async (_id: string, p: string) => READS[p]);
    let n = 0;
    Object.assign(URL, { createObjectURL: jest.fn((b: Blob) => { made.push(b); return `blob:file/${++n}`; }), revokeObjectURL: jest.fn() });
  });

  it('opens a text file in the code editor, and an edit is held until Save, then written', async () => {
    m.writeEnvironmentFile.mockResolvedValue({});
    await open('files');
    await openFile('run.py');
    expect(document.querySelector('.eo-view-head code')?.textContent).toBe('run.py');
    expect(document.querySelector('.eo-view-head .eo-dim')?.textContent).toBe('8 B');
    expect(code()?.dataset.path).toBe('run.py');
    expect(code()?.getAttribute('aria-label')).toBe('Contents of run.py');
    expect(code()?.value).toBe('print(1)');
    expect(code()?.readOnly).toBe(false);
    const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!;
    await act(async () => { set.call(code(), 'print(2)'); code()?.dispatchEvent(new Event('input', { bubbles: true })); });
    expect(document.querySelector('.eo-view-head .eo-dim')?.textContent).toBe('8 B · edited');
    expect(document.querySelector('.eo-state')?.textContent).toBe('Not saved yet: 1 file edited.');
    await click(button('Save and build'));
    expect(m.writeEnvironmentFile).toHaveBeenCalledWith('henv_1', 'run.py', 'print(2)');
    expect(m.buildEnvironment).toHaveBeenCalledWith('henv_1');
  });

  it('shows an image or a PDF as itself, with its size in the head, and lets the last one go', async () => {
    await open('files');
    await openFile('logo.png');
    expect(code()).toBeNull();
    expect(document.querySelector('.eo-view-head .eo-dim')?.textContent).toBe('37000 B');
    const img = document.querySelector('.eo-show img') as HTMLImageElement;
    expect(img.getAttribute('src')).toBe('blob:file/1');
    expect(img.getAttribute('alt')).toBe('logo.png');
    expect(made[0].type).toBe('image/png');

    await openFile('guide.pdf');
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:file/1');
    const frame = document.querySelector('.eo-show.is-pdf iframe') as HTMLIFrameElement;
    expect(frame.getAttribute('src')).toBe('blob:file/2');
    expect(frame.getAttribute('title')).toBe('guide.pdf');
    expect(made[1].type).toBe('application/pdf');
  });

  it('says a file that is neither text nor a picture, a PDF, a video or a sound has no preview', async () => {
    await open('files');
    await openFile('model.bin');
    expect(code()).toBeNull();
    expect(document.querySelector('.eo-show')).toBeNull();
    expect(document.querySelector('.eo-view .eo-none')?.textContent).toBe('This file is not text, and it has no preview here.');
    expect(document.querySelector('.eo-view-head .eo-dim')?.textContent).toBe('900 B');
  });

  it('says plainly what the service refused, and stops once the environment is full', async () => {
    const tooBig = Object.assign(new Error('A file may be at most 67108864 bytes.'), { status: 413, detail: { max_bytes: 67108864 } });
    const full = Object.assign(new Error('An environment may hold at most 20000 files and directories.'), { status: 413, detail: { max_entries: 20000 } });
    m.writeEnvironmentFile.mockImplementation(async (_id, p) => {
      if (p === 'proj/big.bin') throw tooBig;
      if (p === 'proj/c.py') throw full;
      return {};
    });
    await open('files');
    await act(async () => { pick(folderInput(), ['proj/a.py', 'proj/big.bin', 'proj/b.py', 'proj/c.py', 'proj/d.py', 'proj/e.py']); });
    await flush();
    expect(m.writeEnvironmentFile.mock.calls.map((c) => c[1])).toEqual(['proj/a.py', 'proj/big.bin', 'proj/b.py', 'proj/c.py']);   // nothing after the limit
    const msg = document.querySelector('.eo-files-pane > .eo-msg') as HTMLElement;
    expect(msg.textContent).toBe('2 files uploaded. proj/big.bin is too large to upload. Then the environment held as many files and folders as it can, so the rest were not uploaded.');
    expect(msg.className).toContain('bad');
    expect(msg.textContent).not.toContain('67108864');
  });
});

describe('mediaOf', () => {
  it('shows a file by its own kind, with a type that can only show it, never the one it came with', () => {
    expect(mediaOf('a/logo.png', 'image/png')).toEqual({ kind: 'image', type: 'image/png' });
    expect(mediaOf('logo.png', 'text/html')).toEqual({ kind: 'image', type: 'image/png' });
    expect(mediaOf('photo.JPG', 'application/octet-stream')).toEqual({ kind: 'image', type: 'image/jpeg' });
    expect(mediaOf('guide.pdf', 'text/html; charset=utf-8')).toEqual({ kind: 'pdf', type: 'application/pdf' });
    expect(mediaOf('icon.svg', 'image/svg+xml')).toEqual({ kind: 'svg', type: 'image/svg+xml' });
    expect(mediaOf('icon.png', 'image/svg+xml')).toEqual({ kind: 'svg', type: 'image/svg+xml' });
    expect(mediaOf('clip.mov', '')).toEqual({ kind: 'video', type: 'video/quicktime' });
    expect(mediaOf('clip', 'video/mp4')).toEqual({ kind: 'video', type: 'video/mp4' });
    expect(mediaOf('voice.mp3', 'application/octet-stream')).toEqual({ kind: 'audio', type: 'audio/mpeg' });
  });
  it('has nothing to show for anything else', () => {
    expect(mediaOf('model.bin', 'application/octet-stream')).toBeNull();
    expect(mediaOf('page.html', 'text/html')).toBeNull();
    expect(mediaOf('report.docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')).toBeNull();
    expect(mediaOf('.png', '')).toBeNull();
  });
});

describe('details', () => {
  it('lists the setups that use it, each a link, and asks in the sheet before deleting', async () => {
    const onDelete = jest.fn(async () => true);
    await act(async () => { root.render(<EnvSheet id="henv_1" tab="details" onClose={jest.fn()} onChanged={jest.fn()} onDelete={onDelete} />); });
    await flush();
    const link = document.querySelector('.eo-users a') as HTMLAnchorElement;
    expect(link.textContent).toBe('Docs helper');
    expect(link.getAttribute('href')).toBe('/studio/h1?tab=settings');
    expect(document.querySelector('.set-ro code')?.textContent).toBe('/env/docs-repo');
    await click(button('Delete'));
    expect(document.querySelector('.eo-ask')?.textContent).toContain('Docs helper uses it');
    await click(button('Delete environment'));
    expect(onDelete).toHaveBeenCalledWith(expect.objectContaining({ id: 'henv_1' }), [{ id: 'h1', name: 'Docs helper' }]);
  });
});

describe('the arrow keys', () => {
  const keyOn = async (t: Element, key: string) => {
    (t as HTMLElement).focus();
    await act(async () => { t.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true })); });
    await flush();
  };
  const on = (list: string) => document.querySelector(`[role="tablist"][aria-label="${list}"] [role="tab"][aria-selected="true"]`);
  it('move through the environment’s tabs and the package managers', async () => {
    await open('files');
    expect(on('Environment')?.textContent).toContain('Files');
    await keyOn(on('Environment') as Element, 'ArrowRight');
    expect(on('Environment')?.textContent).toContain('Packages');
    expect(document.activeElement?.textContent).toContain('Packages');
    expect(on('Package manager')?.textContent).toContain('pip');
    await keyOn(on('Package manager') as Element, 'ArrowRight');
    expect(on('Package manager')?.textContent).toContain('npm');
    expect(document.querySelector('label[for="eoSpec"]')?.textContent).toBe('Add a npm package');
  });
});
