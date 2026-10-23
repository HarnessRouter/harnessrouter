// A setup's plugins, skills and tools: one function each, read by every place that lists or counts
// them, and each place says which of two lists it shows:
//   'all'    everything the setup can use, the agent harness's built-in skills and tools included:
//            what Settings › Capabilities lists, each tab counting the ones that are on.
//   'added'  only what a person added to it: their own skills, the MCP servers they added, and every
//            plugin. The picture counts these and never a built-in: the Agent stack's bricks and
//            parts row, Studio's card towers, and the Capabilities line in Settings' layers list,
//            which sits beside the stack.
// In either list a count is the ones that are on (`countOn`); a tab draws the rest dimmed.
//
// Plugins (setupPlugins), in the order the Plugins tab lists them:
//   1. Every workspace plugin the setup includes (its plugins binding, by the plugin's type). A
//      plugin the workspace has since turned off or removed is still on the setup (a warning on its
//      row, not a setting), so it counts. When the record says it has a binding but it has not been
//      read (or could not be), it counts as one, a floor.
//   2. Every plugin package installed on the record; one turned off is listed, not counted.
//   Every plugin is one a person added, so its two lists are the same.
// Skills (setupSkills): the setup's own skills (added), then ('all' only) the agent harness's
// built-in skills it has not replaced with one of its own, each on by its own switch (a built-in by
// the setup's stored choice, else the harness's default). An agent harness that takes no skills has
// none.
// Tools (setupTools): ('all' only) the agent harness's built-in tools, on unless turned off, then the
// setup's own MCP servers (added). Not tools: the workspace plugins binding (plugins).
// Built-ins come from the bases document; while it is not read, 'all' knows only what was added.
import { PLUGS_ENTRY_ID, type BaseInfo, type BaseTool, type BuiltinSkill, type CustomHarness, type McpServer } from '@/lib/harness';

/** Workspace plugins the record has but that were not read. */
export const UNREAD_NAME = 'Plugins from your workspace';

/** Which list a place shows: everything the setup can use, or only what a person added. */
export type Scope = 'all' | 'added';

/** How many of a list are on: the number every place shows. */
export const countOn = (list: readonly { on: boolean }[]) => list.filter((x) => x.on).length;

// ── plugins ──────────────────────────────────────────────────────────────────────────────────────

/** What the setup's plugins binding says, as read: the types of the workspace plugins it includes. */
export interface PlugBinding { plugs: string[]; enabled?: boolean }

export type SetupPlugin =
  | { kind: 'plug'; key: string; type: string; on: true }
  | { kind: 'package'; key: string; name: string; on: boolean }
  | { kind: 'unread'; key: string; on: true };

/** The record says the setup includes workspace plugins (their binding's entry, turned on). */
export const hasPlugsEntry = (h: CustomHarness) => !!(h.mcpServers || []).find((m) => m.id === PLUGS_ENTRY_ID && m.enabled !== false);
/** The plugins binding is the service's own entry on the record, never one of the setup's own MCP servers. */
export const isServiceEntry = (m: McpServer) => m.id === PLUGS_ENTRY_ID;

/** This setup's plugins (the rule above). `binding`: the plugins binding as read; null when the setup
 *  has none, undefined while it is not read or could not be. Every plugin is added by a person, so
 *  `scope` gives the same list either way; each place still says which it shows. */
export function setupPlugins(h: CustomHarness, binding: PlugBinding | null | undefined, scope: Scope): SetupPlugin[] {
  void scope;
  const out: SetupPlugin[] = [];
  if (hasPlugsEntry(h)) {
    if (binding === undefined) out.push({ kind: 'unread', key: 'plugs:unread', on: true });
    else if (binding && binding.enabled !== false) (binding.plugs || []).forEach((type) => out.push({ kind: 'plug', key: `plug:${type}`, type, on: true }));
  }
  (h.plugins || []).forEach((p) => out.push({ kind: 'package', key: `pkg:${p.name}`, name: p.name, on: p.enabled !== false }));
  return out;
}

/** A plugin's name: a package's own, a workspace plugin's label from the catalog (`labels`, by type),
 *  never its type alone when the catalog has a name. */
export function pluginName(p: SetupPlugin, labels: Record<string, string> = {}): string {
  if (p.kind === 'package') return p.name;
  if (p.kind === 'plug') return labels[p.type] || p.type;
  return UNREAD_NAME;
}

/** The names of the plugins that are on, as far as the record alone names them (packages), or null
 *  when it does not name them all. */
export function recordNames(list: SetupPlugin[]): string[] | null {
  const names = list.filter((p) => p.on).map((p) => (p.kind === 'package' ? p.name : ''));
  return names.every(Boolean) ? names : null;
}

// ── skills ───────────────────────────────────────────────────────────────────────────────────────

type Skill = CustomHarness['skills'][number];
/** A skill of the setup's own (its files are on the record), not a built-in's stored switch. */
export const isOwnSkill = (s: Skill) => Boolean((s.files && s.files.length) || (s as { content?: string }).content || s.blob);

export type SetupSkill =
  | { kind: 'own'; key: string; name: string; on: boolean; skill: Skill }
  | { kind: 'builtin'; key: string; name: string; on: boolean; builtin: BuiltinSkill };

/** This setup's skills (the rule above); `base` is its agent harness in the bases document. */
export function setupSkills(h: CustomHarness, base: BaseInfo | null | undefined, scope: Scope): SetupSkill[] {
  if (base?.takesSkills === false) return [];
  const all = h.skills || [];
  const own = all.filter(isOwnSkill);
  const out: SetupSkill[] = own.map((s) => ({ kind: 'own', key: `own:${s.id || s.name}`, name: s.name, on: s.enabled !== false, skill: s }));
  if (scope === 'added') return out;
  (base?.builtinSkills || []).filter((b) => !own.some((s) => s.name === b.name)).forEach((b) => {
    const stored = all.find((s) => s.name === b.name && !isOwnSkill(s));
    out.push({ kind: 'builtin', key: `builtin:${b.name}`, name: b.title || b.name, on: stored ? stored.enabled !== false : b.defaultEnabled, builtin: b });
  });
  return out;
}

// ── tools ────────────────────────────────────────────────────────────────────────────────────────

export type SetupTool =
  | { kind: 'builtin'; key: string; name: string; on: boolean; tool: BaseTool }
  | { kind: 'mcp'; key: string; name: string; on: boolean; server: McpServer; index: number };

/** This setup's tools (the rule above). `index` is the server's place among the setup's own MCP
 *  servers (Settings edits them by it). */
export function setupTools(h: CustomHarness, base: BaseInfo | null | undefined, scope: Scope): SetupTool[] {
  const off = h.disabledTools || [];
  const out: SetupTool[] = (scope === 'added' ? [] : base?.tools || []).map((t) => ({ kind: 'builtin', key: `tool:${t.name}`, name: t.name, on: !off.includes(t.name), tool: t }));
  (h.mcpServers || []).filter((m) => !isServiceEntry(m)).forEach((m, index) => {
    out.push({ kind: 'mcp', key: `mcp:${m.id || index}`, name: m.name || 'MCP server', on: m.enabled !== false, server: m, index });
  });
  return out;
}
