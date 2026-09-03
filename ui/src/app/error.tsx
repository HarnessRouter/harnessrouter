'use client';
// The route-level error boundary. Its one job beyond showing a plain message: a tab loaded
// before a deploy asks for the previous build's chunks on its next navigation; when one is gone
// the router throws a ChunkLoadError. That tab is not broken, it is stale, so reload it once
// (guarded so a genuinely missing chunk cannot loop) instead of showing a dead page.
import { useEffect } from 'react';

const isStaleChunk = (e: Error) => /ChunkLoadError|Loading chunk|Failed to fetch dynamically imported module/i.test(`${e?.name} ${e?.message}`);

export default function RouteError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    if (!isStaleChunk(error)) return;
    try {
      const key = 'hr:reloaded-for-chunk';
      if (sessionStorage.getItem(key) !== '1') { sessionStorage.setItem(key, '1'); window.location.reload(); return; }
    } catch { /* storage blocked: fall through to the button */ }
  }, [error]);
  return (
    <div style={{ minHeight: '60vh', display: 'grid', placeItems: 'center', padding: 24, textAlign: 'center' }}>
      <div style={{ maxWidth: 420 }}>
        <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>{isStaleChunk(error) ? 'This page is out of date' : 'Something went wrong'}</div>
        <div style={{ fontSize: 13.5, color: '#6b6560', lineHeight: 1.6, marginBottom: 16 }}>
          {isStaleChunk(error) ? 'A newer version is available. Reload to pick it up.' : 'Reloading usually clears it. If it keeps happening, tell us what you were doing.'}
        </div>
        <button type="button" onClick={() => { try { sessionStorage.removeItem('hr:reloaded-for-chunk'); } catch { /* ignore */ } window.location.reload(); }}
          style={{ font: 'inherit', fontSize: 13, fontWeight: 500, padding: '8px 14px', border: '1px solid #e0dcd9', borderRadius: 8, background: '#fff', color: '#57534e', cursor: 'pointer' }}>
          Reload
        </button>
        {!isStaleChunk(error) && <button type="button" onClick={reset} style={{ marginLeft: 8, font: 'inherit', fontSize: 13, fontWeight: 500, padding: '8px 14px', border: 0, borderRadius: 8, background: '#1a5cf5', color: '#fff', cursor: 'pointer' }}>Try again</button>}
      </div>
    </div>
  );
}
