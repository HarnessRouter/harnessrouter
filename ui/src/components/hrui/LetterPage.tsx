'use client';
// How it works: the team's letter, opened from the rail above the account button and from the account
// menu. It keeps its own page and pictures (public/letters) in a frame that fills the content area, and
// the letter scrolls inside it, so each picture animates only while it is on screen. New setup in the
// letter goes to Start; its outside links open a new tab.
//
// One fact in it is read from this instance as the page opens, never typed in: how many agent harnesses
// there are (the bases list). When it cannot be read, the sentence goes without the number. Its P.S. is
// about the hosted service's free requests, which a self-hosted instance has none of, so it is left out.
import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { loadBases } from '@/lib/harness';
import { LETTER_FILE } from './letter';
import { Skel, SkLine } from './Skel';

/** The letter with this instance's own facts in the marked places. */
export function fill(html: string, bases: number | null): string {
  const many = bases == null || bases <= 3 ? 'or another' : bases >= 10 ? `or one of ${Math.floor(bases / 5) * 5}+` : `or one of ${bases}`;
  return html
    .replace(/<!--hr:bases-->[\s\S]*?<!--\/hr:bases-->/, many)
    .replace(/<!--hr:ps-->[\s\S]*?<!--\/hr:ps-->/, '');
}

export function LetterPage() {
  const router = useRouter();
  const frame = useRef<HTMLIFrameElement | null>(null);
  const [doc, setDoc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(() => {
    setFailed(false);
    let alive = true;
    Promise.all([
      fetch(LETTER_FILE, { cache: 'force-cache' }).then((r) => (r.ok ? r.text() : Promise.reject(new Error(String(r.status))))),
      loadBases().then((b) => (b ? Object.keys(b).length : null)).catch(() => null),
    ]).then(([html, n]) => { if (alive) setDoc(fill(html, n)); })
      .catch(() => { if (alive) setFailed(true); });
    return () => { alive = false; };
  }, []);
  useEffect(() => load(), [load]);

  // the letter's own links: New setup opens Start in the console, an outside address opens a new tab
  const wire = () => {
    const d = frame.current?.contentDocument;
    if (!d) return;
    d.addEventListener('click', (e) => {
      const a = (e.target as Element | null)?.closest?.('a');
      if (!a) return;
      const h = a.getAttribute('href') || '';
      if (h === '#new-setup') { e.preventDefault(); router.push('/start'); return; }
      if (/^https?:/.test(h)) { a.setAttribute('target', '_blank'); a.setAttribute('rel', 'noopener'); }
    });
  };

  if (failed) {
    return (
      <div className="letter-page letter-off">
        <p>The letter did not load.</p>
        <button type="button" className="btn small" onClick={() => load()}>Try again</button>
      </div>
    );
  }
  if (doc === null) {
    return (
      <div className="letter-page">
        <Skel label="Loading the letter" className="letter-skel">
          <SkLine w="52%" h={12} />
          <SkLine w="88%" h={30} r={8} style={{ marginTop: 22 }} />
          <SkLine w="60%" h={30} r={8} style={{ marginTop: 10 }} />
          {[96, 100, 92, 70, 100, 84].map((w, i) => <SkLine key={i} w={`${w}%`} h={14} style={{ marginTop: i === 0 ? 40 : 14 }} />)}
          <SkLine w="100%" h={220} r={14} style={{ marginTop: 40 }} />
        </Skel>
      </div>
    );
  }
  return (
    <div className="letter-page">
      <iframe ref={frame} className="letter-frame" title="How it works, a letter from the team" srcDoc={doc} onLoad={wire} />
    </div>
  );
}
