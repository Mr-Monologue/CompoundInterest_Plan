import { useEffect, useState } from 'react';
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';
import { 
  TrendingUp, Plus, Wallet, Activity, RefreshCw, 
  BarChart3, ArrowUpRight, ArrowDownRight, 
  PieChart, FileText, Zap, Layers, AlertCircle, Loader2
} from 'lucide-react';
import './App.css';

interface Asset { id: number; code: string; name: string; }
interface AdviceData { fund_code: string; name: string; current_price: number; ma200: number; action: string; suggested_amount: number; reason: string; history: any[]; grid_pos?: number; }
interface PortfolioData { asset_code: string; total_units: number; total_cost: number; }

function App() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [selectedAsset, setSelectedAsset] = useState<Asset | null>(null);
  const [advice, setAdvice] = useState<AdviceData | null>(null);
  const [portfolio, setPortfolio] = useState<PortfolioData | null>(null);
  const [report, setReport] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // UI States
  const [showAddForm, setShowAddForm] = useState(false);
  const [showTransForm, setShowTransForm] = useState(false);
  const [newCode, setNewCode] = useState("");
  const [newName, setNewName] = useState("");
  const [transPrice, setTransPrice] = useState("");
  const [transAmount, setTransAmount] = useState("200");
  const [transType, setTransType] = useState("BUY");

  useEffect(() => { fetchAssets(); }, []);

  const fetchAssets = () => {
    fetch('http://127.0.0.1:8000/api/assets')
      .then(res => res.json())
      .then(setAssets)
      .catch(err => console.error("Assets failed", err));
  };

  const fetchReport = (code: string) => {
    fetch(`http://127.0.0.1:8000/api/strategy/report/${code}`)
      .then(res => res.json())
      .then(data => setReport(data.report))
      .catch(console.error);
  };

  const handleSelectAsset = (asset: Asset) => {
    setSelectedAsset(asset);
    setLoading(true);
    setErrorMsg(null);
    setAdvice(null);
    setPortfolio(null);
    setReport("");
    setShowTransForm(false);

    Promise.all([
      fetch(`http://127.0.0.1:8000/api/advice/${asset.code}`).then(res => res.json()),
      fetch(`http://127.0.0.1:8000/api/portfolio/${asset.code}`).then(res => res.json())
    ]).then(([adviceData, portfolioData]) => {
      if (adviceData.action === "ERROR") {
        throw new Error(adviceData.reason || "数据获取失败");
      }
      setAdvice(adviceData);
      setPortfolio(portfolioData);
      setTransPrice(String(adviceData.current_price));
      fetchReport(asset.code);
    }).catch(err => {
      console.error("Select Error:", err);
      setErrorMsg(err.message || "连接失败");
    }).finally(() => {
      setLoading(false);
    });
  };

  const handleRunStrategy = () => {
    if (!selectedAsset) return;
    fetch(`http://127.0.0.1:8000/api/strategy/run/${selectedAsset.code}`, { method: 'POST' })
      .then(res => res.json())
      .then(data => {
        alert(`✅ 策略执行成功！\n建议: ${data.advice}`);
        handleSelectAsset(selectedAsset);
      });
  };

  const handleAddAsset = () => {
    if (!newCode || !newName) return;
    fetch('http://127.0.0.1:8000/api/assets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code: newCode, name: newName })
    }).then(res => res.json()).then(data => {
       if(data.id) { fetchAssets(); setShowAddForm(false); setNewCode(""); setNewName(""); }
    });
  };

  const handleTransaction = () => {
    if (!selectedAsset) return;
    fetch('http://127.0.0.1:8000/api/transactions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ asset_code: selectedAsset.code, type: transType, price: parseFloat(transPrice), amount: parseFloat(transAmount) })
    }).then(res => res.json()).then(data => {
       if(data.id) { alert("记账成功"); setShowTransForm(false); handleSelectAsset(selectedAsset); }
    });
  };

  // === 🔥 安全数值格式化 (防崩核心) ===
  const safeNum = (num: any, digits = 2) => {
    if (num === null || num === undefined || isNaN(num)) return "0.00";
    return Number(num).toFixed(digits);
  };

  const { profit, rate, marketValue } = (() => {
    if (!advice || !portfolio) return { profit: 0, rate: 0, marketValue: 0 };
    const mv = portfolio.total_units * advice.current_price;
    const pf = mv - portfolio.total_cost;
    const rt = portfolio.total_cost > 0 ? (pf / portfolio.total_cost) * 100 : 0;
    return { profit: pf, rate: rt, marketValue: mv };
  })();

  // 渲染逻辑
  const renderContent = () => {
    if (errorMsg) {
      return (
        <div className="empty-state" style={{borderColor: 'var(--danger)', color: 'var(--danger)'}}>
          <AlertCircle size={48} />
          <h2>数据获取失败</h2>
          <p>{errorMsg}</p>
          <button className="btn btn-secondary" onClick={() => selectedAsset && handleSelectAsset(selectedAsset)}>重试</button>
        </div>
      );
    }

    if (loading) {
      return (
        <div className="empty-state" style={{border:'none'}}>
          <Loader2 className="spin" size={48} color="var(--primary)" />
          <p style={{marginTop: 20, color: 'var(--text-sub)'}}>正在分析行情数据...</p>
        </div>
      );
    }

    if (!selectedAsset) {
      return (
        <div className="empty-state">
          <Layers size={64} strokeWidth={1} />
          <h2>请选择一个投资标的</h2>
        </div>
      );
    }

    if (!advice) return null; // 兜底

    return (
      <div className="dashboard-grid">
        {/* 行情 */}
        <div className="card price-card">
          <div className="card-header"><div className="card-title"><Activity size={16} /> Market Price</div></div>
          <div>
            <div className="price-big">{advice.current_price}</div>
            <div style={{display:'flex', alignItems:'center', gap:6, marginTop:8, color: advice.current_price > advice.ma200 ? '#ef4444' : '#10b981'}}>
              {advice.current_price > advice.ma200 ? <ArrowUpRight size={16}/> : <ArrowDownRight size={16}/>}
              <span style={{fontWeight:600, fontSize:13}}>
                {Math.abs(advice.grid_pos || 0).toFixed(1)} 格偏离
              </span>
            </div>
            <div className="price-sub">MA200: {safeNum(advice.ma200, 4)}</div>
          </div>
        </div>

        {/* 建议 */}
        <div className="card advice-card" style={{borderColor: advice.action === 'BUY' ? 'var(--success)' : (advice.action === 'SELL' ? 'var(--danger)' : 'var(--border)'), background: advice.action === 'BUY' ? 'rgba(16, 185, 129, 0.05)' : 'var(--bg-card)'}}>
          <div className="advice-content">
            <div className="card-title" style={{marginBottom: 5}}><TrendingUp size={18} /> Signal</div>
            <h1 style={{color: advice.action === 'BUY' ? 'var(--success)' : (advice.action === 'SELL' ? 'var(--danger)' : 'var(--warning)')}}>
              {advice.action === 'BUY' ? '建议定投' : (advice.action === 'WAIT' ? '观望/止盈' : '建议卖出')}
            </h1>
            <div style={{color: 'var(--text-sub)', marginTop: 5}}>{advice.reason}</div>
          </div>
          <div style={{textAlign: 'right'}}>
            <div style={{fontSize: 12, color: 'var(--text-sub)', marginBottom: 5}}>建议金额</div>
            <div className="amount-display">¥ {advice.suggested_amount}</div>
          </div>
        </div>

        {/* 策略 */}
        <div className="card strategy-card">
          <div className="card-header">
            <div className="card-title"><FileText size={16} /> Strategy Review</div>
            <button className="btn btn-primary" onClick={handleRunStrategy}><RefreshCw size={14} /> 执行分析</button>
          </div>
          <div className="report-content">{report || "暂无记录，请点击右上角执行分析..."}</div>
        </div>

        {/* 持仓 */}
        <div className="card portfolio-card">
          <div className="card-header">
            <div className="card-title"><Wallet size={16} /> Portfolio</div>
            <button className="btn btn-glass" onClick={() => setShowTransForm(!showTransForm)}>{showTransForm ? 'Cancel' : '+ Record'}</button>
          </div>
          {showTransForm && (
            <div className="input-group" style={{marginBottom: 20}}>
              <select className="input-dark" value={transType} onChange={e=>setTransType(e.target.value)} style={{maxWidth: 100}}><option value="BUY">买入</option><option value="SELL">卖出</option></select>
              <input className="input-dark" type="number" placeholder="价格" value={transPrice} onChange={e=>setTransPrice(e.target.value)} />
              <input className="input-dark" type="number" placeholder="金额" value={transAmount} onChange={e=>setTransAmount(e.target.value)} />
              <button className="btn btn-primary" onClick={handleTransaction}>提交</button>
            </div>
          )}
          <div className="portfolio-grid">
            <div className="portfolio-item"><div className="p-label">总市值</div><div className="p-value">¥ {safeNum(marketValue, 0)}</div></div>
            <div className="portfolio-item"><div className="p-label">投入本金</div><div className="p-value">¥ {portfolio ? safeNum(portfolio.total_cost, 0) : '0'}</div></div>
            <div className="portfolio-item"><div className="p-label">持有收益</div><div className="p-value" style={{color: profit>=0?'#ef4444':'#10b981'}}>{profit>0?'+':''}{safeNum(profit, 0)}</div></div>
            <div className="portfolio-item"><div className="p-label">收益率</div><div className="p-value" style={{color: profit>=0?'#ef4444':'#10b981'}}>{safeNum(rate)}%</div></div>
          </div>
        </div>

        {/* 图表 */}
        <div className="card chart-card">
          <div className="card-header"><div className="card-title"><BarChart3 size={16} /> Trend Analysis</div></div>
          <div style={{flex:1, minHeight:0}}>
            {advice.history && advice.history.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={advice.history}>
                  <defs><linearGradient id="colorPrice" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#6366f1" stopOpacity={0.3}/><stop offset="95%" stopColor="#6366f1" stopOpacity={0}/></linearGradient></defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
                  <XAxis dataKey="date" hide />
                  <YAxis domain={['auto', 'auto']} orientation="right" tick={{fill: '#52525b', fontSize: 11, fontFamily: 'JetBrains Mono'}} axisLine={false} tickLine={false} />
                  <Tooltip contentStyle={{backgroundColor: '#18181b', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8, color: '#fff'}} itemStyle={{color: '#fff'}} formatter={(val:number) => Number(val).toFixed(4)} />
                  <Area type="monotone" dataKey="price" stroke="#6366f1" strokeWidth={2} fillOpacity={1} fill="url(#colorPrice)" />
                  <Line type="monotone" dataKey="ma200" stroke="#f59e0b" strokeWidth={2} dot={false} strokeDasharray="5 5" />
                </AreaChart>
              </ResponsiveContainer>
            ) : <div style={{display:'flex', justifyContent:'center', alignItems:'center', height:'100%', color:'#666'}}>暂无K线数据</div>}
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="app-container">
      <div className="sidebar">
        <div className="brand"><div style={{width:24, height:24, background:'var(--primary)', borderRadius:6}}></div>RevvInvest</div>
        <div className="sidebar-section-title"><span>Watchlist</span><button className="btn-icon" onClick={() => setShowAddForm(!showAddForm)}><Plus size={14} /></button></div>
        {showAddForm && (
          <div style={{marginBottom: 16, padding: 10, background: 'rgba(0,0,0,0.2)', borderRadius: 8}}>
            <input className="input-dark" style={{width:'100%', marginBottom:8}} placeholder="代码 (005827)" value={newCode} onChange={e=>setNewCode(e.target.value)} />
            <input className="input-dark" style={{width:'100%', marginBottom:8}} placeholder="名称" value={newName} onChange={e=>setNewName(e.target.value)} />
            <button className="btn btn-primary" style={{width:'100%', justifyContent:'center'}} onClick={handleAddAsset}>Add</button>
          </div>
        )}
        <div className="asset-list">
          {assets.map(asset => (
            <div key={asset.id} className={`asset-item ${selectedAsset?.id === asset.id ? 'active' : ''}`} onClick={() => handleSelectAsset(asset)}>
              <div className="asset-name">{asset.name}</div><div className="asset-code">{asset.code}</div>
            </div>
          ))}
        </div>
      </div>
      <div className="main-content">
        {renderContent()}
      </div>
    </div>
  );
}

export default App;