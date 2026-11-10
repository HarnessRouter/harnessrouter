// Which addresses a console relay may pass on to the gateway (/api/harness/*, /data/workspaces/*).
//
// A relay gets a path's segments as Next decodes them, once, and builds the gateway's URL from them.
// fetch() resolves '.' and '..' in that URL, also written %2e, takes a backslash for a slash, and drops
// tabs and newlines, so a segment such as '..%2finternal%2fx' (decoded '../internal/x') or '%2e%2e'
// carried a call to another of the gateway's routes. This is the rule the hosted console's proxy has
// kept since 11-05: refuse an empty segment, a dot part ('.' or '..', as a whole segment or as any
// '/'-separated part of one), a backslash, a control character, and a slash or whitespace at either
// end. A name with a slash or a space inside it still passes, as the file routes need
// (/v1/sessions/{id}/files/{path}, /v1/environments/{id}/files/{path} take one).
//
// Every check reads a segment FULLY decoded (CAT, via the pentest session): decoded to a fixed point, at
// most five rounds, so a dot, slash, backslash or control character encoded any number of times up to that
// is seen for what it is (%25252e is '.'). A segment still changing after five rounds, or whose escapes do
// not decode as UTF-8 (%E0%A4, or an overlong '.' such as %C0%AE), is refused. A '%' that does not begin
// an escape is a character of the name ("50% off.pdf"), as it is to the gateway. Nothing here changes
// what is forwarded: a relay sends the segments as it always has.

const ROUNDS = 5;

/** A value decoded to a fixed point, or null when it cannot be: still changing after five rounds, or an
 *  escape run that is not UTF-8. */
export function fullyDecoded(value: string): string | null {
  let cur = value;
  for (let round = 0; round <= ROUNDS; round++) {
    let next: string;
    try {
      next = cur.replace(/(?:%[0-9A-Fa-f]{2})+/g, (run) => decodeURIComponent(run));
    } catch {
      return null;
    }
    if (next === cur) return cur;
    cur = next;
  }
  return null;
}

/** Whether a segment could be read by the gateway's URL as another path, judged fully decoded. */
export function oddSegment(s: string): boolean {
  if (typeof s !== 'string') return true;
  const d = fullyDecoded(s);
  return d === null || d === '' || /^[\s/]|[\s/]$/.test(d) || /[\x00-\x1f\x7f\\]/.test(d)
    || d.split('/').some((p) => p === '.' || p === '..');
}

/** The first segment of a relayed path as the gateway routes it, judged fully decoded: `internal%2Fx`,
 *  a double-encoded `%2569nternal` and deeper ones all arrive under /internal. Call after oddSegment. */
export function gatewayFirstSegment(segments: readonly string[]): string {
  return segments.map((x) => fullyDecoded(x) ?? x).join('/').split('/')[0];
}
