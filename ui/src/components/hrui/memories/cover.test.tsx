/** @jest-environment jsdom */
// A memory's picture (Richard 11-09): the graph its engine draws, kept and only loaded; or, where there is no graph,
// its brick from the agent stack. What counts as a graph, the name a drawing goes by, and what a card shows for each.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Provider } from '@/lib/memories';
import { CAPS } from './fixtures';

jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
jest.mock('@/lib/harness', () => ({ gwHeaders: () => ({}) }));
const drawCover = jest.fn();
jest.mock('./graph/coverShot', () => ({ drawCover: (...a: unknown[]) => drawCover(...a) }));

import { harnessFetch } from '@/lib/hfetch';
import { brickSvg } from '../tower';
import { coverGraphOf, coverSig, isGraph, keepCover, picKindOf } from './cover';
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

describe('what is a graph', () => {
  test('types joined by a relation are; one type alone, names that relate to nothing, or a type related to itself are not', () => {
    expect(isGraph(coverGraphOf(null, mem0))).toBe(false);
    expect(isGraph(coverGraphOf(schemaIn({ types: [{ name: 'Urgent' }, { name: 'Billing' }] }), labels))).toBe(false);
    expect(isGraph(coverGraphOf(schemaIn({ types: [{ name: 'Person' }], relations: [{ name: 'KNOWS', from: 'Person', to: 'Person' }] }), CAPS.graphiti))).toBe(false);
    expect(isGraph(coverGraphOf(null, graphiti))).toBe(true);
    expect(isGraph(coverGraphOf(schemaIn({ types: [{ name: 'Person' }, { name: 'Company' }], relations: [{ name: 'WORKS_AT', from: 'Person', to: 'Company' }] }), CAPS.graphiti))).toBe(true);
  });
  test('a card knows from the list alone: the kept cover, a graph to make, one only its schema can say, or the brick', () => {
    expect(picKindOf({ cover_at: 5 }, mem0)).toBe('cover');
    expect(picKindOf({}, graphiti)).toBe('graph');
    expect(picKindOf({}, CAPS.graphiti)).toBe('maybe');
    expect(picKindOf({}, mem0)).toBe('brick');
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
    expect(sig(doc)).toMatch(/^c1[0-9a-z]{1,16}$/);
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
