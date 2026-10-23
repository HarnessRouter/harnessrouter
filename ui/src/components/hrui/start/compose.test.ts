// New setup's build as the console asks the server for it (start/compose.ts: POST
// /v1/harnesses/builds, GET /v1/harnesses/builds/{key}, by long poll), the configuration on a build's
// record, and New setup's sentence and a setup's name kept apart from the workspace's others
// (start/names.ts).
jest.mock('@/lib/harness', () => ({ gwHeaders: () => ({ 'content-type': 'application/json', 'x-harness-workspace': 'ws_1' }) }));
jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
import { harnessFetch } from '@/lib/hfetch';
import { BuildRefused, POLL_END_MS, readComposed, readRecord, readServerBuild, standOf, startServerBuild, type Chosen } from './compose';
import { tooShort, uniqName } from './names';

const mockFetch = harnessFetch as unknown as jest.Mock;
const answer = (status: number, data: unknown) => new Response(JSON.stringify(data), { status, headers: { 'content-type': 'application/json' } });
const AUTO_PICK: Chosen = { base: 'auto', model: 'auto', baseName: 'Auto' };
const JOB = '帮我构建一个智能体，能够自动给我创建一个客户 outreach 的 CRM 表格，并且根据这个表格上的内容，给我创建邮件和日历提醒';
const CONFIG = {
  name: '客户外联助手', instructions: '你负责为使用者维护客户外联的 CRM 表格：读取表格中的客户信息，起草外联邮件，并为每个跟进节点创建日历提醒。',
  exampleTask: '把这周要跟进的三位客户加进表格，并给每人起草一封邮件，周五上午提醒我跟进。',
  base: 'hermes', baseName: 'Hermes', model: 'gpt-5.4',
  skills: [{ id: 'docx', name: 'Documents' }],
  plugins: [{ id: 'media', name: 'Media tools' }],
  connectionsNeeded: [{ id: 'openmail', name: 'OpenMail' }],
};
// a saved build's record, every field the server gives
const SAVED = {
  key: 'bk1abcdef12', status: 'saved', step: 'saving', setupId: 'chrn_bk1abcdef12',
  config: { ...CONFIG, apps: [{ id: 'googlecalendar', name: 'Google Calendar' }, { id: 'googlesheets', name: 'Google Sheets' }], mcpServers: [], environment: '',
    connectionsNeeded: [{ id: 'openmail', name: 'OpenMail', kind: 'plugin' }] },
  attached: { media: 'on', googlecalendar: 'on', googlesheets: 'off', bogus: 'maybe' },
  startedAt: 1, finishedAt: 2,
};

beforeEach(() => mockFetch.mockReset());

describe('a build’s record', () => {
  it('is read with every field the server gives: its apps drawn with its plugins, each attach', () => {
    const r = readRecord(SAVED, AUTO_PICK);
    expect(r).toMatchObject({ key: 'bk1abcdef12', status: 'saved', step: 'saving', setupId: 'chrn_bk1abcdef12', reason: '' });
    expect(r?.config).toMatchObject({ name: CONFIG.name, instructions: CONFIG.instructions, exampleTask: CONFIG.exampleTask, base: 'hermes', baseName: 'Hermes', model: 'gpt-5.4' });
    expect(r?.config?.plugins).toEqual([{ id: 'media', name: 'Media tools' }, { id: 'googlecalendar', name: 'Google Calendar' }, { id: 'googlesheets', name: 'Google Sheets' }]);
    expect(r?.config?.connectionsNeeded).toEqual([{ id: 'openmail', name: 'OpenMail' }]);
    expect(r?.attached).toEqual({ media: 'on', googlecalendar: 'on', googlesheets: 'off' });
    expect(r?.config?.instructions).not.toBe(JOB);
  });
  it('a build going on, before its configuration is written: its step, and nothing to draw yet', () => {
    expect(readRecord({ key: 'k', status: 'building', step: 'reading' }, AUTO_PICK)).toMatchObject({ status: 'building', step: 'reading', config: null, setupId: '' });
  });
  it('a failed build: its reason in the server’s words', () => {
    expect(readRecord({ key: 'k', status: 'failed', reason: ' Not enough to go on. ' }, AUTO_PICK)).toMatchObject({ status: 'failed', reason: 'Not enough to go on.' });
  });
  it.each([['nothing', null], ['no status', { key: 'k' }], ['an unknown status', { key: 'k', status: 'queued' }]])('holds no record: %s', (_why, raw) => {
    expect(readRecord(raw, AUTO_PICK)).toBeNull();
  });
});

