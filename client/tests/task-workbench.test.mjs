import test from 'node:test';
import assert from 'node:assert/strict';
import { taskProgress, snapshotEvents, workflowDraft, workflowPayload, waitingGate, nodeStatusTone, nodeStatusLive, flowEdgeTone, latestRunOutputs } from '../src/task-workbench.ts';

test('progress uses the bound run attempts, never a percentage inferred from task status', () => {
  const run = { workflow: { nodes: [{ id: 'a' }, { id: 'b' }, { id: 'c' }] }, nodes: [{ node_id: 'a', status: 'succeeded' }, { node_id: 'b', status: 'failed' }] };
  assert.deepEqual(taskProgress(run), { done: 1, total: 3, percent: 33 });
  assert.deepEqual(taskProgress(undefined), { done: 0, total: 0, percent: 0 });
});

test('drafts preserve execution config and zero coordinates and do not mutate snapshots', () => {
  const workflow = { max_concurrency: 2, nodes: [{ id: 'a', name: '分析', x: 0, y: 0, agent_id: 'agent', model: 'm', prompt: '任务', inputRefs: [], deps: [], allow_missing_inputs: true, repeat: { max_iterations: 3, until: { path: 'done', op: 'eq', value: true } } }] };
  const draft = workflowDraft(workflow);
  assert.equal(draft.max_concurrency, 2);
  assert.deepEqual(draft.nodes[0], workflow.nodes[0]);
  draft.nodes[0].deps.push('other');
  assert.deepEqual(workflow.nodes[0].deps, []);
  draft.nodes[0].repeat.until.value = false;
  assert.equal(workflow.nodes[0].repeat.until.value, true);
});

test('replay contains only recorded attempt transitions with actual node ids and timestamps', () => {
  const events = snapshotEvents({ nodes: [{ node_id: 'a', status: 'succeeded', started_at: '2026-11-18T01:00:00', finished_at: '2026-11-18T01:01:00' }, { node_id: 'b', status: 'idle' }, { node_id: 'c', status: 'failed', finished_at: '2026-11-18T01:02:00' }] });
  assert.deepEqual(events.map(e => [e.nodeId, e.status]), [['a', 'running'], ['a', 'succeeded'], ['c', 'failed']]);
  assert.equal(events[1].time, '2026-11-18T01:01:00');
});

test('editor drafts keep approval requirements without mutating the saved workflow', () => {
  const workflow = { tool_approval_policy: { require: ['external_write'] }, nodes: [
    { id: 'a', tool_approval_policy: { require: ['destructive'] } },
  ] };
  const draft = workflowDraft(workflow);
  assert.deepEqual(draft.tool_approval_policy, workflow.tool_approval_policy);
  assert.deepEqual(workflowPayload(draft).tool_approval_policy, workflow.tool_approval_policy);
  assert.deepEqual(workflowPayload(draft).nodes[0].tool_approval_policy, workflow.nodes[0].tool_approval_policy);
  draft.tool_approval_policy.require.push('credential_access');
  draft.nodes[0].tool_approval_policy.require.push('permission_change');
  assert.deepEqual(workflow.tool_approval_policy.require, ['external_write']);
  assert.deepEqual(workflow.nodes[0].tool_approval_policy.require, ['destructive']);
});

test('workflow submissions preserve invalid explicit policies for server rejection and omit absent policies', () => {
  for (const policy of [null, {}, { require: [] }]) {
    assert.deepEqual(workflowPayload(workflowDraft({ nodes: [], tool_approval_policy: policy })).tool_approval_policy, policy);
  }
  assert.deepEqual(workflowPayload(workflowDraft({ nodes: [] })), { nodes: [] });
});

test('human gate only offers succeeded dependencies for the ready gate in the bound run', () => {
  const run = { status: 'waiting_human', workflow: { nodes: [{ id: 'gate', requires_human: true, deps: ['a', 'b'] }] }, nodes: [{ node_id: 'a', status: 'succeeded' }, { node_id: 'b', status: 'succeeded' }, { node_id: 'gate', status: 'idle' }], decisions: [] };
  assert.equal(waitingGate(run).id, 'gate');
  assert.equal(waitingGate({ ...run, decisions: [{ node_id: 'gate' }] }), undefined);
});

test('node and edge tones distinguish live, completed and failed workflow states', () => {
  assert.equal(nodeStatusTone('succeeded'), 'green');
  assert.equal(nodeStatusTone('running'), 'amber');
  assert.equal(nodeStatusTone('queued'), 'blue');
  assert.equal(nodeStatusTone('failed'), 'red');
  assert.equal(nodeStatusTone(undefined), 'gray');

  assert.equal(nodeStatusLive('running'), true);
  assert.equal(nodeStatusLive('queued'), false);
  assert.equal(nodeStatusLive('idle'), false);
  assert.equal(nodeStatusLive('succeeded'), false);

  assert.equal(flowEdgeTone('succeeded', 'succeeded'), 'done');
  assert.equal(flowEdgeTone('succeeded', 'running'), 'active');
  assert.equal(flowEdgeTone('succeeded', 'queued'), 'ready');
  assert.equal(flowEdgeTone('queued', 'queued'), 'pending');
  assert.equal(flowEdgeTone('failed', 'idle'), 'failed');
  assert.equal(flowEdgeTone('idle', 'idle'), 'pending');
});

test('latest run outputs expose node identity and status for direct task results', () => {
  const run = { nodes: [
    { node_id: 'a', status: 'succeeded', output: { text: '来自 API 的节点输出' } },
    { node_id: 'b', status: 'failed', output: null },
    { node_id: 'c', status: 'running', output: {} },
  ] };
  assert.deepEqual(latestRunOutputs(run), [
    { nodeId: 'a', status: 'succeeded', output: { text: '来自 API 的节点输出' } },
    { nodeId: 'c', status: 'running', output: {} },
  ]);
  assert.deepEqual(latestRunOutputs(undefined), []);
});
