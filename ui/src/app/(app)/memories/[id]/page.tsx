'use client';
// One memory. The address carries the open tab (?tab=schema, ?tab=data) and a record opened by its link
// (?record=, with ?in= for a record of a person's memory below this one), so a link to a place in a memory opens there.
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import { MemoryPage } from '@/components/hrui/memories/MemoryPage';

export default function Page() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const params = useSearchParams();
  return (
    <MemoryPage key={id} id={id} tabParam={params.get('tab')} recordParam={params.get('record')} inParam={params.get('in')}
      onTab={(t) => router.replace(`/memories/${encodeURIComponent(id)}?tab=${t}`, { scroll: false })} />
  );
}
