jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn(async () => ({ ok: true, json: async () => ({ ref: 'vault:harness-mcp-x' }) })) }));
jest.mock('@/lib/auth', () => ({ getSession: () => ({ orgId: 'org1', member: { email: 'ana@example.com' } }) }));

import { harnessFetch } from '@/lib/hfetch';
import { storeMcpSecret } from './harness';

const sent = () => JSON.parse(((harnessFetch as jest.Mock).mock.calls.at(-1)?.[1] as { body: string }).body);

test('a token is stored with the address of the server it is for', async () => {
  await expect(storeMcpSecret('mcp.1', 't0k', ' https://mcp.good.example/mcp ')).resolves.toBe('vault:harness-mcp-x');
  expect(sent()).toEqual({ token: 't0k', url: 'https://mcp.good.example/mcp' });
});

test('an address that names no one server is left out', async () => {
  await storeMcpSecret('mcp.1', 't0k', 'https://$headers.X-Host/mcp');
  expect(sent()).toEqual({ token: 't0k' });
  await storeMcpSecret('mcp.1', 't0k');
  expect(sent()).toEqual({ token: 't0k' });
});
