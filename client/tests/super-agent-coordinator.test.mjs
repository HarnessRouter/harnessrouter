import test from 'node:test';
import assert from 'node:assert/strict';
import { coordinatorSummary, dispatchableTasks, latestOutput, mergeCoordinatorRun, runProgress, statusLabel } from '../src/super-agent-coordinator.ts';

test('coordinator aggregates independent runs without deriving status from another task', () => {
  const rows = [
    { taskId: 7, taskTitle: '市场分析', run: { id: 11, task_id: 7, status: 'running', nodes: [{ node_id: 'a', status: 'succeeded' }, { node_id: 'b', status: 'running' }] } },
    { taskId: 8, taskTitle: '竞品评审', run: { id: 12, task_id: 8, status: 'failed', nodes: [{ node_id: 'x', status: 'failed' }] } },
  ];
  assert.deepEqual(coordinatorSummary(rows), { total: 2, active: 1, waiting: 0, completed: 0, failed: 1, percent: 50 });
  assert.deepEqual(runProgress(rows[0].run), { done: 1, total: 2, percent: 50 });
  assert.equal(statusLabel('waiting_human'), '等待人工');
});

test('a live snapshot replaces only its own run and preserves other subscriptions', () => {
  const rows = [
    { taskId: 7, taskTitle: '市场分析', run: { id: 11, task_id: 7, status: 'running', nodes: [] } },
    { taskId: 8, taskTitle: '竞品评审', run: { id: 12, task_id: 8, status: 'running', nodes: [] } },
  ];
  const next = mergeCoordinatorRun(rows, { id: 12, task_id: 8, status: 'completed', nodes: [{ node_id: 'x', status: 'succeeded' }] });
  assert.equal(next[0].run.status, 'running');
  assert.equal(next[1].run.status, 'completed');
  assert.equal(next[1].run.nodes[0].status, 'succeeded');
});

test('coordinator ignores unsaved tasks as dispatch candidates', () => {
  assert.deepEqual(dispatchableTasks([
    { id: 1, title: '已保存', status: 'draft', current_revision: 2, workflow_state: 'saved', workflow: { nodes: [{ id: 'a' }] } },
    { id: 2, title: '草稿', status: 'draft', current_revision: 0, workflow_state: 'draft', workflow: { nodes: [{ id: 'a' }] } },
    { id: 3, title: '空流程', status: 'draft', current_revision: 1, workflow_state: 'saved', workflow: { nodes: [] } },
  ]).map(task => task.id), [1]);
});

test('a delayed previous Run cannot overwrite a newer Run for the same task', () => {
  const rows = [{ taskId: 7, run: { id: 12, task_id: 7, status: 'running', nodes: [] } }];
  assert.equal(mergeCoordinatorRun(rows, { id: 11, task_id: 7, status: 'completed', nodes: [] })[0].run.id, 12);
});

test('only the latest attempt of each workflow node counts toward progress', () => {
  assert.deepEqual(runProgress({ workflow: { nodes: [{ id: 'a' }, { id: 'b' }] }, nodes: [
    { node_id: 'a', attempt: 1, status: 'succeeded' },
    { node_id: 'a', attempt: 2, status: 'running' },
    { node_id: 'b', attempt: 1, status: 'succeeded' },
    { node_id: 'removed', attempt: 1, status: 'succeeded' },
  ] }), { done: 1, total: 2, percent: 50 });
});

test('completed, archived and active tasks are not dispatchable', () => {
  const base = { workflow_state: 'saved', workflow: { nodes: [{ id: 'a' }] } };
  assert.deepEqual(dispatchableTasks(['draft', 'failed', 'running', 'waiting', 'completed', 'archived'].map((status, id) => ({ ...base, id, status }))).map(t => t.status), ['draft', 'failed']);
});

test('reports response message text instead of response IDs or metadata', () => {
  assert.equal(latestOutput({ nodes: [{ node_id: 'report', status: 'succeeded', output: {
    id: 'response-42', status: 'completed', output: [{ type: 'message', content: [{ type: 'output_text', text: '真正的研究结论' }] }],
  } }] }), '真正的研究结论');
  assert.equal(latestOutput({ nodes: [{ node_id: 'report', status: 'succeeded', output: { id: 'response-42', status: 'completed' } }] }), '');
});
