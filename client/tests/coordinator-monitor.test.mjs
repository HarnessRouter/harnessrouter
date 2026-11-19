import test from 'node:test';
import assert from 'node:assert/strict';
import { watchCoordinatorRun } from '../src/coordinator-monitor.ts';

function harness(initial) {
  let receive, disconnect;
  const timers = new Set(), changes = [], connections = [];
  let reads = 0, subscriptions = 0, closed = 0;
  let readValue = initial;
  const stop = watchCoordinatorRun(initial, {
    read: async () => { reads++; if (readValue instanceof Error) throw readValue; return readValue; },
    watch: (_id, change, fail) => { subscriptions++; receive = change; disconnect = fail; return () => { closed++; }; },
    onChange: value => changes.push(value), onConnection: value => connections.push(value),
    schedule: fn => { timers.add(fn); return fn; }, cancel: fn => timers.delete(fn),
  });
  return {
    stop, changes, connections, timers,
    get subscriptions() { return subscriptions; }, get reads() { return reads; }, get closed() { return closed; },
    receive: value => receive(value), disconnect: () => disconnect(), set: value => { readValue = value; },
    tick: async () => { const fn = timers.values().next().value; timers.delete(fn); await fn?.(); },
  };
}
const run = (id, status = 'running') => ({ id, task_id: id + 100, status, nodes: [] });

test('one disconnected stream recovers by reading without disrupting the other stream', async () => {
  const a = harness(run(1)), b = harness(run(2));
  a.disconnect(); a.disconnect();
  assert.equal(a.timers.size, 1);
  b.receive(run(2, 'completed'));
  a.set(run(1)); await a.tick();
  assert.equal(a.reads, 1); assert.equal(a.subscriptions, 2);
  assert.equal(b.changes.at(-1).status, 'completed');
  a.stop(); b.stop();
  assert.equal(a.timers.size, 0);
});

test('waiting runs keep observing external decisions and terminal runs stop polling', async () => {
  const h = harness(run(1, 'waiting_human'));
  assert.equal(h.subscriptions, 0); assert.equal(h.timers.size, 1);
  h.set(run(1)); await h.tick();
  assert.equal(h.subscriptions, 1);
  h.receive(run(1, 'completed'));
  assert.equal(h.timers.size, 0);
  h.receive(run(1));
  assert.equal(h.changes.at(-1).status, 'completed');
  h.stop();
});

test('a stopped observer rejects late reads and snapshots from another run', async () => {
  const h = harness(run(1));
  h.receive(run(2)); assert.equal(h.changes.length, 0);
  h.stop(); h.receive(run(1, 'failed'));
  assert.equal(h.changes.length, 0); assert.equal(h.timers.size, 0);
});

test('permission loss stops recovery instead of repeatedly reading private data', async () => {
  const h = harness(run(1));
  h.disconnect(); h.set(Object.assign(new Error('需要登录'), { status: 401 })); await h.tick();
  assert.equal(h.timers.size, 0);
  assert.equal(h.connections.at(-1), 'unavailable');
  h.stop();
});
