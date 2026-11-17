import test from 'node:test';
import assert from 'node:assert/strict';
import { connectionIssue, edgePath, graphBounds, nodeRole } from '../src/template-graph.ts';

const nodes = [
  { id: 'node-1', name: '理解任务目标', x: 20, y: 210, deps: [] },
  { id: 'node-2', name: '产品价值分析', x: 220, y: 60, deps: ['node-1'] },
  { id: 'node-4', name: '风险评审', x: 420, y: 210, deps: ['node-2'] },
  { id: 'node-5', name: '最终总结', x: 620, y: 210, deps: ['node-4'] },
];

test('connection checks reject self, duplicate and cyclic edges', () => {
  assert.equal(connectionIssue(nodes, 'node-1', 'node-1'), 'self');
  assert.equal(connectionIssue(nodes, 'node-1', 'node-2'), 'duplicate');
  assert.equal(connectionIssue(nodes, 'node-5', 'node-1'), 'cycle');
  assert.equal(connectionIssue(nodes, 'node-1', 'node-5'), null);
});

test('edge paths leave the output port and arrive at the input port', () => {
  const path = edgePath(nodes[0], nodes[1]);
  assert.match(path, /^M 210 256 C /);
  assert.match(path, / 220 106$/);
});

test('node roles distinguish starts, agents and terminal summaries', () => {
  assert.equal(nodeRole(nodes, nodes[0]), '起点');
  assert.equal(nodeRole(nodes, nodes[1]), 'Agent');
  assert.equal(nodeRole(nodes, nodes[3]), '总结');
});

test('graph bounds follow nodes beyond the original canvas area', () => {
  const shifted = nodes.map(node => node.id === 'node-5' ? { ...node, x: 1240, y: 780 } : node);
  const bounds = graphBounds(shifted);
  assert.equal(bounds.left, 20);
  assert.equal(bounds.top, 60);
  assert.equal(bounds.width, 1410);
  assert.equal(bounds.height, 812);
});
