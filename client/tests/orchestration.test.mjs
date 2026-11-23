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

test('nested collections validate the relative path, bound and execution mode', () => {
  const node = { id: 'b', deps: ['a'], foreach: { source: 'a', path: 'groups', max_items: 2,
    nested: { path: 'items', max_items: 3, mode: 'parallel' } } };
  assert.equal(orchestrationIssue({ nodes: [node] }), undefined);
  for (const patch of [{ path: '../items' }, { max_items: 11 }, { mode: 'invalid' }]) {
    assert.match(orchestrationIssue({ nodes: [{ ...node, foreach: { ...node.foreach, nested: { ...node.foreach.nested, ...patch } } }] }), /嵌套集合/);
  }
  assert.deepEqual(withoutDependency({ ...node, inputRefs: ['a'] }, 'a').foreach, undefined);
});

test('dynamic topology is opt-in and rejects unknown values', () => {
  const node = { id: 'b', deps: ['a'], dynamic_plan: { source: 'a', path: 'text', max_items: 10, topology: 'dag' } };
  assert.equal(orchestrationIssue({ nodes: [node] }), undefined);
  assert.match(orchestrationIssue({ nodes: [{ ...node, dynamic_plan: { ...node.dynamic_plan, topology: 'unknown' } }] }), /拓扑/);
});

test('static subgraphs validate bounded one-level nested child definitions', () => {
  const node = { id: 'group', deps: ['source'], subgraph: { max_concurrency: 2, nodes: [{ id: 'child' }] } };
  assert.equal(orchestrationIssue({ nodes: [node] }), undefined);
  assert.match(orchestrationIssue({ nodes: [{ ...node, deps: [] }] }), /必须依赖/);
  assert.match(orchestrationIssue({ nodes: [{ ...node, subgraph: { max_concurrency: 11, nodes: [{ id: 'child' }] } }] }), /并发数/);
  assert.equal(orchestrationIssue({ nodes: [{ ...node, subgraph: { max_concurrency: 1, nodes: [{ id: 'child', subgraph: { max_concurrency: 1, nodes: [{ id: 'leaf' }] } }] } }] }), undefined);
  assert.match(orchestrationIssue({ nodes: [{ ...node, subgraph: { max_concurrency: 1, nodes: [{ id: 'child', subgraph: { max_concurrency: 1, nodes: [{ id: 'leaf', subgraph: { nodes: [{ id: 'deep' }] } }] } }] } }] }), /两层/);
});

test('static subgraphs reject duplicate, unknown, cyclic and invalid child references', () => {
  const base = { id: 'group', deps: ['source'], subgraph: { nodes: [{ id: 'a' }, { id: 'b', deps: ['a'], inputRefs: ['a'] }] } };
  assert.match(orchestrationIssue({ nodes: [{ ...base, subgraph: { nodes: [{ id: 'a' }, { id: 'a' }] } }] }), /重复/);
  assert.match(orchestrationIssue({ nodes: [{ ...base, subgraph: { nodes: [{ id: 'a', deps: ['missing'] }] } }] }), /未知/);
  assert.match(orchestrationIssue({ nodes: [{ ...base, subgraph: { nodes: [{ id: 'a', deps: ['b'] }, { id: 'b', deps: ['a'] }] } }] }), /环/);
  assert.match(orchestrationIssue({ nodes: [{ ...base, subgraph: { nodes: [{ id: 'a', inputRefs: ['b'] }, { id: 'b' }] } }] }), /inputRefs/);
  assert.match(orchestrationIssue({ nodes: [{ ...base, subgraph: { nodes: [{ id: 'a', deps: ['a'] }] } }] }), /环/);
  assert.match(orchestrationIssue({ nodes: [{ ...base, subgraph: { nodes: [{ id: 'a', deps: 'source' }] } }] }), /必须是数组/);
});

test('dynamic subgraphs validate a bounded source and local execution mode', () => {
  const node = { id: 'group', deps: ['planner'], subgraph: { max_concurrency: 2, dynamic: { source: 'planner', path: 'nodes', max_nodes: 3, mode: 'parallel' } } };
  assert.equal(orchestrationIssue({ nodes: [node] }), undefined);
  assert.match(orchestrationIssue({ nodes: [{ ...node, subgraph: { ...node.subgraph, dynamic: { ...node.subgraph.dynamic, source: 'missing' } } }] }), /来源/);
  assert.match(orchestrationIssue({ nodes: [{ ...node, subgraph: { ...node.subgraph, dynamic: { ...node.subgraph.dynamic, path: '../nodes' } } }] }), /路径/);
  assert.match(orchestrationIssue({ nodes: [{ ...node, subgraph: { ...node.subgraph, dynamic: { ...node.subgraph.dynamic, max_nodes: 11 } } }] }), /节点上限/);
  assert.match(orchestrationIssue({ nodes: [{ ...node, subgraph: { ...node.subgraph, dynamic: { ...node.subgraph.dynamic, mode: 'bad' } } }] }), /调度模式/);
});
