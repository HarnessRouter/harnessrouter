// A new setup's build, end to end in the console (start/build.ts), with the server's answers as
// fixtures: a sentence is built and saved by the server, followed by long poll until it is saved, and
// its example request is handed to the setup's first task to wait in the box (never sent, never the
// sentence); a refusal or a failed build is said where the setup would be, and nothing is saved in its
// place; an unchanged demo on its recording's pair is preset from the recording's template and saved by
// the console with the recording named on it, and its request plays the recording when sent; a demo on
// another pair, or one whose recording ran on what this edition cannot add, is built like any setup.
jest.mock('@/lib/harness', () => ({ createCustom: jest.fn(), getCustom: jest.fn(), listCustom: jest.fn() }));
jest.mock('@/lib/plugs', () => ({ setHarnessPlugs: jest.fn() }));
jest.mock('@/lib/workspace', () => ({ getCurrentWorkspaceRef: () => ({ id: 'ws_1' }) }));
jest.mock('@/lib/analytics', () => ({ track: jest.fn() }));
jest.mock('../toast', () => ({ toast: jest.fn() }));
jest.mock('./compose', () => ({ ...jest.requireActual('./compose'), startServerBuild: jest.fn(), readServerBuild: jest.fn() }));
jest.mock('./replay', () => ({ ...jest.requireActual('./replay'), loadRecording: jest.fn() }));

import { createCustom, getCustom, listCustom } from '@/lib/harness';
import { resumeBuild, startBuild, type Build, type BuildInput } from './build';
import { takeFirstTest } from './check';
import { BuildRefused, readServerBuild, startServerBuild } from './compose';
import { DEMOS } from './demos';
import { loadRecording, type RecordedRun } from './replay';

const start = startServerBuild as jest.Mock;
const read = readServerBuild as jest.Mock;
const create = createCustom as jest.Mock;
const rec = loadRecording as jest.Mock;

const JOB = '构建一个美国 Single Family House 施工合同审阅的智能体，能够对合同进行 redlining';
const CFG = {
  name: '合同红线审阅', instructions: '你负责审阅用户发来的美国独栋住宅施工合同条款，逐条标出风险并给出修改建议。',
  exampleTask: '请审阅这份施工合同的付款与变更条款，并给出红线修改。',
  base: 'hermes', baseName: 'Hermes', model: 'gpt-6.1-sol', skills: [], plugins: [], connectionsNeeded: [],
};
const building = (step: string, extra: object = {}) => ({ key: 'k', status: 'building', step, setupId: '', config: null, attached: {}, reason: '', ...extra });
const saved = { key: 'k', status: 'saved', step: '', setupId: 'chrn_built', config: CFG, attached: {}, reason: '' };
const AUTO_IN: BuildInput = { job: JOB, base: 'auto', model: 'auto', baseName: 'auto', demo: null, pick: { baseName: '', model: '' } };

const RUN = {
  demo: 0, ranAt: 1792378362430, base: 'hermes', model: 'gpt-5.4', request: 'A matte black ceramic mug with a bamboo lid.',
  durMs: 7000, status: 'completed', events: [{ t: 0, ev: { type: 'response.created' } }], files: [],
  template: {
    demo: 0, name: 'Product images', base: 'hermes', model: 'gpt-5.4', instructions: DEMOS[0].instr,
    skills: [{ id: 'product-shot-style', name: 'Product shot style', body: 'Square.',
      skill: { name: 'product-shot-style', enabled: true, files: [{ path: 'SKILL.md', content: 'Square.' }] } }],
    plugins: [{ id: 'media', name: 'Image generation' }],
  },
} as unknown as RecordedRun;
const DEMO_IN: BuildInput = { job: DEMOS[0].instr, base: 'hermes', model: 'gpt-5.4', baseName: 'Hermes', demo: 0, pick: { baseName: 'Hermes', model: 'gpt-5.4' } };

/** The build at this key once its work has gone as far as it can on the answers given. */
async function settle(key: string): Promise<Build> {
  for (let i = 0; i < 40; i++) await new Promise((r) => setTimeout(r, 0));
  return resumeBuild(key) as Build;
}

