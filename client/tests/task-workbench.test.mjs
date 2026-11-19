import test from 'node:test';
import assert from 'node:assert/strict';
import { taskProgress, snapshotEvents, workflowDraft, waitingGate, nodeStatusTone, nodeStatusLive, flowEdgeTone, latestRunOutputs } from '../src/task-workbench.ts';

test('progress uses the bound run attempts, never a percentage inferred from task status', () => {
  const run = { workflow: { nodes: [{ id: 'a' }, { id: 'b' }, { id: 'c' }] }, nodes: [{ node_id: 'a', status: 'succeeded' }, { node_id: 'b', status: 'failed' }] };
  assert.deepEqual(taskProgress(run), { done: 1, total: 3, percent: 33 });
  assert.deepEqual(taskProgress(undefined), { done: 0, total: 0, percent: 0 });
});

test('drafts preserve execution config and zero coordinates and do not mutate snapshots', () => {
  const workflow = { nodes: [{ id: 'a', name: '分析', x: 0, y: 0, agent_id: 'agent', model: 'm', prompt: '任务', inputRefs: [], deps: [], allow_missing_inputs: true }] };
  const draft = workflowDraft(workflow);
  assert.deepEqual(draft.nodes[0], workflow.nodes[0]);
  draft.nodes[0].deps.push('other');
  assert.deepEqual(workflow.nodes[0].deps, []);
});

test('replay contains only recorded attempt transitions with actual node ids and timestamps', () => {
  const events = snapshotEvents({ nodes: [{ node_id: 'a', status: 'succeeded', started_at: '2026-11-18T01:00:00', finished_at: '2026-11-18T01:01:00' }, { node_id: 'b', status: 'idle' }, { node_id: 'c', status: 'failed', finished_at: '2026-11-18T01:02:00' }] });
  assert.deepEqual(events.map(e => [e.nodeId, e.status]), [['a', 'running'], ['a', 'succeeded'], ['c', 'failed']]);
  assert.equal(events[1].time, '2026-11-18T01:01:00');
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
