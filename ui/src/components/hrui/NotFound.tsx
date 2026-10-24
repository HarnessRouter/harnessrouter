'use client';
// The redesign's not-found page (NotFoundPage.tsx), loaded on demand like the console's frame in
// app/(app)/layout.tsx: a production build, where HRUI is false, never loads its stylesheet.
import dynamic from 'next/dynamic';

export const ConsoleNotFound = dynamic(() => import('./NotFoundPage').then((m) => m.NotFoundPage), { ssr: false });
