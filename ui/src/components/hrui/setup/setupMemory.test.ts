/** @jest-environment jsdom */
// A setup's own memory goes with the setup (the memories polish round, C5 and C11): deleting the setup says that its
// memory goes too, with what it holds, unless another setup uses it, and says after what the service did; renaming
// the setup renames a memory still named after it. Only where the service made the memory for the setup
// (`memory.provisioned`): otherwise nothing is said and nothing is done.
jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
import { harnessFetch } from '@/lib/hfetch';
import { service } from '../memories/fixtures';
import {
  autoMemoryDescription, autoMemoryName, deletedToast, followRename, memoryOnDelete, memoryOnDeleteLine, memoryRenameOf, ownMemoryOf,
} from './setupMemory';

const H = 'chrn_a';
const harness = (memory: object | null) => ({ id: H, name: 'Support', memory });
const OWN = { id: 'hmem_a', name: 'Support', engine: 'mem0', scope: 'per_user', reason: '', observe: true, provisioned: true };
const mem = (o: object = {}) => ({ id: 'hmem_a', object: 'memory', name: 'Support', description: autoMemoryDescription('Support'), provider: 'mem0', engine: 'mem0',
  parent_id: null, ancestors: [], restricted: false, privileges: ['read', 'write', 'create', 'delete'], records: { count: 0 }, children: { count: 2 }, used_by: [{ harness_id: H, name: 'Support' }], ...o });
const use = (routes: Record<string, unknown>) => { const s = service(routes); (harnessFetch as jest.Mock).mockImplementation(s.fetcher); return s; };

test('the memory a setup’s record names, and whether the service made it for the setup', () => {
  expect(ownMemoryOf(harness(OWN))).toEqual({ id: 'hmem_a', name: 'Support', engine: 'mem0', provisioned: true });
  expect(ownMemoryOf(harness({ ...OWN, provisioned: undefined }))?.provisioned).toBe(false);
  expect(ownMemoryOf(harness(null))).toBeNull();
  expect(ownMemoryOf({ id: H })).toBeNull();
});

test('delete: its memory goes too, with every fact it and the people below it hold', async () => {
  use({
    [`GET /v1/harnesses/${H}`]: harness(OWN),
    'GET /v1/memories/hmem_a': mem(),
    'GET /v1/memories': { data: [{ ...mem(), id: 'hmem_p1', records: { count: 4 } }, { ...mem(), id: 'hmem_p2', records: { count: 1 } }] },
  });
  const x = await memoryOnDelete(H);
  expect(x).toEqual({ name: 'Support', engine: 'mem0', count: 5, others: [] });
  expect(memoryOnDeleteLine(x)).toBe('This also deletes its memory (5 facts), unless another agent uses it.');
});

test('delete: a memory another setup uses stays, and the dialog says who', async () => {
  use({ [`GET /v1/harnesses/${H}`]: harness(OWN), 'GET /v1/memories/hmem_a': mem({ children: { count: 0 }, records: { count: 3 }, used_by: [{ harness_id: H, name: 'Support' }, { harness_id: 'chrn_b', name: 'Billing' }] }) });
  expect(memoryOnDeleteLine(await memoryOnDelete(H))).toBe('Its memory, Support, stays: Billing uses it too.');
});

test('delete: a count that can’t be said is left out, and a memory the setup was given is not mentioned', async () => {
  use({ [`GET /v1/harnesses/${H}`]: harness(OWN), 'GET /v1/memories/hmem_a': mem(), 'GET /v1/memories': { data: [{ ...mem(), id: 'hmem_p1', records: { count: null } }] } });
  expect(memoryOnDeleteLine(await memoryOnDelete(H))).toBe('This also deletes its memory, unless another agent uses it.');
  use({ [`GET /v1/harnesses/${H}`]: harness({ ...OWN, provisioned: false }) });
  expect(await memoryOnDelete(H)).toBeNull();
  // a service before 0.40 says nothing of a memory
  use({ [`GET /v1/harnesses/${H}`]: { id: H, name: 'Support' } });
  expect(memoryOnDeleteLine(await memoryOnDelete(H))).toBe('');
  expect(memoryOnDeleteLine({ name: 'Notes', engine: 'graphiti', count: 1, others: [] })).toBe('This also deletes its memory (1 record), unless another agent uses it.');
});

test('deleted: the toast says what the service did with the memory, and nothing of it where it said nothing', () => {
  expect(deletedToast('Support', { deleted: true, memory_deleted: true })).toBe('Support deleted, and its memory with it.');
  expect(deletedToast('Support', { deleted: true, memory_kept: true })).toBe('Support deleted. Its memory stays: another agent uses it.');
  expect(deletedToast('Support', { deleted: true, memory_kept: { id: 'hmem_a', used_by: [{ harness_id: 'chrn_b', name: 'Billing' }] } })).toBe('Support deleted. Its memory stays: Billing uses it.');
  expect(deletedToast('Support', { deleted: true })).toBe('Support deleted');
  expect(deletedToast('Support', {})).toBe('Support deleted');
});

test('rename: a memory still named after the setup follows it, its description too; one a person renamed keeps its name', () => {
  const made = { name: autoMemoryName('Support'), description: autoMemoryDescription('Support') };
  expect(memoryRenameOf('Support', 'Customer care', made, true)).toEqual({ name: 'Customer care', description: 'What Customer care remembers from its work.' });
  expect(memoryRenameOf('Support', 'Customer care', { ...made, description: 'Our own words.' }, true)).toEqual({ name: 'Customer care' });
  expect(memoryRenameOf('Support', 'Customer care', { ...made, name: 'Dana’s notes' }, true)).toBeNull();
  expect(memoryRenameOf('Support', 'Customer care', made, false)).toBeNull();
  expect(memoryRenameOf('Support', 'Support', made, true)).toBeNull();
  // the service cuts a long name where it made the memory, so the cut name is the one it still carries
  const long = 'x'.repeat(130);
  expect(memoryRenameOf(long, 'Short', { name: long.slice(0, 120), description: '' }, true)).toEqual({ name: 'Short' });
});

test('rename: through the memory update route, and only for a memory the service made for the setup', async () => {
  const s = use({ 'GET /v1/memories/hmem_a': mem(), 'PUT /v1/memories/hmem_a': (c: { body: unknown }) => ({ ...mem(), ...(c.body as object) }) });
  expect(await followRename(harness(OWN), 'Support', 'Customer care')).toBe(true);
  expect(s.sent('PUT', '/v1/memories/hmem_a')[0].body).toEqual({ name: 'Customer care', description: 'What Customer care remembers from its work.' });
  const t = use({ 'GET /v1/memories/hmem_a': mem() });
  expect(await followRename(harness({ ...OWN, provisioned: false }), 'Support', 'Customer care')).toBe(false);
  expect(await followRename({ id: H }, 'Support', 'Customer care')).toBe(false);
  expect(t.calls).toHaveLength(0);
});
