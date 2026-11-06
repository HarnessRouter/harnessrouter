/** @jest-environment jsdom */
// The schema pane against the capability document. Clicking a type or a link opens the same panel whatever the provider;
// only what can change differs. And the round trip that matters: what Save sends is what the provider reads, and any
// icon and caption come back as they went.
import { act, forwardRef, useImperativeHandle } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { CAPS, memory } from '../fixtures';
import type { Provider } from '@/lib/memories';

type CanvasProps = Record<string, (...a: unknown[]) => unknown> & { elements: { data: Record<string, unknown>; position?: { x: number; y: number }; classes?: string }[]; edgeDrawEnabled: boolean };
let canvasProps: CanvasProps;
jest.mock('./CytoscapeCanvas.jsx', () => ({
  __esModule: true,
  default: forwardRef(function Stub(props: unknown, ref) { canvasProps = props as CanvasProps; useImperativeHandle(ref, () => ({ getCy: () => null })); return <div data-testid="canvas" />; }),
  colorFor: () => ({ ring: '#123456' }),
}));
jest.mock('./iconCatalog.jsx', () => ({
  searchIcons: (q: string) => ['Building2', 'Rocket'].filter((n) => n.toLowerCase().includes(q.toLowerCase())),
  IconByName: ({ name }: { name: string }) => <i data-icon={name} />,
  getIconUrl: (name: string) => `data:image/svg+xml;utf8,${name}`,
}));
jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
jest.mock('@/lib/harness', () => ({ gwHeaders: () => ({}), listCustom: jest.fn(async () => []) }));
jest.mock('@/lib/auth', () => ({ getSession: () => null }));
jest.mock('@/lib/edition', () => ({ LOCAL_MEMBER: 'local@localhost' }));
jest.mock('../../setup/settingsModel', () => ({
  plain: (e: unknown, f: string) => (e instanceof Error && e.message ? e.message : f),
  plural: (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`,
}));

import { harnessFetch } from '@/lib/hfetch';
import { schemaIn, schemaOut } from '../schemaModel';
import { useSchemaDoc } from '../useSchemaDoc';
import { SchemaEditor } from './SchemaEditor.jsx';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true, requestAnimationFrame: (f: () => void) => setTimeout(f, 0) });
let root: Root; let el: HTMLElement;
let stored: unknown;
let puts: Record<string, unknown>[];
let graphAnswer: unknown;
const flush = async () => { for (let i = 0; i < 12; i++) await act(async () => { await Promise.resolve(); }); };
const later = async (ms: number) => { await act(async () => { await new Promise((r) => setTimeout(r, ms)); }); await flush(); };
const button = (t: string) => Array.from(el.querySelectorAll('button')).find((b) => (b.textContent || '').trim() === t) as HTMLButtonElement;
const click = async (b: Element) => { await act(async () => { (b as HTMLElement).dispatchEvent(new MouseEvent('click', { bubbles: true })); }); await flush(); };
const type = async (input: Element, v: string) => {
  const proto = input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  await act(async () => {
    Object.getOwnPropertyDescriptor(proto, 'value')?.set?.call(input, v);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await flush();
};
const pick = async (select: Element, v: string) => {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')?.set?.call(select, v);
    select.dispatchEvent(new Event('change', { bubbles: true }));
  });
  await flush();
};
const q = (s: string) => el.querySelector(s) as HTMLElement;
const panel = () => el.querySelector('.dg-detail') as HTMLElement;
const tools = () => el.querySelector('.dg-canvas-tools') as HTMLElement;

function Page({ provider, ro = false, onOpenData = () => {} }: { provider: Provider; ro?: boolean; onOpenData?: (t: string) => void }) {
  const doc = useSchemaDoc('hmem_1', provider);
  return <div id="hrui"><SchemaEditor memory={memory({ name: 'Customers', provider: provider.id })} provider={provider} doc={doc} ro={ro} countOf={() => 2} onOpenData={onOpenData} /></div>;
}
async function open(provider: Provider, props: { ro?: boolean; onOpenData?: (t: string) => void } = {}) {
  await act(async () => { root.render(<Page provider={provider} {...props} />); });
  await flush();
}
const nodes = () => canvasProps.elements.filter((e) => !e.data.source);
const edges = () => canvasProps.elements.filter((e) => e.data.source);

beforeEach(() => {
  puts = [];
  stored = {
    types: [
      { name: 'Company', description: 'A customer.', color: '#ec4899', icon: 'building', x: 100, y: 100, caption: 'website', properties: [{ name: 'website', type: 'text' }, { name: 'tier', type: 'choice', options: ['a', 'b'] }] },
      { name: 'Person', color: '#3b82f6', icon: 'person', x: 300, y: 300, properties: [] },
    ],
    relations: [{ name: 'WORKS_AT', description: 'Where they work.', from: 'Person', to: 'Company', color: '#ef4444' }],
  };
  graphAnswer = { nodes: [], edges: [] };
  (harnessFetch as jest.Mock).mockReset();
  (harnessFetch as jest.Mock).mockImplementation(async (url: string, init: { method: string; body?: string }) => {
    if (url.endsWith('/schema') && init.method === 'GET') return { ok: true, json: async () => stored };
    if (url.endsWith('/schema') && init.method === 'PUT') { const b = JSON.parse(init.body || '{}'); puts.push(b); stored = b; return { ok: true, json: async () => b }; }
    if (url.endsWith('/graph')) return { ok: true, json: async () => graphAnswer };
    return { ok: false, status: 404, json: async () => ({}) };
  });
  el = document.createElement('div');
  document.body.appendChild(el);
  root = createRoot(el);
});
afterEach(async () => { await act(async () => { root.unmount(); }); el.remove(); });

describe('the canvas and its toolbar, as the original has them', () => {
  it('draws one node per type and one edge per pair, from what the service holds', async () => {
    await open(CAPS.graphiti);
    expect(nodes().map((n) => n.data.id)).toEqual(['Company', 'Person']);
    expect(nodes()[0].position).toEqual({ x: 100, y: 100 });
    expect(String(nodes()[0].data.iconUrl)).toMatch(/^data:image\/svg/);
    expect(edges()[0].data).toMatchObject({ source: 'Person', target: 'Company', caption: 'WORKS_AT', edgeLabel: 'WORKS_AT', lineColor: '#ef4444' });
    expect(el.textContent).toContain('Graphiti uses these types to decide what to pull out of each task.');
  });
  it('has the pencil, + Type and the expand, and nothing else until there is something to save', async () => {
    await open(CAPS.graphiti);
    expect(Array.from(tools().children).map((c) => c.getAttribute('aria-label') || c.textContent)).toEqual(['Inspect selected type', '+ Type', 'expand']);
    await click(q('.dg-canvas-tools button[aria-label="expand"]'));
    expect(q('.mgv').classList.contains('is-max')).toBe(true);
    await click(q('.dg-canvas-tools button[aria-label="Inspect selected type"]'));
    expect(panel().textContent).toContain('Company');   // the first type is selected on load, as in the original
    await click(q('.dg-canvas-tools button[aria-label="Inspect selected type"]'));
    expect(panel()).toBeNull();
  });
});

describe('a click or a double click on a type or a link opens the panel', () => {
  it.each(['onTapNode', 'onDblTapNode'])('%s on a type: colour, icon, caption, properties, add, delete', async (how) => {
    await open(CAPS.graphiti);
    await act(async () => { canvasProps[how]('Company', {}); });
    await flush();
    const p = panel();
    expect((p.querySelector('input[aria-label="Name"]') as HTMLInputElement).value).toBe('Company');
    expect((p.querySelector('textarea[aria-label="Description"]') as HTMLTextAreaElement).value).toBe('A customer.');
    expect(p.textContent).toContain('Color');
    expect(p.querySelectorAll('button[aria-label^="Color #"]')).toHaveLength(12);
    expect(p.textContent).toContain('Icon');
    expect(p.querySelector('.icon-combo-name')?.textContent).toBe('building');
    expect((p.querySelector('select[aria-label="Caption"]') as HTMLSelectElement).value).toBe('website');
    expect(p.textContent).toContain('Which field labels each Company on the canvas.');
    expect(Array.from(p.querySelectorAll('.prop-row input[aria-label="Property name"]')).map((i) => (i as HTMLInputElement).value)).toEqual(['website', 'tier']);
    expect(Array.from(p.querySelectorAll('.prop-row select[aria-label="Property type"]')).map((s) => s.textContent)).toEqual(['Text', 'Choice']);
    expect(p.querySelector('button[aria-label="Delete website"]')).not.toBeNull();
    expect(button('+ Add property')).toBeDefined();
    expect(button('Delete this type')).toBeDefined();
    expect(p.textContent).toContain('Records already kept stay as they are.');
    expect(p.textContent).toContain('Types work best for things with a name');
  });
  it.each(['onTapEdge', 'onDblTapEdge'])('%s on a link: its colour, description and endpoints', async (how) => {
    await open(CAPS.graphiti);
    await act(async () => { canvasProps[how]('e', { edgeLabel: 'WORKS_AT' }); });
    await flush();
    const p = panel();
    expect((p.querySelector('input[aria-label="Name"]') as HTMLInputElement).value).toBe('WORKS_AT');
    expect((p.querySelector('textarea[aria-label="Description"]') as HTMLTextAreaElement).value).toBe('Where they work.');
    expect(p.querySelector('button[aria-label="Color #EF4444"]')?.getAttribute('aria-pressed')).toBe('true');
    expect(p.textContent).toContain('Endpoints');
    expect(p.querySelector('.endpoint-row')?.textContent).toContain('Person');
    expect(p.querySelector('button[aria-label="Add endpoint"]')).not.toBeNull();
    expect(p.textContent).toContain('Relations you name replace the words');
    expect(button('Delete this type')).toBeDefined();
  });
});

describe('the round trip', () => {
  it('holds cosmetic and additive edits until Save, then writes them all at once, whole', async () => {
    await open(CAPS.graphiti);
    await act(async () => { canvasProps.onNodeDragEnd('Company', { x: 412.4, y: 87.6 }, {}); });
    await flush();
    expect(nodes()[0].position).toEqual({ x: 412, y: 88 });
    await act(async () => { canvasProps.onTapNode('Company'); });
    await flush();
    await click(q('button[aria-label="Color #4F46E5"], button[aria-label="Color #3B82F6"]'));
    // any icon in the whole catalogue
    await click(q('.icon-combo-trigger'));
    await type(q('.icon-combo-search'), 'rock');
    await click(q('.icon-combo-item'));
    expect(q('.icon-combo-name').textContent).toBe('Rocket');
    await pick(q('select[aria-label="Caption"]'), 'tier');
    await type(q('textarea[aria-label="Description"]'), 'A paying customer.');
    await click(button('+ Add property'));
    await type(q('input[aria-label="New property name"]'), 'Seats Sold');
    await pick(q('select[aria-label="New property type"]'), 'number');
    await type(q('input[aria-label="Name"]'), 'Customer Co');
    expect(nodes()[0].data.caption).toContain('Customer Co');
    await later(700);
    expect(puts).toEqual([]);
    await click(button('Save'));
    await later(20);
    expect(puts).toHaveLength(1);
    expect(puts[0]).toMatchObject({
      types: [
        { name: 'Customer_Co', description: 'A paying customer.', color: '#3B82F6', icon: 'Rocket', x: 412, y: 88, caption: 'tier',
          properties: [{ name: 'website', type: 'text' }, { name: 'tier', type: 'choice' }, { name: 'seats_sold', type: 'number' }] },
        { name: 'Person', x: 300, y: 300 },
      ],
      relations: [{ name: 'WORKS_AT', from: 'Person', to: 'Customer_Co', color: '#ef4444' }],
    });
    expect(el.textContent).toContain('Saved');
    // the panel follows the rename, and the toolbar's Save has gone
    expect((q('input[aria-label="Name"]') as HTMLInputElement).value).toBe('Customer Co');
    expect(Array.from(tools().children).length).toBe(3);
    // it comes back as it went
    const again = schemaIn(puts[0] as never);
    expect(again.types[0]).toMatchObject({ icon: 'Rocket', caption: 'tier', x: 412, y: 88 });
    expect(schemaOut(again, CAPS.graphiti).relations?.[0]).toMatchObject({ color: '#ef4444' });
  });
  it('a link\'s edits: colour and endpoints wait for Save; drawn ones are pending until then', async () => {
    await open(CAPS.graphiti);
    await act(async () => { canvasProps.onTapEdge('e', { edgeLabel: 'WORKS_AT' }); });
    await flush();
    await click(q('button[aria-label="Color #14B8A6"]'));
    await pick(q('select[aria-label="Source"]'), 'Company');
    await pick(q('select[aria-label="Target"]'), 'Company');
    await click(q('button[aria-label="Add endpoint"]'));
    expect(edges().find((e) => e.data.source === 'Company')?.classes).toBe('preview');
    await later(700);
    expect(puts).toEqual([]);
    await click(button('Save'));
    await later(20);
    expect((puts[0].relations as unknown[])).toEqual([
      expect.objectContaining({ name: 'WORKS_AT', from: 'Person', to: 'Company', color: '#14B8A6' }),
      expect.objectContaining({ name: 'WORKS_AT', from: 'Company', to: 'Company', color: '#14B8A6' }),
    ]);
  });
  it('removing an endpoint waits for Save too', async () => {
    await open(CAPS.graphiti);
    await act(async () => { canvasProps.onTapEdge('e', { edgeLabel: 'WORKS_AT' }); });
    await flush();
    await click(q('.endpoint-row button[aria-label="Remove"]'));
    expect(edges()).toEqual([]);
    await click(button('Save'));
    await later(20);
    expect(puts[0].relations).toEqual([]);
  });
  it('Discard drops all of it, and nothing was written', async () => {
    await open(CAPS.graphiti);
    await act(async () => { canvasProps.onNodeDragEnd('Person', { x: 1, y: 2 }, {}); });
    await flush();
    await click(button('Discard'));
    expect(nodes()[1].position).toEqual({ x: 300, y: 300 });
    await later(700);
    expect(puts).toEqual([]);
    expect(Array.from(tools().children).length).toBe(3);
  });
  it('a draft the service would refuse stays here and says why', async () => {
    await open(CAPS.graphiti);
    await act(async () => { canvasProps.onTapNode('Person'); });
    await flush();
    await type(q('input[aria-label="Name"]'), 'Company');
    await click(button('Save'));
    await later(20);
    expect(puts).toEqual([]);
    expect(el.querySelector('.mm-sstat.bad')?.textContent).toContain('Two types are called Company.');
  });
  it('renaming a property applies at once, with its caption, and offers to keep the old name', async () => {
    await open(CAPS.graphiti);
    await act(async () => { canvasProps.onTapNode('Company'); });
    await flush();
    await type(q('.prop-row input[aria-label="Property name"]'), 'home page');
    expect(q('button[aria-label="Keep the old name"]')).not.toBeNull();
    await click(q('button[aria-label="Save new name"]'));
    await later(20);
    expect(puts).toHaveLength(1);
    expect(puts[0]).toMatchObject({ types: [{ caption: 'home_page', properties: [{ name: 'home_page' }, { name: 'tier' }] }, {}] });
  });
  it('deleting a property or a type asks first with the console\'s own sheet, then applies at once', async () => {
    const native = jest.spyOn(window, 'confirm');
    await open(CAPS.graphiti);
    await act(async () => { canvasProps.onTapNode('Company'); });
    await flush();
    await click(q('button[aria-label="Delete website"]'));
    expect(document.body.textContent).toContain('Values already kept on records stay on them.');
    await click(button('Delete'));
    await later(20);
    expect(puts[0]).toMatchObject({ types: [{ caption: 'title', properties: [{ name: 'tier' }] }, {}] });
    await act(async () => { canvasProps.onTapNode('Person'); });
    await flush();
    await click(button('Delete this type'));
    await click(button('Delete Person'));
    await later(20);
    expect(puts[1]).toMatchObject({ types: [{ name: 'Company' }], relations: [] });
    expect(native).not.toHaveBeenCalled();
    native.mockRestore();
  });
  it('+ Type makes a type or a link, with its name up front, and applies at once', async () => {
    await open(CAPS.graphiti);
    await click(button('+ Type'));
    await type(q('.sp-graph-addtype input[aria-label="Label"]'), 'Project');
    await click(q('.sp-graph-addtype .btn.primary:last-child'));
    await later(20);
    expect((puts[0].types as { name: string; x: number }[]).map((t) => t.name)).toEqual(['Company', 'Person', 'Project']);
    expect(Number.isFinite((puts[0].types as { x: number }[])[2].x)).toBe(true);
    expect((q('input[aria-label="Name"]') as HTMLInputElement).value).toBe('Project');
    await click(button('+ Type'));
    await click(button('Edge'));
    await type(q('.sp-graph-addtype input[aria-label="Label"]'), 'owns');
    await pick(q('.sp-graph-addtype select[aria-label="Source"]'), 'Company');
    await pick(q('.sp-graph-addtype select[aria-label="Target"]'), 'Project');
    await click(Array.from(q('.sp-graph-addtype').querySelectorAll('button')).find((b) => b.textContent === 'Create') as Element);
    await later(20);
    expect((puts[1].relations as unknown[])[1]).toMatchObject({ name: 'OWNS', from: 'Company', to: 'Project' });
  });
  it('drawing from one type to another asks the link\'s name and colour, and applies at once', async () => {
    await open(CAPS.graphiti);
    await act(async () => { canvasProps.onEdgeDraw('Company', 'Person', { x: 200, y: 200 }); });
    await flush();
    await type(q('.dg-eh-pop input[aria-label="Link name"]'), 'employs people');
    await click(q('.dg-eh-pop button[aria-label="Color #EC4899"]'));
    await click(q('.dg-eh-pop .btn.primary'));
    await later(20);
    expect((puts[0].relations as unknown[])[1]).toMatchObject({ name: 'EMPLOYS_PEOPLE', from: 'Company', to: 'Person', color: '#EC4899' });
    expect(panel().textContent).toContain('Endpoints');
  });
  it('starts from an empty schema with the same starting points', async () => {
    stored = { types: [], relations: [] };
    await open(CAPS.graphiti);
    // the memory already holds a record, so the page says so rather than reading as a blank one
    expect(el.textContent).toContain('No types yet');
    expect(el.textContent).toContain('It already holds 1 record.');
    await click(Array.from(el.querySelectorAll('.mm-start')).find((b) => (b.textContent || '').startsWith('Customers')) as Element);
    await later(20);
    expect(nodes()).toHaveLength(3);
    expect(puts).toHaveLength(1);
  });
  it('says so when the schema can\'t be read', async () => {
    (harnessFetch as jest.Mock).mockImplementation(async () => ({ ok: false, status: 500, json: async () => ({}) }));
    await open(CAPS.graphiti);
    expect(el.querySelector('[role="alert"]')?.textContent).toContain('The schema could not be read just now.');
  });
});

describe('where something can\'t change, the same panel shows all of it, not editable', () => {
  it('read only: everything there, nothing to add or delete, and the pencil still opens it', async () => {
    await open(CAPS.graphiti, { ro: true });
    expect(Array.from(tools().children).map((c) => c.getAttribute('aria-label') || c.textContent)).toEqual(['Inspect selected type', 'Read only', 'expand']);
    expect(canvasProps.edgeDrawEnabled).toBe(false);
    await act(async () => { canvasProps.onNodeDragEnd('Person', { x: 1, y: 2 }, {}); });
    await flush();
    expect(nodes()[1].position).toEqual({ x: 300, y: 300 });
    await act(async () => { canvasProps.onTapNode('Company'); });
    await flush();
    const p = panel();
    expect(p.querySelector('input[aria-label="Name"]')).toBeNull();
    expect(p.textContent).toContain('Company');
    expect((p.querySelector('textarea[aria-label="Description"]') as HTMLTextAreaElement).disabled).toBe(true);
    expect((p.querySelector('textarea[aria-label="Description"]') as HTMLTextAreaElement).value).toBe('A customer.');
    expect((p.querySelector('button[aria-label^="Color #"]') as HTMLButtonElement).disabled).toBe(true);
    expect((p.querySelector('.icon-combo-trigger') as HTMLButtonElement).disabled).toBe(true);
    expect((p.querySelector('select[aria-label="Caption"]') as HTMLSelectElement).disabled).toBe(true);
    expect(Array.from(p.querySelectorAll('input[aria-label="Property name"]')).every((i) => (i as HTMLInputElement).disabled)).toBe(true);
    expect(p.querySelector('button[aria-label="Delete website"]')).toBeNull();
    expect(button('+ Add property')).toBeUndefined();
    expect(button('Delete this type')).toBeUndefined();
    await act(async () => { canvasProps.onTapEdge('e', { edgeLabel: 'WORKS_AT' }); });
    await flush();
    expect(panel().querySelector('.endpoint-row')?.textContent).toContain('Person');
    expect(panel().querySelector('button[aria-label="Remove"]')).toBeNull();
    expect(panel().querySelector('button[aria-label="Add endpoint"]')).toBeNull();
  });
  it('labels: a name and what it means can change, the rest shows, and only those two are written', async () => {
    stored = { types: [{ name: 'Company', description: 'A customer.' }] };
    await open(CAPS.hindsight);
    expect(el.textContent).toContain('Facts pulled out of each task get the labels that fit them.');
    expect(Array.from(tools().children).map((c) => c.getAttribute('aria-label') || c.textContent)).toEqual(['Inspect selected type', '+ Label', 'expand']);
    expect(canvasProps.edgeDrawEnabled).toBe(false);
    await act(async () => { canvasProps.onTapNode('Company'); });
    await flush();
    const p = panel();
    expect((p.querySelector('button[aria-label^="Color #"]') as HTMLButtonElement).disabled).toBe(true);
    expect((p.querySelector('.icon-combo-trigger') as HTMLButtonElement).disabled).toBe(true);
    expect(p.textContent).toContain('no properties yet');
    expect(button('+ Add property')).toBeUndefined();
    await type(p.querySelector('textarea[aria-label="Description"]') as Element, 'Someone who pays.');
    await later(700);
    expect(puts).toEqual([]);
    await click(button('Save'));
    await later(20);
    expect(puts[0]).toEqual({ types: [{ name: 'Company', description: 'Someone who pays.' }] });
    await click(button('+ Label'));
    expect(q('.sp-graph-addtype').textContent).toContain('New label');
    expect(button('Edge')).toBeUndefined();
  });
  describe('a provider that decides for itself', () => {
    const rec = (id: string, type: string, attributes: Record<string, unknown> = {}) => ({ record: { id, object: 'memory.record', memory_id: 'hmem_1', type, title: id, content: [], attributes, references: [] }, memory: { id: 'hmem_1', name: 'x' } });
    it('a type panel for each kind it holds, its count, and the attribute names actually seen', async () => {
      graphAnswer = {
        nodes: [rec('a', 'fact', { account: 'acme', seats: 40 }), rec('b', 'fact', { active: true }), rec('n', 'note'), rec('e', 'entity')],
        edges: [{ from: { record_id: 'n' }, to: { record_id: 'e' }, rel: 'about', available: true }],
      };
      const seen: string[] = [];
      await open(CAPS.mem0, { onOpenData: (t) => seen.push(t) });
      expect(el.textContent).toContain('Mem0 decides for itself what to keep, and takes no schema');
      expect(Array.from(tools().children).map((c) => c.getAttribute('aria-label') || c.textContent)).toEqual(['Inspect selected type', 'Read only', 'expand']);
      expect(nodes().map((n) => n.data.id).sort()).toEqual(['entity', 'fact', 'note']);
      expect(nodes().find((n) => n.data.id === 'fact')?.data.caption).toBe('Fact\n2 records');
      await act(async () => { canvasProps.onTapNode('fact'); });
      await flush();
      const p = panel();
      expect(p.textContent).toContain('2 records of this type');
      expect(Array.from(p.querySelectorAll('input[aria-label="Property name"]')).map((i) => [(i as HTMLInputElement).value, (i as HTMLInputElement).disabled])).toEqual([['account', true], ['seats', true], ['active', true]]);
      expect(Array.from(p.querySelectorAll('select[aria-label="Property type"]')).map((s) => s.textContent)).toEqual(['Text', 'Number', 'Yes / no']);
      expect((p.querySelector('button[aria-label^="Color #"]') as HTMLButtonElement).disabled).toBe(true);
      expect((p.querySelector('.icon-combo-trigger') as HTMLButtonElement).disabled).toBe(true);
      expect((p.querySelector('select[aria-label="Caption"]') as HTMLSelectElement).disabled).toBe(true);
      expect(button('Delete this type')).toBeUndefined();
      expect(button('+ Add property')).toBeUndefined();
      await click(button('Open in Data'));
      expect(seen).toEqual(['fact']);
      await act(async () => { canvasProps.onTapEdge('x', { edgeLabel: 'about' }); });
      await flush();
      expect(panel().querySelector('.endpoint-row')?.textContent).toContain('Note');
      expect(panel().textContent).toContain('1 link');
      expect(panel().querySelector('button[aria-label="Remove"]')).toBeNull();
      expect(puts).toEqual([]);
    });
    it('says so when nothing is kept yet, and when it can\'t be read', async () => {
      await open(CAPS.reme);
      expect(el.textContent).toContain('Nothing is kept here yet.');
      expect(el.textContent).toContain('ReMe decides for itself');
      await act(async () => { root.unmount(); });
      root = createRoot(el);
      (harnessFetch as jest.Mock).mockImplementation(async () => ({ ok: false, status: 500, json: async () => ({}) }));
      await open(CAPS.reme);
      expect(el.querySelector('[role="alert"]')?.textContent).toContain('could not be read just now');
    });
  });
});

describe('a schema with no saved places', () => {
  it('keeps every saved place as it is, and puts the others by the graph\'s layout, around what they relate to', () => {
    const s = schemaIn({ types: [{ name: 'A', x: 10, y: 20 }, { name: 'B', x: 400, y: 20 }, { name: 'C' }], relations: [{ name: 'R', from: 'A', to: 'C' }] });
    expect(s.types[0]).toMatchObject({ x: 10, y: 20 });
    expect(s.types[1]).toMatchObject({ x: 400, y: 20 });
    expect(Number.isFinite(s.types[2].x) && Number.isFinite(s.types[2].y)).toBe(true);
    expect(Math.hypot(s.types[2].x - 10, s.types[2].y - 20)).toBeLessThan(Math.hypot(s.types[2].x - 400, s.types[2].y - 20) + 200);
  });
  it('with none saved, all of them around the middle of the canvas, the most related in the centre', () => {
    const s = schemaIn({ types: [{ name: 'A' }, { name: 'Hub' }, { name: 'C' }], relations: [{ name: 'R', from: 'A', to: 'Hub' }, { name: 'S', from: 'C', to: 'Hub' }] });
    const hub = s.types[1];
    s.types.forEach((t) => expect(Number.isInteger(t.x)).toBe(true));
    const d = (a: { x: number; y: number }, b: { x: number; y: number }) => Math.hypot(a.x - b.x, a.y - b.y);
    expect(d(s.types[0], hub)).toBeGreaterThan(50);
    expect(Math.abs(d(s.types[0], hub) - d(s.types[2], hub))).toBeLessThan(40);
  });
  it('keeps any icon and caption it was stored with', () => {
    const s = schemaIn({ types: [{ name: 'A', icon: 'Rocket', caption: 'seats', x: 1, y: 1 }] });
    expect(s.types[0]).toMatchObject({ icon: 'Rocket', caption: 'seats' });
  });
});

describe('nothing here looks editable where the vendor takes no schema', () => {
  const editIcon = 'M16 4l4 4-11 11H5v-4z';
  test.each([['Mem0', 'mem0'], ['ReMe', 'reme']])('%s has no pencil and says it is read only', async (_name, id) => {
    await open(CAPS[id]);
    expect(el.innerHTML).not.toContain(editIcon);
    expect(el.textContent).toContain('Read only');
  });
  test('a vendor a schema guides keeps the pencil, and says a change applies from here on', async () => {
    await open(CAPS.graphiti);
    expect(el.innerHTML).toContain(editIcon);
    expect(el.textContent).not.toContain('Read only');
    expect(el.textContent).toContain('A change applies from here on: what’s already kept stays as it is.');
  });
  test('someone who may only read sees no pencil on a vendor that takes a schema', async () => {
    await open(CAPS.graphiti, { ro: true });
    expect(el.innerHTML).not.toContain(editIcon);
    expect(el.textContent).toContain('Read only');
  });
});
