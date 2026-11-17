import test from 'node:test';
import assert from 'node:assert/strict';
import { fromWorkflowRecord, mergeWorkflowTasks } from '../src/workflow.ts';

function record(overrides = {}) {
  return {
    id: 'wtask_1', title: '远程任务', input: '执行', status: 'running', created_at: 10, updated_at: 20,
    snapshot: { template_id: 'tpl', template_version: 2, title: '模板', description: '说明', nodes: [
      { id: 'a', name: '分析', agent_id: 'agent', agent_name: '分析 Agent', deps: [], status: 'done', attempts: 1, output: '结果', response_id: 'resp_1' },
    ] },
    ...overrides,
  };
}

test('workflow records normalize into the client task shape', () => {
  const task = fromWorkflowRecord(record());
  assert.equal(task.id, 'wtask_1');
  assert.equal(task.status, 'running');
  assert.equal(task.snapshot.nodes[0].status, 'done');
  assert.equal(task.snapshot.nodes[0].responseId, 'resp_1');
});

test('remote records replace the matching local snapshot and retain local drafts', () => {
  const current = [
    fromWorkflowRecord(record({ status: 'pending', updated_at: 15 })),
    { id: 'task-local', title: '本地草稿', templateId: '', templateVersion: 1, createdAt: 1, status: 'pending', input: '', lastUpdated: 1, snapshot: { title: '草稿', description: '', nodes: [] } },
  ];
  const merged = mergeWorkflowTasks(current, [record()]);
  assert.equal(merged[0].status, 'running');
  assert.equal(merged[0].snapshot.nodes[0].output, '结果');
  assert.equal(merged[1].id, 'task-local');
});

test('a delayed poll cannot roll a newer remote task back', () => {
  const current = [fromWorkflowRecord(record({ status: 'completed', updated_at: 30 }))];
  const merged = mergeWorkflowTasks(current, [record({ status: 'running', updated_at: 20 })]);
  assert.equal(merged[0].status, 'completed');
  assert.equal(merged[0].lastUpdated, 30);
});
