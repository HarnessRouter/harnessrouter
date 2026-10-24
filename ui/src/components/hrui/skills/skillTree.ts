// A skill's folder in the editor: the tree drawn from its file paths, and what New file, New folder,
// upload, rename and remove do to a draft. SKILL.md (files[0]) is never moved or removed, and no
// other file can take its place at the root. Each function returns the draft's changed fields.
import { skillRoot, splitSkillMd, type SkillDraft, type SkillFile } from './skillMd';

export type Patch = Partial<Pick<SkillDraft, 'name' | 'desc' | 'rest' | 'files' | 'cur' | 'dirs'>>;

export const parentOf = (p: string) => { const i = p.lastIndexOf('/'); return i < 0 ? '' : p.slice(0, i); };
export const joinPath = (dir: string, rel: string) => (dir ? `${dir}/${rel}` : rel);
const under = (p: string, dir: string) => p === dir || p.startsWith(dir + '/');
const curPath = (d: SkillDraft) => d.files[d.cur]?.path ?? 'SKILL.md';
const indexOf = (files: SkillFile[], path: string) => Math.max(0, files.findIndex((f) => f.path === path));

/** A typed or uploaded path as it is stored: forward slashes, nothing doubled, none at either end. */
export function normPath(raw: string): string {
  return raw.trim().replace(/\\/g, '/').replace(/^(\.\/)+/, '').replace(/\/{2,}/g, '/').replace(/^\/+|\/+$/g, '')
    .split('/').map((s) => s.trim()).join('/');
}

/** Files a computer adds to a folder by itself; an uploaded folder leaves them out. */
export const isJunk = (p: string) => p.split('/').some((s) => s === '.DS_Store' || s === 'Thumbs.db' || s === '__MACOSX' || s === '.git');

/** Every folder in the draft: the ones its files sit in and the empty ones made in the editor. */
export function folders(d: SkillDraft): Set<string> {
  const out = new Set<string>();
  const add = (p: string) => { for (let q = p; q; q = parentOf(q)) out.add(q); };
  d.files.forEach((f) => add(parentOf(f.path)));
  (d.dirs || []).forEach(add);
  return out;
}

const invisible = (p: string) => Array.from(p).some((c) => { const n = c.charCodeAt(0); return n < 32 || n === 127; });

/** Why `p` can't be added as a file or a folder, or '' when it can. */
export function pathProblem(d: SkillDraft, p: string, kind: 'file' | 'dir'): string {
  if (!p) return kind === 'dir' ? 'Type a folder name.' : 'Type a file name.';
  if (p.split('/').some((s) => !s || s === '.' || s === '..')) {
    return kind === 'dir' ? 'Use a folder name like scripts, or a path like scripts/helpers.' : 'Use a file name like notes.md, or a path like scripts/run.py.';
  }
  if (invisible(p)) return 'Use visible characters only.';
  if (p === 'SKILL.md') return 'SKILL.md is already here. A skill has one, at its top.';
  if (d.files.some((f) => f.path === p)) return `${p} already exists.`;
  if (folders(d).has(p)) return kind === 'dir' ? `The folder ${p} already exists.` : `${p} is already a folder.`;
  for (let q = parentOf(p); q; q = parentOf(q)) {
    if (d.files.some((f) => f.path === q)) return `${q} is a file, so nothing can go inside it.`;
  }
  return '';
}

/** Empty folders that still hold nothing, each once. */
function keepEmpty(dirs: string[], files: SkillFile[]): string[] {
  return Array.from(new Set(dirs)).filter((x) => x && !files.some((f) => f.path.startsWith(x + '/')));
}

export function addFile(d: SkillDraft, p: string): Patch {
  const files = [...d.files, { path: p, content: '' }];
  return { files, cur: files.length - 1, dirs: keepEmpty(d.dirs || [], files) };
}

export function addDir(d: SkillDraft, p: string): Patch {
  return { dirs: keepEmpty([...(d.dirs || []), p], d.files) };
}

/** Remove a file, or a folder with everything in it. The folder it was in stays, even if empty now. */
export function removeAt(d: SkillDraft, path: string, dir: boolean): Patch {
  const gone = (p: string) => (dir ? under(p, path) : p === path);
  const files = d.files.filter((f, i) => i === 0 || !gone(f.path));
  const dirs = (d.dirs || []).filter((x) => !(dir && under(x, path)));
  const par = parentOf(path);
  if (par) dirs.push(par);
  return { files, dirs: keepEmpty(dirs, files), cur: indexOf(files, curPath(d)) };
}

