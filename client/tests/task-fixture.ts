import type { Page } from '@playwright/test';

export const nodes = [
  { id: 'a', name: '资料收集', agent_id: 'agent-1', model: 'model-1', prompt: '收集资料', deps: [], x: 0, y: 0 },
  { id: 'b', name: '风险分析', agent_id: 'agent-1', model: 'model-1', prompt: '分析风险', deps: [], x: 0, y: 140 },
  { id: 'report', name: '汇总报告', agent_id: 'agent-1', model: 'model-1', deps: ['a', 'b'], inputRefs: ['a'], requires_human: true, final_report: true, x: 240, y: 60 },
];

export async function taskFixture(page: Page, options: { failSave?: boolean; failList?: boolean; empty?: boolean; paginatedTemplateVersions?: boolean } = {}) {
  const tasks: any[] = options.empty ? [] : [
    { id: 71, title: '安全事件调查', description: 'API 返回的调查任务', workspace_id: null, status: 'waiting', current_revision: 4, workflow: { nodes }, current_result: {}, latest_run_id: 18 },
    { id: 72, title: '产品方案评估', description: '已完成评估', workspace_id: null, status: 'completed', current_revision: 2, workflow: { nodes: [{ ...nodes[0], name: '当前产品分析' }] }, current_result: {}, latest_run_id: 19 },
    { id: 73, title: '待配置的草稿', description: '尚未运行', workspace_id: null, status: 'draft', current_revision: 1, workflow: { nodes: [nodes[0]] }, current_result: {}, latest_run_id: null },
    { id: 74, title: '执行失败的任务', description: '节点失败', workspace_id: null, status: 'failed', current_revision: 1, workflow: { nodes: [nodes[0]] }, current_result: {}, latest_run_id: 20 },
  ];
  const attempt = (id: number, node: string, status: string, time: number) => ({ id, node_id: node, run_id: id < 100 ? 18 : id < 200 ? 19 : 20, attempt: 1, status, input: { task_input: '真实夹具输入' }, output: status === 'succeeded' ? { text: '来自 API 的节点输出' } : null, error_code: status === 'failed' ? 'agent_failed' : null, started_at: status === 'idle' ? null : `2026-11-18T01:00:0${time}`, finished_at: status === 'succeeded' ? `2026-11-18T01:00:1${time}` : null });
  const runs: any[] = options.empty ? [] : [
    { id: 18, task_id: 71, workflow_revision: 3, status: 'waiting_human', kind: 'normal', paused: false, workflow: { nodes }, decisions: [], nodes: [attempt(1, 'a', 'succeeded', 0), attempt(2, 'b', 'succeeded', 1), attempt(3, 'report', 'idle', 2)] },
    { id: 19, task_id: 72, workflow_revision: 1, status: 'completed', kind: 'normal', workflow: { nodes: [{ ...nodes[0], name: '历史产品分析' }] }, decisions: [], nodes: [attempt(101, 'a', 'succeeded', 0)] },
    { id: 20, task_id: 74, workflow_revision: 1, status: 'failed', kind: 'normal', workflow: { nodes: [nodes[0]] }, decisions: [], nodes: [attempt(201, 'a', 'failed', 0)] },
  ];
  const templates: any[] = options.empty ? [] : [{ id: 41, title: '安全调查模板', workspace_id: null, versions: options.paginatedTemplateVersions ? [
    { id: 301, version: 1, workflow: { nodes } },
    { id: 302, version: 2, workflow: { nodes: [{ ...nodes[0], name: '第二版收集' }] } },
    { id: 303, version: 3, workflow: { nodes: [{ ...nodes[0], name: '第三版收集' }] } },
  ] : [{ id: 301, version: 1, workflow: { nodes } }] }];
  const writes: Array<{ path: string; body: any; key?: string }> = [];
  let failSave = options.failSave, failList = options.failList;
  const paged = (rows: any[], url: URL) => {
    const offset = Number(url.searchParams.get('offset') || 0), limit = Number(url.searchParams.get('limit') || 100);
    const q = (url.searchParams.get('q') || '').toLowerCase(), status = url.searchParams.get('status');
    const filtered = rows.filter(row => (!status || row.status === status) && `${row.title || tasks.find(t => t.id === row.task_id)?.title || ''} ${row.id}`.toLowerCase().includes(q));
    return { rows: filtered.slice(offset, offset + limit), pagination: { offset, limit, has_more: offset + limit < filtered.length } };
  };
  await page.route('**/api/hexa/**', async route => {
    const req = route.request(), url = new URL(req.url()), path = url.pathname;
    const body = req.postData() ? req.postDataJSON() : {};
    if (req.method() !== 'GET') writes.push({ path, body, key: req.headers()['idempotency-key'] });
    if (path.endsWith('/auth/session')) return route.fulfill({ json: { authenticated: true, username: 'admin' } });
    if (path.endsWith('/agents')) return route.fulfill({ json: { agents: [{ id: 'agent-1', name: '调查分析师' }] } });
    if (path.endsWith('/models')) return route.fulfill({ json: { default: 'model-1', models: [{ id: 'model-1', label: '模型一', available: true }] } });
    if (path.endsWith('/workspaces')) return route.fulfill({ json: { workspaces: [], selected_id: null } });
    if (path.endsWith('/conversations')) return route.fulfill({ json: { conversations: [] } });
    if (path.endsWith('/tasks')) {
      if (failList) return route.fulfill({ status: 503, json: { detail: '任务服务暂时不可用。' } });
      const page = paged(tasks, url);
      return route.fulfill({ json: { tasks: page.rows, pagination: page.pagination } });
    }
    const taskMatch = path.match(/\/tasks\/(\d+)(?:\/(.*))?$/);
    if (taskMatch) {
      const task = tasks.find(t => t.id === Number(taskMatch[1])), tail = taskMatch[2];
      if (!task) return route.fulfill({ status: 404, json: { detail: '任务不存在。' } });
      if (!tail) return route.fulfill({ json: task });
      if (tail === 'runs') return route.fulfill({ json: { runs: runs.filter(r => r.task_id === task.id) } });
      if (tail === 'artifacts') return route.fulfill({ json: { artifacts: [], pagination: { limit: 50, offset: 0, total: 0, has_more: false } } });
      if (tail === 'workflow') {
        if (failSave) return route.fulfill({ status: 409, json: { detail: { code: 'revision_conflict', message: '工作流版本已变化，请刷新后重试。' } } });
        task.workflow = body.workflow; task.current_revision++;
        return route.fulfill({ json: task });
      }
    }
    if (path.endsWith('/templates')) {
      const list = options.paginatedTemplateVersions ? templates.map(template => ({ ...template, versions: template.versions.slice(0, 1), versions_pagination: { offset: 0, limit: 1, has_more: true } })) : templates;
      const page = paged(list.map(t => ({ ...t, latest_version: templates.find(item => item.id === t.id)?.versions.at(-1) })), url);
      return route.fulfill({ json: { templates: page.rows, pagination: page.pagination } });
    }
    if (path.endsWith('/runs')) { const page = paged(runs, url); return route.fulfill({ json: { runs: page.rows, pagination: page.pagination } }); }
    const templateMatch = path.match(/\/templates\/(\d+)(?:\/versions)?$/);
    if (templateMatch) {
      const template = templates.find(t => t.id === Number(templateMatch[1]));
      if (req.method() === 'POST') template.versions.push({ id: 302, version: 2, workflow: body.workflow });
      const offset = Number(url.searchParams.get('versions_offset') || 0), limit = Number(url.searchParams.get('versions_limit') || 100);
      return route.fulfill({ json: { ...template, latest_version: template.versions.at(-1), ...(options.paginatedTemplateVersions ? { versions: template.versions.slice(offset, offset + limit), versions_pagination: { offset, limit, has_more: offset + limit < template.versions.length } } : {}) } });
    }
    const runMatch = path.match(/\/runs\/(\d+)(?:\/(.*))?$/);
    if (runMatch) {
      const run = runs.find(r => r.id === Number(runMatch[1]));
      if (runMatch[2] === 'continue') { run.status = 'running'; run.decisions.push({ node_id: body.node_id, input_refs: body.input_refs }); return route.fulfill({ json: { id: run.id, status: 'running' } }); }
      if (runMatch[2] === 'events') return route.fulfill({ contentType: 'text/event-stream', body: `data: ${JSON.stringify(run)}\n\n` });
      if (runMatch[2] === 'artifacts') return route.fulfill({ json: { artifacts: [], pagination: { limit: 50, offset: 0, total: 0, has_more: false } } });
      return route.fulfill({ json: run });
    }
    if (/\/node-runs\/\d+\/artifacts$/.test(path)) return route.fulfill({ json: { artifacts: [], pagination: { limit: 50, offset: 0, has_more: false } } });
    const debugMatch = path.match(/\/node-runs\/(\d+)$/);
    if (debugMatch) { const node = runs.flatMap(r => r.nodes).find(n => n.id === Number(debugMatch[1])); return route.fulfill({ json: { ...node, environment: { workflow: runs.find(r => r.nodes.some(n => n.id === node.id))?.workflow }, attempts: [node] } }); }
    return route.fulfill({ json: {} });
  });
  return { tasks, runs, templates, writes, allowSave: () => { failSave = false; }, allowList: () => { failList = false; } };
}
