'use client';
// A call with us, booked without leaving the console: the homepage's dialog (harnessrouter.ai,
// BookDemoLink), the Calendly page in a frame with our mark shown until it is running. The
// sidebar opens it from the calendar mark beside the community links.
import { useCallback, useEffect, useRef, useState } from 'react';

export const BOOK_CALL_URL = 'https://calendly.com/contact-harnessrouter/30min';

export function BookCallDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [frameMounted, setFrameMounted] = useState(false);
  const [frameLoaded, setFrameLoaded] = useState(false);
  const [embedUrl, setEmbedUrl] = useState('');

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open) {
      // embed_domain is the host the page is on, as Calendly asks; computed here, never at render.
      setEmbedUrl(`${BOOK_CALL_URL}?embed_domain=${encodeURIComponent(window.location.hostname)}&embed_type=PopupWidget&hide_gdpr_banner=1`);
      setFrameMounted(true);
      if (!d.open) d.showModal();
    } else if (d.open) {
      d.close();
    }
  }, [open]);

  // The frame's onLoad fires when Calendly's document arrives, well before its app renders.
  // Calendly posts `calendly.*` messages once it is running, so the first one is the accurate
  // hide signal; onLoad only arms a late fallback in case messaging is unavailable.
  useEffect(() => {
    if (!frameMounted || frameLoaded) return;
    const onMessage = (e: MessageEvent) => {
      const data: unknown = e.data;
      if (!(e.origin.endsWith('.calendly.com') || e.origin === 'https://calendly.com')) return;
      if (typeof data === 'object' && data !== null && 'event' in data && typeof (data as { event: unknown }).event === 'string'
          && ((data as { event: string }).event.startsWith('calendly.') || (data as { event: string }).event.startsWith('calendly:'))) {
        setFrameLoaded(true);
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [frameMounted, frameLoaded]);

  const onBackdrop = useCallback((e: React.MouseEvent<HTMLDialogElement>) => { if (e.target === ref.current) onClose(); }, [onClose]);

  return (
    <dialog aria-label="Book a call" className="book-demo-dialog" ref={ref} onClick={onBackdrop} onClose={onClose}>
      <button aria-label="Close" className="book-demo-close" type="button" onClick={onClose}>
        <iconify-icon icon="tabler:x"></iconify-icon>
      </button>
      {frameMounted && embedUrl ? (
        <iframe className="book-demo-frame" src={embedUrl} title="Schedule a meeting with HarnessRouter"
                onLoad={() => { window.setTimeout(() => setFrameLoaded(true), 4000); }} />
      ) : null}
      <div aria-hidden={frameLoaded} className={frameLoaded ? 'book-demo-loading book-demo-loading-done' : 'book-demo-loading'}>
        {/* eslint-disable-next-line @next/next/no-img-element -- static brand asset */}
        <img alt="" className="book-demo-loading-mark" src="/brand/harnessrouter-logo-mark-dark.png" width={56} height={56} />
        <p className="book-demo-loading-title">The best agent harnesses as your infrastructure, <em>one conversation away.</em></p>
        <p className="book-demo-loading-subtitle">Finding the best time slots for you…</p>
      </div>
    </dialog>
  );
}
