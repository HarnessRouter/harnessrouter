// A read of a setup's tasks that failed is never an empty list (2026-10-19: under a burst the console's
// proxy dropped some of 43 reads, each failure read as "no tasks", and Studio drew Connected setups as
// "Not connected · No tasks yet"). Each failure says so once in the browser console, with the setup and
// the answer.
jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
jest.mock('@/lib/auth', () => ({ getSession: jest.fn(() => ({ orgId: 'org.t', member: { email: 'me@example.com' } })) }));
jest.mock('@/lib/workspace', () => ({ appendWorkspaceQuery: jest.fn() }));

import { harnessFetch } from '@/lib/hfetch';
import { fetchHarnessTasks, TasksReadError } from '@/lib/revamp-data';

const hf = harnessFetch as jest.Mock;
const answer = (status: number, body: string, type = 'application/json') =>
  hf.mockResolvedValueOnce(new Response(body, { status, headers: { 'content-type': type } }));
let warn: jest.SpyInstance;
beforeEach(() => { hf.mockReset(); warn = jest.spyOn(console, 'warn').mockImplementation(() => {}); });
afterEach(() => warn.mockRestore());

test('a page of tasks reads as the server lists it, an empty list included', async () => {
  answer(200, JSON.stringify({ sessions: [{ session_id: 's1', status: 'completed' }], cursor: 'c2' }));
  await expect(fetchHarnessTasks('chrn_a')).resolves.toEqual({ sessions: [{ session_id: 's1', status: 'completed' }], cursor: 'c2' });
  answer(200, JSON.stringify({ sessions: [], cursor: '' }));
  await expect(fetchHarnessTasks('chrn_a')).resolves.toEqual({ sessions: [], cursor: '' });
  expect(warn).not.toHaveBeenCalled();
});

test('an error answer, a page that is not the list, and no answer all reject, each with one console line', async () => {
  answer(502, 'Bad gateway', 'text/plain');
  await expect(fetchHarnessTasks('chrn_a')).rejects.toBeInstanceOf(TasksReadError);
  expect(warn).toHaveBeenLastCalledWith('Task list read failed: tasks of chrn_a: HTTP 502');

  answer(200, '<!doctype html><title>console</title>', 'text/html');
  await expect(fetchHarnessTasks('chrn_b')).rejects.toMatchObject({ harness: 'chrn_b' });
  expect(warn).toHaveBeenLastCalledWith('Task list read failed: tasks of chrn_b: HTTP 200, not a task list');

  hf.mockRejectedValueOnce(new TypeError('Failed to fetch'));
  await expect(fetchHarnessTasks('chrn_c')).rejects.toMatchObject({ status: 'no answer' });
  expect(warn).toHaveBeenLastCalledWith('Task list read failed: tasks of chrn_c: no answer');
  expect(warn).toHaveBeenCalledTimes(3);
});

test('a read its caller cancels rejects without a console line of its own', async () => {
  const ctl = new AbortController();
  ctl.abort();
  hf.mockRejectedValueOnce(new DOMException('aborted', 'AbortError'));
  await expect(fetchHarnessTasks('chrn_a', '', { signal: ctl.signal })).rejects.toThrow('aborted');
  expect(warn).not.toHaveBeenCalled();
});
