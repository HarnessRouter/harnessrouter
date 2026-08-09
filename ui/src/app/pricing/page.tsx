import Link from 'next/link';
export const metadata = { title: 'Pricing' };
export default function Pricing() {
  return (
    <div className="hr-wrap">
      <nav className="lp-nav" style={{ padding: 0, marginBottom: 12 }}>
        {/* eslint-disable-next-line @next/next/no-img-element -- static brand asset */}
        <Link href="/" className="hr-brand" aria-label="HarnessRouter"><img className="hr-brand-logo" src="/harnessrouter-wordmark.png" alt="HarnessRouter" /></Link>
        <span className="sp" /><Link href="/login" className="hr-btn primary">Get API key</Link>
      </nav>
      <h2 className="hr-h2">Pricing</h2>
      <p className="hr-meta">Usage-based pricing. Details coming soon.</p>
    </div>
  );
}
