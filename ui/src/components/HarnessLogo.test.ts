import fs from 'fs';
import path from 'path';
import { harnessLogoSrc } from './HarnessLogo';

// Every base of open source 0.37.0's batch draws its own mark, and the file the map names is there.
test.each(['vibe', 'docker-agent', 'fast-agent', 'dcode'])('%s has a mark that exists', (id) => {
  const src = harnessLogoSrc(id);
  expect(src).toMatch(/^\/logos\/.+\.(svg|png)$/);
  expect(fs.existsSync(path.join(__dirname, '..', '..', 'public', src))).toBe(true);
});

test('a base with no mark draws none', () => {
  expect(harnessLogoSrc('no-such-base')).toBe('');
});
