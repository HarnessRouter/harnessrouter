// The redesign's line icons, drawn as the design draws them (24 viewBox, 1.8 stroke).
import type { ReactNode } from 'react';

function Svg({ children, cap = true }: { children: ReactNode; cap?: boolean }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}
      strokeLinecap={cap ? 'round' : undefined} strokeLinejoin="round" aria-hidden="true">{children}</svg>
  );
}

export const Ic = {
  start: <Svg><circle cx="12" cy="12" r="8.5" /><path d="M10.2 8.9l5 3.1-5 3.1z" /></Svg>,
  studio: <Svg cap={false}><rect x="3.5" y="9" width="17" height="10.5" rx="2" /><rect x="6.5" y="5" width="4" height="4" rx="1" /><rect x="13.5" y="5" width="4" height="4" rx="1" /></Svg>,
  arena: <Svg cap={false}><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M9 4v16M15 4v16" /></Svg>,
  shop: <Svg><path d="M6 7.5h12l1 12.5H5L6 7.5z" /><path d="M9 10V6.5a3 3 0 0 1 6 0V10" /><path d="M5.4 15h13.2" /></Svg>,
  extensions: <Svg cap={false}><rect x="3" y="10" width="8" height="10" rx="1.5" /><rect x="13" y="10" width="8" height="10" rx="1.5" /><path d="M5 10V8M9 10V8M15 10V8M19 10V8" /></Svg>,
  keys: <Svg cap={false}><circle cx="8" cy="15" r="4" /><path d="M11 12l9-9M17 6l3 3" /></Svg>,
  usage: <Svg><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></Svg>,
  letter: <Svg><rect x="3" y="5.5" width="18" height="13" rx="2" /><path d="M3.5 7l8.5 6 8.5-6" /></Svg>,
  billing: <Svg><rect x="3" y="5.5" width="18" height="13" rx="2.2" /><path d="M3 10h18M7 15h4" /></Svg>,
  byok: <Svg><path d="M9 3v4M15 3v4M6.5 7h11v4a5.5 5.5 0 0 1-11 0V7zM12 16.5V21" /></Svg>,
  plans: <Svg><path d="M3 6l2 2 3-3M3 13l2 2 3-3M12 7h9M12 14h9M3 20h18" /></Svg>,
  docs: <Svg><path d="M6 3h9l4 4v14H6z" /><path d="M14 3v5h5M9 13h7M9 17h5" /></Svg>,
  discord: <Svg><path d="M7.9 20A9 9 0 1 0 4 16.1L2 22z" /></Svg>,
  calendar: <Svg><rect x="3" y="4" width="18" height="18" rx="2" /><path d="M16 2v4M8 2v4M3 10h18" /></Svg>,
  github: <Svg><path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.4 5.4 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4" /><path d="M9 18c-4.51 2-5-2-7-2" /></Svg>,
  logout: <Svg><path d="M15 4h4v16h-4M10 8l-4 4 4 4M6 12h11" /></Svg>,
  star: <Svg><path d="M12 3.5l2.6 5.3 5.8.8-4.2 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8-4.2-4.1 5.8-.8z" /></Svg>,
  check: <Svg><path d="M5 12.5l4.5 4.5L19 7.5" /></Svg>,
  x: <Svg><path d="M6 6l12 12M18 6L6 18" /></Svg>,
  staff: <Svg><circle cx="12" cy="8" r="3.5" /><path d="M5 20c.8-3.6 3.6-5.5 7-5.5s6.2 1.9 7 5.5" /></Svg>,
  people: <Svg><circle cx="9" cy="8.5" r="3.2" /><path d="M3 19.5c.7-3.2 3-5 6-5s5.3 1.8 6 5" /><path d="M15.5 5.6a3.2 3.2 0 0 1 0 5.8M17.5 14.8c1.8.6 3 2.2 3.5 4.7" /></Svg>,
  // Account (the account menu): a person in a circle, apart from Staff's bare person
  account: <Svg><circle cx="12" cy="12" r="9" /><circle cx="12" cy="10" r="3" /><path d="M6.6 18.4c1.2-2 3.1-3.1 5.4-3.1s4.2 1.1 5.4 3.1" /></Svg>,
};
