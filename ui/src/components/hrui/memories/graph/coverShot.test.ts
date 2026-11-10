/** @jest-environment jsdom */
// A memory's cover is the Schema tab's canvas, rendered the same way (Richard 11-09): the same stylesheet object, the
// same elements from the same function, straight links, the canvas's own sizes, and only the export scale chosen for
// the card. The one difference is the record count, which a stored picture can't keep true.
const made: { opts: Record<string, unknown>; styled: unknown[]; png: Record<string, unknown>[] }[] = [];
jest.mock('cytoscape', () => {
  const fn = (opts: Record<string, unknown>) => {
    const rec = { opts, styled: [] as unknown[], png: [] as Record<string, unknown>[] };
    made.push(rec);
    const coll = () => ({ style: (o: unknown) => { rec.styled.push(o); }, length: 0, forEach: () => {} });
    return {
      fit: () => {}, nodes: coll, edges: coll, batch: (f: () => void) => f(), renderer: () => ({ imageCache: {} }),
      elements: () => ({ boundingBox: () => ({ x1: 0, y1: 0, w: 400, h: 300 }) }),
      png: (o: Record<string, unknown>) => { rec.png.push(o); return o.output === 'blob-promise' ? Promise.resolve(new Blob(['p'], { type: 'image/png' })) : ''; },
      destroy: () => {},
    };
  };
  fn.use = () => {};
  return { __esModule: true, default: fn };
});

import { CANVAS_STYLE } from './CytoscapeCanvas.jsx';
import { buildSchemaElements, schemaCaption } from './schemaElements';
import { CARD, FILL, coverElements, coverOptions, coverScale, drawCover } from './coverShot';
import { coverGraphOf } from '../cover';
import { schemaIn } from '../schemaModel';
import type { Provider } from '@/lib/memories';

const graphiti = { id: 'graphiti', schema: { mode: 'guides', properties: true, relations: true, builtin: {
  types: [{ name: 'episode', description: '' }, { name: 'entity', description: '' }, { name: 'fact', description: '' }],
  relations: [{ name: 'about', from: 'fact', to: 'entity', description: '' }, { name: 'derived_from', from: 'fact', to: 'episode', description: '' }],
} } } as unknown as Provider;
const graph = coverGraphOf(schemaIn({ types: [{ name: 'Company', color: '#ec4899', icon: 'building', x: 470, y: 150 }, { name: 'Person', color: '#3b82f6', icon: 'person', x: 260, y: 430 }],
  relations: [{ name: 'WORKS_AT', from: 'Person', to: 'Company' }] }), graphiti);

test('the cover is drawn with the canvas’s own stylesheet, the very same object', () => {
  expect(coverOptions(document.createElement('div'), []).style).toBe(CANVAS_STYLE);
});

test('its elements are the canvas’s, from the same function: same places, same straight links, names less the count', () => {
  // the Schema tab names a type schemaCaption(graph, label, d, "<n> records"); the cover gives no count
  const canvas = buildSchemaElements(graph, null, null, (l: string, d: unknown) => schemaCaption(graph, l, d, '3 records'));
  const cover = coverElements(graph);
  expect(cover.map((e: { data: { id: string } }) => e.data.id)).toEqual(canvas.map((e: { data: { id: string } }) => e.data.id));
  cover.forEach((e: { data: Record<string, unknown>; position?: unknown; classes?: string }, i: number) => {
    const c = canvas[i] as { data: Record<string, unknown>; position?: unknown; classes?: string };
    expect(e.position).toEqual(c.position);
    expect(e.classes).toEqual(c.classes);
    const { caption: a, ...restA } = e.data, { caption: b, ...restB } = c.data;
    expect(restA).toEqual(restB);
    // the one difference: no count; "Built in" stays where the canvas says it
    expect(String(b).replace(/ · 3 records|\n3 records/, '')).toBe(a);
  });
  expect(cover.find((e: { data: { id: string } }) => e.data.id === 'episode').data.caption).toBe('Episode\nBuilt in');
  expect(cover.find((e: { data: { id: string } }) => e.data.id === 'Company').data.caption).toBe('Company');
});

test('drawn at the canvas’s own sizes, links never bowed: only the export scale fills the card', async () => {
  made.length = 0;
  await drawCover(graph);
  const rec = made[0];
  expect(rec.opts.style).toBe(CANVAS_STYLE);
  expect(rec.styled).toEqual([]);
  const taken = rec.png.find((o) => o.output === 'blob-promise') as Record<string, unknown>;
  expect(taken.full).toBe(true);
  expect(taken.scale).toBeCloseTo(coverScale({ w: 400, h: 300 }) * 2);
  expect(coverScale({ w: 400, h: 300 })).toBeCloseTo(Math.min((CARD.w * FILL) / 400, (CARD.h * FILL) / 300));
});
