import { p95Of, timeAgo, type TraceCard } from '@/lib/revamp-data';

// The gateway stamps `elapsed` to one decimal (app.py rounds the turn's seconds), so a value like
// 119.7 is the normal case rather than a corner: the p95 column read it as "1m 60s".
const cards = (...elapsed: number[]): TraceCard[] => elapsed.map((e) => ({ session_id: 's', elapsed: e }));

test('a p95 whose seconds round up carries into the minutes', () => {
  expect(p95Of(cards(5, 9, 119.7))).toBe('2m 00s');
  expect(p95Of(cards(5, 9, 59.7))).toBe('1m 00s');
});

test('a p95 that needs no carry reads exactly as it did', () => {
  expect(p95Of(cards(5, 9, 90))).toBe('1m 30s');
  expect(p95Of(cards(5, 9, 12.4))).toBe('12s');
  expect(p95Of(cards(5, 9, 61))).toBe('1m 01s');
});

test('a minute that rounds to sixty is an hour, and an hour that rounds to twenty-four is a day', () => {
  const MIN = 60_000, DAY = 86_400_000;
  expect(timeAgo(Date.now() - 59.5 * MIN)).toBe('1 hr ago');
  expect(timeAgo(Date.now() - (DAY - 1))).toBe('1d ago');
  expect(timeAgo(Date.now() - 30 * MIN)).toBe('30 min ago');
  expect(timeAgo(Date.now() - 90 * MIN)).toBe('2 hr ago');
  expect(timeAgo(Date.now() - 3 * DAY)).toBe('3d ago');
  expect(timeAgo(Date.now() - 10_000)).toBe('just now');
});
