import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { latencyText, minutesAndSeconds, traceDurationText } from '@/lib/duration';

test('sixty seconds that have a minute beside them become one of it', () => {
  expect(minutesAndSeconds(119.7)).toEqual([2, 0]);
  expect(minutesAndSeconds(59.7)).toEqual([1, 0]);
  expect(minutesAndSeconds(90)).toEqual([1, 30]);
  expect(minutesAndSeconds(12.4)).toEqual([0, 12]);
});

test('the harness list latency carries at each of its edges', () => {
  // it read `1m 60s` at 119.7 and `60s` at 59.7, from Math.round(s - m * 60)
  expect(latencyText(119.7)).toBe('2m 0s');
  expect(latencyText(59.7)).toBe('1m 0s');
  expect(latencyText(9.96)).toBe('10s');
  expect(latencyText(4.24)).toBe('4.2s');
  expect(latencyText(42.4)).toBe('42s');
  expect(latencyText(72)).toBe('1m 12s');
});

test('a trace span duration carries at each of its edges', () => {
  expect(traceDurationText(0.9996)).toBe('1.0s');
  expect(traceDurationText(0.42)).toBe('420ms');
  expect(traceDurationText(59.96)).toBe('1m 0s');
  expect(traceDurationText(4.24)).toBe('4.2s');
  expect(traceDurationText(119.6)).toBe('2m 0s');
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
  // the `Math.floor(s / 60)` it is paired with to do it; nor does it have to be spelled with `%`
  // (`Math.round(s - m * 60)` is the same remainder). `minutesAndSeconds` is the one owner.
  const offenders = sources(join(__dirname, '..'))
    .filter((file) => !file.endsWith('lib/duration.ts'))
    .filter((file) => /Math\.round\([^)]*(%\s*60|-\s*\w+\s*\*\s*60)/.test(readFileSync(file, 'utf8')));
  expect(offenders).toEqual([]);
});
