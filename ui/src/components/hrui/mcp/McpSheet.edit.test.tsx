/** @jest-environment jsdom */
// Editing an MCP server never lists the setups that use it (Richard, 2026-10-21: "delete Used by"); saving keeps them.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

jest.mock('@/lib/auth', () => ({ authFetch: jest.fn(), getSession: () => ({}) }));

import { McpSheet } from './McpSheet';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let root: Root; let el: HTMLElement;
afterEach(() => { act(() => root.unmount()); el.remove(); document.body.innerHTML = ''; });

test('editing: no Used by list, and Save keeps the setups it had', async () => {
  const onSave = jest.fn(async () => '');
  el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el);
  await act(async () => { root.render(<McpSheet server={{ name: 'docs', url: 'https://example.com/mcp', enabled: true } as never}
    targets={[{ id: 'h.a', name: 'Alpha', base: 'claude', headers: [] }, { id: 'h.b', name: 'Beta', base: 'codex', headers: [] }] as never}
    initialTo={['h.a']} nameTaken={() => ''} onSave={onSave} onClose={() => {}} />); });
  expect(document.body.textContent).not.toContain('Used by');
  expect(document.body.querySelector('.mcp-opt')).toBeNull();
  const save = Array.from(document.body.querySelectorAll('button')).find((b) => b.textContent === 'Save') as HTMLButtonElement | undefined;
  if (save) {
    await act(async () => { save.click(); });
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ to: ['h.a'] }));
  }
});
