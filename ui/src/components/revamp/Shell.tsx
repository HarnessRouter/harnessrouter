'use client';
// Revamped app shell, header + sidebar per the HIG UI/UX prototype
// (02-产品与设计/assets/HTML原型/2026-07-17-HIG-UIUX-重构沟通示例.html).
// Header: brand · global search · Docs · Credits · notifications · account.
// Sidebar: Dashboard (org level) → Workspace switcher → Quickstart / Overview / Harnesses /
// Tasks / Analytics / API Keys / Settings, with Support/Feedback footer.
import 'iconify-icon';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { getSession, logout } from '@/lib/auth';
import { useWorkspace } from '@/lib/workspace';
import { listCustom, OOB } from '@/lib/harness';
import { fetchTraceWindow, type TraceCard } from '@/lib/revamp-data';
import { PLATFORM_ADMIN_ORGS, SELF_HOSTED, SELF_HOSTED_NAV } from '@/lib/edition';

// Global search result, a workspace to switch to, a harness to open, or a task to jump into.
type SearchItem =
  | { kind: 'workspace'; id: string; label: string; sub?: string; current: boolean }
  | { kind: 'harness'; id: string; label: string; sub?: string }
  | { kind: 'task'; sid: string; harnessId?: string; label: string; sub?: string };

const MAX_PER_GROUP = 6;

/** A task's display name, its title, falling back to a short session handle. */
function taskLabel(t: TraceCard): string {
  return (t.title && t.title.trim()) || `Task ${(t.session_id || '').slice(0, 8)}`;
}

/** Wrap the first case-insensitive occurrence of `q` in <mark> for match highlighting. */
function highlight(text: string, q: string): React.ReactNode {
  if (!q) return text;
  const i = text.toLowerCase().indexOf(q);
  if (i < 0) return text;
  return (<>{text.slice(0, i)}<mark>{text.slice(i, i + q.length)}</mark>{text.slice(i + q.length)}</>);
}

// Finalized IA (2026-07-19 prototype revision): Monetization joins the workspace nav;
// Workspace Settings moves INTO the workspace switcher menu (no standalone sidebar entry).
const WORKSPACE_NAV = [
  { href: '/quickstart', icon: 'tabler:rocket', label: 'Quickstart' },
  { href: '/overview', icon: 'tabler:home', label: 'Overview' },
  { href: '/harnesses', icon: 'tabler:assembly', label: 'Harnesses' },
  { href: '/tasks', icon: 'tabler:list-details', label: 'Tasks' },
  // Monetization (builder revenue / Stripe Connect) hidden until the backend ships, owner
  // decision 2026-07-21; the route stays for direct links, only the nav entry is removed.
  { href: '/keys', icon: 'tabler:key', label: 'API Keys' },
].filter((n) => !SELF_HOSTED || SELF_HOSTED_NAV.includes(n.href));
// Platform-org-only surfaces (the Integrations console configures GLOBAL model routing).
// Customer BYOK later widens this to every org.
const PLATFORM_NAV = [
  { href: '/integrations', icon: 'tabler:plug-connected', label: 'Integrations', orgs: PLATFORM_ADMIN_ORGS },
];

