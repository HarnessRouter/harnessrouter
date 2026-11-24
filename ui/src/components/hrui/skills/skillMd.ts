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

/** What a frontmatter reader reads: a name and a description are short. */
const FRONTMATTER_MAX = 65536;

/** A value without its YAML comment, which starts at a `#` at the start or after whitespace. One
 *  linear search: `(^|\s+)#.*$` backtracked over a long run of spaces with no `#`. */
function uncomment(v: string): string {
  const i = v.search(/(?:^|\s)#/);
  return (i >= 0 ? v.slice(0, i) : v).trimEnd();
}

/** One frontmatter value as YAML reads it, from its first line and the indented lines after it. The
 *  server reads a SKILL.md the same way, so the editor shows what the agent is told:
 *  - a quoted value runs to its closing quote (over more lines if it has to) and a comment may
 *    follow it; double quotes take backslash escapes, single quotes write a quote as '';
 *  - a `>` block is joined with spaces and a `|` block keeps its lines;
 *  - a plain value ends at a ` #` comment, and indented lines continue it. */
export function frontmatterValue(first: string, more: string[]): string {
  const lines = more.map((x) => x.trim()).filter(Boolean);
  const t = first.trim();
  if (t.startsWith('"') || t.startsWith("'")) {
    const q = t[0];
    const raw = [t, ...lines].join(' ');
    let end = -1;
    for (let i = 1; i < raw.length; i++) {
      if (q === '"' && raw[i] === '\\') { i++; continue; }
      if (raw[i] === q) {
        if (q === "'" && raw[i + 1] === "'") { i++; continue; }
        end = i;
        break;
      }
    }
    const body = end > 0 ? raw.slice(1, end) : raw.slice(1);
    if (q === "'") return body.replace(/''/g, "'");
    try { return JSON.parse(`"${body}"`) as string; } catch { return body.replace(/\\(.)/g, '$1'); }
  }
  const head = uncomment(t);
  if (/^[>|][1-9+-]{0,2}$/.test(head)) return lines.join(head.startsWith('|') ? '\n' : ' ');
  return [head, ...lines.map(uncomment)].filter(Boolean).join(' ');
}

/** SKILL.md split into its frontmatter's name and description, the other frontmatter lines (kept
 *  as they are), and the body the editor shows. The indented lines that continue a name or a
 *  description are part of it: left among the other lines, they were written back under the quoted
 *  value the editor saves, which no YAML reader accepts. */
export function splitSkillMd(text: string): { name: string; description: string; rest: string[]; body: string } {
  const src = (text || '').replace(/^\uFEFF/, '');
  const m = /^---[ \t]*\r?\n([\s\S]*?)\r?\n---[ \t]*(\r?\n|$)/.exec(src.slice(0, FRONTMATTER_MAX));
  if (!m) return { name: '', description: '', rest: [], body: text || '' };
  const lines = m[1].split(/\r?\n/);
  let name = '', description = '';
  const rest: string[] = [];
  for (let i = 0; i < lines.length; i++) {
    const k = /^(name|description):\s*(.*)$/.exec(lines[i]);
    if (!k) { rest.push(lines[i]); continue; }
    // Its indented lines, and the blank lines between them (a block's second paragraph); a blank
    // line after the last one belongs to the frontmatter.
    let j = i + 1;
    while (j < lines.length && (/^\s+\S/.test(lines[j]) || !lines[j].trim())) j++;
    while (j > i + 1 && !lines[j - 1].trim()) j--;
    const more = lines.slice(i + 1, j);
    i = j - 1;
    const v = frontmatterValue(k[2], more);
    if (k[1] === 'name') name = v; else description = v;
  }
  return { name, description, rest, body: src.slice(m[0].length).replace(/^\r?\n/, '') };
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
