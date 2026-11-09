// A memory search in a conversation, as a person reads it (the memories spec, C6): what the agent looked for, and a
// list of what it found, in the records' own words. The tool answers the agent in JSON (gateway memory_tools.py,
// memory_recall: {results: [{record: {title, content: [{type, text}]}}], abstain}); shown as it is, that is two hundred
// lines of ids and braces. An agent CLI may hand it on wrapped: Hermes puts a connected server's answer in
// {"result": "<the text>"} and that in an <untrusted_tool_result> block with a sentence for the model in front of it
// (hermes agent/tool_dispatch_helpers.py _maybe_wrap_untrusted, tools/mcp_tool.py), and a CLI may give it as MCP
// content ([{type: 'text', text}]). Each wrapping comes off before it is read. Any other call, and an answer that
// isn't that JSON (an error, a sentence), is left as it is.
import type { ToolItem, Turn } from 'reifyui/agent-chat';
import type { AsstMsg } from '@/lib/conversation';

/** memory_recall under whatever name an agent CLI gives a connected server's tool (mcp__memories__memory_recall,
 *  memories.memory_recall, memories__memory_recall). */
export const isRecall = (name: string) => /(^|__|\.|:|\/)memory_recall$/.test(String(name || '').trim());

const parse = (s: string): unknown => { try { return JSON.parse(s) as unknown; } catch { return null; } };

const OPEN_TAG = /^<untrusted_tool_result\b[^>]*>\s*/;
const CLOSE_TAG = '</untrusted_tool_result>';
/** The answer inside the block Hermes puts a connected server's answer in, without the sentence for the model in front
 *  of it (which ends at the first blank line); the text unchanged where there is no such block. A block cut short (no
 *  closing tag) gives what came. */
export function unwrapUntrusted(raw: string): string {
  const t = String(raw || '').trim();
  const open = OPEN_TAG.exec(t);
  if (!open) return t;
  let inner = t.slice(open[0].length);
  const close = inner.lastIndexOf(CLOSE_TAG);
  if (close >= 0) inner = inner.slice(0, close);
  const gap = inner.indexOf('\n\n');
  return (gap >= 0 ? inner.slice(gap + 2) : inner).trim();
}

/** Hermes's {"result": "..."} cut short: the string's characters as far as they came, unescaped; null when it isn't
 *  that. What came is then read as a recall's start, so the records that arrived whole are still said. */
function partialResult(s: string): string | null {
  const m = /^\{\s*"result"\s*:\s*"/.exec(s);
  if (!m) return null;
  // a closing quote and brace that did come go first, then an escape cut in half
  const body = s.slice(m[0].length).replace(/"\s*\}\s*$/, '');
  for (let cut = 0; cut < 7 && cut <= body.length; cut++) {
    const v = parse(`"${body.slice(0, body.length - cut)}"`);
    if (typeof v === 'string') return v;
  }
  return null;
}

/** The JSON a tool answered, however the CLI wrapped it: in an <untrusted_tool_result> block, as {"result": ...} (a
 *  string of JSON, the JSON itself, or text beside structuredContent), or as MCP content. */
function answerOf(raw: string): unknown {
  let j = parse(unwrapUntrusted(raw));
  if (Array.isArray(j) && j.length && j.every((x) => x && typeof x === 'object' && (x as { type?: unknown }).type === 'text')) {
    j = parse(j.map((x) => String((x as { text?: unknown }).text || '')).join(''));
  }
  if (j && typeof j === 'object' && !Array.isArray(j) && 'result' in j && !('results' in j)) {
    const o = j as { result?: unknown; structuredContent?: unknown };
    const inner = typeof o.result === 'string' ? parse(o.result) : o.result;
    if (inner && typeof inner === 'object') return inner;
    if (o.structuredContent && typeof o.structuredContent === 'object') return o.structuredContent;
    return null;
  }
  return j;
}
/** The text of an answer, to read when it isn't whole JSON: the wrapping off, and a cut {"result": "..."} unescaped as
 *  far as it came. */
function textOf(raw: string): string {
  const t = unwrapUntrusted(raw);
  return partialResult(t) ?? t;
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

/** What a recall's answer found: each record's id (where it has one) and its line, in the answer's order; null when
 *  the answer isn't a recall's. */
export function recallFound(output: string | undefined): { found: { id: string; line: string }[]; abstain: boolean } | null {
  if (output === undefined) return null;
  const a = answerOf(output) as { results?: unknown; abstain?: unknown } | null;
  if (!a || typeof a !== 'object' || !Array.isArray(a.results)) return null;
  const found = a.results.flatMap((x) => {
    const record = x && typeof x === 'object' ? (x as { record?: unknown }).record : null;
    const line = saidBy(record);
    const id = record && typeof record === 'object' && typeof (record as { id?: unknown }).id === 'string' ? (record as { id: string }).id : '';
    return line ? [{ id, line }] : [];
  });
  return { found, abstain: !!a.abstain };
}

const things = (n: number) => `${n} ${n === 1 ? 'thing' : 'things'}`;

/** The found list as lines, or null when the answer isn't a recall's. */
export function recallLines(output: string | undefined): string | null {
  if (output === undefined) return null;
  const r = recallFound(output);
  if (!r) {
    // an answer cut short (the record keeps its start): the records' words that arrived whole, said as part of it
    const text = textOf(output);
    if (!/^\s*\{\s*"results"\s*:/.test(text)) return null;
    const words = [...text.matchAll(/"text"\s*:\s*("(?:[^"\\]|\\.)*")/g)].map((m) => { try { return String(JSON.parse(m[1])); } catch { return ''; } })
      .map((t) => t.replace(/\s+/g, ' ').trim()).filter(Boolean).map((t) => (t.length > LINE_MAX ? `${t.slice(0, LINE_MAX - 1).trim()}…` : t));
    return words.length ? ['Some of what it found:', ...words.map((t) => `• ${t}`)].join('\n') : null;
  }
  if (!r.found.length) return r.abstain ? 'Nothing it holds answers this.' : 'Nothing found.';
  return [`Found ${things(r.found.length)}:`, ...r.found.map((t) => `• ${t.line}`)].join('\n');
}

/** How many things a turn's memory searches found, each counted once however many of them found it: 0 where it
 *  searched and found nothing, null where it didn't search (or no answer of one could be read). */
export function recalledIn(m: Pick<AsstMsg, 'blocks'> | null | undefined): number | null {
  let read = false;
  const seen = new Set<string>();
  for (const b of m?.blocks || []) {
    if (b.kind !== 'tools') continue;
    for (const s of b.steps) {
      if (!isRecall(s.name) || s.isError) continue;
      const r = recallFound(s.result);
      if (!r) continue;
      read = true;
      r.found.forEach((x) => seen.add(x.id || `line:${x.line}`));
    }
  }
  return read ? seen.size : null;
}
/** "Recalled N things", for a turn whose searches found something; '' otherwise. */
export const recalledLine = (n: number | null) => (n ? `Recalled ${things(n)}` : '');

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
