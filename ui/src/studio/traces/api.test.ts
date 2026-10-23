// A trace's events as the console reads them (Richard, 10-19: no fallbacks). The whole compact
// transcript in one read; where that fails, every chunk the manifest names, one by one. A trace that
// could not be read throws, and one with a chunk missing is never handed back as whole: either would
// draw "No events recorded." or a trace cut short as if it were the record.
const harnessFetch = jest.fn();
jest.mock('@/lib/hfetch', () => ({ harnessFetch: (...a: unknown[]) => harnessFetch(...a) }));
jest.mock('@/lib/auth', () => ({ getSession: () => ({ orgId: 'org.a', member: { email: 'ana@example.com' } }) }));

import { tracesApi } from './api';

const nd = (...evs: object[]) => evs.map((e) => JSON.stringify(e)).join('\n');
const ok = (text: string) => ({ ok: true, status: 200, text: async () => text });
const bad = (status: number) => ({ ok: false, status, text: async () => '' });

beforeEach(() => harnessFetch.mockReset());

test('the correct path: the whole compact transcript in one read', async () => {
  harnessFetch.mockResolvedValueOnce(ok(nd({ type: 'user' }, { type: 'result' })));
  expect(await tracesApi.events('hsess1', [])).toEqual([{ type: 'user' }, { type: 'result' }]);
  expect(harnessFetch).toHaveBeenCalledWith('/api/harness/v1/traces/hsess1/all?compact=1');
});

test('where the one read fails, every chunk the manifest names', async () => {
  harnessFetch.mockResolvedValueOnce(bad(502)).mockResolvedValueOnce(ok(nd({ n: 0 }))).mockResolvedValueOnce(ok(nd({ n: 1 })));
  expect(await tracesApi.events('hsess1', [{}, {}])).toEqual([{ n: 0 }, { n: 1 }]);
});

test('nothing read throws, never [] ("No events recorded.")', async () => {
  harnessFetch.mockResolvedValueOnce(bad(502));
  await expect(tracesApi.events('hsess1', [])).rejects.toThrow('502');
  harnessFetch.mockRejectedValueOnce(new TypeError('Failed to fetch'));
  await expect(tracesApi.events('hsess1', null)).rejects.toThrow();
  harnessFetch.mockResolvedValueOnce(bad(502)).mockResolvedValueOnce(bad(503));
  await expect(tracesApi.events('hsess1', [{}])).rejects.toThrow('503');
});

test('a chunk missing throws: a trace cut short is never handed back as whole', async () => {
  harnessFetch.mockResolvedValueOnce(bad(502)).mockResolvedValueOnce(ok(nd({ n: 0 }))).mockResolvedValueOnce(bad(500));
  await expect(tracesApi.events('hsess1', [{}, {}])).rejects.toThrow('chunk 1');
});
