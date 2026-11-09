/** @jest-environment jsdom */
// The two agent harnesses whose CLIs take a task's prompt only as an argument carry one line wherever a person picks
// or sees one as a setup's, on a self-hosted instance; no other harness does, and hosted says nothing.

jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
jest.mock('@/lib/auth', () => ({ getSession: () => ({ orgId: 'org.a', member: { email: 'ana@example.com' } }) }));
jest.mock('@/lib/workspace', () => ({ workspaceHeaders: () => ({}), appendWorkspaceQuery: () => {} }));

const LINE = 'With this agent, other tasks on the same machine can see what it’s asked while it works.';

function load(selfHosted: boolean) {
  let mod: typeof import('@/lib/harness') | undefined;
  jest.isolateModules(() => {
    jest.doMock('@/lib/edition', () => ({ LOCAL_MEMBER: 'local@localhost', LOCAL_ORG: 'local', SELF_HOSTED: selfHosted }));
    mod = require('@/lib/harness');
  });
  return mod as typeof import('@/lib/harness');
}

test('self-hosted, jcode and kimi carry the line, by base id or by backend, and no other harness does', () => {
  const { OOB, promptSeenNote } = load(true);
  expect(promptSeenNote('jcode')).toBe(LINE);
  expect(promptSeenNote('kimi')).toBe(LINE);
  const others = OOB.filter((o) => o.backend !== 'jcode' && o.backend !== 'kimi');
  expect(others.length).toBeGreaterThan(10);
  for (const o of others) expect(promptSeenNote(o.id)).toBeNull();
  expect(promptSeenNote('')).toBeNull();
  expect(promptSeenNote(undefined)).toBeNull();
});

test('hosted, nothing is said: one session per sandbox', () => {
  const { promptSeenNote } = load(false);
  expect(promptSeenNote('jcode')).toBeNull();
  expect(promptSeenNote('kimi')).toBeNull();
});
