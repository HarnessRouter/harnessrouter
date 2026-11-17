import { notFound } from 'next/navigation';
import { SELF_HOSTED } from '@/lib/edition';
import { RunnersPage } from '@/components/hrui/RunnersPage';

export default function Page() {
  if (!SELF_HOSTED) notFound();
  return <RunnersPage />;
}
