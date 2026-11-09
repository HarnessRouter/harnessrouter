// How many memories a setup's agent holds, for the Agent stack, from the same read as its Settings. The setup's record
// doesn't say: access is grants on the memories. Settings says when it has read them, so a change there reaches
// the brick at once.
import { useEffect, useState } from 'react';
import { getHarnessMemories, type HarnessMemories } from '@/lib/memories';

const READ = 'hr:harness-memories';

export function announceHarnessMemories(hid: string, d: HarnessMemories): void {
  if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent(READ, { detail: { hid, d } }));
}

/** The names of what it holds; null until read, or if it could not be. */
export function useHarnessMemories(hid: string | undefined): string[] | null {
  const [names, setNames] = useState<string[] | null>(null);
  useEffect(() => {
    if (!hid) { setNames(null); return undefined; }
    let live = true;
    const take = (d: HarnessMemories) => { if (live) setNames((d.data || []).map((x) => x.name)); };
    getHarnessMemories(hid).then(take).catch(() => { if (live) setNames(null); });
    const heard = (e: Event) => {
      const { hid: h, d } = (e as CustomEvent<{ hid: string; d: HarnessMemories }>).detail;
      if (h === hid) take(d);
    };
    window.addEventListener(READ, heard);
    return () => { live = false; window.removeEventListener(READ, heard); };
  }, [hid]);
  return names;
}
