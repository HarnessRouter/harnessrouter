// House rules read straight off the source. A provider's name decides nothing outside vendors.ts; no
// native browser popup; no word for how the service is built, and no dash as punctuation, in anything a
// person reads; and every style is scoped to the console's root.
import { readdirSync, readFileSync } from 'fs';
import { join } from 'path';

const DIR = __dirname;
const sources = readdirSync(DIR).filter((f) => /\.(ts|tsx)$/.test(f) && !/\.test\.|fixtures/.test(f));
const read = (f: string) => readFileSync(join(DIR, f), 'utf8');
/** What a person can read: JSX text and string literals, with comments gone. */
const code = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '').replace(/\s\/\/ .*$/gm, '').replace(/\{\/\*[\s\S]*?\*\/\}/g, '');

test('no provider is named outside vendors.ts: what a memory can do comes from the capability document', () => {
  for (const f of sources.filter((x) => x !== 'vendors.ts')) {
    expect([f, code(read(f)).match(/['"`](mem0|graphiti|hindsight|reme)['"`]/gi)]).toEqual([f, null]);
    expect([f, /\b(Mem0|Graphiti|Hindsight|ReMe)\b/.test(code(read(f)))]).toEqual([f, false]);
  }
});
test('no native browser popup', () => {
  for (const f of sources) expect([f, /window\.(prompt|confirm|alert)|[^.\w](prompt|confirm|alert)\(/.test(code(read(f)))]).toEqual([f, false]);
});
test('no word for how the service is built, in anything a person reads', () => {
  const INTERNAL = /['">`][^'"<`]*\b(vector ?graph|gremlin|cosmos|postgres|spanner|tenant|subgraph|azure|blob store|gateway|workflow engine)\b/i;
  for (const f of sources) expect([f, INTERNAL.test(code(read(f)))]).toEqual([f, false]);
});
test('no dash as punctuation in copy: only the honest dash that stands alone for a value not known', () => {
  const dash = /'[^'\n;{}()]* - [^'\n;{}()]*'|`[^`\n;{}()]* - [^`\n;{}()]*`|>[^<{}=\n]* - [^<{}=\n]*<|–|\w ?— ?\w/;
  for (const f of sources) {
    const lines = code(read(f)).replace(/\$\{[^}]*\}/g, '').split('\n').filter((l) => dash.test(l));
    expect([f, lines]).toEqual([f, []]);
  }
});
test('the measured lines name no provider', () => {
  const caps = read('caps.ts');
  for (const name of ['TYPES_LINE', 'RELATIONS_LINE', 'NO_RELATIONS_LINE']) {
    const line = new RegExp(`${name} = '([^']+)'`).exec(caps)?.[1] || '';
    expect(line.length).toBeGreaterThan(20);
    expect(line).not.toMatch(/vendorName|\$\{/);
  }
});
test('every style is scoped to the console’s root', () => {
  const css = readFileSync(join(DIR, 'memories.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
  // a comma inside a value (a shadow, a function) is not a selector: only what opens a rule counts
  const heads = css.replace(/@(?:media|container)[^{]+\{/g, '').split('}').map((r) => r.split('{')[0].trim()).filter(Boolean);
  for (const h of heads) expect([h, h.split(/,(?![^(]*\))/).every((x) => x.trim().startsWith('#hrui '))]).toEqual([h, true]);
});
test('the narrow rules the design has are kept', () => {
  const css = readFileSync(join(DIR, 'memories.css'), 'utf8');
  for (const q of ['max-width:1180px', 'max-width:860px', 'max-width:560px']) expect(css).toContain(`@media (${q})`);
});
