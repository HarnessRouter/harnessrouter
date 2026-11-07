// The graph read as the canvas draws it. The shapes here are the ones the providers answered on a real
// install: Graphiti and Hindsight say a fact is `about` two entities, a stated record says `subject` and
// `object`, Mem0 keeps no references at all.
import type { GraphEdge, GraphNode, MemoryGraph, MemoryRecord } from '@/lib/memories';

jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
jest.mock('@/lib/harness', () => ({ gwHeaders: () => ({}) }));

import { harnessFetch } from '@/lib/hfetch';
import { closedKey, computeCollapse, edgeCaption, elementOf, exploreOf, kindsIn, lineCaption, lineKey, mergeGraphs, readGraph, recordsIn } from './adapter';

const rec = (id: string, type: string, o: Partial<MemoryRecord> = {}): MemoryRecord => ({
  id, object: 'memory.record', memory_id: 'hmem_1', type, title: '', content: [], attributes: {}, version: 1, status: 'active', supersedes: null,
  time: { valid_from: null, valid_to: null, written_at: null, invalidated_at: null }, written_by: { kind: 'provider', id: 'x' }, references: [], trust: 'untrusted', ...o,
});
const node = (r: MemoryRecord, memory = { id: 'hmem_1', name: 'One' }): GraphNode => ({ record: r, memory });
const edge = (from: string, to: string, rel: string): GraphEdge => ({ from: { memory_id: 'hmem_1', record_id: from }, to: { memory_id: 'hmem_1', record_id: to }, rel, available: true });
const graph = (nodes: GraphNode[], edges: GraphEdge[], o: Partial<MemoryGraph> = {}): MemoryGraph => ({ nodes, edges, truncated: false, degraded: [], ...o });
const text = (t: string) => [{ type: 'text', text: t }];

describe('a fact is the line between what it relates', () => {
  const acme = rec('acme', 'entity', { title: 'Acme' });
  const pro = rec('pro', 'entity', { title: 'Photon Pro' });
  const ep = rec('ep', 'episode');
  const buys = rec('f1', 'fact', { content: text('Acme signed up for Photon Pro.'), attributes: { predicate: 'BUYS' } });
  const g = exploreOf(graph([node(acme), node(pro), node(ep), node(buys)], [edge('f1', 'acme', 'about'), edge('f1', 'pro', 'about'), edge('f1', 'ep', 'derived_from'), edge('acme', 'ep', 'derived_from')]));

  it('two entities it is about: one line, no node for the fact, and no direction it did not state', () => {
    expect(Object.keys(g.nodes).sort()).toEqual(['acme', 'ep', 'pro']);
    const line = g.edges.find((e) => e.key === lineKey('f1'));
    expect(line).toMatchObject({ from: 'acme', to: 'pro', directed: false, available: true });
    expect(line?.fact?.id).toBe('f1');
    expect(elementOf(g, 'f1')).toBe(lineKey('f1'));
  });
  it('where it came from has no end to draw from, so the line holds it', () => {
    expect(g.edges.find((e) => e.key === lineKey('f1'))?.also).toEqual([{ rel: 'derived_from', to: 'ep' }]);
    expect(g.edges.some((e) => e.from === 'f1')).toBe(false);
    expect(g.edges.some((e) => e.from === 'acme' && e.to === 'ep' && e.rel === 'derived_from')).toBe(true);
  });
  it('a subject and an object: one line, pointing the way it says', () => {
    const f = rec('f2', 'fact', { title: 'Dana works at Quillon' });
    const x = exploreOf(graph([node(rec('quillon', 'entity')), node(rec('dana', 'entity')), node(f)], [edge('f2', 'quillon', 'object'), edge('f2', 'dana', 'subject')]));
    expect(x.edges.find((e) => e.key === lineKey('f2'))).toMatchObject({ from: 'dana', to: 'quillon', directed: true });
  });
  it('stays a node when a line would lose something', () => {
    const one = exploreOf(graph([node(rec('a', 'entity')), node(rec('f', 'fact'))], [edge('f', 'a', 'about')]));
    expect(one.nodes.f).toBeDefined();
    expect(one.edges.map((e) => e.rel)).toEqual(['about']);
    const other = exploreOf(graph([node(rec('a', 'entity')), node(rec('b', 'entity')), node(rec('f', 'fact')), node(rec('g', 'fact'))],
      [edge('f', 'a', 'about'), edge('f', 'b', 'about'), edge('g', 'f', 'contradicts'), edge('f', 'g', 'contradicts')]));
    expect(other.nodes.f).toBeDefined();
    const three = exploreOf(graph(['a', 'b', 'c'].map((x) => node(rec(x, 'entity'))).concat(node(rec('f', 'fact'))), [edge('f', 'a', 'about'), edge('f', 'b', 'about'), edge('f', 'c', 'about')]));
    expect(three.nodes.f).toBeDefined();
    const missing = exploreOf(graph([node(rec('a', 'entity')), node(rec('f', 'fact'))], [edge('f', 'a', 'subject'), edge('f', 'gone', 'object')]));
    expect(missing.nodes.f).toBeDefined();
  });
  it('reads as the word it was filed under, or its sentence where that word says nothing', () => {
    expect(lineCaption(buys)).toBe('BUYS');
    expect(lineCaption(rec('f', 'fact', { content: text('Globex uses Photon Lite with twelve seats.'), attributes: { predicate: 'RELATES_TO' } }))).toBe('Globex uses Photon Lite…');
  });
});

