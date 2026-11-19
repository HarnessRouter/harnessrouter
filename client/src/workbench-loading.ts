import { appListRuns, appListTasksPage, appListTemplates, AppApiError } from './app-api.ts';

type Lists = { tasks: Awaited<ReturnType<typeof appListTasksPage>>; templates: Awaited<ReturnType<typeof appListTemplates>>; runs: Awaited<ReturnType<typeof appListRuns>> };

export async function loadWorkbenchLists(requests: { [K in keyof Lists]: Promise<Lists[K]> }) {
  const entries = Object.entries(requests);
  const settled = await Promise.allSettled(entries.map(([, request]) => request));
  const failures: Array<{ section: string; message: string }> = [];
  const result: Partial<Lists> = {};
  settled.forEach((item, index) => {
    const section = entries[index][0] as keyof Lists;
    if (item.status === 'fulfilled') Object.assign(result, { [section]: item.value });
    else {
      if (item.reason instanceof AppApiError && item.reason.status === 401) throw item.reason;
      const detail = item.reason instanceof AppApiError && item.reason.status !== 404 ? item.reason.message : '';
      failures.push({ section, message: `${section === 'tasks' ? '任务' : section === 'templates' ? '模板' : '运行记录'}列表接口不可用，请重试。${detail ? ` ${detail}` : ''}` });
    }
  });
  return { ...result, failures };
}
