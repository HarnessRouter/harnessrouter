'use client';
// Monetization, per the finalized 2026-07-19 design revision (prototype view-monetization):
// Overview / Products & pricing / Customers & access / Payouts tabs.
// The Stripe Connect backend is CT-125 (in progress): every number here is server-provided
// once connected, nothing is invented client-side. Until then each tab shows its real
// not-connected state, and the static explainers (settlement flow, fee policy) render as
// designed so developers understand the contract before onboarding.
import { useState } from 'react';
import { useWorkspace } from '@/lib/workspace';

const TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'products', label: 'Products & pricing' },
  { id: 'customers', label: 'Customers & access' },
  { id: 'payouts', label: 'Payouts' },
] as const;
type TabId = typeof TABS[number]['id'];

function NotConnected({ children }: { children?: React.ReactNode }) {
  return (
    <div className="dashboard-card" style={{ padding: 28 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 14 }}>
        <iconify-icon icon="tabler:building-bank" style={{ fontSize: 26, color: 'var(--accent)' }}></iconify-icon>
        <div>
          <h2 style={{ margin: 0, fontSize: 16 }}>Stripe is not connected yet</h2>
          <p style={{ margin: '6px 0 0', color: 'var(--muted)', fontSize: 13, maxWidth: 640, lineHeight: 1.55 }}>
            Monetization turns on when this Workspace connects a Stripe account. Secure Stripe
            onboarding creates the connected payout account and collects identity and bank
            details, a prior Stripe account is not required.
          </p>
          {children}
          <button className="button primary" type="button" disabled title="Stripe Connect onboarding is being built"
            style={{ marginTop: 14 }}>
            <iconify-icon icon="tabler:plug-connected"></iconify-icon>Connect Stripe, coming soon
          </button>
        </div>
      </div>
    </div>
  );
}

export default function MonetizationPage() {
  const { current } = useWorkspace();
  const [tab, setTab] = useState<TabId>('overview');

  return (
    <section className="view is-active" id="view-monetization">
      <div className="page">
        <div className="page-header">
          <div><h1>Monetization</h1><p>Manage what end users can buy, verify their access, and understand the revenue of <span className="workspace-name">{current.name}</span>.</p></div>
        </div>
        <div className="tabs monetization-tabs" role="tablist" aria-label="Monetization sections">
          {TABS.map((t) => (
            <button key={t.id} className="tab" role="tab" aria-selected={tab === t.id}
              onClick={() => setTab(t.id)}>{t.label}</button>
          ))}
        </div>

        {tab === 'overview' && (
          <div className="tab-panel is-active">
            <div className="dashboard-card-head">
              <div><h2>Business performance</h2><p>Payments from end users of this Workspace.</p></div>
            </div>
            <div className="dashboard-kpis" aria-label="Revenue key metrics">
              <div className="kpi-card green"><span>Gross revenue (MTD, USD)</span><strong>—</strong><small>Successful end-user payments</small><iconify-icon icon="tabler:currency-dollar"></iconify-icon></div>
              <div className="kpi-card"><span>Net sales (MTD, USD)</span><strong>—</strong><small>After fees and refunds</small><iconify-icon icon="tabler:chart-line"></iconify-icon></div>
              <div className="kpi-card primary-tint"><span>Pending balance</span><strong>—</strong><small>Inside the 7-day refund hold</small><iconify-icon icon="tabler:clock-hour-4"></iconify-icon></div>
              <div className="kpi-card blue"><span>Available to payout</span><strong>—</strong><small>Net of fees, refunds, and holds</small><iconify-icon icon="tabler:building-bank"></iconify-icon></div>
            </div>
            <NotConnected>
              <p style={{ margin: '10px 0 0', color: 'var(--muted)', fontSize: 13, maxWidth: 640, lineHeight: 1.55 }}>
                Once connected, this tab shows gross revenue, net sales, the revenue trend, product
                performance, and every payment and refund, all reconciled server-side.
              </p>
            </NotConnected>
          </div>
        )}

        {tab === 'products' && (
          <div className="tab-panel is-active">
            <div className="monetization-panel-head">
              <div><h2>Products &amp; pricing</h2><p>Define what end users buy and the App access each purchase unlocks.</p></div>
              <button className="button primary" type="button" disabled title="Available after Stripe is connected">
                <iconify-icon icon="tabler:plus"></iconify-icon>New product
              </button>
            </div>
            <div className="dashboard-card" style={{ padding: 24 }}>
              <p style={{ margin: 0, color: 'var(--muted)', fontSize: 13, lineHeight: 1.55, maxWidth: 680 }}>
                Products define a price (one-time or monthly) and the App Credits a purchase unlocks
                inside your product. Product prices and App Credits belong to this Workspace business;
                HarnessRouter production Credits remain account-wide under Credits &amp; Billing.
                Product creation opens after Stripe is connected.
              </p>
              <p style={{ margin: '10px 0 0', color: 'var(--muted)', fontSize: 12.5 }}>
                <span className="info-label">Platform fee
                  <span className="info-tip" tabIndex={0} aria-label="Platform fee details">
                    <iconify-icon icon="tabler:info-circle"></iconify-icon>
                    <span className="info-tip-content" role="tooltip">HarnessRouter charges 5% of successful pre-tax payments. Stripe processing and payout fees are separate and vary.</span>
                  </span>
                </span>
              </p>
            </div>
          </div>
        )}

        {tab === 'customers' && (
          <div className="tab-panel is-active">
            <div className="monetization-panel-head"><div><h2>Customers &amp; access</h2><p>Confirm which product a customer owns and whether the corresponding App access is available.</p></div></div>
            <div className="dashboard-card" style={{ padding: 24 }}>
              <p style={{ margin: 0, color: 'var(--muted)', fontSize: 13, lineHeight: 1.55, maxWidth: 680 }}>
                Paying customers appear here with their product, access status, remaining App Credits,
                and renewal date, populated from real purchases once Stripe is connected and your
                product sells its first plan.
              </p>
            </div>
          </div>
        )}

        {tab === 'payouts' && (
          <div className="tab-panel is-active">
            <div className="monetization-panel-head"><div><h2>Payouts</h2><p>Understand when end-user revenue becomes available and where HarnessRouter sends it.</p></div></div>
            <NotConnected />
            <div className="section-header"><h2>Settlement flow</h2></div>
            <div className="money-flow" aria-label="End-user payment flow">
              <div className="money-flow-step"><strong>End-user payment</strong><span>Creates product access immediately.</span></div><iconify-icon icon="tabler:arrow-right"></iconify-icon>
              <div className="money-flow-step"><strong>Pending · 7 days</strong><span>Held for the Workspace refund policy.</span></div><iconify-icon icon="tabler:arrow-right"></iconify-icon>
              <div className="money-flow-step"><strong>Available balance</strong><span>Net amount eligible for payout.</span></div><iconify-icon icon="tabler:arrow-right"></iconify-icon>
              <div className="money-flow-step"><strong>Bank payout</strong><span>Transferred according to Stripe payout settings.</span></div>
            </div>
            <div className="payout-guidance"><iconify-icon icon="tabler:info-circle"></iconify-icon><p><strong>Revenue is not immediately withdrawable.</strong> New payments remain pending during the 7-day refund hold. Refunds appear in Monetization Overview and reduce the balance before it becomes available.</p></div>
            <p className="monetization-note">A prior Stripe account is not required. Secure Stripe onboarding creates the connected payout account and collects identity and bank details. Eligible debit cards can support Instant Payouts in selected regions; a standard credit card is not a payout destination.</p>
          </div>
        )}
      </div>
    </section>
  );
}