/** Rename a file or a folder in place (a folder's files move with it). A message when it can't. */
export function renameAt(d: SkillDraft, path: string, dir: boolean, raw: string): { patch: Patch; to: string } | string {
  const nm = raw.trim();
  if (!nm) return dir ? 'Type a folder name.' : 'Type a file name.';
  if (/[\\/]/.test(nm)) return 'Use a name without a slash.';
  const to = joinPath(parentOf(path), nm);
  if (to === path) return { patch: {}, to };
  const why = pathProblem({ ...d, ...removeAt(d, path, dir) }, to, dir ? 'dir' : 'file');
  if (why) return why;
  const move = (p: string) => (dir ? (under(p, path) ? to + p.slice(path.length) : p) : (p === path ? to : p));
  const files = d.files.map((f, i) => (i === 0 ? f : { ...f, path: move(f.path) }));
  const dirs = (d.dirs || []).map(move);
  return { patch: { files, dirs, cur: indexOf(files, move(curPath(d))) }, to };
}

/** Files under a folder, all the way down. */
export const countIn = (d: SkillDraft, dir: string) => d.files.filter((f) => f.path.startsWith(dir + '/')).length;

/** Where uploaded files land: a skill's own folder (it holds SKILL.md at its top) lands at the
 *  root without its name in front, so its SKILL.md is this skill's; anything else lands in `at`
 *  with the folders it came in. */
export function uploadPaths(rels: string[], at: string): string[] {
  const top = skillRoot(rels);
  return rels.map((r) => (top ? r.slice(top.length + 1) : joinPath(at, r)));
}

export interface Merged { patch: Patch; added: number; replaced: number; clashed: number; md: 'read' | 'binary' | null; last: string }

/** Uploaded files into the draft. A file at a path already taken by a file replaces it; one whose
 *  path is a folder, or sits inside a file, is left out. A SKILL.md at the root is read into the
 *  skill: its name, description and other header lines (where it has them) and its body. */
export function mergeUploads(d: SkillDraft, adds: SkillFile[]): Merged {
  const files = d.files.slice();
  let { name, desc, rest } = d;
  let added = 0, replaced = 0, clashed = 0, md: Merged['md'] = null, last = '';
  for (const a of adds) {
    if (a.path === 'SKILL.md') {
      if (a.content === undefined) { md = 'binary'; continue; }
      const sp = splitSkillMd(a.content);
      name = sp.name || name; desc = sp.description || desc;
      if (sp.name || sp.description || sp.rest.length) rest = sp.rest;
      files[0] = { path: 'SKILL.md', content: sp.body };
      md = 'read'; last = 'SKILL.md';
      continue;
    }
    const at = files.findIndex((f) => f.path === a.path);
    if (at > 0) { files[at] = a; replaced++; last = a.path; continue; }
    if (pathProblem({ ...d, files }, a.path, 'file')) { clashed++; continue; }
    files.push(a); added++; last = a.path;
  }
  return {
    patch: { name, desc, rest, files, dirs: keepEmpty(d.dirs || [], files), cur: last ? indexOf(files, last) : indexOf(files, curPath(d)) },
    added, replaced, clashed, md, last,
  };
}

export interface TNode { name: string; path: string; dir: boolean; i: number; kids: TNode[]; n: number }

/** The folder tree: SKILL.md first, then folders, then files, each by name. `i` is a file's index
 *  in draft.files (-1 for a folder); `n` is how many files a folder holds, all the way down. */
export function buildTree(d: SkillDraft): TNode[] {
  const root: TNode = { name: '', path: '', dir: true, i: -1, kids: [], n: 0 };
  const byPath = new Map<string, TNode>([['', root]]);
  const ensure = (path: string): TNode => {
    const hit = byPath.get(path);
    if (hit) return hit;
    const parent = ensure(parentOf(path));
    const node: TNode = { name: path.slice(path.lastIndexOf('/') + 1), path, dir: true, i: -1, kids: [], n: 0 };
    parent.kids.push(node);
    byPath.set(path, node);
    return node;
  };
  (d.dirs || []).forEach((x) => { if (x) ensure(x); });
  d.files.forEach((f, i) => {
    const parent = ensure(parentOf(f.path));
    parent.kids.push({ name: f.path.slice(f.path.lastIndexOf('/') + 1), path: f.path, dir: false, i, kids: [], n: 0 });
    for (let q = parentOf(f.path); q; q = parentOf(q)) { const n = byPath.get(q); if (n) n.n++; }
  });
  const order = (a: TNode, b: TNode) => (a.i === 0 ? -1 : b.i === 0 ? 1
    : a.dir !== b.dir ? (a.dir ? -1 : 1) : a.name.localeCompare(b.name, undefined, { numeric: true }));
  const sort = (n: TNode) => { n.kids.sort(order); n.kids.forEach(sort); };
  sort(root);
  return root.kids;
}
