/** @jest-environment jsdom */
// A memory's picture (Richard 11-09): the graph its engine draws, kept and only loaded; or, where there is no graph,
// its brick from the agent stack. What counts as a graph, the name a drawing goes by, and what a card shows for each.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { GraphEdge, GraphNode, MemoryGraph, MemoryRecord, Provider } from '@/lib/memories';
import { CAPS } from './fixtures';

jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
jest.mock('@/lib/harness', () => ({ gwHeaders: () => ({}) }));
const drawCover = jest.fn();
jest.mock('./graph/coverShot', () => ({ drawCover: (...a: unknown[]) => drawCover(...a) }));

import { harnessFetch } from '@/lib/hfetch';
import { brickSvg } from '../tower';
import { coverGraphOf, coverSig, coverState, DRAW_VERSION, heldFlat, isGraph, keepCover, markHeldLooked, picKindOf } from './cover';
import { heldOf } from './graph/held';
import { MemoryArt } from './MemoryArt';
import { schemaIn } from './schemaModel';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const B = (types: string[], relations: [string, string, string][]) => ({
  types: types.map((name) => ({ name, description: '' })), relations: relations.map(([name, from, to]) => ({ name, from, to, description: '' })),
});
const withBuiltin = (p: Provider, b: ReturnType<typeof B>) => ({ ...p, schema: { ...p.schema, builtin: b } }) as Provider;
const mem0 = withBuiltin(CAPS.mem0, B(['fact'], []));
const graphiti = withBuiltin(CAPS.graphiti, B(['episode', 'entity', 'fact'], [['about', 'fact', 'entity'], ['derived_from', 'fact', 'episode']]));
const labels = withBuiltin(CAPS.hindsight, B([], []));
// what a Mem0 memory held on the test instance: facts, the names in them, and notes about those names
const rec = (id: string, type: string): MemoryRecord => ({
  id, object: 'memory.record', memory_id: 'hmem_1', type, title: id, content: [], attributes: {}, version: 1, status: 'active', supersedes: null,
  time: { valid_from: null, valid_to: null, written_at: null, invalidated_at: null }, written_by: { kind: 'provider', id: 'x' }, references: [], trust: 'untrusted',
});
const nodeOf = (r: MemoryRecord): GraphNode => ({ record: r, memory: { id: 'hmem_1', name: 'Company' } });
const edgeOf = (from: string, to: string, rel: string): GraphEdge => ({ from: { memory_id: 'hmem_1', record_id: from }, to: { memory_id: 'hmem_1', record_id: to }, rel, available: true });
const graphOf = (nodes: GraphNode[], edges: GraphEdge[]): MemoryGraph => ({ nodes, edges, truncated: false, degraded: [] });
const HOLDS = graphOf([nodeOf(rec('acme', 'entity')), nodeOf(rec('f1', 'fact')), nodeOf(rec('n1', 'note'))],
  [edgeOf('f1', 'acme', 'about'), edgeOf('n1', 'acme', 'about')]);

describe('what is a graph', () => {
  test('types joined by a relation are; one type alone, names that relate to nothing, or a type related to itself are not', () => {
    expect(isGraph(coverGraphOf(null, mem0))).toBe(false);
    expect(isGraph(coverGraphOf(schemaIn({ types: [{ name: 'Urgent' }, { name: 'Billing' }] }), labels))).toBe(false);
    expect(isGraph(coverGraphOf(schemaIn({ types: [{ name: 'Person' }], relations: [{ name: 'KNOWS', from: 'Person', to: 'Person' }] }), CAPS.graphiti))).toBe(false);
    expect(isGraph(coverGraphOf(null, graphiti))).toBe(true);
    expect(isGraph(coverGraphOf(schemaIn({ types: [{ name: 'Person' }, { name: 'Company' }], relations: [{ name: 'WORKS_AT', from: 'Person', to: 'Company' }] }), CAPS.graphiti))).toBe(true);
  });
  test('a card knows from the list alone: the kept cover, what it holds to read, a graph to make, one only its schema can say, or the brick', () => {
    expect(picKindOf({ cover_at: 5 }, mem0)).toBe('cover');
    expect(picKindOf({}, graphiti)).toBe('graph');
    expect(picKindOf({}, CAPS.graphiti)).toBe('maybe');
    // where nobody sets types (Mem0, ReMe), the Schema tab draws what the memory holds, and so does its cover
    expect(picKindOf({}, mem0)).toBe('held');
    expect(picKindOf({}, CAPS.reme)).toBe('held');
    expect(picKindOf({}, labels)).toBe('brick');
    expect(picKindOf({ cover_at: null }, null)).toBe('brick');
  });
});

