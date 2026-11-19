import test from 'node:test';
import assert from 'node:assert/strict';
import { formatElapsed } from '../src/reply-details.ts';

test('reply elapsed labels omit unknown values and format recorded durations', () => {
  assert.equal(formatElapsed(null), '');
  assert.equal(formatElapsed(undefined), '');
  assert.equal(formatElapsed(NaN), '');
  assert.equal(formatElapsed(-1), '');
  assert.equal(formatElapsed(0), '用时 0秒');
  assert.equal(formatElapsed(173000), '用时 2分钟 53秒');
});
