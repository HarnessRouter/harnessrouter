// The columns are ResizableColumns' to place. A column moved off to one side by a rule of its own, from when these were
// drawers, stays there with nothing overflowing, so a page can look fine to a check and show an empty column to a person.
import { readFileSync } from 'fs';
import { join } from 'path';

const css = readFileSync(join(__dirname, 'memories.css'), 'utf8');

test.each(['.mm-conn', '.mm-doc', '.mm-graphbox'])('%s takes its place from the column it is in', (sel) => {
  const rules = css.match(new RegExp(`\\${sel}\\{[^}]*\\}`, 'g')) || [];
  for (const r of rules) expect(r).not.toMatch(/position:\s*(absolute|fixed)|transform:|visibility:\s*hidden/);
});

test('nothing styles the drawers these columns replaced', () => {
  expect(css).not.toMatch(/conn-open|tree-open|mm-scrim|mm-dtog|mm-ctog|no-conn/);
});

test('a memory’s name and description are one column: the name on its row, the description and its help on the next', () => {
  const rule = (css.match(/#hrui \.mm-nf\{[^}]*\}/) || [''])[0];
  expect(rule).toContain('grid-template-columns:minmax(0,1fr);');
  expect(rule).not.toMatch(/minmax\(0,1fr\) minmax/);
});

test('a memory’s picture is contained and centred in its box, and the list’s small one never takes Studio’s own .mini', () => {
  const rule = (sel: string) => (css.match(new RegExp(`${sel.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\{[^}]*\\}`)) || [''])[0];
  expect(rule('#hrui .mm-cover')).toMatch(/object-fit:contain/);
  expect(rule('#hrui .mm-cover')).toMatch(/object-position:center/);
  expect(rule('#hrui .mm-mini-box .mm-cover')).toMatch(/width:100%;height:100%/);
  expect(css).not.toMatch(/\.mm-(cv|brick|cv-wait)\.mini\b/);
});
