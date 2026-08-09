// Harness data layer. Out-of-box catalog is static for v1 (will read the runner /backends
// metadata next). Custom harnesses are persisted server-side per-org in the VectorGraph tenant
// via the gateway (/api/harness/v1/orgs/{org}/harnesses); the BFF injects the internal trust key.
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
  backend: 'claude' | 'codex' | 'hermes' | null; // gateway backend; null = coming soon
  systemPrompt: string;    // the harness's built-in system prompt (shown read-only)
  tools: string[];         // built-in tools (read-only)
  skills: string[];        // built-in skills (read-only)
}

export interface CustomHarness {
  id: string;
  name: string;
  base: string;            // base harness id (codex / claude-code)
  baseLabel: string;
  defaultModel: string;
  systemPrompt: string;
  mcpServers: { id: string; name: string; enabled: boolean; url?: string; auth?: string; transport?: string }[];
  // A skill carries its bundle inline as `files`; bundles over the gateway's inline cap are
  // offloaded server-side and round-trip as {name, enabled, blob}, `blob` is an opaque pointer,
  // resolved back to files via getSkillFiles() when editing. Either shape is a REAL own skill.
  skills: { id: string; name: string; enabled: boolean; files?: { path: string; content?: string; content_b64?: string }[]; blob?: string }[];
  disabledTools?: string[];  // inherited/built-in tool names disabled for this harness
  maxStep?: number | null;        // default agent step budget per turn (blank = 40)
  timeoutSeconds?: number | null; // default per-turn wall-clock cap (blank = server default)
  additionalHeaders?: string[]; // declared header NAMES callers pass per request (app-level auth)
  createdAt: number;
}

export const OOB: OobHarness[] = [
  { id: 'codex', name: 'Codex', version: 'v1.0.1', backend: 'codex', status: 'ready',
    models: ['gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.5', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.2'], defaultModel: 'gpt-5.5', moreModels: 0,
    systemPrompt: 'You are Codex, an autonomous software-engineering agent. You operate on a real git workspace with shell access, reading and editing files and running commands to complete the task, returning reviewable diffs and results.',
    tools: ['Shell', 'Apply Patch', 'File Read/Write', 'Git', 'Network (sandboxed)'],
    skills: ['docx', 'pdf', 'pptx', 'xlsx'] },
  { id: 'claude-code', name: 'Claude Code', version: 'v1.0.1', backend: 'claude', status: 'ready',
    models: ['claude-opus-5', 'claude-fable-5', 'claude-opus-4.8', 'claude-sonnet-5', 'claude-opus-4.7', 'claude-sonnet-4.6', 'claude-haiku-4.5'], defaultModel: 'claude-opus-4.8', moreModels: 0,
    systemPrompt: 'You are Claude Code, an agentic coding assistant. You work on a real local git working tree with bash, edit files, run tests, and use sub-agents to complete engineering tasks end to end.',
    tools: ['Bash', 'Read', 'Edit', 'Write', 'Grep', 'Glob', 'WebFetch', 'Task (subagents)'],
    skills: ['docx', 'pdf', 'pptx', 'xlsx'] },
  { id: 'pi', name: 'Pi', version: 'v1.0.1', backend: null, status: 'soon',
    models: [], moreModels: 0,
    systemPrompt: 'Pi harness, coming soon.', tools: [], skills: [] },
  { id: 'hermes', name: 'Hermes', version: 'v0.19.0', backend: 'hermes', status: 'ready',
    // Multi-family: Hermes runs any frontier model, the gpt + claude catalogs, default gpt-5.5.
    models: ['gpt-5.5', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.2', 'claude-opus-5', 'claude-fable-5', 'claude-opus-4.8', 'claude-sonnet-5', 'claude-opus-4.7', 'claude-sonnet-4.6', 'claude-haiku-4.5', 'gemini-3.6-flash', 'deepseek-v4-pro', 'kimi-k3', 'glm-5.2', 'qwen3.7-max'], defaultModel: 'gpt-5.5', moreModels: 0,
    systemPrompt: 'You are Hermes, a self-improving autonomous agent. You work on a real project workspace with shell and file access, complete tasks end to end, and build a persistent memory and skill library from what you learn, getting more capable the longer you run.',
    tools: ['Terminal', 'File Read/Write', 'Patch', 'Search', 'Web Search', 'Web Extract', 'Browser'],
    skills: ['docx', 'pdf', 'pptx', 'xlsx'] },
];

export const oobById = (id: string) => OOB.find((o) => o.id === id) || null;

// ── model catalog: the GATEWAY owns it, this file does not ────────────────────────────
// The `models` / `defaultModel` fields above used to be the console's own copy of the
// gateway's _MODEL_CATALOG. Two lists meant two places to edit, and only one of them got
// edited: adding deepseek-v4-flash to the gateway left it invisible in every picker here,
// and grok-4.5 has been wired in the TokenRouter integration all along without ever
// appearing in the UI. A picker that disagrees with what the server will accept is worse
// than a slow picker.
//
// So the catalog is fetched from GET /v1/models (same shape the gateway serves) and cached
// for the tab. The literals above remain ONLY as the pre-fetch placeholder so first paint
// isn't empty; once the fetch lands the server's list wins. Never add a model here — add it
// to _MODEL_CATALOG in the gateway and it shows up everywhere.
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
      if (Object.keys(out).length) _catalog = out;
      return _catalog || {};
    } catch {
      return {};              // keep the placeholder; a picker that renders beats one that throws
    } finally {
      _catalogInflight = null;
    }
  })();
  return _catalogInflight;
}

