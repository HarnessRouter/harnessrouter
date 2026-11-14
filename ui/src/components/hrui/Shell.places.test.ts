// The rail's words, the hosted console's too (Richard, 11-14): Studio is Harness, and every word is singular. This
// console has no Arena or Usage. Memory shows only where memory is on.
import { readFileSync } from 'fs';
import { join } from 'path';

test('the rail reads Start, Harness, Memory, Add-on, Shop, API Key', () => {
  const src = readFileSync(join(__dirname, 'Shell.tsx'), 'utf8');
  const list = src.slice(src.indexOf('const PLACES: Place[] = ['), src.indexOf('];', src.indexOf('const PLACES: Place[] = [')));
  const labels = Array.from(list.matchAll(/label: '([^']+)'/g)).map((m) => m[1]);
  expect(labels).toEqual(['Start', 'Harness', 'Memory', 'Add-on', 'Shop', 'API Key']);
});
