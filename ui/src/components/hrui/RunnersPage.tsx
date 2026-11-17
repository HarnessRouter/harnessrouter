'use client';

import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { harnessFetch } from '@/lib/hfetch';
import { gwHeaders } from '@/lib/harness';
import './runners.css';

interface Runner {
  name: string; url: string; static: boolean; alive: boolean; ready: boolean; accepting: boolean;
  phase: string; draining: boolean; active: number; capacity: number; sessions: number;
  backends?: string[]; installed_backends?: string[]; version?: string;
  last_heartbeat?: number | null; last_error?: string;
}

async function request(path = '', body?: object) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await harnessFetch(`/api/harness/internal/runners${path}`, {
      method: body ? 'POST' : 'GET', headers: gwHeaders(), cache: 'no-store',
      body: body ? JSON.stringify(body) : undefined, signal: controller.signal,
    });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Runner 操作失败，请重试。');
    return data;
  } finally {
    clearTimeout(timer);
  }
}

const phases: Record<string, string> = { starting: '启动中', installing: '安装中', ready: '就绪', failed: '准备失败', offline: '离线', draining: '排空中' };

export function RunnersPage() {
  const [rows, setRows] = useState<Runner[] | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');
  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [capacity, setCapacity] = useState('0');
  const [updated, setUpdated] = useState('');
  const [view, setView] = useState<'cards' | 'list'>('cards');
  const fetching = useRef(false);
  const reload = useCallback(async () => {
    if (fetching.current) return;
    fetching.current = true;
    try {
      const data = await request();
      setRows(data.runners); setError(''); setUpdated(new Date().toLocaleTimeString('zh-CN'));
    } catch (e) { setError(e instanceof Error ? e.message : '暂时无法读取 Runner。'); }
    finally { fetching.current = false; }
  }, []);
  useEffect(() => {
    void reload();
    const timer = setInterval(() => { if (!document.hidden) void reload(); }, 5000);
    return () => clearInterval(timer);
  }, [reload]);

  async function action(key: string, path: string, body: object) {
    setBusy(key); setError('');
    try { await request(path, body); await reload(); return true; }
    catch (e) { setError(e instanceof Error ? e.message : '操作失败。'); return false; }
    finally { setBusy(''); }
  }
  async function register(event: FormEvent) {
    event.preventDefault();
    if (await action('register', '/register', { name: name.trim(), url: url.trim(), capacity: Number(capacity) })) {
      setName(''); setUrl('');
    }
  }

  const statusOf = (runner: Runner) => !runner.alive ? '离线' : runner.draining ? '排空中'
    : runner.ready && runner.accepting ? '正常' : phases[runner.phase] || runner.phase || '准备中';
  const canAccept = (runner: Runner) => runner.alive && runner.ready && runner.accepting && !runner.draining;
  const runnerActions = (runner: Runner, compact = false) => <span className={compact ? 'runner-row-actions' : undefined}>
    <button className="btn" disabled={!!busy} onClick={() => void action(runner.name, '/drain', { name: runner.name, draining: !runner.draining, capacity: runner.capacity })}>
      {runner.draining ? '恢复接单' : '排空'}
    </button>
    {!runner.static && <button className="btn" disabled={!!busy || !runner.draining || runner.active > 0} onClick={() => {
      if (window.confirm(`确认注销节点 ${runner.name}？绑定会话仍需原节点或通过 hydrate 恢复。`)) void action(runner.name, '/deregister', { name: runner.name });
    }}>注销</button>}
  </span>;

  return <div className="scroll"><div className="list-wrap lw-n runner-page">
    <header className="runner-header"><div><h1>节点管理</h1><p>管理此实例的执行节点，每 5 秒刷新状态。</p></div>
      <button className="btn" onClick={() => void reload()}>刷新</button></header>
    {error && <p className="runner-error" role="alert">{error}</p>}
    <div className="runner-summary" aria-live="polite">
      <span>节点总数 <b>{rows?.length ?? '—'}</b></span>
      <span>可接单 <b>{rows?.filter(r => r.alive && r.ready && r.accepting && !r.draining).length ?? '—'}</b></span>
      <span>排空中 <b>{rows?.filter(r => r.draining).length ?? '—'}</b></span>
      {updated && <small>更新于 {updated}</small>}
    </div>
    <section className="runner-register"><h2>注册节点</h2><p>填写 session-router 可访问的 Runner 地址。节点通过就绪检查后才能接收任务。</p>
      <form onSubmit={e => void register(e)}>
        <label>节点名称<input className="set-in" required value={name} onChange={e => setName(e.target.value)} placeholder="runner-3" /></label>
        <label>服务地址<input className="set-in" required type="url" value={url} onChange={e => setUrl(e.target.value)} placeholder="http://runner-3:8081" /></label>
        <label>并发容量<input className="set-in" required type="number" min="0" step="1" value={capacity} onChange={e => setCapacity(e.target.value)} /></label>
        <button className="btn primary" disabled={!!busy}>注册</button>
      </form><small>容量为 0 表示不限。节点地址和名称需在当前集群内唯一。</small>
    </section>
    <div className="runner-toolbar"><h2>节点列表</h2><div className="runner-view-switch" role="group" aria-label="节点显示模式">
      <button type="button" aria-pressed={view === 'cards'} onClick={() => setView('cards')}>卡片</button>
      <button type="button" aria-pressed={view === 'list'} onClick={() => setView('list')}>列表</button>
    </div></div>
    {rows === null ? <p role="status">正在读取节点…</p> : rows.length === 0 ? <p>暂无 Runner，可在上方注册节点。</p> : view === 'list' ? (
      <div className="runner-table-wrap"><table className="runner-table"><thead><tr>
        <th>名称</th><th>健康状态</th><th>任务 / 容量</th><th>会话</th><th>已安装后端</th><th>最近心跳</th><th aria-label="操作" />
      </tr></thead><tbody>{rows.map(r => <tr key={r.name}>
        <td><div className="runner-name-cell"><span className={`runner-dot${canAccept(r) ? ' is-ready' : ''}`} /><span><strong>{r.name}</strong><small>{r.url}</small></span></div></td>
        <td><span className={`runner-phase runner-phase-compact${canAccept(r) ? ' is-ready' : ''}`}>{statusOf(r)}</span></td>
        <td>{r.active}{r.capacity ? ` / ${r.capacity}` : ' / 不限'}</td>
        <td>{r.sessions}</td>
        <td><span className="runner-backends">{(r.backends || r.installed_backends || []).join('、') || '尚未上报'}</span></td>
        <td>{r.last_heartbeat ? new Date(r.last_heartbeat * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : '—'}</td>
        <td>{runnerActions(r, true)}</td>
      </tr>)}</tbody></table></div>
    ) : (
      <div className="runner-list runner-view-cards">{rows.map(r => <article key={r.name} className="runner-card">
        <header><div><h2>{r.name}</h2><code>{r.url}</code></div><span className={`runner-phase ${canAccept(r) ? 'is-ready' : ''}`}>
          {statusOf(r)}</span></header>
        <dl><div><dt>来源</dt><dd>{r.static ? '静态配置' : '动态注册'}</dd></div>
          <div><dt>可接单</dt><dd>{r.alive && r.ready && r.accepting && !r.draining ? '是' : '否'}</dd></div>
          <div><dt>活动请求</dt><dd>{r.active}</dd></div><div><dt>容量</dt><dd>{r.capacity || '不限'}</dd></div>
          <div><dt>绑定会话</dt><dd>{r.sessions}</dd></div><div><dt>版本</dt><dd>{r.version || '—'}</dd></div>
          <div><dt>最近心跳</dt><dd>{r.last_heartbeat ? new Date(r.last_heartbeat * 1000).toLocaleString('zh-CN') : '尚未收到'}</dd></div></dl>
        <p>已安装后端 <strong>{(r.backends || r.installed_backends || []).join('、') || '尚未上报'}</strong></p>
        {r.last_error && <p className="runner-error">探测错误 {r.last_error}</p>}
        <footer><span>{r.static ? '静态节点通过 HR_RUNNERS 管理。' : '注销前请先排空节点并等待活动请求结束。'}</span>{runnerActions(r)}</footer>
      </article>)}</div>
    )}
  </div></div>;
}
