'use client';
// The skill editor, one for every place a skill is made or changed (Extensions › Skills and a
// setup's Settings › Capabilities): the design's sheet (docs/uxuidesign/console-79: skillEdHtml)
// with the folder a skill is (Agent Skills): SKILL.md at the root plus any files and folders,
// listed as a tree beside the editor. New file, New folder, Upload files and Upload folder add to
// the folder picked in the tree; any row but SKILL.md can be renamed or removed in place.
//
// Name and Description are SKILL.md's frontmatter. The editor shows that header above SKILL.md's
// body, read only, exactly as it will be written: the name as it is stored (skillSlug), the
// description, and any other lines the file came with (license, allowed-tools), which are kept.
// The header and the body are one page that scrolls as one (Richard, 2026-10-18): the header's lines
// wrap, never scroll sideways, and the body grows with what it holds, so no part stays pinned and no
// scroll sits inside another. The body is the console's code editor (CodeEditor, Richard 10-21: a
// skill's files are edited with their code highlighted): its long lines wrap too, never a sideways
// scroll, each line keeping one number, beside its first row, numbered on from the header's.
import { Fragment, useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type DragEvent, type ReactNode } from 'react';
import dynamic from 'next/dynamic';
import { readSkillUpload } from '@/components/HarnessEditors';
import { Sheet, SheetTop } from '../Sheet';
import { Skel, SkLine } from '../Skel';
import { toast } from '../toast';
import { SKILL_NAME_MAX, skillHeader, skillMissing, skillSlug, type SkillDraft, type SkillFile } from './skillMd';
import {
  addDir, addFile, buildTree, isJunk, mergeUploads, normPath, parentOf, pathProblem,
  removeAt, renameAt, uploadPaths, type TNode,
} from './skillTree';
import './skills.css';

// the editor and its languages load when a skill is opened, not with the page
const CodeEditor = dynamic(() => import('../CodeEditor').then((m) => m.CodeEditor), {
  ssr: false, loading: () => <div className="hr-code-wait" aria-hidden="true" />,
});

const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`;
const bytesOf = (b64: string) => Math.floor(((b64 || '').length * 3) / 4);
const fmtBytes = (n: number) => (n < 1024 ? `${n} bytes` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`);

function Svg({ children, s = 16 }: { children: ReactNode; s?: number }) {
  return <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>;
}
const I = {
  file: <Svg s={14}><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5" /></Svg>,
  folder: <Svg s={14}><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /></Svg>,
  chev: <Svg s={12}><path d="M9 6l6 6-6 6" /></Svg>,
  newFile: <Svg><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5M12 11.5v6M9 14.5h6" /></Svg>,
  newDir: <Svg><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><path d="M12 10.5v6M9 13.5h6" /></Svg>,
  upFile: <Svg><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><path d="M7 9l5-5 5 5M12 4v12" /></Svg>,
  upDir: <Svg><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><path d="M12 16.5v-6M9.5 13 12 10.5 14.5 13" /></Svg>,
  pen: <Svg s={14}><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" /></Svg>,
  bin: <Svg s={14}><path d="M4 7h16M9 7V4.5h6V7M18 7l-1 13H7L6 7M10 11v5M14 11v5" /></Svg>,
};

/** The name of a file, its extension kept whole when it is cut (the design's fnSplit). */
function FileName({ path }: { path: string }) {
  const i = path.lastIndexOf('.');
  if (i <= 0) return <span className="fn"><span className="fn-a">{path}</span></span>;
  return <span className="fn"><span className="fn-a">{path.slice(0, i)}</span><span className="fn-b">{path.slice(i)}</span></span>;
}

type Entry = { kind: 'file' | 'dir'; value: string; err: string };
type Ren = { path: string; dir: boolean; value: string; err: string };
type Picked = { file: File; rel: string };

/** The pauses before a file or folder that could not be read is read again; after the last, it is
 *  named as not read. */
export const READ_RETRY_MS = [250, 750];
const sleep = (ms: number) => new Promise<void>((done) => { setTimeout(done, ms); });
async function retried<T>(read: () => Promise<T>): Promise<T> {
  for (let i = 0; ; i++) {
    try { return await read(); }
    catch (e) { if (i >= READ_RETRY_MS.length) throw e; await sleep(READ_RETRY_MS[i]); }
  }
}

