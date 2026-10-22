import { readFold, stackOff, STACK_KEY, toggled, writeFold, type Fold } from './stackFold';

function memStore(init: Record<string, string> = {}) {
  const m = new Map(Object.entries(init));
  return { getItem: (k: string) => (m.has(k) ? m.get(k)! : null), setItem: (k: string, v: string) => { m.set(k, v); }, m };
}
const broken = { getItem: () => { throw new Error('blocked'); }, setItem: () => { throw new Error('blocked'); } };

describe('the Agent stack fold', () => {
  it('starts open on a first visit (nothing kept)', () => {
    expect(readFold(memStore())).toBeNull();
    expect(stackOff(null, false, false)).toBe(false);
  });

  it('follows the kept choice at desktop width', () => {
    expect(stackOff(readFold(memStore({ [STACK_KEY]: 'closed' })), false, false)).toBe(true);
    expect(stackOff(readFold(memStore({ [STACK_KEY]: 'open' })), false, false)).toBe(false);
  });

  it('ignores a value it did not write', () => {
    expect(readFold(memStore({ [STACK_KEY]: '1' }))).toBeNull();
  });

  it('a desktop toggle writes the choice, both ways', () => {
    const s = memStore();
    let kept: Fold | null = readFold(s);
    const a = toggled(kept, false, false);
    expect(a.keep).toBe('closed');
    writeFold(s, a.keep!);
    kept = readFold(s);
    expect(kept).toBe('closed');
    expect(stackOff(kept, false, false)).toBe(true);
    const b = toggled(kept, false, false);
    expect(b.keep).toBe('open');
  });

  it('under the overlay width starts folded whatever was kept', () => {
    expect(stackOff('open', true, false)).toBe(true);
    expect(stackOff(null, true, false)).toBe(true);
    expect(stackOff('closed', true, false)).toBe(true);
  });

  it('under the overlay width the toggle opens it for the visit and writes nothing', () => {
    const t = toggled('closed', true, false);
    expect(t.keep).toBeNull();
    expect(t.openedNarrow).toBe(true);
    expect(stackOff('closed', true, t.openedNarrow)).toBe(false);
    // back at desktop width the kept choice is as it was
    expect(stackOff('closed', false, t.openedNarrow)).toBe(true);
    expect(toggled('open', true, true)).toEqual({ keep: null, openedNarrow: false });
  });

  it('a browser that keeps nothing reads as a first visit and never throws', () => {
    expect(readFold(broken)).toBeNull();
    expect(() => writeFold(broken, 'closed')).not.toThrow();
    expect(readFold(undefined)).toBeNull();
  });
});
