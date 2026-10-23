// readSettled: a read a page waits on always ends (2026-10-19 06:03Z, a stalled store left Extensions
// on its skeleton). One quiet second try; the error within about 15 seconds of asking.
import { readSettled, ReadTimeout, withDeadline } from './settle';

const never = <T,>() => new Promise<T>(() => { /* no answer */ });

beforeEach(() => { jest.useFakeTimers(); });
afterEach(() => { jest.useRealTimers(); });

test('an answer on the first try is the answer, asked once', async () => {
  const read = jest.fn(async () => 'rows');
  await expect(readSettled(read)).resolves.toBe('rows');
  expect(read).toHaveBeenCalledTimes(1);
});

test('a failed first try is asked once more, after a short pause', async () => {
  const read = jest.fn().mockRejectedValueOnce(new Error('503')).mockResolvedValueOnce('rows');
  const out = readSettled(read);
  await jest.advanceTimersByTimeAsync(999);
  expect(read).toHaveBeenCalledTimes(1);
  await jest.advanceTimersByTimeAsync(1);
  await expect(out).resolves.toBe('rows');
  expect(read).toHaveBeenCalledTimes(2);
});

test('two failures reject with the second', async () => {
  const read = jest.fn().mockRejectedValueOnce(new Error('first')).mockRejectedValueOnce(new Error('second'));
  const out = readSettled(read);
  out.catch(() => { /* asserted below */ });
  await jest.advanceTimersByTimeAsync(1000);
  await expect(out).rejects.toThrow('second');
  expect(read).toHaveBeenCalledTimes(2);
});

test('a read with no answer is cancelled at 10 s, asked again, and the whole read rejects at 15 s', async () => {
  const signals: AbortSignal[] = [];
  const read = jest.fn((signal: AbortSignal) => { signals.push(signal); return never<string>(); });
  let failed: unknown = null;
  readSettled(read).catch((e) => { failed = e; });
  await jest.advanceTimersByTimeAsync(10_000);
  expect(signals[0].aborted).toBe(true);
  expect(signals[0].reason).toBeInstanceOf(ReadTimeout);
  await jest.advanceTimersByTimeAsync(1_000);
  expect(read).toHaveBeenCalledTimes(2);
  expect(failed).toBeNull();
  await jest.advanceTimersByTimeAsync(4_000);
  expect(failed).toBeInstanceOf(ReadTimeout);
  expect(signals[1].aborted).toBe(true);
});

test('a deadline holds even for a read that ignores its signal', async () => {
  let failed: unknown = null;
  withDeadline(() => never<string>(), 500).catch((e) => { failed = e; });
  await jest.advanceTimersByTimeAsync(500);
  expect(failed).toBeInstanceOf(ReadTimeout);
});

test('a read that throws before it returns a promise still settles', async () => {
  const read = jest.fn(() => { throw new Error('sync'); });
  const out = readSettled(read as unknown as (s: AbortSignal) => Promise<string>);
  out.catch(() => { /* asserted below */ });
  await jest.advanceTimersByTimeAsync(1000);
  await expect(out).rejects.toThrow('sync');
});
