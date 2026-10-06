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
