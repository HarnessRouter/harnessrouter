import test from 'node:test';
import assert from 'node:assert/strict';
import { createWorkspaceRestorer } from '../src/workspace-restoration.ts';

test('workspace restoration distinguishes loading, failure and a restored null selection', async () => {
  const seen = [];
  const unavailable = new Error('unavailable');
  let read = () => Promise.reject(unavailable);
  const restorer = createWorkspaceRestorer(() => read(), state => seen.push(state));
  assert.equal(await restorer.load(), false);
  assert.deepEqual(seen, [{ status: 'loading' }, { status: 'error', cause: unavailable }]);
  read = () => Promise.resolve({ workspaces: [], selected_id: null });
  assert.equal(await restorer.load(), true);
  assert.deepEqual(seen.slice(2), [{ status: 'loading' }, { status: 'ready', value: { workspaces: [], selected_id: null } }]);
});

test('late success or failure cannot replace a newer workspace or an expired session', async () => {
  const seen = [];
  const pending = [];
  const restorer = createWorkspaceRestorer(() => new Promise((resolve, reject) => pending.push({ resolve, reject })), state => seen.push(state));
  const staleSuccess = restorer.load();
  const staleFailure = restorer.load();
  const latest = restorer.load();
  pending[2].resolve({ workspaces: [{ id: 9, name: 'current', description: '' }], selected_id: 9 });
  await latest;
  const committed = [...seen];
  pending[0].resolve({ workspaces: [], selected_id: null });
  pending[1].reject(new Error('stale failure'));
  await Promise.all([staleSuccess, staleFailure]);
  assert.deepEqual(seen, committed);
  const expired = restorer.load();
  restorer.invalidate();
  const invalidated = [...seen];
  pending[3].resolve({ workspaces: [], selected_id: null });
  await expired;
  assert.deepEqual(seen, invalidated);
});
