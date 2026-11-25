// Duplicate harness gives the copy the harness's own MCP servers and its variables. Until 0.41.14 the copy left them
// behind, so a copy of a harness whose tools sign in with a request header ran its first task with no tools.
import { MEMORIES_ENTRY_ID, PLUGS_ENTRY_ID, type CustomHarness } from '@/lib/harness';
import { duplicateParts, notCopiedLine } from './duplicate';

let mockN = 0;
jest.mock('../mcp/McpSheet', () => ({ newMcpId: () => `mcp.new${++mockN}` }));

const ORIGINAL = {
  id: 'chrn_orig', name: 'notes-agent', base: 'dsh', baseLabel: 'DeepSeek Harness', defaultModel: '',
  systemPrompt: 'Answer from my notes.', skills: [], createdAt: 1,
  mcpServers: [
    // signs in with a header each request sends
    { id: 'mcp.a1b2c3d4', name: 'notes', url: 'https://notes.example/mcp', auth: '$headers.X-Notes-Key', enabled: true, transport: 'http' },
    // a token kept for the organization, by its reference; switched off
    { id: 'mcp.tok', name: 'tracker', url: 'https://tracker.example/mcp', auth: 'vault:harness-mcp-mcp-tok', enabled: false },
    // no sign-in at all
    { id: 'mcp.open', name: 'weather', url: 'https://weather.example/mcp', enabled: true },
    // servers this instance hosts for this harness alone
    { id: 'mcp.database', name: 'orders-db', url: 'https://box.example/v1/mcp/database', auth: 'vault:harness-hosted-chrn-orig-mcp-database', enabled: true },
    { id: 'mcp.media', name: 'media', url: 'https://box.example/v1/mcp/media', auth: 'vault:harness-hosted-chrn-orig-mcp-media', enabled: true },
    // the service's own entries
    { id: PLUGS_ENTRY_ID, name: 'plugs', url: 'https://box.example/v1/mcp/plugs', auth: 'vault:harness-hosted-chrn-orig-mcp-plugs', enabled: true },
    { id: MEMORIES_ENTRY_ID, name: 'memories', url: 'https://box.example/v1/mcp/memories', auth: 'vault:harness-hosted-chrn-orig-mcp-memories', enabled: true },
  ],
  additionalHeaders: ['X-Notes-Key'],
  env: { NOTES_KEY: '$headers.X-Notes-Key', REGION: 'us', API_TOKEN: 'vault:harness-mcp-env-api-token' },
} as CustomHarness;

beforeEach(() => { mockN = 0; });

test('the copy takes its own servers with the same address, auth and on/off, under new ids', () => {
  const p = duplicateParts(ORIGINAL);
  expect(p.mcpServers).toEqual([
    { id: 'mcp.new1', name: 'notes', url: 'https://notes.example/mcp', auth: '$headers.X-Notes-Key', enabled: true, transport: 'http' },
    { id: 'mcp.new2', name: 'tracker', url: 'https://tracker.example/mcp', auth: 'vault:harness-mcp-mcp-tok', enabled: false },
    { id: 'mcp.new3', name: 'weather', url: 'https://weather.example/mcp', enabled: true },
  ]);
  for (const m of p.mcpServers) expect(ORIGINAL.mcpServers.map((o) => o.id)).not.toContain(m.id);
});

test('a server hosted for the original alone is left out and named; the service’s own entries are left to the service', () => {
  const p = duplicateParts(ORIGINAL);
  const names = p.mcpServers.map((m) => m.name);
  for (const n of ['orders-db', 'media', 'plugs', 'memories']) expect(names).not.toContain(n);
  expect(p.notCopied).toEqual(['orders-db', 'media']);
});

test('its variables come along as they are', () => {
  expect(duplicateParts(ORIGINAL).env).toEqual({ NOTES_KEY: '$headers.X-Notes-Key', REGION: 'us', API_TOKEN: 'vault:harness-mcp-env-api-token' });
});

test('the copy shares no list or map with the original, so changing one leaves the other', () => {
  const p = duplicateParts(ORIGINAL);
  p.env.REGION = 'eu';
  p.mcpServers[0].url = 'https://elsewhere.example/mcp';
  expect(ORIGINAL.env).toEqual({ NOTES_KEY: '$headers.X-Notes-Key', REGION: 'us', API_TOKEN: 'vault:harness-mcp-env-api-token' });
  expect(ORIGINAL.mcpServers[0].url).toBe('https://notes.example/mcp');
});

test('a harness with none of these gives empty parts, never undefined', () => {
  const bare = { id: 'h', name: 'b', base: 'pi', baseLabel: 'Pi', defaultModel: '', systemPrompt: '', mcpServers: [], skills: [], createdAt: 1 } as CustomHarness;
  expect(duplicateParts(bare)).toEqual({ mcpServers: [], notCopied: [], env: {} });
});

test('what the sheet says of the servers it leaves out, before Save and after', () => {
  expect(notCopiedLine([], 'before')).toBe('');
  expect(notCopiedLine(['orders-db'], 'before')).toBe('orders-db is tied to this harness, so the copy won’t have it.');
  expect(notCopiedLine(['orders-db', 'media'], 'after')).toBe('orders-db and media are tied to the original, so the copy doesn’t have them.');
  expect(notCopiedLine(['a', 'b', 'c'], 'before')).toBe('a, b and c are tied to this harness, so the copy won’t have them.');
});
