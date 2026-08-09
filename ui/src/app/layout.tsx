import type { Metadata } from 'next';
import 'reifyui/styles/themes/light.css';
import 'reifyui/styles/chat.css';
import 'reifyui/styles/tasks.css';
import './globals.css';
import { Nav } from '@/components/Nav';

export const metadata: Metadata = {
  title: 'HarnessRouter',
  description: 'Self-hosted harness management',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="shell">
          <Nav />
          <main className="main">{children}</main>
        </div>
      </body>
    </html>
  );
}
