'use client';
// The console's frame: a 64px rail on the left (the mark, the workspace, five places, the team's letter, the
// account) and the page beside it. Every page draws its own top. The workspace and account menus open beside
// the rail. On a phone the rail is a bottom bar of three places and More; Add-ons, API Keys and the letter are
// in More there.
import './hrui.css';
import './hrui-console.css';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useWorkspace } from '@/lib/workspace';
import { Ic } from './icons';
import { MyPic, useOperator } from './Avatar';
import { wsColor, WsBadge } from './ws';
import { toast, ToastHost } from './toast';
import { NewWorkspaceSheet, PeopleSheet, useWorkspaceSheets, WS_MENU_EVENT } from './WorkspaceSheets';
import { movedTo } from './moved';
import { letterUnread, markLetterRead } from './letter';
import { Skel, SkHead, SkRows } from './Skel';

export const LINKS = {
  docs: 'https://harnessrouter.ai/docs',
  discord: 'https://discord.gg/nPcbwqVPb2',
  demo: 'https://calendly.com/contact-harnessrouter/30min',
  repo: 'https://github.com/HarnessRouter/harnessrouter',
};

// `nav` is the design's name for the place: its stylesheet keeps Add-ons and API Keys off the phone bar by
// it (they are in More there)
type Place = { key: string; href: string; label: string; icon: React.ReactNode; aria?: string; nav: string };
const PLACES: Place[] = [
  { key: 'start', href: '/start', label: 'Start', icon: Ic.start, nav: 'start' },
  { key: 'studio', href: '/studio', label: 'Studio', icon: Ic.studio, aria: 'Harness Studio', nav: 'agents' },
  { key: 'shop', href: '/shop', label: 'Shop', icon: Ic.shop, nav: 'harbor' },
  { key: 'extensions', href: '/extensions', label: 'Add-ons', icon: Ic.extensions, nav: 'library' },   // 'Extensions' was too long for the rail (Richard, 10-21)
  { key: 'keys', href: '/keys', label: 'API Keys', icon: Ic.keys, nav: 'keys' },
];

/** Which rail place a path belongs to. */
function placeOf(path: string): string {
  if (/^\/(studio|harnesses|tasks)(\/|$)/.test(path)) return 'studio';
  if (/^\/(shop|kits|marketplace)(\/|$)/.test(path)) return 'shop';
  if (/^\/(extensions|plugins|environments)(\/|$)/.test(path)) return 'extensions';
  if (/^\/(start|quickstart|dashboard|overview)(\/|$)/.test(path)) return 'start';
  if (/^\/letter\/?$/.test(path)) return 'letter';
  const p = PLACES.find((x) => path === x.href || path.startsWith(x.href + '/'));
  return p ? p.key : '';
}

function useGithubStars(): string | null {
  const [stars, setStars] = useState<number | null>(null);
  useEffect(() => {
    let alive = true;
    fetch('/api/github-stars', { cache: 'no-store' }).then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (alive && d && Number.isFinite(d.stars)) setStars(d.stars); })
      .catch(() => {});
    return () => { alive = false; };
  }, []);
  if (stars === null) return null;
  return stars >= 1000 ? `${(stars / 1000).toFixed(stars >= 10000 ? 0 : 1)}k` : String(stars);
}

/** A menu that opens beside the button that opened it, closes on a click outside or Escape. `also`:
 *  another element that opened it (a press on it is not outside). */
function usePop(also?: React.RefObject<HTMLElement | null>): [boolean, (v: boolean) => void, React.RefObject<HTMLDivElement | null>, React.RefObject<HTMLButtonElement | null>] {
  const [open, setOpen] = useState(false);
  const pop = useRef<HTMLDivElement | null>(null);
  const btn = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    if (!open) return;
    const down = (e: MouseEvent) => {
      const t = e.target as Node;
      if (pop.current?.contains(t) || btn.current?.contains(t) || also?.current?.contains(t)) return;
      setOpen(false);
    };
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') { setOpen(false); (also?.current || btn.current)?.focus(); } };
    document.addEventListener('mousedown', down);
    document.addEventListener('keydown', key);
    return () => { document.removeEventListener('mousedown', down); document.removeEventListener('keydown', key); };
  }, [open]);
  return [open, setOpen, pop, btn];
}

