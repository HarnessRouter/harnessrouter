// A setup's plugins, skills and tools: one function each, and every place says which list it shows
// (Richard, 10-18). Settings › Capabilities lists everything the setup can use, built-ins included
// ('all'); the picture counts only what a person added ('added': "the built-in skills and tools are
// not counted on the picture"): the Agent stack, Studio's card tower, and the Capabilities line in the
// layers list beside the stack. Each place is checked on the same setups.
import { PLUGS_ENTRY_ID, type BaseInfo, type CustomHarness, type HarnessPlugin } from '@/lib/harness';
import { rowOf } from '../setups';
import { isoSvg } from '../tower';
import { addedLine } from './settingsModel';
import {
  countOn, pluginName, recordNames, setupPlugins, setupSkills, setupTools, UNREAD_NAME, type PlugBinding,
} from './setupParts';

const PLUGS = { id: PLUGS_ENTRY_ID, url: 'https://plugs.example/mcp', enabled: true };
// Hermes with seven built-in tools and three built-in skills, on by default
const BASE = {
  id: 'hermes', label: 'Hermes', backend: 'hermes', status: 'ok', systemPrompt: '', defaultModel: 'deepseek-v4.1-flash', models: [],
  tools: ['terminal', 'read_file', 'write_file', 'patch', 'search_files', 'web_search', 'web_extract'].map((name) => ({ name, label: name, enforcement: 'hard' })),
  builtinSkills: ['plan', 'research', 'write'].map((name) => ({ name, title: name, description: `${name} well`, defaultEnabled: true, origin: 'hermes' })),
  builtinSkillsEnumerable: true,
} as BaseInfo;
const setup = (o: Partial<CustomHarness> = {}) => ({
  id: 'chrn_p2', name: 'Product images 2', base: 'hermes', defaultModel: 'deepseek-v4.1-flash', systemPrompt: 'Make product images.',
  skills: [], plugins: [], mcpServers: [], createdAt: 1, ...o,
}) as unknown as CustomHarness;
const pkg = (name: string, enabled = true) => ({ name, enabled, files: [], manifest: { name } }) as unknown as HarnessPlugin;
const own = (name: string, enabled = true) => ({ id: `skl_${name}`, name, enabled, files: [{ path: 'SKILL.md', content: 'x' }] });
const DOCS = { id: 'mcp_1', name: 'Docs', url: 'https://docs.example/mcp', enabled: true };
const MEDIA = { id: 'mcp.media', name: 'media', url: 'https://box.example/v1/mcp/media', enabled: true };
const servers = (...m: object[]) => m as CustomHarness['mcpServers'];

/** what every place says for one setup: the tabs (all, the ones on), and the picture (added): the
 *  layers line, the stack's parts and the card tower's bricks */
function everywhere(h: CustomHarness, binding: PlugBinding | null | undefined = null, labels: Record<string, string> = {}) {
  const tabs = { plugin: countOn(setupPlugins(h, binding, 'all')), skill: countOn(setupSkills(h, BASE, 'all')), tool: countOn(setupTools(h, BASE, 'all')) };
  const added = { plugin: countOn(setupPlugins(h, binding, 'added')), skill: countOn(setupSkills(h, BASE, 'added')), tool: countOn(setupTools(h, BASE, 'added')) };
  const r = rowOf(h, 'Hermes', [], false, binding, BASE);
  return {
    plugins: setupPlugins(h, binding, 'all').filter((p) => p.on).map((p) => pluginName(p, labels)),
    tabs,
    line: addedLine(added),
    stack: { plugin: r.tower.parts.plugin, skill: r.tower.parts.skill, tool: r.tower.parts.mcp },
    card: isoSvg(r.tower, 13, 'card'),
  };
}

describe('a setup with one workspace plugin and nothing else added, Hermes’s built-ins on', () => {
  const e = everywhere(setup({ mcpServers: servers(PLUGS) }), { plugs: ['github'] }, { github: 'GitHub' });
  test('the tabs list everything, built-ins included: Plugins 1, Skills 3, Tools 7', () => {
    expect(e.tabs).toEqual({ plugin: 1, skill: 3, tool: 7 });
    expect(e.plugins).toEqual(['GitHub']);
  });
  test('the picture counts only what was added: 1 plugin, no skill, no tool', () => {
    expect(e.stack).toEqual({ plugin: 1, skill: 0, tool: 0 });
    expect(e.card).toContain('<title>Plugin: 1</title>');
    expect(e.card).not.toMatch(/<title>Skills?:/);
    expect(e.card).not.toMatch(/<title>Tools?:/);
  });
  test('the layers list says what was added, as the stack beside it does', () => {
    expect(e.line).toBe('1 plugin added');
  });
});

describe('a setup with only built-ins', () => {
  const e = everywhere(setup());
  test('its tabs still list the built-ins', () => {
    expect(e.tabs).toEqual({ plugin: 0, skill: 3, tool: 7 });
    expect(setupTools(setup(), BASE, 'all').map((t) => t.name)).toContain('terminal');
  });
  test('its picture is empty, and the line says nothing was added', () => {
    expect(e.stack).toEqual({ plugin: 0, skill: 0, tool: 0 });
    expect(e.card).not.toMatch(/<title>(Plugins?|Skills?|Tools?):/);
    expect(e.line).toBe('Nothing added yet');
  });
});

