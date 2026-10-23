/** @jest-environment jsdom */
// A skill's files from an upload or a drop (skills/SkillEditor). A file or folder that cannot be read
// is read again, then named; an upload that could not be read whole adds nothing (the skill is never
// saved half read), and Try again reads the same upload again. The open file is the console's code
// editor (CodeEditor, tested on its own), drawn here as a plain field: SKILL.md's body numbered on from
// its header, every other file from 1, a file that is not text never put in it.
import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';

// the shared reader, as text (jsdom's File reads through FileReader)
jest.mock('@/components/HarnessEditors', () => ({
  readSkillUpload: (file: File, path: string) => new Promise((res) => { const fr = new FileReader(); fr.onload = () => res({ path, content: String(fr.result) }); fr.readAsText(file); }),
}));
jest.mock('../toast', () => ({ toast: jest.fn() }));
// CodeMirror needs a laid-out page: the editor is stood in for by a field that shows what it was given
jest.mock('../CodeEditor', () => ({
  CodeEditor: (p: { value: string; onChange?: (v: string) => void; path: string; firstLineNumber?: number; ariaLabel: string; placeholder?: string }) => (
    <textarea className="code-stub" aria-label={p.ariaLabel} data-path={p.path} data-first={p.firstLineNumber ?? 1}
      placeholder={p.placeholder} value={p.value} onChange={(e) => p.onChange?.(e.target.value)} />
  ),
}));

import { READ_RETRY_MS, SkillEditor, unreadLine, walk } from './SkillEditor';
import type { SkillDraft } from './skillMd';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

/** A file whose bytes read as `text`, or fail to read the first `fails` times. */
function file(name: string, text: string, fails = 0): File {
  const f = new File([text], name, { type: 'text/plain' });
  let left = fails;
  Object.defineProperty(f, 'arrayBuffer', { value: async () => {
    if (left > 0) { left -= 1; throw new DOMException('The file could not be read.', 'NotReadableError'); }
    return Uint8Array.from(Buffer.from(text)).buffer;
  } });
  return f;
}
const fileEntry = (name: string, f: File | null, fails = 0) => {
  let left = fails;
  return { name, isFile: true, isDirectory: false,
    file: (ok: (x: File) => void, bad: (e: Error) => void) => { if (!f || left > 0) { left -= 1; bad(new Error('NotFoundError')); } else ok(f); } } as unknown as FileSystemEntry;
};
const dirEntry = (name: string, kids: FileSystemEntry[] | null) => ({ name, isFile: false, isDirectory: true,
  createReader: () => { let done = false; return { readEntries: (ok: (x: FileSystemEntry[]) => void, bad: (e: Error) => void) => {
    if (!kids) { bad(new Error('NotReadableError')); return; }
    ok(done ? [] : kids); done = true;
  } }; } }) as unknown as FileSystemEntry;
const WAITS = READ_RETRY_MS.reduce((a, b) => a + b, 0);

describe('walk', () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());
  it('reads a dropped folder all the way down, and names what it could not read, a folder with a slash', async () => {
    const out: { file: File; rel: string }[] = [];
    const lost: string[] = [];
    const tree = dirEntry('report', [
      fileEntry('SKILL.md', file('SKILL.md', 'Hi')),
      fileEntry('flaky.md', file('flaky.md', 'ok'), 1),          // fails once, then reads
      fileEntry('gone.md', null),
      dirEntry('locked', null),
    ]);
    const p = walk(tree, '', out, lost);
    await jest.advanceTimersByTimeAsync(WAITS * 3);
    await p;
    expect(out.map((x) => x.rel)).toEqual(['report/SKILL.md', 'report/flaky.md']);
    expect(lost).toEqual(['report/gone.md', 'report/locked/']);
  });
});

describe('unreadLine', () => {
  it('says how many and which', () => {
    expect(unreadLine(['a.md'])).toBe('a.md could not be read.');
    expect(unreadLine(['a.md', 'b.py'])).toBe('2 files could not be read: a.md and b.py.');
    expect(unreadLine(['refs/'])).toBe('refs/ could not be read.');
    expect(unreadLine(['a', 'b', 'c', 'd', 'e', 'refs/'])).toBe('6 files and folders could not be read: a, b, c, d and 2 more.');
  });
});

