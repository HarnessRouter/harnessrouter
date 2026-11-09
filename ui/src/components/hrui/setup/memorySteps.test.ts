// A memory search in a conversation reads as what was looked for and what was found, never as the JSON the agent was
// given (the memories walkthrough, 11-09: 202 lines of ids and braces under "Used Memories · memory recall").
import type { ToolItem, Turn } from 'reifyui/agent-chat';
import { isRecall, readableStep, readableTurn, recallLines } from './memorySteps';

const rec = (title: string, text = '') => ({ id: `r-${title || text}`, memory_id: 'hmem_x', type: 'fact', title, content: text ? [{ type: 'text', text }] : [] });
const answer = (results: unknown[], extra: object = {}) => JSON.stringify({ results: results.map((record) => ({ record, memory: { id: 'hmem_x' }, score: 0.7 })), degraded: [], abstain: false, ...extra }, null, 1);
const call = (o: Partial<ToolItem> = {}): ToolItem => ({ kind: 'tool', id: 'c1', name: 'mcp__memories__memory_recall', args: JSON.stringify({ memory: 'hmem_x', query: 'Dana preferences' }),
  output: answer([rec('', 'User’s name is Dana and they are from Larkspur Bakery.'), rec('Prefers written steps')]), status: 'done', startedAt: null, endedAt: null, ...o });

test('it knows a recall under every name a CLI gives a connected server’s tool, and nothing else', () => {
  expect(['mcp__memories__memory_recall', 'memories.memory_recall', 'memories__memory_recall', 'memory_recall'].every(isRecall)).toBe(true);
  expect(['mcp__memories__memory_remember', 'memory_recall_all', 'grep'].some(isRecall)).toBe(false);
});

test('what it found is a list in the records’ own words, and what it looked for has no memory id', () => {
  const s = readableStep(call());
  expect(s.output).toBe('Found 2 things:\n• User’s name is Dana and they are from Larkspur Bakery.\n• Prefers written steps');
  expect(JSON.parse(s.args)).toEqual({ 'Looked for': 'Dana preferences' });
  expect(s.args).not.toContain('hmem_x');
});

test('nothing found says so; nothing it holds answers says that', () => {
  expect(recallLines(answer([]))).toBe('Nothing found.');
  expect(recallLines(answer([], { abstain: true }))).toBe('Nothing it holds answers this.');
});

test('an answer the CLI wrapped as MCP content reads the same', () => {
  expect(recallLines(JSON.stringify([{ type: 'text', text: answer([rec('One thing')]) }]))).toBe('Found 1 thing:\n• One thing');
});

test('an answer cut short says what arrived whole, as part of what it found', () => {
  const cut = answer([rec('', 'First fact.'), rec('', 'Second fact.')]).slice(0, -40);
  expect(recallLines(cut)).toBe('Some of what it found:\n• First fact.\n• Second fact.');
});

test('anything else is left as it is: another tool, a failure, an answer that isn’t a recall’s', () => {
  const other = call({ name: 'mcp__memories__memory_remember' });
  expect(readableStep(other)).toBe(other);
  const failed = call({ status: 'failed', output: 'This agent holds no memory.' });
  expect(readableStep(failed).output).toBe('This agent holds no memory.');
  expect(readableStep(call({ output: 'Name the memory.' })).output).toBe('Name the memory.');
});

test('a turn without a recall is handed back untouched', () => {
  const t = { items: [{ kind: 'text', id: 't', text: 'Hi' }] } as unknown as Turn;
  expect(readableTurn(t)).toBe(t);
  const withOne = { items: [call()] } as unknown as Turn;
  expect((readableTurn(withOne).items[0] as ToolItem).output).toContain('Found 2 things');
});
