// A memory search in a conversation, as a person reads it (the memories spec, C6): what the agent looked for, and a
// list of what it found, in the records' own words. The tool answers the agent in JSON (gateway memory_tools.py,
// memory_recall: {results: [{record: {title, content: [{type, text}]}}], abstain}); shown as it is, that is two hundred
// lines of ids and braces. Any other call, and an answer that isn't that JSON (cut short, or an error), is left as it is.
import type { ToolItem, Turn } from 'reifyui/agent-chat';

/** memory_recall under whatever name an agent CLI gives a connected server's tool (mcp__memories__memory_recall,
 *  memories.memory_recall, memories__memory_recall). */
export const isRecall = (name: string) => /(^|__|\.|:|\/)memory_recall$/.test(String(name || '').trim());

/** The JSON a tool answered, also where the CLI wraps it as MCP content ([{type: 'text', text}]). */
function answerOf(raw: string): unknown {
  const at = (s: string) => { try { return JSON.parse(s) as unknown; } catch { return null; } };
  const j = at(String(raw || '').trim());
  if (Array.isArray(j) && j.every((x) => x && typeof x === 'object' && (x as { type?: unknown }).type === 'text')) {
    return at(j.map((x) => String((x as { text?: unknown }).text || '')).join(''));
  }
  return j;
}

const LINE_MAX = 220;
/** What one found record says: its title, else its words. */
function saidBy(record: unknown): string {
  if (!record || typeof record !== 'object') return '';
  const r = record as { title?: unknown; content?: unknown };
  const parts = Array.isArray(r.content) ? r.content : typeof r.content === 'string' ? [{ type: 'text', text: r.content }] : [];
  const words = parts.filter((p) => p && typeof p === 'object' && (p as { type?: unknown }).type === 'text')
    .map((p) => String((p as { text?: unknown }).text || '')).join(' ');
  const t = (typeof r.title === 'string' && r.title.trim() ? r.title : words).replace(/\s+/g, ' ').trim();
  return t.length > LINE_MAX ? `${t.slice(0, LINE_MAX - 1).trim()}…` : t;
}

/** The found list as lines, or null when the answer isn't a recall's. */
export function recallLines(output: string | undefined): string | null {
  if (output === undefined) return null;
  const a = answerOf(output) as { results?: unknown; abstain?: unknown } | null;
  if (!a || typeof a !== 'object' || !Array.isArray(a.results)) {
    // an answer cut short (the record keeps its start): the records' words that arrived whole, said as part of it
    if (!/^\s*\{\s*"results"\s*:/.test(output)) return null;
    const words = [...output.matchAll(/"text"\s*:\s*("(?:[^"\\]|\\.)*")/g)].map((m) => { try { return String(JSON.parse(m[1])); } catch { return ''; } })
      .map((t) => t.replace(/\s+/g, ' ').trim()).filter(Boolean).map((t) => (t.length > LINE_MAX ? `${t.slice(0, LINE_MAX - 1).trim()}…` : t));
    return words.length ? ['Some of what it found:', ...words.map((t) => `• ${t}`)].join('\n') : null;
  }
  const found = a.results.map((x) => saidBy(x && typeof x === 'object' ? (x as { record?: unknown }).record : null)).filter(Boolean);
  if (!found.length) return a.abstain ? 'Nothing it holds answers this.' : 'Nothing found.';
  return [`Found ${found.length} ${found.length === 1 ? 'thing' : 'things'}:`, ...found.map((t) => `• ${t}`)].join('\n');
}

/** A recall call as a person reads it: what it looked for (no memory id) and what it found. */
export function readableStep(item: ToolItem): ToolItem {
  if (!isRecall(item.name)) return item;
  let a: Record<string, unknown> = {};
  try { a = JSON.parse(item.args || '{}') as Record<string, unknown>; } catch { return item; }
  const asked = [a.query, a.text].find((v) => typeof v === 'string' && v.trim()) as string | undefined;
  const lines = item.status === 'failed' ? null : recallLines(item.output);
  return {
    ...item,
    args: JSON.stringify(asked ? { 'Looked for': asked } : {}),
    ...(lines !== null ? { output: lines, truncated: null } : {}),
  };
}

/** Every memory search in a turn, readable. */
export function readableTurn(t: Turn): Turn {
  if (!t.items.some((x) => x.kind === 'tool' && isRecall(x.name))) return t;
  return { ...t, items: t.items.map((x) => (x.kind === 'tool' ? readableStep(x) : x)) };
}
