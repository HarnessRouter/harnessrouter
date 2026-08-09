'use client';

// Billing / Usage, HarnessRouter consumption only (app=harnessrouter):
// range presets, spent total, stacked bars, pricing reference.
import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import dynamic from 'next/dynamic';
import { billing, formatSpent, metricInfo } from '../lib';

const ReactECharts = dynamic(() => import('echarts-for-react'), { ssr: false });

const MS_PER_DAY = 24 * 60 * 60 * 1000;
const PRESETS = [
  { label: '1 day', ms: MS_PER_DAY },
  { label: '7 days', ms: 7 * MS_PER_DAY },
  { label: '30 days', ms: 30 * MS_PER_DAY },
];
const SERIES_COLORS = ['#285AFF', '#2E7D5B', '#B26A00', '#8A3FFC', '#A2191F', '#0F62FE', '#5B5D66'];
const CORE_PRICING = ['harness.session_minute', 'llm.gpt-5.4.input_1k', 'llm.gpt-5.4.output_1k',
  'llm.claude-sonnet-5.input_1k', 'llm.claude-sonnet-5.output_1k'];

type Bucket = { key: string; credits: number; apps: Record<string, Record<string, { units: number; credits: number }>> };
type PricingItem = { metric: string; credits_per_unit: string; status: string };