describe('the name a drawing goes by', () => {
  const doc = { types: [{ name: 'Person', color: '#3b82f6', icon: 'person', x: 10, y: 20 }, { name: 'Company', color: '#ec4899', icon: 'building', x: 200, y: 20 }],
    relations: [{ name: 'WORKS_AT', from: 'Person', to: 'Company', color: '#ef4444' }] };
  const sig = (d: typeof doc) => coverSig(coverGraphOf(schemaIn(d), graphiti));
  test('the same drawing is always the same name, whatever order it was read in', () => {
    expect(sig(doc)).toBe(sig(JSON.parse(JSON.stringify(doc))));
    expect(sig(doc)).toBe(sig({ ...doc, types: [...doc.types].reverse() }));
    expect(sig(doc)).toMatch(new RegExp(`^c${DRAW_VERSION}s_[0-9a-z]{1,16}$`));
  });
  test('it says whether the drawing is only what the provider makes, has a person’s own types, or is what the memory holds', () => {
    expect(coverSig(coverGraphOf(null, graphiti))).toMatch(/^c\d+b_/);
    expect(sig(doc)).toMatch(/^c\d+s_/);
    expect(coverSig(heldOf(HOLDS, mem0).graph)).toMatch(new RegExp(`^c${DRAW_VERSION}h_[0-9a-z]+$`));
  });
  test('a name, colour, icon, place or relation changed is another drawing', () => {
    const was = sig(doc);
    const t0 = doc.types[0];
    for (const d of [
      { ...doc, types: [{ ...t0, name: 'Human' }, doc.types[1]] },
      { ...doc, types: [{ ...t0, color: '#111827' }, doc.types[1]] },
      { ...doc, types: [{ ...t0, icon: 'star' }, doc.types[1]] },
      { ...doc, types: [{ ...t0, x: 11 }, doc.types[1]] },
      { ...doc, relations: [{ ...doc.relations[0], name: 'LEADS' }] },
      { ...doc, relations: [{ ...doc.relations[0], color: '#14b8a6' }] },
      { ...doc, relations: [] },
    ]) expect(sig(d as typeof doc)).not.toBe(was);
  });
});

describe('a cover kept from before', () => {
  const now = coverSig(coverGraphOf(null, graphiti));
  test('one of what the provider makes is checked against the provider list alone, and made again when it differs', () => {
    expect(coverState({ id: 'hmem_x', cover_at: 1, cover_sig: now }, graphiti)).toBe('fresh');
    expect(coverState({ id: 'hmem_x', cover_at: 1, cover_sig: now.replace(`c${DRAW_VERSION}`, `c${DRAW_VERSION - 1}`) }, graphiti)).toBe('builtin');
    expect(coverState({ id: 'hmem_x', cover_at: 1, cover_sig: `c${DRAW_VERSION}b_0` }, graphiti)).toBe('builtin');
  });
  test('one with a person’s own types waits for its Schema tab, whatever its version', () => {
    expect(coverState({ id: 'hmem_x', cover_at: 1, cover_sig: `c${DRAW_VERSION - 1}s_abc` }, graphiti)).toBe('fresh');
  });
  test('one made before drawings said which they were is read once where the provider reads a schema, else made from the list', () => {
    expect(coverState({ id: 'hmem_x', cover_at: 1, cover_sig: 'c1abc123' }, graphiti)).toBe('read');
    const reme = withBuiltin(CAPS.reme, B(['episode', 'note'], [['derived_from', 'note', 'episode']]));
    // where the cover is what the memory holds, one drawn before it showed that is read again
    expect(coverState({ id: 'hmem_x', cover_at: 1, cover_sig: 'c1abc123' }, reme)).toBe('held');
    expect(coverState({ id: 'hmem_x', cover_at: null, cover_sig: null }, graphiti)).toBe('fresh');
  });
});

