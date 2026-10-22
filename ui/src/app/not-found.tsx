// An address with no page, drawn in the console's own frame with the way back to Start
// (components/hrui/NotFoundPage.tsx).
import type { Metadata } from 'next';
import { ConsoleNotFound } from '@/components/hrui/NotFound';

export const metadata: Metadata = { title: 'Page not found' };

export default function NotFound() {
  return <ConsoleNotFound />;
}
