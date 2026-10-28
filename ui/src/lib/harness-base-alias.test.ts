/** @jest-environment jsdom */
// A setup made through the API can name its base by the backend it runs (`claude`); it is named and drawn as that base all
// the same (as on the hosted console, where such setups read "claude", with no mark, on the setup list and cards).

jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
jest.mock('@/lib/auth', () => ({ getSession: () => ({ orgId: 'org.a', member: { email: 'ana@example.com' } }) }));
jest.mock('@/lib/workspace', () => ({ workspaceHeaders: () => ({}), appendWorkspaceQuery: () => {} }));

import { OOB, oobById } from '@/lib/harness';
import { BACKEND_BASE, harnessLogoSrc } from '@/components/HarnessLogo';

test('every base whose backend is named apart from it is found and drawn by that backend', () => {
  const apart = OOB.filter((o) => o.backend !== o.id);
  expect(apart.length).toBeGreaterThan(0);
  for (const o of apart) {
    const backend = String(o.backend);
    expect(oobById(backend)?.id).toBe(o.id);
    expect(BACKEND_BASE[backend]).toBe(o.id);
    expect(harnessLogoSrc(backend)).toBe(harnessLogoSrc(o.id));
  }
  expect(oobById('claude')?.name).toBe('Claude Code');
  expect(harnessLogoSrc('claude')).toBe('/logos/claude.png');
});

test('a base id still wins over a backend of the same name, and an unknown one stays unknown', () => {
  expect(oobById('codex')?.id).toBe('codex');
  expect(oobById('no-such-base')).toBeNull();
  expect(harnessLogoSrc('no-such-base')).toBe('');
});
