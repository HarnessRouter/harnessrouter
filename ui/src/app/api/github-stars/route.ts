// The open-source repository's star count for the sidebar's "Star us on GitHub" row. Read from
// GitHub server-side and kept for ten minutes, so a thousand open consoles do not spend GitHub's
// unauthenticated rate limit (sixty an hour per address) and the browser never talks to GitHub.
// When GitHub does not answer there is no number: the row then shows no count rather than a
// remembered or invented one.
import { NextResponse } from 'next/server';

const REPO = 'HarnessRouter/harnessrouter';
const TTL_MS = 10 * 60 * 1000;
let cached: { stars: number; at: number } | null = null;

export const dynamic = 'force-dynamic';

export async function GET() {
  if (cached && Date.now() - cached.at < TTL_MS) return NextResponse.json({ stars: cached.stars, repo: REPO });
  try {
    const r = await fetch(`https://api.github.com/repos/${REPO}`, {
      headers: { accept: 'application/vnd.github+json', 'user-agent': 'harnessrouter-console' },
      cache: 'no-store',
    });
    if (!r.ok) throw new Error(`github ${r.status}`);
    const stars = Number((await r.json())?.stargazers_count);
    if (!Number.isFinite(stars)) throw new Error('no count');
    cached = { stars, at: Date.now() };
    return NextResponse.json({ stars, repo: REPO });
  } catch (e) {
    if (cached) return NextResponse.json({ stars: cached.stars, repo: REPO, stale: true });
    return NextResponse.json({ detail: e instanceof Error ? e.message : 'unavailable' }, { status: 502 });
  }
}
