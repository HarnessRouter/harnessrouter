/** @jest-environment jsdom */
// A memory's card draws what was read of it: a schema's types and relations, a vocabulary of labels,
// the first records where there is no schema, and an unbuilt shape where nothing is kept yet.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { CardArt } from './CardArt';
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
