// Change the sign-in credentials of a self-hosted instance.
//
// The current password is required even though the caller is already signed in. A session cookie
// proves someone was signed in once, on this browser; it does not prove they are the operator
// now. Without the re-check, an unattended tab is a permanent credential-change token.
//
// WHY THIS RESTARTS THE CONSOLE. The gate lives in middleware, which Next.js runs on the Edge
// runtime: no filesystem, and no visibility into environment variables changed after start-up
// (measured, not assumed). So a running console cannot be told about new credentials — it can
// only be replaced by one that boots with them. The entrypoint supervises the console process
// for exactly this, and restarts it in about a second while the gateway and runner — and any
// task mid-turn — keep running untouched.
//
// The alternative was a second gate in Node that checks the file while the middleware checks
// stale credentials. Two gates that can disagree about who is signed in is a worse thing to own
// than a one-second restart.
import type { NextRequest } from 'next/server';
import {
  AUTH_DISABLED, SELF_HOSTED, SESSION_COOKIE, SESSION_TTL_MS, mintSessionWith,
} from '@/lib/selfhost-auth';
import {
  authUser, currentSessionKey, passwordValid, setCredentials, usingDefaultPassword,
} from '@/lib/selfhost-credentials';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/** Short enough to type, long enough that guessing it over the network is hopeless. */
const MIN_PASSWORD = 8;

export async function GET() {
  if (!SELF_HOSTED) return Response.json({ detail: 'not a self-hosted instance' }, { status: 404 });
  return Response.json({
    user: authUser(),
    gated: !AUTH_DISABLED,
    usingDefaultPassword: usingDefaultPassword(),
  });
}

export async function PUT(req: NextRequest) {
  if (!SELF_HOSTED || AUTH_DISABLED) {
    return Response.json({ detail: 'sign-in is not enabled on this instance' }, { status: 404 });
  }
  let body: { currentPassword?: string; username?: string; newPassword?: string };
  try {
    body = await req.json();
  } catch {
    return Response.json({ detail: 'Invalid request.' }, { status: 400 });
  }

  const currentPassword = String(body.currentPassword || '');
  if (!passwordValid(currentPassword)) {
    await new Promise((r) => setTimeout(r, 400));   // the same brake as the sign-in form
    return Response.json({ detail: 'Current password is incorrect.' }, { status: 403 });
  }

  const username = String(body.username || '').trim() || authUser();
  const newPassword = String(body.newPassword || '');
  if (/\s/.test(username)) {
    return Response.json({ detail: 'Username cannot contain spaces.' }, { status: 400 });
  }
  // An empty new password means "leave it alone" — this form changes either field or both.
  if (newPassword && newPassword.length < MIN_PASSWORD) {
    return Response.json(
      { detail: `Password must be at least ${MIN_PASSWORD} characters.` }, { status: 400 });
  }
  if (username === authUser() && !newPassword) {
    return Response.json({ detail: 'Nothing to change.' }, { status: 400 });
  }

  setCredentials(username, newPassword || currentPassword);

  // Signed with the NEW key, not this process's: the console that verifies this cookie is the one
  // about to boot. Every other browser's cookie is signed with the old key and stops working —
  // which is the entire point of changing a password.
  const res = Response.json({ ok: true, user: username, restarting: true });
  const secure = req.nextUrl.protocol === 'https:' ? '; Secure' : '';
  res.headers.set('set-cookie',
    `${SESSION_COOKIE}=${await mintSessionWith(currentSessionKey())}; Path=/`
    + `; Max-Age=${Math.floor(SESSION_TTL_MS / 1000)}; HttpOnly; SameSite=Lax${secure}`);

  // After the response is on the wire. Exiting first would drop it, and the operator would be
  // left unable to tell whether their password had changed — the worst possible thing to be
  // unsure about.
  setTimeout(() => process.exit(0), 500);
  return res;
}
