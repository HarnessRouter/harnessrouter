import test from 'node:test';
import assert from 'node:assert/strict';
import { agentDetailOf } from '../src/agent-detail.ts';

test('agent detail reads Gateway camelCase fields into the settings layers', () => {
  const detail = agentDetailOf({
    id: 'harn_1',
    name: '产品分析师',
    base: 'codex',
    baseLabel: 'Codex',
    defaultModel: 'gpt-6.1',
    systemPrompt: '你负责分析产品机会，并给出可验证的结论。',
    reasoningEffort: 'high',
    skills: [{ name: 'research', enabled: true }, { name: 'writing', enabled: false }],
    mcpServers: [{ name: 'docs', url: 'https://docs.example/mcp' }],
    disabledTools: ['browser'],
    plugins: [{ name: 'product-kit', enabled: true }],
    additionalHeaders: ['X-Tenant'],
    env: { API_KEY: 'vault:harness-mcp-test', REGION: 'cn', EMPTY: '' },
    maxStep: 12,
    timeoutSeconds: 600,
    memory: { id: 'hmem_1', name: '团队记忆', engine: 'mem0', scope: 'shared', reason: '团队偏好', observe: true, provisioned: true },
    environment: 'henv_1',
    createdAt: 1760000000000,
  });

  assert.equal(detail.instructions.text, '你负责分析产品机会，并给出可验证的结论。');
  assert.equal(detail.instructions.known, true);
  assert.equal(detail.harness.runtime, 'Codex');
  assert.equal(detail.harness.model, 'gpt-6.1');
  assert.equal(detail.harness.reasoning, 'high');
  assert.deepEqual(detail.capabilities.counts, { skills: 2, mcpServers: 1, tools: 1, plugins: 1 });
  assert.deepEqual(detail.capabilities.skills.map((row) => [row.name, row.on]), [['research', true], ['writing', false]]);
  assert.equal(detail.capabilities.mcpServers[0].detail, 'https://docs.example/mcp');
  assert.equal(detail.memory.engine, 'mem0');
  assert.equal(detail.memory.name, '团队记忆');
  assert.deepEqual(detail.environment.vars.map((row) => [row.name, row.valueKind]), [['API_KEY', 'reference'], ['REGION', 'literal'], ['EMPTY', 'empty']]);
  assert.deepEqual(detail.environment.headers, ['X-Tenant']);
  assert.equal(detail.environment.maxStep, 12);
  assert.equal(detail.environment.timeoutSeconds, 600);
  assert.equal(detail.environment.environmentId, 'henv_1');
});

test('agent detail accepts snake_case records and reports absent Gateway fields instead of inventing values', () => {
  const legacy = agentDetailOf({
    id: 'a1',
    name: '旧版 Agent',
    base: 'openai',
    default_model: 'm1',
    system_prompt: '保留原有提示词',
  });
  assert.equal(legacy.instructions.text, '保留原有提示词');
  assert.equal(legacy.harness.model, 'm1');
  assert.equal(legacy.capabilities.known, false);
  assert.equal(legacy.memory.known, false);
  assert.equal(legacy.environment.known, false);

  const missing = agentDetailOf({ id: 'a2', name: '最小 Agent' });
  assert.equal(missing.instructions.known, false);
  assert.equal(missing.harness.runtimeKnown, false);
  assert.equal(missing.harness.modelKnown, false);
  assert.equal(missing.capabilities.counts.skills, 0);
  assert.equal(missing.memory.configured, false);
  assert.equal(missing.environment.vars.length, 0);
  assert.equal(missing.environment.maxStepKnown, false);
});

test('agent detail explains a disabled or string memory without treating it as a provider', () => {
  const off = agentDetailOf({ id: 'a1', name: '无记忆', base: 'codex', memory: 'none' });
  assert.equal(off.memory.known, true);
  assert.equal(off.memory.configured, false);
  assert.equal(off.memory.engine, 'none');

  const reason = agentDetailOf({ id: 'a2', name: '未开通', base: 'codex', memory: null, memory_reason: '该运行时暂不支持记忆。' });
  assert.equal(reason.memory.known, true);
  assert.equal(reason.memory.configured, false);
  assert.equal(reason.memory.reason, '该运行时暂不支持记忆。');
});
