// The environment sheet's rules (ext/envModel): a package's spec as the service splits and keeps it,
// Add's check against the registry exactly as the old environment page ran it, what a package row says,
// the state a head and a row show, which versions can be switched to, and the plain words a failure
// becomes.
import type { Environment, EnvironmentVersion, PackageCheck } from '@/lib/environments';
import {
  specParts, specProblem, planAdd, pkgRow, statusView, versionRows, took, dur, gitUrl, folderFiles, statusOf, sayFail, treeOf, MAX_PER_MANAGER,
  limitOf, uploadSummary, TOO_MANY, TOO_BIG,
} from './envModel';

const check = (over: Partial<PackageCheck>): PackageCheck => ({ manager: 'pip', name: 'flask', spec: 'flask', exists: true, latest: '3.0.3', version: '', error: '', ...over });

describe('a package spec', () => {
  it('splits the way the service splits it', () => {
    expect(specParts('requests==2.31.0', 'pip')).toEqual({ name: 'requests', version: '2.31.0' });
    expect(specParts('numpy>=1.26', 'pip')).toEqual({ name: 'numpy', version: '>=1.26' });
    expect(specParts('flask', 'pip')).toEqual({ name: 'flask', version: '' });
    expect(specParts('@scope/pkg@1.2.3', 'npm')).toEqual({ name: '@scope/pkg', version: '1.2.3' });
    expect(specParts('@scope/pkg', 'npm')).toEqual({ name: '@scope/pkg', version: '' });
    expect(specParts('ffmpeg', 'apt')).toEqual({ name: 'ffmpeg', version: '' });
  });
  it('is refused where it is typed when the service would not keep it', () => {
    expect(specProblem('', 'pip', [])).toBe('Type a package name.');
    expect(specProblem('requests >= 2', 'pip', [])).toBe('Write it as name==1.0, or just the name for the latest.');
    expect(specProblem('-rf', 'npm', [])).toBe('Write it as name@1.0, or just the name for the latest.');
    expect(specProblem('ffmpeg;rm', 'apt', [])).toBe('Write it as name.');
    expect(specProblem('requests==2.31', 'pip', [])).toBe('');
    // an apt version with its epoch, as the package check recommends it
    expect(specProblem('ffmpeg=7:4.4.2-0ubuntu0.22.04.1', 'apt', [])).toBe('');
    expect(specParts('ffmpeg=7:4.4.2-0ubuntu0.22.04.1', 'apt')).toEqual({ name: 'ffmpeg', version: '7:4.4.2-0ubuntu0.22.04.1' });
    expect(specProblem('ffmpeg=1:2:3', 'apt', [])).toBe('Write it as name.');
    expect(specProblem('sharp@^0.33', 'npm', [])).toBe('');
  });
  it('stops at the most the service keeps, but a name already there can still change its pin', () => {
    const full = Array.from({ length: MAX_PER_MANAGER }, (_, i) => `p${i}`);
    expect(specProblem('another', 'pip', full)).toBe(`An environment holds at most ${MAX_PER_MANAGER} pip packages.`);
    expect(specProblem('p3==1.0', 'pip', full)).toBe('');
  });
});

describe('Add, once the registry answered', () => {
  it('refuses a name the registry does not have, with its own words', () => {
    expect(planAdd([], 'pip', 'flsak', check({ name: 'flsak', exists: false, error: 'flsak was not found on PyPI' }))).toEqual({ ok: false, error: 'flsak was not found on PyPI' });
    expect(planAdd([], 'pip', 'flsak', check({ name: 'flsak', exists: false, error: '' }))).toEqual({ ok: false, error: 'flsak was not found.' });
  });
  it('refuses a pin that was never published', () => {
    const p = planAdd([], 'pip', 'flask==9.9', check({ exists: true, error: 'flask 9.9 was never published' }));
    expect(p).toEqual({ ok: false, error: 'flask 9.9 was never published' });
  });
  it('adds it with the version the registry reported, the pin first', () => {
    expect(planAdd(['requests'], 'pip', 'flask', check({}))).toEqual({ ok: true, next: ['requests', 'flask'], key: 'pip:flask', version: '3.0.3', note: '' });
    const pinned = planAdd([], 'pip', 'flask==3.0.0', check({ version: '3.0.0' }));
    expect(pinned.ok && pinned.version).toBe('3.0.0');
  });
  it('adds it anyway when the registry could not be asked, and says the build will check it', () => {
    const p = planAdd([], 'npm', 'sharp', check({ manager: 'npm', name: 'sharp', exists: null, latest: '', error: 'The registry did not answer.' }));
    expect(p).toEqual({ ok: true, next: ['sharp'], key: 'npm:sharp', version: '', note: 'The registry did not answer. It was added; the build will check it.' });
  });
  it('replaces the same name rather than adding it twice', () => {
    const p = planAdd(['Flask==2.0', 'requests'], 'pip', 'flask==3.0.3', check({ version: '3.0.3' }));
    expect(p.ok && p.next).toEqual(['requests', 'flask==3.0.3']);
  });
});

