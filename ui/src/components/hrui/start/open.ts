// The one way into a setup that has just been made (Richard, 2026-10-19: "无论什么情况下，包括你创建的
// 下一步，都应该进入到 Task 界面里面去 ... 把所有这种旁路全都去掉"). Every path that makes a setup lands on
// that setup's Tasks, on its first task, through this function and no other:
//   - New setup's Save (composed, or an unchanged demo preset from its recording): the
//     setup's page before the setup exists (/studio/new?b=<key>, start/BuildPage.tsx), which goes on
//     to the setup's own page the moment the setup has its id, through here again;
//   - Duplicate (a setup's Settings), a team's listing copied from the Shop, a kit launched to users.
// Nothing after a create goes to Harness Studio or anywhere else, whatever happens: a failure before the
// setup exists is shown where the person is, with Try again; a failure after it exists (a plugin that
// did not attach) is said on the setup's own page. start/open.test.ts holds every navigation in the
// console to this rule.
import { markMade } from './seed';

/** Where a setup just made opens: its own page by its id, or, while it is being made, its page before
 *  the setup exists, by the key of the work that makes it (start/build.ts). */
export type NewSetupTarget = { id: string } | { build: string };

export function newSetupHref(to: NewSetupTarget): string {
  return 'id' in to ? `/studio/${encodeURIComponent(to.id)}` : `/studio/new?b=${encodeURIComponent(to.build)}`;
}

interface Nav { push: (href: string) => void; replace: (href: string) => void }

/** Open the setup just made (or being made) on its Tasks. From the page of a setup being made, the
 *  setup's own page takes that page's place in the history, so Back goes where the person was before. */
export function openNewSetup(nav: Nav, to: NewSetupTarget, here: string = typeof window === 'undefined' ? '' : window.location.pathname): void {
  const href = newSetupHref(to);
  // its page waits for it rather than call it missing while the server catches up with the create
  if ('id' in to) markMade(to.id);
  if (here === '/studio/new') nav.replace(href);
  else nav.push(href);
}
