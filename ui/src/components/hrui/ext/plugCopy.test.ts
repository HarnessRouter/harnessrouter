// The words and marks beside each plugin this instance serves (the gateway's _PLUG_FORMS): every one
// has its line, its paragraph and a mark that is really there, every field a form asks for has a
// label, and no word is written with a dash.
import { existsSync } from 'fs';
import { join } from 'path';
import { ABOUT, BLURB, FIELD, M365_MODES, MARK, REQUIRED, SHOWN } from './plugCopy';

const SERVED = ['browser', 'github', 'vercel', 'insforge', 'microsoft365'];

test('every plugin the server serves has its words and a mark that exists', () => {
  for (const t of SERVED) {
    expect(BLURB[t]).toBeTruthy();
    expect(ABOUT[t]).toBeTruthy();
    expect(MARK[t]).toBeTruthy();
    expect(existsSync(join(__dirname, '../../../../public', MARK[t].src))).toBe(true);
  }
});

test('every field a plugin cannot connect without has a label', () => {
  for (const names of Object.values(REQUIRED)) for (const n of names) expect(FIELD[n]?.label).toBeTruthy();
});

test('no dash in anything a person reads', () => {
  const all = [
    ...Object.values(BLURB), ...Object.values(ABOUT), ...M365_MODES.map(([, t]) => t),
    ...Object.values(FIELD).flatMap((f) => [f.label, f.hint || '']), ...Object.values(SHOWN).flatMap((l) => l.map(([, t]) => t)),
  ];
  for (const s of all) expect(s).not.toMatch(/[–—]| - /);
});
