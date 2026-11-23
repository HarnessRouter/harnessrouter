import { useEffect, useRef, useState } from 'react';
import { Button } from 'antd';
import { AppApiError, appListNodeItems, appRetryNode, appStartTaskRun, type AppNodeRun, type AppRun } from './app-api';
import { attemptLabel, itemRetryAction } from './item-history';
import { mergePage } from './pagination';
import { nodeLabels } from './task-workbench';

export function RunItemHistory({ run, control, replaying, busy, action }: {
  run: AppRun; control: AppNodeRun; replaying: boolean; busy: boolean;
  action: (operation: () => Promise<unknown>) => Promise<void>;
}) {
  const [page, setPage] = useState<Awaited<ReturnType<typeof appListNodeItems>> | null>(null);
  const [error, setError] = useState(''), [loading, setLoading] = useState(true);
  const generation = useRef(0), inflight = useRef(false);
  const [retry, setRetry] = useState(0);
  const read = async (offset: number, serial: number) => {
    inflight.current = true; setLoading(true); setError('');
    try {
      const next = await appListNodeItems(control.id, { offset, limit: 50 });
      if (serial !== generation.current || next.anchor_node_run_id !== control.id) return;
      setPage(current => ({ ...next, items: offset && current ? mergePage(current.items, next.items) : next.items }));
    } catch (cause) {
      if (serial === generation.current) setError(cause instanceof AppApiError ? cause.message : '集合项暂时不可用，请重试。');
    } finally {
      if (serial === generation.current) { inflight.current = false; setLoading(false); }
    }
  };
  useEffect(() => {
    const serial = ++generation.current;
    setPage(null);
    void read(0, serial);
    return () => { ++generation.current; };
  }, [control.id, control.status, retry]);
  const more = () => {
    if (inflight.current) return;
    if (!page) { setRetry(value => value + 1); return; }
    void read(page.pagination.offset + page.pagination.limit, generation.current);
  };
  return <section className="run-item-history" aria-label="集合项历史" aria-busy={loading}>
    <h4>集合项历史</h4>
    {loading && !page && <p role="status">正在加载集合项…</p>}
    {error && <p role="alert">{error}</p>}
    {page && !page.items.length && <p>当前节点没有集合项历史。</p>}
    {!!page?.items.length && <ol>{page.items.map(item => {
      const operation = itemRetryAction(run, control, item, replaying);
      return <li key={item.id}>
        <div><strong>{attemptLabel(item)}</strong><span> · {nodeLabels[item.status] || item.status}</span></div>
        {item.error_code && <p>{item.error_code}</p>}
        {item.input?.reused_from ? <p>复用自 #{String(item.input.reused_from)}</p> : null}
        <details><summary>查看项输入与输出</summary><pre>{JSON.stringify({ input: item.input, output: item.output }, null, 2)}</pre></details>
        {operation?.kind === 'retry' && <Button disabled={busy} onClick={() => void action(() => appRetryNode(run.id, control.node_id, crypto.randomUUID(), { item_node_run_id: operation.itemId }))}>重试此项</Button>}
        {operation?.kind === 'resume' && <Button disabled={busy} onClick={() => void action(() => appStartTaskRun(run.task_id, crypto.randomUUID(), operation.body))}>新建 Run 恢复此项</Button>}
      </li>;
    })}</ol>}
    {(error || page?.pagination.has_more) && <Button loading={loading} onClick={more}>{error ? '重试加载集合项' : '加载更多集合项'}</Button>}
  </section>;
}
