'use client';
// Revamped IA (2026-07-18 UX/UI revamp): Dashboard (org) + Workspace-scoped sidebar navigation
// (Quickstart / Overview / Harnesses / Tasks / Analytics / API Keys / Settings), replacing the old
// top-nav (AGENTS.md / API Keys / Manage / Playground / Billing). Design source:
// 02-产品与设计/assets/HTML原型/2026-07-17-HIG-UIUX-重构沟通示例.html + the 2026-07-17 IA review.
import '../revamp.css';
import { SkelPage } from '@/components/Skel';
import { useEffect, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { isAuthed, hasActiveOrg, getSession, refreshToken } from '@/lib/auth';
import { WorkspaceProvider } from '@/lib/workspace';
import { Shell } from '@/components/revamp/Shell';
import { billing } from './billing/lib';
import { SELF_HOSTED } from '@/lib/edition';

// Pages that keep their own full-page chrome (no revamp shell): the AGENTS.md doc page stays a
// standalone doc surface reachable from Docs; everything else lives in the shell.
const BARE: string[] = [];

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname() || '';
  const [ready, setReady] = useState(false);
  const [credits, setCredits] = useState<number | null>(null);
  // First-login welcome, shown ONCE EVER per member (persistent flag keyed by member id).
  // Nothing is granted at signup or on card-add. The only promotion is the subscribe bonus,
  // paid on the first real invoice, so this popup points at the plans. step: 0 = none, 1 = offer.
  // The invite-a-friend popup is intentionally disabled (referral rewards are off).
  const [welcomeStep, setWelcomeStep] = useState(0);

  const welcomeSeenKey = () => `hr-welcome-prompted.${getSession()?.member?.id || getSession()?.member?.email || ''}`;

  useEffect(() => {
    if (SELF_HOSTED) { setReady(true); return; }
    if (!isAuthed()) { router.replace('/login'); return; }
    // Multi-org members land here with an org-less session (no auto-select); every org-scoped
    // page would 400 ("no active organization in session"). Send them to /login to pick an org
    // instead of showing a wall of failing/hanging panels.
    if (!hasActiveOrg()) { router.replace('/login'); return; }
    // Slide the session TTL on every app load: an active user's token never hard-expires.
    // A 401 here (token already dead) redirects to /login via handleAuthExpired.
    void refreshToken();
    setReady(true);
  }, [router]);

  // First-login celebration: run ONCE on ready (not on every balance refresh).
  useEffect(() => {
    if (!ready || SELF_HOSTED) return;
    let alive = true;
    billing.balance().then((b) => {
      if (!alive) return;
      setCredits(Math.round(Number(b?.balance ?? b?.credits ?? 0)));
      // Offer the claim once per member. Skipped on /billing (its own surface has the same CTA).
      // Persistent flag so a returning user is never nagged.
      let seen = true;
      try { seen = !!window.localStorage.getItem(welcomeSeenKey()); } catch { /* private mode */ }
      if (!seen && !pathname.startsWith('/billing')) {
        setWelcomeStep(1);
        try { window.localStorage.setItem(welcomeSeenKey(), '1'); } catch { /* private mode */ }
      }
    }).catch(() => { /* header shows an em dash */ });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready]);

  // Keep the nav credit balance fresh WITHOUT a manual refresh: poll every 60s and on tab refocus,
  // so a just-finished run or a top-up shows up on its own. Balance-only (never re-triggers the
  // welcome popup). Pauses while the tab is hidden to avoid idle churn.
  useEffect(() => {
    if (!ready || SELF_HOSTED) return;
    let alive = true;
    const refresh = () => {
      if (document.visibilityState === 'hidden') return;
      billing.balance().then((b) => {
        if (alive) setCredits(Math.round(Number(b?.balance ?? b?.credits ?? 0)));
      }).catch(() => { /* keep the last shown value */ });
    };
    const iv = setInterval(refresh, 60_000);
    const onFocus = () => refresh();
    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', onFocus);
    return () => {
      alive = false; clearInterval(iv);
      window.removeEventListener('focus', onFocus);
      document.removeEventListener('visibilitychange', onFocus);
    };
  }, [ready]);

  if (!ready) return <main style={{ marginLeft: 0 }}><SkelPage /></main>;
  if (BARE.some((p) => pathname.startsWith(p))) return <>{children}</>;

  return (
    <WorkspaceProvider>
      <Shell credits={credits}>{children}</Shell>

      {/* ONE promotion, one surface: subscribe to any plan -> 500 bonus credits. The card-add gift
          and the 7-day trial were both removed on 2026-07-31 — they funded a credit-farming ring
          (170 cards attached across the platform, exactly one real payment ever), because
          "attached a card" and "paid us" were treated as the same thing. Shown once per member. */}
      {welcomeStep === 1 ? (
        <div className="welcome-overlay" role="dialog" aria-modal="true" aria-labelledby="welcome-wide-title">
          <div className="welcome-wide">
            <button className="welcome-wide-close" type="button" aria-label="Close" onClick={() => setWelcomeStep(0)}>
              <iconify-icon icon="tabler:x"></iconify-icon>
            </button>
            <div className="welcome-wide-head">
              <div className="welcome-eyebrow"><iconify-icon icon="tabler:gift"></iconify-icon>Launch offer</div>
              <h2 className="welcome-title" id="welcome-wide-title">Subscribe and get <b>500 bonus credits</b></h2>
              <p className="welcome-sub">Start any plan and we&apos;ll add <b>500 credits</b> on top of your plan&apos;s monthly credits. They land as soon as your first payment goes through.</p>
            </div>
            <div className="welcome-cards">
              {/* Left — launch-partner sponsorship */}
              <div className="welcome-col">
                <div className="welcome-col-badge sponsor">
                  {/* eslint-disable-next-line @next/next/no-img-element -- static partner asset */}
                  <img src="/tokenrouter-logo.png" alt="TokenRouter" />
                </div>
                <h3 className="welcome-col-title">Sponsored by our Launch Partner</h3>
                <p className="welcome-col-sub">Your bonus credits are made possible by <b>TokenRouter</b>. Their support helps us give every new builder a real head start — thank you.</p>
                <div className="welcome-col-spacer" />
                <button className="welcome-cta" type="button" onClick={() => { router.push('/billing'); setWelcomeStep(0); }}>
                  <iconify-icon icon="tabler:sparkles"></iconify-icon>View plans
                </button>
              </div>
              {/* Right — the offer itself */}
              <div className="welcome-col accent">
                <div className="welcome-col-badge"><iconify-icon icon="tabler:sparkles"></iconify-icon></div>
                <h3 className="welcome-col-title">Any plan, <b>500 bonus</b></h3>
                <p className="welcome-col-sub">Pick whichever plan fits. The 500 bonus credits are added once, on your first payment, and stack on top of the credits your plan already includes.</p>
                <div className="welcome-col-spacer" />
                <button className="welcome-cta" type="button" onClick={() => { router.push('/billing'); setWelcomeStep(0); }}>
                  <iconify-icon icon="tabler:sparkles"></iconify-icon>Choose a plan
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </WorkspaceProvider>
  );
}
