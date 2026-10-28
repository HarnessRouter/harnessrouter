// Harness data layer.
//
// What a base harness CAN DO — its models, its tools, its built-in skills, its system prompt —
// comes from the server (/v1/bases), never from this file. It used to be hard-coded here, and it
// drifted: the console advertised four built-in skills (docx, pdf, pptx, xlsx) that exist nowhere,
// with Replace and Disable buttons next to them acting on nothing, while the agent actually had a
// completely different set the CLI discovers for itself. The static table below now carries only
// identity and presentation (and the model placeholders the gateway's tests hold to its catalog);
// every capability field is filled in from the server.
// Custom harnesses (setups) are persisted by the gateway (/v1/harnesses) through the console's own
// proxy (/api/harness).
import { useEffect, useState } from 'react';

import { harnessFetch } from '@/lib/hfetch';
import { getSession } from '@/lib/auth';
import { appendWorkspaceQuery, workspaceHeaders } from '@/lib/workspace';

export interface OobHarness {
  id: string;
  name: string;
  version: string;
  models: string[];        // shown as pills (display order; newest first)
  defaultModel?: string;   // the backend default, NOT necessarily models[0]
  moreModels?: number;     // "+N" pill
  status: 'ready' | 'soon';
  backend: 'claude' | 'codex' | 'hermes' | 'pi' | 'dsh' | 'opencode' | 'kilo' | 'qwen' | 'gemini' | 'cline' | 'omp' | 'goose' | 'kimi' | 'minimax' | 'aider' | 'openhands' | 'grok' | 'systemone' | 'cheetahclaws' | 'agentzero' | 'mimo' | 'jcode' | 'opensquilla' | 'nanobot' | 'zeroclaw' | 'qoder' | 'vibe' | 'docker-agent' | 'fast-agent' | 'dcode' | null; // gateway backend; null = coming soon
  systemPrompt: string;    // the harness's built-in system prompt (shown read-only)
  tools: string[];         // built-in tools (read-only)
  skills: string[];        // built-in skills (read-only)
}

/** One entry in a Harness's tool list: a server somewhere else, addressed by URL. */
export interface McpServer {
  id: string; name: string; enabled: boolean;
  url?: string; auth?: string; transport?: string;
}

export interface CustomHarness {
  id: string;
  name: string;
  base: string;            // base harness id (codex / claude-code)
  baseLabel: string;
  defaultModel: string;
  systemPrompt: string;
  mcpServers: McpServer[];
  // A skill carries its bundle inline as `files`; bundles over the gateway's inline cap are
  // offloaded server-side and round-trip as {name, enabled, blob}, `blob` is an opaque pointer,
  // resolved back to files via getSkillFiles() when editing. Either shape is a REAL own skill.
  skills: { id: string; name: string; enabled: boolean; files?: { path: string; content?: string; content_b64?: string }[]; blob?: string }[];
  disabledTools?: string[];  // inherited/built-in tool names disabled for this harness
  maxStep?: number | null;        // default agent step budget per turn (blank = the server's runtime default)
  timeoutSeconds?: number | null; // default per-turn wall-clock cap (blank = the server's runtime default)
  reasoningEffort?: string;       // how much the model thinks on this harness's Tasks ('' = the model's default)
  // The environment (henv_) every Task of this Harness reads at its mount path, read-only; '' for none.
  environment?: string;
  additionalHeaders?: string[]; // declared header NAMES callers pass per request (app-level auth)
  // Variables every Task's shell and tools start with. A value is `$headers.X-Name` (a declared
  // request header), `vault:ref` (a stored secret) or a literal. Resolved by the service per turn.
  env?: Record<string, string>;
  // Installed plugins (UHP Plugins chapter). The server derives manifest, mcpServers, skills and
  // skipped from the package on every save; a saved plugin round-trips as {name, enabled, blob}
  // plus those derived fields, and a freshly picked one carries its `files` until it is saved.
  plugins?: HarnessPlugin[];
  // Where it came from, as whatever made it said at create ("demo:<n>@<ms>": the recorded demo run
  // Start saved it from, start/replay.ts). Sent only on create; the server never changes it after.
  source?: string;
  createdAt: number;
}

export type HarnessPlugin = {
  name: string; enabled?: boolean; blob?: string;
  files?: { path: string; content?: string; content_b64?: string }[];
  manifest?: { name?: string; version?: string; description?: string; license?: string;
               homepage?: string; repository?: string; keywords?: string[];
               author?: { name?: string; email?: string; url?: string } };
  mcpServers?: { name: string; transport?: string; url?: string; command?: string; args?: string[] }[];
  skills?: { name: string; description?: string }[];
  skipped?: { path: string; reason: string }[];
};

