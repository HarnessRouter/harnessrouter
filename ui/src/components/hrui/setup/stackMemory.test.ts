// The Memory part of the Agent stack: the same brick as every part in its own colour and slot, its own way into
// Settings, and the memories server is never a tool.
import { partIcon } from '../bricks';
import { rowOf } from '../setups';
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
test('with a memory it stands on the top: the same brick and stud as any part, in its own colour', () => {
  const svg = isoSvg(withMemories(tower(), 1), 24, true);
  const g = brick(svg, 'memory');
  expect(g).toContain('f-memory');
  expect(g).toContain('built');
  const shape = (x: string) => x.replace(/f-[a-z]+/g, '').replace(/data-tw="[a-z]+"/, '').replace(/[-\d.]+/g, '#').replace(/<title>.*?<\/title>/g, '');
  expect(shape(g)).toBe(shape(brick(isoSvg(tower({ mcp: 1 }), 24, true), 'mcp')));
  const icon = (fam: string) => partIcon('built', fam).replace(`f-${fam}`, '');
  expect(icon('memory')).toBe(icon('mcp'));
  expect(partIcon('built', 'memory')).toContain('f-memory');
});
test('its place is the middle of the top, on the same grid as the corners', () => {
  const at = (t: ReturnType<typeof tower>) => isoSvg(t, 24, true);
  const pts = (g: string) => [...g.matchAll(/points="([^"]+)"/g)][0][1].split(' ').map((p) => p.split(',').map(Number));
  const top = (k: string, t: ReturnType<typeof tower>) => pts(brick(at(t), k));
  const all = withMemories(tower({ plugin: 1, skill: 1, mcp: 1, env: 1 }), 1);
  const m = top('memory', all), p = top('plugin', all), e = top('env', all);
  // from the back corner to the front one in equal steps: plugin at 0, memory at 2, environment at 4
  const y = (q: number[][]) => q[0][1];
  expect(y(m) - y(p)).toBeCloseTo(y(e) - y(m), 0);
  expect(m[0][0]).toBeCloseTo(p[0][0], 0);
  expect(m[0][0]).toBeCloseTo(e[0][0], 0);
});
test('every part is drawn in the order that keeps it behind what stands in front of it', () => {
  const svg = isoSvg(withMemories(tower({ skill: 3, plugin: 3, mcp: 3, env: 1 }), 3), 24, true);
  ['plugin', 'skill', 'mcp', 'memory', 'env'].forEach((k) => expect(svg).toContain(`data-tw="${k}"`));
  expect(svg.indexOf('data-tw="plugin"')).toBeLessThan(svg.indexOf('data-tw="memory"'));
  expect(svg.indexOf('data-tw="memory"')).toBeLessThan(svg.indexOf('data-tw="env"'));
});
test('it never stacks, so it can’t hide the corner behind it: more than one is a count on the brick, as any part past its stack', () => {
  const polys = (n: number) => (brick(isoSvg(withMemories(tower(), n), 24, true), 'memory').match(/<polygon/g) || []).length;
  expect(polys(5)).toBe(polys(1));
  expect(brick(isoSvg(withMemories(tower(), 1), 24, true), 'memory')).not.toContain('part-n-lbl');
  expect(brick(isoSvg(withMemories(tower(), 2), 24, true), 'memory')).toContain('>2<');
  expect(brick(isoSvg(tower({ mcp: 5 }), 24, true), 'mcp')).toContain('>5<');
});
test('what Settings reads now overrides the list, down to none', () => {
  const had = withMemories(tower(), 2);
  const now = withMemories(had, 0);
  expect(isoSvg(now, 24, true)).not.toContain('data-tw="memory"');
  expect(now.st.memory).toBe('empty');
});
test('a setup’s row carries the count the list read, and only that', () => {
  const h = (memories?: { count: number }) => ({ id: 'h', name: 'x', base: 'claude-code', baseLabel: 'x', defaultModel: 'm', systemPrompt: '', mcpServers: [{ id: 'mcp.memories', name: 'memories', url: 'http://x/v1/mcp/memories', enabled: true }], skills: [], plugins: [], ...(memories ? { memories } : {}) });
  const row = (m?: { count: number }) => rowOf(h(m) as never, 'x', [], false, undefined, null, Date.now());
  expect(row({ count: 2 }).tower.parts.memory).toBe(2);
  expect(row({ count: 2 }).tower.st.memory).toBe('built');
  // the hidden entry is there on every one of these: a grant taken away leaves it behind, and it says nothing
  expect(row({ count: 0 }).tower.parts.memory).toBe(0);
  expect(row({ count: 0 }).tower.st.memory).toBe('empty');
  expect(row().tower.parts.memory).toBe(0);
  expect(isoSvg(row({ count: 1 }).tower, 13, 'card')).toContain('data-tw="memory"');
  expect(isoSvg(row({ count: 1 }).tower, 5, false)).toContain('data-tw="memory"');
  expect(isoSvg(row({ count: 0 }).tower, 5, false)).not.toContain('data-tw="memory"');
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