describe('a cover of what a memory holds', () => {
  afterEach(() => window.localStorage.clear());
  test('the Schema tab’s drawing: the kinds it holds and how they refer to each other, with what the engine makes beside them', () => {
    const g = heldOf(HOLDS, mem0).graph;
    expect(g.vertex_types.map((v) => v.label)).toEqual(['entity', 'fact', 'note']);
    expect(isGraph(g)).toBe(true);
    // one kind alone is no graph: Mem0 holding only facts keeps its brick
    expect(isGraph(heldOf(graphOf([nodeOf(rec('f1', 'fact'))], []), mem0).graph)).toBe(false);
  });
  test('the same kinds and links are the same drawing, whatever order they were read in and however many there are', () => {
    const again = graphOf([...HOLDS.nodes].reverse(), [...HOLDS.edges].reverse());
    const more = graphOf([...HOLDS.nodes, nodeOf(rec('n9', 'note'))], [...HOLDS.edges, edgeOf('n9', 'acme', 'about')]);
    expect(coverSig(heldOf(again, mem0).graph)).toBe(coverSig(heldOf(HOLDS, mem0).graph));
    expect(coverSig(heldOf(more, mem0).graph)).toBe(coverSig(heldOf(HOLDS, mem0).graph));
    const newKind = graphOf([...HOLDS.nodes, nodeOf(rec('p1', 'procedure'))], HOLDS.edges);
    expect(coverSig(heldOf(newKind, mem0).graph)).not.toBe(coverSig(heldOf(HOLDS, mem0).graph));
  });
  test('kept, it is looked at again only once the memory has been used since it was made, or since this browser last looked', () => {
    const sig = coverSig(heldOf(HOLDS, mem0).graph), T = 1762700000000;
    expect(coverState({ id: 'hmem_h', cover_at: T + 100, cover_sig: sig, last_used_at: T + 50 }, mem0)).toBe('fresh');
    expect(coverState({ id: 'hmem_h', cover_at: T + 100, cover_sig: sig, last_used_at: T + 200 }, mem0)).toBe('held');
    markHeldLooked('hmem_h', false, T + 300);
    expect(coverState({ id: 'hmem_h', cover_at: T + 100, cover_sig: sig, last_used_at: T + 200 }, mem0)).toBe('fresh');
    expect(coverState({ id: 'hmem_h', cover_at: T + 100, cover_sig: sig, last_used_at: T + 400 }, mem0)).toBe('held');
  });
  test('one that held no graph when last read here keeps its brick, with no read, until it is used again', () => {
    const T = 1762700000000;
    markHeldLooked('hmem_f', true, T + 300);
    expect(heldFlat({ id: 'hmem_f', cover_at: null, last_used_at: T + 200 })).toBe(true);
    expect(heldFlat({ id: 'hmem_f', cover_at: null, last_used_at: T + 400 })).toBe(false);
    markHeldLooked('hmem_f', false, T + 500);
    expect(heldFlat({ id: 'hmem_f', cover_at: null, last_used_at: T + 200 })).toBe(false);
  });
});

