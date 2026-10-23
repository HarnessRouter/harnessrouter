// THE single way the console talks to the harness BFF (/api/harness/*).
//
// LIVE-B: every call carries the login JWT (Authorization: Bearer <token>) so the gateway can
// verify identity from the signed claims instead of trusting self-asserted org/member headers.
// Attaching it in ONE place makes it impossible for a call site to forget (the failure that broke
// the console when the key was gated on an Authorization the client wasn't sending). The wrapper
// only ADDS the bearer, each caller keeps whatever other headers it already sets.
//
// A 401 WITH a token attached means the session is dead (expired/invalid JWT) — hand off to
// handleAuthExpired (clear session, /login?expired=1) instead of surfacing a raw gateway error
// like "invalid session token" in whatever dialog happened to make the call. Without a token the
// layout guard owns the redirect.
import { getSession, handleAuthExpired } from '@/lib/auth';

const DEFAULT_TIMEOUT_MS = 30000;

export async function harnessFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const token = getSession()?.token;
  const headers: Record<string, string> = {
    ...(token ? { authorization: `Bearer ${token}` } : {}),
    ...(init.headers as Record<string, string> | undefined),
  };
  // No request waits forever: a service that stops answering turns into a failed request the page
  // can show, not a page that stays blank. Streams and long polls pass their own `signal`.
  const ctl = init.signal ? null : new AbortController();
  const timer = ctl ? setTimeout(() => ctl.abort(), DEFAULT_TIMEOUT_MS) : null;
  let res: Response;
  try { res = await fetch(path, { cache: 'no-store', ...init, headers, signal: init.signal ?? ctl?.signal }); }
  finally { if (timer) clearTimeout(timer); }
  if (res.status === 401 && token) handleAuthExpired();
  return res;
}