describe('a package row', () => {
  const env = (over: Partial<Environment> = {}) => ({ status: 'ready', packages: [{ manager: 'pip', name: 'requests', version: '2.31.0' }], ...over }) as Pick<Environment, 'packages' | 'status'>;
  it('shows the version the active build installed', () => {
    expect(pkgRow(env(), 'pip', 'requests', {}, true)).toEqual({ name: 'requests', text: '2.31.0', note: '' });
    expect(pkgRow(env(), 'pip', 'requests>=2', {}, true)).toEqual({ name: 'requests', text: '2.31.0', note: '' });
  });
  it('says when a package is not installed yet, with the version the registry reported', () => {
    expect(pkgRow(env(), 'pip', 'flask', { 'pip:flask': '3.0.3' }, false)).toEqual({ name: 'flask', text: '3.0.3', note: 'installs when you save and build' });
    expect(pkgRow(env(), 'pip', 'flask', {}, true)).toEqual({ name: 'flask', text: 'latest', note: 'installs on the next build' });
    expect(pkgRow(env({ status: 'building' }), 'pip', 'flask==3.0.0', {}, true)).toEqual({ name: 'flask', text: '3.0.0', note: 'installing' });
    // a new pin over an installed version is not installed yet
    expect(pkgRow(env(), 'pip', 'requests==2.32.0', {}, true)).toEqual({ name: 'requests', text: '2.32.0', note: 'installs on the next build' });
  });
});

describe('the state an environment shows', () => {
  const b = (version: number, status: EnvironmentVersion['status']) => ({ version, status }) as EnvironmentVersion;
  it('reads the service status, the version in use and the latest build', () => {
    expect(statusView({ status: 'empty', version: null, build: null })).toEqual({ tone: 'neutral', label: 'Not built yet', note: '' });
    expect(statusView({ status: 'building', version: null, build: b(1, 'building') })).toEqual({ tone: 'run', label: 'Building', note: '' });
    expect(statusView({ status: 'building', version: 1, build: b(2, 'building') }).note).toBe('');
    expect(statusView({ status: 'ready', version: 2, build: b(2, 'ready') })).toEqual({ tone: 'ok', label: 'Ready', note: '' });
    // only what the state hides is said: a newer build failed while an older version serves
    expect(statusView({ status: 'ready', version: 1, build: b(2, 'failed') }).note).toBe('Version 2 failed');
    expect(statusView({ status: 'failed', version: null, build: b(1, 'failed') })).toEqual({ tone: 'bad', label: 'Build failed', note: '' });
  });
});

describe('versions', () => {
  const v = (version: number, status: EnvironmentVersion['status']) => ({ version, status, started_at: 1000 * version, finished_at: 1000 * version + 42 }) as EnvironmentVersion;
  it('lists newest first, marks the one in use, and offers a switch only to another finished build', () => {
    const rows = versionRows({ status: 'ready', version: 2, versions: [v(1, 'ready'), v(3, 'failed'), v(2, 'ready')] });
    expect(rows.map((r) => [r.version, r.active, r.canUse])).toEqual([[3, false, false], [2, true, false], [1, false, true]]);
  });
  it('offers no switch while a build runs: its version takes over when it finishes', () => {
    const rows = versionRows({ status: 'building', version: 2, versions: [v(1, 'ready'), v(2, 'ready'), v(3, 'building')] });
    expect(rows.some((r) => r.canUse)).toBe(false);
  });
  it('says how long a build took only from the two timestamps the service gave', () => {
    expect(took(1000, 1042)).toBe('42 s');
    expect(took(1000, null)).toBe('');
    expect(dur(192)).toBe('3 min 12 s');
    expect(dur(3600 + 120)).toBe('1 h 2 min');
  });
});

