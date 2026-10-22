'use client';
// An address with no page, in the redesign (app/not-found.tsx): said calmly, with the way back to Start.
// Someone signed in sees it inside the console's frame (the rail, their workspace), drawn as one of its
// own pages whatever the address; someone signed out sees it on the sign-in screen's card, with Sign in
// as well. Loaded on demand (NotFound.tsx), so a production build never loads the console's stylesheet.
import Link from 'next/link';
import { useState } from 'react';
import { hasActiveOrg } from '@/lib/auth';
import { WorkspaceProvider } from '@/lib/workspace';
import { HruiShell } from './Shell';
import { AuthFrame } from './auth/AuthFrame';

const HEAD = 'This page isn’t here';
const LINE = 'The link may be old, or the page was moved.';

export function NotFoundPage() {
  // the console's own gate (app/(app)/layout.tsx): a session with an organization chosen
  const [signedIn] = useState(() => hasActiveOrg());
  if (!signedIn) {
    return (
      <AuthFrame n={3}>
        <h1>{HEAD}</h1>
        <p className="au-sub">{LINE}</p>
        <Link className="btn primary au-wide" href="/start">Back to Start</Link>
        <p className="au-switch"><Link className="link-q inl" href="/login">Sign in</Link></p>
      </AuthFrame>
    );
  }
  return (
    <WorkspaceProvider>
      <HruiShell ownStyles>
        <div className="scroll">
          <div className="list-wrap lw-n">
            <div className="list-top"><div><h1>{HEAD}</h1></div></div>
            <div className="empty-list es">
              <span>{LINE}</span>
              <Link className="btn primary" href="/start">Back to Start</Link>
            </div>
          </div>
        </div>
      </HruiShell>
    </WorkspaceProvider>
  );
}
