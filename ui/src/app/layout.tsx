import type { Metadata } from 'next';
import localFont from 'next/font/local';

// Unified with the HarnessRouter marketing landing: paper theme + accent blue (#285AFF)
// and IBM Plex Sans/Mono with a Schibsted Grotesk display face for the wordmark.
import '@/studio/styles/tokens.css';
import '@/studio/styles/chrome.css';
import '@/studio/styles/page.css';
import '@/studio/styles/dialog.css';
import '@/studio/styles/traces.css';
import 'reifyui/styles/chat.css';
// chip.css carries the Chip / Popover / CascadeMenu skins (the hosted tree inlines them in its
// chat.css; the package factors them out) — without it every chip menu renders bare.
import 'reifyui/styles/chip.css';
import './hr.css';
import './hr-billing.css';
// v2 re-skin: MUST load last — its :root remaps every legacy token (fonts, inks, accent) so
// un-migrated pages inherit the v2 look without edits. See harness_router_v2_design/CLAUDE.md.
import './v2.css';

// The faces come from the pinned @fontsource packages (OFL-1.1, the license inside each package), not
// from Google at build time: next/font/google downloads every face while the console builds, and a
// failed download fails the build ("An error occurred in `next/font`. TypeError: Cannot read
// properties of null (reading '1')", main after #467 on 2026-10-15, and the console check before
// it). The same faces, weights and Latin subset, under the same variables. next/font takes only
// literals here, so each file is written out.
const sans = localFont({ variable: '--font-ibm-sans', display: 'swap', src: [
  { path: '../../node_modules/@fontsource/ibm-plex-sans/files/ibm-plex-sans-latin-400-normal.woff2', weight: '400', style: 'normal' },
  { path: '../../node_modules/@fontsource/ibm-plex-sans/files/ibm-plex-sans-latin-500-normal.woff2', weight: '500', style: 'normal' },
  { path: '../../node_modules/@fontsource/ibm-plex-sans/files/ibm-plex-sans-latin-600-normal.woff2', weight: '600', style: 'normal' },
  { path: '../../node_modules/@fontsource/ibm-plex-sans/files/ibm-plex-sans-latin-700-normal.woff2', weight: '700', style: 'normal' },
] });
const mono = localFont({ variable: '--font-ibm-mono', display: 'swap', src: [
  { path: '../../node_modules/@fontsource/ibm-plex-mono/files/ibm-plex-mono-latin-400-normal.woff2', weight: '400', style: 'normal' },
  { path: '../../node_modules/@fontsource/ibm-plex-mono/files/ibm-plex-mono-latin-500-normal.woff2', weight: '500', style: 'normal' },
  { path: '../../node_modules/@fontsource/ibm-plex-mono/files/ibm-plex-mono-latin-600-normal.woff2', weight: '600', style: 'normal' },
] });
// Schibsted Grotesk is one variable file, 400 to 900 (its own @font-face says so).
const display = localFont({ variable: '--font-grotesk', display: 'swap', weight: '400 900', style: 'normal',
  src: '../../node_modules/@fontsource-variable/schibsted-grotesk/files/schibsted-grotesk-latin-wght-normal.woff2' });
const inter = localFont({ variable: '--font-inter', display: 'swap', src: [
  { path: '../../node_modules/@fontsource/inter/files/inter-latin-400-normal.woff2', weight: '400', style: 'normal' },
  { path: '../../node_modules/@fontsource/inter/files/inter-latin-500-normal.woff2', weight: '500', style: 'normal' },
  { path: '../../node_modules/@fontsource/inter/files/inter-latin-600-normal.woff2', weight: '600', style: 'normal' },
  { path: '../../node_modules/@fontsource/inter/files/inter-latin-700-normal.woff2', weight: '700', style: 'normal' },
] });
const jbmono = localFont({ variable: '--font-jbmono', display: 'swap', src: [
  { path: '../../node_modules/@fontsource/jetbrains-mono/files/jetbrains-mono-latin-400-normal.woff2', weight: '400', style: 'normal' },
  { path: '../../node_modules/@fontsource/jetbrains-mono/files/jetbrains-mono-latin-500-normal.woff2', weight: '500', style: 'normal' },
  { path: '../../node_modules/@fontsource/jetbrains-mono/files/jetbrains-mono-latin-600-normal.woff2', weight: '600', style: 'normal' },
] });

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
