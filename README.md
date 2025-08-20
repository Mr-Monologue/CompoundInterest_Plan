# 汇添富消费行业混合 定投仪表盘

一个基于Streamlit的投资仪表盘应用，采用4层架构设计，提供动态定投建议、持仓分析和估值监控功能。

## 🏗️ 架构设计

### 4层架构

1. **config.py** - 配置管理
   - 默认参数定义
   - 用户自定义JSON读取
   - 配置验证

2. **data_sources.py** - 数据源管理
   - AKShare/yfinance/天天基金数据抓取
   - @st.cache_data 缓存机制
   - 网络失败回退策略

3. **signals.py** - 信号计算
   - MA200 偏离计算
   - 阈值/平滑映射
   - 动态定投比例计算

4. **holdings.py** - 持仓计算
   - Decimal 精度运算
   - 持有/累计盈亏计算
   - 盈亏平衡净值计算

### 页面结构

- **🏠 首页**: 四个指标卡 + 一键刷新
- **💰 定投建议**: 本周预算分配 + 可执行指令
- **📊 估值 & 买点**: MA200趋势图 + 买点信号
- **💼 持仓明细**: 成本/份额/盈亏表格 + 导出功能

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置基金信息

编辑 `config.json` 文件，设置您的基金配置：

```json
{
  "fund_code": "000083",
  "fund_name": "汇添富消费行业混合",
  "weekly_budget": 200.0,
  "manual_holdings": {
    "enabled": true,
    "units_left": 6.63,
    "avg_cost": 6.8627,
    "realized_pnl": -7.24
  }
}
```

### 3. 启动应用

```bash
streamlit run GUI.py
```

应用将在浏览器中自动打开，默认地址：http://localhost:8501

## 📊 功能特性

### 动态定投策略
- 基于MA200偏离度的智能定投
- 平滑映射避免阈值跳跃
- 准备金管理机制

### 数据源管理
- 多数据源支持（AKShare、yfinance）
- 智能回退策略
- 缓存机制提升性能

### 持仓分析
- Decimal精度计算
- 实时盈亏分析
- ROI指标计算

### 交互式图表
- Plotly交互图表
- MA200趋势分析
- 买点信号标记

## ⚙️ 配置说明

### 主要参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `weekly_budget` | 周定投预算 | 200.0 |
| `fixed_ratio` | 固定定投比例 | 0.40 |
| `ma200_low` | 低估阈值 | -10.0% |
| `ma200_mid` | 中估阈值 | 5.0% |
| `alloc_low` | 低估时分配比例 | 0.75 |
| `alloc_mid` | 中估时分配比例 | 0.25 |
| `alloc_high` | 高估时分配比例 | 0.0 |

### 数据源配置

```json
{
  "data_sources": {
    "primary": "akshare",
    "fallback": "yfinance",
    "cache_ttl": 900
  }
}
```

## 🔧 开发说明

### 模块测试

每个模块都可以独立测试：

```bash
python config.py
python data_sources.py
python signals.py
python holdings.py
```

### 添加新功能

1. 在相应模块中添加函数
2. 在GUI.py中集成到页面
3. 更新配置和文档

### 缓存管理

- 使用 `@st.cache_data` 缓存外部数据
- 使用 `st.session_state` 保存会话状态
- 避免将易变数据放入全局缓存

## 📈 使用建议

### 定投策略
- 根据个人风险承受能力调整阈值
- 定期检查准备金余额
- 关注MA200趋势变化

### 数据更新
- 净值数据每5分钟更新
- 指数数据每15分钟更新
- 可手动清除缓存强制更新

### 风险提示
- 本工具仅供参考，不构成投资建议
- 投资有风险，入市需谨慎
- 请根据个人情况调整投资策略

## 🤝 贡献指南

欢迎提交Issue和Pull Request！

### 开发环境
- Python 3.8+
- Streamlit 1.28+
- 建议使用虚拟环境

### 代码规范
- 遵循PEP 8规范
- 添加类型注解
- 编写文档字符串

## 📄 许可证

MIT License

## 📞 联系方式

如有问题或建议，请通过GitHub Issues联系。
