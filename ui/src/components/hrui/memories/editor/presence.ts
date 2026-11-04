// One color per person, the same wherever they show up, and a presence that stays alive in a background tab.
const PALETTE = ['#1e40af', '#c2410c', '#15803d', '#6d28d9', '#be123c', '#0e7490', '#b45309', '#166534', '#7e22ce', '#991b1b'];

export function peerColor(key: unknown): string {
  let h = 0;
  for (const ch of String(key || '')) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return PALETTE[h % PALETTE.length];
}

/** A background tab's timers slow to once a minute and its presence would expire for everyone else, so the
 *  renewal runs on a worker's clock, which isn't throttled. */
export function keepPresenceAlive(awareness: { getLocalState(): unknown; setLocalState(s: never): void }, ms = 10_000): () => void {
  if (typeof Worker === 'undefined' || typeof Blob === 'undefined') return () => {};
  let url = '';
  let worker: Worker | null = null;
  try {
    url = URL.createObjectURL(new Blob([`setInterval(() => postMessage(0), ${Math.max(1000, ms)})`], { type: 'text/javascript' }));
    worker = new Worker(url);
  } catch {
    if (url) URL.revokeObjectURL(url);
    return () => {};
  }
  worker.onmessage = () => {
    const s = awareness.getLocalState();
    if (s !== null) awareness.setLocalState(s as never);
  };
  return () => {
    worker?.terminate();
    URL.revokeObjectURL(url);
  };
}