describe('what a person added counts in the picture, the same in every place', () => {
  test('an own skill and an MCP server, with a package', () => {
    const e = everywhere(setup({ mcpServers: servers(DOCS), skills: [own('brand')] as CustomHarness['skills'], plugins: [pkg('kit')] }));
    expect(e.stack).toEqual({ plugin: 1, skill: 1, tool: 1 });
    expect(e.line).toBe('1 plugin, 1 skill and 1 tool added');
    expect(e.tabs).toEqual({ plugin: 1, skill: 4, tool: 8 });
  });
  test('an own skill turned off, an MCP server turned off and a package turned off are listed, not counted', () => {
    const h = setup({ mcpServers: servers({ ...DOCS, enabled: false }), skills: [own('brand', false)] as CustomHarness['skills'], plugins: [pkg('old', false), pkg('kit')] });
    const e = everywhere(h);
    expect(e.stack).toEqual({ plugin: 1, skill: 0, tool: 0 });
    expect(e.line).toBe('1 plugin added');
    expect(setupSkills(h, BASE, 'added').map((x) => [x.name, x.on])).toEqual([['brand', false]]);
    expect(recordNames(setupPlugins(h, null, 'added'))).toEqual(['kit']);
  });
  test('a built-in turned on by the setup is still a built-in: listed, never in the picture', () => {
    const h = setup({ skills: [{ id: 'skl_x', name: 'plan', enabled: true }] as CustomHarness['skills'] });
    expect(setupSkills(h, BASE, 'added')).toEqual([]);
    expect(everywhere(h).stack.skill).toBe(0);
  });
  test('two plugins: 2 everywhere', () => {
    const e = everywhere(setup({ mcpServers: servers(PLUGS), plugins: [pkg('kit')] }), { plugs: ['github'] }, { github: 'GitHub' });
    expect(e.plugins).toEqual(['GitHub', 'kit']);
    expect([e.tabs.plugin, e.stack.plugin]).toEqual([2, 2]);
    expect(e.card).toContain('<title>Plugins: 2</title>');
    expect(e.line).toBe('2 plugins added');
  });
});

describe('the lists', () => {
  test('skills, all: own skills, then the built-ins not replaced, each on by its own switch', () => {
    const h = setup({ skills: [own('brand'), own('plan'), { id: 'skl_x', name: 'research', enabled: false }] as CustomHarness['skills'] });
    expect(setupSkills(h, BASE, 'all').map((x) => [x.kind, x.name, x.on])).toEqual([
      ['own', 'brand', true], ['own', 'plan', true], ['builtin', 'research', false], ['builtin', 'write', true]]);
    expect(setupSkills(h, BASE, 'added').map((x) => x.name)).toEqual(['brand', 'plan']);
  });
  test('an agent harness that takes no skills has none, in either list', () => {
    const h = setup({ skills: [own('brand')] as CustomHarness['skills'] });
    expect(setupSkills(h, { ...BASE, takesSkills: false }, 'all')).toEqual([]);
    expect(setupSkills(h, { ...BASE, takesSkills: false }, 'added')).toEqual([]);
  });
  test('tools, all: built-ins on unless turned off, then the setup’s own MCP servers; the plugins binding is not a tool', () => {
    const h = setup({ disabledTools: ['web_search'], mcpServers: servers(MEDIA, PLUGS, DOCS, { id: 'mcp_2', name: 'Old', url: 'https://old.example/mcp', enabled: false }) });
    expect(countOn(setupTools(h, BASE, 'all'))).toBe(8);
    expect(setupTools(h, BASE, 'added').map((x) => [x.name, x.on, x.kind === 'mcp' && x.index])).toEqual([['media', true, 0], ['Docs', true, 1], ['Old', false, 2]]);
  });
  test('plugins: the same list either way', () => {
    const h = setup({ mcpServers: servers(PLUGS), plugins: [pkg('kit')] });
    expect(setupPlugins(h, { plugs: ['github'] }, 'added')).toEqual(setupPlugins(h, { plugs: ['github'] }, 'all'));
  });
});

describe('the plugins rule', () => {
  test('a binding turned off on the record is no plugin', () => {
    expect(setupPlugins(setup({ mcpServers: servers({ ...PLUGS, enabled: false }) }), { plugs: ['github'] }, 'all')).toEqual([]);
  });
  test('a workspace plugin is named by the catalog’s label, else by its type', () => {
    const [p] = setupPlugins(setup({ mcpServers: servers(PLUGS) }), { plugs: ['browser'] }, 'all');
    expect(p).toMatchObject({ kind: 'plug', type: 'browser' });
    expect(pluginName(p, { browser: 'Browser' })).toBe('Browser');
    expect(pluginName(p)).toBe('browser');
  });
  test('workspace plugins the record has but that were not read count as one; read as none, as none', () => {
    const h = setup({ mcpServers: servers(PLUGS) });
    expect(setupPlugins(h, undefined, 'all').map((p) => p.kind)).toEqual(['unread']);
    expect(pluginName(setupPlugins(h, undefined, 'all')[0])).toBe(UNREAD_NAME);
    expect(setupPlugins(h, null, 'all')).toEqual([]);
    expect(setupPlugins(h, { plugs: ['github'], enabled: false }, 'all')).toEqual([]);
    expect(recordNames(setupPlugins(h, undefined, 'added'))).toBeNull();   // the stack names them only when it can name all
  });
  test('the line: each kind with none left out, the last joined with and', () => {
    expect(addedLine({ plugin: 0, skill: 0, tool: 1 })).toBe('1 tool added');
    expect(addedLine({ plugin: 0, skill: 2, tool: 3 })).toBe('2 skills and 3 tools added');
    expect(addedLine({ plugin: 0, skill: 0, tool: 0 })).toBe('Nothing added yet');
  });
});
