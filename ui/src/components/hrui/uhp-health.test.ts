import type { CustomHarness } from '@/lib/harness';
import { uhpHealth } from './uhp-health';

const remote = (health: CustomHarness['health'], available = true) => ({
  id: 'external', base: 'external_uhp', external: true, available, health,
} as CustomHarness);

test('native agents keep task-based health', () => {
  expect(uhpHealth({ base: 'hermes' } as CustomHarness)).toBeNull();
});

test('healthy target remains available when another harness is missing', () => {
  expect(uhpHealth(remote({ status: 'harness_missing', harness_status: 'healthy', fresh_until: 190 }), 100))
    .toMatchObject({ ready: true, label: '连接正常' });
  expect(uhpHealth(remote({ status: 'harness_missing', harness_status: 'harness_missing', fresh_until: 190 }), 100))
    .toMatchObject({ ready: false, label: 'Harness 缺失' });
});

test.each([undefined, 0, 100])('missing or expired freshness %s never authorizes a task', fresh_until => {
  expect(uhpHealth(remote({ status: 'healthy', harness_status: 'healthy', fresh_until }), 100)?.ready).toBe(false);
});

test('missing health and stale healthy observations fail closed', () => {
  expect(uhpHealth(remote(undefined), 100)).toMatchObject({ ready: false, label: '未检查' });
  expect(uhpHealth(remote({ status: 'healthy', harness_status: 'healthy', fresh_until: 190, stale: true }), 100))
    .toMatchObject({ ready: false, label: '状态已过期' });
});
