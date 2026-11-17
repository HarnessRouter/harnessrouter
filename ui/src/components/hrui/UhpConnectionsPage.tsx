'use client';

import { useCallback, useEffect, useState } from 'react';
import { harnessFetch } from '@/lib/hfetch';
import { gwHeaders } from '@/lib/harness';
import { toast } from './toast';

type RemoteHarness = { id: string; remote_id: string; name: string; enabled: boolean; status?: string };
type Health = {
  status: string; last_checked_at?: number; last_success_at?: number;
  latency_ms?: number; fresh_until?: number; last_error?: string; stale?: boolean;
};
type Connection = {
  id: string; name: string; kind: string; base_url: string;
  config?: { api_key?: string };
  uhp?: { version?: string; capabilities?: Record<string, boolean> };
  harnesses?: RemoteHarness[];
  health?: Health;
};

const SECRET = '__secret__';
const HEALTH_LABELS: Record<string, string> = {
  unknown: '未检查', healthy: '连接正常', unreachable: '无法连接', unauthorized: '鉴权失败',
  harness_missing: 'Harness 缺失', invalid: '响应无效',
};
const checkedTime = (value?: number) => value ? new Date(value * 1000).toLocaleString('zh-CN') : '—';

export function UhpConnectionsPage() {
  const [connections, setConnections] = useState<Connection[] | null>(null);
  const [name, setName] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [checking, setChecking] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now() / 1000);

  const load = useCallback(async () => {
    const res = await harnessFetch('/api/harness/v1/admin/uhp-connections', { headers: { ...gwHeaders() } });
    if (!res.ok) throw new Error(String(res.status));
    const data = await res.json() as { connections?: Connection[] };
    setConnections(Array.isArray(data.connections) ? data.connections : []);
  }, []);

  useEffect(() => { void load().catch(() => setError('暂时无法读取 UHP 连接。')); }, [load]);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(timer);
  }, []);

  async function check(row?: Connection) {
    setChecking(row?.id || 'all'); setError('');
    try {
      if (!row) { await load(); return; }
      const res = await harnessFetch(`/api/harness/v1/admin/uhp-connections/${encodeURIComponent(row.name)}/check`, {
        method: 'POST', headers: { ...gwHeaders() },
      });
      if (!res.ok) throw new Error('检查失败，请稍后重试。');
      const data = await res.json() as { connection: Connection };
      setConnections((old) => (old || []).map((item) => item.id === row.id ? data.connection : item));
    } catch { setError('检查失败，请稍后重试。'); }
    finally { setChecking(null); setNow(Date.now() / 1000); }
  }

  async function save() {
    if (!name.trim() || !baseUrl.trim()) { setError('请填写连接名称和 UHP 地址。'); return; }
    setBusy(true); setError('');
    try {
      const res = await harnessFetch(`/api/harness/v1/admin/uhp-connections/${encodeURIComponent(name.trim())}`, {
        method: 'PUT', headers: { ...gwHeaders(), 'content-type': 'application/json' },
        body: JSON.stringify({ name: name.trim(), base_url: baseUrl.trim(), api_key: apiKey || SECRET }),
      });
      if (!res.ok) { const d = await res.json().catch(() => null) as { detail?: string } | null; throw new Error(d?.detail || `HTTP ${res.status}`); }
      const d = await res.json() as { connection?: Connection };
      setConnections((old) => [...(old || []).filter((x) => x.name !== name.trim()), ...(d.connection ? [d.connection] : [])]);
      setApiKey('');
      toast(d.connection?.health?.status === 'healthy' ? 'UHP 连接已保存，Harness 已同步。' : 'UHP 连接已保存，但当前不可用，可修复后立即检查。');
    } catch (e) { setError(e instanceof Error ? e.message : '连接失败，请检查地址和密钥。'); }
    finally { setBusy(false); }
  }

  async function remove(row: Connection) {
    if (!window.confirm(`删除 UHP 连接“${row.name}”？`)) return;
    setBusy(true);
    try {
      const res = await harnessFetch(`/api/harness/v1/admin/uhp-connections/${encodeURIComponent(row.name)}`, { method: 'DELETE', headers: { ...gwHeaders() } });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setConnections((old) => (old || []).filter((x) => x.name !== row.name));
      toast('UHP 连接已删除。');
    } catch { setError('删除失败，请稍后重试。'); }
    finally { setBusy(false); }
  }

  return (
    <div className="scroll">
      <div className="list-wrap uhp-page">
        <div className="list-top">
          <div><h1>UHP连接</h1><p className="sub">连接外部 UHP Runtime，例如 xred-bc。密钥只保存在 Gateway 服务端，客户端不会接触。</p></div>
          <div className="uhp-actions">{connections ? <span className="kicker prov-count">{connections.length} 个连接</span> : null}
            <button type="button" className="btn small" disabled={busy || checking !== null} onClick={() => void check()}>{checking === 'all' ? '刷新中…' : '刷新状态'}</button></div>
        </div>

        <section className="pv-g uhp-card">
          <header><h2>添加或更新连接</h2><span className="kicker">UHP Runtime</span></header>
          <div className="uhp-form">
            <label>连接名称<input className="set-in" value={name} onChange={(e) => setName(e.target.value)} placeholder="Browser Runtime" /></label>
            <label>UHP 地址<input className="set-in" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="http://xred:8421" /></label>
            <label>Bearer 密钥<input className="set-in" type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="输入密钥；更新已有连接可留空" /></label>
            <button type="button" className="btn small sv-ink" disabled={busy} onClick={() => void save()}>{busy ? '连接中…' : '测试并保存'}</button>
          </div>
          {error ? <p className="uhp-error" role="alert">{error}</p> : null}
        </section>

        {!connections && !error ? <section className="pv-g"><p className="sub">正在读取连接…</p></section> : null}
        {connections?.map((row) => (
          <section className="pv-g uhp-card" key={row.id || row.name}>
            <header><h2>{row.name}</h2><span className="kicker" role="status">{HEALTH_LABELS[row.health?.status || 'unknown'] || '未检查'}{row.health?.last_checked_at && (row.health.stale || (row.health.fresh_until || 0) <= now) ? ' · 状态已过期' : ''}</span></header>
            <div className="uhp-meta"><code>{row.base_url}</code><span>{row.uhp?.version ? `UHP ${row.uhp.version}` : ''}</span>
              <button type="button" className="btn small" disabled={busy || checking !== null} onClick={() => void check(row)}>{checking === row.id ? '检查中…' : '立即检查'}</button>
              <button type="button" className="link-q" disabled={busy || checking !== null} onClick={() => void remove(row)}>删除</button></div>
            <div className="uhp-health-meta"><span>最近检查：{checkedTime(row.health?.last_checked_at)}</span><span>最近成功：{checkedTime(row.health?.last_success_at)}</span>
              <span>延迟：{row.health?.latency_ms == null ? '—' : `${row.health.latency_ms} ms`}</span><span>{(row.harnesses || []).filter((item) => item.status !== 'harness_missing').length} 个已同步 Harness</span></div>
            {row.health?.last_error ? <p className="uhp-error">{row.health.last_error}</p> : null}
            <div className="uhp-harnesses">
              {(row.harnesses || []).map((h) => <div className="uhp-harness" key={h.remote_id}><span className={`uhp-dot${h.status === 'harness_missing' || row.health?.status !== 'healthy' ? ' off' : ''}`} /> <span>{h.name}</span><code title={`Runtime ID: ${h.remote_id}`}>{h.id}</code><span className="muted">{h.status === 'harness_missing' ? 'Harness 缺失' : '已同步 Harness'}</span></div>)}
              {!row.harnesses?.length ? <p className="sub">当前没有可用 Harness。</p> : null}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
