import { brickLayer, cfgOf, LAYER_KEYS, layerOf, SET_KEYS, SET_LAYERS, showRef, storeRef } from './settingsModel';
import type { CustomHarness } from '@/lib/harness';

describe('the Settings layers', () => {
  it('lists them in Richard’s order: Instructions, Agent harness, Capabilities, Environment & limits', () => {
    expect(SET_LAYERS.map(([k]) => k)).toEqual(['instructions', 'harness', 'caps', 'runtime']);
    expect(SET_LAYERS.map(([, label]) => label)).toEqual(['Instructions', 'Agent harness', 'Capabilities', 'Environment & limits']);
  });

  it('keeps the model in the Agent harness layer, so its dot and Save cover both', () => {
    expect(LAYER_KEYS.harness).toEqual(['name', 'model', 'thinking']);
    // every field belongs to exactly one layer
    const all = Object.values(LAYER_KEYS).flat();
    expect([...all].sort()).toEqual([...SET_KEYS].sort());
  });

  it('opens the layer an address names, an older Model link in Agent harness, else the first', () => {
    expect(layerOf('caps')).toBe('caps');
    expect(layerOf('harness')).toBe('harness');
    expect(layerOf('model')).toBe('harness');
    expect(layerOf(null)).toBe('instructions');
    expect(layerOf('')).toBe('instructions');
    expect(layerOf('nope')).toBe('instructions');
  });

  it('opens Agent harness from both the agent harness and the model brick of the Agent stack', () => {
    expect(brickLayer('b-runtime')).toBe('harness');
    expect(brickLayer('model')).toBe('harness');
    expect(brickLayer('task')).toBe('instructions');
    expect(brickLayer('skill')).toBe('caps');
    expect(brickLayer('env')).toBe('runtime');
    expect(brickLayer('b-sandbox')).toBe('runtime');
    expect(brickLayer('product')).toBeNull();
  });
});


describe('a stored secret’s reference', () => {
  // the service reads only a whole reference of its own namespace; a person's own value of that shape is a literal
  it('maps a whole reference both ways, as the service does', () => {
    expect(storeRef('secret:harness-mcp-deploy')).toBe('vault:harness-mcp-deploy');
    expect(showRef('vault:harness-mcp-deploy')).toBe('secret:harness-mcp-deploy');
    expect(storeRef(' secret:harness-mcp-deploy ')).toBe('vault:harness-mcp-deploy');
    expect(showRef('secret:harness-mcp-deploy')).toBe('secret:harness-mcp-deploy');      // the service's own answer, shown as is
  });

  it('saves a literal that starts "secret:" or "vault:" exactly as typed', () => {
    for (const v of ['secret:rotate', 'secret:abc-123', 'secret:', 'secret:harness-conn-x', 'secret:harness-mcp-a b', 'us-east-1', '$headers.X-Key']) {
      expect(storeRef(v)).toBe(v);
    }
    for (const v of ['vault:rotate', 'vault:harness-conn-x', 'region']) expect(showRef(v)).toBe(v);
  });

  it('shows a setup’s variables in the words a person types', () => {
    const h = { name: 'h', env: { DEPLOY: 'vault:harness-mcp-deploy', MODE: 'secret:rotate', OLD: 'vault:rotate' } } as unknown as CustomHarness;
    expect(cfgOf(h).vars).toEqual([
      { name: 'DEPLOY', value: 'secret:harness-mcp-deploy' }, { name: 'MODE', value: 'secret:rotate' }, { name: 'OLD', value: 'vault:rotate' },
    ]);
  });
});
