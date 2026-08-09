'use client';

// Billing, the org's credit center for HarnessRouter. Mirrors the ClawTrace
// credits page (balance, packages, history) on the HR design system.
import { useCallback, useEffect, useMemo, useState } from 'react';
import { SkelRows } from '@/components/Skel';
import Link from 'next/link';
import { billing, RETURN_BASE, LOW_CREDITS, formatCredits, formatDate, sourceLabel, welcomeEnabled } from './lib';
import { WelcomePlansModal } from '@/components/WelcomePlansModal';

type Lot = {
  id: string; source: string; status: string; app_scope: string;
  credits_remaining: string; credits_initial: string;
  granted_at?: string; expires_at?: string; package_id?: string;
  amount_paid_cents?: string; invoice_url?: string; receipt_url?: string;
};
type Pkg = { id: string; name: string; price_usd: string; credits: string; badge?: string; recurring?: string; validity_days?: string; status: string; app_scope?: string };

const PAGE_SIZE = 10;
const STATUS_PILL: Record<string, string> = { active: 'ok', expired: 'mute', exhausted: 'warn', deficit: 'danger' };

export default function BillingPage() {
  const [balance, setBalance] = useState<{ balance: number; is_deficit: boolean; lots: Lot[];
    card?: { brand: string; last4: string; exp_month: string; exp_year: string } | null } | null>(null);
  const [packages, setPackages] = useState<Pkg[]>([]);
  const [loading, setLoading] = useState(true);
  const [purchasing, setPurchasing] = useState('');
  const [notice, setNotice] = useState('');
  const [page, setPage] = useState(1);
  const [sub, setSub] = useState<{ package_id: string; status: string; period_end: string; auto_renew: string } | null>(null);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [cancelReason, setCancelReason] = useState('');
  const [cancelFeedback, setCancelFeedback] = useState('');
  const [cancelBusy, setCancelBusy] = useState(false);
  // Plan-change confirmation (in-app dialog, the action bills or reschedules money).
  const [planChange, setPlanChange] = useState<{ pkg: Pkg; upgrade: boolean } | null>(null);
  const [planBusy, setPlanBusy] = useState(false);
  // Welcome activation: the banner opens THE welcome plan-picker (same dialog as first login).
  const [welcomeOpen, setWelcomeOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [b, p, s] = await Promise.all([
        billing.balance(), billing.packages(),
        billing.subscription().catch(() => null),
      ]);
      setBalance(b);
      setPackages((p.packages || []).filter((x: Pkg) => x.status === 'active' && x.app_scope === 'harnessrouter'));
      setSub(s?.subscription || null);
    } catch (e) {
      setNotice(String((e as Error).message || e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    if (q.get('checkout') === 'success') setNotice('Payment received. Credits are added once Stripe confirms, usually within a few seconds.');
    if (q.get('checkout') === 'cancelled') setNotice('Checkout cancelled.');
    if (q.get('setup') === 'success') setNotice('Card saved. Subscribe to any plan to get your 500 bonus credits.');
    if (q.get('setup') === 'cancelled') setNotice('Card setup cancelled.');
    load();
  }, [load]);

  const total = Number(balance?.balance || 0);
  const isDeficit = Boolean(balance?.is_deficit) && total <= 0;
  const isLow = !isDeficit && total > 0 && total < LOW_CREDITS;

  const lots = useMemo(() => {
    // A deficit lot that netted back to 0 is history, not state, hide it (it reappears only
    // if the org actually overdraws again).
    const ls = (balance?.lots || []).filter((l) =>
      !(l.source === 'deficit' && Number(l.credits_remaining) >= 0));
    ls.sort((a, b) => String(b.granted_at || '').localeCompare(String(a.granted_at || '')));
    return ls;
  }, [balance]);
  const totalPages = Math.max(1, Math.ceil(lots.length / PAGE_SIZE));
  const pageLots = lots.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const buy = async (pkg: Pkg) => {
    setPurchasing(pkg.id);
    try {
      const { url } = await billing.checkout(pkg.id, RETURN_BASE);
      if (url) window.location.href = url;
      else setPurchasing('');
    } catch (e) {
      setNotice(String((e as Error).message || e));
      setPurchasing('');
    }
  };

  const hasWelcome = welcomeEnabled(balance?.lots);
  const card = balance?.card || null;
  const cardExp = card && card.exp_month
    ? `${String(card.exp_month).padStart(2, '0')}/${String(card.exp_year).slice(-2)}` : '';
  const [topupAmount, setTopupAmount] = useState('50');
  const plans = packages.filter((p) => p.recurring === 'monthly')
    .sort((a, b) => Number(a.price_usd) - Number(b.price_usd));
  // The single top-up RATE CARD: its price is the minimum, credits/price the flat rate.
  const rateCard = packages.find((p) => p.recurring !== 'monthly');
  const topupMin = rateCard ? Number(rateCard.price_usd) : 0;
  const topupRate = rateCard ? Number(rateCard.credits) / Number(rateCard.price_usd) : 0;
  const topupNum = Number(topupAmount);
  const topupValid = rateCard != null && Number.isFinite(topupNum) && topupNum >= topupMin;
  const topupCredits = topupValid ? Math.round(topupNum * topupRate) : 0;

  const buyTopup = async () => {
    if (!rateCard || !topupValid) return;
    setPurchasing(rateCard.id);
    try {
      const { url } = await billing.checkoutTopup(rateCard.id, topupNum, RETURN_BASE);
      if (url) window.location.href = url;
      else setPurchasing('');
    } catch (e) {
      setNotice(String((e as Error).message || e));
      setPurchasing('');
    }
  };

  const changePlan = (pkg: Pkg, upgrade: boolean) => setPlanChange({ pkg, upgrade });
  const confirmPlanChange = async () => {
    if (!planChange || planBusy) return;
    setPlanBusy(true);
    try {
      const r = await billing.changeSubscription(planChange.pkg.id, RETURN_BASE);
      if (r.applied === 'checkout' && r.url) { window.location.href = r.url; return; }
      setPlanChange(null);
      setNotice(`Plan change scheduled, ${planChange.pkg.name} starts at your next billing cycle.`);
      void load();
    } catch (e) {
      setNotice(String((e as Error).message || e));
    } finally { setPlanBusy(false); }
  };

  const addCard = async () => {
    setPurchasing('card-setup');
    try {
      const { url } = await billing.cardSetup(RETURN_BASE);
      if (url) window.location.href = url;
      else setPurchasing('');
    } catch (e) {
      setNotice(String((e as Error).message || e));
      setPurchasing('');
    }
  };

  return (
    <div className="hr-wrap hrb-content billing-page">
      <div className="page-header" style={{ marginBottom: 18 }}>
        <div><h1 style={{ margin: 0, fontSize: 28, letterSpacing: '-.035em' }}>Credits &amp; Billing</h1>
          <p style={{ margin: '8px 0 0', color: 'var(--muted)', fontSize: 14 }}>Manage your production Credits and payment history.</p></div>
      </div>
      {notice ? <div className="hrb-notice">{notice}</div> : null}

      {/* Top slot: gift stack, the welcome-credits banner (until claimed) above the
          invite-a-friend card, each full width. The saved-card indicator replaces the
          welcome banner once a card is on file. */}
      <div className="hrb-gift-row">
        {!loading && card ? (
          <div className="pay-card-row">
            <div className="pay-card" aria-hidden="true">
              <div className="pay-card-chip" />
              <div className="pay-card-number">**** ****** **{card.last4}</div>
              <div className="pay-card-foot">
                <span className="pay-card-holder">****</span>
                <span className="pay-card-exp"><em>valid thru</em>{cardExp}</span>
              </div>
            </div>
            <div className="pay-card-meta">
              <button className="hr-btn ghost pay-card-update" disabled={Boolean(purchasing)} onClick={addCard}>
                {purchasing === 'card-setup' ? 'Redirecting…' : 'Update Card'}
              </button>
            </div>
          </div>
        ) : !loading && !hasWelcome ? (
          <div className="welcome-banner">
            <div className="welcome-banner-badge"><iconify-icon icon="tabler:gift"></iconify-icon></div>
            <div className="welcome-banner-main">
              <div className="welcome-banner-head">
                <span className="welcome-banner-eyebrow">Launch offer</span>
                <h3 className="welcome-banner-title">Subscribe and get <b>500 bonus credits</b></h3>
              </div>
              <p className="welcome-banner-sub">Start any plan and we&apos;ll add <b>500 credits</b> on top of the credits your plan already includes. They arrive with your first payment.</p>
              <div className="welcome-banner-chips">
                <span className="welcome-chip"><iconify-icon icon="tabler:sparkles"></iconify-icon>+500 on any plan</span>
                <span className="welcome-chip"><iconify-icon icon="tabler:refresh"></iconify-icon>Cancel anytime</span>
                <span className="welcome-chip"><iconify-icon icon="tabler:lock"></iconify-icon>Secured by Stripe</span>
              </div>
            </div>
            <button className="welcome-banner-cta" onClick={() => setWelcomeOpen(true)}>
              <iconify-icon icon="tabler:sparkles"></iconify-icon>View plans
            </button>
          </div>
        ) : null}
      </div>

      <div className="billing-balance-panel" aria-label="Credit balance summary">
        <div className="billing-balance-primary"><span>Available balance</span>
          {loading && balance === null
            ? <div className="hrb-skeleton hrb-skeleton-balance" />
            : <strong>{formatCredits(total)} Credits</strong>}
          <small>Shared across all Workspaces</small></div>
        <div className="billing-balance-stat"><span>Usage</span><strong><Link href="/billing/usage" className="hrb-link">View usage</Link></strong><small>Per-day and per-harness detail</small></div>
        <button className="button primary" type="button"
          onClick={() => document.querySelector('.hrb-plans')?.scrollIntoView({ behavior: 'smooth' })}>Add Credits</button>
      </div>
      {isDeficit ? <div className="hrb-alert hrb-alert-deficit">Your credits are exhausted. Top up now to keep your harnesses running.</div> : null}
      {isLow ? <div className="hrb-alert hrb-alert-low">Credits running low. Top up now to avoid interruptions.</div> : null}

      <h2 style={{ margin: '18px 0 8px', fontSize: 17 }}>Subscriptions</h2>
      <div className="hrb-plans">
        {(loading && plans.length === 0 ? Array.from({ length: 3 }) : plans).map((pkg, i) => {
          if (!pkg) return <div className="hrb-skeleton hrb-skeleton-card" key={i} />;
          const p = pkg as Pkg;
          const isCurrent = sub?.package_id === p.id;
          const popular = plans.length >= 3 && p.id === plans[Math.floor(plans.length / 2)].id;
          const perCredit = Number(p.credits) > 0 ? Number(p.price_usd) / Number(p.credits) : 0;
          const isUpgrade = sub ? Number(p.price_usd) > Number(plans.find((x) => x.id === sub.package_id)?.price_usd || 0) : false;
          return (
            <div className={'hrb-plan' + (isCurrent ? ' current' : '') + (popular ? ' popular' : '')} key={p.id}>
              {isCurrent
                ? <span className="hrb-plan-flag on"><iconify-icon icon="tabler:circle-check-filled"></iconify-icon>Your plan</span>
                : popular ? <span className="hrb-plan-flag">Most popular</span> : null}
              <span className="hrb-plan-name">{p.name}</span>
              <span className="hrb-plan-price">${Number(p.price_usd).toLocaleString()}<small>/mo</small></span>
              <span className="hrb-plan-credits">{formatCredits(p.credits)} Credits / month</span>
              <ul className="hrb-plan-feats">
                <li><iconify-icon icon="tabler:check"></iconify-icon>{perCredit ? `$${perCredit.toFixed(perCredit < 0.03 ? 3 : 2)} per credit` : 'Flat monthly rate'}</li>
                <li><iconify-icon icon="tabler:check"></iconify-icon>Credits renew monthly</li>
                <li><iconify-icon icon="tabler:check"></iconify-icon>All harnesses &amp; models</li>
              </ul>
              {isCurrent && sub ? (
                <>
                  <span className="hrb-plan-sub-state">
                    <iconify-icon icon="tabler:circle-check-filled"></iconify-icon>
                    {sub.status === 'trialing' ? 'Free trial' : 'Active'}
                    {/* A monthly subscription renews by default — no need to state the obvious.
                        Only the CANCELLED state (auto_renew off) carries real, non-obvious info:
                        when access actually ends. */}
                    {sub.auto_renew === '0' ? ` · ends ${formatDate(sub.period_end)}` : ''}
                  </span>
                  {sub.auto_renew !== '0' && (
                    <button className="hr-btn hrb-plan-cta hrb-plan-cancel" type="button"
                      onClick={() => { setCancelReason(''); setCancelFeedback(''); setCancelOpen(true); }}>
                      Cancel subscription</button>
                  )}
                </>
              ) : sub ? (
                <button className={'hr-btn hrb-plan-cta' + (isUpgrade ? ' primary' : '')} type="button"
                  disabled={Boolean(purchasing)}
                  onClick={() => changePlan(p, isUpgrade)}>
                  {purchasing === p.id ? 'Applying…' : isUpgrade ? 'Upgrade now' : 'Downgrade'}
                </button>
              ) : (
                <button className="hr-btn primary hrb-plan-cta" type="button" disabled={Boolean(purchasing)} onClick={() => buy(p)}>
                  {purchasing === p.id ? 'Redirecting…' : 'Subscribe'}
                </button>
              )}
              {!isCurrent && sub ? (
                <span className="hrb-plan-note">
                  {isUpgrade ? 'Checkout now · new credits added on payment, current credits keep their expiry'
                    : 'Takes effect at the next billing cycle'}
                </span>
              ) : null}
            </div>
          );
        })}
      </div>

      <h2 style={{ margin: '18px 0 8px', fontSize: 17 }}>Top-up</h2>
      <p style={{ margin: '0 0 10px', color: 'var(--muted)', fontSize: 13 }}>
        One-time credits, valid for 1 year, choose any amount{topupMin ? ` (minimum $${topupMin})` : ''}.
      </p>
      {loading && !rateCard ? <div className="hrb-skeleton hrb-skeleton-card" /> : rateCard ? (
        <div className="hr-card" style={{ padding: 18, maxWidth: 440 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 20, color: 'var(--muted)' }}>$</span>
            <input className="hr-input" type="number" inputMode="decimal"
                   min={topupMin} step="1" value={topupAmount} style={{ fontSize: 18, width: 140 }}
                   aria-label="Top-up amount in dollars"
                   onChange={(e) => setTopupAmount(e.target.value)} />
            <span style={{ fontSize: 14, color: 'var(--muted)' }}>
              {topupValid
                ? <>= <strong style={{ color: 'var(--fg)' }}>{formatCredits(topupCredits)} Credits</strong></>
                : `Minimum $${topupMin}`}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 14 }}>
            <button className="hr-btn primary" disabled={Boolean(purchasing) || !topupValid} onClick={buyTopup}>
              {purchasing === rateCard.id ? 'Redirecting…' : topupValid ? `Buy ${formatCredits(topupCredits)} Credits` : 'Buy Credits'}
            </button>
            <span style={{ fontSize: 12.5, color: 'var(--muted)' }}>Expires in 1 year</span>
          </div>
        </div>
      ) : null}

      <h2 style={{ margin: '18px 0 8px', fontSize: 17 }}>Credit History</h2>
      <div className="hr-card hrb-table-card">
        <div className="hrb-table-scroll">
          <table className="hrb-table">
            <thead>
              <tr>
                <th>Type</th><th>Credit Balance</th><th>Granted At</th><th>Expires At</th>
                <th>Status</th><th>Amount Paid</th><th>Invoice</th>
              </tr>
            </thead>
            <tbody>
              {loading && lots.length === 0 ? (
                <SkelRows rows={3} cols={7} first={110} />
              ) : pageLots.length === 0 ? (
                <tr><td colSpan={7} className="hrb-table-empty">No credit history yet</td></tr>
              ) : pageLots.map((l) => {
                const od = l.source === 'deficit';
                return (
                  <tr key={l.id} className={od ? 'hrb-row-overdraft' : ''}>
                    <td>{l.source === 'subscription'
                      ? (packages.find((p) => p.id === l.package_id)?.name || sourceLabel(l.source))
                      : sourceLabel(l.source)}</td>
                    <td>{od ? formatCredits(l.credits_remaining) : `${formatCredits(l.credits_remaining)}/${formatCredits(l.credits_initial)}`}</td>
                    <td>{formatDate(l.granted_at)}</td>
                    <td>{od ? 'N/A' : formatDate(l.expires_at)}</td>
                    <td><span className={`hrb-pill hrb-pill-${STATUS_PILL[od ? 'deficit' : l.status] || 'mute'}`}>
                      {od ? 'Overdraft' : (l.status || '').replace(/^./, (c) => c.toUpperCase())}
                    </span></td>
                    <td>{l.amount_paid_cents ? `$${(Number(l.amount_paid_cents) / 100).toFixed(2)}` : 'N/A'}</td>
                    <td>
                      {l.invoice_url
                        ? <a className="hrb-link" href={l.invoice_url} target="_blank" rel="noopener noreferrer">Download</a>
                        : l.receipt_url
                          ? <a className="hrb-link" href={l.receipt_url} target="_blank" rel="noopener noreferrer">Receipt</a>
                          : 'N/A'}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {totalPages > 1 ? (
          <div className="hrb-pager">
            <button className="hr-btn ghost" disabled={page === 1} onClick={() => setPage(page - 1)}>Prev</button>
            {Array.from({ length: totalPages }).map((_, i) => (
              <button key={i} className={`hr-btn ${page === i + 1 ? 'primary' : 'ghost'}`} onClick={() => setPage(i + 1)}>{i + 1}</button>
            ))}
            <button className="hr-btn ghost" disabled={page === totalPages} onClick={() => setPage(page + 1)}>Next</button>
          </div>
        ) : null}
      </div>
      {welcomeOpen ? <WelcomePlansModal plans={plans} onClose={() => setWelcomeOpen(false)} /> : null}
      {planChange ? (
        <div className="modal-backdrop">
          <section className="modal" role="dialog" aria-modal="true" aria-labelledby="planChangeTitle" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div><h2 id="planChangeTitle">{planChange.upgrade ? `Upgrade to ${planChange.pkg.name}?` : `Switch to ${planChange.pkg.name}?`}</h2>
                <p>
                  {planChange.upgrade
                    ? `You'll be taken to checkout for $${Number(planChange.pkg.price_usd).toLocaleString()}. On payment, ${formatCredits(planChange.pkg.credits)} credits are added immediately and your current plan stops billing. Credits you already have keep their original expiration.`
                    : `Nothing changes today, ${planChange.pkg.name} (${formatCredits(planChange.pkg.credits)} credits / month at $${Number(planChange.pkg.price_usd).toLocaleString()}/mo) starts at your next billing cycle.`}
                </p></div>
              <button className="icon-button modal-close" type="button" aria-label="Close dialog" onClick={() => !planBusy && setPlanChange(null)}><iconify-icon icon="tabler:x"></iconify-icon></button>
            </div>
            <div className="modal-body">
              <div className="modal-actions">
                <button className="button" type="button" disabled={planBusy} onClick={() => setPlanChange(null)}>Keep current plan</button>
                <button className="button primary" type="button" disabled={planBusy} onClick={() => void confirmPlanChange()}>
                  {planBusy ? (planChange.upgrade ? 'Redirecting…' : 'Applying…') : planChange.upgrade ? 'Continue to checkout' : 'Confirm change'}
                </button>
              </div>
            </div>
          </section>
        </div>
      ) : null}
      {cancelOpen ? (
        <div className="modal-backdrop">
          <section className="modal" role="dialog" aria-modal="true" aria-labelledby="cancelSubTitle" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div><h2 id="cancelSubTitle">Cancel subscription</h2>
                <p>You keep your plan and credits until the end of the current period. We&rsquo;d love to know why you&rsquo;re leaving.</p></div>
              <button className="icon-button modal-close" type="button" aria-label="Close dialog" onClick={() => setCancelOpen(false)}><iconify-icon icon="tabler:x"></iconify-icon></button>
            </div>
            <div className="modal-body">
              <div className="field-stack">
                <div className="field"><label>Why are you cancelling?</label>
                  <div className="hrb-cancel-reasons" role="radiogroup" aria-label="Cancellation reason">
                    {['Too expensive', 'Not using it enough', 'Missing features I need', 'Ran into problems or bugs', 'Switching to another tool', 'Other'].map((r) => (
                      <label key={r} className={'hrb-cancel-reason' + (cancelReason === r ? ' on' : '')}>
                        <input type="radio" name="cancelReason" checked={cancelReason === r} onChange={() => setCancelReason(r)} />
                        <span className="hrb-cancel-dot" aria-hidden="true" />
                        <span className="hrb-cancel-label">{r}</span>
                      </label>
                    ))}
                  </div>
                </div>
                <div className="field"><label htmlFor="cancelFb">Anything else you&rsquo;d like us to know? <span className="optional-label">Optional</span></label>
                  <textarea id="cancelFb" rows={3} value={cancelFeedback} placeholder="What could we have done better?"
                    onChange={(e) => setCancelFeedback(e.target.value)} /></div>
              </div>
              <div className="modal-actions">
                <button className="button" type="button" disabled={cancelBusy} onClick={() => setCancelOpen(false)}>Keep my plan</button>
                <button className="button danger" type="button" disabled={cancelBusy || !cancelReason}
                  onClick={async () => {
                    setCancelBusy(true);
                    try {
                      await billing.cancelSubscription(cancelReason, cancelFeedback.trim());
                      setCancelOpen(false);
                      setNotice('Subscription cancelled, your plan stays active until the end of the current period.');
                      void load();
                    } catch (e) {
                      setNotice(String((e as Error).message || e));
                    } finally { setCancelBusy(false); }
                  }}>{cancelBusy ? 'Cancelling…' : 'Continue cancel'}</button>
              </div>
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}
