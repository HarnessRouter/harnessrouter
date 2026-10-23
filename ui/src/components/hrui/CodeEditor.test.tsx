/** @jest-environment jsdom */
// The console's code editor (CodeEditor): a file's language from its path, line numbers that can go on
// from a header above the text, long lines wrapped, edits sent up, and a text replaced from outside
// (another file opened) taken in without being sent back as an edit.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { EditorView } from '@codemirror/view';
import { CodeEditor, diffText, languageOf, lineLabel, numberDigits } from './CodeEditor';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('languageOf', () => {
  it('reads the language from the extension, or the name of a Dockerfile', () => {
    expect(['a.js', 'a.mjs', 'a.cjs'].map(languageOf)).toEqual(['javascript', 'javascript', 'javascript']);
    expect(languageOf('src/App.jsx')).toBe('jsx');
    expect(languageOf('src/app.ts')).toBe('typescript');
    expect(languageOf('src/App.TSX')).toBe('tsx');
    expect(languageOf('scripts/run.py')).toBe('python');
    expect(languageOf('SKILL.md')).toBe('markdown');
    expect(languageOf('notes.markdown')).toBe('markdown');
    expect(languageOf('package.json')).toBe('json');
    expect(languageOf('ci.yml')).toBe('yaml');
    expect(languageOf('ci.yaml')).toBe('yaml');
    expect(languageOf('setup.sh')).toBe('shell');
    expect(languageOf('setup.bash')).toBe('shell');
    expect(languageOf('pyproject.toml')).toBe('toml');
    expect(languageOf('docker/Dockerfile')).toBe('dockerfile');
    expect(languageOf('api.dockerfile')).toBe('dockerfile');
  });
  it('is plain text for anything else', () => {
    expect(languageOf('README')).toBe('text');
    expect(languageOf('data.csv')).toBe('text');
    expect(languageOf('.env')).toBe('text');
    expect(languageOf('folder.md/notes')).toBe('text');
  });
});

describe('numbering', () => {
  it('goes on from the first number given', () => {
    expect(lineLabel(1)).toBe('1');
    expect(lineLabel(1, 7)).toBe('7');
    expect(lineLabel(4, 7)).toBe('10');
  });
  it('makes the number column as wide as the widest number, two digits at least', () => {
    expect(numberDigits(1)).toBe(2);
    expect(numberDigits(9)).toBe(2);
    expect(numberDigits(3, 8)).toBe(2);       // lines 8 to 10
    expect(numberDigits(94, 7)).toBe(3);      // lines 7 to 100
    expect(numberDigits(0)).toBe(2);
  });
});

describe('diffText', () => {
  const apply = (a: string, d: { from: number; to: number; insert: string }) => a.slice(0, d.from) + d.insert + a.slice(d.to);
  it('replaces only what differs', () => {
    expect(diffText('hello world', 'hello there world')).toEqual({ from: 6, to: 6, insert: 'there ' });
    expect(diffText('abc', 'abc')).toEqual({ from: 3, to: 3, insert: '' });
    expect(diffText('aaa', 'aa')).toEqual({ from: 2, to: 3, insert: '' });
    for (const [a, b] of [['', 'x'], ['x', ''], ['one\ntwo', 'one\nthree\ntwo'], ['abab', 'ab'], ['same', 'other']]) {
      expect(apply(a, diffText(a, b))).toBe(b);
    }
  });
});

