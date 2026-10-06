import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { minutesAndSeconds } from '@/lib/duration';

test('sixty seconds that have a minute beside them become one of it', () => {
  expect(minutesAndSeconds(119.7)).toEqual([2, 0]);
  expect(minutesAndSeconds(59.7)).toEqual([1, 0]);
  expect(minutesAndSeconds(90)).toEqual([1, 30]);
  expect(minutesAndSeconds(12.4)).toEqual([0, 12]);
});

/** Every file under src, as the rule is repo-wide rather than one module's. */
function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.(ts|tsx|js|jsx)$/.test(name) && !name.includes('.test.') ? [path] : [];
  });
}

test('no duration in the console rounds its seconds half out of the minute it is in', () => {
  // `Math.round(s % 60)` can name sixty seconds, and it does not have to sit on the same line as
  // the `Math.floor(s / 60)` it is paired with to do it. `minutesAndSeconds` is the one owner.
  const offenders = sources(join(__dirname, '..'))
    .filter((file) => !file.endsWith('lib/duration.ts'))
    .filter((file) => /Math\.round\([^)]*%\s*60/.test(readFileSync(file, 'utf8')));
  expect(offenders).toEqual([]);
});
