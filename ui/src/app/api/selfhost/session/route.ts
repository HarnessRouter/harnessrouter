// Who is signed in to this instance.
//
// The username can't be a NEXT_PUBLIC_* build-time constant: the image is built once and the
// credentials are set when it RUNS, so the client has to ask. Only the username is returned —
// it is a label, not a secret, and the password never leaves the server.
//
// Reaching this route at all means the middleware already validated the session.
import { AUTH_DISABLED, AUTH_USER, SELF_HOSTED } from '@/lib/selfhost-auth';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET() {
  if (!SELF_HOSTED) return Response.json({ detail: 'not a self-hosted instance' }, { status: 404 });
  return Response.json({ user: AUTH_USER, gated: !AUTH_DISABLED });
}
