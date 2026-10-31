// Serve a Starter Kit's app out of the image.
//
// The apps are built at image build time into /opt/harnessrouter/kits/<kit>/app (see
// docker/install-kits.sh), so there is nothing to deploy at launch: the kit's UI is already here,
// and Launch only provisions the Harness behind it.
//
// A route handler rather than Next's static serving because these files are not part of this
// app's build — they arrive from another repository, and which ones exist depends on what the
// image was built with. Unknown paths fall through to index.html because a kit app is a SPA and
// its client-side routes must survive a reload. A kit that was renamed keeps its old address: an
// id listed in a kit's `aliases` (kit.json) is sent on to the kit's current one.
import { NextResponse, type NextRequest } from 'next/server';
import { promises as fs } from 'node:fs';
import path from 'node:path';

export const dynamic = 'force-dynamic';

const KITS_DIR = process.env.HR_KITS_DIR || '/opt/harnessrouter/kits';

const TYPES: Record<string, string> = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8', '.svg': 'image/svg+xml',
  '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif',
  '.webp': 'image/webp', '.ico': 'image/x-icon', '.woff': 'font/woff', '.woff2': 'font/woff2',
  '.ttf': 'font/ttf', '.otf': 'font/otf', '.map': 'application/json; charset=utf-8',
};

const SLUG = /^[a-z0-9][a-z0-9-]{0,63}$/;

const readJson = (file: string) => fs.readFile(file, 'utf8').then((t) => JSON.parse(t)).catch(() => null);

/** The kit in this image that lists `id` among its `aliases` (the ids it had before a rename), or
 *  null. Read from the kits themselves, so a rename is one line in its kit.json and nothing here. */
async function renamedTo(id: string): Promise<string | null> {
  const manifest = await readJson(path.join(KITS_DIR, 'manifest.json'));
  for (const kid of Array.isArray(manifest?.kits) ? manifest.kits : []) {
    if (!SLUG.test(String(kid))) continue;
    const k = await readJson(path.join(KITS_DIR, String(kid), 'kit.json'));
    if (Array.isArray(k?.aliases) && k.aliases.includes(id)) return String(kid);
  }
  return null;
}

export async function GET(req: NextRequest, ctx: { params: Promise<{ kit: string; path?: string[] }> }) {
  const { kit, path: rest } = await ctx.params;
  // The kit id names a directory, so it must not be able to name a different one. Anything but
  // a plain slug is refused outright rather than normalised into something that looks safe.
  if (!SLUG.test(kit || '')) {
    return new NextResponse('Not found', { status: 404 });
  }
  if (!(await fs.stat(path.join(KITS_DIR, kit)).then((st) => st.isDirectory()).catch(() => false))) {
    // An old id of a renamed kit: the same page under the current one, the query kept. The
    // Location is relative, so it names whatever host the person reached this console by.
    const to = await renamedTo(kit);
    if (!to) return new NextResponse('Not found', { status: 404 });
    const where = `/kits/${to}/${(rest || []).map(encodeURIComponent).join('/')}${req.nextUrl.search}`;
    return new NextResponse(null, { status: 308, headers: { location: where } });
  }
  const root = path.join(KITS_DIR, kit, 'app');
  const wanted = (rest || []).join('/');

  // Resolve, then prove the result is still inside the kit's own directory. Checking the input
  // for '..' instead would miss encodings and symlinks; checking the resolved path cannot.
  const target = path.resolve(root, wanted || 'index.html');
  const inside = target === root || target.startsWith(root + path.sep);

  // What we actually served, so the content type describes the bytes rather than the request.
  let served = wanted || 'index.html';
  let file: Buffer | null = inside ? await fs.readFile(target).catch(() => null) : null;

  // SPA fallback: a client-side route is not a missing file. Asset extensions are exempt — a
  // missing .js served as HTML produces a syntax error in the console instead of a 404, which is
  // a much worse thing to debug.
  if (!file && !/\.[a-z0-9]+$/i.test(wanted)) {
    file = await fs.readFile(path.join(root, 'index.html')).catch(() => null);
    served = 'index.html';
  }
  if (!file) return new NextResponse('Not found', { status: 404 });

  const ext = path.extname(served).toLowerCase();
  const headers = new Headers();
  headers.set('content-type', TYPES[ext] || 'application/octet-stream');
  headers.set('x-content-type-options', 'nosniff');
  // Vite fingerprints its assets, so they are safe to cache hard; index.html must not be, or a
  // rebuilt kit keeps loading the previous bundle.
  headers.set('cache-control', ext === '.html' ? 'no-store' : 'public, max-age=31536000, immutable');
  return new NextResponse(new Uint8Array(file), { status: 200, headers });
}
