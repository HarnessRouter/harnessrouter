import { fillStep } from './tool-steps';

type Blk = { kind: 'text'; text: string } | { kind: 'tools'; reasoning: string; steps: { name: string; args: string; result?: string; callId?: string }[] };
const tools = (steps: { name: string; args: string; result?: string; callId?: string }[]): Blk => ({ kind: 'tools', reasoning: '', steps });

describe('fillStep', () => {
  it('puts late arguments on the row the call started, not a new row', () => {
    const blocks: Blk[] = [tools([{ name: 'exec_command', args: '{}', callId: 'call_1' }]), { kind: 'text', text: 'working' }];
    const out = fillStep(blocks, { name: 'exec_command', args: '{"cmd":"echo one"}', callId: 'call_1' });
    expect(out).not.toBeNull();
    const t = out![0] as Extract<Blk, { kind: 'tools' }>;
    expect(t.steps).toHaveLength(1);
    expect(t.steps[0].args).toBe('{"cmd":"echo one"}');
    expect(blocks[0]).toEqual(tools([{ name: 'exec_command', args: '{}', callId: 'call_1' }])); // not mutated
  });

  it('leaves everything else to append, as before', () => {
    const answered: Blk[] = [tools([{ name: 'bash', args: '{}', callId: 'tool', result: 'ok' }])];
    expect(fillStep(answered, { name: 'bash', args: '{"command":"ls"}', callId: 'tool' })).toBeNull();
    const other: Blk[] = [tools([{ name: 'read', args: '{}', callId: 'x' }])];
    expect(fillStep(other, { name: 'write', args: '{"path":"a"}', callId: 'x' })).toBeNull();
    const full: Blk[] = [tools([{ name: 'bash', args: '{"command":"ls"}', callId: 'c' }])];
    expect(fillStep(full, { name: 'bash', args: '{"command":"ls"}', callId: 'c' })).toBeNull();
    expect(fillStep(other, { name: 'read', args: '{}', callId: 'x' })).toBeNull();
    expect(fillStep(other, { name: 'read', args: '{"p":1}' })).toBeNull();
  });
});
