import type { Metadata } from 'next';
import 'reifyui/styles/themes/light.css';
import 'reifyui/styles/chat.css';
import 'reifyui/styles/tasks.css';
import 'reifyui/styles/dialog.css';
import './globals.css';
import { Providers } from '@/components/Providers';
import { Nav } from '@/components/Nav';

export const metadata: Metadata = {
  title: 'HarnessRouter',
  description: 'Self-hosted harness management',
  icons: { icon: '/favicon.svg' },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>
          <div className="shell">
            <Nav />
            <main className="main">{children}</main>
          </div>
        </Providers>
      </body>
    </html>
  );
}
