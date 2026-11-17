'use client';

import { useEffect, useRef, useState } from 'react';
import type { CustomHarness } from '@/lib/harness';
import { withDeadline } from '@/lib/settle';

export function uhpHealth(agent: CustomHarness, now = Date.now() / 1000) {
  if (!agent.external && agent.base !== 'external_uhp') return null;
  const health = agent.health;
  const status = health?.status || 'unknown';
  const expired = !!health && (health.stale || (!!health.fresh_until && health.fresh_until <= now));
  const ready = !expired && (health?.fresh_until || 0) > now && agent.available === true && health?.harness_status === 'healthy'
    && (status === 'healthy' || status === 'harness_missing');
  const labels: Record<string, string> = {
    unknown: '未检查', unreachable: '无法连接', unauthorized: '鉴权失败',
    invalid: '响应无效', harness_missing: 'Harness 缺失', healthy: '不可用',
  };
  const label = expired ? '状态已过期' : ready ? '连接正常'
    : health?.harness_status === 'harness_missing' ? 'Harness 缺失' : labels[status] || '未检查';
  return { ready, label, tone: ready ? 'ok' : expired || status === 'unknown' ? 'neutral' : 'bad',
    reason: expired ? '健康观察已过期，请等待刷新或前往 UHP 连接立即检查。'
      : health?.last_error || (ready ? 'Gateway 最近探测成功；发送任务前仍会强制检查。' : '目标当前不可用，请前往 UHP 连接检查。') };
}

export function useUhpHealthRefresh(enabled: boolean, scope: string, refresh: (signal: AbortSignal) => Promise<void>) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  const callback = useRef(refresh);
  callback.current = refresh;
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    let busy = false;
    const read = async () => {
      if (busy || document.visibilityState === 'hidden') return;
      busy = true;
      const request = new AbortController();
      const abort = () => request.abort();
      controller.signal.addEventListener('abort', abort, { once: true });
      try {
        await withDeadline(signal => {
          signal.addEventListener('abort', abort, { once: true });
          return callback.current(request.signal);
        }, 20_000);
      } catch { }
      finally {
        controller.signal.removeEventListener('abort', abort);
        busy = false;
        if (!controller.signal.aborted) setNow(Date.now() / 1000);
      }
    };
    const tick = setInterval(() => {
      if (document.visibilityState !== 'hidden') setNow(Date.now() / 1000);
    }, 1000);
    const poll = setInterval(() => void read(), 30_000);
    const visible = () => { if (document.visibilityState !== 'hidden') { setNow(Date.now() / 1000); void read(); } };
    window.addEventListener('focus', visible);
    document.addEventListener('visibilitychange', visible);
    return () => {
      controller.abort(); clearInterval(tick); clearInterval(poll);
      window.removeEventListener('focus', visible);
      document.removeEventListener('visibilitychange', visible);
    };
  }, [enabled, scope]);
  return now;
}
