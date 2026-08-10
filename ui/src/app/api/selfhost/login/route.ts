// Sign in to a self-hosted instance. Sets the session cookie; the middleware does the checking.
import type { NextRequest } from 'next/server';
import {
  AUTH_DISABLED, SELF_HOSTED, SESSION_COOKIE, SESSION_TTL_MS, credentialsValid, mintSession,
} from '@/lib/selfhost-auth';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/** Deliberately uniform: "user not found" and "wrong password" are the same answer, because the
 *  difference only helps someone who doesn't know either. */
const REJECT = { detail: 'Incorrect username or password.' };

export async function POST(req: NextRequest) {
  if (!SELF_HOSTED || AUTH_DISABLED) {
    return Response.json({ detail: 'sign-in is not enabled on this instance' }, { status: 404 });
  }
  let body: { username?: string; password?: string };
  try {
    body = await req.json();
  } catch {
    return Response.json(REJECT, { status: 401 });
  }
  if (!credentialsValid(String(body.username || ''), String(body.password || ''))) {
    // A small delay costs an honest user nothing and makes online guessing tediously slow.
    await new Promise((r) => setTimeout(r, 400));
    return Response.json(REJECT, { status: 401 });
  }

  const res = Response.json({ ok: true });
  const secure = req.nextUrl.protocol === 'https:' ? '; Secure' : '';
  res.headers.set('set-cookie',
    `${SESSION_COOKIE}=${await mintSession()}; Path=/; Max-Age=${Math.floor(SESSION_TTL_MS / 1000)}`
    + `; HttpOnly; SameSite=Lax${secure}`);
  return res;
}
