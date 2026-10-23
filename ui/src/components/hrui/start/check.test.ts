/** @jest-environment jsdom */
// New setup's first test is handed to the setup's page once: the request the build wrote, waiting in
// the box (never sent for the person). It is kept for the tab, so the page load that opens the setup
// still finds it; it stays readable for a moment after it is taken (React mounts a page twice), then
// it is gone, and one left for minutes is dropped.
import { handFirstTest, takeFirstTest } from './check';

beforeEach(() => { sessionStorage.clear(); jest.useRealTimers(); });

test('the first test is handed over once, marked as New setup’s, and then it is gone', () => {
  jest.useFakeTimers();
  handFirstTest('chrn_1', { input: 'Review the payment clause.', send: false, free: false });
  expect(takeFirstTest('chrn_1')).toEqual({ input: 'Review the payment clause.', send: false, free: false, setup: true });
  // a second mount right after reads the same one
  expect(takeFirstTest('chrn_1')).toMatchObject({ input: 'Review the payment clause.' });
  jest.advanceTimersByTime(1500);
  expect(takeFirstTest('chrn_1')).toBeNull();
});

test('a page load in between still finds it, from the tab', () => {
  handFirstTest('chrn_2', { input: 'x', send: false, free: false });
  const kept = sessionStorage.getItem('hr.first:chrn_2');
  expect(kept && JSON.parse(kept)).toMatchObject({ input: 'x', send: false });
});

test('another setup has none; one left more than a few minutes is dropped', () => {
  expect(takeFirstTest('chrn_none')).toBeNull();
  sessionStorage.setItem('hr.first:chrn_old', JSON.stringify({ input: 'x', send: false, free: false, at: Date.now() - 6 * 60_000 }));
  expect(takeFirstTest('chrn_old')).toBeNull();
});
