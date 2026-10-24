// The sentence for a turn stopped at one of its runtime limits: that it reached the limit, and the
// field that raises it, never a bare "incomplete" (open source 0.35.2, #495: the step budget now
// binds on every base). `where` names the place that field lives on the surface the turn is read
// on; each caller passes its own, since the settings page differs between the console's views.

/** The setup's Settings in the redesign: the layer that holds Max steps and Timeout. */
export const SETUP_LIMITS = 'Environment & limits in Settings';
/** The harness settings page of the earlier console. */
export const HARNESS_LIMITS = 'Runtime limits in this harness’s settings';

/** "It reached its step limit. Raise Max steps under …", or null for any other reason. */
export function limitStopWhy(reason: string | null | undefined, where: string): string | null {
  if (reason === 'max_steps') return `It reached its step limit. Raise Max steps under ${where} to let it go further.`;
  if (reason === 'timeout') return `It reached its time limit. Raise Timeout under ${where} to give it longer.`;
  return null;
}