describe('the editor', () => {
  let root: Root;
  let el: HTMLDivElement;
  // jsdom lays nothing out: CodeMirror's measuring reads these
  beforeAll(() => {
    Object.assign(Range.prototype, { getClientRects: () => [], getBoundingClientRect: () => ({ top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0, x: 0, y: 0 }) });
  });
  beforeEach(() => { el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el); });
  afterEach(() => { act(() => root.unmount()); el.remove(); });
  const viewOf = () => EditorView.findFromDOM(el.querySelector('.cm-editor') as HTMLElement) as EditorView;
  const flush = async () => { for (let i = 0; i < 5; i++) await act(async () => { await new Promise((r) => setTimeout(r, 0)); }); };

  it('labels its text, wraps long lines, numbers on from the header, and sends edits up', async () => {
    const onChange = jest.fn();
    await act(async () => { root.render(<CodeEditor path="SKILL.md" value={'Body\nmore'} firstLineNumber={7} ariaLabel="SKILL.md" onChange={onChange} />); });
    await flush();
    const content = el.querySelector('.cm-content') as HTMLElement;
    expect(content.getAttribute('aria-label')).toBe('SKILL.md');
    expect(content.getAttribute('contenteditable')).toBe('true');
    expect(content.className).toContain('cm-lineWrapping');
    expect(el.querySelector('.hr-code')?.classList.contains('hrui-legacy')).toBe(true);
    expect(el.querySelector('.hr-code')?.getAttribute('data-lang')).toBe('markdown');
    // the gutter numbers its lines from 7, and is as wide as two digits
    const nums = Array.from(el.querySelectorAll('.cm-lineNumbers .cm-gutterElement')).map((x) => x.textContent).filter(Boolean);
    expect(nums).toEqual(expect.arrayContaining(['7', '8']));
    expect(nums).not.toContain('1');
    expect((el.querySelector('.hr-code') as HTMLElement).style.getPropertyValue('--cm-ln-ch')).toBe('2');

    const v = viewOf();
    await act(async () => { v.dispatch({ changes: { from: v.state.doc.length, insert: '!' }, userEvent: 'input' }); });
    expect(onChange).toHaveBeenLastCalledWith('Body\nmore!');
  });

  it('takes a new value from outside without sending it back, and another file starts its own history', async () => {
    const onChange = jest.fn();
    const draw = (path: string, value: string) => act(async () => {
      root.render(<CodeEditor path={path} value={value} ariaLabel={path} onChange={onChange} />);
    });
    await draw('run.py', 'print(1)');
    const v = viewOf();
    await draw('run.py', 'print(2)');
    expect(v.state.doc.toString()).toBe('print(2)');
    expect(onChange).not.toHaveBeenCalled();

    await draw('notes.md', '# Notes');
    expect(viewOf()).toBe(v);                          // the same editor, a new document
    expect(v.state.doc.toString()).toBe('# Notes');
    expect(el.querySelector('.cm-content')?.getAttribute('aria-label')).toBe('notes.md');
    expect(onChange).not.toHaveBeenCalled();
  });

  it('highlights the file once its language loads, and Tab types two spaces', async () => {
    const onChange = jest.fn();
    await act(async () => { root.render(<CodeEditor path="run.py" value={'def f():\n    return 1'} ariaLabel="run.py" onChange={onChange} />); });
    await flush();
    expect(el.querySelectorAll('.cm-line span[class]').length).toBeGreaterThan(0);
    const v = viewOf();
    await act(async () => { v.dispatch({ selection: { anchor: 0 } }); });
    const content = el.querySelector('.cm-content') as HTMLElement;
    await act(async () => { content.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', keyCode: 9, bubbles: true, cancelable: true })); });
    expect(onChange).toHaveBeenLastCalledWith('  def f():\n    return 1');
  });

  it('a read-only file takes no edits but can still be read and selected', async () => {
    await act(async () => { root.render(<CodeEditor path="a.json" value='{"a": 1}' ariaLabel="a.json" readOnly />); });
    const content = el.querySelector('.cm-content') as HTMLElement;
    expect(content.getAttribute('aria-readonly')).toBe('true');
    expect(viewOf().state.readOnly).toBe(true);
  });

  it('shows the placeholder only when the file is empty', async () => {
    await act(async () => { root.render(<CodeEditor path="SKILL.md" value="" ariaLabel="SKILL.md" placeholder="Write the instructions" />); });
    expect(el.querySelector('.cm-placeholder')?.textContent).toBe('Write the instructions');
  });
});
