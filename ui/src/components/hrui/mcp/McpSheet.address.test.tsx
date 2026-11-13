/** @jest-environment jsdom */
// A stored token goes only to the server it was stored for: moving the server says so until a token is pasted.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

jest.mock('@/lib/auth', () => ({ authFetch: jest.fn(), getSession: () => ({}) }));
jest.mock('@/lib/harness', () => ({ ...jest.requireActual('@/lib/harness'), storeMcpSecret: jest.fn(async () => 'vault:harness-mcp-new') }));

import { storeMcpSecret } from '@/lib/harness';
import { McpSheet, authFor } from './McpSheet';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let root: Root; let el: HTMLElement;
afterEach(() => { act(() => root.unmount()); el.remove(); document.body.innerHTML = ''; });

function type(input: HTMLInputElement, value: string) {
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  act(() => { set.call(input, value); input.dispatchEvent(new Event('input', { bubbles: true })); });
}

test('moving a server with a stored token says the token stays with the old one, until one is pasted', async () => {
  el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el);
  await act(async () => { root.render(<McpSheet server={{ id: 'mcp.1', name: 'gh', url: 'https://mcp.good.example/mcp', auth: 'vault:harness-mcp-mcp-1', enabled: true } as never}
    keptAuth="vault:harness-mcp-mcp-1" nameTaken={() => ''} onSave={jest.fn(async () => '')} onClose={() => {}} />); });
  const moved = () => document.getElementById('mcTokMoved')?.textContent || '';
  expect(moved()).toBe('');
  const url = document.querySelector('input[type="url"], #mcUrl, input[id*="Url"]') as HTMLInputElement;
  type(url, 'https://other.example/mcp');
  expect(moved()).toBe('The stored token is sent only to mcp.good.example. Paste it again to use it at this address.');
  type(url, 'https://MCP.good.example:443/v2');            // the same server at another path
  expect(moved()).toBe('');
  type(url, 'https://other.example/mcp');
  type(document.getElementById('mcTok') as HTMLInputElement, 'new-token');
  expect(moved()).toBe('');
});

test('a token is stored for the address it is saved with', async () => {
  await authFor('mcp.2', ' tok ', undefined, 'https://mcp.good.example/mcp');
  expect(storeMcpSecret).toHaveBeenCalledWith('mcp.2', 'tok', 'https://mcp.good.example/mcp');
  await expect(authFor('mcp.2', '$headers.X-Tok', undefined, 'https://x.example')).resolves.toBe('$headers.X-Tok');
});
