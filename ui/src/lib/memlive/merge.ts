// Two people changed the same text at once: an agent wrote while someone had unsaved typing. Whatever only one of
// them touched is kept as it is. Where both changed the same paragraph, both stay, the newer write first, for a
// person to settle: a memory that holds a disagreement shows it rather than deciding it.
import { diff3Merge } from 'node-diff3';

// diff3 counts two changes next to each other as one conflict, and paragraphs are often next to each other, so a
// marker that every side has sits between them to keep them apart.
const BETWEEN = '\u0000';
const blocks = (s: string): string[] => (s ? s.split(/\n{2,}/).flatMap((b, i) => (i ? [BETWEEN, b] : [b])) : []);

export function mergeText(ours: string, base: string, theirs: string): string {
  if (ours === base) return theirs;
  if (theirs === base || theirs === ours) return ours;
  const out: string[] = [];
  for (const region of diff3Merge(blocks(ours), blocks(base), blocks(theirs), { excludeFalseConflicts: true })) {
    if (region.ok) out.push(...region.ok);
    else if (region.conflict) out.push(...region.conflict.b, ...region.conflict.a);
  }
  return out.filter((b) => b !== BETWEEN).join('\n\n');
}

/** A title is one line: a person's unsaved change stands, and the version chain keeps the other. */
export const mergeTitle = (ours: string, base: string, theirs: string): string => (ours !== base ? ours : theirs);
