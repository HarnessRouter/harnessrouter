'use client';
// One kit: its own app beside a live trace, and Launch.
import { useParams } from 'next/navigation';
import { KitTryPage } from '@/components/hrui/shop/KitTry';

export default function Page() {
  const { kit } = useParams<{ kit: string }>();
  return <KitTryPage key={kit} kitId={decodeURIComponent(kit || '')} />;
}
