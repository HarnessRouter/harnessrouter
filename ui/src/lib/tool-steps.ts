// A call sent again with its arguments after it started without any fills its own row: opensquilla
// announces a call with none and its arguments arrive when the turn ends. Only a row with the same
// call id and name, no arguments yet and no result is filled; anything else adds a row, as before
// (null tells the caller to append).
interface Step { name: string; args: string; result?: string; callId?: string }
type Blk = { kind: 'text'; text: string; error?: true } | { kind: 'tools'; reasoning: string; steps: Step[] };

export function fillStep<B extends Blk>(blocks: B[], step: Step): B[] | null {
  if (!step.callId || !step.args || step.args === '{}') return null;
  for (let i = blocks.length - 1; i >= 0; i--) {
    const b = blocks[i];
    if (b.kind !== 'tools') continue;
    const j = b.steps.findIndex((s) => s.callId === step.callId && s.name === step.name
      && (!s.args || s.args === '{}') && s.result === undefined);
    if (j < 0) continue;
    const steps = b.steps.slice();
    steps[j] = { ...steps[j], args: step.args };
    const out = blocks.slice();
    out[i] = { ...b, steps };
    return out;
  }
  return null;
}
