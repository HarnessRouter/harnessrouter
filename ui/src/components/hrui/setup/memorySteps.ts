// A memory search in a conversation, as a person reads it (the memories spec, C6): what the agent looked for, and a
// list of what it found, in the records' own words. The tool answers the agent in JSON (gateway memory_tools.py,
// memory_recall: {results: [{record: {title, content: [{type, text}]}}], abstain}); shown as it is, that is two hundred
// lines of ids and braces. Each base hands that answer on in its own wrapping, and each wrapping comes off before it
// is read (runner/server.py's normalizers, then the gateway's tool_result, which joins a content list's text):
//   claude, pi, opencode, qwen: the answer's text as it is (claude's and pi's MCP content joined to its text)
//   codex: the MCP CallToolResult itself, {"content": [{type: "text", text}], "structuredContent", "_meta"} (or
//     "structured_content"), and the whole item {"result": null, "error": {"message"}} when the call failed
//   hermes: {"result": "<the text>"} (or the JSON under result, or text beside structuredContent), inside an
//     <untrusted_tool_result> block with a sentence for the model in front of it (hermes
//     agent/tool_dispatch_helpers.py _maybe_wrap_untrusted, tools/mcp_tool.py)
//   gemini: the text, or its function response ([{functionResponse: {response: {content}}}]), or a ```json block
//   any of them: MCP content as a list ([{type: "text", text}])
// A turn read back from its record keeps the start of each answer: an answer cut short is read as far as it came.
// Any other call is left as it is; a recall's answer that isn't that JSON (an error, a sentence) reads as its words.
import type { ToolItem, Turn } from 'reifyui/agent-chat';
import type { AsstMsg } from '@/lib/conversation';

/** memory_recall under whatever name an agent CLI gives a connected server's tool (mcp__memories__memory_recall,
 *  memories.memory_recall, memories__memory_recall, memories_memory_recall, memories/memory_recall). */
export const isRecall = (name: string) => /(^|[_.:/-])memory_recall$/.test(String(name || '').trim());

const parse = (s: string): unknown => { try { return JSON.parse(s) as unknown; } catch { return undefined; } };
const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const isTextPart = (v: unknown): v is { type: 'text'; text?: unknown } => isObj(v) && v.type === 'text';
/** A recall's answer, as the gateway's tool returns it. */
const isRecallAnswer = (v: unknown): v is { results: unknown[]; abstain?: unknown } => isObj(v) && Array.isArray(v.results);

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
/** The text inside a fenced block (```json ... ```), as far as it came; the text unchanged where it isn't one. */
function unfence(s: string): string {
  const m = /^```[\w-]*[ \t]*\n/.exec(s);
  if (!m) return s;
  const body = s.slice(m[0].length);
  const end = body.lastIndexOf('```');
  return (end >= 0 && !body.slice(end + 3).trim() ? body.slice(0, end) : body).trim();
}
/** A tool's answer with the blocks around it off. */
const plainOf = (s: string) => unfence(unwrapUntrusted(s));

type Read = { json: unknown } | { text: string };
/** The text an MCP content list holds, joined; undefined where it holds none. */
function contentText(v: unknown): string | undefined {
  if (!Array.isArray(v)) return undefined;
  const t = v.filter(isTextPart);
  return t.length ? t.map((x) => String(x.text ?? '')).join('') : undefined;
}
/** What a failed call says, where its wrapping carries `error` (a codex item whose call failed). */
function errorText(v: unknown): string | undefined {
  if (typeof v === 'string' && v.trim()) return v.trim();
  return isObj(v) && typeof v.message === 'string' && v.message.trim() ? v.message.trim() : undefined;
}

/** What a tool answered, however the CLI wrapped it: the recall's answer where one is inside, else the first words (or
 *  JSON) found inside. A CallToolResult's structuredContent is read first where it holds the records, then its content. */
function peel(v: unknown, depth = 0): Read {
  if (depth > 8) return { json: v };
  if (typeof v === 'string') {
    const t = plainOf(v);
    const j = parse(t);
    return j === undefined ? { text: t } : peel(j, depth + 1);
  }
  if (Array.isArray(v)) {
    const t = v.length && v.every(isTextPart) ? contentText(v) : undefined;
    if (t !== undefined) return peel(t, depth + 1);
    // Gemini's function response: [{functionResponse: {name, response: {content: [...]}}}]
    const fr = v.length === 1 && isObj(v[0]) && isObj(v[0].functionResponse) ? v[0].functionResponse.response : undefined;
    return fr !== undefined ? peel(fr, depth + 1) : { json: v };
  }
  if (!isObj(v) || isRecallAnswer(v)) return { json: v };
  const inner: { v: unknown; words?: true }[] = [
    { v: v.structuredContent }, { v: v.structured_content }, { v: contentText(v.content) }, { v: v.result }, { v: v.Ok },
    { v: v.response }, { v: errorText(v.error), words: true },
  ];
  let first: Read | null = null;
  for (const x of inner) {
    if (x.v === undefined || x.v === null) continue;
    const r: Read = x.words ? { text: String(x.v) } : peel(x.v, depth + 1);
    if ('json' in r && isRecallAnswer(r.json)) return r;
    first ??= r;
  }
  return first ?? { json: v };
}

