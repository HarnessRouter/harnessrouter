'use client';
// The console's frame: the workspace the person is in, and the rail with every page in it. Who may
// see it is decided before any page loads, by the sign-in gate (src/middleware.ts).
import '../revamp.css';
import dynamic from 'next/dynamic';
import { WorkspaceProvider } from '@/lib/workspace';

// Loaded on demand: the frame is client-only (it reads the window's size and the person's choices).
const HruiShell = dynamic(() => import('@/components/hrui/Shell').then((m) => m.HruiShell), { ssr: false });

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <WorkspaceProvider>
      <HruiShell>{children}</HruiShell>
    </WorkspaceProvider>
  );
}
