// Billing helpers, engine /v1/billing/* via the /api/engine BFF (authFetch).
import { authFetch } from '@/lib/auth';

async function jget(path: string) {
  const r = await authFetch(path);
  if (!r.ok) throw new Error(`${r.status} ${await r.text().catch(() => '')}`);
  return r.json();
}
async function jpost(path: string, body: unknown) {
  const r = await authFetch(path, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status} ${await r.text().catch(() => '')}`);
  return r.json();
}

// The pricing endpoint returns the shared rate card across every product on the platform. Only the
// metrics HarnessRouter actually charges may surface here — token rates for the chat models it runs
// (never embeddings, which it doesn't serve), plus its own session-minute and storage rates. Any
// other product's metrics (e.g. a coaching/review unit price) must never appear on a HarnessRouter
// surface. Deny by default so a new product's rows can't leak in.
export function isHrPriceMetric(metric: string): boolean {
  if (metric.startsWith('harness.') || metric.startsWith('storage.')) return true;
  if (metric.startsWith('llm.')) return !/embed/i.test(metric);
  return false;
}

export const billing = {
  balance: () => jget('/v1/billing/balance'),
  packages: () => jget('/v1/billing/packages'),
  pricing: async () => {
    const d = await jget('/v1/billing/pricing');
    return { ...d, items: (d.items || []).filter((i: { metric?: string }) => isHrPriceMetric(i.metric || '')) };
  },
  usage: (q: { from: string; to: string; bucket: string; app?: string }) => {
    const p = new URLSearchParams({ from: q.from, to: q.to, bucket: q.bucket });
    if (q.app) p.set('app', q.app);
    return jget(`/v1/billing/usage?${p.toString()}`);
  },
  checkout: (packageId: string, returnBase: string) =>
    jpost('/v1/billing/checkout', { package_id: packageId, return_base: returnBase }),
  /** Custom-amount top-up against the rate-card package (server recomputes credits + enforces
   *  the minimum, the client number is display-only). */
  checkoutTopup: (packageId: string, amountUsd: number, returnBase: string) =>
    jpost('/v1/billing/checkout', { package_id: packageId, amount_usd: amountUsd, return_base: returnBase }),
  /** Card-add flow ($0 today): saves a card for later billing. It grants nothing — the card is
   *  recorded so the one-card-one-bonus rule can see it. The only promotion is the subscribe
   *  bonus, minted server-side on the first PAID invoice. */
  cardSetup: (returnBase: string) =>
    jpost('/v1/billing/checkout', { package_id: 'card-setup', return_base: returnBase }),
  subscription: () => jget('/v1/billing/subscription'),
  cancelSubscription: (reason: string, feedback: string) =>
    jpost('/v1/billing/subscription/cancel', { reason, feedback }),
  /** Plan switch: an upgrade returns a Stripe checkout url (new purchase now, the paid
   *  invoice replaces the old subscription); a downgrade reschedules the same subscription's
   *  next purchase. */
  changeSubscription: (packageId: string, returnBase: string) =>
    jpost('/v1/billing/subscription/change', { package_id: packageId, return_base: returnBase }),
};

export const RETURN_BASE = 'https://app.harnessrouter.ai';
export const LOW_CREDITS = 50;

// Invite redemption happens SERVER-SIDE at account creation (the register/Google call carries the
// code, and the engine redeems it against the just-made org). The referral is thus established the
// moment the account exists, independent of which browser later opens the verification email. The
// only client job is to carry the code from the /login?invite=CODE URL to that sign-up request; a
// localStorage bridge keeps it across the sign-in ⇄ register toggle on the login page.
const PENDING_INVITE = 'hr.pending_invite';

/** Stash an invite code seen in the URL so it survives the sign-in ⇄ register toggle on /login. */
export function stashInvite(code: string | null | undefined): void {
  if (!code) return;
  try { localStorage.setItem(PENDING_INVITE, code); } catch { /* private mode, skip */ }
}

/** Read and clear the stashed invite, to hand to the register/Google sign-up request exactly once. */
export function takePendingInvite(): string {
  try {
    const code = localStorage.getItem(PENDING_INVITE) || '';
    if (code) localStorage.removeItem(PENDING_INVITE);
    return code;
  } catch { return ''; }
}

/** The one-time welcome grant is enabled iff its deterministic lot exists (any status —
 *  presence means a card was added at least once). */
export function welcomeEnabled(lots: Array<{ id: string }> | undefined): boolean {
  return (lots || []).some((l) => String(l.id || '').startsWith('lot.welcome.'));
}

export function formatCredits(n: unknown): string {
  return new Intl.NumberFormat('en-US').format(Math.round(Number(n) || 0));
}
export function formatSpent(n: unknown): string {
  const v = Number(n) || 0;
  if (v > 0 && v < 1) return v.toFixed(4);
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(v);
}
export function formatDate(iso?: string): string {
  if (!iso) return 'N/A';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return 'N/A';
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
}
const SOURCE_LABELS: Record<string, string> = {
  signup_bonus: 'Sign Up', referrer_bonus: 'Referral Reward', referee_bonus: 'Invited Bonus',
  referral_bonus: 'Referral Bonus', topup: 'Purchase', subscription: 'Subscription',
  admin_grant: 'Admin Grant', launch_bonus: 'Launch Bonus', deficit: 'Overdraft',
};
export const sourceLabel = (s?: string) => SOURCE_LABELS[s || ''] || s || 'Grant';

export function metricInfo(metric: string): { group: string; label: string; unit: string } {
  if (metric === 'harness.session_minute') return { group: 'Harness', label: 'Harness session', unit: 'credits / minute' };
  if (metric === 'storage.gb_day') return { group: 'Storage', label: 'Storage', unit: 'credits / GB / day' };
  const m = /^llm\.(.+)\.(input_1k|cached_input_1k|cache_read_1k|cache_write_1k|output_1k)$/.exec(metric || '');
  if (m) {
    const kind = { input_1k: 'input', cached_input_1k: 'cached input', cache_read_1k: 'cache read', cache_write_1k: 'cache write', output_1k: 'output' }[m[2] as never];
    return { group: m[1], label: `${m[1]} ${kind}`, unit: 'credits / 1k tokens' };
  }
  return { group: 'Other', label: metric, unit: 'credits / unit' };
}
