// The one way into a setup that has just been made: every path that makes a setup (New setup, Duplicate
// in a setup's Settings, a kit launched from the Shop) lands on that setup's own page, on its Tasks,
// through this function and no other. start/open.test.ts holds every navigation in the console to
// this rule.
import { markMade } from './seed';

/** Where a setup just made opens: its own page, by its id. */
export type NewSetupTarget = { id: string };

export function newSetupHref(to: NewSetupTarget): string {
  return `/studio/${encodeURIComponent(to.id)}`;
}

interface Nav { push: (href: string) => void; replace: (href: string) => void }

/** Open the setup just made on its Tasks. Its page waits for it rather than call it missing while the
 *  server catches up with the create. */
export function openNewSetup(nav: Nav, to: NewSetupTarget): void {
  markMade(to.id);
  nav.push(newSetupHref(to));
}
