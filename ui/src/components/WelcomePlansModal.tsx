'use client';
// THE plan-activation dialog, and the single way an org earns the 500 bonus credits: pick a plan
// and pay for it. There is no free trial — the bonus mints server-side on the FIRST PAID invoice,
// because "subscribed" and "paid us" being different things is exactly what a credit-farming ring
// monetised (170 cards attached platform-wide, one real payment). Used by the app layout's
// first-login prompt AND the billing page's banner, so there is exactly one flow.
import { useEffect, useState } from 'react';
import { billing, RETURN_BASE, formatCredits } from '@/app/(app)/billing/lib';

export type WelcomePlan = { id: string; name: string; price_usd: string; credits: string; badge?: string };

export function useWelcomePlans(): WelcomePlan[] {
  const [plans, setPlans] = useState<WelcomePlan[]>([]);
  useEffect(() => {
    let alive = true;
    billing.packages().then((p) => {
      if (!alive) return;
      setPlans((p?.packages || []).filter((x: { recurring?: string; status?: string; app_scope?: string }) =>
        x.recurring === 'monthly' && x.status === 'active' && x.app_scope === 'harnessrouter'));
    }).catch(() => { /* no plans -> empty picker */ });
    return () => { alive = false; };
  }, []);
  return plans;
}

export function WelcomePlansModal({ plans, onClose }: { plans: WelcomePlan[]; onClose: () => void }) {
  const [plan, setPlan] = useState(plans[0]?.id || '');
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (!plan && plans.length) setPlan(plans[0].id); }, [plans, plan]);

  const subscribe = async () => {
    if (!plan) return;
    setBusy(true);
    try {
      // Plain subscription checkout — charged today, no trial. The 500 bonus mints server-side
      // on the paid invoice.
      const { url } = await billing.checkout(plan, RETURN_BASE);
      if (url) { window.location.href = url; return; }
    } catch { /* fall through */ }
    setBusy(false);
  };

  return (
    <div className="welcome-overlay" role="dialog" aria-modal="true" aria-labelledby="welcome-title">
      <div className="welcome-card">
        <div className="welcome-hero">
          {/* eslint-disable-next-line @next/next/no-img-element -- small static brand asset */}
          <div className="welcome-badge"><img src="/harnessrouter-logo.svg" alt="HarnessRouter" /></div>
          <div className="welcome-eyebrow"><iconify-icon icon="tabler:sparkles"></iconify-icon>Launch offer</div>
          <h2 className="welcome-title" id="welcome-title">Subscribe, get <b>500 bonus credits</b></h2>
          <p className="welcome-sub">Pick a plan to activate your account. The 500 bonus credits are added on top of your plan&apos;s monthly credits.</p>
        </div>
        <div className="welcome-body">
          <div className="welcome-plans" role="radiogroup" aria-label="Choose a plan">
            {plans.map((p) => (
              <button key={p.id} type="button" role="radio" aria-checked={plan === p.id}
                className={'welcome-plan' + (plan === p.id ? ' on' : '')}
                disabled={busy} onClick={() => setPlan(p.id)}>
                <span className="wp-name">{p.name}{p.badge ? <em>{p.badge}</em> : null}</span>
                <span className="wp-price">${Number(p.price_usd).toLocaleString()}<small>/mo</small></span>
                <span className="wp-credits">{formatCredits(p.credits)} credits / month</span>
              </button>
            ))}
          </div>
          <div className="welcome-actions">
            <button className="welcome-cta" disabled={busy || !plan} onClick={() => void subscribe()}>
              {busy ? 'Redirecting…' : <><iconify-icon icon="tabler:sparkles"></iconify-icon>Subscribe & get 500 bonus</>}
            </button>
            <button className="welcome-later" disabled={busy} onClick={onClose}>Maybe later</button>
          </div>
          <div className="welcome-trust">
            <iconify-icon icon="tabler:lock"></iconify-icon>Secured by Stripe · cancel anytime
          </div>
        </div>
      </div>
    </div>
  );
}
