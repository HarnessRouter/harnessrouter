// The pieces of a new setup's first task that are not the network: the parts the save has landed on
// the Agent stack, the save card drawn from a saved record, and the hand-off of the setup to its page.
import { dropsFor, landedParts, withLanded } from './buildStack';
import { seededSetup, seedSetup } from './seed';
import { assemblyOfRow, cardParts, withRecord } from './Assembly';
import type { Build } from './build';
import { rowOf } from '../setups';
import { ghostTower } from '../tower';
import type { CustomHarness } from '@/lib/harness';
import { PLUGS_ENTRY_ID } from '@/lib/plugs';

const build = (o: Partial<Build>): Build => ({
  key: 'k', at: 0, job: '', pick: { baseName: '', model: '' }, phase: 'saving', step: '', asm: null, id: 'chrn_a', first: null, recording: null, firstSid: '', demo: null, error: '', ...o,
});
const cfg = { name: 'Product images', instructions: 'i', exampleTask: 'e', base: 'hermes', baseName: 'Hermes', model: 'gpt-5.4',
  skills: [{ id: 'img', name: 'Image generation' }], plugins: [{ id: 'browser', name: 'Browser' }, { id: 'github', name: 'GitHub' }], connectionsNeeded: [] };

describe('the Agent stack follows the save', () => {
  test('nothing has landed before the setup is created', () => {
    expect(landedParts(null)).toEqual({ skill: 0, plugin: 0 });
    expect(landedParts(build({ asm: { cfg, savedAt: null, plugins: {}, done: false } }))).toEqual({ skill: 0, plugin: 0 });
  });
  test('a template’s own skills land with the record, each plugin as its attach answers', () => {
    const own = { ...cfg, ownSkills: [{ id: 'skl_img', name: 'img', enabled: true, files: [{ path: 'SKILL.md', content: 'x' }] }] };
    expect(landedParts(build({ asm: { cfg: own, savedAt: 1, plugins: { browser: 'now', github: 'now' }, done: false } }))).toEqual({ skill: 1, plugin: 0 });
    expect(landedParts(build({ asm: { cfg: own, savedAt: 1, plugins: { browser: 'on', github: 'off' }, done: true } }))).toEqual({ skill: 1, plugin: 1 });
  });
  test('the builder’s skill picks are the agent harness’s built-ins: no one added them, so none land', () => {
    expect(landedParts(build({ asm: { cfg, savedAt: 1, plugins: { browser: 'on', github: 'on' }, done: true } }))).toEqual({ skill: 0, plugin: 2 });
    expect(cardParts({ cfg, savedAt: 1, plugins: {}, done: true })).toEqual({ skills: [], tools: [] });
  });
  test('landed parts show on the tower as built, never fewer than the record has', () => {
    const t = withLanded(ghostTower(), { skill: 1, plugin: 2 });
    expect(t.parts).toMatchObject({ skill: 1, plugin: 2 });
    expect(t.st.skill).toBe('built');
    expect(t.st.plugin).toBe('built');
    const more = withLanded({ ...ghostTower(), parts: { skill: 3, plugin: 0, mcp: 0, env: 0 } }, { skill: 1, plugin: 0 });
    expect(more.parts.skill).toBe(3);
    expect(more.st.plugin).toBe('empty');
  });
  test('the stack lands everything once on a fresh save, then only a part that has just landed', () => {
    const first = dropsFor(null, { skill: 1, plugin: 0 }, true);
    expect(Object.keys(first)).toEqual(expect.arrayContaining(['b-runtime', 'model', 'task', 'part:skill']));
    expect(first['part:plugin']).toBeUndefined();
    expect(dropsFor(null, { skill: 1, plugin: 1 }, false)).toEqual({});
    expect(dropsFor({ skill: 1, plugin: 0 }, { skill: 1, plugin: 1 }, true)).toEqual({ 'part:plugin': 0 });
    expect(dropsFor({ skill: 1, plugin: 1 }, { skill: 1, plugin: 1 }, true)).toEqual({});
  });
});

describe('the save card', () => {
  const h = { id: 'chrn_a', name: 'Product images', base: 'hermes', baseLabel: 'Hermes', defaultModel: 'gpt-5.4', systemPrompt: 'Make the image.',
    mcpServers: [{ id: PLUGS_ENTRY_ID, url: 'y', enabled: true }],
    skills: [{ id: 's1', name: 'brand', enabled: true, files: [{ path: 'SKILL.md', content: 'x' }] }, { id: 's2', name: 'builtin', enabled: false }],
    createdAt: 5 } as unknown as CustomHarness;
  test('reopened, is drawn from the record: harness, model, instructions, own skills and plugins by name', () => {
    const r = rowOf(h, 'Hermes', [], false, { plugs: ['github'] });
    const a = assemblyOfRow(r, { github: 'GitHub' });
    expect(a.done).toBe(true);
    expect(a.savedAt).toBe(5);
    expect(a.cfg).toMatchObject({ name: 'Product images', instructions: 'Make the image.', baseName: 'Hermes', model: 'gpt-5.4' });
    expect(a.cfg.skills.map((x) => x.name)).toEqual(['brand']);
    expect(a.cfg.plugins.map((x) => x.name)).toEqual(['GitHub']);
    expect(Object.values(a.plugins).every((x) => x === 'on')).toBe(true);
  });
  test('once the setup is saved, names the skills and tools its record says a person added', () => {
    const r = rowOf(h, 'Hermes', [], false, { plugs: [] });
    expect(withRecord({ cfg, savedAt: null, plugins: {}, done: false }, r).added).toBeUndefined();
    expect(withRecord({ cfg, savedAt: 1, plugins: {}, done: false }, r).added?.skills.map((x) => x.name)).toEqual(['brand']);
  });
});

describe('the hand-off from New setup to the setup’s page', () => {
  test('the page a setup was just made on hands it over by its id, in memory; any other id has none', () => {
    const hh = { id: 'chrn_seed', name: 'Product images', base: 'hermes', createdAt: 1 } as unknown as CustomHarness;
    seedSetup('chrn_seed', { h: hh });
    expect(seededSetup('chrn_seed')).toEqual({ h: hh });
    expect(seededSetup('chrn_other')).toBeNull();
    expect(seededSetup('')).toBeNull();
  });
});