beforeEach(() => {
  [start, read, create, rec, getCustom as jest.Mock, listCustom as jest.Mock].forEach((m) => m.mockReset());
  rec.mockResolvedValue(null);
  (listCustom as jest.Mock).mockResolvedValue([]);
  (getCustom as jest.Mock).mockResolvedValue({ id: 'chrn_built', name: CFG.name, base: 'hermes' });
});

test('a sentence is built and saved by the server: followed by long poll, its example request handed to the box', async () => {
  start.mockResolvedValue(building('reading'));
  read.mockResolvedValueOnce(building('writing')).mockResolvedValueOnce(building('saving', { config: CFG })).mockResolvedValueOnce(saved);
  const b = startBuild(AUTO_IN);
  resumeBuild(b.key);
  const end = await settle(b.key);
  expect(start).toHaveBeenCalledWith(b.key, JOB, { base: 'auto', model: 'auto', baseName: 'auto' }, 'ws_1');
  // each read names where the record it last drew stood: the server answers once it stands elsewhere
  expect(read.mock.calls.map((c) => c[2])).toEqual(['building.reading', 'building.writing', 'building.saving']);
  expect(end).toMatchObject({ phase: 'done', id: 'chrn_built', first: { input: CFG.exampleTask, send: false } });
  expect(end.asm?.cfg.instructions).toBe(CFG.instructions);
  // the setup's first test waits in its box: the build's request, never the sentence, never sent for them
  expect(takeFirstTest('chrn_built')).toMatchObject({ input: CFG.exampleTask, send: false, setup: true });
  expect(create).not.toHaveBeenCalled();
});

test('a build the server refuses is said where the setup would be, in its words, and nothing is saved', async () => {
  start.mockRejectedValue(new BuildRefused('Connect a model key first: the setup is built with one of your models.'));
  const b = startBuild(AUTO_IN);
  resumeBuild(b.key);
  const end = await settle(b.key);
  expect(end).toMatchObject({ phase: 'failed', error: 'Connect a model key first: the setup is built with one of your models.', id: '' });
  expect(create).not.toHaveBeenCalled();
});

test('a build that failed on the server says its reason; one with none says it could not be built', async () => {
  start.mockResolvedValue(building('reading'));
  read.mockResolvedValueOnce({ ...saved, status: 'failed', setupId: '', config: null, reason: 'Building the setup took too long. Nothing was saved. Try again.' });
  const b = startBuild(AUTO_IN);
  resumeBuild(b.key);
  expect(await settle(b.key)).toMatchObject({ phase: 'failed', error: 'Building the setup took too long. Nothing was saved. Try again.' });
  start.mockResolvedValue({ ...saved, status: 'failed', setupId: '', config: null, reason: '' });
  const c = startBuild(AUTO_IN);
  resumeBuild(c.key);
  expect(await settle(c.key)).toMatchObject({ phase: 'failed', error: 'Your setup couldn’t be built just now.' });
});

test('a build the server has no record of (it restarted) is asked for again under the same key', async () => {
  start.mockResolvedValueOnce(building('reading')).mockResolvedValueOnce(saved);
  read.mockResolvedValueOnce(null);
  const b = startBuild(AUTO_IN);
  resumeBuild(b.key);
  expect(await settle(b.key)).toMatchObject({ phase: 'done', id: 'chrn_built' });
  expect(start.mock.calls.map((c) => c[0])).toEqual([b.key, b.key]);
});