describe('a build’s configuration', () => {
  const ok = (config: unknown) => ({ status: 'ok', config });
  it('uses every field as sent', () => {
    expect(readComposed(ok(CONFIG), AUTO_PICK)).toEqual(CONFIG);
  });
  it.each([
    ['an empty example', { exampleTask: '' }, { exampleTask: '' }],
    ['no example', { exampleTask: undefined }, { exampleTask: '' }],
    ['no model (Auto left)', { model: undefined }, { model: '' }],
    ['no harness or model (Auto left): nothing guessed', { base: '', baseName: '', model: '' }, { base: '', baseName: '', model: '' }],
    ['no harness name', { baseName: undefined }, { baseName: 'hermes' }],
    ['no parts lists', { skills: undefined, plugins: null, connectionsNeeded: 'x' }, { skills: [], plugins: [], connectionsNeeded: [] }],
    ['parts as bare ids, or without names', { skills: ['docx'], plugins: [{ id: 'media' }] }, { skills: [{ id: 'docx', name: 'docx' }], plugins: [{ id: 'media', name: 'media' }] }],
  ])('a missing field does not drop it: %s', (_why, change, expected) => {
    expect(readComposed(ok({ ...CONFIG, ...change }), AUTO_PICK)).toMatchObject({ ...CONFIG, ...expected });
  });
  it('fills a missing harness and model from what the person chose', () => {
    const chosen: Chosen = { base: 'goose', model: 'gpt-5.4', baseName: 'Goose' };
    expect(readComposed(ok({ ...CONFIG, base: '', baseName: '', model: '' }), chosen)).toMatchObject({ base: 'goose', baseName: 'Goose', model: 'gpt-5.4' });
  });
  it('reads the snake_case spellings too', () => {
    const { exampleTask, baseName, connectionsNeeded, ...rest } = CONFIG;
    expect(readComposed(ok({ ...rest, example_task: exampleTask, base_name: baseName, connections_needed: connectionsNeeded }), AUTO_PICK)).toEqual(CONFIG);
  });
  it.each([
    ['no instructions', { ...CONFIG, instructions: '' }],
    ['blank instructions', { ...CONFIG, instructions: '   ' }],
    ['no name (nothing invents one from the sentence)', { ...CONFIG, name: '' }],
  ])('is none with %s: never one with the sentence as its instructions', (_why, config) => {
    expect(readComposed(ok(config), AUTO_PICK)).toBeNull();
  });
});

