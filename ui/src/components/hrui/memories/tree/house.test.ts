// The Memories house rules, for this folder: no provider named, no native popup, no word for how the
// service is built, no dash as punctuation, and every style scoped to the console's root.
import { readdirSync, readFileSync } from 'fs';
import { join } from 'path';

const DIR = __dirname;
const read = (f: string) => readFileSync(join(DIR, f), 'utf8');
const sources = [...readdirSync(DIR).filter((f) => /\.(ts|tsx)$/.test(f) && !/\.test\./.test(f)), '../ResizableColumns.tsx'];
const code = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '').replace(/\s\/\/ .*$/gm, '');

test('no provider is named: what a memory can do comes from the capability document', () => {
  for (const f of sources) {
    expect([f, code(read(f)).match(/['"`](mem0|graphiti|hindsight|reme)['"`]/gi)]).toEqual([f, null]);
    expect([f, /\b(Mem0|Graphiti|Hindsight|ReMe)\b/.test(read(f))]).toEqual([f, false]);
  }
});
test('no native browser popup', () => {
  for (const f of sources) expect([f, /window\.(prompt|confirm|alert)|[^.\w](prompt|confirm|alert)\(/.test(code(read(f)))]).toEqual([f, false]);
});
test('no word for how anything is built, comments included: this is a public repository', () => {
  const WORDS = /vector ?graph|gremlin|cosmos|postgres|spanner|tenant|subgraph|azure|blob store|gateway|workflow engine|agentstudio|wrapper\.work|rebac/i;
  for (const f of sources) expect([f, WORDS.test(read(f))]).toEqual([f, false]);
});
test('no dash as punctuation in copy', () => {
  const dash = /'[^'\n;{}()]* - [^'\n;{}()]*'|`[^`\n;{}()]* - [^`\n;{}()]*`|>[^<{}=\n]* - [^<{}=\n]*<|–|\w ?— ?\w/;
  for (const f of sources) expect([f, code(read(f)).replace(/\$\{[^}]*\}/g, '').split('\n').filter((l) => dash.test(l))]).toEqual([f, []]);
});
test('every style is scoped to the console’s root', () => {
  for (const f of ['tree.css', 'columns.css']) {
    const css = read(f).replace(/\/\*[\s\S]*?\*\//g, '').replace(/@keyframes[^{]+\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}/g, '').replace(/@media[^{]+\{/g, '');
    const heads = css.split('}').map((r) => r.split('{')[0].trim()).filter(Boolean);
    for (const h of heads) expect([h, h.split(/,(?![^(]*\))/).every((x) => x.trim().startsWith('#hrui '))]).toEqual([h, true]);
  }
});
