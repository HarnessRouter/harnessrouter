/** @jest-environment jsdom */
// "Download all" under a reply's file cards (Richard, 10-18: the old workbench had it, the redesigned
// chat lost it once a reply made several files). Two or more files the server holds get one quiet
// action that saves them as one zip, through the harness proxy with the sign-in; one file, or a
// recorded replay's files (their own /demos url), get none. A refused zip is a toast in plain words,
// the server's own sentence when it is too large.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const harnessFetch = jest.fn();
const toast = jest.fn();
jest.mock('react-markdown', () => ({ __esModule: true, default: () => null }));
jest.mock('remark-gfm', () => ({ __esModule: true, default: () => null }));
jest.mock('rehype-sanitize', () => ({ __esModule: true, default: () => null }));
jest.mock('reifyui/agent-chat', () => ({
  FileCard: ({ name }: { name: string }) => <div className="uic-filecard">{name}</div>,
  ArtifactPanel: () => null,
}));
jest.mock('@/lib/chat', () => ({
  authHeaders: () => ({ 'x-harness-org': 'org_1' }),
  containerFileUrl: (f: { container_id: string; file_id: string; url?: string }) => f.url || `/api/harness/v1/containers/${f.container_id}/files/${f.file_id}/content`,
  downloadFile: jest.fn(() => Promise.resolve()),
  fetchFileBlob: jest.fn(() => Promise.reject(new Error('no thumbs here'))),
}));
jest.mock('@/lib/hfetch', () => ({ harnessFetch: (...a: unknown[]) => harnessFetch(...a) }));
jest.mock('@/lib/conversation', () => ({ isInternalOutput: (n?: string) => n === 'AGENTS.md' }));
jest.mock('../toast', () => ({ toast: (m: string) => toast(m) }));

import { archiveOf, FileCards, plainSentence, zipFileName } from './TurnFiles';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const file = (n: number, extra: Record<string, string> = {}) => ({ container_id: 'hsess_1', file_id: `cfile_${n}`, filename: `cand${n}.jpg`, ...extra });

let root: Root;
let el: HTMLElement;
beforeEach(() => {
  harnessFetch.mockReset();
  toast.mockReset();
  el = document.createElement('div');
  document.body.appendChild(el);
  root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); el.remove(); });

const zipButton = () => Array.from(el.querySelectorAll('button')).find((b) => /Download all/.test(b.textContent || '')) || null;
const draw = (files: ReturnType<typeof file>[], zipName?: string) => act(() => {
  root.render(<FileCards files={files} onOpen={() => {}} zipName={zipName} />);
});

test('two or more files get one Download all, a single file gets none', () => {
  draw([file(1)]);
  expect(el.querySelectorAll('.uic-filecard')).toHaveLength(1);
  expect(zipButton()).toBeNull();
  draw([file(3), file(2), file(1)]);
  expect(el.querySelectorAll('.uic-filecard')).toHaveLength(3);
  expect(zipButton()?.textContent).toBe('Download all (3)');
});

test('the internal instruction file is not counted, so one real file still gets none', () => {
  draw([file(1), { container_id: 'hsess_1', file_id: 'cfile_9', filename: 'AGENTS.md' }]);
  expect(zipButton()).toBeNull();
});

test("the archive asks for exactly that reply's file ids through the harness proxy", () => {
  expect(archiveOf([file(1), file(2)])).toEqual({
    url: '/api/harness/v1/sessions/hsess_1/files/archive?files=cfile_1%2Ccfile_2', count: 2,
  });
  expect(archiveOf([file(1), { ...file(2), container_id: 'hsess_2' }])).toBeNull();
});

test('the zip is named after the task, cleaned of what file systems refuse', () => {
  expect(zipFileName('Find 3 photos: cats/dogs?')).toBe('Find 3 photos cats dogs files.zip');
  expect(zipFileName('..hidden. ')).toBe('hidden files.zip');
  expect(zipFileName('')).toBe('Task files.zip');
  expect(zipFileName('x'.repeat(200))).toBe(`${'x'.repeat(80)} files.zip`);
});

test("the server's sentence for a zip too large reads in plain words, no dashes", () => {
  expect(plainSentence('workspace too large for one archive — download files individually'))
    .toBe('Workspace too large for one archive. Download files individually.');
});

test('a zip too large is a toast with the server sentence, and the action comes back', async () => {
  harnessFetch.mockResolvedValue({ ok: false, status: 413, json: async () => ({ detail: 'workspace too large for one archive — download files individually' }) });
  draw([file(1), file(2)], 'Cats');
  await act(async () => { zipButton()?.click(); });
  expect(harnessFetch).toHaveBeenCalledWith('/api/harness/v1/sessions/hsess_1/files/archive?files=cfile_1%2Ccfile_2',
    expect.objectContaining({ headers: { 'x-harness-org': 'org_1' } }));
  expect(toast).toHaveBeenCalledWith('Workspace too large for one archive. Download files individually.');
  expect(zipButton()?.textContent).toBe('Download all (2)');
});

test('while the zip is prepared the action says so, then it saves as "<task> files.zip"', async () => {
  let answer: (v: unknown) => void = () => {};
  harnessFetch.mockReturnValue(new Promise((res) => { answer = res; }));
  const saved: string[] = [];
  Object.assign(URL, { createObjectURL: () => 'blob:zip', revokeObjectURL: () => {} });
  const click = jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) { saved.push(this.download); });
  draw([file(1), file(2)], 'Cats: best of');
  await act(async () => { zipButton()?.click(); });
  const busy = el.querySelector('button[aria-busy="true"]');
  expect(busy?.textContent).toBe('Preparing the zip…');
  await act(async () => { answer({ ok: true, status: 200, blob: async () => new Blob(['zip']) }); });
  expect(saved).toEqual(['Cats best of files.zip']);
  expect(toast).not.toHaveBeenCalled();
  expect(el.querySelector('button[aria-busy="true"]')).toBeNull();
  click.mockRestore();
});
