/** The server a stored MCP token is kept for: "host:port" from its http(s) address, the host lowercased with any
 *  trailing dot dropped and the default port filled in, as the gateway reads it. '' for an address that names no one
 *  server: unreadable, not http(s), a host filled in per task ($headers.…), or one parsers read differently (a
 *  backslash, user information, whitespace or a control character, a percent sign in the host). The gateway binds
 *  nothing to those, so a token is then stored without an address. */
export function tokenHost(url?: string): string {
  const raw = (url || '').trim();
  // eslint-disable-next-line no-control-regex
  if (!raw || /[\\\s\u0000-\u001f\u007f]/.test(raw)) return '';
  const authority = /^[a-z][a-z0-9+.-]*:\/\/([^/?#]*)/i.exec(raw)?.[1] ?? '';
  if (/[@%]/.test(authority)) return '';            // user information, or a host a parser decodes first
  try {
    const x = new URL(raw);
    const port = x.port || (x.protocol === 'https:' ? '443' : x.protocol === 'http:' ? '80' : '');
    const host = x.hostname.toLowerCase().replace(/\.$/, '');
    return port && host && !/[$%]/.test(host) ? `${host}:${port}` : '';
  } catch {
    return '';
  }
}
