'use client';
import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { isAuthed } from '@/lib/auth';
import { SELF_HOSTED } from '@/lib/edition';

// app.harnessrouter.ai is the product surface only, no marketing here. The landing
// page lives at the apex (https://harnessrouter.ai). Hitting the app root sends a
// signed-in user to their workbench and everyone else to sign in. Auth is held in
// localStorage, so this resolves client-side.
export default function Root() {
  const router = useRouter();
  useEffect(() => {
    // Self-hosted has no sign-in and no workbench surface — harnesses is the front door.
    if (SELF_HOSTED) { router.replace('/harnesses'); return; }
    router.replace(isAuthed() ? '/harnesses' : '/login');
  }, [router]);
  return null;
}
