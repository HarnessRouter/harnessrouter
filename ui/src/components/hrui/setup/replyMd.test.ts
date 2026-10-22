// Copy reply: the reply's Markdown exactly as written, its parts in order, its files as links to their
// own names, and nothing the console made (its error lines, a download address).
import { replyMarkdown } from './replyMd';
import type { Block } from '@/lib/conversation';

const md = '# Plan\n\n- one\n- two\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n```ts\nconst x = 1;\n```\n';

test('the text as written, headings, lists, tables and code fences kept', () => {
  expect(replyMarkdown([{ kind: 'text', text: md }], [])).toBe(md.replace(/\s+$/, ''));
});

test('its parts in order, the work between them and the console’s own error lines left out', () => {
  const blocks: Block[] = [
    { kind: 'text', text: 'First part.' },
    { kind: 'tools', reasoning: 'thinking', steps: [] },
    { kind: 'text', text: 'Second part.\n' },
    { kind: 'text', text: 'stream error', error: true },
  ];
  expect(replyMarkdown(blocks, [])).toBe('First part.\n\nSecond part.');
});

test('its files as links to their own names, never to an address', () => {
  const files = [
    { container_id: 'c1', file_id: 'f1', filename: 'mug v3.png', url: 'https://example.test/signed?sig=abc' },
    { container_id: 'c1', file_id: 'f2', filename: 'out/report.md' },
  ];
  const out = replyMarkdown([{ kind: 'text', text: 'Here you go.' }], files);
  expect(out).toBe('Here you go.\n\n- [mug v3.png](mug%20v3.png)\n- [report.md](out/report.md)');
  expect(out).not.toContain('sig=');
});

test('a reply of files alone is just their list', () => {
  expect(replyMarkdown([], [{ container_id: 'c', file_id: 'f', filename: 'a.csv' }])).toBe('- [a.csv](a.csv)');
});
