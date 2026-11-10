// The console resets everything inside #hrui (`all:revert`, keyed on the ID, in hrui.css), so a rule of plain classes
// never reaches an element in it. A CSS module there is dead on arrival: what it draws (an editor's menu, its handles)
// shows as unstyled text and buttons. Console styles are written under #hrui; a third-party widget sits in a
// `hrui-legacy` box (CodeEditor.tsx).
import { readdirSync, readFileSync, statSync } from 'fs';
import { join, relative } from 'path';

const walk = (dir: string): string[] =>
  readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
const files = walk(__dirname).map((f) => relative(__dirname, f));

test('the reset is keyed on #hrui', () => {
  expect(readFileSync(join(__dirname, 'hrui.css'), 'utf8')).toMatch(/#hrui :where\(:not\(\.hrui-legacy[^{]*\{all:revert\}/);
});

test('no CSS module in the console', () => {
  expect(files.filter((f) => f.endsWith('.module.css'))).toEqual([]);
});

test('nothing in the console imports a CSS module', () => {
  const importing = files
    .filter((f) => /\.(t|j)sx?$/.test(f))
    .filter((f) => /from\s+['"][^'"]+\.module\.css['"]/.test(readFileSync(join(__dirname, f), 'utf8')));
  expect(importing).toEqual([]);
});