export default function UsagePage() {
  const [presetIdx, setPresetIdx] = useState(1);
  const [customFrom, setCustomFrom] = useState('');
  const [customTo, setCustomTo] = useState('');
  const [data, setData] = useState<{ buckets: Bucket[]; total_credits: number } | null>(null);
  const [pricing, setPricing] = useState<PricingItem[]>([]);
  const [showAll, setShowAll] = useState(false);
  const [loading, setLoading] = useState(true);

  const range = useMemo(() => {
    const now = Date.now();
    if (presetIdx >= 0) return { from: now - PRESETS[presetIdx].ms, to: now };
    if (customFrom && customTo) return { from: new Date(customFrom).getTime(), to: new Date(customTo).getTime() + MS_PER_DAY - 1 };
    return null;
  }, [presetIdx, customFrom, customTo]);

  const fetchUsage = useCallback(async () => {
    if (!range) return;
    setLoading(true);
    try {
      const bucket = (range.to - range.from) <= 2 * MS_PER_DAY ? 'hour' : 'day';
      setData(await billing.usage({
        from: new Date(range.from).toISOString(), to: new Date(range.to).toISOString(),
        bucket, app: 'harnessrouter',
      }));
    } catch { setData(null); } finally { setLoading(false); }
  }, [range]);

  useEffect(() => { fetchUsage(); }, [fetchUsage]);
  useEffect(() => { billing.pricing().then((p) => setPricing(p.items || [])).catch(() => {}); }, []);

  const { option, hasData, totalSpent } = useMemo(() => {
    const buckets = data?.buckets || [];
    const keys: string[] = [];
    for (const b of buckets) {
      for (const metrics of Object.values(b.apps || {})) {
        for (const m of Object.keys(metrics)) if (!keys.includes(m)) keys.push(m);
      }
    }
    const labels = buckets.map((b) => {
      if (b.key.includes('T')) return new Date(b.key.replace('Z', ':00Z')).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric' });
      return new Date(`${b.key}T00:00:00Z`).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    });
    const series = keys.map((m, i) => ({
      name: metricInfo(m).label, type: 'bar', stack: 'usage', barWidth: '60%',
      color: SERIES_COLORS[i % SERIES_COLORS.length],
      data: buckets.map((b) => {
        let v = 0;
        for (const metrics of Object.values(b.apps || {})) v += Number(metrics[m]?.credits || 0);
        return v;
      }),
    }));
    return {
      hasData: keys.length > 0,
      totalSpent: Number(data?.total_credits || 0),
      option: {
        animation: false,
        grid: { top: 44, left: 56, right: 16, bottom: 32 },
        legend: { top: 8, right: 12, textStyle: { color: '#5B5D66', fontSize: 11 }, itemWidth: 10, itemHeight: 10 },
        tooltip: { trigger: 'axis' },
        xAxis: { type: 'category', data: labels, axisLabel: { color: '#5B5D66', fontSize: 11 } },
        yAxis: { type: 'value', splitLine: { lineStyle: { color: '#DDDFE6' } } },
        series,
      },
    };
  }, [data]);

  const active = pricing.filter((p) => p.status === 'active');
  const coreCards = CORE_PRICING.map((m) => active.find((p) => p.metric === m)).filter(Boolean) as PricingItem[];
  const grouped = useMemo(() => {
    const g = new Map<string, Array<PricingItem & { info: ReturnType<typeof metricInfo> }>>();
    for (const p of active) {
      const info = metricInfo(p.metric);
      if (!g.has(info.group)) g.set(info.group, []);
      g.get(info.group)!.push({ ...p, info });
    }
    return [...g.entries()];
  }, [active]);

  return (
    <div className="hr-wrap hrb-content">
      <div><Link href="/billing" className="hr-btn ghost">Back to Billing</Link></div>

      <div className="hrb-range">
        {PRESETS.map((p, i) => (
          <button key={p.label} className={`hr-btn ${presetIdx === i ? 'primary' : 'ghost'}`} onClick={() => setPresetIdx(i)}>{p.label}</button>
        ))}
        <button className={`hr-btn ${presetIdx === -1 ? 'primary' : 'ghost'}`} onClick={() => setPresetIdx(-1)}>Custom</button>
        {presetIdx === -1 ? (
          <span className="hrb-range-custom">
            <input type="date" className="hr-input" value={customFrom} onChange={(e) => setCustomFrom(e.target.value)} />
            <span className="hrb-range-sep">to</span>
            <input type="date" className="hr-input" value={customTo} onChange={(e) => setCustomTo(e.target.value)} />
          </span>
        ) : null}
      </div>

      <div className="hr-card hrb-spent">
        <div className="hrb-label">Spent Credits</div>
        {loading ? <div className="hrb-skeleton hrb-skeleton-spent" /> : <div className="hrb-spent-value">{formatSpent(totalSpent)}</div>}
      </div>

      <div className="hr-card hrb-chart-card">
        <h3 className="hrb-section-title">Credits Spent Over Time</h3>
        {loading ? <div className="hrb-skeleton hrb-skeleton-chart" />
          : hasData ? <div className="hrb-chart"><ReactECharts option={option} notMerge style={{ height: '100%', width: '100%' }} /></div>
            : <div className="hrb-chart-empty">No usage data in this time range</div>}
      </div>

      <div className="hr-card hrb-pricing-card">
        <h3 className="hrb-section-title">Pricing</h3>
        <div className="hrb-pricing-grid">
          {coreCards.map((p, i) => {
            const info = metricInfo(p.metric);
            return (
              <div className="hrb-price" key={p.metric}>
                <span className="hrb-price-dot" style={{ background: SERIES_COLORS[i % SERIES_COLORS.length] }} />
                <div>
                  <div className="hrb-price-label">{info.label}</div>
                  <div className="hrb-price-value">{Number(p.credits_per_unit)} {info.unit}</div>
                </div>
              </div>
            );
          })}
        </div>
        <button className="hr-btn ghost" onClick={() => setShowAll(!showAll)}>
          {showAll ? 'Hide full price list' : 'Show full price list'}
        </button>
        {showAll ? (
          <div className="hrb-table-scroll">
            <table className="hrb-table">
              <thead><tr><th>Group</th><th>Item</th><th>Price</th></tr></thead>
              <tbody>
                {grouped.map(([group, items]) => items.map((p, i) => (
                  <tr key={p.metric}>
                    <td>{i === 0 ? group : ''}</td>
                    <td>{p.info.label}</td>
                    <td>{Number(p.credits_per_unit)} {p.info.unit}</td>
                  </tr>
                )))}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>
    </div>
  );
}
