// Where an older console address lives in this console. Shared by the server's redirect for the old
// addresses (src/middleware.ts: the old page never loads, so nothing flashes before the redirect) and
// the shell (a client navigation to an old address), so a bookmark, a link in the docs or an older
// script's URL lands on the same place either way.

/** Where an older console address lives now, or null when it keeps its own page. */
export function movedTo(path: string, q: URLSearchParams): string | null {
  const enc = encodeURIComponent;
  if (path === '/harnesses' || path === '/tasks') {
    const h = q.get('h'), sid = q.get('sid');
    if (h) return `/studio/${enc(h)}${sid ? `?test=${enc(sid)}` : q.get('view') === 'settings' ? '?tab=settings' : ''}`;
    return '/studio';
  }
  const m = path.match(/^\/harnesses\/([^/]+)$/);
  if (m) return `/studio/${m[1]}`;
  if (path === '/dashboard' || path === '/overview' || path === '/quickstart') return '/start';
  if (path === '/kits') return '/shop';
  // a Microsoft 365 sign-in comes back to /plugins with its answer in the query (the address the
  // self-hosting guide registers): the Plugins tab reads it, so the query goes along
  if (path === '/plugins') return `/extensions${q.toString() ? `?${q.toString()}` : ''}`;
  if (path === '/environments') return '/extensions?tab=envs';
  const env = path.match(/^\/environments\/([^/]+)$/);
  if (env) return `/extensions?tab=envs&env=${env[1]}`;
  if (path === '/integrations') return `/byok${q.toString() ? `?${q.toString()}` : ''}`;
  return null;
}
