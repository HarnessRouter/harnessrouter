// Where an older console address lives now: a bookmark, a link in the docs or an older script's URL lands on
// its place in this console, answered by the server before anything loads (src/middleware.ts).
import { readFileSync } from 'fs';
import { join } from 'path';
import { movedTo } from './moved';

const q = (s = '') => new URLSearchParams(s);

test('a harness and a task open in Studio, by the same names', () => {
  expect(movedTo('/harnesses', q())).toBe('/studio');
  expect(movedTo('/tasks', q())).toBe('/studio');
  expect(movedTo('/harnesses', q('h=hrn_1&sid=hsess_2'))).toBe('/studio/hrn_1?test=hsess_2');
  expect(movedTo('/tasks', q('h=hrn_1&sid=hsess_2'))).toBe('/studio/hrn_1?test=hsess_2');
  expect(movedTo('/harnesses', q('h=hrn_1&view=settings'))).toBe('/studio/hrn_1?tab=settings');
  expect(movedTo('/harnesses/hrn_1', q())).toBe('/studio/hrn_1');
});

test('the other pages open their places', () => {
  expect(movedTo('/quickstart', q())).toBe('/start');
  expect(movedTo('/dashboard', q())).toBe('/start');
  expect(movedTo('/overview', q())).toBe('/start');
  expect(movedTo('/kits', q())).toBe('/shop');
  expect(movedTo('/environments', q())).toBe('/extensions?tab=envs');
  expect(movedTo('/environments/henv_1', q())).toBe('/extensions?tab=envs&env=henv_1');
});

test('a sign-in that comes back to an old address keeps its answer', () => {
  // Microsoft 365 returns to /plugins (the address the self-hosting guide registers), and a connection's
  // hand-off to /integrations: the code and state ride along
  expect(movedTo('/plugins', q())).toBe('/extensions');
  expect(movedTo('/plugins', q('code=c1&state=s1'))).toBe('/extensions?code=c1&state=s1');
  expect(movedTo('/integrations', q('code=c1'))).toBe('/byok?code=c1');
});

test('a page of this console keeps its own address', () => {
  for (const p of ['/start', '/studio', '/studio/hrn_1', '/shop', '/extensions', '/keys', '/byok', '/profile', '/agents', '/login', '/settings']) {
    expect(movedTo(p, q())).toBeNull();
  }
});

test('the server answers the redirect, before the sign-in gate', () => {
  const src = readFileSync(join(__dirname, '..', '..', 'middleware.ts'), 'utf8');
  expect(src.indexOf('movedTo(')).toBeGreaterThan(-1);
  expect(src.indexOf('movedTo(')).toBeLessThan(src.indexOf('sessionValid('));
});