describe('the editor', () => {
  let root: Root;
  let el: HTMLElement;
  let draft: SkillDraft;
  const START: SkillDraft = { id: null, name: 'report', desc: 'Reports.', rest: [], files: [{ path: 'SKILL.md', content: 'Body' }], cur: 0 };
  function Host({ start = START, setup }: { start?: SkillDraft; setup?: string }) {
    const [ed, setEd] = useState<SkillDraft>(start);
    draft = ed;
    return <SkillEditor ed={ed} setEd={setEd} busy={false} onSave={() => {}} onClose={() => {}} setup={setup} />;
  }
  const code = () => document.querySelector('.code-stub') as HTMLTextAreaElement | null;
  async function typeCode(value: string) {
    const ta = code() as HTMLTextAreaElement;
    const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!;
    await act(async () => { set.call(ta, value); ta.dispatchEvent(new Event('input', { bubbles: true })); });
  }
  const tree = () => Array.from(document.querySelectorAll('.ske-tree .fn')).map((x) => x.textContent);
  async function upload(files: File[]) {
    const input = document.querySelector('input[type="file"][multiple]') as HTMLInputElement;
    Object.defineProperty(input, 'files', { value: files, configurable: true });
    await act(async () => { input.dispatchEvent(new Event('change', { bubbles: true })); });
  }
  const passTime = (ms: number) => act(async () => { await jest.advanceTimersByTimeAsync(ms); });
  /** the reads of an upload done (jsdom reads each file in a few ticks) */
  const settle = async () => { for (let i = 0; i < 6; i++) await passTime(20); };

  beforeEach(() => {
    jest.useFakeTimers();
    el = document.createElement('div'); document.body.appendChild(el);
    root = createRoot(el);
  });
  afterEach(() => { act(() => root.unmount()); el.remove(); document.body.innerHTML = ''; jest.useRealTimers(); });

  it('edits SKILL.md in the code editor, its lines numbered on from the header, which wraps above it', async () => {
    await act(async () => { root.render(<Host />); });
    await settle();
    const head = Array.from(document.querySelectorAll('.ske-head .ske-ht')).map((x) => x.textContent);
    expect(head).toEqual(['---', 'name: report', 'description: "Reports."', '---', '\u00a0']);
    expect(code()?.dataset.path).toBe('SKILL.md');
    expect(code()?.dataset.first).toBe('6');                    // the header's five lines, then the body
    expect(code()?.value).toBe('Body');
    expect(code()?.placeholder).toBe('Summarize my recent work in three sections: wins, blockers, next steps.');
    // the number column is as wide as the widest number, shared by the header and the editor
    expect((document.querySelector('.ske-code') as HTMLElement).style.getPropertyValue('--cm-ln-ch')).toBe('2');
    // no hidden copy of the text and no plain field of its own: one editor
    expect(document.querySelector('.ske-mir')).toBeNull();
    expect(document.querySelectorAll('.ske-pane textarea')).toHaveLength(1);
    await typeCode('Body\nmore');
    expect(draft.files[0]).toEqual({ path: 'SKILL.md', content: 'Body\nmore' });
    expect(draft.desc).toBe('Reports.');
  });

  it('opens another file from 1 with no header, and keeps a file that is not text out of the editor', async () => {
    const start: SkillDraft = { ...START, files: [{ path: 'SKILL.md', content: 'Body' }, { path: 'scripts/run.py', content: 'print(1)' }, { path: 'logo.png', content_b64: 'iVBORw0K' }] };
    await act(async () => { root.render(<Host start={start} />); });
    await settle();
    const open = (name: string) => act(async () => {
      (Array.from(document.querySelectorAll('.ske-item')).find((b) => b.textContent === name) as HTMLButtonElement).click();
    });
    await open('run.py');
    await settle();
    expect(document.querySelector('.ske-head')).toBeNull();
    expect(code()?.dataset.path).toBe('scripts/run.py');
    expect(code()?.dataset.first).toBe('1');
    expect(code()?.placeholder).toBe('');
    await typeCode('print(2)');
    expect(draft.files[1]).toEqual({ path: 'scripts/run.py', content: 'print(2)' });
    expect(draft.files[0].content).toBe('Body');
    await open('logo.png');
    expect(code()).toBeNull();
    expect(document.querySelector('.ske-bin p')?.textContent).toBe('This file is not text, so it is kept as it is.');
  });

  it('names no setup in the foot, even when editing one in a setup', async () => {
    await act(async () => { root.render(<Host start={{ ...START, id: 'sk_1' }} setup="Docs helper" />); });
    await settle();
    expect(document.querySelector('.sk-state')).toBeNull();
    expect(document.querySelector('.sk-foot')?.textContent).not.toContain('Docs helper');
    expect(Array.from(document.querySelectorAll('.sk-foot button')).map((b) => b.textContent)).toEqual(['Cancel', 'Save']);
  });

  it('adds files that read, as before', async () => {
    await act(async () => { root.render(<Host />); });
    await upload([file('notes.md', 'one'), file('run.py', 'print(1)')]);
    await settle();
    expect(draft.files.map((f) => f.path)).toEqual(['SKILL.md', 'notes.md', 'run.py']);
    expect(document.querySelector('.ske-unread')).toBeNull();
  });

  it('a file that cannot be read: named, nothing from the upload added; Try again adds it whole', async () => {
    await act(async () => { root.render(<Host />); });
    const bad = file('data.csv', 'a,b', READ_RETRY_MS.length + 1);  // fails every try of this upload, then reads
    await upload([file('notes.md', 'one'), bad]);
    await passTime(WAITS);
    const line = document.querySelector('.ske-unread');
    expect(line?.getAttribute('role')).toBe('alert');
    expect(line?.textContent).toBe('data.csv could not be read. Nothing from that upload was added. Try again');
    expect(draft.files.map((f) => f.path)).toEqual(['SKILL.md']);
    expect(tree()).not.toContain('notes.md');
    await act(async () => { (line?.querySelector('button') as HTMLButtonElement).click(); });
    await settle();
    expect(document.querySelector('.ske-unread')).toBeNull();
    expect(draft.files.map((f) => f.path)).toEqual(['SKILL.md', 'notes.md', 'data.csv']);
    expect(draft.files[2].content).toBe('a,b');
  });
});
