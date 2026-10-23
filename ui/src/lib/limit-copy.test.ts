import { HARNESS_LIMITS, SETUP_LIMITS, limitStopWhy } from './limit-copy';

describe('a turn stopped at a runtime limit', () => {
  it('says which limit it reached and the field that raises it', () => {
    expect(limitStopWhy('max_steps', SETUP_LIMITS)).toBe(
      'It reached its step limit. Raise Max steps under Environment & limits in Settings to let it go further.');
    expect(limitStopWhy('timeout', SETUP_LIMITS)).toBe(
      'It reached its time limit. Raise Timeout under Environment & limits in Settings to give it longer.');
    expect(limitStopWhy('max_steps', HARNESS_LIMITS)).toBe(
      'It reached its step limit. Raise Max steps under Runtime limits in this harness’s settings to let it go further.');
  });

  it('says nothing for a reason that is not a runtime limit', () => {
    for (const r of ['cost_cap', 'plan_time_limit', 'interrupted', '', undefined, null]) {
      expect(limitStopWhy(r, SETUP_LIMITS)).toBeNull();
    }
  });

  it('never uses a dash in the sentence', () => {
    for (const r of ['max_steps', 'timeout']) {
      expect(limitStopWhy(r, SETUP_LIMITS)).not.toMatch(/[–—]| - /);
    }
  });
});
