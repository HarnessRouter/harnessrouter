/** @jest-environment jsdom */
// A memory's card draws what was read of it: a schema's types and relations, a vocabulary of labels,
// the first records where there is no schema, and an unbuilt shape where nothing is kept yet.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { CardArt, MiniArt, saysNothing } from './CardArt';
import { concepts } from './graph/builtin';
import type { LSchema } from './schemaModel';

jest.mock('@/lib/harness', () => ({ gwHeaders: () => ({}), listCustom: jest.fn(async () => []) }));
jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));

const draw = (el: React.ReactElement) => {
  const host = document.createElement('div');
  const root = createRoot(host);
  act(() => root.render(el));
  return host;
};
const T = (id: string, name: string, x: number, y: number) =>
  ({ id, name, description: '', properties: [], color: '#285aff', icon: 'building', x, y, caption: 'title' });
const schema: LSchema = {
  types: [T('t1', 'Person', 0, 0), T('t2', 'Company', 300, 0)],
  relations: [{ id: 'r1', name: 'works_at', description: '', from: 't1', to: 't2' }],
};

test('a schema: every type by name, and each relation named on its line', () => {
  const h = draw(<CardArt s={schema} labels={false} records={4} />);
  expect(Array.from(h.querySelectorAll('.mm-ca-type')).map((t) => t.textContent)).toEqual(['Person', 'Company']);
  expect(h.querySelector('.mm-ca-rel text')?.textContent).toBe('works_at');
  expect(h.querySelectorAll('line')).toHaveLength(1);
});

test('labels: a row of chips, never lines between them', () => {
  const h = draw(<CardArt s={schema} labels records={4} />);
  expect(Array.from(h.querySelectorAll('.mm-ca-chip')).map((c) => c.textContent)).toEqual(['Person', 'Company']);
  expect(h.querySelector('line')).toBeNull();
});

test('no schema: the first records by title, and how many more there are', () => {
  const h = draw(<CardArt s={null} labels={false} records={5} recent={['Northwind wants SSO', 'Acme asked about on-prem', 'Pricing call']} />);
  expect(Array.from(h.querySelectorAll('.mm-ca-row span')).map((r) => r.textContent)).toEqual(['Northwind wants SSO', 'Acme asked about on-prem', 'Pricing call']);
  expect(h.querySelector('.mm-ca-rows small')?.textContent).toBe('+2 more');
});

test('titles not read: one quiet row a record, never more than fit', () => {
  expect(draw(<CardArt s={null} labels={false} records={3} recent={null} />).querySelectorAll('.mm-ca-row')).toHaveLength(3);
  const many = draw(<CardArt s={null} labels={false} records={40} recent={null} />);
  expect(many.querySelectorAll('.mm-ca-row')).toHaveLength(5);
  expect(many.querySelector('.mm-ca-rows small')?.textContent).toBe('+35 more');
});

test('nothing kept: the unbuilt shape; still being read: nothing yet', () => {
  expect(draw(<CardArt s={null} labels={false} records={0} />).querySelector('.mm-ca-ghost')).not.toBeNull();
  expect(draw(<CardArt s={schema} labels={false} records={4} pending />).innerHTML).toBe('');
});

test("a vendor's concepts: nothing drawn on anything else, and a name above a type at the top", () => {
  // Graphiti's own: two relations meet at Episode, where their names used to sit on each other ("came fro|came from")
  const T3 = (name: string) => ({ name, description: '' });
  const L = (name: string, from: string, to: string) => ({ name, from, to, description: '' });
  const s = concepts(null, { id: 'graphiti', schema: { builtin: {
    types: [T3('episode'), T3('fact'), T3('entity')],
    relations: [L('came_from', 'fact', 'episode'), L('came_from', 'entity', 'episode'), L('about', 'fact', 'entity')],
  } } }) as LSchema;
  const h = draw(<CardArt s={s} labels={false} records={4} />);
  const n = (el: Element, a: string) => Number(el.getAttribute(a));
  const rels = Array.from(h.querySelectorAll('.mm-ca-rel rect')).map((r) => ({ x: n(r, 'x'), y: n(r, 'y'), w: n(r, 'width'), h: n(r, 'height') }));
  expect(rels).toHaveLength(3);
  for (const [i, a] of rels.entries()) for (const b of rels.slice(i + 1)) {
    expect(a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h).toBe(false);
  }
  const discs = Array.from(h.querySelectorAll('circle')).map((c) => ({ x: n(c, 'cx'), y: n(c, 'cy') }));
  const names = Array.from(h.querySelectorAll('.mm-ca-type'));
  const top = discs.reduce((m, d, i) => (d.y < discs[m].y ? i : m), 0);
  expect(n(names[top], 'y')).toBeLessThan(discs[top].y);
  for (const [i, d] of discs.entries()) if (i !== top) expect(n(names[i], 'y')).toBeGreaterThan(d.y);
});

test('one type related to nothing draws no diagram: what is kept is drawn instead (Mem0’s "Fact")', () => {
  const one: LSchema = { types: [T('t1', 'Fact', 0, 0)], relations: [] };
  expect(saysNothing(one)).toBe(true);
  expect(saysNothing(schema)).toBe(false);
  const h = draw(<CardArt s={one} labels={false} records={2} recent={['User’s name is Dana', 'Prefers email']} />);
  expect(h.querySelector('.mm-ca-type')).toBeNull();
  expect(Array.from(h.querySelectorAll('.mm-ca-row span')).map((r) => r.textContent)).toEqual(['User’s name is Dana', 'Prefers email']);
  expect(draw(<CardArt s={one} labels={false} records={0} />).querySelector('.mm-ca-ghost')).not.toBeNull();
  // the list's small picture likewise: no lone dot
  expect(draw(<MiniArt s={one} labels={false} records={2} />).querySelectorAll('rect')).toHaveLength(2);
  // a vocabulary of one label is still the label a person set
  expect(draw(<CardArt s={one} labels records={2} />).querySelector('.mm-ca-chip')?.textContent).toBe('Fact');
});
