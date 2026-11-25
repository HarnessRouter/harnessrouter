import { tokenHost } from './mcp-host';

test('one server per address, read the way the gateway binds it', () => {
  expect(tokenHost('https://GitHub.com./mcp')).toBe('github.com:443');
  expect(tokenHost('https://x.example:8443/m')).toBe('x.example:8443');
  expect(tokenHost('http://x.example/m')).toBe('x.example:80');
  expect(tokenHost('https://bücher.example/m')).toBe('xn--bcher-kva.example:443');
});

test('an address that names no one server is stored without one', () => {
  for (const u of ['', 'not a url', 'ftp://x.example/m', 'https://$headers.X-Host/m', 'https://good.example\\@evil.example/m',
    'https://good.example@evil.example/m', 'https://user:pw@good.example/m', 'https://good.ex\nample/m', 'https://ex%61mple.com/m']) {
    expect(tokenHost(u)).toBe('');
  }
  expect(tokenHost('https://good.example/users/@me')).toBe('good.example:443');   // an @ in the path is not user information
});
