import { useEffect, useState } from 'react';
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Line, PieChart, Pie, Cell } from 'recharts';
import { 
  TrendingUp, Plus, Wallet, Activity, 
  BarChart3, 
  PieChart as PieChartIcon, FileText, Zap, Layers, AlertCircle, Loader2,
  Trash2, DollarSign, Target, Percent, Settings
} from 'lucide-react';
import './App.css';

interface Asset { id: number; code: string; name: string; }
interface AdviceData { fund_code: string; name: string; current_price: number; ma200: number; action: string; suggested_amount: number; reason: string; history: any[]; grid_pos?: number; vol_daily?: number; }
interface PortfolioData { asset_code: string; total_units: number; total_cost: number; }

// 颜色盘 (用于饼图)
const COLORS = ['#6366f1', '#8b5cf6', '#ec4899', '#f43f5e', '#f59e0b', '#10b981', '#06b6d4', '#3b82f6'];

function App() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [selectedAsset, setSelectedAsset] = useState<Asset | null>(null);
  const [advice, setAdvice] = useState<AdviceData | null>(null);
  const [portfolio, setPortfolio] = useState<PortfolioData | null>(null);
  const [report, setReport] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const [poolState, setPoolState] = useState({ pool_balance: 0, base_investment: 200 });
  const [industryData, setIndustryData] = useState<any[]>([]); 
  const [fundAllocData, setFundAllocData] = useState<{name:string, value:number}[]>([]);
  const [framework, setFramework] = useState<any>(null);

  // Fetch strategy framework on advice load
  useEffect(() => {
    if (!selectedAsset) return;
    fetch(`http://127.0.0.1:9600/api/strategy/framework/${selectedAsset.code}`)
      .then(r => r.json()).then(setFramework).catch(() => {});
  }, [selectedAsset]);

  const [showAddForm, setShowAddForm] = useState(false);
  const [showTransForm, setShowTransForm] = useState(false);
  const [newCode, setNewCode] = useState("");
  const [newName, setNewName] = useState("");
  const [transPrice, setTransPrice] = useState("");
  const [transAmount, setTransAmount] = useState("200");
  const [transType, setTransType] = useState("BUY");
  const [inputMode, setInputMode] = useState<"amount" | "shares">("amount");
  const [transShares, setTransShares] = useState("");
  const [fromPool, setFromPool] = useState(true);

  const [showSuggestions, setShowSuggestions] = useState(false);
  const [suggestions, setSuggestions] = useState<any[]>([]);
  const [dailyDecisions, setDailyDecisions] = useState<any[]>([]);
  const [showDailyPlan, setShowDailyPlan] = useState(false);
  const [dailyLoading, setDailyLoading] = useState(false);
  const [dailyError, setDailyError] = useState<any>(null);
  const [dailyDebug, setDailyDebug] = useState<any>(null);

  const apiUrl = (path: string) => `/api${path}`;

  async function fetchJson(url: string, options?: RequestInit) {
    const res = await fetch(url, options);
    const text = await res.text();
    let data: any = null;
    try { data = text ? JSON.parse(text) : null; } catch { data = { raw: text }; }
    if (!res.ok) throw { status: res.status, url, data, message: data?.reason || data?.message || `HTTP ${res.status}` };
    return { ok: res.ok, data };
  }

  function normalizeToday(data: any) {
    const items = Array.isArray(data) ? data : Array.isArray(data?.items) ? data.items : Array.isArray(data?.results) ? data.results : [];
    const summary = data?.summary || { need_action: 0, observe: 0, blocked: 0, total_final_amount: 0 };
    return { items, summary };
  }

  const fetchDailyDecisions = () => {
    fetchJson(apiUrl('/decision/today'))
      .then(r => { const { items } = normalizeToday(r.data); setDailyDecisions(items); })
      .catch(() => setDailyDecisions([]));
  };

  const handleOpenDailyPlan = () => { fetchDailyDecisions(); setShowDailyPlan(true); setDailyError(null); };

  const handleGenerateToday = async () => {
    setDailyLoading(true); setDailyError(null);
    setDailyDebug({ lastAction: 'run-daily', stage: 'clicked' });
    try {
      const run = await fetchJson(apiUrl('/decision/run-daily'), { method: 'POST' });
      setDailyDebug((p:any) => ({...p, stage: 'run-ok', runData: run.data }));
      if (!run.data?.ok) throw { message: run.data?.reason || 'run-daily returned ok=false', data: run.data };
      const today = await fetchJson(apiUrl('/decision/today'));
      const { items } = normalizeToday(today.data);
      setDailyDebug((p:any) => ({...p, stage: 'today-ok', itemCount: items.length }));
      if (items.length === 0) throw { message: 'run-daily成功但today返回0条' };
      setDailyDecisions(items);
    } catch (e: any) {
      setDailyError(e.message || '生成失败');
      setDailyDebug((p:any) => ({...p, stage: 'error', error: e }));
    } finally { setDailyLoading(false); }
  };

  const handleGenerateDemo = async () => {
    setDailyLoading(true); setDailyError(null);
    setDailyDebug({ lastAction: 'run-demo', stage: 'clicked' });
    try {
      const run = await fetchJson(apiUrl('/decision/run-exposure-demo'), { method: 'POST' });
      setDailyDebug((p:any) => ({...p, stage: 'run-ok', runData: run.data }));
      if (!run.data?.ok) throw { message: run.data?.reason || 'demo failed', data: run.data };
      const today = await fetchJson(apiUrl('/decision/today'));
      const { items } = normalizeToday(today.data);
      setDailyDebug((p:any) => ({...p, stage: 'today-ok', itemCount: items.length }));
      if (!items.some((i:any) => i.decision_source === 'exposure_demo')) throw { message: 'today中没有exposure_demo数据' };
      setDailyDecisions(items);
    } catch (e: any) {
      setDailyError(e.message || 'Demo失败');
      setDailyDebug((p:any) => ({...p, stage: 'error', error: e }));
    } finally { setDailyLoading(false); }
  };

  const handleUserAction = (id: number, action: string, amount?: number, reason?: string) => {
    fetch(`http://127.0.0.1:9600/api/decision/${id}/user-action`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({action, actual_amount: amount, skip_reason: reason || ''}),
    }).then(() => fetchDailyDecisions());
  };
  const [showHistory, setShowHistory] = useState(false);
  const [transactions, setTransactions] = useState<any[]>([]);
  
  const [showDeposit, setShowDeposit] = useState(false);
  const [depositAmount, setDepositAmount] = useState("");
  const [showConfig, setShowConfig] = useState(false);
  const [newBase, setNewBase] = useState("");
  const [newBalance, setNewBalance] = useState("");

  useEffect(() => { 
    fetchAssets(); 
    fetchPool();
    fetchIndustryAnalysis();
  }, []);

  useEffect(() => {
    if (assets.length > 0) {
      calculateFundAllocation();
    }
  }, [assets]);

  const fetchAssets = () => { fetch('http://127.0.0.1:9600/api/assets').then(res => res.json()).then(setAssets); };
  const fetchPool = () => {
    fetch('http://127.0.0.1:9600/api/pool').then(res=>res.json()).then(data => {
      setPoolState(data);
      setNewBase(String(data.base_investment));
      setNewBalance(String(data.pool_balance));
    });
  };
  const fetchIndustryAnalysis = () => {
    fetch('http://127.0.0.1:9600/api/analysis/industry')
      .then(res => res.json())
      .then(setIndustryData)
      .catch(err => console.error("Industry fetch failed", err));
  };
  
  const calculateFundAllocation = async () => {
    const promises = assets.map(async (asset) => {
      const portRes = await fetch(`http://127.0.0.1:9600/api/portfolio/${asset.code}`);
      const portData = await portRes.json();
      const adviceRes = await fetch(`http://127.0.0.1:9600/api/advice/${asset.code}`);
      const adviceData = await adviceRes.json();
      
      if (adviceData.action !== "ERROR" && portData.total_units > 0) {
        return {
          name: asset.name,
          value: portData.total_units * adviceData.current_price
        };
      }
      return null;
    });

    const results = await Promise.all(promises);
    const validData = results.filter((item: any) => item !== null && item.value > 10);
    validData.sort((a:any, b:any) => b.value - a.value);
    setFundAllocData(validData);
  };

  const getSystemStatus = () => {
    if (!advice) return "API_ERROR";
    if (advice.action === "ERROR") return "API_ERROR";
    const src = advice.source || "";
    if (src.toLowerCase() === "mock") return "BLOCKED";
    if (advice.action_allowed === false) return "BLOCKED";
    if (advice.risk_guard_errors && advice.risk_guard_errors.length > 0) return "ANOMALY";
    return "PASS";
  };

  const getStrategyAction = () => {
    if (!advice || getSystemStatus() === "BLOCKED") return "review_required";
    const grid = advice.grid_pos || 0;
    if (grid > 1) return "take_profit_watch";
    if (grid < -2) return "dynamic_dca";
    if (advice.suggested_amount === 0) return "observe";
    if (advice.suggested_amount < advice.pool_balance * 0.5) return "fixed_dca";
    return "dynamic_dca";
  };

  const getAmountPermission = () => {
    if (!advice || getSystemStatus() === "BLOCKED") return "hide_amount";
    if (advice.action_allowed === true && advice.recommended_amount != null) return "show_recommended_amount";
    return "audit_only";
  };

  const strategyLabels: Record<string, string> = {
    fixed_dca: "固定定投", dynamic_dca: "动态定投", observe: "观察 / 暂停新增",
    stop_dynamic: "暂停动态部分", take_profit_watch: "止盈观察", review_required: "需人工复核"
  };
  const fetchReport = (code: string) => { fetch(`http://127.0.0.1:9600/api/strategy/report/${code}`).then(res => res.json()).then(data => setReport(data.report)); };
  const fetchTransactions = (code: string) => { fetch(`http://127.0.0.1:9600/api/transactions/${code}`).then(res => res.json()).then(setTransactions); };

  const handleSelectAsset = (asset: Asset) => {
    setSelectedAsset(asset); setLoading(true); setErrorMsg(null); setAdvice(null); setPortfolio(null); setReport(""); setShowTransForm(false); setShowHistory(false);
    Promise.all([
      fetch(`http://127.0.0.1:9600/api/advice/${asset.code}`).then(res => res.json()),
      fetch(`http://127.0.0.1:9600/api/portfolio/${asset.code}`).then(res => res.json())
    ]).then(([adviceData, portfolioData]) => {
      if (adviceData.action === "ERROR") throw new Error(adviceData.reason);
      setAdvice(adviceData); setPortfolio(portfolioData); setTransPrice(String(adviceData.current_price)); fetchReport(asset.code);
    }).catch(err => { setErrorMsg(err.message); }).finally(() => setLoading(false));
  };

  const handleRunAll = () => {
    if (poolState.pool_balance < 100) { if(!confirm(`⚠️ 资金池仅剩 ¥${poolState.pool_balance}，可能不足以执行建议。\n是否继续？`)) return; }
    setLoading(true);
    fetch('http://127.0.0.1:9600/api/plan/run', { method: 'POST' })
      .then(res => res.json())
      .then(data => {
        setSuggestions(data.suggestions || []); 
        setShowSuggestions(true); 
        fetchPool(); fetchIndustryAnalysis(); calculateFundAllocation();
        setLoading(false);
      })
      .catch(() => { alert("执行失败"); setLoading(false); });
  };

  const handleDeposit = () => { fetch('http://127.0.0.1:9600/api/pool/deposit', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ amount: depositAmount }) }).then(() => { alert(`充值成功`); setShowDeposit(false); fetchPool(); }); };
  const handleUpdateConfig = () => { fetch('http://127.0.0.1:9600/api/pool/config', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ base_investment: newBase, pool_balance: newBalance }) }).then(() => { alert("配置已更新"); setShowConfig(false); fetchPool(); }); };
  const handleAddAsset = () => { if (!newCode || !newName) return; fetch('http://127.0.0.1:9600/api/assets', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code: newCode, name: newName }) }).then(res => res.json()).then(data => { if(data.id) { fetchAssets(); setShowAddForm(false); setNewCode(""); setNewName(""); } }); };
  const handleDetectFund = (code: string) => {
    if (!code || code.length < 4) return;
    fetch('http://127.0.0.1:9600/api/fund/detect/' + code)
      .then(res => res.json())
      .then(data => { if (data.name && data.name !== '基金' + code) setNewName(data.name); });
  };
  const handleDeleteAsset = (e: React.MouseEvent, id: number) => { e.stopPropagation(); if (confirm("确定删除此基金吗？")) fetch(`http://127.0.0.1:9600/api/assets/${id}`, { method: 'DELETE' }).then(fetchAssets); };
  const handleDeleteTransaction = (txId: number) => { if (!confirm("确定删除这条交易记录？")) return; fetch(`http://127.0.0.1:9600/api/transactions/${txId}`, { method: 'DELETE' }).then(() => { if (selectedAsset) { fetchTransactions(selectedAsset.code); handleSelectAsset(selectedAsset); fetchPool(); fetchIndustryAnalysis(); calculateFundAllocation(); } }); };

  const handleTransaction = () => {
    if (!selectedAsset) return;
    let finalAmount = parseFloat(transAmount);
    const price = parseFloat(transPrice);
    if (inputMode === 'shares') finalAmount = parseFloat(transShares) * price;
    fetch('http://127.0.0.1:9600/api/transactions', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ asset_code: selectedAsset.code, type: transType, price: price, amount: finalAmount, fee: inputMode==='shares'?0:0, from_pool: fromPool })
    }).then(res => res.json()).then(data => { 
      if(data.id) { setShowTransForm(false); handleSelectAsset(selectedAsset); fetchPool(); fetchIndustryAnalysis(); calculateFundAllocation(); if (showHistory) fetchTransactions(selectedAsset.code); } 
    });
  };

  const { profit, rate, marketValue } = (() => {
    if (!advice || !portfolio) return { profit: 0, rate: 0, marketValue: 0 };
    const mv = portfolio.total_units * advice.current_price;
    const pf = mv - portfolio.total_cost;
    const rt = portfolio.total_cost > 0 ? (pf / portfolio.total_cost) * 100 : 0;
    return { profit: pf, rate: rt, marketValue: mv };
  })();

  const fmtMoney = (n: number) => new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY', maximumFractionDigits: 0 }).format(n);

  return (
    <div className="app-container">
      {showDailyPlan && (Array.isArray(dailyDecisions) ? (
        <div style={{position:'fixed', top:0, left:0, right:0, bottom:0, background:'rgba(0,0,0,0.85)', backdropFilter:'blur(4px)', display:'flex', alignItems:'center', justifyContent:'center', zIndex:1000}}>
          <div style={{background:'#18181b', border:'1px solid #333', borderRadius:16, width:640, maxHeight:'90vh', overflow:'auto', padding:28, boxShadow:'0 25px 50px -12px rgba(0,0,0,0.5)'}}>
            <div style={{display:'flex', justifyContent:'space-between', marginBottom:16}}>
              <div><h3 style={{margin:0, fontSize:20}}>📋 今日操作计划</h3><div style={{fontSize:12, color:'#71717a', marginTop:4}}>由系统自动分析生成，仅供人工复核，不会自动交易。</div></div>
              <button onClick={()=>setShowDailyPlan(false)} style={{background:'none', border:'none', color:'#666', cursor:'pointer', fontSize:20}}>✕</button>
            </div>
            {dailyDecisions.length > 0 && (() => {
              const candidateTotal = dailyDecisions.reduce((s,d)=>s+(d.candidate_amount||0),0);
              const finalTotal = dailyDecisions.filter(d=>['fixed_dca','dynamic_dca'].includes(d.strategy_action)).reduce((s,d)=>s+(d.recommended_amount||0),0);
              const downgraded = dailyDecisions.filter(d=>d.downgrade_reason);
              const cap = 600;
              const allObserve = dailyDecisions.length > 0 && dailyDecisions.every(d=>d.strategy_action==='observe');
              return (
                <div style={{background:'rgba(99,102,241,0.08)', borderRadius:10, padding:12, marginBottom:16, border:'1px solid rgba(99,102,241,0.15)'}}>
                  <div style={{fontSize:12, fontWeight:600, color:'#a5b4fc', marginBottom:8}}>🔍 暴露闸门审计</div>
                  {dailyDecisions[0]?.decision_source==='exposure_demo' && <div style={{fontSize:10,color:'#f59e0b',marginBottom:8,padding:'4px 8px',background:'rgba(245,158,11,0.1)',borderRadius:4}}>⚠️ 演示数据，仅用于验证暴露闸门，不作为真实操作计划。</div>}
                  <div style={{display:'flex', gap:16, flexWrap:'wrap', fontSize:12}}>
                    <span>原始候选: <b style={{color:'#f59e0b'}}>¥{candidateTotal}</b></span>
                    <span>最终建议: <b style={{color:'#10b981'}}>¥{finalTotal}</b></span>
                    <span>组合上限: ¥{cap}</span>
                    {downgraded.length>0 && <span style={{color:'#f97316'}}>降级: {downgraded.length}只</span>}
                  </div>
                  {finalTotal < candidateTotal && <div style={{fontSize:10, color:'#71717a', marginTop:6}}>最终建议低于原始候选，原因：{(():string=>{
                    const reasons: string[] = [];
                    if (downgraded.some((d:any)=>d.downgrade_reason?.includes('同主题'))) reasons.push('同主题重复暴露');
                    if (dailyDecisions.some((d:any)=>d.valuation_state==='unknown')) reasons.push('估值层未接入');
                    if (dailyDecisions.some((d:any)=>d.risk_reasons?.includes('Mock'))) reasons.push('Mock数据');
                    if (!reasons.length) reasons.push('风控观察');
                    return reasons.join(' / ');
                  })()}</div>}
                  {allObserve && finalTotal===0 && (()=>{
                    const reasons:Record<string,number>={};
                    dailyDecisions.forEach(d=>{
                      if(d.downgrade_reason?.includes('同主题')) reasons['同主题重复暴露']=(reasons['同主题重复暴露']||0)+1;
                      else if(d.downgrade_reason) reasons[d.downgrade_reason]=(reasons[d.downgrade_reason]||0)+1;
                      else if(d.reason_summary?.includes('估值层')) reasons['估值层未接入']=(reasons['估值层未接入']||0)+1;
                      else if(d.risk_reasons?.includes('Mock')) reasons['Mock数据']=(reasons['Mock数据']||0)+1;
                      else reasons['风控观察']=(reasons['风控观察']||0)+1;
                    });
                    return <div style={{fontSize:11,color:'#a5b4fc',marginTop:8}}>
                      今日无可执行项（{dailyDecisions.length}只）：{Object.entries(reasons).map(([k,v])=><span key={k}> {v}只因{k}</span>)}。最终建议金额 ¥0。
                    </div>;
                  })()}
                </div>
              );
            );\n            })()}
            {dailyError && <div style={{background:'rgba(239,68,68,0.08)', padding:12, borderRadius:8, marginBottom:16, border:'1px solid rgba(239,68,68,0.2)'}}><div style={{fontSize:12,color:'#ef4444',marginBottom:4}}>生成失败</div><div style={{fontSize:11,color:'#fca5a5'}}>{dailyError}</div></div>}
            {dailyDebug && <details style={{marginBottom:16, fontSize:10, color:'#6b7280'}}><summary>Debug</summary><pre>{JSON.stringify(dailyDebug,null,2)}</pre></details>}
            {dailyDecisions.length===0 ? (
              <div style={{textAlign:'center', padding:30}}>
                <div style={{color:'#71717a', marginBottom:16}}>今日操作计划尚未生成</div>
                <div style={{fontSize:11, color:'#52525b', marginBottom:16, textAlign:'left', display:'inline-block'}}>
                  可能原因：<br/>1. Scheduler 今天还没有运行<br/>2. 代理指数数据尚未ready<br/>3. 后端 API 未连接<br/>4. 今日计划生成失败
                </div>
                <button type="button" onClick={handleGenerateToday} disabled={dailyLoading} className="btn btn-primary" style={{padding:'10px 24px'}}>{dailyLoading ? '生成中...' : '生成今日计划'}</button>
                                <button type="button" onClick={handleGenerateDemo} disabled={dailyLoading} className="btn btn-secondary" style={{padding:'10px 24px', marginTop:8}}>{dailyLoading ? '...' : '生成 Demo 计划'}</button>
              </div>
            ) : (
              (() => {
                const act = dailyDecisions.filter(d => ['fixed_dca','dynamic_dca','buy'].includes(d.strategy_action) && d.system_status==='PASS');
                const obs = dailyDecisions.filter(d => ['observe','stop_dynamic','take_profit_watch'].includes(d.strategy_action));
                const blk = dailyDecisions.filter(d => d.system_status==='BLOCKED'||d.system_status==='ANOMALY'||d.system_status==='API_ERROR');
                const noa = dailyDecisions.filter(d => ![...act,...obs,...blk].includes(d));
                return (<>
                  <div style={{display:'flex', gap:10, marginBottom:20, flexWrap:'wrap'}}>
                    {[{l:'需处理',n:act.length,c:'#10b981'},{l:'观察',n:obs.length,c:'#f59e0b'},{l:'BLOCKED',n:blk.length,c:'#ef4444'},{l:'无需操作',n:noa.length,c:'#6b7280'}].map(s=>(<div key={s.l} style={{flex:1,minWidth:70,textAlign:'center',padding:10,background:'#27272a',borderRadius:8}}><div style={{fontSize:20,fontWeight:700,color:s.c}}>{s.n}</div><div style={{fontSize:11,color:'#71717a'}}>{s.l}</div></div>))}
                    <div style={{flex:1,minWidth:90,textAlign:'center',padding:10,background:'#27272a',borderRadius:8}}><div style={{fontSize:20,fontWeight:700,color:'var(--primary)'}}>¥{act.reduce((s,d)=>s+(d.recommended_amount||0),0)}</div><div style={{fontSize:11,color:'#71717a'}}>建议总额</div></div>
                  </div>
                  {act.length>0 && (<><div style={{fontSize:13,fontWeight:600,color:'#10b981',marginBottom:8}}>需要处理</div>
                    {act.map(d=>(<div key={d.id} style={{display:'flex',justifyContent:'space-between',alignItems:'center',padding:12,marginBottom:8,background:'rgba(16,185,129,0.06)',borderRadius:10,border:'1px solid rgba(16,185,129,0.15)'}}>
                      <div><div style={{fontWeight:600}}>{d.fund_name} ({d.fund_code})</div><div style={{fontSize:12,color:'#71717a'}}>{d.reason_summary}</div></div>
                      <div style={{display:'flex',alignItems:'center',gap:12}}><span style={{fontWeight:700,color:'#10b981'}}>¥{d.recommended_amount||0}</span>
                        <button onClick={()=>handleUserAction(d.id,'executed',d.recommended_amount)} className="btn" style={{fontSize:11,padding:'4px 8px',background:'#10b98120',color:'#10b981',border:'1px solid #10b98150',borderRadius:6}}>已完成</button>
                        <button onClick={()=>{const r=prompt('跳过原因');if(r)handleUserAction(d.id,'skipped',undefined,r)}} className="btn" style={{fontSize:11,padding:'4px 8px',background:'#f59e0b20',color:'#f59e0b',border:'1px solid #f59e0b50',borderRadius:6}}>跳过</button>
                      </div></div>))}</>)}
                  {obs.length>0 && (<><div style={{fontSize:13,fontWeight:600,color:'#f59e0b',marginBottom:8,marginTop:16}}>观察项</div>
                    {obs.map(d=>{
                      const reasonLabel = (()=>{
                        if(d.downgrade_reason) return d.downgrade_reason;
                        if(d.risk_reasons?.includes('Mock')) return 'Mock数据，禁止输出金额';
                        if(d.valuation_state==='unknown'||!d.signal_ready) return '估值层未接入，当前仅观察';
                        return d.reason_summary||'观察中';
                      })();
                      const cs = d.classification_source||'local_rule';
                      const cf = d.classification_confidence||'medium';
                      const candAmt = d.candidate_amount;
                      const finAmt = d.recommended_amount;
                      return (<div key={d.id} style={{padding:12,marginBottom:8,background:'rgba(245,158,11,0.04)',borderRadius:10,border:'1px solid rgba(245,158,11,0.1)'}}>
                        <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start'}}>
                          <div style={{flex:1}}>
                            <div style={{fontWeight:600}}>{d.fund_name} ({d.fund_code})</div>
                            {candAmt != null && <div style={{fontSize:11,color:'#71717a',marginTop:4}}>
                              原始信号：{d.candidate_action||d.strategy_action} ¥{candAmt}
                              → 最终动作：{d.strategy_action} {finAmt===0?'¥0':(finAmt!=null?'¥'+finAmt:'不输出')}
                            </div>}
                            <div style={{fontSize:11,color:'#f59e0b',marginTop:4}}>{reasonLabel}</div>
                            {d.overlap_status && d.overlap_status!=='N/A' && <div style={{fontSize:10,color:'#6b7280',marginTop:4}}>
                              {d.overlap_status==='DATA_MISSING'
                                ? '持仓数据缺失，无法判断真实重叠，当前仅观察。'
                                : `Top10重叠:${(d.overlap_score*100).toFixed(0)}% | 行业重叠:${(d.overlap_industry*100).toFixed(0)}% | ${d.overlap_status}`
                              }
                              {d.is_fixture && ' ⚠️规则推断/示例数据，不进入实盘建议'}
                              {d.holding_date && <span> · 持仓日期:{d.holding_date?.slice(0,10)||'未知'}</span>}
                              {d.stale_days>120 && <span> · ⚠️过期{d.stale_days}天</span>}
                            </div>}
                            <div style={{fontSize:10,color:'#52525b',marginTop:2}}>
                              来源：{cs||'未返回'}，置信度：{cf||'未知'}
                              {cs==='local_rule'&&cf==='medium'?' ⚠️规则推断，后续需持仓穿透验证':''}
                              {(d.theme_bucket&&d.theme_bucket!=='未分类')?` · 主题:${d.theme_bucket}`:' · 主题:规则推断/待持仓穿透确认'}
                            </div>
                          </div>
                          <div style={{display:'flex',alignItems:'center',gap:8,marginLeft:12}}>
                            <span style={{color:'#71717a',fontSize:13}}>{finAmt===0?'¥0 不新增':'不新增'}</span>
                            <button onClick={()=>handleUserAction(d.id,'acknowledged')} className="btn" style={{fontSize:11,padding:'4px 8px',background:'#f59e0b20',color:'#f59e0b',border:'1px solid #f59e0b50',borderRadius:6}}>已观察</button>
                          </div>
                        </div>
                      </div>);
                    })}</>)}
                  {blk.length>0 && (<><div style={{fontSize:13,fontWeight:600,color:'#ef4444',marginBottom:8,marginTop:16}}>⛔ BLOCKED</div>
                    {blk.map(d=>(<div key={d.id} style={{padding:12,marginBottom:8,background:'rgba(239,68,68,0.04)',borderRadius:10,border:'1px solid rgba(239,68,68,0.15)'}}>
                      <div style={{fontWeight:600,color:'#ef4444'}}>{d.fund_name} ({d.fund_code})</div>
                      <div style={{fontSize:12,color:'#ef4444',marginTop:4}}>不输出金额</div>
                      {d.risk_reasons && <div style={{fontSize:11,color:'#71717a',marginTop:4}}>原因: {d.risk_reasons}</div>}
                    </div>))}</>)}
                  {noa.length>0 && <details style={{marginTop:16,color:'#6b7280'}}><summary style={{fontSize:13,cursor:'pointer'}}>无需操作 ({noa.length}) — 系统状态已PASS，无买入信号</summary>
                    {noa.map(d=>(<div key={d.id} style={{padding:8,fontSize:12}}>{d.fund_name} — {d.system_status}</div>))}</details>}
                </>);
              })()
            )}
            <div style={{fontSize:11,color:'#52525b',background:'#27272a',padding:12,borderRadius:8,marginTop:16,lineHeight:1.6}}>
              1. 本计划仅供人工复核，不会自动交易。<br/>2. 若已在平台完成买入，请点击对应基金的「已完成」。<br/>3. 若选择不执行，请点击「跳过」并记录原因。<br/>4. BLOCKED 项不得交易，需先查看阻断原因。
            </div>
            <button onClick={()=>setShowDailyPlan(false)} className="btn btn-secondary" style={{width:'100%', marginTop:12, height:40}}>关闭</button>
          </div>
        </div>
      ) : null)}

      <div className="sidebar">
        <div className="brand"><div style={{width:20, height:20, background:'var(--primary)', borderRadius:4}}></div>RevvInvest</div>
        <div className="global-dashboard" style={{position: 'relative'}}>
          <button className="btn-icon" style={{position: 'absolute', top: 10, right: 10}} onClick={() => setShowConfig(!showConfig)}><Settings size={14} /></button>
          <div><div className="global-label">Investable Pool</div><div className="global-value" style={{color: poolState.pool_balance < 100 ? '#ef4444' : '#fff'}}>¥ {Number(poolState.pool_balance).toFixed(0)}</div></div>
          <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginTop:5}}><div className="global-sub">基准: ¥{poolState.base_investment}/次</div></div>
          <div style={{display: 'flex', gap: 8, marginTop: 15}}><button onClick={() => setShowDeposit(!showDeposit)} className="btn btn-secondary" style={{flex:1, justifyContent:'center'}}>+ 充值</button><button onClick={handleOpenDailyPlan} className="btn btn-primary" style={{flex:1, justifyContent:'center'}}>今日计划</button></div>
          {showDeposit && (<div style={{marginTop: 10, paddingTop: 10, borderTop: '1px solid rgba(255,255,255,0.1)'}}><input className="input-dark" placeholder="金额" value={depositAmount} onChange={e => setDepositAmount(e.target.value)} style={{marginBottom: 5}} /><button onClick={handleDeposit} className="btn btn-primary" style={{width: '100%', fontSize: 12, padding: 6}}>确认充值</button></div>)}
          {showConfig && (<div style={{marginTop: 10, paddingTop: 10, borderTop: '1px solid rgba(255,255,255,0.1)'}}><div style={{fontSize: 11, color: '#aaa', marginBottom: 4}}>校准余额:</div><input className="input-dark" value={newBalance} onChange={e => setNewBalance(e.target.value)} type="number" style={{marginBottom: 5}} /><div style={{fontSize: 11, color: '#aaa', marginBottom: 4}}>每份基准:</div><input className="input-dark" value={newBase} onChange={e => setNewBase(e.target.value)} type="number" style={{marginBottom: 5}} /><button onClick={handleUpdateConfig} className="btn btn-secondary" style={{width: '100%', fontSize: 12, padding: 6}}>保存</button></div>)}
        </div>
        <div className="section-header"><span>Watchlist</span><button className="btn-icon" onClick={() => setShowAddForm(!showAddForm)}><Plus size={14} /></button></div>
        {showAddForm && (<div style={{padding:12, background:'var(--bg-panel)', borderRadius:12, marginBottom:10, border:'1px solid var(--border-active)'}}><input className="input-dark" style={{marginBottom:8}} placeholder="代码" value={newCode} onChange={e=>setNewCode(e.target.value)} onBlur={e=>handleDetectFund(e.target.value)} /><input className="input-dark" style={{marginBottom:8}} placeholder="名称（自动识别）" value={newName} onChange={e=>setNewName(e.target.value)} /><button className="btn btn-primary" style={{width:'100%', justifyContent:'center'}} onClick={handleAddAsset}>确认</button></div>)}
        <div className="asset-list">{[...new Map(assets.map(a => [a.code, a])).values()].map(asset => (<div key={asset.code} className={`asset-item ${selectedAsset?.code === asset.code ? 'active' : ''}`} onClick={() => handleSelectAsset(asset)}><div><div className="name">{asset.name}</div><div className="code">{asset.code}</div></div><button className="btn-icon" onClick={(e) => handleDeleteAsset(e, asset.id)}><Trash2 size={14}/></button></div>))}</div>
        <div className="section-header"><span>Runtime Status</span></div>
        <div style={{padding:10, background:'var(--bg-panel)', borderRadius:10, marginBottom:16, fontSize:12}}>
          <div style={{display:'flex', justifyContent:'space-between', padding:'4px 0'}}><span style={{color:'var(--text-dim)'}}>Backend</span><span style={{color:'#10b981'}}>✅ READY</span></div>
          <div style={{display:'flex', justifyContent:'space-between', padding:'4px 0'}}><span style={{color:'var(--text-dim)'}}>Frontend</span><span style={{color:'#10b981'}}>✅ READY</span></div>
          <div style={{display:'flex', justifyContent:'space-between', padding:'4px 0'}}><span style={{color:'var(--text-dim)'}}>Scheduler</span><span style={{color:dailyDecisions.length>0?'#10b981':'#f59e0b'}}>{dailyDecisions.length>0?'✅ READY':'⏳ WAITING'}</span></div>
          <div style={{display:'flex', justifyContent:'space-between', padding:'4px 0'}}><span style={{color:'var(--text-dim)'}}>Today</span><span style={{color:framework?'#10b981':'#71717a'}}>{framework?'📋 generated':'not_generated'}</span></div>
        </div>
      </div>

      <div className="main-content">
        {!selectedAsset ? (
          <div className="empty-state"><Layers size={64} strokeWidth={1.5} color="#333"/><div style={{color:'var(--text-muted)', marginTop:24, fontSize:18, fontWeight:500}}>请选择一个资产查看详情</div></div>
        ) : loading ? (
          <div className="empty-state" style={{border:'none'}}><Loader2 className="spin" size={48} color="var(--primary)"/><p style={{marginTop:24, color:'var(--text-muted)'}}>正在分析市场数据...</p></div>
        ) : errorMsg ? (
          <div className="empty-state" style={{borderColor:'var(--danger)', color:'var(--danger)'}}><AlertCircle size={48} /><h3 style={{marginTop:20}}>数据获取失败</h3><p style={{fontSize:14, opacity:0.8}}>{errorMsg}</p><button className="btn btn-outline" style={{marginTop:20}} onClick={()=>handleSelectAsset(selectedAsset)}>重试</button></div>
        ) : advice && (
          <div className="dashboard-grid">
            
            <div className="card price-card">
              <div className="card-header"><div className="card-title"><Activity size={18}/> 实时行情</div><div className={`tag ${advice.current_price>advice.ma200?'tag-red':'tag-green'}`}>{advice.current_price>advice.ma200?'高于年线':'低于年线'}</div></div>
              <div><div className="big-number">{advice.current_price}</div><div style={{display:'flex', alignItems:'center', gap:12, marginTop:8, fontSize:13, color:'var(--text-muted)'}}><span>MA200: {advice.ma200.toFixed(4)}</span><span style={{color:'var(--text-dim)'}}>|</span><span>波动率: {advice.vol_daily ? (advice.vol_daily*100).toFixed(2) : '0.00'}%</span></div></div>
            </div>

            <div className="card signal-card">
              <div className="card-header"><div className="card-title"><Zap size={18}/> 今日决策</div></div>
              {(() => {
                const ss = getSystemStatus();
                const sa = getStrategyAction();
                const ap = getAmountPermission();
                const labels: Record<string, {icon: string, color: string}> = {PASS: {icon:'✅', color:'#10b981'}, BLOCKED: {icon:'⛔', color:'#ef4444'}, WAITING: {icon:'⏳', color:'#f59e0b'}, ANOMALY: {icon:'⚠️', color:'#f97316'}, API_ERROR: {icon:'❌', color:'#ef4444'}};
                const l = labels[ss] || labels.API_ERROR;
                return (<>
                  <div style={{display:'flex', flexDirection:'column', gap:8}}>
                    <div style={{fontSize:13, color:'var(--text-dim)'}}>系统状态</div>
                    <div style={{fontSize:18, fontWeight:700, color:l.color}}>{l.icon} {ss}</div>
                    <div style={{fontSize:13, color:'var(--text-dim)', marginTop:4}}>策略动作</div>
                    <div style={{fontSize:16, fontWeight:600}}>{strategyLabels[sa] || sa}</div>
                    <div style={{fontSize:13, color:'var(--text-dim)', marginTop:4}}>建议金额</div>
                    {ap === 'show_recommended_amount' && advice.recommended_amount != null
                      ? <div style={{fontSize:22, fontFamily:'var(--font-mono)', fontWeight:700, color:'var(--primary)'}}>¥ {advice.recommended_amount} <span style={{fontSize:11, color:'var(--text-dim)', fontWeight:400}}>仅供人工复核</span></div>
                      : ap === 'audit_only'
                      ? <div style={{fontSize:14, color:'var(--text-dim)'}}>¥0（计算金额见审计详情）</div>
                      : <div style={{fontSize:14, color:'#ef4444'}}>不输出金额</div>}
                    {ss === 'BLOCKED' && <div style={{fontSize:11, color:'#ef4444', marginTop:4}}>原因: {advice.risk_guard_errors?.join('; ') || '数据异常'}</div>}
                  </div>
                </>);
              })()}
            </div>

            <div className="card strategy-card">
              <div className="card-header"><div className="card-title"><FileText size={18}/> 策略透视</div><div style={{fontSize:11, color:'var(--text-dim)', letterSpacing:1}}>VOLATILITY GRID</div></div>
              <div style={{padding:'0 10px'}}>
                <div style={{display:'flex', justifyContent:'space-between', marginBottom:24}}><div className={`tag ${(advice.grid_pos||0)<-1?'tag-green':(advice.grid_pos||0)>1?'tag-red':'tag-wait'}`}>{(advice.grid_pos||0)<-1?'低估区域':(advice.grid_pos||0)>1?'高估区域':'中性震荡'}</div><div style={{fontFamily:'var(--font-mono)', color:'var(--text-muted)', fontSize:13}}>Z-Score: <b>{(advice.grid_pos||0).toFixed(2)}</b></div></div>
                <div className="grid-thermometer" style={{background: 'linear-gradient(90deg, #10b981 0%, #1e293b 40%, #1e293b 60%, #ef4444 100%)', height:6, borderRadius:3, position:'relative', marginBottom:10}}><div style={{position:'absolute', left:'50%', width:1, height:6, background:'#52525b'}}></div><div className="grid-cursor" style={{position:'absolute', top:-6, width:4, height:18, background:'#fff', borderRadius:2, boxShadow:'0 0 10px white', left: `${Math.min(Math.max(((advice.grid_pos||0)+4)/8*100, 0), 100)}%`}}></div></div>
                <div className="data-grid" style={{marginTop:30}}><div className="data-box"><div className="data-label">网格位置</div><div className="data-value" style={{color:(advice.grid_pos||0)>0?'#f87171':'#34d399'}}>{advice.grid_pos?.toFixed(1)}</div></div><div className="data-box"><div className="data-label">策略动作</div><div className="data-value" style={{fontSize:16}}>{advice.suggested_amount>200?"激进买入":(advice.suggested_amount===0?"防守/存钱":"标准定投")}</div></div><div className="data-box" style={{gridColumn:'span 2'}}><div className="data-label">最近计划报告</div><div style={{fontSize:12, color:'var(--text-muted)', lineHeight:1.5}}>{report ? report.split('\n')[2] : "暂无最近活动记录"}</div></div></div>
              </div>
            </div>

            <div className="card portfolio-card">
              <div className="card-header"><div className="card-title"><Wallet size={18}/> 持仓管理</div><div style={{display:'flex', gap:10}}><button className="btn btn-outline" onClick={()=>{setShowHistory(!showHistory);if(!showHistory)fetchTransactions(selectedAsset.code)}}>📜 历史记录</button><button className="btn btn-glass" onClick={()=>setShowTransForm(!showTransForm)}>{showTransForm?'取消':'📝 记一笔'}</button></div></div>
              {showTransForm && (<div style={{background:'var(--bg-panel)', padding:20, borderRadius:16, marginBottom:24, border:'1px solid var(--border-active)'}}><div style={{display:'flex', gap:16, marginBottom:16, borderBottom:'1px solid var(--border-subtle)', paddingBottom:12}}><div onClick={()=>setInputMode("amount")} style={{cursor:'pointer', color:inputMode==='amount'?'var(--primary)':'var(--text-dim)', fontWeight:inputMode==='amount'?600:400}}>💰 按金额</div><div onClick={()=>setInputMode("shares")} style={{cursor:'pointer', color:inputMode==='shares'?'var(--primary)':'var(--text-dim)', fontWeight:inputMode==='shares'?600:400}}>📊 按份额</div></div><div style={{display:'flex', gap:12}}><select className="input-dark" value={transType} onChange={e=>setTransType(e.target.value)} style={{width:100}}><option value="BUY">买入</option><option value="SELL">卖出</option></select><input className="input-dark" type="number" placeholder="单价" value={transPrice} onChange={e=>setTransPrice(e.target.value)}/><input className="input-dark" type="number" placeholder={inputMode==='amount'?"金额 (¥)":"份额"} value={inputMode==='amount'?transAmount:transShares} onChange={e=>inputMode==='amount'?setTransAmount(e.target.value):setTransShares(e.target.value)}/><button className="btn btn-primary" onClick={handleTransaction}>提交</button></div>{transType==="BUY"&&(<label style={{marginTop:12, display:'flex', alignItems:'center', gap:8, fontSize:13, color:'var(--text-muted)'}}><input type="checkbox" checked={fromPool} onChange={e=>setFromPool(e.target.checked)}/> 从资金池扣款</label>)}</div>)}
              <div className="data-grid">
                <div className="data-box"><div className="data-label"><DollarSign size={14}/> 持有市值</div><div className="data-value">{fmtMoney(marketValue)}</div></div>
                <div className="data-box"><div className="data-label"><Target size={14}/> 投入本金</div><div className="data-value">{fmtMoney(portfolio?.total_cost||0)}</div></div>
                <div className="data-box"><div className="data-label"><TrendingUp size={14}/> 持有盈亏</div><div className="data-value" style={{color:profit>=0?'#ef4444':'#10b981'}}>{profit>0?'+':''}{fmtMoney(profit)}</div></div>
                <div className="data-box"><div className="data-label"><Percent size={14}/> 收益率</div><div className="data-value" style={{color:profit>=0?'#ef4444':'#10b981'}}>{rate.toFixed(2)}%</div></div>
              </div>
              {showHistory && transactions.length > 0 && (<div style={{marginTop:20, maxHeight:300, overflowY:'auto', borderTop:'1px solid var(--border-subtle)', paddingTop:20}}>{transactions.map((tx:any) => (<div key={tx.id} style={{display:'flex', justifyContent:'space-between', padding:12, background:'var(--bg-panel)', marginBottom:8, borderRadius:8, border:'1px solid var(--border-subtle)'}}><div><div style={{fontWeight:600, fontSize:14, color:tx.type==='BUY'?'#ef4444':'#10b981'}}>{tx.type==='BUY'?'买入':'卖出'}</div><div style={{fontSize:12, color:'var(--text-muted)', marginTop:4}}>{new Date(tx.date).toLocaleDateString()}</div></div><div style={{textAlign:'right'}}><div style={{fontSize:14, fontWeight:600}}>¥{tx.amount.toFixed(0)}</div><div style={{fontSize:12, color:'var(--text-muted)'}}>@{tx.price.toFixed(4)}</div></div><button className="btn-icon" onClick={()=>handleDeleteTransaction(tx.id)}><Trash2 size={14}/></button></div>))}</div>)}
            </div>

            <div style={{display:'grid', gridTemplateColumns: 'repeat(12, 1fr)', gap: 24, gridColumn: 'span 12'}}>
              {/* v0.8 Strategy Layers */}
              {framework && !framework.error && (
              <div className="card" style={{ gridColumn: 'span 12', minHeight: 180 }}>
                <div className="card-header"><div className="card-title"><Layers size={18}/> 策略分层视图</div><div style={{fontSize:11, color:'var(--text-dim)'}}>VALUE-DCA FRAMEWORK</div></div>
                <div style={{display:'flex', gap:8, flexWrap:'wrap'}}>
                  {Object.entries(framework.layers||{}).map(([key, l]:[string,any]) => {
                    const colors: Record<string,string> = {READY:'#10b981', PASS:'#10b981', BLOCKED:'#ef4444', STOP:'#f97316', REVIEW:'#f97316', triggered:'#f59e0b', waiting_trigger:'#3b82f6', unknown:'#6b7280', disabled_by_valuation:'#6b7280', normal_position:'#10b981', low_position:'#3b82f6', high_position:'#f97316'};
                    const color = colors[l.status] || '#6b7280';
                    const labels: Record<string,string> = {data:'数据', thesis:'资产', valuation:'估值', price:'价格', four_percent:'4%触发', amount:'资金', risk:'风控'};
                    return (
                      <div key={key} style={{flex:'1 1 120px', minWidth:100, background:'var(--bg-panel)', borderRadius:8, padding:10, borderLeft:`3px solid ${color}`}}>
                        <div style={{fontSize:10, color:'var(--text-dim)', marginBottom:4}}>{labels[key]||key}层</div>
                        <div style={{fontSize:13, fontWeight:600, color}}>{l.status}</div>
                        {l.reason && <div style={{fontSize:10, color:'var(--text-muted)', marginTop:2}}>{l.reason}</div>}
                        {l.blocking && <div style={{fontSize:9, color:'#ef4444', marginTop:2}}>⛔ 阻断</div>}
                      </div>
                    );
                  })}
                </div>
                {(() => {
                  const fp = framework?.layers?.four_percent;
                  const val = framework?.layers?.valuation;
                  const msgs: string[] = [];
                  if (val?.status === 'unknown') msgs.push('⚠️ 估值层尚未接入 PE/PB/股息率等基本面指标；当前不代表已完成价值估值判断。');
                  if (fp?.status === 'triggered') msgs.push('🔬 4%触发仅作为观察信号（dry_run），未进入本次建议金额。');
                  if (fp?.status && fp.status !== 'triggered') msgs.push('🔬 4%触发层为实验模块（dry_run），不影响实盘金额。');
                  if (msgs.length === 0) msgs.push('风控层决定金额展示');
                  return msgs.map((m, i) => <div key={i} style={{marginTop:8, fontSize:11, color:'var(--text-dim)'}}>{m}</div>);
                })()}
              </div>
              )}
              <div className="card" style={{ gridColumn: 'span 6', minHeight: 400 }}>
                <div className="card-header"><div className="card-title"><PieChartIcon size={18}/> 穿透行业分布</div><div style={{fontSize:11, color:'var(--text-dim)'}}>UNDERLYING ASSETS</div></div>
                <div style={{flex:1, display:'flex', flexDirection:'column', height:'100%'}}>
                  {industryData.length > 0 ? (
                    <>
                      <div style={{flex:1, minHeight: 200}}>
                        <ResponsiveContainer width="100%" height="100%">
                          <PieChart><Pie data={industryData} cx="50%" cy="50%" innerRadius={60} outerRadius={80} paddingAngle={2} dataKey="value">{industryData.map((_, index) => (<Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} stroke="var(--bg-card)" strokeWidth={2}/>))}</Pie><Tooltip contentStyle={{backgroundColor:'#18181b', border:'1px solid rgba(255,255,255,0.1)', borderRadius:8}} itemStyle={{color:'#fff'}} formatter={(val:number)=>fmtMoney(val)}/></PieChart>
                        </ResponsiveContainer>
                      </div>
                      <div style={{height: 120, overflowY:'auto', padding:'0 10px'}}>
                        {industryData.map((item, index) => (
                          <div key={index} style={{display:'flex', justifyContent:'space-between', marginBottom:8, fontSize:13}}>
                            <div style={{display:'flex', alignItems:'center', gap:6}}><div style={{width:8, height:8, borderRadius:2, background:COLORS[index % COLORS.length]}}></div><span style={{color:'#e2e8f0'}}>{item.name}</span></div><span style={{fontWeight:600}}>{item.ratio}%</span>
                          </div>
                        ))}
                      </div>
                    </>
                  ) : <div style={{display:'flex', justifyContent:'center', alignItems:'center', height:'100%', color:'#666'}}>暂无穿透数据</div>}
                </div>
              </div>

              <div className="card" style={{ gridColumn: 'span 6', minHeight: 400 }}>
                <div className="card-header"><div className="card-title"><Layers size={18}/> 我的持仓占比</div><div style={{fontSize:11, color:'var(--text-dim)'}}>MY ASSET ALLOCATION</div></div>
                <div style={{flex:1, display:'flex', flexDirection:'column', height:'100%'}}>
                  {fundAllocData.length > 0 ? (
                    <>
                      <div style={{flex:1, minHeight: 200}}>
                        <ResponsiveContainer width="100%" height="100%">
                          <PieChart><Pie data={fundAllocData} cx="50%" cy="50%" innerRadius={60} outerRadius={80} paddingAngle={2} dataKey="value">{fundAllocData.map((_, index) => (<Cell key={`cell-f-${index}`} fill={COLORS[(index+2) % COLORS.length]} stroke="var(--bg-card)" strokeWidth={2}/>))}</Pie><Tooltip contentStyle={{backgroundColor:'#18181b', border:'1px solid rgba(255,255,255,0.1)', borderRadius:8}} itemStyle={{color:'#fff'}} formatter={(val:number)=>fmtMoney(val)}/></PieChart>
                        </ResponsiveContainer>
                      </div>
                      <div style={{height: 120, overflowY:'auto', padding:'0 10px'}}>
                        {fundAllocData.map((item, index) => (
                          <div key={index} style={{display:'flex', justifyContent:'space-between', marginBottom:8, fontSize:13}}>
                             <div style={{display:'flex', alignItems:'center', gap:6}}><div style={{width:8, height:8, borderRadius:2, background:COLORS[(index+2) % COLORS.length]}}></div><span style={{color:'#e2e8f0'}}>{item.name}</span></div><span style={{fontWeight:600}}>¥{item.value.toFixed(0)}</span>
                          </div>
                        ))}
                      </div>
                    </>
                  ) : <div style={{display:'flex', justifyContent:'center', alignItems:'center', height:'100%', color:'#666'}}>暂无持仓数据</div>}
                </div>
              </div>
            </div>

            <div className="card chart-card">
              <div className="card-header"><div className="card-title"><BarChart3 size={18}/> 价格趋势</div></div>
              <div style={{flex:1, minHeight:0}}>
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={advice.history}>
                    <defs><linearGradient id="colorPrice" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#6366f1" stopOpacity={0.3}/><stop offset="95%" stopColor="#6366f1" stopOpacity={0}/></linearGradient></defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
                    <XAxis dataKey="date" hide />
                    <YAxis domain={['auto', 'auto']} orientation="right" tick={{fill:'#52525b', fontSize:11, fontFamily:'var(--font-mono)'}} axisLine={false} tickLine={false} />
                    <Tooltip contentStyle={{backgroundColor:'#18181b', border:'1px solid rgba(255,255,255,0.1)', borderRadius:8}} itemStyle={{color:'#fff'}} formatter={(val:number)=>val.toFixed(4)} />
                    <Area type="monotone" dataKey="price" stroke="#6366f1" strokeWidth={2} fillOpacity={1} fill="url(#colorPrice)" />
                    <Line type="monotone" dataKey="ma200" stroke="#f59e0b" strokeWidth={2} dot={false} strokeDasharray="5 5" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>

          </div>
        )}
      </div>
    </div>
  );
}


export default App