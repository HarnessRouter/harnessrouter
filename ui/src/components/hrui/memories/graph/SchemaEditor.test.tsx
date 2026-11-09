/** @jest-environment jsdom */
// The schema pane against the capability document. Clicking a type or a link opens the same panel whatever the provider;
// only what can change differs. And the round trip that matters: what Save sends is what the provider reads, and any
// icon and caption come back as they went.
import { act, forwardRef, useImperativeHandle } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { CAPS, memory } from '../fixtures';
import type { Memory, Provider } from '@/lib/memories';

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
const drawCover = jest.fn();
jest.mock('./coverShot', () => ({ drawCover: (...a: unknown[]) => drawCover(...a) }));
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
import { coverGraphOf, coverSig } from '../cover';
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

function Page({ provider, ro = false, onOpenData = () => {}, m = {} }: { provider: Provider; ro?: boolean; onOpenData?: (t: string) => void; m?: Partial<Memory> }) {
  const doc = useSchemaDoc('hmem_1', provider);
  return <div id="hrui"><SchemaEditor memory={memory({ name: 'Customers', provider: provider.id, ...m })} provider={provider} doc={doc} ro={ro} countOf={() => 2} onOpenData={onOpenData} /></div>;
}
async function open(provider: Provider, props: { ro?: boolean; onOpenData?: (t: string) => void; m?: Partial<Memory> } = {}) {
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
    // the canvas is the whole pane: no explanation under it, for any engine (Richard 11-09)
    expect(el.textContent).not.toContain('uses these types to decide');
    expect(el.querySelector('.mm-guide')).toBeNull();
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
  it('labels: a type is a name and what it means, only those two are offered and written, and nothing relates (Richard 11-09)', async () => {
    stored = { types: [{ name: 'Company', description: 'A customer.' }] };
    await open(CAPS.hindsight);
    expect(el.textContent).not.toContain('Facts pulled out of each task');
    expect(Array.from(tools().children).map((c) => c.getAttribute('aria-label') || c.textContent)).toEqual(['Inspect selected type', '+ Type', 'expand']);
    // dragging from one type to another draws nothing
    expect(canvasProps.edgeDrawEnabled).toBe(false);
    await act(async () => { canvasProps.onTapNode('Company'); });
    await flush();
    const p = panel();
    expect(p.querySelector('input[aria-label="Name"]')).toBeTruthy();
    expect(p.querySelector('textarea[aria-label="Description"]')).toBeTruthy();
    expect(p.querySelector('button[aria-label^="Color #"]')).toBeNull();
    expect(p.querySelector('.icon-combo-trigger')).toBeNull();
    expect(Array.from(p.querySelectorAll('.dg-field-label')).map((x) => x.textContent)).toEqual([]);
    expect(p.textContent).not.toContain('Properties');
    expect(p.textContent).not.toContain('no properties yet');
    expect(button('+ Add property')).toBeUndefined();
    await type(p.querySelector('textarea[aria-label="Description"]') as Element, 'Someone who pays.');
    await later(700);
    expect(puts).toEqual([]);
    await click(button('Save'));
    await later(20);
    expect(puts[0]).toEqual({ types: [{ name: 'Company', description: 'Someone who pays.' }] });
    // its entries are types, as on every engine (Richard 11-09: "make them consistent called schema"); the new one is a
    // name and a description, one per row, and no colour, no vertex or edge
    await click(button('+ Type'));
    const form = q('.sp-graph-addtype');
    expect(Array.from(form.querySelectorAll('label')).map((x) => x.textContent)).toEqual(['Name', 'Description']);
    expect(form.textContent).toContain('New type');
    expect(button('Edge')).toBeUndefined();
    expect(form.querySelector('button[aria-label^="Color #"]')).toBeNull();
    await type(form.querySelector('#sgNewName') as Element, 'Billing');
    await type(form.querySelector('#sgNewDesc') as Element, 'Money owed or paid.');
    await click(Array.from(form.querySelectorAll('button')).find((b) => b.textContent === 'Create') as Element);
    await later(20);
    expect(puts.pop()).toEqual({ types: [{ name: 'Company', description: 'Someone who pays.' }, { name: 'Billing', description: 'Money owed or paid.' }] });
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
      expect(el.textContent).not.toContain('decides for itself');
      expect(Array.from(tools().children).map((c) => c.getAttribute('aria-label') || c.textContent)).toEqual(['Edit types', 'Read only', '+ Type', 'expand']);
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
      expect(el.textContent).not.toContain('decides for itself');
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

describe('where the engine reads no schema (schema.mode "none"), the pencil and + Type are there and off, saying why', () => {
  const editIcon = 'M16 4l4 4-11 11H5v-4z';
  const mem0 = { ...CAPS.mem0, schema: { mode: 'none', builtin: { types: [{ name: 'fact', description: 'A short fact.' }], relations: [] } } } as Provider;
  const reme = { ...CAPS.reme, schema: { mode: 'none', builtin: { types: [{ name: 'episode', description: 'A conversation.' }, { name: 'note', description: 'A note.' }], relations: [{ name: 'derived_from', from: 'note', to: 'episode', description: '' }] } } } as Provider;
  test.each([
    ['Mem0', mem0, 'Mem0 keeps facts without types of its own.'],
    ['ReMe', reme, 'ReMe keeps notes without types of its own.'],
  ])('%s (Richard 11-09: "If not supported, should disable this +Type button")', async (_name, provider, why) => {
    await open(provider);
    const pencil = tools().querySelector('button[aria-label="Edit types"]') as HTMLButtonElement;
    expect(pencil.disabled).toBe(true);
    expect(pencil.title).toBe(why);
    expect(pencil.innerHTML).toContain(editIcon);
    const add = button('+ Type');
    expect(add.disabled).toBe(true);
    expect(add.title).toBe(why);
    expect(el.textContent).toContain('Read only');
    await click(add);
    expect(el.querySelector('.sp-graph-addtype')).toBeNull();
    // the built-in shape is still drawn, to read
    expect(nodes().length).toBeGreaterThan(0);
    expect(puts).toEqual([]);
  });
  test('the reason comes from what the engine declares, never from its name', async () => {
    const other = { ...CAPS.mem0, id: 'acme-memory', schema: { mode: 'none' } } as Provider;
    await open(other);
    expect(button('+ Type').title).toBe('acme-memory keeps records without types of its own.');
    await act(async () => { root.unmount(); }); root = createRoot(el);
    await open({ ...CAPS.reme, schema: { mode: 'guides', properties: true, relations: true } } as Provider);
    expect(button('+ Type').disabled).toBe(false);
  });
  test('a vendor a schema guides keeps the pencil, and nothing on the canvas explains it (Richard 11-09)', async () => {
    await open(CAPS.graphiti);
    expect(el.innerHTML).toContain(editIcon);
    expect(el.textContent).not.toContain('Read only');
    expect(el.textContent).not.toContain('A change applies from here on');
  });
  test('someone who may only read sees no pencil on a vendor that takes a schema', async () => {
    await open(CAPS.graphiti, { ro: true });
    expect(el.innerHTML).not.toContain(editIcon);
    expect(el.textContent).toContain('Read only');
  });
});

describe('what the provider makes itself is drawn, locked, beside what a person sets', () => {
  const GRAPHITI_MADE = {
    types: [
      { name: 'episode', description: 'A conversation or task Graphiti read, kept as it was given.' },
      { name: 'entity', description: 'A person, place or thing Graphiti found.' },
      { name: 'fact', description: 'A statement that joins two entities, with when it was true.' },
    ],
    relations: [
      { name: 'about', from: 'fact', to: 'entity', description: 'The two entities a fact joins.' },
      { name: 'derived_from', from: 'fact', to: 'episode', description: 'Where Graphiti read it.' },
      { name: 'derived_from', from: 'entity', to: 'episode', description: 'Where Graphiti read it.' },
    ],
  };
  const graphiti = { ...CAPS.graphiti, schema: { ...CAPS.graphiti.schema, builtin: GRAPHITI_MADE } } as Provider;
  const mem0 = { ...CAPS.mem0, schema: { mode: 'none', builtin: { types: [{ name: 'fact', description: 'A short fact Mem0 drew from a conversation.' }], relations: [] } } } as Provider;
  const reme = { ...CAPS.reme, schema: { mode: 'none', builtin: { types: [{ name: 'episode', description: 'A conversation ReMe was given.' }, { name: 'note', description: "What ReMe's own agent wrote down." }], relations: [{ name: 'derived_from', from: 'note', to: 'episode', description: 'The conversation the note is about.' }] } } } as Provider;
  const toasts: string[] = [];
  const onToast = (e: Event) => { toasts.push(String((e as CustomEvent).detail)); };
  beforeEach(() => { toasts.length = 0; window.addEventListener('hrui:toast', onToast); });
  afterEach(() => { window.removeEventListener('hrui:toast', onToast); });
  const node = (id: string) => nodes().find((n) => n.data.id === id) as { data: Record<string, unknown>; position: { x: number; y: number }; grabbable?: boolean; classes?: string };

  it("draws Graphiti's own types and links beside a person's, marked built in and fixed in place", async () => {
    await open(graphiti);
    expect(nodes().map((n) => n.data.id).sort()).toEqual(['Company', 'Person', 'entity', 'episode', 'fact']);
    expect(node('fact').data.caption).toBe('Fact\nBuilt in · 2 records');
    expect(node('fact').grabbable).toBe(false);
    expect(node('Company').grabbable).toBe(true);
    expect(node('Company').data.caption).toBe('Company\n2 records');
    expect(Math.max(node('fact').position.x, node('entity').position.x, node('episode').position.x)).toBeLessThan(100);
    const made = edges().filter((e) => String(e.classes || '').includes('builtin')).map((e) => `${e.data.source} ${e.data.caption} ${e.data.target}`).sort();
    expect(made).toEqual(['entity came from episode', 'fact about entity', 'fact came from episode']);
    expect(el.textContent).not.toContain('Built into');
  });
  it('a built-in type or link opens read only and says why, and nothing about it is written', async () => {
    await open(graphiti);
    await act(async () => { canvasProps.onTapNode('fact'); });
    await flush();
    expect(panel().querySelector('.mm-locked')?.textContent).toBe("Built into Graphiti, so it can't be changed here.");
    expect(panel().querySelector('input[aria-label="Name"]')).toBeNull();
    expect((panel().querySelector('textarea[aria-label="Description"]') as HTMLTextAreaElement).value).toBe('A statement that joins two entities, with when it was true.');
    expect((panel().querySelector('textarea[aria-label="Description"]') as HTMLTextAreaElement).disabled).toBe(true);
    expect(button('Delete this type')).toBeUndefined();
    await act(async () => { canvasProps.onTapEdge('x', { edgeLabel: 'about' }); });
    await flush();
    expect(panel().querySelector('.mm-locked')).toBeTruthy();
    expect(panel().querySelector('button[aria-label="Remove"]')).toBeNull();
    // a person's own type next to it is as editable as before
    await act(async () => { canvasProps.onTapNode('Company'); });
    await flush();
    expect(panel().querySelector('.mm-locked')).toBeNull();
    expect(panel().querySelector('input[aria-label="Name"]')).toBeTruthy();
    expect(puts).toEqual([]);
  });
  it('a person relates their own types, and names none after a built-in one', async () => {
    await open(graphiti);
    await act(async () => { canvasProps.onEdgeDraw('fact', 'Person', { x: 200, y: 200 }); });
    await flush();
    expect(q('.dg-eh-pop')).toBeNull();
    expect(toasts).toContain('Fact is built into Graphiti. Relate your own types.');
    await click(button('+ Type'));
    await type(q('.sp-graph-addtype input[aria-label="Label"]'), 'Fact');
    await click(q('.sp-graph-addtype .btn.primary:last-child'));
    await later(20);
    expect(toasts).toContain('Fact is built into Graphiti. Call yours something else.');
    expect(puts).toEqual([]);
    // a relation's ends are a person's own types
    await click(button('+ Type'));
    await click(button('Edge'));
    const sources = Array.from(q('.sp-graph-addtype select[aria-label="Source"]').querySelectorAll('option')).map((o) => (o as HTMLOptionElement).value).filter(Boolean);
    expect(sources).toEqual(['Company', 'Person']);
  });
  it('with none of their own yet, the canvas is the whole pane: no panel of starting points under it', async () => {
    stored = { types: [], relations: [] };
    await open(graphiti);
    expect(q('.mm-sch-empty')).toBeNull();
    // nothing under the graph or over it: no panel, no caption (Richard 11-09)
    expect(q('.mm-sch-own')).toBeNull();
    expect(el.textContent).not.toContain('Add your own types');
    expect(el.querySelector('.mgv > .dg-body + *')).toBeNull();
    // what Graphiti makes is a triangle, never three in a line: Episode on top, Fact and Entity beneath it
    const p = (id: string) => (nodes().find((n) => n.data.id === id)?.position as { x: number; y: number });
    expect(p('episode').y).toBeLessThan(p('fact').y);
    expect(p('fact').y).toBe(p('entity').y);
    const area = (p('fact').x - p('episode').x) * (p('entity').y - p('episode').y) - (p('entity').x - p('episode').x) * (p('fact').y - p('episode').y);
    expect(Math.abs(area)).toBeGreaterThan(10000);
    // + Type is the one-type form, as it was
    await click(button('+ Type'));
    expect(el.querySelector('.sp-graph-addtype .mm-start')).toBeNull();
    expect(q('.sp-graph-addtype').textContent).toContain('New type');
  });
  it('Mem0: the one type it makes, locked, and what writers stated beside it', async () => {
    const rec = (id: string, type: string) => ({ record: { id, object: 'memory.record', memory_id: 'hmem_1', type, title: id, content: [], attributes: {}, references: [] }, memory: { id: 'hmem_1', name: 'x' } });
    graphAnswer = { nodes: [rec('a', 'fact'), rec('b', 'fact'), rec('n', 'note'), rec('e', 'entity')], edges: [{ from: { record_id: 'n' }, to: { record_id: 'e' }, rel: 'about', available: true }] };
    await open(mem0);
    expect(node('fact').data.caption).toBe('Fact\nBuilt in · 2 records');
    expect(node('note').data.caption).toBe('Note\n1 record');
    expect(el.textContent).not.toContain('Built into');
  });
  it('ReMe with nothing kept yet still shows what it makes', async () => {
    await open(reme);
    expect(el.textContent).not.toContain('Nothing is kept here yet.');
    expect(nodes().map((n) => n.data.id).sort()).toEqual(['episode', 'note']);
    expect(edges().map((e) => `${e.data.source} ${e.data.caption} ${e.data.target}`)).toEqual(['note came from episode']);
    expect(el.textContent).not.toContain('Built into');
  });
});

describe('the memory’s cover is the drawing the tab shows', () => {
  const PIC = new Blob([new Uint8Array([137, 80, 78, 71])], { type: 'image/png' });
  let covers: { url: string; sig: string; body: unknown }[];
  beforeEach(() => {
    covers = [];
    drawCover.mockReset();
    drawCover.mockResolvedValue(PIC);
    Object.assign(window, { CanvasRenderingContext2D: function CanvasRenderingContext2D() { /* a canvas to draw on */ } });
    Object.assign(URL, { createObjectURL: jest.fn(() => 'blob:drawn'), revokeObjectURL: jest.fn() });
    const answer = (harnessFetch as jest.Mock).getMockImplementation() as (u: string, i: { method: string; body?: unknown; headers?: Record<string, string> }) => unknown;
    (harnessFetch as jest.Mock).mockImplementation(async (url: string, init: { method: string; body?: unknown; headers?: Record<string, string> }) => {
      if (url.includes('/cover') && init.method === 'PUT') {
        covers.push({ url, sig: init.headers?.['x-cover-sig'] || '', body: init.body });
        return { ok: true, json: async () => ({ cover_at: 7, cover_sig: init.headers?.['x-cover-sig'] }) };
      }
      return answer(url, init);
    });
  });
  afterEach(() => { delete (window as { CanvasRenderingContext2D?: unknown }).CanvasRenderingContext2D; });

  it('once the schema is read, it is drawn and kept, with which drawing it shows', async () => {
    await open(CAPS.graphiti, { m: { id: 'hmem_c1' } });
    expect(drawCover).not.toHaveBeenCalled();
    await later(1400);
    expect(drawCover).toHaveBeenCalledTimes(1);
    const g = drawCover.mock.calls[0][0] as { vertex_types: { label: string }[] };
    expect(g.vertex_types.map((v) => v.label)).toEqual(['Company', 'Person']);
    expect(covers).toHaveLength(1);
    expect(covers[0].url).toBe('/api/harness/v1/memories/hmem_c1/cover');
    expect(covers[0].body).toBe(PIC);
    expect(covers[0].sig).toBe(coverSig(coverGraphOf(schemaIn(stored as never), CAPS.graphiti)));
  });
  it('the kept one already shows this drawing: nothing is drawn again', async () => {
    const sig = coverSig(coverGraphOf(schemaIn(stored as never), CAPS.graphiti));
    await open(CAPS.graphiti, { m: { id: 'hmem_c2', cover_at: 3, cover_sig: sig } });
    await later(1400);
    expect(drawCover).not.toHaveBeenCalled();
    expect(covers).toEqual([]);
  });
  it('someone who may only read the memory makes none', async () => {
    await open(CAPS.graphiti, { m: { id: 'hmem_c3', privileges: ['read'] } });
    await later(1400);
    expect(drawCover).not.toHaveBeenCalled();
    expect(covers).toEqual([]);
  });
  it('a change to the schema, once saved, makes it again', async () => {
    await open(CAPS.graphiti, { m: { id: 'hmem_c4' } });
    await later(1400);
    expect(covers).toHaveLength(1);
    // a link's colour, changed and saved: the drawing differs, so another is made once it has settled
    await act(async () => { canvasProps.onTapEdge('e', { edgeLabel: 'WORKS_AT' }); });
    await flush();
    await click(q('button[aria-label="Color #14B8A6"]'));
    await later(700);
    expect(covers).toHaveLength(1);
    await click(button('Save'));
    await later(1400);
    expect(puts).toHaveLength(1);
    expect(covers).toHaveLength(2);
    expect(covers[1].sig).not.toBe(covers[0].sig);
    expect((drawCover.mock.calls[1][0] as { edge_types: { ui: { color?: string } }[] }).edge_types[0].ui.color).toBe('#14B8A6');
  });
});
