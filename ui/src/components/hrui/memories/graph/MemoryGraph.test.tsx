/** @jest-environment jsdom */
// The explorer against a stand-in canvas: what it is given to draw, and where each click goes.
import { act, forwardRef, useImperativeHandle } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { CAPS, memory } from '../fixtures';
import type { Provider } from '@/lib/memories';

type CanvasProps = Record<string, (...a: unknown[]) => unknown> & { elements: { data: Record<string, unknown>; classes?: string }[]; selectedId: string | null; layout: string };
let canvasProps: CanvasProps;
const pinned: unknown[][] = [];
jest.mock('./CytoscapeCanvas.jsx', () => ({
  colorFor: () => ({ ring: '#123456' }),
  __esModule: true,
  default: forwardRef(function Stub(props: unknown, ref) {
    canvasProps = props as CanvasProps;
    useImperativeHandle(ref, () => ({ getCy: () => null, pinPositionsAndSkipLayout: (...a: unknown[]) => { pinned.push(a); } }));
    return <div data-testid="canvas" />;
  }),
}));
jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
jest.mock('@/lib/harness', () => ({ gwHeaders: () => ({}), listCustom: jest.fn(async () => []) }));
jest.mock('@/lib/auth', () => ({ getSession: () => null }));
jest.mock('@/lib/edition', () => ({ LOCAL_MEMBER: 'local@localhost' }));
jest.mock('../../setup/settingsModel', () => ({ plain: (_e: unknown, f: string) => f, plural: (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}` }));

import { harnessFetch } from '@/lib/hfetch';
import { MemoryGraph } from './MemoryGraph.jsx';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true, requestAnimationFrame: (f: () => void) => setTimeout(f, 0) });
let root: Root; let el: HTMLElement;
const flush = async () => { for (let i = 0; i < 12; i++) await act(async () => { await Promise.resolve(); }); };
const later = async (ms: number) => { await act(async () => { await new Promise((r) => setTimeout(r, ms)); }); await flush(); };
const click = async (b: Element) => { await act(async () => { (b as HTMLElement).dispatchEvent(new MouseEvent('click', { bubbles: true })); }); await flush(); };
const button = (t: string) => Array.from(el.querySelectorAll('button')).find((b) => (b.textContent || '').trim() === t) as HTMLButtonElement;
const rec = (id: string, type: string, o: Record<string, unknown> = {}) => ({ id, object: 'memory.record', memory_id: 'hmem_1', type, title: id, content: [], attributes: {}, references: [], status: 'active', ...o });
const n = (r: unknown, memory = { id: 'hmem_1', name: 'Here' }) => ({ record: r, memory });
const e = (from: string, to: string, rel?: string, available = true) => ({ from: { memory_id: 'hmem_1', record_id: from }, to: available ? { memory_id: 'hmem_1', record_id: to } : { record_id: to }, available, ...(rel ? { rel } : {}) });

let answer: (body: { around?: string; hops?: number }) => unknown;
const bodies: { around?: string; hops?: number; limit?: number }[] = [];
let opened: unknown[][];

function show(p: Partial<{ provider: Provider | null; activeRecordId: string; refreshKey: number; changed: string[] }> = {}) {
  return act(async () => {
    root.render(<div id="hrui"><MemoryGraph memory={memory({ id: 'hmem_1', name: 'Customers' })} provider={p.provider === undefined ? CAPS.graphiti : p.provider} schema={null}
      activeRecordId={p.activeRecordId || ''} refreshKey={p.refreshKey || 0} changed={p.changed} onOpenRecord={(...a: unknown[]) => { opened.push(a); }} /></div>);
  });
}
const nodes = () => canvasProps.elements.filter((x) => !x.data.source);
const edges = () => canvasProps.elements.filter((x) => x.data.source);

const whole = {
  nodes: [
    n(rec('acme', 'entity', { title: 'Acme' })), n(rec('pro', 'entity', { title: 'Photon Pro' })),
    n(rec('f1', 'fact', { title: '', content: [{ type: 'text', text: 'Acme bought Photon Pro.' }], attributes: { predicate: 'BUYS' } })),
    n(rec('ep', 'episode', { title: 'A task' })), n(rec('far', 'note', { title: 'Elsewhere' }), { id: 'hmem_2', name: 'Other memory' }),
  ],
  edges: [e('f1', 'acme', 'about'), e('f1', 'pro', 'about'), e('f1', 'ep', 'derived_from'), e('acme', 'ep', 'derived_from'), e('acme', 'far', 'part_of'), e('acme', 'hrec_secret', undefined, false)],
  truncated: false, degraded: [],
};

beforeEach(() => {
  localStorage.clear();
  opened = [];
  pinned.length = 0;
  bodies.length = 0;
  answer = () => whole;
  (harnessFetch as jest.Mock).mockReset();
  (harnessFetch as jest.Mock).mockImplementation(async (url: string, init: { body?: string }) => {
    if (url.endsWith('/graph')) { const b = JSON.parse(init.body || '{}'); bodies.push(b); return { ok: true, json: async () => answer(b) }; }
    if (url.endsWith('/recall')) return { ok: true, json: async () => ({ results: [], degraded: [] }) };
    return { ok: false, status: 404, json: async () => ({}) };
  });
  el = document.createElement('div');
  document.body.appendChild(el);
  root = createRoot(el);
});
afterEach(async () => { await act(async () => { root.unmount(); }); el.remove(); });

describe('on open', () => {
  it('reads the whole memory, and draws a fact as the line between what it relates', async () => {
    await show();
    await flush();
    expect(bodies[0].around).toBeUndefined();
    expect(nodes().map((x) => x.data.id).sort()).toEqual(['acme', 'closed:hrec_secret', 'ep', 'far', 'pro']);
    expect(edges().find((x) => x.data.id === 'line:f1')?.data).toMatchObject({ source: 'acme', target: 'pro', caption: 'BUYS' });
    expect(edges().find((x) => x.data.id === 'line:f1')?.classes).toBe('plain');
  });
  it('arranges by the layout on first paint, the record with the most links in the middle, and from where this person left it after that', async () => {
    await show();
    await flush();
    const first = pinned[0][0] as Record<string, { x: number; y: number }>;
    expect(Object.keys(first).sort()).toEqual(['acme', 'closed:hrec_secret', 'ep', 'far', 'pro']);
    expect(pinned[0][1]).toBe(true);
    expect(canvasProps.layout).toBe('none');
    const d = (a: string, b: string) => Math.hypot(first[a].x - first[b].x, first[a].y - first[b].y);
    ['ep', 'far', 'pro', 'closed:hrec_secret'].forEach((k) => expect(d('acme', k)).toBeLessThan(300));
    await act(async () => { root.unmount(); });
    root = createRoot(el);
    localStorage.setItem('mm-graph:hmem_1', JSON.stringify({ v: 1, positions: { acme: { x: 5, y: 6 }, pro: { x: 7, y: 8 }, ep: { x: 1, y: 1 }, far: { x: 2, y: 2 }, 'closed:hrec_secret': { x: 3, y: 3 } } }));
    pinned.length = 0;
    await show();
    await flush();
    expect(pinned[0][0]).toMatchObject({ acme: { x: 5, y: 6 } });
    expect(pinned[0][1]).toBe(true);
  });
  it('says what is true when empty, failed, unlinked or cut short', async () => {
    answer = () => ({ nodes: [], edges: [], truncated: false, degraded: [] });
    await show();
    await flush();
    expect(el.textContent).toContain('Nothing is kept here yet.');
    await act(async () => { root.unmount(); });
    root = createRoot(el);
    answer = () => ({ nodes: [n(rec('a', 'fact')), n(rec('b', 'fact'))], edges: [], truncated: true, degraded: [] });
    await show({ provider: CAPS.mem0 });
    await flush();
    expect(edges()).toEqual([]);
    expect(el.textContent).toContain('These records don’t link to each other.');
    expect(el.textContent).toContain('Only the first 500 records are drawn.');
    await act(async () => { root.unmount(); });
    root = createRoot(el);
    (harnessFetch as jest.Mock).mockImplementation(async () => ({ ok: false, status: 500, json: async () => ({}) }));
    await show();
    await flush();
    expect(el.querySelector('[role="alert"]')?.textContent).toContain('The graph could not be read just now.');
    expect(button('Try again')).toBeDefined();
  });
});

describe('going places', () => {
  it('a click opens the record, in its own memory', async () => {
    await show();
    await flush();
    await act(async () => { canvasProps.onTapNode('acme'); });
    await flush();
    expect(opened.pop()).toEqual(['acme', 'hmem_1']);
    await act(async () => { canvasProps.onTapNode('far'); });
    await flush();
    expect(opened.pop()).toEqual(['far', 'hmem_2']);
  });
  it('a line that is a fact opens the fact, and its ends and where it came from each lead there', async () => {
    await show();
    await flush();
    await act(async () => { canvasProps.onTapEdge('line:f1'); });
    await flush();
    expect(opened.pop()).toEqual(['f1', 'hmem_1']);
    const panel = el.querySelector('.dg-detail') as HTMLElement;
    expect(panel.textContent).toContain('Acme bought Photon Pro.');
    expect(panel.textContent).toContain('Came from');
    expect(panel.textContent).toContain('Endpoints');
    await click(Array.from(panel.querySelectorAll('button')).find((b) => b.textContent === 'Photon Pro') as Element);
    expect(opened.pop()).toEqual(['pro', 'hmem_1']);
  });
  it('a bare reference says what it means, and both ends lead there', async () => {
    await show();
    await flush();
    const id = String(edges().find((x) => x.data.target === 'far')?.data.id);
    await act(async () => { canvasProps.onTapEdge(id); });
    await flush();
    const panel = el.querySelector('.dg-detail') as HTMLElement;
    expect(panel.textContent).toContain('part of');
    await click(Array.from(panel.querySelectorAll('button')).find((b) => b.textContent === 'Elsewhere') as Element);
    expect(opened.pop()).toEqual(['far', 'hmem_2']);
  });
  it('a node\'s detail lists its links, a fact by its sentence, each one a way there', async () => {
    await show();
    await flush();
    await act(async () => { canvasProps.onTapNode('acme'); });
    await flush();
    const panel = el.querySelector('.dg-detail') as HTMLElement;
    await click(Array.from(panel.querySelectorAll('button')).find((b) => b.textContent === 'Acme bought Photon Pro.') as Element);
    expect(opened.pop()).toEqual(['f1', 'hmem_1']);
  });
  it('a record you can\'t open says only that: not its memory, not what the link means, and nothing opens', async () => {
    await show();
    await flush();
    const before = opened.length;
    await act(async () => { canvasProps.onTapNode('closed:hrec_secret'); });
    await flush();
    expect(opened).toHaveLength(before);
    const panel = el.querySelector('.dg-detail') as HTMLElement;
    expect(panel.textContent).toContain('A record you can’t open');
    expect(panel.textContent).not.toContain('hrec_secret');
    expect(nodes().find((x) => x.data.id === 'closed:hrec_secret')?.data.caption).toBe('Can’t open');
    const line = edges().find((x) => x.data.target === 'closed:hrec_secret');
    expect(line?.data.caption).toBe('');
    expect(line?.classes).toContain('closed');
  });
});

describe('active record, depth and change', () => {
  it('selects the open record, and a fact by its line', async () => {
    await show({ activeRecordId: 'acme' });
    await flush();
    expect(canvasProps.selectedId).toBe('acme');
    await show({ activeRecordId: 'f1' });
    await flush();
    expect(canvasProps.selectedId).toBe('line:f1');
  });
  it('asks for what is near the open record at the chosen depth, and offers depth only with one open', async () => {
    await show();
    await flush();
    expect(el.querySelector('button[aria-label="Within 1 link of the open record"]')).toHaveProperty('disabled', true);
    await show({ activeRecordId: 'acme' });
    await flush();
    await click(el.querySelector('button[aria-label="Within 2 links of the open record"]') as Element);
    expect(bodies.pop()).toMatchObject({ around: 'acme', hops: 2 });
    await click(button('All'));
    expect(bodies.pop()?.around).toBeUndefined();
  });
  it('a record the read doesn\'t hold is brought in once it is opened', async () => {
    answer = (b) => (b.around === 'x' ? { nodes: [n(rec('x', 'note'))], edges: [], truncated: false, degraded: [] } : whole);
    await show({ activeRecordId: 'x' });
    await flush();
    expect(nodes().some((v) => v.data.id === 'x')).toBe(true);
    expect(canvasProps.selectedId).toBe('x');
  });
  it('a refresh re-reads, and removed records go', async () => {
    await show();
    await flush();
    answer = () => ({ nodes: [n(rec('acme', 'entity', { title: 'Acme' })), n(rec('new', 'note', { title: 'New one' }))], edges: [e('new', 'acme', 'about')], truncated: false, degraded: [] });
    await show({ refreshKey: 1 });
    await flush();
    expect(nodes().map((x) => x.data.id).sort()).toEqual(['acme', 'new']);
  });
  it('double click brings in what it links to, and says so when there is nothing more', async () => {
    await show();
    await flush();
    answer = (b) => (b.around === 'ep' ? { nodes: [n(rec('ep', 'episode', { title: 'A task' })), n(rec('more', 'note', { title: 'More' }))], edges: [e('more', 'ep', 'derived_from')], truncated: false, degraded: [] } : whole);
    await act(async () => { canvasProps.onDblTapNode('ep'); });
    await flush();
    expect(nodes().some((x) => x.data.id === 'more')).toBe(true);
    expect(bodies.pop()).toMatchObject({ around: 'ep', hops: 1 });
  });
  it('a kind can be hidden from the legend, and its lines with it', async () => {
    await show();
    await flush();
    await click(Array.from(el.querySelectorAll('.mgv-legend button')).find((b) => (b.textContent || '').startsWith('Facts')) as Element);
    expect(edges().some((x) => x.data.id === 'line:f1')).toBe(false);
    expect(nodes().some((x) => x.data.id === 'acme')).toBe(true);
  });
});

describe('search', () => {
  it('finds what is on the canvas, a fact by its sentence, and opens it', async () => {
    await show();
    await flush();
    const input = el.querySelector('input[aria-label="Search nodes"]') as HTMLInputElement;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set?.call(input, 'bought');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await flush();
    const hit = el.querySelector('.sb-drop-item') as HTMLElement;
    expect(hit.textContent).toContain('Acme bought Photon Pro.');
    await act(async () => { hit.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); });
    await flush();
    expect(opened.pop()).toEqual(['f1', 'hmem_1']);
    await later(10);
  });
});