/** Models for a base harness — server catalog when loaded, placeholder literals until then. */
export const oobModels = (o: OobHarness | null | undefined): string[] => {
  if (!o) return [];
  const fromServer = o.backend ? _catalog?.[o.backend]?.models : undefined;
  return (fromServer && fromServer.length) ? fromServer : o.models;
};

/** Can this backend actually run this model? False only when the server said so — before the
 *  catalog loads (or if the fetch failed) nothing is greyed out on a guess. */
export function modelAvailable(backend: string | null | undefined, id: string): boolean {
  const list = backend ? _catalog?.[backend]?.unavailable : undefined;
  return !list || !list.includes(id);
}

export const oobDefaultModel = (o: OobHarness | null | undefined): string => {
  if (!o) return '';
  const fromServer = o.backend ? _catalog?.[o.backend]?.default : '';
  return o.defaultModel || fromServer || oobModels(o)[0] || '';
};

/** Load the server catalog once per tab and re-render when it lands. Any surface that shows a
 *  model picker calls this; without it the placeholder literals would be what the user sees. */
export function useModelCatalog(): ModelCatalog | null {
  const [cat, setCat] = useState<ModelCatalog | null>(_catalog);
  useEffect(() => {
    let alive = true;
    fetchModelCatalog().then((c) => { if (alive && Object.keys(c).length) setCat(c); });
    return () => { alive = false; };
  }, []);
  return cat;
}

// HarnessRouter business logic is VISUAL WORKFLOWS in the engine (the HarnessRouter
// Space), not a bespoke backend. Every CRUD op runs hr.harness.* against HR's own
// VectorGraph tenant via the engine run API; the JWT carries the principal.
const ENGINE = '/api/engine';

/** Shadow User vertex id (HR tenant), sanitized email; '@' can't be a vertex id. */
function memberUid(email: string): string {
  return 'usr.' + email.toLowerCase().replace(/[^a-z0-9]+/g, '.').replace(/^\.|\.$/g, '');
}
/** Shadow Account vertex id (HR tenant), HR-local; org_id kept as the link prop. */
function orgUid(orgId: string): string {
  return 'acct.' + orgId;
}

function principal() {
  const s = getSession();
  const orgId = s?.orgId || '';
  const org = (s?.orgs || []).find((o) => o.id === orgId);
  return {
    token: s?.token || '',
    orgId,
    orgName: (org?.name as string) || orgId,
    member: s?.member?.email || s?.member?.id || '',
    memberName: (s?.member?.name as string) || (s?.member?.display_name as string) || '',
  };
}

