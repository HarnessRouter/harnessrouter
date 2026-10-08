/** The console's duration rule: sixty of a unit that has a next one is one of that next unit.
 *
 *  Each place that renders an elapsed time rounds it, and rounding the seconds half on its own let
 *  119.7 s read as `1m 60s` and 59.7 s as `60s`. The strings the console prints are not one string —
 *  one pads the seconds, one does not, one starts in milliseconds — so only the split is owned here,
 *  and each caller keeps its own rendering. */
export function minutesAndSeconds(seconds: number): [number, number] {
  const total = Math.round(seconds);
  return [Math.floor(total / 60), total % 60];
}

/** The harness list's latency: "4.2s" under ten seconds, "42s" under a minute, "1m 12s" past it.
 *  A band is chosen on the ROUNDED value, so 9.96 s is "10s", not "10.0s", and 59.7 s is "1m 0s". */
export function latencyText(s: number): string {
  const tenths = Math.round(s * 10) / 10;
  if (tenths < 10) return `${tenths.toFixed(1)}s`;
  const [m, sec] = minutesAndSeconds(s);
  return m ? `${m}m ${sec}s` : `${sec}s`;
}

/** A trace span's duration: "420ms" under a second, "4.2s" under a minute, "1m 12s" past it. The
 *  same carry at each edge: 0.9996 s is "1.0s", not "1000ms", and 59.96 s is "1m 0s", not "60.0s". */
export function traceDurationText(s: number): string {
  const ms = Math.round(s * 1000);
  if (ms < 1000) return `${ms}ms`;
  const tenths = Math.round(s * 10) / 10;
  if (tenths < 60) return `${tenths.toFixed(1)}s`;
  const [m, sec] = minutesAndSeconds(s);
  return `${m}m ${sec}s`;
}
