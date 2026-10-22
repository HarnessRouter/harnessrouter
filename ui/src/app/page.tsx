'use client';
import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

// The root opens Start. The sign-in gate (src/middleware.ts) has already sent anyone without a
// session to the login page, so whoever reaches this is signed in.
export default function Root() {
  const router = useRouter();
  useEffect(() => { router.replace('/start'); }, [router]);
  return null;
}