/** A dropped folder, read all the way down with the paths it had. What cannot be read (after its
 *  retries) is named in `lost`, a folder with a trailing slash: never skipped silently. */
export async function walk(entry: FileSystemEntry, prefix: string, out: Picked[], lost: string[]): Promise<void> {
  const here = prefix ? `${prefix}/${entry.name}` : entry.name;
  if (entry.isFile) {
    try { out.push({ file: await retried(() => new Promise<File>((res, rej) => (entry as FileSystemFileEntry).file(res, rej))), rel: here }); }
    catch { lost.push(here); }
  } else if (entry.isDirectory) {
    const reader = (entry as FileSystemDirectoryEntry).createReader();
    for (;;) {
      let batch: FileSystemEntry[];
      try { batch = await retried(() => new Promise<FileSystemEntry[]>((res, rej) => reader.readEntries(res, rej))); }
      catch { lost.push(`${here}/`); return; }
      if (!batch.length) break;
      for (const e of batch) await walk(e, here, out, lost);
    }
  }
}

/** One picked file as the skill keeps it; throws when its bytes cannot be read (an empty file is
 *  never put in its place). */
async function readPicked(file: File, path: string): Promise<SkillFile> {
  const bytes = await retried(() => file.arrayBuffer());
  return readSkillUpload(new File([bytes], file.name, { type: file.type }), path);
}

/** What could not be read, in one sentence: how many, and the first few by name ("a, b and 3 more"). */
export function unreadLine(xs: string[]): string {
  if (xs.length === 1) return `${xs[0]} could not be read.`;
  const dirs = xs.filter((x) => x.endsWith('/')).length;
  const what = dirs === 0 ? `${xs.length} files` : dirs === xs.length ? `${xs.length} folders` : `${xs.length} files and folders`;
  const shown = xs.slice(0, 4);
  const more = xs.length - shown.length;
  const names = more > 0 ? `${shown.join(', ')} and ${more} more` : `${shown.slice(0, -1).join(', ')} and ${shown[shown.length - 1]}`;
  return `${what} could not be read: ${names}.`;
}

