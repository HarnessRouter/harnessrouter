/** @jest-environment jsdom */
// The task a setup was made with is handed to its page once (New setup: the sentence the person sent
// runs as the setup's first task as its page opens). Taking it forgets it, in this page and in the tab,
// so a reload, a second visit or a re-render never runs it twice.
import { peekFirstTask, setFirstTask, takeFirstTask } from './seed';

beforeEach(() => { sessionStorage.clear(); });

test('the first task is handed over once, and then it is gone', () => {
  setFirstTask('chrn_1', 'Generate a product image');
  expect(peekFirstTask('chrn_1')).toBe('Generate a product image');
  expect(takeFirstTask('chrn_1')).toBe('Generate a product image');
  expect(takeFirstTask('chrn_1')).toBe('');
  expect(peekFirstTask('chrn_1')).toBe('');
});

test('the tab keeps it for the page load that opens the setup, and taking it there forgets it too', () => {
  setFirstTask('chrn_2', 'Review this contract');
  expect(sessionStorage.getItem('hr.first:chrn_2')).toBe('Review this contract');
  expect(takeFirstTask('chrn_2')).toBe('Review this contract');
  expect(sessionStorage.getItem('hr.first:chrn_2')).toBeNull();
});

test('nothing to hand over: no id, an empty sentence, or another setup', () => {
  setFirstTask('', 'x');
  setFirstTask('chrn_3', '   ');
  expect(peekFirstTask('chrn_3')).toBe('');
  setFirstTask('chrn_4', 'mine');
  expect(takeFirstTask('chrn_5')).toBe('');
  expect(peekFirstTask('chrn_4')).toBe('mine');
});
