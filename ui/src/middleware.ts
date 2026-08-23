// The gate for a self-hosted instance that anyone can reach.
//
// Self-hosted has no accounts service, and on a machine only you can reach that is the right
// answer — a login would be ceremony with nothing behind it. The moment the box has a public URL
// that stops being true: the console creates harnesses, reads every task transcript, and runs an
// agent with your provider key. So exposure needs a gate, and the gate ships INSIDE the image
// rather than in whatever proxy happens to sit in front, because `docker run -p 3000:3000` on a
// cloud host must be safe by default and not by configuration.
//
// Middleware is the chokepoint deliberately: pages, the /api/harness proxy, static assets and any
// route added later all pass through here, so no individual handler can forget to check.
//
//   HR_AUTH_USER / HR_AUTH_PASSWORD   the initial credentials. Defaults are published in the
//                                     README, so an instance still running them is open to
//                                     anyone who read it. Change them here or on the profile
//                                     page, which stores them on the data volume and wins.
//   HR_AUTH_DISABLED=1                no gate at all. Only for a box nobody else can reach.
import { NextResponse, type NextRequest } from 'next/server';
import { AUTH_DISABLED, SELF_HOSTED, SESSION_COOKIE, sessionValid } from '@/lib/selfhost-auth';

// Static assets shipped IN the image: brand marks, icons, fonts. They are public by
// construction — baked into a published container and containing no user data — so gating them
// protects nothing and breaks the login page, which needs its own logo before anyone can sign in.
const STATIC_ASSET = /\.(svg|png|jpe?g|gif|webp|avif|ico|woff2?|ttf|otf|css|js|map)$/i;

/** An API call authenticating with a user-minted key (Authorization: Bearer sk-hr-…).
 *  The GATEWAY is the authority on those keys — it resolves the org from the key and answers
 *  401 itself when the key is bad — but this gate ran first and rejected every bearer-only
 *  request on the cookie check alone, which made the keys the console's own Keys page mints
 *  unusable on self-host (and made the UHP conformance suite, which authenticates exactly
 *  this way, unrunnable). Only the API proxy is opened, and only for a bearer in the key's
 *  own format: pages and everything else stay cookie-gated. */
function isApiKeyCall(req: NextRequest, path: string): boolean {
  if (!path.startsWith('/api/harness/')) return false;
  // ANY bearer, not just well-formed keys: an invalid credential must get the gateway's own
  // 401 (error.type authentication_error, UHP-Version header) — the shape UHP check A-02
  // requires — not this gate's sign-in JSON. The proxy attaches internal trust only for
  // cookie-authenticated callers, so a bearer-only request stands or falls on its key alone.
  return (req.headers.get('authorization') || '').toLowerCase().startsWith('bearer ');
}

/** Reachable without a session: the login page, the endpoints it posts to, and static assets.
 *  Everything else is an allow-list miss, so a route added later is gated by default. */
function isPublic(path: string): boolean {
  return path === '/login'
    || path === '/api/selfhost/login'
    || path === '/api/selfhost/logout'
    // UHP discovery is unauthenticated BY SPEC (D-02): a client must be able to learn whether
    // this is a UHP server before deciding what credential to present. The document is version
    // metadata — no user data.
    || path === '/api/harness/v1/uhp'
    // A shared task is FOR people without an account: the link is the credential. The page and
    // the data it fetches are public; what they reveal is decided by the gateway, which answers
    // only for a token whose owner has sharing switched on, and with nothing but that session.
    || path.startsWith('/share/')
    || path.startsWith('/api/share/')
    || path.startsWith('/_next/')
    // An /api path is never a static asset, whatever it ends with. Neither is /data — those are
    // files a TASK produced, and agents write .png, .svg, .css and .js routinely. Matching those
    // by extension would hand a user's own artifacts to anyone who could guess the path.
    || (!path.startsWith('/api/') && !path.startsWith('/data/') && STATIC_ASSET.test(path));
}

export async function middleware(req: NextRequest) {
  // Hosted has its own login; this gate exists only for the self-hosted image.
  if (!SELF_HOSTED || AUTH_DISABLED) return NextResponse.next();

  const { pathname, search } = req.nextUrl;
  if (isPublic(pathname)) return NextResponse.next();
  if (isApiKeyCall(req, pathname)) return NextResponse.next();
  if (await sessionValid(req.cookies.get(SESSION_COOKIE)?.value)) return NextResponse.next();

  // An API call gets a status it can act on; a page gets sent to the form. Redirecting an API
  // call to HTML would make every fetch look like it succeeded and return a login page as data.
  if (pathname.startsWith('/api/')) {
    return new NextResponse(JSON.stringify({ detail: 'sign in to continue' }), {
      status: 401,
      headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
    });
  }
  const to = req.nextUrl.clone();
  to.pathname = '/login';
  // Come back to where they were headed, path only — an absolute URL here would let a crafted
  // link bounce someone off this instance after they authenticate.
  to.search = pathname === '/' ? '' : `?next=${encodeURIComponent(pathname + search)}`;
  return NextResponse.redirect(to);
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
};
