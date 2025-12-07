import { useEffect, useState } from 'react';
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Line } from 'recharts';
import { 
  TrendingUp, Plus, Wallet, Activity, RefreshCw, 
  BarChart3, ArrowUpRight, ArrowDownRight, 
  PieChart, FileText, Zap, Layers, AlertCircle, Loader2,
  Trash2, DollarSign, Target, Percent, Settings
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
  // 新增 Pool 相关的状态
  const [poolState, setPoolState] = useState({ pool_balance: 0, base_investment: 200 });
  const [showDeposit, setShowDeposit] = useState(false); // 充值弹窗开关
  const [depositAmount, setDepositAmount] = useState("");
  const [showConfig, setShowConfig] = useState(false);   // 设置弹窗开关
  const [newBase, setNewBase] = useState("");
  const [newBalance, setNewBalance] = useState(""); // 🔥 新增：用于编辑余额

  const [showAddForm, setShowAddForm] = useState(false);
  const [showTransForm, setShowTransForm] = useState(false);
  const [newCode, setNewCode] = useState("");
  const [newName, setNewName] = useState("");
  const [transPrice, setTransPrice] = useState("");
  const [transAmount, setTransAmount] = useState("200");
  const [transType, setTransType] = useState("BUY");
  const [inputMode, setInputMode] = useState<"amount" | "shares">("amount");
  const [transShares, setTransShares] = useState("");
  const [fromPool, setFromPool] = useState(true); // 从资金池扣款
  const [showSuggestions, setShowSuggestions] = useState(false); // 建议清单弹窗
  const [suggestions, setSuggestions] = useState<any[]>([]); // 建议列表
  const [showHistory, setShowHistory] = useState(false); // 历史记录显示
  const [transactions, setTransactions] = useState<any[]>([]); // 交易历史

  useEffect(() => { 
    fetchAssets(); 
    fetchPool(); // <--- 改这里
  }, []);

  const fetchAssets = () => { fetch('http://127.0.0.1:8000/api/assets').then(res => res.json()).then(setAssets); };
  // 获取池子状态
  const fetchPool = () => {
    fetch('http://127.0.0.1:8000/api/pool').then(res=>res.json()).then(data => {
      setPoolState(data);
      setNewBase(String(data.base_investment));
      setNewBalance(String(data.pool_balance)); // 🔥 新增：同步余额到输入框
    });
  };
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

  // 充值处理
  const handleDeposit = () => {
    fetch('http://127.0.0.1:8000/api/pool/deposit', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ amount: depositAmount })
    }).then(() => {
      alert(`🎉 充值成功！资金池增加了 ¥${depositAmount}`);
      setShowDeposit(false);
      setDepositAmount("");
      fetchPool();
    });
  };

  // 修改基准处理
  const handleUpdateConfig = () => {
    fetch('http://127.0.0.1:8000/api/pool/config', {
      method: 'POST', 
      headers: {'Content-Type': 'application/json'},
      // 🔥 修改：同时发送 base_investment 和 pool_balance
      body: JSON.stringify({ 
        base_investment: newBase, 
        pool_balance: newBalance 
      })
    }).then(() => {
      alert("✅ 配置与资金校准已保存");
      setShowConfig(false);
      fetchPool();
    });
  };

  const handleRunAll = () => {
    // 1. 先检查有没有钱，没钱提示一下（但也允许继续跑，看策略建议）
    if (poolState.pool_balance < 100) {
      if(!confirm("⚠️ 资金池余额不足 (¥" + poolState.pool_balance + ")，可能无法生成买入建议。\n是否继续？")) return;
    }

    setLoading(true);
    fetch('http://127.0.0.1:8000/api/plan/run', { method: 'POST' })
      .then(res => res.json())
      .then(data => {
        // data.suggestions 是后端返回的列表
        setSuggestions(data.suggestions || []); 
        setShowSuggestions(true); // 打开弹窗
        fetchPool(); // 刷新余额显示
        setLoading(false);
      })
      .catch(err => {
        alert("执行失败，请检查后端日志");
        setLoading(false);
      });
  };

  // 获取交易历史
  const fetchTransactions = (code: string) => {
    fetch(`http://127.0.0.1:8000/api/transactions/${code}`).then(res => res.json()).then(setTransactions);
  };

  // 删除交易
  const handleDeleteTransaction = (txId: number) => {
    if (!confirm("确定删除这条交易记录？")) return;
    fetch(`http://127.0.0.1:8000/api/transactions/${txId}`, { method: 'DELETE' }).then(() => {
      if (selectedAsset) {
        fetchTransactions(selectedAsset.code);
        handleSelectAsset(selectedAsset); // 刷新持仓数据
      }
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
      body: JSON.stringify({ 
        asset_code: selectedAsset.code, 
        type: transType, 
        price: price, 
        amount: finalAmount, 
        fee: inputMode==='shares'?0:0,
        from_pool: fromPool
      })
    }).then(res => res.json()).then(data => { 
      if(data.id) { 
        setShowTransForm(false); 
        handleSelectAsset(selectedAsset); 
        fetchPool(); // 刷新资金池
        if (showHistory) fetchTransactions(selectedAsset.code);
      } 
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
      {/* === 📋 本周建议清单弹窗 === */}
      {showSuggestions && (
        <div style={{
          position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
          backgroundColor: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(5px)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000
        }}>
          <div style={{
            background: '#18181b', border: '1px solid #333', borderRadius: '16px',
            width: '500px', maxWidth: '90%', padding: '24px', boxShadow: '0 20px 50px rgba(0,0,0,0.5)'
          }}>
            <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:20}}>
              <h3 style={{margin:0, display:'flex', alignItems:'center', gap:8}}>
                <FileText size={20} color="var(--primary)"/> 本周建议清单
              </h3>
              <button onClick={() => setShowSuggestions(false)} style={{background:'none', border:'none', color:'#666', cursor:'pointer'}}>✕</button>
            </div>

            <div style={{maxHeight:'60vh', overflowY:'auto', marginBottom:20}}>
              {suggestions.length === 0 ? (
                <div style={{textAlign:'center', color:'#666', padding:20}}>暂无建议</div>
              ) : (
                suggestions.map((item: any, index: number) => (
                  <div key={index} style={{
                    display:'flex', justifyContent:'space-between', alignItems:'center',
                    padding:'12px', marginBottom:'8px', borderRadius:'8px',
                    background: item.amt > 0 ? 'rgba(16, 185, 129, 0.1)' : 'rgba(255,255,255,0.03)',
                    border: item.amt > 0 ? '1px solid rgba(16, 185, 129, 0.2)' : '1px solid transparent'
                  }}>
                    <div>
                      <div style={{fontWeight:600, color:'#eee'}}>{item.name}</div>
                      <div style={{fontSize:12, color: item.amt > 0 ? '#34d399' : '#888'}}>{item.msg}</div>
                    </div>
                    {item.amt > 0 && (
                      <div style={{fontSize:18, fontWeight:'bold', color:'var(--success)'}}>
                        ¥ {item.amt}
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>

            <div style={{fontSize:12, color:'#666', lineHeight:1.5, background:'rgba(0,0,0,0.2)', padding:10, borderRadius:8}}>
              💡 提示：<br/>
              1. 系统不会自动扣款。请根据上述清单，去支付宝/券商手动买入。<br/>
              2. 买完后，请回到列表点击对应资产的 <b>"📝 记一笔"</b> 按钮进行记账。<br/>
              3. 记账时勾选"从资金池扣款"，系统余额才会减少。
            </div>

            <button onClick={() => setShowSuggestions(false)} className="btn btn-primary" style={{width:'100%', marginTop:20, padding:12}}>
              知道了，这就去操作
            </button>
          </div>
        </div>
      )}

      {/* 侧边栏 */}
      <div className="sidebar">
        <div className="brand">
          <div style={{width:20, height:20, background:'var(--primary)', borderRadius:4}}></div>
          RevvInvest
        </div>

        {/* === 💰 资金池管理卡片 === */}
        <div className="global-dashboard" style={{position: 'relative'}}>
          {/* 设置按钮 (右上角) */}
          <button 
            className="btn-icon" 
            style={{position: 'absolute', top: 10, right: 10}}
            onClick={() => setShowConfig(!showConfig)}
            title="设置定投基准"
          >
            <Settings size={14} />
          </button>

          <div>
            <div className="global-label">Investable Pool</div>
            <div className="global-value" style={{color: poolState.pool_balance < 100 ? '#ef4444' : '#fff'}}>
              ¥ {Number(poolState.pool_balance).toFixed(0)}
            </div>
          </div>
          
          <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginTop:5}}>
             <div className="global-sub">基准: ¥{poolState.base_investment}/次</div>
          </div>

          <div style={{display: 'flex', gap: 8, marginTop: 15}}>
            <button onClick={() => setShowDeposit(!showDeposit)} className="btn btn-secondary" style={{flex:1, justifyContent:'center'}}>
               + 充值
            </button>
            <button onClick={handleRunAll} className="btn btn-primary" style={{flex:1, justifyContent:'center'}}>
               🚀 发车
            </button>
          </div>

          {/* 充值折叠面板 */}
          {showDeposit && (
            <div style={{marginTop: 10, paddingTop: 10, borderTop: '1px solid rgba(255,255,255,0.1)'}}>
               <input 
                 className="input-dark" 
                 placeholder="金额 (¥)" 
                 value={depositAmount}
                 onChange={e => setDepositAmount(e.target.value)}
                 style={{marginBottom: 5}}
               />
               <button onClick={handleDeposit} className="btn btn-primary" style={{width: '100%', fontSize: 12, padding: 6}}>确认充值</button>
            </div>
          )}

          {/* 配置折叠面板 */}
          {showConfig && (
            <div style={{marginTop: 10, paddingTop: 10, borderTop: '1px solid rgba(255,255,255,0.1)'}}>
               
               {/* 修改资金池余额 */}
               <div style={{marginBottom: 10}}>
                 <div style={{fontSize: 11, color: '#aaa', marginBottom: 4}}>校准资金池余额 (¥):</div>
                 <input 
                   className="input-dark" 
                   value={newBalance}
                   onChange={e => setNewBalance(e.target.value)}
                   type="number"
                 />
               </div>

               {/* 修改定投基准 */}
               <div style={{marginBottom: 10}}>
                 <div style={{fontSize: 11, color: '#aaa', marginBottom: 4}}>每份定投基准 (¥):</div>
                 <input 
                   className="input-dark" 
                   value={newBase}
                   onChange={e => setNewBase(e.target.value)}
                   type="number"
                 />
               </div>

               <button onClick={handleUpdateConfig} className="btn btn-secondary" style={{width: '100%', fontSize: 12, padding: 6}}>
                 💾 保存修改
               </button>
            </div>
          )}
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
                  <div style={{display:'flex', gap:10, marginBottom:10}}>
                    <select className="input-dark" value={transType} onChange={e=>setTransType(e.target.value)} style={{width:100}}><option value="BUY">买入</option><option value="SELL">卖出</option></select>
                    <input className="input-dark" type="number" placeholder="价格" value={transPrice} onChange={e=>setTransPrice(e.target.value)} />
                    <input className="input-dark" type="number" placeholder={inputMode==='amount'?"金额 (¥)":"份额"} value={inputMode==='amount'?transAmount:transShares} onChange={e=>inputMode==='amount'?setTransAmount(e.target.value):setTransShares(e.target.value)} />
                    <button className="btn btn-primary" onClick={handleTransaction}>保存</button>
                  </div>
                  {transType === "BUY" && (
                    <label style={{display:'flex', alignItems:'center', gap:8, fontSize:12, color:'var(--text-muted)', cursor:'pointer'}}>
                      <input type="checkbox" checked={fromPool} onChange={e=>setFromPool(e.target.checked)} style={{cursor:'pointer'}} />
                      <span>从资金池扣款</span>
                    </label>
                  )}
                </div>
              )}

              <div className="data-grid">
                <div className="data-box"><div className="data-label"><DollarSign size={12}/> 市值</div><div className="data-value">{fmtMoney(marketValue)}</div></div>
                <div className="data-box"><div className="data-label"><Target size={12}/> 成本</div><div className="data-value">{fmtMoney(portfolio?.total_cost || 0)}</div></div>
                <div className="data-box"><div className="data-label"><TrendingUp size={12}/> 盈亏</div><div className="data-value" style={{color: profit>=0?'var(--danger)':'var(--success)'}}>{profit>0?'+':''}{fmtMoney(profit)}</div></div>
                <div className="data-box"><div className="data-label"><Percent size={12}/> 收益率</div><div className="data-value" style={{color: profit>=0?'var(--danger)':'var(--success)'}}>{rate.toFixed(2)}%</div></div>
              </div>

              {/* 历史记录按钮 */}
              <div style={{marginTop: 15, paddingTop: 15, borderTop: '1px solid var(--border-subtle)'}}>
                <button className="btn btn-outline" onClick={() => {
                  setShowHistory(!showHistory);
                  if (!showHistory && selectedAsset) fetchTransactions(selectedAsset.code);
                }} style={{width: '100%', justifyContent: 'center'}}>
                  📜 {showHistory ? '隐藏' : '显示'}历史记录
                </button>
              </div>

              {/* 历史记录列表 */}
              {showHistory && transactions.length > 0 && (
                <div style={{marginTop: 15, maxHeight: 300, overflowY: 'auto'}}>
                  <div style={{fontSize: 12, color: 'var(--text-dim)', marginBottom: 8}}>交易历史</div>
                  {transactions.map((tx: any) => (
                    <div key={tx.id} style={{
                      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                      padding: '10px', background: 'var(--bg-panel)', borderRadius: 8, marginBottom: 8,
                      border: '1px solid var(--border-subtle)'
                    }}>
                      <div style={{flex: 1}}>
                        <div style={{fontSize: 13, fontWeight: 600}}>
                          {tx.type === 'BUY' ? '买入' : '卖出'} - {new Date(tx.date).toLocaleDateString()}
                        </div>
                        <div style={{fontSize: 11, color: 'var(--text-muted)', marginTop: 4}}>
                          价格: ¥{tx.price.toFixed(4)} | 金额: ¥{tx.amount.toFixed(2)} | 份额: {tx.units.toFixed(2)}
                        </div>
                      </div>
                      <button 
                        className="btn-icon" 
                        onClick={() => handleDeleteTransaction(tx.id)}
                        style={{color: 'var(--danger)'}}
                        title="删除"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  ))}
                </div>
              )}
              {showHistory && transactions.length === 0 && (
                <div style={{marginTop: 15, textAlign: 'center', color: 'var(--text-muted)', fontSize: 12}}>
                  暂无交易记录
                </div>
              )}
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
