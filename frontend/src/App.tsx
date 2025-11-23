import { useEffect, useState } from 'react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import './App.css';

interface Asset { id: number; code: string; name: string; }
interface AdviceData { fund_code: string; name: string; current_price: number; ma200: number; action: string; suggested_amount: number; reason: string; history: any[]; }
interface PortfolioData { asset_code: string; total_units: number; total_cost: number; }

function App() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [selectedAsset, setSelectedAsset] = useState<Asset | null>(null);
  const [advice, setAdvice] = useState<AdviceData | null>(null);
  const [portfolio, setPortfolio] = useState<PortfolioData | null>(null);
  const [report, setReport] = useState<string>(""); 
  
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState("准备就绪");
  const [showAddForm, setShowAddForm] = useState(false);
  const [newCode, setNewCode] = useState("");
  const [newName, setNewName] = useState("");
  const [showTransForm, setShowTransForm] = useState(false);
  const [transPrice, setTransPrice] = useState("");
  const [transAmount, setTransAmount] = useState("1000");
  const [transType, setTransType] = useState("BUY");

  useEffect(() => { fetchAssets(); }, []);

  const fetchAssets = () => {
    fetch('http://127.0.0.1:8000/api/assets').then(res => res.json()).then(data => setAssets(data));
  };

  // === 🔥 修改点 1: 把获取报告提取为独立函数，接受 code 参数 ===
  const fetchReport = (code: string) => {
    fetch(`http://127.0.0.1:8000/api/strategy/report/${code}`)
      .then(res => res.json())
      .then(data => {
        // 如果没有数据，后端通常返回一段话，直接显示即可
        setReport(data.report);
      });
  };

  // === 🔥 修改点 2: 切换资产时，自动加载所有数据（包括报告） ===
  const handleSelectAsset = (asset: Asset) => {
    setSelectedAsset(asset);
    setLoading(true);
    setAdvice(null);
    setPortfolio(null);
    setReport(""); // 先清空，避免闪烁
    setMsg(`正在获取 ${asset.name} ...`);
    setShowTransForm(false);

    // 1. 获取行情
    fetch(`http://127.0.0.1:8000/api/advice/${asset.code}`)
      .then(res => res.json())
      .then(data => {
        if (data.action === "ERROR") {
          setMsg(`错误: ${data.reason}`);
        } else {
          setAdvice(data);
          setTransPrice(String(data.current_price));
          setMsg("行情更新成功");
        }
        setLoading(false);
      })
      .catch(() => { setMsg("网络请求失败"); setLoading(false); });

    // 2. 获取持仓
    fetch(`http://127.0.0.1:8000/api/portfolio/${asset.code}`)
      .then(res => res.json())
      .then(data => setPortfolio(data));

    // 3. 🔥 自动获取复盘报告 (之前这里没有调用) 🔥
    fetchReport(asset.code);
  };

  // === 执行策略分析 ===
  const handleRunStrategy = () => {
    if (!selectedAsset) return;
    setMsg("正在执行策略分析...");
    
    fetch(`http://127.0.0.1:8000/api/strategy/run/${selectedAsset.code}`, { method: 'POST' })
      .then(res => res.json())
      .then(data => {
        if (data.error) {
          alert("执行失败: " + data.error);
        } else {
          alert(`✅ 策略执行成功！\n建议: ${data.advice}`);
          // 🔥 执行完后，立即刷新报告，显示最新的结果
          fetchReport(selectedAsset.code);
        }
        setMsg("策略分析完成");
      });
  };

  // === 手动刷新报告 (保留这个按钮，以防万一) ===
  const handleManualGetReport = () => {
    if (selectedAsset) fetchReport(selectedAsset.code);
  }

  // ... (提交数据相关代码保持不变) ...
  const handleAddAsset = () => {
    if (!newCode || !newName) return;
    fetch('http://127.0.0.1:8000/api/assets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code: newCode, name: newName })
    }).then(res => res.json()).then(data => { if(data.id) { fetchAssets(); setShowAddForm(false); setNewCode(""); setNewName(""); } });
  };

  const handleTransaction = () => {
    if (!selectedAsset) return;
    fetch('http://127.0.0.1:8000/api/transactions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ asset_code: selectedAsset.code, type: transType, price: parseFloat(transPrice), amount: parseFloat(transAmount) })
    }).then(res => res.json()).then(data => { 
      if(data.id) { 
        alert("记账成功"); 
        setShowTransForm(false); 
        // 记账后刷新持仓
        fetch(`http://127.0.0.1:8000/api/portfolio/${selectedAsset.code}`)
          .then(res => res.json())
          .then(data => setPortfolio(data));
      } 
    });
  };

  const calculateProfit = () => {
    if (!advice || !portfolio) return { profit: 0, rate: 0, marketValue: 0 };
    const marketValue = portfolio.total_units * advice.current_price;
    const profit = marketValue - portfolio.total_cost;
    const rate = portfolio.total_cost > 0 ? (profit / portfolio.total_cost) * 100 : 0;
    return { profit, rate, marketValue };
  };
  const { profit, rate, marketValue } = calculateProfit();

  return (
    <div style={{ display: 'flex', height: '100vh', backgroundColor: '#121212', color: '#e0e0e0', fontFamily: 'Segoe UI, Roboto, sans-serif' }}>
      
      {/* 左侧栏 */}
      <div style={{ width: '260px', background: '#1e1e1e', borderRight: '1px solid #333', padding: '20px', display: 'flex', flexDirection: 'column' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
          <h3 style={{ margin: 0, color: '#40a9ff' }}>📊 智能定投</h3>
          <button onClick={() => setShowAddForm(!showAddForm)} style={btnSmallStyle}>{showAddForm ? 'x' : '+'}</button>
        </div>
        {showAddForm && (
          <div style={{ background: '#2c2c2c', padding: '10px', borderRadius: '8px', marginBottom: '10px' }}>
            <input placeholder="代码" value={newCode} onChange={e => setNewCode(e.target.value)} style={inputStyle} />
            <input placeholder="名称" value={newName} onChange={e => setNewName(e.target.value)} style={inputStyle} />
            <button onClick={handleAddAsset} style={{...btnPrimaryStyle, width: '100%', marginTop: '5px'}}>确认</button>
          </div>
        )}
        <div style={{ flex: 1, overflowY: 'auto' }}>
          {assets.map(asset => (
            <div key={asset.id} onClick={() => handleSelectAsset(asset)}
              style={{
                padding: '12px', margin: '5px 0', cursor: 'pointer', borderRadius: '6px',
                background: selectedAsset?.id === asset.id ? '#264666' : 'transparent',
                borderLeft: selectedAsset?.id === asset.id ? '3px solid #40a9ff' : '3px solid transparent'
              }}>
              <div style={{ fontWeight: '600', color: selectedAsset?.id === asset.id ? '#fff' : '#ccc' }}>{asset.name}</div>
              <div style={{ fontSize: '12px', color: '#666' }}>{asset.code}</div>
            </div>
          ))}
        </div>
      </div>

      {/* 右侧详情 */}
      <div style={{ flex: 1, padding: '30px', overflowY: 'auto' }}>
        {!selectedAsset && !loading && (
           <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#444' }}>
             <h2>👈 请选择或添加一个标的</h2>
           </div>
        )}
        {loading && <div style={{ textAlign: 'center', marginTop: '100px', color: '#888' }}>🚀 数据加载中...</div>}
        {advice && !loading && (
          <div style={{ maxWidth: '900px', margin: '0 auto' }}>
            
            {/* 看板 */}
            <div style={{ display: 'flex', gap: '20px', marginBottom: '20px' }}>
              <div style={cardStyle}>
                <div style={{ color: '#888', fontSize: '14px' }}>当前价格</div>
                <div style={{ fontSize: '32px', fontWeight: 'bold', margin: '5px 0' }}>{advice.current_price}</div>
                <div style={{ color: '#faad14', fontSize: '14px' }}>MA200: {advice.ma200}</div>
              </div>
              <div style={{ ...cardStyle, flex: 1.5, textAlign: 'center', background: advice.action === 'BUY' ? 'rgba(200,50,50,0.1)' : 'rgba(50,200,50,0.1)' }}>
                <div style={{ color: '#888', fontSize: '14px' }}>智能建议</div>
                <div style={{ fontSize: '32px', fontWeight: 'bold', margin: '5px 0', color: advice.action === 'BUY' ? '#ff4d4f' : '#52c41a' }}>
                  {advice.action === 'BUY' ? '建议定投' : '建议止盈/观望'}
                </div>
                <div style={{ color: '#888' }}>建议金额: <span style={{ color: '#40a9ff', fontWeight: 'bold' }}>¥{advice.suggested_amount}</span></div>
              </div>
            </div>

            {/* 策略与复盘 */}
            <div style={{ ...cardStyle, marginBottom: '20px', border: '1px solid #333' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '15px' }}>
                <h3 style={{ margin: 0 }}>🧠 策略复盘</h3>
                <div style={{ display: 'flex', gap: '10px' }}>
                  {/* 改名：更直观 */}
                  <button onClick={handleRunStrategy} style={btnPrimaryStyle}>⚡ 执行今日分析(打卡)</button>
                  {/* 刷新按钮 */}
                  <button onClick={handleManualGetReport} style={btnSecondaryStyle}>🔄 刷新报告</button>
                </div>
              </div>
              <div style={{ background: '#111', padding: '15px', borderRadius: '6px', color: '#ccc', fontSize: '14px', lineHeight: '1.6', whiteSpace: 'pre-wrap', minHeight: '80px' }}>
                {/* 这里现在会自动显示内容，不需要先点按钮 */}
                {report ? report : "暂无策略记录，请点击右上角'执行今日分析'..."}
              </div>
            </div>

            {/* 持仓 */}
            <div style={{ ...cardStyle, marginBottom: '20px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '15px' }}>
                <h3 style={{ margin: 0 }}>💰 我的持仓</h3>
                <button onClick={() => setShowTransForm(!showTransForm)} style={btnSmallStyle}>{showTransForm ? '取消' : '📝 记一笔'}</button>
              </div>
              {showTransForm && (
                <div style={{ background: '#333', padding: '15px', borderRadius: '6px', marginBottom: '15px', display: 'flex', gap: '10px' }}>
                  <select value={transType} onChange={e => setTransType(e.target.value)} style={inputStyle}><option value="BUY">买入</option><option value="SELL">卖出</option></select>
                  <input type="number" placeholder="价格" value={transPrice} onChange={e => setTransPrice(e.target.value)} style={inputStyle} />
                  <input type="number" placeholder="金额" value={transAmount} onChange={e => setTransAmount(e.target.value)} style={inputStyle} />
                  <button onClick={handleTransaction} style={btnPrimaryStyle}>提交</button>
                </div>
              )}
              {portfolio && portfolio.total_units > 0 ? (
                <div style={{ display: 'flex', justifyContent: 'space-around', textAlign: 'center' }}>
                  <div><div style={{color:'#888'}}>市值</div><div style={{fontSize:'20px'}}>¥{marketValue.toFixed(0)}</div></div>
                  <div><div style={{color:'#888'}}>本金</div><div style={{fontSize:'20px'}}>¥{portfolio.total_cost.toFixed(0)}</div></div>
                  <div><div style={{color:'#888'}}>收益</div><div style={{fontSize:'20px', color: profit>=0?'#ff4d4f':'#52c41a'}}>{profit>0?'+':''}{profit.toFixed(0)}</div></div>
                  <div><div style={{color:'#888'}}>率</div><div style={{fontSize:'20px', color: profit>=0?'#ff4d4f':'#52c41a'}}>{rate.toFixed(2)}%</div></div>
                </div>
              ) : ( <div style={{textAlign:'center', color:'#666'}}>暂无持仓</div> )}
            </div>

            {/* 图表 */}
            <div style={{ height: '300px', background: '#1e1e1e', padding: '10px', borderRadius: '12px' }}>
              <ResponsiveContainer>
                <LineChart data={advice.history}>
                  <YAxis domain={['auto', 'auto']} stroke="#444" />
                  <Tooltip contentStyle={{ background: '#333', border: 'none' }} />
                  <Line type="monotone" dataKey="price" stroke="#40a9ff" dot={false} strokeWidth={2} />
                  <Line type="monotone" dataKey="ma200" stroke="#faad14" dot={false} strokeWidth={2} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

const cardStyle = { background: '#1e1e1e', borderRadius: '12px', padding: '20px', flex: 1 };
const inputStyle = { padding: '8px', background: '#333', border: '1px solid #444', color: 'white', borderRadius: '4px', width: '100px' };
const btnPrimaryStyle = { padding: '8px 16px', background: '#1890ff', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer' };
const btnSecondaryStyle = { padding: '8px 16px', background: '#333', color: '#ccc', border: '1px solid #555', borderRadius: '4px', cursor: 'pointer' };
const btnSmallStyle = { padding: '4px 10px', background: '#333', color: '#ccc', border: 'none', borderRadius: '4px', cursor: 'pointer' };

export default App;