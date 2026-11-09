// What a branch starts with (issue #477), and whether a server offers one at all.
import type { AsstMsg, Msg } from '@/lib/conversation';

const mockDoc: { value: unknown; fail: boolean; status: number; url: string } = { value: null, fail: false, status: 200, url: '' };
jest.mock('@/lib/hfetch', () => ({
  harnessFetch: async (url: string) => {
    mockDoc.url = url;
    if (mockDoc.fail) throw new Error('down');
    return { ok: mockDoc.status < 300, status: mockDoc.status, json: async () => mockDoc.value };
  },
}));

import { branchableTurns, branchMsgs, importedTurnCount, sessionBranching } from './branch';

const asst = (text: string, over: Partial<AsstMsg> = {}): AsstMsg => ({ role: 'assistant', blocks: [{ kind: 'text', text }], files: [], status: 'done', ...over });
const MSGS: Msg[] = [{ role: 'user', text: 'a' }, asst('one'), { role: 'user', text: 'b' }, asst('two'), { role: 'user', text: 'c' }, asst('three')];

describe('sessionBranching', () => {
  beforeEach(() => { mockDoc.fail = false; mockDoc.status = 200; });
  test('it asks the protocol’s discovery document, where the capability is', async () => {
    mockDoc.value = { capabilities: { session_branching: true } };
    await sessionBranching();
    expect(mockDoc.url).toBe('/api/harness/v1/uhp');
  });
  test.each([
    [{ capabilities: { session_branching: true } }, true],
    [{ capabilities: { session_branching: false } }, false],
    [{ capabilities: { session_branching: 'yes' } }, false],
    [{ capabilities: {} }, false],
    [{}, false],
    [null, false],
  ])('%j is %s', async (doc, want) => {
    mockDoc.value = doc as Record<string, unknown> | null;
    await expect(sessionBranching()).resolves.toBe(want);
  });
  test('a discovery read that fails offers nothing', async () => {
    mockDoc.fail = true;
    await expect(sessionBranching()).resolves.toBe(false);
  });
  test('a discovery read the server refuses offers nothing', async () => {
    mockDoc.status = 503; mockDoc.value = { capabilities: { session_branching: true } };
    await expect(sessionBranching()).resolves.toBe(false);
  });
});

describe('branchMsgs', () => {
  test('ends at the reply, whichever it is', () => {
    expect(branchMsgs(MSGS, MSGS[1])).toHaveLength(2);
    expect(branchMsgs(MSGS, MSGS[3])).toHaveLength(4);
    expect(branchMsgs(MSGS, MSGS[5])).toHaveLength(6);
  });
  test('every message is marked imported, and the original conversation is left as it was', () => {
    const out = branchMsgs(MSGS, MSGS[3]);
    expect(out.every((m) => m.imported)).toBe(true);
    expect(MSGS.some((m) => m.imported)).toBe(false);
  });
  test('a question the reply ended on stays with the original', () => {
    const asked = asst('which?', { status: 'incomplete', incompleteReason: 'input_required', inputRequest: { id: 'q1', kind: 'free_text', prompt: 'Which?' } });
    const msgs: Msg[] = [{ role: 'user', text: 'a' }, asked];
    const last = branchMsgs(msgs, asked)[1] as AsstMsg;
    expect(last.inputRequest).toBeUndefined();
    expect(last.status).toBe('incomplete');
    expect(asked.inputRequest?.id).toBe('q1');
  });
  test('a reply that is not in the conversation brings nothing', () => {
    expect(branchMsgs(MSGS, asst('elsewhere'))).toEqual([]);
  });
});

describe('importedTurnCount', () => {
  test('counts the turns brought along, by their answers', () => {
    expect(importedTurnCount(MSGS)).toBe(0);
    expect(importedTurnCount([...branchMsgs(MSGS, MSGS[3]), { role: 'user', text: 'new' }, asst('new')])).toBe(2);
  });
});

describe('branchableTurns', () => {
  test('a turn is offered only where it says it can be branched', () => {
    expect(branchableTurns([{ branchable: true }, { branchable: false }, {}])).toEqual([true, false, false]);
  });
  test('anything but true is not: a server that does not say is not guessed for', () => {
    expect(branchableTurns([{ branchable: 'yes' as unknown as boolean }, { branchable: null as unknown as boolean }])).toEqual([false, false]);
    expect(branchableTurns([])).toEqual([]);
  });
});
