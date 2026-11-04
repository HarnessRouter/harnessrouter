/** @jest-environment jsdom */
// jsdom has no layout, so the container's width is given to it and a resize is told to the observer.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { fits, NARROW, ResizableColumns, resolveWidths, type ColumnPane } from './ResizableColumns';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const P = (id: string, min: number, initial: number, grow = false): ColumnPane => ({ id, label: id.toUpperCase(), min, initial, grow, node: <div className={`in-${id}`}>{id}</div> });
const THREE = [P('tree', 240, 300), P('doc', 400, 600, true), P('graph', 300, 420)];
const KEY = 'test.cols';

let root: Root; let el: HTMLElement; let width = 1440; let resize: () => void = () => {};
beforeEach(() => {
  window.localStorage.clear();
  width = 1440;
  Element.prototype.getBoundingClientRect = function rect() { return { width, height: 800, top: 0, left: 0, right: width, bottom: 800, x: 0, y: 0, toJSON: () => ({}) } as DOMRect; };
  (globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = class { constructor(cb: () => void) { resize = cb; } observe() {} disconnect() {} };
  el = document.createElement('div'); el.id = 'hrui'; document.body.appendChild(el);
  root = createRoot(el);
});
afterEach(async () => { await act(async () => root.unmount()); el.remove(); });
const mount = async (panes = THREE, extra: Record<string, unknown> = {}) => { await act(async () => { root.render(<ResizableColumns storageKey={KEY} panes={panes} {...extra} />); }); };
const seps = () => Array.from(el.querySelectorAll<HTMLElement>('[role=separator]'));
const col = (id: string) => el.querySelector(`#rc-p-${id}`) as HTMLElement;
const basis = (id: string) => col(id).style.flex;
const setWidth = async (w: number) => { width = w; await act(async () => resize()); };
const fire = async (t: Element, type: string, clientX: number) => { await act(async () => { t.dispatchEvent(new MouseEvent(type, { bubbles: true, clientX, button: 0 })); }); };
const drag = async (s: Element, from: number, to: number) => { await fire(s, 'pointerdown', from); await fire(s, 'pointermove', to); await fire(s, 'pointerup', to); };
const press = async (t: Element, key: string) => { await act(async () => { t.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true })); }); };

