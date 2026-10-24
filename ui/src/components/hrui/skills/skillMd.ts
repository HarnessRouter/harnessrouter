// A skill as the editor holds it (Agent Skills): a folder with SKILL.md at its root plus any other
// files and folders. SKILL.md's frontmatter carries the skill's name and description; the editor
// keeps those two as fields, the frontmatter's other lines as they are, and SKILL.md's body as the
// first file. One module for both places that edit a skill (Extensions › Skills and a setup's
// Settings), so the file written is the same wherever it is written from.
import type { SkillFile } from '@/components/HarnessEditors';

export type { SkillFile };

/** Agent Skills: a name is lowercase letters, digits and single hyphens, 64 characters at most. */
export const SKILL_NAME_MAX = 64;
const NAME_RE = /^[a-z0-9]+(-[a-z0-9]+)*$/;

/** The name as it is stored: lowercase ASCII letters and digits, every other run of characters one
 *  hyphen, none at either end, cut to 64 characters. A name that is already valid comes back as it is. */
export function skillSlug(n: string): string {
  return (n || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').trim().toLowerCase()
    .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')
    .slice(0, SKILL_NAME_MAX).replace(/-+$/, '');
}
export const isSkillName = (n: string) => n.length <= SKILL_NAME_MAX && NAME_RE.test(n);

/** SKILL.md split into its frontmatter's name and description, the other frontmatter lines (kept
 *  as they are), and the body the editor shows. */
export function splitSkillMd(text: string): { name: string; description: string; rest: string[]; body: string } {
  const m = /^---\r?\n([\s\S]*?)\r?\n---[ \t]*(\r?\n|$)/.exec(text || '');
  if (!m) return { name: '', description: '', rest: [], body: text || '' };
  const lines = m[1].split(/\r?\n/);
  let name = '', description = '';
  const rest: string[] = [];
  const unq = (v: string) => {
    const t = v.trim();
    if (/^".*"$/.test(t)) { try { return JSON.parse(t) as string; } catch { return t.slice(1, -1); } }
    return /^'.*'$/.test(t) ? t.slice(1, -1).replace(/''/g, "'") : t;
  };
  for (let i = 0; i < lines.length; i++) {
    const k = /^(name|description):\s*(.*)$/.exec(lines[i]);
    if (!k) { rest.push(lines[i]); continue; }
    let v = k[2];
    // a block scalar (description: > or |) runs on over its indented lines
    if (/^[>|][-+]?\s*$/.test(v.trim()) || v.trim() === '') {
      const more: string[] = [];
      while (i + 1 < lines.length && /^\s+\S/.test(lines[i + 1])) more.push(lines[++i].trim());
      v = more.join(v.trim().startsWith('|') ? '\n' : ' ');
    } else v = unq(v);
    if (k[1] === 'name') name = v; else description = v;
  }
  return { name, description, rest, body: text.slice(m[0].length).replace(/^\r?\n/, '') };
}

/** SKILL.md's frontmatter, line by line, exactly as joinSkillMd writes it (the editor shows these). */
export function skillHeader(name: string, description: string, rest: string[]): string[] {
  const d = description.replace(/\s+/g, ' ').trim();
  return ['---', `name: ${name}`, `description: ${JSON.stringify(d)}`, ...rest.filter((l) => l.trim()), '---'];
}

export function joinSkillMd(name: string, description: string, rest: string[], body: string): string {
  return `${skillHeader(name, description, rest).join('\n')}\n\n${body.replace(/^\s*\n/, '')}${body.endsWith('\n') ? '' : '\n'}`;
}

export interface SkillDraft {
  id: string | null;             // null: a new skill
  name: string; desc: string; rest: string[];
  files: SkillFile[];            // SKILL.md's body first, then the other files, paths from the skill's root
  cur: number;                   // the file open in the editor
  dirs?: string[];               // folders made in the editor that hold no file yet (only files are stored)
}

/** The folder every path sits in when they all sit in one folder that holds SKILL.md: a skill's own
 *  folder, uploaded or stored with its name in front. '' otherwise. */
export function skillRoot(paths: string[]): string {
  if (!paths.length || !paths.every((p) => p.includes('/'))) return '';
  const top = paths[0].slice(0, paths[0].indexOf('/'));
  return paths.every((p) => p.startsWith(top + '/')) && paths.includes(`${top}/SKILL.md`) ? top : '';
}

/** A skill's files as the editor opens them: SKILL.md first, split into name, description and body. */
export function skillDraft(id: string | null, fallbackName: string, files: SkillFile[]): SkillDraft {
  let list = files;
  if (!list.some((f) => f.path === 'SKILL.md')) {
    const top = skillRoot(list.map((f) => f.path));
    if (top) list = list.map((f) => ({ ...f, path: f.path.slice(top.length + 1) }));
  }
  const at = list.findIndex((f) => f.path === 'SKILL.md');
  const md = at >= 0 ? list[at] : { path: 'SKILL.md', content: '' };
  const sp = splitSkillMd(md.content || '');
  return { id, name: sp.name || fallbackName, desc: sp.description, rest: sp.rest,
    files: [{ path: 'SKILL.md', content: sp.body }, ...list.filter((_, i) => i !== at)], cur: 0 };
}

/** The files to store: SKILL.md written back with its frontmatter. Empty folders are not files. */
export const skillFiles = (e: SkillDraft, name: string): SkillFile[] =>
  [{ path: 'SKILL.md', content: joinSkillMd(name, e.desc, e.rest, e.files[0]?.content || '') }, ...e.files.slice(1)];

/** Why the skill can't be saved yet, or ''. */
export function skillMissing(e: SkillDraft): string {
  const m: string[] = [];
  if (!e.name.trim()) m.push('a name');
  if (!e.desc.trim()) m.push('a description');
  if (!(e.files[0]?.content || '').trim()) m.push('instructions');
  if (m.length) return 'Add ' + m.join(', ').replace(/, ([^,]*)$/, ' and $1') + '.';
  return skillSlug(e.name) ? '' : 'Use letters or digits in the name.';
}
