// The gateway and console both enforce the boundary so a rolling deployment cannot leave
// an older gateway's active content running with the console's origin. No allow-same-origin.
export const PUBLIC_ARTIFACT_CSP =
  "sandbox allow-scripts; base-uri 'none'; object-src 'none'; form-action 'none'; frame-ancestors 'none'";

export function publicShareResponseHeaders(upstream: Headers, artifact: boolean): Headers {
  const out = new Headers({
    'content-type': upstream.get('content-type') || 'application/octet-stream',
    'cache-control': 'private, no-store',
    'x-content-type-options': 'nosniff',
    'referrer-policy': 'no-referrer',
  });
  for (const name of ['content-disposition', 'content-security-policy']) {
    const value = upstream.get(name);
    if (value) out.set(name, value);
  }
  if (artifact) {
    // Separate policies intersect; an upstream policy must never weaken this sandbox.
    const upstreamPolicy = out.get('content-security-policy');
    out.set('content-security-policy', upstreamPolicy
      ? `${upstreamPolicy}, ${PUBLIC_ARTIFACT_CSP}` : PUBLIC_ARTIFACT_CSP);
  }
  // Do not forward Set-Cookie, CORS grants, or Content-Length (fetch may decompress bytes).
  return out;
}

/** The policy for what a same-origin relay passes on from the gateway (/api/harness/*,
 *  /data/workspaces/*): a file an agent wrote, a media clip, an API body. None of it is the console's
 *  own page, and /api/harness takes the session cookie, so a link to an HTML or SVG file there ran
 *  with the console's origin and the visitor's session. Every response is sandboxed, PDF alone
 *  excepted: a sandboxed document cannot open the browser's PDF viewer, and a PDF cannot run script on
 *  this origin. Both stay unframable, and an upstream policy is kept beside ours (separate policies intersect). */
export function relayContentSecurityPolicy(upstream: string | null, contentType: string): string {
  const local = /^application\/pdf\b/i.test(contentType.trim()) ? "frame-ancestors 'none'" : PUBLIC_ARTIFACT_CSP;
  return upstream ? `${upstream}, ${local}` : local;
}

/** Whether every segment of an address a relay builds names exactly one thing: none empty, '.' or '..',
 *  none holding a '/' or a '\'. The segments are a route's params, which Next has already decoded once
 *  (`%2e%2e` arrives as '..', `a%2fb` as 'a/b'); they are checked as they are and never decoded again.
 *  fetch() resolves '.' and '..' in the URL it is handed, and encodeURIComponent leaves both as they
 *  are, so one of them in a segment would carry the relay to another of the gateway's routes. */
export function plainSegments(segments: readonly string[]): boolean {
  return segments.every((s) => typeof s === 'string' && s !== '' && s !== '.' && s !== '..'
    && !s.includes('/') && !s.includes('\\'));
}

/** The gateway's own 404 for a file (or a share) that is not there, for a relay that refuses an
 *  address before asking: the same status, body and headers, so a refusal reads as a missing file. */
export function notFoundResponse(message: 'file not found' | 'share not found', artifact: boolean): Response {
  const body = { error: { type: 'invalid_request_error', code: 'not_found', message, param: null, detail: null }, detail: message };
  return new Response(JSON.stringify(body), {
    status: 404, headers: publicShareResponseHeaders(new Headers({ 'content-type': 'application/json' }), artifact),
  });
}