describe('the builds client', () => {
  it('starts a build under the key, with the job, the choices and the workspace, and reads its record', async () => {
    mockFetch.mockResolvedValue(answer(200, { key: 'bk1abcdef12', status: 'building', step: 'reading' }));
    const r = await startServerBuild('bk1abcdef12', JOB, AUTO_PICK, 'ws_1');
    expect(mockFetch).toHaveBeenCalledWith('/api/harness/v1/harnesses/builds', expect.objectContaining({ method: 'POST' }));
    expect(JSON.parse(mockFetch.mock.calls[0][1].body)).toEqual({ job: JOB, base: 'auto', model: 'auto', workspace: 'ws_1', key: 'bk1abcdef12' });
    expect(r).toMatchObject({ status: 'building', step: 'reading' });
  });
  it('a refusal comes back in the server’s words; a code or an object is no words', async () => {
    mockFetch.mockResolvedValueOnce(answer(400, { detail: 'Say what it should do first.' }));
    await expect(startServerBuild('bk1abcdef12', '', AUTO_PICK, 'ws_1')).rejects.toEqual(new BuildRefused('Say what it should do first.'));
    mockFetch.mockResolvedValueOnce(answer(409, { detail: { code: 'workspace_mismatch' } }));
    await expect(startServerBuild('bk1abcdef12', JOB, AUTO_PICK, 'ws_2')).rejects.toMatchObject({ reason: '' });
  });
  it('a server that could not answer, or a call cut off, is not a refusal', async () => {
    mockFetch.mockResolvedValueOnce(answer(503, { detail: 'could not be started just now' }));
    await expect(startServerBuild('bk1abcdef12', JOB, AUTO_PICK, 'ws_1')).rejects.not.toBeInstanceOf(BuildRefused);
    mockFetch.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    await expect(startServerBuild('bk1abcdef12', JOB, AUTO_PICK, 'ws_1')).rejects.toBeInstanceOf(TypeError);
  });
  it('reads a build by its key; none when the server has none', async () => {
    mockFetch.mockResolvedValueOnce(answer(200, SAVED));
    expect(await readServerBuild('bk1abcdef12', AUTO_PICK)).toMatchObject({ status: 'saved', setupId: 'chrn_bk1abcdef12' });
    expect(mockFetch.mock.calls[0][0]).toBe('/api/harness/v1/harnesses/builds/bk1abcdef12');
    mockFetch.mockResolvedValueOnce(answer(404, { detail: 'Not found' }));
    expect(await readServerBuild('bk1abcdef12', AUTO_PICK)).toBeNull();
    mockFetch.mockResolvedValueOnce(answer(502, { detail: 'x' }));
    await expect(readServerBuild('bk1abcdef12', AUTO_PICK)).rejects.toThrow();
  });
  it('a long poll names where the record last drawn stood, and has its own end past the server’s hold', async () => {
    expect(standOf({ status: 'building', step: 'writing' })).toBe('building.writing');
    expect(standOf({ status: 'saved', step: 'saving' })).toBe('saved.');
    mockFetch.mockResolvedValueOnce(answer(200, { key: 'bk1abcdef12', status: 'building', step: 'saving' }));
    expect(await readServerBuild('bk1abcdef12', AUTO_PICK, 'building.writing')).toMatchObject({ status: 'building', step: 'saving' });
    expect(mockFetch.mock.calls[0][0]).toBe('/api/harness/v1/harnesses/builds/bk1abcdef12?after=building.writing');
    expect(mockFetch.mock.calls[0][1].signal).toBeInstanceOf(AbortSignal);
    expect(POLL_END_MS).toBeGreaterThan(30_000);
  });
});

describe('tooShort', () => {
  it('asks for three words, a Chinese, Japanese or Korean character counting as half of one', () => {
    expect(tooShort('Help with contracts')).toBe(false);
    expect(tooShort('Generate cat images')).toBe(false);
    expect(tooShort('Cat images')).toBe(true);
    expect(tooShort('  -  - ')).toBe(true);
    expect(tooShort('根据用户描述的场景，为每位用户生成一张猫咪图片。')).toBe(false);
    expect(tooShort('お客様のメールに返信してください')).toBe(false);
    expect(tooShort('猫图')).toBe(true);
    expect(tooShort('生成猫的图片')).toBe(false);
  });
});

describe('uniqName', () => {
  it('never repeats a name the workspace has', () => {
    expect(uniqName('Cat video', ['Cat video', 'Cat video 2'])).toBe('Cat video 3');
    expect(uniqName('Cat video', [])).toBe('Cat video');
  });
  it('treats names that differ only in capitals or spacing as the same name', () => {
    expect(uniqName('Cat Images', ['Cat images'])).toBe('Cat Images 2');
    expect(uniqName('cat images', ['Cat Images', 'CAT IMAGES 2'])).toBe('cat images 3');
    expect(uniqName('Cat images', ['  cat   images '])).toBe('Cat images 2');
    expect(uniqName('Revisión de contratos', ['Revisión de contratos'])).toBe('Revisión de contratos 2');
    expect(uniqName('猫咪场景图', ['猫咪场景图'])).toBe('猫咪场景图 2');
    expect(uniqName('Cat images', ['Cat image'])).toBe('Cat images');
  });
});
