/** @jest-environment jsdom */
// A setup built while the person is elsewhere (start/build.ts tellList, pickUpBuilds). The server goes on
// with a build whatever page the person is on and saves the setup there; the setups list on screen has to
// hear of it. A build this page still follows tells the list as it lands. One left by a page load is asked
// for by its key when Harness Studio opens, and, saved, lands the same way; it is only read, never
// started again, and one the server has no record of, or that failed, is left as it is.
jest.mock('@/lib/harness', () => ({ createCustom: jest.fn(), getCustom: jest.fn(), listCustom: jest.fn() }));
jest.mock('@/lib/plugs', () => ({ setHarnessPlugs: jest.fn() }));
jest.mock('@/lib/workspace', () => ({ getCurrentWorkspaceRef: () => ({ id: 'ws_1' }) }));
jest.mock('@/lib/analytics', () => ({ track: jest.fn() }));
jest.mock('../toast', () => ({ toast: jest.fn() }));
jest.mock('./compose', () => ({ ...jest.requireActual('./compose'), startServerBuild: jest.fn(), readServerBuild: jest.fn() }));
jest.mock('./replay', () => ({ ...jest.requireActual('./replay'), loadRecording: jest.fn() }));

import { createCustom, getCustom, listCustom } from '@/lib/harness';
import { SETUPS_EVENT } from '../setups';
import { pickUpBuilds, resumeBuild, startBuild, type BuildInput } from './build';
import { takeFirstTest } from './check';
import { readServerBuild, startServerBuild } from './compose';
import { loadRecording } from './replay';

const start = startServerBuild as jest.Mock;
const read = readServerBuild as jest.Mock;
const create = createCustom as jest.Mock;

const CFG = {
  name: 'Greetings', instructions: 'Greet each user with one short friendly line.', exampleTask: 'Hello there',
  base: 'hermes', baseName: 'Hermes', model: 'gpt-6.1-sol', skills: [], plugins: [], connectionsNeeded: [],
};
const building = (step: string) => ({ key: 'k', status: 'building', step, setupId: '', config: null, attached: {}, reason: '' });
const saved = { key: 'k', status: 'saved', step: '', setupId: 'chrn_left', config: CFG, attached: {}, reason: '' };
const IN: BuildInput = { job: 'Greet each user with one short friendly line.', base: 'auto', model: 'auto', baseName: 'auto', demo: null, pick: { baseName: '', model: '' } };

let told: (string | undefined)[];
const hear = (e: Event) => { told.push((e as CustomEvent<{ id?: string }>).detail?.id); };
const settle = async () => { for (let i = 0; i < 40; i++) await new Promise((r) => setTimeout(r, 0)); };
/** A build this tab kept before a page load: what was asked, under its key, and nothing more. */
const leftBy = (key: string, extra: object = {}) => sessionStorage.setItem(`hr.build:${key}`, JSON.stringify({ v: 1, key, at: Date.now(), input: IN, ...extra }));
const kept = (key: string) => JSON.parse(sessionStorage.getItem(`hr.build:${key}`) || 'null');

beforeEach(() => {
  [start, read, create, getCustom as jest.Mock, listCustom as jest.Mock, loadRecording as jest.Mock].forEach((m) => m.mockReset());
  (loadRecording as jest.Mock).mockResolvedValue(null);
  (listCustom as jest.Mock).mockResolvedValue([]);
  (getCustom as jest.Mock).mockResolvedValue({ id: 'chrn_left', name: CFG.name, base: 'hermes' });
  sessionStorage.clear();
  told = [];
  window.addEventListener(SETUPS_EVENT, hear);
});
afterEach(() => { window.removeEventListener(SETUPS_EVENT, hear); });

test('a build this page follows tells the setups list, by its id, as the server saves it', async () => {
  start.mockResolvedValue(building('writing'));
  read.mockResolvedValueOnce(building('saving')).mockResolvedValueOnce(saved);
  const b = startBuild(IN);
  resumeBuild(b.key);
  // Studio opened meanwhile: this page follows it already, so it is not asked for again
  pickUpBuilds();
  await settle();
  expect(read).toHaveBeenCalledTimes(2);
  expect(told).toEqual(['chrn_left']);
});

test('a build left by a page load is asked for by its key as Studio opens, followed, and its setup lands in the list', async () => {
  leftBy('bleft0001');
  read.mockResolvedValueOnce(building('writing')).mockResolvedValueOnce(saved);
  pickUpBuilds();
  await settle();
  // read only: the first read answers at once, the next waits on where the record stood
  expect(read.mock.calls.map((c) => [c[0], c[2] ?? ''])).toEqual([['bleft0001', ''], ['bleft0001', 'building.writing']]);
  expect(start).not.toHaveBeenCalled();
  expect(create).not.toHaveBeenCalled();
  expect(told).toEqual(['chrn_left']);
  // taken as saved: kept done with its setup, and its example request waits in the setup's box
  expect(kept('bleft0001')).toMatchObject({ id: 'chrn_left', done: true });
  expect(takeFirstTest('chrn_left')).toMatchObject({ input: CFG.exampleTask, send: false });
  // asked once: Studio opened again reads nothing more
  pickUpBuilds();
  await settle();
  expect(read).toHaveBeenCalledTimes(2);
});

test('one the server has no record of, or that failed, is left as it is: nothing is started, saved or told', async () => {
  leftBy('bnone0001');
  leftBy('bfail0001');
  read.mockImplementation(async (key: string) => (key === 'bfail0001' ? { ...saved, status: 'failed', setupId: '', reason: 'No model' } : null));
  pickUpBuilds();
  await settle();
  expect(read).toHaveBeenCalledTimes(2);
  expect(start).not.toHaveBeenCalled();
  expect(create).not.toHaveBeenCalled();
  expect(told).toEqual([]);
  expect(kept('bnone0001')).not.toHaveProperty('done');
  expect(kept('bfail0001')).not.toHaveProperty('done');
});

test('a demo preset from its recording, a build already saved and one that failed here are not asked for', async () => {
  leftBy('bdemo0001', { preset: true, composed: true, cfg: CFG });
  leftBy('bdone0001', { id: 'chrn_done', done: true });
  leftBy('berr00001', { error: 'Your setup couldn’t be saved just now.' });
  pickUpBuilds();
  await settle();
  expect(read).not.toHaveBeenCalled();
  expect(told).toEqual([]);
});

test('a read that could not be made is asked again the next time Studio opens', async () => {
  leftBy('bnet00001');
  read.mockRejectedValueOnce(new Error('502')).mockResolvedValueOnce(saved);
  pickUpBuilds();
  await settle();
  expect(told).toEqual([]);
  pickUpBuilds();
  await settle();
  expect(read).toHaveBeenCalledTimes(2);
  expect(told).toEqual(['chrn_left']);
});
