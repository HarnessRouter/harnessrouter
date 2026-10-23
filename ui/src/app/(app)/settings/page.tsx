'use client';
// A workspace's settings live in its settings sheet, so this address opens that sheet over Studio and
// links to it keep working.
import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { openPeopleSheet } from '@/components/hrui/WorkspaceSheets';

export default function WorkspaceSettingsRoute() {
  const router = useRouter();
  useEffect(() => {
    router.replace('/studio');
    // the frame is listening by the next task (it stays mounted across the move), so the sheet opens
    // over Studio; not cancelled when this page goes, which is what the move does
    setTimeout(openPeopleSheet, 0);
  }, [router]);
  return null;
}
