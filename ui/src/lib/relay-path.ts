// Which addresses a console relay may pass on to the gateway (/api/harness/*, /data/workspaces/*).
//
// A relay gets a path's segments as Next decodes them, once, and builds the gateway's URL from them.
// fetch() resolves '.' and '..' in that URL, also written %2e, takes a backslash for a slash, and drops
// tabs and newlines, so a segment such as '..%2finternal%2fx' (decoded '../internal/x') or '%2e%2e'
// carried a call to another of the gateway's routes. This is the rule the hosted console's proxy has
// kept since 11-05: refuse an empty segment, a dot part ('.' or '..', as a whole segment or as any
// '/'-separated part of one), a backslash, a control character, and a slash or whitespace at either
// end. A name with a slash or a space inside it still passes, as the file routes need
// (/v1/sessions/{id}/files/{path}, /v1/environments/{id}/files/{path} take one). Beyond the hosted
// rule: a dot part written %2e counts as a dot, since fetch() reads it as one after Next's decode.

const isDot = (part: string) => {
  const p = part.replace(/%2e/gi, '.');
  return p === '.' || p === '..';
};

/** Whether a decoded segment could be read by the gateway's URL as another path. */
export function oddSegment(s: string): boolean {
  return typeof s !== 'string' || s === '' || /^[\s/]|[\s/]$/.test(s) || /[\x00-\x1f\x7f\\]/.test(s)
    || s.split('/').some(isDot);
}

/** The first segment of a relayed path as the gateway routes it: the gateway decodes the path once more,
 *  so `internal%2Fx` and a double-encoded `%2569nternal` both arrive there under /internal. */
export function gatewayFirstSegment(segments: readonly string[]): string {
  const joined = segments.join('/').replace(/%([0-9a-fA-F]{2})/g, (_, h: string) => String.fromCharCode(parseInt(h, 16)));
  return joined.split('/')[0];
}
