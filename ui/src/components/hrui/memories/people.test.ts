// A memory kept for one person is listed by that person's name, as the service gives it to whoever manages the memory
// (`end_user`), never by the hash it is named by (the memories spec, A4 and C5). The engine a new memory gets is the
// service's to say (GET /v1/memories/choose), so nothing here reads what a memory is for.
import { agentMemoryOf, CONSOLE_PERSON, personName, rememberedOf, shownName, userOf } from '@/lib/memories';
import * as vendors from './vendors';
import { scopeWord } from './vendors';

test('a person’s memory is shown by the person the service names in end_user', () => {
  expect(shownName({ name: '9f2c41aa', end_user: 'Dana' })).toBe('Dana');
  expect(shownName({ name: 'Accounts' })).toBe('Accounts');
  expect(userOf({ end_user: '  ' })).toBe('');
  // what the service never sends is never read: a bare `user` is not who a memory is for
  expect(shownName({ name: '9f2c41aa', user: 'Sam' } as never)).toBe('9f2c41aa');
});

test('the console’s own test identity reads as you, never as its address; anyone else keeps the string their app sent', () => {
  // a task sent from this console names nobody, so the gateway takes the console member as its person
  expect(shownName({ name: '1f0c9a', end_user: 'local@localhost' })).toBe('You (this console)');
  expect(CONSOLE_PERSON).toBe('You (this console)');
  expect(personName(' local@localhost ')).toBe('You (this console)');
  expect(personName('user_8812')).toBe('user_8812');
  expect(personName('')).toBe('');
});

test('the console keeps no copy of the engine scorer: the service chooses', () => {
  expect('chooseEngine' in vendors).toBe(false);
});

test('the words people read for how an agent keeps people', () => {
  expect(scopeWord('per_user')).toBe('Separately for each person');
  expect(scopeWord('shared')).toBe('Shared');
});

test('an agent’s memory on its record: undefined where the record says nothing, null with why where it has none', () => {
  expect(agentMemoryOf({ id: 'h', name: 'x' })).toBeUndefined();
  expect(agentMemoryOf({ memory: null, memory_reason: 'No engine is running here.' })).toEqual({ memory: null, reason: 'No engine is running here.' });
  expect(agentMemoryOf({ memory: { id: 'm', name: 'M', engine: 'mem0', scope: 'per_user', reason: 'Why.', observe: true } })).toEqual({
    memory: { id: 'm', name: 'M', engine: 'mem0', scope: 'per_user', reason: 'Why.' }, reason: 'Why.' });
});

test('what a build proposes before it saves: the engine and why, with nothing made yet', () => {
  expect(agentMemoryOf({ memory: { engine: 'graphiti', scope: 'shared', reason: 'It tracks people.' } })).toEqual({
    memory: { id: '', name: '', engine: 'graphiti', scope: 'shared', reason: 'It tracks people.' }, reason: 'It tracks people.' });
  expect(agentMemoryOf({ memory: { engine: null, scope: 'per_user', reason: 'No memory engine is running here.' } })).toEqual({
    memory: null, reason: 'No memory engine is running here.' });
});

test('what a turn remembered, as the service writes it: each record with the memory it is in', () => {
  expect(rememberedOf({ memory: { remembered: 2, records: [{ id: 'a', memory_id: 'm1' }, { id: 'b', memory_id: 'm2' }] } }))
    .toEqual({ count: 2, records: [{ id: 'a', memory_id: 'm1' }, { id: 'b', memory_id: 'm2' }], memoryId: 'm1' });
  expect(rememberedOf({ memory: { remembered: 0, records: [], pending: true } })).toBeNull();
  expect(rememberedOf({ memory: { skipped: 'no end user named' } })).toBeNull();
  expect(rememberedOf({ id: 'resp' })).toBeNull();
});
