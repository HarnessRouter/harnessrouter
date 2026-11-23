import test from 'node:test';
import assert from 'node:assert/strict';
import { itemRetryAction, attemptLabel, hasManifest, manifestLabel } from '../src/item-history.ts';

const run = { id: 71, task_id: 9, status: 'failed', paused: false };
const control = { id: 8, iteration: 2, node_id: 'work', status: 'failed', input: { item_node_run_ids: [11, 12] } };
const item = { id: 12, run_id: 71, node_id: 'work', iteration: 2, attempt: 3, execution_kind: 'foreach_item', foreach_index: 1, status: 'failed' };

test('only current failed item receives precise active retry or new-run recovery', () => {
  assert.deepEqual(itemRetryAction(run, control, item, false), { kind: 'resume', body: { kind: 'rerun', target_node: 'work', resume_from_run_id: 71, item_node_run_id: 12 } });
  assert.deepEqual(itemRetryAction({ ...run, status: 'waiting_human' }, control, item, false), { kind: 'retry', itemId: 12 });
  for (const altered of [{ ...item, id: 13 }, { ...item, status: 'succeeded' }, { ...item, iteration: 1 }, { ...item, node_id: 'other' }, { ...item, run_id: 72 }]) {
    assert.equal(itemRetryAction(run, control, altered, false), null);
  }
  assert.equal(itemRetryAction(run, control, item, true), null);
  assert.equal(itemRetryAction({ ...run, status: 'completed' }, control, item, false), null);
});

test('history labels distinguish rounds, item indexes and aggregates', () => {
  assert.equal(attemptLabel(item), '第 2 轮 · 集合项 2 · 尝试 3');
  assert.equal(attemptLabel({ ...item, execution_kind: 'foreach_aggregate' }), '第 2 轮 · 聚合 · 尝试 3');
  assert.equal(attemptLabel({ attempt: 1 }), '第 1 轮 · 节点 · 尝试 1');
});

test('nested history identifies both indexes and remains read-only at the leaf', () => {
  const leaf = { ...item, execution_kind: 'foreach_nested_item', input: { outer_foreach_index: 0 } };
  assert.equal(attemptLabel(leaf), '第 2 轮 · 外层项 1 / 内层项 2 · 尝试 3');
  assert.equal(attemptLabel({ ...leaf, execution_kind: 'foreach_nested_aggregate', foreach_index: 0 }), '第 2 轮 · 外层项 1 聚合 · 尝试 3');
  assert.equal(itemRetryAction(run, control, leaf, false), null);
});

test('dynamic item labels expose stable local node identity', () => {
  assert.equal(attemptLabel({ ...item, execution_kind: 'dynamic_item', input: { dynamic_item: { id: 'join' } } }), '第 2 轮 · 计划节点 join · 尝试 3');
});

test('subgraph history uses its persisted child manifest and local identity', () => {
  const control = { id: 18, node_id: 'group', input: { subgraph_node_run_ids: [21, 22] } };
  assert.equal(hasManifest(control), true);
  assert.equal(manifestLabel(control), '子编排节点历史');
  assert.equal(attemptLabel({ ...item, execution_kind: 'subgraph_node', input: { subgraph_node_id: 'review' } }), '第 2 轮 · 子节点 review · 尝试 3');
  assert.equal(attemptLabel({ ...item, execution_kind: 'subgraph_aggregate' }), '第 2 轮 · 子编排聚合 · 尝试 3');
  assert.equal(hasManifest({ id: 19, node_id: 'group', input: {} }), false);
});

test('nested subgraph history labels inner children separately', () => {
  assert.equal(attemptLabel({ execution_kind: 'subgraph_node', attempt: 1, iteration: 1,
    input: { subgraph_node_id: 'leaf', nested_subgraph_parent: true } }), '第 1 轮 · 嵌套子节点 leaf · 尝试 1');
});
