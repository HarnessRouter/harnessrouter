import test from 'node:test';
import assert from 'node:assert/strict';
import { parseComparison, orchestrationIssue, withoutDependency } from '../src/orchestration.ts';

test('comparison inputs retain JSON types and ordinary text', () => {
  for (const [text, expected] of [['fast', 'fast'], ['true', true], ['3', 3], ['null', null], ['["a",2]', ['a', 2]], ['"true"', 'true']]) assert.deepEqual(parseComparison(text), expected);
});
test('configuration validation rejects unsafe paths, invalid bounds and combined execution modes', () => {
  assert.match(orchestrationIssue({ max_concurrency: 0, nodes: [] }), /最大并发/);
  const node = { id: 'b', deps: ['a'], condition: { source: 'a', path: 'route', op: 'eq', value: 'fast' } };
  assert.equal(orchestrationIssue({ nodes: [node] }), undefined);
  assert.match(orchestrationIssue({ nodes: [{ ...node, condition: { ...node.condition, path: '../route' } }] }), /路径/);
  assert.match(orchestrationIssue({ nodes: [{ ...node, foreach: { source: 'missing', path: 'items', max_items: 2 } }] }), /来源/);
  assert.match(orchestrationIssue({ nodes: [{ ...node, repeat: { max_iterations: 3, until: { path: 'done', op: 'exists' } }, foreach: { source: 'a', path: 'items', max_items: 2 } }] }), /同时/);
});
test('removing a dependency also removes conditions and collection references', () => {
  const node = { id: 'b', deps: ['a', 'c'], inputRefs: ['a'], condition: { source: 'a', path: 'route', op: 'exists' }, foreach: { source: 'a', path: 'items', max_items: 2 } };
  const next = withoutDependency(node, 'a');
  assert.deepEqual(next.deps, ['c']); assert.deepEqual(next.inputRefs, []);
  assert.equal(next.condition, undefined); assert.equal(next.foreach, undefined);
  assert.deepEqual(node.deps, ['a', 'c']);
});
