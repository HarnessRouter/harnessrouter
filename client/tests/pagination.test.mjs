import test from 'node:test';
import assert from 'node:assert/strict';
import { mergePage, nextOffset } from '../src/pagination.ts';

test('appending overlapping pages updates rows without duplicates or mutating old data', () => {
  const before = [{ id: 1, value: 'old' }, { id: 2, value: 'keep' }];
  assert.deepEqual(mergePage(before, [{ id: 1, value: 'new' }, { id: 3, value: 'added' }]), [
    { id: 1, value: 'new' }, { id: 2, value: 'keep' }, { id: 3, value: 'added' },
  ]);
  assert.equal(before[0].value, 'old');
});

test('server offset and limit advance the cursor even when rows overlap', () => {
  assert.equal(nextOffset({ offset: 40, limit: 20, has_more: true }), 60);
  assert.equal(nextOffset({ offset: 60, limit: 20, has_more: false }), null);
  assert.equal(nextOffset(undefined), null);
});