test('what fits: chosen widths first, the growing pane takes what is left', () => {
  expect(resolveWidths(THREE, {}, 1440)).toEqual({ tree: 300, graph: 420, doc: 718 });
  expect(resolveWidths(THREE, { tree: 500 }, 1440)).toEqual({ tree: 500, graph: 420, doc: 518 });
});
test('a narrower window takes from the growing pane, then the others from the last back, never under a minimum', () => {
  expect(resolveWidths(THREE, {}, 1200)).toEqual({ tree: 300, graph: 420, doc: 478 });
  expect(resolveWidths(THREE, {}, 1022)).toEqual({ tree: 300, graph: 320, doc: 400 });
  expect(resolveWidths(THREE, {}, 942)).toEqual({ tree: 240, graph: 300, doc: 400 });
  expect(resolveWidths(THREE, { tree: 9000 }, 1440)).toEqual({ tree: 738, graph: 300, doc: 400 });
});
test('a chosen width below a minimum is held at the minimum', () => {
  expect(resolveWidths(THREE, { tree: 10 }, 1440).tree).toBe(240);
});
test('fits: the minimums and the rules between them', () => {
  expect(fits(THREE, 942)).toBe(true);
  expect(fits(THREE, 941)).toBe(false);
});
test('columns: a separator between each, sized as chosen, with the width said to a screen reader', async () => {
  await mount();
  expect(seps()).toHaveLength(2);
  expect(basis('tree')).toBe('0 0 300px');
  expect(basis('doc')).toBe('1 1 0px');
  expect(basis('graph')).toBe('0 0 420px');
  const s = seps()[0];
  expect(s.getAttribute('aria-orientation')).toBe('vertical');
  expect(s.getAttribute('aria-valuenow')).toBe('300');
  expect(s.getAttribute('aria-valuemin')).toBe('240');
  expect(s.getAttribute('aria-valuemax')).toBe(String(300 + 718 - 400));
  expect(s.tabIndex).toBe(0);
  expect(el.querySelector('[role=tablist]')).toBeNull();
});
test('a drag moves only the two neighbours and stops at their minimums, and is saved when it ends', async () => {
  await mount();
  await drag(seps()[0], 300, 380);
  expect(basis('tree')).toBe('0 0 380px');
  expect(basis('graph')).toBe('0 0 420px');
  expect(JSON.parse(window.localStorage.getItem(KEY) as string)).toEqual({ tree: 380 });
  await drag(seps()[0], 380, 0);
  expect(basis('tree')).toBe('0 0 240px');
  await drag(seps()[0], 240, 5000);
  expect(basis('tree')).toBe('0 0 618px');    // 240 and the 778 the growing pane had, less its minimum of 400
});
test('a rule whose right neighbour is fixed moves it the other way', async () => {
  await mount();
  await drag(seps()[1], 1000, 900);
  expect(basis('graph')).toBe('0 0 520px');
  expect(basis('tree')).toBe('0 0 300px');
});
test('during a drag nothing selects and no pane catches the pointer', async () => {
  await mount();
  await fire(seps()[0], 'pointerdown', 300);
  expect(el.querySelector('.rc')?.className).toContain('dragging');
  await fire(seps()[0], 'pointerup', 300);
  expect(el.querySelector('.rc')?.className).not.toContain('dragging');
});
test('a move with no drag under way does nothing', async () => {
  await mount();
  await fire(seps()[0], 'pointermove', 900);
  expect(basis('tree')).toBe('0 0 300px');
});
test('double click puts both neighbours back', async () => {
  await mount();
  await drag(seps()[0], 300, 380);
  await act(async () => { seps()[0].dispatchEvent(new MouseEvent('dblclick', { bubbles: true })); });
  expect(basis('tree')).toBe('0 0 300px');
  expect(JSON.parse(window.localStorage.getItem(KEY) as string)).toEqual({});
});
test('arrow keys move a rule by 16, Home and End to its ends', async () => {
  await mount();
  await press(seps()[0], 'ArrowRight');
  expect(basis('tree')).toBe('0 0 316px');
  await press(seps()[0], 'ArrowLeft');
  await press(seps()[0], 'ArrowLeft');
  expect(basis('tree')).toBe('0 0 284px');
  await press(seps()[0], 'Home');
  expect(basis('tree')).toBe('0 0 240px');
  expect(JSON.parse(window.localStorage.getItem(KEY) as string)).toEqual({ tree: 240 });
});
test('widths come back from the store, clamped to the window, and a wider window gives them back', async () => {
  window.localStorage.setItem(KEY, JSON.stringify({ tree: 700, graph: 600 }));
  await mount();
  expect(basis('tree')).toBe('0 0 700px');
  await setWidth(1000);
  expect(basis('tree')).toBe('0 0 298px');
  expect(basis('graph')).toBe('0 0 300px');
  await setWidth(1800);
  expect(basis('tree')).toBe('0 0 700px');
  expect(basis('graph')).toBe('0 0 600px');
});
test('a broken store is no store', async () => {
  window.localStorage.setItem(KEY, '{nope');
  await mount();
  expect(basis('tree')).toBe('0 0 300px');
});
test('below the line: tabs named by the panes, one shown, full width, every pane still mounted', async () => {
  width = NARROW - 1;
  await mount();
  const tabs = Array.from(el.querySelectorAll<HTMLElement>('[role=tab]'));
  expect(tabs.map((t) => t.textContent)).toEqual(['TREE', 'DOC', 'GRAPH']);
  expect(seps()).toHaveLength(0);
  expect(col('doc').hidden).toBe(false);
  expect(col('tree').hidden).toBe(true);
  expect(col('graph').hidden).toBe(true);
  expect(el.querySelector('.in-tree')).not.toBeNull();
  expect(el.querySelector('.in-graph')).not.toBeNull();
  expect(col('doc').style.flex).toBe('');
  await act(async () => { tabs[2].click(); });
  expect(col('graph').hidden).toBe(false);
  expect(col('doc').hidden).toBe(true);
  expect(col('graph').getAttribute('role')).toBe('tabpanel');
});
test('tabs too where the minimums cannot fit, whatever the width', async () => {
  width = 950;
  await mount([P('a', 400, 400), P('b', 400, 400, true), P('c', 400, 400)]);
  expect(el.querySelector('[role=tablist]')).not.toBeNull();
});
test('tabs answer the arrow keys', async () => {
  width = 500;
  await mount();
  await press(el.querySelector('[role=tablist]') as Element, 'ArrowRight');
  expect(col('graph').hidden).toBe(false);
});
test('going from columns to tabs and back keeps what is in the panes the same instance', async () => {
  await mount();
  const before = el.querySelector('.in-doc');
  await setWidth(600);
  expect(el.querySelector('.in-doc')).toBe(before);
  await setWidth(1440);
  expect(el.querySelector('.in-doc')).toBe(before);
  expect(el.querySelector('[role=tablist]')).toBeNull();
});
test('a page can move the tabs itself', async () => {
  width = 500;
  const onTab = jest.fn();
  await mount(THREE, { tab: 'tree', onTab });
  expect(col('tree').hidden).toBe(false);
  await act(async () => { (Array.from(el.querySelectorAll('[role=tab]'))[1] as HTMLElement).click(); });
  expect(onTab).toHaveBeenCalledWith('doc');
  expect(col('tree').hidden).toBe(false);
  await mount(THREE, { tab: 'doc', onTab });
  expect(col('doc').hidden).toBe(false);
});