export function SkillEditor<T extends SkillDraft>({ ed, setEd, busy, onSave, onClose, setup, primary }: {
  ed: T; setEd: (e: T) => void; busy: boolean; onSave: (e: T) => void; onClose: () => void;
  /** the setup the skill is in (the foot no longer names it: Richard, 10-21) */
  setup?: string;
  /** the main button's word when it is not Save or Create: Next, where the setups come in a second
   *  step (Extensions › Skills, AddToSheet) */
  primary?: string;
}) {
  const nameRef = useRef<HTMLInputElement | null>(null);
  const descRef = useRef<HTMLTextAreaElement | null>(null);
  const scRef = useRef<HTMLDivElement | null>(null);       // the open file's page: the header and the body, one scroll
  const boxRef = useRef<HTMLDivElement | null>(null);
  const inlineRef = useRef<HTMLInputElement | null>(null);
  const askRef = useRef<HTMLButtonElement | null>(null);
  const upRef = useRef<HTMLInputElement | null>(null);
  const dirRef = useRef<HTMLInputElement | null>(null);
  const edRef = useRef(ed);
  edRef.current = ed;

  const [at, setAt] = useState('');                          // the folder New and Upload add to ('' is the top)
  const [shut, setShut] = useState<Set<string>>(() => new Set());
  // a path being typed: kept in a ref too, so a blur that comes after Escape or Enter finds it gone
  const [entry, setEntryState] = useState<Entry | null>(null);
  const entryRef = useRef<Entry | null>(null);
  const setEntry = (x: Entry | null) => { entryRef.current = x; setEntryState(x); };
  const [ren, setRenState] = useState<Ren | null>(null);
  const renRef = useRef<Ren | null>(null);
  const setRen = (r: Ren | null) => { renRef.current = r; setRenState(r); };
  const [ask, setAsk] = useState<{ path: string; dir: boolean } | null>(null);
  const [reading, setReading] = useState(0);
  const [drop, setDrop] = useState(false);
  // an upload that could not be read whole: what was not read, and the same upload again. Nothing of it
  // was added, so the skill is never saved half read
  const [unread, setUnread] = useState<{ names: string[]; again: () => void } | null>(null);

  // the name takes focus on a desktop, selected when editing; a phone keeps its keyboard down
  const [desktop] = useState(() => typeof window === 'undefined' || window.innerWidth > 700);
  useEffect(() => {
    if (!desktop || !ed.id) return;
    const t = setTimeout(() => { const f = nameRef.current; if (f && document.activeElement === f) f.select(); }, 60);
    return () => clearTimeout(t);
  // once, on open
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  // the description grows with what is typed, up to 240px
  useLayoutEffect(() => { const d = descRef.current; if (d) { d.style.height = 'auto'; d.style.height = Math.min(d.scrollHeight + 2, 240) + 'px'; } }, [ed.desc]);
  // the editor grows with what it holds, so the page around it is the one scroll, and it keeps its
  // caret in view in that page as it moves or text is typed (CodeEditor)
  const focusCode = () => requestAnimationFrame(() => scRef.current?.querySelector<HTMLElement>('.cm-content, textarea')?.focus());
  // the folder picker: only an input that carries webkitdirectory offers folders. Set as the input
  // mounts: the Sheet draws its content a render after this component, so a mount effect here ran
  // before the input existed and the picker could only open folders, never choose one.
  const dirInput = useCallback((el: HTMLInputElement | null) => {
    dirRef.current = el;
    if (el) { el.setAttribute('webkitdirectory', ''); el.setAttribute('directory', ''); }
  }, []);
  // a path being typed or a remove being asked takes focus as it opens
  useEffect(() => {
    const el = inlineRef.current;
    if (!el) return;
    el.focus();
    const v = el.value;
    if (ren) { const dot = ren.dir ? -1 : v.lastIndexOf('.'); el.setSelectionRange(0, dot > 0 ? dot : v.length); }
    else el.setSelectionRange(v.length, v.length);
  // when one opens, not on every keystroke
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entry?.kind, ren?.path]);
  // a remove that asks first: its Remove button takes focus, as the design's confirms do
  useEffect(() => { askRef.current?.focus(); }, [ask?.path, ask?.dir]);

  const focusRow = (key: string) => requestAnimationFrame(() => {
    const el = boxRef.current?.querySelector<HTMLElement>(`[data-p="${CSS.escape(key)}"]`);
    el?.focus();
  });
  // Escape in a path field or a remove question puts that away; the dialog stays open
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      const host = (e.target as HTMLElement | null)?.closest?.('[data-esc]') as HTMLElement | null;
      if (!host) return;
      e.stopPropagation();
      e.preventDefault();
      setRen(null); setEntry(null); setAsk(null);
      focusRow(host.dataset.esc || '');
    };
    window.addEventListener('keydown', k, true);
    return () => window.removeEventListener('keydown', k, true);
  }, []);

  const put = (p: Partial<SkillDraft>) => setEd({ ...edRef.current, ...p });
  const openTo = (path: string) => setShut((s) => {
    const n = new Set(s);
    for (let q = path; q; q = parentOf(q)) n.delete(q);
    return n;
  });

  const f = ed.files[ed.cur] || ed.files[0];
  const isMd = (ed.files[ed.cur] ? ed.cur : 0) === 0;
  const binary = f.content_b64 !== undefined && f.content === undefined;   // a file that is not text stays as it is
  const slug = skillSlug(ed.name);
  const typed = ed.name.trim();
  const why = skillMissing(ed);
  const head = isMd ? [...skillHeader(slug, ed.desc, ed.rest), ''] : [];
  const first = head.length + 1;
  // the header's numbers sit in a column as wide as the editor's (CodeEditor's numberDigits: the widest
  // number, two digits at least), so the two columns of numbers are one
  const lnCh = Math.max(2, String(head.length + String(f.content || '').split('\n').length).length);
  const tree = buildTree(ed);
  const hold = busy || reading > 0;
  // another file opens at its top
  useLayoutEffect(() => { if (scRef.current) scRef.current.scrollTop = 0; }, [ed.cur]);

  // ── New file / New folder: a path typed in the list ──────────────────────────────────────────
  function start(kind: 'file' | 'dir') {
    setRen(null); setAsk(null);
    if (at) openTo(at);
    setEntry({ kind, value: at ? at + '/' : '', err: '' });
  }
  function commitEntry(fromBlur: boolean) {
    const entry = entryRef.current;
    if (!entry) return;
    const p = normPath(entry.value);
    const bare = /\/\s*$/.test(entry.value);     // only a folder's path typed, nothing after it
    const err = bare && entry.kind === 'file' && p ? 'Type the file’s name after the last slash.'
      : bare && entry.kind === 'dir' && at && p === at ? 'Type the new folder’s name after the last slash.'
        : pathProblem(ed, p, entry.kind);
    if (err) { setEntry({ ...entry, err }); return; }
    setEntry(null);
    if (entry.kind === 'file') {
      put(addFile(ed, p));
      setAt(parentOf(p)); openTo(parentOf(p));
      if (!fromBlur) focusCode();
    } else {
      put(addDir(ed, p));
      setAt(p); openTo(p);
      if (!fromBlur) focusRow('d:' + p);
    }
  }

  // ── Rename and remove, in the row ────────────────────────────────────────────────────────────
  function commitRen(fromBlur: boolean) {
    const r = renRef.current;
    if (!r) return;
    const res = renameAt(ed, r.path, r.dir, r.value);
    if (typeof res === 'string') {
      if (fromBlur) { setRen(null); toast(`Not renamed. ${res}`); }
      else setRen({ ...r, err: res });
      return;
    }
    setRen(null);
    if (res.to === r.path) { if (!fromBlur) focusRow((r.dir ? 'd:' : 'f:') + r.path); return; }
    put(res.patch);
    if (r.dir) {
      const move = (p: string) => (p === r.path || p.startsWith(r.path + '/') ? res.to + p.slice(r.path.length) : p);
      setAt(move(at));
      setShut((s) => new Set(Array.from(s).map(move)));
    } else if (at === r.path) setAt(res.to);
    if (!fromBlur) focusRow((r.dir ? 'd:' : 'f:') + res.to);
  }
  function remove(path: string, dir: boolean) {
    setAsk(null);
    put(removeAt(ed, path, dir));
    if (dir && (at === path || at.startsWith(path + '/'))) setAt(parentOf(path));
    focusRow(parentOf(path) ? 'd:' + parentOf(path) : 'f:SKILL.md');
  }
  function askRemove(n: TNode) {
    setEntry(null); setRen(null);
    const file = !n.dir ? ed.files[n.i] : null;
    const empty = n.dir ? !n.n : !(file?.content || file?.content_b64);
    if (empty) remove(n.path, n.dir);              // nothing would be lost: no question
    else setAsk({ path: n.path, dir: n.dir });
  }

  // ── Uploads: files, a folder, or either dropped on the list ──────────────────────────────────
  // An upload is added whole or not at all: anything in it that cannot be read (after its retries)
  // is named, with Try again, and nothing of that upload is added.
  async function ingest(picked: Picked[], lost: string[], again: () => void) {
    setUnread(null);
    const keep = picked.filter((x) => !isJunk(x.rel));
    if (!keep.length && !lost.length) return;
    const into = at;
    const dests = uploadPaths(keep.map((x) => normPath(x.rel)), into);
    setReading(keep.length);
    const adds: SkillFile[] = [];
    const bad = [...lost];
    try {
      for (let i = 0; i < keep.length; i++) {
        try { adds.push(await readPicked(keep[i].file, dests[i])); }
        catch { bad.push(keep[i].rel); }
      }
    } finally { setReading(0); }
    if (bad.length) { setUnread({ names: bad, again }); return; }
    const r = mergeUploads(edRef.current, adds);
    put(r.patch);
    if (r.last) openTo(parentOf(r.last));
    const where = into && dests.some((p) => p.startsWith(into + '/')) ? ` to ${into}` : '';
    const say: string[] = [];
    if (r.md === 'read') say.push('SKILL.md was read into Name, Description and the instructions');
    if (r.md === 'binary') say.push('SKILL.md was not read: it is not text');
    if (r.added) say.push(`Added ${plural(r.added, 'file')}${where}`);
    if (r.replaced) say.push(`Replaced ${plural(r.replaced, 'file')} with the same path`);
    if (r.clashed) say.push(`${plural(r.clashed, 'file')} not added: a folder or file here already has that path`);
    if (say.length) toast(say.join('. ') + '.');
  }
  const fromInput = (el: HTMLInputElement | null) => {
    const list = Array.from(el?.files || []);
    const picked = list.map((file) => ({ file, rel: (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name }));
    const run = (): Promise<void> => ingest(picked, [], () => void run());
    void run().finally(() => { if (el) el.value = ''; });
  };
  const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer?.types || []).includes('Files');
  function onDrop(e: DragEvent<HTMLDivElement>) {
    if (!hasFiles(e)) return;
    e.preventDefault();
    setDrop(false);
    if (hold) return;
    // the entries must be taken while the drop event runs: the list is gone once it returns
    const roots: FileSystemEntry[] = [];
    for (const it of Array.from(e.dataTransfer.items || [])) {
      const en = it.kind === 'file' && typeof it.webkitGetAsEntry === 'function' ? it.webkitGetAsEntry() : null;
      if (en) roots.push(en);
    }
    const plain = roots.length ? [] : Array.from(e.dataTransfer.files || []);
    // the entries stay readable after the drop, so Try again walks them again
    const run = async (): Promise<void> => {
      const picked: Picked[] = plain.map((file) => ({ file, rel: file.name }));
      const lost: string[] = [];
      for (const r of roots) await walk(r, '', picked, lost);
      await ingest(picked, lost, () => void run());
    };
    void run();
  }

  // ── The tree ─────────────────────────────────────────────────────────────────────────────────
  function row(n: TNode, depth: number): ReactNode {
    const md = !n.dir && n.i === 0;
    const key = (n.dir ? 'd:' : 'f:') + n.path;
    const editing = ren && ren.path === n.path && ren.dir === n.dir;
    const asking = ask && ask.path === n.path && ask.dir === n.dir;
    const open = n.dir && !shut.has(n.path);
    const style = { '--d': depth } as CSSProperties;
    return (
      <li key={n.dir ? 'd:' + n.path : 'f' + n.i}>
        <div className={`ske-row${!n.dir && n.i === ed.cur ? ' on' : ''}${n.dir && n.path === at ? ' at' : ''}`} style={style}>
          {editing ? (
            <span className="ske-ren" data-esc={key}>
              <span className="ske-gap" aria-hidden="true" />
              <span className="ske-ic" aria-hidden="true">{n.dir ? I.folder : I.file}</span>
              <input ref={inlineRef} className="set-in ske-in" aria-label={`New name for ${n.path}`} value={ren.value}
                aria-invalid={!!ren.err} aria-describedby={ren.err ? 'skeRenErr' : undefined}
                onChange={(e) => setRen({ ...ren, value: e.target.value, err: '' })}
                onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); commitRen(false); } }}
                onBlur={() => commitRen(true)} />
            </span>
          ) : (
            <button type="button" className="ske-item" data-p={key} disabled={reading > 0}
              aria-expanded={n.dir ? open : undefined} aria-current={!n.dir && n.i === ed.cur ? 'true' : undefined}
              onClick={() => {
                setEntry(null); setAsk(null);
                if (n.dir) { setAt(n.path); setShut((s) => { const x = new Set(s); if (x.has(n.path)) x.delete(n.path); else x.add(n.path); return x; }); }
                else { put({ cur: n.i }); setAt(parentOf(n.path)); }
              }}>
              <span className={`ske-gap${n.dir ? ' chev' : ''}${open ? ' open' : ''}`} aria-hidden="true">{n.dir ? I.chev : null}</span>
              <span className="ske-ic" aria-hidden="true">{n.dir ? I.folder : I.file}</span>
              <FileName path={n.name} />
              {n.dir && !n.n ? <small className="ske-tag">empty</small> : null}
            </button>
          )}
          {!md && !editing ? (
            <span className="ske-acts">
              <button type="button" className="ske-ib" title="Rename" aria-label={`Rename ${n.path}`} disabled={hold}
                onClick={() => { setEntry(null); setAsk(null); setRen({ path: n.path, dir: n.dir, value: n.name, err: '' }); }}>{I.pen}</button>
              <button type="button" className="ske-ib" title="Remove" aria-label={`Remove ${n.path}`} disabled={hold}
                onClick={() => askRemove(n)}>{I.bin}</button>
            </span>
          ) : null}
        </div>
        {editing && ren.err ? <p className="ske-err" id="skeRenErr" role="alert" style={style}>{ren.err}</p> : null}
        {asking ? (
          <div className="ske-ask" data-esc={key} style={style} role="group" aria-label={`Remove ${n.path}`}>
            <span>{n.dir ? `Remove ${n.name} and the ${plural(n.n, 'file')} in it?` : `Remove ${n.name}?`}</span>
            <span className="ske-ask-b">
              <button type="button" className="link-q" onClick={() => { setAsk(null); focusRow(key); }}>Keep</button>
              <button type="button" className="link-q danger" ref={askRef} onClick={() => remove(n.path, n.dir)}>Remove</button>
            </span>
          </div>
        ) : null}
        {open && n.kids.length ? <ul>{n.kids.map((k) => row(k, depth + 1))}</ul> : null}
      </li>
    );
  }

  const nameHelp = !typed ? null
    : !slug ? <>Use letters or digits. A skill’s name is stored as lowercase letters, digits and hyphens.</>
      : slug !== typed ? <>Saved as <code>{slug}</code>: lowercase letters, digits and hyphens, {SKILL_NAME_MAX} characters at most.</>
        : null;
  const empties = (ed.dirs || []).length > 0;

  return (
    <Sheet onClose={onClose} labelledBy="skh" className="sk-sheet ske-sheet" busy={busy} initialFocus={desktop ? nameRef : 'dialog'}>
      <SheetTop id="skh" title={ed.id ? 'Edit skill' : 'Create a skill'} onClose={onClose} />
      <div className="sk-f"><label htmlFor="skN">Skill name</label>
        <input id="skN" ref={nameRef} className="set-in" placeholder="Weekly status report" autoComplete="off" value={ed.name}
          aria-describedby={nameHelp ? 'skNh' : undefined} onChange={(e) => put({ name: e.target.value })} />
        {nameHelp ? <p className="set-help" id="skNh">{nameHelp}</p> : null}
      </div>
      <div className="sk-f"><label htmlFor="skD">Description</label>
        <textarea id="skD" ref={descRef} className="set-in sk-desc" rows={2} value={ed.desc}
          placeholder="Generate weekly status reports from recent work. Use when asked for updates or progress summaries."
          onChange={(e) => put({ desc: e.target.value })} /></div>

      <div ref={boxRef} className={`ske${drop ? ' drop' : ''}`}
        onDragOver={(e) => { if (hasFiles(e)) { e.preventDefault(); if (!drop) setDrop(true); } }}
        onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDrop(false); }}
        onDrop={onDrop}>
        <div className="ske-bar" role="group" aria-label="Files">
          <span className="ske-cap">Files</span>
          <button type="button" className="sk-add" data-p="bar:file" aria-label="New file" title="New file" disabled={hold} onClick={() => start('file')}>{I.newFile}<span>New file</span></button>
          <button type="button" className="sk-add" data-p="bar:dir" aria-label="New folder" title="New folder" disabled={hold} onClick={() => start('dir')}>{I.newDir}<span>New folder</span></button>
          <button type="button" className="sk-add" aria-label="Upload files" title="Upload files" disabled={hold} onClick={() => upRef.current?.click()}>{I.upFile}<span>Upload files</span></button>
          <button type="button" className="sk-add" aria-label="Upload folder" title="Upload folder" disabled={hold} onClick={() => dirRef.current?.click()}>{I.upDir}<span>Upload folder</span></button>
          <input type="file" ref={upRef} multiple hidden tabIndex={-1} onChange={(e) => fromInput(e.currentTarget)} />
          <input type="file" ref={dirInput} hidden tabIndex={-1} onChange={(e) => fromInput(e.currentTarget)} />
        </div>
        <div className="ske-body">
          <div className="ske-files">
            {entry ? (
              <div className="ske-new" data-esc={entry.kind === 'file' ? 'bar:file' : 'bar:dir'}>
                <span className="ske-ic" aria-hidden="true">{entry.kind === 'file' ? I.file : I.folder}</span>
                <input ref={inlineRef} className="set-in ske-in" value={entry.value} autoComplete="off" spellCheck={false}
                  aria-label={entry.kind === 'file' ? 'New file path' : 'New folder path'}
                  placeholder={entry.kind === 'file' ? 'scripts/run.py' : 'references'}
                  aria-invalid={!!entry.err} aria-describedby={entry.err ? 'skeNewErr' : undefined}
                  onChange={(e) => setEntry({ ...entry, value: e.target.value, err: '' })}
                  onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); commitEntry(false); } }}
                  onBlur={(e) => {
                    if (!entryRef.current) return;
                    const v = normPath(e.currentTarget.value);
                    if (!v || v === at) setEntry(null); else commitEntry(true);
                  }} />
                {entry.err ? <p className="ske-err" id="skeNewErr" role="alert">{entry.err}</p> : null}
              </div>
            ) : null}
            {unread ? (
              <p className="ske-err ske-unread" role="alert">
                {unreadLine(unread.names)} Nothing from that upload was added.{' '}
                <button type="button" className="link-q inl" disabled={hold} onClick={unread.again}>Try again</button>
              </p>
            ) : null}
            {reading ? (
              <Skel label={`Reading ${plural(reading, 'file')}`} className="ske-skel">
                {Array.from({ length: Math.min(reading, 4) }, (_, i) => <SkLine key={i} w={`${62 - i * 9}%`} h={11} style={{ margin: '9px 0 9px 26px' }} />)}
              </Skel>
            ) : null}
            <ul className="ske-tree" aria-label="Files in this skill">{tree.map((n) => row(n, 0))}</ul>
            {empties ? <p className="ske-hint">An empty folder is saved once a file is in it.</p> : null}
          </div>

          <div className="ske-pane">
            <div className="ske-path">
              <span className="ske-pth">{f.path}</span>
            </div>
            {binary ? (
              <div className="ske-bin">
                <p>This file is not text, so it is kept as it is.</p>
                <small>{fmtBytes(bytesOf(f.content_b64 || ''))}</small>
              </div>
            ) : (
              <div ref={scRef} className={`sk-code ske-code ske-cm${isMd ? ' md' : ''}`} style={{ '--cm-ln-ch': lnCh } as CSSProperties}>
                {/* the header's lines, each numbered beside it, a long one wrapped under its own number */}
                {isMd ? (
                  <div className="ske-head" role="group" aria-label="SKILL.md header, written from Name and Description">
                    {head.map((l, i) => (
                      <Fragment key={i}>
                        <span className="ske-hn" aria-hidden="true">{i + 1}</span>
                        <span className={`ske-ht${i === 1 && !slug ? ' ske-blank' : ''}`}>{l || '\u00a0'}</span>
                      </Fragment>
                    ))}
                  </div>
                ) : null}
                <CodeEditor path={f.path} ariaLabel={f.path} value={f.content || ''} firstLineNumber={first}
                  placeholder={isMd ? 'Summarize my recent work in three sections: wins, blockers, next steps.' : undefined}
                  onChange={(text) => {
                    const cur = edRef.current;
                    put({ files: cur.files.map((x, k) => (k === cur.cur ? { path: x.path, content: text } : x)) });
                  }} />
              </div>
            )}
          </div>
        </div>
        {drop ? <div className="ske-drop" aria-hidden="true"><span>Drop files or a folder to add them{at ? ` to ${at}` : ''}</span></div> : null}
      </div>

      <div className="sheet-actions sk-foot">
        <span className="grow" />
        <button type="button" className="btn" disabled={busy} onClick={onClose}>Cancel</button>
        <button type="button" className="btn primary" disabled={hold || !!why} title={why || undefined} onClick={() => onSave(edRef.current)}>{primary || (ed.id ? 'Save' : 'Create')}</button>
      </div>
    </Sheet>
  );
}
