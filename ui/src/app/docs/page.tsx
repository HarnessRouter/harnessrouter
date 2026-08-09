import Link from 'next/link';
export const metadata = { title: 'Docs' };
export default function Docs() {
  return (
    <div className="hr-wrap">
      <nav className="lp-nav" style={{ padding: 0, marginBottom: 12 }}>
        {/* eslint-disable-next-line @next/next/no-img-element -- static brand asset */}
        <Link href="/" className="hr-brand" aria-label="HarnessRouter"><img className="hr-brand-logo" src="/harnessrouter-wordmark.png" alt="HarnessRouter" /></Link>
        <span className="sp" /><Link href="/login" className="hr-btn primary">Get API key</Link>
      </nav>
      <h2 className="hr-h2">Docs</h2>
      <p className="hr-meta">Quickstart: get an API key, then route any request to a harness.</p>
      <pre style={{ background: '#0B0F1A', color: '#E6E9F0', padding: 18, borderRadius: 12, fontSize: 13 }}>{`curl https://api.harnessrouter.com/v1/run \\
  -H "Authorization: Bearer $HARNESSROUTER_API_KEY" \\
  -d '{"harness":"claude-code","input":"Hello"}'`}</pre>
    </div>
  );
}
