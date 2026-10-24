'use client';
// The console's code editor (Richard, 10-21: the environment's file preview and a skill's files are
// edited in a real code editor, with the code highlighted). CodeMirror 6, used directly: line
// numbers, highlighting by the file's kind, undo and redo, Tab as two spaces, and no completion
// popups. Long lines always wrap (Richard, twice: the skill editor never scrolls sideways): a
// wrapped line keeps one number, beside its first row. The editor is as tall as its lines, so the
// page around it is the one scroll, never a scroll inside a scroll.
//
// The editor sits in a `hrui-legacy` box: #hrui's reset (`all:revert` on everything inside it)
// would otherwise undo CodeMirror's own layout rules. Colors come from #hrui's tokens (--fg,
// --accent, --ok, --warn, --faint, ...), which still reach in, so light and dark both follow the
// console's theme.
//
// Load it with next/dynamic (ssr: false) where it is used; a file's language is loaded when the
// file opens, so only the kinds that are opened are fetched.
import { useEffect, useRef } from 'react';
import { Annotation, Compartment, EditorState, type Extension } from '@codemirror/state';
import { EditorView, keymap, lineNumbers, placeholder as placeholderText, type Command } from '@codemirror/view';
import { defaultKeymap, history, historyKeymap, indentLess, indentMore } from '@codemirror/commands';
import { HighlightStyle, StreamLanguage, indentUnit, syntaxHighlighting } from '@codemirror/language';
import { tags as t } from '@lezer/highlight';

export type CodeLang =
  | 'javascript' | 'jsx' | 'typescript' | 'tsx' | 'python' | 'markdown' | 'json' | 'yaml'
  | 'shell' | 'toml' | 'dockerfile' | 'text';

/** A file's language, from its path: its extension, or the name itself (Dockerfile). */
export function languageOf(path: string): CodeLang {
  const name = (path.split('/').pop() || '').toLowerCase();
  if (name === 'dockerfile' || name.startsWith('dockerfile.') || name.endsWith('.dockerfile')) return 'dockerfile';
  const dot = name.lastIndexOf('.');
  switch (dot < 0 ? '' : name.slice(dot + 1)) {
    case 'js': case 'mjs': case 'cjs': return 'javascript';
    case 'jsx': return 'jsx';
    case 'ts': case 'mts': case 'cts': return 'typescript';
    case 'tsx': return 'tsx';
    case 'py': case 'pyi': return 'python';
    case 'md': case 'markdown': return 'markdown';
    case 'json': return 'json';
    case 'yml': case 'yaml': return 'yaml';
    case 'sh': case 'bash': case 'zsh': return 'shell';
    case 'toml': return 'toml';
    default: return 'text';
  }
}

/** The widest line number's digits (two at least): the number column is that many characters
 *  wide, so a header numbered above the editor (SkillEditor) can line its numbers up with it. */
export function numberDigits(lines: number, first = 1): number {
  return Math.max(2, String(first + Math.max(1, lines) - 1).length);
}

/** Line `n` of the text as it is numbered when the numbers start at `first`. */
export const lineLabel = (n: number, first = 1) => String(n + first - 1);

const LOAD: Record<Exclude<CodeLang, 'text'>, () => Promise<Extension>> = {
  javascript: () => import('@codemirror/lang-javascript').then((m) => m.javascript()),
  jsx: () => import('@codemirror/lang-javascript').then((m) => m.javascript({ jsx: true })),
  typescript: () => import('@codemirror/lang-javascript').then((m) => m.javascript({ typescript: true })),
  tsx: () => import('@codemirror/lang-javascript').then((m) => m.javascript({ typescript: true, jsx: true })),
  python: () => import('@codemirror/lang-python').then((m) => m.python()),
  markdown: () => import('@codemirror/lang-markdown').then((m) => m.markdown({ base: m.markdownLanguage })),
  json: () => import('@codemirror/lang-json').then((m) => m.json()),
  yaml: () => import('@codemirror/lang-yaml').then((m) => m.yaml()),
  shell: () => import('@codemirror/legacy-modes/mode/shell').then((m) => StreamLanguage.define(m.shell)),
  toml: () => import('@codemirror/legacy-modes/mode/toml').then((m) => StreamLanguage.define(m.toml)),
  dockerfile: () => import('@codemirror/legacy-modes/mode/dockerfile').then((m) => StreamLanguage.define(m.dockerFile)),
};
const loadLanguage = (lang: CodeLang): Promise<Extension> => (lang === 'text' ? Promise.resolve([]) : LOAD[lang]());

