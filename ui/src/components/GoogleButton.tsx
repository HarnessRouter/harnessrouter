'use client';
import { useEffect, useRef } from 'react';

// Google Identity Services button. Renders only when NEXT_PUBLIC_GOOGLE_CLIENT_ID is set; on a
// successful sign-in it hands the id_token (credential) back to the caller, which exchanges it for a
// session via /v1/auth/google. The Google consent screen shows the brand "Wrapper" (set in GCP).
const CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || '';

declare global {
  interface Window { google?: any } // eslint-disable-line @typescript-eslint/no-explicit-any
}

export function GoogleButton({ onCredential, onError }: { onCredential: (credential: string) => void; onError?: (m: string) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  // Keep the latest callbacks in a ref so the GIS button mounts EXACTLY ONCE and never re-renders
  // when the parent re-renders (e.g. on every keystroke in the email/password fields). Re-running
  // the init/renderButton on each render is what caused the visible flicker.
  const cb = useRef({ onCredential, onError });
  cb.current = { onCredential, onError };

  useEffect(() => {
    if (!CLIENT_ID || !ref.current) return;
    const SRC = 'https://accounts.google.com/gsi/client';
    let done = false;
    const render = () => {
      if (done) return;
      const g = window.google;
      if (!g?.accounts?.id || !ref.current) return;
      done = true;
      try {
        g.accounts.id.initialize({
          client_id: CLIENT_ID,
          callback: (resp: { credential?: string }) => {
            if (resp?.credential) cb.current.onCredential(resp.credential);
            else cb.current.onError?.('Google sign-in was cancelled.');
          },
        });
        ref.current.innerHTML = '';
        g.accounts.id.renderButton(ref.current, {
          theme: 'outline', size: 'large', shape: 'pill', text: 'continue_with', width: 320,
        });
      } catch { cb.current.onError?.('Could not start Google sign-in.'); }
    };
    let s = document.querySelector<HTMLScriptElement>(`script[src="${SRC}"]`);
    if (s && window.google) { render(); return; }
    if (!s) { s = document.createElement('script'); s.src = SRC; s.async = true; s.defer = true; document.head.appendChild(s); }
    s.addEventListener('load', render);
    return () => s?.removeEventListener('load', render);
  }, []); // mount once, never re-render on parent state changes

  if (!CLIENT_ID) return null;
  return <div ref={ref} className="hr-gbtn" />;
}

export const GOOGLE_ENABLED = !!CLIENT_ID;