export function Shell({ children, credits }: { children: React.ReactNode; credits?: number | null }) {
  const pathname = usePathname() || '';
  const router = useRouter();
  const { workspaces, current, setCurrent, create } = useWorkspace();
  const [wsMenu, setWsMenu] = useState(false);
  const [wsCreate, setWsCreate] = useState(false);
  const [wsName, setWsName] = useState('');
  const [wsDesc, setWsDesc] = useState('');
  const [wsBusy, setWsBusy] = useState(false);
  const [wsErr, setWsErr] = useState('');
  const [acctMenu, setAcctMenu] = useState(false);
  // Not a build-time constant: the image is built once and credentials are set when it runs.
  const [selfHostUser, setSelfHostUser] = useState('');
  useEffect(() => {
    if (!SELF_HOSTED) return;
    fetch('/api/selfhost/session')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (d?.user) setSelfHostUser(String(d.user)); })
      .catch(() => { /* the menu just says "this instance" */ });
  }, []);
  const [mobileNav, setMobileNav] = useState(false);
  const [connectOpen, setConnectOpen] = useState(false);
  const wsRef = useRef<HTMLDivElement>(null);
  const acctRef = useRef<HTMLDivElement>(null);
  const connectRef = useRef<HTMLDivElement>(null);
  const mainRef = useRef<HTMLElement>(null);

  // Global search, matches workspaces (from context), and this workspace's harnesses + tasks
  // (loaded lazily on first focus, then filtered client-side). Substring, case-insensitive.
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [activeIdx, setActiveIdx] = useState(0);
  const [harnesses, setHarnesses] = useState<{ id: string; name: string }[] | null>(null);
  const [tasks, setTasks] = useState<TraceCard[] | null>(null);
  const [searchLoading, setSearchLoading] = useState(false);
  const searchRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const searchLoaded = useRef(false);

  const ensureSearchData = useCallback(async () => {
    if (searchLoaded.current) return;
    searchLoaded.current = true;
    setSearchLoading(true);
    try {
      const [h, t] = await Promise.all([
        listCustom().catch(() => []),
        fetchTraceWindow().catch(() => []),
      ]);
      // Search spans the built-in (default) harnesses AND the workspace's custom ones; the base
      // catalog also names tasks whose trace card carries only a base harness id (e.g. Codex).
      setHarnesses([...OOB.map((o) => ({ id: o.id, name: o.name })), ...h.map((c) => ({ id: c.id, name: c.name }))]);
      setTasks(t);
    } finally { setSearchLoading(false); }
  }, []);

  const q = query.trim().toLowerCase();
  const groups = useMemo(() => {
    if (!q) return null;
    // harness_name is missing on older trace cards; resolve it from the loaded harness list
    // (id -> name), which is how the Overview tables label tasks too.
    const hname = new Map((harnesses || []).map((h) => [h.id, h.name]));
    const ws = workspaces
      .filter((w) => w.name.toLowerCase().includes(q))
      .slice(0, MAX_PER_GROUP)
      .map((w): SearchItem => ({ kind: 'workspace', id: w.id, label: w.name, sub: w.description, current: w.id === current.id }));
    const hs = (harnesses || [])
      .filter((h) => h.name.toLowerCase().includes(q))
      .slice(0, MAX_PER_GROUP)
      .map((h): SearchItem => ({ kind: 'harness', id: h.id, label: h.name }));
    const ts = (tasks || [])
      .filter((t) => taskLabel(t).toLowerCase().includes(q) || (t.session_id || '').toLowerCase().includes(q))
      .slice(0, MAX_PER_GROUP)
      .map((t): SearchItem => ({ kind: 'task', sid: t.session_id, harnessId: t.harness_id, label: taskLabel(t), sub: (t.harness_id && hname.get(t.harness_id)) || t.harness_name || undefined }));
    return { ws, hs, ts };
  }, [q, workspaces, harnesses, tasks, current.id]);
  const flat = useMemo(() => (groups ? [...groups.ws, ...groups.hs, ...groups.ts] : []), [groups]);

  // Reset the keyboard cursor whenever the result set changes.
  useEffect(() => { setActiveIdx(0); }, [q, flat.length]);

  const openItem = useCallback((it: SearchItem) => {
    setSearchOpen(false);
    setQuery('');
    searchInputRef.current?.blur();
    if (it.kind === 'workspace') {
      if (it.current) return;
      setCurrent(it.id);
      // Match the switcher: hard reload so every workspace-scoped surface re-queries.
      window.location.reload();
      return;
    }
    if (it.kind === 'harness') { router.push(`/harnesses/${encodeURIComponent(it.id)}`); return; }
    const p = new URLSearchParams();
    if (it.harnessId) p.set('h', it.harnessId);
    p.set('sid', it.sid);
    // Hard nav (not router.push): the workbench binds its deep-linked task on mount, so when the
    // user is already on /tasks a client-side query swap changes the URL but doesn't reopen the
    // task. A full load remounts the workbench and opens the exact task every time.
    window.location.assign(`/tasks?${p.toString()}`);
  }, [router, setCurrent]);

  const onSearchKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setSearchOpen(true); setActiveIdx((i) => Math.min(i + 1, flat.length - 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActiveIdx((i) => Math.max(i - 1, 0)); }
    else if (e.key === 'Enter') { const it = flat[activeIdx]; if (it) { e.preventDefault(); openItem(it); } }
    else if (e.key === 'Escape') { setSearchOpen(false); searchInputRef.current?.blur(); }
  };

  // ⌘K / Ctrl+K focuses search from anywhere.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
        e.preventDefault();
        setSearchOpen(true);
        searchInputRef.current?.focus();
        void ensureSearchData();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [ensureSearchData]);

  // main is the scroll container (not the document), start each page at its top,
  // otherwise client-side nav lands mid-scroll on the next page.
  useEffect(() => { mainRef.current?.scrollTo(0, 0); }, [pathname]);

  async function submitCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!wsName.trim() || wsBusy) return;
    setWsBusy(true); setWsErr('');
    try {
      await create(wsName.trim(), wsDesc.trim());
      setWsCreate(false); setWsName(''); setWsDesc('');
      // Per the design: after creation, Quickstart opens so the user connects a coding agent
      // and mints the first Workspace API Key. Hard nav so every surface re-queries under the
      // new workspace scope.
      window.location.assign('/quickstart');
    } catch (ex) { setWsErr(ex instanceof Error ? ex.message : 'create failed'); }
    finally { setWsBusy(false); }
  }

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (wsRef.current && !wsRef.current.contains(e.target as Node)) setWsMenu(false);
      if (acctRef.current && !acctRef.current.contains(e.target as Node)) setAcctMenu(false);
      if (connectRef.current && !connectRef.current.contains(e.target as Node)) setConnectOpen(false);
      if (searchRef.current && !searchRef.current.contains(e.target as Node)) setSearchOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, []);
  useEffect(() => { setMobileNav(false); setSearchOpen(false); }, [pathname]);

  const s = getSession();
  const initials = (s?.member?.name || s?.member?.email || '?').slice(0, 2).toUpperCase();
  const avatarUrl = (s?.member?.avatar_url as string) || '';
  const isActive = (href: string) => pathname === href || pathname.startsWith(href + '/');

  const renderGroup = (title: string, icon: string, items: SearchItem[], offset: number) => {
    if (!items.length) return null;
    return (
      <div className="search-group">
        <p className="search-group-label">{title}</p>
        {items.map((it, i) => {
          const idx = offset + i;
          const active = idx === activeIdx;
          const key = it.kind === 'task' ? `task:${it.sid}` : `${it.kind}:${it.id}`;
          const isCurrentWs = it.kind === 'workspace' && it.current;
          return (
            <button key={key} type="button" role="option" aria-selected={active}
              className={'search-item' + (active ? ' is-active' : '')}
              onMouseEnter={() => setActiveIdx(idx)}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => openItem(it)}>
              <iconify-icon icon={icon} aria-hidden="true"></iconify-icon>
              <span className="search-item-main">
                <span className="search-item-label">{highlight(it.label, q)}</span>
                {it.sub ? <span className="search-item-sub">{it.sub}</span> : null}
              </span>
              {isCurrentWs
                ? <span className="search-item-tag">Current</span>
                : active ? <iconify-icon className="search-item-go" icon="tabler:corner-down-left" aria-hidden="true"></iconify-icon> : null}
            </button>
          );
        })}
      </div>
    );
  };

  return (
    <>
      <header className="app-header">
        <Link className="brand" href="/dashboard" aria-label="Open Dashboard">
          {/* Full wordmark on roomy headers; the icon alone once space gets tight. */}
          {/* eslint-disable-next-line @next/next/no-img-element -- small static brand asset */}
          <img className="brand-full" src="/harnessrouter-wordmark.png" alt="HarnessRouter" />
          {/* eslint-disable-next-line @next/next/no-img-element -- small static brand asset */}
          <img className="brand-icon" src="/harnessrouter-logo.svg" alt="HarnessRouter" />
        </Link>
        <div className="global-search" ref={searchRef}>
          <iconify-icon icon="tabler:search" aria-hidden="true"></iconify-icon>
          <input type="search" placeholder="Search workspaces, harnesses, tasks"
            aria-label="Search workspaces, harnesses, and tasks" role="combobox"
            aria-expanded={searchOpen} aria-controls="global-search-panel" autoComplete="off"
            ref={searchInputRef} value={query}
            onFocus={() => { setSearchOpen(true); void ensureSearchData(); }}
            onChange={(e) => { setQuery(e.target.value); setSearchOpen(true); void ensureSearchData(); }}
            onKeyDown={onSearchKey} />
          <span className="search-key">⌘ K</span>
          {searchOpen && q ? (
            <div className="search-panel" id="global-search-panel" role="listbox" aria-label="Search results">
              {flat.length === 0 ? (
                <div className="search-empty">{searchLoading ? 'Searching…' : `No matches for “${query.trim()}”`}</div>
              ) : (
                <>
                  {renderGroup('Workspaces', 'tabler:building', groups!.ws, 0)}
                  {renderGroup('Harnesses', 'tabler:assembly', groups!.hs, groups!.ws.length)}
                  {renderGroup('Tasks', 'tabler:list-details', groups!.ts, groups!.ws.length + groups!.hs.length)}
                </>
              )}
            </div>
          ) : null}
        </div>
        <div className="header-utils">
          <a className="utility-link" href="https://harnessrouter.ai/docs" target="_blank" rel="noreferrer"><iconify-icon icon="tabler:book-2"></iconify-icon>Docs</a>
          {SELF_HOSTED ? (
            <div className="account-wrap" ref={acctRef}>
              <button className="account-button" type="button" aria-expanded={acctMenu}
                      aria-label="Account" onClick={() => setAcctMenu((v) => !v)}>
                <iconify-icon icon="tabler:user"></iconify-icon>
              </button>
              {acctMenu && (
                <div className="account-menu">
                  <div className="account-meta">
                    <strong>Signed in</strong>
                    <span>{selfHostUser || 'this instance'}</span>
                  </div>
                  <button className="menu-item" type="button" onClick={() => {
                    setAcctMenu(false);
                    router.push('/profile');
                  }}><iconify-icon icon="tabler:user-cog"></iconify-icon>Profile</button>
                  <button className="menu-item" type="button" onClick={async () => {
                    setAcctMenu(false);
                    await fetch('/api/selfhost/logout', { method: 'POST' }).catch(() => undefined);
                    // Full navigation: the middleware must re-evaluate without the cookie.
                    window.location.assign('/login');
                  }}><iconify-icon icon="tabler:logout"></iconify-icon>Sign out</button>
                </div>
              )}
            </div>
          ) : (
          <div className="account-wrap" ref={acctRef}>
            <button className="account-button" type="button" aria-expanded={acctMenu} onClick={() => setAcctMenu((v) => !v)}>
              {avatarUrl
                /* eslint-disable-next-line @next/next/no-img-element -- external OAuth photo, not a local asset */
                ? <img className="account-avatar" src={avatarUrl} alt="" referrerPolicy="no-referrer" />
                : initials}
            </button>
            {acctMenu && (
              <div className="account-menu">
                <div className="account-meta"><strong>{s?.member?.name || 'Account'}</strong><span>{s?.member?.email || ''}</span></div>
                <button className="menu-item" type="button" onClick={() => { setAcctMenu(false); router.push('/billing'); }}><iconify-icon icon="tabler:credit-card"></iconify-icon>Billing &amp; plan</button>
                <button className="menu-item" type="button" onClick={() => { setAcctMenu(false); router.push('/account'); }}><iconify-icon icon="tabler:settings"></iconify-icon>Account settings</button>
                <button className="menu-item" type="button" onClick={() => { logout(); router.replace('/login'); }}><iconify-icon icon="tabler:logout"></iconify-icon>Sign out</button>
              </div>
            )}
          </div>
          )}
          <button className="icon-button mobile-menu" type="button" aria-label="Open navigation" aria-expanded={mobileNav}
            onClick={() => setMobileNav((v) => !v)}><iconify-icon icon="tabler:menu-2"></iconify-icon></button>
        </div>
      </header>

      <aside className={'sidebar' + (mobileNav ? ' is-open' : '')} aria-label="Product navigation">
        {SELF_HOSTED ? null : (
          <div className="side-section global-nav">
            <Link className="side-nav" href="/dashboard" aria-current={isActive('/dashboard') ? 'page' : undefined}>
              <iconify-icon icon="tabler:layout-dashboard"></iconify-icon>Dashboard
            </Link>
          </div>
        )}
        <div className="switcher-wrap" ref={wsRef}>
          <p className="side-label">Workspace</p>
          <button className="workspace-switcher" type="button" aria-expanded={wsMenu} onClick={() => setWsMenu((v) => !v)}>
            <span><iconify-icon icon="tabler:building"></iconify-icon><span className="switcher-label">{current.name}</span></span>
            <iconify-icon icon="tabler:chevron-down"></iconify-icon>
          </button>
          {wsMenu && (
            <div className="workspace-menu">
              {workspaces.map((w) => (
                <button key={w.id} className="workspace-menu-item" type="button"
                  aria-current={w.id === current.id}
                  onClick={() => {
                    setWsMenu(false);
                    if (w.id !== current.id) {
                      setCurrent(w.id);
                      // Every data surface scopes reads by the active workspace, hard refresh so
                      // long-lived client caches (recents polls, dashboards) re-query cleanly.
                      window.location.reload();
                    }
                  }}>
                  <span>{w.name}</span>
                  {w.id === current.id && <iconify-icon icon="tabler:check"></iconify-icon>}
                </button>
              ))}
              <div className="workspace-menu-separator"></div>
              <button className="workspace-menu-item" type="button"
                onClick={() => { setWsMenu(false); router.push('/settings'); }}>
                <span><iconify-icon icon="tabler:settings"></iconify-icon> Workspace settings</span>
              </button>
              <button className="workspace-menu-item" type="button"
                onClick={() => { setWsMenu(false); setWsCreate(true); setWsErr(''); }}>
                <span><iconify-icon icon="tabler:plus"></iconify-icon> Create Workspace</span>
              </button>
            </div>
          )}
        </div>
        <div className="side-section workspace-nav">
          {WORKSPACE_NAV.map((n) => (
            <Link key={n.href} className="side-nav" href={n.href} aria-current={isActive(n.href) ? 'page' : undefined}>
              <iconify-icon icon={n.icon}></iconify-icon>{n.label}
            </Link>
          ))}
          {PLATFORM_NAV.filter((n) => (SELF_HOSTED
            ? SELF_HOSTED_NAV.includes(n.href)     // your own keys, on your own box
            : n.orgs.includes(s?.orgId || ''))).map((n) => (
            <Link key={n.href} className="side-nav" href={n.href} aria-current={isActive(n.href) ? 'page' : undefined}>
              <iconify-icon icon={n.icon}></iconify-icon>{n.label}
            </Link>
          ))}
        </div>
        <div className="sidebar-foot" ref={connectRef}>
          {SELF_HOSTED ? null : (
          <button className="credits-card" type="button" onClick={() => router.push('/billing')}
            aria-label={credits != null ? `Credit balance, ${credits} credits — manage billing` : 'Billing'}>
            <span className="credits-card-coin" aria-hidden="true"><iconify-icon icon="tabler:currency-dollar"></iconify-icon></span>
            <span className="credits-card-body">
              <span className="credits-card-label">Credits</span>
              <span className="credits-card-value">{credits != null ? credits.toLocaleString() : '—'}</span>
            </span>
            <iconify-icon className="credits-card-go" icon="tabler:chevron-right" aria-hidden="true"></iconify-icon>
          </button>
          )}
          <button className="side-nav connect-trigger" type="button" aria-expanded={connectOpen}
            onClick={() => setConnectOpen((v) => !v)}>
            <iconify-icon icon="tabler:world" aria-hidden="true"></iconify-icon>
            <span>Connect</span>
            <iconify-icon className="connect-chevron" icon="tabler:chevron-up" aria-hidden="true"></iconify-icon>
          </button>
          {connectOpen && (
            <div className="connect-menu">
              <a className="connect-item" href="https://discord.gg/nPcbwqVPb2" target="_blank" rel="noopener noreferrer" aria-label="Open the public HarnessRouter Discord community in a new tab">
                <iconify-icon icon="tabler:brand-discord" aria-hidden="true"></iconify-icon><span>Discord</span><iconify-icon className="connect-external" icon="tabler:external-link" aria-hidden="true"></iconify-icon>
              </a>
              <a className="connect-item" href="https://github.com/HarnessRouter" target="_blank" rel="noopener noreferrer" aria-label="Open HarnessRouter on GitHub in a new tab">
                <iconify-icon icon="tabler:brand-github" aria-hidden="true"></iconify-icon><span>GitHub</span><iconify-icon className="connect-external" icon="tabler:external-link" aria-hidden="true"></iconify-icon>
              </a>
              <a className="connect-item" href="https://linkedin.com/company/harnessrouter/" target="_blank" rel="noopener noreferrer" aria-label="Open HarnessRouter on LinkedIn in a new tab">
                <iconify-icon icon="tabler:brand-linkedin" aria-hidden="true"></iconify-icon><span>LinkedIn</span><iconify-icon className="connect-external" icon="tabler:external-link" aria-hidden="true"></iconify-icon>
              </a>
              <a className="connect-item" href="https://x.com/HARNESSROUTER" target="_blank" rel="noopener noreferrer" aria-label="Open HarnessRouter on X in a new tab">
                <iconify-icon icon="tabler:brand-x" aria-hidden="true"></iconify-icon><span>X</span><iconify-icon className="connect-external" icon="tabler:external-link" aria-hidden="true"></iconify-icon>
              </a>
            </div>
          )}
        </div>
      </aside>

      <main ref={mainRef}>{children}</main>

      {wsCreate && (
        <div className="modal-backdrop">
          <section className="modal" role="dialog" aria-modal="true" aria-labelledby="newWsTitle" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div><h2 id="newWsTitle">Create Workspace</h2><p>Create a business or environment boundary for its Harnesses, Tasks, API Keys, and Revenue.</p></div>
              <button className="icon-button modal-close" type="button" aria-label="Close dialog" onClick={() => setWsCreate(false)}><iconify-icon icon="tabler:x"></iconify-icon></button>
            </div>
            <div className="modal-body">
              <form onSubmit={submitCreate}>
                <div className="field-stack">
                  <div className="field"><label htmlFor="newWsName">Name</label>
                    <input id="newWsName" value={wsName} placeholder="Customer Support" autoFocus
                      onChange={(e) => setWsName(e.target.value)} />
                    <span className="field-help">Use a product, customer, or environment name your team will recognize.</span></div>
                  <div className="field"><label htmlFor="newWsDesc">Description <span className="optional-label">Optional</span></label>
                    <textarea id="newWsDesc" value={wsDesc} placeholder="Customer-facing support workflows."
                      onChange={(e) => setWsDesc(e.target.value)} /></div>
                  {wsErr && <div className="notice"><iconify-icon icon="tabler:alert-triangle"></iconify-icon><div><strong>Could not create</strong>{wsErr}</div></div>}
                </div>
                <div className="creation-next"><iconify-icon icon="tabler:arrow-right"></iconify-icon><span>After creation, Quickstart opens so you can connect a coding agent and create the first Workspace API Key.</span></div>
                <div className="modal-actions">
                  <button className="button" type="button" onClick={() => setWsCreate(false)} disabled={wsBusy}>Cancel</button>
                  <button className="button primary" type="submit" disabled={wsBusy || !wsName.trim()}>{wsBusy ? 'Creating…' : 'Create Workspace'}</button>
                </div>
              </form>
            </div>
          </section>
        </div>
      )}
    </>
  );
}
