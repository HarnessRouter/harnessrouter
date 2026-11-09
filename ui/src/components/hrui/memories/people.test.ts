// A memory kept for one person is listed by that person's name, as the service stored it, never by the hash it is
// named by (the memories spec, A4 and C5); the engine a new memory gets follows what it is for (vendors.ts).
import { agentMemoryOf, rememberedOf, shownName, userOf } from '@/lib/memories';
import { chooseEngine, scopeWord } from './vendors';

test('a person’s memory is shown by the person: the user field, else the property the service kept it under', () => {
  expect(shownName({ name: 'u_9f2c41', user: 'Dana' })).toBe('Dana');
  expect(shownName({ name: 'u_9f2c41', properties: { user: 'Sam' } } as never)).toBe('Sam');
  expect(shownName({ name: 'Accounts' })).toBe('Accounts');
  expect(userOf({ user: '  ' })).toBe('');
});

test('the engine follows what a memory is for; with nothing to go on, the first connected', () => {
  const all = ['mem0', 'graphiti', 'hindsight', 'reme'];
  expect(chooseEngine('Customer preferences', all)?.id).toBe('mem0');
  expect(chooseEngine('Competitor research timeline', all)?.id).toBe('graphiti');
  expect(chooseEngine('Deployment incidents', all)?.id).toBe('hindsight');
  expect(chooseEngine('Team handbook and wiki', all)?.id).toBe('reme');
  expect(chooseEngine('Misc', ['graphiti', 'reme'])?.id).toBe('graphiti');
  expect(chooseEngine('Anything', [])).toBeNull();
});

test('the words people read for how an agent keeps people', () => {
  expect(scopeWord('per_user')).toBe('Separately for each person');
  expect(scopeWord('shared')).toBe('Shared');
});

test('an agent’s memory on its record: undefined where the record says nothing, null with why where it has none', () => {
  expect(agentMemoryOf({ id: 'h', name: 'x' })).toBeUndefined();
  expect(agentMemoryOf({ memory: null, memory_reason: 'No engine is running here.' })).toEqual({ memory: null, reason: 'No engine is running here.' });
  expect(agentMemoryOf({ memory: { id: 'm', name: 'M', engine: 'mem0', scope: 'per_user', reason: 'Why.' } })?.memory?.scope).toBe('per_user');
});

test('what a turn remembered, read leniently; nothing kept is nothing to say', () => {
  expect(rememberedOf({ memory: { remembered: 2, records: ['a', { id: 'b', memory_id: 'm2' }] } })).toEqual({ count: 2, records: [{ id: 'a' }, { id: 'b', memory_id: 'm2' }], memoryId: 'm2' });
  expect(rememberedOf({ memory: { remembered: 0, records: [] } })).toBeNull();
  expect(rememberedOf({ id: 'resp' })).toBeNull();
});
