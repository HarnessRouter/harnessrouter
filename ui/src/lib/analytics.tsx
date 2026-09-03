'use client';
// Product analytics, open-source build: there is no analytics pipeline in this distribution, so
// `track` is a no-op with the hosted signature. Pages ported from the hosted console keep their
// call sites unchanged (same file, same lines), which is what keeps the two trees one product
// rather than a fork — the calls simply have nothing behind them here, like the other surfaces
// gated in lib/edition.ts. Nothing is recorded and nothing leaves the browser.
export const ANALYTICS_ENABLED = false;

export function track(_event: string, _props?: Record<string, unknown>): void {
  // Intentionally empty.
}
