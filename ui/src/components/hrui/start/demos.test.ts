// A demo's harness and model are the design's pair, each only when this account can have it, and never
// another harness or model in its place (Richard 10-19: no fallbacks).
const mockCat: { runs: Record<string, string[]>; def: Record<string, string> } = { runs: {}, def: {} };
jest.mock('@/lib/harness', () => ({
  ...jest.requireActual('@/lib/harness'),
  oobModels: (o: { id: string } | null) => (o ? mockCat.runs[o.id] || [] : []),
  oobDefaultModel: (o: { id: string } | null) => (o ? mockCat.def[o.id] || '' : ''),
  modelAvailability: () => 'yes',
}));

import type { BaseInfo } from '@/lib/harness';
import { DEMOS, defaultModelOf, demoPick } from './demos';

const bases = (...ids: string[]) => Object.fromEntries(ids.map((id) => [id, { id } as unknown as BaseInfo]));
const contract = DEMOS.findIndex((d) => d.base === 'dsh');

beforeEach(() => { mockCat.runs = { dsh: ['deepseek-v4-pro'], hermes: ['gpt-5.4'] }; mockCat.def = { dsh: 'deepseek-v4-pro', hermes: 'gpt-5.4' }; });

test('the demo\'s own pair when the server offers its harness and runs its model', () => {
  expect(demoPick(contract, bases('dsh', 'hermes'))).toEqual({ base: 'dsh', model: 'deepseek-v4-pro' });
});

test('a demo whose harness is not offered gets no harness, never the default one', () => {
  expect(demoPick(contract, bases('hermes'))).toEqual({ base: '', model: '' });
});

test('a demo whose model its harness cannot run now gets no model, never another', () => {
  mockCat.runs.dsh = ['deepseek-v4-flash'];
  expect(demoPick(contract, bases('dsh'))).toEqual({ base: 'dsh', model: '' });
});

test('a harness whose default cannot run has no default here, never its first runnable model', () => {
  mockCat.runs.hermes = ['glm-5.3'];
  expect(defaultModelOf('hermes')).toBe('');
  mockCat.runs.hermes = ['glm-5.3', 'gpt-5.4'];
  expect(defaultModelOf('hermes')).toBe('gpt-5.4');
});