describe('making one', () => {
  beforeEach(() => {
    drawCover.mockReset();
    drawCover.mockResolvedValue(new Blob(['p'], { type: 'image/png' }));
    (harnessFetch as jest.Mock).mockReset();
    (harnessFetch as jest.Mock).mockResolvedValue({ ok: true, json: async () => ({ cover_at: 1, cover_sig: 'x' }) });
    Object.assign(window, { CanvasRenderingContext2D: function CanvasRenderingContext2D() { /* a canvas */ } });
    Object.assign(URL, { createObjectURL: jest.fn(() => 'blob:made'), revokeObjectURL: jest.fn() });
  });
  afterEach(() => { delete (window as { CanvasRenderingContext2D?: unknown }).CanvasRenderingContext2D; });
  const g = coverGraphOf(null, graphiti);
  test('nothing is drawn where the kept cover shows this drawing, or there is no graph', async () => {
    expect(await keepCover({ id: 'hmem_a', cover_at: 4, cover_sig: coverSig(g) }, g, true)).toBeNull();
    expect(await keepCover({ id: 'hmem_b' }, coverGraphOf(null, mem0), true)).toBeNull();
    expect(drawCover).not.toHaveBeenCalled();
    expect(harnessFetch).not.toHaveBeenCalled();
  });
  test('drawn once and kept, and asked again, the one made is given back', async () => {
    const one = await keepCover({ id: 'hmem_c' }, g, true);
    const two = await keepCover({ id: 'hmem_c' }, g, true);
    expect(one).toEqual({ sig: coverSig(g), url: 'blob:made' });
    expect(two).toBe(one);
    expect(drawCover).toHaveBeenCalledTimes(1);
    const [url, init] = (harnessFetch as jest.Mock).mock.calls[0];
    expect([url, init.method, init.headers['x-cover-sig']]).toEqual(['/api/harness/v1/memories/hmem_c/cover', 'PUT', coverSig(g)]);
  });
  test('not kept where the person may only read it, and a keep that fails still shows the picture', async () => {
    expect(await keepCover({ id: 'hmem_d' }, g, false)).toEqual({ sig: coverSig(g), url: 'blob:made' });
    expect(harnessFetch).not.toHaveBeenCalled();
    (harnessFetch as jest.Mock).mockResolvedValue({ ok: false, status: 503, json: async () => ({ error: { message: 'Not now.' } }) });
    expect(await keepCover({ id: 'hmem_e' }, g, true)).toEqual({ sig: coverSig(g), url: 'blob:made' });
  });
});

describe('the brick', () => {
  test('is the Memory brick of the agent stack, built, alone on its shadow, with no words in it', () => {
    const svg = brickSvg('memory', 'built');
    const host = document.createElement('div');
    host.innerHTML = svg;
    expect(host.querySelector('svg.iso > g > .iso-shadow')).not.toBeNull();
    const brick = host.querySelector('.bk.f-memory.built') as Element;
    expect(brick.querySelectorAll('polygon.t, polygon.l, polygon.r')).toHaveLength(3);
    expect(brick.querySelector('ellipse.su')).not.toBeNull();
    expect(host.querySelector('text')).toBeNull();
    expect(host.querySelector('svg')?.getAttribute('aria-hidden')).toBe('true');
  });
  test('a memory with no graph shows it on its card, and one with a cover shows the cover only', () => {
    const host = document.createElement('div');
    const r = createRoot(host);
    act(() => r.render(<MemoryArt m={{ id: 'hmem_1' }} kind="brick" />));
    expect(host.querySelector('.mm-brick .f-memory.built')).not.toBeNull();
    act(() => r.render(<MemoryArt m={{ id: 'hmem_1' }} kind="graph" />));
    expect(host.querySelector('.mm-cv-wait')).not.toBeNull();
    expect(host.querySelector('svg')).toBeNull();
    act(() => r.render(<MemoryArt m={{ id: 'hmem_1', cover_sig: 'c1a' }} kind="graph" drawn={{ sig: 'c1a', url: 'blob:here' }} />));
    expect(host.querySelector('img')?.getAttribute('src')).toBe('blob:here');
    act(() => r.unmount());
  });
});
