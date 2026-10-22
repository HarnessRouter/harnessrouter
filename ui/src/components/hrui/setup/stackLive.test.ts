import { newTurn, reduceTurn } from 'reifyui/agent-chat';
import type { AsstMsg } from '@/lib/conversation';
import { towerOf, type SetupFacts } from '../tower';
import { liveTower, runningNames, toolLayers, workingNow } from './stackLive';

const run = (blocks: AsstMsg['blocks'], extra: Partial<AsstMsg> = {}): AsstMsg => ({ role: 'assistant', blocks, files: [], status: 'running', ...extra });
const facts = (over: Partial<SetupFacts> = {}): SetupFacts => ({
  harness: 'Hermes', model: 'gpt-5.4', instructions: true, tested: true,
  parts: { skill: 1, plugin: 1, mcp: 1, env: 1 }, running: false, ...over,
});

describe('toolLayers', () => {
  it('names the brick each kind of call works through', () => {
    expect(toolLayers('Bash', { command: 'ls' })).toEqual(['b-sandbox', 'env']);
    expect(toolLayers('list_files', { path: '.' })).toEqual(['b-files', 'env']);
    expect(toolLayers('write_file', { path: 'a.md' })).toEqual(['b-files', 'env']);
    expect(toolLayers('Skill', { skill: 'pdf' })).toEqual(['skill']);
    expect(toolLayers('mcp__plugs__github_list_repos', {})).toEqual(['plugin']);
    expect(toolLayers('mcp_plugs_browser_navigate', {})).toEqual(['plugin']);
    expect(toolLayers('plugs.slack_send', {})).toEqual(['plugin']);
    expect(toolLayers('mcp__weather__forecast', {})).toEqual(['mcp']);
    expect(toolLayers('mcp__media__generate_image', {})).toEqual(['mcp']);
    expect(toolLayers('TodoWrite', { todos: [] })).toEqual([]);
  });
});

describe('workingNow', () => {
  it('is nothing once the turn is over', () => {
    expect(workingNow(null)).toBeNull();
    expect(workingNow(run([], { status: 'done' }))).toBeNull();
  });
  it('starts on the session, the orchestration, the harness, the instructions and the model', () => {
    expect(workingNow(run([]))).toEqual(['b-orch', 'b-runtime', 'b-sessions', 'b-trace', 'backend', 'model', 'task']);
  });
  it('lights the model while it thinks, and Streaming while it writes', () => {
    expect(workingNow(run([{ kind: 'tools', reasoning: 'Looking', steps: [] }]))).toContain('model');
    const w = workingNow(run([{ kind: 'tools', reasoning: '', steps: [{ name: 'ls', args: '{}', result: 'a', callId: 'c1' }] }, { kind: 'text', text: 'Here' }]));
    expect(w).toEqual(expect.arrayContaining(['model', 'b-stream']));
    expect(w).not.toContain('task');
  });
  it('lights the brick of the call in flight, not the model', () => {
    const w = workingNow(run([{ kind: 'tools', reasoning: '', steps: [{ name: 'list_files', args: '{"path":"."}', callId: 'c1' }] }]));
    expect(w).toEqual(expect.arrayContaining(['b-files', 'env']));
    expect(w).not.toContain('model');
    expect(w).not.toContain('task');
  });
  it('lights Errors on a failed call, an error, and a Stop', () => {
    expect(workingNow(run([{ kind: 'tools', reasoning: '', steps: [{ name: 'Bash', args: '{}', result: 'no', callId: 'c1', isError: true }] }]))).toContain('b-errors');
    expect(workingNow(run([{ kind: 'text', text: 'Error: boom', error: true }]))).toContain('b-errors');
    expect(workingNow(run([]), true)).toContain('b-errors');
  });
  it('reads the live clock the thread reads', () => {
    let clock = newTurn({ startedAt: 1 });
    clock = reduceTurn(clock, { type: 'response.created', response: { id: 'r1' } }, 2);
    clock = reduceTurn(clock, { type: 'response.output_item.added', output_index: 0, item: { type: 'function_call', id: 'fc1', call_id: 'c1', name: 'Bash', arguments: '' } }, 3);
    const w = workingNow(run([{ kind: 'tools', reasoning: '', steps: [{ name: 'Bash', args: '{"command":"ls"}', callId: 'c1' }] }], { clock }));
    expect(w).toEqual(expect.arrayContaining(['b-sandbox']));
  });
});

describe('liveTower', () => {
  it('runs only the bricks the turn works through, and only where the setup has them', () => {
    const t = liveTower(towerOf(facts({ parts: { skill: 0, plugin: 1, mcp: 0, env: 0 } })), ['b-runtime', 'backend', 'b-sessions', 'b-orch', 'b-trace', 'plugin', 'skill']);
    expect(t.st.plugin).toBe('run');
    expect(t.st.skill).toBe('empty');
    expect(t.st.model).toBe('built');
    expect(t.st['b-sandbox']).toBe('built');
    expect(runningNames(t, true)).toEqual(['Agent harness', 'HarnessRouter', 'Plugin']);
  });
  it('replaces the coarse running set a task list gave', () => {
    const coarse = towerOf(facts({ running: true }));
    expect(coarse.st['b-sandbox']).toBe('run');
    const t = liveTower(coarse, ['b-runtime', 'backend', 'b-sessions', 'b-orch', 'model', 'b-stream']);
    expect(t.st['b-sandbox']).toBe('built');
    expect(runningNames(t, true)).toEqual(['Agent harness', 'Model', 'HarnessRouter', 'Streaming']);
  });
  it('lights Trace while the turn is recorded (every task keeps its trace)', () => {
    const t = liveTower(towerOf(facts()), ['b-runtime', 'backend', 'b-trace']);
    expect(t.st['b-trace']).toBe('run');
  });
  it('counts a first test as the instructions it follows', () => {
    const t = liveTower(towerOf(facts({ instructions: false, tested: false })), ['b-runtime', 'backend', 'model', 'task']);
    expect(runningNames(t)).toEqual(['Agent harness', 'Model', 'Instructions', 'HarnessRouter']);
  });
});