describe('what the read did not answer is not drawn', () => {
  it('a record you can\'t open: an anonymous node, and nothing about it', () => {
    const closed: GraphEdge = { from: { memory_id: 'hmem_1', record_id: 'a' }, to: { record_id: 'hrec_77' }, available: false };
    const g = exploreOf(graph([node(rec('a', 'note', { title: 'A' }))], [closed]));
    const n = g.nodes[closedKey('hrec_77')];
    expect(n).toMatchObject({ record: null, memoryId: null, memoryName: '', title: '', kind: '' });
    const e = g.edges[0];
    expect(e).toMatchObject({ from: 'a', to: closedKey('hrec_77'), rel: null, available: false });
    expect(edgeCaption(e)).toBe('');
    expect(JSON.stringify(g)).not.toContain('hmem_2');
  });
  it('an end outside this read is left off', () => {
    const g = exploreOf(graph([node(rec('a', 'note'))], [edge('a', 'elsewhere', 'derived_from')]));
    expect(g.edges).toEqual([]);
    expect(Object.keys(g.nodes)).toEqual(['a']);
  });
  it('a provider that keeps no links has isolated records', () => {
    const g = exploreOf(graph([node(rec('a', 'fact', { content: text('One') })), node(rec('b', 'fact', { content: text('Two') }))], []));
    expect(g.edges).toEqual([]);
    expect(Object.keys(g.nodes).sort()).toEqual(['a', 'b']);
  });
  it('a record in another memory keeps the memory it is in, to go there', () => {
    const g = exploreOf(graph([node(rec('a', 'note')), node(rec('b', 'note'), { id: 'hmem_2', name: 'Two' })], [edge('a', 'b', 'derived_from')]));
    expect(g.nodes.b).toMatchObject({ memoryId: 'hmem_2', memoryName: 'Two' });
  });
  it('says when it was cut short', () => {
    expect(exploreOf(graph([], [], { truncated: true, degraded: ['x'] }))).toMatchObject({ truncated: true, degraded: ['x'] });
  });
});

describe('reads and folds', () => {
  it('leaves `around` out for the whole memory, and asks for it by name otherwise', async () => {
    (harnessFetch as jest.Mock).mockResolvedValue({ ok: true, json: async () => ({ nodes: [], edges: [] }) });
    await readGraph('hmem_1');
    expect(JSON.parse((harnessFetch as jest.Mock).mock.calls[0][1].body)).toEqual({ hops: 1, limit: 500 });
    await readGraph('hmem_1', { around: 'r', hops: 3 });
    expect((harnessFetch as jest.Mock).mock.calls[1][0]).toBe('/api/harness/v1/memories/hmem_1/graph');
    expect(JSON.parse((harnessFetch as jest.Mock).mock.calls[1][1].body)).toEqual({ hops: 3, limit: 500, around: 'r' });
  });
  it('merges two reads, the later copy winning, and counts facts drawn as lines', () => {
    const a = graph([node(rec('x', 'entity')), node(rec('y', 'entity')), node(rec('f', 'fact'))], [edge('f', 'x', 'about'), edge('f', 'y', 'about')]);
    const b = graph([node(rec('x', 'entity', { title: 'New' }))], []);
    const m = exploreOf(mergeGraphs(a, b));
    expect(m.nodes.x.title).toBe('New');
    expect(m.edges).toHaveLength(1);
    expect(kindsIn(m).get('fact')).toBe(1);
    expect(recordsIn(m).map((r) => r.record.id).sort()).toEqual(['f', 'x', 'y']);
  });
  it('a fact that one read holds half of is still one line once the other half is read', () => {
    const near = graph([node(rec('x', 'entity')), node(rec('f', 'fact'))], [edge('f', 'x', 'about')]);
    const rest = graph([node(rec('x', 'entity')), node(rec('y', 'entity')), node(rec('f', 'fact'))], [edge('f', 'x', 'about'), edge('f', 'y', 'about')]);
    expect(exploreOf(near).nodes.f).toBeDefined();
    const m = exploreOf(mergeGraphs(near, rest));
    expect(m.nodes.f).toBeUndefined();
    expect(m.edges.map((e) => e.key)).toEqual([lineKey('f')]);
  });
  it('folding hides only what is left with nothing, and never what was put there by hand', () => {
    const g = exploreOf(graph(['hub', 'leaf', 'kept', 'other', 'mine'].map((x) => node(rec(x, 'note'))),
      [edge('hub', 'leaf', 'r'), edge('hub', 'kept', 'r'), edge('kept', 'other', 'r'), edge('hub', 'mine', 'r')]));
    const c = computeCollapse('hub', g.edges, new Set(['mine']));
    expect(c?.hidden).toEqual(['leaf']);
    expect(c?.removed).toHaveLength(3);
    expect(computeCollapse('other', [], new Set())).toBeNull();
  });
});