describe('the rest', () => {
  it('knows a git address', () => {
    expect(gitUrl('https://github.com/acme/docs')).toBe('https://github.com/acme/docs');
    expect(gitUrl('git@github.com:acme/docs.git')).toBe('git@github.com:acme/docs.git');
    expect(gitUrl('github.com/acme/docs')).toBe('https://github.com/acme/docs');
    expect(gitUrl('docs folder')).toBeNull();
  });
  it('takes a picked folder as the project, every file in it (Richard, 10-19: "Upload everything")', () => {
    const f = (p: string) => Object.assign(new File(['x'], p.split('/').pop() as string), { webkitRelativePath: p });
    const picked = [f('proj/run.py'), f('proj/src/a.py'), f('proj/node_modules/x/index.js'), f('proj/.git/HEAD'), f('proj/.DS_Store'), f('proj/src/__pycache__/a.pyc'), f('proj/.venv/bin/python')];
    expect(folderFiles(picked, true).map((x) => x.path)).toEqual(['run.py', 'src/a.py', 'node_modules/x/index.js', '.git/HEAD', '.DS_Store', 'src/__pycache__/a.pyc', '.venv/bin/python']);
    expect(folderFiles(picked, false).map((x) => x.path)).toEqual(picked.map((x) => (x as File & { webkitRelativePath: string }).webkitRelativePath));
    expect(folderFiles([new File(['x'], 'loose.txt')], false).map((x) => x.path)).toEqual(['loose.txt']);
  });
  it('tells the service’s two limits apart, and says each plainly', () => {
    const e = (status: number, detail: unknown = null) => Object.assign(new Error('An environment may hold at most 20000 files and directories.'), { status, detail });
    expect(limitOf(e(413, { max_entries: 20000 }))).toBe('entries');
    expect(limitOf(e(413, { max_bytes: 67108864 }))).toBe('size');
    expect(limitOf(e(409))).toBe('');
    expect(sayFail(e(413, { max_entries: 20000 }), 'It failed.')).toBe(TOO_MANY);
    expect(sayFail(e(413, { max_bytes: 1 }), 'It failed.')).toBe(TOO_BIG);
  });
  it('sums up an upload of many files in plain words', () => {
    expect(uploadSummary(40, [], false)).toBe('40 files uploaded.');
    expect(uploadSummary(1, [{ path: 'big.bin', tooBig: true }], false)).toBe('1 file uploaded. big.bin is too large to upload.');
    expect(uploadSummary(5, [{ path: 'a', tooBig: true }, { path: 'b', tooBig: true }, { path: 'c', tooBig: true }, { path: 'd', tooBig: false }], false))
      .toBe('5 files uploaded. 3 files are too large to upload (a, b and more). d could not be uploaded.');
    expect(uploadSummary(19990, [], true)).toBe('19990 files uploaded. Then the environment held as many files and folders as it can, so the rest were not uploaded.');
  });
  it('turns a failure into plain words, never the server’s text', () => {
    const e = (status: number, message = 'internal detail') => Object.assign(new Error(message), { status });
    expect(statusOf(new Error('409'))).toBe(409);
    expect(statusOf(e(422))).toBe(422);
    expect(statusOf(new Error('boom'))).toBe(0);
    expect(sayFail(e(409), 'It failed.', { 409: 'A build is already running.' })).toBe('A build is already running.');
    expect(sayFail(e(503), 'It failed.')).toBe('We are busy right now. Try again in a minute.');
    expect(sayFail(e(429), 'It failed.')).toBe('Too much is running at once. Try again when something finishes.');
    expect(sayFail(e(402), 'It failed.')).toBe('It failed. Try again.');
    expect(sayFail(e(500, 'The runner failed: HTTP 500.'), 'The build could not start.')).toBe('The build could not start. Try again.');
  });
  it('draws the files as a tree, folders first, each counting its files', () => {
    const t = treeOf([{ path: 'b.py', dir: false, bytes: 1, mtime: 0 }, { path: 'src/x.py', dir: false, bytes: 1, mtime: 0 }, { path: 'src/y/z.py', dir: false, bytes: 1, mtime: 0 }]);
    expect(t.map((n) => [n.name, n.dir, n.count])).toEqual([['src', true, 2], ['b.py', false, 1]]);
  });
});
