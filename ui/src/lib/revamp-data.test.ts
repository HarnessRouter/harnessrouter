import { p95Of, type TraceCard } from '@/lib/revamp-data';

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
