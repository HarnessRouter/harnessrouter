'use client';
// The sign-in page: this instance's own username and password (components/SelfHostLogin.tsx). `next`
// is where the sign-in gate (src/middleware.ts) was sending the person, kept only when it is a path
// on this site (lib/safe-next.ts).
import { useState } from 'react';
import { SelfHostLogin } from '@/components/SelfHostLogin';
import { safeNext } from '@/lib/safe-next';

export default function LoginPage() {
  const [next] = useState(() => (typeof window === 'undefined' ? safeNext('') : safeNext(new URLSearchParams(window.location.search).get('next'))));
  return <SelfHostLogin next={next} />;
}
