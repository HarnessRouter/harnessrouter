'use client';
// The line between what a branched task brought with it and what has happened in it since: "Continued
// from <the task it was branched from>", the title a link back to that task (issue #477).
import Link from 'next/link';

export const BRANCH_ICON = <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M6 3v12" /><circle cx="18" cy="6" r="3" /><circle cx="6" cy="18" r="3" /><path d="M18 9a9 9 0 0 1-9 9" /></svg>;

/** `href` is empty when the original task can't be opened (deleted, or out of this person's reach: the
 *  service answers both alike): the line stays, as words only. `title` is empty when the original's
 *  could not be read, and it is then called what it surely is, never guessed: "an earlier task". */
export function BranchMark({ href, title }: { href: string; title: string }) {
  const name = title.trim() || (href ? 'the original task' : 'an earlier task');
  return (
    <div className="pg-branch">
      <span className="pg-branch-in">
        {BRANCH_ICON}
        <span className="pg-branch-tx">Continued from{' '}
          {href ? <Link href={href} className="pg-branch-link" title={title.trim() || undefined}>{name}</Link> : name}
        </span>
      </span>
    </div>
  );
}
