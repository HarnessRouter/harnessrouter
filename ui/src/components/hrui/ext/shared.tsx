'use client';
// Bits every Add-ons tab uses: the "Used by" line, a setup's address and a list that could not be
// read. (A new skill's or MCP server's setups are chosen in the step after its sheet: AddToSheet.)

export const PLUS = <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>;

/** A setup's own page, on its settings (where its capabilities are). */
export const setupHref = (id: string) => `/studio/${encodeURIComponent(id)}?tab=settings`;

/** The design's libUsed: who uses it, three names at most. */
export function usedText(names: string[]): string {
  return names.length ? `Used by ${names.slice(0, 3).join(', ')}${names.length > 3 ? ` and ${names.length - 3} more` : ''}` : 'Not used by any setup';
}
export const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`;

/** A list that could not be read (lib/settle.ts readSettled gave up after its quiet second try): one
 *  plain line where the list goes, and Try again, never a skeleton that waits forever. */
export function ReadFailed({ what, retry }: { what: string; retry: () => void }) {
  return (
    <div className="empty-list ld-fail" role="alert">
      Your {what} could not be loaded just now.{' '}
      <button type="button" className="link-q inl" onClick={retry}>Try again</button>
    </div>
  );
}
