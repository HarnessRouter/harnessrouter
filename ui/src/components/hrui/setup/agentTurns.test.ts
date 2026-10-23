// A finished answer's thoughts read finished (Richard, 10-18: a loading indicator that kept going over
// a thought). The record ends a turn even when its live stream dropped before the end reached the
// turn's clock; the clock's thought then still reads open, and the view drew "Thinking" in motion
// under an answer that was over. Once the turn has ended nothing in it is live: a thought shows as
// done, with how long it took when both its ends were seen.
import { newTurn, reduceTurn } from 'reifyui/agent-chat';
import type { AsstMsg } from '@/lib/conversation';
import { viewTurn } from './AgentTurns';

// a clock that saw the thought start and then lost the stream (no end, no response.completed)
function droppedClock() {
  let c = newTurn({ startedAt: 1000 });
  c = reduceTurn(c, { type: 'response.created', response: { id: 'resp_1' } }, 1000);
  c = reduceTurn(c, { type: 'response.output_item.added', output_index: 0, item: { type: 'reasoning', id: 'rs_1', summary: [] } }, 1200);
  c = reduceTurn(c, { type: 'response.reasoning_summary_text.delta', item_id: 'rs_1', output_index: 0, delta: 'Reading the file first.' }, 1300);
  return c;
}
const msg = (status: AsstMsg['status'], clock = droppedClock()): AsstMsg => ({
  role: 'assistant', status, files: [], clock,
  blocks: [{ kind: 'tools', reasoning: 'Reading the file first.', steps: [] }, { kind: 'text', text: 'Done.' }],
} as unknown as AsstMsg);
const thought = (m: AsstMsg) => viewTurn(m, null).items.find((x) => x.kind === 'thinking') as { open?: boolean; endedAt: number | null };

test.each(['done', 'failed', 'cancelled', 'incomplete'] as const)('a %s turn whose stream dropped shows its thought finished', (st) => {
  const t = thought(msg(st));
  expect(!!t.open && t.endedAt == null).toBe(false);
});

test('a running turn keeps its thought live', () => {
  const t = thought(msg('running'));
  expect(t.open).toBe(true);
  expect(t.endedAt).toBeNull();
});

test('a thought whose end was seen keeps its duration', () => {
  let c = droppedClock();
  c = reduceTurn(c, { type: 'response.output_item.done', output_index: 0, item: { type: 'reasoning', id: 'rs_1', summary: [] } }, 7300);
  const t = viewTurn(msg('done', c), null).items.find((x) => x.kind === 'thinking') as { startedAt: number | null; endedAt: number | null };
  expect(t.startedAt).toBe(1200);
  expect(t.endedAt).toBe(7300);
});
