import { GET as shareGET } from '@/app/api/share/[...path]/route';
import { GET as workspaceGET } from '@/app/[harness]/[sid]/workspace/[...fpath]/route';
import { publicShareResponseHeaders } from './public-artifact-response';
import type { NextRequest } from 'next/server';

const request = new Request('https://console.test/') as NextRequest;
const originalFetch = global.fetch;
afterEach(() => { global.fetch = originalFetch; });

function expectIsolated(headers: Headers) {
  const csp = headers.get('content-security-policy')!;
  const sandbox = csp.split(';').find((part) => part.trim().startsWith('sandbox'))!;
  expect(sandbox).toContain('allow-scripts');
  expect(sandbox).not.toContain('allow-same-origin');
  expect(headers.get('cache-control')).toBe('private, no-store');
  expect(headers.get('x-content-type-options')).toBe('nosniff');
}

test.each(['text/html', 'image/svg+xml', 'application/xhtml+xml', 'text/plain', 'text/css'])('%s public artifacts are isolated even from an older gateway', async (media) => {
  const bytes = new Uint8Array([60, 115, 99, 114, 105, 112, 116, 62, 0, 255]);
  const fetchMock = jest.fn().mockImplementation(async () => new Response(bytes, {
    headers: { 'content-type': media, 'cache-control': 'public, max-age=300', 'set-cookie': 'unexpected=value' },
  }));
  global.fetch = fetchMock;
  const share = await shareGET(request, { params: Promise.resolve({ path: ['token', 'f', 'file'] }) });
  const workspace = await workspaceGET(request, { params: Promise.resolve({ harness: 'h', sid: 's', fpath: ['file'] }) });
  for (const response of [share, workspace]) {
    expect(response.status).toBe(200);
    expectIsolated(response.headers);
    expect(response.headers.get('content-type')).toBe(media);
    expect(response.headers.has('set-cookie')).toBe(false);
    expect(new Uint8Array(await response.arrayBuffer())).toEqual(bytes);
  }
  for (const [, options] of fetchMock.mock.calls) {
    expect(options).toEqual({ cache: 'no-store' });
  }
});

test('an upstream restrictive CSP survives in addition to the local sandbox', () => {
  const headers = publicShareResponseHeaders(new Headers({
    'content-security-policy': "default-src 'none'",
    'content-length': '100',
    'access-control-allow-origin': '*',
  }), true);
  expect(headers.get('content-security-policy')).toContain("default-src 'none', sandbox allow-scripts");
  expect(headers.has('content-length')).toBe(false);
  expect(headers.has('access-control-allow-origin')).toBe(false);
});

test.each([200, 404])('public metadata status %s remains JSON and cannot be cached', async (status) => {
  global.fetch = jest.fn().mockResolvedValue(new Response('{"detail":"view"}', {
    status, headers: { 'content-type': 'application/json', 'cache-control': 'public, max-age=300' },
  }));
  const response = await shareGET(request, { params: Promise.resolve({ path: ['token', 'meta'] }) });
  expect(response.status).toBe(status);
  expect(response.headers.get('cache-control')).toBe('private, no-store');
  expect(await response.json()).toEqual({ detail: 'view' });
});

test('unreachable public artifact upstream produces an uncached error', async () => {
  global.fetch = jest.fn().mockRejectedValue(new Error('unreachable'));
  const response = await shareGET(request, { params: Promise.resolve({ path: ['token', 'f', 'index.html'] }) });
  expect(response.status).toBe(502);
  expectIsolated(response.headers);
  expect(await response.json()).toEqual({ detail: 'share upstream unreachable' });
});