// Every models list and defaultModel below is the gateway's _MODEL_CATALOG for that backend
// (gateway/app.py), byte for byte; gateway/tests/test_console_placeholders.py fails the suite when
// they drift. They stand in only until the catalog read on page load lands (fetchModelCatalog),
// which then wins everywhere. On 2026-09-27 the placeholder defaults were older than the gateway's
// (codex and hermes on gpt-5.5, claude-code on claude-opus-4.8) and the helper put the placeholder
// ahead of the server's answer, so a fresh page could open on a model the gateway no longer
// defaults to; hosted found the same shape with entries that had no default at all and opened on
// the first entry of a list that leads with the newest and priciest ids. The default is data here,
// never the first entry.
export const OOB: OobHarness[] = [
  { id: 'codex', name: 'Codex', version: 'v1.0.1', backend: 'codex', status: 'ready',
    models: ['gpt-6.1-sol', 'gpt-6-astra', 'gpt-6-sol', 'gpt-6-luna', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.5', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.3-codex', 'gpt-5.2'], defaultModel: 'gpt-6.1-sol', moreModels: 0,
    systemPrompt: 'You are Codex, an autonomous software-engineering agent. You operate on a real git workspace with shell access, reading and editing files and running commands to complete the task, returning reviewable diffs and results.',
    tools: [], skills: [] },
  { id: 'claude-code', name: 'Claude Code', version: 'v1.0.1', backend: 'claude', status: 'ready',
    models: ['claude-fable-5-1', 'claude-fable-5', 'claude-opus-5.5', 'claude-opus-5', 'claude-sonnet-5.5', 'claude-sonnet-5', 'claude-opus-4.8', 'claude-opus-4.7', 'claude-sonnet-4.6', 'claude-haiku-5.5', 'claude-haiku-4.5'], defaultModel: 'claude-sonnet-4.6', moreModels: 0,
    systemPrompt: 'You are Claude Code, an agentic coding assistant. You work on a real local git working tree with bash, edit files, run tests, and use sub-agents to complete engineering tasks end to end.',
    tools: [], skills: [] },
  { id: 'hermes', name: 'Hermes', version: 'v0.19.0', backend: 'hermes', status: 'ready',
    // Multi-family: Hermes runs any frontier model, the gpt + claude catalogs, default gpt-5.5.
    models: ['gpt-6.1-sol', 'gpt-6-astra', 'gpt-6-sol', 'gpt-6-luna', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.5', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.3-codex', 'gpt-5.2', 'claude-fable-5-1', 'claude-fable-5', 'claude-opus-5.5', 'claude-opus-5', 'claude-sonnet-5.5', 'claude-sonnet-5', 'claude-opus-4.8', 'claude-opus-4.7', 'claude-sonnet-4.6', 'claude-haiku-5.5', 'claude-haiku-4.5', 'gemini-4-argon', 'gemini-3.8-flash', 'gemini-3.7-flash', 'gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-pro-preview', 'gemini-3.1-flash-lite', 'gemini-3-flash-preview', 'grok-4.6', 'grok-4.5', 'grok-4.3', 'grok-4.20', 'grok-build-0.1', 'muse-wonder-1.0', 'muse-spark-1.3', 'muse-spark-1.2', 'muse-spark-1.1', 'muse-glimmer-30b', 'llama-4-maverick', 'deepseek-v4.1-flash', 'deepseek-v4-pro', 'deepseek-v4-flash', 'kimi-k3', 'kimi-k2.7-code', 'qwen3.8-max', 'qwen3.8-flash', 'qwen3.8-27b', 'qwen3.7-max', 'qwen3.7-plus', 'qwen3.7-flash', 'glm-5.3', 'glm-5.3-flash', 'mistral-medium-3.5', 'step-3.7-flash', 'hunyuan-4-preview', 'hunyuan-3', 'minimax-m3', 'nemotron-3.5-lightning', 'nemotron-3-ultra', 'nemotron-3-super', 'ling-3.0-flash'], defaultModel: 'gpt-6.1-sol', moreModels: 0,
    systemPrompt: 'You are Hermes, a self-improving autonomous agent. You work on a real project workspace with shell and file access, complete tasks end to end, and build a persistent memory and skill library from what you learn, getting more capable the longer you run.',
    tools: [], skills: [] },
  { id: 'pi', name: 'Pi', version: 'v0.84.2', backend: 'pi', status: 'ready',
    // Multi-family like Hermes: the gpt + claude catalogs (placeholder until /v1/models lands).
    models: ['gpt-6.1-sol', 'gpt-6-astra', 'gpt-6-sol', 'gpt-6-luna', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.5', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.3-codex', 'gpt-5.2', 'claude-fable-5-1', 'claude-fable-5', 'claude-opus-5.5', 'claude-opus-5', 'claude-sonnet-5.5', 'claude-sonnet-5', 'claude-opus-4.8', 'claude-opus-4.7', 'claude-sonnet-4.6', 'claude-haiku-5.5', 'claude-haiku-4.5', 'gemini-4-argon', 'gemini-3.8-flash', 'gemini-3.7-flash', 'gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-pro-preview', 'gemini-3.1-flash-lite', 'gemini-3-flash-preview', 'grok-4.6', 'grok-4.5', 'grok-4.3', 'grok-4.20', 'grok-build-0.1', 'muse-wonder-1.0', 'muse-spark-1.3', 'muse-spark-1.2', 'muse-spark-1.1', 'muse-glimmer-30b', 'llama-4-maverick', 'deepseek-v4.1-flash', 'deepseek-v4-pro', 'deepseek-v4-flash', 'kimi-k3', 'kimi-k2.7-code', 'qwen3.8-max', 'qwen3.8-flash', 'qwen3.8-27b', 'qwen3.7-max', 'qwen3.7-plus', 'glm-5.3', 'glm-5.3-flash', 'mistral-medium-3.5', 'step-3.7-flash', 'hunyuan-4-preview', 'nemotron-3.5-lightning', 'nemotron-3-super'], defaultModel: 'gpt-6.1-sol', moreModels: 0,
    systemPrompt: 'You are Pi, a minimal autonomous coding agent. You operate on a real git workspace, reading, writing and editing files and running bash to complete the task end to end.',
    tools: [], skills: [] },
  { id: 'dsh', name: 'DeepSeek Harness', version: 'v0.1.0-rc.7', backend: 'dsh', status: 'ready',
    // Multi-family via dsh-llm-pi-ai (pi's LLM library as a dsh plugin); placeholder until /v1/models lands.
    models: ['gpt-6.1-sol', 'gpt-6-astra', 'gpt-6-sol', 'gpt-6-luna', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.5', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.3-codex', 'gpt-5.2', 'claude-fable-5-1', 'claude-fable-5', 'claude-opus-5.5', 'claude-opus-5', 'claude-sonnet-5.5', 'claude-sonnet-5', 'claude-opus-4.8', 'claude-opus-4.7', 'claude-sonnet-4.6', 'claude-haiku-5.5', 'claude-haiku-4.5', 'gemini-4-argon', 'gemini-3.8-flash', 'gemini-3.7-flash', 'gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-pro-preview', 'gemini-3.1-flash-lite', 'gemini-3-flash-preview', 'grok-4.6', 'grok-4.5', 'grok-4.3', 'grok-4.20', 'grok-build-0.1', 'muse-wonder-1.0', 'muse-spark-1.3', 'muse-spark-1.2', 'muse-spark-1.1', 'muse-glimmer-30b', 'llama-4-maverick', 'llama-3.3-70b', 'deepseek-v4.1-flash', 'deepseek-v4-pro', 'deepseek-v4-flash', 'kimi-k3', 'kimi-k2.7-code', 'qwen3.8-max', 'qwen3.8-flash', 'qwen3.8-27b', 'qwen3.7-max', 'qwen3.7-plus', 'glm-5.3', 'glm-5.3-flash', 'mistral-medium-3.5', 'step-3.7-flash', 'hunyuan-4-preview', 'nemotron-3.5-lightning', 'nemotron-3-super'], defaultModel: 'deepseek-v4-pro', moreModels: 0,
    systemPrompt: 'You are DeepSeek Harness, an autonomous coding agent. You work on a real git workspace, running shell commands and editing files to complete the task end to end.',
    tools: [], skills: [] },
  { id: 'opencode', name: 'OpenCode', version: 'v1.18.23', backend: 'opencode', status: 'ready',
    // Multi-family, matching the server catalogue: opencode reaches models through the same
    // relays as pi, with the ai-sdk package chosen per turn from the model family.
    models: ['gpt-6.1-sol', 'gpt-6-astra', 'gpt-6-sol', 'gpt-6-luna', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.5', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.3-codex', 'gpt-5.2', 'claude-fable-5-1', 'claude-fable-5', 'claude-opus-5.5', 'claude-opus-5', 'claude-sonnet-5.5', 'claude-sonnet-5', 'claude-opus-4.8', 'claude-opus-4.7', 'claude-sonnet-4.6', 'claude-haiku-5.5', 'claude-haiku-4.5', 'gemini-4-argon', 'gemini-3.8-flash', 'gemini-3.7-flash', 'gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-pro-preview', 'gemini-3.1-flash-lite', 'gemini-3-flash-preview', 'grok-4.6', 'grok-4.5', 'grok-4.3', 'grok-4.20', 'grok-build-0.1', 'muse-wonder-1.0', 'muse-spark-1.3', 'muse-spark-1.2', 'muse-spark-1.1', 'muse-glimmer-30b', 'llama-4-maverick', 'llama-3.3-70b', 'deepseek-v4.1-flash', 'deepseek-v4-pro', 'deepseek-v4-flash', 'kimi-k3', 'kimi-k2.7-code', 'qwen3.8-max', 'qwen3.8-flash', 'qwen3.8-27b', 'qwen3.7-max', 'qwen3.7-plus', 'glm-5.3', 'glm-5.3-flash', 'mistral-medium-3.5', 'step-3.7-flash', 'hunyuan-4-preview', 'nemotron-3.5-lightning', 'nemotron-3-super'], defaultModel: 'gpt-6.1-sol', moreModels: 0,
    systemPrompt: 'You are OpenCode, an autonomous coding agent. You work on a real git workspace with shell and file access, reading and editing files and running commands to complete the task end to end.',
    tools: [], skills: [] },
  { id: 'kilo', name: 'Kilo Code', version: 'v7.8.1', backend: 'kilo', status: 'ready',
    // Placeholder only: the gateway's catalog wins once fetched. Kilo CLI is an opencode fork with
    // opencode's provider layer, so it is offered opencode's set; one local E2E ran on it, no
    // matrix column yet (see _MODEL_CATALOG["kilo"]).
    models: ['gpt-6.1-sol', 'gpt-6-astra', 'gpt-6-sol', 'gpt-6-luna', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.5', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.3-codex', 'gpt-5.2', 'claude-fable-5-1', 'claude-fable-5', 'claude-opus-5.5', 'claude-opus-5', 'claude-sonnet-5.5', 'claude-sonnet-5', 'claude-opus-4.8', 'claude-opus-4.7', 'claude-sonnet-4.6', 'claude-haiku-5.5', 'claude-haiku-4.5', 'gemini-4-argon', 'gemini-3.8-flash', 'gemini-3.7-flash', 'gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-pro-preview', 'gemini-3.1-flash-lite', 'gemini-3-flash-preview', 'grok-4.6', 'grok-4.5', 'grok-4.3', 'grok-4.20', 'grok-build-0.1', 'muse-wonder-1.0', 'muse-spark-1.3', 'muse-spark-1.2', 'muse-spark-1.1', 'muse-glimmer-30b', 'llama-4-maverick', 'deepseek-v4.1-flash', 'deepseek-v4-pro', 'deepseek-v4-flash', 'kimi-k3', 'kimi-k2.7-code', 'qwen3.8-max', 'qwen3.8-flash', 'qwen3.8-27b', 'qwen3.7-max', 'qwen3.7-plus', 'glm-5.3', 'glm-5.3-flash', 'mistral-medium-3.5', 'step-3.7-flash', 'hunyuan-4-preview', 'nemotron-3.5-lightning', 'nemotron-3-super'], defaultModel: 'gpt-6.1-sol', moreModels: 0,
    systemPrompt: 'You are Kilo Code, an autonomous coding agent. You work on a real git workspace with shell and file access, reading and editing files and running commands to complete the task end to end.',
    tools: [], skills: [] },
  { id: 'qwen', name: 'Qwen Code', version: 'v0.22.1', backend: 'qwen', status: 'ready',
    // Same relay reach as pi/opencode; qwen family first since it is the backend's home family.
    models: ['gpt-6.1-sol', 'gpt-6-sol', 'gpt-6-luna', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.5', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.2', 'claude-fable-5-1', 'claude-fable-5', 'claude-opus-5.5', 'claude-opus-5', 'claude-sonnet-5.5', 'claude-sonnet-5', 'claude-opus-4.8', 'claude-opus-4.7', 'claude-sonnet-4.6', 'claude-haiku-5.5', 'claude-haiku-4.5', 'gemini-4-argon', 'gemini-3.8-flash', 'gemini-3.7-flash', 'gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-pro-preview', 'gemini-3.1-flash-lite', 'gemini-3-flash-preview', 'grok-4.6', 'grok-4.5', 'grok-4.3', 'grok-4.20', 'grok-build-0.1', 'muse-wonder-1.0', 'muse-spark-1.3', 'muse-spark-1.2', 'muse-spark-1.1', 'muse-glimmer-30b', 'llama-3.3-70b', 'deepseek-v4.1-flash', 'deepseek-v4-pro', 'deepseek-v4-flash', 'kimi-k3', 'kimi-k2.7-code', 'qwen3.8-max', 'qwen3.8-flash', 'qwen3.8-27b', 'qwen3.7-max', 'qwen3.7-plus', 'glm-5.3', 'glm-5.3-flash', 'mistral-medium-3.5', 'step-3.7-flash', 'hunyuan-4-preview', 'nemotron-3.5-lightning', 'nemotron-3-super'], defaultModel: 'qwen3.7-max', moreModels: 0,
    systemPrompt: 'You are Qwen Code, an autonomous coding agent. You work on a real git workspace with shell and file access, reading and editing files and running commands to complete the task end to end.',
    tools: [], skills: [] },
  { id: 'gemini', name: 'Gemini CLI', version: 'v0.58.0', backend: 'gemini', status: 'ready',
    // Google's own native models only (Path A: Gemini API Key) — this backend has no relay
    // reach into the gpt/claude/deepseek/etc catalogs the way qwen/pi/opencode do, because it
    // speaks neither the OpenAI nor the Anthropic wire protocol. Placeholder until the gateway's
    // /v1/models catalog for this backend is populated (see gateway's _MODEL_CATALOG["gemini"]).
    // Google's own ids, each served as itself: the runner pins every id in gemini-cli's resolution table (the CLI
    // otherwise rewrites every "-flash" id to gemini-3.5-flash), and a substituted turn fails rather than completes
    models: ['gemini-4-argon', 'gemini-3.8-flash', 'gemini-3.7-flash', 'gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-pro-preview', 'gemini-3.1-flash-lite', 'gemini-3-flash-preview'], defaultModel: 'gemini-3.8-flash', moreModels: 0,
    systemPrompt: 'You are Gemini CLI, an autonomous coding agent. You work on a real git workspace with shell and file access, reading and editing files and running commands to complete the task end to end.',
    tools: [], skills: [] },
  { id: 'cline', name: 'Cline', version: 'v3.0.60', backend: 'cline', status: 'ready',
    // Placeholder only, like every list above: the gateway's catalog wins once fetched. Every
    // row completed a live substitution-checked turn through the gateway (2026-08-30 sweep).
    models: ['gpt-6.1-sol', 'gpt-6-sol', 'gpt-6-luna', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.5', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.2', 'claude-fable-5-1', 'claude-fable-5', 'claude-opus-5.5', 'claude-opus-5', 'claude-sonnet-5.5', 'claude-sonnet-5', 'claude-opus-4.8', 'claude-opus-4.7', 'claude-sonnet-4.6', 'claude-haiku-5.5', 'claude-haiku-4.5', 'gemini-4-argon', 'gemini-3.8-flash', 'gemini-3.7-flash', 'gemini-3.5-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-pro-preview', 'gemini-3.1-flash-lite', 'gemini-3-flash-preview', 'grok-4.6', 'grok-4.5', 'grok-4.3', 'grok-4.20', 'grok-build-0.1', 'muse-wonder-1.0', 'muse-spark-1.3', 'muse-spark-1.2', 'muse-spark-1.1', 'muse-glimmer-30b', 'llama-4-maverick', 'llama-3.3-70b', 'deepseek-v4.1-flash', 'deepseek-v4-pro', 'deepseek-v4-flash', 'kimi-k3', 'kimi-k2.7-code', 'qwen3.8-max', 'qwen3.8-flash', 'qwen3.8-27b', 'qwen3.7-max', 'qwen3.7-plus', 'glm-5.3', 'glm-5.3-flash', 'mistral-medium-3.5', 'step-3.7-flash', 'hunyuan-4-preview', 'nemotron-3.5-lightning', 'nemotron-3-super'], defaultModel: 'gpt-5.4', moreModels: 0,
    systemPrompt: 'You are Cline, an autonomous coding agent. You work on a real git workspace with shell and file access, reading and editing files and running commands to complete the task end to end.',
    tools: [], skills: [] },
  { id: 'omp', name: 'Oh My Pi', version: 'v18.1.13', backend: 'omp', status: 'ready',
    // pi's lineage, pi's reach: the placeholder is pi's list; the gateway's catalog wins once fetched
    models: ['gpt-6.1-sol', 'gpt-6-astra', 'gpt-6-sol', 'gpt-6-luna', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.5', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.3-codex', 'gpt-5.2', 'claude-fable-5-1', 'claude-fable-5', 'claude-opus-5.5', 'claude-opus-5', 'claude-sonnet-5.5', 'claude-sonnet-5', 'claude-opus-4.8', 'claude-opus-4.7', 'claude-sonnet-4.6', 'claude-haiku-5.5', 'claude-haiku-4.5', 'gemini-4-argon', 'gemini-3.8-flash', 'gemini-3.7-flash', 'gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-pro-preview', 'gemini-3.1-flash-lite', 'gemini-3-flash-preview', 'grok-4.6', 'grok-4.5', 'grok-4.3', 'grok-4.20', 'grok-build-0.1', 'muse-wonder-1.0', 'muse-spark-1.3', 'muse-spark-1.2', 'muse-spark-1.1', 'muse-glimmer-30b', 'llama-4-maverick', 'llama-3.3-70b', 'deepseek-v4.1-flash', 'deepseek-v4-pro', 'deepseek-v4-flash', 'kimi-k3', 'kimi-k2.7-code', 'qwen3.8-max', 'qwen3.8-flash', 'qwen3.8-27b', 'qwen3.7-max', 'qwen3.7-plus', 'glm-5.3', 'glm-5.3-flash', 'mistral-medium-3.5', 'step-3.7-flash', 'hunyuan-4-preview', 'nemotron-3.5-lightning', 'nemotron-3-super'], defaultModel: 'gpt-6.1-sol', moreModels: 0,
    systemPrompt: 'You are Oh My Pi (OMP), an autonomous coding agent. You operate on a real git workspace with shell, file access, LSP, web search, and subagents to complete engineering tasks end to end.',
    tools: [], skills: [] },
  { id: 'goose', name: 'goose', version: 'v1.50.0', backend: 'goose', status: 'ready',
    // Placeholder only, like every list above: the gateway's catalog wins once fetched. It started
    // short — inheriting cline's serving path is not a completed turn — and grew to what the goose
    // column measured on 2026-09-12 across seven providers, substitution-checked with the served
    // model the relay reads off the provider's own answer. The last five are not yet measured;
    // see the gateway's _MODEL_CATALOG["goose"], which says which are which.
    models: ['gpt-6.1-sol', 'gpt-6-sol', 'gpt-6-luna', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.5', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.2', 'claude-fable-5-1', 'claude-fable-5', 'claude-sonnet-5.5', 'claude-sonnet-5', 'claude-opus-4.8', 'claude-opus-4.7', 'claude-sonnet-4.6', 'claude-haiku-5.5', 'claude-haiku-4.5', 'gemini-4-argon', 'gemini-3.8-flash', 'gemini-3.7-flash', 'gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-pro-preview', 'gemini-3.1-flash-lite', 'gemini-3-flash-preview', 'grok-4.6', 'grok-4.5', 'grok-4.3', 'grok-4.20', 'grok-build-0.1', 'muse-wonder-1.0', 'muse-spark-1.3', 'muse-spark-1.2', 'muse-spark-1.1', 'muse-glimmer-30b', 'llama-4-maverick', 'deepseek-v4.1-flash', 'deepseek-v4-pro', 'deepseek-v4-flash', 'kimi-k3', 'kimi-k2.7-code', 'qwen3.8-max', 'qwen3.8-flash', 'qwen3.8-27b', 'qwen3.7-max', 'qwen3.7-plus', 'qwen3.7-flash', 'glm-5.3', 'glm-5.3-flash', 'mistral-medium-3.5', 'step-3.7-flash', 'hunyuan-4-preview', 'hunyuan-3', 'minimax-m3', 'nemotron-3.5-lightning', 'nemotron-3-ultra', 'nemotron-3-super', 'ling-3.0-flash'], defaultModel: 'gpt-6.1-sol', moreModels: 0,
    systemPrompt: 'You are goose, an autonomous coding agent. You work on a real git workspace with shell and file access, reading and editing files and running commands to complete the task end to end.',
    tools: [], skills: [] },
  { id: 'kimi', name: 'Kimi Code CLI', version: 'v2.0.0', backend: 'kimi', status: 'ready',
    // Placeholder only, like every list above: the gateway's catalog wins once fetched. Every id was
    // measured on Kimi Code CLI 2.0.0 (five console scenarios, 248 of 250); the gateway's
    // _MODEL_CATALOG["kimi"] and docs/support-matrix-notes.md carry the record.
    models: ['gpt-6.1-sol', 'gpt-6-sol', 'gpt-6-luna', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.5', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.2', 'claude-fable-5-1', 'claude-fable-5', 'claude-opus-5.5', 'claude-opus-5', 'claude-sonnet-5.5', 'claude-sonnet-5', 'claude-opus-4.8', 'claude-opus-4.7', 'claude-sonnet-4.6', 'claude-haiku-5.5', 'claude-haiku-4.5', 'gemini-4-argon', 'gemini-3.8-flash', 'gemini-3.7-flash', 'gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-pro-preview', 'gemini-3.1-flash-lite', 'gemini-3-flash-preview', 'grok-4.6', 'grok-4.5', 'grok-4.3', 'grok-4.20', 'grok-build-0.1', 'muse-wonder-1.0', 'muse-spark-1.3', 'muse-spark-1.2', 'muse-spark-1.1', 'muse-glimmer-30b', 'llama-3.3-70b', 'deepseek-v4.1-flash', 'deepseek-v4-pro', 'deepseek-v4-flash', 'kimi-k3', 'kimi-k2.7-code', 'qwen3.8-max', 'qwen3.8-flash', 'qwen3.8-27b', 'qwen3.7-max', 'qwen3.7-plus', 'glm-5.3', 'glm-5.3-flash', 'mistral-medium-3.5', 'step-3.7-flash', 'hunyuan-4-preview', 'nemotron-3.5-lightning', 'nemotron-3-super'], defaultModel: 'kimi-k3', moreModels: 0,
    systemPrompt: 'You are Kimi Code CLI, an autonomous coding agent. You work on a real git workspace with shell and file access, reading and editing files and running commands to complete the task end to end.',
    tools: [], skills: [] },
  { id: 'minimax', name: 'MiniMax Code', version: 'v0.5.4', backend: 'minimax', status: 'ready',
    // Placeholder only: the gateway's catalog wins once fetched. MiniMax's own model first and the
    // default; the rest is kimi's relay reach, offered so the matrix can measure it on this base (no
    // minimax column has run yet). _MODEL_CATALOG["minimax"] says which ids were measured.
    models: ['gpt-6.1-sol', 'gpt-6-sol', 'gpt-6-luna', 'gpt-5.6-sol', 'gpt-5.6-luna', 'gpt-5.5', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.2', 'claude-fable-5-1', 'claude-fable-5', 'claude-opus-5.5', 'claude-opus-5', 'claude-sonnet-5.5', 'claude-sonnet-5', 'claude-opus-4.8', 'claude-opus-4.7', 'claude-sonnet-4.6', 'claude-haiku-5.5', 'claude-haiku-4.5', 'gemini-4-argon', 'gemini-3.8-flash', 'gemini-3.7-flash', 'gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-3.1-pro-preview', 'gemini-3.1-flash-lite', 'gemini-3-flash-preview', 'grok-4.6', 'grok-4.5', 'grok-4.3', 'grok-4.20', 'grok-build-0.1', 'muse-wonder-1.0', 'muse-spark-1.3', 'muse-spark-1.2', 'muse-spark-1.1', 'muse-glimmer-30b', 'llama-3.3-70b', 'deepseek-v4.1-flash', 'deepseek-v4-pro', 'deepseek-v4-flash', 'kimi-k3', 'kimi-k2.7-code', 'qwen3.8-max', 'qwen3.8-flash', 'qwen3.8-27b', 'qwen3.7-max', 'qwen3.7-plus', 'glm-5.3', 'glm-5.3-flash', 'mistral-medium-3.5', 'step-3.7-flash', 'hunyuan-4-preview', 'minimax-m3.1-flash', 'minimax-m3', 'nemotron-3.5-lightning', 'nemotron-3-super'], defaultModel: 'minimax-m3', moreModels: 0,
    systemPrompt: 'You are MiniMax Code, an autonomous coding agent. You work on a real git workspace with shell and file access, reading and editing files and running commands to complete the task end to end.',
    tools: [], skills: [] },
  { id: 'aider', name: 'Aider', version: 'v0.86.2', backend: 'aider', status: 'ready',
    // Placeholder only: the gateway's catalog wins once fetched. Two columns ran on this backend
    // (vercel 52 ids, google 11); three of those ids were the Gemini 2.5 family, retired from the
    // catalog since (#196). _MODEL_CATALOG["aider"] carries what they measured.
    models: ['gpt-6.1-sol', 'gpt-6-sol', 'gpt-6-luna', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.5', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.2', 'claude-fable-5-1', 'claude-fable-5', 'claude-opus-5.5', 'claude-opus-5', 'claude-sonnet-5.5', 'claude-sonnet-5', 'claude-opus-4.8', 'claude-opus-4.7', 'claude-sonnet-4.6', 'claude-haiku-4.5', 'gemini-4-argon', 'gemini-3.8-flash', 'gemini-3.7-flash', 'gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-pro-preview', 'gemini-3.1-flash-lite', 'gemini-3-flash-preview', 'grok-4.6', 'grok-4.5', 'grok-4.3', 'grok-4.20', 'grok-build-0.1', 'muse-spark-1.3', 'muse-spark-1.2', 'muse-spark-1.1', 'muse-glimmer-30b', 'llama-3.3-70b', 'deepseek-v4.1-flash', 'deepseek-v4-pro', 'deepseek-v4-flash', 'kimi-k3', 'kimi-k2.7-code', 'qwen3.8-max', 'qwen3.8-flash', 'qwen3.8-27b', 'qwen3.7-max', 'qwen3.7-plus', 'glm-5.3', 'glm-5.3-flash', 'mistral-medium-3.5', 'step-3.7-flash', 'hunyuan-4-preview', 'nemotron-3.5-lightning', 'nemotron-3-super'], defaultModel: 'gpt-6.1-sol', moreModels: 0,
    systemPrompt: 'You are Aider, an autonomous coding agent. You work on a real git workspace, editing files and proposing shell commands to complete the task end to end.',
    tools: [], skills: [] },
  { id: 'openhands', name: 'OpenHands', version: 'v1.49.2', backend: 'openhands', status: 'ready',
    // Placeholder only, like every list above: the gateway's catalog wins once fetched. Measured
    // on openhands-agent-server 1.49.2, five console scenarios per id: Vercel 239 of 245 over 49
    // of these, Google 40 of 40 over the eight gemini ids; the gateway's _MODEL_CATALOG["openhands"]
    // and docs/support-matrix-notes.md carry the record.
    models: ['gpt-6.1-sol', 'gpt-6-sol', 'gpt-6-luna', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.5', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.2', 'claude-fable-5-1', 'claude-fable-5', 'claude-opus-5.5', 'claude-opus-5', 'claude-sonnet-5.5', 'claude-sonnet-5', 'claude-opus-4.8', 'claude-opus-4.7', 'claude-sonnet-4.6', 'claude-haiku-5.5', 'claude-haiku-4.5', 'gemini-4-argon', 'gemini-3.8-flash', 'gemini-3.7-flash', 'gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-pro-preview', 'gemini-3.1-flash-lite', 'gemini-3-flash-preview', 'grok-4.6', 'grok-4.5', 'grok-4.3', 'grok-4.20', 'grok-build-0.1', 'muse-spark-1.3', 'muse-spark-1.2', 'muse-spark-1.1', 'muse-glimmer-30b', 'llama-3.3-70b', 'deepseek-v4.1-flash', 'deepseek-v4-pro', 'deepseek-v4-flash', 'kimi-k3', 'kimi-k2.7-code', 'qwen3.8-max', 'qwen3.8-flash', 'qwen3.8-27b', 'qwen3.7-max', 'qwen3.7-plus', 'glm-5.3', 'glm-5.3-flash', 'mistral-medium-3.5', 'step-3.7-flash', 'hunyuan-4-preview', 'nemotron-3.5-lightning', 'nemotron-3-super'], defaultModel: 'gpt-5.4', moreModels: 0,
    systemPrompt: 'You are OpenHands, an autonomous coding agent. You work on a real git workspace with shell and file access, reading and editing files and running commands to complete the task end to end.',
    tools: [], skills: [] },
  { id: 'cheetahclaws', name: 'CheetahClaws', version: 'v3.5.88', backend: 'cheetahclaws', status: 'ready',
    // Placeholder only, like every list above: the gateway's catalog wins once fetched. The list is
    // the other chat-completions bases' (same relay reach); _MODEL_CATALOG["cheetahclaws"] says what
    // has and has not been measured on it.
    models: ['gpt-6.1-sol', 'gpt-6-sol', 'gpt-6-luna', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.5', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.2', 'claude-fable-5-1', 'claude-fable-5', 'claude-opus-5.5', 'claude-opus-5', 'claude-sonnet-5.5', 'claude-sonnet-5', 'claude-opus-4.8', 'claude-opus-4.7', 'claude-sonnet-4.6', 'claude-haiku-5.5', 'claude-haiku-4.5', 'gemini-4-argon', 'gemini-3.8-flash', 'gemini-3.7-flash', 'gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-pro-preview', 'gemini-3.1-flash-lite', 'gemini-3-flash-preview', 'grok-4.6', 'grok-4.5', 'grok-4.3', 'grok-4.20', 'grok-build-0.1', 'muse-glimmer-30b', 'llama-3.3-70b', 'deepseek-v4.1-flash', 'deepseek-v4-pro', 'deepseek-v4-flash', 'kimi-k3', 'kimi-k2.7-code', 'qwen3.8-max', 'qwen3.8-flash', 'qwen3.8-27b', 'qwen3.7-max', 'qwen3.7-plus', 'glm-5.3', 'glm-5.3-flash', 'mistral-medium-3.5', 'step-3.7-flash', 'hunyuan-4-preview', 'nemotron-3.5-lightning', 'nemotron-3-super'], defaultModel: 'gpt-5.4', moreModels: 0,
    systemPrompt: 'You are CheetahClaws, an autonomous coding agent. You work on a real git workspace with shell and file access, reading and editing files and running commands to complete the task end to end.',
    tools: [], skills: [] },
  { id: 'grok', name: 'Grok Build', version: 'v1.0.41', backend: 'grok', status: 'ready',
    // Placeholder only: the gateway's catalog wins once fetched. Grok Build drives any
    // chat/completions endpoint through the runner's relay, so its list is kimi's, xAI's family
    // included. OFFERED, NOT YET MEASURED: no column has run on this base (_MODEL_CATALOG["grok"]).
    models: ['gpt-6.1-sol', 'gpt-6-sol', 'gpt-6-luna', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.5', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.2', 'claude-fable-5-1', 'claude-fable-5', 'claude-opus-5.5', 'claude-opus-5', 'claude-sonnet-5.5', 'claude-sonnet-5', 'claude-opus-4.8', 'claude-opus-4.7', 'claude-sonnet-4.6', 'claude-haiku-5.5', 'claude-haiku-4.5', 'gemini-4-argon', 'gemini-3.8-flash', 'gemini-3.7-flash', 'gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-pro-preview', 'gemini-3.1-flash-lite', 'gemini-3-flash-preview', 'grok-4.6', 'grok-4.5', 'grok-4.3', 'grok-4.20', 'grok-build-0.1', 'muse-wonder-1.0', 'muse-spark-1.3', 'muse-spark-1.2', 'muse-spark-1.1', 'muse-glimmer-30b', 'llama-3.3-70b', 'deepseek-v4.1-flash', 'deepseek-v4-flash', 'kimi-k3', 'kimi-k2.7-code', 'qwen3.8-max', 'qwen3.8-flash', 'qwen3.8-27b', 'qwen3.7-max', 'qwen3.7-plus', 'glm-5.3', 'glm-5.3-flash', 'mistral-medium-3.5', 'step-3.7-flash', 'hunyuan-4-preview', 'nemotron-3.5-lightning', 'nemotron-3-super'], defaultModel: 'grok-4.6', moreModels: 0,
    systemPrompt: 'You are Grok Build, an autonomous coding agent. You work on a real git workspace with shell and file access, reading and editing files and running commands to complete the task end to end.',
    tools: [], skills: [] },
  { id: 'agentzero', name: 'Agent Zero', version: 'v2.13', backend: 'agentzero', status: 'ready',
    // Placeholder only: the gateway's catalog wins once fetched. openhands' list, because the relay
    // reach is the same (litellm's openai provider through the loopback relay). NOT yet measured on
    // this base: no support-matrix column has run; _MODEL_CATALOG["agentzero"] says so at the ids.
    models: ['gpt-6.1-sol', 'gpt-6-sol', 'gpt-6-luna', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.5', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.2', 'claude-opus-5.5', 'claude-opus-5', 'claude-sonnet-5.5', 'claude-sonnet-5', 'claude-opus-4.8', 'claude-opus-4.7', 'claude-sonnet-4.6', 'claude-haiku-5.5', 'claude-haiku-4.5', 'gemini-4-argon', 'gemini-3.8-flash', 'gemini-3.7-flash', 'gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-pro-preview', 'gemini-3.1-flash-lite', 'gemini-3-flash-preview', 'grok-4.6', 'grok-4.5', 'grok-4.3', 'grok-4.20', 'grok-build-0.1', 'muse-spark-1.3', 'muse-spark-1.2', 'muse-spark-1.1', 'muse-glimmer-30b', 'llama-3.3-70b', 'deepseek-v4.1-flash', 'deepseek-v4-pro', 'deepseek-v4-flash', 'kimi-k3', 'kimi-k2.7-code', 'qwen3.8-max', 'qwen3.8-flash', 'qwen3.8-27b', 'qwen3.7-max', 'qwen3.7-plus', 'glm-5.3', 'glm-5.3-flash', 'mistral-medium-3.5', 'step-3.7-flash', 'hunyuan-4-preview', 'nemotron-3.5-lightning', 'nemotron-3-super'], defaultModel: 'gpt-6.1-sol', moreModels: 0,
    systemPrompt: 'You are Agent Zero, an autonomous agent. You work on a real git workspace with a terminal and file tools, running commands and editing files to complete the task end to end.',
    tools: [], skills: [] },
  { id: 'systemone', name: 'System One', version: 'v0.4.0', backend: 'systemone', status: 'ready',
    // Placeholder only: the gateway's catalog wins once fetched. Jev, a decision model, under the
    // ids its two providers serve: jev-latest on both (the default), jev-preview on TypeSafe's own
    // API, jev-1.13 on OpenRouter; then the three open-weight models a HarnessRouter key serves
    // (laya, openthai-systemone, system-one-phase2). The composer resolves a harness's saved default
    // against THIS list before the catalog arrives, so an id missing here is silently swapped for
    // jev-latest: a harness saved on laya ran on Jev (hr-test, 2026-09-24). There is no chat model
    // on this base because the loop asks typed questions a text model cannot answer.
    models: ['jev-latest', 'jev-preview', 'jev-1.13', 'laya', 'openthai-systemone', 'system-one-phase2'], defaultModel: 'jev-latest', moreModels: 0,
    systemPrompt: 'You act inside a finite set of actions the environment offers each step. Choose the action that moves the goal forward, finish when the goal is reached, and escalate when nothing offered fits.',
    tools: [], skills: [] },
  { id: 'qoder', name: 'Qoder Cloud Agent', version: 'Managed API', backend: 'qoder', status: 'ready',
    // Placeholder only: the gateway's catalog wins once fetched. Qoder's own model ids, as its
    // GET /models lists them for the tenant; the runtime is Qoder's cloud, not a process on this
    // box, and Qoder picks and bills the model behind an id.
    models: ['auto', 'ultimate', 'performance', 'smodel', 'qmodel_38max', 'qmodel', 'kmodel_latest', 'gmodel', 'gfmodel', 'dmodel', 'dfmodel', 'mmodel'], defaultModel: 'ultimate', moreModels: 0,
    systemPrompt: 'You are Qoder, an autonomous coding agent running in a cloud sandbox with shell and file access. Read, edit and run what the task needs, and deliver every file the user should receive with DeliverArtifacts.',
    tools: ['Bash', 'Read', 'Write', 'Edit', 'Glob', 'Grep', 'WebFetch', 'WebSearch', 'ImageSearch', 'ImageGen', 'DeliverArtifacts'], skills: [] },
  { id: 'mimo', name: 'MiMo Code', version: 'v0.1.15', backend: 'mimo', status: 'ready',
    // Placeholder only, like every list above: the gateway's catalog wins once fetched. MiMo Code is
    // an opencode fork and reaches what opencode reaches, so the list is opencode's.
    models: ['gpt-6.1-sol', 'gpt-6-astra', 'gpt-6-sol', 'gpt-6-luna', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.5', 'gpt-5.4', 'gpt-5.3-codex', 'gpt-5.2', 'claude-fable-5-1', 'claude-fable-5', 'claude-opus-5.5', 'claude-opus-5', 'claude-sonnet-5.5', 'claude-sonnet-5', 'claude-opus-4.8', 'claude-sonnet-4.6', 'claude-haiku-5.5', 'claude-haiku-4.5', 'gemini-4-argon', 'gemini-3.8-flash', 'gemini-3.7-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-pro-preview', 'gemini-3.1-flash-lite', 'gemini-3-flash-preview', 'grok-4.6', 'grok-4.5', 'grok-4.3', 'grok-4.20', 'grok-build-0.1', 'muse-wonder-1.0', 'muse-spark-1.3', 'muse-spark-1.2', 'muse-spark-1.1', 'muse-glimmer-30b', 'deepseek-v4.1-flash', 'deepseek-v4-pro', 'deepseek-v4-flash', 'kimi-k2.7-code', 'qwen3.8-max', 'qwen3.8-27b', 'qwen3.7-max', 'qwen3.7-plus', 'glm-5.3', 'glm-5.3-flash', 'step-3.7-flash', 'nemotron-3.5-lightning'], defaultModel: 'gpt-6.1-sol', moreModels: 0,
    systemPrompt: 'You are MiMo Code, an autonomous coding agent. You work on a real git workspace with shell and file access, reading and editing files and running commands to complete the task end to end.',
    tools: [], skills: [] },
  { id: 'jcode', name: 'jcode', version: 'v0.90.0', backend: 'jcode', status: 'ready',
    // Placeholder only. jcode speaks one OpenAI shape, chat/completions, through the relay, so the
    // list is the other chat-completions bases' and the two Responses-only ids are not on it.
    models: ['gpt-6.1-sol', 'gpt-6-sol', 'gpt-6-luna', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.5', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.2', 'claude-fable-5-1', 'claude-fable-5', 'claude-opus-5.5', 'claude-opus-5', 'claude-sonnet-5.5', 'claude-sonnet-5', 'claude-opus-4.8', 'claude-opus-4.7', 'claude-sonnet-4.6', 'claude-haiku-5.5', 'claude-haiku-4.5', 'gemini-4-argon', 'gemini-3.8-flash', 'gemini-3.7-flash', 'gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-pro-preview', 'gemini-3.1-flash-lite', 'grok-4.6', 'grok-4.5', 'grok-4.3', 'grok-4.20', 'muse-wonder-1.0', 'muse-spark-1.3', 'muse-spark-1.2', 'deepseek-v4.1-flash', 'deepseek-v4-pro', 'deepseek-v4-flash', 'kimi-k2.7-code', 'qwen3.8-max', 'qwen3.8-flash', 'qwen3.8-27b', 'qwen3.7-max', 'qwen3.7-plus', 'glm-5.3', 'glm-5.3-flash', 'mistral-medium-3.5', 'step-3.7-flash', 'nemotron-3.5-lightning'], defaultModel: 'gpt-5.4', moreModels: 0,
    systemPrompt: 'You are jcode, an autonomous coding agent. You work on a real git workspace with shell and file access, reading and editing files and running commands to complete the task end to end.',
    tools: [], skills: [] },
  { id: 'opensquilla', name: 'OpenSquilla', version: 'v0.5.6', backend: 'opensquilla', status: 'ready',
    // Placeholder only; the chat-completions list, for jcode's reason.
    models: ['gpt-6-sol', 'gpt-6-luna', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.5', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.2', 'claude-fable-5-1', 'claude-fable-5', 'claude-opus-5.5', 'claude-opus-5', 'claude-sonnet-5.5', 'claude-sonnet-5', 'claude-opus-4.8', 'claude-sonnet-4.6', 'claude-haiku-5.5', 'claude-haiku-4.5', 'gemini-4-argon', 'gemini-3.8-flash', 'gemini-3.7-flash', 'gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-pro-preview', 'gemini-3.1-flash-lite', 'gemini-3-flash-preview', 'grok-4.6', 'grok-4.5', 'grok-4.3', 'grok-build-0.1', 'muse-wonder-1.0', 'muse-spark-1.3', 'muse-spark-1.2', 'muse-spark-1.1', 'muse-glimmer-30b', 'deepseek-v4.1-flash', 'deepseek-v4-pro', 'deepseek-v4-flash', 'kimi-k3', 'kimi-k2.7-code', 'qwen3.8-max', 'qwen3.8-flash', 'qwen3.8-27b', 'qwen3.7-max', 'qwen3.7-plus', 'glm-5.3', 'glm-5.3-flash', 'mistral-medium-3.5', 'step-3.7-flash', 'nemotron-3.5-lightning'], defaultModel: 'gpt-5.4', moreModels: 0,
    systemPrompt: 'You are OpenSquilla, an autonomous agent. You work on a real git workspace with shell and file access, reading and editing files and running commands to complete the task end to end.',
    tools: [], skills: [] },
  { id: 'nanobot', name: 'nanobot', version: 'v0.3.5', backend: 'nanobot', status: 'ready',
    // Placeholder only; the chat-completions list, for jcode's reason.
    models: ['gpt-6.1-sol', 'gpt-6-sol', 'gpt-6-luna', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.5', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.2', 'claude-fable-5-1', 'claude-fable-5', 'claude-opus-5.5', 'claude-opus-5', 'claude-sonnet-5.5', 'claude-sonnet-5', 'claude-opus-4.8', 'claude-opus-4.7', 'claude-sonnet-4.6', 'claude-haiku-5.5', 'claude-haiku-4.5', 'gemini-4-argon', 'gemini-3.8-flash', 'gemini-3.7-flash', 'gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-pro-preview', 'gemini-3.1-flash-lite', 'gemini-3-flash-preview', 'grok-4.6', 'grok-4.3', 'grok-4.20', 'muse-wonder-1.0', 'muse-spark-1.3', 'muse-spark-1.2', 'muse-spark-1.1', 'muse-glimmer-30b', 'deepseek-v4.1-flash', 'deepseek-v4-pro', 'deepseek-v4-flash', 'kimi-k2.7-code', 'qwen3.8-max', 'qwen3.8-flash', 'qwen3.8-27b', 'qwen3.7-max', 'qwen3.7-plus', 'glm-5.3', 'glm-5.3-flash', 'mistral-medium-3.5', 'step-3.7-flash', 'hunyuan-4-preview', 'nemotron-3.5-lightning'], defaultModel: 'gpt-5.4', moreModels: 0,
    systemPrompt: 'You are nanobot, an autonomous agent. You work on a real git workspace with shell and file access, reading and editing files and running commands to complete the task end to end.',
    tools: [], skills: [] },
  { id: 'zeroclaw', name: 'ZeroClaw', version: 'v0.8.5', backend: 'zeroclaw', status: 'ready',
    // Placeholder only; the chat-completions list, for jcode's reason.
    models: ['gpt-6.1-sol', 'gpt-6-sol', 'gpt-6-luna', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.5', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.2', 'claude-fable-5-1', 'claude-fable-5', 'claude-opus-5.5', 'claude-opus-5', 'claude-sonnet-5.5', 'claude-sonnet-5', 'claude-opus-4.8', 'claude-opus-4.7', 'claude-sonnet-4.6', 'claude-haiku-5.5', 'claude-haiku-4.5', 'gemini-4-argon', 'gemini-3.8-flash', 'gemini-3.7-flash', 'gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-pro-preview', 'gemini-3.1-flash-lite', 'gemini-3-flash-preview', 'grok-4.6', 'grok-4.5', 'grok-4.3', 'grok-build-0.1', 'muse-wonder-1.0', 'muse-spark-1.3', 'muse-spark-1.2', 'muse-spark-1.1', 'muse-glimmer-30b', 'deepseek-v4.1-flash', 'deepseek-v4-pro', 'deepseek-v4-flash', 'kimi-k3', 'kimi-k2.7-code', 'qwen3.8-max', 'qwen3.8-27b', 'qwen3.7-max', 'qwen3.7-plus', 'glm-5.3', 'glm-5.3-flash', 'mistral-medium-3.5', 'step-3.7-flash', 'hunyuan-4-preview', 'nemotron-3.5-lightning'], defaultModel: 'gpt-5.4', moreModels: 0,
    systemPrompt: 'You are ZeroClaw, an autonomous agent. You work on a real git workspace with shell and file access, reading and editing files and running commands to complete the task end to end.',
    tools: [], skills: [] },
  { id: 'vibe', name: 'Mistral Vibe', version: 'v3.0.2', backend: 'vibe', status: 'ready',
    // Placeholder only; the chat-completions list, for jcode's reason.
    models: ['gpt-6.1-sol', 'gpt-6-sol', 'gpt-6-luna', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.5', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.2', 'claude-fable-5-1', 'claude-fable-5', 'claude-opus-5.5', 'claude-opus-5', 'claude-sonnet-5.5', 'claude-sonnet-5', 'claude-opus-4.8', 'claude-sonnet-4.6', 'claude-haiku-5.5', 'claude-haiku-4.5', 'gemini-4-argon', 'gemini-3.8-flash', 'gemini-3.7-flash', 'gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-pro-preview', 'gemini-3.1-flash-lite', 'gemini-3-flash-preview', 'grok-4.6', 'grok-4.5', 'grok-4.3', 'grok-4.20', 'grok-build-0.1', 'muse-wonder-1.0', 'muse-spark-1.3', 'muse-spark-1.2', 'muse-spark-1.1', 'muse-glimmer-30b', 'deepseek-v4-pro', 'deepseek-v4-flash', 'kimi-k3', 'kimi-k2.7-code', 'qwen3.8-max', 'qwen3.8-flash', 'qwen3.8-27b', 'qwen3.7-max', 'qwen3.7-plus', 'glm-5.3', 'glm-5.3-flash', 'mistral-medium-3.5', 'step-3.7-flash', 'hunyuan-4-preview', 'nemotron-3.5-lightning', 'nemotron-3-super'], defaultModel: 'gpt-5.4', moreModels: 0,
    systemPrompt: 'You are Vibe, an autonomous coding agent. You work on a real git workspace with shell and file access, reading and editing files and running commands to complete the task end to end.',
    tools: [], skills: [] },
  { id: 'docker-agent', name: 'Docker Agent', version: 'v1.152.0', backend: 'docker-agent', status: 'ready',
    // Placeholder only; the chat-completions list, for jcode's reason.
    models: ['gpt-6.1-sol', 'gpt-6-sol', 'gpt-6-luna', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.5', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.2', 'claude-fable-5-1', 'claude-fable-5', 'claude-opus-5.5', 'claude-opus-5', 'claude-sonnet-5.5', 'claude-sonnet-5', 'claude-opus-4.8', 'claude-sonnet-4.6', 'claude-haiku-5.5', 'claude-haiku-4.5', 'gemini-4-argon', 'gemini-3.8-flash', 'gemini-3.7-flash', 'gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-pro-preview', 'gemini-3.1-flash-lite', 'gemini-3-flash-preview', 'grok-4.6', 'grok-4.3', 'muse-wonder-1.0', 'muse-spark-1.3', 'muse-spark-1.2', 'muse-spark-1.1', 'muse-glimmer-30b', 'deepseek-v4.1-flash', 'deepseek-v4-pro', 'deepseek-v4-flash', 'kimi-k3', 'kimi-k2.7-code', 'qwen3.8-max', 'qwen3.8-flash', 'qwen3.8-27b', 'qwen3.7-max', 'qwen3.7-plus', 'glm-5.3', 'glm-5.3-flash', 'mistral-medium-3.5', 'step-3.7-flash', 'hunyuan-4-preview', 'nemotron-3-super'], defaultModel: 'gpt-5.4', moreModels: 0,
    systemPrompt: 'You are an autonomous coding agent working in a real git workspace with shell and file access, reading and editing files and running commands to complete the task end to end.',
    tools: [], skills: [] },
  { id: 'fast-agent', name: 'fast-agent', version: 'v0.10.47', backend: 'fast-agent', status: 'ready',
    // Placeholder only; the chat-completions list, for jcode's reason.
    models: ['gpt-6.1-sol', 'gpt-6-sol', 'gpt-6-luna', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.5', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.2', 'claude-fable-5-1', 'claude-fable-5', 'claude-opus-5.5', 'claude-opus-5', 'claude-sonnet-5.5', 'claude-sonnet-5', 'claude-opus-4.8', 'claude-opus-4.7', 'claude-sonnet-4.6', 'claude-haiku-5.5', 'claude-haiku-4.5', 'gemini-3.8-flash', 'gemini-3.7-flash', 'gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-pro-preview', 'gemini-3.1-flash-lite', 'gemini-3-flash-preview', 'grok-4.6', 'grok-4.3', 'grok-4.20', 'grok-build-0.1', 'muse-wonder-1.0', 'muse-spark-1.3', 'muse-spark-1.2', 'muse-spark-1.1', 'muse-glimmer-30b', 'deepseek-v4.1-flash', 'deepseek-v4-pro', 'deepseek-v4-flash', 'kimi-k3', 'qwen3.8-flash', 'qwen3.7-max', 'qwen3.7-plus', 'glm-5.3', 'glm-5.3-flash', 'mistral-medium-3.5', 'step-3.7-flash'], defaultModel: 'gpt-5.4', moreModels: 0,
    systemPrompt: 'You are an autonomous coding agent. You work on a real git workspace with shell and file access, reading and editing files and running commands to complete the task end to end.',
    tools: [], skills: [] },
  { id: 'dcode', name: 'Deep Agents Code', version: 'v0.2.1', backend: 'dcode', status: 'ready',
    // Placeholder only; the same list the gateway gives it. Unlike the other four this
    // base drives the Responses API, which is about the wire and not about these ids.
    models: ['gpt-6.1-sol', 'gpt-6-sol', 'gpt-6-luna', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.5', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.2', 'claude-fable-5-1', 'claude-fable-5', 'claude-opus-5.5', 'claude-opus-5', 'claude-sonnet-5.5', 'claude-sonnet-5', 'claude-opus-4.8', 'claude-opus-4.7', 'claude-sonnet-4.6', 'claude-haiku-5.5', 'claude-haiku-4.5', 'gemini-4-argon', 'gemini-3.8-flash', 'gemini-3.7-flash', 'gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-pro-preview', 'gemini-3.1-flash-lite', 'gemini-3-flash-preview', 'grok-4.6', 'grok-4.3', 'grok-4.20', 'grok-build-0.1', 'muse-wonder-1.0', 'muse-spark-1.3', 'muse-spark-1.2', 'deepseek-v4.1-flash', 'deepseek-v4-pro', 'deepseek-v4-flash', 'kimi-k3', 'qwen3.8-max', 'qwen3.8-flash', 'qwen3.8-27b', 'qwen3.7-max', 'qwen3.7-plus', 'glm-5.3', 'glm-5.3-flash', 'mistral-medium-3.5', 'step-3.7-flash', 'nemotron-3-super'], defaultModel: 'gpt-6.1-sol', moreModels: 0,
    systemPrompt: 'You are Deep Agents Code, an autonomous coding agent. You work on a real git workspace with shell and file access, reading and editing files and running commands to complete the task end to end.',
    tools: [], skills: [] },
];

/** The built-in harnesses a person can pick: the ones the server's bases document lists. None until
 *  it has been read (useBasesRead says whether it could be). */
export function offeredOob(bases: Record<string, BaseInfo> | null): OobHarness[] {
  return OOB.filter((o) => o.status === 'ready' && !!bases?.[o.id]);
}

export const oobById = (id: string) => OOB.find((o) => o.id === id) || null;

// ── model catalog: the GATEWAY owns it, this file does not ────────────────────────────
// The `models` / `defaultModel` fields above are the pre-fetch placeholder only (so first paint
// isn't empty). The catalog is fetched from GET /v1/models and cached for the tab; once it lands
// the server's list wins everywhere. Never add a model here: add it to _MODEL_CATALOG in the
// gateway and it shows up everywhere (and the gateway's tests ask for it here too).
export type ModelCatalog = Record<string, {
  default: string;
  models: string[];
  /** Models the server has no provider configured for. Offering one is a promise the router
   *  then breaks — the picker accepts it and the turn fails at the point of no return. */
  unavailable: string[];
}>;

let _catalog: ModelCatalog | null = null;
let _catalogInflight: Promise<ModelCatalog> | null = null;

export async function fetchModelCatalog(): Promise<ModelCatalog> {
  if (_catalog) return _catalog;
  if (_catalogInflight) return _catalogInflight;
  _catalogInflight = (async () => {
    // A few tries, not one: the first paint of a tab races this read, and one failed read used
    // to leave the placeholder standing in for the server for the life of the tab.
    for (const wait of [0, 1500, 3000, 6000]) {
      if (wait) await new Promise((r) => setTimeout(r, wait));
      try {
        const r = await harnessFetch('/api/harness/v1/models', { headers: gwHeaders(), cache: 'no-store' });
        if (!r.ok) throw new Error(String(r.status));
        const j = await r.json();
        const out: ModelCatalog = {};
        for (const [backend, c] of Object.entries((j?.backends || {}) as Record<string, {
          default?: string; models?: Array<{ id?: string; available?: boolean }> }>)) {
          const rows = (c?.models || []).filter((m) => m?.id);
          out[backend] = {
            default: String(c?.default || ''),
            models: rows.map((m) => String(m.id)),
            unavailable: rows.filter((m) => m.available === false).map((m) => String(m.id)),
          };
        }
        if (Object.keys(out).length) { _catalog = out; break; }
      } catch {
        // try again; the placeholder keeps painting meanwhile, with nothing offered as runnable
      }
    }
    _catalogInflight = null;
    return _catalog || {};
  })();
  return _catalogInflight;
}

/** Models for a base harness: the server catalog once loaded, the placeholder literals until then. */
export const oobModels = (o: OobHarness | null | undefined): string[] => {
  if (!o) return [];
  const fromServer = o.backend ? _catalog?.[o.backend]?.models : undefined;
  return (fromServer && fromServer.length) ? fromServer : o.models;
};

/** The base's default model: the server catalog's once loaded, else the placeholder's. Never the
 *  first entry of the list (2026-09-27: Oh My Pi opened on gpt-6-astra that way). */
export const oobDefaultModel = (o: OobHarness | null | undefined): string => {
  if (!o) return '';
  const fromServer = o.backend ? _catalog?.[o.backend]?.default : '';
  return fromServer || o.defaultModel || '';
};

/** Whether this backend can run this model, as three answers rather than two. "unknown" is the
 *  state before the server's catalog has arrived (or while every read of it has failed), and it
 *  is not "yes": the picker used to treat it that way, offering the placeholder list as runnable
 *  for the second or two before the catalog landed, and a model picked in that window was refused
 *  at the send ("no provider serves it") after it had been accepted. Unknown is shown as unknown,
 *  and nothing unknown can be sent. */
export type ModelAvailability = 'yes' | 'no' | 'unknown';
export function modelAvailability(backend: string | null | undefined, id: string): ModelAvailability {
  const entry = backend ? _catalog?.[backend] : undefined;
  if (!entry) return 'unknown';
  return entry.unavailable.includes(id) ? 'no' : 'yes';
}
/** The picker's note beside a model that cannot be picked; one wording everywhere. */
export function availabilityNote(state: ModelAvailability): string {
  return state === 'no' ? 'no provider' : state === 'unknown' ? 'checking providers' : '';
}
export function modelAvailable(backend: string | null | undefined, id: string): boolean {
  return modelAvailability(backend, id) === 'yes';
}

export interface BaseTool { name: string; label: string; enforcement: 'hard' | 'instruction' }
export interface BuiltinSkill { name: string; title: string; description: string; defaultEnabled: boolean; origin: string }
export interface BaseInfo {
  id: string; label: string; backend: string; status: string; systemPrompt: string;
  defaultModel: string;
  /** `reasoning`: the thinking levels the model has, lowest first; empty or absent where it has
   *  none to offer. The control is drawn from this list and never from one kept here. */
  models: { id: string; available: boolean; default: boolean; reasoning?: string[] }[];
  tools: BaseTool[];
  /** Skills bundled into the image, which any harness can use. `defaultEnabled` is what a NEW
   *  harness starts with; a harness that stored its own answer overrides it. */
  builtinSkills: BuiltinSkill[];
  /** false means the base brings its own skills but nothing outside a turn can list them. The UI
   *  must say that rather than render an empty list as "this base has no skills". */
  builtinSkillsEnumerable: boolean;
  /** false means skills mean nothing on this base (System One: a decision model chooses among
   *  offered actions and reads no documents), so none are offered and none can be added. Absent
   *  on older gateways, which is the same as true. */
  takesSkills?: boolean;
  /** false means a Task on this base cannot open an environment (Qoder Cloud Agent runs in its own
   *  cloud, and the layer is mounted on this box's sandboxes only), so none is offered. Absent on
   *  older gateways, which is the same as true. */
  takesEnvironments?: boolean;
}

let _bases: Record<string, BaseInfo> | null = null;
let _basesInflight: Promise<Record<string, BaseInfo>> | null = null;
/** The limits a turn gets when neither the request nor the harness sets one, from the server's
 *  bases document. null until it lands: the settings page shows nothing rather than a guess. */
export interface RuntimeDefaults { maxStep: number; timeoutSeconds: number }
let _runtimeDefaults: RuntimeDefaults | null = null;
// the bases document as the server answered it, for what it says beyond the bases (its capabilities)
let _basesDoc: Record<string, unknown> | null = null;

async function fetchBases(): Promise<Record<string, BaseInfo>> {
  if (_bases) return _bases;
  if (_basesInflight) return _basesInflight;
  _basesInflight = (async () => {
    // a few tries of the same read, as the model catalog's: one failed read must not leave the page
    // with no harness for the life of the tab
    try {
      for (const wait of [0, 1500, 3000]) {
        if (wait) await new Promise((r) => setTimeout(r, wait));
        try {
          const r = await harnessFetch('/api/harness/v1/bases', { headers: gwHeaders(), cache: 'no-store' });
          if (!r.ok) throw new Error(String(r.status));
          const doc = await r.json();
          if (!doc || typeof doc !== 'object' || !Array.isArray(doc.bases)) throw new Error('not the bases document');
          const map: Record<string, BaseInfo> = {};
          for (const b of doc.bases) map[b.id] = b as BaseInfo;
          const rd = doc.runtimeDefaults;
          if (rd && Number(rd.maxStep) > 0 && Number(rd.timeoutSeconds) > 0) {
            _runtimeDefaults = { maxStep: Number(rd.maxStep), timeoutSeconds: Number(rd.timeoutSeconds) };
          }
          _basesDoc = doc as Record<string, unknown>;
          _bases = map;
          return map;
        } catch {
          // try again
        }
      }
      return {};
    } finally { _basesInflight = null; }
  })();
  return _basesInflight;
}

/** The server-described bases for a caller that is not a component (once per tab; {} when it could not
 *  be read, which offers no harness: the caller says it could not read them). */
export const loadBases = fetchBases;

/** The bases document as the server answered it (once per tab), or null when it could not be read. */
export async function basesDoc(): Promise<Record<string, unknown> | null> {
  await fetchBases();
  return _basesDoc;
}

/** The server's runtime defaults, once the bases document has landed. */
export function useRuntimeDefaults(): RuntimeDefaults | null {
  const [d, setD] = useState<RuntimeDefaults | null>(_runtimeDefaults);
  useEffect(() => {
    let alive = true;
    fetchBases().then(() => { if (alive && _runtimeDefaults) setD(_runtimeDefaults); });
    return () => { alive = false; };
  }, []);
  return d;
}

/** A read the page waits on: its value once it has landed (null until then), whether the last
 *  read failed, and `retry` to read it again. */
export interface Read<T> { value: T | null; failed: boolean; retry: () => void }
function useServerRead<T extends object>(get: () => Promise<T>, have: T | null): Read<T> {
  const [value, setValue] = useState<T | null>(have);
  const [failed, setFailed] = useState(false);
  const [n, setN] = useState(0);
  useEffect(() => {
    let alive = true;
    get().then((v) => {
      if (!alive) return;
      if (Object.keys(v).length) { setValue(v); setFailed(false); } else setFailed(true);
    });
    return () => { alive = false; };
  // `n` is a Try again
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [n]);
  return { value, failed: failed && !value, retry: () => { setFailed(false); setN((x) => x + 1); } };
}

/** The server-described bases, null until loaded (a caller shows nothing rather than a guess). */
export function useBasesRead(): Read<Record<string, BaseInfo>> { return useServerRead(fetchBases, _bases); }
export function useBases(): Record<string, BaseInfo> | null { return useBasesRead().value; }

/** The server's model catalog, once per tab: every model picker reads it, and offers the
 *  placeholders until it lands (`failed` once every try failed: the picker says so, with Try again). */
export function useModelCatalogRead(): Read<ModelCatalog> { return useServerRead(fetchModelCatalog, _catalog); }
export function useModelCatalog(): ModelCatalog | null { return useModelCatalogRead().value; }

function principal() {
  const s = getSession();
  return { orgId: s?.orgId || '', member: s?.member?.email || s?.member?.id || '' };
}

/** Gateway CRUD via the same-origin BFF (/api/harness injects the trust headers).
 *  All harness writes go through the gateway so config validation (skills need a
 *  SKILL.md) and large-bundle offloading apply no matter which surface saved. The
 *  gateway returns the camelCase CustomHarness shape directly. */
export function gwHeaders(): Record<string, string> {
  const p = principal();
  return { 'content-type': 'application/json', 'x-harness-org': p.orgId, 'x-harness-member': p.member,
           ...workspaceHeaders() };
}

/** `signal`: a read with its own end (readSettled, lib/settle.ts) in place of harnessFetch's 30 s. */
export async function gw<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const r = await harnessFetch(`/api/harness${path}`, {
    method, headers: gwHeaders(), cache: 'no-store', signal,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) {
    let detail = `${r.status}`;
    try {
      const d = await r.json() as { detail?: unknown; error?: { message?: unknown } } | null;
      detail = String(d?.detail || d?.error?.message || detail);
    } catch { /* keep the status */ }
    throw new Error(detail);
  }
  return r.json() as Promise<T>;
}

/** The record as the gateway takes it. Only the fields a harness has: the gateway refuses any other
 *  by name (a field it would not apply is never saved). */
function harnessBody(input: Partial<CustomHarness> & { name: string; base: string }) {
  const base = oobById(input.base);
  return {
    name: input.name, base: input.base,
    base_label: input.baseLabel || base?.name || input.base,
    // what the person chose; '' when they chose none: the server runs it on the base's default
    default_model: input.defaultModel || '',
    system_prompt: input.systemPrompt || '',
    mcp_servers: input.mcpServers || [],
    skills: input.skills || [],
    disabled_tools: input.disabledTools || [],
    plugins: input.plugins || [],
    max_step: input.maxStep || null,
    timeout_seconds: input.timeoutSeconds || null,
    reasoning_effort: input.reasoningEffort || null,
    additional_headers: input.additionalHeaders || [],
    env: input.env || {},
    environment: input.environment || '',
  };
}

export async function listCustom(signal?: AbortSignal): Promise<CustomHarness[]> {
  if (!principal().orgId) return [];
  // Workspace scoping rides the request headers (gwHeaders); the query params make the
  // filter explicit for the gateway's list handler as well.
  const q = new URLSearchParams();
  appendWorkspaceQuery(q);
  const qs = q.toString();
  // an answer without the list is a failed read, never "no setups"
  const d = await gw<{ harnesses?: CustomHarness[] }>('GET', `/v1/harnesses${qs ? `?${qs}` : ''}`, undefined, signal);
  if (!d || !Array.isArray(d.harnesses)) throw new Error('Your setups could not be read just now.');
  return d.harnesses;
}

export async function getCustom(id: string): Promise<CustomHarness | null> {
  try { return await gw<CustomHarness>('GET', `/v1/harnesses/${encodeURIComponent(id)}`); }
  catch { return null; }
}

/** One setup by id for a page that must tell "not here" from "could not be read": null only when the
 *  server answers 404 (not in this workspace, or gone); any other failure throws, so a moment of
 *  downtime is never shown as a missing setup. */
export async function readCustom(id: string): Promise<CustomHarness | null> {
  const r = await harnessFetch(`/api/harness/v1/harnesses/${encodeURIComponent(id)}`, { headers: gwHeaders(), cache: 'no-store' });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(String(r.status));
  return r.json() as Promise<CustomHarness>;
}

export async function createCustom(input: Partial<CustomHarness> & { name: string; base: string }): Promise<CustomHarness> {
  // where it came from goes with the create alone: an update never changes it (the server keeps it)
  return gw<CustomHarness>('POST', '/v1/harnesses', { ...harnessBody(input), ...(input.source ? { source: input.source } : {}) });
}

export async function saveCustom(c: CustomHarness): Promise<CustomHarness> {
  // Return the gateway's canonical record so the caller can reset its draft to it, otherwise the
  // edited draft never structurally equals the reloaded harness and the Save button stays "changed".
  return gw<CustomHarness>('PUT', `/v1/harnesses/${encodeURIComponent(c.id)}`, harnessBody(c));
}

/** Delete a session for good: transcript, trace, and working folder. */
export async function deleteSession(sid: string): Promise<void> {
  await gw<{ deleted: boolean }>('DELETE', `/v1/sessions/${encodeURIComponent(sid)}`);
}

/** Delete a setup: it stops at once and is removed for good after 30 days; its tasks stay. */
export async function deleteCustom(id: string): Promise<void> {
  await gw<{ deleted: boolean }>('DELETE', `/v1/harnesses/${encodeURIComponent(id)}`);
}

let _pluginSchemas: Promise<string[]> | null = null;
/** The Agent Plugins manifest schemas this server installs, from its discovery document; empty
 *  when the server reports no plugin support (the Console then leaves the check to Save). */
export function pluginSchemas(): Promise<string[]> {
  if (!_pluginSchemas) {
    _pluginSchemas = gw<{ capabilities?: Record<string, boolean>; plugin_schemas?: string[] }>('GET', '/v1/uhp')
      .then((d) => (d.capabilities?.plugins ? (d.plugin_schemas || []) : []))
      .catch(() => []);
  }
  return _pluginSchemas;
}

/** The complete package of one installed plugin, byte for byte (UHP Plugins 3.1). */
export async function getPluginFiles(harnessId: string, name: string):
  Promise<{ path: string; content?: string; content_b64?: string }[]> {
  const r = await gw<{ files: { path: string; content?: string; content_b64?: string }[] }>(
    'GET', `/v1/harnesses/${encodeURIComponent(harnessId)}/plugins/${encodeURIComponent(name)}/files`);
  return r.files || [];
}

/** Full files of one skill on a harness, resolving the server-side blob offload, used to
 *  hydrate a folder skill for editing when the record only carries {name, enabled, blob}. */
export async function getSkillFiles(harnessId: string, skillId: string):
  Promise<{ path: string; content?: string; content_b64?: string }[]> {
  const r = await gw<{ files: { path: string; content?: string; content_b64?: string }[] }>(
    'GET', `/v1/harnesses/${encodeURIComponent(harnessId)}/skills/${encodeURIComponent(skillId)}/files`);
  return r.files || [];
}

/** Probe an MCP server (server-side handshake via the gateway) and return its tools. `auth` may
 *  be a literal bearer token or an existing 'vault:<ref>'. */
export async function testMcp(url: string, auth?: string): Promise<{ ok: boolean; error?: string; server?: string; tools?: { name: string; description?: string }[] }> {
  const p = principal();
  const r = await harnessFetch(`/api/harness/v1/orgs/${encodeURIComponent(p.orgId)}/mcp-test`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-harness-org': p.orgId, 'x-harness-member': p.member },
    body: JSON.stringify({ url, auth: auth || '' }),
    cache: 'no-store',
  });
  if (!r.ok) return { ok: false, error: `test failed: ${r.status}` };
  return r.json();
}

/** Store an MCP bearer token securely and return a 'vault:<ref>' reference. The token never lands
 *  on the harness record; only the reference is kept there. */
export async function storeMcpSecret(serverId: string, token: string): Promise<string> {
  const p = principal();
  const r = await harnessFetch(`/api/harness/v1/orgs/${encodeURIComponent(p.orgId)}/mcp-secrets/${encodeURIComponent(serverId)}`, {
    method: 'PUT',
    headers: { 'content-type': 'application/json', 'x-harness-org': p.orgId, 'x-harness-member': p.member },
    body: JSON.stringify({ token }),
    cache: 'no-store',
  });
  if (!r.ok) throw new Error(`mcp-secret store failed: ${r.status}`);
  return (await r.json()).ref as string;
}

/** Try a database connection string the way a kit's launch will: engine, host, database, table count. */
export async function testDatabase(engine: string, connectionString: string):
  Promise<{ ok: boolean; error?: string; host?: string; database?: string; tableCount?: number; tables?: string[] }> {
  const p = principal();
  const r = await harnessFetch(`/api/harness/v1/orgs/${encodeURIComponent(p.orgId)}/mcp-test/database`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-harness-org': p.orgId, 'x-harness-member': p.member },
    body: JSON.stringify({ engine, connection_string: connectionString }),
    cache: 'no-store',
  });
  if (!r.ok) return { ok: false, error: `test failed: ${r.status}` };
  return r.json();
}

// ── the instruction file each base actually reads ─────────────────────────────────────────────
// The NAME of the file the runner writes for a base, which is the label the settings page puts on
// the instructions box. It has to agree with runner/server.py's `_agent_doc_path`, and until
// 2026-10-03 it did not: the page labelled qwen and gemini "AGENTS.md" while the runner wrote
// QWEN.md and GEMINI.md, so a person edited a box named for a file their agent never read.
// gateway/tests/test_instruction_file_label.py now holds this map to the runner's function, so the
// next base that chooses its own name cannot drift the same way.
//
// systemone and qoder have no file at all: systemone reads no workspace and its instructions travel
// in the job, and qoder's travel with the hosted session it drives, so the page calls the box
// "Instructions".
export const INSTRUCTION_FILE: Record<string, string> = {
  qwen: 'QWEN.md',
  gemini: 'GEMINI.md',
  systemone: 'Instructions',
  qoder: 'Instructions',
};
const AGENTS_MD_BASES = [
  'codex', 'hermes', 'omp', 'pi', 'opencode', 'kilo', 'dsh', 'qwen', 'cline', 'goose', 'kimi',
  'minimax', 'aider', 'openhands', 'grok', 'agentzero',
  'mimo', 'jcode', 'opensquilla', 'nanobot', 'zeroclaw',
  // this batch: vibe reads AGENTS.md only in a trusted folder (--trust), docker-agent through
  // its own prompt-files lookup, and fast-agent has no convention at all — the file is passed as
  // its instruction with -i.
  'vibe', 'docker-agent', 'fast-agent',
  // dcode reads the project's AGENTS.md through find_project_agent_md — but only when the
  // workspace is a git PROJECT, which every session here is.
  'dcode',
];
export function instructionFileLabel(baseId: string | null | undefined): string {
  const id = baseId || '';
  return INSTRUCTION_FILE[id] || (AGENTS_MD_BASES.includes(id) ? 'AGENTS.md' : 'CLAUDE.md');
}

// ── plugins: services a workspace connects once, each Harness including the ones it needs ────
// The workspace's catalog and a plugin's attachments are read through lib/plugs.ts (reads with a
// signal); the calls that change a plugin, and a Harness's own binding, are here.
export interface PlugPricing { unit: string; usd_per_unit: number; markup: number; source: string; vendor: string; billed_as: string; rounding: string; session_cap_minutes: number; session_estimate_usd: number }
export interface Plug {
  type: string; label: string; source: 'platform' | 'local'; official: boolean;
  status: 'connected' | 'disabled' | 'needs_auth' | 'missing';
  config: Record<string, unknown>; secrets_set: string[]; secrets_needed: string[]; config_fields: string[];
  version: number; tools: number; pricing?: PlugPricing;
  /** What the plugin waits for before it can serve (a Microsoft 365 plug waiting for a person's sign-in). */
  attention?: string;
}
export const PLUGS_ENTRY_ID = 'mcp.plugs';

/** Connect a plugin for the workspace, change its settings, or turn it off. */
export function setPlug(type: string, body: { enabled: boolean; config?: Record<string, unknown>; secrets?: Record<string, string> }): Promise<Plug> {
  return gw<Plug>('PUT', `/v1/plugs/${encodeURIComponent(type)}`, body);
}
/** Microsoft 365 as each person: the member's own sign-in with Microsoft on the workspace's application. */
export function microsoftStart(redirect_uri: string): Promise<{ auth_url: string; state: string }> {
  return gw<{ auth_url: string; state: string }>('POST', '/v1/plugs/microsoft365/microsoft/start', { redirect_uri });
}
export function microsoftComplete(code: string, state: string): Promise<Plug> {
  return gw<Plug>('POST', '/v1/plugs/microsoft/complete', { code, state });
}
export function microsoftSignout(): Promise<Plug> {
  return gw<Plug>('POST', '/v1/plugs/microsoft365/microsoft/signout', {});
}
export interface PlugTool { name: string; description: string; risk: string }
/** The tools a plugin serves, the same list the agent gets. */
export function plugTools(type: string): Promise<{ type: string; label: string; tools: PlugTool[] }> {
  return gw<{ type: string; label: string; tools: PlugTool[] }>('GET', `/v1/plugs/${encodeURIComponent(type)}/tools`);
}
/** Remove a plugin from the workspace: the record and the credential it kept are deleted. */
export function deletePlug(type: string): Promise<{ type: string; workspace: string; removed: boolean }> {
  return gw<{ type: string; workspace: string; removed: boolean }>('DELETE', `/v1/plugs/${encodeURIComponent(type)}`);
}
export interface HarnessPlugs { id: string; name: string; enabled: boolean; workspace: string; plugs: string[]; tools?: Record<string, string[]>; status: Record<string, string> }
/** The plugins one Harness includes, or null when it includes none. */
export async function getHarnessPlugs(harnessId: string): Promise<HarnessPlugs | null> {
  const r = await harnessFetch(`/api/harness/v1/harnesses/${encodeURIComponent(harnessId)}/servers/${PLUGS_ENTRY_ID}`, { headers: gwHeaders(), cache: 'no-store' });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`plugins read failed (${r.status})`);
  return (await r.json()) as HarnessPlugs;
}
/** Set the plugins a Harness includes; an empty list detaches the server. */
export async function setHarnessPlugs(harnessId: string, plugs: string[]): Promise<HarnessPlugs | null> {
  if (plugs.length === 0) {
    const r = await harnessFetch(`/api/harness/v1/harnesses/${encodeURIComponent(harnessId)}/servers/plugs`, { method: 'DELETE', headers: gwHeaders() });
    if (!r.ok && r.status !== 404) throw new Error(`plugins update failed (${r.status})`);
    return null;
  }
  return gw<HarnessPlugs>('POST', `/v1/harnesses/${encodeURIComponent(harnessId)}/servers/plugs`, { plugs });
}
