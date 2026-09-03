import type { Metadata } from 'next';
import { IBM_Plex_Sans, IBM_Plex_Mono, Schibsted_Grotesk, Inter, JetBrains_Mono } from 'next/font/google';

// Unified with the HarnessRouter marketing landing: paper theme + accent blue (#285AFF)
// and IBM Plex Sans/Mono with a Schibsted Grotesk display face for the wordmark.
import '@/studio/styles/tokens.css';
import '@/studio/styles/chrome.css';
import '@/studio/styles/page.css';
import '@/studio/styles/dialog.css';
import '@/studio/styles/traces.css';
import 'reifyui/styles/chat.css';
import './hr.css';
import './hr-billing.css';
// v2 re-skin: MUST load last — its :root remaps every legacy token (fonts, inks, accent) so
// un-migrated pages inherit the v2 look without edits. See harness_router_v2_design/CLAUDE.md.
import './v2.css';

const sans = IBM_Plex_Sans({ variable: '--font-ibm-sans', subsets: ['latin'], weight: ['400', '500', '600', '700'] });
const mono = IBM_Plex_Mono({ variable: '--font-ibm-mono', subsets: ['latin'], weight: ['400', '500', '600'] });
const display = Schibsted_Grotesk({ variable: '--font-grotesk', subsets: ['latin'], weight: 'variable' });
const inter = Inter({ variable: '--font-inter', subsets: ['latin'], weight: ['400', '500', '600', '700'] });
const jbmono = JetBrains_Mono({ variable: '--font-jbmono', subsets: ['latin'], weight: ['400', '500', '600'] });

const SITE = 'https://app.harnessrouter.ai';
// Self-hosted bills nothing and indexes nothing — a private box must not describe itself in
// hosted terms, and must not invite a crawler.
const SELF_HOSTED = process.env.NEXT_PUBLIC_HR_EDITION === 'selfhost';
const DESC = SELF_HOSTED
  ? 'Run coding agents like Codex, Claude Code and Hermes on your own machine, with your own keys.'
  : 'One API routes your app to coding agents like Codex, Claude Code, Hermes, and Pi: '
    + 'run tasks, stream results, and pay per use with credits.';

export const metadata: Metadata = {
  metadataBase: new URL(SITE),
  title: { default: 'HarnessRouter: one API for every coding agent', template: '%s · HarnessRouter' },
  description: DESC,
  applicationName: 'HarnessRouter',
  keywords: ['coding agent API', 'Codex', 'Claude Code', 'Hermes', 'agent harness', 'AI agent router'],
  openGraph: {
    type: 'website', siteName: 'HarnessRouter', url: SITE,
    title: 'HarnessRouter, one API for every coding agent', description: DESC,
    images: ['/icon.png'],
  },
  twitter: { card: 'summary', title: 'HarnessRouter', description: DESC, images: ['/icon.png'] },
  robots: SELF_HOSTED ? { index: false, follow: false } : { index: true, follow: true },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable} ${display.variable} ${inter.variable} ${jbmono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
