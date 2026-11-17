import test from 'node:test';
import assert from 'node:assert/strict';
import { replayStates, layoutRunNodes } from '../src/run-history.ts';

const nodes = [{ id: 'a', name: '收集 A', deps: [] }, { id: 'b', name: '收集 B', deps: [] }, { id: 'c', name: '总结', deps: ['a', 'b'] }];
const events = [{ nodeId: 'a', status: 'running' }, { nodeId: 'b', status: 'running' }, { nodeId: 'a', status: 'succeeded' }, { nodeId: 'b', status: 'failed' }];
test('replay applies only visible events and preserves parallel execution', () => {
  assert.deepEqual(replayStates(nodes, events, 0), { a: 'pending', b: 'pending', c: 'pending' });
  assert.deepEqual(replayStates(nodes, events, 2), { a: 'running', b: 'running', c: 'pending' });
  assert.deepEqual(replayStates(nodes, events, 4), { a: 'succeeded', b: 'failed', c: 'pending' });
});
test('replay clamps boundaries, ignores unknown nodes and never mutates the snapshot', () => {
  const before = JSON.stringify({ nodes, events });
  assert.deepEqual(replayStates(nodes, [...events, { nodeId: 'unknown', status: 'running' }], 99), { a: 'succeeded', b: 'failed', c: 'pending' });
  assert.equal(replayStates(nodes, events, -2).a, 'pending');
  assert.equal(replayStates(nodes, events, Number.NaN).a, 'pending');
  assert.deepEqual(replayStates([], [], 0), {});
  assert.equal(JSON.stringify({ nodes, events }), before);
});
test('DAG layout places parallel nodes separately and dependent nodes after both parents', () => {
  const layout = layoutRunNodes(nodes);
  const a = layout.find(n => n.id === 'a'), b = layout.find(n => n.id === 'b'), c = layout.find(n => n.id === 'c');
  assert.ok(a && b && c);
  assert.equal(a.x, b.x);
  assert.notEqual(a.y, b.y);
  assert.ok(c.x > a.x && c.x > b.x);
  assert.equal(new Set(layout.map(n => `${n.x},${n.y}`)).size, 3);
});
test('layout handles empty and invalid dependency snapshots without hanging', () => {
  assert.deepEqual(layoutRunNodes([]), []);
  const layout = layoutRunNodes([{ id: 'a', name: 'A', deps: ['b'] }, { id: 'b', name: 'B', deps: ['a', 'missing'] }]);
  assert.equal(layout.length, 2);
  assert.ok(layout.every(n => Number.isFinite(n.x) && Number.isFinite(n.y)));
});
