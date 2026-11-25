// Hexa keeps localized navigation and adds runtime management only in the allowed editions.
import { readFileSync } from 'fs';
import { join } from 'path';

test('the base rail preserves Hexa navigation without the retired Start entry', () => {
  const src = readFileSync(join(__dirname, 'Shell.tsx'), 'utf8');
  const start = src.indexOf('const BASE_PLACES: Place[] = [');
  expect(start).toBeGreaterThan(-1);
  const list = src.slice(start, src.indexOf('];', start));
  const labels = Array.from(list.matchAll(/label: '([^']+)'/g)).map((m) => m[1]);
  expect(labels).toEqual(['工作台', '记忆', '扩展', 'Agent 商店', 'API 密钥']);
  expect(list).not.toContain("href: '/start'");
  expect(src).toContain("selfHosted ? [{ key: 'runners'");
  expect(src).toContain("selfHosted || showAdmin ? [{ key: 'uhp'");
});
