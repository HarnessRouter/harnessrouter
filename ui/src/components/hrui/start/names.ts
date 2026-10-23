// New setup's sentence check (tooShort), the name a new setup is saved under (nameFromJob: the lead
// of the sentence it was given, which Settings renames), kept apart from the workspace's others
// (docs/uxuidesign/console-87: uniqName).

// Chinese, Japanese and Korean characters: written without spaces between words.
const CJK = /[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af]/;
const CJK_ALL = new RegExp(CJK.source, 'g');
// Punctuation a name never keeps; letters of every language stay as written.
const PUNCT = /[!"#$%&'()*+,/:;<=>?@[\\\]^_`{|}~“”‘’«»¿¡…·，。、！？；：（）【】《》「」『』]/g;

/** Words written with spaces between them. */
function latinWords(t: string): number {
  return t.replace(CJK_ALL, ' ').split(/\s+/).filter((w) => w.replace(PUNCT, '').length > 0).length;
}
/** Chinese, Japanese and Korean characters, each counted as half a word. */
function cjkUnits(t: string): number {
  return (t.match(CJK_ALL) || []).length / 2;
}

/** Too short to say what a setup does: fewer than three words, where a Chinese, Japanese or Korean
 *  character counts as half of one (New setup's first check before anything is sent). Counting
 *  spaces alone refused every Chinese and Japanese sentence, which has none. */
export function tooShort(j: string): boolean {
  const t = String(j || '').trim();
  return latinWords(t) + cjkUnits(t) < 3;
}

/** A name no other setup here has, whatever its capitals or spacing ("Cat Images" clashes with
 *  "Cat images"): " 2", " 3"… on a clash. */
export function uniqName(n: string, names: string[]): string {
  const key = (s: string) => String(s || '').normalize('NFC').trim().replace(/\s+/g, ' ').toLowerCase();
  const taken = new Set(names.map(key));
  let k = n, i = 2;
  while (taken.has(key(k))) k = `${n} ${i++}`;
  return k;
}

/** The name a new setup is saved under: the lead of the sentence that says what it does (up to its
 *  first colon, full stop, comma or question mark), at most five words or 40 characters (16 where the
 *  words have no spaces between them), its first letter capitalised. '' for an empty sentence. */
export function nameFromJob(j: string): string {
  const t = String(j || '').normalize('NFC').trim().replace(/\s+/g, ' ');
  const lead = (t.split(/[:.;!?,，。：；！？]/)[0] || '').trim() || t;
  let n: string;
  if (CJK.test(lead) && !/\s/.test(lead)) n = lead.slice(0, 16);
  else {
    n = lead.split(' ').slice(0, 5).join(' ');
    if (n.length > 40) n = n.slice(0, 40).replace(/\s+\S*$/, '') || n.slice(0, 40);
  }
  n = n.replace(/[\s\-–—]+$/, '');
  return n ? n.charAt(0).toUpperCase() + n.slice(1) : '';
}