export function HruiShell({ children }: { children: React.ReactNode; ownStyles?: boolean }) {
  const pathname = usePathname() || '';
  const router = useRouter();
  const here = placeOf(pathname);
  const { workspaces, current, known, setCurrent, failed, lost, clearLost, refresh } = useWorkspace();
  // The workspace list is the switcher: until it has answered no page is drawn (every page is the current
  // workspace's, and nothing stands in for it); a list that could not be read is an error here and in place
  // of the page; a chosen workspace gone from the list moved to Default, and that is said.
  const listFailed = failed;
  const waiting = !known && !failed;
  const [retrying, setRetrying] = useState(false);
  const retry = () => { if (retrying) return; setRetrying(true); void refresh().finally(() => setRetrying(false)); };
  useEffect(() => {
    if (!lost) return;
    toast(`You no longer have access to ${lost.name || 'that workspace'}.`);
    clearLost();
  }, [lost, clearLost]);
  // the workspace menu opens under the rail's button or under Studio's workspace name (WS_MENU_EVENT)
  const wsAnchor = useRef<HTMLElement | null>(null);
  const [wsAt, setWsAt] = useState(0);                 // each opening places the menu again
  const [wsOpen, setWsOpen, wsPop, wsBtn] = usePop(wsAnchor);
  const [meOpen, setMeOpen, mePop, meBtn] = usePop();
  // the workspace menu's sheets: Workspace settings, New workspace
  const [wsSheet, setWsSheet] = useWorkspaceSheets();
  const openSheet = (k: 'people' | 'newws') => { (wsAnchor.current || wsBtn.current)?.focus(); setWsOpen(false); setWsSheet(k); };
  useEffect(() => {
    const on = (e: Event) => {
      const anchor = (e as CustomEvent<{ anchor?: HTMLElement }>).detail?.anchor || null;
      if (wsOpen && wsAnchor.current === anchor) { setWsOpen(false); return; }
      wsAnchor.current = anchor;
      setMeOpen(false);
      setWsOpen(true);
      setWsAt((n) => n + 1);
    };
    window.addEventListener(WS_MENU_EVENT, on);
    return () => window.removeEventListener(WS_MENU_EVENT, on);
  }, [wsOpen, setWsOpen, setMeOpen]);
  // the letter's dot, until it has been opened here
  const [unread, setUnread] = useState(false);
  useEffect(() => { if (here === 'letter') markLetterRead(); setUnread(letterUnread()); }, [here]);
  const stars = useGithubStars();
  const op = useOperator();
  useEffect(() => { setWsOpen(false); setMeOpen(false); }, [pathname, setWsOpen, setMeOpen]);
  // an older address (a bookmark, a link in a guide or an email) opens its place in the redesign
  useEffect(() => {
    const to = movedTo(pathname, new URLSearchParams(window.location.search));
    if (to) router.replace(to);
  }, [pathname, router]);

  // The menus sit beside the rail: the workspace menu level with its button, the account menu
  // rising from the bottom; on a phone the rail is a bottom bar and the account menu rises above it.
  useLayoutEffect(() => {
    const head = wsAnchor.current;
    if (wsOpen && wsPop.current && head) {
      // under Studio's workspace name, as the design places it from there
      const r = head.getBoundingClientRect();
      wsPop.current.style.left = `${Math.max(8, Math.min(r.left, window.innerWidth - 328))}px`;
      wsPop.current.style.top = `${r.bottom + 6}px`;
    } else if (wsOpen && wsPop.current && wsBtn.current) {
      const r = wsBtn.current.getBoundingClientRect();
      const narrow = window.innerWidth <= 700;
      wsPop.current.style.left = narrow ? '8px' : `${r.right + 8}px`;
      wsPop.current.style.top = narrow ? `${r.bottom + 6}px` : `${r.top}px`;
    }
    if (wsOpen && wsPop.current) {
      // never past the window's foot: the workspaces scroll inside it, its two actions stay in reach
      // (an organization with many workspaces could not reach New workspace, 2026-10-23)
      const top = wsPop.current.getBoundingClientRect().top;
      wsPop.current.style.maxHeight = `${Math.max(160, window.innerHeight - top - 8)}px`;
    }
    if (meOpen && mePop.current && meBtn.current) {
      const r = meBtn.current.getBoundingClientRect();
      const st = mePop.current.style;
      const bottom = window.innerWidth <= 700 ? window.innerHeight - r.top + 8 : Math.max(8, window.innerHeight - r.bottom);
      if (window.innerWidth <= 700) { st.left = 'auto'; st.right = '8px'; st.top = 'auto'; }
      else { st.right = 'auto'; st.left = `${r.right + 10}px`; st.top = 'auto'; }
      st.bottom = `${bottom}px`;
      // a short window: the menu scrolls
      st.maxHeight = `${Math.max(160, window.innerHeight - bottom - 8)}px`;
    }
  }, [wsOpen, wsAt, meOpen, wsPop, wsBtn, mePop, meBtn]);

  const go = (href: string) => { setMeOpen(false); setWsOpen(false); router.push(href); };
  const meMore = ['/byok', '/profile', '/extensions', '/keys'].some((p) => pathname === p || pathname.startsWith(p + '/'));
  return (
    <div id="hrui">
      <div className="app">
        <nav className="rail" aria-label="Console">
          <Link className="rail-logo" href="/start" aria-label="Go to Start" title="Start">
            {/* the brand's own mark file (brand decisions live with the brand pack, not a mockup) */}
            <img className="hr-mark" src="/brand/hr-mark-duo-light.svg" alt="" width={24} height={24} />
          </Link>
          <button ref={wsBtn} type="button" className={`ws-rail${known ? '' : ' ws-rail-x'}`} aria-haspopup="menu" aria-expanded={wsOpen}
            aria-label="Switch workspace" title={known ? `${current.name} · switch workspace` : 'Switch workspace'}
            style={known ? { background: wsColor(current.name) } : undefined} onClick={() => { const fromHead = !!wsAnchor.current; wsAnchor.current = null; setMeOpen(false); setWsOpen(fromHead || !wsOpen); setWsAt((n) => n + 1); }}>
            {known ? current.name.charAt(0).toUpperCase() : ''}
          </button>
          {PLACES.map((p) => (
            <Link key={p.key} href={p.href} className={`rail-btn${here === p.key ? ' on' : ''}`} data-nav={p.nav}
              aria-current={here === p.key ? 'page' : undefined} aria-label={p.aria} title={p.aria}>
              {p.icon}{p.key === 'studio' ? <span className="rail-l2">{p.label}</span> : p.label}
            </Link>
          ))}
          {/* How it works: the team's letter, above the account button (in More on a phone) */}
          <Link href="/letter" className={`rail-btn rail-letter${here === 'letter' ? ' on' : ''}`} data-nav="letter"
            aria-current={here === 'letter' ? 'page' : undefined} title="How it works · a letter from the team" aria-label="How it works, a letter from the team">
            {Ic.letter}Letter<i className="letter-dot" aria-hidden="true" hidden={!unread} />
          </Link>
          <button ref={meBtn} type="button" className={`rail-me${meOpen || pathname.startsWith('/profile') || pathname.startsWith('/byok') ? ' on' : ''}${meMore ? ' more-on' : ''}${unread ? ' dot' : ''}`}
            aria-haspopup="menu" aria-expanded={meOpen} aria-label="Account and settings"
            onClick={() => { setWsOpen(false); setMeOpen(!meOpen); }}>
            <MyPic className="me-av" /><span className="me-l">More</span>
          </button>
        </nav>
        <section className="page" id="page">
          {listFailed ? (
            <div className="scroll">
              <div className="list-wrap lw-n">
                <div className="empty-list ws-fail" role="alert">
                  Your workspaces could not be read just now.{' '}
                  <button type="button" className="link-q inl" disabled={retrying} onClick={retry}>Try again</button>
                </div>
              </div>
            </div>
          ) : waiting ? (
            <div className="scroll">
              <div className="list-wrap lw-n">
                <Skel label="Loading"><SkHead /><SkRows n={4} /></Skel>
              </div>
            </div>
          ) : children}
        </section>
      </div>

      {wsOpen && (
        <div ref={wsPop} className="ws-pop" role="menu" aria-label="Workspaces">
          {listFailed ? (
            <button type="button" className="ws-row ws-fail" role="menuitem" disabled={retrying} onClick={retry}>
              <span className="grow"><b>Your workspaces could not be read just now.</b><small>Try again</small></span>
            </button>
          ) : waiting ? (
            <Skel label="Loading workspaces"><SkRows n={2} /></Skel>
          ) : (
            <div className="ws-list">
              {workspaces.map((w) => (
                <button key={w.id || 'default'} type="button" className="ws-row" role="menuitem"
                  onClick={() => { setWsOpen(false); if (w.id !== current.id) { setCurrent(w.id); window.location.assign('/studio'); } else go('/studio'); }}>
                  <WsBadge name={w.name} size={30} />
                  <span className="grow"><b>{w.name}</b>{w.description ? <small>{w.description}</small> : null}</span>
                  {w.id === current.id ? <span className="chk">{Ic.check}</span> : null}
                </button>
              ))}
            </div>
          )}
          {!known ? null : (<>
            <hr />
            <button type="button" className="ws-row plain" role="menuitem" onClick={() => openSheet('people')}>Workspace settings</button>
            <button type="button" className="ws-row plain" role="menuitem" onClick={() => openSheet('newws')}>New workspace</button>
          </>)}
        </div>
      )}

      {meOpen && (
        <div ref={mePop} className="ws-pop me-pop" role="menu" aria-label="Account">
          {op?.user ? <div className="me-h">{op.user}</div> : null}
          {/* How it works stays in this menu at every width, first, with the unread dot until it is read */}
          <button type="button" className={`me-row${here === 'letter' ? ' on' : ''}`} role="menuitem" onClick={() => go('/letter')}>
            {Ic.letter}How it works{unread ? <i className="me-dot" role="img" aria-label="Unread" /> : null}
          </button>
          <hr />
          {PLACES.filter((p) => ['extensions', 'keys'].includes(p.key)).map((p) => (
            <button key={p.key} type="button" className={`me-row me-mob${here === p.key ? ' on' : ''}`} role="menuitem" onClick={() => go(p.href)}>{p.icon}{p.label}</button>
          ))}
          <hr className="me-mob" />
          {/* the instance's sign-in: its username and password */}
          <button type="button" className={`me-row${pathname.startsWith('/profile') ? ' on' : ''}`} role="menuitem" onClick={() => go('/profile')}>{Ic.account}Profile</button>
          <button type="button" className={`me-row${pathname.startsWith('/byok') ? ' on' : ''}`} role="menuitem" onClick={() => go('/byok')}>{Ic.byok}Bring your own key</button>
          <a className="me-row" href={LINKS.docs} target="_blank" rel="noopener noreferrer" role="menuitem">{Ic.docs}Docs<span className="me-n" aria-hidden="true">↗</span></a>
          <hr />
          <div className="me-h me-sec" role="presentation">Get help</div>
          <a className="me-row" href={LINKS.discord} target="_blank" rel="noopener noreferrer" role="menuitem">{Ic.discord}Join our Discord<span className="me-n" aria-hidden="true">↗</span></a>
          <a className="me-row" href={LINKS.demo} target="_blank" rel="noopener noreferrer" role="menuitem">{Ic.calendar}Book a demo<span className="me-n" aria-hidden="true">↗</span></a>
          <a className="me-gh" href={LINKS.repo} target="_blank" rel="noopener noreferrer" role="menuitem">
            {Ic.github}Star us on GitHub{stars ? <span className="me-star">{Ic.star}{stars}</span> : null}
          </a>
          {op?.gated === false ? null : (<>
            <hr />
            <button type="button" className="me-row" role="menuitem"
              onClick={() => { setMeOpen(false); void fetch('/api/selfhost/logout', { method: 'POST' }).catch(() => {}).finally(() => window.location.assign('/login')); }}>{Ic.logout}Log out</button>
          </>)}
        </div>
      )}

      {wsSheet === 'people' && known ? <PeopleSheet onClose={() => setWsSheet(null)} /> : null}
      {wsSheet === 'newws' && known ? <NewWorkspaceSheet onClose={() => setWsSheet(null)} /> : null}

      <ToastHost />
    </div>
  );
}
