// A reply as Markdown, for its Copy reply button (Playground.tsx; Richard 10-18): its text exactly as
// the agent wrote it (headings, lists, tables and code fences as they are), its parts in order, and
// the files it made as links to their own names. Any address the reply wrote stays in its text as
// written; a file's link is never an address the console made (a download needs your sign-in, and a
// signed address must not travel in a copy).
import type { RespFile } from '@/lib/chat';
import type { Block } from '@/lib/conversation';

const label = (name: string) => (name.split('/').pop() || name).replace(/([[\]\\])/g, '\\$1');

/** `files`: the reply's own files, the console's internal ones already left out. */
export function replyMarkdown(blocks: Block[], files: RespFile[]): string {
  const text = blocks
    .filter((b): b is Extract<Block, { kind: 'text' }> => b.kind === 'text' && !b.error)
    .map((b) => b.text.replace(/\s+$/, ''))
    .filter((t) => t.trim())
    .join('\n\n');
  const named = files.filter((f) => f.filename);
  if (!named.length) return text;
  const list = named.map((f) => `- [${label(f.filename)}](${encodeURI(f.filename)})`).join('\n');
  return [text, list].filter(Boolean).join('\n\n');
}
