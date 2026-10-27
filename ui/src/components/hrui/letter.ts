// The team's letter. One letter at a time; the rail's Letter button and the account menu's "How it
// works" carry a dot until this person has opened it in this browser. A new letter gets a new id, so
// the dot comes back for it.
export const LETTER_ID = '2026-10-how-it-works';
/** the letter's page, the hosted console's letter word for word */
export const LETTER_FILE = `/letters/${LETTER_ID}.html`;
const READ_KEY = 'hr.letter.read';

/** Unread until opened. Without storage there is no dot (nothing could ever clear it). */
export function letterUnread(): boolean {
  try { return localStorage.getItem(READ_KEY) !== LETTER_ID; } catch { return false; }
}

export function markLetterRead(): void {
  try { localStorage.setItem(READ_KEY, LETTER_ID); } catch { /* no storage: no dot either */ }
}