// the colors: keywords in the accent, literals green and amber, comments faint, the rest the text's own
const highlight = HighlightStyle.define([
  { tag: [t.keyword, t.modifier, t.self], color: 'var(--accent)' },
  { tag: [t.string, t.regexp, t.special(t.string)], color: 'var(--ok)' },
  { tag: [t.number, t.bool, t.null, t.atom, t.constant(t.name), t.escape], color: 'var(--warn)' },
  { tag: [t.comment, t.meta, t.processingInstruction], color: 'var(--faint)' },
  { tag: [t.typeName, t.className, t.namespace, t.tagName, t.definition(t.propertyName), t.attributeName], color: 'var(--lb-ink)' },
  { tag: [t.operator, t.punctuation], color: 'var(--muted)' },
  { tag: t.invalid, color: 'var(--bad)' },
  { tag: t.heading, color: 'var(--fg)', fontWeight: '600' },
  { tag: t.strong, fontWeight: '600' },
  { tag: t.emphasis, fontStyle: 'italic' },
  { tag: t.strikethrough, textDecoration: 'line-through' },
  { tag: [t.link, t.url], color: 'var(--accent)' },
  { tag: t.monospace, color: 'var(--ok)' },
  { tag: t.quote, color: 'var(--muted)' },
]);

// 13px mono at 1.6, the console's code text; the number column as wide as the widest number
// (--cm-ln-ch, set as the text changes) plus its padding, the same as a header beside it
const theme = EditorView.theme({
  '&': { color: 'var(--fg)', backgroundColor: 'transparent', fontSize: '13px' },
  '&.cm-focused': { outline: 'none' },
  '.cm-scroller': { fontFamily: 'var(--mono)', lineHeight: '1.6', overflowX: 'hidden' },
  '.cm-content': { padding: '14px 0', caretColor: 'var(--fg)' },
  '.cm-line': { padding: '0 16px 0 6px' },
  '.cm-gutters': { backgroundColor: 'transparent', color: 'var(--faint)', border: 'none' },
  '.cm-lineNumbers': { width: 'calc(var(--cm-ln-ch, 2) * 1ch + 26px)' },
  '.cm-lineNumbers .cm-gutterElement': { padding: '0 10px 0 16px', minWidth: '0', userSelect: 'none' },
  '.cm-placeholder': { color: 'var(--faint)' },
});

/** Tab: two spaces at the caret, or the selected lines indented; Shift-Tab takes them back. Escape
 *  then Tab leaves the editor (CodeMirror's own tab focus mode), so it never traps the keyboard. */
const tab: Command = (view) => {
  if (view.state.readOnly) return false;
  if (view.state.selection.ranges.some((r) => !r.empty)) return indentMore(view);
  view.dispatch(view.state.update(view.state.replaceSelection('  '), { scrollIntoView: true, userEvent: 'input' }));
  return true;
};

/** A change that came from `value` (another file opened, the text replaced outside): not echoed back. */
const outside = Annotation.define<boolean>();

/** The smallest change that turns `a` into `b`: what they share at each end stays, so the caret and
 *  the undo history keep their places. */
export function diffText(a: string, b: string): { from: number; to: number; insert: string } {
  let s = 0;
  const n = Math.min(a.length, b.length);
  while (s < n && a.charCodeAt(s) === b.charCodeAt(s)) s++;
  let e = 0;
  while (e < n - s && a.charCodeAt(a.length - 1 - e) === b.charCodeAt(b.length - 1 - e)) e++;
  return { from: s, to: a.length - e, insert: b.slice(s, b.length - e) };
}

export type CodeEditorProps = {
  value: string;
  onChange?: (value: string) => void;
  readOnly?: boolean;
  /** the file's path: its language, and a new path is a new file (its own undo history) */
  path: string;
  /** the number of the first line, when the numbering goes on from a header above (SKILL.md's) */
  firstLineNumber?: number;
  placeholder?: string;
  ariaLabel: string;
  className?: string;
};

