import React, { useEffect, useState } from 'react';
import { TrendingUp, Wallet, AlertCircle, Loader2, Lock, ChevronDown, ChevronUp, Check, X, Clock, FileText, Shield, BarChart3, Activity, PieChart } from 'lucide-react';
import './App.css';
import type { WeeklyInvestmentPlan, WeeklyPlanItem, DecisionAction } from './types/productCore';
import { buildWeeklyPlan, freezeWeeklyPlan } from './api/weeklyPlan';
import { submitDecision } from './api/confirmation';

/* ── Constants ── */
const STATUS_LABEL: Record<string, string> = {
  PASS: '数据可信', WARNING: '需要关注', REVIEW_REQUIRED: '需要复核',
  BLOCKED: '数据阻断', SOURCE_ERROR: '数据获取失败',
};
const ROLE_LABEL: Record<string, string> = { core: '核心', satellite: '卫星', defensive: '防守' };
const DQ_COLORS: Record<string, string> = {
  PASS: 'var(--success)', WARNING: 'var(--warning)', REVIEW_REQUIRED: '#f97316',
  BLOCKED: 'var(--danger)', SOURCE_ERROR: 'var(--danger)',
};
const fmt = (v: number | null | undefined) => (v != null ? v.toFixed(2) : '—');

/* ── App Shell ── */
function App() {
  const [plan, setPlan] = useState<(WeeklyInvestmentPlan & { items: WeeklyPlanItem[] }) | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<'plan' | 'diagnostics'>('plan');
  const [expandedItem, setExpandedItem] = useState<number | null>(null);

  const fetchPlan = async () => {
    setLoading(true); setError(null);
    try {
      const res = await fetch('/api/weekly-plans'); if (!res.ok) throw {};
      const data = await res.json();
      const list = data.plans || data || [];
      const latest = list?.[list.length - 1];
      if (latest) {
        const r2 = await fetch(`/api/weekly-plans/${latest.id}`);
        const full = await r2.json();
        setPlan({ ...full.plan, items: full.items || [] });
      } else { setPlan(null); }
    } catch { setError('无法加载计划'); }
    finally { setLoading(false); }
  };

  useEffect(() => { fetchPlan(); }, []);

  /* ── Actions ── */
  const getMonday = () => { const d = new Date(); d.setDate(d.getDate() - ((d.getDay() + 6) % 7)); return d.toISOString().slice(0, 10); };

  const handleBuild = async () => {
    setLoading(true); setError(null);
    try { await buildWeeklyPlan({ week_start: getMonday(), config_id: 1, rebuild: true }); await fetchPlan(); }
    catch { setError('生成计划失败'); }
    finally { setLoading(false); }
  };

  const handleFreeze = async () => {
    if (!plan?.id || !confirm('冻结后金额不可静默修改。确认冻结？')) return;
    setLoading(true);
    try { await freezeWeeklyPlan(plan.id); await fetchPlan(); }
    catch { setError('冻结失败'); }
    finally { setLoading(false); }
  };

  const handleDecision = async (itemId: number, action: DecisionAction, amount?: number, reason?: string) => {
    setLoading(true); setError(null);
    try { await submitDecision(itemId, { user_action: action, approved_amount: amount, reason }); await fetchPlan(); }
    catch { setError('决策提交失败'); }
    finally { setLoading(false); }
  };

  const isDraft = plan?.status === 'DRAFT';
  const isFrozen = plan?.status === 'FROZEN';
  const passItems = plan?.items?.filter(i => i.data_quality_status === 'PASS' && i.final_amount && i.final_amount > 0) || [];
  const blockedItems = plan?.items?.filter(i => !passItems.includes(i)) || [];

  /* ── Render ── */
  return (
    <div className="app-container">
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="brand"><TrendingUp size={24} /> 复利定投工作台</div>

        <div className="global-dashboard">
          <span className="global-label">本周建议金额</span>
          <span className="global-value">¥{fmt(plan?.total_final_amount)}</span>
          <span className="global-sub">{plan ? `预算 ¥${plan.weekly_budget || 200} · ${isDraft ? '草稿' : isFrozen ? '已冻结' : plan.status}` : '暂无计划'}</span>
        </div>

        <div className="section-header">导航</div>
        <nav className="asset-list" style={{ gap: 2 }}>
          {[
            { id: 'plan', label: '本周计划', icon: Activity },
            { id: 'diagnostics', label: '诊断', icon: Shield },
          ].map(nav => (
            <div key={nav.id} className={`asset-item ${activeView === nav.id ? 'active' : ''}`}
                 onClick={() => setActiveView(nav.id as any)}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <nav.icon size={16} style={{ color: 'var(--text-dim)' }} />
                <span className="name">{nav.label}</span>
              </div>
            </div>
          ))}
        </nav>

        <div style={{ marginTop: 'auto', fontSize: 11, color: 'var(--text-dim)' }}>
          策略 v2.1 · 数据 MA200
        </div>
      </aside>

      {/* Main */}
      <main className="main-content" style={{ padding: '32px 40px' }}>
        {error && <div className="error-banner"><AlertCircle size={14} />{error}</div>}

        {activeView === 'diagnostics' ? (
          <DiagnosticsView />
        ) : (
          <>
            {loading && <div style={{ textAlign: 'center', padding: 60 }}><Loader2 size={28} className="spinner" /></div>}

            {!plan && !loading && (
              <div className="card" style={{ textAlign: 'center', padding: 60, maxWidth: 480, margin: '60px auto' }}>
                <Wallet size={40} style={{ color: 'var(--text-dim)', marginBottom: 12 }} />
                <p style={{ color: 'var(--text-muted)', fontSize: 15 }}>暂无本周投资计划</p>
                <button className="btn btn-primary" onClick={handleBuild} style={{ marginTop: 16 }}>生成本周计划</button>
              </div>
            )}

            {plan && (
              <div className="dashboard-grid">
                {/* Header */}
                <div className="card" style={{ gridColumn: 'span 12', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    <h1 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>本周投资计划</h1>
                    <p style={{ margin: '4px 0 0', color: 'var(--text-muted)', fontSize: 13 }}>
                      {plan.week_start} → {plan.week_end} · {isDraft ? '草稿' : isFrozen ? '已冻结' : plan.status}
                    </p>
                  </div>
                  <div style={{ display: 'flex', gap: 10 }}>
                    {isDraft && <button className="btn btn-secondary" onClick={handleBuild}>刷新数据</button>}
                    {isDraft && <button className="btn btn-primary" onClick={handleFreeze}><Lock size={14} />冻结计划</button>}
                    {(plan.status === 'CLOSED' || plan.status === 'SUPERSEDED') && <button className="btn btn-primary" onClick={handleBuild}>重新生成</button>}
                  </div>
                </div>

                {/* Budget summary */}
                <div className="card" style={{ gridColumn: 'span 4' }}>
                  <span className="global-label">核心预算</span>
                  <span className="global-value">¥{fmt(passItems.filter(i => i.asset_role === 'core').reduce((s, i) => s + (i.final_amount || 0), 0))}</span>
                  <span className="global-sub">{passItems.filter(i => i.asset_role === 'core').length} 项核心</span>
                </div>
                <div className="card" style={{ gridColumn: 'span 4' }}>
                  <span className="global-label">卫星预算</span>
                  <span className="global-value">¥{fmt(passItems.filter(i => i.asset_role === 'satellite').reduce((s, i) => s + (i.final_amount || 0), 0))}</span>
                  <span className="global-sub">{passItems.filter(i => i.asset_role === 'satellite').length} 项卫星</span>
                </div>
                <div className="card" style={{ gridColumn: 'span 4' }}>
                  <span className="global-label">待处理</span>
                  <span className="global-value" style={{ color: 'var(--warning)' }}>{passItems.length} 可执行</span>
                  <span className="global-sub">{blockedItems.length} 项待修复</span>
                </div>

                {/* PASS items */}
                {passItems.length > 0 && (
                  <div className="card" style={{ gridColumn: 'span 12' }}>
                    <div className="section-header">可执行资产</div>
                    {passItems.map(item => (
                      <PlanAssetRow key={item.id} item={item} expanded={expandedItem === item.id}
                        onToggle={() => setExpandedItem(expandedItem === item.id ? null : item.id)}
                        frozen={isFrozen} onDecision={(a, amt, r) => handleDecision(item.id, a, amt, r)} />
                    ))}
                  </div>
                )}

                {/* Blocked items */}
                {blockedItems.length > 0 && (
                  <div className="card" style={{ gridColumn: 'span 12' }}>
                    <div className="section-header">待修复数据</div>
                    <div style={{ color: 'var(--text-muted)', fontSize: 12, marginBottom: 12 }}>以下资产因数据缺失被阻断，不会生成投资金额</div>
                    {blockedItems.map(item => (
                      <BlockedAssetRow key={item.id} item={item} />
                    ))}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}

/* ── Plan Asset Row ── */
function PlanAssetRow({ item, expanded, onToggle, frozen, onDecision }: {
  item: WeeklyPlanItem; expanded: boolean; onToggle: () => void; frozen: boolean;
  onDecision: (action: DecisionAction, amount?: number, reason?: string) => void;
}) {
  const [mode, setMode] = useState<'none' | 'approve' | 'skip' | 'defer'>('none');
  const [amt, setAmt] = useState(item.final_amount ?? 0);
  const [reason, setReason] = useState('');
  const dq = item.data_quality_status;
  const canDecide = frozen && item.data_quality_status === 'PASS' && (item.final_amount || 0) > 0;

  return (
    <div className="asset-item" style={{ flexDirection: 'column', alignItems: 'stretch', cursor: 'default', marginBottom: 2 }}
         onClick={() => onToggle()}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span className="name">{item.asset_name || item.asset_code}</span>
            <span className="code">{item.asset_code}</span>
            <span className="role-tag">{ROLE_LABEL[item.asset_role] || item.asset_role}</span>
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
            {item.reason_summary || `${STATUS_LABEL[dq] || dq}${item.market_data_date ? ' · 数据更新于 ' + item.market_data_date : ''}`}
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: 11, color: DQ_COLORS[dq] || 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 4 }}>
            <StatusDot color={DQ_COLORS[dq]} /> {STATUS_LABEL[dq] || dq}
          </span>
          <span className="global-value" style={{ fontSize: 20 }}>
            ¥{item.final_amount != null ? fmt(item.final_amount) : '—'}
          </span>
          {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </div>
      </div>

      {expanded && (
        <div style={{ marginTop: 14, borderTop: 'var(--border-subtle)', paddingTop: 14 }}>
          {/* Evidence */}
          <div className="data-grid" style={{ marginBottom: 12 }}>
            <EvidenceField label="净值" value={item.nav} />
            <EvidenceField label="代理指数" value={item.proxy_code} />
            <EvidenceField label="指数收盘" value={item.proxy_close} />
            <EvidenceField label="MA200" value={item.proxy_ma200} />
            <EvidenceField label="偏离" value={item.dev_pct != null ? (item.dev_pct * 100).toFixed(2) + '%' : '—'} />
            <EvidenceField label="估值" value={item.valuation_state} />
            <EvidenceField label="固定/动态" value={item.fixed_amount != null ? `${fmt(item.fixed_amount)} / ${fmt(item.dynamic_amount)}` : '—'} />
            <EvidenceField label="数据源" value={item.data_source} />
          </div>

          {/* Decision */}
          {frozen && canDecide && (
            <div>
              <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
                <button className={`btn ${mode === 'approve' ? 'btn-primary' : 'btn-secondary'}`}
                        onClick={(e) => { e.stopPropagation(); setMode('approve'); }}>批准投入</button>
                <button className={`btn ${mode === 'skip' ? 'btn-primary' : 'btn-secondary'}`}
                        onClick={(e) => { e.stopPropagation(); setMode('skip'); }}>本周跳过</button>
                <button className={`btn ${mode === 'defer' ? 'btn-primary' : 'btn-secondary'}`}
                        onClick={(e) => { e.stopPropagation(); setMode('defer'); }}>延期观察</button>
              </div>

              {mode === 'approve' && (
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <input type="number" value={amt} onChange={e => setAmt(Number(e.target.value))}
                         className="input" placeholder="批准金额" min={0} max={item.final_amount ?? 0} style={{ width: 120 }} />
                  <button className="btn btn-primary" onClick={(e) => { e.stopPropagation(); onDecision('APPROVED', amt); setMode('none'); }}>
                    <Check size={14} />确认批准 ¥{fmt(amt)}
                  </button>
                </div>
              )}
              {mode === 'skip' && (
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <input value={reason} onChange={e => setReason(e.target.value)} className="input" placeholder="跳过原因" style={{ flex: 1 }} />
                  <button className="btn btn-primary" onClick={(e) => { e.stopPropagation(); onDecision('SKIPPED', undefined, reason); setMode('none'); }}>
                    确认跳过
                  </button>
                </div>
              )}
              {mode === 'defer' && (
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <input value={reason} onChange={e => setReason(e.target.value)} className="input" placeholder="延期原因" style={{ flex: 1 }} />
                  <button className="btn btn-primary" onClick={(e) => { e.stopPropagation(); onDecision('DEFERRED', undefined, reason || '延期'); setMode('none'); }}>
                    确认延期
                  </button>
                </div>
              )}
            </div>
          )}
          {frozen && !canDecide && <div style={{ color: 'var(--text-dim)', fontSize: 12 }}>此项当前不可批准</div>}
        </div>
      )}
    </div>
  );
}

/* ── Blocked Row ── */
function BlockedAssetRow({ item }: { item: WeeklyPlanItem }) {
  return (
    <div className="asset-item" style={{ opacity: 0.7, cursor: 'default', marginBottom: 2 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span className="name">{item.asset_name || item.asset_code}</span>
            <span className="code">{item.asset_code}</span>
            <span className="role-tag">{ROLE_LABEL[item.asset_role] || item.asset_role}</span>
          </div>
          <div style={{ fontSize: 12, color: 'var(--danger)', marginTop: 2 }}>
            {STATUS_LABEL[item.data_quality_status] || item.data_quality_status} — {item.reason_summary || '未生成投资金额'}
          </div>
        </div>
        <span style={{ fontSize: 18, fontFamily: 'var(--font-mono)', fontWeight: 700, color: 'var(--text-dim)' }}>¥—</span>
      </div>
    </div>
  );
}

/* ── Helpers ── */
function EvidenceField({ label, value }: { label: string; value: any }) {
  return (
    <div className="data-box">
      <span className="global-label">{label}</span>
      <span style={{ fontSize: 13, fontFamily: 'var(--font-mono)', color: 'var(--text-main)' }}>{value ?? '—'}</span>
    </div>
  );
}

function StatusDot({ color }: { color: string }) {
  return <span style={{ display: 'inline-block', width: 6, height: 6, borderRadius: '50%', background: color }} />;
}

function DiagnosticsView() {
  return (
    <div className="card" style={{ padding: 24, maxWidth: 600 }}>
      <h3 style={{ color: 'var(--warning)', fontSize: 14, margin: '0 0 8px' }}>旧版诊断</h3>
      <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>
        旧版"今日操作计划"（/api/decision/today）已降级为只读诊断。
        当前正式产品入口为 v2.1 WeeklyInvestmentPlan。
      </p>
      <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>POST /api/transactions 已禁用 (HTTP 410)。</p>
    </div>
  );
}

export default App;
