'use client';
// A new setup's page while it is being set up, before it has its id (start/BuildPage.tsx): New
// setup's sheet opens it as it closes, and the setup's own page takes over once the setup exists.
import { Suspense } from 'react';
import { BuildPage } from '@/components/hrui/start/BuildPage';

export default function NewSetupPage() {
  return <Suspense fallback={null}><BuildPage /></Suspense>;
}
