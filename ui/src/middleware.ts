// The gate for a self-hosted instance that is reachable by anyone.
//
// Self-hosted has no accounts service, and on a machine only you can reach that is the right
// answer — a login would be ceremony with nothing behind it. The moment the box has a public
// URL that stops being true: the console can create harnesses, read every task transcript, and
// run an agent with your provider key. So exposure needs a gate, and the gate ships INSIDE the
// image rather than in whatever proxy happens to sit in front, because `docker run -p 3000:3000`
// on a cloud host must be safe by default and not by configuration.
//
// Middleware is the chokepoint deliberately: pages, the /api/harness proxy, static assets and any
// route added later all pass through here, so no individual handler can forget to check. HTTP
// Basic is the mechanism because it needs no session store, no cookie signing and no login route
// to keep in sync with the hosted edition's — fewer moving parts is the security argument.
//
//   HR_AUTH_USER / HR_AUTH_PASSWORD   set them. Defaults are published in the README, so an
//                                     instance still running them is open to anyone who read it.
//   HR_AUTH_DISABLED=1                no gate at all. Only for a box nobody else can reach.
import { NextResponse, type NextRequest } from 'next/server';

const SELF_HOSTED = process.env.NEXT_PUBLIC_HR_EDITION === 'selfhost';
const DISABLED = process.env.HR_AUTH_DISABLED === '1';
const USER = process.env.HR_AUTH_USER || 'harnessrouter';
const PASSWORD = process.env.HR_AUTH_PASSWORD || 'harnessrouter';

/** Length-independent comparison: a plain === leaks how much of the password was right through
 *  timing. Cheap to do properly, so do it properly. */
function sameSecret(a: string, b: string): boolean {
  const enc = new TextEncoder();
  const x = enc.encode(a);
  const y = enc.encode(b);
  // Compare a fixed number of bytes so length alone doesn't change the timing.
  let diff = x.length ^ y.length;
  const n = Math.max(x.length, y.length);
  for (let i = 0; i < n; i++) diff |= (x[i] ?? 0) ^ (y[i] ?? 0);
  return diff === 0;
}

function unauthorized(): NextResponse {
  return new NextResponse('Authentication required.', {
    status: 401,
    headers: {
      // The realm is what the browser shows in its prompt.
      'WWW-Authenticate': 'Basic realm="HarnessRouter", charset="UTF-8"',
      'Cache-Control': 'no-store',
    },
  });
}

export function middleware(req: NextRequest) {
  // Hosted has its own login; this gate exists only for the self-hosted image.
  if (!SELF_HOSTED || DISABLED) return NextResponse.next();

  const header = req.headers.get('authorization') || '';
  if (header.toLowerCase().startsWith('basic ')) {
    let decoded = '';
    try {
      decoded = atob(header.slice(6).trim());
    } catch {
      return unauthorized();      // malformed base64 is a failed attempt, not a server error
    }
    // Only the FIRST colon separates them — a password may legitimately contain one.
    const i = decoded.indexOf(':');
    const user = i < 0 ? decoded : decoded.slice(0, i);
    const pass = i < 0 ? '' : decoded.slice(i + 1);
    // Both are checked every time, so a wrong username costs the same as a wrong password.
    const okUser = sameSecret(user, USER);
    const okPass = sameSecret(pass, PASSWORD);
    if (okUser && okPass) return NextResponse.next();
  }
  return unauthorized();
}

export const config = {
  // Everything. The one exception is the favicon, so a browser tab doesn't provoke a second
  // credential prompt before the page itself has asked for one.
  matcher: ['/((?!favicon.ico).*)'],
};