/** Gateway CRUD via the same-origin BFF (/api/harness injects the trust headers).
 *  All harness writes go through the gateway so config validation (skills need a
 *  SKILL.md) and large-bundle offloading apply no matter which surface saved. The
 *  gateway returns the camelCase CustomHarness shape directly. */
function gwHeaders(): Record<string, string> {
  const p = principal();
  return { 'content-type': 'application/json', 'x-harness-org': p.orgId, 'x-harness-member': p.member,
           ...workspaceHeaders() };
}

async function gw<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await harnessFetch(`/api/harness${path}`, {
    method, headers: gwHeaders(), cache: 'no-store',
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) {
    let detail = `${r.status}`;
    try { detail = (await r.json())?.detail || detail; } catch { /* keep the status */ }
    throw new Error(String(detail));
  }
  return r.json() as Promise<T>;
}

function harnessBody(input: Partial<CustomHarness> & { name: string; base: string }) {
  const base = oobById(input.base);
  return {
    name: input.name, base: input.base,
    base_label: input.baseLabel || base?.name || input.base,
    default_model: input.defaultModel || oobDefaultModel(base) || '',
    system_prompt: input.systemPrompt || '',
    mcp_servers: input.mcpServers || [],
    skills: input.skills || [],
    disabled_tools: input.disabledTools || [],
    max_step: input.maxStep || null,
    timeout_seconds: input.timeoutSeconds || null,
    additional_headers: input.additionalHeaders || [],
  };
}

export async function listCustom(): Promise<CustomHarness[]> {
  if (!principal().orgId) return [];
  // Workspace scoping rides the request headers (gwHeaders); the query params make the
  // filter explicit for the gateway's list handler as well.
  const q = new URLSearchParams();
  appendWorkspaceQuery(q);
  const qs = q.toString();
  return (await gw<{ harnesses: CustomHarness[] }>('GET', `/v1/harnesses${qs ? `?${qs}` : ''}`)).harnesses || [];
}

export async function getCustom(id: string): Promise<CustomHarness | null> {
  try { return await gw<CustomHarness>('GET', `/v1/harnesses/${encodeURIComponent(id)}`); }
  catch { return null; }
}

export async function createCustom(input: Partial<CustomHarness> & { name: string; base: string }): Promise<CustomHarness> {
  return gw<CustomHarness>('POST', '/v1/harnesses', harnessBody(input));
}

export async function saveCustom(c: CustomHarness): Promise<CustomHarness> {
  // Return the gateway's canonical record so the caller can reset its draft to it, otherwise the
  // edited draft never structurally equals the reloaded harness and the Save button stays "changed".
  return gw<CustomHarness>('PUT', `/v1/harnesses/${encodeURIComponent(c.id)}`, harnessBody(c));
}

export async function deleteCustom(id: string): Promise<void> {
  await gw<{ deleted: boolean }>('DELETE', `/v1/harnesses/${encodeURIComponent(id)}`);
}

/** Full files of one skill on a harness, resolving the server-side blob offload, used to
 *  hydrate a folder skill for editing when the record only carries {name, enabled, blob}. */
export async function getSkillFiles(harnessId: string, skillId: string):
  Promise<{ path: string; content?: string; content_b64?: string }[]> {
  const r = await gw<{ files: { path: string; content?: string; content_b64?: string }[] }>(
    'GET', `/v1/harnesses/${encodeURIComponent(harnessId)}/skills/${encodeURIComponent(skillId)}/files`);
  return r.files || [];
}

export async function cloneCustom(id: string): Promise<CustomHarness | null> {
  const c = await getCustom(id);
  if (!c) return null;
  return createCustom({ ...c, name: c.name + ' (copy)' });
}

export async function cloneFromOob(oobId: string): Promise<CustomHarness | null> {
  const o = oobById(oobId);
  if (!o) return null;
  return createCustom({ name: o.name + ' (custom)', base: o.id, defaultModel: oobDefaultModel(o) });
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

/** Store an MCP bearer token in the vault and return a 'vault:<ref>' reference. The token never
 *  lands in the graph, only the ref is persisted on the harness config. */
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
