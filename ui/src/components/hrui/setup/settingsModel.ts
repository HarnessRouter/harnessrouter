'use client';
// What a setup's Settings tab edits (docs/uxuidesign/console-79: SET_KEYS, SET_LAYERS, LAYER_KEYS,
// agentCfg, setDirty, hasDraft) and the Agent stack's clicks into it (data-tw, §9.6).
//
// The draft is a patch over the saved record: only the fields a person touched, so a change made
// elsewhere to a field they did not touch is never written back over. It is kept per setup for the
// life of the tab, so leaving Settings for Tasks and coming back keeps it (and the header keeps its
// dot).
import { useEffect, useRef } from 'react';
import { instructionFileLabel, type CustomHarness, type McpServer } from '@/lib/harness';
import { isServiceEntry } from './setupParts';

export type LayerKey = 'instructions' | 'harness' | 'caps' | 'runtime';
/** The layers in the order the rail and the narrow chips list them, top first (Richard, 2026-10-18):
 *  Instructions, then Agent harness (the agent harness and its model, one layer), Capabilities, and
 *  Environment & limits last. The Agent stack still draws them as a stack, the agent harness at its
 *  foot (tower.ts); only the list's order is this one. */
export const SET_LAYERS: [LayerKey, string][] = [['instructions', 'Instructions'], ['harness', 'Agent harness'], ['caps', 'Capabilities'], ['runtime', 'Environment & limits']];
export const isLayer = (v: string | null | undefined): v is LayerKey => SET_LAYERS.some(([k]) => k === v);
/** The layer an address (?layer=) opens: the Model layer of an older link is part of Agent harness
 *  now, and an address with none (or one not known) opens the first. */
export const layerOf = (v: string | null | undefined): LayerKey => (v === 'model' ? 'harness' : isLayer(v) ? v : SET_LAYERS[0][0]);
/** Capabilities' tabs, in Extensions order (the design's capTab) */
export type CapTab = 'plugin' | 'skill' | 'tool';
export const isCapTab = (v: string | null | undefined): v is CapTab => v === 'plugin' || v === 'skill' || v === 'tool';
/** the Capabilities tab a part of the Agent stack opens (the design's capFrom) */
export const capOf = (tw: string): CapTab | undefined => (tw === 'skill' ? 'skill' : tw === 'plugin' ? 'plugin' : tw === 'mcp' ? 'tool' : undefined);

export interface EnvRow { name: string; value: string }
export interface Cfg {
  name: string; model: string; thinking: string; agentsMd: string;
  mins: string; turns: string;
  tools: string[];        // built-in tools turned off
  mcp: McpServer[];       // the setup's own MCP servers (the service's own entries are not here)
  vars: EnvRow[]; headers: string[];
}
export type CfgKey = keyof Cfg;
export const SET_KEYS: CfgKey[] = ['name', 'model', 'thinking', 'agentsMd', 'mins', 'turns', 'tools', 'mcp', 'vars', 'headers'];
export const LAYER_KEYS: Record<LayerKey, CfgKey[]> = {
  instructions: ['agentsMd'], harness: ['name', 'model', 'thinking'], caps: ['tools', 'mcp'], runtime: ['vars', 'headers', 'mins', 'turns'],
};

/** The plugins binding is this service's own entry on the record, listed as plugins (setupParts.ts)
 *  and attached and detached by its own route, never edited as an MCP server. */
export { isServiceEntry };

// A stored secret is written `secret:harness-mcp-…` here (the reference storing it answered); older records hold the
// same reference as `vault:harness-mcp-…`, and the service takes both. Only a whole reference of that namespace is
// translated, as the service does: a person's own value that starts "secret:" or "vault:" ("secret:rotate") is a
// literal, saved as typed (the loose translation saved it as a reference that resolves to nothing).
const REF_IN = /^\s*secret:(harness-mcp-[A-Za-z0-9-]+)\s*$/;
const REF_OUT = /^\s*vault:(harness-mcp-[A-Za-z0-9-]+)\s*$/;
export const showRef = (v: string) => { const m = REF_OUT.exec(v); return m ? `secret:${m[1]}` : v; };
export const storeRef = (v: string) => { const m = REF_IN.exec(v); return m ? `vault:${m[1]}` : v; };

/** The record as the settings form edits it. `model` is the record's own: '' when it has none (the
 *  server runs it on its harness's default), never a default filled in here. */
