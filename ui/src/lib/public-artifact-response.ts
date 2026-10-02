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
