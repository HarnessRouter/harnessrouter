// The Memory part of the Agent stack: its own slot, its own shape, its own way into Settings, and the memories server
// is never a tool.
import { partIcon } from '../bricks';
import { isoSvg, PARTS, towerOf, withMemories, type PartCounts } from '../tower';
import { brickLayer } from './settingsModel';
import { isServiceEntry, setupTools } from './setupParts';
import { toolLayers } from './stackLive';

const tower = (parts: Partial<PartCounts> = {}) => towerOf({ harness: 'Claude Code', model: 'm', instructions: true, tested: true, running: false, parts: { skill: 0, plugin: 0, mcp: 0, env: 0, ...parts } });
const brick = (svg: string, k: string) => { const m = new RegExp(`<g class="bk f-[a-z]+ [a-z]+[^"]*" data-tw="${k}".*?</g>`).exec(svg); return m ? m[0] : ''; };

test('it’s the fifth part, between Tool and Environment as Settings has it', () => {
  expect(PARTS.map(([, n]) => n)).toEqual(['Plugin', 'Skill', 'Tool', 'Memory', 'Environment']);
});
test('no memory, no brick', () => {
  const t = withMemories(tower(), 0);
  expect(isoSvg(t, 24, true)).not.toContain('data-tw="memory"');
});
test('with memories it stands on the top, in its own colour and a shape no other part has', () => {
  const svg = isoSvg(withMemories(tower(), 1), 24, true);
  const g = brick(svg, 'memory');
  expect(g).toContain('f-memory');
  expect(g).toContain('built');
  expect(g).toContain('class="mk"');
  expect(g).not.toContain('<polygon');
  const icon = partIcon('built', 'memory');
  expect(icon).toContain('f-memory');
  expect(icon).not.toContain('<polygon');
  expect(partIcon('built', 'mcp')).toContain('<polygon');
});
test('its place is the centre of the top, clear of every corner when all five are there', () => {
  const svg = isoSvg(withMemories(tower({ skill: 3, plugin: 3, mcp: 3, env: 1 }), 3), 24, true);
  ['plugin', 'skill', 'mcp', 'memory', 'env'].forEach((k) => expect(svg).toContain(`data-tw="${k}"`));
  // drawn after the corner behind it and before the corner in front of it, or one would cover the other
  expect(svg.indexOf('data-tw="plugin"')).toBeLessThan(svg.indexOf('data-tw="memory"'));
  expect(svg.indexOf('data-tw="memory"')).toBeLessThan(svg.indexOf('data-tw="env"'));
});
test('past three, the count is printed as on other parts', () => {
  expect(brick(isoSvg(withMemories(tower(), 7), 24, true), 'memory')).toContain('>7<');
});
test('a click goes to the Memory layer, not to Tools', () => {
  expect(brickLayer('memory')).toBe('memory');
  expect(brickLayer('mcp')).toBe('caps');
});
test('the memories server is the service’s: not a tool, not counted, not listed', () => {
  const entry = { id: 'mcp.memories', name: 'memories', url: 'http://127.0.0.1:8080/v1/mcp/memories', enabled: true };
  expect(isServiceEntry(entry as never)).toBe(true);
  const h = { id: 'h', name: 'x', base: 'claude-code', mcpServers: [entry, { id: 'docs', name: 'docs', url: 'https://d' }] };
  expect(setupTools(h as never, null, 'added').map((t) => t.name)).toEqual(['docs']);
  expect(setupTools(h as never, null, 'all').map((t) => t.name)).toEqual(['docs']);
});
test('an agent’s memory calls light the Memory brick, whichever way its harness spells them', () => {
  ['mcp__memories__memory_recall', 'memories.memory_remember', 'memories_2_memory_get', 'memory_revise'].forEach((n) => expect(toolLayers(n, {})).toEqual(['memory']));
  expect(toolLayers('mcp__docs__search', {})).toEqual(['mcp']);
  expect(toolLayers('mcp__docs__memory_card', {})).toEqual(['mcp']);
});
