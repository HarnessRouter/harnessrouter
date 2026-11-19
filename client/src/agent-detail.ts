import type { AppAgent } from './app-api';

export type AgentLayer = 'instructions' | 'harness' | 'capabilities' | 'memory' | 'limits';

export const AGENT_LAYERS: ReadonlyArray<{ id: AgentLayer; label: string }> = [
  { id: 'instructions', label: 'Instructions' },
  { id: 'harness', label: 'Agent harness' },
  { id: 'capabilities', label: 'Capabilities' },
  { id: 'memory', label: 'Memory' },
  { id: 'limits', label: 'Environment & limits' },
];

export interface AgentCapabilityRow {
  name: string;
  detail: string;
  on: boolean | null;
}

export interface AgentEnvironmentVar {
  name: string;
  valueKind: 'reference' | 'literal' | 'empty';
}

export interface AgentDetailView {
  instructions: { text: string; known: boolean; chars: number };
  harness: {
    id: string;
    name: string;
    runtime: string;
    runtimeKnown: boolean;
    model: string;
    modelKnown: boolean;
    reasoning: string;
    reasoningKnown: boolean;
    createdAt: number | null;
  };
  capabilities: {
    known: boolean;
    skills: AgentCapabilityRow[];
    mcpServers: AgentCapabilityRow[];
    tools: AgentCapabilityRow[];
    plugins: AgentCapabilityRow[];
    counts: { skills: number; mcpServers: number; tools: number; plugins: number };
  };
  memory: {
    known: boolean;
    configured: boolean;
    name: string;
    engine: string;
    scope: string;
    reason: string;
    observe: boolean;
    provisioned: boolean;
  };
  environment: {
    known: boolean;
    vars: AgentEnvironmentVar[];
    headers: string[];
    maxStep: number | null;
    maxStepKnown: boolean;
    timeoutSeconds: number | null;
    timeoutKnown: boolean;
    environmentId: string;
    environmentKnown: boolean;
  };
}

const recordOf = (value: unknown): Record<string, unknown> | null =>
  value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null;

const arrayOf = (value: unknown): unknown[] => Array.isArray(value) ? value : [];

const textOf = (value: unknown): string => typeof value === 'string' ? value : '';

const hasText = (value: unknown): value is string => typeof value === 'string';

const numberOrNull = (value: unknown): number | null => {
  const number = typeof value === 'number' ? value : Number.NaN;
  return Number.isFinite(number) ? number : null;
};

const firstText = (...values: unknown[]): { value: string; known: boolean } => {
  for (const value of values) if (hasText(value)) return { value, known: true };
  return { value: '', known: false };
};

function capabilityRows(value: unknown, detail: (row: Record<string, unknown>) => string): AgentCapabilityRow[] {
  const rows: AgentCapabilityRow[] = [];
  for (const item of arrayOf(value)) {
    if (typeof item === 'string') { rows.push({ name: item, detail: '', on: null }); continue; }
    const row = recordOf(item);
    if (!row) continue;
    const name = textOf(row.name) || textOf(row.id);
    if (name) rows.push({ name, detail: detail(row), on: row.enabled === false ? false : true });
  }
  return rows;
}

function pluginRows(value: unknown): AgentCapabilityRow[] {
  const rows: AgentCapabilityRow[] = [];
  for (const item of arrayOf(value)) {
    if (typeof item === 'string') { rows.push({ name: item, detail: '已安装', on: true }); continue; }
    const row = recordOf(item);
    if (!row) continue;
    const name = textOf(row.name);
    if (name) rows.push({ name, detail: '已安装', on: row.enabled === false ? false : true });
  }
  return rows;
}

function toolRows(value: unknown): AgentCapabilityRow[] {
  return arrayOf(value).flatMap((item): AgentCapabilityRow[] => typeof item === 'string' ? [{ name: item, detail: '已停用', on: false }] : []);
}

function environmentVars(value: unknown): AgentEnvironmentVar[] {
  const row = recordOf(value);
  if (!row) return [];
  return Object.entries(row).map(([name, raw]) => {
    const text = textOf(raw);
    const valueKind = !text ? 'empty' : /^\s*(?:vault|secret):/i.test(text) ? 'reference' : 'literal';
    return { name, valueKind };
  });
}

export function agentDetailOf(agent: AppAgent): AgentDetailView {
  const instructions = firstText(agent.systemPrompt, agent.system_prompt);
  const runtime = firstText(agent.baseLabel, agent.base);
  const model = firstText(agent.defaultModel, agent.default_model);
  const reasoning = firstText(agent.reasoningEffort);
  const skills = capabilityRows(agent.skills, (row) => textOf(row.description));
  const mcpServers = capabilityRows(agent.mcpServers, (row) => textOf(row.url) || textOf(row.endpoint));
  const tools = toolRows(agent.disabledTools);
  const plugins = pluginRows(agent.plugins);
  const capabilitiesKnown = Array.isArray(agent.skills) || Array.isArray(agent.mcpServers) || Array.isArray(agent.disabledTools) || Array.isArray(agent.plugins);

  const memoryValue = agent.memory;
  const memoryObject = recordOf(memoryValue);
  const memoryText = textOf(memoryValue);
  const memoryReason = textOf(agent.memory_reason) || textOf(memoryObject?.reason);
  const memoryKnown = memoryValue !== undefined || hasText(agent.memory_reason);
  const memoryConfigured = Boolean(memoryObject && textOf(memoryObject.id));
  const memoryEngine = textOf(memoryObject?.engine) || memoryText;
  const memoryName = textOf(memoryObject?.name);
  const memoryScope = textOf(memoryObject?.scope);
  const maxStep = numberOrNull(agent.maxStep);
  const timeoutSeconds = numberOrNull(agent.timeoutSeconds);
  const maxStepKnown = agent.maxStep !== undefined;
  const timeoutKnown = agent.timeoutSeconds !== undefined;
  const vars = environmentVars(agent.env);
  const headers = arrayOf(agent.additionalHeaders).flatMap((value) => typeof value === 'string' && value.trim() ? [value.trim()] : []);
  const environmentKnown = agent.env !== undefined || maxStepKnown || timeoutKnown || agent.additionalHeaders !== undefined || agent.environment !== undefined;

  return {
    instructions: { text: instructions.value, known: instructions.known, chars: instructions.value.length },
    harness: {
      id: agent.id,
      name: agent.name,
      runtime: runtime.value,
      runtimeKnown: runtime.known,
      model: model.value,
      modelKnown: model.known,
      reasoning: reasoning.value,
      reasoningKnown: reasoning.known,
      createdAt: numberOrNull(agent.createdAt),
    },
    capabilities: {
      known: capabilitiesKnown,
      skills,
      mcpServers,
      tools,
      plugins,
      counts: { skills: skills.length, mcpServers: mcpServers.length, tools: tools.length, plugins: plugins.length },
    },
    memory: {
      known: memoryKnown,
      configured: memoryConfigured,
      name: memoryName,
      engine: memoryEngine,
      scope: memoryScope,
      reason: memoryReason,
      observe: memoryObject ? memoryObject.observe !== false : false,
      provisioned: memoryObject?.provisioned === true,
    },
    environment: {
      known: environmentKnown,
      vars,
      headers,
      maxStep,
      maxStepKnown,
      timeoutSeconds,
      timeoutKnown,
      environmentId: textOf(agent.environment),
      environmentKnown: agent.environment !== undefined,
    },
  };
}