// ── an answer cut short (a turn's record keeps the start of each answer) ─────────────────────────────────────────
/** Where a JSON string whose characters start at `at` (just past its opening quote) ends: its closing quote, or -1
 *  where it was cut before it closed. */
function stringEnd(s: string, at: number): number {
  for (let i = at; i < s.length; i++) {
    if (s[i] === '\\') { i++; continue; }
    if (s[i] === '"') return i;
  }
  return -1;
}
/** A JSON string's characters as far as they came, unescaped (an escape cut in half goes); null where they aren't. */
function stringFrom(s: string, at: number): string | null {
  const end = stringEnd(s, at);
  let body = end >= 0 ? s.slice(at, end) : s.slice(at);
  if (end < 0) {
    // an escape cut in half: a lone backslash, or \u and fewer than four digits (never an escaped backslash)
    const m = /\\(u[0-9a-fA-F]{0,3})?$/.exec(body);
    if (m) {
      let before = 0;
      for (let i = m.index - 1; i >= 0 && body[i] === '\\'; i--) before++;
      if (before % 2 === 0) body = body.slice(0, m.index);
    }
  }
  const v = parse(`"${body}"`);
  return typeof v === 'string' ? v : null;
}
// the wrappings whose text holds the answer, as their JSON starts: Hermes's {"result": "...", codex's content list,
// a bare content list
const STRING_HOLDERS = [
  /^\{\s*"result"\s*:\s*"/,
  /^\{\s*"content"\s*:\s*\[\s*\{\s*(?:"type"\s*:\s*"text"\s*,\s*)?"text"\s*:\s*"/,
  /^\[\s*\{\s*(?:"type"\s*:\s*"text"\s*,\s*)?"text"\s*:\s*"/,
];
const RESULTS_START = /^\{\s*"results"\s*:\s*\[/;
/** The start of a recall's answer inside an answer cut short, whatever wrapped it; null where there is none. */
function cutRecall(raw: string): string | null {
  let t = plainOf(raw);
  for (let i = 0; i < 4; i++) {
    if (RESULTS_START.test(t)) return t;
    const under = /^\{\s*"(?:result|structuredContent|structured_content)"\s*:\s*(?=\{)/.exec(t);
    if (under) { t = t.slice(under[0].length); continue; }
    const holder = STRING_HOLDERS.map((re) => re.exec(t)).find(Boolean);
    if (!holder) return null;
    const inner = stringFrom(t, holder[0].length);
    if (inner === null) return null;
    t = plainOf(inner);
  }
  return null;
}
const jsonString = (m: RegExpExecArray | RegExpMatchArray | null): string => {
  const v = m ? parse(m[1]) : undefined;
  return typeof v === 'string' ? v : '';
};
const STR = '("(?:[^"\\\\]|\\\\.)*")';
/** The results that came of a recall's answer cut short: each that came whole, and the one cut in the middle as far
 *  as its own words came whole (its id, its title, its text). `whole`: the list itself closed, so every result came. */
function cutResults(t: string): { results: unknown[]; whole: boolean } {
  const at = RESULTS_START.exec(t);
  if (!at) return { results: [], whole: false };
  const out: unknown[] = [];
  let depth = 0, from = -1;
  for (let i = at[0].length; i < t.length; i++) {
    const c = t[i];
    if (c === '"') { const e = stringEnd(t, i + 1); if (e < 0) break; i = e; continue; }
    if (c === '{' || c === '[') { if (depth === 0) from = i; depth++; continue; }
    if (c === '}' || c === ']') {
      if (depth === 0) return { results: out, whole: true };
      depth--;
      if (depth === 0 && from >= 0) { const v = parse(t.slice(from, i + 1)); if (v !== undefined) out.push(v); from = -1; }
    }
  }
  if (from >= 0) {
    const part = t.slice(from);
    const id = jsonString(new RegExp(`"record"\\s*:\\s*\\{\\s*"id"\\s*:\\s*${STR}`).exec(part));
    const title = jsonString(new RegExp(`"title"\\s*:\\s*${STR}`).exec(part));
    const texts = [...part.matchAll(new RegExp(`"text"\\s*:\\s*${STR}`, 'g'))].map(jsonString).filter(Boolean);
    if (title.trim() || texts.length) out.push({ record: { id, title, content: texts.map((text) => ({ type: 'text', text })) } });
  }
  return { results: out, whole: false };
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
/** Each found record's id (where it has one) and its line, in the answer's order. */
const foundIn = (results: unknown[]) => results.flatMap((x) => {
  const record = x && typeof x === 'object' ? (x as { record?: unknown }).record : null;
  const line = saidBy(record);
  const id = record && typeof record === 'object' && typeof (record as { id?: unknown }).id === 'string' ? (record as { id: string }).id : '';
  return line ? [{ id, line }] : [];
});

/** What a recall's answer found: each record's id and line, whether nothing it holds answers (`abstain`), and whether
 *  the answer was cut short (`cut`: then what is listed is what came, and there may be more). Null when the answer
 *  isn't a recall's. */
export function recallFound(output: string | undefined): { found: { id: string; line: string }[]; abstain: boolean; cut: boolean } | null {
  if (output === undefined) return null;
  const a = peel(output);
  if ('json' in a && isRecallAnswer(a.json)) return { found: foundIn(a.json.results), abstain: !!a.json.abstain, cut: false };
  const t = cutRecall(output);
  if (t === null) return null;
  // cut after its list of results closed: every result came, only what follows it was cut
  const { results, whole } = cutResults(t);
  return { found: foundIn(results), abstain: whole && /"abstain"\s*:\s*true/.test(t), cut: !whole };
}
/** A recall's answer that isn't JSON (an error, a sentence), its wrapping off; null where it came unwrapped. */
function wordsOf(output: string | undefined): string | null {
  if (output === undefined) return null;
  const a = peel(output);
  return 'text' in a && a.text.trim() && a.text !== output.trim() ? a.text : null;
}

const things = (n: number) => `${n} ${n === 1 ? 'thing' : 'things'}`;

/** The found list as lines; a recall's answer that isn't JSON as its words, its wrapping off; null when there is
 *  nothing to say other than what came (the step then shows it as it is). */
export function recallLines(output: string | undefined): string | null {
  if (output === undefined) return null;
  const r = recallFound(output);
  if (r?.cut) return r.found.length ? ['Some of what it found:', ...r.found.map((t) => `• ${t.line}`)].join('\n') : null;
  if (r) {
    if (!r.found.length) return r.abstain ? 'Nothing it holds answers this.' : 'Nothing found.';
    return [`Found ${things(r.found.length)}:`, ...r.found.map((t) => `• ${t.line}`)].join('\n');
  }
  // not a recall's answer: what it says (an error, a sentence), where it came wrapped
  return wordsOf(output);
}

/** What a turn's memory searches found: how many things, each counted once however many searches found it (0 where
 *  it searched and found nothing), and whether an answer was cut short (so there may be more); null where it didn't
 *  search (or no answer of one could be read). */
export interface SearchesFound { n: number; cut: boolean }
export function recalledIn(m: Pick<AsstMsg, 'blocks'> | null | undefined): SearchesFound | null {
  let read = false, cut = false;
  const seen = new Set<string>();
  for (const b of m?.blocks || []) {
    if (b.kind !== 'tools') continue;
    for (const s of b.steps) {
      if (!isRecall(s.name) || s.isError) continue;
      const r = recallFound(s.result);
      if (!r) continue;
      read = true;
      if (r.cut) cut = true;
      r.found.forEach((x) => seen.add(x.id || `line:${x.line}`));
    }
  }
  return read ? { n: seen.size, cut } : null;
}
/** "Recalled N things", for a turn that recalled something: what its searches found, and what the platform recalled
 *  for it as it began (`atStart`, the turn record's memory.recalled_at_start). The two can be the same things and only
 *  the searches name theirs, so N is the larger, never their sum; "at least" where the larger came from an answer cut
 *  short. '' when it recalled nothing. */
export function recalledLine(found: SearchesFound | null, atStart = 0): string {
  const s = found?.n || 0, a = atStart > 0 ? Math.floor(atStart) : 0;
  const n = Math.max(s, a);
  if (!n) return '';
  return `Recalled ${found?.cut && s >= a ? 'at least ' : ''}${things(n)}`;
}
/** Where the things came from, for the line's title: as the task began, from its own searches, or both. */
export function recalledTitle(found: SearchesFound | null, atStart = 0): string {
  const s = found?.n || 0, a = atStart > 0 ? Math.floor(atStart) : 0;
  return [a ? `${things(a)} recalled as the task began` : '', s ? `${found?.cut ? 'at least ' : ''}${things(s)} found by its own searches` : '']
    .filter(Boolean).join('; ');
}

/** A recall call as a person reads it: what it looked for (no memory id) and what it found. */
export function readableStep(item: ToolItem): ToolItem {
  if (!isRecall(item.name)) return item;
  let a: Record<string, unknown> = {};
  try { a = JSON.parse(item.args || '{}') as Record<string, unknown>; } catch { return item; }
  const asked = [a.query, a.text].find((v) => typeof v === 'string' && v.trim()) as string | undefined;
  // a call that failed says why, in its words; one that answered, what it found
  const lines = item.status === 'failed' ? wordsOf(item.output) : recallLines(item.output);
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
