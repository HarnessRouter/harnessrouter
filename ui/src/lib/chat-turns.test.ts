// A task's turns that could not be read are never a task with no turns (the gateway answers 503 when
// it cannot read a conversation): loadSessionTurns throws, and only a 404 is a task that is gone.
import { loadSessionTurns, TurnsReadError } from './chat';
import { harnessFetch } from '@/lib/hfetch';

jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
jest.mock('@/lib/auth', () => ({ getSession: () => null }));
jest.mock('@/lib/workspace', () => ({ workspaceHeaders: () => ({}) }));
jest.mock('reifyui', () => ({ pumpResponsesStream: jest.fn(), readSSEStream: jest.fn() }));

const answer = (status: number, body: unknown) =>
  (harnessFetch as jest.Mock).mockResolvedValue({ ok: status < 400, status, json: async () => body });

test('a read the gateway could not answer throws, never answers no turns', async () => {
  answer(503, { error: { type: 'server_error', code: 'server_error' } });
  const err = await loadSessionTurns('hsess1').catch((e) => e);
  expect(err).toBeInstanceOf(TurnsReadError);
  expect(err.status).toBe(503);
});

test('a body that is not the turns throws too', async () => {
  answer(200, { nothing: true });
  await expect(loadSessionTurns('hsess1')).rejects.toBeInstanceOf(TurnsReadError);
});

test('a task that is gone is a 404, and says so', async () => {
  answer(404, { error: { code: 'session_not_found' } });
  await expect(loadSessionTurns('hsess1')).resolves.toEqual({ turns: [], lastResponseId: null, missing: true });
});

test('the turns, as read', async () => {
  answer(200, { turns: [{ id: 'resp_1', status: 'completed', user: 'hi', assistant: 'Done.' }], last_response_id: 'resp_1' });
  const r = await loadSessionTurns('hsess1');
  expect(r.turns.map((t) => t.id)).toEqual(['resp_1']);
  expect(r.lastResponseId).toBe('resp_1');
  expect(r.missing).toBeUndefined();
});
