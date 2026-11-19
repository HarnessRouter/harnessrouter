import type { AppRun } from './app-api';

type MonitorPort = {
  read: (id: number) => Promise<AppRun>;
  watch: (id: number, change: (run: AppRun) => void, fail: () => void) => () => void;
  onChange: (run: AppRun) => void;
  onConnection: (state: 'live' | 'recovering' | 'unavailable') => void;
  schedule: (callback: () => Promise<void>, delay: number) => unknown;
  cancel: (timer: unknown) => void;
};

// One observer owns one Run. Waiting/paused Runs must be read as the existing
// SSE endpoint deliberately closes at an interaction boundary.
export function watchCoordinatorRun(initial: AppRun, port: MonitorPort): () => void {
  let stopped = false, timer: unknown, close: (() => void) | undefined;
  let recovering = false, streamGeneration = 0, failures = 0;
  const terminal = (run: AppRun) => ['completed', 'failed', 'canceled'].includes(run.status);
  const canStream = (run: AppRun) => ['pending', 'running'].includes(run.status) && !run.paused;
  const stopStream = () => { streamGeneration++; close?.(); close = undefined; };
  const finish = () => { stopped = true; stopStream(); if (timer !== undefined) port.cancel(timer); timer = undefined; };
  const accept = (run: AppRun) => !stopped && run.id === initial.id && run.task_id === initial.task_id;
  const schedule = () => {
    if (stopped || timer !== undefined) return;
    timer = port.schedule(async () => {
      timer = undefined;
      try {
        const snapshot = await port.read(initial.id);
        if (!accept(snapshot)) return;
        failures = 0;
        port.onChange(snapshot);
        if (terminal(snapshot)) { port.onConnection('live'); finish(); }
        else if (canStream(snapshot)) connect();
        else { port.onConnection('live'); schedule(); }
      } catch (cause) {
        if (stopped) return;
        const status = (cause as { status?: number })?.status;
        if (status === 401 || status === 403 || status === 404) { port.onConnection('unavailable'); finish(); return; }
        failures++;
        port.onConnection('recovering'); schedule();
      }
    }, Math.min(15000, 2000 * 2 ** Math.min(failures, 3)));
  };
  const connect = () => {
    if (stopped) return;
    stopStream(); recovering = false;
    const serial = streamGeneration;
    close = port.watch(initial.id, snapshot => {
      if (serial !== streamGeneration || !accept(snapshot)) return;
      port.onChange(snapshot); port.onConnection('live');
      if (terminal(snapshot)) finish();
      else if (!canStream(snapshot)) { stopStream(); schedule(); }
    }, () => {
      if (stopped || serial !== streamGeneration || recovering) return;
      recovering = true; stopStream(); port.onConnection('recovering'); schedule();
    });
  };
  if (terminal(initial)) return finish;
  if (canStream(initial)) connect(); else schedule();
  return finish;
}
