// A kit's app out of the image, and the old address of a kit that was renamed: an id in a kit's
// `aliases` goes on to the same page under the kit's current id, its query kept.
import { mkdtempSync, mkdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { NextRequest } from 'next/server';

const dir = mkdtempSync(path.join(tmpdir(), 'kits-'));
writeFileSync(path.join(dir, 'manifest.json'), JSON.stringify({ kits: ['slides', 'harness-bot'] }));
for (const [id, aliases] of [['slides', []], ['harness-bot', ['workplace']]] as const) {
  mkdirSync(path.join(dir, id, 'app'), { recursive: true });
  writeFileSync(path.join(dir, id, 'kit.json'), JSON.stringify({ id, aliases }));
  writeFileSync(path.join(dir, id, 'app', 'index.html'), `<title>${id}</title>`);
}
process.env.HR_KITS_DIR = dir;
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { GET } = require('./route') as typeof import('./route');

const get = (url: string, kit: string, rest?: string[]) =>
  GET(new NextRequest(`http://console.local${url}`), { params: Promise.resolve({ kit, path: rest }) });

test('a kit serves its own app, and a client route falls back to its index', async () => {
  const r = await get('/kits/harness-bot/dm/chrn_1', 'harness-bot', ['dm', 'chrn_1']);
  expect(r.status).toBe(200);
  expect(await r.text()).toBe('<title>harness-bot</title>');
});

test('an old id of a renamed kit goes on to the same page under the current id', async () => {
  const r = await get('/kits/workplace/group/s%201?x=1', 'workplace', ['group', 's 1']);
  expect(r.status).toBe(308);
  expect(r.headers.get('location')).toBe('/kits/harness-bot/group/s%201?x=1');
  const home = await get('/kits/workplace', 'workplace');
  expect(home.status).toBe(308);
  expect(home.headers.get('location')).toBe('/kits/harness-bot/');
});

test('an id no kit has, or had, is not found', async () => {
  expect((await get('/kits/nothing/', 'nothing')).status).toBe(404);
  expect((await get('/kits/..%2Fetc/', '../etc')).status).toBe(404);
});
