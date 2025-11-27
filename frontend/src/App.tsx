import { useEffect, useState } from 'react';
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Line } from 'recharts';
import { 
  TrendingUp, Plus, Wallet, Activity, RefreshCw, 
  BarChart3, ArrowUpRight, ArrowDownRight, 
  PieChart, FileText, Zap, Layers, AlertCircle, Loader2,
  Trash2, DollarSign, Target, Percent
} from 'lucide-react';
import './App.css';

// ... (接口定义保持不变)
interface Asset { id: number; code: string; name: string; }
interface AdviceData { fund_code: string; name: string; current_price: number; ma200: number; action: string; suggested_amount: number; reason: string; history: any[]; grid_pos?: number; vol_daily?: number;}
interface PortfolioData { asset_code: string; total_units: number; total_cost: number; }

function App() {
  // ... (状态管理逻辑保持不变，复制你原来的即可)
  const [assets, setAssets] = useState<Asset[]>([]);
  const [selectedAsset, setSelectedAsset] = useState<Asset | null>(null);
  const [advice, setAdvice] = useState<AdviceData | null>(null);
  const [portfolio, setPortfolio] = useState<PortfolioData | null>(null);
  const [report, setReport] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [globalState, setGlobalState] = useState({ budget_left: 0, global_reserve: 0 });

  const [showAddForm, setShowAddForm] = useState(false);
  const [showTransForm, setShowTransForm] = useState(false);
  const [newCode, setNewCode] = useState("");
  const [newName, setNewName] = useState("");
  const [transPrice, setTransPrice] = useState("");
  const [transAmount, setTransAmount] = useState("200");
  const [transType, setTransType] = useState("BUY");
  const [inputMode, setInputMode] = useState<"amount" | "shares">("amount");
  const [transShares, setTransShares] = useState("");

  useEffect(() => { 
    fetchAssets(); 
    fetchGlobalState();
  }, []);

  const fetchAssets = () => { fetch('http://127.0.0.1:8000/api/assets').then(res => res.json()).then(setAssets); };
  const fetchGlobalState = () => { fetch('http://127.0.0.1:8000/api/plan/state').then(res=>res.json()).then(setGlobalState); };
  const fetchReport = (code: string) => { fetch(`http://127.0.0.1:8000/api/strategy/report/${code}`).then(res => res.json()).then(data => setReport(data.report)); };

  const handleSelectAsset = (asset: Asset) => {
    setSelectedAsset(asset); setLoading(true); setErrorMsg(null); setAdvice(null); setPortfolio(null); setReport(""); setShowTransForm(false);
    Promise.all([
      fetch(`http://127.0.0.1:8000/api/advice/${asset.code}`).then(res => res.json()),
      fetch(`http://127.0.0.1:8000/api/portfolio/${asset.code}`).then(res => res.json())
    ]).then(([adviceData, portfolioData]) => {
      if (adviceData.action === "ERROR") throw new Error(adviceData.reason);
      setAdvice(adviceData); setPortfolio(portfolioData); setTransPrice(String(adviceData.current_price)); fetchReport(asset.code);
    }).catch(err => { setErrorMsg(err.message); }).finally(() => setLoading(false));
  };

  const handleRunAll = () => {
    if(!confirm("确定执行全组合策略？")) return;
    setLoading(true);
    fetch('http://127.0.0.1:8000/api/plan/run', { method: 'POST' }).then(res=>res.json()).then(data => {
        alert(data.logs.join("\n")); fetchGlobalState(); 
        if(selectedAsset) handleSelectAsset(selectedAsset);
        setLoading(false);
    });
  };

  // ... (Transaction/Add 逻辑保持不变)
  const handleAddAsset = () => {
    if (!newCode || !newName) return;
    fetch('http://127.0.0.1:8000/api/assets', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code: newCode, name: newName }) })
    .then(res => res.json()).then(data => { if(data.id) { fetchAssets(); setShowAddForm(false); setNewCode(""); setNewName(""); } });
  };

  const handleDeleteAsset = (e: React.MouseEvent, id: number) => {
    e.stopPropagation();
    if (confirm("确定删除？")) fetch(`http://127.0.0.1:8000/api/assets/${id}`, { method: 'DELETE' }).then(fetchAssets);
  };

  const handleTransaction = () => {
    if (!selectedAsset) return;
    let finalAmount = parseFloat(transAmount);
    const price = parseFloat(transPrice);
    if (inputMode === 'shares') finalAmount = parseFloat(transShares) * price;
    
    fetch('http://127.0.0.1:8000/api/transactions', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ asset_code: selectedAsset.code, type: transType, price: price, amount: finalAmount, fee: inputMode==='shares'?0:0 })
    }).then(res => res.json()).then(data => { if(data.id) { setShowTransForm(false); handleSelectAsset(selectedAsset); fetchGlobalState(); } });
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
      {/* 侧边栏 */}
      <div className="sidebar">
        <div className="brand">
          <div style={{width:20, height:20, background:'var(--primary)', borderRadius:4}}></div>
          RevvInvest
        </div>

        {/* 全局仪表盘 (重做) */}
        <div className="global-dashboard">
          <div>
            <div className="global-label">本周预算</div>
            <div className="global-value">¥ {Number(globalState.budget_left).toFixed(0)}</div>
          </div>
          <div>
            <div className="global-label">全局准备金</div>
            <div className="global-sub">¥ {Number(globalState.global_reserve).toFixed(0)}</div>
          </div>
          <button onClick={handleRunAll} className="btn btn-primary" style={{justifyContent:'center', marginTop:10}}>
            <Zap size={14} /> 一键发车
          </button>
        </div>

        <div className="section-header">
          <span>关注列表</span>
          <button className="btn-icon" onClick={() => setShowAddForm(!showAddForm)}><Plus size={14} /></button>
        </div>

        {/* 添加表单 */}
        {showAddForm && (
          <div style={{padding:12, background:'var(--bg-panel)', borderRadius:12, marginBottom:10, border:'1px solid var(--border-active)'}}>
            <input className="input-dark" style={{marginBottom:8}} placeholder="代码" value={newCode} onChange={e=>setNewCode(e.target.value)} />
            <input className="input-dark" style={{marginBottom:8}} placeholder="名称" value={newName} onChange={e=>setNewName(e.target.value)} />
            <button className="btn btn-primary" style={{width:'100%', justifyContent:'center'}} onClick={handleAddAsset}>确认</button>
          </div>
        )}

        <div className="asset-list">
          {assets.map(asset => (
            <div key={asset.id} 
              className={`asset-item ${selectedAsset?.id === asset.id ? 'active' : ''}`}
              onClick={() => handleSelectAsset(asset)}>
              <div>
                <div className="name">{asset.name}</div>
                <div className="code">{asset.code}</div>
              </div>
              <button className="btn-icon" onClick={(e) => handleDeleteAsset(e, asset.id)}><Trash2 size={14}/></button>
            </div>
          ))}
        </div>
      </div>

      {/* 主内容区 */}
      <div className="main-content">
        {!selectedAsset ? (
          <div className="empty-state">
            <Layers size={64} color="#333" />
            <div style={{color:'var(--text-muted)', marginTop:20}}>选择一个资产查看详情</div>
          </div>
        ) : loading ? (
          <div className="empty-state" style={{border:'none'}}>
            <Loader2 className="spin" size={40} color="var(--primary)" />
          </div>
        ) : errorMsg ? (
          <div className="empty-state" style={{borderColor: 'var(--danger)', color: 'var(--danger)'}}>
            <AlertCircle size={40} />
            <p>{errorMsg}</p>
            <button className="btn btn-outline" onClick={()=>handleSelectAsset(selectedAsset)}>重试</button>
          </div>
        ) : advice && (
          <div className="dashboard-grid">
            
            {/* 1. 行情卡片 */}
            <div className="card price-card">
              <div className="card-header">
                <div className="card-title"><Activity size={16}/> 市场价格</div>
                <div className={`tag ${advice.current_price > advice.ma200 ? 'tag-red' : 'tag-green'}`}>
                  {advice.current_price > advice.ma200 ? '高于MA200' : '低于MA200'}
                </div>
              </div>
              <div className="big-number">{advice.current_price}</div>
              <div style={{display:'flex', alignItems:'center', gap:8, marginTop:8, fontSize:13, color: 'var(--text-muted)'}}>
                <span>MA200: {advice.ma200.toFixed(4)}</span>
                <span style={{color: 'var(--text-dim)'}}>|</span>
                <span>Vol: {advice.vol_daily ? (advice.vol_daily * 100).toFixed(2) : '0.00'}%</span>
              </div>
            </div>

            {/* 2. 建议卡片 */}
            <div className="card signal-card">
              <div className="card-header">
                <div className="card-title"><Zap size={16}/> 智能信号</div>
              </div>
              <div style={{display:'flex', justifyContent:'space-between', alignItems:'flex-end'}}>
                <div>
                  <div className="big-number" style={{
                    fontSize: 36,
                    color: advice.action === 'BUY' ? 'var(--success)' : (advice.action === 'SELL' ? 'var(--danger)' : 'var(--warning)'),
                    background: 'none', WebkitTextFillColor: 'initial'
                  }}>
                    {advice.action === 'BUY' ? '强烈买入' : (advice.action === 'WAIT' ? '持有/等待' : '卖出')}
                  </div>
                  <div style={{marginTop:8, color:'var(--text-muted)', fontSize:13}}>
                    {advice.reason}
                  </div>
                </div>
                <div style={{textAlign:'right'}}>
                  <div style={{fontSize:12, color:'var(--text-dim)', marginBottom:4}}>建议金额</div>
                  <div style={{fontSize:24, fontFamily:'var(--font-mono)', fontWeight:700, color:'var(--primary)'}}>
                    ¥ {advice.suggested_amount}
                  </div>
                </div>
              </div>
            </div>

            {/* 3. 策略透视 (保留你最喜欢的样式，微调边距) */}
            <div className="card strategy-card">
              <div className="card-header">
                <div className="card-title"><FileText size={16}/> 策略透视</div>
                <div style={{fontSize:11, color:'var(--text-dim)'}}>波动率网格系统</div>
              </div>
              
              <div style={{padding: '0 10px'}}>
                {/* 状态徽章 */}
                <div style={{display:'flex', justifyContent:'space-between', marginBottom:20}}>
                   <div className={`tag ${(advice.grid_pos||0) < -1 ? 'tag-green' : (advice.grid_pos||0) > 1 ? 'tag-red' : 'tag-wait'}`}>
                      {(advice.grid_pos||0) < -1 ? '低估' : (advice.grid_pos||0) > 1 ? '高估' : '中性'}
                   </div>
                   <div style={{fontFamily:'var(--font-mono)', color:'var(--text-muted)'}}>Z分数: {(advice.grid_pos||0).toFixed(2)}</div>
                </div>

                {/* 温度计 */}
                <div className="grid-thermometer" style={{background: 'linear-gradient(90deg, #10b981 0%, #1e293b 40%, #1e293b 60%, #ef4444 100%)', height:6, borderRadius:3, position:'relative', marginBottom:10}}>
                  <div style={{position:'absolute', left:'50%', width:1, height:6, background:'#52525b'}}></div>
                  <div className="grid-cursor" style={{
                    position:'absolute', top:-5, width:4, height:16, background:'#fff', borderRadius:2, boxShadow:'0 0 10px white',
                    left: `${Math.min(Math.max(((advice.grid_pos || 0) + 4) / 8 * 100, 0), 100)}%`
                  }}></div>
                </div>
                
                {/* 底部数据面板 */}
                <div className="data-grid" style={{marginTop:30}}>
                   <div className="data-box">
                      <div className="data-label">网格位置</div>
                      <div className="data-value" style={{color: (advice.grid_pos||0)>0?'#f87171':'#34d399'}}>
                        {advice.grid_pos?.toFixed(1)}
                      </div>
                   </div>
                   <div className="data-box">
                      <div className="data-label">操作</div>
                      <div className="data-value" style={{fontSize:16}}>
                        {advice.suggested_amount > 200 ? "激进" : (advice.suggested_amount === 0 ? "防守" : "标准")}
                      </div>
                   </div>
                   <div className="data-box" style={{gridColumn:'span 2'}}>
                      <div className="data-label">计划报告</div>
                      <div style={{fontSize:12, color:'var(--text-muted)', lineHeight:1.4}}>
                        {report ? report.split('\n')[2] : "暂无最近活动记录"}
                      </div>
                   </div>
                </div>
              </div>
            </div>

            {/* 4. 持仓 */}
            <div className="card portfolio-card">
              <div className="card-header">
                <div className="card-title"><Wallet size={16}/> 持仓</div>
                <button className="btn btn-outline" onClick={() => setShowTransForm(!showTransForm)}>
                  {showTransForm ? '取消' : '+ 记账'}
                </button>
              </div>

              {showTransForm && (
                <div style={{background:'var(--bg-panel)', padding:20, borderRadius:12, marginBottom:20, border:'1px solid var(--border-active)'}}>
                  <div style={{display:'flex', gap:10, marginBottom:15, borderBottom:'1px solid var(--border-subtle)', paddingBottom:10}}>
                    <div onClick={()=>setInputMode("amount")} style={{cursor:'pointer', color:inputMode==='amount'?'var(--primary)':'var(--text-dim)', fontWeight:inputMode==='amount'?600:400}}>金额模式</div>
                    <div onClick={()=>setInputMode("shares")} style={{cursor:'pointer', color:inputMode==='shares'?'var(--primary)':'var(--text-dim)', fontWeight:inputMode==='shares'?600:400}}>份额模式</div>
                  </div>
                  <div style={{display:'flex', gap:10}}>
                    <select className="input-dark" value={transType} onChange={e=>setTransType(e.target.value)} style={{width:100}}><option value="BUY">买入</option><option value="SELL">卖出</option></select>
                    <input className="input-dark" type="number" placeholder="价格" value={transPrice} onChange={e=>setTransPrice(e.target.value)} />
                    <input className="input-dark" type="number" placeholder={inputMode==='amount'?"金额 (¥)":"份额"} value={inputMode==='amount'?transAmount:transShares} onChange={e=>inputMode==='amount'?setTransAmount(e.target.value):setTransShares(e.target.value)} />
                    <button className="btn btn-primary" onClick={handleTransaction}>保存</button>
                  </div>
                </div>
              )}

              <div className="data-grid">
                <div className="data-box"><div className="data-label"><DollarSign size={12}/> 市值</div><div className="data-value">{fmtMoney(marketValue)}</div></div>
                <div className="data-box"><div className="data-label"><Target size={12}/> 成本</div><div className="data-value">{fmtMoney(portfolio?.total_cost || 0)}</div></div>
                <div className="data-box"><div className="data-label"><TrendingUp size={12}/> 盈亏</div><div className="data-value" style={{color: profit>=0?'var(--danger)':'var(--success)'}}>{profit>0?'+':''}{fmtMoney(profit)}</div></div>
                <div className="data-box"><div className="data-label"><Percent size={12}/> 收益率</div><div className="data-value" style={{color: profit>=0?'var(--danger)':'var(--success)'}}>{rate.toFixed(2)}%</div></div>
              </div>
            </div>

            {/* 5. 图表 */}
            <div className="card chart-card">
              <div className="card-header"><div className="card-title"><BarChart3 size={16}/> 价格趋势</div></div>
              <div style={{flex:1, minHeight:0}}>
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={advice.history}>
                    <defs>
                      <linearGradient id="colorPrice" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3}/>
                        <stop offset="95%" stopColor="#6366f1" stopOpacity={0}/>
                      </linearGradient>
                    </defs>
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

export default App;