export function cfgOf(h: CustomHarness): Cfg {
  return {
    name: h.name || '', model: h.defaultModel || '', thinking: h.reasoningEffort || '', agentsMd: h.systemPrompt || '',
    mins: h.timeoutSeconds ? String(Math.max(1, Math.round(h.timeoutSeconds / 60))) : '',
    turns: h.maxStep ? String(h.maxStep) : '',
    tools: [...(h.disabledTools || [])],
    mcp: (h.mcpServers || []).filter((m) => !isServiceEntry(m)),
    vars: Object.entries(h.env || {}).map(([name, value]) => ({ name, value: showRef(String(value)) })),
    headers: [...(h.additionalHeaders || [])],
  };
}

export const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
export const dirtyKeys = (patch: Partial<Cfg>, base: Cfg): CfgKey[] => SET_KEYS.filter((k) => k in patch && !same(patch[k], base[k]));

const drafts = new Map<string, { patch: Partial<Cfg>; dirty: boolean }>();
export const draftOf = (id: string): Partial<Cfg> => drafts.get(id)?.patch || {};
export function keepDraft(id: string, patch: Partial<Cfg>, dirty: boolean) {
  if (!dirty) drafts.delete(id); else drafts.set(id, { patch, dirty });
}
/** The setup has edits in Settings not saved yet (the header's dot, on every tab). */
export const hasSettingsDraft = (id: string) => !!drafts.get(id)?.dirty;

/** The instruction file each base reads, as the runner writes it (runner/server.py _agent_doc_path): one map,
 *  instructionFileLabel in lib/harness.ts, which gateway/tests/test_instruction_file_label.py holds to the runner. */
export const mdName = (baseId: string): string => instructionFileLabel(baseId);

// Words that name how the service is built: a message carrying one is not shown as it is.
const INTERNAL = /\b(blob|vault|graph|gremlin|cosmos|tenant|azure|postgres|spanner|vertex|gateway)\b/i;
/** A server's refusal in its own words when they are plain words, else the given sentence. */
export function plain(e: unknown, fallback: string): string {
  const m = (e instanceof Error ? e.message : '').trim();
  if (!m || /^\d+$/.test(m) || m.startsWith('[object') || m.length > 240 || INTERNAL.test(m)) return fallback;
  const s = m.charAt(0).toUpperCase() + m.slice(1);
  return /[.!?]$/.test(s) ? s : s + '.';
}

export const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`;
/** Capabilities' line in the layers list: what a person added, as the Agent stack beside it counts
 *  (setupParts.ts, scope 'added'), in the tabs' order, each kind with none left out, and saying
 *  "added" so it never reads as the tabs' counts, which include the built-ins: "1 plugin added",
 *  "1 plugin, 2 skills and 1 tool added", or "Nothing added yet". */
export function addedLine(n: Record<CapTab, number>): string {
  const said = ([['plugin', 'plugin'], ['skill', 'skill'], ['tool', 'tool']] as [CapTab, string][])
    .filter(([k]) => n[k] > 0).map(([k, w]) => plural(n[k], w));
  if (!said.length) return 'Nothing added yet';
  return `${said.length > 1 ? `${said.slice(0, -1).join(', ')} and ${said[said.length - 1]}` : said[0]} added`;
}
export function cutWords(s: string, n: number): string {
  s = String(s || '').replace(/\s+/g, ' ').trim();
  if (s.length <= n) return s;
  let out = '';
  for (const w of s.split(' ')) { if ((out ? out.length + 1 : 0) + w.length > n) break; out += (out ? ' ' : '') + w; }
  return (out || s.slice(0, n)).replace(/[,.;:]$/, '') + '…';
}

/** Which Settings layer a brick of the Agent stack opens (the design's secMap / SET_OF). The agent
 *  harness and the model are one layer, so both bricks open it. */
export function brickLayer(tw: string): LayerKey | null {
  if (tw === 'b-runtime' || tw === 'model') return 'harness';
  if (tw === 'task') return 'instructions';
  if (tw === 'skill' || tw === 'plugin' || tw === 'mcp') return 'caps';
  if (tw === 'env' || tw === 'backend' || /^b-/.test(tw)) return 'runtime';
  return null;
}

/** A click on a brick or part of the setup page's Agent stack opens the layer of Settings it is (a
 *  part, its own tab of Capabilities, even one the setup has none of yet). */
export function useBrickNav(o: { onLayer: (k: LayerKey, cap?: CapTab) => void }) {
  const ref = useRef(o);
  ref.current = o;
  useEffect(() => {
    const click = (e: MouseEvent) => {
      const g = (e.target as Element | null)?.closest?.('#hrui .agent-side [data-tw], #hrui .agent-side [data-partlock]');
      if (!g) return;
      const tw = g.getAttribute('data-tw') || g.getAttribute('data-partlock') || '';
      const k = brickLayer(tw);
      if (k) ref.current.onLayer(k, capOf(tw));
    };
    document.addEventListener('click', click);
    return () => document.removeEventListener('click', click);
  }, []);
}
