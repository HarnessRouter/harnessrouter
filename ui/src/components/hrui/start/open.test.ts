// The one post-create path (Richard, 2026-10-19: "无论什么情况下 ... 都应该进入到 Task 界面里面去 ... 把所有这种
// 旁路全都去掉"). After any create, the only destination is that setup's Tasks, through openNewSetup
// (start/open.ts):
//   1. every file in the console's redesign that makes a setup (createCustom, launchKit) opens what it
//      made through openNewSetup, itself or through the one page that lands it;
//   2. in Harness Studio's own files, every Studio address and every navigation to an address worked out
//      at run time is listed with why it is not a landing after a create (a new one fails this test
//      until it is reviewed);
//   3. openNewSetup goes to the setup's own page.
import { readdirSync, readFileSync, statSync } from 'fs';
import { join, relative } from 'path';

jest.mock('./seed', () => ({ markMade: jest.fn() }));

import { markMade } from './seed';
import { newSetupHref, openNewSetup } from './open';

const SRC = join(__dirname, '../../..');

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    if (statSync(p).isDirectory()) return files(p);
    return /\.(ts|tsx)$/.test(n) && !/\.test\.(ts|tsx)$/.test(n) ? [p] : [];
  });
}
interface Line { file: string; n: number; text: string }
const linesOf = (dirs: string[]): Line[] => dirs.flatMap((d) => {
  const p = join(SRC, d);
  return statSync(p).isDirectory() ? files(p) : [p];
}).flatMap((p) => {
  const file = relative(SRC, p);
  return readFileSync(p, 'utf8').split('\n').map((text, i) => ({ file, n: i + 1, text }))
    // comments may name addresses; only code navigates
    .filter((l) => !/^\s*(\/\/|\*|\/\*)/.test(l.text));
});

type Entry = [file: string, needle: string, why: string];
/** Each finding must be one of these; each of these must still be found (no stale entries). */
function check(found: Line[], allowed: Entry[]) {
  const used = new Set<number>();
  const stray = found.filter((l) => {
    const i = allowed.findIndex(([f, needle]) => f === l.file && l.text.includes(needle));
    if (i >= 0) used.add(i);
    return i < 0;
  }).map((l) => `${l.file}:${l.n}  ${l.text.trim().slice(0, 140)}`);
  expect(stray).toEqual([]);
  expect(allowed.filter((_, i) => !used.has(i)).map(([f, needle]) => `${f}  ${needle}`)).toEqual([]);
}

// ── 1. every create path lands through openNewSetup ───────────────────────────────────────────────
const ALL = linesOf(['components/hrui', 'app/(app)']);
const CREATE = /\b(createCustom|launchKit)\(/;
/** a file that makes a setup but leaves the landing to the page that opened it */
const LANDS: Record<string, string> = {
  'components/hrui/setup/settingsSheets.tsx': 'components/hrui/setup/SetupSettings.tsx',   // Duplicate
  'components/hrui/shop/LaunchSheet.tsx': 'components/hrui/shop/KitTry.tsx',               // a kit launched to users
};

describe('after any create, the only destination is that setup’s Tasks', () => {
  test('each file that makes a setup opens it through openNewSetup, itself or through the page that lands it', () => {
    const opens = (f: string) => ALL.some((l) => l.file === f && /\bopenNewSetup\(\s*router\s*,/.test(l.text));
    const makers = [...new Set(ALL.filter((l) => CREATE.test(l.text) && !/\b(function|async function)\s+(createCustom|launchKit)\b/.test(l.text)).map((l) => l.file))];
    expect(makers.length).toBeGreaterThan(0);
    const missing = makers.filter((f) => !opens(LANDS[f] || f)).map((f) => `${f} makes a setup and ${LANDS[f] || 'it'} never calls openNewSetup`);
    expect(missing).toEqual([]);
  });
});

// ── 2. Harness Studio's own addresses, and addresses worked out at run time ──────────────────────
const MINE = linesOf(['app/(app)/studio', 'components/hrui/setup', 'components/hrui/setups.ts', 'components/hrui/SetUpApp.tsx', 'components/hrui/start/open.ts']);
const STUDIO = /['"`]\/studio(?=['"`?/]|\$\{)/;
const STUDIO_ALLOWED: Entry[] = [
  ['components/hrui/start/open.ts', '`/studio/${encodeURIComponent(to.id)}`', 'the one way into a setup just made'],
  ['components/hrui/setup/SetupSettings.tsx', "toast(`${rec.name} deleted`); router.push('/studio')", 'the setup was deleted: it has no page any more'],
  ['components/hrui/setup/parts.tsx', 'className="ag-back" href="/studio"', 'a setup page’s Back, pressed'],
  ['app/(app)/studio/page.tsx', 'const setupHref = ', 'a setup’s card on Harness Studio, pressed'],
  ['app/(app)/studio/page.tsx', "router.replace('/studio', { scroll: false })", 'Studio takes ?new=1 out of its own address as it opens New setup'],
  ['app/(app)/studio/[id]/page.tsx', "rawTab === 'playground') router.replace(`/studio/${enc(id)}", 'the setup’s own address (an old tab name)'],
  ['app/(app)/studio/[id]/page.tsx', 'const pgHref = ', 'the setup’s own address (the open task)'],
  ['app/(app)/studio/[id]/page.tsx', ": `/studio/${enc(id)}?tab=${t}`", 'the setup’s own address (its tab)'],
  ['app/(app)/studio/[id]/page.tsx', 'router.replace(`/studio/${enc(id)}?tab=settings&layer=', 'the setup’s own address (Settings’ layer)'],
  ['app/(app)/studio/[id]/page.tsx', 'This setup is not in this workspace. <a className="link-q inl" href="/studio">', 'a setup that is not here: Back, pressed'],
];
/** A navigation whose address is worked out at run time (it could be anywhere). */
const RUNTIME = /(router\.(push|replace)|location\.(assign|replace))\(\s*(?![`'"]\/)|location\.href\s*=\s*(?![`'"]\/)/;
const RUNTIME_ALLOWED: Entry[] = [
  ['app/(app)/studio/[id]/page.tsx', 'router.replace(pgHref(', 'the setup’s own address (the open task)'],
  ['app/(app)/studio/[id]/page.tsx', "router.replace(t === 'tasks' ? pgHref(testSid)", 'the setup’s own address (its tab)'],
];

describe('Harness Studio is never where a create lands', () => {
  test('every Studio address in Studio’s own files is one of these, none of them after a create', () => {
    check(MINE.filter((l) => STUDIO.test(l.text)), STUDIO_ALLOWED);
  });
  test('every navigation to an address worked out at run time is one of these', () => {
    check(MINE.filter((l) => RUNTIME.test(l.text)), RUNTIME_ALLOWED);
  });
});

// ── 3. the one way ─────────────────────────────────────────────────────────────────────────────
describe('openNewSetup', () => {
  test('opens the setup’s own Tasks by its id, and its page waits for it rather than call it missing', () => {
    expect(newSetupHref({ id: 'chrn_a b' })).toBe('/studio/chrn_a%20b');
    const n = { push: jest.fn(), replace: jest.fn() };
    openNewSetup(n, { id: 'chrn_a' });
    expect(n.push).toHaveBeenCalledWith('/studio/chrn_a');
    expect(n.replace).not.toHaveBeenCalled();
    expect(markMade).toHaveBeenCalledWith('chrn_a');
  });
});
