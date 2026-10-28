// One bar for a setup, before it exists and after (as on the hosted console): every header the console draws as a setup's
// bar is the right-aligned one (`ag-bar ag-rt`: the name on the left, the tabs at its right end), and its tabs carry the
// same icons, so the building page can never draw a bar of its own again.
import { readdirSync, readFileSync, statSync } from 'fs';
import { join, relative } from 'path';

const SRC = join(__dirname, '../../..');
function files(dir: string): string[] {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    if (statSync(p).isDirectory()) return files(p);
    return /\.tsx$/.test(n) && !/\.test\.tsx$/.test(n) ? [p] : [];
  });
}
const BARS = ['components/hrui', 'app/(app)/studio'].flatMap((d) => files(join(SRC, d))).flatMap((p) =>
  readFileSync(p, 'utf8').split('\n').map((text, i) => ({ file: relative(SRC, p), n: i + 1, text }))
    .filter((l) => /className="ag-bar[" ]/.test(l.text)));

test('every setup bar is the right-aligned bar', () => {
  expect(BARS.length).toBeGreaterThanOrEqual(3);                           // the setup page's, its loading bar and the building page's
  expect(BARS.filter((l) => !/className="ag-bar ag-rt"/.test(l.text)).map((l) => `${l.file}:${l.n}`)).toEqual([]);
});

test('the building page\'s tabs carry the setup page\'s icons', () => {
  const build = readFileSync(join(SRC, 'components/hrui/start/BuildPage.tsx'), 'utf8');
  expect(build).toContain('{TASKS_IC}Tasks');
  expect(build).toContain('{SETTINGS_IC}Settings');
});