export function CodeEditor({ value, onChange, readOnly = false, path, firstLineNumber = 1, placeholder, ariaLabel, className }: CodeEditorProps) {
  const host = useRef<HTMLDivElement | null>(null);
  const view = useRef<EditorView | null>(null);
  const parts = useRef<{ lang: Compartment; conf: Compartment; base: Extension } | null>(null);
  const latest = useRef({ value, onChange, path, readOnly, firstLineNumber, placeholder, ariaLabel });
  latest.current = { value, onChange, path, readOnly, firstLineNumber, placeholder, ariaLabel };
  const shownPath = useRef(path);
  const said = useRef(value);              // the text as the editor last had it, so a value it sent is not put back
  const loading = useRef(0);

  // what follows the props: the numbers' start, read only, the placeholder, the label
  const conf = (): Extension => {
    const p = latest.current;
    return [
      lineNumbers({ formatNumber: (n) => lineLabel(n, p.firstLineNumber) }),
      EditorState.readOnly.of(p.readOnly),
      EditorView.contentAttributes.of({
        'aria-label': p.ariaLabel, spellcheck: 'false', autocorrect: 'off', autocapitalize: 'off',
        ...(p.readOnly ? { 'aria-readonly': 'true' } : {}),
      }),
      p.placeholder ? placeholderText(p.placeholder) : [],
    ];
  };
  const digits = (state: EditorState) => {
    host.current?.style.setProperty('--cm-ln-ch', String(numberDigits(state.doc.lines, latest.current.firstLineNumber)));
  };
  const stateFor = (doc: string) => {
    const pp = parts.current as NonNullable<typeof parts.current>;
    return EditorState.create({ doc, extensions: [pp.base, pp.lang.of([]), pp.conf.of(conf())] });
  };
  // the file's language, once loaded; a load that a newer file overtook is dropped
  const language = (p: string) => {
    const ticket = ++loading.current;
    loadLanguage(languageOf(p)).then((ext) => {
      const v = view.current, pp = parts.current;
      if (v && pp && ticket === loading.current) v.dispatch({ effects: pp.lang.reconfigure(ext) });
    }).catch(() => { /* the text stays, plain */ });
  };

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    const base: Extension = [
      history(),
      indentUnit.of('  '),
      EditorState.tabSize.of(2),
      keymap.of([{ key: 'Tab', run: tab, shift: indentLess }, ...defaultKeymap, ...historyKeymap]),
      EditorView.lineWrapping,
      syntaxHighlighting(highlight),
      theme,
      EditorView.updateListener.of((u) => {
        if (!u.docChanged) return;
        digits(u.state);
        if (u.transactions.some((tr) => tr.annotation(outside))) return;
        const text = u.state.doc.toString();
        said.current = text;
        latest.current.onChange?.(text);
      }),
    ];
    parts.current = { lang: new Compartment(), conf: new Compartment(), base };
    const v = new EditorView({ parent: el, state: stateFor(latest.current.value) });
    view.current = v;
    said.current = latest.current.value;
    shownPath.current = latest.current.path;
    digits(v.state);
    language(latest.current.path);
    return () => { loading.current++; v.destroy(); view.current = null; parts.current = null; };
  // once: what changes later reaches it through the effects below
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // another file: a new document with its own history and language. The same file's text changed
  // from outside: only what differs is replaced, and it is not sent back as an edit
  useEffect(() => {
    const v = view.current;
    if (!v) return;
    if (shownPath.current !== path) {
      shownPath.current = path;
      said.current = value;
      v.setState(stateFor(value));
      digits(v.state);
      language(path);
      return;
    }
    if (value === said.current) return;
    said.current = value;
    const cur = v.state.doc.toString();
    if (cur !== value) v.dispatch({ changes: diffText(cur, value), annotations: [outside.of(true)] });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, value]);

  useEffect(() => {
    const v = view.current, pp = parts.current;
    if (!v || !pp) return;
    v.dispatch({ effects: pp.conf.reconfigure(conf()) });
    digits(v.state);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [readOnly, firstLineNumber, placeholder, ariaLabel]);

  return <div ref={host} className={`hr-code hrui-legacy${className ? ' ' + className : ''}`} data-lang={languageOf(path)} />;
}

export default CodeEditor;
