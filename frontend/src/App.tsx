import React, { useEffect, useState } from 'react';
import { TrendingUp, Wallet, AlertCircle, Loader2, Lock, FileText, Check, X, Clock, ChevronDown, ChevronUp } from 'lucide-react';
import './App.css';
import type { WeeklyInvestmentPlan, WeeklyPlanItem, DecisionAction } from './types/productCore';
import { getWeeklyPlan, buildWeeklyPlan, freezeWeeklyPlan } from './api/weeklyPlan';
import { submitDecision, getDecision } from './api/confirmation';

/* ── Helpers ── */
const STATUS_COLORS: Record<string, string> = {
  PASS: '#10b981', WARNING: '#f59e0b', REVIEW_REQUIRED: '#f97316',
  BLOCKED: '#ef4444', SOURCE_ERROR: '#ef4444',
};
const fmt = (v: number | null | undefined) => (v != null ? v.toFixed(2) : '—');
const pct = (v: number | null | undefined) => (v != null ? `${(v * 100).toFixed(2)}%` : '—');

/* ── Main App ── */
function App() {
  const [plan, setPlan] = useState<(WeeklyInvestmentPlan & { items: WeeklyPlanItem[] }) | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'plan' | 'diagnostics'>('plan');
  const [expandedItem, setExpandedItem] = useState<number | null>(null);

  const fetchPlan = async () => {
    setLoading(true); setError(null);
    try {
      const list = await getWeeklyPlans();
      const latest = list?.[list.length - 1];
      if (latest) {
        const full = await getWeeklyPlan(latest.id);
        setPlan(full);
      } else {
        setPlan(null);
      }
    } catch (e: any) { setError(e?.detail || 'Failed to load plan'); }
    finally { setLoading(false); }
  };

  useEffect(() => { fetchPlan(); }, []);

  const handleBuild = async () => {
    setLoading(true); setError(null);
    try {
      await buildWeeklyPlan({ week_start: '', config_id: 1 });
      await fetchPlan();
    } catch (e: any) { setError(e?.detail || 'Build failed'); }
    finally { setLoading(false); }
  };

  const handleFreeze = async () => {
    if (!plan?.id) return;
    if (!confirm('冻结后计划金额不可静默修改。确认冻结？')) return;
    setLoading(true);
    try {
      await freezeWeeklyPlan(plan.id);
      await fetchPlan();
    } catch (e: any) { setError(e?.detail || 'Freeze failed'); }
    finally { setLoading(false); }
  };

  const handleDecision = async (itemId: number, action: DecisionAction, approvedAmount?: number, reason?: string) => {
    setLoading(true); setError(null);
    try {
      await submitDecision(itemId, { user_action: action, approved_amount: approvedAmount, reason });
      await fetchPlan();
    } catch (e: any) { setError(e?.detail || 'Decision failed'); }
    finally { setLoading(false); }
  };

  /* ── Render ── */
  const isFrozen = plan?.status === 'FROZEN';
  const isDraft = plan?.status === 'DRAFT';
  const executableItems = plan?.items?.filter(i => i.data_quality_status === 'PASS' && i.final_amount && i.final_amount > 0) || [];
  const blockedItems = plan?.items?.filter(i => ['SOURCE_ERROR', 'BLOCKED', 'REVIEW_REQUIRED'].includes(i.data_quality_status)) || [];

  return (
    <div style={{ maxWidth: 960, margin: '0 auto', padding: 20, color: '#e2e8f0', fontFamily: 'system-ui', minHeight: '100vh', background: '#0f172a' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 18 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, color: '#f1f5f9', margin: 0 }}>
          <TrendingUp size={22} style={{ marginRight: 8, verticalAlign: -4 }} />
          复利定投工作台
        </h1>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => setActiveTab('plan')} style={tabStyle(activeTab === 'plan')}>本周计划</button>
          <button onClick={() => setActiveTab('diagnostics')} style={tabStyle(activeTab === 'diagnostics')}>诊断</button>
        </div>
      </div>

      {error && <div style={{ background: '#7f1d1d', padding: 10, borderRadius: 8, marginBottom: 12, color: '#fca5a5' }}><AlertCircle size={16} style={{ verticalAlign: -3 }} /> {error}</div>}

      {activeTab === 'diagnostics' ? (
        <DiagnosticsView />
      ) : (
        <>
          {/* Empty state */}
          {!plan && !loading && (
            <div style={{ textAlign: 'center', padding: 60, background: '#1e293b', borderRadius: 12 }}>
              <Wallet size={48} style={{ color: '#64748b', marginBottom: 12 }} />
              <p style={{ color: '#94a3b8', fontSize: 16 }}>暂无本周投资计划</p>
              <button onClick={handleBuild} style={primaryBtn}>生成本周计划</button>
            </div>
          )}

          {loading && <div style={{ textAlign: 'center', padding: 40 }}><Loader2 size={32} style={{ animation: 'spin 1s linear infinite', color: '#6366f1' }} /></div>}

          {plan && (
            <>
              {/* Summary Bar */}
              <div style={{ background: '#1e293b', borderRadius: 12, padding: 18, marginBottom: 16 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                  <span style={{ fontSize: 14, color: '#94a3b8' }}>
                    周期: {plan.week_start} → {plan.week_end}
                  </span>
                  <StatusBadge status={plan.status} />
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, fontSize: 13 }}>
                  <Metric label="周预算" value={plan.weekly_budget} />
                  <Metric label="核心预算" value={plan.core_budget} />
                  <Metric label="卫星预算" value={plan.satellite_budget} />
                  <Metric label="建议总额" value={plan.total_final_amount ?? 0} />
                </div>
                <div style={{ marginTop: 12, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  {isDraft && <button onClick={handleBuild} style={secondaryBtn}>刷新计划</button>}
                  {isDraft && <button onClick={handleFreeze} style={primaryBtn}><Lock size={14} /> 冻结计划</button>}
                </div>
              </div>

              {/* Executable Items */}
              <Section title={`可执行项 (${executableItems.length})`} color="#10b981">
                {executableItems.map(item => (
                  <PlanItemCard key={item.id} item={item} expanded={expandedItem === item.id}
                    onToggle={() => setExpandedItem(expandedItem === item.id ? null : item.id)}
                    frozen={isFrozen} onDecision={(a, amt, r) => handleDecision(item.id, a, amt, r)} />
                ))}
              </Section>

              {/* Blocked Items */}
              {blockedItems.length > 0 && (
                <Section title={`阻断/复核项 (${blockedItems.length})`} color="#ef4444">
                  {blockedItems.map(item => (
                    <PlanItemCard key={item.id} item={item} expanded={expandedItem === item.id}
                      onToggle={() => setExpandedItem(expandedItem === item.id ? null : item.id)}
                      frozen={false} onDecision={() => {}} />
                  ))}
                </Section>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}

/* ── Sub-components ── */
function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = { DRAFT: '#6366f1', FROZEN: '#10b981', CLOSED: '#64748b', SUPERSEDED: '#f59e0b' };
  return <span style={{ background: colors[status] || '#334155', padding: '2px 10px', borderRadius: 6, fontSize: 12, fontWeight: 600 }}>{status}</span>;
}

function Metric({ label, value }: { label: string; value: number | null | undefined }) {
  return (
    <div>
      <div style={{ color: '#64748b', fontSize: 11 }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 700, color: '#f1f5f9' }}>¥{fmt(value)}</div>
    </div>
  );
}

function Section({ title, color, children }: { title: string; color: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <h2 style={{ fontSize: 14, fontWeight: 600, color, marginBottom: 8, borderLeft: `3px solid ${color}`, paddingLeft: 8 }}>{title}</h2>
      {children}
    </div>
  );
}

function PlanItemCard({ item, expanded, onToggle, frozen, onDecision }: {
  item: WeeklyPlanItem; expanded: boolean; onToggle: () => void; frozen: boolean;
  onDecision: (action: DecisionAction, amount?: number, reason?: string) => void;
}) {
  const [approveAmount, setApproveAmount] = useState(item.final_amount ?? 0);
  const [skipReason, setSkipReason] = useState('');
  const dq = item.data_quality_status;
  const canApprove = frozen && dq === 'PASS' && item.final_amount && item.final_amount > 0;

  return (
    <div style={{ background: '#1e293b', borderRadius: 10, marginBottom: 8, overflow: 'hidden' }}>
      <div onClick={onToggle} style={{ padding: '12px 16px', cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <span style={{ fontWeight: 600, fontSize: 14 }}>{item.asset_name || item.asset_code}</span>
          <span style={{ marginLeft: 8, fontSize: 12, padding: '2px 8px', borderRadius: 4, background: item.asset_role === 'core' ? '#1e40af' : '#7c3aed' }}>
            {item.asset_role?.toUpperCase() || 'CORE'}
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: qtyColor(dq) }}>{dq}</span>
          <span style={{ fontSize: 18, fontWeight: 700, color: item.final_amount ? '#f1f5f9' : '#64748b' }}>
            ¥{item.final_amount != null ? fmt(item.final_amount) : '—'}
          </span>
          {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </div>
      </div>

      {expanded && (
        <div style={{ padding: '0 16px 14px', borderTop: '1px solid #334155', fontSize: 12 }}>
          {/* Evidence grid */}
          <EvidenceBlock item={item} />
          {item.reason_summary && <div style={{ marginTop: 8, color: '#f87171', background: '#450a0a', padding: '6px 10px', borderRadius: 6 }}>⚠ {item.reason_summary}</div>}

          {/* Decision UI */}
          {frozen && canApprove && (
            <div style={{ marginTop: 10, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <input type="number" value={approveAmount} onChange={e => setApproveAmount(Number(e.target.value))}
                style={inputStyle} placeholder="批准金额" min={0} max={item.final_amount ?? 0} />
              <button onClick={() => onDecision('APPROVED', approveAmount)} style={primaryBtn}>批准</button>
              <input value={skipReason} onChange={e => setSkipReason(e.target.value)} style={inputStyle} placeholder="跳过原因" />
              <button onClick={() => onDecision('SKIPPED', undefined, skipReason)} style={secondaryBtn}>跳过</button>
              <button onClick={() => onDecision('DEFERRED', undefined, skipReason || '延期')} style={secondaryBtn}>延期</button>
            </div>
          )}
          {frozen && !canApprove && <div style={{ marginTop: 8, color: '#64748b' }}>此项不可批准</div>}
        </div>
      )}
    </div>
  );
}

/* ── Evidence ── */
function EvidenceBlock({ item }: { item: WeeklyPlanItem }) {
  const pairs: [string, string | number | null | undefined][] = [
    ['净值', item.nav], ['净值日期', item.nav_date],
    ['代理指数', item.proxy_code], ['指数收盘', item.proxy_close], ['MA200', item.proxy_ma200],
    ['偏离', item.dev_pct != null ? pct(item.dev_pct) : '—'],
    ['估值', item.valuation_state], ['风险', item.risk_status], ['暴露', item.exposure_status],
    ['固定', item.fixed_amount], ['动态', item.dynamic_amount],
    ['已分配固定', item.allocated_fixed], ['已分配动态', item.allocated_dynamic],
    ['数据源', item.data_source], ['数据日期', item.market_data_date],
  ];
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 4, marginTop: 8 }}>
      {pairs.filter(([, v]) => v != null && v !== '').map(([k, v]) => (
        <div key={k}><span style={{ color: '#64748b' }}>{k}</span>: <span style={{ color: '#e2e8f0' }}>{String(v)}</span></div>
      ))}
    </div>
  );
}

/* ── Diagnostics (Legacy) ── */
function DiagnosticsView() {
  return (
    <div style={{ background: '#1e293b', borderRadius: 12, padding: 20, color: '#94a3b8' }}>
      <h3 style={{ color: '#f59e0b', fontSize: 14 }}>⚠ 旧版诊断</h3>
      <p style={{ fontSize: 12 }}>
        旧版“今日操作计划”(/api/decision/today) 和“每日决策”(/api/decision/run-daily) 已降级为只读诊断。
        当前正式产品入口为 v2.1 WeeklyInvestmentPlan。
      </p>
      <p style={{ fontSize: 12 }}>旧版直接交易表单 (POST /api/transactions) 已禁用 (HTTP 410)。</p>
    </div>
  );
}

/* ── Helpers ── */
async function getWeeklyPlans(): Promise<any[]> {
  const res = await fetch('/api/weekly-plans');
  if (!res.ok) throw { detail: await res.text() };
  return res.json();
}

function qtyColor(dq: string) { return STATUS_COLORS[dq] || '#94a3b8'; }
const primaryBtn: React.CSSProperties = { background: '#6366f1', color: '#fff', border: 'none', padding: '6px 14px', borderRadius: 6, cursor: 'pointer', fontWeight: 600, fontSize: 12 };
const secondaryBtn: React.CSSProperties = { ...primaryBtn, background: '#334155', color: '#e2e8f0' };
const tabStyle = (active: boolean): React.CSSProperties => ({ background: active ? '#334155' : 'transparent', color: active ? '#f1f5f9' : '#64748b', border: 'none', padding: '6px 14px', borderRadius: 6, cursor: 'pointer', fontSize: 13, fontWeight: 600 });
const inputStyle: React.CSSProperties = { background: '#0f172a', border: '1px solid #334155', color: '#e2e8f0', padding: '6px 10px', borderRadius: 6, fontSize: 12, width: 100 };

export default App;
