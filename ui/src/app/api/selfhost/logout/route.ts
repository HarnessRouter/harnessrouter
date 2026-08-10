// Sign out: clear the session cookie. The cookie IS the session (signed, not stored), so
// expiring it here is the whole of it.
import type { NextRequest } from 'next/server';
import { SESSION_COOKIE } from '@/lib/selfhost-auth';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function POST(req: NextRequest) {
  const res = Response.json({ ok: true });
  const secure = req.nextUrl.protocol === 'https:' ? '; Secure' : '';
  res.headers.set('set-cookie',
    `${SESSION_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax${secure}`);
  return res;
}
