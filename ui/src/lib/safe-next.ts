// Where a sign-in may send the browser next: a path on this site, or the default.
//
// The value comes from the address bar (`/login?next=...`), so anyone can write it into a link and
// hand it to someone about to sign in. Sent to another site, that person lands there straight after
// typing their password on ours (reported privately, GHSA-59mq-hx4p-fw48). Only a path that starts
// with a single "/" passes, and the URL parser has the last word. Refused, each one a way a browser
// would leave the site:
//   https://evil.example, javascript:...   absolute or scheme-bearing
//   //evil.example                          scheme-relative
//   /\evil.example, \\evil.example          a backslash, which browsers read as "/"
//   /%2F%2Fevil.example, /%5Cevil.example   an encoded slash or backslash
//   /<tab>/evil.example                     a tab or line break, which browsers drop before parsing
// The middleware only ever writes a plain path here, so nothing it sends is refused.
const SITE = 'https://site.invalid';

export function safeNext(raw: string | null | undefined, fallback = '/harnesses'): string {
  const v = String(raw ?? '');
  if (!v.startsWith('/') || v.startsWith('//')) return fallback;
  if (/[\\\u0000-\u001f\u007f]/.test(v)) return fallback;
  if (/%(2f|5c)/i.test(v)) return fallback;
  let u: URL;
  try {
    u = new URL(v, SITE);
  } catch {
    return fallback;
  }
  if (u.origin !== SITE) return fallback;
  return u.pathname + u.search + u.hash;
}
