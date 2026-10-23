// A connected plugin's row says something a person can read: Microsoft 365 says how people use it (and its
// directory by name when known), never its two ids side by side.
import { accountOf, type Row } from './pluginParts';

const row = (config: Record<string, unknown>): Row => ({
  key: 'microsoft365', name: 'Microsoft 365', desc: 'desc', mark: undefined,
  p: { type: 'microsoft365', label: 'Microsoft 365', source: 'local', official: true, status: 'connected', config,
       secrets_set: ['client_secret'], secrets_needed: [], config_fields: [], version: 1, tools: 0 },
} as unknown as Row);

test('Microsoft 365 as each person: the way it is used, not its ids', () => {
  const a = accountOf(row({ tenant_id: 'e89476d8-de43-4956-ad54-8911aeaa0dae', client_id: '4173a4b0-cfed-4fa7-be88-b442ce3dc47d' }));
  expect(a).toEqual({ text: 'Each person signs in with Microsoft', mono: false });
  expect(a.text).not.toMatch(/[0-9a-f]{8}-/);
});

test('as the application, with its directory named', () => {
  expect(accountOf(row({ mode: 'application', directory: 'contoso.onmicrosoft.com', tenant_id: 'x', client_id: 'y' })).text)
    .toBe('contoso.onmicrosoft.com · Runs as the application');
});