test('an unchanged demo on its recording’s pair is preset from the template and saved here, naming the recording', async () => {
  rec.mockResolvedValue(RUN);
  create.mockResolvedValue({ id: 'chrn_demo', name: 'Product images', base: 'hermes', source: 'demo:0@1792378362430' });
  const b = startBuild(DEMO_IN);
  resumeBuild(b.key);
  const end = await settle(b.key);
  expect(start).not.toHaveBeenCalled();
  expect(create).toHaveBeenCalledTimes(1);
  const body = create.mock.calls[0][0];
  expect(body).toMatchObject({ name: 'Product images', base: 'hermes', defaultModel: 'gpt-5.4', systemPrompt: DEMOS[0].instr, source: 'demo:0@1792378362430' });
  expect(body.skills).toEqual([{ id: expect.stringMatching(/^skl_[a-z0-9]+$/i), name: 'product-shot-style', enabled: true, files: [{ path: 'SKILL.md', content: 'Square.' }] }]);
  // the request the recording ran waits in the box, and sent as it is plays the recording
  expect(end).toMatchObject({ phase: 'done', id: 'chrn_demo', first: { input: RUN.request, send: false }, recording: RUN });
  expect(takeFirstTest('chrn_demo')).toMatchObject({ input: RUN.request, send: false, setup: true });
});

test('a demo on another model than its recording’s, or whose recording ran on what this edition cannot add, is built like any setup', async () => {
  rec.mockResolvedValue(RUN);
  start.mockResolvedValue(saved);
  const b = startBuild({ ...DEMO_IN, model: 'glm-5.3' });
  resumeBuild(b.key);
  expect(await settle(b.key)).toMatchObject({ phase: 'done', id: 'chrn_built', recording: null });
  expect(create).not.toHaveBeenCalled();
  rec.mockResolvedValue({ ...RUN, template: { ...RUN.template, plugins: [{ id: 'github', name: 'GitHub' }] } });
  const c = startBuild(DEMO_IN);
  resumeBuild(c.key);
  expect(await settle(c.key)).toMatchObject({ phase: 'done', id: 'chrn_built', recording: null });
  expect(create).not.toHaveBeenCalled();
  expect(start).toHaveBeenCalledTimes(2);
});

test('recordings that cannot be read are said, and nothing is built or saved in their place', async () => {
  rec.mockRejectedValue(new Error('Loading chunk 412 failed.'));
  const b = startBuild(DEMO_IN);
  resumeBuild(b.key);
  expect(await settle(b.key)).toMatchObject({ phase: 'failed', error: 'Your setup couldn’t be built just now.' });
  expect(start).not.toHaveBeenCalled();
  expect(create).not.toHaveBeenCalled();
});

describe('a long poll that fails', () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());
  test('is asked again after about 2 s, then 4 s, and goes on from where it stood', async () => {
    start.mockResolvedValue(building('writing'));
    read.mockRejectedValueOnce(new Error('502')).mockRejectedValueOnce(new Error('502')).mockResolvedValueOnce(saved);
    const b = startBuild(AUTO_IN);
    resumeBuild(b.key);
    await jest.advanceTimersByTimeAsync(0);
    expect(read).toHaveBeenCalledTimes(1);
    await jest.advanceTimersByTimeAsync(1_999);
    expect(read).toHaveBeenCalledTimes(1);
    await jest.advanceTimersByTimeAsync(1);
    expect(read).toHaveBeenCalledTimes(2);
    await jest.advanceTimersByTimeAsync(4_000);
    expect(read).toHaveBeenCalledTimes(3);
    expect(read.mock.calls.map((c) => c[2])).toEqual(['building.writing', 'building.writing', 'building.writing']);
    await jest.advanceTimersByTimeAsync(0);
    expect(resumeBuild(b.key)).toMatchObject({ phase: 'done', id: 'chrn_built' });
  });
  test('a server that answers at once with the record where it stood is not asked again in a tight loop', async () => {
    start.mockResolvedValue(building('reading'));
    read.mockResolvedValue(building('reading'));
    const b = startBuild(AUTO_IN);
    resumeBuild(b.key);
    await jest.advanceTimersByTimeAsync(0);
    expect(read).toHaveBeenCalledTimes(1);
    await jest.advanceTimersByTimeAsync(1_999);
    expect(read).toHaveBeenCalledTimes(1);
    await jest.advanceTimersByTimeAsync(1);
    expect(read).toHaveBeenCalledTimes(2);
    read.mockResolvedValue(saved);
    await jest.advanceTimersByTimeAsync(2_000);
    expect(resumeBuild(b.key)).toMatchObject({ phase: 'done' });
  });
});
